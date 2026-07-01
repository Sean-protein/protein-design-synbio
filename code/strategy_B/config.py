# -*- coding: utf-8 -*-
"""
策略B 全局配置
==============
路径、常量、日志、WT序列加载。
所有模块 import 此文件获取统一配置。
"""

import logging
import os
import sys

# ══════════════════════════════════════════════════════════════════════════════
# 路径
# ══════════════════════════════════════════════════════════════════════════════
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
COMP_DIR = os.path.join(PROJECT_ROOT, "competition")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
STRAT_B_DIR = os.path.join(RESULTS_DIR, "strategy_B")
STRAT_D_DIR = os.path.join(RESULTS_DIR)
MODELS_DIR = os.path.join(STRAT_B_DIR, "models")

os.makedirs(STRAT_B_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
# 模型与嵌入
# ══════════════════════════════════════════════════════════════════════════════
ESM_MODEL_NAME = "esm2_t33_650M_UR50D"
EMBED_DIM = 1280
BATCH_SIZE = 4          # L40 48GB 安全值；OOM 时降至 2
MAX_SEQ_LEN = 238

# ══════════════════════════════════════════════════════════════════════════════
# 训练参数
# ══════════════════════════════════════════════════════════════════════════════
TEST_SIZE = 0.10
VAL_SIZE = 0.10
RANDOM_SEED = 42
N_FOLDS = 5
N_TRIALS_OPTUNA = 30  # Optuna 超参搜索试验次数

# ══════════════════════════════════════════════════════════════════════════════
# 数据文件
# ══════════════════════════════════════════════════════════════════════════════
TRAINING_DATA = os.path.join(COMP_DIR, "GFP_data.xlsx")
AVGFP_PROCESSED = os.path.join(STRAT_B_DIR, "avGFP_processed.csv")
SPLIT_JSON = os.path.join(STRAT_B_DIR, "train_val_test_split.json")
EMBEDDINGS_NPZ = os.path.join(STRAT_B_DIR, "embeddings_esm2_650M.npz")
FEATURES_X_NPY = os.path.join(STRAT_B_DIR, "features_X.npy")
FEATURES_Y_NPY = os.path.join(STRAT_B_DIR, "features_y.npy")
FEATURES_META_JSON = os.path.join(STRAT_B_DIR, "features_metadata.json")
CANDIDATE_SCORES_CSV = os.path.join(STRAT_B_DIR, "candidate_scores.csv")
ENSEMBLE_PRED_CSV = os.path.join(STRAT_B_DIR, "ensemble_predictions.csv")

# 策略 D 产出
CONSERVATION_CSV = os.path.join(STRAT_D_DIR, "strategy_D_conservation_profile.csv")
EPISTASIS_JSON = os.path.join(STRAT_D_DIR, "strategy_D_epistasis_rules.json")
EPISTASIS_MATRIX_CSV = os.path.join(STRAT_D_DIR, "strategy_D_epistasis_matrix.csv")

# 策略 A 产出
STRAT_A_PASSED = os.path.join(RESULTS_DIR, "strategy_A_passed.csv")
STRAT_A_FOLDX = os.path.join(RESULTS_DIR, "strategy_A_foldx_results.csv")

# 策略 D 产出
STRAT_D_ALL = os.path.join(RESULTS_DIR, "strategy_D_all_candidates.csv")
STRAT_D_FOLDX = os.path.join(RESULTS_DIR, "strategy_D_foldx_results.csv")

# 序列参考文件
WT_SEQS_FILE = os.path.join(COMP_DIR, "AAseqs of 5 GFP proteins_20260511.txt")

# ══════════════════════════════════════════════════════════════════════════════
# 约束常量 (与策略A/D一致)
# ══════════════════════════════════════════════════════════════════════════════
LEVEL1 = {65, 66, 67, 71, 96, 222}   # 1-based
LEVEL2 = {69, 94, 148, 203, 205}

REGIONS = {
    "chromophore": list(range(65, 68)),       # 65-67
    "beta_core": [10, 17, 31, 39, 42, 47, 50, 58, 61, 73, 76, 79,
                  82, 85, 88, 91, 97, 100, 103, 106, 109, 112, 115,
                  118, 121, 124, 127, 130, 133, 136, 139, 142, 145,
                  154, 157, 160, 163, 166, 169, 172, 175, 178, 181,
                  184, 187, 190, 193, 196, 199, 202, 208, 211, 214,
                  217, 220, 223, 226, 229, 232],
    "hydrophobic_core": [8, 12, 14, 16, 22, 25, 27, 29, 36, 40, 44,
                         53, 56, 60, 64, 68, 75, 81, 84, 89, 93, 95,
                         98, 104, 107, 111, 113, 119, 123, 129, 132,
                         134, 138, 141, 143, 146, 150, 152, 156, 161,
                         164, 168, 170, 173, 177, 180, 183, 186, 189,
                         191, 195, 198, 200, 204, 207, 210, 213, 216,
                         219, 221, 225, 228, 231, 235],
    "surface": [1, 2, 3, 4, 5, 6, 7, 9, 11, 13, 15, 18, 19, 20, 21,
                23, 24, 26, 28, 30, 32, 33, 34, 35, 37, 38, 41, 43,
                45, 46, 48, 49, 51, 52, 54, 55, 57, 59, 62, 63, 70,
                72, 74, 77, 78, 80, 83, 86, 87, 90, 92, 99, 101,
                102, 105, 108, 110, 114, 116, 117, 120, 122, 125,
                126, 128, 131, 135, 137, 140, 144, 147, 149, 151,
                153, 155, 158, 159, 162, 165, 167, 171, 174, 176,
                179, 182, 185, 188, 192, 194, 197, 201, 206, 209,
                212, 215, 218, 224, 227, 230, 233, 234, 236, 237, 238],
    "c_terminal": list(range(224, 239)),
}
REGION_LIST = ["chromophore", "beta_core", "hydrophobic_core", "surface", "c_terminal"]

# sfGFP superfolder mutations (1-based positions that differ from avGFP)
SFGFP_CORE_POSITIONS = {
    30, 39, 65, 66, 99, 105, 145, 148, 163, 171, 205, 220
}

# ══════════════════════════════════════════════════════════════════════════════
# BLOSUM62 矩阵
# ══════════════════════════════════════════════════════════════════════════════
AMINO_ACIDS = "ARNDCQEGHILKMFPSTWYV"
BLOSUM62 = {
    ('A', 'A'): 4, ('A', 'R'): -1, ('A', 'N'): -2, ('A', 'D'): -2, ('A', 'C'): 0,
    ('A', 'Q'): -1, ('A', 'E'): -1, ('A', 'G'): 0, ('A', 'H'): -2, ('A', 'I'): -1,
    ('A', 'L'): -1, ('A', 'K'): -1, ('A', 'M'): -1, ('A', 'F'): -2, ('A', 'P'): -1,
    ('A', 'S'): 1, ('A', 'T'): 0, ('A', 'W'): -3, ('A', 'Y'): -2, ('A', 'V'): 0,
    ('R', 'R'): 5, ('R', 'N'): 0, ('R', 'D'): -2, ('R', 'C'): -3, ('R', 'Q'): 1,
    ('R', 'E'): 0, ('R', 'G'): -2, ('R', 'H'): 0, ('R', 'I'): -3, ('R', 'L'): -2,
    ('R', 'K'): 2, ('R', 'M'): -1, ('R', 'F'): -3, ('R', 'P'): -2, ('R', 'S'): -1,
    ('R', 'T'): -1, ('R', 'W'): -3, ('R', 'Y'): -2, ('R', 'V'): -3,
    ('N', 'N'): 6, ('N', 'D'): 1, ('N', 'C'): -3, ('N', 'Q'): 0, ('N', 'E'): 0,
    ('N', 'G'): 0, ('N', 'H'): 1, ('N', 'I'): -3, ('N', 'L'): -3, ('N', 'K'): 0,
    ('N', 'M'): -2, ('N', 'F'): -3, ('N', 'P'): -2, ('N', 'S'): 1, ('N', 'T'): 0,
    ('N', 'W'): -4, ('N', 'Y'): -2, ('N', 'V'): -3,
    ('D', 'D'): 6, ('D', 'C'): -3, ('D', 'Q'): 0, ('D', 'E'): 2, ('D', 'G'): -1,
    ('D', 'H'): -1, ('D', 'I'): -3, ('D', 'L'): -4, ('D', 'K'): -1, ('D', 'M'): -3,
    ('D', 'F'): -3, ('D', 'P'): -1, ('D', 'S'): 0, ('D', 'T'): -1, ('D', 'W'): -4,
    ('D', 'Y'): -3, ('D', 'V'): -3,
    ('C', 'C'): 9, ('C', 'Q'): -3, ('C', 'E'): -4, ('C', 'G'): -3, ('C', 'H'): -3,
    ('C', 'I'): -1, ('C', 'L'): -1, ('C', 'K'): -3, ('C', 'M'): -1, ('C', 'F'): -2,
    ('C', 'P'): -3, ('C', 'S'): -1, ('C', 'T'): -1, ('C', 'W'): -2, ('C', 'Y'): -2,
    ('C', 'V'): -1,
    ('Q', 'Q'): 5, ('Q', 'E'): 2, ('Q', 'G'): -2, ('Q', 'H'): 0, ('Q', 'I'): -3,
    ('Q', 'L'): -2, ('Q', 'K'): 1, ('Q', 'M'): 0, ('Q', 'F'): -3, ('Q', 'P'): -1,
    ('Q', 'S'): 0, ('Q', 'T'): -1, ('Q', 'W'): -2, ('Q', 'Y'): -1, ('Q', 'V'): -2,
    ('E', 'E'): 5, ('E', 'G'): -2, ('E', 'H'): 0, ('E', 'I'): -3, ('E', 'L'): -3,
    ('E', 'K'): 1, ('E', 'M'): -2, ('E', 'F'): -3, ('E', 'P'): -1, ('E', 'S'): 0,
    ('E', 'T'): -1, ('E', 'W'): -3, ('E', 'Y'): -2, ('E', 'V'): -2,
    ('G', 'G'): 6, ('G', 'H'): -2, ('G', 'I'): -4, ('G', 'L'): -4, ('G', 'K'): -2,
    ('G', 'M'): -3, ('G', 'F'): -3, ('G', 'P'): -2, ('G', 'S'): 0, ('G', 'T'): -2,
    ('G', 'W'): -2, ('G', 'Y'): -3, ('G', 'V'): -3,
    ('H', 'H'): 8, ('H', 'I'): -3, ('H', 'L'): -3, ('H', 'K'): -1, ('H', 'M'): -2,
    ('H', 'F'): -1, ('H', 'P'): -2, ('H', 'S'): -1, ('H', 'T'): -2, ('H', 'W'): -2,
    ('H', 'Y'): 2, ('H', 'V'): -3,
    ('I', 'I'): 4, ('I', 'L'): 2, ('I', 'K'): -3, ('I', 'M'): 1, ('I', 'F'): 0,
    ('I', 'P'): -3, ('I', 'S'): -2, ('I', 'T'): -1, ('I', 'W'): -3, ('I', 'Y'): -1,
    ('I', 'V'): 3,
    ('L', 'L'): 4, ('L', 'K'): -2, ('L', 'M'): 2, ('L', 'F'): 0, ('L', 'P'): -3,
    ('L', 'S'): -2, ('L', 'T'): -1, ('L', 'W'): -2, ('L', 'Y'): -1, ('L', 'V'): 1,
    ('K', 'K'): 5, ('K', 'M'): -1, ('K', 'F'): -3, ('K', 'P'): -1, ('K', 'S'): 0,
    ('K', 'T'): -1, ('K', 'W'): -3, ('K', 'Y'): -2, ('K', 'V'): -2,
    ('M', 'M'): 5, ('M', 'F'): 0, ('M', 'P'): -2, ('M', 'S'): -1, ('M', 'T'): -1,
    ('M', 'W'): -1, ('M', 'Y'): -1, ('M', 'V'): 1,
    ('F', 'F'): 6, ('F', 'P'): -4, ('F', 'S'): -2, ('F', 'T'): -2, ('F', 'W'): 1,
    ('F', 'Y'): 3, ('F', 'V'): -1,
    ('P', 'P'): 7, ('P', 'S'): -1, ('P', 'T'): -2, ('P', 'W'): -4, ('P', 'Y'): -3,
    ('P', 'V'): -2,
    ('S', 'S'): 4, ('S', 'T'): 1, ('S', 'W'): -3, ('S', 'Y'): -2, ('S', 'V'): -2,
    ('T', 'T'): 5, ('T', 'W'): -2, ('T', 'Y'): -2, ('T', 'V'): 0,
    ('W', 'W'): 11, ('W', 'Y'): 2, ('W', 'V'): -3,
    ('Y', 'Y'): 7, ('Y', 'V'): -1,
    ('V', 'V'): 4,
}

# 对称补全
for (a, b), v in list(BLOSUM62.items()):
    if (b, a) not in BLOSUM62:
        BLOSUM62[(b, a)] = v

# ══════════════════════════════════════════════════════════════════════════════
# 日志
# ══════════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("strategy_B")


# ══════════════════════════════════════════════════════════════════════════════
# WT 序列加载
# ══════════════════════════════════════════════════════════════════════════════
def load_wt_sequences(filepath=None):
    """从参考文件加载所有 WT 序列。返回 {name: sequence} dict。"""
    if filepath is None:
        filepath = WT_SEQS_FILE
    seqs = {}
    cur_name = None
    cur_lines = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(">"):
                if cur_name and cur_lines:
                    seqs[cur_name] = "".join(cur_lines)
                cur_name = line[1:].strip()
                cur_lines = []
            else:
                cur_lines.append(line)
        if cur_name and cur_lines:
            seqs[cur_name] = "".join(cur_lines)
    return seqs


def get_avGFP_wt():
    """获取 avGFP WT 序列"""
    seqs = load_wt_sequences()
    for name, seq in seqs.items():
        if "avGFP" in name:
            return seq
    raise ValueError("avGFP sequence not found")


def get_sfGFP_wt():
    """获取 sfGFP WT 序列"""
    seqs = load_wt_sequences()
    for name, seq in seqs.items():
        if "sfGFP" in name:
            return seq
    raise ValueError("sfGFP sequence not found")


# ══════════════════════════════════════════════════════════════════════════════
# 服务器 vs 本地检测
# ══════════════════════════════════════════════════════════════════════════════
def is_server():
    """检测是否在服务器上运行"""
    return os.path.exists("/data2/fenghaohui")


def get_device():
    """获取可用的计算设备"""
    import torch
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")
