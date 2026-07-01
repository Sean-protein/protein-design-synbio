# -*- coding: utf-8 -*-
"""
策略C v2 — ML亮度预测 + 与A/D对比
==================================
依赖: ESM-2 650M + 策略B特征工程 + 策略B训练好的模型
"""
import os, sys, pickle, time
import numpy as np, pandas as pd, torch

# ── 路径 ──
SRV = "/data2/fenghaohui"
SYS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = SRV if os.path.exists(SRV) else SYS

B_DIR  = os.path.join(ROOT, "gfp_strategy_B")
B_CODE = os.path.join(B_DIR, "code")
B_MODELS = os.path.join(B_DIR, "results", "models")

C_V2_CSV = os.path.join(ROOT, "results", "strategy_C", "v2", "strategy_C_v2_candidates.csv")
A_CSV    = os.path.join(ROOT, "results", "strategy_A_passed.csv")
D_CSV    = os.path.join(ROOT, "results", "strategy_D_foldx_results.csv")
B_SCORES = os.path.join(ROOT, "results", "strategy_B", "candidate_scores.csv")

OUT_CSV  = os.path.join(ROOT, "results", "strategy_C", "v2", "strategy_C_v2_scored.csv")

sys.path.insert(0, B_CODE)

# ═══════════════════════════════════════════════════════════════
# Step 1: 加载数据
# ═══════════════════════════════════════════════════════════════
print("=" * 60)
print("Strategy C v2 — ML Brightness Scoring & Cross-Strategy Comparison")
print("=" * 60)

c_v2 = pd.read_csv(C_V2_CSV)
print("\n[1] Loaded C_v2: {} candidates".format(len(c_v2)))

# 只取突变>0的非WT序列做评分
non_wt = c_v2[c_v2.num_mutations > 0].copy()
print("    Non-WT: {} (will score these)".format(len(non_wt)))

# ═══════════════════════════════════════════════════════════════
# Step 2: ESM-2 650M 嵌入
# ═══════════════════════════════════════════════════════════════
print("\n[2] Loading ESM-2 650M...")
import esm
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
model, alphabet = esm.pretrained.load_model_and_alphabet("esm2_t33_650M_UR50D")
model = model.to(device).eval()
batch_converter = alphabet.get_batch_converter()
print("    Device: {}".format(device))

seqs = non_wt["sequence"].tolist()
embeddings = []
bs = 4
t0 = time.time()
for i in range(0, len(seqs), bs):
    batch = seqs[i:i+bs]
    data = [(str(j), s) for j, s in enumerate(batch)]
    _, _, tokens = batch_converter(data)
    tokens = tokens.to(device)
    with torch.no_grad():
        r = model(tokens, repr_layers=[model.num_layers])
    reps = r["representations"][model.num_layers]
    for j in range(len(batch)):
        emb = reps[j, 1:len(batch[j])+1, :].mean(dim=0).cpu().numpy()
        embeddings.append(emb.astype(np.float32))
    if (i//bs+1) % 50 == 0:
        print("    {}/{} ({:.0f}s)".format(i+len(batch), len(seqs), time.time()-t0))
embeddings = np.array(embeddings)
print("    Done: {} embeddings in {:.0f}s".format(embeddings.shape, time.time()-t0))

# ═══════════════════════════════════════════════════════════════
# Step 3: 特征工程 + 模型预测
# ═══════════════════════════════════════════════════════════════
print("\n[3] Feature engineering + ML prediction...")
from features import featurize_batch, _get_sfgfp

wt = _get_sfgfp()
mut_strs = non_wt["mutation_str"].tolist()
X = featurize_batch(seqs, mut_strs, wt, embeddings=embeddings)
print("    Features: {}".format(X.shape))

# 加载模型
models = {}
for name in ["rf", "xgb", "lgb"]:
    with open(os.path.join(B_MODELS, "{}_model.pkl".format(name)), "rb") as f:
        models[name] = pickle.load(f)
with open(os.path.join(B_MODELS, "meta_model.pkl"), "rb") as f:
    meta = pickle.load(f)

p_rf  = models["rf"].predict(X)
p_xgb = models["xgb"].predict(X)
p_lgb = models["lgb"].predict(X)
p_ens = meta.predict(np.column_stack([p_rf, p_xgb, p_lgb]))

non_wt["pred_brightness"] = p_ens
non_wt["pred_brightness_rf"]  = p_rf
non_wt["pred_brightness_xgb"] = p_xgb
non_wt["pred_brightness_lgb"] = p_lgb

# WT的亮度（单独处理）
c_v2.loc[c_v2.num_mutations == 0, "pred_brightness"] = np.nan  # WT不评分

# 合并
out = c_v2.copy()
out.to_csv(OUT_CSV, index=False)
print("    Saved -> {}".format(OUT_CSV))

# ═══════════════════════════════════════════════════════════════
# Step 4: 统计
# ═══════════════════════════════════════════════════════════════
print("\n[4] C_v2 Brightness Statistics:")
b = non_wt["pred_brightness"]
print("    Mean:  {:.3f}".format(b.mean()))
print("    Median: {:.3f}".format(b.median()))
print("    Std:   {:.3f}".format(b.std()))
print("    Min:   {:.3f}".format(b.min()))
print("    Max:   {:.3f}".format(b.max()))
print("    > 1.0: {}/{} ({:.0f}%)".format((b > 1.0).sum(), len(b), (b > 1.0).sum()/len(b)*100))
print("    > 1.5: {}/{} ({:.0f}%)".format((b > 1.5).sum(), len(b), (b > 1.5).sum()/len(b)*100))

# ═══════════════════════════════════════════════════════════════
# Step 5: 与 A/D 对比
# ═══════════════════════════════════════════════════════════════
print("\n[5] Cross-strategy brightness comparison:")

comparisons = {}
for label, csv_path in [("A", A_CSV), ("D", D_CSV), ("B_scored", B_SCORES)]:
    if os.path.exists(csv_path):
        adf = pd.read_csv(csv_path)
        bright_col = None
        for c in adf.columns:
            if "pred_brightness" in c.lower() and "rf" not in c and "xgb" not in c and "lgb" not in c:
                bright_col = c
                break
        if bright_col is None:
            for c in ["pred_brightness", "brightness", "composite_score"]:
                if c in adf.columns:
                    bright_col = c; break
        if bright_col:
            vals = adf[bright_col].dropna()
            comparisons[label] = {
                "n": len(adf), "mean": vals.mean(), "median": vals.median(),
                "std": vals.std(), "min": vals.min(), "max": vals.max(),
                "above_1": (vals > 1.0).sum(), "above_1pct": (vals > 1.0).sum()/len(vals)*100
            }

# 添加C_v2
comparisons["C_v2"] = {
    "n": len(non_wt), "mean": b.mean(), "median": b.median(),
    "std": b.std(), "min": b.min(), "max": b.max(),
    "above_1": (b > 1.0).sum(), "above_1pct": (b > 1.0).sum()/len(b)*100
}

print("    {:>8} {:>6} {:>8} {:>8} {:>8} {:>8} {:>8} {:>8} {:>10}".format(
    "strategy", "n", "mean", "median", "std", "min", "max", ">1.0", ">1.0%"))
print("    " + "-" * 75)
for label in ["A", "D", "B_scored", "C_v2"]:
    s = comparisons.get(label)
    if s:
        print("    {:>8} {:>6} {:>8.3f} {:>8.3f} {:>8.3f} {:>8.3f} {:>8.3f} {:>8} {:>9.1f}%".format(
            label, s["n"], s["mean"], s["median"], s["std"],
            s["min"], s["max"], s["above_1"], s["above_1pct"]))

print("\n" + "=" * 60)
print("CONCLUSION:")
if comparisons.get("C_v2", {}).get("mean", 0) > 0.5:
    print("  C_v2 brightness OK — some candidates may be functionally viable")
else:
    print("  C_v2 brightness LOW — mutations disrupt chromophore environment")
print("=" * 60)
