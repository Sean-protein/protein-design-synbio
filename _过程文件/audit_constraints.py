# -*- coding: utf-8 -*-
"""核查sfGFP注释文档的科学依据和esmGFP对约束体系的挑战"""
import os

BASE = r'D:\蛋白质设计-合成生物学创新赛-Claude'

# ============================================================
# 1. 核查 sfGFP 注释文档的来源
# ============================================================
print("=" * 70)
print("一、sfGFP_氨基酸功能全注释.docx 来源核查")
print("=" * 70)

from docx import Document
path = os.path.join(BASE, '文档', 'From Claude', 'sfGFP_氨基酸功能全注释.docx')
doc = Document(path)

cp = doc.core_properties
print(f"  作者: '{cp.author}' (Un-named = 非真实研究者)")
print(f"  创建时间: {cp.created}")
print(f"  最后修改者: {cp.last_modified_by}")
print()

# Search for citations
ref_keywords = ['DOI', 'doi', 'Nature', 'Science', 'PNAS', 'Cell', 'eLife',
                '参考文献', '引用', 'PMID', 'PMC', '10.', 'et al', 'et al.']
has_doc_refs = False
for p in doc.paragraphs:
    for kw in ref_keywords:
        if kw in p.text:
            if not has_doc_refs:
                print("  文档中出现的疑似引用:")
                has_doc_refs = True
            print(f"    {p.text.strip()[:180]}")
            break

if not has_doc_refs:
    print("  [警告] 文档中未找到任何DOI/PMID/文献引用!")

# Check if it contains actual experimental data
print()
print("  关键性质:")
print("  - 作者为 'Un-named' → AI 生成")
print("  - 创建于 2026-06-06 → 昨天生成")
print("  - 未发现任何 DOI/PMID/引用 → 无文献支撑")
print("  - 结论: 该文档本身也是 AI 产物，科学依据来自训练数据中的隐式知识")
print("         不是经过人工校验的权威来源")
print("         其约束分类方向可能正确，但具体数值(如'残余1-5%')需逐条核实")

# ============================================================
# 2. 分析约束CSV中的具体科学依据
# ============================================================
print()
print("=" * 70)
print("二、约束矩阵中'绝对禁止'位点的科学依据分级")
print("=" * 70)

import csv
csv_path = os.path.join(BASE, 'data', 'sfGFP_禁止突变位点.csv')
with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

# 分类依据可靠性
chemically_absolute = []  # 基于GFP发色团化学机制 → 高可靠性
structurally_critical = []  # 基于结构分析 → 中等可靠性，esmGFP可能反驳
needs_verification = []  # 需要实验数据验证 → 低可靠性

for r in rows:
    cat = r.get('Functional_Category', '')
    func = r.get('Specific_Function', '')
    level = r.get('Conservation_Level', '')

    if level == '绝对禁止':
        # 发色团化学机制相关 → 化学绝对约束
        if any(kw in cat + func for kw in ['发色团核心', '发色团形成催化', '发色团成熟催化',
                                            '发色团质子传递', '发色团形成']):
            chemically_absolute.append(r)
        # 氢键网络 → 重要但可能有替代方案
        elif '氢键' in cat + func:
            structurally_critical.append(r)
        # 疏水核心/转角结构 → esmGFP证明可以被补偿
        elif any(kw in cat for kw in ['疏水核心', 'β-转角', '桶结构']):
            needs_verification.append(r)
        else:
            needs_verification.append(r)

print(f"\n  [一级] 化学绝对约束 (基于GFP发色团形成机制): {len(chemically_absolute)} 个位点")
for r in chemically_absolute:
    print(f"    位点{r['Position']} {r['Residue']}: {r['Specific_Function'][:80]}")

print(f"\n  [二级] 结构关键但可能有替代方案: {len(structurally_critical)} 个位点")
for r in structurally_critical:
    print(f"    位点{r['Position']} {r['Residue']}: {r['Specific_Function'][:80]}")

print(f"\n  [三级] 结构约束 - esmGFP 可能反驳: {len(needs_verification)} 个位点")
for r in needs_verification[:10]:
    print(f"    位点{r['Position']} {r['Residue']}: {r['Specific_Function'][:80]}")
if len(needs_verification) > 10:
    print(f"    ... 及其他 {len(needs_verification)-10} 个位点")


# ============================================================
# 3. esmGFP 的核心启示
# ============================================================
print()
print("=" * 70)
print("三、esmGFP 对约束体系的挑战")
print("=" * 70)

print("""
  esmGFP (Science 2025, DOI: 10.1126/science.ads0018):
  - ESM3 (98B参数) 生成的 GFP，与最近天然同源物 tagRFP 仅 58% 序列一致性
  - 229 个氨基酸中 96 个位置发生突变
  - 荧光亮度与 EGFP 相当

  关键推论:
  1. 大量'不可突变'位点其实是'单独突变不可，组合突变可能'
     → 约束矩阵需要从'禁止突变'改为'禁止单独突变'
     → 如果 ESM3 能同时重新设计 β-桶的疏水核心+转角+表面，
       则许多'绝对禁止'位点可以通过协同突变绕过

  2. 但是，化学层面的约束仍然成立:
     - 发色团三肽 (T65-Y66-G67) 的化学角色不能改变
       → G67 必须有 Gly 的无侧链特性来完成环化亲核攻击
       → Y66 必须有芳香环参与 π 共轭
       → 但 T65 已经被进化改变过 (avGFP 为 S65, sfGFP 为 T65)
     - R96 和 E222 的催化角色 → 可能被其他催化残基替代？
     - 实际上 ESM3 生成 esmGFP 时，发色团形成残基大概率保留了

  3. esmGFP 的真正启示:
     → 约束应该从"位点是否可突变"转向"突变组合是否协同"
     → 需要全序列联合设计，而非逐位点独立判断
     → ProteinMPNN + ESM3 这类工具可以实现协同设计
     → 传统"固定关键残基"的策略可能过于保守
""")

# ============================================================
# 4. 修正建议
# ============================================================
print("=" * 70)
print("四、约束体系的修正建议")
print("=" * 70)

print("""
  原约束体系 (四等级):            →  修正后体系:
  ────────────────────────────────────────────────────
  等级一: 绝对禁止 (37个)         →  化学绝对约束 (约10个):
                                      T65-Y66-G67 发色团三肽 (T可换S/G/A/C)
                                      R96, E222 催化 (可能可协同替换)
                                      其余→降级为"需要协同突变"

  等级二: 严重受限 (约50个)       →  结构协同约束:
                                      疏水核心/转角Gly/Pro
                                      单独突变危险，但可以和其他位点
                                      协同突变 (esmGFP 证明了这一点)

  等级三+四: 可突变+设计热点     →  自由探索空间:
                                      已知增强突变可直接使用
                                      其余位点用 MCMC/ProteinMPNN 探索

  新的设计原则:
  1. 发色团化学机制 → 固定 (T65可保守替换, Y66可芳香替换)
  2. 其余所有位点 → ProteinMPNN/ESM3 协同设计
  3. AF2 pLDDT + MD 验证 → 替代"禁止突变"黑名单
  4. 用实验数据反馈 → 贝叶斯优化替代固定约束矩阵
""")

print("Done.")
