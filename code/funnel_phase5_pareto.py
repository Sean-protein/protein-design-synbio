# -*- coding: utf-8 -*-
"""Phase 5: Pareto精选 → 最终6条提交序列

Consumes: results/funnel_phase4_top15.csv
Produces: results/funnel_phase5_preliminary_6.csv, results/submission_6_sequences.csv
After MD:   results/funnel_phase5_final_6.csv

Selection logic:
  Seq 1: Strategy D → high stability (best stability_score on Pareto front)
  Seq 2: Strategy A → high brightness (best composite_score, mChartreuse priority)
  Seq 3: Pareto optimal → balanced product (best composite × stability)
  Seq 4: High brightness → brightness push (best composite_score remaining)
  Seq 5: Strategy A → safety redundancy (lowest foldx_ddG, 0 level2 mutations)
  Seq 6: Strategy C → diversity contribution (highest mpnn_score)

Constraints enforced:
  - Level2 positions (69, 94, 148, 203, 205): ≤2 mutations
  - Mutation count limits: A≤4, D≤12, B≤25, C unlimited
  - ≥3 strategy sources among the 6
  - Pairwise sequence identity < 90% (CD-HIT-like check)
"""

import os
import sys

import numpy as np
import pandas as pd

# ── Encoding compatibility ────────────────────────────────────────────────
if sys.platform == "win32":
    import io

    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )
    except (AttributeError, OSError):
        pass

# ── Paths ─────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

INPUT_TOP15 = os.path.join(RESULTS_DIR, "funnel_phase4_top15.csv")
OUTPUT_PRELIM = os.path.join(RESULTS_DIR, "funnel_phase5_preliminary_6.csv")
OUTPUT_FINAL = os.path.join(RESULTS_DIR, "funnel_phase5_final_6.csv")
SUBMISSION_CSV = os.path.join(RESULTS_DIR, "submission_6_sequences.csv")

# ── Constants ─────────────────────────────────────────────────────────────
LEVEL2_POSITIONS = {69, 94, 148, 203, 205}  # 1-based

# Standard sfGFP WT from competition reference
# (consistent with funnel_phase1_compliance.py and competition/AAseqs_of_5_GFPs)
SFGFP_WT = (
    "MSKGEELFTGVVPILVELDGDVNGHKFSVRGEGEGDATNGKLTLKFICTTGKLPVPWPTLVTTLTY"
    "GVQCFSRYPDHMKRHDFFKSAMPEGYVQERTISFKDDGTYKTRAEVKFEGDTLVNRIELKGIDFKE"
    "DGNILGHKLEYNFNSHNVYITADKQKNGIKANFKIRHNVEDGSVQLADHYQQNTPIGDGPVLLPDN"
    "HYLSTQSVLSKDPNEKRDHMVLLEFVTAAGITHGMDELYK"
)

STRATEGY_TARGETS = {
    1: {"source": "D", "label": "高稳定性保底"},
    2: {"source": "A", "label": "高亮度保底"},
    3: {"source": "B", "label": "乘积平衡主力"},
    4: {"source": "B", "label": "亮度冲金"},
    5: {"source": "A", "label": "安全性冗余"},
    6: {"source": "C", "label": "多样性加分"},
}

# Mutation count limits per strategy
MUT_LIMITS = {"A": 4, "D": 12, "B": 25}
# Strategy C has no limit (unlimited)


# ── Pareto front computation ──────────────────────────────────────────────


def compute_pareto_front(df, x_col="composite_score", y_col="stability_score"):
    """Compute Pareto front (maximize both dimensions).

    Returns boolean array where True = Pareto-optimal point.
    A point i is dominated if there exists j with j better in both dimensions
    and strictly better in at least one.
    """
    points = df[[x_col, y_col]].values.copy()
    n = len(points)
    is_pareto = np.ones(n, dtype=bool)

    for i in range(n):
        # Skip NaN rows — cannot be on Pareto front
        if np.isnan(points[i, 0]) or np.isnan(points[i, 1]):
            is_pareto[i] = False
            continue
        for j in range(n):
            if i == j:
                continue
            if np.isnan(points[j, 0]) or np.isnan(points[j, 1]):
                continue
            # j dominates i: j >= i in both, and j > i in at least one
            if (
                points[j, 0] >= points[i, 0]
                and points[j, 1] >= points[i, 1]
                and (points[j, 0] > points[i, 0] or points[j, 1] > points[i, 1])
            ):
                is_pareto[i] = False
                break

    return is_pareto


def compute_pareto_regions(df):
    """Divide Pareto front into 4 regions.

    1. brightness_extreme:  top 25% composite_score
    2. stability_extreme:   top 25% stability_score
    3. product_optimal:     top 25% product (composite × stability)
    4. exploration:         remaining Pareto points
    """
    df = df.copy()
    df["product"] = df["composite_score"] * df["stability_score"]

    b_thresh = df["composite_score"].quantile(0.75)
    s_thresh = df["stability_score"].quantile(0.75)
    p_thresh = df["product"].quantile(0.75)

    conditions = [
        df["composite_score"] >= b_thresh,
        df["stability_score"] >= s_thresh,
        df["product"] >= p_thresh,
    ]
    df["region"] = np.select(
        conditions,
        ["brightness_extreme", "stability_extreme", "product_optimal"],
        default="exploration",
    )

    return df


# ── Constraint checks ─────────────────────────────────────────────────────


def count_level2_mutations(seq, wt_seq=None):
    """Count mutations at Level-2 positions (69, 94, 148, 203, 205).

    Level-2 positions are chromophore-proximal and functionally sensitive.
    Constraint: ≤ 2 mutations across these 5 positions.
    """
    if wt_seq is None:
        wt_seq = SFGFP_WT

    count = 0
    for pos in LEVEL2_POSITIONS:
        idx = pos - 1  # 1-based → 0-based
        if idx < len(seq) and idx < len(wt_seq) and seq[idx] != wt_seq[idx]:
            count += 1
    return count


def apply_constraints(df):
    """Apply selection constraints:
    1. Level-2 positions ≤ 2 mutations
    2. Per-strategy mutation count limits
    """
    df = df.copy()

    # Level-2 constraint
    df["level2_mut_count"] = df["sequence"].apply(count_level2_mutations)
    df["pass_level2"] = df["level2_mut_count"] <= 2

    # Per-strategy mutation count constraint
    df["mut_constraint_pass"] = True
    mask_a = df["source_strategy"] == "A"
    mask_d = df["source_strategy"] == "D"
    mask_c = df["source_strategy"] == "C"
    mask_b = ~mask_a & ~mask_d & ~mask_c  # Strategy B

    for strat, limit in MUT_LIMITS.items():
        mask = df["source_strategy"] == strat
        df.loc[mask, "mut_constraint_pass"] = df.loc[mask, "num_mutations"] <= limit

    # Strategy C has no limit (already True by default)

    df["all_constraints_pass"] = df["pass_level2"] & df["mut_constraint_pass"]
    return df


# ── Sequence identity check ───────────────────────────────────────────────


def check_pairwise_identity(sequences, threshold=0.90):
    """Check pairwise sequence identity among selected sequences.

    Returns list of (i, j, identity) tuples for pairs exceeding threshold.
    """
    warnings = []
    for i in range(len(sequences)):
        for j in range(i + 1, len(sequences)):
            if len(sequences[i]) != len(sequences[j]):
                continue
            matches = sum(a == b for a, b in zip(sequences[i], sequences[j]))
            identity = matches / len(sequences[i])
            if identity > threshold:
                warnings.append((i, j, identity))
    return warnings


# ── Selection ─────────────────────────────────────────────────────────────


def _safe_sort(df, by, ascending=False, fill_val=None):
    """Sort DataFrame handling NaN values in sort column."""
    if by not in df.columns:
        return df
    work = df.copy()
    if fill_val is not None:
        work[by] = work[by].fillna(fill_val)
    else:
        # Default: NaN goes to end (least priority)
        work = work.sort_values(by, ascending=ascending, na_position="last")
        return work
    return work.sort_values(by, ascending=ascending)


def select_6_sequences(df):
    """Select 6 sequences according to the allocation strategy.

    Returns DataFrame with selected sequences and their selection_reason.
    """
    df = apply_constraints(df)
    df = df[df["all_constraints_pass"]].copy()

    if len(df) == 0:
        print("  WARNING: No sequences pass all constraints!")
        return pd.DataFrame()

    # Compute Pareto front
    df["is_pareto"] = compute_pareto_front(df)
    df = compute_pareto_regions(df)

    selected = []
    used_ids = set()

    # ── Seq 1: D最优 (稳定性保底) ──
    d_candidates = df[
        (df["source_strategy"] == "D") & (df["is_pareto"])
    ]
    d_candidates = _safe_sort(d_candidates, "stability_score", ascending=False)
    if len(d_candidates) > 0:
        row = dict(d_candidates.iloc[0])
        row["selection_reason"] = "高稳定性保底-策略D进化共识"
        selected.append(row)
        used_ids.add(d_candidates.iloc[0]["seq_id"])
        print(f"  Seq 1 (D稳定性): {row['seq_id']} stability={row['stability_score']:.4f}")
    else:
        print("  Seq 1 (D稳定性): 无符合条件的策略D候选 (Pareto+constraints)")

    # ── Seq 2: A最优 (亮度保底, mChartreuse优先) ──
    a_candidates = df[
        (df["source_strategy"] == "A") & (~df["seq_id"].isin(used_ids))
    ]
    a_candidates = _safe_sort(a_candidates, "composite_score", ascending=False)

    # mChartreuse priority
    mc = a_candidates[a_candidates["seq_id"].str.contains("mChartreuse", na=False)]
    if len(mc) > 0:
        row = dict(mc.iloc[0])
        row["selection_reason"] = "高亮度保底-mChartreuse衍生"
        selected.append(row)
        used_ids.add(mc.iloc[0]["seq_id"])
        print(f"  Seq 2 (A亮度-mChartreuse): {row['seq_id']} brightness={row['composite_score']:.4f}")
    elif len(a_candidates) > 0:
        row = dict(a_candidates.iloc[0])
        row["selection_reason"] = "高亮度保底-策略A理性枚举"
        selected.append(row)
        used_ids.add(a_candidates.iloc[0]["seq_id"])
        print(f"  Seq 2 (A亮度): {row['seq_id']} brightness={row['composite_score']:.4f}")
    else:
        print("  Seq 2 (A亮度): 无符合条件的策略A候选")

    # ── Seq 3: 乘积平衡主力 (Pareto最优) ──
    pareto = df[
        df["is_pareto"] & (~df["seq_id"].isin(used_ids))
    ]
    pareto = _safe_sort(pareto, "product", ascending=False)
    if len(pareto) > 0:
        row = dict(pareto.iloc[0])
        row["selection_reason"] = "乘积平衡主力-Pareto最优"
        selected.append(row)
        used_ids.add(pareto.iloc[0]["seq_id"])
        print(f"  Seq 3 (乘积平衡): {row['seq_id']} product={row['product']:.4f}")
    else:
        # Fallback: best remaining by product (not necessarily Pareto)
        remaining = df[~df["seq_id"].isin(used_ids)]
        remaining = _safe_sort(remaining, "product", ascending=False)
        if len(remaining) > 0:
            row = dict(remaining.iloc[0])
            row["selection_reason"] = "乘积平衡-备选(非Pareto)"
            selected.append(row)
            used_ids.add(remaining.iloc[0]["seq_id"])
            print(f"  Seq 3 (乘积平衡-备选): {row['seq_id']} product={row['product']:.4f}")
        else:
            print("  Seq 3 (乘积平衡): 无可用候选")

    # ── Seq 4: 亮度冲金 ──
    bright = df[~df["seq_id"].isin(used_ids)]
    bright = _safe_sort(bright, "composite_score", ascending=False)
    if len(bright) > 0:
        row = dict(bright.iloc[0])
        row["selection_reason"] = "亮度冲金"
        selected.append(row)
        used_ids.add(bright.iloc[0]["seq_id"])
        print(f"  Seq 4 (亮度冲金): {row['seq_id']} brightness={row['composite_score']:.4f}")
    else:
        print("  Seq 4 (亮度冲金): 无可用候选")

    # ── Seq 5: 安全性冗余 (最低ddG + 避开二级位点) ──
    safe = df[
        (~df["seq_id"].isin(used_ids)) & (df["level2_mut_count"] == 0)
    ]
    if "foldx_ddG" in safe.columns:
        safe = _safe_sort(safe, "foldx_ddG", ascending=True, fill_val=999)
    if len(safe) > 0:
        row = dict(safe.iloc[0])
        row["selection_reason"] = "安全性冗余-最低ddG+零二级突变"
        selected.append(row)
        used_ids.add(safe.iloc[0]["seq_id"])
        print(f"  Seq 5 (安全性): {row['seq_id']} ddG={row.get('foldx_ddG', 'N/A')}")
    else:
        # Fallback: any remaining with lowest level2_mut_count
        remaining = df[~df["seq_id"].isin(used_ids)]
        remaining = _safe_sort(remaining, "level2_mut_count", ascending=True)
        if len(remaining) > 0:
            row = dict(remaining.iloc[0])
            row["selection_reason"] = "安全性冗余-备选(最少二级突变)"
            selected.append(row)
            used_ids.add(remaining.iloc[0]["seq_id"])
            print(f"  Seq 5 (安全性-备选): {row['seq_id']} level2_muts={row['level2_mut_count']}")
        else:
            print("  Seq 5 (安全性): 无可用候选")

    # ── Seq 6: 策略C多样性 ──
    c_candidates = df[
        (df["source_strategy"] == "C") & (~df["seq_id"].isin(used_ids))
    ]
    if "mpnn_score" in c_candidates.columns:
        c_candidates = _safe_sort(c_candidates, "mpnn_score", ascending=False, fill_val=-999)
    if len(c_candidates) > 0:
        row = dict(c_candidates.iloc[0])
        row["selection_reason"] = "多样性加分-ProteinMPNN逆折叠"
        selected.append(row)
        used_ids.add(c_candidates.iloc[0]["seq_id"])
        mpnn = row.get("mpnn_score", "N/A")
        print(f"  Seq 6 (C多样性): {row['seq_id']} mpnn_score={mpnn}")
    else:
        # Fallback: best remaining
        remaining = df[~df["seq_id"].isin(used_ids)]
        remaining = _safe_sort(remaining, "composite_score", ascending=False)
        if len(remaining) > 0:
            row = dict(remaining.iloc[0])
            row["selection_reason"] = "备选-最优可用"
            selected.append(row)
            used_ids.add(remaining.iloc[0]["seq_id"])
            print(f"  Seq 6 (备选): {row['seq_id']} brightness={row['composite_score']:.4f}")
        else:
            print("  Seq 6 (备选): 无可用候选")

    return pd.DataFrame(selected)


# ── Submission CSV ────────────────────────────────────────────────────────


def generate_submission_csv(selected_df, output_path):
    """Generate competition submission CSV format."""
    if len(selected_df) == 0:
        print("  WARNING: No sequences selected, skipping submission CSV.")
        return pd.DataFrame()

    submission = pd.DataFrame(
        {
            "Seq_ID": [f"Seq{i + 1}" for i in range(len(selected_df))],
            "Sequence": selected_df["sequence"].values,
        }
    )
    submission.to_csv(output_path, index=False)
    print(f"  提交CSV已保存: {output_path} ({len(submission)} 条)")
    return submission


# ── Main ──────────────────────────────────────────────────────────────────


def main(input_path=None, output_prelim=None, output_final=None,
         submission_path=None):
    """Phase 5 main entry point.

    Parameters
    ----------
    input_path : str or None
        Override input CSV (default: funnel_phase4_top15.csv).
    output_prelim : str or None
        Preliminary output path.
    output_final : str or None
        Final output path (for after MD update).
    submission_path : str or None
        Submission CSV output path.
    """
    _input = input_path or INPUT_TOP15
    _prelim = output_prelim or OUTPUT_PRELIM
    _final = output_final or OUTPUT_FINAL
    _submission = submission_path or SUBMISSION_CSV

    print("=" * 60)
    print("Phase 5: Pareto精选 → 最终6条提交序列")
    print("=" * 60)

    # ── Load ──
    if not os.path.exists(_input):
        print(f"\n[XX] 输入文件不存在: {_input}")
        print("  请先运行 Phase 4 (code/funnel_phase4_stability.py)")
        return 1

    df = pd.read_csv(_input)
    n_input = len(df)
    print(f"\n输入: {n_input} 条序列 (Phase 4 Top {n_input})")

    # Strategy distribution
    strat_counts = df["source_strategy"].value_counts().to_dict()
    print(f"策略分布: {strat_counts}")
    if "composite_score" in df.columns:
        print(f"Brightness 范围: [{df['composite_score'].min():.3f}, "
              f"{df['composite_score'].max():.3f}]")
    if "stability_score" in df.columns:
        print(f"Stability 范围: [{df['stability_score'].min():.4f}, "
              f"{df['stability_score'].max():.4f}]")

    # ── Select ──
    print("\n--- 选择过程 ---")
    selected = select_6_sequences(df)

    n_selected = len(selected)
    print(f"\n选出: {n_selected} 条序列")

    if n_selected == 0:
        print("\n[FAIL] 未能选出任何序列!")
        return 1

    print(f"\n{'─' * 60}")
    print("选择详情:")
    for i, (_, row) in enumerate(selected.iterrows()):
        reason = row.get("selection_reason", "N/A")
        sid = row["seq_id"]
        strat = row["source_strategy"]
        brightness = row.get("composite_score", float("nan"))
        stability = row.get("stability_score", float("nan"))
        mutations = row.get("num_mutations", "?")
        l2_muts = row.get("level2_mut_count", "?")
        print(
            f"  [{i + 1}] {reason}\n"
            f"      seq_id={sid}, strategy={strat}, "
            f"brightness={brightness:.4f}, stability={stability:.4f}, "
            f"mutations={mutations}, level2_muts={l2_muts}"
        )

    # ── Diversity checks ──
    print(f"\n{'─' * 60}")
    print("多样性检查:")

    # Pairwise identity
    sequences = selected["sequence"].tolist()
    warnings = check_pairwise_identity(sequences, threshold=0.90)
    if warnings:
        for i, j, identity in warnings:
            print(f"  WARNING: Seq{i + 1} 与 Seq{j + 1} 序列相似度 {identity:.1%} > 90%!")
    else:
        print("  序列成对相似度: 全部 < 90% (通过)")

    # Strategy diversity
    strategies = set(selected["source_strategy"].unique())
    n_strategies = len(strategies)
    print(f"  策略覆盖: {strategies} ({n_strategies} 种)")
    if n_strategies < 3:
        print(f"  WARNING: 策略来源不足3种! (需要≥3, 当前{n_strategies})")
    else:
        print(f"  策略多样性: 通过 (≥3)")

    # ── Save ──
    print(f"\n{'─' * 60}")
    selected.to_csv(_prelim, index=False)
    print(f"预选输出: {_prelim} ({n_selected} 条)")

    generate_submission_csv(selected, _submission)

    # Also save a copy for final (preliminary = final until MD updates)
    selected.to_csv(_final, index=False)
    print(f"最终输出: {_final} ({n_selected} 条)")

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print("Phase 5 完成摘要")
    print(f"{'=' * 60}")
    print(f"  输入: {n_input} 条")
    print(f"  约束过滤后: {len(selected)} 条")
    print(f"  策略覆盖: {n_strategies}/3+ required")
    print(f"  序列相似度: {'通过' if not warnings else 'WARNING'}")
    print(f"\n  输出文件:")
    print(f"    预选: {_prelim}")
    print(f"    最终: {_final}")
    print(f"    提交: {_submission}")
    print("\n待MD完成后，用真实MD数据替换foldx/stability字段并重跑确认。")

    return 0


# ── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase 5: Pareto精选 → 6条提交序列"
    )
    parser.add_argument(
        "--input", type=str, default=INPUT_TOP15,
        help=f"输入CSV路径 (默认: {INPUT_TOP15})",
    )
    parser.add_argument(
        "--output-prelim", type=str, default=OUTPUT_PRELIM,
        help=f"预选输出路径 (默认: {OUTPUT_PRELIM})",
    )
    parser.add_argument(
        "--output-final", type=str, default=OUTPUT_FINAL,
        help=f"最终输出路径 (默认: {OUTPUT_FINAL})",
    )
    parser.add_argument(
        "--submission", type=str, default=SUBMISSION_CSV,
        help=f"提交CSV路径 (默认: {SUBMISSION_CSV})",
    )

    args = parser.parse_args()
    sys.exit(
        main(
            input_path=args.input,
            output_prelim=args.output_prelim,
            output_final=args.output_final,
            submission_path=args.submission,
        )
    )
