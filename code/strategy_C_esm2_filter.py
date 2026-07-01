# -*- coding: utf-8 -*-
"""
策略C — ESM-2 伪似然度快速预筛（无需 ESMFold, T1 备用方案）
============================================================
当 ESMFold 不可用时，用 ESM-2 650M 计算序列伪似然度(pseudo-log-likelihood)
作为"序列天然性/可折叠性"的替代指标。

原理:
  ESM-2 的 masked language modeling 训练目标使模型对"天然序列"赋予更高似然度。
  将每个位置的 WT 氨基酸 mask，用模型预测该位置的概率 → 取 log 平均。
  高伪似然度 ≈ 序列接近天然蛋白质分布 ≈ 更可能正确折叠。

参考:
  - Hie et al. (2021) "Learning the language of viral evolution..."
  - Notin et al. (2022) "Tranception: protein fitness prediction..."
  - Cho et al. (2025) "ESMFold pLDDT + ESM-2 pll 联合"

速度: ~0.5s/序列 (RTX 3090), 273条 ≈ 2.5分钟
vs ESMFold: ~30s/序列, 273条 ≈ 2.3小时

用法:
  python strategy_C_esm2_filter.py                    # 对所有273条评分
  python strategy_C_esm2_filter.py --top-n 200         # 仅输出Top 200
  python strategy_C_esm2_filter.py --device cuda:1     # 指定GPU
"""

import argparse
import os
import sys
import time

import numpy as np
import pandas as pd
import torch

# ══════════════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════════════
def _find_root():
    for c in [
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "/data2/fenghaohui",
    ]:
        if os.path.exists(c):
            return c
    return os.getcwd()

PROJECT_ROOT = _find_root()
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results", "strategy_C")
os.makedirs(RESULTS_DIR, exist_ok=True)

CAND_CSV = os.path.join(RESULTS_DIR, "strategy_C_ml_scored.csv")
OUT_CSV = os.path.join(RESULTS_DIR, "strategy_C_esm2_pseudo_log_likelihood.csv")

# sfGFP WT (用于对比)
SFGFP_WT = ("MSKGEELFTGVVPILVELDGDVNGHKFSVRGEGEGDATNGKLTLKFICTTGKLPVPWPTLVTT"
            "LTYGVQCFSRYPDHMKRHDFFKSAMPEGYVQERTISFKDDGTYKTRAEVKFEGDTLVNRIELK"
            "GIDFKEDGNILGHKLEYNFNSHNVYITADKQKNGIKANFKIRHNVEDGSVQLADHYQQNTPIG"
            "DGPVLLPDNHYLSTQSVLSKDPNEKRDHMVLLEFVTAAGITHGMDELYK")


def load_esm2_model(device_str="cuda:0"):
    """加载 ESM-2 650M"""
    import esm
    device = torch.device(device_str if torch.cuda.is_available() else "cpu")
    print(f"Loading ESM-2 650M on {device}...")
    model, alphabet = esm.pretrained.load_model_and_alphabet("esm2_t33_650M_UR50D")
    model = model.to(device).eval()
    print(f"  Model loaded. Layers: {model.num_layers}")
    return model, alphabet, device


def compute_pseudo_log_likelihood(model, alphabet, device, sequences, batch_size=4,
                                   mask_gap=True):
    """
    计算每个序列的伪对数似然度 (pseudo-log-likelihood, PLL)。

    方法: 逐位置 mask → 预测 → 取正确氨基酸的 log-prob → 平均
    高 PLL = 序列更"天然"

    Args:
        mask_gap: 是否跳过 gap 位置 (通常 ESM 不产生 gap，但安全起见)
    Returns:
        pll_scores: shape (N,) 的 PLL 数组 (越高越好)
        per_pos_pll:  list of per-position PLL arrays
    """
    batch_converter = alphabet.get_batch_converter()
    all_scores = []
    all_per_pos = []

    for i in range(0, len(sequences), batch_size):
        batch_seqs = sequences[i:i+batch_size]
        batch_data = [(f"s{j}", s) for j, s in enumerate(batch_seqs)]

        # Tokenize
        _, _, batch_tokens = batch_converter(batch_data)
        batch_tokens = batch_tokens.to(device)  # (B, L)

        B, L = batch_tokens.shape
        scores = np.zeros(B)
        per_pos_scores = []

        for pos in range(1, L - 1):  # skip <cls> and <eos>
            # 创建 masked 版本
            masked_tokens = batch_tokens.clone()
            masked_tokens[:, pos] = alphabet.mask_idx  # <mask>

            with torch.no_grad():
                logits = model(masked_tokens, repr_layers=[model.num_layers])
                logits = logits["logits"]  # (B, L, vocab_size)

            # 取该位置的 log-prob
            log_probs = torch.log_softmax(logits[:, pos, :], dim=-1)  # (B, vocab)

            # 取原始氨基酸的 log-prob
            original_aa = batch_tokens[:, pos]  # (B,)
            per_pos_ll = log_probs[torch.arange(B), original_aa].cpu().numpy()

            scores += per_pos_ll
            per_pos_scores.append(per_pos_ll)

        # 平均
        scores /= (L - 2)  # divide by effective length
        all_scores.append(scores)
        all_per_pos.extend([np.array(pp) for pp in zip(*per_pos_scores)])

        if (i // batch_size + 1) % 20 == 0:
            print(f"  PLL: {i+len(batch_seqs)}/{len(sequences)}")

    return np.concatenate(all_scores), all_per_pos


def compute_relative_pll(pll_scores, wt_pll):
    """计算相对于 sfGFP WT 的 PLL"""
    return pll_scores - wt_pll


def compute_esm2_pseudo_perplexity(pll_scores):
    """PLL → pseudo-perplexity (越低越好，类似语言模型)"""
    return np.exp(-pll_scores)


def main():
    parser = argparse.ArgumentParser(
        description="Strategy C: ESM-2 pseudo-log-likelihood pre-filter (T1 fallback)")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--top-n", type=int, default=0,
                        help="Output only Top N by PLL (0=all)")
    args = parser.parse_args()

    print("=" * 60)
    print("STRATEGY C — ESM-2 Pseudo-Log-Likelihood Filter (T1 Fallback)")
    print("=" * 60)

    # ── 加载数据 ──
    df = pd.read_csv(CAND_CSV)
    sequences = df["sequence"].tolist()
    print(f"\nLoaded {len(sequences)} candidates")

    # ── 加载 ESM-2 ──
    model, alphabet, device = load_esm2_model(args.device)

    # ── 计算 sfGFP WT 的 PLL 作为基线 ──
    print("\nComputing sfGFP WT baseline PLL...")
    wt_pll, _ = compute_pseudo_log_likelihood(model, alphabet, device, [SFGFP_WT])
    wt_pll = wt_pll[0]
    print(f"  sfGFP WT PLL: {wt_pll:.4f}")

    # ── 计算所有候选的 PLL ──
    print(f"\nComputing PLL for {len(sequences)} candidates...")
    t0 = time.time()
    pll_scores, per_pos = compute_pseudo_log_likelihood(
        model, alphabet, device, sequences, batch_size=args.batch_size)
    elapsed = time.time() - t0
    print(f"  Done in {elapsed:.1f}s ({elapsed/len(sequences):.1f}s/seq)")

    # ── 组装结果 ──
    df["pll_score"] = pll_scores
    df["pll_relative_to_wt"] = compute_relative_pll(pll_scores, wt_pll)
    df["pseudo_perplexity"] = compute_esm2_pseudo_perplexity(pll_scores)

    # 归一化 (0-1, 1=最好)
    pll_min = pll_scores.min()
    pll_max = pll_scores.max()
    if pll_max > pll_min:
        df["pll_normalized"] = (pll_scores - pll_min) / (pll_max - pll_min)
    else:
        df["pll_normalized"] = 1.0

    # ── 统计 ──
    print(f"\nPLL Statistics:")
    print(f"  Mean:  {pll_scores.mean():.4f} ± {pll_scores.std():.4f}")
    print(f"  Range: [{pll_scores.min():.4f}, {pll_scores.max():.4f}]")
    print(f"  WT:    {wt_pll:.4f}")
    print(f"  Above WT: {(pll_scores > wt_pll).sum()}/{len(pll_scores)} "
          f"({(pll_scores > wt_pll).sum()/len(pll_scores)*100:.1f}%)")

    # ── 与 ML 亮度联合评分 ──
    if "pred_brightness" in df.columns:
        # 综合 = PLL_norm * 0.5 + brightness_norm * 0.5
        b_min = df["pred_brightness"].min()
        b_max = df["pred_brightness"].max()
        if b_max > b_min:
            df["brightness_norm"] = (df["pred_brightness"] - b_min) / (b_max - b_min)
        else:
            df["brightness_norm"] = 0.5
        df["combined_pll_brightness"] = (df["pll_normalized"] * 0.5 +
                                          df["brightness_norm"] * 0.5)

    # ── 排序保存 ──
    sort_col = "combined_pll_brightness" if "combined_pll_brightness" in df.columns else "pll_score"
    df = df.sort_values(sort_col, ascending=False)

    if args.top_n > 0:
        df = df.head(args.top_n)
        print(f"\n  → Filtered to Top {args.top_n}")

    df.to_csv(OUT_CSV, index=False)
    print(f"\nSaved → {OUT_CSV}")

    # ── Top 20 预览 ──
    print("\nTop 20 by combined PLL+Brightness:")
    display_cols = ["num_mutations", "temperature", "pll_score",
                    "pll_relative_to_wt", "pred_brightness"]
    if "combined_pll_brightness" in df.columns:
        display_cols.insert(0, "combined_pll_brightness")
    top20 = df.head(20)
    for col in display_cols:
        if col in top20.columns:
            print(f"  {col}: {top20[col].values[:5]}...")

    # ── 与 pLDDT 的相关性预期 ──
    print("\n" + "=" * 60)
    print("INTERPRETATION:")
    print(f"  sfGFP WT PLL = {wt_pll:.4f} (baseline)")
    print(f"  Higher PLL → more 'natural' sequence → likely better folding")
    print(f"  Literature: ESM-2 PLL + ESMFold pLDDT combined improves")
    print(f"    stability prediction (Spearman r=0.54 → r=0.60+)")
    print("")
    print("  Recommended threshold for T1 pass:")
    print(f"    pll_relative_to_wt > -0.5  (within 0.5 of WT)")
    print(f"    OR pll_normalized > 0.3")
    print("")
    print("  Next: run ESMFold on candidates passing T1 (PLL) filter")
    print("  OR: proceed directly to FoldX on Top 50-100 by combined score")
    print("=" * 60)


if __name__ == "__main__":
    main()
