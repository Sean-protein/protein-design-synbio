# -*- coding: utf-8 -*-
"""
策略C — ESMFold 全量结构预筛（替代直接FoldX批处理）
====================================================
对全部 273 条 ProteinMPNN 候选运行 ESMFold 结构验证，
替代原计划中对 60-90 突变序列运行 FoldX 的不合理做法。

筛选逻辑 (T1):
  - 全局 pLDDT > 80   → 序列可折叠
  - pTM > 0.75         → 全局折叠置信度
  - 发色团区域局部 pLDDT > 85 (位点 62-67, 93, 219)
  → 通过 T1 的候选进入下一级 (ESM-2 pseudo-likelihood / FoldX Top 50-100)

特性:
  - 断点续跑: 每 5 条增量保存，中断后可恢复
  - 输出: pLDDT 均值、pTM、发色团区域 pLDDT、每残基 pLDDT
  - ETA 实时估计

用法:
  # 本地 RTX 3090
  python strategy_C_esmfold_full.py

  # 服务器 L40
  python strategy_C_esmfold_full.py --device cuda:0 --batch-size 4

  # 仅跑 Top N ML 亮度候选
  python strategy_C_esmfold_full.py --top-ml 150
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

# ══════════════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════════════

# 自动检测项目根目录和服务器路径
def _find_root():
    candidates = [
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "/data2/fenghaohui",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]

PROJECT_ROOT = _find_root()
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results", "strategy_C")
os.makedirs(RESULTS_DIR, exist_ok=True)

# 输入文件
CAND_CSV = os.path.join(RESULTS_DIR, "strategy_C_ml_scored.csv")
# 输出文件
OUT_CSV = os.path.join(RESULTS_DIR, "strategy_C_esmfold_full.csv")
OUT_JSON = os.path.join(RESULTS_DIR, "strategy_C_esmfold_per_residue.json")

# sfGFP 发色团区域 (0-based index, 全长序列位置)
# 发色团三联体: T65(64), Y66(65), G67(66)
# 关键催化残基: R96(95), E222(221)
# 发色团近邻: I71(70), Q69(68), H148(147)
CHROMOPHORE_REGION = list(range(62, 68)) + [70, 93, 95, 147, 219, 221]  # 0-based

# 筛选阈值
PLDDT_GLOBAL_THRESHOLD = 80.0     # 全局均值
PTM_THRESHOLD = 0.75               # 全局折叠置信度
PLDDT_CHROMOPHORE_THRESHOLD = 85.0 # 发色团区域最低均值


def load_candidates(csv_path, top_ml=None):
    """加载策略C候选序列，可选仅取Top N (by ML brightness)"""
    df = pd.read_csv(csv_path)
    print(f"Loaded {len(df)} candidates from {csv_path}")

    if top_ml and top_ml < len(df):
        # 按 ML 亮度排序，取 Top N
        if "pred_brightness" in df.columns:
            df = df.sort_values("pred_brightness", ascending=False).head(top_ml)
            print(f"  → Filtered to Top {top_ml} by ML brightness")
            print(f"  → Range: [{df.pred_brightness.min():.3f}, {df.pred_brightness.max():.3f}]")
        else:
            print("  WARNING: pred_brightness column not found, using first N rows")

    print(f"  num_mutations: [{df.num_mutations.min()}, {df.num_mutations.max()}], "
          f"mean={df.num_mutations.mean():.1f}")
    return df


def load_esmfold_model(device_str="cuda:0"):
    """加载 ESMFold 模型"""
    import esm
    device = torch.device(device_str if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    model = esm.pretrained.esmfold_v1()
    model = model.to(device).eval()
    print("ESMFold v1 loaded")
    return model, device


def compute_esmfold_metrics(output, seq):
    """从 ESMFold 输出提取所有关键指标。"""
    metrics = {}

    # 全局 pLDDT
    plddt = output["plddt"].cpu().numpy()  # shape: (1, L)
    metrics["plddt_mean"] = float(plddt.mean())
    metrics["plddt_per_residue"] = plddt[0].tolist()
    metrics["ptm"] = float(output["ptm"].item())

    # 发色团区域局部 pLDDT
    L = plddt.shape[1]
    chromo_indices = [i for i in CHROMOPHORE_REGION if i < L]
    if chromo_indices:
        metrics["plddt_chromophore_mean"] = float(plddt[0, chromo_indices].mean())
        metrics["plddt_chromophore_min"] = float(plddt[0, chromo_indices].min())
    else:
        metrics["plddt_chromophore_mean"] = None
        metrics["plddt_chromophore_min"] = None

    # pLDDT < 70 的残基比例 (低置信度区域)
    metrics["frac_low_conf"] = float((plddt[0] < 70).mean())
    # pLDDT < 50 的残基比例 (极低置信度)
    metrics["frac_very_low_conf"] = float((plddt[0] < 50).mean())

    # 发色团三联体各残基 pLDDT
    for pos_name, pos_idx in [("T65", 64), ("Y66", 65), ("G67", 66),
                               ("R96", 95), ("E222", 221)]:
        if pos_idx < L:
            metrics[f"plddt_{pos_name}"] = float(plddt[0, pos_idx])

    return metrics


def determine_status(metrics):
    """根据指标判断结构验证状态。"""
    checks = []

    # 1. 全局 pLDDT
    if metrics["plddt_mean"] >= PLDDT_GLOBAL_THRESHOLD:
        checks.append("global_ok")
    else:
        checks.append("global_low")

    # 2. pTM
    if metrics["ptm"] >= PTM_THRESHOLD:
        checks.append("ptm_ok")
    else:
        checks.append("ptm_low")

    # 3. 发色团区域
    if (metrics["plddt_chromophore_mean"] is not None and
        metrics["plddt_chromophore_mean"] >= PLDDT_CHROMOPHORE_THRESHOLD):
        checks.append("chromo_ok")
    else:
        checks.append("chromo_low")

    # 综合状态
    if "global_ok" in checks and "ptm_ok" in checks and "chromo_ok" in checks:
        return "pass"
    elif "global_low" in checks or "ptm_low" in checks:
        return "fail_structure"
    else:
        return "fail_chromophore"


def run_batch(model, device, sequences, batch_size=2):
    """批量推理 ESMFold"""
    results = []
    for i in range(0, len(sequences), batch_size):
        batch = sequences[i:i+batch_size]
        try:
            with torch.no_grad():
                outputs = model.infer(batch)
            # Handle single vs batch output
            if not isinstance(outputs, list):
                outputs = [outputs]
            for seq, out in zip(batch, outputs):
                results.append(compute_esmfold_metrics(out, seq))
        except Exception as e:
            for seq in batch:
                results.append({"error": str(e)[:100]})
        torch.cuda.empty_cache()
    return results


def load_checkpoint():
    """加载已有结果用于断点续跑"""
    if not os.path.exists(OUT_CSV):
        return set(), []
    existing = pd.read_csv(OUT_CSV)
    done_seqs = set(existing["sequence"].tolist())
    records = existing.to_dict("records")
    print(f"Resume: {len(done_seqs)} already processed, {len(records)} records loaded")
    return done_seqs, records


def save_incremental(records, out_csv, per_residue_data, out_json):
    """增量保存 CSV + per-residue JSON"""
    df = pd.DataFrame(records)
    df.to_csv(out_csv, index=False)

    # 保存 per-residue pLDDT (仅保存 pass 候选以减少文件大小)
    if per_residue_data:
        with open(out_json, "w") as f:
            json.dump(per_residue_data, f, indent=2)


def print_summary(records):
    """打印当前摘要"""
    if not records:
        return
    df = pd.DataFrame(records)
    n = len(df)
    n_pass = (df["status"] == "pass").sum()
    n_fail_struct = (df["status"] == "fail_structure").sum()
    n_fail_chromo = (df["status"] == "fail_chromophore").sum()
    n_err = df["status"].str.startswith("error").sum() if "status" in df.columns else 0

    plddts = df[df["plddt_mean"].notna()]["plddt_mean"]
    ptms = df[df["ptm"].notna()]["ptm"]

    print(f"\n{'='*60}")
    print(f"SUMMARY ({n} sequences)")
    print(f"  ✅ pass (global+ptm+chromo): {n_pass} ({n_pass/n*100:.1f}%)")
    print(f"  ❌ fail structure:           {n_fail_struct} ({n_fail_struct/n*100:.1f}%)")
    print(f"  ⚠️  fail chromophore:         {n_fail_chromo} ({n_fail_chromo/n*100:.1f}%)")
    if n_err: print(f"  💥 errors:                   {n_err}")
    if len(plddts) > 0:
        print(f"  pLDDT mean: {plddts.mean():.1f} ± {plddts.std():.1f}, "
              f"range [{plddts.min():.1f}, {plddts.max():.1f}]")
    if len(ptms) > 0:
        print(f"  pTM mean:   {ptms.mean():.3f} ± {ptms.std():.3f}, "
              f"range [{ptms.min():.3f}, {ptms.max():.3f}]")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Strategy C: ESMFold full-scale structure screening")
    parser.add_argument("--device", default="cuda:0",
                        help="PyTorch device (default: cuda:0)")
    parser.add_argument("--batch-size", type=int, default=2,
                        help="Batch size for ESMFold inference (default: 2)")
    parser.add_argument("--top-ml", type=int, default=0,
                        help="Only process top N candidates by ML brightness (0=all)")
    parser.add_argument("--save-every", type=int, default=5,
                        help="Save checkpoint every N sequences (default: 5)")
    parser.add_argument("--no-resume", action="store_true",
                        help="Don't resume from checkpoint")
    parser.add_argument("--max-seqs", type=int, default=0,
                        help="Max sequences to process (0=all, for testing)")
    args = parser.parse_args()

    print("=" * 60)
    print("STRATEGY C — ESMFold Full-Scale Structure Screening (T1)")
    print("=" * 60)

    # ── 加载数据 ──
    df = load_candidates(CAND_CSV, top_ml=args.top_ml if args.top_ml > 0 else None)
    sequences = df["sequence"].tolist()

    # ── 断点续跑 ──
    if not args.no_resume:
        done_seqs, records = load_checkpoint()
    else:
        done_seqs, records = set(), []
        print("Fresh start (--no-resume)")

    # 找出未处理的序列
    remaining_indices = []
    remaining_seqs = []
    for idx, seq in enumerate(sequences):
        if seq not in done_seqs:
            remaining_indices.append(idx)
            remaining_seqs.append(seq)

    if args.max_seqs > 0 and len(remaining_seqs) > args.max_seqs:
        remaining_seqs = remaining_seqs[:args.max_seqs]
        remaining_indices = remaining_indices[:args.max_seqs]

    if not remaining_seqs:
        print("All sequences already processed!")
        print_summary(records)
        return

    print(f"\nTo process: {len(remaining_seqs)}/{len(sequences)} sequences")
    est_time = len(remaining_seqs) * 30 / 60  # ~30s per seq
    print(f"Estimated time: ~{est_time:.1f} min ({est_time/60:.1f} h)")

    # ── 加载模型 ──
    model, device = load_esmfold_model(args.device)

    # ── 逐序列推理 ──
    per_residue_data = {}
    t0 = time.time()
    new_count = 0

    for idx, seq in zip(remaining_indices, remaining_seqs):
        seq_idx = idx  # 0-based index in original dataframe
        row = df.iloc[idx]

        # ESMFold 推理
        seq_start = time.time()
        try:
            with torch.no_grad():
                output = model.infer([seq])
            metrics = compute_esmfold_metrics(output, seq)
        except Exception as e:
            metrics = {"error": str(e)[:150]}

        seq_time = time.time() - seq_start

        # 组装记录
        status = determine_status(metrics) if "error" not in metrics else f"error:{metrics['error'][:30]}"
        record = {
            "idx": idx,
            "status": status,
            "num_mutations": int(row["num_mutations"]),
            "temperature": row["temperature"],
            "mpnn_score": row["mpnn_score"],
            "pred_brightness": row.get("pred_brightness", np.nan),
            "plddt_mean": round(metrics.get("plddt_mean", 0), 2),
            "ptm": round(metrics.get("ptm", 0), 3),
            "plddt_chromophore_mean": (round(metrics["plddt_chromophore_mean"], 2)
                                       if metrics.get("plddt_chromophore_mean") is not None else None),
            "plddt_chromophore_min": (round(metrics["plddt_chromophore_min"], 2)
                                      if metrics.get("plddt_chromophore_min") is not None else None),
            "frac_low_conf": round(metrics.get("frac_low_conf", 0), 3),
            "frac_very_low_conf": round(metrics.get("frac_very_low_conf", 0), 3),
            "plddt_T65": metrics.get("plddt_T65"),
            "plddt_Y66": metrics.get("plddt_Y66"),
            "plddt_G67": metrics.get("plddt_G67"),
            "plddt_R96": metrics.get("plddt_R96"),
            "plddt_E222": metrics.get("plddt_E222"),
            "seq_time_s": round(seq_time, 1),
        }

        records.append(record)
        new_count += 1
        done_seqs.add(seq)

        # 保存 per-residue pLDDT (仅 pass 候选)
        if status == "pass" and "plddt_per_residue" in metrics:
            per_residue_data[str(idx)] = {
                "status": "pass",
                "plddt": metrics["plddt_per_residue"],
                "chromophore_mean": metrics.get("plddt_chromophore_mean"),
            }

        torch.cuda.empty_cache()

        # ── 进度报告 + 增量保存 ──
        total_done = len(records)
        if new_count % args.save_every == 0:
            save_incremental(records, OUT_CSV, per_residue_data, OUT_JSON)

        elapsed = time.time() - t0
        rate = total_done / max(elapsed, 1) * 60  # seqs/min
        eta = max(0, len(sequences) - total_done) / max(rate, 0.001)  # minutes

        print(f"  [{total_done}/{len(sequences)}] "
              f"idx={idx} pLDDT={record['plddt_mean']:.1f} "
              f"pTM={record['ptm']:.3f} "
              f"chromo={record['plddt_chromophore_mean']} "
              f"| {record['num_mutations']}muts "
              f"| {seq_time:.0f}s "
              f"| {status} "
              f"| ETA {eta:.0f}min")

    # ── 最终保存 ──
    save_incremental(records, OUT_CSV, per_residue_data, OUT_JSON)

    elapsed_total = (time.time() - t0) / 60
    print(f"\nDone in {elapsed_total:.1f} min ({elapsed_total/60:.1f} h)")

    print_summary(records)

    # ── 推荐下一步 ──
    df_out = pd.DataFrame(records)
    pass_df = df_out[df_out["status"] == "pass"]
    if len(pass_df) > 0:
        print(f"\nRecommended next: FoldX on Top {min(100, len(pass_df))} pass candidates")
        pass_top = pass_df.nlargest(min(20, len(pass_df)), "plddt_mean")
        print("\nTop 20 by pLDDT:")
        cols = ["idx", "plddt_mean", "ptm", "plddt_chromophore_mean",
                "num_mutations", "pred_brightness", "status"]
        print(pass_top[cols].to_string())


if __name__ == "__main__":
    main()
