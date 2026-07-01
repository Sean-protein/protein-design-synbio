# -*- coding: utf-8 -*-
"""
策略C v2 — 数据驱动的 ProteinMPNN 重跑方案
============================================
基于项目全部可用数据的约束设计:

数据来源:
  策略D MSA:         135条GFP同源序列 → 238位点保守性概况
  策略D EVcouplings: 262共进化对 → 上位性约束
  策略A+D FoldX:     ~4,800条通过序列 → 位点突变耐受性
  三级约束体系:      Level1(6)+Level2(5)+Level3(~227)

核心改进 (vs v1):
  1. 固定位点: 6→16 (Level1 + 最保守的10个MSA位点)
  2. 温度: [0.05, 0.1, 0.2] (vs 原来的 0.1/0.3/0.5)
  3. 突变后过滤: 上位性规则(策略D) + MSA保守性 + 突变数上限
  4. 结合策略B ML亮度预测排序

用法:
  python strategy_C_proteinmpnn_v2.py --mpnn /path/to/ProteinMPNN \
      --msa results/strategy_D_conservation_profile.csv \
      --epistasis results/strategy_D_epistasis_matrix.csv
"""

import argparse, json, os, re, subprocess, sys
import numpy as np, pandas as pd

# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════
def _find_root():
    for d in [os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "/data2/fenghaohui"]:
        if os.path.exists(d): return d
    return os.getcwd()

ROOT = _find_root()
R_DIR = os.path.join(ROOT, "results", "strategy_C")
os.makedirs(R_DIR, exist_ok=True)

# sfGFP WT
SFGFP_WT = ("MSKGEELFTGVVPILVELDGDVNGHKFSVRGEGEGDATNGKLTLKFICTTGKLPVPWPTLVTT"
            "LTYGVQCFSRYPDHMKRHDFFKSAMPEGYVQERTISFKDDGTYKTRAEVKFEGDTLVNRIELK"
            "GIDFKEDGNILGHKLEYNFNSHNVYITADKQKNGIKANFKIRHNVEDGSVQLADHYQQNTPIG"
            "DGPVLLPDNHYLSTQSVLSKDPNEKRDHMVLLEFVTAAGITHGMDELYK")

# ── 三级约束 ──
# Level 1: 化学绝对不可变 (6个)
LEVEL1 = {65, 66, 67, 71, 96, 222}  # 1-based
# Level 2: 发色团H键网络 可探索需补偿 (5个)
LEVEL2 = {69, 94, 148, 203, 205}
# Level 3: MSA高度保守位点 (策略D数据) → 动态加载

# ── 采样参数 ──
TEMPERATURES_V2 = [0.05, 0.1, 0.2]  # 远低于v1的[0.1,0.3,0.5]
SEQ_PER_TEMP = 300


def find_mpnn_script(mpnn_dir):
    candidates = [
        os.path.join(mpnn_dir, "protein_mpnn_run.py"),
        os.path.join(mpnn_dir, "vanilla_proteinmpnn", "protein_mpnn_run.py"),
    ]
    for p in candidates:
        if os.path.exists(p): return p
    for root, dirs, files in os.walk(mpnn_dir):
        if "protein_mpnn_run.py" in files:
            return os.path.join(root, "protein_mpnn_run.py")
    raise FileNotFoundError("Cannot find protein_mpnn_run.py")


def load_msa_conservation(path):
    """加载策略D的MSA保守性数据, 返回 {position(1-based): conservation_score}"""
    if not path or not os.path.exists(path):
        print("  MSA conservation file not found, using Level1+2 only")
        return {}
    df = pd.read_csv(path)
    # 尝试自动检测列名
    pos_col = None; cons_col = None
    for c in df.columns:
        if c.lower() in ("position", "pos", "residue", "resi"):
            pos_col = c
        if c.lower() in ("conservation", "cons_score", "conservation_score"):
            cons_col = c
    if pos_col is None or cons_col is None:
        print("  WARNING: cannot parse MSA columns, skipping. Cols={}".format(list(df.columns)))
        return {}
    cons = {}
    for _, row in df.iterrows():
        pos = int(row[pos_col])
        score = float(row[cons_col])
        if 1 <= pos <= 238:
            cons[pos] = score
    print("  Loaded MSA conservation for {} positions".format(len(cons)))
    print("  Top-10 most conserved: {}".format(
        sorted(cons.items(), key=lambda x: -x[1])[:10]))
    return cons


def load_epistasis_rules(path, z_threshold=3.0):
    """从238x238上位性矩阵中提取显著共进化对.
    矩阵格式: 第1列=位点标签(P1-P238), 第2-239列=z-scores
    z>threshold → synergistic, z<-threshold → antagonistic
    """
    if not path or not os.path.exists(path):
        print("  Epistasis rules not found, skipping")
        return {}
    rules = {}
    try:
        df = pd.read_csv(path, index_col=0)
        # 行/列标签是 P1-P238, 提取数字
        def parse_pos(label):
            return int(str(label).lstrip('P'))
        positions = [parse_pos(c) for c in df.columns]

        synergistic = 0; antagonistic = 0
        for i, row_label in enumerate(df.index):
            p1 = parse_pos(row_label)
            for j, col_label in enumerate(df.columns):
                if i >= j: continue  # 只取上三角
                p2 = parse_pos(col_label)
                z = float(df.iloc[i, j])
                if np.isnan(z): continue
                if z > z_threshold:
                    rules[frozenset([p1, p2])] = "synergistic"
                    synergistic += 1
                elif z < -z_threshold:
                    rules[frozenset([p1, p2])] = "antagonistic"
                    antagonistic += 1
        print("  Extracted from matrix: {} synergistic + {} antagonistic = {} rules (|z|>{})".format(
            synergistic, antagonistic, len(rules), z_threshold))
    except Exception as e:
        print("  Epistasis loading failed: {}".format(e))
    return rules


def determine_fixed_positions(msa_cons, n_top=10):
    """
    固定位点 = Level1(6) + MSA最保守的Top-N(排除已在Level1中的)
    """
    fixed = set(LEVEL1)

    # 从MSA中选最保守的Top-N
    if msa_cons:
        sorted_pos = sorted(msa_cons.items(), key=lambda x: -x[1])
        added = 0
        for pos, score in sorted_pos:
            if pos not in fixed and score > 0.85:  # 高度保守
                fixed.add(pos)
                added += 1
                if added >= n_top:
                    break
        print("  Added {} MSA-conserved positions to fixed set".format(added))

    print("  Total fixed positions: {} ({:.0f}% of 238)".format(
        len(fixed), len(fixed)/238*100))
    print("  Fixed: {}".format(sorted(fixed)))
    return fixed


def run_mpnn(mpnn_script, pdb_path, chain, fixed_positions, temp, n_seq, out_dir):
    """运行一次 ProteinMPNN"""
    os.makedirs(out_dir, exist_ok=True)
    fixed_str = " ".join(str(p) for p in sorted(fixed_positions))

    cmd = [
        sys.executable, mpnn_script,
        "--pdb_path", pdb_path,
        "--chain", chain,
        "--fixed_positions", fixed_str,
        "--sampling_temp", str(temp),
        "--num_seq_per_target", str(n_seq),
        "--out_folder", out_dir,
        "--save_score", "1",
        "--save_probs", "0",
        "--batch_size", "1",
    ]
    print("  T={} {}seqs → {}".format(temp, n_seq, out_dir))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("  WARNING: rc={}, stderr={}".format(result.returncode, result.stderr[:200]))
    return result.returncode == 0


def parse_fasta(fasta_path, wt_seq):
    """解析ProteinMPNN FASTA输出"""
    seqs = {}
    cur_h, cur_s = None, []
    with open(fasta_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                if cur_h and cur_s:
                    s = fix_seq("".join(cur_s), wt_seq)
                    if s:
                        m = re.search(r"score=([\d.]+)", cur_h)
                        seqs[s] = float(m.group(1)) if m else np.nan
                cur_h, cur_s = line, []
            else:
                cur_s.append(line)
        if cur_h and cur_s:
            s = fix_seq("".join(cur_s), wt_seq)
            if s:
                m = re.search(r"score=([\d.]+)", cur_h)
                seqs[s] = float(m.group(1)) if m else np.nan
    return seqs


def fix_seq(raw, wt):
    """修复ProteinMPNN偏移+补齐"""
    raw = raw.strip()
    chars = []
    for i, ch in enumerate(raw):
        wt_idx = i + 1
        if ch in 'ACDEFGHIKLMNPQRSTVWY':
            chars.append(ch)
        elif wt_idx < len(wt):
            chars.append(wt[wt_idx])
        else:
            chars.append('G')
    seq = wt[0] + "".join(chars)
    if len(seq) < len(wt):
        seq = seq + wt[len(seq):]
    if len(seq) > len(wt):
        seq = seq[:len(wt)]
    return seq if len(seq) == len(wt) else None


def mutation_str(seq, wt):
    muts = []
    for i, (a, b) in enumerate(zip(seq, wt)):
        if a != b:
            muts.append("{}{}{}".format(b, i+1, a))
    return ":".join(muts) if muts else "WT"


def check_constraints(seq, wt, msa_cons, epistasis_rules, max_muts=40):
    """
    多维度过滤
    Returns: (pass, violations, flags)
    """
    violations = []
    flags = []
    mut_positions = set()

    for i, (a, b) in enumerate(zip(seq, wt)):
        if a != b:
            mut_positions.add(i + 1)  # 1-based

    num_muts = len(mut_positions)

    # 1. Level 1
    for pos in LEVEL1:
        if (pos - 1) < len(seq) and seq[pos - 1] != wt[pos - 1]:
            violations.append("L1_violation_{}".format(pos))

    # 2. Level 2
    for pos in LEVEL2:
        if (pos - 1) < len(seq) and seq[pos - 1] != wt[pos - 1]:
            flags.append("L2_mutated_{}".format(pos))

    # 3. 突变数限制
    if num_muts > max_muts:
        violations.append("too_many_muts_{}".format(num_muts))

    # 4. MSA 高度保守位点突变检查
    if msa_cons:
        for pos in mut_positions:
            if msa_cons.get(pos, 0) > 0.95:
                flags.append("MSA_ultra_conserved_{}".format(pos))

    # 5. 上位性规则检查
    if epistasis_rules:
        mut_set = frozenset(mut_positions)
        for pair, rtype in epistasis_rules.items():
            if pair.issubset(mut_set):
                if rtype == "antagonistic":
                    violations.append("epistasis_antagonist_{}".format(tuple(pair)))
                else:
                    flags.append("epistasis_synergistic_{}".format(tuple(pair)))

    passed = len(violations) == 0
    return passed, violations, flags, num_muts


def main():
    p = argparse.ArgumentParser(description="Strategy C v2: data-driven ProteinMPNN")
    p.add_argument("--mpnn", required=True, help="Path to ProteinMPNN directory")
    p.add_argument("--pdb", help="Path to sfGFP PDB")
    p.add_argument("--msa", help="Path to MSA conservation CSV (from strategy D)")
    p.add_argument("--epistasis", help="Path to epistasis rules CSV (from strategy D)")
    p.add_argument("--output", help="Output directory")
    p.add_argument("--max-muts", type=int, default=40, help="Max mutations allowed (default: 40)")
    p.add_argument("--temps", type=float, nargs="+", help="Temperatures (default: 0.05 0.1 0.2)")
    p.add_argument("--seq-per-temp", type=int, default=SEQ_PER_TEMP)
    args = p.parse_args()

    print("=" * 60)
    print("STRATEGY C v2 — Data-driven ProteinMPNN")
    print("=" * 60)

    # ── 加载外部数据 ──
    print("\n[1/5] Loading external data...")
    msa_cons = load_msa_conservation(args.msa) if args.msa else {}
    epistasis_rules = load_epistasis_rules(args.epistasis) if args.epistasis else {}

    # ── 确定固定位点 ──
    print("\n[2/5] Determining fixed positions...")
    fixed = determine_fixed_positions(msa_cons)
    print("  Level2 (flagged, not fixed): {}".format(sorted(LEVEL2)))

    # ── 定位MPNN和PDB ──
    print("\n[3/5] Setting up ProteinMPNN...")
    mpnn_script = find_mpnn_script(args.mpnn)
    print("  Script: {}".format(mpnn_script))

    pdb = args.pdb
    if pdb is None:
        for c in [os.path.join(ROOT, "data", "2B3P_sfGFP.pdb"),
                   "/data2/fenghaohui/data/2B3P_sfGFP.pdb"]:
            if os.path.exists(c): pdb = c; break
    if pdb is None:
        print("ERROR: PDB not found"); sys.exit(1)
    print("  PDB: {}".format(pdb))

    out_dir = args.output or os.path.join(R_DIR, "v2")
    temps = args.temps if args.temps else TEMPERATURES_V2
    n_seq = args.seq_per_temp

    # ── 运行采样 ──
    print("\n[4/5] Running ProteinMPNN ({} temps × {} seqs)...".format(
        len(temps), n_seq))

    all_seqs = {}
    for temp in temps:
        od = os.path.join(out_dir, "T{}".format(str(temp).replace(".", "_")))
        ok = run_mpnn(mpnn_script, pdb, "A", fixed, temp, n_seq, od)
        if not ok:
            continue

        # 解析输出
        seqs_dir = os.path.join(od, "seqs") if os.path.isdir(os.path.join(od, "seqs")) else od
        for fa in [f for f in os.listdir(seqs_dir) if f.endswith(".fa")]:
            seqs = parse_fasta(os.path.join(seqs_dir, fa), SFGFP_WT)
            for seq, score in seqs.items():
                if seq not in all_seqs or score > all_seqs[seq]["score"]:
                    all_seqs[seq] = {"score": score, "temp": temp}
        print("    T={}: {} unique (total: {})".format(temp, len(seqs), len(all_seqs)))

    print("  Total unique sequences: {}".format(len(all_seqs)))

    # ── 多维过滤 ──
    print("\n[5/5] Multi-dimensional filtering...")

    candidates = []
    for seq, meta in all_seqs.items():
        if len(seq) != len(SFGFP_WT):
            continue

        passed, violations, flags, nmuts = check_constraints(
            seq, SFGFP_WT, msa_cons, epistasis_rules, args.max_muts)

        candidates.append({
            "sequence": seq,
            "mutation_str": mutation_str(seq, SFGFP_WT),
            "num_mutations": nmuts,
            "mpnn_score": meta["score"],
            "temperature": meta["temp"],
            "passed_filter": passed,
            "violations": "|".join(violations) if violations else "",
            "flags": "|".join(flags) if flags else "",
            "level2_mutated": any(seq[pos-1] != SFGFP_WT[pos-1] for pos in LEVEL2
                                  if pos-1 < len(seq)),
        })

    df = pd.DataFrame(candidates)
    n_pass = df.passed_filter.sum()
    print("  Passed all filters: {} / {} ({:.0f}%)".format(n_pass, len(df), n_pass/len(df)*100))

    # 按温度分层统计
    for t in sorted(temps):
        sub = df[df.temperature == t]
        n_p = sub.passed_filter.sum()
        print("    T={}: {} total, {} pass, muts mean={:.0f}".format(
            t, len(sub), n_p, sub.num_mutations.mean()))

    # ── 排序保存 ──
    df = df.sort_values(["passed_filter", "mpnn_score"], ascending=[False, False])
    out_csv = os.path.join(out_dir, "strategy_C_v2_candidates.csv")
    df.to_csv(out_csv, index=False)
    print("  Saved → {}".format(out_csv))

    # ── 推荐 ──
    if n_pass > 0:
        print("\n" + "=" * 60)
        print("NEXT: {} candidates passed. Run ML scoring:".format(n_pass))
        print("  python score_strategy_C_v2.py")
        print("=" * 60)
    else:
        print("\n  WARNING: No candidates passed. Try --max-muts 50 or check MSA data.")


if __name__ == "__main__":
    main()
