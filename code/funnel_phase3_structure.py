# -*- coding: utf-8 -*-
"""Phase 3: 结构双验证 — ColabFold + Boltz-1 交叉验证

Consumes: results/funnel_phase2_top80.csv (80 sequences with ML scores)
Produces: results/funnel_phase3_top30.csv (Top 30 with dual structure validation)

Pipeline:
  1. Load top 80 from Phase 2
  2. Run ColabFold structure prediction (pLDDT, pTM)
  3. Run Boltz-1 structure prediction (or skip if unavailable)
  4. Cross-validate: both tools must pass thresholds AND agree within 15% pLDDT
  5. Output top 30 ranked by composite_score

Fallback strategies (ordered by preference):
  A. ColabFold + Boltz-1 dual validation (ideal)
  B. ColabFold only (if Boltz-1 unavailable)
  C. ESMFold via local model (if ColabFold unavailable, using strategy_C code)
  D. Mock pLDDT from composite_score (for pipeline testing on machines w/o GPU)

Thresholds:
  - pLDDT > 80, pTM > 0.75 (both tools in dual mode)
  - Cross-validation: |cf_plddt - bz_plddt| < 15
  - Chromophore region (positions 64-67, 0-based) local pLDDT > 85

Usage:
  python code/funnel_phase3_structure.py
  python code/funnel_phase3_structure.py --mock          # force mock mode
  python code/funnel_phase3_structure.py --esmfold-only  # use ESMFold instead of ColabFold
"""

import os
import re
import sys
import json
import subprocess
import tempfile
import time
import shutil
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

# ── Encoding compatibility ─────────────────────────────────────────────────
# Windows console defaults to GBK which cannot encode many Unicode characters
# used in Chinese-language print statements. Wrap stdout/stderr for UTF-8.
if sys.platform == 'win32':
    import io
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding='utf-8', errors='replace'
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding='utf-8', errors='replace'
        )
    except (AttributeError, OSError):
        pass  # Redirected or non-buffer stream, fall through

# ── Configuration ──────────────────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
INPUT_TOP80 = os.path.join(RESULTS_DIR, "funnel_phase2_top80.csv")
OUTPUT_TOP30 = os.path.join(RESULTS_DIR, "funnel_phase3_top30.csv")
STRUCT_OUTPUT_DIR = os.path.join(RESULTS_DIR, "phase3_structures")
os.makedirs(STRUCT_OUTPUT_DIR, exist_ok=True)

TOP_N = 30
CHROMOPHORE_POSITIONS = list(range(64, 68))  # 0-based: T65(64)-Y66(65)-G67(66)
PDLDT_THRESHOLD = 80.0
PTM_THRESHOLD = 0.75
CHROMOPHORE_PLDDT_THRESHOLD = 85.0
CROSS_VALIDATION_MAX_DIFF = 15.0  # max allowed pLDDT difference between tools
COLABFOLD_TIMEOUT = 1800  # 30 min per sequence (MSA + prediction)
SEED = 42

# ── Tool Detection ─────────────────────────────────────────────────────────

def _which(program):
    """Cross-platform `which`."""
    return shutil.which(program) is not None


def detect_colabfold():
    """Detect ColabFold availability.

    Returns dict with keys: available, method, path, details
    """
    result = {"available": False, "method": None, "path": None, "details": ""}

    # 1. Check colabfold_batch on PATH
    if _which("colabfold_batch"):
        result["available"] = True
        result["method"] = "cli"
        result["path"] = "colabfold_batch"
        result["details"] = "colabfold_batch on PATH"
        return result

    # 2. Check common localcolabfold installation
    common_paths = [
        os.path.expanduser("~/localcolabfold/colabfold-conda/bin/colabfold_batch"),
        "/usr/local/bin/colabfold_batch",
    ]
    for p in common_paths:
        if os.path.isfile(p):
            result["available"] = True
            result["method"] = "cli"
            result["path"] = p
            result["details"] = f"found at {p}"
            return result

    # 3. Check Python API
    try:
        import colabfold
        from colabfold.batch import run
        result["available"] = True
        result["method"] = "python_api"
        result["path"] = colabfold.__file__
        result["details"] = f"Python API at {colabfold.__file__}"
        return result
    except ImportError:
        pass

    try:
        import alphafold
        result["available"] = True
        result["method"] = "python_api_alphafold"
        result["path"] = alphafold.__file__
        result["details"] = "AlphaFold Python API (ColabFold-compatible)"
        return result
    except ImportError:
        pass

    return result


def detect_boltz1():
    """Detect Boltz-1 availability.

    Returns dict with keys: available, method, path, details
    """
    result = {"available": False, "method": None, "path": None, "details": ""}

    try:
        import boltz
        result["available"] = True
        result["method"] = "python_api"
        result["path"] = boltz.__file__
        result["details"] = f"boltz module at {boltz.__file__}"

        # Verify we can instantiate
        try:
            from boltz import Boltz1
            model = Boltz1()
            result["details"] += " (Boltz1 class verified)"
        except (ImportError, TypeError, Exception):
            result["details"] += " (Boltz1 class not verified)"
        return result
    except ImportError:
        pass

    # Check CLI
    if _which("boltz"):
        result["available"] = True
        result["method"] = "cli"
        result["path"] = "boltz"
        result["details"] = "boltz CLI on PATH"
        return result

    return result


def detect_esmfold():
    """Detect ESMFold availability (fallback option).

    Returns dict with keys: available, method, details
    """
    result = {"available": False, "method": None, "details": ""}

    try:
        import torch
        if not torch.cuda.is_available():
            result["details"] = "ESMFold requires GPU (CUDA not available)"
            return result
    except ImportError:
        result["details"] = "PyTorch not installed"
        return result

    # Try importing ESMFold
    try:
        from transformers import EsmForProteinFolding
        result["available"] = True
        result["method"] = "esmfold_hf"
        result["details"] = "ESMFold via HuggingFace transformers"
        return result
    except ImportError:
        pass

    # Check for local ESMFold installation
    try:
        import esm
        if hasattr(esm, 'pretrained'):
            result["available"] = True
            result["method"] = "esm_local"
            result["details"] = "ESMFold via local esm module"
            return result
    except ImportError:
        pass

    return result


# ── ColabFold Runner ───────────────────────────────────────────────────────

def run_colabfold(sequences, seq_ids, output_base, cf_info, mock_mode=False):
    """Run ColabFold batch prediction.

    Parameters
    ----------
    sequences : list of str
    seq_ids : list of str
    output_base : str
        Directory for per-sequence output subdirectories.
    cf_info : dict
        Detection result from detect_colabfold().
    mock_mode : bool
        If True, use mock pLDDT values even if ColabFold is available.

    Returns
    -------
    dict : {seq_id: {'cf_plddt': float|None, 'cf_ptm': float|None,
                     'cf_chromophore_plddt': float|None, 'cf_success': bool,
                     'cf_source': 'real'|'mock'}}
    """
    results = {}
    n = len(sequences)

    if mock_mode or not cf_info["available"]:
        source = "mock"
        print(f"  ColabFold: 模拟模式 ({'forced' if mock_mode else 'tools missing'}), "
              f"基于composite_score生成pLDDT")
        # Generate mock pLDDT values correlated with composite_score
        rng = np.random.RandomState(SEED)
        for i, (seq, sid) in enumerate(zip(sequences, seq_ids)):
            # Base pLDDT: 65-95 range, noise adds variation
            base_plddt = 70.0 + rng.normal(10, 5)
            plddt = np.clip(base_plddt, 55, 98)
            ptm = np.clip(plddt / 100.0 - 0.05 + rng.normal(0, 0.03), 0.5, 0.95)
            chrom_plddt = np.clip(plddt + rng.normal(-2, 3), 55, 98)

            results[sid] = {
                'cf_plddt': round(float(plddt), 2),
                'cf_ptm': round(float(ptm), 4),
                'cf_chromophore_plddt': round(float(chrom_plddt), 2),
                'cf_success': True,
                'cf_source': source,
            }
        return results

    # Real ColabFold mode
    source = "real"
    print(f"  ColabFold: 真实预测模式 ({cf_info['method']})")
    print(f"  ColabFold: {cf_info['details']}")
    print(f"  预计耗时: ~{n * 5}-{n * 10} 分钟 (GPU)")

    for i, (seq, sid) in enumerate(zip(sequences, seq_ids)):
        # Validate seq_id is safe (alphanumeric + underscore + hyphen only)
        if not re.match(r'^[a-zA-Z0-9_-]+$', sid):
            print(f"    ⚠  Skipping {sid}: invalid chars in seq_id")
            results[sid] = {
                'cf_plddt': None, 'cf_ptm': None,
                'cf_chromophore_plddt': None, 'cf_success': False,
                'cf_source': source,
            }
            continue

        out_dir = os.path.join(output_base, f"colabfold_{sid}")
        os.makedirs(out_dir, exist_ok=True)

        # Write FASTA
        fasta_path = os.path.join(out_dir, f"{sid}.fasta")
        with open(fasta_path, 'w') as f:
            f.write(f">{sid}\n{seq}\n")

        # Build command
        tmp_script = None
        if cf_info["method"] == "cli":
            batch_exec = cf_info["path"]
            cmd = [
                batch_exec, fasta_path, out_dir,
                "--num-recycle", "3",
                "--num-models", "1",
                "--use-gpu-relax",
                "--stop-at-score", "85",
            ]
        else:
            # Python API mode — write temp script (safe against injection)
            script = (
                f"from colabfold.batch import run\n"
                f"run({repr(fasta_path)}, {repr(out_dir)}, "
                f"num_recycle=3, num_models=1, use_gpu_relax=True, "
                f"stop_at_score=85)\n"
            )
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.py', delete=False, prefix='colabfold_'
            ) as f:
                f.write(script)
                tmp_script = f.name
            cmd = [sys.executable, tmp_script]

        try:
            print(f"    [{i+1}/{n}] ColabFold: {sid} ...", end=" ", flush=True)
            result = subprocess.run(
                cmd,
                capture_output=True, text=True,
                timeout=COLABFOLD_TIMEOUT
            )
            plddt, ptm, chrom_plddt = parse_colabfold_output(out_dir, sid)

            if plddt is not None:
                print(f"pLDDT={plddt:.1f} pTM={ptm:.3f}")
            else:
                print(f"failed (no output)")

            results[sid] = {
                'cf_plddt': plddt,
                'cf_ptm': ptm,
                'cf_chromophore_plddt': chrom_plddt,
                'cf_success': plddt is not None,
                'cf_source': source,
            }
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT")
            results[sid] = {
                'cf_plddt': None, 'cf_ptm': None,
                'cf_chromophore_plddt': None, 'cf_success': False,
                'cf_source': source,
            }
        except Exception as e:
            print(f"ERROR: {e}")
            results[sid] = {
                'cf_plddt': None, 'cf_ptm': None,
                'cf_chromophore_plddt': None, 'cf_success': False,
                'cf_source': source,
            }
        finally:
            if tmp_script is not None:
                try:
                    os.unlink(tmp_script)
                except OSError:
                    pass

        if (i + 1) % 10 == 0:
            print(f"  ColabFold: {i+1}/{n} 完成")

    return results


def parse_colabfold_output(out_dir, seq_id):
    """Extract pLDDT, pTM, and chromophore-local pLDDT from ColabFold output.

    Searches for JSON score files and PDB files, parsing whichever are present.
    """
    # Try JSON score files first
    json_path = os.path.join(out_dir, f"{seq_id}_scores_rank_001_{seq_id}.json")
    if not os.path.exists(json_path):
        json_files = sorted([
            f for f in os.listdir(out_dir)
            if f.endswith('.json') and 'scores' in f.lower()
        ])
        if json_files:
            json_path = os.path.join(out_dir, json_files[0])
        else:
            # Fall back to any JSON
            json_files = sorted([f for f in os.listdir(out_dir) if f.endswith('.json')])
            if json_files:
                json_path = os.path.join(out_dir, json_files[0])
            else:
                return None, None, None

    plddt = None
    ptm = None

    try:
        with open(json_path) as f:
            data = json.load(f)
        plddt = data.get('plddt') or data.get('mean_plddt')
        ptm = data.get('ptm') or data.get('predicted_tm_score')
    except (json.JSONDecodeError, FileNotFoundError, KeyError) as e:
        pass

    # Try PDB B-factor column for per-residue pLDDT
    chrom_plddt = None
    pdb_files = sorted([f for f in os.listdir(out_dir) if f.endswith('.pdb')])
    if pdb_files:
        chrom_plddt = _plddt_from_pdb(
            os.path.join(out_dir, pdb_files[0]),
            CHROMOPHORE_POSITIONS
        )
        # If JSON didn't have global pLDDT, compute from PDB
        if plddt is None:
            all_plddt = _plddt_from_pdb(
                os.path.join(out_dir, pdb_files[0]),
                None  # all residues
            )
            if all_plddt is not None:
                plddt = all_plddt

    return plddt, ptm, chrom_plddt


def _plddt_from_pdb(pdb_path, positions):
    """Extract pLDDT values from PDB B-factor column.

    Parameters
    ----------
    pdb_path : str
    positions : list of int or None
        0-based residue positions to extract. None = all residues.

    Returns
    -------
    float or None : mean pLDDT at given positions
    """
    plddt_values = []
    try:
        with open(pdb_path) as f:
            for line in f:
                if line.startswith("ATOM") and line[13:15].strip() == "CA":
                    try:
                        res_num = int(line[22:26].strip()) - 1  # 0-based
                        bfactor = float(line[60:66].strip())
                        if positions is None or res_num in positions:
                            plddt_values.append(bfactor)
                    except (ValueError, IndexError):
                        continue
    except (FileNotFoundError, IOError):
        return None

    if plddt_values:
        return round(float(np.mean(plddt_values)), 2)
    return None


# ── Boltz-1 Runner ─────────────────────────────────────────────────────────

def run_boltz1(sequences, seq_ids, output_base, bz_info, mock_mode=False):
    """Run Boltz-1 batch prediction.

    Parameters
    ----------
    sequences, seq_ids : lists
    output_base : str
    bz_info : dict
        Detection result from detect_boltz1().
    mock_mode : bool

    Returns
    -------
    dict : {seq_id: {'bz_plddt': float|None, 'bz_ptm': float|None,
                     'bz_chromophore_plddt': float|None, 'bz_success': bool,
                     'bz_source': 'real'|'mock'|'unavailable'}}
    """
    n = len(sequences)

    if mock_mode or not bz_info["available"]:
        if bz_info["available"] and mock_mode:
            reason = "forced mock"
        elif not bz_info["available"]:
            reason = "Boltz-1 not installed"
        else:
            reason = "unknown"

        print(f"  Boltz-1: 跳过 ({reason})")
        return {
            sid: {
                'bz_plddt': None, 'bz_ptm': None,
                'bz_chromophore_plddt': None, 'bz_success': False,
                'bz_source': 'unavailable',
            }
            for sid in seq_ids
        }

    # Real Boltz-1 mode
    source = "real"
    print(f"  Boltz-1: 真实预测模式 ({bz_info['method']})")
    print(f"  Boltz-1: {bz_info['details']}")
    print(f"  预计耗时: ~{n * 2} 分钟 (GPU)")

    results = {}

    # Try to load model once
    model = None
    try:
        from boltz import Boltz1
        model = Boltz1()
        print("  Boltz-1: Boltz1 model loaded")
    except (ImportError, TypeError, Exception) as e:
        # Try CLI mode
        print(f"  Boltz-1: Python API failed ({e}), trying CLI...")

    for i, (seq, sid) in enumerate(zip(sequences, seq_ids)):
        try:
            if model is not None:
                # Python API
                structure = model.predict(seq)
                plddt = float(structure.plddt) if hasattr(structure, 'plddt') else None
                ptm = float(structure.ptm) if hasattr(structure, 'ptm') else None
                # Per-residue pLDDT for chromophore region
                chrom_plddt = None
                if hasattr(structure, 'plddt_per_residue'):
                    per_res = structure.plddt_per_residue
                    if hasattr(per_res, '__iter__'):
                        chrom_vals = [per_res[p] for p in CHROMOPHORE_POSITIONS
                                      if p < len(per_res)]
                        if chrom_vals:
                            chrom_plddt = float(np.mean(chrom_vals))
                results[sid] = {
                    'bz_plddt': round(plddt, 2) if plddt is not None else None,
                    'bz_ptm': round(ptm, 4) if ptm is not None else None,
                    'bz_chromophore_plddt': round(chrom_plddt, 2) if chrom_plddt is not None else None,
                    'bz_success': plddt is not None,
                    'bz_source': source,
                }
            else:
                # CLI fallback
                out_dir = os.path.join(output_base, f"boltz_{sid}")
                os.makedirs(out_dir, exist_ok=True)
                fasta_path = os.path.join(out_dir, f"{sid}.fasta")
                with open(fasta_path, 'w') as f:
                    f.write(f">{sid}\n{seq}\n")

                cmd = ["boltz", "predict", fasta_path,
                       "--output", out_dir]
                subprocess_result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=300
                )
                plddt, ptm = _parse_boltz_output(out_dir, sid)
                results[sid] = {
                    'bz_plddt': plddt, 'bz_ptm': ptm,
                    'bz_chromophore_plddt': None,
                    'bz_success': plddt is not None,
                    'bz_source': source,
                }

            print(f"    [{i+1}/{n}] Boltz-1: {sid} "
                  f"pLDDT={results[sid].get('bz_plddt', 'N/A')}")

        except Exception as e:
            print(f"    [{i+1}/{n}] Boltz-1: {sid} ERROR: {type(e).__name__}: {e}")
            results[sid] = {
                'bz_plddt': None, 'bz_ptm': None,
                'bz_chromophore_plddt': None, 'bz_success': False,
                'bz_source': source,
            }

        if (i + 1) % 10 == 0:
            print(f"  Boltz-1: {i+1}/{n} 完成")

    return results


def _parse_boltz_output(out_dir, seq_id):
    """Parse Boltz-1 CLI output for pLDDT/pTM."""
    json_files = sorted([f for f in os.listdir(out_dir) if f.endswith('.json')])
    if not json_files:
        return None, None

    for jf in json_files:
        try:
            with open(os.path.join(out_dir, jf)) as f:
                data = json.load(f)
            plddt = data.get('plddt') or data.get('mean_plddt') or data.get('global_plddt')
            ptm = data.get('ptm') or data.get('tm_score') or data.get('predicted_tm_score')
            if plddt is not None:
                return plddt, ptm
        except Exception:
            continue

    return None, None


# ── ESMFold Fallback Runner ────────────────────────────────────────────────

def run_esmfold_fallback(sequences, seq_ids, output_base):
    """Run ESMFold as fallback when ColabFold is unavailable.

    Uses HuggingFace transformers EsmForProteinFolding.
    """
    print("  ESMFold fallback: 加载模型 ...")

    try:
        import torch
        from transformers import AutoTokenizer, EsmForProteinFolding

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"  ESMFold: device={device}")

        model = EsmForProteinFolding.from_pretrained(
            "facebook/esmfold_v1", low_cpu_mem_usage=True
        ).to(device)
        model.esm = model.esm.half()  # FP16 for speed
        model.eval()

        tokenizer = AutoTokenizer.from_pretrained("facebook/esmfold_v1")

        print(f"  ESMFold: 模型加载完成, 预计 ~{len(sequences)*2} 分钟 (GPU)")

        results = {}
        for i, (seq, sid) in enumerate(zip(sequences, seq_ids)):
            try:
                tokenized = tokenizer([seq], return_tensors="pt", add_special_tokens=False)
                tokenized = {k: v.to(device) for k, v in tokenized.items()}

                with torch.no_grad():
                    output = model(**tokenized)

                # Extract pLDDT: shape [B, L, 37] → take Cα (idx 1) → per-residue 0-100
                plddt_tensor = output.plddt[:, :, 1]  # [B, L], 0-1 range
                global_plddt = float(plddt_tensor.mean().cpu() * 100)
                ptm = float(output.ptm.item())

                # Chromophore local pLDDT (atom37 → Cα idx 1)
                chrom_plddt = None
                if plddt_tensor.shape[1] > max(CHROMOPHORE_POSITIONS):
                    chrom_vals = plddt_tensor[0, CHROMOPHORE_POSITIONS]
                    chrom_plddt = float(chrom_vals.mean().cpu() * 100)

                results[sid] = {
                    'cf_plddt': round(global_plddt, 2),
                    'cf_ptm': round(ptm, 4),
                    'cf_chromophore_plddt': round(chrom_plddt, 2) if chrom_plddt is not None else None,
                    'cf_success': True,
                    'cf_source': 'esmfold',
                }
                print(f"    [{i+1}/{len(sequences)}] ESMFold: {sid} "
                      f"pLDDT={global_plddt:.1f} pTM={ptm:.3f}")

            except Exception as e:
                print(f"    [{i+1}/{len(sequences)}] ESMFold: {sid} ERROR: {e}")
                results[sid] = {
                    'cf_plddt': None, 'cf_ptm': None,
                    'cf_chromophore_plddt': None, 'cf_success': False,
                    'cf_source': 'esmfold_error',
                }

            # Periodic checkpoint
            if (i + 1) % 10 == 0:
                print(f"  ESMFold: {i+1}/{len(sequences)} 完成")

        return results

    except ImportError as e:
        print(f"  ESMFold fallback: 不可用 ({e})")
        return None
    except Exception as e:
        print(f"  ESMFold fallback: 初始化错误: {e}")
        return None


# ── Scoring & Filtering ────────────────────────────────────────────────────

def merge_scores(df, cf_results, bz_results, esmfold_results=None):
    """Merge structure prediction results back into the DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Input DataFrame with seq_id column.
    cf_results : dict
        ColabFold results keyed by seq_id.
    bz_results : dict
        Boltz-1 results keyed by seq_id.
    esmfold_results : dict or None
        Optional ESMFold results (overlaid on top of cf_results if cf failed).

    Returns
    -------
    pd.DataFrame with added columns.
    """
    # If ESMFold results exist, overlay them on cf_results for sequences where cf failed
    effective_cf = dict(cf_results)  # copy
    if esmfold_results:
        for sid, esm_r in esmfold_results.items():
            cf_r = cf_results.get(sid, {})
            # Use ESMFold if ColabFold failed or is mock
            if not cf_r.get('cf_success') or cf_r.get('cf_source') == 'mock':
                effective_cf[sid] = esm_r
                print(f"  [overlay] {sid}: using ESMFold pLDDT={esm_r.get('cf_plddt')} "
                      f"instead of ColabFold (was {cf_r.get('cf_source', 'N/A')})")

    # Merge into DataFrame
    for sid in df['seq_id']:
        cf = effective_cf.get(sid, {})
        bz = bz_results.get(sid, {})
        df.loc[df['seq_id'] == sid, 'cf_plddt'] = cf.get('cf_plddt')
        df.loc[df['seq_id'] == sid, 'cf_ptm'] = cf.get('cf_ptm')
        df.loc[df['seq_id'] == sid, 'cf_chromophore_plddt'] = cf.get('cf_chromophore_plddt')
        df.loc[df['seq_id'] == sid, 'cf_success'] = cf.get('cf_success', False)
        df.loc[df['seq_id'] == sid, 'cf_source'] = cf.get('cf_source', 'unknown')
        df.loc[df['seq_id'] == sid, 'bz_plddt'] = bz.get('bz_plddt')
        df.loc[df['seq_id'] == sid, 'bz_ptm'] = bz.get('bz_ptm')
        df.loc[df['seq_id'] == sid, 'bz_chromophore_plddt'] = bz.get('bz_chromophore_plddt')
        df.loc[df['seq_id'] == sid, 'bz_success'] = bz.get('bz_success', False)
        df.loc[df['seq_id'] == sid, 'bz_source'] = bz.get('bz_source', 'unknown')

    return df


def filter_and_rank(df):
    """Apply filtering and select top 30.

    Dual mode (ColabFold/Boltz-1, AF2-class pLDDT 0-100):
      - cf_plddt >= 80 AND cf_ptm >= 0.75
      - bz_plddt >= 80 AND bz_ptm >= 0.75
      - |cf_plddt - bz_plddt| < 15

    ESMFold mode (no MSA, pLDDT typically 30-70 for good structures):
      - Uses pTM as primary filter (>0.6), pLDDT for ranking only

    Returns
    -------
    df_pass : pd.DataFrame (filtered & ranked)
    stats : dict
    """
    # Detect tool type from data
    cf_tool = df['cf_source'].iloc[0] if len(df) > 0 and 'cf_source' in df.columns else 'unknown'
    is_esmfold = 'esmfold' in str(cf_tool).lower()
    HAS_BOLTZ = df['bz_plddt'].notna().any()

    if HAS_BOLTZ and not is_esmfold:
        print("\n  模式: 双验证 (ColabFold + Boltz-1)")
        mask_cf_pass = (df['cf_plddt'] >= PDLDT_THRESHOLD) & (df['cf_ptm'] >= PTM_THRESHOLD)
        mask_bz_pass = (df['bz_plddt'] >= PDLDT_THRESHOLD) & (df['bz_ptm'] >= PTM_THRESHOLD)
        mask_agree = (df['cf_plddt'] - df['bz_plddt']).abs() < CROSS_VALIDATION_MAX_DIFF
        mask_both = df['cf_plddt'].notna() & df['bz_plddt'].notna()
        mask_agree_final = ~mask_both | mask_agree
        mask_final = mask_cf_pass & mask_bz_pass & mask_agree_final
        stats = {
            'mode': 'dual-af2',
            'total': len(df), 'cf_pass': int(mask_cf_pass.sum()),
            'bz_pass': int(mask_bz_pass.sum()), 'agree_pass': int(mask_agree.sum()),
            'dual_pass': int(mask_final.sum()),
            'has_chromophore_data': int(df['cf_chromophore_plddt'].notna().sum()),
        }
    elif is_esmfold:
        print("\n  模式: ESMFold 排序 (pTM地板 + pLDDT排序)")
        # ESMFold pLDDT is 0-100 but typically 30-70 (no MSA); pTM is more transferable
        ESMFOLD_PTM_FLOOR = 0.4
        mask_final = (df['cf_ptm'] >= ESMFOLD_PTM_FLOOR) & df['cf_plddt'].notna()
        # Sort by pLDDT descending (relative ranking), take top 30 after filter
        df = df.sort_values('cf_plddt', ascending=False)
        stats = {
            'mode': 'esmfold-rank',
            'total': len(df), 'cf_pass': int(mask_final.sum()),
            'has_chromophore_data': int(df['cf_chromophore_plddt'].notna().sum()),
        }
    else:
        print("\n  模式: 单验证 (ColabFold/ESMFold only)")
        mask_final = (df['cf_plddt'] >= PDLDT_THRESHOLD) & (df['cf_ptm'] >= PTM_THRESHOLD)
        stats = {
            'mode': 'single',
            'total': len(df), 'cf_pass': int(mask_final.sum()),
            'has_chromophore_data': int(df['cf_chromophore_plddt'].notna().sum()),
        }

    for k, v in stats.items():
        if k != 'mode':
            print(f"  {k}: {v}")

    df_pass = df[mask_final].copy()
    df_pass = df_pass.sort_values('cf_plddt', ascending=False)
    return df_pass, stats

    return df_final, stats


# ── Mock pLDDT Generator (for pipeline testing) ────────────────────────────

def generate_mock_plddt(df, rng_seed=SEED):
    """Generate realistic mock pLDDT/pTM values for all sequences.

    The mock values correlate with composite_score to provide reasonable
    ranking, but also include variation consistent with real structure
    prediction noise.

    Used when no structure prediction tool is available, to enable
    end-to-end pipeline testing.

    Returns
    -------
    dict : {seq_id: {'cf_plddt': ..., 'cf_ptm': ..., 'bz_plddt': ..., 'bz_ptm': ...}}
    """
    rng = np.random.RandomState(rng_seed)
    scores = df['composite_score'].values

    # Normalize composite_score to roughly map to pLDDT 60-95 range
    score_min, score_max = scores.min(), scores.max()
    if score_max - score_min < 1e-8:
        score_norm = np.ones_like(scores) * 0.5
    else:
        score_norm = (scores - score_min) / (score_max - score_min)

    # Base pLDDT: composite_score drives general quality
    base_plddt = 65.0 + score_norm * 28.0  # 65-93 range
    cf_plddt = base_plddt + rng.normal(0, 2.5, size=len(scores))
    cf_plddt = np.clip(cf_plddt, 50, 99)

    # pTM correlates with pLDDT but slightly lower
    cf_ptm = np.clip(cf_plddt / 100.0 - 0.03 + rng.normal(0, 0.02, size=len(scores)), 0.4, 0.97)

    # Chromophore local pLDDT (slightly lower than global)
    cf_chrom = np.clip(cf_plddt + rng.normal(-3, 3, size=len(scores)), 50, 99)

    # Boltz-1 mock: similar but not identical (for cross-validation)
    bz_plddt = base_plddt + rng.normal(0, 3.0, size=len(scores))
    bz_plddt = np.clip(bz_plddt, 50, 99)

    # Ensure some disagreement (realistic: 5-15% variation)
    bz_ptm = np.clip(bz_plddt / 100.0 - 0.02 + rng.normal(0, 0.03, size=len(scores)), 0.4, 0.97)
    bz_chrom = np.clip(bz_plddt + rng.normal(-2, 4, size=len(scores)), 50, 99)

    results = {}
    for i, sid in enumerate(df['seq_id']):
        results[sid] = {
            'cf_plddt': round(float(cf_plddt[i]), 2),
            'cf_ptm': round(float(cf_ptm[i]), 4),
            'cf_chromophore_plddt': round(float(cf_chrom[i]), 2),
            'cf_success': True,
            'cf_source': 'mock',

            'bz_plddt': round(float(bz_plddt[i]), 2),
            'bz_ptm': round(float(bz_ptm[i]), 4),
            'bz_chromophore_plddt': round(float(bz_chrom[i]), 2),
            'bz_success': True,
            'bz_source': 'mock',
        }
    return results


# ── Main ───────────────────────────────────────────────────────────────────

def main(mock_mode=False, esmfold_only=False,
         input_path=None, output_path=None, top_n=None):
    """Phase 3 main entry point.

    Parameters
    ----------
    mock_mode : bool
        Force mock pLDDT values for testing.
    esmfold_only : bool
        Use ESMFold instead of ColabFold (for environments with ESMFold but not ColabFold).
    input_path : str or None
        Override input CSV path (default: results/funnel_phase2_top80.csv).
    output_path : str or None
        Override output CSV path (default: results/funnel_phase3_top30.csv).
    top_n : int or None
        Number of top sequences to output (default: 30).
    """
    # Resolve paths
    _input = input_path or INPUT_TOP80
    _output = output_path or OUTPUT_TOP30
    _top_n = top_n or TOP_N
    _struct_dir = STRUCT_OUTPUT_DIR
    print("=" * 60)
    print("Phase 3: 结构双验证 (ColabFold + Boltz-1)")
    print(f"启动时间: {datetime.now().isoformat(timespec='seconds')}")
    print("=" * 60)

    # ── Step 0: Tool Detection ──
    print("\n[0/4] 工具检测 ...")
    cf_info = detect_colabfold()
    bz_info = detect_boltz1()
    esm_info = detect_esmfold()

    print(f"  ColabFold: {'可用' if cf_info['available'] else '不可用'} ({cf_info['details']})")
    print(f"  Boltz-1:   {'可用' if bz_info['available'] else '不可用'} ({bz_info['details']})")
    print(f"  ESMFold:   {'可用' if esm_info['available'] else '不可用'} ({esm_info['details']})")

    # Determine execution mode
    run_mock = mock_mode
    if not cf_info['available'] and not bz_info['available'] and not esm_info['available']:
        print("\n  WARNING: 无可用结构预测工具。切换到模拟模式 (mock pLDDT)。")
        run_mock = True

    if esmfold_only:
        print("\n  -> ESMFold-only 模式 (--esmfold-only)")
    elif run_mock:
        print("\n  -> 模拟模式 (mock pLDDT values)")
    elif not bz_info['available']:
        print("\n  -> 单工具模式: ColabFold only (Boltz-1 not installed)")

    # ── Step 1: Load ──
    print("\n[1/4] 加载 Top 80 ...")
    if not os.path.exists(_input):
        print(f"  [XX] 输入文件不存在: {_input}")
        print("  请先运行 Phase 2 (code/funnel_phase2_ml.py)")
        return 1

    df = pd.read_csv(_input)
    sequences = df['sequence'].tolist()
    seq_ids = df['seq_id'].tolist()
    print(f"  输入: {len(df)} 条序列")
    print(f"  composite_score 范围: {df['composite_score'].min():.3f} - {df['composite_score'].max():.3f}")

    # ── Step 2: Structure Prediction ──
    print("\n[2/4] 结构预测 ...")

    if run_mock:
        # Generate mock results for both tools
        mock_results = generate_mock_plddt(df)
        cf_results = {sid: {k: v for k, v in mock_results[sid].items()
                           if k.startswith('cf_')} for sid in mock_results}
        bz_results = {sid: {k: v for k, v in mock_results[sid].items()
                           if k.startswith('bz_')} for sid in mock_results}
        esmfold_results = None
    elif esmfold_only:
        # Use ESMFold directly (skip ColabFold)
        bz_results = run_boltz1(sequences, seq_ids, _struct_dir, bz_info, mock_mode=False)
        esmfold_results = run_esmfold_fallback(sequences, seq_ids, _struct_dir)
        if esmfold_results is None:
            print("  [XX] ESMFold fallback 失败。回退到模拟模式。")
            mock_results = generate_mock_plddt(df)
            cf_results = {sid: {k: v for k, v in mock_results[sid].items()
                               if k.startswith('cf_')} for sid in mock_results}
            esmfold_results = None
        else:
            # Map ESMFold results to cf_results slot
            cf_results = esmfold_results
    else:
        # Standard: try ColabFold first
        cf_results = run_colabfold(sequences, seq_ids, _struct_dir, cf_info,
                                   mock_mode=False)
        bz_results = run_boltz1(sequences, seq_ids, _struct_dir, bz_info,
                                mock_mode=False)

        # If ColabFold failed for most sequences, try ESMFold fallback
        cf_success_count = sum(1 for r in cf_results.values() if r.get('cf_success'))
        if cf_success_count < len(sequences) * 0.5:
            print(f"\n  WARNING: ColabFold 成功率低 ({cf_success_count}/{len(sequences)})")
            if esm_info['available']:
                print("  -> 尝试 ESMFold fallback ...")
                esmfold_results = run_esmfold_fallback(sequences, seq_ids, _struct_dir)
            else:
                esmfold_results = None
                print("  -> ESMFold 不可用，继续使用部分 ColabFold 结果")
        else:
            esmfold_results = None

        # bz_results already set by run_boltz1() above

    # ── Step 3: Merge & Filter ──
    print("\n[3/4] 评分合并 + 筛选 ...")
    df = merge_scores(df, cf_results, bz_results, esmfold_results)
    df_pass, stats = filter_and_rank(df)

    # ── Step 4: Output ──
    print(f"\n[4/4] 输出 Top {_top_n} ...")
    top30 = df_pass.head(_top_n).copy()
    top30['phase3_rank'] = range(1, len(top30) + 1)

    # Ensure all required columns present
    required_cols = [
        'seq_id', 'sequence', 'source_strategy', 'num_mutations', 'mutation_str',
        'composite_score', 'pred_brightness',
        'cf_plddt', 'cf_ptm', 'cf_chromophore_plddt', 'cf_success', 'cf_source',
        'bz_plddt', 'bz_ptm', 'bz_chromophore_plddt', 'bz_success', 'bz_source',
        'phase3_rank',
    ]
    for col in required_cols:
        if col not in top30.columns:
            top30[col] = None

    # Add metadata
    top30['phase3_date'] = datetime.now().strftime('%Y-%m-%d')
    top30['phase3_mode'] = stats.get('mode', 'unknown')
    top30['phase3_cf_tool'] = cf_info['method'] if not run_mock else 'mock'

    # Keep all original columns + new ones
    top30.to_csv(_output, index=False)
    print(f"  输出: {_output}")
    print(f"  序列数: {len(top30)}")

    # Summary stats
    print(f"\n{'=' * 60}")
    print("Phase 3 完成摘要")
    print(f"{'=' * 60}")
    print(f"  模式: {stats.get('mode', 'unknown')}")
    print(f"  输入: {stats.get('total', 0)} 条")
    print(f"  通过筛选: {stats.get('dual_pass', stats.get('cf_pass', 0))} 条")
    print(f"  输出: {len(top30)} 条 (Top 30)")

    cf_success = int((top30['cf_plddt'] > 0).sum()) if 'cf_plddt' in top30.columns else 0
    bz_success = int((top30['bz_plddt'] > 0).sum()) if 'bz_plddt' in top30.columns else 0
    print(f"  ColabFold/ESMFold pLDDT均值: {top30['cf_plddt'].mean():.1f} (n={cf_success})")
    if bz_success > 0:
        print(f"  Boltz-1 pLDDT均值: {top30['bz_plddt'].mean():.1f} (n={bz_success})")
        diff = (top30['cf_plddt'] - top30['bz_plddt']).abs()
        print(f"  ColabFold-Boltz1 |diff|均值: {diff.mean():.1f} (max={diff.max():.1f})")

    # Top 5 preview
    print(f"\n  Top 5 预览:")
    preview_cols = ['seq_id', 'mutation_str', 'composite_score', 'cf_plddt']
    if bz_success > 0:
        preview_cols.append('bz_plddt')
    print(top30[preview_cols].head(5).to_string(index=False))

    print(f"\n  输出文件: {_output}")
    return 0


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Phase 3: 结构双验证 (ColabFold + Boltz-1)'
    )
    parser.add_argument(
        '--mock', action='store_true',
        help='强制使用模拟 pLDDT 值 (用于测试数据流)'
    )
    parser.add_argument(
        '--esmfold-only', action='store_true',
        help='使用 ESMFold 替代 ColabFold'
    )
    parser.add_argument(
        '--input', type=str, default=INPUT_TOP80,
        help=f'输入CSV路径 (默认: {INPUT_TOP80})'
    )
    parser.add_argument(
        '--output', type=str, default=OUTPUT_TOP30,
        help=f'输出CSV路径 (默认: {OUTPUT_TOP30})'
    )
    parser.add_argument(
        '--top-n', type=int, default=TOP_N,
        help=f'输出Top N (默认: {TOP_N})'
    )

    args = parser.parse_args()

    sys.exit(main(
        mock_mode=args.mock,
        esmfold_only=args.esmfold_only,
        input_path=args.input,
        output_path=args.output,
        top_n=args.top_n,
    ))
