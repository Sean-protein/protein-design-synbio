#!/usr/bin/env python3
"""Pipeline diagram v8: labels inside boxes, pool from right, thin arrows, 40% larger fonts."""
import os, xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as _e

L = []
W, H = 1100, 1260
L.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d">' % (W, H))
L.append('<defs>')
L.append('<marker id="a" markerWidth="8" markerHeight="5" refX="7" refY="2.5" orient="auto"><polygon points="0 0,8 2.5,0 5" fill="#777"/></marker>')
L.append('<marker id="aR" markerWidth="8" markerHeight="5" refX="7" refY="2.5" orient="auto"><polygon points="0 0,8 2.5,0 5" fill="#C0392B"/></marker>')
L.append('</defs>')
L.append('<rect width="%d" height="%d" fill="#fff"/>' % (W, H))
L.append('<text x="%d" y="34" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="20" font-weight="bold" fill="#1a1a1a">GFP Protein Design Pipeline  Four-Strategy Generation + Layered Funnel Selection</text>' % (W//2))

def gbox(x, y, w, h, fill, stroke, title, body, fs_t=11, fs_b=10, fc_t="#333", fc_b="#555"):
    """Green input boxes with bold title inside, top-left."""
    L.append('<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="%s" stroke="%s" stroke-width="0.6"/>' % (x, y, w, h, fill, stroke))
    L.append('<text x="%d" y="%d" font-family="Arial,Helvetica,sans-serif" font-size="%d" font-weight="bold" fill="%s">%s</text>' % (x+10, y+20, fs_t, fc_t, _e(title)))
    L.append('<text x="%d" y="%d" font-family="Arial,Helvetica,sans-serif" font-size="%d" fill="%s">%s</text>' % (x+10, y+40, fs_b, fc_b, _e(body)))

def bbox(x, y, w, h, fill, stroke, lines, fs=10.5, fc="#333"):
    """Blue/gray boxes with centered text."""
    L.append('<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="%s" stroke="%s" stroke-width="0.6"/>' % (x, y, w, h, fill, stroke))
    for j, t in enumerate(lines):
        fw = "font-weight=\"600\"" if j == 0 and len(lines) > 1 else ""
        L.append('<text x="%d" y="%d" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="%d" fill="%s" %s>%s</text>' % (x+w//2, y + 20 + j*16, fs, fc, fw, _e(t)))

def ha(x1, y, x2, sw=0.75):
    L.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#888" stroke-width="%.2f" marker-end="url(#a)"/>' % (x1, y, x2, y, sw))

def va(x, y1, y2, sw=0.75):
    L.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#888" stroke-width="%.2f" marker-end="url(#a)"/>' % (x, y1, x, y2, sw))

# ═══════════════════ STEP 1 ═══════════════════
s1_y = 52
L.append('<rect x="70" y="%d" width="960" height="26" rx="3" fill="#F0F0F0" stroke="#ddd" stroke-width="0.5"/>' % s1_y)
L.append('<text x="%d" y="%d" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="14" font-weight="bold" fill="#555">Step 1: Four-Strategy Parallel Generation</text>' % (W//2, s1_y+17))

# 3-column strict alignment
in_x = 180; in_w = 210
algo_x = in_x + in_w + 40; algo_w = 260
out_x = algo_x + algo_w + 40; out_w = 220
bh = 60
row_y = s1_y + 38
row_h = 85

S = [
    ('A: Rational Enumeration', 'sfGFP Structure (PDB 2B3P, 1.45 A)',
     ['45 Positions x 2-3 Mut', 'FoldX ddG < 3.0'],
     ['2,424 Passed (80.0%)']),
    ('B: ML Ensemble Scoring', 'Sarkisyan 2016 avGFP Fitness',
     ['ESM-2 650M + Handcrafted (1,531d)', 'XGB + LGBM + RF Ensemble'],
     ['R2 = 0.712', 'All A+D Candidates Scored'], True),
    ('C: ProteinMPNN Inverse Folding', 'sfGFP Backbone (PDB 2B3P)',
     ['Multi-T Sampling (0.1 / 0.3 / 0.5)', 'mpnn_score ranking'],
     ['271 Designs (1 for Diversity)']),
    ('D: Evolutionary Consensus', 'Swiss-Prot GFP Homologs (135 seqs)',
     ['MAFFT MSA + Shannon Entropy', 'EVcouplings MI+APC | Grafting'],
     ['295 ddG<3.0 Passed (from 436 candidates)']),
]

results_rc = []  # (right_edge_x, center_y) per strategy result box

for i, s in enumerate(S):
    y = row_y + i * row_h
    title, body, algo, out = s[0], s[1], s[2], s[3]

    # Green input box with bold title inside
    gbox(in_x, y, in_w, bh, '#E6F4EA', '#b8d8be', title, body)
    ha(in_x+in_w, y+bh//2, algo_x-6)

    # Blue algo box
    bbox(algo_x, y, algo_w, bh, '#E3F2FD', '#b8cfe0', algo)
    ha(algo_x+algo_w, y+bh//2, out_x-6)

    # Gray result box
    bbox(out_x, y, out_w, bh, '#F5F5F5', '#d0d0d0', out)
    results_rc.append((out_x + out_w, y + bh//2))

# Pool
pool_y = row_y + 4 * row_h + 25
pool_w = 680; pool_h = 68
pool_x = (W - pool_w)//2
L.append('<rect x="%d" y="%d" width="%d" height="%d" rx="5" fill="#F5F5F5" stroke="#bbb" stroke-width="0.8"/>' % (pool_x, pool_y, pool_w, pool_h))
L.append('<text x="%d" y="%d" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="14" font-weight="bold" fill="#333">Unified Candidate Pool -- ~2,800 sequences</text>' % (W//2, pool_y+28))
L.append('<text x="%d" y="%d" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="11" fill="#777">Sources: 2,424 (A) + 295 (D) + 2 (C)</text>' % (W//2, pool_y+52))

# Collect arrows: from RIGHT side of result boxes -> down -> pool RIGHT side
collect_x = out_x + out_w + 50  # to the right of all result boxes
for rx, cy in results_rc:
    # horizontal line right from result box
    L.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#aaa" stroke-width="0.6"/>' % (rx, cy, collect_x, cy))
    # vertical line down
    L.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#aaa" stroke-width="0.6"/>' % (collect_x, cy, collect_x, pool_y+pool_h//2))
# Merge into pool right side
L.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#888" stroke-width="0.8" marker-end="url(#a)"/>' % (collect_x, pool_y+pool_h//2, pool_x+pool_w, pool_y+pool_h//2))

# Main line: pool bottom center → Step 2
pool_cx = W//2
va(pool_cx, pool_y+pool_h, pool_y+pool_h+40, sw=1.0)

# ═══════════════════ STEP 2 ═══════════════════
s2_y = pool_y + pool_h + 45
L.append('<rect x="70" y="%d" width="960" height="26" rx="3" fill="#F0F0F0" stroke="#ddd" stroke-width="0.5"/>' % s2_y)
L.append('<text x="%d" y="%d" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="14" font-weight="bold" fill="#555">Step 2: Funnel Screening &amp; Layered Selection</text>' % (pool_cx, s2_y+17))

pw = 740; ph_h = 64
px = (W - pw)//2
ph_gap = 34

# Phase 1
p1_y = s2_y + 36
L.append('<rect x="%d" y="%d" width="%d" height="%d" rx="4" fill="#E3F2FD" stroke="#b8cfe0" stroke-width="0.7"/>' % (px, p1_y, pw, ph_h))
L.append('<text x="%d" y="%d" font-family="Arial,Helvetica,sans-serif" font-size="11" font-weight="600" fill="#333">Phase 1: Compliance Filter</text>' % (px+14, p1_y+21))
L.append('<text x="%d" y="%d" font-family="Arial,Helvetica,sans-serif" font-size="10" fill="#666">L1 Fixed Sites (6) | 220-250 aa | Exclusion_List (135,415) | Exact Dedup</text>' % (px+14, p1_y+46))
# Badge
L.append('<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="#E6F4EA" stroke="#b8d8be" stroke-width="0.6"/>' % (px+pw-140, p1_y+14, 128, 38))
L.append('<text x="%d" y="%d" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="11" font-weight="600" fill="#2d6a4f">~2,500 passed</text>' % (px+pw-76, p1_y+40))
va(pool_cx, p1_y+ph_h, p1_y+ph_h+ph_gap-4, sw=0.75)

# Phase 2
p2_y = p1_y + ph_h + ph_gap
L.append('<rect x="%d" y="%d" width="%d" height="%d" rx="4" fill="#E3F2FD" stroke="#b8cfe0" stroke-width="0.7"/>' % (px, p2_y, pw, ph_h))
L.append('<text x="%d" y="%d" font-family="Arial,Helvetica,sans-serif" font-size="11" font-weight="600" fill="#333">Phase 2: ML Brightness Ranking</text>' % (px+14, p2_y+21))
L.append('<text x="%d" y="%d" font-family="Arial,Helvetica,sans-serif" font-size="10" fill="#666">Ensemble Scoring (R2=0.712) | Strategy Diversity Quota: 53A + 25D + 2C</text>' % (px+14, p2_y+46))
L.append('<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="#E6F4EA" stroke="#b8d8be" stroke-width="0.6"/>' % (px+pw-140, p2_y+14, 128, 38))
L.append('<text x="%d" y="%d" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="11" font-weight="600" fill="#2d6a4f">Top 80</text>' % (px+pw-76, p2_y+40))
va(pool_cx, p2_y+ph_h, p2_y+ph_h+ph_gap-4, sw=0.75)

# R2 dash line removed per request

# Phase 3
p3_y = p2_y + ph_h + ph_gap
p3_h = 140
L.append('<rect x="%d" y="%d" width="%d" height="%d" rx="4" fill="#E3F2FD" stroke="#b8cfe0" stroke-width="0.7"/>' % (px, p3_y, pw, p3_h))
L.append('<text x="%d" y="%d" font-family="Arial,Helvetica,sans-serif" font-size="11" font-weight="600" fill="#333">Phase 3: Layered Selection</text>' % (px+14, p3_y+21))
L.append('<text x="%d" y="%d" font-family="Arial,Helvetica,sans-serif" font-size="10" fill="#666">Per-Strategy Single-Objective Filtering  No Pareto, No Composite Formula</text>' % (px+14, p3_y+44))
L.append('<text x="%d" y="%d" font-family="Arial,Helvetica,sans-serif" font-size="10" fill="#888">Thresholds: ddG&lt;3.0 (A) | ddG&lt;2.0 (D) | ML&gt;3.0 | ML&gt;1.5 | consensus&gt;0.3 | L2&lt;3</text>' % (px+14, p3_y+67))

criteria = ['ML Highest (B)', 'Lowest ddG', 'Site Diversity', 'Top Consensus', '2nd Consensus', 'L2-Safe+mpnn']
cw = 108; total_cw = 6*cw + 5*10
cx0 = px + (pw - total_cw)//2
for j, c in enumerate(criteria):
    cx = cx0 + j*(cw+10)
    L.append('<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="#F5F5F5" stroke="#d0d0d0" stroke-width="0.5"/>' % (cx, p3_y+92, cw, 28))
    L.append('<text x="%d" y="%d" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="9" fill="#555">%s</text>' % (cx+cw//2, p3_y+110, _e(c)))

va(pool_cx, p3_y+p3_h, p3_y+p3_h+30, sw=0.75)

# Final
fy = p3_y + p3_h + 34
fw = 460
L.append('<rect x="%d" y="%d" width="%d" height="%d" rx="5" fill="#E6F4EA" stroke="#a0c8a8" stroke-width="1"/>' % ((W-fw)//2, fy, fw, 54))
L.append('<text x="%d" y="%d" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="15" font-weight="bold" fill="#1a5c2a">Final 6 Sequences (3A + 2D + 1C)</text>' % (pool_cx, fy+35))

# Legend
ly = fy + 85
for x, f, s, label in [(50, '#E6F4EA', '#b8d8be', 'Data Source'),
                         (240, '#E3F2FD', '#b8cfe0', 'Algorithm'),
                         (430, '#F5F5F5', '#d0d0d0', 'Result / Pool'),
                         (620, '#E6F4EA', '#a0c8a8', 'Final Output')]:
    L.append('<rect x="%d" y="%d" width="24" height="15" rx="2" fill="%s" stroke="%s" stroke-width="0.6"/>' % (x, ly, f, s))
    L.append('<text x="%d" y="%d" font-family="Arial,Helvetica,sans-serif" font-size="10" fill="#666">%s</text>' % (x+30, ly+12, _e(label)))
L.append('<line x1="810" y1="%d" x2="855" y2="%d" stroke="#888" stroke-width="0.7"/>' % (ly+7, ly+7))
L.append('<text x="862" y="%d" font-family="Arial,Helvetica,sans-serif" font-size="10" fill="#666">Arrow</text>' % (ly+12))

L.append('</svg>')

svg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', 'final_submission', 'pipeline_diagram.svg')
with open(svg_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(L))
print('SVG: %s (%d bytes)' % (svg_path, os.path.getsize(svg_path)))
ET.parse(svg_path)
print('XML valid')
