# -*- coding: utf-8 -*-
"""阶段一：数据准备 — 探索训练数据
对应文档 1.2 节：第一个脚本——看一眼训练数据长什么样
"""
import pandas as pd
import numpy as np
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")

# ============================================================
# 1. 训练数据概览
# ============================================================
print("=" * 60)
print("1. 训练数据 (GFP data.xlsx)")
print("=" * 60)

xls_path = os.path.join(DATA_DIR, "GFP data.xlsx")
xls = pd.ExcelFile(xls_path)
print(f"Sheet 数量: {len(xls.sheet_names)} → {xls.sheet_names}")

for sheet in xls.sheet_names:
    df = pd.read_excel(xls, sheet)
    print(f"\n--- Sheet: [{sheet}] ---")
    print(f"行数: {len(df):,}  |  列数: {len(df.columns)}")
    print(f"列名: {list(df.columns)}")
    print(f"\n前 5 行:")
    print(df.head().to_string())
    print(f"\n数据类型:")
    print(df.dtypes)

# ============================================================
# 2. 亮度分布
# ============================================================
print("\n" + "=" * 60)
print("2. 亮度分布 (Brightness)")
print("=" * 60)

df_bright = pd.read_excel(xls_path, sheet_name="brightness")

print(f"描述统计:")
print(df_bright["Brightness"].describe())
print(f"\n亮度分布 (分箱):")
bins = [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
labels = ["0-0.5", "0.5-1", "1-1.5", "1.5-2", "2-2.5", "2.5-3", "3-3.5", "3.5-4"]
df_bright["bin"] = pd.cut(df_bright["Brightness"], bins=bins, labels=labels)
print(df_bright["bin"].value_counts().sort_index())

# ============================================================
# 3. GFP 类型分布
# ============================================================
print("\n" + "=" * 60)
print("3. GFP 类型分布")
print("=" * 60)

type_counts = df_bright["GFP type"].value_counts()
for t, c in type_counts.items():
    sub = df_bright[df_bright["GFP type"] == t]
    print(f"  {t}: {c} 条,  亮度 {sub['Brightness'].min():.2f} - {sub['Brightness'].max():.2f} (均值 {sub['Brightness'].mean():.2f})")

# ============================================================
# 4. 突变分析
# ============================================================
print("\n" + "=" * 60)
print("4. 突变模式分析")
print("=" * 60)

# 统计每条序列的突变数量
def count_mutations(mut_str):
    if not isinstance(mut_str, str) or mut_str.strip().upper() == "WT":
        return 0
    return len(mut_str.split(":"))

df_bright["n_mutations"] = df_bright["aaMutations"].apply(count_mutations)
print(f"突变数量分布:")
print(df_bright["n_mutations"].value_counts().sort_index().head(10))

# 最高/最低亮度的突变体
print(f"\n--- 亮度 TOP 5 突变体 ---")
top5 = df_bright.nlargest(5, "Brightness")[
    ["GFP type", "aaMutations", "Brightness"]
]
print(top5.to_string(index=False))

print(f"\n--- 亮度 BOTTOM 5 突变体 ---")
bottom5 = df_bright.nsmallest(5, "Brightness")[
    ["GFP type", "aaMutations", "Brightness"]
]
print(bottom5.to_string(index=False))

# ============================================================
# 5. 野生型序列
# ============================================================
print("\n" + "=" * 60)
print("5. 野生型序列")
print("=" * 60)

wt_path = os.path.join(DATA_DIR, "WildType AAseqs of 4 GFP proteins.txt")
wt_seqs = {}
with open(wt_path) as f:
    current_name = ""
    current_seq = []
    for line in f:
        line = line.strip()
        if line.startswith(">"):
            if current_name and current_seq:
                wt_seqs[current_name] = "".join(current_seq)
            current_name = line[1:].strip()
            current_seq = []
        elif line:
            current_seq.append(line)
    if current_name and current_seq:
        wt_seqs[current_name] = "".join(current_seq)

for name, seq in wt_seqs.items():
    print(f"  {name}: {len(seq)} aa")
    print(f"    前 30: {seq[:30]}...")
    print(f"    末 10: ...{seq[-10:]}")

# ============================================================
# 6. 排除列表
# ============================================================
print("\n" + "=" * 60)
print("6. 排除列表 (Exclusion_List.csv)")
print("=" * 60)

excl_path = os.path.join(DATA_DIR, "Exclusion_List.csv")
excl_df = pd.read_csv(excl_path)
print(f"排除序列数: {len(excl_df)}")
print(f"列名: {list(excl_df.columns)}")
print(f"前 5 条:")
print(excl_df.head().to_string())

# ============================================================
# 7. 额外数据
# ============================================================
print("\n" + "=" * 60)
print("7. 额外可用数据")
print("=" * 60)

# Sarkisyan 2016 数据
tsv_path = os.path.join(DATA_DIR, "nature2016_gfp_fitness.tsv")
if os.path.exists(tsv_path):
    try:
        sark_df = pd.read_csv(tsv_path, sep="\t")
        print(f"  Sarkisyan 2016 (nature2016): {len(sark_df):,} 条")
        print(f"  列名: {list(sark_df.columns)[:10]}...")
    except Exception as e:
        print(f"  无法读取: {e}")

# 综合数据集
comp_path = os.path.join(DATA_DIR, "comprehensive_GFP_dataset.xlsx")
if os.path.exists(comp_path):
    try:
        comp_xls = pd.ExcelFile(comp_path)
        print(f"  comprehensive_GFP_dataset.xlsx sheets: {comp_xls.sheet_names}")
        for s in comp_xls.sheet_names:
            cdf = pd.read_excel(comp_xls, s)
            print(f"    [{s}]: {len(cdf)} rows, {len(cdf.columns)} cols")
    except Exception as e:
        print(f"  无法读取: {e}")

# GFP_training_data.csv
csv_path = os.path.join(DATA_DIR, "GFP_training_data.csv")
if os.path.exists(csv_path):
    try:
        csv_df = pd.read_csv(csv_path)
        print(f"  GFP_training_data.csv: {len(csv_df)} 条")
        print(f"  列名: {list(csv_df.columns)}")
    except Exception as e:
        print(f"  无法读取: {e}")

# 禁止突变位点
ban_path = os.path.join(DATA_DIR, "sfGFP_禁止突变位点.csv")
if os.path.exists(ban_path):
    ban_df = pd.read_csv(ban_path)
    print(f"  sfGFP_禁止突变位点.csv: {len(ban_df)} 条规则")

print("\n" + "=" * 60)
print("阶段一数据探索完成！")
print("=" * 60)
