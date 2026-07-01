# -*- coding: utf-8 -*-
"""候选序列 ESM-2 650M 嵌入 + 打分（服务器端一步完成）"""

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd
import torch

PROJECT_ROOT = "/data2/fenghaohui/gfp_strategy_B"
RESULTS = os.path.join(PROJECT_ROOT, "results")
MODELS = os.path.join(RESULTS, "models")

# ── 加载候选 ──
dfs = []
for fname in ["strategy_A_passed.csv", "strategy_D_all_candidates.csv"]:
    fpath = os.path.join(RESULTS, fname)
    if os.path.exists(fpath):
        df = pd.read_csv(fpath)
        if "source" not in df.columns:
            df["source"] = "strategy_A" if "strategy_A" in fname else "strategy_D"
        print(f"Loaded {len(df)} from {fname}")
        dfs.append(df)

cand = pd.concat(dfs, ignore_index=True)
cand = cand.drop_duplicates(subset="sequence", keep="first")
seqs = cand["sequence"].tolist()
print(f"Total candidates: {len(seqs)}")

# ── ESM-2 650M 嵌入 ──
import esm

device = torch.device("cuda")
model, alphabet = esm.pretrained.load_model_and_alphabet("esm2_t33_650M_UR50D")
model = model.to(device).eval()
batch_converter = alphabet.get_batch_converter()

embeddings = []
bs = 8
for i in range(0, len(seqs), bs):
    batch = seqs[i : i + bs]
    data = [(f"s{j}", s) for j, s in enumerate(batch)]
    _, _, tokens = batch_converter(data)
    tokens = tokens.to(device)
    with torch.no_grad():
        r = model(tokens, repr_layers=[model.num_layers])
    t = r["representations"][model.num_layers]
    for j, s in enumerate(batch):
        embeddings.append(t[j, 1 : len(s) + 1, :].mean(dim=0).cpu().numpy())
    if (i // bs + 1) % 20 == 0:
        print(f"  {i + len(batch)}/{len(seqs)} embedded")

embeddings = np.array(embeddings, dtype=np.float32)
print(f"Embeddings: {embeddings.shape}")
np.savez_compressed(os.path.join(RESULTS, "candidate_embeddings.npz"), embeddings=embeddings)
print("Embeddings saved.")

# ── 特征化（复用本地 features.py 逻辑） ──
sys.path.insert(0, os.path.join(PROJECT_ROOT, "code"))
from features import featurize_batch, _load_conservation, _load_epistasis_rules, _get_sfgfp

wt_seq = _get_sfgfp()
mutation_strs = cand["mutation_str"].tolist() if "mutation_str" in cand.columns else ["WT"] * len(seqs)

print("Featurizing...")
X = featurize_batch(seqs, mutation_strs, wt_seq, embeddings=embeddings)
print(f"Features: {X.shape}")

# ── 加载模型 + 预测 ──
model_names = ["rf", "xgb", "lgb"]
models = {}
for name in model_names:
    path = os.path.join(MODELS, f"{name}_model.pkl")
    if os.path.exists(path):
        with open(path, "rb") as f:
            models[name] = pickle.load(f)
        print(f"Loaded {name}")

meta_path = os.path.join(MODELS, "meta_model.pkl")
if os.path.exists(meta_path):
    with open(meta_path, "rb") as f:
        meta = pickle.load(f)
    print("Loaded meta-model")

# 预测
p_rf = models["rf"].predict(X)
p_xgb = models["xgb"].predict(X)
p_lgb = models["lgb"].predict(X)

if meta is not None:
    meta_X = np.column_stack([p_rf, p_xgb, p_lgb])
    pred_ens = meta.predict(meta_X)
else:
    pred_ens = (p_rf + p_xgb + p_lgb) / 3.0

print(f"Predictions: range [{pred_ens.min():.3f}, {pred_ens.max():.3f}], mean {pred_ens.mean():.3f}")

# ── 合并 FoldX ddG + 综合评分 ──
# 策略A
foldx_a = os.path.join(RESULTS, "strategy_A_foldx_results.csv")
if os.path.exists(foldx_a):
    fa = pd.read_csv(foldx_a)
    if "ddG_kcal_mol" in fa.columns:
        ddg_map = fa.set_index("seq_id")["ddG_kcal_mol"].to_dict()
        cand["ddG_kcal_mol"] = cand["seq_id"].map(ddg_map)

# 策略D
foldx_d = os.path.join(RESULTS, "strategy_D_foldx_results.csv")
if os.path.exists(foldx_d):
    fd = pd.read_csv(foldx_d)
    if "ddG_kcal_mol" in fd.columns:
        ddg_map = fd.set_index("seq_id")["ddG_kcal_mol"].to_dict()
        cand_d_mask = cand["source"] == "strategy_D"
        for idx in cand[cand_d_mask].index:
            sid = cand.at[idx, "seq_id"]
            if sid in ddg_map:
                cand.at[idx, "ddG_kcal_mol"] = ddg_map[sid]

ddg = cand["ddG_kcal_mol"].fillna(2.0).values
cand["pred_brightness"] = pred_ens
cand["pred_brightness_rf"] = p_rf
cand["pred_brightness_xgb"] = p_xgb
cand["pred_brightness_lgb"] = p_lgb
cand["composite_score"] = pred_ens / np.maximum(ddg, 1.0)

cand = cand.sort_values("composite_score", ascending=False)

# ── 保存 ──
out_path = os.path.join(RESULTS, "candidate_scores.csv")
cand.to_csv(out_path, index=False)
print(f"Candidate scores saved → {out_path}")

# ── Top 20 ──
print("\n" + "=" * 70)
print("TOP 20 CANDIDATES")
print("=" * 70)
cols = ["seq_id", "source", "num_mutations", "mutation_str",
        "pred_brightness", "ddG_kcal_mol", "composite_score"]
print(cand.head(20)[cols].to_string(index=False))
