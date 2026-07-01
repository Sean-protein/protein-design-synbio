# -*- coding: utf-8 -*-
"""策略B虚拟筛选：用已有ML评分 + FoldX ddG跨策略对比"""
import pandas as pd, numpy as np, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

RESULTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")

# Load
scored = pd.read_csv(os.path.join(RESULTS, "strategy_B", "candidate_scores.csv"))
existing = pd.read_csv(os.path.join(RESULTS, "funnel_phase5_final_6.csv"))
existing_ids = set(existing['seq_id'].tolist())
a_fx = pd.read_csv(os.path.join(RESULTS, "strategy_A_foldx_results.csv"))[['seq_id','ddG_kcal_mol']]
d_fx = pd.read_csv(os.path.join(RESULTS, "strategy_D_foldx_results.csv"))[['seq_id','ddG_kcal_mol']]
c_pool = pd.read_csv(os.path.join(RESULTS, "strategy_C", "strategy_C_candidates.csv"))
if 'seq_id' not in c_pool.columns:
    c_pool['seq_id'] = [f'SC_C_{i:04d}' for i in range(len(c_pool))]

print('='*70)
print('策略B ML虚拟筛选 — A/D/C全量对比')
print('='*70)

# ── Strategy A ──
print('\n' + '─'*70)
print('【策略A】ddG<3.0 且非当前6条，按ML brightness排序')
print('─'*70)
a_s = scored[scored['source']=='strategy_A'].copy()
a_ok = a_s[(a_s['ddG_kcal_mol'].fillna(999)<3.0) & (~a_s['seq_id'].isin(existing_ids))]
a_ok = a_ok.sort_values('composite_score', ascending=False)
print(f'候选: {len(a_ok)}条 | ML range:[{a_ok["composite_score"].min():.3f},{a_ok["composite_score"].max():.3f}] | ddG range:[{a_ok["ddG_kcal_mol"].min():.2f},{a_ok["ddG_kcal_mol"].max():.2f}]')
print('\nTop 15 by ML brightness:')
for i,(_,r) in enumerate(a_ok.head(15).iterrows()):
    print(f'  {i+1:2d}. {r["seq_id"]}: ML={r["composite_score"]:.3f} ddG={r["ddG_kcal_mol"]:.2f} | {str(r["mutation_str"])[:50]}')

# By ML/ddG product
a_ok = a_ok.copy()
a_ok['ml_ddg_product'] = a_ok['composite_score'] / np.maximum(a_ok['ddG_kcal_mol'].fillna(1.0), 0.5)
a_bal = a_ok.sort_values('ml_ddg_product', ascending=False)
print('\nTop 15 by ML/ddG (亮度×稳定性平衡):')
for i,(_,r) in enumerate(a_bal.head(15).iterrows()):
    print(f'  {i+1:2d}. {r["seq_id"]}: ML/ddG={r["ml_ddg_product"]:.3f} ML={r["composite_score"]:.3f} ddG={r["ddG_kcal_mol"]:.2f} | {str(r["mutation_str"])[:50]}')

# ── Strategy D ──
print('\n' + '─'*70)
print('【策略D】ddG<3.0 且非当前6条，按ML brightness排序')
print('─'*70)
d_s = scored[scored['source']=='strategy_D'].copy()
d_all = pd.read_csv(os.path.join(RESULTS, "strategy_D_all_candidates.csv"))
if 'consensus_score' in d_all.columns:
    cs_map = d_all.set_index('seq_id')['consensus_score']
    d_s['consensus_score'] = d_s['seq_id'].map(cs_map)
d_ok = d_s[(d_s['ddG_kcal_mol'].fillna(999)<3.0) & (~d_s['seq_id'].isin(existing_ids))]
d_ok = d_ok.sort_values('composite_score', ascending=False)
print(f'候选: {len(d_ok)}条 | ML range:[{d_ok["composite_score"].min():.3f},{d_ok["composite_score"].max():.3f}]')
if 'consensus_score' in d_ok.columns:
    has = d_ok['consensus_score'].notna()
    if has.any():
        print(f'consensus range:[{d_ok.loc[has,"consensus_score"].min():.3f},{d_ok.loc[has,"consensus_score"].max():.3f}]')
ddg_ok = d_ok['ddG_kcal_mol'].notna()
if ddg_ok.any():
    print(f'ddG range:[{d_ok.loc[ddg_ok,"ddG_kcal_mol"].min():.2f},{d_ok.loc[ddg_ok,"ddG_kcal_mol"].max():.2f}]')

print('\nTop 15 by ML brightness:')
for i,(_,r) in enumerate(d_ok.head(15).iterrows()):
    cs = r.get('consensus_score', None)
    cs_s = f'cons={cs:.3f}' if pd.notna(cs) else ''
    print(f'  {i+1:2d}. {r["seq_id"]}: ML={r["composite_score"]:.3f} ddG={r["ddG_kcal_mol"]:.2f} {cs_s} | {str(r["mutation_str"])[:50]}')

# Best combined: ML * consensus / ddG
if 'consensus_score' in d_ok.columns:
    d_ok = d_ok.copy()
    d_ok['combined'] = d_ok['composite_score'] * d_ok['consensus_score'].fillna(0.3) / np.maximum(d_ok['ddG_kcal_mol'].fillna(1.0), 0.5)
    d_comb = d_ok.sort_values('combined', ascending=False)
    print('\nTop 15 by ML×consensus/ddG combined:')
    for i,(_,r) in enumerate(d_comb.head(15).iterrows()):
        print(f'  {i+1:2d}. {r["seq_id"]}: combined={r["combined"]:.3f} ML={r["composite_score"]:.3f} cons={r["consensus_score"]:.3f} ddG={r["ddG_kcal_mol"]:.2f} | {str(r["mutation_str"])[:50]}')

# ── Strategy C ──
print('\n' + '─'*70)
print('【策略C】ProteinMPNN mpnn_score排序 (ML模型不适用)')
print('─'*70)
c_new = c_pool[~c_pool['seq_id'].isin(existing_ids)]
c_new = c_new.sort_values('mpnn_score', ascending=False)
print(f'候选: {len(c_new)}条 | mpnn range:[{c_new["mpnn_score"].min():.3f},{c_new["mpnn_score"].max():.3f}] | muts range:[{c_new["num_mutations"].min()},{c_new["num_mutations"].max()}]')
print('\nTop 15 by mpnn_score:')
for i,(_,r) in enumerate(c_new.head(15).iterrows()):
    l2w = r.get('level2_warning', False)
    l2_tag = ' [L2!]' if l2w and str(l2w)!='False' and str(l2w)!='False' else ''
    print(f'  {i+1:2d}. {r["seq_id"]}: mpnn={r["mpnn_score"]:.3f} muts={r["num_mutations"]} T={r["temperature"]}{l2_tag} | {str(r["mutation_str"])[:60]}')

# ── CROSS-STRATEGY RECOMMENDATIONS ──
print('\n' + '='*70)
print('【推荐】B视角最佳候选 vs 当前6条')
print('='*70)
print('\n当前6条:')
for _,r in existing.iterrows():
    print(f'  [{r["source_strategy"]}] {r["seq_id"]}: {str(r["mutation_str"])[:50]} | brightness={r.get("composite_score","?")} ddG={r.get("ddG_kcal_mol","?")}')

print('\n策略B推荐备选 (按策略内排名):')
print('  A-ML最高:', a_ok.head(3)[['seq_id','mutation_str','composite_score','ddG_kcal_mol']].to_string(index=False))
print('  A-ML/ddG最佳:', a_bal.head(3)[['seq_id','mutation_str','ml_ddg_product','composite_score','ddG_kcal_mol']].to_string(index=False))
print('  D-ML最高:', d_ok.head(3)[['seq_id','mutation_str','composite_score','ddG_kcal_mol']].to_string(index=False))
if 'combined' in locals():
    print('  D-综合最佳:', d_comb.head(3)[['seq_id','mutation_str','combined','composite_score','ddG_kcal_mol']].to_string(index=False))
print('  C-mpnn最高:', c_new.head(3)[['seq_id','mpnn_score','num_mutations']].to_string(index=False))

print('\nDone.')
