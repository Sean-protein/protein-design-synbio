# -*- coding: utf-8 -*-
"""Phase 2: 亮度排序 — 使用策略B预计算ESM分数（完整ESM-2 650M嵌入），Top 80输出

修复说明：
  旧版脚本用 featurize_batch() 重新提取特征并预测，但 ESM 嵌入列（1280维）全为0，
  因为未加载ESM模型。策略B模型训练时使用了完整ESM嵌入（R²=0.712），缺少ESM会严重
  降低预测质量。

  策略B的 score.py 已对所有 A+D 候选序列完成了带ESM嵌入的打分，结果保存在
  results/strategy_B/candidate_scores.csv。本脚本现在：
  1. 加载 candidate_scores.csv（含 composite_score 等完整ESM预测）
  2. LEFT JOIN Phase 1 pool ← candidate_scores on sequence
  3. 匹配到的序列直接使用已有分数（~2827/2830 条）
  4. 未匹配序列（Strategy C picks + mChartreuse）用 featurize_batch 兜底，
     标记 scored_with_esm=False
  5. 按 composite_score 降序排序，取 Top 80
"""

import os, sys, pickle, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "code", "strategy_B"))

from config import (
    MODELS_DIR, RESULTS_DIR, CANDIDATE_SCORES_CSV, log,
    get_sfGFP_wt,
)
from features import featurize_batch

INPUT_POOL = os.path.join(RESULTS_DIR, "funnel_phase1_pool.csv")
OUTPUT_TOP80 = os.path.join(RESULTS_DIR, "funnel_phase2_top80.csv")
OUTPUT_ALL = os.path.join(RESULTS_DIR, "funnel_phase2_all_scored.csv")
TOP_N = 80


def load_ensemble_models():
    """加载策略B训练的模型（含 sklearn 1.3.2 -> 1.7.x 兼容性修补）。

    返回 dict: {"rf": ..., "xgb": ..., "lgb": ..., "meta": ...|None}
    """
    models = {}
    for name in ["rf", "xgb", "lgb"]:
        path = os.path.join(MODELS_DIR, f"{name}_model.pkl")
        with open(path, "rb") as f:
            models[name] = pickle.load(f)

    # sklearn 1.3.2 -> 1.7.x 兼容性修补
    if "rf" in models:
        for est in models["rf"].estimators_:
            if not hasattr(est, "monotonic_cst") or est.monotonic_cst is None:
                est.monotonic_cst = None
    if "lgb" in models:
        if models["lgb"]._n_classes is None:
            models["lgb"]._n_classes = 1

    meta_path = os.path.join(MODELS_DIR, "meta_model.pkl")
    if os.path.exists(meta_path):
        with open(meta_path, "rb") as f:
            models["meta"] = pickle.load(f)
    return models


def predict_with_ensemble(X, models):
    """集成预测：3个基模型 + Ridge stacking 元模型。

    Returns:
        final: (N,) 集成最终预测 (pred_brightness)
        preds: dict of (N,) 各基模型预测
    """
    preds = {}
    for name in ["rf", "xgb", "lgb"]:
        preds[name] = models[name].predict(X)

    meta_X = np.column_stack([preds["rf"], preds["xgb"], preds["lgb"]])
    if models.get("meta") is not None:
        final = models["meta"].predict(meta_X)
    else:
        final = np.mean(meta_X, axis=1)
    return final, preds


def fallback_score(unmatched_df, models):
    """对未匹配序列使用手工特征（无ESM嵌入）进行预测。

    与 score.py 的 composite_score 公式一致：
        composite_score = pred_brightness / max(ddG, 1.0)
        ddG 缺失值填 2.0

    Returns:
        DataFrame with columns: pred_brightness_rf, pred_brightness_xgb,
        pred_brightness_lgb, pred_brightness, composite_score, scored_with_esm
    """
    if len(unmatched_df) == 0:
        return unmatched_df

    log.info("Fallback scoring %d sequences (no ESM embeddings)...", len(unmatched_df))
    wt_seq = get_sfGFP_wt()
    sequences = unmatched_df["sequence"].tolist()
    mutation_strs = unmatched_df["mutation_str"].tolist()

    X = featurize_batch(sequences, mutation_strs, wt_seq)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    final_preds, individual_preds = predict_with_ensemble(X, models)

    result = unmatched_df.copy()
    result["pred_brightness_rf"] = individual_preds["rf"]
    result["pred_brightness_xgb"] = individual_preds["xgb"]
    result["pred_brightness_lgb"] = individual_preds["lgb"]
    result["pred_brightness"] = final_preds

    # composite_score = pred_brightness / max(ddG, 1.0) — 与 score.py 一致
    ddg = unmatched_df["ddG_kcal_mol"].fillna(2.0).values
    result["composite_score"] = final_preds / np.maximum(ddg, 1.0)
    result["scored_with_esm"] = False

    return result


def main():
    print("=" * 60)
    print("Phase 2: 亮度排序 (使用策略B ESM预计算分数)")
    print("=" * 60)

    # ── 1. 加载数据 ──
    print("\n[1/5] 加载数据...")
    pool = pd.read_csv(INPUT_POOL)
    print(f"  Phase 1 pool: {len(pool)} 条")

    cand_scores = pd.read_csv(CANDIDATE_SCORES_CSV)
    print(f"  Strategy B candidate_scores: {len(cand_scores)} 条")

    # 验证 candidate_scores 必要列
    required_cols = ["sequence", "composite_score", "pred_brightness",
                     "pred_brightness_rf", "pred_brightness_xgb", "pred_brightness_lgb"]
    missing = [c for c in required_cols if c not in cand_scores.columns]
    if missing:
        raise KeyError(f"candidate_scores.csv 缺少列: {missing}")
    print(f"  ESM分数列验证通过: {required_cols}")

    # ── 2. LEFT JOIN pool ← candidate_scores on sequence ──
    print("\n[2/5] LEFT JOIN Phase 1 pool ← Strategy B scores (on sequence)...")

    score_cols = ["sequence", "composite_score", "pred_brightness",
                  "pred_brightness_rf", "pred_brightness_xgb", "pred_brightness_lgb"]
    scores_subset = cand_scores[score_cols].copy()

    merged = pool.merge(scores_subset, on="sequence", how="left")

    matched_mask = merged["composite_score"].notna()
    n_matched = matched_mask.sum()
    n_unmatched = (~matched_mask).sum()
    print(f"  匹配成功: {n_matched} 条 (使用完整ESM-2 650M分数)")
    print(f"  未匹配: {n_unmatched} 条 (需fallback评分)")

    merged["scored_with_esm"] = matched_mask  # True=ESM分数, False=fallback

    if n_unmatched > 0:
        unmatched_info = merged.loc[~matched_mask, ["seq_id", "source_strategy"]]
        print(f"  未匹配序列详情:")
        for _, row in unmatched_info.iterrows():
            print(f"    {row['seq_id']} (source={row['source_strategy']})")

    # ── 3. Fallback: 对未匹配序列使用手工特征评分 ──
    if n_unmatched > 0:
        print("\n[3/5] Fallback: 为未匹配序列加载模型并评分（无ESM嵌入）...")
        models = load_ensemble_models()
        print(f"  模型已加载: {list(models.keys())}")

        unmatched_df = merged[~matched_mask].copy()
        unmatched_scored = fallback_score(unmatched_df, models)

        # 回填 fallback 结果到 merged
        score_cols_fill = ["pred_brightness_rf", "pred_brightness_xgb",
                           "pred_brightness_lgb", "pred_brightness",
                           "composite_score", "scored_with_esm"]
        for col in score_cols_fill:
            merged.loc[~matched_mask, col] = unmatched_scored[col].values

        print(f"  Fallback完成: {len(unmatched_scored)} 条已评分")
        print(f"  Fallback分数范围: "
              f"[{unmatched_scored['composite_score'].min():.3f}, "
              f"{unmatched_scored['composite_score'].max():.3f}]")
    else:
        print("\n[3/5] 无需fallback: 所有序列均已匹配 (scored_with_esm=True)")

    # ── 4. 排序并取 Top 80 ──
    print("\n[4/5] 排序输出...")
    merged = merged.sort_values("composite_score", ascending=False)

    # 统计 mChartreuse 排名
    mc_mask = merged["seq_id"] == "MC_mChartreuse_001"
    if mc_mask.any():
        mc_idx = merged[mc_mask].index[0]
        mc_rank = merged.index.get_loc(mc_idx) + 1
        mc_row = merged.loc[mc_idx]
        print(f"  mChartreuse排名: {mc_rank}/{len(merged)}, "
              f"score={mc_row['composite_score']:.4f}, "
              f"scored_with_esm={mc_row['scored_with_esm']}")

    top80 = merged.head(TOP_N).copy()
    top80["phase2_rank"] = range(1, len(top80) + 1)

    # 统计 Top 80 组成
    print(f"\nTop {TOP_N} 策略分布:")
    for s in ["A", "D", "C"]:
        count = (top80["source_strategy"] == s).sum()
        print(f"  {s}: {count} 条")
    esm_count = top80["scored_with_esm"].sum()
    print(f"  使用ESM分数: {esm_count}/{len(top80)}")
    print(f"  分数范围: [{top80['composite_score'].min():.3f}, "
          f"{top80['composite_score'].max():.3f}]")

    # ── 5. 输出 ──
    print("\n[5/5] 输出...")
    top80.to_csv(OUTPUT_TOP80, index=False)
    print(f"  Top 80 → {OUTPUT_TOP80} ({len(top80)} 条)")

    # 同时输出完整排序池（供 Phase 3 等后续步骤使用）
    merged.to_csv(OUTPUT_ALL, index=False)
    print(f"  完整排序池 → {OUTPUT_ALL} ({len(merged)} 条)")


if __name__ == "__main__":
    main()
