# -*- coding: utf-8 -*-
"""
策略C — ESMFold HF 版结构验证 v2
require: pip install transformers accelerate
"""
import os, sys, time, json, argparse, traceback
import numpy as np, pandas as pd, torch

def _find_root():
    for d in [os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "/data2/fenghaohui"]:
        if os.path.exists(d): return d
    return os.getcwd()
ROOT = _find_root()
RESULTS_DIR = os.path.join(ROOT, "results", "strategy_C")
os.makedirs(RESULTS_DIR, exist_ok=True)
CAND_CSV  = os.path.join(RESULTS_DIR, "strategy_C_ml_scored.csv")
OUT_CSV   = os.path.join(RESULTS_DIR, "strategy_C_esmfold_full.csv")

CHROMOPHORE = list(range(62,68)) + [70,93,95,147,219,221]

def load_candidates(csv_path, top_ml=0, max_n=0):
    df = pd.read_csv(csv_path)
    if top_ml > 0 and "pred_brightness" in df.columns:
        df = df.sort_values("pred_brightness", ascending=False).head(top_ml)
    if max_n > 0: df = df.head(max_n)
    print("Candidates: {} | muts [{}, {}] mean={:.0f}".format(
        len(df), df.num_mutations.min(), df.num_mutations.max(), df.num_mutations.mean()))
    return df

def load_model(device_str="cuda:0"):
    from transformers import EsmForProteinFolding, AutoTokenizer
    device = torch.device(device_str if torch.cuda.is_available() else "cpu")
    print("Loading ESMFold HF model...")
    tok = AutoTokenizer.from_pretrained("facebook/esmfold_v1")
    model = EsmForProteinFolding.from_pretrained(
        "facebook/esmfold_v1", low_cpu_mem_usage=True,
        torch_dtype=torch.float32
    ).to(device).eval()
    print("  Loaded on {}".format(device))
    return model, tok, device

def infer_one(model, tok, device, seq):
    tok_out = tok([seq], return_tensors="pt", add_special_tokens=False)
    tok_out = {k: v.to(device) for k, v in tok_out.items()}
    with torch.no_grad():
        out = model(**tok_out)
    plddt = out.plddt[0].detach().cpu().float().numpy()
    ptm = out.ptm[0].item()
    return plddt, ptm

def compute_metrics(plddt, ptm):
    m = {"plddt_mean": float(plddt.mean()), "ptm": float(ptm)}
    L = len(plddt)
    ci = [i for i in CHROMOPHORE if i < L]
    if ci:
        m["plddt_chr_mean"] = float(plddt[ci].mean())
        m["plddt_chr_min"]  = float(plddt[ci].min())
    else:
        m["plddt_chr_mean"] = m["plddt_chr_min"] = None
    m["frac_low"] = float((plddt < 70).mean())
    for name, i in [("T65",64),("Y66",65),("G67",66),("R96",95),("E222",221)]:
        m["plddt_"+name] = float(plddt[i]) if i < L else None
    return m

def status_of(m):
    if m["plddt_mean"] >= 80 and m["ptm"] >= 0.75:
        return "pass" if (m.get("plddt_chr_mean") or 100) >= 85 else "fail_chromo"
    return "fail_structure"

def load_done():
    if not os.path.exists(OUT_CSV): return set(), []
    ex = pd.read_csv(OUT_CSV)
    done = set(ex["sequence"].tolist())
    print("Resume: {} done".format(len(done)))
    return done, ex.to_dict("records")

def save(recs):
    pd.DataFrame(recs).to_csv(OUT_CSV, index=False)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--top-ml", type=int, default=0)
    p.add_argument("--max", type=int, default=0)
    p.add_argument("--save-every", type=int, default=5)
    p.add_argument("--fresh", action="store_true")
    args = p.parse_args()

    print("="*60)
    print("STRATEGY C — ESMFold HF v2")
    print("="*60)

    df = load_candidates(CAND_CSV, args.top_ml, args.max)
    done_seqs, records = (set(), []) if args.fresh else load_done()

    seqs = df["sequence"].tolist()
    todo = [(i, s) for i, s in enumerate(seqs) if s not in done_seqs]
    if not todo:
        print("All done!")
        return
    print("To run: {} | ETA ~{:.0f}min".format(len(todo), len(todo)*40/60))

    model, tok, device = load_model(args.device)
    t0 = time.time()
    n_ok = 0
    n_err = 0
    first_errs = []

    for k, (idx, seq) in enumerate(todo):
        row = df.iloc[idx]
        t1 = time.time()
        err_msg = ""
        try:
            plddt_arr, ptm = infer_one(model, tok, device, seq)
            met = compute_metrics(plddt_arr, ptm)
            del plddt_arr
        except Exception as e:
            met = {"plddt_mean": 0, "ptm": 0}
            err_msg = str(e)[:200]
            if n_err < 3:
                first_errs.append("seq[{}]: {}".format(idx, err_msg))
            n_err += 1
        finally:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        dt = time.time() - t1
        status = "error" if err_msg else status_of(met)
        if status == "error":
            pass  # n_err already counted
        elif status == "pass":
            n_ok += 1

        rec = {
            "idx": idx, "sequence": seq, "status": status,
            "error_msg": err_msg,
            "num_mutations": int(row["num_mutations"]),
            "temperature": row["temperature"],
            "mpnn_score": row["mpnn_score"],
            "pred_brightness": row.get("pred_brightness", np.nan),
            "plddt_mean": round(met.get("plddt_mean",0), 1),
            "ptm": round(met.get("ptm",0), 3),
            "plddt_chr_mean": round(met["plddt_chr_mean"],1) if met.get("plddt_chr_mean") is not None else None,
            "plddt_chr_min":  round(met["plddt_chr_min"],1)  if met.get("plddt_chr_min")  is not None else None,
            "frac_low":      round(met.get("frac_low",0), 3),
            "plddt_T65":  met.get("plddt_T65"),
            "plddt_Y66":  met.get("plddt_Y66"),
            "plddt_G67":  met.get("plddt_G67"),
            "plddt_R96":  met.get("plddt_R96"),
            "plddt_E222": met.get("plddt_E222"),
            "seq_time_s": round(dt, 1),
        }
        records.append(rec)
        done_seqs.add(seq)

        if (k+1) % args.save_every == 0:
            save(records)

        total = len(records)
        eta = (len(seqs)-total) * max(dt, 1) / 60
        print("  [{}/{}] pLDDT={} pTM={} chr={} | {}muts | {:.0f}s | {} | ETA {:.0f}min{}".format(
            total, len(seqs),
            rec["plddt_mean"], rec["ptm"],
            rec["plddt_chr_mean"] if rec["plddt_chr_mean"] else "N/A",
            rec["num_mutations"], dt, status, eta,
            "" if status != "error" or n_err > 3 else " | "+err_msg[:80]))

    save(records)

    # --- summary ---
    print("\n" + "="*60)
    print("Summary: {} done in {:.0f}min".format(len(records), (time.time()-t0)/60))
    print("  pass (pLDDT>=80,pTM>=0.75,chr>=85): {}".format(n_ok))
    print("  errors: {}".format(n_err))

    if first_errs:
        print("\n  First 3 errors:")
        for e in first_errs:
            print("    {}".format(e[:200]))

    # show next step
    if n_ok >= 30:
        print("\n  {} candidates passed — proceed to FoldX on top 50-100".format(n_ok))
    else:
        print("\n  Only {} passed. Consider lowering threshold or using ML scores directly.".format(n_ok))
    print("="*60)

if __name__ == "__main__":
    main()
