# -*- coding: utf-8 -*-
"""Phase 1: 合规筛选 — 合并策略A/D/C候选池，长度/排除列表/CD-HIT过滤"""

import os
import sys
import re
import hashlib
import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
COMP_DIR = os.path.join(PROJECT_ROOT, "competition")
os.makedirs(RESULTS_DIR, exist_ok=True)

# 输入
STRAT_A_PASSED = os.path.join(RESULTS_DIR, "strategy_A_passed.csv")
STRAT_D_ALL = os.path.join(RESULTS_DIR, "strategy_D_all_candidates.csv")
STRAT_C_SCORED = os.path.join(RESULTS_DIR, "strategy_C", "strategy_C_ml_scored.csv")
EXCLUSION_LIST = os.path.join(COMP_DIR, "Exclusion_List.csv")

# 输出
OUTPUT_POOL = os.path.join(RESULTS_DIR, "funnel_phase1_pool.csv")

# 约束常量
LEVEL1_POSITIONS = {65, 66, 67, 71, 96, 222}  # 1-based
# 使用比赛参考序列中的sfGFP WT (competition/AAseqs of 5 GFP proteins_20260511.txt)
SFGFP_WT = "MSKGEELFTGVVPILVELDGDVNGHKFSVRGEGEGDATNGKLTLKFICTTGKLPVPWPTLVTTLTYGVQCFSRYPDHMKRHDFFKSAMPEGYVQERTISFKDDGTYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNFNSHNVYITADKQKNGIKANFKIRHNVEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSVLSKDPNEKRDHMVLLEFVTAAGITHGMDELYK"


def check_level1_constraints(seq, wt_seq=None, tolerance=0):
    """检查6个一级位点是否固定。1-based positions: 65,66,67,71,96,222

    位点71是sfGFP中的F71（原avGFP为R71，sfGFP骨架中为F），实际上
    v3.1规约中一级位点是G67/Y66/T65/R96/E222/发色团，共6个。
    位点71(R/Q)在v3.0中属于一级但标记了可探索。这里按规约检查5个核心位点。
    """
    if wt_seq is None:
        wt_seq = SFGFP_WT

    # 核心5个一级位点 (1-based index → 0-based Python)
    core_level1 = {64, 65, 66, 95, 221}  # 0-based: T65,Y66,G67,R96,E222
    # G67=index 66, Y66=index 65, T65=index 64, R96=index 95, E222=index 221

    failures = []
    for pos in core_level1:
        if pos >= len(seq):
            failures.append(f"pos_{pos+1}_out_of_range")
        elif seq[pos] != wt_seq[pos]:
            failures.append(f"pos_{pos+1}:{seq[pos]}!={wt_seq[pos]}")

    return len(failures) == 0, failures


def check_length(seq):
    """序列长度 220-250 aa"""
    return 220 <= len(seq) <= 250


def check_amino_acids(seq):
    """仅含20种标准氨基酸，以M开头"""
    valid_aa = set("ACDEFGHIKLMNPQRSTVWY")
    return seq[0] == 'M' and all(aa in valid_aa for aa in seq)


def load_exclusion_set(filepath):
    """加载排除列表到set，支持hash快速查找。处理135K条目。"""
    excluded = set()
    with open(filepath, 'r') as f:
        for line in f:
            seq = line.strip().replace('"', '').replace("'", "")
            if seq and not seq.startswith('#') and len(seq) > 20:
                excluded.add(seq)
    # 直接匹配用set，前缀/子串匹配用trie（对135K条高效）
    return excluded


def is_excluded(seq, exclusion_set):
    """检查序列是否在排除列表中（完全匹配）"""
    return seq in exclusion_set


def compute_seq_identity(seq1, seq2):
    """计算两条序列的序列相似度 = matches / min_len"""
    min_len = min(len(seq1), len(seq2))
    matches = sum(a == b for a, b in zip(seq1[:min_len], seq2[:min_len]))
    return matches / min_len if min_len > 0 else 0


def cdhit_cluster(sequences, threshold=0.90):
    """贪心聚类去冗余。返回代表序列索引列表。"""
    # 按长度降序排列，长序列优先作为representative
    indexed = [(i, seq) for i, seq in enumerate(sequences)]
    indexed.sort(key=lambda x: -len(x[1]))

    representatives = []
    clustered = set()

    for i, seq in indexed:
        if i in clustered:
            continue
        representatives.append(i)
        # 将此序列的所有高相似度序列标记为已聚类
        for j, other_seq in indexed:
            if j in clustered or j == i:
                continue
            if compute_seq_identity(seq, other_seq) >= threshold:
                clustered.add(j)

    return representatives


def load_strategy_A():
    """加载策略A FoldX通过的候选，附加完整序列和元数据"""
    df = pd.read_csv(STRAT_A_PASSED)
    df['source_strategy'] = 'A'
    # 确保序列列存在
    if 'sequence' not in df.columns:
        raise ValueError(f"策略A数据缺少sequence列，列名: {list(df.columns)}")
    return df


def load_strategy_D():
    """加载策略D全部候选"""
    df = pd.read_csv(STRAT_D_ALL)
    df['source_strategy'] = 'D'
    return df


def load_strategy_C(top_n=2):
    """加载策略C精选候选。选mpnn_score最高+pred_brightness>1.0的top 2条"""
    df = pd.read_csv(STRAT_C_SCORED)
    # 排除WT
    df = df[df['mutation_str'] != 'WT'].copy()
    # 组合评分：mpnn_score × pred_brightness
    df['c_composite'] = df['mpnn_score'] * df['pred_brightness'].clip(lower=0.5)
    df = df.sort_values('c_composite', ascending=False)
    selected = df.head(top_n).copy()
    selected['source_strategy'] = 'C'
    selected['seq_id'] = ['SC_C_' + str(i).zfill(4) for i in range(len(selected))]
    return selected


def create_mchartreuse_variant():
    """生成mChartreuse变体：sfGFP + N39I + I128S + D129G + F145Y + N149K + V206K
    注意：这些是sfGFP骨架上的突变（1-based positions）
    mChartreuse = sfGFP + {39:N→I, 128:I→S, 129:D→G, 145:F→Y, 149:N→K, 206:V→K}
    """
    seq = list(SFGFP_WT)
    mutations = {
        38: 'I',   # N39I (0-based index 38)
        127: 'S',  # I128S
        128: 'G',  # D129G
        144: 'Y',  # F145Y
        148: 'K',  # N149K
        205: 'K',  # V206K
    }
    for pos, aa in mutations.items():
        if pos < len(seq):
            seq[pos] = aa
    return "".join(seq)


def create_mchartreuse_rows():
    """生成mChartreuse的DataFrame行"""
    seq = create_mchartreuse_variant()
    return pd.DataFrame([{
        'seq_id': 'MC_mChartreuse_001',
        'sequence': seq,
        'mutation_str': 'N39I:I128S:D129G:F145Y:N149K:V206K',
        'num_mutations': 6,
        'positions_mutated': '39,128,129,145,149,206',
        'constraint_max': 3,
        'level2_warning': False,
        'level2_positions': '',
        'regions': 'beta_core;surface',
        'ddG_kcal_mol': None,  # 待FoldX评估
        'status': 'mchartreuse',
        'source_strategy': 'A',  # 归入策略A（理性工程衍生）
    }])


def main():
    print("=" * 60)
    print("Phase 1: 合规筛选")
    print("=" * 60)

    # 1. 加载排除列表
    print("\n[1/5] 加载排除列表...")
    exclusion_set = load_exclusion_set(EXCLUSION_LIST)
    print(f"  排除列表: {len(exclusion_set):,} 条")

    # 2. 加载各策略候选
    print("\n[2/5] 加载候选池...")
    df_a = load_strategy_A()
    df_d = load_strategy_D()
    df_c = load_strategy_C(top_n=2)
    df_mc = create_mchartreuse_rows()

    print(f"  策略A: {len(df_a)} 条")
    print(f"  策略D: {len(df_d)} 条")
    print(f"  策略C: {len(df_c)} 条")
    print(f"  mChartreuse: {len(df_mc)} 条")

    # 3. 统一列并合并
    print("\n[3/5] 合并候选池...")
    cols_common = ['seq_id', 'sequence', 'source_strategy']

    # 提取每组的核心列
    def normalize_df(df, strategy):
        out = pd.DataFrame()
        out['seq_id'] = df.get('seq_id', [f'{strategy}_' + str(i).zfill(4) for i in range(len(df))])
        out['sequence'] = df['sequence']
        out['source_strategy'] = strategy
        out['num_mutations'] = df.get('num_mutations', 0)
        out['mutation_str'] = df.get('mutation_str', '')
        out['level2_warning'] = df.get('level2_warning', False)
        out['level2_positions'] = df.get('level2_positions', '')
        out['ddG_kcal_mol'] = df.get('ddG_kcal_mol', None)
        out['mpnn_score'] = df.get('mpnn_score', None)
        out['consensus_score'] = df.get('consensus_score', None) if 'consensus_score' in df.columns else None
        return out

    df_a_norm = normalize_df(df_a, 'A')
    df_d_norm = normalize_df(df_d, 'D')
    df_c_norm = normalize_df(df_c, 'C')

    pool = pd.concat([df_a_norm, df_d_norm, df_c_norm, df_mc], ignore_index=True)
    print(f"  合并后: {len(pool)} 条")

    # 4. 合规检查
    print("\n[4/5] 合规检查...")

    # 长度检查
    mask_len = pool['sequence'].apply(check_length)
    print(f"  长度合规 (220-250): {mask_len.sum()}/{len(pool)}")

    # 氨基酸检查
    mask_aa = pool['sequence'].apply(check_amino_acids)
    print(f"  氨基酸合规 (M开头+20种AA): {mask_aa.sum()}/{len(pool)}")

    # 一级位点检查
    level1_results = pool['sequence'].apply(lambda s: check_level1_constraints(s)[0])
    print(f"  一级位点固定: {level1_results.sum()}/{len(pool)}")

    # 排除列表检查
    mask_excl = ~pool['sequence'].apply(lambda s: is_excluded(s, exclusion_set))
    print(f"  排除列表通过: {mask_excl.sum()}/{len(pool)}")

    # 综合过滤
    mask_all = mask_len & mask_aa & mask_excl & level1_results
    pool_filtered = pool[mask_all].copy()
    pool_filtered['passes_compliance'] = True
    print(f"\n  综合通过: {len(pool_filtered)}/{len(pool)} ({len(pool_filtered)/len(pool)*100:.1f}%)")

    # 5. 精确去重（去除跨策略完全重复的序列）
    print("\n[5/5] 精确去重...")
    seen = set()
    keep_idx = []
    for i, seq in enumerate(pool_filtered['sequence']):
        if seq not in seen:
            seen.add(seq)
            keep_idx.append(i)
    pool_final = pool_filtered.iloc[keep_idx].copy()
    print(f"  去重后: {len(pool_final)}/{len(pool_filtered)} ({len(pool_final)/max(1,len(pool_filtered))*100:.1f}%)")
    print("  注: CD-HIT 90%多样性检查将在Phase 5对最终6条序列执行")

    # 6. 保存
    pool_final.to_csv(OUTPUT_POOL, index=False)
    print(f"\n输出: {OUTPUT_POOL} ({len(pool_final)} 条)")

    # 统计
    print(f"\n策略分布:")
    for s in ['A', 'D', 'C']:
        count = (pool_final['source_strategy'] == s).sum()
        print(f"  {s}: {count} 条")
    print(f"  mChartreuse: {(pool_final['seq_id'] == 'MC_mChartreuse_001').sum()} 条")


if __name__ == '__main__':
    main()
