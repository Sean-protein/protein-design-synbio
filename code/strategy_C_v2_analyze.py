# -*- coding: utf-8 -*-
"""分析策略C v2 结果"""
import pandas as pd
import os

def find_csv():
    for p in [
        "/data2/fenghaohui/results/strategy_C/v2/strategy_C_v2_candidates.csv",
        "results/strategy_C/v2/strategy_C_v2_candidates.csv",
    ]:
        if os.path.exists(p): return p
    raise FileNotFoundError("v2 candidates not found")

df = pd.read_csv(find_csv())

print("=" * 60)
print("STRATEGY C v2 — Results Analysis")
print("=" * 60)

# 1. 过滤统计
print("\n[1] Filter statistics:")
print("    passed_filter: {}".format(dict(df.passed_filter.value_counts())))

# 2. 每温度突变分布
print("\n[2] Mutations per temperature:")
for t in sorted(df.temperature.unique()):
    sub = df[df.temperature == t]
    print("    T={}: n={} mean={:.0f} median={:.0f} min={} max={}".format(
        t, len(sub), sub.num_mutations.mean(), sub.num_mutations.median(),
        sub.num_mutations.min(), sub.num_mutations.max()))

# 3. 突变数分布直方图
print("\n[3] Mutation count distribution:")
bins = [(0,10),(10,20),(20,30),(30,40),(40,50),(50,60),(60,70),(70,80),(80,100)]
for lo, hi in bins:
    n = ((df.num_mutations >= lo) & (df.num_mutations < hi)).sum()
    if n > 0:
        bar = "#" * (n // 5)
        print("    {:>2}-{:<3}: {:>3}  {}".format(lo, hi, n, bar))

# 4. 通过的候选
print("\n[4] Passed candidates:")
good = df[df.passed_filter]
if len(good):
    for _, r in good.iterrows():
        print("    muts={} mpnn={:.3f} T={} L2_mutated={}".format(
            int(r.num_mutations), r.mpnn_score, r.temperature, r.level2_mutated))
else:
    print("    NONE passed all filters")

# 5. Top 10 突变最少
print("\n[5] Top 10 fewest mutations:")
top = df.nsmallest(10, "num_mutations")
for _, r in top.iterrows():
    print("    muts={} mpnn={:.3f} T={} pass={} L2={}".format(
        int(r.num_mutations), r.mpnn_score, r.temperature, r.passed_filter, r.level2_mutated))

# 6. 提取可用的（突变<20 且 mpnn>0.85）
print("\n[6] Usable candidates (muts<=20, mpnn>=0.85):")
usable = df[(df.num_mutations <= 20) & (df.mpnn_score >= 0.85)]
if len(usable):
    for _, r in usable.iterrows():
        print("    muts={} mpnn={:.3f} T={} mut_str={}".format(
            int(r.num_mutations), r.mpnn_score, r.temperature, r.mutation_str[:80]))
else:
    print("    NONE. ProteinMPNN cannot produce low-mutation high-confidence candidates.")
    print("    This is a fundamental limitation: the method is designed for")
    print("    backbone redesign, not conservative optimization.")
    print()
    print("    RECOMMENDATION: Take 1-2 best (lowest muts + highest mpnn_score)")
    print("    as 'exploratory diversity' contributions. Do not attempt FoldX.")

# 7. 最佳候选（选2条）
print("\n[7] Best 2 candidates for diversity submission:")
best = df[(df.num_mutations <= 15)].nsmallest(2, "num_mutations")
if len(best) < 2:
    best = df.nsmallest(2, "num_mutations")
for i, (_, r) in enumerate(best.iterrows()):
    print("    C_v2_{}: muts={} mpnn={:.3f} T={} L2={}".format(
        i+1, int(r.num_mutations), r.mpnn_score, r.temperature, r.level2_mutated))

print("\n" + "=" * 60)
