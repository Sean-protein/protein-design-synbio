# -*- coding: utf-8 -*-
"""
策略C — ESMFold 后处理 & FoldX 候选精选
========================================
读取 ESMFold 全量结果，联合 ML 亮度打分，生成:
  1. 综合排序 (structural_confidence × brightness)
  2. FoldX 输入候选 (Top 50-100 by combined score)
  3. 结构结果摘要报告

筛选层级:
  T1: ESMFold pLDDT + pTM + 发色团区域 → 已在 esmfold_full 中完成
  T2: 综合评分 = pLDDT_zscore + pTM_zscore + brightness_zscore
  T3: 选取 Top-N 进入 FoldX (默认 Top 100)
  T4: 为 FoldX 生成 individual_list.txt 输入

用法:
  python strategy_C_post_esmfold.py                    # 分析+选FoldX候选
  python strategy_C_post_esmfold.py --top-foldx 50     # 仅选 Top 50 跑FoldX
  python strategy_C_post_esmfold.py --gen-foldx-input  # 生成FoldX输入文件
"""

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# ══════════════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════════════
def _find_project_root():
    for c in [
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "/data2/fenghaohui",
    ]:
        if os.path.exists(c):
            return c
    return os.getcwd()

PROJECT_ROOT = _find_project_root()
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results", "strategy_C")
os.makedirs(RESULTS_DIR, exist_ok=True)

# 输入
CAND_CSV = os.path.join(RESULTS_DIR, "strategy_C_ml_scored.csv")
ESMFOLD_CSV = os.path.join(RESULTS_DIR, "strategy_C_esmfold_full.csv")

# 输出
COMBINED_CSV = os.path.join(RESULTS_DIR, "strategy_C_combined_ranked.csv")
FOLDX_SELECTION_CSV = os.path.join(RESULTS_DIR, "strategy_C_foldx_selection.csv")
SUMMARY_TXT = os.path.join(RESULTS_DIR, "strategy_C_esmfold_summary.txt")
FOLDX_INPUT_DIR = os.path.join(RESULTS_DIR, "..", "strategy_C_foldx_input")

# sfGFP WT (for mutation string generation)
SFGFP_WT = ("MSKGEELFTGVVPILVELDGDVNGHKFSVRGEGEGDATNGKLTLKFICTTGKLPVPWPTLVTT"
            "LTYGVQCFSRYPDHMKRHDFFKSAMPEGYVQERTISFKDDGTYKTRAEVKFEGDTLVNRIELK"
            "GIDFKEDGNILGHKLEYNFNSHNVYITADKQKNGIKANFKIRHNVEDGSVQLADHYQQNTPIG"
            "DGPVLLPDNHYLSTQSVLSKDPNEKRDHMVLLEFVTAAGITHGMDELYK")

# Level 1 固定位点 (不可变)
LEVEL1_FIXED = {65, 66, 67, 71, 96, 222}


def seq_to_mutation_str(seq, wt):
    """全长序列 → FoldX individual_list 格式"""
    if len(seq) != len(wt):
        return None
    muts = []
    for i, (a, b) in enumerate(zip(seq, wt)):
        if a != b:
            muts.append(f"{b}A{i+1}{a}")
    return ",".join(muts) + ";" if muts else ""


def load_data():
    """加载数据并合并"""
    cand = pd.read_csv(CAND_CSV)
    esm = pd.read_csv(ESMFOLD_CSV)

    # 合并 (by sequence)
    merged = cand.merge(esm, on="sequence", how="inner", suffixes=("_cand", "_esm"))
    print(f"Candidates: {len(cand)}, ESMFold results: {len(esm)}, Merged: {len(merged)}")
    return merged


def compute_combined_score(df):
    """计算综合评分 = 归一化(pLDDT) + 归一化(pTM) + 归一化(brightness)"""
    df = df.copy()

    # z-score 归一化
    for col in ["plddt_mean", "ptm", "pred_brightness"]:
        if col in df.columns and df[col].notna().any():
            mean_val = df[col].mean()
            std_val = df[col].std()
            if std_val > 0:
                df[f"{col}_z"] = (df[col] - mean_val) / std_val
            else:
                df[f"{col}_z"] = 0
        else:
            df[f"{col}_z"] = 0

    # 综合得分 (pLDDT权重2x, pTM权重1x, brightness权重1x)
    weights = {"plddt_mean_z": 2.0, "ptm_z": 1.0, "pred_brightness_z": 1.0}
    df["combined_score"] = sum(
        df.get(f"{k}_z", 0) * w for k, w in weights.items()
    )

    # 结构分数 (仅结构指标)
    df["structure_score"] = (
        df.get("plddt_mean_z", 0) * 2.0 + df.get("ptm_z", 0) * 1.0
    )

    return df


def classify_candidates(df):
    """将候选分为不同等级"""
    conditions = [
        # Tier A: 完美通过所有筛选
        (df["status"] == "pass") &
        (df["plddt_mean"] >= 85) &
        (df["ptm"] >= 0.80) &
        (df["plddt_chromophore_mean"] >= 88),

        # Tier B: 通过但非顶级
        (df["status"] == "pass") &
        ((df["plddt_mean"] < 85) | (df["ptm"] < 0.80)),

        # Tier C: 发色团问题但结构OK
        (df["status"] == "fail_chromophore") &
        (df["plddt_mean"] >= 75),

        # Tier D: 结构勉强
        (df["status"].isin(["fail_structure", "fail_chromophore"])) &
        (df["plddt_mean"] >= 70) & (df["plddt_mean"] < 75),

        # Tier F: 不通过
        (df["plddt_mean"] < 70) |
        (df["status"].str.startswith("error", na=False)),
    ]
    choices = ["A", "B", "C", "D", "F"]
    df["tier"] = np.select(conditions, choices, default="U")
    return df


def select_for_foldx(df, top_n=100, min_tier="C"):
    """选取进入 FoldX 的候选"""
    tier_order = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 99, "U": 99}

    df = df.copy()
    df["tier_rank"] = df["tier"].map(tier_order)

    # 过滤: 至少达到 min_tier
    min_rank = tier_order.get(min_tier, 2)
    eligible = df[df["tier_rank"] <= min_rank].copy()

    if len(eligible) == 0:
        print(f"WARNING: No candidates meet tier >= {min_tier}. Falling back to all passing structure.")
        eligible = df[df["plddt_mean"] >= 70].copy()

    # 按 combined_score 排序取 Top N
    eligible = eligible.sort_values("combined_score", ascending=False)
    selected = eligible.head(top_n)

    print(f"\nFoldX selection: {len(selected)}/{len(df)} candidates")
    print(f"  Tier A: {(selected['tier']=='A').sum()}")
    print(f"  Tier B: {(selected['tier']=='B').sum()}")
    print(f"  Tier C: {(selected['tier']=='C').sum()}")
    print(f"  pLDDT range: [{selected['plddt_mean'].min():.1f}, {selected['plddt_mean'].max():.1f}]")
    print(f"  Mutations range: [{selected['num_mutations_esm'].min()}, {selected['num_mutations_esm'].max()}]")

    return selected


def generate_foldx_input(selected_df):
    """为选中的候选生成 FoldX individual_list.txt"""
    out_dir = FOLDX_INPUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    wt = SFGFP_WT
    generated = 0

    for _, row in selected_df.iterrows():
        seq = row["sequence"]
        # 使用 idx 或生成唯一ID
        seq_id = f"C_{int(row.get('idx_esm', row.get('idx_cand', 0))):04d}"

        mut_str = seq_to_mutation_str(seq, wt)
        if mut_str is None:
            print(f"  SKIP {seq_id}: length mismatch")
            continue

        # 创建目录和文件
        seq_dir = os.path.join(out_dir, seq_id)
        os.makedirs(seq_dir, exist_ok=True)

        ind_list_path = os.path.join(seq_dir, "individual_list.txt")
        with open(ind_list_path, "w") as f:
            f.write(mut_str + "\n")

        generated += 1

    print(f"\nGenerated FoldX input for {generated} sequences → {out_dir}")

    # 生成 foldx_index.csv
    index_rows = []
    for _, row in selected_df.iterrows():
        seq_id = f"C_{int(row.get('idx_esm', row.get('idx_cand', 0))):04d}"
        index_rows.append({
            "seq_id": seq_id,
            "plddt_mean": row["plddt_mean"],
            "ptm": row["ptm"],
            "combined_score": row["combined_score"],
            "tier": row["tier"],
            "num_mutations": row["num_mutations_esm"],
            "pred_brightness": row["pred_brightness"],
        })

    index_df = pd.DataFrame(index_rows)
    index_path = os.path.join(out_dir, "foldx_index.csv")
    index_df.to_csv(index_path, index=False)
    print(f"Index saved → {index_path}")

    return generated


def print_analysis(df):
    """打印详细分析"""
    lines = []
    lines.append("=" * 70)
    lines.append("STRATEGY C — ESMFold Structure Screening Analysis")
    lines.append("=" * 70)
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Total candidates: {len(df)}")
    lines.append("")

    # 整体统计
    lines.append("─" * 50)
    lines.append("1. OVERALL STATISTICS")
    lines.append("─" * 50)
    n_pass = (df["status"] == "pass").sum()
    n_fail_struct = (df["status"] == "fail_structure").sum()
    n_fail_chromo = (df["status"] == "fail_chromophore").sum()
    lines.append(f"  Pass (all criteria):         {n_pass:4d} ({n_pass/len(df)*100:5.1f}%)")
    lines.append(f"  Fail structure:              {n_fail_struct:4d} ({n_fail_struct/len(df)*100:5.1f}%)")
    lines.append(f"  Fail chromophore only:       {n_fail_chromo:4d} ({n_fail_chromo/len(df)*100:5.1f}%)")

    # pLDDT 分布
    lines.append("")
    lines.append("─" * 50)
    lines.append("2. pLDDT DISTRIBUTION")
    lines.append("─" * 50)
    bins = [0, 50, 60, 70, 80, 85, 90, 100]
    labels = ["<50", "50-60", "60-70", "70-80", "80-85", "85-90", "90-100"]
    plddt_bins = pd.cut(df["plddt_mean"], bins=bins, labels=labels)
    for label in labels:
        count = (plddt_bins == label).sum()
        pct = count / len(df) * 100
        bar = "█" * int(pct)
        lines.append(f"  {label:>7}: {count:4d} ({pct:5.1f}%) {bar}")

    # pLDDT vs 突变数
    lines.append("")
    lines.append("─" * 50)
    lines.append("3. pLDDT vs NUMBER OF MUTATIONS")
    lines.append("─" * 50)
    mut_bins = [0, 20, 40, 60, 80, 100]
    mut_labels = ["0-20", "20-40", "40-60", "60-80", "80-100"]
    df["mut_bin"] = pd.cut(df["num_mutations_esm"], bins=mut_bins, labels=mut_labels)
    for label in mut_labels:
        sub = df[df["mut_bin"] == label]
        if len(sub) > 0:
            lines.append(f"  {label:>7} muts: n={len(sub):3d}, "
                         f"pLDDT={sub['plddt_mean'].mean():.1f}±{sub['plddt_mean'].std():.1f}, "
                         f"pass_rate={ (sub['status']=='pass').sum()/len(sub)*100:.0f}%")

    # 发色团区域
    lines.append("")
    lines.append("─" * 50)
    lines.append("4. CHROMOPHORE REGION ANALYSIS")
    lines.append("─" * 50)
    chromo_ok = df[df["plddt_chromophore_mean"].notna()]
    if len(chromo_ok) > 0:
        lines.append(f"  Chromophore pLDDT: mean={chromo_ok['plddt_chromophore_mean'].mean():.1f}, "
                     f"range=[{chromo_ok['plddt_chromophore_mean'].min():.1f}, "
                     f"{chromo_ok['plddt_chromophore_mean'].max():.1f}]")
        for pos in ["T65", "Y66", "G67", "R96", "E222"]:
            col = f"plddt_{pos}"
            if col in df.columns and df[col].notna().any():
                vals = df[col].dropna()
                lines.append(f"  {pos}: mean={vals.mean():.1f}±{vals.std():.1f}, "
                             f"min={vals.min():.1f}, max={vals.max():.1f}")

    # 按温度分层
    lines.append("")
    lines.append("─" * 50)
    lines.append("5. BY SAMPLING TEMPERATURE")
    lines.append("─" * 50)
    for temp in sorted(df["temperature_cand"].unique()):
        sub = df[df["temperature_cand"] == temp]
        if len(sub) > 0:
            lines.append(f"  T={temp}: n={len(sub):3d}, "
                         f"pLDDT={sub['plddt_mean'].mean():.1f}±{sub['plddt_mean'].std():.1f}, "
                         f"pass_rate={(sub['status']=='pass').sum()/len(sub)*100:.0f}%, "
                         f"mutations={sub['num_mutations_esm'].mean():.0f}")

    # Tier 分布
    lines.append("")
    lines.append("─" * 50)
    lines.append("6. TIER DISTRIBUTION")
    lines.append("─" * 50)
    for tier in ["A", "B", "C", "D", "F"]:
        count = (df["tier"] == tier).sum()
        if count > 0:
            lines.append(f"  Tier {tier}: {count:4d} ({count/len(df)*100:5.1f}%)")

    lines.append("")
    lines.append("=" * 70)

    # Print and save
    report = "\n".join(lines)
    print(report)

    with open(SUMMARY_TXT, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nSummary saved → {SUMMARY_TXT}")

    return lines


def main():
    parser = argparse.ArgumentParser(
        description="Strategy C: Post-ESMFold analysis & FoldX selection")
    parser.add_argument("--top-foldx", type=int, default=100,
                        help="Number of candidates to select for FoldX (default: 100)")
    parser.add_argument("--min-tier", default="C",
                        help="Minimum tier for FoldX selection (default: C)")
    parser.add_argument("--gen-foldx-input", action="store_true",
                        help="Generate FoldX individual_list.txt files")
    parser.add_argument("--esmfold-csv", default=ESMFOLD_CSV,
                        help="Path to ESMFold results CSV")
    args = parser.parse_args()

    global ESMFOLD_CSV
    ESMFOLD_CSV = args.esmfold_csv

    if not os.path.exists(ESMFOLD_CSV):
        print(f"ERROR: ESMFold results not found: {ESMFOLD_CSV}")
        print("Run strategy_C_esmfold_full.py first.")
        sys.exit(1)

    print("=" * 60)
    print("STRATEGY C — Post-ESMFold Analysis & FoldX Selection")
    print("=" * 60)

    # ── 加载合并 ──
    df = load_data()

    # ── 综合评分 ──
    df = compute_combined_score(df)
    df = classify_candidates(df)

    # ── 分析报告 ──
    print_analysis(df)

    # ── 保存完整排名 ──
    ranked = df.sort_values("combined_score", ascending=False)
    ranked.to_csv(COMBINED_CSV, index=False)
    print(f"\nCombined ranking saved → {COMBINED_CSV}")

    # ── FoldX 候选精选 ──
    selected = select_for_foldx(df, top_n=args.top_foldx, min_tier=args.min_tier)
    selected.to_csv(FOLDX_SELECTION_CSV, index=False)
    print(f"FoldX selection saved → {FOLDX_SELECTION_CSV}")

    # ── 生成 FoldX 输入 ──
    if args.gen_foldx_input:
        generate_foldx_input(selected)

    # ── 推荐 ──
    print("\n" + "=" * 60)
    print("NEXT STEPS:")
    n_pass = (df["status"] == "pass").sum()
    n_tier_ab = ((df["tier"] == "A") | (df["tier"] == "B")).sum()

    if n_tier_ab >= 100:
        print(f"  ✅ {n_tier_ab} Tier A+B candidates — proceed to FoldX on Top 100")
    elif n_pass >= 50:
        print(f"  ✅ {n_pass} pass candidates — proceed to FoldX on Top {min(100, n_pass)}")
    else:
        print(f"  ⚠️  Only {n_pass} pass candidates — consider:")
        print(f"     1. Lower ESMFold threshold to pLDDT>70")
        print(f"     2. Rely more on Tier C (chromophore issue but structure OK)")
        print(f"     3. Increase strategy D/A candidate weight")

    print(f"  If this is the server, run:")
    print(f"    python run_foldx_strategy_C.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
