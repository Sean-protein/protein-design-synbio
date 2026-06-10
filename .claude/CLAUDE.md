# 2026合成生物学创新赛 — 蛋白质设计赛道

## 🧠 项目记忆系统

- **PROJECT_STATUS.md**：项目全景与进度追踪文件（数据清单、代码资产、环境状态、进度、下一步）。
  **每次启动本项目时先读取 `PROJECT_STATUS.md`** 以快速恢复上下文，避免重复扫描全项目。
- **自动更新**：每次完成实质性工作（代码编写、数据处理、模型训练、文档生成）后，
  **必须更新 `PROJECT_STATUS.md`** 的"进度更新"部分和"更新日志"。
- **关键文件**：管线蓝图 = `文档/GFP蛋白质设计_管线设计与实施方案_v3.0.docx`（五策略+DBLT+18天时间线）。

## 🔄 会话结束仪式（每次会话结束前必须执行）

**每次会话结束前，按以下顺序执行：**

1. **更新 PROJECT_STATUS.md**：更新"进度更新"部分和"更新日志"，记录本次会话完成的工作
2. **更新 SESSION_LOG.md**：追加一条会话记录（日期、摘要、关键产出）
3. **Git 提交**：
   ```bash
   git add -A
   git commit -m "<日期> <简短摘要>"
   git push origin master
   ```
   - 提交信息格式：`2026-06-10 数据修复+环境配置+GitHub上传规划`
   - **注意**：`.gitignore` 已排除 `cache/`、`_过程文件/`、`训练数据/`、`参考文献/`、`网站/` 等
4. **更新记忆文件**：如有新的关键信息，更新 `memory/` 下的持久记忆文件

**提交内容白名单**（确认这些类型的文件已被 git 追踪）：
- `代码/*.py` — 所有 Python 脚本
- `文档/**/*.docx` — 设计文档（非临时文件）
- `文档/**/*.md` — Markdown 文档
- `PROJECT_STATUS.md`, `SESSION_LOG.md`, `README.md`
- `.gitignore`, `requirements.txt`, `setup.ps1`
- `data/*.csv` — 核心数据（排除名单等）
- `data/*.pdb` — 结构文件
- `.claude/CLAUDE.md` — 项目指令
- `2026Protein Design/*.csv` — 竞赛官方排除名单
- `2026Protein Design/*.ipynb` — 官方教程 Notebook
- `2026Protein Design/*.txt` — 参考序列

## Python 环境

- **包管理器**: Anaconda 2025.12-2（`D:\Anaconda`）
- **虚拟环境**: conda 环境 `gfp_design`（Python 3.10.20）
- **环境位置**: `D:\Anaconda\envs\gfp_design\`
- **激活方式**: PowerShell 中 `conda activate gfp_design`，或运行 `.\setup.ps1`
- **注意**: conda 已配置清华镜像源（`.condarc`），国内下载速度快

## 模型与缓存 (全部在 D 盘)

| 缓存类型 | 路径 | 大小 |
|----------|------|------|
| ESM-2 35M (torch hub) | `cache/torch/hub/checkpoints/esm2_t12_35M_UR50D.pt` | ~134 MB |
| ESM-2 150M (torch hub) | `cache/torch/hub/checkpoints/esm2_t30_150M_UR50D.pt` | ~593 MB |
| ESM-2 650M | ❌ 未下载 | ~2.5 GB |
| HuggingFace 模型 | `cache/huggingface/` | (按需) |
| pip 缓存 | `cache/pip/` | (按需) |

- **强制 D 盘**: `gfp_design.py` 启动时自动设置 `TORCH_HOME`、`HF_HOME`、`TRANSFORMERS_CACHE` 指向项目 `cache/` 目录

## 核心约定

1. **编程语言默认 Python**：所有脚本、数据处理、文件解析、文档生成、图表绘制等均默认使用 Python。
2. **过程文件统一存放**：所有非输出结果的中间过程文件（临时脚本、调试输出、中间数据、缓存等）统一放入 `_过程文件/` 目录。
3. **输出结果放入 `运行结果/`**：Pipeline 产出的 CSV、预测结果等放入 `运行结果/`。

## 文件处理库

| 文件类型 | 库 | 版本 | 用途 |
|----------|-----|------|------|
| Word (.docx) | `python-docx` | 1.2.0 | 创建、读取、编辑 Word 文档 |
| Excel (.xlsx/.xlsm) | `openpyxl` | 3.1.5 | 读取、写入 Excel 文件（公式、格式、图表） |
| CSV/TSV | `pandas` | - | 表格数据读取与处理 |
| PowerPoint (.pptx) | `python-pptx` | 1.0.2 | 创建、读取、编辑幻灯片 |
| PDF（文本提取） | `pdfplumber` | 0.11.9 | PDF 文本/表格精确提取 |
| PDF（高性能处理） | `PyMuPDF` (fitz) | 1.27.2.3 | 高速 PDF 读取、渲染、转换 |
| PDF（合并/分割） | `PyPDF2` | 3.0.1 | PDF 合并、分割、旋转、元数据 |

### 文件处理默认选择
- **读取 Excel** → `openpyxl`（.xlsx）或 `pandas`（数据分析场景）
- **生成/编辑 Word** → `python-docx`
- **生成/编辑 PPT** → `python-pptx`
- **读取 PDF 文本** → `pdfplumber`（精确文本/表格）或 `PyMuPDF`（高速大量读取）
- **合并/分割 PDF** → `PyPDF2`

## 文档格式约定

- **正文**: 中文宋体 (SimSun)，英文/数字 Times New Roman，小四 (12pt, `Pt(12)`)
- **一级标题**: 微软雅黑 (Microsoft YaHei), 小二 (18pt), 粗体
- **二级标题**: 微软雅黑 (Microsoft YaHei), 小三 (15pt), 粗体
- **三级标题**: 微软雅黑 (Microsoft YaHei), 四号 (14pt), 粗体
- **代码块**: Consolas, 小五 (9pt), 灰色背景
- **页面**: A4, 上下边距 2.5cm, 左右边距 2.5cm

### python-docx 字号速查表
| 中文字号 | pt | python-docx Pt() |
|----------|-----|-------------------|
| 小二 | 18 | `Pt(18)` |
| 小三 | 15 | `Pt(15)` |
| 四号 | 14 | `Pt(14)` |
| 小四 | 12 | `Pt(12)` |
| 五号 | 10.5 | `Pt(10)` 或 `Pt(11)` |
| 小五 | 9 | `Pt(9)` |

## 项目结构

```
D:\蛋白质设计-合成生物学创新赛-Claude\
├── .claude/               # Claude 配置
├── _过程文件/              # ★ 中间过程文件（临时脚本、调试输出、缓存等）
├── data/                   # 原始数据
├── 代码/                   # Python 脚本
├── 2026Protein Design/     # 竞赛官方材料
├── 参考文献/               # 参考文献 PDF
├── 文档/                   # 输出文档（.docx 报告等）
├── 训练数据/               # 训练数据集
├── 运行结果/               # ★ Pipeline 输出结果（CSV、预测结果等）
├── output/                 # 运行输出
├── cache/                  # 缓存（嵌入向量、AF2 结果等）
└── images/                 # 图片
```

## 核心文件速查

| 文件 | 说明 |
|------|------|
| **`PROJECT_STATUS.md`** | ★ 项目全景与进度（数据/代码/环境/下一步），每次启动必读 |
| `文档/GFP蛋白质设计_管线设计与实施方案_v3.0.docx` | ★ 管线蓝图（五策略+DBLT+Agent+18天时间线） |
| `文档/GFP蛋白质设计_零基础实操指南.docx` | 名词解释+代码示例（培训用） |
| `代码/gfp_design.py` | v1 原型 Pipeline（ESM-2 35M + RF），**非v3.0版本** |
| `训练数据/已整合/integrated_csv/03_genotype_brightness_sarkisyan.csv` | Sarkisyan 2016 全量数据（54,026条） |
| `训练数据/已整合/integrated_csv/02_brightness_full.csv` | 亮度训练全集（141,572条） |
| `data/GFP data.xlsx` | 官方训练数据（500条）+ 往年Top20 |
| `data/comprehensive_GFP_dataset.xlsx` | 综合数据集（7 sheets，含45候选位点） |
| `data/FPbase GFP 光谱.csv` | GFP变体光谱性质（~1,110条） |
| `data/fireprotdb_20251015-164116.csv` | FireProtDB 热稳定性ΔΔG |
| `data/Exclusion_List.csv` | 禁止提交序列黑名单（50条） |
| `data/2B3P_sfGFP.pdb` | sfGFP 晶体结构 |
| `data/sfGFP_禁止突变位点.csv` | 位点约束分类（⚠️ 格式损坏需修复） |
| `2026Protein Design/2026Protein Design in Synbio challenges.pdf` | 竞赛官方说明 |
