# -*- coding: utf-8 -*-
"""
策略B — ML集成训练
==================
XGBoost + LightGBM + RandomForest + 5-fold CV + Stacking Ensemble

用法:
  python train.py                              # 全量训练+评估
  python train.py --quick                      # 快速模式（10K子集，无超参调优）
  python train.py --no-tune                    # 跳过超参调优
  python train.py --no-stacking                # 跳过集成，只训练独立模型
"""

import json
import os
import pickle
import sys
import time
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score, mean_squared_error
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")

from config import (
    AVGFP_PROCESSED, FEATURES_X_NPY, FEATURES_Y_NPY, SPLIT_JSON,
    MODELS_DIR, STRAT_B_DIR, ENSEMBLE_PRED_CSV, FEATURES_META_JSON,
    RANDOM_SEED, N_FOLDS, N_TRIALS_OPTUNA, log,
)


def load_data():
    """加载特征矩阵、标签和划分信息。"""
    X = np.load(FEATURES_X_NPY)
    y = np.load(FEATURES_Y_NPY)
    df = pd.read_csv(AVGFP_PROCESSED)
    log.info("X: %s, y: %s (mean=%.3f, std=%.3f)", X.shape, y.shape, y.mean(), y.std())

    # NaN 清洗
    nan_mask = np.isnan(X).any(axis=1)
    if nan_mask.any():
        log.warning("Dropping %d NaN rows", nan_mask.sum())
        valid = ~nan_mask
        X, y = X[valid], y[valid]
        df = df[valid].reset_index(drop=True)

    return X, y, df


def get_splits(df):
    """从 JSON 或 DataFrame split 列获取 train/val/test 划分。"""
    if os.path.exists(SPLIT_JSON):
        with open(SPLIT_JSON, "r") as f:
            split_info = json.load(f)
        train_idx = split_info["train_indices"]
        val_idx = split_info["val_indices"]
        test_idx = split_info["test_indices"]
        # 确保索引在范围内
        max_idx = len(df) - 1
        train_idx = [i for i in train_idx if i <= max_idx]
        val_idx = [i for i in val_idx if i <= max_idx]
        test_idx = [i for i in test_idx if i <= max_idx]
        log.info("Using pre-saved splits: train=%d, val=%d, test=%d",
                 len(train_idx), len(val_idx), len(test_idx))
    elif "split" in df.columns:
        train_idx = df[df["split"] == "train"].index.tolist()
        val_idx = df[df["split"] == "val"].index.tolist()
        test_idx = df[df["split"] == "test"].index.tolist()
        log.info("Using DataFrame split column: train=%d, val=%d, test=%d",
                 len(train_idx), len(val_idx), len(test_idx))
    else:
        # 降级：重新划分
        from sklearn.model_selection import train_test_split
        log.warning("No split info found, creating new split")
        train_val_idx, test_idx = train_test_split(
            range(len(df)), test_size=0.2, random_state=RANDOM_SEED
        )
        train_idx, val_idx = train_test_split(
            train_val_idx, test_size=0.125, random_state=RANDOM_SEED
        )
        log.info("New split: train=%d, val=%d, test=%d",
                 len(train_idx), len(val_idx), len(test_idx))

    return train_idx, val_idx, test_idx


def tune_xgboost(X_train, y_train, X_val, y_val, n_trials=N_TRIALS_OPTUNA):
    """Optuna 超参调优 XGBoost。"""
    try:
        import optuna
        import xgboost as xgb
    except ImportError:
        log.warning("Optuna/xgboost not available, using defaults")
        return {"n_estimators": 500, "max_depth": 6, "learning_rate": 0.05,
                "subsample": 0.8, "colsample_bytree": 0.8}

    def objective(trial):
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 300, 800),
            "max_depth": trial.suggest_int("max_depth", 4, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.15, log=True),
            "subsample": trial.suggest_float("subsample", 0.6, 0.95),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 0.95),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-6, 1.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-6, 1.0, log=True),
            "random_state": RANDOM_SEED,
            "n_jobs": -1,
        }
        model = xgb.XGBRegressor(**params)
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        pred = model.predict(X_val)
        return r2_score(y_val, pred)

    log.info("Tuning XGBoost (%d trials)...", n_trials)
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    log.info("Best XGBoost params: %s", study.best_params)
    log.info("Best XGBoost val R2: %.4f", study.best_value)
    return study.best_params


def tune_lightgbm(X_train, y_train, X_val, y_val, n_trials=N_TRIALS_OPTUNA):
    """Optuna 超参调优 LightGBM。"""
    try:
        import optuna
        import lightgbm as lgb
    except ImportError:
        log.warning("Optuna/lightgbm not available, using defaults")
        return {"n_estimators": 500, "max_depth": 6, "learning_rate": 0.05,
                "subsample": 0.8, "colsample_bytree": 0.8}

    def objective(trial):
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 300, 800),
            "max_depth": trial.suggest_int("max_depth", 4, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.15, log=True),
            "subsample": trial.suggest_float("subsample", 0.6, 0.95),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 0.95),
            "num_leaves": trial.suggest_int("num_leaves", 31, 255),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-6, 1.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-6, 1.0, log=True),
            "random_state": RANDOM_SEED,
            "n_jobs": -1,
            "verbosity": -1,
        }
        model = lgb.LGBMRegressor(**params)
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)])
        pred = model.predict(X_val)
        return r2_score(y_val, pred)

    log.info("Tuning LightGBM (%d trials)...", n_trials)
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    log.info("Best LightGBM params: %s", study.best_params)
    log.info("Best LightGBM val R2: %.4f", study.best_value)
    return study.best_params


def run_cv(model_class, model_params, X, y, n_folds=N_FOLDS):
    """运行 K-fold 交叉验证，返回 OOF 预测和每折分数。"""
    kf = KFold(n_splits=n_folds, shuffle=True, random_state=RANDOM_SEED)
    oof_preds = np.zeros(len(y))
    fold_scores = []

    for fold, (train_idx, val_idx) in enumerate(kf.split(X)):
        X_tr, X_va = X[train_idx], X[val_idx]
        y_tr, y_va = y[train_idx], y[val_idx]

        model = model_class(**model_params)
        model.fit(X_tr, y_tr)
        pred = model.predict(X_va)
        oof_preds[val_idx] = pred

        r2 = r2_score(y_va, pred)
        rmse = np.sqrt(mean_squared_error(y_va, pred))
        fold_scores.append({"fold": fold, "r2": r2, "rmse": rmse})
        log.info("  Fold %d: R2=%.4f, RMSE=%.4f", fold + 1, r2, rmse)

    mean_r2 = np.mean([s["r2"] for s in fold_scores])
    mean_rmse = np.mean([s["rmse"] for s in fold_scores])

    # 在全量数据上训练最终模型
    final_model = model_class(**model_params)
    final_model.fit(X, y)

    return oof_preds, fold_scores, mean_r2, mean_rmse, final_model


def train_ensemble(X_train, y_train, X_val, y_val, X_test, y_test,
                   do_tune=True, do_stacking=True, quick=False):
    """训练 XGBoost + LightGBM + RandomForest 集成。

    Returns
    -------
    dict: 包含所有模型、预测和指标的字典
    """
    import xgboost as xgb
    import lightgbm as lgb

    results = {}

    # ── 0. 快速模式：使用数据子集 ──
    if quick:
        n_quick = min(10000, len(X_train))
        log.info("Quick mode: using %d samples", n_quick)
        idx = np.random.RandomState(RANDOM_SEED).choice(len(X_train), n_quick, replace=False)
        X_train, y_train = X_train[idx], y_train[idx]

    # ── 1. RandomForest 基线 ──
    log.info("─" * 40)
    log.info("Training RandomForest (baseline)...")
    rf_params = {
        "n_estimators": 200 if quick else 300,
        "max_depth": 12 if quick else 20,
        "min_samples_leaf": 5 if quick else 3,
        "n_jobs": -1,
        "random_state": RANDOM_SEED,
    }
    rf_oof, rf_folds, rf_r2, rf_rmse, rf_model = run_cv(
        RandomForestRegressor, rf_params, X_train, y_train
    )
    results["rf"] = {
        "model": rf_model, "oof_preds": rf_oof,
        "cv_r2": rf_r2, "cv_rmse": rf_rmse,
        "fold_scores": rf_folds, "params": rf_params,
    }
    log.info("RF CV R2=%.4f, RMSE=%.4f", rf_r2, rf_rmse)

    # ── 2. XGBoost ──
    log.info("─" * 40)
    log.info("Training XGBoost...")
    if do_tune and not quick:
        xgb_best = tune_xgboost(X_train, y_train, X_val, y_val)
    else:
        xgb_best = {"n_estimators": 500, "max_depth": 6, "learning_rate": 0.05,
                    "subsample": 0.8, "colsample_bytree": 0.8,
                    "reg_alpha": 0.1, "reg_lambda": 0.1}
    xgb_params = {**xgb_best, "random_state": RANDOM_SEED, "n_jobs": -1}
    xgb_oof, xgb_folds, xgb_r2, xgb_rmse, xgb_model = run_cv(
        xgb.XGBRegressor, xgb_params, X_train, y_train
    )
    results["xgb"] = {
        "model": xgb_model, "oof_preds": xgb_oof,
        "cv_r2": xgb_r2, "cv_rmse": xgb_rmse,
        "fold_scores": xgb_folds, "params": xgb_params,
    }
    log.info("XGBoost CV R2=%.4f, RMSE=%.4f", xgb_r2, xgb_rmse)

    # ── 3. LightGBM ──
    log.info("─" * 40)
    log.info("Training LightGBM...")
    if do_tune and not quick:
        lgb_best = tune_lightgbm(X_train, y_train, X_val, y_val)
    else:
        lgb_best = {"n_estimators": 500, "max_depth": 6, "learning_rate": 0.05,
                    "subsample": 0.8, "colsample_bytree": 0.8, "num_leaves": 127,
                    "reg_alpha": 0.1, "reg_lambda": 0.1}
    lgb_params = {**lgb_best, "random_state": RANDOM_SEED, "n_jobs": -1, "verbosity": -1}
    lgb_oof, lgb_folds, lgb_r2, lgb_rmse, lgb_model = run_cv(
        lgb.LGBMRegressor, lgb_params, X_train, y_train
    )
    results["lgb"] = {
        "model": lgb_model, "oof_preds": lgb_oof,
        "cv_r2": lgb_r2, "cv_rmse": lgb_rmse,
        "fold_scores": lgb_folds, "params": lgb_params,
    }
    log.info("LightGBM CV R2=%.4f, RMSE=%.4f", lgb_r2, lgb_rmse)

    # ── 4. 集成 ──
    log.info("─" * 40)
    if do_stacking:
        log.info("Building stacking ensemble (Ridge meta-learner)...")
        # 用 OOF 预测作为元特征
        meta_X_train = np.column_stack([rf_oof, xgb_oof, lgb_oof])
        meta_model = Ridge(alpha=1.0)
        meta_model.fit(meta_X_train, y_train)
        log.info("Meta-learner weights: RF=%.3f, XGB=%.3f, LGB=%.3f",
                 meta_model.coef_[0], meta_model.coef_[1], meta_model.coef_[2])

        # 集成预测函数
        def ensemble_predict(X):
            p_rf = rf_model.predict(X)
            p_xgb = xgb_model.predict(X)
            p_lgb = lgb_model.predict(X)
            meta_X = np.column_stack([p_rf, p_xgb, p_lgb])
            return meta_model.predict(meta_X)

        # 简单平均作为对照
        def simple_avg_predict(X):
            p_rf = rf_model.predict(X)
            p_xgb = xgb_model.predict(X)
            p_lgb = lgb_model.predict(X)
            return (p_rf + p_xgb + p_lgb) / 3.0

        results["ensemble"] = {
            "meta_model": meta_model,
            "predict_fn": ensemble_predict,
            "simple_avg_fn": simple_avg_predict,
        }
    else:
        # 仅简单平均
        log.info("Using simple average ensemble (no stacking)")
        def simple_avg_predict(X):
            p_rf = rf_model.predict(X)
            p_xgb = xgb_model.predict(X)
            p_lgb = lgb_model.predict(X)
            return (p_rf + p_xgb + p_lgb) / 3.0

        results["ensemble"] = {
            "simple_avg_fn": simple_avg_predict,
            "predict_fn": simple_avg_predict,
        }

    # ── 5. 测试集评估 ──
    log.info("─" * 40)
    log.info("Test Set Evaluation:")
    log.info("─" * 40)

    test_scores = {}
    for name in ["rf", "xgb", "lgb"]:
        model = results[name]["model"]
        pred = model.predict(X_test)
        r2 = r2_score(y_test, pred)
        rmse = np.sqrt(mean_squared_error(y_test, pred))
        pearson = np.corrcoef(y_test, pred)[0, 1]
        test_scores[name] = {"r2": r2, "rmse": rmse, "pearson_r": pearson}
        log.info("  %-4s: R2=%.4f  RMSE=%.4f  Pearson r=%.4f", name.upper(), r2, rmse, pearson)

    # 集成
    pred_ens = results["ensemble"]["predict_fn"](X_test)
    ens_r2 = r2_score(y_test, pred_ens)
    ens_rmse = np.sqrt(mean_squared_error(y_test, pred_ens))
    ens_pearson = np.corrcoef(y_test, pred_ens)[0, 1]
    test_scores["ensemble_stacking"] = {"r2": ens_r2, "rmse": ens_rmse, "pearson_r": ens_pearson}
    log.info("  ENS (stacking): R2=%.4f  RMSE=%.4f  Pearson r=%.4f", ens_r2, ens_rmse, ens_pearson)

    # 简单平均
    pred_avg = results["ensemble"]["simple_avg_fn"](X_test)
    avg_r2 = r2_score(y_test, pred_avg)
    avg_rmse = np.sqrt(mean_squared_error(y_test, pred_avg))
    avg_pearson = np.corrcoef(y_test, pred_avg)[0, 1]
    test_scores["ensemble_simple_avg"] = {"r2": avg_r2, "rmse": avg_rmse, "pearson_r": avg_pearson}
    log.info("  ENS (avg):      R2=%.4f  RMSE=%.4f  Pearson r=%.4f", avg_r2, avg_rmse, avg_pearson)

    results["test_scores"] = test_scores

    return results


def save_models(results):
    """保存所有模型到磁盘。"""
    os.makedirs(MODELS_DIR, exist_ok=True)

    for name in ["rf", "xgb", "lgb"]:
        model = results[name]["model"]
        path = os.path.join(MODELS_DIR, f"{name}_model.pkl")
        with open(path, "wb") as f:
            pickle.dump(model, f)
        log.info("Saved %s → %s", name, path)

    # 保存 Ridge 元模型
    if results["ensemble"].get("meta_model"):
        path = os.path.join(MODELS_DIR, "meta_model.pkl")
        with open(path, "wb") as f:
            pickle.dump(results["ensemble"]["meta_model"], f)
        log.info("Saved meta_model → %s", path)

    # 保存测试分数
    scores_path = os.path.join(STRAT_B_DIR, "test_scores.json")
    with open(scores_path, "w") as f:
        json.dump(results["test_scores"], f, indent=2)
    log.info("Test scores → %s", scores_path)


def run_training(do_tune=True, quick=False, do_stacking=True):
    """运行完整的训练流程。"""
    log.info("=" * 60)
    log.info("STRATEGY B — ML Ensemble Training")
    log.info("=" * 60)

    # ── 加载数据 ──
    X, y, df = load_data()
    train_idx, val_idx, test_idx = get_splits(df)

    X_train, y_train = X[train_idx], y[train_idx]
    X_val, y_val = X[val_idx], y[val_idx]
    X_test, y_test = X[test_idx], y[test_idx]

    log.info("Train: %d, Val: %d, Test: %d", len(X_train), len(X_val), len(X_test))

    # ── 训练 ──
    results = train_ensemble(X_train, y_train, X_val, y_val, X_test, y_test,
                             do_tune=do_tune, do_stacking=do_stacking, quick=quick)

    # ── 保存 ──
    save_models(results)

    # ── 输出预测到 CSV ──
    pred_df = df.iloc[test_idx].copy()
    pred_df["y_true"] = y_test
    pred_df["pred_rf"] = results["rf"]["model"].predict(X_test)
    pred_df["pred_xgb"] = results["xgb"]["model"].predict(X_test)
    pred_df["pred_lgb"] = results["lgb"]["model"].predict(X_test)
    pred_df["pred_ensemble"] = results["ensemble"]["predict_fn"](X_test)
    pred_df.to_csv(ENSEMBLE_PRED_CSV, index=False)
    log.info("Test predictions → %s", ENSEMBLE_PRED_CSV)

    # ── 汇总 ──
    log.info("=" * 60)
    log.info("Training Complete!")
    log.info("=" * 60)
    ts = results["test_scores"]
    log.info("Best model on test set: %s",
             max(ts, key=lambda k: ts[k]["r2"]))

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Strategy B: ML Training")
    parser.add_argument("--quick", action="store_true", help="Quick mode (10K subset)")
    parser.add_argument("--no-tune", action="store_true", help="Skip hyperparameter tuning")
    parser.add_argument("--no-stacking", action="store_true", help="Skip stacking ensemble")
    args = parser.parse_args()

    run_training(
        do_tune=not args.no_tune,
        quick=args.quick,
        do_stacking=not args.no_stacking,
    )


if __name__ == "__main__":
    main()
