# -*- coding: utf-8 -*-
"""FoldX 批处理（增量保存，断点续跑）"""
import os, re, shutil, subprocess, threading, time, pandas as pd, sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOLDX = os.path.join(PROJECT, "Tools", "foldx5_Windows", "foldx_1_20270131.exe")
PDB = os.path.join(PROJECT, "data", "2B3P_sfGFP.pdb")
OUT_CSV = os.path.join(PROJECT, "运行结果", "strategy_A_foldx_results.csv")
WORK_BASE = os.path.join(PROJECT, "foldx_work_v4")
NUM_WORKERS = int(sys.argv[1]) if len(sys.argv) > 1 else 8

cand = pd.read_csv(os.path.join(PROJECT, "运行结果", "strategy_A_candidates.csv"))

# Resume
done_ids = set()
existing_df = None
if os.path.exists(OUT_CSV):
    existing_df = pd.read_csv(OUT_CSV)
    done_ids = set(existing_df["seq_id"].tolist())
    print(f"Resume: {len(done_ids)} done, {len(cand) - len(done_ids)} remaining")
else:
    print(f"Fresh start: {len(cand)} candidates")

remaining = cand[~cand["seq_id"].isin(done_ids)]
rows = list(remaining.iterrows())

# Assign to workers (save as DataFrames for proper iteration)
subsets = [[] for _ in range(NUM_WORKERS)]
for i, (_, row) in enumerate(rows):
    subsets[i % NUM_WORKERS].append(row)
for i in range(NUM_WORKERS):
    subsets[i] = pd.DataFrame(subsets[i]) if subsets[i] else pd.DataFrame()

# Prepare work dirs
for w in range(NUM_WORKERS):
    wd = os.path.join(WORK_BASE, f"w{w}")
    os.makedirs(os.path.join(wd, "output"), exist_ok=True)
    pdb_local = os.path.join(wd, "2B3P_sfGFP.pdb")
    if not os.path.exists(pdb_local):
        shutil.copy(PDB, pdb_local)

results = []
lock = threading.Lock()
t0 = time.time()

def parse_mutation(mut_str):
    """Convert 'G10A:E32K' to 'GA10A,EA32K;' """
    muts = []
    for part in mut_str.split(":"):
        m = re.match(r"([A-Z])(\d+)([A-Z])", part)
        if not m:
            return None, True  # parse error
        pos = int(m.group(2))
        if pos > 232:
            return None, False  # out of PDB range
        muts.append(m.group(1) + "A" + m.group(2) + m.group(3))
    return ",".join(muts) + ";\n", False

def worker(wid):
    wd = os.path.join(WORK_BASE, f"w{wid}")
    for _, row in subsets[wid].iterrows():
        sid = row["seq_id"]
        mut_str = row["mutation_str"]

        foldx_input, out_of_range = parse_mutation(mut_str)
        if out_of_range:
            with lock:
                results.append({"seq_id": sid, "mutation_str": mut_str,
                                "ddG_kcal_mol": None, "status": "skipped_out_of_PDB_range"})
            continue
        if foldx_input is None:
            with lock:
                results.append({"seq_id": sid, "mutation_str": mut_str,
                                "ddG_kcal_mol": None, "status": "parse_error"})
            continue

        # Setup candidate directory
        cd = os.path.join(wd, sid)
        os.makedirs(os.path.join(cd, "output"), exist_ok=True)
        pdb_local = os.path.join(cd, "2B3P_sfGFP.pdb")
        if not os.path.exists(pdb_local):
            shutil.copy(os.path.join(wd, "2B3P_sfGFP.pdb"), pdb_local)

        with open(os.path.join(cd, "individual_list.txt"), "w") as f:
            f.write(foldx_input)

        # Run FoldX
        try:
            r = subprocess.run(
                [FOLDX, "--command=BuildModel", "--pdb=2B3P_sfGFP.pdb",
                 "--mutant-file=individual_list.txt", "--output-dir=output"],
                capture_output=True, text=True, cwd=cd, timeout=120)
            ok = "successfully finished" in r.stdout
        except Exception:
            ok = False

        # Parse ddG
        ddg = None
        if ok:
            out_dir = os.path.join(cd, "output")
            for fn in os.listdir(out_dir):
                if fn.startswith("Dif_") and fn.endswith(".fxout"):
                    with open(os.path.join(out_dir, fn)) as f:
                        for line in f:
                            if line.startswith("2B3P"):
                                try:
                                    ddg = float(line.split("\t")[1])
                                except ValueError:
                                    pass
                                break
                    break

        status = "pass" if ddg is not None and ddg < 3.0 else \
                 ("fail_ddG" if ddg is not None else "error")

        # Save incrementally
        with lock:
            results.append({"seq_id": sid, "mutation_str": mut_str,
                            "ddG_kcal_mol": ddg, "status": status})
            if len(results) % 10 == 0:
                _save_results()

def _save_results():
    all_r = list(results)
    if existing_df is not None:
        old = []
        for _, row in existing_df.iterrows():
            old.append({"seq_id": row["seq_id"], "mutation_str": row["mutation_str"],
                        "ddG_kcal_mol": row["ddG_kcal_mol"], "status": row["status"]})
        all_r = old + all_r
    pd.DataFrame(all_r).to_csv(OUT_CSV, index=False)

# Start workers
threads = []
for w in range(NUM_WORKERS):
    t = threading.Thread(target=worker, args=(w,))
    t.start()
    threads.append(t)

print(f"Started {NUM_WORKERS} workers, {len(remaining)} remaining")

# Monitor
while any(t.is_alive() for t in threads):
    time.sleep(30)
    with lock:
        d = len(results) + len(done_ids)
    elapsed = max(time.time() - t0, 0.1)
    rate = len(results) / (elapsed / 60)
    eta = (len(remaining) - len(results)) / max(rate, 0.01)
    bar_len = 25
    filled = int(bar_len * d / len(cand))
    bar = "#" * filled + "-" * (bar_len - filled)
    print(f"  [{bar}] {d}/{len(cand)} ({100*d/len(cand):.0f}%) {rate:.0f}/min ETA:{eta:.0f}min")

for t in threads:
    t.join()

# Final save
_save_results()

df = pd.read_csv(OUT_CSV)
passed = (df["status"] == "pass").sum()
failed = (df["status"] == "fail_ddG").sum()
skipped = (df["status"].str.contains("skip")).sum()
errors = (~df["status"].isin(["pass", "fail_ddG"]) & ~df["status"].str.contains("skip")).sum()

elapsed = time.time() - t0
print(f"\nDone! {len(df)} total in {elapsed/60:.0f}min")
print(f"  Pass: {passed} | Fail: {failed} | Skip: {skipped} | Error: {errors}")
