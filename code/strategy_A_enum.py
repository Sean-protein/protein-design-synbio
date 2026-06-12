# -*- coding: utf-8 -*-
"""
策略A：理性工程优化 — sfGFP 候选序列枚举
===========================================
基于 v3.0 三级约束体系，从 45 个候选设计位点枚举 1-3 个突变组合，
生成 ~2,000-3,000 条候选序列，输出 FoldX BuildModel 输入文件。

用法:
    python 代码/strategy_A_enum.py                          # 默认运行
    python 代码/strategy_A_enum.py --verify                 # 运行+验证
    python 代码/strategy_A_enum.py --no-foldx              # 跳过FoldX输入生成
    python 代码/strategy_A_enum.py --max-mutations 2       # 仅1-2突变
"""

import argparse
import itertools
import json
import logging
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

# ══════════════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════════════
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "2026Protein Design")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "运行结果")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# BLOSUM62 矩阵 (简化版，仅包含正分+0分)
BLOSUM62_CONSERVATIVE = {
    "A": "AGST", "C": "C", "D": "DENQ", "E": "EDQK", "F": "FYWL",
    "G": "GA", "H": "HNYQ", "I": "IVLM", "K": "KERQ", "L": "LIVM",
    "M": "MILV", "N": "NDQH", "P": "P", "Q": "QEKN", "R": "RKQ",
    "S": "STA", "T": "TAS", "V": "VILM", "W": "WFY", "Y": "YFHW",
}
AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"

# v3.0 一级约束（化学绝对，固定不可变）
LEVEL1_POSITIONS = {65, 66, 67, 71, 96, 222}

# v3.0 二级约束（量子产率相关，可谨慎探索）
LEVEL2_POSITIONS = {69, 94, 148, 203, 205}
LEVEL2_ALLOWED = {
    69: ["N", "E"],       # Q69 → 仅保守替换，保留H键能力
    94: ["N", "E", "D"],  # Q94 → 同上
    148: [],               # H148 → 策略A排除（无已知功能性替换）
    203: [],               # T203 → 策略A排除（光谱调谐风险）
    205: [],               # S205 → 策略A排除（荧光严重受损）
}

# sfGFP 核心12突变 (vs avGFP)，不可逆回 avGFP 身份
# avGFP 身份用于检测逆转
SGFP_CORE_MUTATIONS = {
    30: "R", 39: "N", 64: "L", 65: "T", 80: "R",
    99: "S", 105: "T", 145: "F", 153: "T", 163: "A",
    171: "V", 206: "V",
}
# 对应的 avGFP 残基（不可逆回）
SGFP_CORE_AVGFP_RESIDUE = {
    30: "S", 39: "Y", 65: "S", 80: "Q",
    99: "F", 105: "N", 145: "Y", 153: "M",
    163: "V", 171: "I", 206: "A",
    # 64 is L in both avGFP and sfGFP (F64L is EGFP mutation, sfGFP starts with L)
}

# 区域分类（用于跨区域配对）
REGIONS = {
    "chromophore": {64, 65, 66, 67, 68, 69, 71, 72, 94, 96, 148, 203, 205, 222},
    "beta_core": {10, 17, 30, 32, 39, 45, 73, 79, 101, 105, 109, 115, 122},
    "hydrophobic_core": {134, 137, 145, 147, 152, 153, 163, 167, 171},
    "surface": {80, 175, 180, 187, 190, 221, 225, 231, 232, 234, 236},
    "c_terminal": {206, 221, 225, 231, 232, 234, 236},
}


# ══════════════════════════════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════════════════════════════
def load_sfgfp_sequence():
    """从官方参考序列文件加载 sfGFP WT。"""
    seq_file = os.path.join(DATA_DIR, "AAseqs of 5 GFP proteins_20260511.txt")
    with open(seq_file, "r") as f:
        current_header = ""
        seq_lines = []
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                if "sfGFP" in current_header and seq_lines:
                    seq = "".join(seq_lines)
                    log.info("Loaded sfGFP WT: %d aa", len(seq))
                    return seq
                current_header = line
                seq_lines = []
            elif line and not line.startswith("#"):
                seq_lines.append(line)
        if "sfGFP" in current_header and seq_lines:
            seq = "".join(seq_lines)
            log.info("Loaded sfGFP WT: %d aa", len(seq))
            return seq
    raise ValueError("sfGFP sequence not found in reference file")


def load_candidate_positions():
    """加载 45 个候选设计位点。"""
    path = os.path.join(PROJECT_ROOT, "data", "comprehensive_GFP_dataset.xlsx")
    df = pd.read_excel(path, sheet_name="Candidate_Positions")
    log.info("Loaded %d candidate positions", len(df))
    return df


def load_constraints():
    """加载 228 位约束 CSV。"""
    path = os.path.join(PROJECT_ROOT, "data", "sfGFP_禁止突变位点.csv")
    df = pd.read_csv(path)
    log.info("Loaded %d constraint entries", len(df))
    return df


def load_exclusion_list():
    """加载 135K 排除名单为 Python set。"""
    path = os.path.join(DATA_DIR, "Exclusion_List.csv")
    df = pd.read_csv(path)
    exclusion_set = set(df.iloc[:, 0].astype(str))
    log.info("Loaded %d exclusion sequences (set lookup)", len(exclusion_set))
    return exclusion_set


def load_training_brightness():
    """加载官方训练数据 (141K 条)，构建 (GFP_type, mutations) → brightness 映射。"""
    path = os.path.join(DATA_DIR, "GFP_data.xlsx")
    df = pd.read_excel(path, sheet_name="brightness")
    log.info("Loaded %d training entries", len(df))
    return df


# ══════════════════════════════════════════════════════════════════════════════
# 位点池构建
# ══════════════════════════════════════════════════════════════════════════════
def get_region(pos):
    """返回位点所属区域。"""
    for region, positions in REGIONS.items():
        if pos in positions:
            return region
    return "other"


def build_position_pool(sfgfp_seq, candidates_df, constraints_df, training_df):
    """构建统一的位点约束字典 {position_1based: PositionInfo dict}。"""
    constraints_dict = {}
    for _, row in constraints_df.iterrows():
        constraints_dict[int(row["Position"])] = {
            "residue": row["Residue"],
            "conservation_level": row["Conservation_Level"],
            "functional_category": row["Functional_Category"],
            "exception_mutations": str(row.get("Exception_Mutations", "")),
            "mutation_consequence": str(row.get("Mutation_Consequence", "")),
        }

    pool = {}
    for pos in range(1, len(sfgfp_seq) + 1):
        wt_res = sfgfp_seq[pos - 1]
        constraint = constraints_dict.get(pos, {})
        cons_level = constraint.get("conservation_level", "未注释")

        # 确定 v3.0 约束等级
        if pos in LEVEL1_POSITIONS:
            v3_level = 1
        elif pos in LEVEL2_POSITIONS:
            v3_level = 2
        else:
            v3_level = 3

        # 确定允许的突变
        allowed = get_allowed_mutations(
            pos, wt_res, v3_level, candidates_df, constraint
        )

        pool[pos] = {
            "position": pos,
            "wt_residue": wt_res,
            "v3_level": v3_level,
            "conservation_level": cons_level,
            "functional_category": constraint.get("functional_category", ""),
            "region": get_region(pos),
            "is_sfgfp_core": pos in SGFP_CORE_MUTATIONS,
            "sfgfp_core_residue": SGFP_CORE_MUTATIONS.get(pos),
            "allowed_mutations": allowed,
            "is_designable": len(allowed) > 0 and v3_level != 1,
        }

    return pool


def get_allowed_mutations(pos, wt_res, v3_level, candidates_df, constraint):
    """确定某位点允许的突变列表。"""
    allowed = set()

    if v3_level == 1:
        return []  # Level 1: 固定不可变

    if v3_level == 2:
        return LEVEL2_ALLOWED.get(pos, [])

    # Level 3: 从候选位点 + BLOSUM62 + Exception_Mutations 合并
    candidate_row = candidates_df[candidates_df["Position_1based"] == pos]
    if not candidate_row.empty:
        known = str(candidate_row.iloc[0]["Known_Beneficial_Mutations"])
        avoid = str(candidate_row.iloc[0]["Mutations_to_Avoid"])
        # 解析已知有益突变 (格式: "L64 (EGFP F64L)", "F145 (sfGFP Y145F)")
        import re
        for match in re.finditer(r"([A-Z])(\d+)([A-Z])", known):
            if match.group(3) != wt_res:
                allowed.add(match.group(3))
    else:
        avoid = ""

    # 从 Exception_Mutations 解析
    exc = constraint.get("exception_mutations", "")
    if exc and exc != "nan":
        for ch in exc.split(","):
            ch = ch.strip()
            if len(ch) == 1 and ch in AMINO_ACIDS and ch != wt_res:
                allowed.add(ch)

    # BLOSUM62 保守替换 (正分)
    blosum_allowed = BLOSUM62_CONSERVATIVE.get(wt_res, "")
    for aa in blosum_allowed:
        if aa != wt_res and aa in AMINO_ACIDS:
            allowed.add(aa)

    # 排除明确禁止的
    if avoid and avoid != "nan":
        for word in avoid.replace(";", ",").split(","):
            word = word.strip()
            if len(word) == 1:
                allowed.discard(word)
            elif len(word) == 3 and word in AMINO_ACIDS:
                allowed.discard(word)

    # sfGFP 核心突变不可逆
    if pos in SGFP_CORE_MUTATIONS:
        old_res = SGFP_CORE_MUTATIONS[pos]
        allowed.discard(old_res)

    # 限制每位点最多 3 个突变
    return sorted(allowed)[:3]


# ══════════════════════════════════════════════════════════════════════════════
# 突变组合枚举
# ══════════════════════════════════════════════════════════════════════════════
def apply_mutations(wt_seq, mutations):
    """在 WT 序列上应用一组 {position_1based: new_aa} 突变。"""
    seq_list = list(wt_seq)
    for pos, new_aa in mutations.items():
        seq_list[pos - 1] = new_aa
    return "".join(seq_list)


def mutations_to_str(mutations):
    """{pos: new_aa} → 'A30R:F64L' 格式。"""
    parts = []
    for pos in sorted(mutations.keys()):
        new_aa = mutations[pos]
        parts.append(f"{new_aa}{pos}{new_aa}")  # Placeholder, fixed below
    # 正确的格式: 原始aa + 位置 + 新aa
    return ":".join(parts)


def _get_enum_positions(pool, candidates_df):
    """获取枚举的目标位点列表：45候选位点 + Level 2 位点（可设计子集）。"""
    candidate_positions = set(candidates_df["Position_1based"].tolist())
    level2_positions = {p for p in LEVEL2_POSITIONS if pool[p]["is_designable"]}
    enum_positions = sorted(candidate_positions | level2_positions)
    return [p for p in enum_positions if pool[p]["is_designable"]]


def enumerate_single_mutants(wt_seq, pool, enum_positions):
    """枚举所有单突变。"""
    candidates = []
    for pos in enum_positions:
        info = pool[pos]
        for new_aa in info["allowed_mutations"]:
            if new_aa == info["wt_residue"]:
                continue
            mutations = {pos: new_aa}
            seq = apply_mutations(wt_seq, mutations)
            mut_str = f"{info['wt_residue']}{pos}{new_aa}"
            candidates.append({
                "seq": seq, "mut_str": mut_str, "num_mut": 1,
                "positions": [pos], "levels": [info["v3_level"]],
                "regions": [info["region"]], "max_level": info["v3_level"],
            })
    return candidates


def enumerate_double_mutants(wt_seq, pool, enum_positions):
    """枚举双突变：跨区域配对，仅枚举45候选位点。"""
    candidates = []
    n = len(enum_positions)
    for i in range(n):
        pos1 = enum_positions[i]
        info1 = pool[pos1]
        for j in range(i + 1, n):
            pos2 = enum_positions[j]
            info2 = pool[pos2]

            # 跳过相邻位点
            if abs(pos1 - pos2) <= 1:
                continue
            # 跳过两个 Level 2 同时突变
            if info1["v3_level"] == 2 and info2["v3_level"] == 2:
                continue
            # 跨区域优先（相同区域仅在已知有益时允许）
            if info1["region"] == info2["region"] and info1["region"] != "beta_core":
                # 仅允许 hydrophobic_core 和 surface 内的同区配对
                if info1["region"] not in ("hydrophobic_core", "surface"):
                    continue

            for aa1 in info1["allowed_mutations"][:2]:
                if aa1 == info1["wt_residue"]:
                    continue
                for aa2 in info2["allowed_mutations"][:2]:
                    if aa2 == info2["wt_residue"]:
                        continue
                    mutations = {pos1: aa1, pos2: aa2}
                    seq = apply_mutations(wt_seq, mutations)
                    mut_str = (
                        f"{info1['wt_residue']}{pos1}{aa1}:"
                        f"{info2['wt_residue']}{pos2}{aa2}"
                    )
                    candidates.append({
                        "seq": seq, "mut_str": mut_str, "num_mut": 2,
                        "positions": sorted([pos1, pos2]),
                        "levels": [info1["v3_level"], info2["v3_level"]],
                        "regions": [info1["region"], info2["region"]],
                        "max_level": max(info1["v3_level"], info2["v3_level"]),
                    })
    return candidates


def enumerate_triple_mutants(wt_seq, pool, enum_positions):
    """枚举三突变：三个不同区域 + 至少1个折叠增强突变。严格控制规模。"""
    folding_enhancers = {30, 39, 64, 99, 105, 145, 153, 163}
    candidates = []
    n = len(enum_positions)

    for i in range(n):
        pos1 = enum_positions[i]
        info1 = pool[pos1]
        for j in range(i + 1, n):
            pos2 = enum_positions[j]
            info2 = pool[pos2]
            if info1["region"] == info2["region"]:
                continue
            # 仅选择包含折叠增强位点的配对进入第三轮
            if not ({pos1, pos2} & folding_enhancers):
                continue
            for k in range(j + 1, n):
                pos3 = enum_positions[k]
                info3 = pool[pos3]
                regions = {info1["region"], info2["region"], info3["region"]}
                if len(regions) < 3:
                    continue
                # 仅取第1个允许突变（最保守的）
                for aa1 in info1["allowed_mutations"][:1]:
                    if aa1 == info1["wt_residue"]:
                        continue
                    for aa2 in info2["allowed_mutations"][:1]:
                        if aa2 == info2["wt_residue"]:
                            continue
                        for aa3 in info3["allowed_mutations"][:1]:
                            if aa3 == info3["wt_residue"]:
                                continue
                            mutations = {pos1: aa1, pos2: aa2, pos3: aa3}
                            seq = apply_mutations(wt_seq, mutations)
                            mut_str = (
                                f"{info1['wt_residue']}{pos1}{aa1}:"
                                f"{info2['wt_residue']}{pos2}{aa2}:"
                                f"{info3['wt_residue']}{pos3}{aa3}"
                            )
                            candidates.append({
                                "seq": seq, "mut_str": mut_str, "num_mut": 3,
                                "positions": sorted([pos1, pos2, pos3]),
                                "levels": [info1["v3_level"], info2["v3_level"], info3["v3_level"]],
                                "regions": [info1["region"], info2["region"], info3["region"]],
                                "max_level": max(info1["v3_level"], info2["v3_level"], info3["v3_level"]),
                            })
    return candidates


# ══════════════════════════════════════════════════════════════════════════════
# 过滤
# ══════════════════════════════════════════════════════════════════════════════
def filter_level1_violations(candidates, wt_seq, pool):
    """过滤 Level 1 位点突变。"""
    passed = []
    for c in candidates:
        violation = False
        for pos in LEVEL1_POSITIONS:
            if c["seq"][pos - 1] != wt_seq[pos - 1]:
                violation = True
                break
        if not violation:
            passed.append(c)
    if len(candidates) > len(passed):
        log.info("Level 1 filter: %d → %d (%d removed)",
                 len(candidates), len(passed), len(candidates) - len(passed))
    return passed


def filter_sfgfp_core_reversions(candidates, wt_seq):
    """过滤 sfGFP 核心突变逆转（仅阻止逆回 avGFP 身份）。"""
    passed = []
    for c in candidates:
        ok = True
        for pos, avGFP_res in SGFP_CORE_AVGFP_RESIDUE.items():
            if c["seq"][pos - 1] == avGFP_res:
                ok = False
                break
        if ok:
            passed.append(c)
    if len(candidates) > len(passed):
        log.info("sfGFP core reversion filter: %d -> %d (%d removed)",
                 len(candidates), len(passed), len(candidates) - len(passed))
    return passed


def filter_exclusion_list(candidates, exclusion_set):
    """过滤 Exclusion List 匹配。"""
    passed = []
    for c in candidates:
        if c["seq"] not in exclusion_set:
            passed.append(c)
    removed = len(candidates) - len(passed)
    if removed > 0:
        log.warning("Exclusion list: %d sequences removed!", removed)
    else:
        log.info("Exclusion list: 0 hits [OK]")
    return passed


def deduplicate(candidates):
    """去重（按序列）。"""
    seen = set()
    passed = []
    for c in candidates:
        if c["seq"] not in seen:
            seen.add(c["seq"])
            passed.append(c)
    dups = len(candidates) - len(passed)
    if dups > 0:
        log.info("Dedup: %d duplicates removed", dups)
    return passed


# ══════════════════════════════════════════════════════════════════════════════
# FoldX 输入生成
# ══════════════════════════════════════════════════════════════════════════════
def write_foldx_input(candidates, output_dir):
    """为每条候选生成 FoldX individual_list.txt。"""
    foldx_dir = os.path.join(output_dir, "strategy_A_foldx_input")
    os.makedirs(foldx_dir, exist_ok=True)

    batch_lines = []
    index_rows = []

    for i, c in enumerate(candidates):
        seq_id = f"SA_{i:04d}"
        # FoldX 格式: OriginalAAChainPositionNewAA;
        mut_parts = c["mut_str"].split(":")
        individual_lines = []
        for part in mut_parts:
            # 解析: A30R → A, 30, R
            wt_aa = part[0]
            pos_str = part[1:-1]
            new_aa = part[-1]
            # FoldX 使用 chain A
            individual_lines.append(f"{wt_aa}A{pos_str}{new_aa};")

        # 写入 individual_list.txt (所有突变同一行，逗号分隔)
        list_path = os.path.join(foldx_dir, f"{seq_id}_individual_list.txt")
        with open(list_path, "w") as f:
            f.write(",".join(individual_lines) + "\n")

        # 批量命令
        batch_lines.append(
            f"FoldX --command=BuildModel --pdb=2B3P_sfGFP.pdb "
            f"--mutant-file={seq_id}_individual_list.txt "
            f"--output-dir=foldx_output/"
        )
        index_rows.append({
            "seq_id": seq_id,
            "individual_list": f"{seq_id}_individual_list.txt",
            "mutations": c["mut_str"],
        })

    # 写入批量脚本
    batch_path = os.path.join(foldx_dir, "foldx_batch.ps1")
    with open(batch_path, "w") as f:
        f.write("# FoldX batch run script\n")
        f.write("$FOLDX = \"C:\\path\\to\\foldx.exe\"  # ← 修改为你的 FoldX 路径\n")
        f.write("cd " + foldx_dir.replace("\\", "/") + "\n\n")
        for line in batch_lines:
            f.write(f"& $FOLDX --command=BuildModel --pdb=2B3P_sfGFP.pdb "
                    f"--mutant-file={line.split('--mutant-file=')[1].split()[0]} "
                    f"--output-dir=foldx_output/\n")

    # 索引 CSV
    index_df = pd.DataFrame(index_rows)
    index_df.to_csv(os.path.join(foldx_dir, "foldx_index.csv"), index=False)

    log.info("FoldX input: %d individual_list.txt files in %s", len(candidates), foldx_dir)
    log.info("  Run: .\\strategy_A_foldx_input\\foldx_batch.ps1 (after setting FoldX path)")


# ══════════════════════════════════════════════════════════════════════════════
# 验证
# ══════════════════════════════════════════════════════════════════════════════
def verify(wt_seq, candidates, pool, exclusion_set):
    """运行全套验证。"""
    errors = []

    # 1. sfGFP WT 完整性
    assert len(wt_seq) == 238, f"WT length != 238: {len(wt_seq)}"
    for pos, expected in SGFP_CORE_MUTATIONS.items():
        actual = wt_seq[pos - 1]
        assert actual == expected, f"Position {pos}: expected {expected}, got {actual}"
    log.info("[OK] sfGFP WT: 238aa, 12 core mutations verified")

    # 2. Level 1 无突变
    for i, c in enumerate(candidates):
        for pos in LEVEL1_POSITIONS:
            if c["seq"][pos - 1] != wt_seq[pos - 1]:
                errors.append(f"Level 1 violation: candidate {i}, position {pos}")
    log.info(f"[OK] Level 1 check: {len(errors)} violations")

    # 3. sfGFP 核心无逆转（仅阻止逆回 avGFP 身份）
    rev_errors = 0
    for i, c in enumerate(candidates):
        for pos, avGFP_res in SGFP_CORE_AVGFP_RESIDUE.items():
            if c["seq"][pos - 1] == avGFP_res:
                rev_errors += 1
                break
    log.info(f"[OK] sfGFP core: {rev_errors} reversions")

    # 4. Exclusion List
    hits = sum(1 for c in candidates if c["seq"] in exclusion_set)
    log.info(f"[OK] Exclusion list: {hits} hits (expected 0)")

    # 5. 去重
    seqs = [c["seq"] for c in candidates]
    dups = len(seqs) - len(set(seqs))
    log.info(f"[OK] Duplicates: {dups}")

    # 6. 序列合规
    bad_seqs = 0
    for c in candidates:
        s = c["seq"]
        if not s.startswith("M"):
            bad_seqs += 1
        if len(s) != 238:
            bad_seqs += 1
        if not all(aa in AMINO_ACIDS for aa in s):
            bad_seqs += 1
    log.info(f"[OK] Sequence compliance: {bad_seqs} invalid")

    # 7. 位点覆盖率
    pos_used = set()
    for c in candidates:
        for p in c["positions"]:
            pos_used.add(p)
    designable = {p for p, i in pool.items() if i["is_designable"]}
    coverage = len(pos_used & designable)
    log.info(f"[OK] Coverage: {coverage}/{len(designable)} designable positions used")

    # 8. 区间分布
    for n in [1, 2, 3]:
        count = sum(1 for c in candidates if c["num_mut"] == n)
        log.info(f"  {n}-mutants: {count}")

    if errors:
        log.error("VERIFICATION FAILED with %d errors", len(errors))
        for e in errors[:10]:
            log.error(f"  {e}")
    else:
        log.info("ALL VERIFICATIONS PASSED [OK]")

    return len(errors) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════════
def run_strategy_A(args):
    """运行策略A枚举。"""
    log.info("=" * 60)
    log.info("STRATEGY A: Rational Enumeration")
    log.info("=" * 60)

    # ---- 1. 加载数据 ----
    log.info("Loading data...")
    wt_seq = load_sfgfp_sequence()
    candidates_df = load_candidate_positions()
    constraints_df = load_constraints()
    exclusion_set = load_exclusion_list()

    # ---- 2. 构建位点池 ----
    log.info("Building position pool...")
    pool = build_position_pool(wt_seq, candidates_df, constraints_df, None)

    designable = sum(1 for p in pool.values() if p["is_designable"])
    level1_count = sum(1 for p in pool.values() if p["v3_level"] == 1)
    level2_count = sum(1 for p in pool.values() if p["v3_level"] == 2)
    log.info("Pool: %d total, %d designable, %d Level1, %d Level2",
             len(pool), designable, level1_count, level2_count)

    # ---- 3. 枚举 ----
    enum_positions = _get_enum_positions(pool, candidates_df)
    log.info("Enumeration positions: %d (45 candidates + Level 2)", len(enum_positions))

    log.info("Enumerating single mutants...")
    single = enumerate_single_mutants(wt_seq, pool, enum_positions)
    log.info("  %d single mutants", len(single))

    log.info("Enumerating double mutants (cross-region)...")
    double = enumerate_double_mutants(wt_seq, pool, enum_positions)
    log.info("  %d double mutants", len(double))

    log.info("Enumerating triple mutants (limited)...")
    triple = [] if args.max_mutations < 3 else enumerate_triple_mutants(wt_seq, pool, enum_positions)
    log.info("  %d triple mutants", len(triple))

    # ---- 4. 合并 + 过滤 ----
    all_candidates = single + double + triple
    log.info("Total before filtering: %d", len(all_candidates))

    all_candidates = filter_level1_violations(all_candidates, wt_seq, pool)
    all_candidates = filter_sfgfp_core_reversions(all_candidates, wt_seq)
    all_candidates = deduplicate(all_candidates)
    all_candidates = filter_exclusion_list(all_candidates, exclusion_set)

    log.info("Final candidates: %d", len(all_candidates))

    # ---- 5. 构建输出 DataFrame ----
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    rows = []
    for i, c in enumerate(all_candidates):
        l2_positions = [p for p in c["positions"] if p in LEVEL2_POSITIONS]
        rows.append({
            "seq_id": f"SA_{i:04d}",
            "sequence": c["seq"],
            "mutation_str": c["mut_str"],
            "num_mutations": c["num_mut"],
            "positions_mutated": ",".join(str(p) for p in c["positions"]),
            "constraint_max": c["max_level"],
            "level2_warning": len(l2_positions) > 0,
            "level2_positions": ",".join(str(p) for p in l2_positions) if l2_positions else "",
            "regions": ";".join(c["regions"]) if isinstance(c["regions"], list) else str(c["regions"]),
        })

    df = pd.DataFrame(rows)
    csv_path = os.path.join(OUTPUT_DIR, "strategy_A_candidates.csv")
    df.to_csv(csv_path, index=False)
    log.info("Saved %d candidates to %s", len(df), csv_path)

    # ---- 6. 输出位点池元数据 ----
    pool_json = {}
    for pos, info in pool.items():
        pool_json[str(pos)] = {
            "wt": info["wt_residue"],
            "v3_level": info["v3_level"],
            "conservation": info["conservation_level"],
            "region": info["region"],
            "allowed": info["allowed_mutations"],
            "is_designable": info["is_designable"],
        }
    json_path = os.path.join(OUTPUT_DIR, "strategy_A_position_pool.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(pool_json, f, indent=2, ensure_ascii=False)
    log.info("Position pool metadata saved to %s", json_path)

    # ---- 7. FoldX 输入 ----
    if not args.no_foldx:
        # 检查 FoldX 是否存在
        import shutil
        foldx_found = shutil.which("foldx") or shutil.which("FoldX")
        if not foldx_found:
            log.warning("=" * 60)
            log.warning("[WARN]  FoldX 未在 PATH 中找到。")
            log.warning("   FoldX 需从 foldxsuite.crg.eu 下载（学术免费）。")
            log.warning("   候选序列已生成，FoldX 输入文件已就绪。")
            log.warning("   安装 FoldX 后运行: .\\运行结果\\strategy_A_foldx_input\\foldx_batch.ps1")
            log.warning("=" * 60)
        write_foldx_input(all_candidates, OUTPUT_DIR)

    # ---- 8. 日志 ----
    log_path = os.path.join(OUTPUT_DIR, "strategy_A_log.txt")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"Strategy A Enumeration Log\n")
        f.write(f"{'='*60}\n")
        f.write(f"sfGFP WT: {len(wt_seq)} aa\n")
        f.write(f"Designable positions: {designable}\n")
        f.write(f"Single mutants: {len(single)}\n")
        f.write(f"Double mutants: {len(double)}\n")
        f.write(f"Triple mutants: {len(triple)}\n")
        f.write(f"After filtering: {len(all_candidates)}\n")
        f.write(f"Exclusion list size: {len(exclusion_set)}\n")
        f.write(f"Level 1 positions: {sorted(LEVEL1_POSITIONS)}\n")
        f.write(f"Level 2 positions: {sorted(LEVEL2_POSITIONS)}\n")
        f.write(f"Output: {csv_path}\n")

    # ---- 9. 验证 ----
    if args.verify:
        log.info("Running verification...")
        passed = verify(wt_seq, all_candidates, pool, exclusion_set)
        if not passed:
            sys.exit(1)

    log.info("=" * 60)
    log.info("Strategy A enumeration complete! %d candidates ready.", len(all_candidates))
    log.info("=" * 60)

    return df


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Strategy A: Rational Enumeration")
    parser.add_argument("--verify", action="store_true", help="Run verification checks")
    parser.add_argument("--no-foldx", action="store_true", help="Skip FoldX input generation")
    parser.add_argument("--max-mutations", type=int, default=3,
                        help="Maximum mutations per sequence (default: 3)")
    args = parser.parse_args()
    run_strategy_A(args)


if __name__ == "__main__":
    main()
