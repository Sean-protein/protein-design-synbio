# -*- coding: utf-8 -*-
"""
策略C — 精选可用序列（严格条件筛选）
=====================================
从273条ProteinMPNN候选中选出真正可用的1-3条：
  1. 突变数 < 30（FoldX可验证范围）
  2. mpnn_score > 0.85（ProteinMPNN自评高置信度）
  3. ML亮度 > 1.5（策略B预测高亮度）

用法:
  python strategy_C_select.py                    # 筛选+保存
  python strategy_C_select.py --save-seqs        # 同时保存序列FASTA
"""

import os, sys
import numpy as np
import pandas as pd

# ── 路径 ──
def _find_root():
    for d in [os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "/data2/fenghaohui"]:
        if os.path.exists(d): return d
    return os.getcwd()
ROOT = _find_root()
R_DIR = os.path.join(ROOT, "results", "strategy_C")
os.makedirs(R_DIR, exist_ok=True)
IN_CSV  = os.path.join(R_DIR, "strategy_C_ml_scored.csv")
OUT_CSV = os.path.join(R_DIR, "strategy_C_selected.csv")
OUT_FASTA = os.path.join(R_DIR, "strategy_C_selected.fasta")

# ── 筛选条件（三级递进） ──
FILTERS = [
    {
        "name": "strict",
        "desc": "高标准：低突变+高MPNN置信度+高ML亮度",
        "mpnn_min": 0.85,
        "max_muts": 30,
        "bright_min": 1.5,
    },
    {
        "name": "moderate",
        "desc": "中等标准：放宽突变数",
        "mpnn_min": 0.80,
        "max_muts": 50,
        "bright_min": 1.0,
    },
    {
        "name": "relaxed",
        "desc": "宽松标准：确保至少选出1-2条",
        "mpnn_min": 0.75,
        "max_muts": 60,
        "bright_min": 0.5,
    },
]


def load_data():
    df = pd.read_csv(IN_CSV)
    print("=" * 60)
    print("STRATEGY C — Candidate Selection")
    print("=" * 60)
    print("Total: {} candidates".format(len(df)))
    print("Mutations: [{}, {}] mean={:.0f}".format(
        df.num_mutations.min(), df.num_mutations.max(), df.num_mutations.mean()))
    print("mpnn_score: [{:.3f}, {:.3f}] mean={:.3f}".format(
        df.mpnn_score.min(), df.mpnn_score.max(), df.mpnn_score.mean()))
    print("pred_brightness: [{:.2f}, {:.2f}] mean={:.2f}".format(
        df.pred_brightness.min(), df.pred_brightness.max(), df.pred_brightness.mean()))
    print()
    return df


def apply_filter(df, cfg):
    mask = (
        (df.mpnn_score >= cfg["mpnn_min"]) &
        (df.num_mutations <= cfg["max_muts"]) &
        (df.pred_brightness >= cfg["bright_min"])
    )
    return df[mask].copy()


def print_candidates(sub, title):
    if len(sub) == 0:
        print("  {}: 0 candidates\n".format(title))
        return
    print("  {}: {} candidates".format(title, len(sub)))
    sub = sub.sort_values("mpnn_score", ascending=False)
    for _, r in sub.iterrows():
        print("    {}muts | mpnn={:.3f} | bright={:.2f} | T={} | L2_warn={}".format(
            int(r.num_mutations), r.mpnn_score, r.pred_brightness,
            r.temperature, r.level2_warning))
    print()


def save_results(sub, output_csv, output_fasta=None):
    sub.to_csv(output_csv, index=False)
    print("Saved -> {}".format(output_csv))

    if output_fasta and len(sub) > 0:
        with open(output_fasta, "w") as f:
            for i, (_, r) in enumerate(sub.iterrows()):
                f.write(">C_{:04d} mpnn={:.3f} bright={:.2f} muts={}\n".format(
                    i, r.mpnn_score, r.pred_brightness, int(r.num_mutations)))
                f.write(r.sequence + "\n")
        print("Saved -> {}".format(output_fasta))


def main():
    df = load_data()

    selected = None
    used_filter = None

    for cfg in FILTERS:
        sub = apply_filter(df, cfg)
        print_candidates(sub, "[{}] {}".format(cfg["name"].upper(), cfg["desc"]))
        if len(sub) >= 1:
            selected = sub
            used_filter = cfg["name"]
            break

    if selected is None or len(selected) == 0:
        print("WARNING: No candidates pass any filter!")
        print("  Top 10 by mpnn_score regardless of constraints:")
        top10 = df.nlargest(10, "mpnn_score")
        for _, r in top10.iterrows():
            print("    {}muts | mpnn={:.3f} | bright={:.2f} | T={}".format(
                int(r.num_mutations), r.mpnn_score, r.pred_brightness, r.temperature))
        # take top 2 as fallback
        selected = top10.head(2)
        used_filter = "top2_fallback"

    print("=" * 60)
    print("SELECTED: {} candidates via [{}]".format(len(selected), used_filter))
    print("  These are 'diversity contributors' — not the primary submission pool.")
    print("  For final 6, pick at most 1-2 from here.")
    print("=" * 60)

    save_results(selected, OUT_CSV, OUT_FASTA)

    # ── 建议 ──
    print("\nNext steps:")
    print("  1. Review selected candidates manually")
    print("  2. Add 1-2 to final Pareto pool alongside A/D/B/TGP candidates")
    print("  3. Optional: run FoldX on these low-mutation candidates if time allows")


if __name__ == "__main__":
    main()
