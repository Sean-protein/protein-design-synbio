# -*- coding: utf-8 -*-
"""将AutoDL GPU结果(ColabFold + ThermoMPNN)合并入漏斗数据流

用法:
  python code/merge_gpu_results.py \\
    --cf-results deploy/colabfold_results.csv \\
    --thermo-results deploy/thermompnn_results.csv \\
    --phase2-input results/funnel_phase2_top80.csv \\
    --output results/funnel_phase3_input_with_gpu.csv

功能:
  1. 加载Phase 2 Top 80 (含多样性配额修复)
  2. LEFT JOIN ColabFold真实pLDDT/pTM
  3. LEFT JOIN ThermoMPNN真实ΔTm
  4. 输出合并CSV，可直接供Phase 3/4使用
"""
import os, sys, argparse
import pandas as pd
import numpy as np


def main():
    parser = argparse.ArgumentParser(description='Merge GPU results into funnel')
    parser.add_argument('--cf-results', default='deploy/colabfold_results.csv',
                       help='ColabFold pLDDT/pTM CSV from AutoDL')
    parser.add_argument('--thermo-results', default='deploy/thermompnn_results.csv',
                       help='ThermoMPNN dTm CSV from AutoDL')
    parser.add_argument('--phase2-input', default='results/funnel_phase2_top80.csv',
                       help='Phase 2 Top 80 CSV')
    parser.add_argument('--output', default='results/funnel_phase3_input_with_gpu.csv',
                       help='Merged output CSV')
    args = parser.parse_args()

    # 1. Load Phase 2 Top 80
    print(f"Loading Phase 2 Top 80: {args.phase2_input}")
    df = pd.read_csv(args.phase2_input)
    print(f"  {len(df)} sequences")
    for s in ['A', 'D', 'C']:
        print(f"  Strategy {s}: {(df['source_strategy']==s).sum()}")

    # 2. Merge ColabFold results
    cf_path = args.cf_results
    if os.path.exists(cf_path):
        print(f"\nMerging ColabFold results: {cf_path}")
        cf = pd.read_csv(cf_path)
        print(f"  {len(cf)} predictions")

        # Match by seq_id
        cf_cols = ['seq_id', 'cf_plddt', 'cf_ptm', 'cf_chromophore_plddt',
                   'cf_success', 'cf_source']
        cf_subset = cf[[c for c in cf_cols if c in cf.columns]].copy()

        # If ColabFold used different IDs, try matching by index position
        if not df['seq_id'].iloc[0] in cf_subset['seq_id'].values:
            print("  WARNING: seq_id mismatch, attempting positional match...")
            # Align by row order (ColabFold processes FASTA in order)
            for col in cf_subset.columns:
                if col != 'seq_id' and col in df.columns:
                    df.drop(columns=[col], inplace=True, errors='ignore')
            for i, cf_row in cf_subset.iterrows():
                if i < len(df):
                    for col in cf_subset.columns:
                        if col != 'seq_id':
                            df.at[df.index[i], col] = cf_row[col]
        else:
            # Normal merge by seq_id
            for col in cf_subset.columns:
                if col != 'seq_id' and col in df.columns:
                    df.drop(columns=[col], inplace=True, errors='ignore')
            df = df.merge(cf_subset, on='seq_id', how='left')

        # Mark sequences with real ColabFold data
        df['cf_source'] = df.get('cf_source', pd.Series(['real_colabfold']*len(df)))
        df['cf_success'] = df.get('cf_success', pd.Series([True]*len(df)))
        n_real = df['cf_plddt'].notna().sum() if 'cf_plddt' in df.columns else 0
        print(f"  Merged: {n_real}/{len(df)} with pLDDT values")
        if 'cf_plddt' in df.columns:
            valid = df['cf_plddt'].notna()
            if valid.any():
                print(f"  pLDDT range: [{df.loc[valid,'cf_plddt'].min():.1f}, "
                      f"{df.loc[valid,'cf_plddt'].max():.1f}]")
    else:
        print(f"\n  ColabFold results not found at {cf_path}")
        print("  Will use mock pLDDT (run on AutoDL first!)")

    # 3. Merge ThermoMPNN results
    thermo_path = args.thermo_results
    if os.path.exists(thermo_path):
        print(f"\nMerging ThermoMPNN results: {thermo_path}")
        tp = pd.read_csv(thermo_path)
        print(f"  {len(tp)} predictions")

        if 'seq_id' in tp.columns and 'thermo_dTm' in tp.columns:
            if 'thermo_dTm' in df.columns:
                df.drop(columns=['thermo_dTm'], inplace=True)
            if 'thermo_status' in df.columns:
                df.drop(columns=['thermo_status'], inplace=True)

            df = df.merge(tp[['seq_id', 'thermo_dTm']], on='seq_id', how='left')
            n_real = df['thermo_dTm'].notna().sum()
            print(f"  Merged: {n_real}/{len(df)} with dTm values")
            if n_real > 0:
                print(f"  dTm range: [{df['thermo_dTm'].min():.1f}, "
                      f"{df['thermo_dTm'].max():.1f}]")
    else:
        print(f"\n  ThermoMPNN results not found at {thermo_path}")

    # 4. Save
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    df.to_csv(args.output, index=False)
    print(f"\nOutput: {args.output} ({len(df)} sequences)")
    print("Done. Use this as input for Phase 3 (funnel_phase3_structure.py).")


if __name__ == '__main__':
    main()
