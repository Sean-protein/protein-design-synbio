# -*- coding: utf-8 -*-
"""
策略B — ESM-2 650M 嵌入提取（服务器GPU）
=========================================
在服务器 L40 GPU 上运行，对 avGFP 训练序列提取 ESM-2 650M 均值池化嵌入。

用法:
  # 全量嵌入
  python embed.py --input results/strategy_B/avGFP_processed.csv

  # 指定输出路径 + batch size
  python embed.py --input avGFP_processed.csv --output embeddings.npz --batch-size 2

  # 仅嵌入前 N 条（测试用）
  python embed.py --input avGFP_processed.csv --max-seqs 100

注意事项:
  - 必须在有 GPU 的服务器上运行 (L40 48GB)
  - 建议 tmux + nohup 避免断连
  - 650M 模型 ~2.6GB 参数, batch_size=4 约 36GB VRAM
"""

import argparse
import os
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd
import torch

# 强制缓存到项目目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CACHE_ROOT = os.path.join(_PROJECT_ROOT, "cache")
os.environ.setdefault("TORCH_HOME", os.path.join(_CACHE_ROOT, "torch"))
os.environ.setdefault("HF_HOME", os.path.join(_CACHE_ROOT, "huggingface"))

from config import (
    ESM_MODEL_NAME, EMBED_DIM, BATCH_SIZE, AVGFP_PROCESSED,
    EMBEDDINGS_NPZ, STRAT_B_DIR, log,
)


def load_sequences(input_path, max_seqs=None):
    """加载待嵌入的序列列表。"""
    df = pd.read_csv(input_path)
    sequences = df["full_sequence"].tolist()
    if max_seqs:
        sequences = sequences[:max_seqs]
    log.info("Loaded %d sequences from %s", len(sequences), input_path)
    return sequences


def get_esm_embeddings(sequences, model, alphabet, batch_converter, device, batch_size):
    """ESM-2 均值池化嵌入生成（复用 gfp_design.py 的稳健实现）。"""
    embeddings = []
    num_sequences = len(sequences)
    num_batches = (num_sequences + batch_size - 1) // batch_size
    model.eval()
    model = model.to(device)

    log.info(
        "Generating ESM embeddings: %d sequences, %d batches (batch_size=%d, device=%s)...",
        num_sequences, num_batches, batch_size, device,
    )
    t0 = time.time()

    with torch.no_grad():
        for i in range(0, num_sequences, batch_size):
            batch_seqs = sequences[i : i + batch_size]
            batch_labels = [f"seq_{j + i}" for j in range(len(batch_seqs))]
            data = list(zip(batch_labels, batch_seqs))
            bn = i // batch_size + 1

            try:
                _, _, batch_tokens = batch_converter(data)
                batch_tokens = batch_tokens.to(device)
                results = model(batch_tokens, repr_layers=[model.num_layers])
                token_representations = results["representations"][model.num_layers]

                seq_repr_list = []
                for j, seq in enumerate(batch_seqs):
                    actual_len = len(seq)
                    seq_tokens_repr = token_representations[j, 1 : actual_len + 1, :]
                    seq_repr = seq_tokens_repr.mean(dim=0)
                    seq_repr_list.append(seq_repr)

                batch_seq_repr = torch.stack(seq_repr_list, dim=0)
                embeddings.append(batch_seq_repr.cpu())

                # 进度（每 50 批或最后一批）
                if bn % 50 == 0 or bn == num_batches:
                    elapsed = time.time() - t0
                    eta = (elapsed / bn) * (num_batches - bn)
                    log.info(
                        "  Batch %d/%d (%.1f%%) — elapsed %.1f min, ETA %.1f min",
                        bn, num_batches, 100*bn/num_batches, elapsed/60, eta/60,
                    )

            except RuntimeError as e:
                if "CUDA out of memory" in str(e) and device.type == "cuda":
                    log.error("CUDA OOM at batch %d. Try reducing batch_size.", bn)
                    embed_dim = model.embed_dim if hasattr(model, "embed_dim") else EMBED_DIM
                    error_placeholder = torch.full(
                        (len(batch_seqs), embed_dim), float("nan"), device="cpu"
                    )
                    embeddings.append(error_placeholder)
                    torch.cuda.empty_cache()
                else:
                    log.error("Runtime error at batch %d: %s", bn, e)
                    embed_dim = model.embed_dim if hasattr(model, "embed_dim") else EMBED_DIM
                    error_placeholder = torch.full(
                        (len(batch_seqs), embed_dim), float("nan"), device="cpu"
                    )
                    embeddings.append(error_placeholder)
            except Exception as e:
                log.error("Unknown error at batch %d: %s", bn, e)
                embed_dim = model.embed_dim if hasattr(model, "embed_dim") else EMBED_DIM
                error_placeholder = torch.full(
                    (len(batch_seqs), embed_dim), float("nan"), device="cpu"
                )
                embeddings.append(error_placeholder)

    log.info("Embedding generation completed in %.1f min.", (time.time() - t0) / 60)

    if not embeddings:
        return torch.tensor([])

    try:
        full_embeddings = torch.cat(embeddings, dim=0)
    except RuntimeError as e:
        log.error("Error concatenating embeddings: %s", e)
        embed_dim = EMBED_DIM
        valid_embeddings = [
            emb for emb in embeddings
            if isinstance(emb, torch.Tensor) and emb.ndim == 2
            and emb.shape[1] == embed_dim and not torch.isnan(emb).all()
        ]
        if valid_embeddings:
            full_embeddings = torch.cat(valid_embeddings, dim=0)
        else:
            return torch.tensor([])

    return full_embeddings


def run_embedding(input_path=None, output_path=None, batch_size=None, max_seqs=None):
    """运行嵌入提取主流程。"""
    log.info("=" * 60)
    log.info("STRATEGY B — ESM-2 650M Embedding Extraction")
    log.info("=" * 60)
    log.info("Start time: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # ── 参数默认值 ──
    if input_path is None:
        input_path = AVGFP_PROCESSED
    if output_path is None:
        output_path = EMBEDDINGS_NPZ
    if batch_size is None:
        batch_size = BATCH_SIZE

    # ── 设备检测 ──
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log.info("Device: %s", device)
    if device.type == "cuda":
        log.info("GPU: %s, VRAM: %.1f GB", torch.cuda.get_device_name(0),
                 torch.cuda.get_device_properties(0).total_mem / 1e9)

    # ── 加载序列 ──
    sequences = load_sequences(input_path, max_seqs)

    # ── 加载模型 ──
    log.info("Loading ESM model: %s ...", ESM_MODEL_NAME)
    import esm
    model, alphabet = esm.pretrained.load_model_and_alphabet(ESM_MODEL_NAME)
    batch_converter = alphabet.get_batch_converter()
    log.info("Model loaded. Layers: %d, Embed dim: %d", model.num_layers, model.embed_dim)

    # ── 嵌入 ──
    embeddings_tensor = get_esm_embeddings(
        sequences, model, alphabet, batch_converter, device, batch_size
    )

    if embeddings_tensor.numel() == 0:
        log.error("No embeddings generated. Exiting.")
        sys.exit(1)

    embeddings_np = embeddings_tensor.cpu().numpy()
    log.info("Embedding matrix shape: %s", embeddings_np.shape)

    # ── NaN 检查 ──
    nan_rows = np.isnan(embeddings_np).any(axis=1).sum()
    if nan_rows > 0:
        log.warning("Found %d NaN rows in embeddings (%.1f%%)",
                     nan_rows, 100*nan_rows/len(embeddings_np))

    # 统计
    norms = np.linalg.norm(embeddings_np[~np.isnan(embeddings_np).any(axis=1)], axis=1)
    log.info("Embedding L2 norms: mean=%.4f, std=%.4f, min=%.4f, max=%.4f",
             norms.mean(), norms.std(), norms.min(), norms.max())

    # ── 保存 ──
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    np.savez_compressed(output_path, embeddings=embeddings_np)
    file_size_mb = os.path.getsize(output_path) / 1e6
    log.info("Embeddings saved → %s (%.1f MB)", output_path, file_size_mb)
    log.info("End time: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    return embeddings_np


def main():
    parser = argparse.ArgumentParser(description="Strategy B: ESM-2 650M Embedding")
    parser.add_argument("--input", type=str, help="Path to processed CSV with sequences")
    parser.add_argument("--output", type=str, help="Output .npz path")
    parser.add_argument("--batch-size", type=int, help="Batch size (default: 4)")
    parser.add_argument("--max-seqs", type=int, help="Max sequences to embed (for testing)")
    args = parser.parse_args()

    run_embedding(
        input_path=args.input,
        output_path=args.output,
        batch_size=args.batch_size,
        max_seqs=args.max_seqs,
    )


if __name__ == "__main__":
    main()
