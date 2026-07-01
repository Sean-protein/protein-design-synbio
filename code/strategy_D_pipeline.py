# -*- coding: utf-8 -*-
"""
策略D Phase 4：合并、排序、输出
===============================
合并 Phase 1-3 的所有候选序列，去重，多因子排序，
生成最终策略D输出和 FoldX 输入文件。

排序因子：
  1. 共识分数 (Phase 1) — 进化保守性
  2. 嫁接分数 (Phase 2) — 文献验证
  3. 上位性兼容 (Phase 3) — 共进化规则
  4. 结构多样性 — 跨区域突变

用法:
  python code/strategy_D_pipeline.py
"""

import json
import logging
import os
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
COMPETITION_DIR = os.path.join(PROJECT_ROOT, "competition")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

LEVEL1 = {65, 66, 67, 71, 96, 222}
LEVEL2 = {69, 94, 148, 203, 205}
SGFP_CORE_REVERT = {30:"S",39:"Y",65:"S",80:"Q",99:"F",105:"N",145:"Y",153:"M",163:"V",171:"I",206:"A"}


def load_all():
    """加载所有候选池"""
    files = {
        "consensus": os.path.join(RESULTS_DIR, "strategy_D_consensus_candidates.csv"),
        "grafts": os.path.join(RESULTS_DIR, "strategy_D_feature_grafts.csv"),
    }
    # 如果有上位性过滤版本，优先使用
    filtered_c = os.path.join(RESULTS_DIR, "strategy_D_consensus_epistasis_filtered.csv")
    filtered_g = os.path.join(RESULTS_DIR, "strategy_D_grafts_epistasis_filtered.csv")

    pools = {}
    for name, path in files.items():
        if name == "consensus" and os.path.exists(filtered_c):
            path = filtered_c
        elif name == "grafts" and os.path.exists(filtered_g):
            path = filtered_g

        if os.path.exists(path):
            df = pd.read_csv(path)
            log.info("Loaded %s: %d candidates", name, len(df))
            pools[name] = df
        else:
            log.warning("Missing: %s", path)

    return pools


def load_sfgfp():
    path = os.path.join(COMPETITION_DIR, "AAseqs of 5 GFP proteins_20260511.txt")
    with open(path) as f:
        cur, lines = "", []
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                if "sfGFP" in cur and lines:
                    return "".join(lines)
                cur, lines = line, []
            elif line and not line.startswith("#"):
                lines.append(line)
        if "sfGFP" in cur and lines:
            return "".join(lines)
    raise ValueError("sfGFP not found")


def merge_candidates(pools):
    """合并候选池，按序列去重，保留最高分版本"""
    merged = {}
    for pool_name, df in pools.items():
        for _, row in df.iterrows():
            seq = str(row["sequence"])
            if seq not in merged:
                merged[seq] = dict(row)
                merged[seq]["_pools"] = [pool_name]
            else:
                merged[seq]["_pools"].append(pool_name)
                # 保留分数更高的
                existing_score = merged[seq].get("consensus_score", 0) or 0
                new_score = row.get("consensus_score", 0) or row.get("graft_score", 0) or 0
                if new_score > existing_score:
                    merged[seq] = dict(row)
                    merged[seq]["_pools"] = list(set(
                        merged[seq].get("_pools", []) + [pool_name]
                    ))

    log.info("Merged: %d unique sequences from %d pools", len(merged), len(pools))
    return list(merged.values())


def compute_rank_score(candidate, conservation_profile=None):
    """多因子综合评分 (0-1)"""
    score = 0.0
    weights = {
        "consensus": 0.35,
        "graft": 0.25,
        "epistasis": 0.15,
        "diversity": 0.15,
        "mutation_count": 0.10,
    }

    # 1. 共识分数
    cs = candidate.get("consensus_score", 0)
    if cs is None:
        cs = 0
    score += weights["consensus"] * min(float(cs), 1.0)

    # 2. 嫁接分数
    gs = candidate.get("graft_score", 0)
    if gs is None:
        gs = 0
    score += weights["graft"] * min(float(gs), 1.0)

    # 3. 上位性兼容
    epistasis_viol = candidate.get("epistasis_violations", "")
    bonus = candidate.get("epistasis_bonus", 0)
    if bonus is None:
        bonus = 0
    if not epistasis_viol or str(epistasis_viol).strip() == "":
        score += weights["epistasis"] * (1.0 + min(float(bonus), 1.0))

    # 4. 结构多样性
    regions_str = str(candidate.get("regions", ""))
    n_regions = len(set(regions_str.split(";")) - {""})
    if n_regions >= 2:
        score += weights["diversity"] * min(n_regions / 3, 1.0)

    # 5. 突变数量偏好 (2突变通常最优)
    nmut = candidate.get("num_mutations", 1)
    if isinstance(nmut, str):
        nmut = int(nmut)
    if 2 <= nmut <= 3:
        score += weights["mutation_count"]
    elif nmut == 1:
        score += weights["mutation_count"] * 0.5

    return round(float(score), 4)


def export_final(candidates, sfgfp):
    """导出最终策略D输出"""
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # 排序
    candidates.sort(key=lambda x: -x.get("_rank_score", 0))

    # 标准列
    std_cols = [
        "seq_id", "sequence", "mutation_str", "num_mutations",
        "positions_mutated", "constraint_max", "level2_warning",
        "level2_positions", "regions", "source_scheme",
        "consensus_score", "graft_score", "epistasis_bonus",
        "_rank_score", "_pools",
    ]

    rows = []
    for i, c in enumerate(candidates):
        row = {}
        for col in std_cols:
            if col == "seq_id":
                row["seq_id"] = f"SD_{i:04d}"
            elif col == "_rank_score":
                row["rank_score"] = c.get("_rank_score", 0)
            elif col == "_pools":
                row["source_pools"] = ";".join(c.get("_pools", []))
            else:
                val = c.get(col, "")
                if isinstance(val, float) and np.isnan(val):
                    val = ""
                row[col] = val
        rows.append(row)

    df = pd.DataFrame(rows)
    csv_path = os.path.join(RESULTS_DIR, "strategy_D_all_candidates.csv")
    df.to_csv(csv_path, index=False)
    log.info("Strategy D final output: %d candidates → %s", len(df), csv_path)

    # Top 20
    log.info("\n  Top 10 Ranked Candidates:")
    log.info("  " + "-" * 60)
    for i in range(min(10, len(df))):
        row = df.iloc[i]
        log.info(f"  {i+1:2d}. {row['mutation_str'][:40]:40s}  "
                 f"score={row['rank_score']:.3f}  "
                 f"src={row['source_pools']}")

    return csv_path


def generate_foldx_input(candidates, sfgfp):
    """生成 FoldX individual_list.txt 文件"""
    import re
    foldx_dir = os.path.join(RESULTS_DIR, "strategy_D_foldx_input")
    os.makedirs(foldx_dir, exist_ok=True)

    index_rows = []
    for c in candidates[:500]:  # top 500
        seq_id = c.get("seq_id", "")
        mut_str = c.get("mutation_str", "")
        if not mut_str:
            continue

        # FoldX 格式: OriginalAA + Chain + Position + NewAA
        mut_parts = []
        for part in mut_str.split(":"):
            m = re.match(r"([A-Z])(\d+)([A-Z])", part)
            if m:
                mut_parts.append(f"{m.group(1)}A{m.group(2)}{m.group(3)}")

        if not mut_parts:
            continue

        # 写入 individual_list.txt (格式: GA10A,EA32K;)
        list_path = os.path.join(foldx_dir, f"{seq_id}_individual_list.txt")
        with open(list_path, "w") as f:
            f.write(",".join(mut_parts) + ";\n")

        index_rows.append({
            "seq_id": seq_id,
            "individual_list": f"{seq_id}_individual_list.txt",
            "mutations": mut_str,
            "rank_score": c.get("_rank_score", 0),
        })

    # 索引文件
    idx_path = os.path.join(foldx_dir, "foldx_index.csv")
    pd.DataFrame(index_rows).to_csv(idx_path, index=False)
    log.info("FoldX input: %d files → %s", len(index_rows), foldx_dir)

    return foldx_dir


def run_phase4():
    log.info("=" * 60)
    log.info("STRATEGY D — Phase 4: Merge, Rank & Export")
    log.info("=" * 60)

    sfgfp = load_sfgfp()
    log.info("sfGFP WT: %d aa", len(sfgfp))

    # 1. 加载
    pools = load_all()
    if not pools:
        log.error("No candidate pools found. Run Phase 1-3 first.")
        sys.exit(1)

    # 2. 合并
    candidates = merge_candidates(pools)
    log.info("After merge: %d unique candidates", len(candidates))

    # 3. 评分
    for c in candidates:
        c["_rank_score"] = compute_rank_score(c)

    # 按分数分档
    scores = [c["_rank_score"] for c in candidates]
    log.info("Rank scores: min=%.3f, mean=%.3f, max=%.3f",
             min(scores), np.mean(scores), max(scores))

    # 4. 去重 + 约束最终检查 + 突变数限制
    seen_seqs = set()
    final = []
    for c in candidates:
        seq = c["sequence"]
        if seq in seen_seqs or seq == sfgfp:
            continue
        # 突变数限制 (最多7个)
        nmut = c.get("num_mutations", 1)
        if isinstance(nmut, str):
            nmut = int(nmut)
        if nmut > 7:
            continue
        # 最终 Level 1 检查
        ok = True
        for p in LEVEL1:
            if seq[p - 1] != sfgfp[p - 1]:
                ok = False
                break
        if not ok:
            continue
        # sfGFP 核心逆转
        for p, aa in SGFP_CORE_REVERT.items():
            if seq[p - 1] == aa:
                ok = False
                break
        if not ok:
            continue
        seen_seqs.add(seq)
        final.append(c)

    log.info("Final check: %d candidates (removed %d)", len(final), len(candidates) - len(final))

    # 5. 导出
    csv_path = export_final(final, sfgfp)
    foldx_dir = generate_foldx_input(final, sfgfp)

    # 6. 统计报告
    log.info("\n  Summary:")
    log.info("  " + "-" * 40)
    schemes = {}
    for c in final:
        for pool in c.get("_pools", []):
            schemes[pool] = schemes.get(pool, 0) + 1
    for k, v in schemes.items():
        log.info(f"  From {k}: {v}")
    log.info(f"  Total unique: {len(final)}")

    # 突变分布
    mut_counts = {}
    for c in final:
        n = c.get("num_mutations", 1)
        if isinstance(n, str):
            n = int(n)
        mut_counts[n] = mut_counts.get(n, 0) + 1
    for k in sorted(mut_counts):
        log.info(f"  {k}-mutants: {mut_counts[k]}")

    # 高分区
    top20 = max(1, len(final) // 5)
    top_scores = [c["_rank_score"] for c in final[:top20]]
    log.info(f"  Top {top20} mean score: {np.mean(top_scores):.3f}")

    log.info("=" * 60)
    log.info("Strategy D COMPLETE!")
    log.info(f"  CSV: {csv_path}")
    log.info(f"  FoldX: {foldx_dir}")
    log.info("=" * 60)

    return final


if __name__ == "__main__":
    run_phase4()
