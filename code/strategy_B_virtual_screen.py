# -*- coding: utf-8 -*-
"""策略B虚拟筛选：用ML模型对A/D/C全量候选打分，找出高潜力序列

用法:
  python code/strategy_B_virtual_screen.py

输出:
  results/strategy_B/virtual_screen_A_top50.csv
  results/strategy_B/virtual_screen_D_top50.csv
  results/strategy_B/virtual_screen_C_top50.csv
  results/strategy_B/virtual_screen_summary.csv  (汇总推荐)
"""

import json, os, pickle, sys
import numpy as np
import pandas as pd

# ── Paths ──
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(PROJECT_ROOT, "results")
STRAT_B = os.path.join(RESULTS, "strategy_B")
MODELS_DIR = os.path.join(STRAT_B, "models")
OUT_DIR = os.path.join(STRAT_B, "virtual_screen")
os.makedirs(OUT_DIR, exist_ok=True)

# Data paths
A_CAND = os.path.join(RESULTS, "strategy_A_candidates.csv")
D_CAND = os.path.join(RESULTS, "strategy_D_all_candidates.csv")
C_CAND = os.path.join(RESULTS, "strategy_C", "strategy_C_candidates.csv")
A_FOLDX = os.path.join(RESULTS, "strategy_A_foldx_results.csv")
D_FOLDX = os.path.join(RESULTS, "strategy_D_foldx_results.csv")
SCORED = os.path.join(STRAT_B, "candidate_scores.csv")
EXISTING_6 = os.path.join(RESULTS, "funnel_phase5_final_6.csv")

# Feature dependencies
CONSERVATION = os.path.join(RESULTS, "strategy_D_conservation_profile.csv")
EPISTASIS = os.path.join(RESULTS, "strategy_D_epistasis_rules.json")

# ── Constants ──
SFGFP_WT = (
    "MSKGEELFTGVVPILVELDGDVNGHKFSVRGEGEGDATNGKLTLKFICTTGKLPVPWPTLVTTLTY"
    "GVQCFSRYPDHMKRHDFFKSAMPEGYVQERTISFKDDGTYKTRAEVKFEGDTLVNRIELKGIDFKE"
    "DGNILGHKLEYNFNSHNVYITADKQKNGIKANFKIRHNVEDGSVQLADHYQQNTPIGDGPVLLPDN"
    "HYLSTQSVLSKDPNEKRDHMVLLEFVTAAGITHGMDELYK"
)

MAX_SEQ_LEN = 238
EMBED_DIM = 1280

REGIONS = {
    "chromophore": [65, 66, 67, 68, 69, 70, 94, 95, 96, 146, 147, 148, 202, 203, 204, 205, 222],
    "beta_core": list(range(1, 14)) + list(range(19, 30)) + list(range(40, 51)) +
                 list(range(80, 91)) + list(range(106, 117)) + list(range(128, 139)),
    "hydrophobic_core": [3, 5, 7, 15, 18, 21, 29, 34, 36, 42, 46, 58, 60, 61, 64,
                         83, 85, 104, 106, 108, 118, 120, 122, 137, 139, 150, 152,
                         154, 164, 166, 167, 171, 179, 181, 183, 186, 205, 207, 209,
                         219, 221],
    "surface": [8, 10, 16, 19, 25, 27, 33, 38, 39, 41, 44, 48, 50, 75, 76, 77, 80,
                84, 87, 88, 97, 99, 101, 103, 110, 113, 114, 115, 123, 125, 128, 129,
                130, 131, 132, 134, 136, 140, 141, 142, 143, 144, 145, 157, 158, 159,
                162, 163, 165, 168, 169, 170, 172, 173, 174, 175, 176, 177, 178, 180,
                188, 189, 190, 191, 192, 193, 194, 196, 197, 198, 199, 200, 201, 206,
                208, 210, 211, 212, 213, 214, 215, 216, 217, 218, 220, 224, 225, 226,
                227, 228, 229, 230, 231, 232, 233, 234, 235, 236, 237],
    "c_terminal": list(range(225, 239)),
}
REGION_LIST = list(REGIONS.keys())

# BLOSUM62 matrix (20x20, order: A R N D C Q E G H I L K M F P S T W Y V)
BLOSUM62 = {}
_blosum_str = """
A  4 -1 -2 -2  0 -1 -1  0 -2 -1 -1 -1 -1 -2 -1  1  0 -3 -2  0
R -1  5  0 -2 -3  1  0 -2  0 -3 -2  2 -1 -3 -2 -1 -1 -3 -2 -3
N -2  0  6  1 -3  0  0  0  1 -3 -3  0 -2 -3 -2  1  0 -4 -2 -3
D -2 -2  1  6 -3  0  2 -1 -1 -3 -4 -1 -3 -3 -1  0 -1 -4 -3 -3
C  0 -3 -3 -3  9 -3 -4 -3 -3 -1 -1 -3 -1 -2 -3 -1 -1 -2 -2 -1
Q -1  1  0  0 -3  5  2 -2  0 -3 -2  1  0 -3 -1  0 -1 -2 -1 -2
E -1  0  0  2 -4  2  5 -2  0 -3 -3  1 -2 -3 -1  0 -1 -3 -2 -2
G  0 -2  0 -1 -3 -2 -2  6 -2 -4 -4 -2 -3 -3 -2  0 -2 -2 -3 -3
H -2  0  1 -1 -3  0  0 -2  8 -3 -3 -1 -2 -1 -2 -1 -2 -2  2 -3
I -1 -3 -3 -3 -1 -3 -3 -4 -3  4  2 -3  1  0 -3 -2 -1 -3 -1  3
L -1 -2 -3 -4 -1 -2 -3 -4 -3  2  4 -2  2  0 -3 -2 -1 -2 -1  1
K -1  2  0 -1 -3  1  1 -2 -1 -3 -2  5 -1 -3 -1  0 -1 -3 -2 -2
M -1 -1 -2 -3 -1  0 -2 -3 -2  1  2 -1  5  0 -2 -1 -1 -1 -1  1
F -2 -3 -3 -3 -2 -3 -3 -3 -1  0  0 -3  0  6 -4 -2 -2  1  3 -1
P -1 -2 -2 -1 -3 -1 -1 -2 -2 -3 -3 -1 -2 -4  7 -1 -1 -4 -3 -2
S  1 -1  1  0 -1  0  0  0 -1 -2 -2  0 -1 -2 -1  4  1 -3 -2 -2
T  0 -1  0 -1 -1 -1 -1 -2 -2 -1 -1 -1 -1 -2 -1  1  5 -2 -2  0
W -3 -3 -4 -4 -2 -2 -3 -2 -2 -3 -2 -3 -1  1 -4 -3 -2 11  2 -3
Y -2 -2 -2 -3 -2 -1 -2 -3  2 -1 -1 -2 -1  3 -3 -2 -2  2  7 -1
V  0 -3 -3 -3 -1 -2 -2 -3 -3  3  1 -2  1 -1 -2 -2  0 -3 -1  4
"""
_aa_order = "ARNDCQEGHILKMFPSTWYV"
for row in _blosum_str.strip().split("\n"):
    parts = row.strip().split()
    a1 = parts[0]
    for j, a2 in enumerate(_aa_order):
        BLOSUM62[(a1, a2)] = int(parts[j + 1])

# ── Feature computation (same logic as features.py) ──

def load_data():
    """Load shared data files."""
    conservation = pd.read_csv(CONSERVATION)
    cons_scores = conservation["conservation"].values
    with open(EPISTASIS) as f:
        epistasis_data = json.load(f)
    return cons_scores, epistasis_data.get("rules", [])


def parse_mutations(mutation_str):
    """Parse 'S72T:H231F' or 'WT' into dict {pos: new_aa}."""
    import re
    mutations = {}
    if isinstance(mutation_str, str) and mutation_str.strip().upper() != "WT":
        for part in str(mutation_str).split(":"):
            m = re.match(r"([A-Z])(\d+)([A-Z])", part.strip())
            if m:
                mutations[int(m.group(2))] = m.group(3).upper()
    return mutations


def compute_handcrafted_features(sequence, mutation_str, wt_seq, cons_scores, rules):
    """Compute 251-dim handcrafted feature vector (no ESM)."""
    feats = []

    # 1. Conservation features (238d): cons[i] if mutated else 0
    mut_set = parse_mutations(mutation_str)
    cons_feat = np.zeros(MAX_SEQ_LEN, dtype=np.float32)
    for pos in mut_set:
        idx = pos - 1
        if 0 <= idx < len(cons_scores):
            cons_feat[idx] = cons_scores[idx]
    feats.append(cons_feat)

    # 2. BLOSUM62 total (1d)
    blosum = 0.0
    for i in range(min(len(sequence), len(wt_seq))):
        if sequence[i] != wt_seq[i]:
            blosum += BLOSUM62.get((wt_seq[i], sequence[i]), -4)
    feats.append(np.array([blosum], dtype=np.float32))

    # 3. Epistasis bonus (1d)
    epistasis = 0.0
    for rule in rules:
        rpos, raa = rule["trigger_pos"], rule["trigger_aa"]
        cpos = rule["coupled_pos"]
        if rpos in mut_set and mut_set[rpos] == raa:
            coupled_aa = mut_set.get(cpos)
            if rule["type"] == "synergistic" and coupled_aa == rule.get("favored_aa"):
                epistasis += rule.get("enrichment", 1.0)
    feats.append(np.array([epistasis], dtype=np.float32))

    # 4. Number of mutations (1d)
    feats.append(np.array([len(mut_set)], dtype=np.float32))

    # 5. Region one-hot (5d)
    region_feat = np.zeros(len(REGION_LIST), dtype=np.float32)
    for pos in mut_set:
        for idx, rname in enumerate(REGION_LIST):
            if pos in REGIONS.get(rname, []):
                region_feat[idx] = 1.0
    feats.append(region_feat)

    # 6. Position diversity — Shannon entropy over 10 bins (1d)
    bins = np.zeros(10)
    for pos in mut_set:
        bin_idx = min((pos - 1) // 24, 9)
        bins[bin_idx] += 1
    total = bins.sum()
    entropy = 0.0
    if total > 0:
        for count in bins:
            if count > 0:
                p = count / total
                entropy -= p * np.log(p)
    feats.append(np.array([entropy], dtype=np.float32))

    # 7. sfGFP core preservation (1d) — always 1.0 for sfGFP-based candidates
    feats.append(np.array([1.0], dtype=np.float32))

    # 8. Mutation site conservation stats (3d): min/max/mean
    cons_at_muts = []
    for pos in mut_set:
        idx = pos - 1
        if 0 <= idx < len(cons_scores):
            cons_at_muts.append(cons_scores[idx])
    if cons_at_muts:
        feats.append(np.array([min(cons_at_muts), max(cons_at_muts), np.mean(cons_at_muts)], dtype=np.float32))
    else:
        feats.append(np.zeros(3, dtype=np.float32))

    return np.concatenate(feats)


def build_full_features(sequences, mutation_strs, wt_seq, cons_scores, rules):
    """Build 1531-dim features: ESM=0 + 251 handcrafted."""
    n = len(sequences)
    X = np.zeros((n, EMBED_DIM + sum([
        MAX_SEQ_LEN, 1, 1, 1, len(REGION_LIST), 1, 1, 3
    ])), dtype=np.float32)

    for i in range(n):
        hf = compute_handcrafted_features(
            sequences[i], mutation_strs[i], wt_seq, cons_scores, rules
        )
        X[i, EMBED_DIM:] = hf

    return X


def predict_with_models(X, models, meta):
    """Run ensemble prediction."""
    p_rf = models["rf"].predict(X)
    p_xgb = models["xgb"].predict(X)
    p_lgb = models["lgb"].predict(X)

    if meta is not None:
        meta_X = np.column_stack([p_rf, p_xgb, p_lgb])
        pred_ens = meta.predict(meta_X)
    else:
        pred_ens = (p_rf + p_xgb + p_lgb) / 3.0

    return p_rf, p_xgb, p_lgb, pred_ens


def calibrate_with_scored(unscored_pred, scored_df, strategy):
    """Calibrate ESM-less predictions to roughly match real composite_score scale.

    Since we're missing ESM embeddings, predictions have a systematic bias.
    We rescale to match the mean/std of real composite_scores for each strategy.
    """
    strat_scored = scored_df[scored_df["source"] == f"strategy_{strategy}"]
    if len(strat_scored) == 0:
        return unscored_pred

    target_mean = strat_scored["composite_score"].mean()
    target_std = strat_scored["composite_score"].std()

    pred_mean = unscored_pred.mean()
    pred_std = unscored_pred.std()

    if pred_std > 1e-6:
        calibrated = (unscored_pred - pred_mean) / pred_std * target_std + target_mean
    else:
        calibrated = np.full_like(unscored_pred, target_mean)

    return calibrated


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("策略B 虚拟筛选 — ML模型全量候选评分")
    print("=" * 70)

    # ── Load models ──
    print("\n[1/6] 加载ML模型...")
    models = {}
    for name in ["rf", "xgb", "lgb"]:
        path = os.path.join(MODELS_DIR, f"{name}_model.pkl")
        with open(path, "rb") as f:
            models[name] = pickle.load(f)
        print(f"  {name}: loaded")
    meta_path = os.path.join(MODELS_DIR, "meta_model.pkl")
    meta = None
    if os.path.exists(meta_path):
        with open(meta_path, "rb") as f:
            meta = pickle.load(f)
        print("  meta (stacking): loaded")

    # ── Load data ──
    print("\n[2/6] 加载候选池和特征数据...")
    cons_scores, rules = load_data()
    scored = pd.read_csv(SCORED)
    existing = pd.read_csv(EXISTING_6)
    existing_ids = set(existing["seq_id"].tolist())
    print(f"  已有评分: {len(scored)} 条")
    print(f"  当前6条: {existing_ids}")

    # Load candidates
    a_pool = pd.read_csv(A_CAND)
    d_pool = pd.read_csv(D_CAND)
    c_pool = pd.read_csv(C_CAND)

    # Add seq_id for C
    if "seq_id" not in c_pool.columns:
        c_pool["seq_id"] = [f"SC_C_{i:04d}" for i in range(len(c_pool))]

    # Merge FoldX ddG
    a_foldx = pd.read_csv(A_FOLDX)[["seq_id", "ddG_kcal_mol"]]
    d_foldx = pd.read_csv(D_FOLDX)
    if "ddG_kcal_mol" in d_foldx.columns:
        d_foldx = d_foldx[["seq_id", "ddG_kcal_mol"]]
    else:
        d_foldx = pd.DataFrame(columns=["seq_id", "ddG_kcal_mol"])

    a_pool = a_pool.merge(a_foldx, on="seq_id", how="left")
    d_pool = d_pool.merge(d_foldx, on="seq_id", how="left")

    print(f"  A池: {len(a_pool)} | D池: {len(d_pool)} | C池: {len(c_pool)}")

    # ── Build features for ALL candidates ──
    print("\n[3/6] 构建手写特征 (CPU, 无ESM)...")
    wt = SFGFP_WT

    all_pools = {"A": a_pool, "D": d_pool, "C": c_pool}
    all_results = {}

    for strategy, pool in all_pools.items():
        seqs = pool["sequence"].tolist()
        muts = pool["mutation_str"].tolist()

        print(f"  策略{strategy}: {len(seqs)} 条 → featurizing...")
        X = build_full_features(seqs, muts, wt, cons_scores, rules)

        # Predict
        p_rf, p_xgb, p_lgb, pred_ens = predict_with_models(X, models, meta)

        # Calibrate to match real composite_score scale
        calibrated = calibrate_with_scored(pred_ens, scored, strategy)

        pool = pool.copy()
        pool["ml_brightness_raw"] = pred_ens
        pool["ml_brightness"] = calibrated
        pool["ml_brightness_rf"] = p_rf
        pool["ml_brightness_xgb"] = p_xgb
        pool["ml_brightness_lgb"] = p_lgb

        # Merge existing composite_score where available
        scored_lookup = scored.set_index("seq_id")[["composite_score", "pred_brightness"]]
        pool["composite_score_existing"] = pool["seq_id"].map(
            scored_lookup["composite_score"]
        )
        pool["pred_brightness_existing"] = pool["seq_id"].map(
            scored_lookup["pred_brightness"]
        )

        # Best available brightness: prefer existing, fallback to calibrated
        pool["best_brightness"] = pool["composite_score_existing"].fillna(
            pool["ml_brightness"]
        )

        # Composite score with ddG penalty
        ddg = pool["ddG_kcal_mol"].fillna(2.0)
        pool["composite_virtual"] = pool["best_brightness"] / np.maximum(ddg, 1.0)

        # For C (no ddG), use mpnn_score as stability proxy
        if strategy == "C" and "mpnn_score" in pool.columns:
            mpnn = pool["mpnn_score"].fillna(0.5)
            pool["stability_proxy"] = mpnn
            pool["composite_virtual"] = pool["best_brightness"] * mpnn

        # Sort by composite_virtual
        pool = pool.sort_values("composite_virtual", ascending=False)

        all_results[strategy] = pool

        # Print summary
        n_existing = pool["composite_score_existing"].notna().sum()
        print(f"    已有评分: {n_existing}/{len(pool)}")
        print(f"    composite_virtual 范围: [{pool['composite_virtual'].min():.3f}, "
              f"{pool['composite_virtual'].max():.3f}]")
        if "ddG_kcal_mol" in pool.columns:
            valid_ddg = pool["ddG_kcal_mol"].notna()
            if valid_ddg.any():
                print(f"    ddG 范围: [{pool.loc[valid_ddg,'ddG_kcal_mol'].min():.3f}, "
                      f"{pool.loc[valid_ddg,'ddG_kcal_mol'].max():.3f}]")

    # ── Per-strategy top candidates ──
    print("\n[4/6] 各策略Top候选 (排除已选的6条)...")
    recommendations = []

    for strategy, pool in all_results.items():
        # Exclude already-selected
        new = pool[~pool["seq_id"].isin(existing_ids)]

        # Apply basic filters
        if strategy in ("A", "D"):
            ddg_col = "ddG_kcal_mol"
            if ddg_col in new.columns:
                # Relax ddG threshold to 5.0 for virtual screen (wider net)
                new = new[new[ddg_col].fillna(999) < 5.0]

        # Top 10 by composite_virtual
        top10 = new.head(10)

        out_path = os.path.join(OUT_DIR, f"virtual_screen_{strategy}_top10.csv")
        cols = ["seq_id", "mutation_str", "num_mutations", "best_brightness",
                "composite_virtual"]
        if "ddG_kcal_mol" in top10.columns:
            cols.insert(4, "ddG_kcal_mol")
        if "mpnn_score" in top10.columns:
            cols.insert(4, "mpnn_score")
        if "consensus_score" in top10.columns:
            cols.insert(4, "consensus_score")

        top10[cols].to_csv(out_path, index=False)
        print(f"\n  策略{strategy} Top 10 → {out_path}")
        for _, row in top10.head(5).iterrows():
            sid = row["seq_id"]
            mut = str(row["mutation_str"])[:60]
            cv = row["composite_virtual"]
            ddg_str = f"ddG={row.get('ddG_kcal_mol', 'N/A'):.2f}" if pd.notna(row.get('ddG_kcal_mol')) else ""
            mpnn_str = f"mpnn={row.get('mpnn_score', 'N/A'):.3f}" if pd.notna(row.get('mpnn_score')) else ""
            extra = ddg_str + " " + mpnn_str
            print(f"    {sid}: cv={cv:.3f} | {mut} | {extra}")

        # Save recommendation for summary
        for _, row in top10.head(3).iterrows():
            recommendations.append({
                "strategy": strategy,
                "seq_id": row["seq_id"],
                "mutation_str": row["mutation_str"],
                "num_mutations": row["num_mutations"],
                "composite_virtual": row["composite_virtual"],
                "ddG_kcal_mol": row.get("ddG_kcal_mol", None),
                "mpnn_score": row.get("mpnn_score", None),
                "consensus_score": row.get("consensus_score", None),
            })

    # ── Cross-strategy comparison ──
    print("\n[5/6] 跨策略对比分析...")
    # Normalize composite_virtual within each strategy for cross-comparison
    for r in recommendations:
        strat_pool = all_results[r["strategy"]]
        mean_cv = strat_pool["composite_virtual"].mean()
        std_cv = strat_pool["composite_virtual"].std()
        r["cv_zscore"] = (r["composite_virtual"] - mean_cv) / std_cv if std_cv > 0 else 0

    rec_df = pd.DataFrame(recommendations)
    rec_df = rec_df.sort_values("cv_zscore", ascending=False)
    summary_path = os.path.join(OUT_DIR, "virtual_screen_summary.csv")
    rec_df.to_csv(summary_path, index=False)
    print(f"  汇总推荐 → {summary_path}")
    print(f"\n  跨策略Top推荐 (按策略内Z-score排序):")
    for _, row in rec_df.head(10).iterrows():
        print(f"    [{row['strategy']}] {row['seq_id']}: z={row['cv_zscore']:.2f} "
              f"cv={row['composite_virtual']:.3f} | {str(row['mutation_str'])[:50]}")

    # ── Compare with current 6 ──
    print("\n[6/6] 与当前6条对比...")
    print(f"\n  {'当前6条':─^60}")
    for _, row in existing.iterrows():
        sid = row["seq_id"]
        strat = row["source_strategy"]
        reason = row.get("selection_reason", "")
        cv = row.get("composite_score", "N/A")
        ddg = row.get("ddG_kcal_mol", "N/A")
        print(f"  [{strat}] {sid}: brightness={cv} ddG={ddg} | {reason}")

    print(f"\n  {'策略B ML推荐备选':─^60}")
    # Find candidates that are DIFFERENT from current 6 in mutation sites
    current_mutations = set()
    for _, row in existing.iterrows():
        muts = parse_mutations(str(row.get("mutation_str", "")))
        current_mutations.update(muts.keys())

    for _, row in rec_df.iterrows():
        sid = row["seq_id"]
        strat = row["strategy"]
        mut_str = row["mutation_str"]
        muts = parse_mutations(str(mut_str))
        new_sites = set(muts.keys()) - current_mutations
        diversity_tag = f"[新位点:{new_sites}]" if new_sites else "[位点重复]"
        print(f"  [{strat}] {sid}: z={row['cv_zscore']:.2f} cv={row['composite_virtual']:.3f} "
              f"| {str(mut_str)[:50]}... {diversity_tag}")

    print(f"\n{'=' * 70}")
    print("虚拟筛选完成。输出目录: " + OUT_DIR)
    print("=" * 70)


if __name__ == "__main__":
    main()
