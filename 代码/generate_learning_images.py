# -*- coding: utf-8 -*-
"""
为学习文档添加配图——生成结构示意图并插入文档
"""
from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle, Circle, FancyArrow, Polygon, Arc
import numpy as np
import os

img_dir = r'C:\Users\fengs\Desktop\蛋白质设计-合成生物学创新赛-Claude\images'
os.makedirs(img_dir, exist_ok=True)

# 设置中文字体
for font_name in ['SimHei', 'Microsoft YaHei', 'Noto Sans SC']:
    try:
        plt.rcParams['font.sans-serif'] = [font_name, 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
        break
    except:
        continue


# ===================================================================
# 图1: 学习路线图 (for Doc1)
# ===================================================================
def draw_learning_roadmap():
    fig, ax = plt.subplots(1, 1, figsize=(14, 8))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 8)
    ax.axis('off')
    ax.set_title('GFP蛋白质设计——初学者学习路线图', fontsize=16, fontweight='bold', color='#003366', pad=20)

    stages = [
        (1, 6.5, '阶段 1\nGFP基础理论\n(2-3天)', '#2E86AB',
         ['结构: Beta-桶\n发色团三肽\n自催化成熟\nESPT质子转移']),
        (3.5, 6.5, '阶段 2\nAI工具入门\n(3-5天)', '#1B7A43',
         ['ESM-2/ESM3\nProteinMPNN\nAlphaFold/ColabFold\nGoogle Colab平台']),
        (7.5, 6.5, '阶段 3\n稳定性工程\n(2-3天)', '#D81159',
         ['适应度景观\n上位效应\nDeltaDeltaG预测\nPROSS/TemBERTure']),
        (10.5, 6.5, '阶段 4\n竞赛设计策略\n(3-5天)', '#8B4513',
         ['评分规则解读\nsfGFP突变分析\n管线搭建\n文档撰写']),
    ]

    for x, y, title, color, items in stages:
        box = FancyBboxPatch((x, y), 2.8, 1.5, boxstyle="round,pad=0.1",
                             facecolor=color, edgecolor='white', lw=0, alpha=0.15)
        ax.add_patch(box)
        box2 = FancyBboxPatch((x, y), 2.8, 1.5, boxstyle="round,pad=0.1",
                             fill=False, edgecolor=color, lw=3)
        ax.add_patch(box2)
        ax.text(x+1.4, y+1.1, title, ha='center', fontsize=10, fontweight='bold', color=color)

        for j, item in enumerate(items):
            ax.text(x+0.3, y+0.5 - j*0.25, item, fontsize=7, color='#555555')

        if x < 10.5:
            ax.annotate('', xy=(x+2.8, y+0.75), xytext=(x+3.5, y+0.75),
                       arrowprops=dict(arrowstyle='->', color='#FF8C00', lw=2.5))

    # 先修知识
    prereq_box = FancyBboxPatch((0.3, 4.5), 13.4, 1.2, boxstyle="round,pad=0.15",
                               facecolor='#FFF8DC', edgecolor='#FFD700', lw=3)
    ax.add_patch(prereq_box)
    ax.text(7, 5.3, '先修知识：Python基础编程 · 蛋白质基本概念（氨基酸、一级/二级/三级结构） · 基础的机器学习概念（嵌入、回归、分类）',
            ha='center', fontsize=9, color='#8B4513')

    # 下方资源
    res_box = FancyBboxPatch((0.3, 0.3), 13.4, 3.5, boxstyle="round,pad=0.15",
                            facecolor='#F0F8FF', edgecolor='#4682B4', lw=2)
    ax.add_patch(res_box)
    ax.text(7, 3.5, '核心学习资源', ha='center', fontsize=12, fontweight='bold', color='#003366')

    resources = [
        'ColabDesign → ProteinMPNN/RFdiffusion实操  |  Rosetta Commons YouTube → 理论讲座',
        'ESM GitHub → 蛋白质语言模型  |  FPbase → 荧光蛋白数据库  |  PROSS → 在线稳定性设计',
        '必读文献: Tsien 1998 Annu Rev Biochem  |  Pedelacq 2006 sfGFP  |  Sarkisyan 2016 Nature',
    ]
    for j, res in enumerate(resources):
        ax.text(7, 3.0 - j*0.5, res, ha='center', fontsize=9, color='#4682B4')

    ax.text(7, 1.0, '完成全部学习 → 具备独立参加合成生物学创新赛"蛋白设计赛道"的能力',
            ha='center', fontsize=10, fontweight='bold', color='#D81159')

    path = os.path.join(img_dir, 'learning_roadmap.png')
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path


# ===================================================================
# 图2: AI蛋白质设计管线流程图 (for Doc3)
# ===================================================================
def draw_ai_pipeline():
    fig, ax = plt.subplots(1, 1, figsize=(14, 6))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 6)
    ax.axis('off')
    ax.set_title('AI蛋白质设计标准管线 (2025 Workshop Consensus)', fontsize=14, fontweight='bold', color='#003366', pad=15)

    steps = [
        (0.5, 3.5, '输入\nPDB结构\n(2B3P)', '#2E86AB', '已有高分辨率结构\n直接作为ProteinMPNN\n或RFdiffusion输入'),
        (3.0, 3.5, 'ProteinMPNN\n逆折叠设计', '#1B7A43', '固定发色团残基\nT=0.3-0.5\n生成50-100条候选'),
        (6.0, 3.5, 'AlphaFold2\n结构验证', '#D81159', '预测设计序列结构\n筛选 pLDDT>80\nRMSD<2A'),
        (9.0, 3.5, '稳定性 & 功能\n计算筛选', '#8B4513', 'FoldX/SPURS ddG\nTemBERTure Tm\nESM-2嵌入相似度'),
        (11.5, 3.5, 'Top 6\n候选序列', '#FF6347', '选择6条互补序列\n确保格式合规\n撰写设计文档'),
    ]

    for x, y, title, color, desc in steps:
        box = FancyBboxPatch((x, y), 2.2, 2.2, boxstyle="round,pad=0.1",
                             facecolor=color, edgecolor='white', lw=0, alpha=0.12)
        ax.add_patch(box)
        box2 = FancyBboxPatch((x, y), 2.2, 2.2, boxstyle="round,pad=0.1",
                             fill=False, edgecolor=color, lw=3)
        ax.add_patch(box2)
        ax.text(x+1.1, y+1.6, title, ha='center', fontsize=10, fontweight='bold', color=color)
        for j, line in enumerate(desc.split('\n')):
            ax.text(x+0.2, y+0.9 - j*0.3, line, fontsize=7, color='#555555')

        if x < 11:
            ax.annotate('', xy=(x+2.2, y+1.1), xytext=(x+2.8, y+1.1),
                       arrowprops=dict(arrowstyle='->', color='#FF8C00', lw=2.5))

    # 底部: 迭代循环
    arc = FancyArrowPatch((9.0, 1.0), (3.0, 1.0),
                          connectionstyle="arc3,rad=-.4", color='#999999', lw=1.5,
                          arrowstyle='->', linestyle='dashed')
    ax.add_patch(arc)
    ax.text(6.0, 0.5, '迭代 (Iterate): 低分候选返回ProteinMPNN重新设计', ha='center', fontsize=9, color='#999999')

    path = os.path.join(img_dir, 'ai_pipeline.png')
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path


# ===================================================================
# 图3: 发色团关键残基互作网络 (for Doc2)
# ===================================================================
def draw_chromophore_network():
    fig, ax = plt.subplots(1, 1, figsize=(10, 8))
    ax.set_xlim(-5, 5)
    ax.set_ylim(-5, 5)
    ax.axis('off')
    ax.set_title('GFP发色团微环境关键残基网络', fontsize=14, fontweight='bold', color='#003366', pad=15)

    # 发色团中心
    chromo = Circle((0, 0), 0.6, fill=True, facecolor='#3DDC84', edgecolor='#1B7A43', lw=3, alpha=0.8)
    ax.add_patch(chromo)
    ax.text(0, 0, 'Cro\n(T66-G67-G68)', ha='center', fontsize=8, fontweight='bold', color='white')

    # 关键残基
    residues = [
        ('Glu222\n(E222)', 2.5, 2.0, '#D81159', '终端质子受体\n控制pKa\n氧化vs裂解分支'),
        ('Ser205\n(S205)', 3.0, -0.5, '#9370DB', '质子线中间站\nS205V使ESPT\n减慢30倍'),
        ('Arg96\n(R96)', -2.0, 2.5, '#FF8C00', '环化催化剂\n稳定螺旋kink\nR96A→成熟月级'),
        ('His148\n(H148)', -3.0, -0.5, '#2E86AB', '桶盖残基\nH148S→亮度\n提高1.5倍'),
        ('Thr203\n(T203)', 1.5, -2.5, '#1B7A43', '与酚OH形成\nH-bond\n稳定阴离子'),
        ('Tyr145\n(Y145)', -2.5, -2.5, '#8B4513', '核心堆积\nY145F→Tm\n提高3-4°C'),
    ]

    for name, x, y, color, desc in residues:
        box = FancyBboxPatch((x-0.8, y-0.5), 1.6, 1.0, boxstyle="round,pad=0.05",
                             facecolor=color, edgecolor='white', lw=0, alpha=0.15)
        ax.add_patch(box)
        box2 = FancyBboxPatch((x-0.8, y-0.5), 1.6, 1.0, boxstyle="round,pad=0.05",
                             fill=False, edgecolor=color, lw=2)
        ax.add_patch(box2)
        ax.text(x, y+0.3, name, ha='center', fontsize=8, fontweight='bold', color=color)
        for j, line in enumerate(desc.split('\n')):
            ax.text(x, y-0.1 - j*0.2, line, ha='center', fontsize=6, color='#555555')

        # 连线
        ax.plot([x, 0], [y, 0], '-', color=color, lw=1.5, alpha=0.5)

    # Wat分子
    wat = Circle((-0.3, 1.5), 0.25, fill=True, facecolor='#87CEEB', edgecolor='#4682B4', lw=1.5)
    ax.add_patch(wat)
    ax.text(-0.3, 1.5, 'W1', ha='center', fontsize=7, color='#4682B4')
    ax.plot([-0.3, 0], [1.5, 0.6], '-', color='#87CEEB', lw=1.5, alpha=0.5)

    # 氯离子(mBaoJin)
    cl = Circle((0.8, 1.2), 0.3, fill=True, facecolor='#90EE90', edgecolor='#006400', lw=2)
    ax.add_patch(cl)
    ax.text(0.8, 1.2, 'Cl⁻', ha='center', fontsize=8, color='#006400', fontweight='bold')
    ax.plot([0.8, 0.3], [1.2, 0.3], '-', color='#006400', lw=1.5, alpha=0.5)

    ax.text(4, 4.5, '固定残基 (设计时不动)', fontsize=9, fontweight='bold', color='#D81159')
    ax.text(4, 4.0, '可优化残基 (表面/核心)', fontsize=9, color='#2E86AB')

    path = os.path.join(img_dir, 'chromophore_network.png')
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path


# ===================================================================
# 图4: 稳定性工程策略 (for Doc4)
# ===================================================================
def draw_stability_strategies():
    fig, ax = plt.subplots(1, 1, figsize=(12, 7))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 7)
    ax.axis('off')
    ax.set_title('GFP热稳定性提升——六大工程策略', fontsize=14, fontweight='bold', color='#003366', pad=15)

    strategies = [
        (0.3, 3.8, '1. 疏水核心\n堆积优化', '#1B7A43',
         'Y145F (sfGFP)\n移除极性OH → 紧密\n堆积 → +3-4°C\nI171V协同优化'),
        (2.2, 3.8, '2. 静电网络\n增强', '#2E86AB',
         'S30R (sfGFP)\nE32-R30-E17-\nR122-E115五元\n离子网络'),
        (4.1, 3.8, '3. 表面电荷\n工程', '#9370DB',
         'K/R→E替换 (TGP)\n增加净负电荷\n电荷互斥 →\n减少热聚集'),
        (6.0, 3.8, '4. 发色团环境\n加固', '#D81159',
         'H193Y (TGP/YTP)\nπ-堆积稳定发色团\nQ66E → 化学稳定\nH148S → H-bond'),
        (7.9, 3.8, '5. C末端\n优化', '#CD853F',
         '保留C末端尾巴\n不截断!\n截断→Tm降低\n约6°C'),
        (9.8, 3.8, '6. 折叠动力\n学优化', '#FF6347',
         '快速折叠 →\n少错配中间体\nsfGFP vs folding\nreporter GFP'),
    ]

    for x, y, title, color, desc in strategies:
        box = FancyBboxPatch((x, y), 1.9, 2.5, boxstyle="round,pad=0.1",
                             facecolor=color, edgecolor='white', lw=0, alpha=0.1)
        ax.add_patch(box)
        box2 = FancyBboxPatch((x, y), 1.9, 2.5, boxstyle="round,pad=0.1",
                             fill=False, edgecolor=color, lw=2.5)
        ax.add_patch(box2)
        ax.text(x+0.95, y+2.0, title, ha='center', fontsize=9, fontweight='bold', color=color)
        for j, line in enumerate(desc.split('\n')):
            ax.text(x+0.2, y+1.2 - j*0.3, line, fontsize=7, color='#555555')

    # 底部总结
    sum_box = FancyBboxPatch((0.3, 0.3), 11.4, 2.5, boxstyle="round,pad=0.15",
                             facecolor='#FFF8DC', edgecolor='#FF8C00', lw=3)
    ax.add_patch(sum_box)
    ax.text(6, 2.4, '综合策略：多条路径并行 → 交叉验证 → Top 6序列', ha='center', fontsize=12, fontweight='bold', color='#8B4513')
    ax.text(6, 1.7, '保守路径 (8-12突变)   |   数据驱动路径 (ML预测+多目标优化)   |   生成式路径 (ESM3/GeoEvoBuilder)',
            ha='center', fontsize=9, color='#8B4513')
    ax.text(6, 1.1, '评分: 综合得分 = (F_initial / F_initial_WT) × (F_final / F_initial)  →  拒绝偏科，追求极限！',
            ha='center', fontsize=9, fontweight='bold', color='#D81159')
    ax.text(6, 0.6, '极低亮度淘汰线: F_initial < 0.3 × F_initial_WT  →  序列直接出局 (0分)',
            ha='center', fontsize=8, color='#FF6347')

    path = os.path.join(img_dir, 'stability_strategies.png')
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path


# ===================================================================
# 图5: GFP适应度景观示意 (for Doc4)
# ===================================================================
def draw_fitness_landscape():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    # 左图: 适应度景观概念
    x = np.linspace(-3, 3, 100)
    y_simple = 1 / (1 + np.exp(-x))  # sigmoid
    y_linear = (x + 3) / 6  # linear

    ax1.plot(x, y_linear, 'b--', lw=2, alpha=0.5, label='线性叠加 (无上位)')
    ax1.plot(x, y_simple, 'r-', lw=3, label='Sigmoid截断 (有上位)')
    ax1.axhline(y=0.3, color='gray', linestyle=':', alpha=0.5)
    ax1.axhline(y=0, color='black', linestyle='-', lw=0.5)

    # 标注
    ax1.fill_between(x, y_linear, y_simple, alpha=0.2, color='red')
    ax1.text(-1.5, 0.5, '上位效应区域\n(实际 < 预期)', fontsize=9, color='#D81159', ha='center')

    ax1.set_xlabel('累积突变效应 (Fitness Potential)', fontsize=11)
    ax1.set_ylabel('荧光 (Fluorescence)', fontsize=11)
    ax1.set_title('GFP适应度函数的Sigmoid模型', fontsize=12, fontweight='bold', color='#003366')
    ax1.legend(fontsize=9)
    ax1.set_ylim(-0.05, 1.05)
    ax1.grid(True, alpha=0.3)

    # 右图: 突变数量 vs 荧光
    mutations = ['0', '1', '2', '3', '4', '5', '6', '7+']
    fractions = [0, 23, 35, 45, 50, 58, 65, 72]
    colors = ['#1B7A43', '#2E86AB', '#2E86AB', '#9370DB', '#D81159', '#D81159', '#FF6347', '#FF6347']

    bars = ax2.bar(mutations, fractions, color=colors, alpha=0.8, edgecolor='black', lw=0.5)
    ax2.set_xlabel('突变数量 (Number of Mutations)', fontsize=11)
    ax2.set_ylabel('非荧光基因型比例 (%)', fontsize=11)
    ax2.set_title('多突变导致荧光丧失的比例\n(Sarkisyan et al., Nature 2016)', fontsize=12, fontweight='bold', color='#003366')
    ax2.grid(True, alpha=0.3, axis='y')

    # 关键数据标注
    ax2.annotate('75%单突变\n降低荧光', xy=(1, 23), xytext=(2.5, 35),
                fontsize=9, color='#2E86AB', fontweight='bold',
                arrowprops=dict(arrowstyle='->', color='#2E86AB', lw=1.5))
    ax2.annotate('50%的4突变\n完全丧失荧光', xy=(4, 50), xytext=(5.5, 55),
                fontsize=9, color='#D81159', fontweight='bold',
                arrowprops=dict(arrowstyle='->', color='#D81159', lw=1.5))

    ax2.set_ylim(0, 85)

    plt.tight_layout()
    path = os.path.join(img_dir, 'fitness_landscape.png')
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path


# ===================================================================
# 图6: 学习阶段甘特图-like时间线 (for Doc1)
# ===================================================================
def draw_timeline():
    fig, ax = plt.subplots(1, 1, figsize=(14, 4))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 5)
    ax.axis('off')
    ax.set_title('两周学习时间线推荐', fontsize=14, fontweight='bold', color='#003366', pad=15)

    phases = [
        (0.3, 2.8, 'Day 1-3\nGFP基础', '#2E86AB', '结构·发色团·荧光机制'),
        (3.3, 2.8, 'Day 4-7\nAI工具', '#1B7A43', 'ESM·ProteinMPNN·ColabFold'),
        (6.3, 2.8, 'Day 8-10\n稳定性', '#D81159', '适应度景观·ddG·PROSS'),
        (9.3, 2.8, 'Day 11-14\n管线+提交', '#8B4513', '整合·筛选·文档·GitHub'),
    ]

    # 时间轴
    ax.plot([0.3, 13.5], [1.5, 1.5], 'k-', lw=3)
    for i in range(15):
        ax.plot([i, i], [1.3, 1.7], 'k-', lw=1)
        ax.text(i, 1.1, f'D{i+1}' if i < 14 else '', ha='center', fontsize=7, color='#555555')

    for x, y, title, color, desc in phases:
        box = FancyBboxPatch((x, y), 2.5, 1.7, boxstyle="round,pad=0.1",
                             facecolor=color, edgecolor='white', lw=0, alpha=0.12)
        ax.add_patch(box)
        box2 = FancyBboxPatch((x, y), 2.5, 1.7, boxstyle="round,pad=0.1",
                             fill=False, edgecolor=color, lw=3)
        ax.add_patch(box2)
        ax.text(x+1.25, y+1.2, title, ha='center', fontsize=10, fontweight='bold', color=color)
        ax.text(x+1.25, y+0.5, desc, ha='center', fontsize=8, color='#555555')

        # 时间轴标记点
        ax.plot(x+1.25, 1.5, 'o', color=color, markersize=12, alpha=0.7)

    path = os.path.join(img_dir, 'timeline.png')
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path


# ===================================================================
# 主程序：生成所有图片
# ===================================================================
if __name__ == '__main__':
    print("生成配图...")
    img_timeline = draw_timeline()
    print("  [1/6] 学习时间线完成")
    img_roadmap = draw_learning_roadmap()
    print("  [2/6] 学习路线图完成")
    img_chromophore = draw_chromophore_network()
    print("  [3/6] 发色团互作网络完成")
    img_pipeline = draw_ai_pipeline()
    print("  [4/6] AI设计管线完成")
    img_stability = draw_stability_strategies()
    print("  [5/6] 稳定性策略完成")
    img_fitness = draw_fitness_landscape()
    print("  [6/6] 适应度景观完成")
    print("\n所有配图生成完成！可用于插入各学习文档。")
