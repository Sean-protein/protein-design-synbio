# -*- coding: utf-8 -*-
"""
FoldX5.1 批量 BuildModel 运行脚本（多进程并行）
=============================================
为策略A生成的候选序列运行 FoldX BuildModel，提取 ΔΔG，筛选通过序列。

用法:
    python 代码/run_foldx_batch.py                          # 运行全部（4进程）
    python 代码/run_foldx_batch.py --test                   # 仅测试前10条
    python 代码/run_foldx_batch.py --workers 8              # 8进程并行
    python 代码/run_foldx_batch.py --resume                 # 从断点续跑
"""

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import threading

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOLDX_EXE = os.path.join(PROJECT_ROOT, "Tools", "foldx5_Windows", "foldx_1_20270131.exe")
PDB_PATH = os.path.join(PROJECT_ROOT, "data", "2B3P_sfGFP.pdb")
CANDIDATES_CSV = os.path.join(PROJECT_ROOT, "运行结果", "strategy_A_candidates.csv")
WORK_DIR = os.path.join(PROJECT_ROOT, "foldx_work")
OUTPUT_CSV = os.path.join(PROJECT_ROOT, "运行结果", "strategy_A_foldx_results.csv")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# Positions > 232 are outside PDB 2B3P structure range
PDB_MAX_RES = 232


def ensure_work_dir():
    """准备 FoldX 工作目录。"""
    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(os.path.join(WORK_DIR, "output"), exist_ok=True)
    # Copy PDB to work dir
    pdb_local = os.path.join(WORK_DIR, "2B3P_sfGFP.pdb")
    if not os.path.exists(pdb_local):
        shutil.copy(PDB_PATH, pdb_local)
    return pdb_local


def generate_individual_list(mut_str, seq_id):
    """为一条候选生成 FoldX individual_list.txt。

    格式: OriginalAA + Chain + Position + NewAA + ;
    例如: GA10A;
    """
    parts = mut_str.split(":")
    mut_list = []
    for part in parts:
        m = re.match(r"([A-Z])(\d+)([A-Z])", part)
        if not m:
            log.warning("  Cannot parse mutation: %s", part)
            return None
        wt_aa, pos_str, new_aa = m.group(1), m.group(2), m.group(3)
        pos = int(pos_str)
        if pos > PDB_MAX_RES:
            return None  # Outside PDB
        mut_list.append(f"{wt_aa}A{pos}{new_aa}")
    # All mutations on ONE line, comma-separated, ending with semicolon
    return ",".join(mut_list) + ";\n"


def run_foldx(seq_id, individual_list_content):
    """运行单个 FoldX BuildModel。"""
    list_path = os.path.join(WORK_DIR, "individual_list.txt")
    with open(list_path, "w") as f:
        f.write(individual_list_content)

    # Clean previous output
    out_dir = os.path.join(WORK_DIR, "output")
    for f in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, f))

    result = subprocess.run(
        [
            FOLDX_EXE,
            "--command=BuildModel",
            "--pdb=2B3P_sfGFP.pdb",
            "--mutant-file=individual_list.txt",
            "--output-dir=output",
        ],
        capture_output=True,
        text=True,
        cwd=WORK_DIR,
        timeout=120,
    )

    success = "successfully finished" in result.stdout
    return result.stdout, success


def parse_ddg():
    """解析 FoldX Dif_*.fxout 文件中的 ΔΔG 值。"""
    out_dir = os.path.join(WORK_DIR, "output")
    for fname in os.listdir(out_dir):
        if fname.startswith("Dif_") and fname.endswith(".fxout"):
            path = os.path.join(out_dir, fname)
            with open(path) as f:
                content = f.read()
            # Parse tab-separated table after header
            lines = content.strip().split("\n")
            for line in lines:
                if line.startswith("2B3P") and "BuildModel" in content:
                    # Data line: Pdb \t total energy \t ...
                    cols = line.split("\t")
                    if len(cols) > 1:
                        try:
                            return float(cols[1])
                        except ValueError:
                            pass
            # Fallback: find first numeric line after header
            for i, line in enumerate(lines):
                if line.startswith("2B3P"):
                    cols = line.split("\t")
                    if len(cols) > 1:
                        for c in cols[1:]:
                            try:
                                return float(c)
                            except ValueError:
                                continue
    return None


def process_candidate_serial(row, work_dir):
    """在指定工作目录中处理单条候选。每候选用独立子目录避免文件冲突。"""
    mut_str = row["mutation_str"]
    seq_id = row["seq_id"]

    # Check PDB range (positions > 232 not in structure)
    parts = mut_str.split(":")
    for part in parts:
        m = re.match(r"([A-Z])(\d+)([A-Z])", part)
        if m and int(m.group(2)) > PDB_MAX_RES:
            return {"seq_id": seq_id, "mutation_str": mut_str,
                    "ddG_kcal_mol": None, "status": "skipped_out_of_PDB_range"}

    ind_list = generate_individual_list(mut_str, seq_id)
    if ind_list is None:
        return {"seq_id": seq_id, "mutation_str": mut_str,
                "ddG_kcal_mol": None, "status": "skipped_out_of_PDB_range"}

    # Unique per-candidate subdirectory
    cand_dir = os.path.join(work_dir, seq_id)
    os.makedirs(cand_dir, exist_ok=True)
    pdb_local = os.path.join(cand_dir, "2B3P_sfGFP.pdb")
    if not os.path.exists(pdb_local):
        shutil.copy(os.path.join(work_dir, "2B3P_sfGFP.pdb"), pdb_local)

    list_path = os.path.join(cand_dir, "individual_list.txt")
    with open(list_path, "w") as f:
        f.write(ind_list)

    os.makedirs(os.path.join(cand_dir, "output"), exist_ok=True)

    # Run FoldX in unique directory
    try:
        result = subprocess.run(
            [FOLDX_EXE, "--command=BuildModel", "--pdb=2B3P_sfGFP.pdb",
             "--mutant-file=individual_list.txt", "--output-dir=output"],
            capture_output=True, text=True, cwd=cand_dir, timeout=120,
        )
        success = "successfully finished" in result.stdout
    except Exception as e:
        return {"seq_id": seq_id, "mutation_str": mut_str,
                "ddG_kcal_mol": None, "status": f"error:{e}"}

    # Parse ddG from this candidate's unique output
    ddg = None
    if success:
        out_dir = os.path.join(cand_dir, "output")
        for fname in os.listdir(out_dir):
            if fname.startswith("Dif_") and fname.endswith(".fxout"):
                with open(os.path.join(out_dir, fname)) as f:
                    for line in f:
                        if line.startswith("2B3P"):
                            cols = line.split("\t")
                            if len(cols) > 1:
                                try:
                                    ddg = float(cols[1])
                                except ValueError:
                                    pass
                                break

    status = "foldx_error" if ddg is None else ("pass" if ddg < 3.0 else "fail_ddG")
    return {"seq_id": seq_id, "mutation_str": mut_str,
            "ddG_kcal_mol": ddg, "status": status}


def worker_thread(work_dir, candidates_subset, results_list, lock):
    """Worker 线程：串行处理分配给它的候选序列。"""
    for _, row in candidates_subset.iterrows():
        r = process_candidate_serial(row, work_dir)
        with lock:
            results_list.append(r)


def batch_run(candidates_df, test_mode=False, workers=4, start_from=0):
    """多线程并行运行 FoldX BuildModel（每线程独立工作目录+PDB）。"""
    total = min(len(candidates_df), 10) if test_mode else len(candidates_df)
    log.info("=" * 60)
    log.info("FoldX Batch BuildModel: %d candidates x %d workers", total, workers)
    log.info("=" * 60)

    # Prepare work directories
    work_dirs = []
    for w in range(workers):
        wd = os.path.join(WORK_DIR, f"w{w}")
        os.makedirs(os.path.join(wd, "output"), exist_ok=True)
        if not os.path.exists(os.path.join(wd, "2B3P_sfGFP.pdb")):
            shutil.copy(PDB_PATH, os.path.join(wd, "2B3P_sfGFP.pdb"))
        work_dirs.append(wd)

    # Split candidates across workers
    rows = list(candidates_df.iterrows())[start_from:start_from + total]
    subsets = [[] for _ in range(workers)]
    for i, (_, row) in enumerate(rows):
        subsets[i % workers].append(row)

    results = []
    lock = threading.Lock()
    threads = []

    t0 = time.time()
    for w in range(workers):
        t = threading.Thread(
            target=worker_thread,
            args=(work_dirs[w], pd.DataFrame(subsets[w]), results, lock),
        )
        t.start()
        threads.append(t)

    # Progress monitor
    while any(t.is_alive() for t in threads):
        with lock:
            done = len(results)
        elapsed = max(time.time() - t0, 0.1)
        rate = done / (elapsed / 60)
        eta = (total - done) / max(rate, 0.01)
        log.info("  [%d/%d] %.1f seq/min | ETA %.0f min", done, total, rate, eta)
        time.sleep(30)

    for t in threads:
        t.join()

    # Sort results
    results.sort(key=lambda x: int(x["seq_id"].split("_")[1]))

    # Save
    df_out = pd.DataFrame(results)
    df_out.to_csv(OUTPUT_CSV, index=False)

    # Summary
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] == "fail_ddG")
    errors = sum(1 for r in results if "error" in r["status"])
    skipped = sum(1 for r in results if "skipped" in r["status"])

    elapsed = time.time() - t0
    log.info("=" * 60)
    log.info("FoldX complete in %.1f min: %d/%d passed (ddG < 3.0)",
             elapsed / 60, passed, len(results))
    log.info("  Pass: %d | Fail ddG: %d | Error: %d | Skipped: %d",
             passed, failed, errors, skipped)
    log.info("  Rate: %.1f seq/min", len(results) / (elapsed / 60))
    log.info("  Results: %s", OUTPUT_CSV)
    log.info("=" * 60)

    return df_out


def main():
    parser = argparse.ArgumentParser(description="FoldX Batch BuildModel Runner")
    parser.add_argument("--test", action="store_true", help="Test first 10 candidates")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers (default: 4)")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    parser.add_argument("--start", type=int, default=0, help="Start from candidate index")
    args = parser.parse_args()

    if not os.path.exists(FOLDX_EXE):
        log.error("FoldX not found at: %s", FOLDX_EXE)
        sys.exit(1)

    df = pd.read_csv(CANDIDATES_CSV)
    log.info("Loaded %d candidates from %s", len(df), CANDIDATES_CSV)

    # Check for resume
    start_from = args.start
    if args.resume and os.path.exists(OUTPUT_CSV):
        existing = pd.read_csv(OUTPUT_CSV)
        start_from = len(existing)
        log.info("Resuming from index %d (%d already done)", start_from, start_from)

    batch_run(df, test_mode=args.test, workers=args.workers, start_from=start_from)


if __name__ == "__main__":
    main()
