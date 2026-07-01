# -*- coding: utf-8 -*-
"""
策略B — 主编排脚本
==================
按序执行 M0→M5 各步骤。支持 --step 分步执行。

用法:
  python pipeline.py --step data_prep     # 仅数据准备
  python pipeline.py --step embed         # 仅ESM嵌入（需服务器）
  python pipeline.py --step features      # 仅特征工程
  python pipeline.py --step train         # 仅模型训练
  python pipeline.py --step score         # 仅候选打分
  python pipeline.py --step all           # 全流程（默认）

  python pipeline.py --quick              # 快速验证模式
  python pipeline.py --server             # 服务器模式（路径自动调整）
"""

import argparse
import os
import sys

from config import log, STRAT_B_DIR


def step_data_prep(args):
    """M1: 数据准备"""
    from data_prep import load_and_prepare
    load_and_prepare()


def step_embed(args):
    """M2: ESM-2 650M 嵌入提取（服务器 GPU）"""
    from embed import run_embedding
    run_embedding(
        input_path=args.embed_input,
        output_path=args.embed_output,
        batch_size=args.batch_size,
        max_seqs=args.max_seqs,
    )


def step_features(args):
    """M3: 特征工程"""
    from features import build_training_features, build_candidate_features
    if args.candidates:
        build_candidate_features()
    else:
        build_training_features()


def step_train(args):
    """M4: ML 集成训练"""
    from train import run_training
    run_training(
        do_tune=not args.no_tune,
        quick=args.quick,
        do_stacking=not args.no_stacking,
    )


def step_score(args):
    """M5: 候选打分"""
    from score import run_scoring
    run_scoring(
        model_dir=args.model_dir,
        embeddings_npz=args.score_embeddings,
    )


def step_status(args):
    """显示当前进度"""
    import json
    log.info("=" * 60)
    log.info("STRATEGY B — Status Check")
    log.info("=" * 60)

    checks = {
        "avGFP_processed.csv": os.path.exists(os.path.join(STRAT_B_DIR, "avGFP_processed.csv")),
        "embeddings.npz": os.path.exists(os.path.join(STRAT_B_DIR, "embeddings_esm2_650M.npz")),
        "features_X.npy": os.path.exists(os.path.join(STRAT_B_DIR, "features_X.npy")),
        "features_y.npy": os.path.exists(os.path.join(STRAT_B_DIR, "features_y.npy")),
        "rf_model.pkl": os.path.exists(os.path.join(STRAT_B_DIR, "models", "rf_model.pkl")),
        "xgb_model.pkl": os.path.exists(os.path.join(STRAT_B_DIR, "models", "xgb_model.pkl")),
        "lgb_model.pkl": os.path.exists(os.path.join(STRAT_B_DIR, "models", "lgb_model.pkl")),
        "candidate_scores.csv": os.path.exists(os.path.join(STRAT_B_DIR, "candidate_scores.csv")),
    }

    for name, exists in checks.items():
        status = "[OK]" if exists else "[MISSING]"
        log.info("  %s %s", status, name)

    # 检查测试分数
    scores_path = os.path.join(STRAT_B_DIR, "test_scores.json")
    if os.path.exists(scores_path):
        with open(scores_path) as f:
            scores = json.load(f)
        log.info("  Test scores:")
        for model, metrics in scores.items():
            log.info("    %s: R2=%.4f, RMSE=%.4f", model, metrics["r2"], metrics["rmse"])


def main():
    parser = argparse.ArgumentParser(description="Strategy B: Full Pipeline")
    parser.add_argument("--step", choices=["data_prep", "embed", "features", "train",
                                           "score", "status", "all"],
                        default="status", help="Pipeline step to run")
    parser.add_argument("--quick", action="store_true", help="Quick mode")
    parser.add_argument("--server", action="store_true", help="Server mode")
    parser.add_argument("--candidates", action="store_true", help="Build candidate features")
    parser.add_argument("--no-tune", action="store_true", help="Skip Optuna tuning")
    parser.add_argument("--no-stacking", action="store_true", help="Skip stacking ensemble")
    parser.add_argument("--batch-size", type=int, help="ESM embedding batch size")
    parser.add_argument("--max-seqs", type=int, help="Max sequences for embedding")
    parser.add_argument("--embed-input", type=str, help="Input CSV for embedding")
    parser.add_argument("--embed-output", type=str, help="Output .npz for embeddings")
    parser.add_argument("--model-dir", type=str, help="Model directory for scoring")
    parser.add_argument("--score-embeddings", type=str, help="Candidate embeddings for scoring")

    args = parser.parse_args()

    log.info("Strategy B Pipeline — Step: %s", args.step)

    if args.step == "all":
        log.info("Running full pipeline: data_prep → embed → features → train → score")
        step_data_prep(args)
        step_features(args)  # 先执行手工特征(不含ESM)，等ESM嵌入完成后再更新
        log.warning("Embed step (embed) must be run on the GPU server separately.")
        log.warning("After embeddings are ready, re-run: python pipeline.py --step features")
        log.warning("Then: python pipeline.py --step train && python pipeline.py --step score")
    elif args.step == "data_prep":
        step_data_prep(args)
    elif args.step == "embed":
        step_embed(args)
    elif args.step == "features":
        step_features(args)
    elif args.step == "train":
        step_train(args)
    elif args.step == "score":
        step_score(args)
    elif args.step == "status":
        step_status(args)


if __name__ == "__main__":
    main()
