# -*- coding: utf-8 -*-
"""
策略B — 数据准备
================
从 competition/GFP_data.xlsx 提取 avGFP 训练数据：
  1. 筛选 avGFP 类型（51,715 条）
  2. 突变字符串 → 全长序列重建
  3. 去重 + 亮度聚合
  4. Train/Val/Test 分层划分
"""

import json
import re

import numpy as np
import pandas as pd

from config import (
    TRAINING_DATA, AVGFP_PROCESSED, SPLIT_JSON,
    TEST_SIZE, VAL_SIZE, RANDOM_SEED, log,
    get_avGFP_wt,
)


def generate_mutated_sequence(mutation_str, wt_sequence):
    """根据突变字符串和 WT 序列生成全长突变序列。

    复用 gfp_design.py 的逻辑，独立副本避免跨模块依赖。

    Parameters
    ----------
    mutation_str : str
        "WT", "E172V", "A12G:C34T"
    wt_sequence : str
        野生型氨基酸序列

    Returns
    -------
    str or None
    """
    if not isinstance(mutation_str, str) or not wt_sequence:
        return None
    if mutation_str.strip().upper() == "WT":
        return wt_sequence

    sequence = list(wt_sequence)
    mutations = mutation_str.split(":")
    try:
        for mut in mutations:
            match = re.match(
                r"([A-Z])(\d+)([A-Z*.])$", mut.strip(), re.IGNORECASE
            )
            if not match:
                continue
            original_aa, pos, new_aa = match.groups()
            pos = int(pos) - 1
            if pos < 0 or pos >= len(sequence):
                continue
            if new_aa == "*":
                return None
            elif new_aa == ".":
                new_aa = sequence[pos]
            sequence[pos] = new_aa.upper()
        return "".join(sequence)
    except Exception:
        return None


def parse_mutations(mutation_str):
    """解析突变字符串，返回 {(1-based pos): new_aa} dict。"""
    if not isinstance(mutation_str, str) or mutation_str.strip().upper() == "WT":
        return {}
    mutations = {}
    for part in mutation_str.split(":"):
        m = re.match(r"([A-Z])(\d+)([A-Z])", part.strip())
        if m:
            mutations[int(m.group(2))] = m.group(3).upper()
    return mutations


def load_and_prepare():
    """加载 avGFP 训练数据，重建序列，去重，划分。"""
    log.info("=" * 60)
    log.info("STRATEGY B — Data Preparation")
    log.info("=" * 60)

    # ── 1. 加载原始数据 ──
    log.info("Loading training data from %s", TRAINING_DATA)
    df = pd.read_excel(TRAINING_DATA, sheet_name="brightness")
    log.info("Total rows: %d, GFP types: %s", len(df), df["GFP type"].unique().tolist())

    # ── 2. 筛选 avGFP ──
    df = df[df["GFP type"] == "avGFP"].copy()
    log.info("Filtered to avGFP: %d rows", len(df))

    # ── 3. 加载 WT 序列 ──
    wt_seq = get_avGFP_wt()
    log.info("avGFP WT sequence length: %d", len(wt_seq))

    # ── 4. 突变 → 全长序列 ──
    original_len = len(df)
    df["full_sequence"] = df["aaMutations"].apply(
        lambda x: generate_mutated_sequence(x, wt_seq)
    )

    # 清理无效序列和亮度
    df.dropna(subset=["full_sequence", "Brightness"], inplace=True)
    df["Brightness"] = pd.to_numeric(df["Brightness"], errors="coerce")
    df.dropna(subset=["Brightness"], inplace=True)
    log.info("After cleaning: %d rows (removed %d)", len(df), original_len - len(df))

    # ── 5. 添加元信息 ──
    df["num_mutations"] = df["aaMutations"].apply(
        lambda x: 0 if str(x).strip().upper() == "WT"
        else len(str(x).split(":"))
    )
    # 解析突变位置
    df["mutation_dict"] = df["aaMutations"].apply(parse_mutations)

    # ── 6. 按序列去重（同序列取亮度中位数） ──
    log.info("Deduplicating by sequence...")
    n_before = len(df)
    grouped = df.groupby("full_sequence").agg(
        aaMutations=("aaMutations", "first"),
        Brightness=("Brightness", "median"),
        GFP_type=("GFP type", "first"),
        num_mutations=("num_mutations", "first"),
        mutation_dict=("mutation_dict", "first"),
    ).reset_index()
    log.info("After dedup: %d unique sequences (removed %d)", len(grouped), n_before - len(grouped))

    # ── 7. 序列长度过滤 ──
    grouped = grouped[grouped["full_sequence"].str.len() == len(wt_seq)]
    log.info("After length filter (238aa): %d sequences", len(grouped))

    # ── 8. 分层划分 ──
    # 用亮度分位数分层，保持分布一致
    grouped["brightness_decile"] = pd.qcut(
        grouped["Brightness"], q=10, labels=False, duplicates="drop"
    )

    from sklearn.model_selection import train_test_split

    # 先分出 test
    train_val, test = train_test_split(
        grouped, test_size=TEST_SIZE, random_state=RANDOM_SEED,
        stratify=grouped["brightness_decile"],
    )
    # 再从 train_val 分出 val
    train, val = train_test_split(
        train_val, test_size=VAL_SIZE / (1 - TEST_SIZE),
        random_state=RANDOM_SEED,
        stratify=train_val["brightness_decile"],
    )

    log.info("Split sizes: train=%d, val=%d, test=%d",
             len(train), len(val), len(test))

    # ── 9. 标记 split ──
    grouped["split"] = "unused"
    grouped.loc[train.index, "split"] = "train"
    grouped.loc[val.index, "split"] = "val"
    grouped.loc[test.index, "split"] = "test"

    used = grouped[grouped["split"] != "unused"]
    log.info("Final dataset: %d sequences", len(used))
    log.info("  train: %d (%.1f%%)", len(train), 100*len(train)/len(used))
    log.info("  val:   %d (%.1f%%)", len(val), 100*len(val)/len(used))
    log.info("  test:  %d (%.1f%%)", len(test), 100*len(test)/len(used))
    log.info("  Brightness range: [%.3f, %.3f]", used["Brightness"].min(), used["Brightness"].max())
    log.info("  Brightness mean: %.3f ± %.3f", used["Brightness"].mean(), used["Brightness"].std())

    # ── 10. 保存 ──
    used.to_csv(AVGFP_PROCESSED, index=False)
    log.info("Processed data → %s", AVGFP_PROCESSED)

    # 保存划分索引
    split_info = {
        "train_indices": train.index.tolist(),
        "val_indices": val.index.tolist(),
        "test_indices": test.index.tolist(),
        "n_total": len(used),
        "n_train": len(train),
        "n_val": len(val),
        "n_test": len(test),
        "brightness_stats": {
            "min": float(used["Brightness"].min()),
            "max": float(used["Brightness"].max()),
            "mean": float(used["Brightness"].mean()),
            "std": float(used["Brightness"].std()),
        },
    }
    with open(SPLIT_JSON, "w") as f:
        json.dump(split_info, f, indent=2)
    log.info("Split info → %s", SPLIT_JSON)

    return used


if __name__ == "__main__":
    load_and_prepare()
