# -*- coding: utf-8 -*-
"""
策略C：ProteinMPNN 逆折叠多温度采样
=====================================
对 sfGFP 骨架 (PDB 2B3P) 运行 ProteinMPNN，在三级约束下
以多温度采样生成序列变体。

温度策略:
  T=0.1 (保守) — 倾向于 WT 氨基酸，200 条
  T=0.3 (平衡) — 适度探索，200 条
  T=0.5 (探索) — 高多样性，200 条

固定位点 (Level 1, 化学绝对):
  T65, Y66/CRO, G67, I71, R96, E222

用法:
  python strategy_C_proteinmpnn.py --pdb data/2B3P_sfGFP.pdb --mpnn /path/to/ProteinMPNN
"""

import argparse
import os
import re
import subprocess
import sys

import numpy as np
import pandas as pd

# ══════════════════════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════════════════════
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")

# Level 1 固定位点 (1-based sequence numbering = PDB numbering for sfGFP 2B3P)
LEVEL1_FIXED = {65, 66, 67, 71, 96, 222}

# Level 2 可探索但需补偿的位点
LEVEL2_WARNING = {69, 94, 148, 203, 205}

# sfGFP WT 序列
SFGFP_WT = ("MSKGEELFTGVVPILVELDGDVNGHKFSVRGEGEGDATNGKLTLKFICTTGKLPVPWPTLVTT"
            "LTYGVQCFSRYPDHMKRHDFFKSAMPEGYVQERTISFKDDGTYKTRAEVKFEGDTLVNRIELK"
            "GIDFKEDGNILGHKLEYNFNSHNVYITADKQKNGIKANFKIRHNVEDGSVQLADHYQQNTPIG"
            "DGPVLLPDNHYLSTQSVLSKDPNEKRDHMVLLEFVTAAGITHGMDELYK")

# 采样参数
TEMPERATURES = [0.1, 0.3, 0.5]
SEQ_PER_TEMP = 200


def find_mpnn_script(mpnn_dir):
    """定位 ProteinMPNN 主脚本。"""
    candidates = [
        os.path.join(mpnn_dir, "protein_mpnn_run.py"),
        os.path.join(mpnn_dir, "vanilla_proteinmpnn", "protein_mpnn_run.py"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    # fallback: search
    for root, dirs, files in os.walk(mpnn_dir):
        if "protein_mpnn_run.py" in files:
            return os.path.join(root, "protein_mpnn_run.py")
    raise FileNotFoundError(f"Cannot find protein_mpnn_run.py under {mpnn_dir}")


def get_pdb_numbering(pdb_path, chain="A"):
    """解析 PDB 的残基编号范围，确认固定位点都存在。"""
    residues = set()
    with open(pdb_path) as f:
        for line in f:
            if (line.startswith("ATOM") or line.startswith("HETATM")):
                if line[21] == chain:
                    resi = int(line[22:26].strip())
                    resn = line[17:20].strip()
                    residues.add(resi)
    return sorted(residues)


def run_mpnn(mpnn_script, pdb_path, chain, fixed_positions, temp, n_seq, out_dir):
    """运行一次 ProteinMPNN 采样。"""
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

    print(f"  Running: T={temp}, {n_seq} seqs → {out_dir}")
    print(f"  Fixed: {fixed_str}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  WARNING: ProteinMPNN returned {result.returncode}")
        print(f"  stderr: {result.stderr[:500]}")
    return result.returncode == 0


def parse_mpnn_fasta(fasta_path, wt_seq):
    """解析 ProteinMPNN FASTA 输出，返回 {sequence: score} dict。
    修复: N端补齐M, XXX→WT残基替换。"""
    seqs = {}
    cur_header = None
    cur_seq = []
    with open(fasta_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                if cur_header and cur_seq:
                    raw = "".join(cur_seq)
                    fixed = fix_mpnn_sequence(raw, wt_seq)
                    if fixed:
                        seqs[fixed] = _parse_score(cur_header)
                cur_header = line
                cur_seq = []
            else:
                cur_seq.append(line)
        if cur_header and cur_seq:
            raw = "".join(cur_seq)
            fixed = fix_mpnn_sequence(raw, wt_seq)
            if fixed:
                seqs[fixed] = _parse_score(cur_header)
    return seqs


def fix_mpnn_sequence(raw, wt_seq):
    """修复 ProteinMPNN 输出序列。

    ProteinMPNN 从 PDB residue 2 开始输出, 比全长序列偏移+1.
    例: 输出[0]=S(=wt[1]), 输出[63]对应 wt[64]=T65.
    发色团区域为 X, 需用 wt 对应位置氨基酸替换.
    """
    raw = raw.strip()
    wt_len = len(wt_seq)

    # 步骤1: 先替换非标准字符 (X/B 等)
    fixed_chars = []
    for i, ch in enumerate(raw):
        wt_idx = i + 1  # 输出位置 i 对应 wt 位置 i+1 (0-based)
        if ch in 'ACDEFGHIKLMNPQRSTVWY':
            fixed_chars.append(ch)
        elif wt_idx < wt_len:
            fixed_chars.append(wt_seq[wt_idx])
        else:
            fixed_chars.append('G')

    # 步骤2: 前面补 M (wt_seq[0])
    seq = wt_seq[0] + "".join(fixed_chars)

    # 步骤3: C端补齐（从PDB尾部截断的位置补齐 WT）
    if len(seq) < wt_len:
        seq = seq + wt_seq[len(seq):]

    # 步骤4: 截断到 WT 长度（如果过长）
    if len(seq) > wt_len:
        seq = seq[:wt_len]

    if len(seq) == wt_len:
        return seq
    return None


def _parse_score(header):
    """从 FASTA header 提取 score。"""
    m = re.search(r"score=([\d.]+)", header)
    return float(m.group(1)) if m else np.nan


def seq_to_mutation_str(seq, wt):
    """全长序列 → 突变字符串（相对于 sfGFP WT）。"""
    if len(seq) != len(wt):
        return "LENGTH_MISMATCH"
    muts = []
    for i, (a, b) in enumerate(zip(seq, wt)):
        if a != b:
            muts.append(f"{b}{i+1}{a}")
    return ":".join(muts) if muts else "WT"


def check_constraints(seq, wt):
    """
    检查三级约束合规性。
    Returns: (level1_ok, level2_warnings, level2_positions)
    """
    level1_violations = []
    level2_violations = []

    for pos in LEVEL1_FIXED:
        idx = pos - 1
        if idx < len(seq) and seq[idx] != wt[idx]:
            level1_violations.append(pos)

    for pos in LEVEL2_WARNING:
        idx = pos - 1
        if idx < len(seq) and seq[idx] != wt[idx]:
            level2_violations.append(pos)

    return (len(level1_violations) == 0,
            level2_violations,
            len(level2_violations) > 0)


def run_strategy_c(mpnn_dir, pdb_path, output_dir=None):
    """运行完整策略C流程。"""
    print("=" * 60)
    print("STRATEGY C — ProteinMPNN Inverse Folding")
    print("=" * 60)

    if output_dir is None:
        output_dir = os.path.join(RESULTS_DIR, "strategy_C")

    # ── 定位 ProteinMPNN ──
    mpnn_script = find_mpnn_script(mpnn_dir)
    print(f"ProteinMPNN script: {mpnn_script}")

    # ── PDB 编号检查 ──
    pdb_residues = get_pdb_numbering(pdb_path)
    print(f"PDB residues: {min(pdb_residues)}-{max(pdb_residues)} ({len(pdb_residues)} atoms)")

    # 确认 Level 1 固定位点在 PDB 中
    missing = LEVEL1_FIXED - set(pdb_residues)
    if missing:
        print(f"WARNING: Level 1 positions not in PDB: {missing}")
    fixed = LEVEL1_FIXED & set(pdb_residues)
    print(f"Fixed positions (Level 1): {sorted(fixed)}")

    # ── 加载 sfGFP WT ──
    wt_seq = SFGFP_WT

    # ── 多温度采样 ──
    all_seqs = {}  # sequence → {score, temp}
    for temp in TEMPERATURES:
        out_dir = os.path.join(output_dir, f"T{str(temp).replace('.', '_')}")
        ok = run_mpnn(mpnn_script, pdb_path, "A", fixed, temp,
                      SEQ_PER_TEMP, out_dir)
        if not ok:
            print(f"  Skipping T={temp} due to error")
            continue

        # 解析 FASTA 输出（在 seqs/ 子目录中）
        seqs_dir = os.path.join(out_dir, "seqs")
        if os.path.isdir(seqs_dir):
            fasta_files = [f for f in os.listdir(seqs_dir) if f.endswith(".fa")]
        else:
            fasta_files = [f for f in os.listdir(out_dir) if f.endswith(".fa")]
            seqs_dir = out_dir
        for fa in fasta_files:
            seqs = parse_mpnn_fasta(os.path.join(seqs_dir, fa), wt_seq)
            for seq, score in seqs.items():
                if seq not in all_seqs:
                    all_seqs[seq] = {"score": score, "temp": temp}
                else:
                    # 保留更好的 score
                    if score > all_seqs[seq]["score"]:
                        all_seqs[seq] = {"score": score, "temp": temp}
            print(f"    {fa}: {len(seqs)} sequences (total unique: {len(all_seqs)})")

    print(f"\nTotal unique sequences: {len(all_seqs)}")

    # ── 约束过滤 ──
    candidates = []
    for seq, meta in all_seqs.items():
        if len(seq) != len(wt_seq):
            continue
        l1_ok, l2_warn, l2_flag = check_constraints(seq, wt_seq)
        if not l1_ok:
            continue  # Level 1 违规直接淘汰
        mutation_str = seq_to_mutation_str(seq, wt_seq)
        num_mutations = 0 if mutation_str == "WT" else len(mutation_str.split(":"))

        candidates.append({
            "sequence": seq,
            "mutation_str": mutation_str,
            "num_mutations": num_mutations,
            "mpnn_score": meta["score"],
            "temperature": meta["temp"],
            "level2_warning": l2_flag,
            "level2_positions": ":".join(str(p) for p in l2_warn) if l2_warn else "",
        })

    df = pd.DataFrame(candidates)
    print(f"After Level 1 filter: {len(df)} candidates")

    if len(df) == 0:
        print("ERROR: No candidates passed constraints. Check PDB numbering and WT sequence.")
        return None

    # ── 去重（同序列保留高 score 低 temp） ──
    df = df.sort_values(["mpnn_score", "temperature"], ascending=[False, True])
    df = df.drop_duplicates(subset="sequence", keep="first")
    print(f"After dedup: {len(df)} candidates")

    # ── 统计 ──
    print(f"\nMPNN score: mean={df.mpnn_score.mean():.3f}, "
          f"range=[{df.mpnn_score.min():.3f}, {df.mpnn_score.max():.3f}]")
    for t in TEMPERATURES:
        sub = df[df.temperature == t]
        print(f"  T={t}: {len(sub)} seqs, score mean={sub.mpnn_score.mean():.3f}")

    # ── 保存 ──
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "strategy_C_candidates.csv")
    df.to_csv(out_path, index=False)
    print(f"\nSaved → {out_path}")

    return df


def main():
    parser = argparse.ArgumentParser(description="Strategy C: ProteinMPNN")
    parser.add_argument("--mpnn", required=True, help="Path to ProteinMPNN directory")
    parser.add_argument("--pdb", help="Path to sfGFP PDB (default: auto-detect)")
    parser.add_argument("--output", help="Output directory")
    parser.add_argument("--seq-per-temp", type=int, default=SEQ_PER_TEMP,
                        help=f"Sequences per temperature (default: {SEQ_PER_TEMP})")
    parser.add_argument("--temps", type=float, nargs="+",
                        help="Temperatures (default: 0.1 0.3 0.5)")
    args = parser.parse_args()

    # PDB 自动检测
    pdb = args.pdb
    if pdb is None:
        for candidate in [
            os.path.join(PROJECT_ROOT, "data", "2B3P_sfGFP.pdb"),
            "/data2/fenghaohui/gfp_strategy_D/data/2B3P_sfGFP.pdb",
        ]:
            if os.path.exists(candidate):
                pdb = candidate
                break
    if pdb is None:
        print("ERROR: Cannot find PDB file. Use --pdb to specify.")
        sys.exit(1)

    # 温度
    temps = args.temps if args.temps else TEMPERATURES
    n_seq = args.seq_per_temp

    # 运行时覆盖全局常量
    import strategy_C_proteinmpnn as self_mod
    self_mod.TEMPERATURES = temps
    self_mod.SEQ_PER_TEMP = n_seq

    run_strategy_c(args.mpnn, pdb, args.output)


if __name__ == "__main__":
    main()
