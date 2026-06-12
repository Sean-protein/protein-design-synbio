# -*- coding: utf-8 -*-
"""
GFP 蛋白质设计 - 合成生物学创新赛
====================================
基于 ESM/SaProt 蛋白质语言模型 + 随机森林回归的 GFP 亮度预测与候选序列生成。

用法:
    # 使用 ESM 嵌入 (默认)
    python gfp_design.py --data-dir ./data --method esm

    # 使用 SaProt 嵌入
    python gfp_design.py --data-dir ./data --method saprot

    # 自定义参数
    python gfp_design.py --data-dir ./data --method esm \
        --esm-model esm2_t12_35M_UR50D \
        --max-mutations 6 \
        --candidates 500 \
        --top-n 6
"""

import argparse
import logging
import os
import random
import re
import sys
import time
import warnings

# ══════════════════════════════════════════════════════════════════════════════
# 强制所有模型/缓存写入 D 盘，避免占用 C 盘空间
# 必须在 import torch / transformers 之前设置
# ══════════════════════════════════════════════════════════════════════════════
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_ROOT = os.path.join(_PROJECT_ROOT, "cache")
os.environ.setdefault("TORCH_HOME", os.path.join(_CACHE_ROOT, "torch"))
os.environ.setdefault("HF_HOME", os.path.join(_CACHE_ROOT, "huggingface"))
os.environ.setdefault("TRANSFORMERS_CACHE", os.path.join(_CACHE_ROOT, "huggingface"))
os.environ.setdefault("PIP_CACHE_DIR", os.path.join(_CACHE_ROOT, "pip"))

import numpy as np
import pandas as pd
import torch
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import r2_score
from sklearn.model_selection import train_test_split

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def generate_mutated_sequence(mutation_str, wt_sequence):
    """根据突变描述字符串和野生型序列生成突变后的完整序列。

    mutation_str: "WT", "G101A", "A12B:C34D"
    wt_sequence: 野生型氨基酸序列字符串
    """
    if not isinstance(mutation_str, str) or not wt_sequence:
        return None
    if mutation_str.strip().upper() == "WT":
        return wt_sequence

    sequence = list(wt_sequence)
    mutations = mutation_str.split(":")
    try:
        for mut in mutations:
            match = re.match(
                r"([A-Z])(\d+)([A-Z*.])$", mut.strip(), re.IGNORECASE
            )
            if not match:
                continue
            original_aa, pos, new_aa = match.groups()
            pos = int(pos) - 1
            if pos < 0 or pos >= len(sequence):
                continue
            if new_aa == "*":
                return None
            elif new_aa == ".":
                new_aa = sequence[pos]
            sequence[pos] = new_aa.upper()
        return "".join(sequence)
    except Exception:
        return None


def generate_single_candidate(wt_sequence, position_pool_0based, max_mutations):
    """生成一个随机组合突变的候选序列。"""
    amino_acids = "ACDEFGHIKLMNPQRSTVWY"
    num_mutations = random.randint(1, max_mutations)
    positions_to_mutate = random.sample(position_pool_0based, num_mutations)

    mutated_sequence = list(wt_sequence)
    mutation_details = []

    for pos in positions_to_mutate:
        original_aa = wt_sequence[pos]
        possible_new_aas = [aa for aa in amino_acids if aa != original_aa]
        new_aa = random.choice(possible_new_aas)
        mutated_sequence[pos] = new_aa
        mutation_details.append(f"{original_aa}{pos + 1}{new_aa}")

    return (
        "".join(mutated_sequence),
        ":".join(
            sorted(
                mutation_details,
                key=lambda x: int(re.search(r"\d+", x).group()),
            )
        ),
    )


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def load_data(data_dir, train_file, wt_seq_file, exclusion_file):
    """加载训练数据、野生型序列和排除列表。"""
    # 加载训练数据
    train_path = os.path.join(data_dir, train_file)
    log.info("Loading training data from %s ...", train_path)
    gfp_df = pd.read_excel(train_path, sheet_name="brightness")
    log.info("Loaded %d rows.", len(gfp_df))

    # 加载 avGFP 野生型序列
    wt_path = os.path.join(data_dir, wt_seq_file)
    log.info("Loading avGFP WT sequence from %s ...", wt_path)
    avGFP_WT_sequence = None
    with open(wt_path, "r") as f:
        header = ""
        seq_lines = []
        for line in f:
            if line.startswith(">"):
                if "avGFP" in header and seq_lines:
                    avGFP_WT_sequence = "".join(seq_lines).strip()
                    break
                header = line.strip()
                seq_lines = []
            else:
                seq_lines.append(line.strip())
        if avGFP_WT_sequence is None and "avGFP" in header and seq_lines:
            avGFP_WT_sequence = "".join(seq_lines).strip()

    if avGFP_WT_sequence:
        log.info("Found avGFP WT sequence (Length: %d).", len(avGFP_WT_sequence))
    else:
        raise ValueError(f"avGFP WT sequence not found in {wt_path}")

    # 加载排除列表
    exclusion_path = os.path.join(data_dir, exclusion_file)
    log.info("Loading exclusion list from %s ...", exclusion_path)
    exclusion_df = pd.read_csv(exclusion_path)
    exclusion_sequences = set(
        exclusion_df["sequences-not-submit"].astype(str)
    )
    log.info("Loaded %d sequences into exclusion list.", len(exclusion_sequences))

    # 筛选 avGFP 数据
    avGFP_train_df = gfp_df[gfp_df["GFP type"] == "avGFP"].copy()
    log.info("Filtered down to %d avGFP entries.", len(avGFP_train_df))

    # 生成完整序列
    avGFP_train_df["full_sequence"] = avGFP_train_df["aaMutations"].apply(
        lambda x: generate_mutated_sequence(x, avGFP_WT_sequence)
    )

    # 清理
    original_len = len(avGFP_train_df)
    avGFP_train_df.dropna(subset=["full_sequence", "Brightness"], inplace=True)
    avGFP_train_df["Brightness"] = pd.to_numeric(
        avGFP_train_df["Brightness"], errors="coerce"
    )
    avGFP_train_df.dropna(subset=["Brightness"], inplace=True)
    log.info(
        "Removed %d rows due to invalid sequences or brightness. Final: %d",
        original_len - len(avGFP_train_df),
        len(avGFP_train_df),
    )

    return avGFP_train_df, avGFP_WT_sequence, exclusion_sequences


# ---------------------------------------------------------------------------
# ESM 嵌入
# ---------------------------------------------------------------------------
def get_esm_embeddings(sequences, model, alphabet, batch_converter, device, batch_size):
    """在指定设备上生成 ESM 嵌入（平均池化）。"""
    embeddings = []
    num_sequences = len(sequences)
    num_batches = (num_sequences + batch_size - 1) // batch_size
    model.eval()
    model = model.to(device)

    log.info(
        "Generating ESM embeddings for %d sequences, %d batches (batch_size=%d, device=%s)...",
        num_sequences,
        num_batches,
        batch_size,
        device,
    )
    t0 = time.time()

    with torch.no_grad():
        for i in range(0, num_sequences, batch_size):
            batch_seqs = sequences[i : i + batch_size]
            batch_labels = [f"seq_{j + i}" for j in range(len(batch_seqs))]
            data = list(zip(batch_labels, batch_seqs))

            try:
                _, _, batch_tokens = batch_converter(data)
                batch_tokens = batch_tokens.to(device)
                results = model(batch_tokens, repr_layers=[model.num_layers])
                token_representations = results["representations"][model.num_layers]

                seq_repr_list = []
                for j, seq in enumerate(batch_seqs):
                    actual_len = len(seq)
                    seq_tokens_repr = token_representations[
                        j, 1 : actual_len + 1, :
                    ]
                    seq_repr = seq_tokens_repr.mean(dim=0)
                    seq_repr_list.append(seq_repr)

                batch_seq_repr = torch.stack(seq_repr_list, dim=0)
                embeddings.append(batch_seq_repr.cpu())

                bn = i // batch_size + 1
                if bn % 10 == 0 or bn == num_batches:
                    log.info(
                        "  Processed batch %d/%d... (%.1fs)",
                        bn,
                        num_batches,
                        time.time() - t0,
                    )

            except RuntimeError as e:
                if "CUDA out of memory" in str(e) and device.type == "cuda":
                    log.error("CUDA OOM at batch %d. Reducing batch size may help.", bn)
                    embed_dim = model.embed_dim
                    error_placeholder = torch.full(
                        (len(batch_seqs), embed_dim), float("nan"), device="cpu"
                    )
                    embeddings.append(error_placeholder)
                    torch.cuda.empty_cache()
                else:
                    log.error("Runtime error at batch %d: %s", bn, e)
                    embed_dim = model.embed_dim
                    error_placeholder = torch.full(
                        (len(batch_seqs), embed_dim), float("nan"), device="cpu"
                    )
                    embeddings.append(error_placeholder)
            except Exception as e:
                log.error("Unknown error at batch %d: %s", bn, e)
                embed_dim = model.embed_dim
                error_placeholder = torch.full(
                    (len(batch_seqs), embed_dim), float("nan"), device="cpu"
                )
                embeddings.append(error_placeholder)

    log.info("Embedding generation completed in %.1fs.", time.time() - t0)

    if not embeddings:
        return torch.tensor([])

    # 拼接所有批次
    try:
        full_embeddings = torch.cat(embeddings, dim=0)
    except RuntimeError as e:
        log.error("Error concatenating embeddings: %s", e)
        embed_dim = model.embed_dim
        valid_embeddings = [
            emb
            for emb in embeddings
            if isinstance(emb, torch.Tensor)
            and emb.ndim == 2
            and emb.shape[1] == embed_dim
            and not torch.isnan(emb).all()
        ]
        if valid_embeddings:
            full_embeddings = torch.cat(valid_embeddings, dim=0)
        else:
            return torch.tensor([])

    return full_embeddings


# ---------------------------------------------------------------------------
# SaProt 嵌入
# ---------------------------------------------------------------------------
def get_saprot_embeddings(sequences, model, tokenizer, device, batch_size,
                          use_compile=False):
    """使用 SaProt 模型为序列列表生成嵌入 (平均池化)。"""
    embeddings = []
    num_sequences = len(sequences)
    if num_sequences == 0:
        return torch.tensor([])

    num_batches = (num_sequences + batch_size - 1) // batch_size
    log.info(
        "Generating SaProt embeddings for %d sequences, %d batches (batch_size=%d)...",
        num_sequences,
        num_batches,
        batch_size,
    )
    t0 = time.time()
    model.eval()

    with torch.no_grad():
        for i in range(0, num_sequences, batch_size):
            batch_seqs = sequences[i : i + batch_size]
            batch_seqs_spaced = [" ".join(list(s)) for s in batch_seqs]
            bn = i // batch_size + 1

            try:
                inputs = tokenizer(
                    batch_seqs_spaced,
                    add_special_tokens=True,
                    padding=True,
                    truncation=True,
                    return_tensors="pt",
                )
                inputs = {key: val.to(device) for key, val in inputs.items()}
                outputs = model(**inputs)
                last_hidden_states = outputs.last_hidden_state

                mask = (
                    inputs["attention_mask"]
                    .unsqueeze(-1)
                    .expand(last_hidden_states.size())
                    .float()
                )
                sum_hidden_states = torch.sum(last_hidden_states * mask, dim=1)
                sum_mask = torch.clamp(mask.sum(dim=1), min=1e-9)
                mean_pooled = sum_hidden_states / sum_mask

                embeddings.append(mean_pooled.cpu())

                if bn % max(1, num_batches // 10) == 0 or bn == num_batches:
                    progress = (bn / num_batches) * 100
                    log.info(
                        "  Processed batch %d/%d (%.1f%%) - %.1fs",
                        bn,
                        num_batches,
                        progress,
                        time.time() - t0,
                    )

            except RuntimeError as e:
                if "CUDA out of memory" in str(e) and device.type == "cuda":
                    log.error("CUDA OOM at batch %d. Reduce batch size.", bn)
                    torch.cuda.empty_cache()
                    hidden_size = (
                        model.config.hidden_size
                        if hasattr(model, "config")
                        else 768
                    )
                    error_placeholder = torch.full(
                        (len(batch_seqs), hidden_size), float("nan"), device="cpu"
                    )
                    embeddings.append(error_placeholder)
                else:
                    log.error("Runtime error at batch %d: %s", bn, e)
                    hidden_size = (
                        model.config.hidden_size
                        if hasattr(model, "config")
                        else 768
                    )
                    error_placeholder = torch.full(
                        (len(batch_seqs), hidden_size), float("nan"), device="cpu"
                    )
                    embeddings.append(error_placeholder)
            except Exception as e:
                log.error("Unknown error at batch %d: %s", bn, e)
                hidden_size = (
                    model.config.hidden_size if hasattr(model, "config") else 768
                )
                error_placeholder = torch.full(
                    (len(batch_seqs), hidden_size), float("nan"), device="cpu"
                )
                embeddings.append(error_placeholder)

    log.info("SaProt embedding completed in %.1fs.", time.time() - t0)

    if not embeddings:
        return torch.tensor([])

    try:
        full_embeddings = torch.cat(embeddings, dim=0)
    except Exception as cat_err:
        log.error("Error concatenating embeddings: %s", cat_err)
        valid_embeddings = [
            emb
            for emb in embeddings
            if isinstance(emb, torch.Tensor)
            and emb.ndim == 2
            and not torch.isnan(emb).all()
        ]
        if valid_embeddings:
            expected_dim = valid_embeddings[0].shape[1]
            valid_embeddings = [
                emb for emb in valid_embeddings if emb.shape[1] == expected_dim
            ]
            if valid_embeddings:
                full_embeddings = torch.cat(valid_embeddings, dim=0)
            else:
                return torch.tensor([])
        else:
            return torch.tensor([])

    return full_embeddings


# ---------------------------------------------------------------------------
# 候选位置池 (基于文献: Superfolder GFP 关键位点 + 发色团附近位点)
# ---------------------------------------------------------------------------
DEFAULT_CANDIDATE_POSITIONS = [
    # 靠近发色团 (65-67)
    64, 68, 69, 70, 71, 72,
    # Superfolder GFP 关键突变位置
    10, 30,          # F64L is at 64 (already included above)
    101, 105, 109,
    145, 147, 153,   # M153T
    163, 167,        # V163A
    171, 187,
    203, 205, 221, 231, 232, 235,
]


# ---------------------------------------------------------------------------
# 完整 Pipeline
# ---------------------------------------------------------------------------
def run_pipeline(args):
    """运行完整的 GFP 蛋白质设计流程。"""
    seed = args.seed
    random.seed(seed)
    np.random.seed(seed)

    # ---- 第一步: 加载数据 ----
    log.info("=" * 60)
    log.info("STEP 1: Loading and preprocessing data")
    log.info("=" * 60)

    train_df, wt_seq, exclusion_set = load_data(
        args.data_dir, args.train_file, args.wt_seq_file, args.exclusion_file
    )

    # ---- 第二步: 加载蛋白质语言模型 ----
    log.info("=" * 60)
    log.info("STEP 2: Loading protein language model (%s)", args.method.upper())
    log.info("=" * 60)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log.info("Using device: %s", device)

    if args.method == "esm":
        import esm

        log.info("Loading ESM model: %s ...", args.esm_model)
        esm_model, alphabet = esm.pretrained.load_model_and_alphabet(args.esm_model)
        esm_model.eval()
        esm_model = esm_model.to(device)
        batch_converter = alphabet.get_batch_converter()
        log.info("ESM model loaded successfully.")

        embed_func = get_esm_embeddings
        embed_kwargs = {
            "model": esm_model,
            "alphabet": alphabet,
            "batch_converter": batch_converter,
            "device": device,
            "batch_size": args.batch_size,
        }

    elif args.method == "saprot":
        from transformers import AutoTokenizer, AutoModel

        # 设置 HuggingFace 镜像（国内加速）
        if args.hf_mirror:
            os.environ["HF_ENDPOINT"] = args.hf_mirror
            log.info("HF_ENDPOINT set to %s", args.hf_mirror)

        log.info("Loading SaProt model: %s ...", args.saprot_model)
        saprot_tokenizer = AutoTokenizer.from_pretrained(args.saprot_model)
        saprot_model = AutoModel.from_pretrained(args.saprot_model)

        if device.type == "cuda" and hasattr(torch, "compile"):
            try:
                saprot_model = torch.compile(
                    saprot_model, mode="reduce-overhead", fullgraph=True
                )
                log.info("torch.compile applied to SaProt model.")
            except Exception as e:
                log.warning("torch.compile failed: %s. Using uncompiled model.", e)

        saprot_model.eval()
        saprot_model = saprot_model.to(device)
        log.info("SaProt model loaded successfully.")

        embed_func = get_saprot_embeddings
        embed_kwargs = {
            "model": saprot_model,
            "tokenizer": saprot_tokenizer,
            "device": device,
            "batch_size": args.batch_size,
        }

    # ---- 第三步: 嵌入训练数据 ----
    log.info("=" * 60)
    log.info("STEP 3: Generating embeddings for training data")
    log.info("=" * 60)

    # 采样（如果数据量过大）
    max_train_samples = args.max_train_samples
    if len(train_df) > max_train_samples:
        log.info(
            "Training data (%d) > limit (%d). Sampling...",
            len(train_df),
            max_train_samples,
        )
        sampled_train_df = train_df.sample(n=max_train_samples, random_state=seed)
    else:
        sampled_train_df = train_df.copy()

    train_seqs = sampled_train_df["full_sequence"].tolist()
    X_tensor = embed_func(train_seqs, **embed_kwargs)

    if X_tensor.numel() == 0:
        log.error("Failed to generate training embeddings. Exiting.")
        sys.exit(1)

    log.info("Embedding tensor shape: %s", X_tensor.shape)
    X_np = X_tensor.cpu().numpy()

    # 处理 NaN
    nan_mask = np.isnan(X_np).any(axis=1)
    if np.any(nan_mask):
        log.warning("Found %d NaN rows in embeddings. Removing.", nan_mask.sum())
        X_np = X_np[~nan_mask]
        sampled_train_df = sampled_train_df[~nan_mask].reset_index(drop=True)

    if X_np.shape[0] == 0:
        log.error("No valid training data after NaN removal. Exiting.")
        sys.exit(1)

    y = sampled_train_df["Brightness"].values
    log.info("Prepared X shape: %s, y shape: %s", X_np.shape, y.shape)

    # 清理
    del X_tensor

    # ---- 第四步: 训练随机森林模型 ----
    log.info("=" * 60)
    log.info("STEP 4: Training Random Forest Regressor")
    log.info("=" * 60)

    if len(X_np) > 10:
        X_train, X_val, y_train, y_val = train_test_split(
            X_np, y, test_size=0.2, random_state=seed
        )
        log.info(
            "Split data into training (%d) and validation (%d) sets.",
            len(X_train),
            len(X_val),
        )
    else:
        X_train, y_train = X_np, y
        X_val, y_val = None, None
        log.warning("Dataset too small for validation split.")

    rf_model = RandomForestRegressor(
        n_estimators=args.n_estimators,
        random_state=seed,
        n_jobs=-1,
        max_depth=args.max_depth,
        min_samples_leaf=args.min_samples_leaf,
    )
    rf_model.fit(X_train, y_train)
    log.info("Random Forest training complete.")

    # 评估
    if X_val is not None:
        y_pred_val = rf_model.predict(X_val)
        r2 = r2_score(y_val, y_pred_val)
        log.info("Model R^2 on validation set: %.4f", r2)
    else:
        y_pred_train = rf_model.predict(X_train)
        r2_train = r2_score(y_train, y_pred_train)
        log.info("Model R^2 on training set (may be optimistic): %.4f", r2_train)

    # ---- 第五步: 生成候选序列 ----
    log.info("=" * 60)
    log.info("STEP 5: Generating candidate sequences")
    log.info("=" * 60)

    candidate_positions_0based = [p - 1 for p in args.candidate_positions]
    log.info(
        "Candidate position pool (%d sites): %s",
        len(candidate_positions_0based),
        args.candidate_positions,
    )

    candidate_sequences = {}
    generated_count = 0
    attempts = 0
    max_attempts = args.n_candidates * 10

    while generated_count < args.n_candidates and attempts < max_attempts:
        attempts += 1
        seq, mut_str = generate_single_candidate(
            wt_seq, candidate_positions_0based, args.max_mutations
        )
        if seq not in candidate_sequences and seq != wt_seq:
            candidate_sequences[seq] = mut_str
            generated_count += 1
            if generated_count % max(1, args.n_candidates // 10) == 0:
                log.info("  Generated %d/%d unique candidates...", generated_count, args.n_candidates)

    candidate_list = list(candidate_sequences.keys())
    mutation_list = [candidate_sequences[seq] for seq in candidate_list]
    log.info("Generated %d unique candidate sequences.", len(candidate_list))

    # ---- 第六步: 预测候选序列亮度 ----
    log.info("=" * 60)
    log.info("STEP 6: Predicting brightness for candidate sequences")
    log.info("=" * 60)

    if not candidate_list:
        log.error("No candidate sequences generated. Exiting.")
        sys.exit(1)

    cand_tensor = embed_func(candidate_list, **embed_kwargs)
    cand_np = cand_tensor.cpu().numpy()
    log.info("Candidate embedding shape: %s", cand_np.shape)

    # 处理 NaN
    nan_mask_cand = np.isnan(cand_np).any(axis=1)
    if np.any(nan_mask_cand):
        log.warning(
            "Found %d NaN rows in candidate embeddings. Removing.",
            nan_mask_cand.sum(),
        )
        valid_idx = ~nan_mask_cand
        cand_np = cand_np[valid_idx]
        candidate_list = [s for i, s in enumerate(candidate_list) if valid_idx[i]]
        mutation_list = [m for i, m in enumerate(mutation_list) if valid_idx[i]]

    if cand_np.shape[0] == 0:
        log.error("No valid candidate embeddings. Exiting.")
        sys.exit(1)

    predicted_brightness = rf_model.predict(cand_np)
    log.info("Prediction complete for %d candidates.", len(predicted_brightness))

    # ---- 第七步: 筛选与输出 ----
    log.info("=" * 60)
    log.info("STEP 7: Filtering, ranking, and saving results")
    log.info("=" * 60)

    results_df = pd.DataFrame(
        {
            "Sequence": candidate_list,
            "Mutations": mutation_list,
            "PredictedBrightness": predicted_brightness,
        }
    )

    # 排除黑名单
    initial_count = len(results_df)
    results_df = results_df[~results_df["Sequence"].isin(exclusion_set)]
    removed = initial_count - len(results_df)
    if removed > 0:
        log.info("Removed %d sequences in exclusion list.", removed)

    # 排序并取 Top N
    results_df = results_df.sort_values(by="PredictedBrightness", ascending=False)
    final_candidates = results_df.head(args.top_n).copy()
    final_candidates.insert(
        0, "Sequence ID", [f"Candidate_{i + 1}" for i in range(len(final_candidates))]
    )

    # 输出结果
    output_df = final_candidates[["Sequence ID", "Mutations", "Sequence", "PredictedBrightness"]]

    print("\n" + "=" * 60)
    print("TOP %d CANDIDATES (Predicted Brightness)" % args.top_n)
    print("=" * 60)
    print(output_df.to_string(index=False))

    # 保存 CSV
    submission_df = final_candidates[["Sequence ID", "Mutations", "Sequence"]].copy()
    output_path = os.path.join(args.output_dir, args.output_file)
    os.makedirs(args.output_dir, exist_ok=True)
    submission_df.to_csv(output_path, index=False)
    log.info("Saved top %d candidates to %s", len(submission_df), output_path)

    # ---- 清理 ----
    log.info("=" * 60)
    log.info("Pipeline completed successfully!")
    log.info("=" * 60)

    return output_df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="GFP Protein Design Pipeline (合成生物学创新赛)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # 数据路径
    data_group = parser.add_argument_group("Data Paths")
    data_group.add_argument(
        "--data-dir",
        default="./data",
        help="Directory containing data files (default: ./data)",
    )
    data_group.add_argument(
        "--train-file", default="GFP data.xlsx", help="Training data file name"
    )
    data_group.add_argument(
        "--wt-seq-file",
        default="WildType AAseqs of 4 GFP proteins.txt",
        help="Wild-type sequence file name",
    )
    data_group.add_argument(
        "--exclusion-file",
        default="Exclusion_List.csv",
        help="Exclusion list file name",
    )
    data_group.add_argument(
        "--output-dir", default="./运行结果", help="Output directory (default: ./运行结果)"
    )
    data_group.add_argument(
        "--output-file",
        default="top_candidates.csv",
        help="Output CSV file name (default: top_candidates.csv)",
    )

    # 模型参数
    model_group = parser.add_argument_group("Model Configuration")
    model_group.add_argument(
        "--method",
        choices=["esm", "saprot"],
        default="esm",
        help="Protein language model to use: esm or saprot (default: esm)",
    )
    model_group.add_argument(
        "--esm-model",
        default="esm2_t12_35M_UR50D",
        help="ESM model name (default: esm2_t12_35M_UR50D)",
    )
    model_group.add_argument(
        "--saprot-model",
        default="westlake-repl/SaProt_35M_AF2",
        help="SaProt model name (default: westlake-repl/SaProt_35M_AF2)",
    )
    model_group.add_argument(
        "--hf-mirror",
        default="https://hf-mirror.com",
        help="HuggingFace mirror URL for China (default: https://hf-mirror.com)",
    )
    model_group.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Batch size for embedding generation (default: 8)",
    )

    # 生成参数
    gen_group = parser.add_argument_group("Generation Parameters")
    gen_group.add_argument(
        "--max-mutations",
        type=int,
        default=6,
        help="Maximum mutations per sequence (default: 6)",
    )
    gen_group.add_argument(
        "--n-candidates",
        type=int,
        default=500,
        help="Number of candidate sequences to generate (default: 500)",
    )
    gen_group.add_argument(
        "--top-n",
        type=int,
        default=6,
        help="Number of top candidates to output (default: 6)",
    )
    gen_group.add_argument(
        "--candidate-positions",
        type=int,
        nargs="+",
        default=DEFAULT_CANDIDATE_POSITIONS,
        help="1-based candidate position pool (default: Superfolder GFP key sites)",
    )

    # RF 参数
    rf_group = parser.add_argument_group("Random Forest Parameters")
    rf_group.add_argument(
        "--n-estimators", type=int, default=100, help="Number of trees (default: 100)"
    )
    rf_group.add_argument(
        "--max-depth",
        type=int,
        default=20,
        help="Maximum tree depth (default: 20)",
    )
    rf_group.add_argument(
        "--min-samples-leaf",
        type=int,
        default=3,
        help="Minimum samples per leaf (default: 3)",
    )
    rf_group.add_argument(
        "--max-train-samples",
        type=int,
        default=5000,
        help="Max training samples for embedding (default: 5000)",
    )

    # 其他
    other_group = parser.add_argument_group("Other")
    other_group.add_argument(
        "--seed", type=int, default=42, help="Random seed (default: 42)"
    )

    args = parser.parse_args()

    # 设置随机种子
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    run_pipeline(args)


if __name__ == "__main__":
    main()
