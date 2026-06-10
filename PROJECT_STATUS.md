# PROJECT_STATUS.md — 项目全景与进度追踪

> **自动读取**：每次启动本项目时读取此文件以恢复上下文。
> **自动更新**：每次完成实质性工作后更新"进度更新"部分和"更新日志"。
> **最后更新**：2026-06-10

---

## 一、项目身份

| 项目 | 2026合成生物学创新赛 — 蛋白质设计赛道 |
|------|--------------------------------------|
| 目标 | 设计 **高亮度 + 高热稳定性** 的新型 GFP，提交 **6条氨基酸序列**（220-250aa） |
| 截止 | **2026年7月1日**（有效工作日 18 天） |
| 基线 | sfGFP（superfolder GFP，238aa，PDB 2B3P） |
| 评分 | `Score = (I/I₀) × (I_heat/I)` — 相对亮度 × 热稳定性保留率 |
| 淘汰线 | 初始亮度 < WT sfGFP 的 30% → 直接 0 分 |
| 排名 | 6条中 **Best Top-1** 决定排名，前30%金奖 |
| 提交 | ① CSV（6条序列）② PDF（设计文档）③ GitHub开源仓库 |

---

## 二、核心蓝图文档（按优先级）

| 文档 | 路径 | 用途 |
|------|------|------|
| **管线 v3.0**（权威） | `文档/GFP蛋白质设计_管线设计与实施方案_v3.0.docx` | 五策略+DBLT+Agent+18天时间线 |
| 竞赛官方规则 | `2026Protein Design/2026Protein Design in Synbio challenges.pdf` | 提交格式、评分规则 |
| 零基础实操指南 | `文档/GFP蛋白质设计_零基础实操指南.docx` | 名词解释+代码示例 |
| v2.1 评委审阅 | `文档/运行结果/v2.1_评委视角审阅报告.md` | v3.0 改进依据 |
| 氨基酸注释 | `文档/From Claude/sfGFP_氨基酸功能全注释.docx` | 238位逐位约束参考 |

---

## 三、v3.0 管线架构速览

### 三级约束体系
- **一级（化学绝对，6位点）**：G67/Y66/T65/R96/E222/发色团π堆积 → 固定不可变
- **二级（量子产率，5位点）**：Q69/Q94/H148/T203/S205 → 可探索但需补偿+验证
- **三级（结构验证，~227位点）**：不预先禁止，事后AF2+MD验证

### 五条设计策略
| 策略 | 方法 | GPU需求 | 预期产出 | 风险 |
|------|------|---------|----------|------|
| A | 理性枚举（45位点2-3突变+FoldX） | 无 | ~2-3K条 | 低（保底） |
| B | ESM2+SaProt+ESM3 LoRA + ML集成 + GP贝叶斯优化 | 高 | ~3-5K条 | 中高 |
| C | ProteinMPNN逆折叠（多温度采样） | 中 | ~2-4K条 | 中 |
| D | MSA+EVcouplings进化共识+特征嫁接 | 无 | ~1-2K条 | 中低 |
| E | ESM3 Gibbs采样生成（esmGFP式） | 极高 | ~500-1.5K条 | 高 |

### 五级漏斗筛选
~14K → Phase1合规(~3K) → Phase2亮度(~600) → Phase3 AF2结构(~200) → Phase4三级稳定性(~15) → Phase5 Pareto精选(6)

### DBLT迭代闭环
GP(Matern 5/2核, 50维PCA) + MCMC采样 + EI采集 → MD金标准反馈 → 2-3轮迭代

### GPU预算
| GPU | 串行总计 |
|-----|----------|
| RTX 3090 24GB | ~349h ≈ 14.5天 |
| A100 80GB | ~103h ≈ 4.3天 |

### 18天时间线（v3.0 §10）
- Day 1-2 (6/10-11)：环境搭建 + 模型下载 + 策略A枚举
- Day 3-4 (6/12-13)：LoRA微调 + 策略C + 策略D MSA
- Day 5-6 (6/14-15)：策略B嵌入 + AF2验证 + BioEmu
- Day 7-9 (6/16-18)：MD第1轮 + DBLT第1轮
- Day 10-11 (6/19-20)：Go/No-Go决策 + DBLT第2轮
- Day 12-13 (6/21-22)：MD第2轮 + 策略E进漏斗
- Day 14-15 (6/23-24)：Pareto精选 + 6条确定
- Day 16-18 (6/25-7/1)：提交材料准备

---

## 四、数据资产清单

### 核心数据（已就绪）
| 文件 | 路径 | 条数 |
|------|------|------|
| 官方训练数据 | `data/GFP data.xlsx` (sheet: brightness) | 500 |
| Sarkisyan 2016 全量 | `训练数据/已整合/integrated_csv/03_genotype_brightness_sarkisyan.csv` | **54,026** |
| 亮度训练全集 | `训练数据/已整合/integrated_csv/02_brightness_full.csv` | 141,572 |
| FPbase GFP光谱 | `data/FPbase GFP 光谱.csv` | ~1,110 |
| FireProtDB ΔΔG | `data/fireprotdb_20251015-164116.csv` | ~58 (GFP) |
| 综合GFP数据集 | `data/comprehensive_GFP_dataset.xlsx` | 7 sheets |
| 45候选位点 | 同上，sheet "Candidate_Positions" | 45 |
| Exclusion List | `data/Exclusion_List.csv` | 50 |
| sfGFP PDB | `data/2B3P_sfGFP.pdb` | — |
| 5条参考序列 | `data/WildType AAseqs of 4 GFP proteins.txt` | 5 |
| 往年Top20 | `data/GFP data.xlsx` (sheet: beforetop10) | 20 |

### 数据问题
| 问题 | 文件 | 状态 |
|------|------|------|
| ✅ 已修复 | `data/nature2016_gfp_fitness.tsv` | 已删除（损坏副本），正确数据在 `训练数据/已整合/` |
| ✅ 已修复 | `data/sfGFP_禁止突变位点.csv` | 228行×8列，14行字段数异常已修复（4条9→8，10条7→8） |
| 🔴 未下载 | ProteinGym GFP子集 | ~51K条含序列+亮度 |
| 🔴 未下载 | TemBERTure权重 | ~400MB热稳定性模型 |

---

## 五、代码资产

### 已有（文献调研阶段）
| 文件 | 用途 |
|------|------|
| `代码/gfp_design.py` | v1原型（ESM-2 35M+RF，avGFP骨架，仅亮度） |
| `代码/integrate_data.py` | 数据整合脚本 |
| `代码/build_comprehensive_dataset.py` | 综合数据集构建 |
| `代码/generate_report.py` 系列 | 文献调研报告生成 |

### 缺失（v3.0 管线全部待开发）
策略A枚举、策略B ML集成、策略C ProteinMPNN、策略D MSA/EVcouplings、策略E ESM3 Gibbs、五级漏斗、DBLT迭代、Agent编排 — **全部待写**。

---

## 六、环境状态

| 维度 | 当前 | 需求 |
|------|------|------|
| Python | 3.10.20 ✅ | ≥3.9 ✅ |
| Conda env | `gfp_design` ✅ | — |
| **本地** | 暗影精灵笔记本，**RTX 3090 24GB** | ✅ 可跑ESM2 650M/LoRA/ProteinMPNN/AF2 |
| **服务器** | 浪潮NF8480M6，**2×L40 48GB**（共享） | ✅ 可跑MD/ESM3 Gibbs（不能独占） |
| RAM | 16 GB（本地） | 勉强（650M模型需~13GB） |
| ESM-2 35M | ✅ 已缓存 | — |
| ESM-2 150M | ✅ 已缓存 | — |
| ESM-2 650M | ❌ 未下载 | 策略B默认模型（~2.5GB） |
| SaProt | ❌ 未下载 | 策略B结构嵌入 |
| ESM3-sm-open | ❌ 未下载 | 策略B LoRA + 策略E生成（需HF许可） |
| xgboost | ✅ 3.2.0 | 策略B集成 |
| lightgbm | ✅ 4.6.0 | 策略B集成 |
| gpytorch | ✅ 1.15.2 | GP贝叶斯优化 |
| botorch | ✅ 0.16.1 | EI + MCMC |
| peft | ✅ 0.19.1 | ESM3 LoRA微调 |

### GPU 资源规划

| GPU | 位置 | 用途 | 约束 |
|-----|------|------|------|
| RTX 3090 24GB | 本地笔记本 | ESM2 650M嵌入、LoRA微调、ProteinMPNN、AF2/ESMFold | 可独占 |
| L40 48GB ×2 | 实验室服务器 | MD 72°C、ESM3 Gibbs生成（高显存+高算力任务） | **不能独占**，课题组共享 |

> ⚠️ **关键**：本地 PyTorch 是 CPU 版本。在 RTX 3090 笔记本上需重装 CUDA 版 PyTorch。
> 服务器上需单独配置 conda 环境。

---

## 七、当前进度（对照 v3.0 时间线）

### 已完成 ✅
- [x] 文献调研与报告（~57篇参考文献）
- [x] 评委视角审阅报告（→ v3.0 改进依据）
- [x] v3.0 管线设计文档
- [x] 三级约束体系定义
- [x] 数据收集整合（Sarkisyan 54K + FPbase + FireProtDB）
- [x] 基础环境（Python + 核心库）
- [x] ESM-2 35M + 150M 模型下载

### 进行中 🟡
- [ ] **GPU 资源解决**（最大阻塞项）
- [ ] 缺失包安装（xgboost/lightgbm/gpytorch/botorch/peft）

### 待启动 🔴
- [ ] 修复损坏数据文件
- [ ] ESM-2 650M 下载
- [ ] 策略A：理性枚举脚本
- [ ] 策略D：MSA构建（jackhmmer）
- [ ] 策略B：ESM-2嵌入 + ML训练
- [ ] SaProt 下载 + 嵌入
- [ ] ESM3 HuggingFace许可 + 下载
- [ ] 策略C：ProteinMPNN
- [ ] 策略E：ESM3 Gibbs生成
- [ ] 五级漏斗筛选
- [ ] DBLT迭代闭环
- [ ] Agent编排
- [ ] 提交材料准备

---

## 八、立即下一步

1. **解决GPU** — AutoDL A100 或确认本地GPU
2. `pip install xgboost lightgbm gpytorch botorch peft`
3. 修复 `data/sfGFP_禁止突变位点.csv` 格式
4. 删除损坏的 `data/nature2016_gfp_fitness.tsv`
5. 下载 ESM-2 650M 模型
6. 编写策略A枚举脚本（无GPU可立即跑）

---

## 九、更新日志

| 日期 | 更新内容 |
|------|----------|
| 2026-06-10 | 初始创建：全项目扫描，建立数据/代码/环境/进度基线 |
| 2026-06-10 | **修复**：删除损坏的 `nature2016_gfp_fitness.tsv`；修复 `sfGFP_禁止突变位点.csv`（14行字段异常→全部8字段）；安装 xgboost/lightgbm/gpytorch/botorch/peft；确认硬件 RTX3090笔记本+L40服务器 |
