# -*- coding: utf-8 -*-
"""
策略D Phase 1：MSA + 进化保守性共识分析
========================================
从 GFP 同源序列的多序列比对 (MSA) 中提取进化保守性信号，
生成基于进化共识的候选突变组合 (~500-800 条)。

工作流程：
  1. 加载/生成 MSA (jackhmmer vs Swiss-Prot，或 Pfam 参考比对)
  2. 计算位点频率矩阵 (238×21) 和保守性分数
  3. 对每个可能突变打分 (共识频率 × BLOSUM62)
  4. 生成 1-2 突变候选序列
  5. 应用三级约束过滤
  6. 输出 CSV

用法：
  # 完整运行（需要 MSA 文件，在服务器上生成）:
  python code/strategy_D_msa_consensus.py --msa path/to/msa.sto

  # 本地快速测试（使用 5 条参考序列构建的迷你MSA）:
  python code/strategy_D_msa_consensus.py --test-mode

  # 仅分析MSA不生成候选:
  python code/strategy_D_msa_consensus.py --msa msa.sto --analyze-only
"""

import argparse
import itertools
import json
import logging
import os
import re
import sys

import numpy as np
import pandas as pd

# ══════════════════════════════════════════════════════════════════════════════
# 路径配置
# ══════════════════════════════════════════════════════════════════════════════
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPETITION_DIR = os.path.join(PROJECT_ROOT, "competition")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "results")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# 常量 (与 strategy_A_enum.py 保持一致)
# ══════════════════════════════════════════════════════════════════════════════
AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"
AA_TO_IDX = {aa: i for i, aa in enumerate(AMINO_ACIDS)}
GAP_IDX = 20  # gap 字符在第21列

BLOSUM62_CONSERVATIVE = {
    "A": "AGST", "C": "C", "D": "DENQ", "E": "EDQK", "F": "FYWL",
    "G": "GA", "H": "HNYQ", "I": "IVLM", "K": "KERQ", "L": "LIVM",
    "M": "MILV", "N": "NDQH", "P": "P", "Q": "QEKN", "R": "RKQ",
    "S": "STA", "T": "TAS", "V": "VILM", "W": "WFY", "Y": "YFHW",
}

# BLOSUM62 归一化分数 (对角线=1.0)
BLOSUM62_SCORE = {
    ("A","A"):4, ("A","G"):0, ("A","S"):1, ("A","T"):0,
    ("C","C"):9,
    ("D","D"):6, ("D","E"):2, ("D","N"):1, ("D","Q"):0,
    ("E","D"):2, ("E","E"):5, ("E","K"):1, ("E","Q"):2,
    ("F","F"):6, ("F","W"):1, ("F","Y"):3, ("F","L"):0,
    ("G","A"):0, ("G","G"):6,
    ("H","H"):8, ("H","N"):1, ("H","Y"):2, ("H","Q"):0,
    ("I","I"):4, ("I","L"):2, ("I","M"):1, ("I","V"):3,
    ("K","E"):1, ("K","K"):5, ("K","R"):2, ("K","Q"):1,
    ("L","F"):0, ("L","I"):2, ("L","L"):4, ("L","M"):2, ("L","V"):1,
    ("M","I"):1, ("M","L"):2, ("M","M"):5, ("M","V"):1,
    ("N","D"):1, ("N","H"):1, ("N","N"):6, ("N","Q"):0,
    ("P","P"):7,
    ("Q","D"):0, ("Q","E"):2, ("Q","H"):0, ("Q","K"):1, ("Q","N"):0, ("Q","Q"):5, ("Q","R"):1,
    ("R","K"):2, ("R","Q"):1, ("R","R"):5,
    ("S","A"):1, ("S","S"):4, ("S","T"):1,
    ("T","A"):0, ("T","S"):1, ("T","T"):5,
    ("V","I"):3, ("V","L"):1, ("V","M"):1, ("V","V"):4,
    ("W","F"):1, ("W","W"):11, ("W","Y"):2,
    ("Y","F"):3, ("Y","H"):2, ("Y","W"):2, ("Y","Y"):7,
}

# 计算 BLOSUM62 最大值用于归一化
_MAX_BLOSUM = max(BLOSUM62_SCORE.values())

def blosum_norm(aa1, aa2):
    """归一化 BLOSUM62 分数 [0, 1]"""
    key = (aa1, aa2) if (aa1, aa2) in BLOSUM62_SCORE else (aa2, aa1)
    score = BLOSUM62_SCORE.get(key, -4)
    return max(0.0, score / _MAX_BLOSUM)

# v3.0 三级约束体系
LEVEL1_POSITIONS = {65, 66, 67, 71, 96, 222}  # 化学绝对，固定不可变
LEVEL2_POSITIONS = {69, 94, 148, 203, 205}     # 量子产率相关，谨慎探索
LEVEL2_ALLOWED = {
    69: ["N", "E"],
    94: ["N", "E", "D"],
    148: [],
    203: [],
    205: [],
}

# sfGFP 核心12突变 (vs avGFP)，不可逆回 avGFP 身份
SGFP_CORE_MUTATIONS = {
    30: "R", 39: "N", 64: "L", 65: "T", 80: "R",
    99: "S", 105: "T", 145: "F", 153: "T", 163: "A",
    171: "V", 206: "V",
}
SGFP_CORE_AVGFP_RESIDUE = {
    30: "S", 39: "Y", 65: "S", 80: "Q",
    99: "F", 105: "N", 145: "Y", 153: "M",
    163: "V", 171: "I", 206: "A",
}

# 区域分类
REGIONS = {
    "chromophore": {64, 65, 66, 67, 68, 69, 71, 72, 94, 96, 148, 203, 205, 222},
    "beta_core": {10, 17, 30, 32, 39, 45, 73, 79, 101, 105, 109, 115, 122},
    "hydrophobic_core": {134, 137, 145, 147, 152, 153, 163, 167, 171},
    "surface": {80, 175, 180, 187, 190, 221, 225, 231, 232, 234, 236},
    "c_terminal": {206, 221, 225, 231, 232, 234, 236},
}

# 折叠增强位点 (来自文献)
FOLDING_ENHANCERS = {30, 39, 64, 99, 105, 145, 153, 163}


# ══════════════════════════════════════════════════════════════════════════════
# 序列工具
# ══════════════════════════════════════════════════════════════════════════════
def get_region(pos):
    """返回位点所属区域"""
    for region, positions in REGIONS.items():
        if pos in positions:
            return region
    return "other"


def apply_mutations(wt_seq, mutations):
    """在 WT 序列上应用 {pos_1based: new_aa} 突变"""
    seq_list = list(wt_seq)
    for pos, new_aa in mutations.items():
        seq_list[pos - 1] = new_aa
    return "".join(seq_list)


def parse_mutation_str(mut_str):
    """解析 'A30R:F64L' → {30: 'R', 64: 'L'}"""
    mutations = {}
    for part in mut_str.split(":"):
        m = re.match(r"([A-Z])(\d+)([A-Z])", part)
        if m:
            mutations[int(m.group(2))] = m.group(3)
    return mutations


# ══════════════════════════════════════════════════════════════════════════════
# MSA 对齐解析 (MAFFT 输出适配)
# ══════════════════════════════════════════════════════════════════════════════
def parse_mafft_alignment(filepath, ref_name="sfGFP"):
    """
    解析 MAFFT 多序列比对输出。
    以 sfGFP 为参考，移除参考序列中为 gap 的列（其他序列的插入），
    仅保留参考序列的 238 个非 gap 位置。
    返回: (msa_seqs_dict, ref_seq_238aa)
    """
    # 读取多行 FASTA 比对
    raw_seqs = {}
    current_name = None
    current_seq = []
    order = []

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if current_name:
                    raw_seqs[current_name] = "".join(current_seq)
                    order.append(current_name)
                current_name = line[1:].split()[0] if line[1:].split() else line[1:]
                current_seq = []
            else:
                current_seq.append(line.upper().replace(".", "-").replace("~", "-"))
        if current_name:
            raw_seqs[current_name] = "".join(current_seq)
            order.append(current_name)

    log.info("Parsed MAFFT alignment: %d sequences, alignment length=%d",
             len(raw_seqs), len(raw_seqs[order[0]]) if order else 0)

    # 找参考序列 (sfGFP)
    ref_key = None
    for key in raw_seqs:
        if ref_name.lower() in key.lower():
            ref_key = key
            break
    if ref_key is None:
        ref_key = order[0]  # fallback: first sequence
        log.warning("sfGFP not found by name, using first sequence: %s", ref_key)

    ref_aligned = raw_seqs[ref_key]

    # 找出参考序列中非 gap 的列索引 → 即 238 个 sfGFP 位置
    ref_positions = [i for i, ch in enumerate(ref_aligned) if ch != "-"]
    log.info("Reference '%s': %d non-gap positions out of %d alignment columns",
             ref_key[:30], len(ref_positions), len(ref_aligned))

    # 提取参考序列的纯净 238aa
    ref_seq_clean = "".join(ref_aligned[i] for i in ref_positions)

    # 对所有序列，只保留参考序列非 gap 的列
    msa_seqs = {}
    for name in raw_seqs:
        full_seq = raw_seqs[name]
        clean_seq = "".join(full_seq[i] if i < len(full_seq) else "-" for i in ref_positions)
        # 过滤全是 gap 的序列
        if clean_seq.count("-") < len(clean_seq) * 0.9:
            msa_seqs[name] = clean_seq

    log.info("Stripped MSA: %d sequences × %d positions", len(msa_seqs), len(ref_positions))
    return msa_seqs, ref_seq_clean


# ══════════════════════════════════════════════════════════════════════════════
# 序列加载
# ══════════════════════════════════════════════════════════════════════════════
def load_sfgfp_sequence():
    """从参考序列文件加载 sfGFP WT"""
    seq_file = os.path.join(COMPETITION_DIR, "AAseqs of 5 GFP proteins_20260511.txt")
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
    raise ValueError("sfGFP sequence not found")


def load_all_reference_sequences():
    """加载所有可用参考 GFP 序列 (本地5条 + WT 4条, 去重)"""
    sequences = {}  # {name: seq}
    seen_seqs = set()

    # 竞赛参考序列 (5条)
    seq_file1 = os.path.join(COMPETITION_DIR, "AAseqs of 5 GFP proteins_20260511.txt")
    if os.path.exists(seq_file1):
        _load_fasta(seq_file1, sequences, seen_seqs)

    # WT 序列 (4条)
    seq_file2 = os.path.join(DATA_DIR, "WT_AAseqs_4_GFP.txt")
    if os.path.exists(seq_file2):
        _load_fasta(seq_file2, sequences, seen_seqs)

    log.info("Loaded %d unique reference sequences", len(sequences))
    return sequences


def _load_fasta(filepath, sequences, seen_seqs):
    """FASTA 加载器 (内部)"""
    with open(filepath, "r") as f:
        current_header = ""
        seq_lines = []
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                if current_header and seq_lines:
                    seq = "".join(seq_lines)
                    if seq not in seen_seqs and len(seq) >= 200:
                        sequences[current_header] = seq
                        seen_seqs.add(seq)
                current_header = line[1:]  # remove >
                seq_lines = []
            elif line and not line.startswith("#"):
                seq_lines.append(line)
        if current_header and seq_lines:
            seq = "".join(seq_lines)
            if seq not in seen_seqs and len(seq) >= 200:
                sequences[current_header] = seq


def load_exclusion_list():
    """加载排除名单"""
    path = os.path.join(COMPETITION_DIR, "Exclusion_List.csv")
    if not os.path.exists(path):
        log.warning("Exclusion list not found at %s", path)
        return set()
    df = pd.read_csv(path)
    exclusion_set = set(df.iloc[:, 0].astype(str))
    log.info("Loaded %d exclusion sequences", len(exclusion_set))
    return exclusion_set


# ══════════════════════════════════════════════════════════════════════════════
# MSA 解析
# ══════════════════════════════════════════════════════════════════════════════
def parse_stockholm_msa(filepath):
    """解析 Stockholm 格式 MSA (jackhmmer 输出)"""
    sequences = {}
    current_name = None
    current_seq = []

    with open(filepath, "r") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("#") or line.startswith("//"):
                continue
            if line.startswith("#=GF"):
                continue  # GF 注释行
            if line.strip() == "":
                continue

            # Stockholm: name + whitespace + sequence
            parts = line.split()
            if len(parts) >= 2:
                name = parts[0]
                seq_fragment = parts[1].upper().replace(".", "-").replace("~", "-")

                if name == current_name:
                    current_seq.append(seq_fragment)
                else:
                    if current_name and current_seq:
                        sequences[current_name] = "".join(current_seq)
                    current_name = name
                    current_seq = [seq_fragment]

    if current_name and current_seq:
        sequences[current_name] = "".join(current_seq)

    log.info("Parsed Stockholm MSA: %d sequences", len(sequences))
    return sequences


def parse_fasta_msa(filepath):
    """解析 FASTA 格式 MSA"""
    sequences = {}  # preserve insertion order
    current_header = ""
    seq_lines = []
    order = []

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                if current_header and seq_lines:
                    seq = "".join(seq_lines)
                    sequences[current_header] = seq
                    order.append(current_header)
                current_header = line[1:]
                seq_lines = []
            elif line:
                seq_lines.append(line.upper().replace(".", "-").replace("~", "-"))

    if current_header and seq_lines:
        sequences[current_header] = "".join(seq_lines)
        order.append(current_header)

    log.info("Parsed FASTA MSA: %d sequences", len(sequences))
    return sequences, order


def build_test_msa(sfgfp_seq, ref_seqs=None):
    """
    构建测试用迷你 MSA（本地无服务器 MSA 时使用）。
    使用 MAFFT 风格的渐进比对 — 这里简化：将所有参考序列与 sfGFP 对齐，
    仅保留与 sfGFP 相同长度的序列 (238aa)。
    """
    if ref_seqs is None:
        ref_seqs = load_all_reference_sequences()

    msa_seqs = {"sfGFP": sfgfp_seq}

    for name, seq in ref_seqs.items():
        if "sfGFP" in name:
            continue
        if len(seq) == len(sfgfp_seq):
            msa_seqs[name] = seq
        elif abs(len(seq) - len(sfgfp_seq)) <= 3:
            # 尝试简单对齐：基于公共 N/C 端
            n_match = 0
            for i in range(min(10, min(len(seq), len(sfgfp_seq)))):
                if seq[i] == sfgfp_seq[i]:
                    n_match += 1
            if n_match >= 7:
                # 填充至相同长度
                if len(seq) < len(sfgfp_seq):
                    seq = seq + "-" * (len(sfgfp_seq) - len(seq))
                else:
                    seq = seq[:len(sfgfp_seq)]
                msa_seqs[name[:30]] = seq

    log.info("Built test MSA: %d sequences × %d positions",
             len(msa_seqs), len(sfgfp_seq))
    return msa_seqs


def msa_to_array(msa_seqs, ref_length=238):
    """
    将 MSA 字典转换为 numpy 数组 (N × L × 21)。
    21 维 = 20 种氨基酸 + gap。
    只保留长度与参考序列一致 (238aa) 的序列。
    """
    valid_seqs = []
    for name, seq in msa_seqs.items():
        if len(seq) == ref_length:
            valid_seqs.append(seq)
        elif len(seq) > ref_length:
            # 尝试智能截断
            valid_seqs.append(seq[:ref_length])

    if not valid_seqs:
        raise ValueError("No valid sequences in MSA (expected length %d)" % ref_length)

    N = len(valid_seqs)
    L = ref_length
    arr = np.zeros((N, L, 21), dtype=np.float32)

    for i, seq in enumerate(valid_seqs):
        for j, aa in enumerate(seq):
            if aa == "-":
                arr[i, j, GAP_IDX] = 1.0
            elif aa in AA_TO_IDX:
                arr[i, j, AA_TO_IDX[aa]] = 1.0
            # 忽略其他字符

    log.info("MSA → array: %d × %d × 21", N, L)
    return arr, valid_seqs


# ══════════════════════════════════════════════════════════════════════════════
# 位点频率与保守性
# ══════════════════════════════════════════════════════════════════════════════
def compute_frequency_matrix(msa_array, pseudocount=0.01):
    """
    计算位点频率矩阵 (L × 21)。
    pseudocount: Laplace 平滑参数
    """
    N, L, _ = msa_array.shape
    counts = msa_array.sum(axis=0)  # L × 21
    freq = (counts + pseudocount) / (N + 21 * pseudocount)
    log.info("Frequency matrix: %d × 21 (pseudocount=%.3f)", L, pseudocount)
    return freq


def compute_conservation(freq_matrix):
    """
    计算每个位点的保守性分数。
    使用 Shannon 熵：H(pos) = -Σ f(aa) × log2(f(aa))
    conservation = 1 - H(pos)/H_max
    H_max = log2(20) 对于 20 种氨基酸（不含 gap）
    """
    L = freq_matrix.shape[0]
    H_max = np.log2(20)

    conservation = np.zeros(L)
    entropy = np.zeros(L)

    for pos in range(L):
        # 只考虑20种氨基酸，排除gap
        aa_freqs = freq_matrix[pos, :20]
        # 重新归一化
        total = aa_freqs.sum()
        if total > 0:
            aa_freqs = aa_freqs / total
            # Shannon 熵
            h = 0.0
            for f in aa_freqs:
                if f > 1e-10:
                    h -= f * np.log2(f)
            entropy[pos] = h
            conservation[pos] = 1.0 - h / H_max
        else:
            entropy[pos] = H_max
            conservation[pos] = 0.0

    log.info("Conservation: mean=%.3f, range=[%.3f, %.3f]",
             conservation.mean(), conservation.min(), conservation.max())
    return conservation, entropy


def compute_cooccurrence(msa_array, freq_matrix):
    """
    计算位点对之间的共现频率矩阵。
    返回简化表示：对于每个位点对 (i,j)，存储 top co-occurring AA pairs。
    使用伪计数避免 log(0)。
    """
    N, L, _ = msa_array.shape
    pseudocount = 0.01
    top_pairs = {}  # {(i,j): [(aa_i, aa_j, enrichment), ...]}

    log.info("Computing co-occurrence for %d position pairs...", L * (L-1) // 2)
    log.info("  (this may take 1-2 minutes for large MSAs)")

    # 将 MSA 转为整数标签 (N × L)
    labels = np.argmax(msa_array[:, :, :20], axis=2)  # N × L (AA indices only)

    # 只检查距离 > 5 的位点对（避免局部序列相关性）
    n_pairs = 0
    for i in range(L):
        if (i + 1) % 50 == 0:
            log.info("  co-occurrence: position %d/%d done", i + 1, L)
        for j in range(i + 6, L):  # 跳过相邻位点
            n_pairs += 1
            # 联合频率 f_ij(a,b)
            joint = np.zeros((20, 20))
            for s in range(N):
                ai = labels[s, i]
                aj = labels[s, j]
                joint[ai, aj] += 1

            joint = (joint + pseudocount) / (N + 400 * pseudocount)
            marg_i = freq_matrix[i, :20] + pseudocount
            marg_i = marg_i / marg_i.sum()
            marg_j = freq_matrix[j, :20] + pseudocount
            marg_j = marg_j / marg_j.sum()

            # 寻找 enrichment > 1.5 的 AA pairs
            enriched = []
            for ai in range(20):
                for aj in range(20):
                    if marg_i[ai] > 0.01 and marg_j[aj] > 0.01:
                        expected = marg_i[ai] * marg_j[aj]
                        if expected > 0:
                            enrichment = joint[ai, aj] / expected
                            if enrichment > 1.5 and joint[ai, aj] > 0.001:
                                enriched.append((
                                    AMINO_ACIDS[ai],
                                    AMINO_ACIDS[aj],
                                    round(enrichment, 2)
                                ))

            if enriched:
                enriched.sort(key=lambda x: -x[2])
                top_pairs[(i, j)] = enriched[:10]  # 保留 top 10

    log.info("Co-occurrence: %d significant pairs found (out of %d checked)",
             len(top_pairs), n_pairs)
    return top_pairs


# ══════════════════════════════════════════════════════════════════════════════
# 突变评分
# ══════════════════════════════════════════════════════════════════════════════
def score_single_mutations(wt_seq, freq_matrix, conservation):
    """
    对所有设计位点上的所有可能突变打分。
    score(pos, new_aa) = freq_msa(pos, new_aa) × blosum_norm(wt_aa, new_aa) × (1 + conservation(pos))

    返回: [(pos, wt_aa, new_aa, score, freq, blosum, cons), ...]
    """
    L = len(wt_seq)
    scored = []

    for pos in range(1, L + 1):
        if pos in LEVEL1_POSITIONS:
            continue  # Level 1 不可突变

        wt_aa = wt_seq[pos - 1]
        cons = conservation[pos - 1]

        # Level 2: 仅允许预定义的替换
        if pos in LEVEL2_POSITIONS:
            allowed = LEVEL2_ALLOWED.get(pos, [])
            for new_aa in allowed:
                if new_aa == wt_aa:
                    continue
                freq = freq_matrix[pos - 1, AA_TO_IDX[new_aa]]
                blosum = blosum_norm(wt_aa, new_aa)
                score = freq * blosum * (1.0 + cons)
                scored.append((pos, wt_aa, new_aa, score, freq, blosum, cons))
            continue

        # Level 3: 所有氨基酸候选（按 BLOSUM62 过滤 + MSA 频率）
        for new_aa in AMINO_ACIDS:
            if new_aa == wt_aa:
                continue
            # 阻止 sfGFP 核心突变逆回
            if pos in SGFP_CORE_AVGFP_RESIDUE and new_aa == SGFP_CORE_AVGFP_RESIDUE[pos]:
                continue
            # BLOSUM62 过滤：仅考虑正分或中性的替换
            blosum = blosum_norm(wt_aa, new_aa)
            if blosum < 0.1:  # BLOSUM62 原始分 < -2 → 跳过
                continue
            freq = freq_matrix[pos - 1, AA_TO_IDX[new_aa]]
            # 加权评分：频率 × BLOSUM × 保守性bonus
            score = freq * 0.6 + blosum * 0.3 + cons * 0.1
            scored.append((pos, wt_aa, new_aa, score, freq, blosum, cons))

    scored.sort(key=lambda x: -x[3])
    log.info("Scored %d single mutations", len(scored))
    return scored


# ══════════════════════════════════════════════════════════════════════════════
# 候选生成
# ══════════════════════════════════════════════════════════════════════════════
def generate_consensus_singles(wt_seq, scored_muts, top_n_singles=150):
    """
    从评分列表中生成单突变候选。
    每位点最多取 top 3 个突变。
    """
    # 按位点分组，每位点取 top 3
    pos_limited = {}
    for pos, wt_aa, new_aa, score, freq, blosum, cons in scored_muts:
        if pos not in pos_limited:
            pos_limited[pos] = []
        if len(pos_limited[pos]) < 3:
            pos_limited[pos].append((pos, wt_aa, new_aa, score, freq, blosum, cons))

    # 展开并取全局 top N
    all_filtered = []
    for pos, muts in pos_limited.items():
        all_filtered.extend(muts)
    all_filtered.sort(key=lambda x: -x[3])
    all_filtered = all_filtered[:top_n_singles]

    # 构建候选
    candidates = []
    for i, (pos, wt_aa, new_aa, score, freq, blosum, cons) in enumerate(all_filtered):
        mutations = {pos: new_aa}
        seq = apply_mutations(wt_seq, mutations)
        mut_str = f"{wt_aa}{pos}{new_aa}"

        candidates.append({
            "seq_id": f"SD_C_S{i:04d}",
            "sequence": seq,
            "mutation_str": mut_str,
            "num_mutations": 1,
            "positions_mutated": str(pos),
            "constraint_max": 2 if pos in LEVEL2_POSITIONS else 3,
            "level2_warning": pos in LEVEL2_POSITIONS,
            "level2_positions": str(pos) if pos in LEVEL2_POSITIONS else "",
            "regions": get_region(pos),
            "source_scheme": "consensus",
            "consensus_score": round(score, 4),
            "msa_frequency": round(freq, 4),
            "blosum_score": round(blosum, 4),
            "conservation": round(cons, 4),
        })

    log.info("Generated %d single-mutant consensus candidates", len(candidates))
    return candidates


def get_cooccurrence_bonus(mutations, cooccurrence_data):
    """
    计算突变组合的共现奖励因子。
    如果两个突变位点在 MSA 中经常共现，给奖励分。
    """
    if len(mutations) < 2:
        return 1.0

    pos_list = sorted(mutations.keys())
    bonuses = []

    for i in range(len(pos_list)):
        for j in range(i + 1, len(pos_list)):
            p1, p2 = pos_list[i], pos_list[j]
            p1_0, p2_0 = p1 - 1, p2 - 1  # 0-based
            aa1, aa2 = mutations[p1], mutations[p2]

            key = (min(p1_0, p2_0), max(p1_0, p2_0))
            if key in cooccurrence_data:
                for a1, a2, enrich in cooccurrence_data[key]:
                    if a1 == aa1 and a2 == aa2:
                        bonuses.append(min(enrich, 3.0))  # cap at 3x
                        break

    if bonuses:
        return 1.0 + 0.15 * sum(bonuses)
    return 1.0


def generate_consensus_doubles(wt_seq, scored_muts, cooccurrence_data,
                                top_n_singles=50, max_doubles=600):
    """
    生成双突变共识候选。
    从 top N 单突变中跨区域配对，考虑共现奖励。
    """
    # 取 top N 单突变，确保跨区域多样性
    top_singles = scored_muts[:top_n_singles]

    # 按位点分组，每位点取 best mutation
    best_per_pos = {}
    for pos, wt_aa, new_aa, score, freq, blosum, cons in top_singles:
        if pos not in best_per_pos or score > best_per_pos[pos][0]:
            best_per_pos[pos] = (score, pos, wt_aa, new_aa, freq, blosum, cons)

    positions = sorted(best_per_pos.keys())
    candidates = []

    for i in range(len(positions)):
        pos1 = positions[i]
        score1, _, wt1, aa1, f1, bl1, c1 = best_per_pos[pos1]
        region1 = get_region(pos1)

        for j in range(i + 1, len(positions)):
            pos2 = positions[j]
            score2, _, wt2, aa2, f2, bl2, c2 = best_per_pos[pos2]
            region2 = get_region(pos2)

            # 跳过相邻位点 (空间冲突风险高)
            if abs(pos1 - pos2) <= 1:
                continue
            # 两个 Level 2 不能同时突变
            if pos1 in LEVEL2_POSITIONS and pos2 in LEVEL2_POSITIONS:
                continue
            # 同区配对仅允许 hydrophobic_core 和 surface
            if region1 == region2 and region1 not in ("hydrophobic_core", "surface", "beta_core"):
                continue

            mutations = {pos1: aa1, pos2: aa2}
            seq = apply_mutations(wt_seq, mutations)
            mut_str = f"{wt1}{pos1}{aa1}:{wt2}{pos2}{aa2}"

            # 计算共现奖励
            cooc_bonus = get_cooccurrence_bonus(mutations, cooccurrence_data)

            # 综合评分
            pair_score = (score1 + score2) * cooc_bonus

            candidates.append({
                "seq_id": "",  # 稍后填充
                "sequence": seq,
                "mutation_str": mut_str,
                "num_mutations": 2,
                "positions_mutated": f"{pos1},{pos2}",
                "constraint_max": max(
                    2 if pos1 in LEVEL2_POSITIONS else 3,
                    2 if pos2 in LEVEL2_POSITIONS else 3,
                ),
                "level2_warning": pos1 in LEVEL2_POSITIONS or pos2 in LEVEL2_POSITIONS,
                "level2_positions": ",".join(
                    str(p) for p in [pos1, pos2] if p in LEVEL2_POSITIONS
                ),
                "regions": f"{region1};{region2}",
                "source_scheme": "consensus",
                "consensus_score": round(pair_score, 4),
                "msa_frequency": round((f1 + f2) / 2, 4),
                "blosum_score": round((bl1 + bl2) / 2, 4),
                "conservation": round((c1 + c2) / 2, 4),
                "cooccurrence_bonus": round(cooc_bonus, 2),
            })

    # 按综合评分排序，取 top max_doubles
    candidates.sort(key=lambda x: -x["consensus_score"])
    candidates = candidates[:max_doubles]

    # 填充 seq_id
    for i, c in enumerate(candidates):
        c["seq_id"] = f"SD_C_D{i:04d}"

    log.info("Generated %d double-mutant consensus candidates", len(candidates))
    return candidates


# ══════════════════════════════════════════════════════════════════════════════
# 约束过滤
# ══════════════════════════════════════════════════════════════════════════════
def filter_constraints(candidates, wt_seq):
    """
    应用三级约束过滤:
    1. Level 1 位点不可突变
    2. sfGFP 核心突变不可逆回 avGFP 身份
    3. 序列去重
    """
    passed = []
    seen_seqs = set()

    for c in candidates:
        seq = c["sequence"]

        # 1. Level 1 检查
        violation = False
        for pos in LEVEL1_POSITIONS:
            if seq[pos - 1] != wt_seq[pos - 1]:
                violation = True
                break
        if violation:
            continue

        # 2. sfGFP 核心逆转检查
        core_violation = False
        for pos, avGFP_res in SGFP_CORE_AVGFP_RESIDUE.items():
            if seq[pos - 1] == avGFP_res:
                core_violation = True
                break
        if core_violation:
            continue

        # 3. 去重
        if seq in seen_seqs:
            continue
        seen_seqs.add(seq)

        passed.append(c)

    removed = len(candidates) - len(passed)
    if removed > 0:
        log.info("Constraint filter: %d → %d (%d removed)",
                 len(candidates), len(passed), removed)
    return passed


def filter_exclusion_list(candidates, exclusion_set):
    """过滤排除名单"""
    if not exclusion_set:
        return candidates
    passed = [c for c in candidates if c["sequence"] not in exclusion_set]
    removed = len(candidates) - len(passed)
    if removed > 0:
        log.warning("Exclusion list: %d sequences removed!", removed)
    else:
        log.info("Exclusion list: 0 hits [OK]")
    return passed


# ══════════════════════════════════════════════════════════════════════════════
# 输出
# ══════════════════════════════════════════════════════════════════════════════
def save_candidates(candidates, output_name="strategy_D_consensus_candidates.csv"):
    """保存候选序列 CSV"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, output_name)

    rows = []
    for c in candidates:
        rows.append({
            "seq_id": c["seq_id"],
            "sequence": c["sequence"],
            "mutation_str": c["mutation_str"],
            "num_mutations": c["num_mutations"],
            "positions_mutated": c["positions_mutated"],
            "constraint_max": c["constraint_max"],
            "level2_warning": c["level2_warning"],
            "level2_positions": c["level2_positions"],
            "regions": c["regions"],
            "source_scheme": c["source_scheme"],
            "consensus_score": c.get("consensus_score", ""),
            "msa_frequency": c.get("msa_frequency", ""),
            "cooccurrence_bonus": c.get("cooccurrence_bonus", ""),
        })

    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    log.info("Saved %d candidates → %s", len(df), path)
    return path


def save_conservation_profile(conservation, entropy, freq_matrix, wt_seq,
                               output_name="strategy_D_conservation_profile.csv"):
    """保存位点保守性概况"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, output_name)

    rows = []
    for pos in range(1, len(wt_seq) + 1):
        wt_aa = wt_seq[pos - 1]
        pos_freqs = freq_matrix[pos - 1]

        # Top 5 amino acids at this position (excluding gap)
        aa_freqs = [(AMINO_ACIDS[i], pos_freqs[i]) for i in range(20)]
        aa_freqs.sort(key=lambda x: -x[1])
        top5 = [f"{aa}:{freq:.3f}" for aa, freq in aa_freqs[:5]]

        rows.append({
            "position": pos,
            "wt_residue": wt_aa,
            "region": get_region(pos),
            "v3_level": 1 if pos in LEVEL1_POSITIONS else (2 if pos in LEVEL2_POSITIONS else 3),
            "is_sfgfp_core": pos in SGFP_CORE_MUTATIONS,
            "entropy": round(entropy[pos - 1], 4),
            "conservation": round(conservation[pos - 1], 4),
            "top5_amino_acids": "; ".join(top5),
            "wt_frequency": round(pos_freqs[AA_TO_IDX.get(wt_aa, 20)], 4) if wt_aa in AA_TO_IDX else 0,
        })

    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    log.info("Saved conservation profile → %s", path)
    return path


def save_msa_stats(msa_seqs, conservation, output_name="strategy_D_msa_stats.txt"):
    """保存 MSA 统计信息"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, output_name)

    with open(path, "w", encoding="utf-8") as f:
        f.write("Strategy D — MSA Statistics\n")
        f.write("=" * 60 + "\n")
        f.write(f"Total sequences: {len(msa_seqs)}\n")

        lengths = [len(s) for s in msa_seqs.values()]
        f.write(f"Sequence length range: {min(lengths)}–{max(lengths)}\n")

        f.write(f"Conservation mean: {conservation.mean():.4f}\n")
        f.write(f"Conservation std:  {conservation.std():.4f}\n")
        f.write(f"Conservation min:  {conservation.min():.4f}\n")
        f.write(f"Conservation max:  {conservation.max():.4f}\n\n")

        # Top 20 最保守位点
        f.write("Top 20 most conserved positions:\n")
        f.write("-" * 40 + "\n")
        ranked = sorted(
            [(i + 1, conservation[i]) for i in range(len(conservation))],
            key=lambda x: -x[1]
        )
        for pos, cons in ranked[:20]:
            f.write(f"  Position {pos:3d}: conservation = {cons:.4f}\n")

    log.info("Saved MSA stats → %s", path)
    return path


# ══════════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════════
def run_phase1(args):
    """运行 Phase 1: MSA + 保守性共识分析"""
    log.info("=" * 60)
    log.info("STRATEGY D — Phase 1: MSA Consensus Analysis")
    log.info("=" * 60)

    # ---- 1. 加载数据 ----
    log.info("Step 1: Loading reference sequences...")
    wt_seq = load_sfgfp_sequence()
    log.info("  sfGFP WT: %d aa", len(wt_seq))

    exclusion_set = load_exclusion_list()

    # ---- 2. 加载或构建 MSA ----
    log.info("Step 2: Loading MSA...")
    if args.msa:
        if args.mafft:
            # MAFFT 多行比对格式 → 以 sfGFP 为参考，剥除插入列
            msa_seqs, wt_seq_clean = parse_mafft_alignment(args.msa, ref_name="sfGFP")
            log.info("  Loaded MAFFT MSA: %d sequences × %d positions (reference-stripped)",
                     len(msa_seqs), len(wt_seq_clean))
            # 验证 MAFFT 版参考序列与 FASTA 版一致
            if wt_seq_clean != wt_seq:
                log.warning("  MAFFT reference differs from FASTA! Using MAFFT version.")
            wt_seq = wt_seq_clean
        elif args.msa.endswith(".sto") or args.msa.endswith(".stockholm"):
            msa_seqs = parse_stockholm_msa(args.msa)
            log.info("  Loaded Stockholm MSA: %d sequences", len(msa_seqs))
        elif args.msa.endswith(".a3m"):
            msa_seqs = parse_a3m_msa(args.msa)
            log.info("  Loaded A3M MSA: %d sequences", len(msa_seqs))
        else:
            msa_seqs, _ = parse_fasta_msa(args.msa)
            log.info("  Loaded FASTA MSA: %d sequences", len(msa_seqs))
    elif args.test_mode:
        # 测试模式：用参考序列构建迷你 MSA
        log.info("  TEST MODE: building mini-MSA from reference sequences")
        ref_seqs = load_all_reference_sequences()
        msa_seqs = build_test_msa(wt_seq, ref_seqs)
    else:
        log.error("No MSA file provided. Use --msa <file> or --test-mode")
        log.info("To generate MSA on server:")
        log.info("  jackhmmer -N 3 -A gfp_msa.sto --incE 1e-10 sfGFP.fasta uniprot_sprot.fasta")
        sys.exit(1)

    if len(msa_seqs) < 3:
        log.error("MSA too small (%d sequences). Need at least 3.", len(msa_seqs))
        sys.exit(1)

    # ---- 3. 转换 MSA 为数组 ----
    log.info("Step 3: Converting MSA to frequency array...")
    msa_array, valid_seqs = msa_to_array(msa_seqs, len(wt_seq))

    # ---- 4. 计算频率矩阵 ----
    log.info("Step 4: Computing frequency matrix...")
    freq_matrix = compute_frequency_matrix(msa_array)

    # ---- 5. 保守性分析 ----
    log.info("Step 5: Computing conservation scores...")
    conservation, entropy = compute_conservation(freq_matrix)

    # 保存保守性概况
    cons_path = save_conservation_profile(conservation, entropy, freq_matrix, wt_seq)
    save_msa_stats(msa_seqs, conservation)

    if args.analyze_only:
        log.info("Analysis complete (--analyze-only). Output: %s", cons_path)
        return

    # ---- 6. 共现分析 ----
    log.info("Step 6: Computing co-occurrence...")
    cooccurrence_data = compute_cooccurrence(msa_array, freq_matrix)

    # ---- 7. 突变评分 ----
    log.info("Step 7: Scoring mutations...")
    scored_muts = score_single_mutations(wt_seq, freq_matrix, conservation)

    # 打印 top 20 突变供检查
    log.info("  Top 20 consensus mutations:")
    for i, (pos, wt, new, score, freq, bl, cs) in enumerate(scored_muts[:20]):
        log.info("    %2d. %s%d%s  score=%.4f  freq=%.4f  blosum=%.3f  cons=%.3f",
                 i + 1, wt, pos, new, score, freq, bl, cs)

    # ---- 8. 生成候选 ----
    log.info("Step 8: Generating consensus candidates...")
    single_candidates = generate_consensus_singles(wt_seq, scored_muts, top_n_singles=150)
    double_candidates = generate_consensus_doubles(
        wt_seq, scored_muts, cooccurrence_data,
        top_n_singles=50, max_doubles=600
    )

    all_candidates = single_candidates + double_candidates
    log.info("  Total before filtering: %d", len(all_candidates))

    # ---- 9. 约束过滤 ----
    log.info("Step 9: Applying constraint filters...")
    all_candidates = filter_constraints(all_candidates, wt_seq)
    all_candidates = filter_exclusion_list(all_candidates, exclusion_set)
    log.info("  Final candidates: %d", len(all_candidates))

    # ---- 10. 保存 ----
    log.info("Step 10: Saving outputs...")
    csv_path = save_candidates(all_candidates)

    # 按方案分布
    n_singles = sum(1 for c in all_candidates if c["num_mutations"] == 1)
    n_doubles = sum(1 for c in all_candidates if c["num_mutations"] == 2)
    log.info("  Singles: %d, Doubles: %d", n_singles, n_doubles)

    log.info("=" * 60)
    log.info("Phase 1 complete! %d consensus candidates → %s", len(all_candidates), csv_path)
    log.info("=" * 60)

    return freq_matrix, conservation, scored_muts, all_candidates


def parse_a3m_msa(filepath):
    """解析 A3M 格式 MSA (用于 HHblits 输出)"""
    sequences = {}
    name = None
    seq_parts = []

    with open(filepath, "r") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith(">"):
                if name and seq_parts:
                    seq = "".join(seq_parts).upper()
                    sequences[name] = seq
                name = line[1:]
                seq_parts = []
            elif not line.startswith("#"):
                # A3M: lowercase = insert, uppercase/dash = match
                seq_parts.append(line.upper().replace(".", "-"))

    if name and seq_parts:
        sequences[name] = "".join(seq_parts).upper()

    log.info("Parsed A3M MSA: %d sequences", len(sequences))
    return sequences


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="Strategy D Phase 1: MSA Consensus Analysis"
    )
    parser.add_argument("--msa", type=str, default=None,
                        help="Path to MSA file (Stockholm/FASTA/A3M format)")
    parser.add_argument("--mafft", action="store_true",
                        help="MSA is MAFFT alignment format (multi-line, gap-stripped vs sfGFP)")
    parser.add_argument("--test-mode", action="store_true",
                        help="Run with mini-MSA from reference sequences (local testing)")
    parser.add_argument("--analyze-only", action="store_true",
                        help="Only compute conservation, skip candidate generation")
    args = parser.parse_args()

    if not args.msa and not args.test_mode:
        parser.error("Either --msa or --test-mode is required")

    run_phase1(args)


if __name__ == "__main__":
    main()
