# 蛋白质设计 — 合成生物学创新赛 2026

> **赛道**: 蛋白质设计 — GFP 高亮度与热稳定性联合设计
> **队伍**: Sean-protein
> **提交日期**: 2026年7月1日
> **基线蛋白**: sfGFP (238aa, PDB 2B3P)

## 项目简介

设计兼具极高初始亮度与极限热稳定性（72°C, 10min）的新型绿色荧光蛋白（GFP），提交 **6 条氨基酸序列**（220-250aa）。

评分公式：`Score = (I/I₀) × (I_heat/I)` — 相对亮度 × 热稳定性保留率。

## 管线架构

四策略并行生成 + 分层漏斗筛选：

| 策略 | 方法 | 产出 |
|------|------|:--:|
| **A** 理性枚举 | 45位点 2-3突变 + FoldX ΔΔG | 2,424条通过 |
| **B** ML集成 | ESM-2 650M + XGB/LGBM/RF (R²=0.712) | 全量打分 |
| **D** 进化共识 | MSA + EVcouplings + 特征嫁接 + FoldX | 295条通过 |
| **C** ProteinMPNN | 骨架引导逆折叠 | 1条精选 |

漏斗：Phase 1 合规筛选 → Phase 2 ML亮度排序 → Phase 3 分层筛选 → 6条序列

## 最终6条序列

| # | 策略 | 突变 | ML亮度 | ddG | cons/mpnn |
|:--:|:--:|------|:--:|:--:|:--:|
| 1 | A | S72T:H231F | 4.024 | -1.46 | — |
| 2 | A | S72T:H231N | 4.018 | -1.86 | — |
| 3 | A | I152M:D190N | 3.813 | 1.01 | — |
| 4 | D | L137M:I161L | 1.836 | 1.75 | cons=0.809 |
| 5 | D | L18M:L137M | 1.913 | 0.87 | cons=0.707 |
| 6 | C | 84突变 | — | — | mpnn=0.778 |

详见 `results/submission_6_sequences.csv` 和 `docs/final_submission/design_document.pdf`。

## 环境配置

- Python 3.10+
- 核心管线仅需CPU（FoldX + ML推理）
- GPU推荐用于ESM-2嵌入提取（RTX 3090 24GB+）

```bash
conda create -n gfp_design python=3.10 -y
conda activate gfp_design
pip install -r requirements.txt
```

## 项目结构

```
├── code/                          # Python管线脚本
│   ├── funnel_phase1_compliance.py
│   ├── funnel_phase2_brightness.py
│   ├── funnel_phase3_structure.py
│   ├── funnel_phase4_stability.py
│   ├── funnel_phase5_pareto.py
│   ├── final_selection.py         # 分层筛选
│   ├── generate_pipeline_diagram.py
│   ├── strategy_A_enum.py
│   ├── strategy_B/                # ML集成
│   ├── strategy_C_*.py            # ProteinMPNN
│   └── strategy_D_*.py            # 进化共识
├── results/                       # 漏斗输出 + 最终提交CSV
├── docs/final_submission/         # 设计文档 + 管线图
├── competition/                   # 竞赛规则 + 排除列表
└── README.md
```

## 推理运行

```bash
python code/funnel_phase1_compliance.py   # Phase 1: 合规筛选
python code/funnel_phase2_brightness.py   # Phase 2: ML亮度排序
python code/final_selection.py            # Phase 5: 分层筛选 → 6条
```

## 关键词

分层筛选（Layered Filtering）、FoldX ΔΔG、ESM-2 650M、XGBoost/LightGBM/Random Forest 集成、ProteinMPNN 逆折叠、进化共识分析、EVcouplings、三级约束体系

## 参考文献

1. Sarkisyan KS, et al. *Nature* 533:397-401 (2016)
2. Pédelacq J-D, et al. *Nat Biotechnol* 24:79-88 (2006)
3. Dauparas J, et al. *Science* 378:49-56 (2022)
4. Schymkowitz J, et al. *Nucleic Acids Res* 33:W382-W388 (2005)
5. Lin Z, et al. *Science* 379:1123-1130 (2023)
6. Marks DS, et al. *PLoS ONE* 6:e28766 (2011)

## License

MIT License.
