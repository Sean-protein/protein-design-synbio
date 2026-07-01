# -*- coding: utf-8 -*-
"""
策略B — 候选序列打分
====================
用训练好的集成模型对策略A+D候选序列预测亮度。

用法:
  python score.py                              # 全量候选打分
  python score.py --model-dir results/strategy_B/models  # 指定模型目录
"""

import json
import os
import pickle
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from config import (
    MODELS_DIR, STRAT_B_DIR, CANDIDATE_SCORES_CSV, EMBED_DIM,
    STRAT_A_PASSED, STRAT_A_FOLDX, STRAT_D_ALL, STRAT_D_FOLDX,
    log, get_sfGFP_wt,
)
from features import featurize_batch


def load_models(model_dir=None):
    """加载训练好的模型。"""
    if model_dir is None:
        model_dir = MODELS_DIR

    models = {}
    for name in ["rf", "xgb", "lgb"]:
        path = os.path.join(model_dir, f"{name}_model.pkl")
        if os.path.exists(path):
            with open(path, "rb") as f:
                models[name] = pickle.load(f)
            log.info("Loaded %s from %s", name, path)
        else:
            log.error("Model not found: %s", path)
            return None

    # 尝试加载 Ridge 元模型
    meta_path = os.path.join(model_dir, "meta_model.pkl")
    if os.path.exists(meta_path):
        with open(meta_path, "rb") as f:
            models["meta"] = pickle.load(f)
        log.info("Loaded meta-model (Ridge stacking)")
    else:
        models["meta"] = None
        log.info("No meta-model, using simple average ensemble")

    return models


def predict_ensemble(X, models):
    """集成预测"""
    p_rf = models["rf"].predict(X)
    p_xgb = models["xgb"].predict(X)
    p_lgb = models["lgb"].predict(X)

    if models["meta"] is not None:
        meta_X = np.column_stack([p_rf, p_xgb, p_lgb])
        pred = models["meta"].predict(meta_X)
    else:
        pred = (p_rf + p_xgb + p_lgb) / 3.0

    return pred, p_rf, p_xgb, p_lgb


def load_candidates():
    """加载策略A+D候选序列，合并FoldX ddG。"""
    candidates = []

    # ── 策略A ──
    if os.path.exists(STRAT_A_PASSED):
        df_a = pd.read_csv(STRAT_A_PASSED)
        log.info("Strategy A passed: %d", len(df_a))

        # 合并 FoldX ddG
        if os.path.exists(STRAT_A_FOLDX):
            foldx = pd.read_csv(STRAT_A_FOLDX)
            if "ddG_kcal_mol" in foldx.columns:
                foldx_map = foldx.set_index("seq_id")["ddG_kcal_mol"].to_dict()
                df_a["ddG_kcal_mol"] = df_a["seq_id"].map(foldx_map)
                log.info("Merged FoldX ddG for Strategy A")
        else:
            df_a["ddG_kcal_mol"] = np.nan

        df_a["source"] = "strategy_A"
        candidates.append(df_a)

    # ── 策略D ──
    if os.path.exists(STRAT_D_ALL):
        df_d = pd.read_csv(STRAT_D_ALL)
        log.info("Strategy D all: %d", len(df_d))

        if os.path.exists(STRAT_D_FOLDX):
            foldx_d = pd.read_csv(STRAT_D_FOLDX)
            if "ddG_kcal_mol" in foldx_d.columns:
                foldx_map = foldx_d.set_index("seq_id")["ddG_kcal_mol"].to_dict()
                df_d["ddG_kcal_mol"] = df_d["seq_id"].map(foldx_map)
                log.info("Merged FoldX ddG for Strategy D")
        else:
            df_d["ddG_kcal_mol"] = np.nan

        df_d["source"] = "strategy_D"
        candidates.append(df_d)

    if not candidates:
        log.error("No candidate files found")
        return None

    # 合并去重
    cand_df = pd.concat(candidates, ignore_index=True)
    # 按序列去重（保留第一条来源）
    cand_df = cand_df.drop_duplicates(subset="sequence", keep="first")
    log.info("Total unique candidates: %d", len(cand_df))

    return cand_df


def score_candidates(cand_df, models, embeddings_npz=None):
    """为候选序列打分。

    如果提供了 embeddings_npz，使用预计算的 ESM 嵌入；
    否则 ESM 特征列为 0（仅有手工特征预测）。
    """
    wt_seq = get_sfGFP_wt()
    log.info("Using sfGFP WT (len=%d) as reference", len(wt_seq))

    sequences = cand_df["sequence"].tolist()
    # 获取突变字符串
    if "mutation_str" in cand_df.columns:
        mutation_strs = cand_df["mutation_str"].tolist()
    elif "aaMutations" in cand_df.columns:
        mutation_strs = cand_df["aaMutations"].tolist()
    else:
        mutation_strs = ["WT"] * len(sequences)

    # ── 加载 ESM 嵌入 ──
    if embeddings_npz and os.path.exists(embeddings_npz):
        data = np.load(embeddings_npz)
        embeddings = data["embeddings"]
        log.info("Loaded candidate embeddings: %s", embeddings.shape)
        assert len(embeddings) == len(sequences), \
            f"Embeddings {len(embeddings)} != sequences {len(sequences)}"
    else:
        log.warning("No candidate ESM embeddings — using zeros (prediction quality reduced)")
        embeddings = None

    # ── 特征化 ──
    log.info("Featurizing %d candidates...", len(sequences))
    X = featurize_batch(sequences, mutation_strs, wt_seq, embeddings=embeddings)
    log.info("Candidate feature matrix: %s", X.shape)

    # ── NaN 处理 ──
    if embeddings is None:
        # ESM 列全为 NaN，用 0 填充
        nan_cols = np.isnan(X)
        X = np.nan_to_num(X, nan=0.0)

    # ── 预测 ──
    pred_ens, pred_rf, pred_xgb, pred_lgb = predict_ensemble(X, models)
    log.info("Predicted %d candidates", len(pred_ens))
    log.info("  Brightness range: [%.3f, %.3f]", pred_ens.min(), pred_ens.max())
    log.info("  Brightness mean: %.3f ± %.3f", pred_ens.mean(), pred_ens.std())

    # ── 综合评分 ──
    cand_df["pred_brightness"] = pred_ens
    cand_df["pred_brightness_rf"] = pred_rf
    cand_df["pred_brightness_xgb"] = pred_xgb
    cand_df["pred_brightness_lgb"] = pred_lgb

    # Stability penalty: 亮度 / max(ddG, 1.0)
    ddg = cand_df["ddG_kcal_mol"].fillna(2.0).values
    cand_df["composite_score"] = pred_ens / np.maximum(ddg, 1.0)

    # 排序
    cand_df = cand_df.sort_values("composite_score", ascending=False)

    # ── 保存 ──
    cand_df.to_csv(CANDIDATE_SCORES_CSV, index=False)
    log.info("Candidate scores → %s", CANDIDATE_SCORES_CSV)

    # ── Top 20 展示 ──
    top20 = cand_df.head(20)
    print("\n" + "=" * 70)
    print("TOP 20 CANDIDATES (by composite score = pred_brightness / max(ddG, 1.0))")
    print("=" * 70)
    cols = ["seq_id", "source", "num_mutations", "mutation_str",
            "pred_brightness", "ddG_kcal_mol", "composite_score"]
    available = [c for c in cols if c in top20.columns]
    print(top20[available].to_string(index=False))

    return cand_df


def run_scoring(model_dir=None, embeddings_npz=None):
    """运行打分流程。"""
    log.info("=" * 60)
    log.info("STRATEGY B — Candidate Scoring")
    log.info("=" * 60)

    # ── 加载模型 ──
    models = load_models(model_dir)
    if models is None:
        log.error("Failed to load models. Run train.py first.")
        sys.exit(1)

    # ── 加载候选 ──
    cand_df = load_candidates()
    if cand_df is None:
        log.error("No candidates to score.")
        sys.exit(1)

    # ── 打分 ──
    results = score_candidates(cand_df, models, embeddings_npz=embeddings_npz)

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Strategy B: Candidate Scoring")
    parser.add_argument("--model-dir", type=str, help="Directory containing trained models")
    parser.add_argument("--embeddings", type=str, help="Path to candidate ESM embeddings (.npz)")
    args = parser.parse_args()

    run_scoring(model_dir=args.model_dir, embeddings_npz=args.embeddings)


if __name__ == "__main__":
    main()
