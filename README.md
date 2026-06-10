# 蛋白质设计 — 合成生物学创新赛 2026

> 🏆 **赛道**: 蛋白质设计 — GFP 高亮度与热稳定性联合设计  
> **队伍**: Sean-protein  
> **截止**: 2026年7月1日  
> **基线**: sfGFP (superfolder GFP, 238aa, PDB 2B3P)

## 项目简介

设计兼具极高初始亮度与极限热稳定性（72°C, 10min）的新型绿色荧光蛋白（GFP），提交 **6 条氨基酸序列**（220-250aa）。

评分：`Score = (I/I₀) × (I_heat/I)` — 相对亮度 × 热稳定性保留率。

## 管线架构（v3.0）

```
五策略并行 → 五级漏斗筛选 → DBLT迭代闭环 → Pareto前沿精选 → 6条提交序列
```

| 策略 | 方法 | GPU | 产出 |
|------|------|-----|------|
| A | 理性工程枚举（45位点+FoldX） | 无 | ~2-3K |
| B | ESM2+SaProt+ESM3 LoRA + ML集成 + GP贝叶斯优化 | 高 | ~3-5K |
| C | ProteinMPNN 逆折叠（多温度采样） | 中 | ~2-4K |
| D | MSA + EVcouplings 进化共识 + 特征嫁接 | 无 | ~1-2K |
| E | ESM3 Gibbs 采样生成（esmGFP式） | 极高 | ~500-1.5K |

详见 `PROJECT_STATUS.md` 和 `文档/GFP蛋白质设计_管线设计与实施方案_v3.0.docx`。

## 环境配置

### 系统要求
- Python 3.10+
- NVIDIA GPU（推荐 RTX 3090 24GB+ 或 A100）
- CUDA 11.8+

### 安装

```bash
# 创建 conda 环境
conda create -n gfp_design python=3.10 -y
conda activate gfp_design

# CUDA 版 PyTorch
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 依赖
pip install -r requirements.txt

# 模型下载（首次运行自动下载，或手动预下载）
python -c "import esm; esm.pretrained.load_model_and_alphabet('esm2_t33_650M_UR50D')"
```

### 模型依赖

| 模型 | 大小 | 用途 | 来源 |
|------|------|------|------|
| ESM-2 650M | ~2.5GB | 策略B序列嵌入 | Meta FAIR |
| SaProt 35M | ~1GB | 策略B结构感知嵌入 | Westlake U |
| ESM3-sm-open 1.4B | ~3GB | 策略B LoRA + 策略E生成 | EvolutionaryScale (HF) |
| ProteinMPNN | ~100MB | 策略C逆折叠 | Dauparas et al. |
| ESMFold/ColabFold | ~3GB | Phase3结构验证 | Meta / Sokrypton |

### 数据下载

部分训练数据需手动下载（详见 `data/README.md`）：

| 数据 | 来源 | 说明 |
|------|------|------|
| Sarkisyan 2016 | HuggingFace `InstaDeepAI/true-cds-protein-tasks` | 54K条 GFP 突变体 |
| ProteinGym GFP | marks.hms.harvard.edu/proteingym | 51K条序列+亮度 |
| FPbase GFP | fpbase.org/api | 光谱性质 |
| FireProtDB | loschmidt.chemi.muni.cz/fireprotdb | 热稳定性 ΔΔG |

## 项目结构

```
├── 代码/                    # Python 管线脚本
│   └── gfp_design.py        # 主线 Pipeline
├── 文档/                    # 设计文档 (.docx)
├── data/                    # 核心数据（排除名单、参考序列、PDB等）
├── 2026Protein Design/      # 竞赛官方材料
├── PROJECT_STATUS.md        # ★ 项目进度追踪（每次会话更新）
├── SESSION_LOG.md           # 会话日志
├── requirements.txt         # Python 依赖
├── setup.ps1                # Windows 环境激活
└── README.md
```

## 推理运行

```bash
# 完整管线（v3.0 开发中）
python 代码/gfp_design.py --data-dir ./data --method esm --esm-model esm2_t33_650M_UR50D
```

## 参考文献

1. Sarkisyan KS, et al. *Nature* 533:397-401 (2016) — GFP 适应度景观
2. Rives A, et al. *Science* 387:850-858 (2025) — ESM3/esmGFP
3. Pédelacq J-D, et al. *Nat Biotechnol* 24:79-88 (2006) — sfGFP
4. Dauparas J, et al. *Science* 378:49-56 (2022) — ProteinMPNN
5. Lewis S, et al. *Science* (2025) — BioEmu
6. Huang J, et al. *Nat Methods* 14:71-73 (2017) — CHARMM36m

## License

MIT License. 使用 ESM-3 模型需遵守 EvolutionaryScale 非商业许可。
