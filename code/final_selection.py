# -*- coding: utf-8 -*-
"""最终6条序列选择 — 分层筛选版 (Plan v3)

每策略独立分层筛选，不跨策略Pareto，不自编综合公式。
排除列表仅用官方 Exclusion_List.csv。
"""
import os, sys, io, re
import numpy as np
import pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

RESULTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
SFGFP_WT = ("MSKGEELFTGVVPILVELDGDVNGHKFSVRGEGEGDATNGKLTLKFICTTGKLPVPWPTLVTTLTY"
            "GVQCFSRYPDHMKRHDFFKSAMPEGYVQERTISFKDDGTYKTRAEVKFEGDTLVNRIELKGIDFKE"
            "DGNILGHKLEYNFNSHNVYITADKQKNGIKANFKIRHNVEDGSVQLADHYQQNTPIGDGPVLLPDN"
            "HYLSTQSVLSKDPNEKRDHMVLLEFVTAAGITHGMDELYK")
LEVEL2_POS = {69, 94, 148, 203, 205}

def parse_mutations(s):
    muts = {}
    if isinstance(s, str) and s.strip().upper() != 'WT':
        for p in str(s).split(':'):
            m = re.match(r'([A-Z])(\d+)([A-Z])', p.strip())
            if m: muts[int(m.group(2))] = (m.group(1), m.group(3))
    return muts

def seq_identity(s1, s2):
    return sum(a==b for a,b in zip(s1,s2)) / max(len(s1),len(s2))

def count_l2_muts(seq):
    return sum(1 for pos in LEVEL2_POS if (pos-1)<len(seq) and seq[pos-1]!=SFGFP_WT[pos-1])

def mut_sites(mut_str):
    return set(parse_mutations(str(mut_str)).keys())

def fmt_row(seq_id, mut_str, n_mut, ml, ddg, cons=None, mpnn=None, l2=0):
    """Format one row for display."""
    parts = ['%-12s' % seq_id,
             '%-28s' % (str(mut_str)[:28]),
             '%3d' % n_mut,
             '%8.3f' % ml if pd.notna(ml) else '     N/A',
             '%8.2f' % ddg if pd.notna(ddg) else '     N/A']
    if cons is not None: parts.append('%7.3f' % cons if pd.notna(cons) else '    N/A')
    if mpnn is not None: parts.append('%7.3f' % mpnn if pd.notna(mpnn) else '    N/A')
    parts.append('%3d' % l2)
    return ' '.join(parts)

# ═══════════════════════════════════════════════════════════════
print('='*70)
print('最终6条序列选择 — 分层筛选 (Plan v3)')
print('='*70)

# ── Load data ──
scored = pd.read_csv(os.path.join(RESULTS, 'strategy_B', 'candidate_scores.csv'))
ddg_map = pd.read_csv(os.path.join(RESULTS, 'strategy_D_ddg_map.csv'))
mut2ddg = dict(zip(ddg_map['mutation_str'], ddg_map['ddG_kcal_mol']))

a_pool = pd.read_csv(os.path.join(RESULTS, 'strategy_A_candidates.csv'))
d_pool = pd.read_csv(os.path.join(RESULTS, 'strategy_D_all_candidates.csv'))
c_pool = pd.read_csv(os.path.join(RESULTS, 'strategy_C', 'strategy_C_candidates.csv'))
if 'seq_id' not in c_pool.columns:
    c_pool['seq_id'] = ['SC_C_%04d' % i for i in range(len(c_pool))]

# Build sequence lookup
all_seq = {}
for _, r in pd.concat([a_pool, d_pool, c_pool]).iterrows():
    all_seq[r['seq_id']] = r['sequence']

# Exclusion list
excl = pd.read_csv(os.path.join(RESULTS, '..', 'competition', 'Exclusion_List.csv'), header=None, names=['Sequence'])
excl_set = set(excl['Sequence'].str.strip().str.upper())
print('Exclusion_List: %d sequences' % len(excl_set))

# ── Prepare data pools ──
# Strategy A
a_s = scored[scored['source']=='strategy_A'].copy()
a_s = a_s[a_s['ddG_kcal_mol'].notna() & (a_s['ddG_kcal_mol']<3.0)].copy()
a_s['l2_count'] = a_s['seq_id'].apply(lambda sid: count_l2_muts(all_seq.get(sid, '')))
# Exclude only official Exclusion_List
a_excl = a_s['sequence'].apply(lambda s: str(s).strip().upper() in excl_set)
a_s = a_s[~a_excl].copy()
print('A池: %d条 (ddG<3.0, 官方排除后)' % len(a_s))

# Strategy D
d_s = scored[scored['source']=='strategy_D'].copy()
d_s['ddG_kcal_mol'] = d_s['mutation_str'].map(mut2ddg)
d_s = d_s[d_s['ddG_kcal_mol'].notna() & (d_s['ddG_kcal_mol']<3.0)].copy()
d_excl = d_s['sequence'].apply(lambda s: str(s).strip().upper() in excl_set)
d_s = d_s[~d_excl].copy()
print('D池: %d条 (ddG<3.0, 官方排除后)' % len(d_s))

# Strategy C — filter WT (0 mutations)
c_designs = c_pool[c_pool['num_mutations'] > 0].copy()
c_designs['l2_count'] = c_designs['sequence'].apply(count_l2_muts)
c_excl = c_designs['sequence'].apply(lambda s: str(s).strip().upper() in excl_set)
c_s = c_designs[~c_excl].copy()
print('C池: %d条设计 (排除WT, 官方排除后)' % len(c_s))

# ═══════════════════════════════════════════════════════════════
# STRATEGY A: 分层筛选
# ═══════════════════════════════════════════════════════════════
print('\n' + '='*70)
print('策略A — 分层筛选')
print('='*70)
selected = []

# --- A1: ML亮度最高 ---
print('\n[A1] ML亮度最高 (策略B直接贡献)')
a1_candidates = a_s.sort_values('composite_score', ascending=False)
r = a1_candidates.iloc[0]
print('  筛选: ddG<3.0')
print('  排序: composite_score 降序')
print('  选出: %s | ML=%.3f | ddG=%.2f | %s' % (r['seq_id'], r['composite_score'], r['ddG_kcal_mol'], r['mutation_str']))

# Show comparison with runner-up
print('  Top 3对比:')
for i, (_, rr) in enumerate(a1_candidates.head(3).iterrows()):
    flag = ' <--' if i == 0 else ''
    print('    %d. %s ML=%.3f ddG=%.2f %s%s' % (i+1, rr['seq_id'], rr['composite_score'], rr['ddG_kcal_mol'], rr['mutation_str'], flag))

selected.append({
    'slot': 1, 'strategy': 'A', 'seq_id': r['seq_id'],
    'criterion': 'ML亮度最高 — 策略B集成模型直接选出',
    'ml': r['composite_score'], 'ddg': r['ddG_kcal_mol'],
    'extra': 'A池ML排名#1/%d' % len(a1_candidates)})
used_sites = mut_sites(r['mutation_str'])
used_ids = {r['seq_id']}

# --- A2: 最低ddG (ML>3.0 + L2=0 + <=2突变) ---
print('\n[A2] 最低ddG (ML>3.0 + 零L2突变 + <=2总突变)')
a2_pool = a_s[(a_s['composite_score']>3.0) &
              (a_s['l2_count']==0) &
              (a_s['num_mutations']<=2) &
              (~a_s['seq_id'].isin(used_ids))]
print('  第1层(ddG<3.0):        %d条' % len(a_s))
print('  第2层(ML>3.0):          %d条' % len(a_s[a_s['composite_score']>3.0]))
print('  第3层(L2=0):            %d条' % len(a_s[(a_s['composite_score']>3.0)&(a_s['l2_count']==0)]))
print('  第4层(<=2突变):         %d条' % len(a2_pool))
a2_candidates = a2_pool.sort_values('ddG_kcal_mol')
r = a2_candidates.iloc[0]
print('  排序: ddG_kcal_mol 升序')
print('  选出: %s | ddG=%.2f | ML=%.3f | L2=%d | %s' % (r['seq_id'], r['ddG_kcal_mol'], r['composite_score'], r['l2_count'], r['mutation_str']))
print('  Top 3对比:')
for i, (_, rr) in enumerate(a2_candidates.head(3).iterrows()):
    flag = ' <--' if i == 0 else ''
    print('    %d. %s ddG=%.2f ML=%.3f L2=%d %s%s' % (i+1, rr['seq_id'], rr['ddG_kcal_mol'], rr['composite_score'], rr['l2_count'], rr['mutation_str'], flag))

selected.append({
    'slot': 2, 'strategy': 'A', 'seq_id': r['seq_id'],
    'criterion': '最低ddG — ML>3.0+零L2+<=2突变约束下FoldX最稳定',
    'ml': r['composite_score'], 'ddg': r['ddG_kcal_mol'],
    'extra': 'ddG=%.2f, L2=%d' % (r['ddG_kcal_mol'], r['l2_count'])})
used_sites.update(mut_sites(r['mutation_str']))
used_ids.add(r['seq_id'])

# --- A3: 位点多样性 (ML>3.5 + <=2突变 + 位点不重叠) ---
print('\n[A3] 位点多样性 (ML>3.5 + <=2突变 + 位点不与A1/A2重叠)')
a3_pool = a_s[(a_s['composite_score']>3.5) &
              (a_s['num_mutations']<=2) &
              (~a_s['seq_id'].isin(used_ids))]
# Filter by site overlap
a3_pool = a3_pool[a3_pool['mutation_str'].apply(
    lambda x: len(mut_sites(x) & used_sites) == 0)]
print('  第1层(ddG<3.0+ML>3.5):  %d条' % len(a_s[(a_s['composite_score']>3.5)]))
print('  第2层(<=2突变):          %d条' % len(a_s[(a_s['composite_score']>3.5)&(a_s['num_mutations']<=2)]))
print('  第3层(位点不重叠):       %d条' % len(a3_pool))
print('  已用位点: %s' % sorted(used_sites))
a3_candidates = a3_pool.sort_values('composite_score', ascending=False)
r = a3_candidates.iloc[0]
r_sites = mut_sites(r['mutation_str'])
print('  排序: composite_score 降序')
print('  选出: %s | ML=%.3f | ddG=%.2f | 位点=%s | %s' % (r['seq_id'], r['composite_score'], r['ddG_kcal_mol'], sorted(r_sites), r['mutation_str']))
print('  Top 3对比:')
for i, (_, rr) in enumerate(a3_candidates.head(3).iterrows()):
    flag = ' <--' if i == 0 else ''
    sites = sorted(mut_sites(rr['mutation_str']))
    print('    %d. %s ML=%.3f ddG=%.2f 位点=%s %s%s' % (i+1, rr['seq_id'], rr['composite_score'], rr['ddG_kcal_mol'], sites, rr['mutation_str'], flag))

selected.append({
    'slot': 3, 'strategy': 'A', 'seq_id': r['seq_id'],
    'criterion': '位点多样性 — ML>3.5+新位点,与A1/A2完全不重叠',
    'ml': r['composite_score'], 'ddg': r['ddG_kcal_mol'],
    'extra': '新位点=%s' % sorted(r_sites)})
used_sites.update(mut_sites(r['mutation_str']))
used_ids.add(r['seq_id'])

# ═══════════════════════════════════════════════════════════════
# STRATEGY D: 分层筛选 (consensus为主)
# ═══════════════════════════════════════════════════════════════
print('\n' + '='*70)
print('策略D — 分层筛选 (进化共识为主)')
print('='*70)

# --- D1: consensus最高 (ddG<2.0 + consensus>0.3 + ML>1.5) ---
print('\n[D1] 进化共识最强 (ddG<2.0 + consensus>0.3 + ML>1.5)')
d1_pool = d_s[(d_s['ddG_kcal_mol']<2.0) &
              (d_s['consensus_score'].fillna(0)>0.3) &
              (d_s['composite_score']>1.5)]
print('  第1层(ddG<3.0):         %d条' % len(d_s))
print('  第2层(ddG<2.0):         %d条' % len(d_s[d_s['ddG_kcal_mol']<2.0]))
print('  第3层(consensus>0.3):   %d条' % len(d_s[(d_s['ddG_kcal_mol']<2.0)&(d_s['consensus_score'].fillna(0)>0.3)]))
print('  第4层(ML>1.5):          %d条' % len(d1_pool))
d1_candidates = d1_pool.sort_values('consensus_score', ascending=False)
r = d1_candidates.iloc[0]
print('  排序: consensus_score 降序')
print('  选出: %s | cons=%.3f | ddG=%.2f | ML=%.3f | %s' % (r['seq_id'], r['consensus_score'], r['ddG_kcal_mol'], r['composite_score'], r['mutation_str']))
print('  Top 3对比:')
for i, (_, rr) in enumerate(d1_candidates.head(3).iterrows()):
    flag = ' <--' if i == 0 else ''
    cs = rr.get('consensus_score', 0) or 0
    print('    %d. %s cons=%.3f ddG=%.2f ML=%.3f %s%s' % (i+1, rr['seq_id'], cs, rr['ddG_kcal_mol'], rr['composite_score'], rr['mutation_str'], flag))

selected.append({
    'slot': 4, 'strategy': 'D', 'seq_id': r['seq_id'],
    'criterion': '进化共识最强 — ddG<2.0+consensus>0.3+ML>1.5约束下consensus最高',
    'ml': r['composite_score'], 'ddg': r['ddG_kcal_mol'],
    'extra': 'cons=%.3f' % (r.get('consensus_score', 0) or 0)})
d1_sites = mut_sites(r['mutation_str'])
used_sites.update(d1_sites)
used_ids.add(r['seq_id'])

# --- D2: consensus次高 + 位点独立 ---
print('\n[D2] 进化共识次强 + 位点独立 (与D1重叠<=1)')
d2_pool = d1_pool[~d1_pool['seq_id'].isin(used_ids)].copy()
d2_pool = d2_pool[d2_pool['mutation_str'].apply(
    lambda x: len(mut_sites(x) & d1_sites) <= 1)]
print('  额外约束(与D1位点重叠<=1): %d条' % len(d2_pool))
print('  D1位点: %s' % sorted(d1_sites))
d2_candidates = d2_pool.sort_values('consensus_score', ascending=False)
r = d2_candidates.iloc[0]
r_sites = mut_sites(r['mutation_str'])
overlap = r_sites & d1_sites
print('  排序: consensus_score 降序')
print('  选出: %s | cons=%.3f | ddG=%.2f | ML=%.3f | 位点=%s(重叠=%s) | %s' % (r['seq_id'], r.get('consensus_score',0) or 0, r['ddG_kcal_mol'], r['composite_score'], sorted(r_sites), sorted(overlap), r['mutation_str']))
print('  Top 3对比:')
for i, (_, rr) in enumerate(d2_candidates.head(3).iterrows()):
    flag = ' <--' if i == 0 else ''
    cs = rr.get('consensus_score', 0) or 0
    sites_set = mut_sites(rr['mutation_str'])
    sites_sorted = sorted(sites_set)
    ov = sorted(sites_set & d1_sites)
    print('    %d. %s cons=%.3f ddG=%.2f 位点=%s(重叠=%s) %s%s' % (i+1, rr['seq_id'], cs, rr['ddG_kcal_mol'], sites_sorted, ov, rr['mutation_str'], flag))

selected.append({
    'slot': 5, 'strategy': 'D', 'seq_id': r['seq_id'],
    'criterion': '进化共识次强 — 与D1位点独立, consensus排序#2',
    'ml': r['composite_score'], 'ddg': r['ddG_kcal_mol'],
    'extra': 'cons=%.3f, 重叠=%s' % ((r.get('consensus_score',0) or 0), sorted(overlap))})
used_ids.add(r['seq_id'])

# ═══════════════════════════════════════════════════════════════
# STRATEGY C: L2安全 + mpnn最高
# ═══════════════════════════════════════════════════════════════
print('\n' + '='*70)
print('策略C — L2安全 + mpnn最高')
print('='*70)

print('\n[C1] L2安全(<=2) + mpnn最高')
c1_pool = c_s[c_s['l2_count'] <= 2].copy()
print('  第1层(排除WT):          %d条' % len(c_designs))
print('  第2层(官方排除后):      %d条' % len(c_s))
print('  第3层(L2<=2):           %d条' % len(c1_pool))
c1_candidates = c1_pool.sort_values('mpnn_score', ascending=False)
r = c1_candidates.iloc[0]
print('  排序: mpnn_score 降序')
print('  选出: %s | mpnn=%.3f | muts=%d | L2=%d | %s' % (r['seq_id'], r['mpnn_score'], r['num_mutations'], r['l2_count'], str(r['mutation_str'])[:60]+'...'))
print('  Top 3对比:')
for i, (_, rr) in enumerate(c1_candidates.head(3).iterrows()):
    flag = ' <--' if i == 0 else ''
    ms = str(rr['mutation_str'])
    print('    %d. %s mpnn=%.3f muts=%d L2=%d %s%s' % (i+1, rr['seq_id'], rr['mpnn_score'], rr['num_mutations'], rr['l2_count'], ms[:40]+'...', flag))

selected.append({
    'slot': 6, 'strategy': 'C', 'seq_id': r['seq_id'],
    'criterion': 'L2安全+mpnn最高 — 发色团微环境保守, AI设计代表',
    'ml': None, 'ddg': None,
    'extra': 'mpnn=%.3f, L2=%d/5, muts=%d' % (r['mpnn_score'], r['l2_count'], r['num_mutations'])})

# ═══════════════════════════════════════════════════════════════
# FINAL OUTPUT
# ═══════════════════════════════════════════════════════════════
print('\n' + '='*70)
print('最终6条序列')
print('='*70)

# Build final dataframe
final_rows = []
for s in selected:
    sid = s['seq_id']
    seq = all_seq.get(sid, '')
    strategy = s['strategy']
    if strategy == 'A':
        detail = a_pool[a_pool['seq_id']==sid]
    elif strategy == 'D':
        detail = d_pool[d_pool['seq_id']==sid]
    else:
        detail = c_pool[c_pool['seq_id']==sid]

    mut_str = detail['mutation_str'].iloc[0] if len(detail)>0 else '?'
    n_mut = int(detail['num_mutations'].iloc[0]) if len(detail)>0 else 0

    # Get consensus if D
    cons_val = None
    if strategy == 'D':
        d_row = d_s[d_s['seq_id']==sid]
        if len(d_row) > 0:
            cons_val = d_row.iloc[0].get('consensus_score', None)

    # Get mpnn if C
    mpnn_val = None
    if strategy == 'C':
        c_row = c_pool[c_pool['seq_id']==sid]
        if len(c_row) > 0:
            mpnn_val = c_row.iloc[0].get('mpnn_score', None)

    final_rows.append({
        'seq_id': sid,
        'sequence': seq,
        'source_strategy': strategy,
        'num_mutations': n_mut,
        'mutation_str': mut_str,
        'ddG_kcal_mol': s['ddg'],
        'mpnn_score': mpnn_val,
        'consensus_score': cons_val,
        'composite_score': s['ml'],
        'selection_reason': s['criterion'],
        'selection_extra': s['extra'],
    })

final_df = pd.DataFrame(final_rows)

print('\n%-3s %-12s %-4s %-28s %8s %8s %s' % ('#','Seq_ID','策略','突变','ML亮度','ddG','选择理由'))
print('-'*100)
for i, (_, r) in enumerate(final_df.iterrows()):
    ml_s = '%.3f' % r['composite_score'] if pd.notna(r['composite_score']) else 'N/A'
    ddg_s = '%.2f' % r['ddG_kcal_mol'] if pd.notna(r['ddG_kcal_mol']) else 'N/A'
    print('%-3d %-12s %-4s %-28s %8s %8s %s' % (
        i+1, r['seq_id'], r['source_strategy'],
        str(r['mutation_str'])[:28], ml_s, ddg_s, r['selection_reason']))
    print('     %s' % r['selection_extra'])

# Cross-strategy summary
print('\n策略覆盖: %s' % set(final_df['source_strategy']))
all_sites_set = set()
for _, r in final_df.iterrows():
    all_sites_set.update(mut_sites(str(r['mutation_str'])))
print('突变位点: %s (%d个)' % (sorted(all_sites_set), len(all_sites_set)))

seqs = final_df['sequence'].tolist()
print('成对相似度:')
for i in range(len(seqs)):
    for j in range(i+1, len(seqs)):
        ident = seq_identity(seqs[i], seqs[j])
        flag = ' (>95%)' if ident > 0.95 else ''
        print('  Seq%d vs Seq%d: %.1f%%%s' % (i+1, j+1, ident*100, flag))

# Save
final_df.to_csv(os.path.join(RESULTS, 'funnel_phase5_final_6.csv'), index=False)
print('\nSaved: results/funnel_phase5_final_6.csv')

TEAM = 'Sean-protein'
sub = pd.DataFrame({
    'Team_Name': [TEAM]*len(final_df),
    'Seq_ID': ['Seq%d' % (i+1) for i in range(len(final_df))],
    'Sequence': final_df['sequence'].tolist(),
})
sub.to_csv(os.path.join(RESULTS, 'submission_6_sequences.csv'), index=False)
print('Saved: results/submission_6_sequences.csv')
print('\nDone.')
