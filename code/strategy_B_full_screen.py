#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
策略B全量虚拟筛选 — 服务器版 (GPU + ESM-2 650M)
==============================================
在L40服务器上运行，使用完整的ESM-2 650M嵌入 + 手写特征 + 已训练ML模型，
对A/D/C全量候选池打分，找出各策略ML视角下的最佳序列。

用法 (服务器端):
  conda activate gfp_design
  python strategy_B_full_screen.py

输出:
  results/strategy_B/full_screen_A_ranked.csv   (A策略全量排序)
  results/strategy_B/full_screen_D_ranked.csv   (D策略全量排序)
  results/strategy_B/full_screen_C_ranked.csv   (C策略全量排序)
  results/strategy_B/full_screen_summary.csv    (跨策略推荐汇总)
"""

import json, os, pickle, sys, re as re_mod
import numpy as np
import pandas as pd
import torch

# ── Paths (server) ──
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(PROJECT_ROOT, "results")
STRAT_B = os.path.join(RESULTS, "strategy_B")
MODELS_DIR = os.path.join(STRAT_B, "models")
OUT_DIR = os.path.join(STRAT_B, "full_screen")
os.makedirs(OUT_DIR, exist_ok=True)

# Input paths
A_CAND = os.path.join(RESULTS, "strategy_A_candidates.csv")
D_CAND = os.path.join(RESULTS, "strategy_D_all_candidates.csv")
C_CAND = os.path.join(RESULTS, "strategy_C", "strategy_C_candidates.csv")
A_FOLDX = os.path.join(RESULTS, "strategy_A_foldx_results.csv")
D_FOLDX_IDX = os.path.join(RESULTS, "strategy_D_foldx_input", "foldx_index.csv")
D_FOLDX_RES = os.path.join(RESULTS, "strategy_D_foldx_results.csv")
CONSERVATION = os.path.join(RESULTS, "strategy_D_conservation_profile.csv")
EPISTASIS = os.path.join(RESULTS, "strategy_D_epistasis_rules.json")
EXISTING_6 = os.path.join(RESULTS, "funnel_phase5_final_6.csv")

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
    "chromophore": [65,66,67,68,69,70,94,95,96,146,147,148,202,203,204,205,222],
    "beta_core": list(range(1,14))+list(range(19,30))+list(range(40,51))+
                 list(range(80,91))+list(range(106,117))+list(range(128,139)),
    "hydrophobic_core": [3,5,7,15,18,21,29,34,36,42,46,58,60,61,64,83,85,104,106,
                         108,118,120,122,137,139,150,152,154,164,166,167,171,179,
                         181,183,186,205,207,209,219,221],
    "surface": [8,10,16,19,25,27,33,38,39,41,44,48,50,75,76,77,80,84,87,88,97,99,
                101,103,110,113,114,115,123,125,128,129,130,131,132,134,136,140,
                141,142,143,144,145,157,158,159,162,163,165,168,169,170,172,173,
                174,175,176,177,178,180,188,189,190,191,192,193,194,196,197,198,
                199,200,201,206,208,210,211,212,213,214,215,216,217,218,220,224,
                225,226,227,228,229,230,231,232,233,234,235,236,237],
    "c_terminal": list(range(225,239)),
}
REGION_LIST = list(REGIONS.keys())

# BLOSUM62
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
        BLOSUM62[(a1, a2)] = int(parts[j+1])


# ═══════════════════════════════════════════════════════════════
# Feature computation
# ═══════════════════════════════════════════════════════════════

def parse_mutations(mutation_str):
    mutations = {}
    if isinstance(mutation_str, str) and mutation_str.strip().upper() != "WT":
        for part in str(mutation_str).split(":"):
            m = re_mod.match(r"([A-Z])(\d+)([A-Z])", part.strip())
            if m:
                mutations[int(m.group(2))] = m.group(3).upper()
    return mutations


def compute_handcrafted_features(sequence, mutation_str, wt_seq, cons_scores, rules):
    feats = []
    mut_set = parse_mutations(mutation_str)

    # 1. Conservation (238d)
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

    # 6. Position diversity (1d)
    bins = np.zeros(10)
    for pos in mut_set:
        bin_idx = min((pos-1)//24, 9)
        bins[bin_idx] += 1
    total = bins.sum()
    entropy = 0.0
    if total > 0:
        for count in bins:
            if count > 0:
                p = count/total
                entropy -= p*np.log(p)
    feats.append(np.array([entropy], dtype=np.float32))

    # 7. sfGFP core preservation (1d)
    feats.append(np.array([1.0], dtype=np.float32))

    # 8. Mutation site conservation stats (3d)
    cons_at_muts = []
    for pos in mut_set:
        idx = pos-1
        if 0 <= idx < len(cons_scores):
            cons_at_muts.append(cons_scores[idx])
    if cons_at_muts:
        feats.append(np.array([min(cons_at_muts), max(cons_at_muts), np.mean(cons_at_muts)], dtype=np.float32))
    else:
        feats.append(np.zeros(3, dtype=np.float32))

    return np.concatenate(feats)


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print("="*70)
    print("策略B 全量虚拟筛选 — 服务器版 (ESM-2 650M GPU)")
    print("="*70)

    # ── 1. Load models ──
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

    # ── 2. Load data ──
    print("\n[2/6] 加载候选池和特征数据...")
    cons_df = pd.read_csv(CONSERVATION)
    cons_scores = cons_df["conservation"].values
    with open(EPISTASIS) as f:
        epi_data = json.load(f)
    rules = epi_data.get("rules", [])

    existing = pd.read_csv(EXISTING_6)
    existing_ids = set(existing["seq_id"].tolist())
    print(f"  当前6条: {existing_ids}")

    # Load candidates
    a_pool = pd.read_csv(A_CAND)
    d_pool = pd.read_csv(D_CAND)
    c_pool = pd.read_csv(C_CAND)
    if "seq_id" not in c_pool.columns:
        c_pool["seq_id"] = [f"SC_C_{i:04d}" for i in range(len(c_pool))]

    # Merge FoldX ddG
    a_fx = pd.read_csv(A_FOLDX)[["seq_id", "ddG_kcal_mol"]]
    a_pool = a_pool.merge(a_fx, on="seq_id", how="left")

    d_fx_idx = pd.read_csv(D_FOLDX_IDX)
    d_fx_res = pd.read_csv(D_FOLDX_RES)
    d_fx = d_fx_idx.merge(d_fx_res, on="seq_id", how="left")
    mut2ddg = {}
    for _, r in d_fx.iterrows():
        if pd.notna(r["ddG_kcal_mol"]) and pd.notna(r["mutations"]):
            mut2ddg[str(r["mutations"]).strip()] = r["ddG_kcal_mol"]
    d_pool["ddG_kcal_mol"] = d_pool["mutation_str"].map(mut2ddg)

    print(f"  A池: {len(a_pool)} | D池: {len(d_pool)} | C池: {len(c_pool)}")

    # ── 3. ESM-2 650M embeddings ──
    print("\n[3/6] 提取ESM-2 650M嵌入 (GPU)...")
    import esm

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"  Device: {device}")
    model, alphabet = esm.pretrained.load_model_and_alphabet("esm2_t33_650M_UR50D")
    model = model.to(device).eval()
    batch_converter = alphabet.get_batch_converter()

    def extract_embeddings(sequences, label_prefix="s", batch_size=8):
        """Extract mean-pooled ESM-2 embeddings for a list of sequences."""
        embeddings = []
        n = len(sequences)
        for i in range(0, n, batch_size):
            batch = sequences[i:i+batch_size]
            data = [(f"{label_prefix}{j}", s) for j, s in enumerate(batch)]
            _, _, tokens = batch_converter(data)
            tokens = tokens.to(device)
            with torch.no_grad():
                r = model(tokens, repr_layers=[model.num_layers])
            t = r["representations"][model.num_layers]
            for j, s in enumerate(batch):
                embeddings.append(t[j, 1:len(s)+1, :].mean(dim=0).cpu().numpy())
            if (i//batch_size+1) % 50 == 0:
                print(f"    {i+len(batch)}/{n} embedded")
        return np.array(embeddings, dtype=np.float32)

    wt = SFGFP_WT
    all_pools = {"A": a_pool, "D": d_pool, "C": c_pool}
    all_results = {}

    for strategy, pool in all_pools.items():
        seqs = pool["sequence"].tolist()
        muts = pool["mutation_str"].tolist()
        n = len(seqs)
        print(f"\n  策略{strategy}: {n}条 → ESM嵌入...")

        # Extract embeddings
        emb = extract_embeddings(seqs, label_prefix=f"{strategy}_")
        print(f"    Embeddings: {emb.shape}")

        # Build full features
        print(f"    构建完整特征...")
        X = np.zeros((n, EMBED_DIM + 251), dtype=np.float32)
        X[:, :EMBED_DIM] = emb
        for i in range(n):
            hf = compute_handcrafted_features(seqs[i], muts[i], wt, cons_scores, rules)
            X[i, EMBED_DIM:] = hf

        # Predict
        print(f"    ML推理...")
        p_rf = models["rf"].predict(X)
        p_xgb = models["xgb"].predict(X)
        p_lgb = models["lgb"].predict(X)
        if meta is not None:
            meta_X = np.column_stack([p_rf, p_xgb, p_lgb])
            pred_ens = meta.predict(meta_X)
        else:
            pred_ens = (p_rf + p_xgb + p_lgb) / 3.0

        pool = pool.copy()
        pool["ml_brightness"] = pred_ens
        pool["ml_brightness_rf"] = p_rf
        pool["ml_brightness_xgb"] = p_xgb
        pool["ml_brightness_lgb"] = p_lgb

        # Composite score
        if strategy == "C":
            mpnn = pool["mpnn_score"].fillna(0.5)
            pool["composite_score"] = pred_ens * mpnn
        else:
            ddg = pool["ddG_kcal_mol"].fillna(2.0)
            pool["composite_score"] = pred_ens / np.maximum(ddg, 1.0)

        pool = pool.sort_values("composite_score", ascending=False)
        all_results[strategy] = pool

        print(f"    ML brightness range: [{pred_ens.min():.3f}, {pred_ens.max():.3f}]")
        print(f"    composite_score range: [{pool['composite_score'].min():.3f}, {pool['composite_score'].max():.3f}]")

    # ── 4. Save per-strategy rankings ──
    print("\n[4/6] 保存各策略排序结果...")
    save_cols = ["seq_id", "sequence", "mutation_str", "num_mutations",
                 "ml_brightness", "composite_score", "ddG_kcal_mol"]
    if "consensus_score" in d_pool.columns:
        save_cols.append("consensus_score")
    if "mpnn_score" in c_pool.columns:
        save_cols.append("mpnn_score")

    for strategy, pool in all_results.items():
        cols = [c for c in save_cols if c in pool.columns]
        out_path = os.path.join(OUT_DIR, f"full_screen_{strategy}_ranked.csv")
        pool[cols].to_csv(out_path, index=False)
        print(f"  {strategy}: {out_path}")

    # ── 5. Cross-strategy recommendations ──
    print("\n[5/6] 跨策略推荐分析...")
    recommendations = []

    for strategy, pool in all_results.items():
        new = pool[~pool["seq_id"].isin(existing_ids)]

        if strategy in ("A", "D") and "ddG_kcal_mol" in new.columns:
            new = new[new["ddG_kcal_mol"].fillna(999) < 3.0]

        for _, row in new.head(5).iterrows():
            recommendations.append({
                "strategy": strategy,
                "seq_id": row["seq_id"],
                "mutation_str": row["mutation_str"],
                "num_mutations": row["num_mutations"],
                "ml_brightness": row["ml_brightness"],
                "composite_score": row["composite_score"],
                "ddG_kcal_mol": row.get("ddG_kcal_mol", None),
                "consensus_score": row.get("consensus_score", None),
                "mpnn_score": row.get("mpnn_score", None),
            })

    rec_df = pd.DataFrame(recommendations)
    summary_path = os.path.join(OUT_DIR, "full_screen_summary.csv")
    rec_df.to_csv(summary_path, index=False)
    print(f"  汇总: {summary_path}")

    # ── 6. Comparison with current 6 ──
    print("\n[6/6] 与当前6条对比...")
    print(f"\n  {'当前6条':─^60}")
    for _, row in existing.iterrows():
        sid = row["seq_id"]
        strat = row["source_strategy"]
        reason = row.get("selection_reason", "")
        cv = row.get("composite_score", "N/A")
        ddg = row.get("ddG_kcal_mol", "N/A")
        print(f"  [{strat}] {sid}: brightness={cv} ddG={ddg} | {reason}")

    print(f"\n  {'策略B推荐备选 (服务器ESM完整特征)':─^60}")
    for _, row in rec_df.iterrows():
        sid = row["seq_id"]
        strat = row["strategy"]
        cv = row["composite_score"]
        ddg = row.get("ddG_kcal_mol", "N/A")
        ddg_s = f"ddG={ddg:.2f}" if pd.notna(ddg) else ""
        cons = row.get("consensus_score", None)
        cons_s = f"cons={cons:.3f}" if pd.notna(cons) else ""
        mpnn = row.get("mpnn_score", None)
        mpnn_s = f"mpnn={mpnn:.3f}" if pd.notna(mpnn) else ""
        extra = " ".join(filter(None, [ddg_s, cons_s, mpnn_s]))
        print(f"  [{strat}] {sid}: cv={cv:.3f} {extra} | {str(row['mutation_str'])[:50]}")

    print(f"\n{'='*70}")
    print("全量虚拟筛选完成。输出目录: " + OUT_DIR)
    print("="*70)


if __name__ == "__main__":
    main()
