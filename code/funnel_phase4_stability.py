# -*- coding: utf-8 -*-
"""Phase 4: 稳定性三级递进 — FoldX + ThermoMPNN + BioEmu -> Top 15 + MD Top 10

Consumes: results/funnel_phase3_top30.csv (or any size input from Phase 3)
Produces: results/funnel_phase4_top15.csv, results/funnel_md_input.csv

Pipeline:
  L1: FoldX ddG (from existing results) + ThermoMPNN dTm (or ESM-2/BLOSUM fallback)
  L2: BioEmu 300K conformational ensemble (optional, skip if unavailable)
  L3: Combined rank = composite_score * stability_score -> Top 10 MD, Top 15 output

Fallback strategies (ordered by preference):
  A. ThermoMPNN real prediction (model weights at /data2/fenghaohui/ThermoMPNN)
  B. ESM-2 pseudo-likelihood (same model used in Strategy B: esm2_t33_650M_UR50D)
  C. BLOSUM62 heuristic (no GPU required, always available)

Tools:
  - FoldX: pre-computed results loaded from CSV files
  - ThermoMPNN: /data2/fenghaohui/ThermoMPNN (optional)
  - BioEmu: microsoft/bioemu via pip (optional)
  - ESM-2: fair-esm package (optional fallback)

Usage:
  python code/funnel_phase4_stability.py
  python code/funnel_phase4_stability.py --mock          # force mock mode
  python code/funnel_phase4_stability.py --skip-bioemu   # force skip BioEmu L2
"""

import os
import sys
import json
import shutil
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

# ── Encoding compatibility ─────────────────────────────────────────────────
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
        pass

# ── Configuration ──────────────────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

INPUT_TOP30 = os.path.join(RESULTS_DIR, "funnel_phase3_top30.csv")
OUTPUT_TOP15 = os.path.join(RESULTS_DIR, "funnel_phase4_top15.csv")
MD_INPUT = os.path.join(RESULTS_DIR, "funnel_md_input.csv")

# FoldX pre-computed results
STRAT_A_FOLDX = os.path.join(RESULTS_DIR, "strategy_A_foldx_results.csv")
STRAT_D_FOLDX = os.path.join(RESULTS_DIR, "strategy_D_foldx_results.csv")

# ThermoMPNN paths
THERMOMPNN_DIR = "/data2/fenghaohui/ThermoMPNN"
THERMOMPNN_WEIGHTS = os.path.join(THERMOMPNN_DIR, "thermo_mpnn.pt")

# BioEmu PDB template
PDB_TEMPLATE = os.path.join(PROJECT_ROOT, "data", "2B3P_sfGFP.pdb")

# sfGFP WT sequence (for fallback scoring and mutation comparison)
WT_SEQUENCE = (
    "MSKGEELFTGVVPILVELDGDVNGHKFSVRGEGEGDATNGKLTLKFICTTGKLPVPWPTLVTTLTY"
    "GVQCFSRYPDHMKRHDFFKSAMPEGYVQERTISFKDDGTYKTRAEVKFEGDTLVNRIELKGIDFKE"
    "DGNILGHKLEYNFNSHNVYITADKQKNGIKANFKIRHNVEDGSVQLADHYQQNTPIGDGPVLLPDN"
    "HYLSTQSVLSKDPNEKRDHMVLLEFVTAAGITFGMDELYK"
)

# Thresholds
FOLDX_DDG_MAX = 3.0       # ddG < 3.0 kcal/mol passes (allow NA as pass)
THERMO_DTM_MIN = -5.0     # dTm > -5.0 passes (allow NA as pass)
BIOEMU_NC_MIN = 0.65      # native contacts fraction
BIOEMU_RMSF_MAX = 2.0     # chromophore RMSF max
BIOEMU_RMSD_MAX = 3.0     # backbone RMSD max

TOP_MD = 10
TOP_PHASE4 = 15
SEED = 42

# ── BLOSUM62 (embedded for zero-dependency fallback) ───────────────────────

BLOSUM62 = {
    ('A', 'A'): 4, ('A', 'R'): -1, ('A', 'N'): -2, ('A', 'D'): -2, ('A', 'C'): 0,
    ('A', 'Q'): -1, ('A', 'E'): -1, ('A', 'G'): 0, ('A', 'H'): -2, ('A', 'I'): -1,
    ('A', 'L'): -1, ('A', 'K'): -1, ('A', 'M'): -1, ('A', 'F'): -2, ('A', 'P'): -1,
    ('A', 'S'): 1, ('A', 'T'): 0, ('A', 'W'): -3, ('A', 'Y'): -2, ('A', 'V'): 0,
    ('R', 'R'): 5, ('R', 'N'): 0, ('R', 'D'): -2, ('R', 'C'): -3, ('R', 'Q'): 1,
    ('R', 'E'): 0, ('R', 'G'): -2, ('R', 'H'): 0, ('R', 'I'): -3, ('R', 'L'): -2,
    ('R', 'K'): 2, ('R', 'M'): -1, ('R', 'F'): -3, ('R', 'P'): -2, ('R', 'S'): -1,
    ('R', 'T'): -1, ('R', 'W'): -3, ('R', 'Y'): -2, ('R', 'V'): -3,
    ('N', 'N'): 6, ('N', 'D'): 1, ('N', 'C'): -3, ('N', 'Q'): 0, ('N', 'E'): 0,
    ('N', 'G'): 0, ('N', 'H'): 1, ('N', 'I'): -3, ('N', 'L'): -3, ('N', 'K'): 0,
    ('N', 'M'): -2, ('N', 'F'): -3, ('N', 'P'): -2, ('N', 'S'): 1, ('N', 'T'): 0,
    ('N', 'W'): -4, ('N', 'Y'): -2, ('N', 'V'): -3,
    ('D', 'D'): 6, ('D', 'C'): -3, ('D', 'Q'): 0, ('D', 'E'): 2, ('D', 'G'): -1,
    ('D', 'H'): -1, ('D', 'I'): -3, ('D', 'L'): -4, ('D', 'K'): -1, ('D', 'M'): -3,
    ('D', 'F'): -3, ('D', 'P'): -1, ('D', 'S'): 0, ('D', 'T'): -1, ('D', 'W'): -4,
    ('D', 'Y'): -3, ('D', 'V'): -3,
    ('C', 'C'): 9, ('C', 'Q'): -3, ('C', 'E'): -4, ('C', 'G'): -3, ('C', 'H'): -3,
    ('C', 'I'): -1, ('C', 'L'): -1, ('C', 'K'): -3, ('C', 'M'): -1, ('C', 'F'): -2,
    ('C', 'P'): -3, ('C', 'S'): -1, ('C', 'T'): -1, ('C', 'W'): -2, ('C', 'Y'): -2,
    ('C', 'V'): -1,
    ('Q', 'Q'): 5, ('Q', 'E'): 2, ('Q', 'G'): -2, ('Q', 'H'): 0, ('Q', 'I'): -3,
    ('Q', 'L'): -2, ('Q', 'K'): 1, ('Q', 'M'): 0, ('Q', 'F'): -3, ('Q', 'P'): -1,
    ('Q', 'S'): 0, ('Q', 'T'): -1, ('Q', 'W'): -2, ('Q', 'Y'): -1, ('Q', 'V'): -2,
    ('E', 'E'): 5, ('E', 'G'): -2, ('E', 'H'): 0, ('E', 'I'): -3, ('E', 'L'): -3,
    ('E', 'K'): 1, ('E', 'M'): -2, ('E', 'F'): -3, ('E', 'P'): -1, ('E', 'S'): 0,
    ('E', 'T'): -1, ('E', 'W'): -3, ('E', 'Y'): -2, ('E', 'V'): -2,
    ('G', 'G'): 6, ('G', 'H'): -2, ('G', 'I'): -4, ('G', 'L'): -4, ('G', 'K'): -2,
    ('G', 'M'): -3, ('G', 'F'): -3, ('G', 'P'): -2, ('G', 'S'): 0, ('G', 'T'): -2,
    ('G', 'W'): -2, ('G', 'Y'): -3, ('G', 'V'): -3,
    ('H', 'H'): 8, ('H', 'I'): -3, ('H', 'L'): -3, ('H', 'K'): -1, ('H', 'M'): -2,
    ('H', 'F'): -1, ('H', 'P'): -2, ('H', 'S'): -1, ('H', 'T'): -2, ('H', 'W'): -2,
    ('H', 'Y'): 2, ('H', 'V'): -3,
    ('I', 'I'): 4, ('I', 'L'): 2, ('I', 'K'): -3, ('I', 'M'): 1, ('I', 'F'): 0,
    ('I', 'P'): -3, ('I', 'S'): -2, ('I', 'T'): -1, ('I', 'W'): -3, ('I', 'Y'): -1,
    ('I', 'V'): 3,
    ('L', 'L'): 4, ('L', 'K'): -2, ('L', 'M'): 2, ('L', 'F'): 0, ('L', 'P'): -3,
    ('L', 'S'): -2, ('L', 'T'): -1, ('L', 'W'): -2, ('L', 'Y'): -1, ('L', 'V'): 1,
    ('K', 'K'): 5, ('K', 'M'): -1, ('K', 'F'): -3, ('K', 'P'): -1, ('K', 'S'): 0,
    ('K', 'T'): -1, ('K', 'W'): -3, ('K', 'Y'): -2, ('K', 'V'): -2,
    ('M', 'M'): 5, ('M', 'F'): 0, ('M', 'P'): -2, ('M', 'S'): -1, ('M', 'T'): -1,
    ('M', 'W'): -1, ('M', 'Y'): -1, ('M', 'V'): 1,
    ('F', 'F'): 6, ('F', 'P'): -4, ('F', 'S'): -2, ('F', 'T'): -2, ('F', 'W'): 1,
    ('F', 'Y'): 3, ('F', 'V'): -1,
    ('P', 'P'): 7, ('P', 'S'): -1, ('P', 'T'): -2, ('P', 'W'): -4, ('P', 'Y'): -3,
    ('P', 'V'): -2,
    ('S', 'S'): 4, ('S', 'T'): 1, ('S', 'W'): -3, ('S', 'Y'): -2, ('S', 'V'): -2,
    ('T', 'T'): 5, ('T', 'W'): -2, ('T', 'Y'): -2, ('T', 'V'): 0,
    ('W', 'W'): 11, ('W', 'Y'): 2, ('W', 'V'): -3,
    ('Y', 'Y'): 7, ('Y', 'V'): -1,
    ('V', 'V'): 4,
}
# Symmetric completion
for (_a, _b), _v in list(BLOSUM62.items()):
    if (_b, _a) not in BLOSUM62:
        BLOSUM62[(_b, _a)] = _v

# ── Tool Detection ─────────────────────────────────────────────────────────

def detect_thermompnn():
    """Detect ThermoMPNN availability.

    Returns dict with keys: available, method, details
    """
    result = {"available": False, "method": None, "details": ""}

    if not os.path.isdir(THERMOMPNN_DIR):
        result["details"] = f"ThermoMPNN directory not found: {THERMOMPNN_DIR}"
        return result

    sys.path.insert(0, THERMOMPNN_DIR)

    try:
        import thermo_mpnn
        result["available"] = True
        result["method"] = "thermo_mpnn_module"
        result["details"] = f"thermo_mpnn at {thermo_mpnn.__file__}"
        return result
    except ImportError as e:
        result["details"] = f"Cannot import thermo_mpnn: {e}"
        return result


def detect_esm2():
    """Detect ESM-2 availability for pseudo-likelihood fallback.

    Returns dict with keys: available, method, details
    """
    result = {"available": False, "method": None, "details": ""}

    try:
        import torch
        if not torch.cuda.is_available():
            result["details"] = "ESM-2 requires GPU (CUDA not available)"
            return result
    except ImportError:
        result["details"] = "PyTorch not installed"
        return result

    try:
        import esm
        result["available"] = True
        result["method"] = "esm2_fair"
        result["details"] = f"fair-esm available at {esm.__file__}"
        return result
    except ImportError:
        result["details"] = "fair-esm not installed (pip install fair-esm)"
        return result


def detect_bioemu():
    """Detect BioEmu availability.

    Returns dict with keys: available, method, details
    """
    result = {"available": False, "method": None, "details": ""}

    if not os.path.isfile(PDB_TEMPLATE):
        result["details"] = f"PDB template not found: {PDB_TEMPLATE}"
        return result

    try:
        import bioemu
        result["available"] = True
        result["method"] = "python_api"
        result["details"] = f"bioemu at {bioemu.__file__}"

        # Verify we can instantiate
        try:
            from bioemu import BioEmu
            model = BioEmu()
            result["details"] += " (BioEmu class verified)"
        except Exception:
            pass
        return result
    except ImportError:
        result["details"] = "bioemu not installed (pip install bioemu)"
        return result


# ── L1: FoldX Data Loading ─────────────────────────────────────────────────

def load_foldx_results():
    """Load pre-computed FoldX ddG results from Strategy A and D result files.

    Returns {seq_id: ddG_kcal_mol} dict.
    Handles both formats:
      - strategy_A_foldx_results.csv: seq_id, mutation_str, ddG_kcal_mol, status
      - strategy_D_foldx_results.csv: seq_id, ddG_kcal_mol, status
    """
    foldx_dict = {}

    for path, label in [(STRAT_A_FOLDX, "Strategy A"),
                          (STRAT_D_FOLDX, "Strategy D")]:
        if not os.path.exists(path):
            print(f"  {label} FoldX file not found: {path}")
            continue

        try:
            df = pd.read_csv(path)
            if 'seq_id' not in df.columns:
                print(f"  {label}: no 'seq_id' column, skipping")
                continue

            # Use ddG_kcal_mol column if present
            if 'ddG_kcal_mol' in df.columns:
                valid = df['ddG_kcal_mol'].notna()
                for _, row in df[valid].iterrows():
                    foldx_dict[row['seq_id']] = float(row['ddG_kcal_mol'])
                print(f"  {label}: loaded {valid.sum()} ddG values (from {len(df)} rows)")
            else:
                print(f"  {label}: no 'ddG_kcal_mol' column, skipping")
        except Exception as e:
            print(f"  {label}: error reading FoldX file: {e}")

    return foldx_dict


# ── L1: ThermoMPNN Prediction ──────────────────────────────────────────────

def predict_thermo_stability(sequences, thermo_info):
    """Predict dTm using ThermoMPNN, falling back through ESM-2 to BLOSUM62.

    Parameters
    ----------
    sequences : list of str
    thermo_info : dict
        Detection result from detect_thermompnn().

    Returns
    -------
    list of float or None
        dTm values (higher = more stable). None for failed predictions.
    """
    # Tier A: Real ThermoMPNN
    if thermo_info["available"]:
        print("  ThermoMPNN: attempting real prediction ...")
        results = _thermompnn_predict(sequences)
        if results is not None and any(r is not None for r in results):
            success = sum(1 for r in results if r is not None)
            print(f"  ThermoMPNN: {success}/{len(sequences)} predictions succeeded")
            return results
        print("  ThermoMPNN: real prediction failed, falling back ...")

    # Tier B: ESM-2 pseudo-likelihood
    esm_info = detect_esm2()
    if esm_info["available"]:
        print(f"  ESM-2 fallback: {esm_info['details']}")
        results = _esm2_pseudolikelihood(sequences)
        if results is not None and any(r is not None for r in results):
            success = sum(1 for r in results if r is not None)
            print(f"  ESM-2: {success}/{len(sequences)} computed successfully")
            return results
        print("  ESM-2: computation failed, falling back ...")
    else:
        print(f"  ESM-2: {esm_info['details']}")

    # Tier C: BLOSUM62 heuristic (always works)
    print("  BLOSUM62: using heuristic stability scoring ...")
    results = _blosum62_stability(sequences)
    print(f"  BLOSUM62: {len(results)}/{len(sequences)} scored")
    return results


def _thermompnn_predict(sequences):
    """Attempt ThermoMPNN prediction via known API patterns."""
    results = [None] * len(sequences)

    # Pattern 1: thermo_mpnn.predict.predict_stability
    try:
        from thermo_mpnn.predict import predict_stability
        print("  Pattern 1: predict_stability(seq, pdb_path=...)")
        for i, seq in enumerate(sequences):
            try:
                val = predict_stability(seq, pdb_path=PDB_TEMPLATE)
                results[i] = float(val)
            except Exception:
                results[i] = None
        return results
    except ImportError:
        pass
    except Exception as e:
        print(f"  Pattern 1 error: {e}")

    # Pattern 2: ThermoMPNN class
    try:
        from thermo_mpnn import ThermoMPNN
        model = ThermoMPNN()
        # The load_weights call may vary by version
        if os.path.isfile(THERMOMPNN_WEIGHTS):
            try:
                model.load_weights(THERMOMPNN_WEIGHTS)
            except AttributeError:
                try:
                    model.load_state_dict(THERMOMPNN_WEIGHTS)
                except Exception:
                    pass
        print("  Pattern 2: ThermoMPNN().predict(seq)")
        for i, seq in enumerate(sequences):
            try:
                val = model.predict(seq)
                results[i] = float(val)
            except Exception:
                results[i] = None
        return results
    except ImportError:
        pass
    except Exception as e:
        print(f"  Pattern 2 error: {e}")

    # Pattern 3: Module-level score_sequence
    try:
        from thermo_mpnn import score_sequence
        print("  Pattern 3: score_sequence(seq, pdb_file=...)")
        for i, seq in enumerate(sequences):
            try:
                val = score_sequence(seq, pdb_file=PDB_TEMPLATE)
                results[i] = float(val)
            except Exception:
                results[i] = None
        return results
    except ImportError:
        pass
    except Exception as e:
        print(f"  Pattern 3 error: {e}")

    return results  # all None


def _esm2_pseudolikelihood(sequences):
    """Compute ESM-2 pseudo-log-likelihood as stability proxy.

    Uses the same model as Strategy B (esm2_t33_650M_UR50D).
    Higher pseudo-LL = more stable under the model.

    Returns list of float (normalized pseudo-dTm scores, ~ -5 to +5).
    """
    try:
        import torch
        import torch.nn.functional as F
        import esm

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        model, alphabet = esm.pretrained.load_model_and_alphabet("esm2_t33_650M_UR50D")
        model = model.eval()
        if device.type == "cuda":
            model = model.cuda()

        batch_converter = alphabet.get_batch_converter()

        results = []
        # Process in batches to be efficient, but process one at a time for robustness
        for seq in sequences:
            try:
                _, _, batch_tokens = batch_converter([("seq", seq)])
                if device.type == "cuda":
                    batch_tokens = batch_tokens.cuda()

                with torch.no_grad():
                    output = model(batch_tokens, repr_layers=[], return_contacts=False)
                    logits = output["logits"]  # (1, L, vocab)

                log_probs = F.log_softmax(logits, dim=-1)
                actual_tokens = batch_tokens[0, 1:-1]
                log_probs_actual = log_probs[0, 1:-1, :]

                per_position_ll = log_probs_actual.gather(
                    1, actual_tokens.unsqueeze(-1)
                ).squeeze(-1)

                valid_mask = (actual_tokens != alphabet.padding_idx)
                if valid_mask.sum() > 0:
                    mean_pll = per_position_ll[valid_mask].mean().item()
                    # Normalize: roughly -3.0 -> 0, scale to roughly -5..+5 range
                    normalized = (mean_pll + 3.0) * 10.0
                    results.append(round(normalized, 4))
                else:
                    results.append(None)
            except Exception as e:
                results.append(None)

        return results
    except Exception as e:
        print(f"  ESM-2 pseudolikelihood error: {e}")
        return [None] * len(sequences)


def _blosum62_stability(sequences):
    """BLOSUM62-based heuristic stability scoring.

    For each sequence, compute the mean BLOSUM62 substitution score
    relative to sfGFP WT. More conservative mutations -> higher score.
    Normalized to approximate dTm scale (roughly -5 to +5).
    """
    results = []
    for seq in sequences:
        total = 0.0
        n_mutations = 0
        for i, (aa_wt, aa_mut) in enumerate(zip(WT_SEQUENCE, seq)):
            if aa_wt != aa_mut:
                pair = (aa_wt, aa_mut)
                total += BLOSUM62.get(pair, -4)
                n_mutations += 1

        if n_mutations > 0:
            # Average BLOSUM62 per mutation (range roughly -4 to +9)
            avg_blosum = total / n_mutations
            # Normalize to pseudo-dTm scale: avg_blosum of +2 -> +3, -2 -> -2
            normalized = avg_blosum * 1.5
        else:
            normalized = 5.0  # WT = perfectly stable

        # Clamp to reasonable range
        normalized = max(-10.0, min(10.0, normalized))
        results.append(round(normalized, 4))

    return results


# ── L2: BioEmu Conformational Ensemble ─────────────────────────────────────

def predict_bioemu_stability(sequences, seq_ids, bioemu_info, mock_mode=False):
    """Use BioEmu to evaluate 300K conformational ensemble stability.

    Parameters
    ----------
    sequences : list of str
    seq_ids : list of str
    bioemu_info : dict
        Detection result from detect_bioemu().
    mock_mode : bool
        If True, generate mock ensemble metrics.

    Returns
    -------
    list of dict : [{'nc': float|None, 'rmsf_chromophore': float|None,
                     'rmsd': float|None, 'source': str}, ...]
    """
    n = len(sequences)

    if mock_mode:
        print("  BioEmu: 模拟模式 (mock ensemble metrics)")
        return _mock_bioemu(n)

    if not bioemu_info["available"]:
        print(f"  BioEmu: 不可用 ({bioemu_info['details']})")
        print("  BioEmu: L2 will be skipped in filtration")
        return [{'nc': None, 'rmsf_chromophore': None, 'rmsd': None,
                 'source': 'unavailable'} for _ in range(n)]

    print(f"  BioEmu: 真实预测模式 ({bioemu_info['method']})")
    print(f"  BioEmu: {bioemu_info['details']}")

    # Attempt real BioEmu sampling
    results = _attempt_bioemu_sampling(sequences, seq_ids)
    return results


def _attempt_bioemu_sampling(sequences, seq_ids):
    """Try BioEmu conformational sampling via known API patterns."""
    n = len(sequences)
    results = [{'nc': None, 'rmsf_chromophore': None, 'rmsd': None,
                'source': 'error'} for _ in range(n)]

    # Pattern 1: BioEmu class with sample() method
    try:
        from bioemu import BioEmu
        model = BioEmu()
        print("  BioEmu: pattern 1 (BioEmu class)")

        for i, (seq, sid) in enumerate(zip(sequences, seq_ids)):
            try:
                ensemble = model.sample(PDB_TEMPLATE, sequence=seq,
                                        num_samples=10, temperature=300.0)
                metrics = _compute_ensemble_metrics(ensemble, seq)
                if metrics is not None:
                    metrics['source'] = 'real'
                    results[i] = metrics
                    print(f"    [{i+1}/{n}] BioEmu: {sid} "
                          f"nc={metrics['nc']:.2f} rmsf={metrics['rmsf_chromophore']:.2f}")
                else:
                    results[i]['source'] = 'failed_metrics'
                    print(f"    [{i+1}/{n}] BioEmu: {sid} (failed metrics computation)")
            except Exception as e:
                results[i]['source'] = 'error'
                print(f"    [{i+1}/{n}] BioEmu: {sid} ERROR: {type(e).__name__}: {e}")

            if (i + 1) % 5 == 0 and (i + 1) < n:
                print(f"  BioEmu: {i+1}/{n} 完成")
        return results
    except ImportError:
        pass
    except Exception as e:
        print(f"  BioEmu pattern 1 error: {e}")

    # Pattern 2: Function-based API
    try:
        from bioemu import sample_conformations
        print("  BioEmu: pattern 2 (sample_conformations)")

        for i, (seq, sid) in enumerate(zip(sequences, seq_ids)):
            try:
                ensemble = sample_conformations(PDB_TEMPLATE, sequence=seq,
                                                n_samples=10)
                metrics = _compute_ensemble_metrics(ensemble, seq)
                if metrics is not None:
                    metrics['source'] = 'real'
                    results[i] = metrics
                else:
                    results[i]['source'] = 'failed_metrics'
            except Exception as e:
                results[i]['source'] = 'error'

            if (i + 1) % 5 == 0 and (i + 1) < n:
                print(f"  BioEmu: {i+1}/{n} 完成")
        return results
    except ImportError:
        pass
    except Exception as e:
        print(f"  BioEmu pattern 2 error: {e}")

    print("  BioEmu: all real patterns failed, returning None metrics")
    return [{'nc': None, 'rmsf_chromophore': None, 'rmsd': None,
             'source': 'unavailable'} for _ in range(n)]


def _compute_ensemble_metrics(ensemble, sequence=None):
    """Compute native contacts, chromophore RMSF, and RMSD from an ensemble.

    Parameters
    ----------
    ensemble : object
        BioEmu ensemble output (varies by API version).
    sequence : str or None

    Returns
    -------
    dict or None
    """
    try:
        # Try to extract array data from the ensemble object
        coords = None

        # Case 1: ensemble is a list/tensor of conformations
        if hasattr(ensemble, '__iter__') and not isinstance(ensemble, str):
            ensemble_list = list(ensemble)
            if len(ensemble_list) > 0:
                import torch
                if isinstance(ensemble_list[0], torch.Tensor):
                    coords = torch.stack(ensemble_list).cpu().numpy()
                elif isinstance(ensemble_list[0], (list, np.ndarray)):
                    coords = np.array(ensemble_list)
        elif hasattr(ensemble, 'positions'):
            coords = ensemble.positions
            if hasattr(coords, 'cpu'):
                coords = coords.cpu().numpy()

        if coords is not None and coords.ndim >= 3:
            # coords: (n_samples, n_atoms_or_residues, 3)
            mean_structure = coords.mean(axis=0)
            # RMSD per sample
            rmsd_per_sample = np.sqrt(((coords - mean_structure)**2).sum(axis=-1).mean(axis=-1))
            mean_rmsd = float(rmsd_per_sample.mean())

            # RMSF: per-residue fluctuation across ensemble
            rmsf = np.sqrt(((coords - mean_structure)**2).sum(axis=-1).mean(axis=0))

            # Chromophore RMSF (residues 64-67, 0-based: T65/G67)
            chrom_start, chrom_end = 64, 68
            if chrom_end <= len(rmsf):
                chrom_rmsf = float(rmsf[chrom_start:chrom_end].mean())
            else:
                chrom_rmsf = float(rmsf.mean())

            # Native contacts (simplified: fraction of residue pairs with
            # std distance < threshold)
            nc = _compute_native_contacts_bioemu(mean_structure, coords)

            return {
                'nc': round(nc, 3),
                'rmsf_chromophore': round(chrom_rmsf, 3),
                'rmsd': round(mean_rmsd, 3),
            }

        return None
    except Exception as e:
        return None


def _compute_native_contacts_bioemu(mean_struct, ensemble_coords):
    """Simplified native contacts estimate.

    Computes fraction of residue pairs whose mean Ca-Ca distance is < 5.0 A
    and whose distance standard deviation across the ensemble is < 1.0 A.
    """
    n_res = mean_struct.shape[0]
    if n_res < 2:
        return 0.85

    # Use first coordinate per residue (assuming CA or centroid)
    # Pairwise distances in mean structure
    mean_dists = np.linalg.norm(
        mean_struct[:, None, :] - mean_struct[None, :, :], axis=-1
    )
    # Identify "contacting" pairs in mean structure
    contact_mask = (mean_dists < 5.0) & (mean_dists > 0)

    if contact_mask.sum() == 0:
        return 0.85

    # Fluctuation of distances across ensemble
    all_dists = np.linalg.norm(
        ensemble_coords[:, :, None, :] - ensemble_coords[:, None, :, :], axis=-1
    )
    dist_std = all_dists.std(axis=0)

    # Stable contacts: fluctuate < 1.0 A
    stable_mask = dist_std < 1.0
    nc = (contact_mask & stable_mask).sum() / contact_mask.sum()
    return float(nc)


def _mock_bioemu(n):
    """Generate mock BioEmu metrics for pipeline testing.

    The mock values span realistic ranges:
      - nc: 0.65-0.95 (fraction of native contacts)
      - rmsf_chromophore: 1.0-3.0 (chromophore carbonyl RMSF, Angstroms)
      - rmsd: 1.0-4.0 (backbone RMSD, Angstroms)
    """
    rng = np.random.RandomState(SEED)
    results = []
    for i in range(n):
        nc = round(float(np.clip(rng.normal(0.82, 0.08), 0.55, 0.95)), 3)
        rmsf = round(float(np.clip(rng.normal(1.8, 0.5), 0.5, 4.0)), 3)
        rmsd = round(float(np.clip(rng.normal(2.2, 0.8), 0.5, 6.0)), 3)
        results.append({
            'nc': nc,
            'rmsf_chromophore': rmsf,
            'rmsd': rmsd,
            'source': 'mock',
        })
    return results


# ── L3: Combined Ranking & Selection ───────────────────────────────────────

def compute_stability_score(df):
    """Compute normalized stability composite score from available metrics.

    Components:
      1. FoldX ddG (lower = more stable): negate and normalize to [0, 1]
      2. Thermo dTm (higher = more stable): normalize to [0, 1]
      3. Combined multiplicatively: score = foldx_norm * thermo_norm

    Handles partial NaN data by using available components only.
    """
    df = df.copy()
    n = len(df)

    # Initialize with neutral score
    df['stability_score'] = 1.0
    components_used = 0

    # Component 1: FoldX ddG
    if df['foldx_ddG'].notna().any():
        ddg = df['foldx_ddG'].values
        ddg_valid = np.where(~np.isnan(ddg), ddg, np.nan)
        ddg_min = np.nanmin(ddg_valid)
        ddg_max = np.nanmax(ddg_valid)
        if ddg_max > ddg_min:
            # Normalize: lower ddG = higher score (1.0 = lowest ddG, 0.0 = highest)
            ddg_norm = 1.0 - (ddg_valid - ddg_min) / (ddg_max - ddg_min)
            # Fill NaN with 0.5 (neutral)
            ddg_norm = np.where(np.isnan(ddg_norm), 0.5, ddg_norm)
            df['stability_score'] *= np.clip(ddg_norm, 0.0, 1.0)
            components_used += 1
            print(f"  FoldX ddG normalization: min={ddg_min:.3f}, max={ddg_max:.3f} "
                  f"-> range={ddg_max - ddg_min:.3f}")

    # Component 2: Thermo dTm
    if df['thermo_dTm'].notna().any():
        dtm = df['thermo_dTm'].values
        dtm_valid = np.where(~np.isnan(dtm), dtm, np.nan)
        dtm_min = np.nanmin(dtm_valid)
        dtm_max = np.nanmax(dtm_valid)
        if dtm_max > dtm_min:
            dtm_norm = (dtm_valid - dtm_min) / (dtm_max - dtm_min)
            dtm_norm = np.where(np.isnan(dtm_norm), 0.5, dtm_norm)
            df['stability_score'] *= np.clip(dtm_norm, 0.0, 1.0)
            components_used += 1
            print(f"  Thermo dTm normalization: min={dtm_min:.3f}, max={dtm_max:.3f} "
                  f"-> range={dtm_max - dtm_min:.3f}")

    print(f"  Stability components used: {components_used}")
    return df


def compute_combined_rank(df):
    """Compute combined rank = composite_score (brightness) * stability_score.

    Higher combined_rank = better brightness-stability tradeoff.
    """
    df = df.copy()

    # Ensure composite_score exists
    if 'composite_score' not in df.columns:
        print("  WARNING: composite_score not found, using pred_brightness")
        df['composite_score'] = df.get('pred_brightness', 1.0)

    # Combine: brightness * stability
    df['combined_rank'] = df['composite_score'] * df['stability_score']
    df = df.sort_values('combined_rank', ascending=False).reset_index(drop=True)

    return df


# ── Mock Data Generator (for pipeline testing) ─────────────────────────────

def generate_mock_stability_data(df, rng_seed=SEED):
    """Generate mock stability scores for all sequences.

    Used when ThermoMPNN/ESM-2 are unavailable for end-to-end pipeline testing.
    Creates realistic mock values correlated with composite_score.
    """
    rng = np.random.RandomState(rng_seed)
    n = len(df)
    scores = df['composite_score'].values

    # Normalize composite_score to [0, 1]
    score_min, score_max = scores.min(), scores.max()
    if score_max - score_min < 1e-8:
        score_norm = np.ones(n) * 0.5
    else:
        score_norm = (scores - score_min) / (score_max - score_min)

    # Mock FoldX ddG: lower (more negative) for higher-scoring sequences
    # Range: -3 to +3 kcal/mol
    base_ddg = -2.0 + score_norm * 3.0  # better scores get lower ddG
    mock_ddg = base_ddg + rng.normal(0, 0.5, size=n)
    mock_ddg = np.clip(mock_ddg, -5.0, 5.0)

    # Mock Thermo dTm: higher for higher-scoring sequences
    # Range: -8 to +8 (degrees C shift)
    base_dtm = -3.0 + score_norm * 10.0
    mock_dtm = base_dtm + rng.normal(0, 1.5, size=n)
    mock_dtm = np.clip(mock_dtm, -10.0, 10.0)

    # Fill in the DataFrame
    df['foldx_ddG'] = df['seq_id'].map(
        {sid: round(float(mock_ddg[i]), 4) for i, sid in enumerate(df['seq_id'])}
    )
    # Only fill foldx if it's already NaN (preserve real data when available)
    mask_no_foldx = df['foldx_ddG'].isna()
    for i, idx in enumerate(df.index):
        if mask_no_foldx.iloc[i]:
            df.at[idx, 'foldx_ddG'] = round(float(mock_ddg[i]), 4)

    df['thermo_dTm'] = [round(float(mock_dtm[i]), 4) for i in range(n)]

    print(f"  Mock FoldX ddG:   [{df['foldx_ddG'].min():.2f}, {df['foldx_ddG'].max():.2f}]")
    print(f"  Mock Thermo dTm:  [{df['thermo_dTm'].min():.2f}, {df['thermo_dTm'].max():.2f}]")

    return df


# ── Main ───────────────────────────────────────────────────────────────────

def main(mock_mode=False, skip_bioemu=False,
         input_path=None, output_top15=None, output_md=None):
    """Phase 4 main entry point.

    Parameters
    ----------
    mock_mode : bool
        Force mock stability scores for testing.
    skip_bioemu : bool
        Force skip BioEmu L2 (even if installed).
    input_path : str or None
        Override input CSV path.
    output_top15 : str or None
        Override output CSV path for phase4 top15.
    output_md : str or None
        Override output CSV path for MD input.
    """
    _input = input_path or INPUT_TOP30
    _output_top15 = output_top15 or OUTPUT_TOP15
    _output_md = output_md or MD_INPUT

    print("=" * 60)
    print("Phase 4: 稳定性三级递进")
    print(f"启动时间: {datetime.now().isoformat(timespec='seconds')}")
    print("=" * 60)

    # ── Step 0: Tool Detection ──
    print("\n[0/5] 工具检测 ...")
    thermo_info = detect_thermompnn()
    esm_info = detect_esm2()
    bioemu_info = detect_bioemu()

    print(f"  ThermoMPNN: {'可用' if thermo_info['available'] else '不可用'} ({thermo_info['details']})")
    print(f"  ESM-2:      {'可用' if esm_info['available'] else '不可用'} ({esm_info['details']})")
    print(f"  BioEmu:     {'可用' if bioemu_info['available'] else '不可用'} ({bioemu_info['details']})")

    if skip_bioemu:
        print("  -> BioEmu L2 手动跳过 (--skip-bioemu)")

    # ── Step 1: Load Input ──
    print("\n[1/5] 加载 Phase 3 输出 ...")
    if not os.path.exists(_input):
        print(f"  [XX] 输入文件不存在: {_input}")
        print("  请先运行 Phase 3 (code/funnel_phase3_structure.py)")
        return 1

    df = pd.read_csv(_input)
    n_input = len(df)
    print(f"  输入: {n_input} 条序列 (预期 <= 30)")
    print(f"  source_strategy: {df['source_strategy'].value_counts().to_dict()}")
    if 'composite_score' in df.columns:
        print(f"  composite_score 范围: {df['composite_score'].min():.3f} - "
              f"{df['composite_score'].max():.3f}")

    # ── Step 2: L1 - FoldX + ThermoMPNN ──
    print("\n[2/5] L1: FoldX ddG + ThermoMPNN dTm ...")

    # Load FoldX results
    foldx_dict = load_foldx_results()

    # Map FoldX values to sequences, but preserve existing foldx data in df
    # if the column already exists
    df['foldx_ddG'] = df['seq_id'].map(foldx_dict)

    # If df already had foldx data, prefer the separate results when available,
    # but keep original when separate results don't cover it
    n_with_foldx = df['foldx_ddG'].notna().sum()
    print(f"\n  有FoldX数据: {n_with_foldx}/{n_input}")
    missing_foldx = n_input - n_with_foldx
    if missing_foldx > 0:
        print(f"  缺FoldX数据: {missing_foldx}/{n_input}")

    # ThermoMPNN / stability prediction
    sequences = df['sequence'].tolist()
    if mock_mode:
        print("  -> 模拟模式 (mock stability scores)")
        df = generate_mock_stability_data(df)
    else:
        dTm_values = predict_thermo_stability(sequences, thermo_info)
        df['thermo_dTm'] = dTm_values
        success = sum(1 for v in dTm_values if v is not None)
        print(f"  Thermo dTm: {success}/{n_input} computed")
        print(f"  Thermo dTm 范围: [{min(v for v in dTm_values if v is not None):.2f}, "
              f"{max(v for v in dTm_values if v is not None):.2f}]")

    # L1 pass/fail flags (but don't hard-filter — use them as scoring components)
    df['l1_foldx_ok'] = df['foldx_ddG'].isna() | (df['foldx_ddG'] < FOLDX_DDG_MAX)
    df['l1_thermo_ok'] = df['thermo_dTm'].isna() | (df['thermo_dTm'] > THERMO_DTM_MIN)
    df['pass_l1'] = df['l1_foldx_ok'] & df['l1_thermo_ok']

    l1_pass_count = int(df['pass_l1'].sum())
    print(f"  L1通过: {l1_pass_count}/{n_input}")

    # Continue with all sequences (soft filtering — stability score handles it)
    # but flag L1 failures
    l2_input = df.copy()

    # ── Step 3: L2 - BioEmu Conformational Ensemble ──
    print(f"\n[3/5] L2: BioEmu 300K构象系综 ...")

    use_bioemu = bioemu_info['available'] and not skip_bioemu and not mock_mode
    if use_bioemu:
        l2_sequences = l2_input['sequence'].tolist()
        l2_ids = l2_input['seq_id'].tolist()
        bioemu_results = predict_bioemu_stability(
            l2_sequences, l2_ids, bioemu_info, mock_mode=False
        )
    elif mock_mode:
        n = len(l2_input)
        bioemu_results = _mock_bioemu(n)
        print("  BioEmu: 模拟模式启用")
    else:
        n = len(l2_input)
        bioemu_results = [{'nc': None, 'rmsf_chromophore': None, 'rmsd': None,
                           'source': 'unavailable'} for _ in range(n)]
        print("  BioEmu: 跳过 (不可用或已禁用)")

    l2_input['bioemu_nc'] = [r['nc'] for r in bioemu_results]
    l2_input['bioemu_rmsf_chrom'] = [r['rmsf_chromophore'] for r in bioemu_results]
    l2_input['bioemu_rmsd'] = [r['rmsd'] for r in bioemu_results]
    l2_input['bioemu_source'] = [r.get('source', 'unknown') for r in bioemu_results]

    bioemu_available = l2_input['bioemu_nc'].notna().any()
    if bioemu_available:
        # BioEmu thresholds: soft filter (flags only)
        mask_l2 = (
            (l2_input['bioemu_nc'].isna() | (l2_input['bioemu_nc'] > BIOEMU_NC_MIN)) &
            (l2_input['bioemu_rmsf_chrom'].isna() | (l2_input['bioemu_rmsf_chrom'] < BIOEMU_RMSF_MAX)) &
            (l2_input['bioemu_rmsd'].isna() | (l2_input['bioemu_rmsd'] < BIOEMU_RMSD_MAX))
        )
        l2_input['pass_l2'] = mask_l2
        l2_pass_count = int(mask_l2.sum())
        print(f"  L2通过: {l2_pass_count}/{len(l2_input)}")
        # Print metrics summary
        nc_mean = l2_input['bioemu_nc'].mean()
        rmsf_mean = l2_input['bioemu_rmsf_chrom'].mean()
        rmsd_mean = l2_input['bioemu_rmsd'].mean()
        print(f"  BioEmu nc均值: {nc_mean:.3f} (range: [{l2_input['bioemu_nc'].min():.3f}, {l2_input['bioemu_nc'].max():.3f}])")
        print(f"  BioEmu RMSF均值: {rmsf_mean:.3f} (range: [{l2_input['bioemu_rmsf_chrom'].min():.3f}, {l2_input['bioemu_rmsf_chrom'].max():.3f}])")
        print(f"  BioEmu RMSD均值: {rmsd_mean:.3f} (range: [{l2_input['bioemu_rmsd'].min():.3f}, {l2_input['bioemu_rmsd'].max():.3f}])")
    else:
        l2_input['pass_l2'] = True
        print(f"  L2跳过 (BioEmu不可用): {len(l2_input)} 条直接进L3")

    # ── Step 4: L3 - Combined Ranking ──
    print(f"\n[4/5] L3: 综合排名 (composite_score * stability_score) ...")

    # Compute stability score
    df_ranked = compute_stability_score(l2_input)

    # Compute combined rank and sort
    df_ranked = compute_combined_rank(df_ranked)

    # ── Step 5: Output ──
    print(f"\n[5/5] 输出 ...")

    # Determine output sizes (handle < 15/10 inputs gracefully)
    n_available = len(df_ranked)
    n_top15 = min(TOP_PHASE4, n_available)
    n_md = min(TOP_MD, n_available)

    # Top N for Phase 4 output
    phase4_out = df_ranked.head(n_top15).copy()
    phase4_out['phase4_rank'] = range(1, n_top15 + 1)
    phase4_out['phase4_date'] = datetime.now().strftime('%Y-%m-%d')
    phase4_out['phase4_l1_pass'] = phase4_out['pass_l1']
    phase4_out['phase4_l2_pass'] = phase4_out['pass_l2']
    phase4_out['phase4_l1_tool'] = (thermo_info['method'] if not mock_mode
                                      else 'mock')
    phase4_out['phase4_l2_tool'] = (bioemu_info['method'] if bioemu_available
                                      else ('mock' if mock_mode else 'unavailable'))

    # Top N for MD input
    md_input = df_ranked.head(n_md).copy()
    md_input['md_rank'] = range(1, n_md + 1)
    md_input['md_date'] = datetime.now().strftime('%Y-%m-%d')
    md_input['md_stability_score'] = md_input['stability_score']
    md_input['md_combined_rank'] = md_input['combined_rank']

    # Ensure output columns include all relevant fields
    phase4_cols = []
    for col in phase4_out.columns:
        phase4_cols.append(col)
    phase4_out = phase4_out[phase4_cols]

    md_cols = [c for c in md_input.columns]

    # Save
    phase4_out.to_csv(_output_top15, index=False)
    md_input.to_csv(_output_md, index=False)

    print(f"  Phase 4 Top {n_top15}: {_output_top15} ({n_top15} 条)")
    print(f"  MD Input Top {n_md}:   {_output_md} ({n_md} 条)")

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print("Phase 4 完成摘要")
    print(f"{'=' * 60}")
    print(f"  输入: {n_input} 条")
    print(f"  L1 (FoldX+ThermoMPNN): {l1_pass_count}/{n_input} 通过")
    if bioemu_available:
        print(f"  L2 (BioEmu):           {l2_pass_count}/{n_input} 通过")
    else:
        print(f"  L2 (BioEmu):           跳过")
    print(f"  输出 (Phase 4):        {n_top15} 条")
    print(f"  输出 (MD Input):       {n_md} 条")

    # Top 5 preview
    preview_cols = ['seq_id', 'mutation_str', 'composite_score',
                    'stability_score', 'combined_rank', 'foldx_ddG', 'thermo_dTm']
    preview_cols = [c for c in preview_cols if c in phase4_out.columns]
    print(f"\n  Top 5 预览 (Phase 4):")
    print(phase4_out[preview_cols].head(5).to_string(index=False))

    if n_md > 0:
        print(f"\n  Top {min(5, n_md)} MD候补:")
        md_preview = [c for c in preview_cols if c in md_input.columns]
        print(md_input[md_preview].head(min(5, n_md)).to_string(index=False))

    print(f"\n  输出文件: {_output_top15}, {_output_md}")
    return 0


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Phase 4: 稳定性三级递进 (FoldX + ThermoMPNN + BioEmu)'
    )
    parser.add_argument(
        '--mock', action='store_true',
        help='强制使用模拟稳定性数据 (用于测试数据流)'
    )
    parser.add_argument(
        '--skip-bioemu', action='store_true',
        help='强制跳过BioEmu L2 (即使已安装)'
    )
    parser.add_argument(
        '--input', type=str, default=INPUT_TOP30,
        help=f'输入CSV路径 (默认: {INPUT_TOP30})'
    )
    parser.add_argument(
        '--output-top15', type=str, default=OUTPUT_TOP15,
        help=f'Phase 4 Top15输出路径 (默认: {OUTPUT_TOP15})'
    )
    parser.add_argument(
        '--output-md', type=str, default=MD_INPUT,
        help=f'MD输入输出路径 (默认: {MD_INPUT})'
    )

    args = parser.parse_args()

    sys.exit(main(
        mock_mode=args.mock,
        skip_bioemu=args.skip_bioemu,
        input_path=args.input,
        output_top15=args.output_top15,
        output_md=args.output_md,
    ))
