# 2026合成生物学创新赛 — 蛋白质设计赛道

## Python 环境

- **包管理器**: Anaconda 2025.12-2（`D:\Anaconda`）
- **虚拟环境**: conda 环境 `gfp_design`（Python 3.10.20）
- **环境位置**: `D:\Anaconda\envs\gfp_design\`
- **激活方式**: PowerShell 中 `conda activate gfp_design`，或运行 `.\setup.ps1`
- **注意**: conda 已配置清华镜像源（`.condarc`），国内下载速度快

## 模型与缓存 (全部在 D 盘)

| 缓存类型 | 路径 | 大小 |
|----------|------|------|
| ESM 模型 (torch hub) | `cache/torch/hub/checkpoints/` | ~128 MB |
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
| `代码/gfp_design.py` | 主线 Pipeline（ESM 嵌入 + 随机森林） |
| `代码/generate_report.py` | 文献调研报告生成脚本 |
| `sfGFP_氨基酸功能全注释.docx` | 238 个氨基酸逐位功能注释 |
| `sfGFP_禁止突变位点.csv` | 位点约束分类（绝对禁止/严重受限/可突变） |
| `data/GFP_training_data.csv` | 训练数据（GFP 突变体亮度） |
| `data/GFP data.xlsx` | 完整训练数据（多 sheet） |
| `data/Exclusion_List.csv` | 禁止提交序列黑名单 |
| `2026Protein Design/2026Protein Design in Synbio challenges.pdf` | 竞赛官方说明 |
