# -*- coding: utf-8 -*-
"""
策略B — 特征工程管线
====================
组合 ESM-2 650M 嵌入与手工特征，生成 ~1531 维特征矩阵。

特征组成:
  [ESM嵌入 1280d] + [保守性 238d] + [BLOSUM62总分 1d] + [上位性 1d] +
  [突变数 1d] + [区域one-hot 5d] + [位置多样性 1d] + [sfGFP核心保留 1d] +
  [突变位点保守性 aggr 3d] = ~1531d

用法:
  python features.py                          # 生成训练特征
  python features.py --candidates             # 为候选序列生成特征
"""

import json
import os
import sys

import numpy as np
import pandas as pd

from config import (
    AVGFP_PROCESSED, EMBEDDINGS_NPZ, FEATURES_X_NPY, FEATURES_Y_NPY,
    FEATURES_META_JSON, STRAT_B_DIR, CONSERVATION_CSV, EPISTASIS_JSON,
    STRAT_A_PASSED, STRAT_D_ALL, CANDIDATE_SCORES_CSV,
    EMBED_DIM, MAX_SEQ_LEN, REGIONS, REGION_LIST, SFGFP_CORE_POSITIONS,
    BLOSUM62, AMINO_ACIDS, log,
    get_avGFP_wt, get_sfGFP_wt,
)

# 缓存已加载的数据（避免重复 IO）
_conservation_df = None
_epistasis_rules = None
_sfgfp_wt = None
_avGFP_wt = None


def _load_conservation():
    global _conservation_df
    if _conservation_df is None:
        _conservation_df = pd.read_csv(CONSERVATION_CSV)
    return _conservation_df


def _load_epistasis_rules():
    global _epistasis_rules
    if _epistasis_rules is None:
        with open(EPISTASIS_JSON, "r") as f:
            data = json.load(f)
        _epistasis_rules = data.get("rules", [])
    return _epistasis_rules


def _get_sfgfp():
    global _sfgfp_wt
    if _sfgfp_wt is None:
        _sfgfp_wt = get_sfGFP_wt()
    return _sfgfp_wt


def _get_avGFP():
    global _avGFP_wt
    if _avGFP_wt is None:
        _avGFP_wt = get_avGFP_wt()
    return _avGFP_wt


# ══════════════════════════════════════════════════════════════════════════════
# 手工特征计算
# ══════════════════════════════════════════════════════════════════════════════

def compute_conservation_features(sequence, wt_seq):
    """位点保守性特征 (238维)。

    对每个位置 i：保守性分数 × I[seq[i] != wt[i]]
    即仅在突变位置保留保守性信息，未突变位置为 0。
    """
    cons_df = _load_conservation()
    conservation_scores = cons_df["conservation"].values  # length 238
    features = np.zeros(MAX_SEQ_LEN, dtype=np.float32)
    for i in range(min(len(sequence), MAX_SEQ_LEN)):
        if sequence[i] != wt_seq[i]:
            features[i] = conservation_scores[i]
    return features


def compute_blosum62_score(sequence, wt_seq):
    """BLOSUM62 替换总分 (1维)。

    对所有突变位置 i 累加 BLOSUM62(wt[i], seq[i])。
    """
    total = 0.0
    for i in range(min(len(sequence), len(wt_seq))):
        if sequence[i] != wt_seq[i]:
            a, b = wt_seq[i], sequence[i]
            total += BLOSUM62.get((a, b), -4)
    return np.array([total], dtype=np.float32)


def compute_epistasis_score(mutation_str):
    """上位性违规/奖励分数 (1维)。

    从 strategy_D_epistasis_rules.json 加载规则，
    对每条突变序列计算协同奖励总和（synergistic enrichment 累加）。
    高值 = 突变组合在进化上协同。
    """
    from re import match as re_match

    rules = _load_epistasis_rules()
    if not rules:
        return np.array([0.0], dtype=np.float32)

    # 解析突变
    mutations = {}
    if isinstance(mutation_str, str) and mutation_str.strip().upper() != "WT":
        for part in mutation_str.split(":"):
            m = re_match(r"([A-Z])(\d+)([A-Z])", part.strip())
            if m:
                mutations[int(m.group(2))] = m.group(3).upper()

    bonus = 0.0
    for rule in rules:
        rpos = rule["trigger_pos"]
        raa = rule["trigger_aa"]
        cpos = rule["coupled_pos"]
        if rpos in mutations and mutations[rpos] == raa:
            coupled_aa = mutations.get(cpos)
            if rule["type"] == "synergistic" and coupled_aa == rule.get("favored_aa"):
                bonus += rule.get("enrichment", 1.0)

    return np.array([bonus], dtype=np.float32)


def compute_mutation_count(mutation_str):
    """突变数量 (1维)。"""
    if not isinstance(mutation_str, str) or mutation_str.strip().upper() == "WT":
        return np.array([0], dtype=np.float32)
    return np.array([len(mutation_str.split(":"))], dtype=np.float32)


def compute_region_features(sequence, wt_seq):
    """被突变区域的 one-hot 编码 (5维)。

    五区域: chromophore, beta_core, hydrophobic_core, surface, c_terminal
    若某区域至少有一个位点被突变，对应维 = 1。
    """
    mutated_positions = set()
    for i in range(min(len(sequence), len(wt_seq))):
        if sequence[i] != wt_seq[i]:
            mutated_positions.add(i + 1)  # 1-based

    features = np.zeros(len(REGION_LIST), dtype=np.float32)
    for idx, region_name in enumerate(REGION_LIST):
        region_positions = set(REGIONS.get(region_name, []))
        if mutated_positions & region_positions:
            features[idx] = 1.0
    return features


def compute_position_diversity(sequence, wt_seq):
    """突变位置多样性 (1维) — 香农熵。

    将 238 个位置分成 10 个 bin (每 24 个位置一个 bin)，
    计算突变在各 bin 间分布的熵。高值 = 突变均匀分布。
    """
    bins = np.zeros(10)
    for i in range(min(len(sequence), len(wt_seq))):
        if sequence[i] != wt_seq[i]:
            bin_idx = min(i // 24, 9)
            bins[bin_idx] += 1

    total = bins.sum()
    if total == 0:
        return np.array([0.0], dtype=np.float32)

    entropy = 0.0
    for count in bins:
        if count > 0:
            p = count / total
            entropy -= p * np.log(p)
    return np.array([entropy], dtype=np.float32)


def compute_sfgfp_core_preservation(sequence, wt_avGFP):
    """sfGFP 超折叠核心突变保留率 (1维)。

    sfGFP 相比 avGFP 有 12 个关键突变（SFGFP_CORE_POSITIONS）。
    此特征衡量序列在这些位点上保留了 sfGFP 氨基酸的比例。
    仅对使用 avGFP WT 引用时有效（候选序列使用 sfGFP WT 时返回 1.0）。
    """
    sfgfp = _get_sfgfp()
    preserved = 0
    for pos in SFGFP_CORE_POSITIONS:
        idx = pos - 1  # 0-based
        if idx < len(sequence) and idx < len(sfgfp):
            if sequence[idx] == sfgfp[idx]:
                preserved += 1
    return np.array([preserved / max(len(SFGFP_CORE_POSITIONS), 1)], dtype=np.float32)


def compute_mutation_site_conservation(sequence, wt_seq):
    """突变位点保守性统计 (3维)。

    对突变位置的保守性分数计算 min / max / mean。
    若没有突变，返回 [0, 0, 0]。
    """
    cons_df = _load_conservation()
    conservation_scores = cons_df["conservation"].values  # 238

    scores = []
    for i in range(min(len(sequence), len(wt_seq))):
        if sequence[i] != wt_seq[i]:
            scores.append(conservation_scores[i])

    if not scores:
        return np.zeros(3, dtype=np.float32)

    return np.array([min(scores), max(scores), np.mean(scores)], dtype=np.float32)


# ══════════════════════════════════════════════════════════════════════════════
# 主特征工程函数
# ══════════════════════════════════════════════════════════════════════════════

def featurize(sequence, mutation_str, wt_seq):
    """为单条序列生成完整特征向量 (~1531维)。

    Parameters
    ----------
    sequence : str
        全长氨基酸序列 (238aa)
    mutation_str : str
        突变描述字符串，如 "WT" 或 "E172V:S205T"
    wt_seq : str
        参考 WT 序列（训练数据用 avGFP，候选用 sfGFP）

    Returns
    -------
    np.ndarray (1531,)
    """
    features = []

    # Bloc 1: ESM 嵌入 (1280d) — 由外部传入并拼接，这里放 NaN placeholder
    esm_placeholder = np.full(EMBED_DIM, np.nan, dtype=np.float32)
    features.append(esm_placeholder)

    # Bloc 2: 保守性 (238d)
    features.append(compute_conservation_features(sequence, wt_seq))

    # Bloc 3: BLOSUM62 (1d)
    features.append(compute_blosum62_score(sequence, wt_seq))

    # Bloc 4: 上位性 (1d)
    features.append(compute_epistasis_score(mutation_str))

    # Bloc 5: 突变数 (1d)
    features.append(compute_mutation_count(mutation_str))

    # Bloc 6: 区域 one-hot (5d)
    features.append(compute_region_features(sequence, wt_seq))

    # Bloc 7: 位置多样性 (1d)
    features.append(compute_position_diversity(sequence, wt_seq))

    # Bloc 8: sfGFP 核心保留 (1d)
    features.append(compute_sfgfp_core_preservation(sequence, wt_seq))

    # Bloc 9: 突变位点保守性 aggr (3d)
    features.append(compute_mutation_site_conservation(sequence, wt_seq))

    return np.concatenate(features)


def featurize_batch(sequences, mutation_strs, wt_seq, embeddings=None):
    """批量特征化，可选拼接 ESM 嵌入。

    Parameters
    ----------
    sequences : list[str]
    mutation_strs : list[str]
    wt_seq : str
    embeddings : np.ndarray or None, shape (N, 1280)

    Returns
    -------
    np.ndarray (N, 1531)
    """
    n = len(sequences)
    if embeddings is not None:
        assert len(embeddings) == n, f"Embeddings {len(embeddings)} != sequences {n}"
        assert embeddings.shape[1] == EMBED_DIM, f"Embed dim {embeddings.shape[1]} != {EMBED_DIM}"

    features_list = []
    for i in range(n):
        feat = featurize(sequences[i], mutation_strs[i], wt_seq)
        if embeddings is not None:
            feat[:EMBED_DIM] = embeddings[i]
        else:
            # 无 ESM 嵌入时用 0 填充（而非 NaN），保证下游可用
            feat[:EMBED_DIM] = 0.0
        features_list.append(feat)

    X = np.array(features_list, dtype=np.float32)
    return X


def get_feature_names():
    """返回特征名列表。"""
    names = []
    # ESM
    for i in range(EMBED_DIM):
        names.append(f"esm_{i}")
    # Conservation
    for i in range(1, MAX_SEQ_LEN + 1):
        names.append(f"cons_pos{i}")
    # BLOSUM62
    names.append("blosum62_total")
    # Epistasis
    names.append("epistasis_bonus")
    # Mutation count
    names.append("num_mutations")
    # Region one-hot
    for r in REGION_LIST:
        names.append(f"region_{r}")
    # Position diversity
    names.append("position_diversity")
    # sfGFP core preservation
    names.append("sfgfp_core_preservation")
    # Mutation site conservation
    names.extend(["mut_site_cons_min", "mut_site_cons_max", "mut_site_cons_mean"])
    return names


# ══════════════════════════════════════════════════════════════════════════════
# 训练数据特征生成
# ══════════════════════════════════════════════════════════════════════════════

def build_training_features():
    """对 avGFP 训练数据生成完整特征矩阵。"""
    log.info("=" * 60)
    log.info("STRATEGY B — Feature Engineering (Training)")
    log.info("=" * 60)

    # ── 加载处理后的训练数据 ──
    df = pd.read_csv(AVGFP_PROCESSED)
    log.info("Loaded %d training sequences", len(df))

    # ── 加载 ESM 嵌入 ──
    if os.path.exists(EMBEDDINGS_NPZ):
        data = np.load(EMBEDDINGS_NPZ)
        embeddings = data["embeddings"]
        log.info("Loaded embeddings: %s", embeddings.shape)
        assert len(embeddings) == len(df), \
            f"Embeddings {len(embeddings)} != data {len(df)}"
    else:
        log.error("Embeddings not found at %s. Run embed.py first.", EMBEDDINGS_NPZ)
        log.warning("Proceeding with NaN ESM features (for testing only)")
        embeddings = None

    # ── WT 引用（训练数据 = avGFP） ──
    wt_seq = _get_avGFP()
    log.info("Using avGFP WT (len=%d) as reference", len(wt_seq))

    # ── 批量特征化 ──
    sequences = df["full_sequence"].tolist()
    mutation_strs = df["aaMutations"].tolist()

    log.info("Featurizing %d sequences...", len(sequences))
    X = featurize_batch(sequences, mutation_strs, wt_seq, embeddings=embeddings)
    log.info("Feature matrix: %s", X.shape)

    # ── NaN 检查 ──
    nan_mask = np.isnan(X).any(axis=1)
    if nan_mask.any():
        log.warning("Found %d rows with NaN features (dropping)", nan_mask.sum())
        valid = ~nan_mask
        X = X[valid]
        df = df.loc[valid].reset_index(drop=True)
        log.info("After NaN removal: %d sequences, X=%s", len(df), X.shape)

    # ── 保存 ──
    y = df["Brightness"].values.astype(np.float32)

    np.save(FEATURES_X_NPY, X)
    np.save(FEATURES_Y_NPY, y)
    log.info("X → %s", FEATURES_X_NPY)
    log.info("y → %s", FEATURES_Y_NPY)

    # 特征元信息
    meta = {
        "n_samples": X.shape[0],
        "n_features": X.shape[1],
        "feature_names": get_feature_names(),
        "esm_dim": EMBED_DIM,
        "conservation_dim": MAX_SEQ_LEN,
        "total_dim": X.shape[1],
        "y_mean": float(y.mean()),
        "y_std": float(y.std()),
    }
    with open(FEATURES_META_JSON, "w") as f:
        json.dump(meta, f, indent=2)
    log.info("Feature metadata → %s", FEATURES_META_JSON)

    return X, y, df


# ══════════════════════════════════════════════════════════════════════════════
# 候选序列特征生成
# ══════════════════════════════════════════════════════════════════════════════

def build_candidate_features(candidates_csvs=None):
    """为策略A+D候选序列生成特征矩阵。

    候选序列基于 sfGFP，因此使用 sfGFP WT 作为参考。
    注意：候选序列的 ESM 嵌入需要单独在服务器上生成。

    Parameters
    ----------
    candidates_csvs : list[str] or None
        候选 CSV 文件列表，默认用策略A_passed + 策略D_all

    Returns
    -------
    X_cand : np.ndarray
    cand_df : pd.DataFrame
    """
    log.info("=" * 60)
    log.info("STRATEGY B — Feature Engineering (Candidates)")
    log.info("=" * 60)

    if candidates_csvs is None:
        candidates_csvs = [STRAT_A_PASSED, STRAT_D_ALL]

    # ── 加载候选 ──
    dfs = []
    for csv_path in candidates_csvs:
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            log.info("Loaded %d from %s", len(df), os.path.basename(csv_path))
            dfs.append(df)
        else:
            log.warning("Not found: %s", csv_path)

    if not dfs:
        log.error("No candidate files loaded")
        return None, None

    cand_df = pd.concat(dfs, ignore_index=True)
    # 去重（按序列）
    cand_df = cand_df.drop_duplicates(subset="sequence", keep="first")
    log.info("Total unique candidates: %d", len(cand_df))

    # ── WT 引用（候选 = sfGFP） ──
    wt_seq = _get_sfgfp()
    log.info("Using sfGFP WT (len=%d) as reference for candidates", len(wt_seq))

    # ── 特征化（暂不用 ESM 嵌入） ──
    sequences = cand_df["sequence"].tolist()
    mutation_strs = cand_df["mutation_str"].tolist()

    X_cand = featurize_batch(sequences, mutation_strs, wt_seq, embeddings=None)
    log.info("Candidate feature matrix: %s", X_cand.shape)

    # ── 保存 ──
    cand_out = os.path.join(STRAT_B_DIR, "candidate_features_X.npy")
    np.save(cand_out, X_cand)
    cand_df.to_csv(os.path.join(STRAT_B_DIR, "candidate_features_metadata.csv"), index=False)
    log.info("Candidate X → %s", cand_out)

    return X_cand, cand_df


def _fill_esm_features(X_cand, cand_embeddings_npz):
    """将候选ESM嵌入填入特征矩阵的前1280列。"""
    data = np.load(cand_embeddings_npz)
    embeddings = data["embeddings"]
    assert len(embeddings) == X_cand.shape[0], \
        f"Embeddings {len(embeddings)} != candidates {X_cand.shape[0]}"
    X_cand[:, :EMBED_DIM] = embeddings
    return X_cand


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Strategy B: Feature Engineering")
    parser.add_argument("--candidates", action="store_true", help="Build candidate features")
    args = parser.parse_args()

    if args.candidates:
        build_candidate_features()
    else:
        build_training_features()


if __name__ == "__main__":
    main()
