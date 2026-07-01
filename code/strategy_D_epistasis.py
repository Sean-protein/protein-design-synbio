# -*- coding: utf-8 -*-
"""
策略D Phase 3：上位性规则 (Epistasis Rules)
===========================================
从 MSA 共进化信号中提取残基对之间的耦合关系，生成 238×238 的共进化矩阵
和上位性过滤规则。这些规则供策略 B/C/E 使用，确保突变组合尊重进化约束。

算法：
  1. 从 MSA 频率矩阵计算加权互信息 (MI)
  2. APC (Average Product Correction) 消除系统偏差
  3. Z-score 阈值识别显著共进化对
  4. 生成 synergistic（协同）和 antagonistic（拮抗）规则
  5. 对现有候选序列进行上位性合规检查

用法:
  # 从 Phase 1 的 MSA 文件计算
  python code/strategy_D_epistasis.py --msa gfp_msa_full.fasta --mafft

  # 从已有的频率矩阵加载（跳过 MSA 解析）
  python code/strategy_D_epistasis.py --freq-matrix results/freq_matrix.npy
"""

import argparse
import json
import logging
import os
import sys
import time

import numpy as np
import pandas as pd

# ══════════════════════════════════════════════════════════════════════════════
# 路径与常量
# ══════════════════════════════════════════════════════════════════════════════
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"
AA_TO_IDX = {aa: i for i, aa in enumerate(AMINO_ACIDS)}
N_AA = 20

# 约束常量
LEVEL1 = {65, 66, 67, 71, 96, 222}
LEVEL2 = {69, 94, 148, 203, 205}


# ══════════════════════════════════════════════════════════════════════════════
# MSA 解析 (与 Phase 1 共享逻辑)
# ══════════════════════════════════════════════════════════════════════════════
def parse_mafft_msa(filepath, ref_name="sfGFP"):
    """解析 MAFFT 多行对齐，以 sfGFP 为参考剥离插入列"""
    raw = {}
    cur_name, cur_seq, order = None, [], []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if cur_name:
                    raw[cur_name] = "".join(cur_seq)
                    order.append(cur_name)
                cur_name = line[1:].split()[0] if line[1:].split() else line[1:]
                cur_seq = []
            else:
                cur_seq.append(line.upper().replace(".", "-").replace("~", "-"))
        if cur_name:
            raw[cur_name] = "".join(cur_seq)
            order.append(cur_name)

    # 找参考序列
    ref_key = None
    for k in raw:
        if ref_name.lower() in k.lower():
            ref_key = k
            break
    if ref_key is None:
        ref_key = order[0]

    ref_aligned = raw[ref_key]
    ref_positions = [i for i, ch in enumerate(ref_aligned) if ch != "-"]
    L = len(ref_positions)
    log.info("Reference '%s': %d positions stripped from %d alignment columns",
             ref_key[:30], L, len(ref_aligned))

    N = len(raw)
    msa_arr = np.zeros((N, L, N_AA), dtype=np.float32)
    valid = []
    for i, name in enumerate(order):
        full = raw[name]
        clean = "".join(full[j] if j < len(full) else "-" for j in ref_positions)
        if clean.count("-") < L * 0.9:
            for j, aa in enumerate(clean):
                if aa in AA_TO_IDX:
                    msa_arr[i, j, AA_TO_IDX[aa]] = 1.0
            valid.append(i)

    msa_arr = msa_arr[valid]
    log.info("MSA array: %d sequences × %d positions × 20AA", len(valid), L)
    return msa_arr, L


def compute_freq_matrix(msa_arr, pseudocount=0.01):
    """位点频率矩阵 L×20"""
    N, L, _ = msa_arr.shape
    return (msa_arr.sum(axis=0) + pseudocount) / (N + N_AA * pseudocount)


# ══════════════════════════════════════════════════════════════════════════════
# 互信息 + APC
# ══════════════════════════════════════════════════════════════════════════════
def compute_mi_matrix_from_freq(msa_arr, freq_matrix, pseudocount=0.01):
    """
    从 MSA 数组和频率矩阵计算加权互信息矩阵 (L×L)。

    MI(i,j) = Σ_a,b P_ij(a,b) × log[ P_ij(a,b) / (P_i(a) × P_j(b)) ]
    """
    N, L, _ = msa_arr.shape
    mi = np.zeros((L, L), dtype=np.float32)
    log.info("Computing MI for %d position pairs...", L * (L - 1) // 2)

    # 转为整数标签加速
    labels = np.argmax(msa_arr[:, :, :N_AA], axis=2)  # N × L

    t0 = time.time()
    n_done = 0
    for i in range(L):
        for j in range(i + 1, L):
            n_done += 1
            # 联合频率
            joint = np.zeros((N_AA, N_AA))
            for s in range(N):
                ai, aj = labels[s, i], labels[s, j]
                joint[ai, aj] += 1
            joint = (joint + pseudocount) / (N + N_AA * N_AA * pseudocount)

            marg_i = freq_matrix[i] + pseudocount / N_AA
            marg_i = marg_i / marg_i.sum()
            marg_j = freq_matrix[j] + pseudocount / N_AA
            marg_j = marg_j / marg_j.sum()

            # MI
            val = 0.0
            for ai in range(N_AA):
                for aj in range(N_AA):
                    if joint[ai, aj] > 1e-10 and marg_i[ai] > 1e-10 and marg_j[aj] > 1e-10:
                        expected = marg_i[ai] * marg_j[aj]
                        if expected > 1e-10:
                            ratio = joint[ai, aj] / expected
                            if ratio > 1.0:
                                val += joint[ai, aj] * np.log(ratio)
            mi[i, j] = val
            mi[j, i] = val

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            log.info("  MI: row %d/%d done (%.1fs)", i + 1, L, elapsed)

    log.info("MI matrix complete in %.1f seconds", time.time() - t0)
    return mi


def apc_correct(mi):
    """Average Product Correction (Dunn et al. 2008)"""
    L = mi.shape[0]
    mi_mean = mi.sum() / (L * L)
    mi_row_means = mi.sum(axis=1) / L

    apc = np.zeros_like(mi)
    for i in range(L):
        for j in range(L):
            apc[i, j] = mi[i, j] - (mi_row_means[i] * mi_row_means[j]) / max(mi_mean, 1e-10)

    return apc


def identify_significant_pairs(apc, z_threshold=3.0, min_distance=5):
    """
    识别显著共进化位点对。
    z-score > z_threshold 且距离 > min_distance。
    """
    L = apc.shape[0]
    # 计算 z-score
    upper = apc[np.triu_indices(L, k=1)]
    mean = upper.mean()
    std = upper.std()
    log.info("APC: mean=%.4f, std=%.4f, threshold=%.1f×std (z>%.1f)", mean, std, z_threshold, z_threshold)

    pairs = []
    for i in range(L):
        for j in range(i + min_distance, L):
            z = (apc[i, j] - mean) / max(std, 1e-10)
            if z > z_threshold:
                pairs.append({
                    "pos_i": i + 1,  # 1-based
                    "pos_j": j + 1,
                    "mi_raw": round(float(mi_raw[i, j]) if 'mi_raw' in dir() else apc[i, j], 6),
                    "mi_apc": round(float(apc[i, j]), 6),
                    "z_score": round(float(z), 2),
                    "distance": j - i,
                })

    pairs.sort(key=lambda x: -x["z_score"])
    log.info("Significant pairs (z>%.1f, d>%d): %d", z_threshold, min_distance, len(pairs))
    return pairs


def compute_conditional_spectra(msa_arr, freq_matrix, sig_pairs):
    """
    对显著位点对，计算条件突变谱。
    P(aa_j = Y | aa_i = X) 对比 P(aa_j = Y) 的富集比。
    """
    N, L, _ = msa_arr.shape
    labels = np.argmax(msa_arr[:, :, :N_AA], axis=2)

    rules = []
    for pair in sig_pairs[:500]:  # top 500 pairs
        i = pair["pos_i"] - 1
        j = pair["pos_j"] - 1

        for ai in range(N_AA):
            # 条件：position i = ai
            cond_mask = labels[:, i] == ai
            n_cond = cond_mask.sum()
            if n_cond < 3:
                continue

            for aj in range(N_AA):
                if ai == aj:
                    continue
                # 条件概率
                p_cond = (labels[cond_mask][:, j] == aj).mean()
                p_marginal = freq_matrix[j, aj]

                if p_marginal > 0.01 and p_cond > 0.01:
                    enrichment = p_cond / p_marginal
                    if enrichment > 2.0:  # 富集 > 2×
                        rules.append({
                            "type": "synergistic",
                            "trigger_pos": i + 1,
                            "trigger_aa": AMINO_ACIDS[ai],
                            "coupled_pos": j + 1,
                            "favored_aa": AMINO_ACIDS[aj],
                            "enrichment": round(float(enrichment), 2),
                            "z_score": pair["z_score"],
                            "confidence": "high" if enrichment > 3.0 else "medium",
                        })
                    elif p_cond < 0.005:  # 几乎不在条件中出现
                        rules.append({
                            "type": "antagonistic",
                            "trigger_pos": i + 1,
                            "trigger_aa": AMINO_ACIDS[ai],
                            "coupled_pos": j + 1,
                            "disallowed_aa": AMINO_ACIDS[aj],
                            "depletion": round(float(1.0 - float(p_cond)), 4),
                            "z_score": pair["z_score"],
                            "confidence": "medium",
                        })

    log.info("Generated %d epistasis rules (synergistic + antagonistic)", len(rules))
    return rules


# ══════════════════════════════════════════════════════════════════════════════
# 候选过滤
# ══════════════════════════════════════════════════════════════════════════════
def check_epistasis(mutation_str, rules, sfgfp_seq):
    """检查一个突变组合是否遵守上位性规则"""
    # 解析突变
    mutations = {}
    for part in mutation_str.split(":"):
        import re
        m = re.match(r"([A-Z])(\d+)([A-Z])", part)
        if m:
            mutations[int(m.group(2))] = m.group(3)

    violations = []
    bonuses = []

    for rule in rules:
        rpos = rule["trigger_pos"]
        raa = rule["trigger_aa"]
        cpos = rule["coupled_pos"]

        if rpos in mutations and mutations[rpos] == raa:
            coupled_aa = mutations.get(cpos)
            if rule["type"] == "synergistic":
                if coupled_aa is not None and coupled_aa != rule["favored_aa"]:
                    violations.append(
                        f"Pos {rpos}{raa}→{cpos} 应配合 {cpos}{rule['favored_aa']}，"
                        f"实际为 {cpos}{coupled_aa}"
                    )
                elif coupled_aa == rule["favored_aa"]:
                    bonuses.append(rule["enrichment"])
            elif rule["type"] == "antagonistic":
                if coupled_aa == rule.get("disallowed_aa"):
                    violations.append(
                        f"Pos {rpos}{raa} 与 {cpos}{coupled_aa} 进化拮抗"
                    )

    return violations, bonuses


def filter_candidates_by_epistasis(candidates_csv, rules, sfgfp_seq):
    """对候选 CSV 进行上位性合规检查"""
    if not os.path.exists(candidates_csv):
        log.warning("Candidate file not found: %s", candidates_csv)
        return None

    df = pd.read_csv(candidates_csv)
    log.info("Filtering %d candidates from %s", len(df), os.path.basename(candidates_csv))

    violations_list = []
    bonus_list = []
    for _, row in df.iterrows():
        mut_str = str(row.get("mutation_str", row.get("mutations", "")))
        viol, bonus = check_epistasis(mut_str, rules, sfgfp_seq)
        violations_list.append("; ".join(viol) if viol else "")
        bonus_list.append(sum(bonus) if bonus else 0.0)

    df["epistasis_violations"] = violations_list
    df["epistasis_bonus"] = bonus_list
    df["epistasis_ok"] = df["epistasis_violations"] == ""

    n_pass = df["epistasis_ok"].sum()
    n_fail = len(df) - n_pass
    log.info("  Pass: %d,  Fail: %d  (%.1f%% pass rate)",
             n_pass, n_fail, 100 * n_pass / max(len(df), 1))

    return df


# ══════════════════════════════════════════════════════════════════════════════
# 输出
# ══════════════════════════════════════════════════════════════════════════════
def sanitize(obj):
    """递归转换 numpy 类型为 Python 原生类型"""
    if isinstance(obj, (np.floating, np.float32, np.float64)):
        return float(obj)
    elif isinstance(obj, (np.integer, np.int32, np.int64)):
        return int(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize(v) for v in obj]
    return obj


def save_epistasis_rules(sig_pairs, rules, L):
    """保存上位性规则为 JSON"""
    os.makedirs(RESULTS_DIR, exist_ok=True)

    output = sanitize({
        "metadata": {
            "method": "MI + APC + Conditional Spectra",
            "n_positions": L,
            "n_significant_pairs": len(sig_pairs),
            "n_rules": len(rules),
            "synergistic": sum(1 for r in rules if r["type"] == "synergistic"),
            "antagonistic": sum(1 for r in rules if r["type"] == "antagonistic"),
        },
        "top_pairs": sig_pairs[:200],
        "rules": rules[:2000],
    })

    path = os.path.join(RESULTS_DIR, "strategy_D_epistasis_rules.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log.info("Epistasis rules → %s", path)
    return path


def save_epistasis_matrix(apc_matrix):
    """保存 APC 校正后的共进化矩阵"""
    path = os.path.join(RESULTS_DIR, "strategy_D_epistasis_matrix.csv")
    df = pd.DataFrame(apc_matrix)
    # 行/列标签 = 1-based positions
    df.index = [f"P{i+1}" for i in range(apc_matrix.shape[0])]
    df.columns = [f"P{i+1}" for i in range(apc_matrix.shape[1])]
    df.to_csv(path)
    log.info("Epistasis matrix (APC) → %s", path)
    return path


# ══════════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════════
def load_sfgfp():
    import re
    path = os.path.join(PROJECT_ROOT, "competition", "AAseqs of 5 GFP proteins_20260511.txt")
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


def run_phase3(args):
    log.info("=" * 60)
    log.info("STRATEGY D — Phase 3: Epistasis Analysis")
    log.info("=" * 60)

    # 1. 加载/计算频率矩阵
    sfgfp = load_sfgfp()
    L = len(sfgfp)

    if args.freq_matrix:
        freq = np.load(args.freq_matrix)
        log.warning("Loading precomputed frequency matrix (MSA data not available for MI)")
        log.warning("MI computation requires full MSA, not just frequencies. Use --msa instead.")
        if not args.msa:
            log.error("Need --msa for MI computation")
            sys.exit(1)

    if args.msa:
        log.info("Loading MSA from: %s", args.msa)
        if args.mafft:
            msa_arr, L = parse_mafft_msa(args.msa)
        else:
            log.error("Only MAFFT format currently supported. Use --mafft")
            sys.exit(1)

        freq = compute_freq_matrix(msa_arr)
        log.info("Frequency matrix: %d × 20", L)

        # 2. 计算 MI 矩阵
        mi_matrix = compute_mi_matrix_from_freq(msa_arr, freq)

        # 3. APC 校正
        apc_matrix = apc_correct(mi_matrix)
        log.info("APC correction applied. Range: [%.4f, %.4f]", apc_matrix.min(), apc_matrix.max())

        # 保存矩阵
        np.save(os.path.join(RESULTS_DIR, "mi_matrix.npy"), mi_matrix)
        np.save(os.path.join(RESULTS_DIR, "apc_matrix.npy"), apc_matrix)
        save_epistasis_matrix(apc_matrix)

        # 4. 识别显著对 (使用 APC 矩阵)
        sig_pairs = identify_significant_pairs(apc_matrix)

        # 5. 条件突变谱 → 上位性规则
        rules = compute_conditional_spectra(msa_arr, freq, sig_pairs)
        save_epistasis_rules(sig_pairs, rules, L)

    else:
        log.error("No input specified")
        sys.exit(1)

    # 6. 过滤已有候选（策略A + 策略D Phase 1/2）
    sfgfp_seq = sfgfp

    # 加载规则（从文件）
    rules_path = os.path.join(RESULTS_DIR, "strategy_D_epistasis_rules.json")
    with open(rules_path) as f:
        rules_data = json.load(f)
    all_rules = rules_data.get("rules", [])

    # 策略A 候选
    strat_a_path = os.path.join(RESULTS_DIR, "strategy_A_passed.csv")
    if os.path.exists(strat_a_path):
        df_a = filter_candidates_by_epistasis(strat_a_path, all_rules, sfgfp_seq)
        if df_a is not None:
            out_a = os.path.join(RESULTS_DIR, "strategy_A_epistasis_filtered.csv")
            df_a.to_csv(out_a, index=False)
            log.info("Strategy A filtered → %s", out_a)

    # 策略D 共识候选
    d_cons_path = os.path.join(RESULTS_DIR, "strategy_D_consensus_candidates.csv")
    if os.path.exists(d_cons_path):
        df_d = filter_candidates_by_epistasis(d_cons_path, all_rules, sfgfp_seq)
        if df_d is not None:
            out_d = os.path.join(RESULTS_DIR, "strategy_D_consensus_epistasis_filtered.csv")
            df_d.to_csv(out_d, index=False)

    # 策略D 嫁接候选
    d_graft_path = os.path.join(RESULTS_DIR, "strategy_D_feature_grafts.csv")
    if os.path.exists(d_graft_path):
        df_g = filter_candidates_by_epistasis(d_graft_path, all_rules, sfgfp_seq)
        if df_g is not None:
            out_g = os.path.join(RESULTS_DIR, "strategy_D_grafts_epistasis_filtered.csv")
            df_g.to_csv(out_g, index=False)

    log.info("=" * 60)
    log.info("Phase 3 complete!")
    log.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Strategy D Phase 3: Epistasis")
    parser.add_argument("--msa", type=str, help="Path to MSA file")
    parser.add_argument("--mafft", action="store_true", help="MSA is MAFFT format")
    parser.add_argument("--freq-matrix", type=str, help="Path to precomputed frequency matrix (.npy)")
    args = parser.parse_args()
    run_phase3(args)
