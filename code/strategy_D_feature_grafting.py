# -*- coding: utf-8 -*-
"""
策略D Phase 2：特征嫁接
=======================
从已知高性能 GFP 变体（mBaoJin, TGP, StayGold, EGFP 等）中提取有益突变，
通过序列比对识别可移植的"特征模块"，嫁接到 sfGFP 骨架。

特征来源：
  - mBaoJin (Zhang 2024, Nat Methods) — 高亮度单体 GFP，StayGold 衍生
  - TGP (Close 2015, Proteins) — 极端热稳定 GFP
  - EGFP (Cormack 1996) — 经典 F64L/S65T 增强型
  - 天然 GFP 同源物 (amacGFP, cgreGFP, ppluGFP) — 序列比对提取差异模块

用法:
  python code/strategy_D_feature_grafting.py
"""

import json
import logging
import os
import sys

import pandas as pd

# ══════════════════════════════════════════════════════════════════════════════
# 路径与常量
# ══════════════════════════════════════════════════════════════════════════════
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPETITION_DIR = os.path.join(PROJECT_ROOT, "competition")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"

# 三级约束 (与策略A一致)
LEVEL1 = {65, 66, 67, 71, 96, 222}
LEVEL2 = {69, 94, 148, 203, 205}
LEVEL2_ALLOWED = {69: ["N","E"], 94: ["N","E","D"], 148:[], 203:[], 205:[]}
SGFP_CORE = {30:"R",39:"N",64:"L",65:"T",80:"R",99:"S",105:"T",145:"F",153:"T",163:"A",171:"V",206:"V"}
SGFP_CORE_REVERT = {30:"S",39:"Y",65:"S",80:"Q",99:"F",105:"N",145:"Y",153:"M",163:"V",171:"I",206:"A"}
REGIONS = {
    "chromophore": {64,65,66,67,68,69,71,72,94,96,148,203,205,222},
    "beta_core": {10,17,30,32,39,45,73,79,101,105,109,115,122},
    "hydrophobic_core": {134,137,145,147,152,153,163,167,171},
    "surface": {80,175,180,187,190,221,225,231,232,234,236},
    "c_terminal": {206,221,225,231,232,234,236},
}

# ══════════════════════════════════════════════════════════════════════════════
# 文献已知有益突变特征
# ══════════════════════════════════════════════════════════════════════════════
FEATURE_GRAFTS = {
    "EGFP_classic": {
        "source": "Cormack 1996 / Tsien 1998 (经典)",
        "positions": {64: "L", 65: "T"},
        "class": "chromophore",
        "evidence": "classical",
        "note": "sfGFP 已包含这两处突变。此特征用于验证方法正确性。",
    },
    "mBaoJin_monomer": {
        "source": "Zhang et al. 2024, Nature Methods (mBaoJin / StayGold衍生)",
        "positions": {206: "K", 221: "K", 223: "R"},
        "class": "surface",
        "evidence": "strong",
        "note": "单体化突变，消除二聚界面。206位在sfGFP中为V，改为K可增强单体性。",
    },
    "mBaoJin_brightness": {
        "source": "Zhang et al. 2024, Nature Methods",
        "positions": {148: "D"},
        "class": "chromophore",
        "evidence": "strong",
        "note": "H148D 可改变发色团环境，提升亮度。但此为Level 2位点，需要谨慎。",
        "level2_override": True,  # 标记为Level 2位点允许
    },
    "TGP_thermostability": {
        "source": "Close et al. 2015, Proteins (TGP)",
        "positions": {30: "R", 39: "N", 105: "T"},
        "class": "folding",
        "evidence": "strong",
        "note": "TGP热稳定核心突变。sfGFP已包含其中大部分。",
    },
    "TGP_surface_stability": {
        "source": "Close et al. 2015, Proteins",
        "positions": {80: "R", 100: "S", 146: "N", 153: "T", 163: "A"},
        "class": "surface",
        "evidence": "medium",
        "note": "TGP表面电荷优化，增强热稳定性。多已在sfGFP中。",
    },
    "avGFP_chromophore": {
        "source": "avGFP vs sfGFP 比对",
        "positions": {65: "S"},
        "class": "chromophore",
        "evidence": "reference",
        "note": "avGFP原始发色团残基。S65T是EGFP经典增强。仅作参考，不用于嫁接。",
    },
    "hydrophobic_core_stabilization": {
        "source": "Multiple thermostable GFP variants",
        "positions": {167: "I"},
        "class": "hydrophobic_core",
        "evidence": "medium",
        "note": "I167 在多种热稳定变体中出现，增强β桶核心堆积。",
    },
    "beta_barrel_dimer_break": {
        "source": "mBaoJin + literature consensus",
        "positions": {221: "K", 223: "R"},
        "class": "surface",
        "evidence": "medium",
        "note": "打破二聚界面，提升单体性。",
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════
def get_region(pos):
    for r, ps in REGIONS.items():
        if pos in ps:
            return r
    return "other"

def apply_mutations(wt_seq, mutations):
    seq = list(wt_seq)
    for pos, aa in mutations.items():
        seq[pos - 1] = aa
    return "".join(seq)

def load_sfgfp():
    path = os.path.join(COMPETITION_DIR, "AAseqs of 5 GFP proteins_20260511.txt")
    with open(path) as f:
        cur, lines = "", []
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                if "sfGFP" in cur and lines:
                    return "".join(lines)
                cur, lines = line, []
            elif line and not line.startswith("#"):
                lines.append(line)
        if "sfGFP" in cur and lines:
            return "".join(lines)
    raise ValueError("sfGFP not found")

def load_all_gfp_sequences():
    """加载所有参考GFP序列"""
    seqs = {}
    for fpath in [
        os.path.join(COMPETITION_DIR, "AAseqs of 5 GFP proteins_20260511.txt"),
        os.path.join(DATA_DIR, "WT_AAseqs_4_GFP.txt"),
    ]:
        if not os.path.exists(fpath):
            continue
        with open(fpath) as f:
            cur, lines = "", []
            for line in f:
                line = line.strip()
                if line.startswith(">"):
                    if cur and lines:
                        s = "".join(lines)
                        if s not in seqs.values():
                            seqs[cur[1:40]] = s
                    cur, lines = line, []
                elif line and not line.startswith("#"):
                    lines.append(line)
            if cur and lines:
                s = "".join(lines)
                if s not in seqs.values():
                    seqs[cur[1:40]] = s
    return seqs

def load_exclusion():
    path = os.path.join(COMPETITION_DIR, "Exclusion_List.csv")
    if not os.path.exists(path):
        return set()
    return set(pd.read_csv(path).iloc[:, 0].astype(str))


# ══════════════════════════════════════════════════════════════════════════════
# 序列比对 → 提取特征模块
# ══════════════════════════════════════════════════════════════════════════════
def pairwise_align_to_sfgfp(sfgfp, variant, var_name):
    """
    简单双序列比对：找到变体与 sfGFP 最相似的偏移对齐。
    返回: {sfGFP_pos_1based: variant_aa}
    """
    # 先看长度是否相同（最简单情况）
    if len(variant) == len(sfgfp):
        diffs = {}
        for i, (a, b) in enumerate(zip(sfgfp, variant)):
            if a != b:
                diffs[i + 1] = b
        return diffs

    # 长度不同：滑动窗口找最佳对齐
    best_score = 0
    best_offset = 0
    min_len = min(len(sfgfp), len(variant))
    for offset in range(-10, 11):
        score = 0
        for i in range(min_len):
            si = i + max(0, offset)
            vi = i + max(0, -offset)
            if si < len(sfgfp) and vi < len(variant):
                if sfgfp[si] == variant[vi]:
                    score += 1
        if score > best_score:
            best_score = score
            best_offset = offset

    diffs = {}
    for i in range(min_len):
        si = i + max(0, best_offset)
        vi = i + max(0, -best_offset)
        if si < len(sfgfp) and vi < len(variant):
            if sfgfp[si] != variant[vi]:
                diffs[si + 1] = variant[vi]  # 1-based

    return diffs


def extract_feature_modules(sfgfp, variant, var_name, window=10, min_diffs=2):
    """
    从变体比对中提取特征模块：≥2个差异在10残基窗口内。
    """
    diffs = pairwise_align_to_sfgfp(sfgfp, variant, var_name)
    if not diffs:
        return []

    pos_list = sorted(diffs.keys())
    modules = []
    i = 0
    while i < len(pos_list):
        cluster = [pos_list[i]]
        j = i + 1
        while j < len(pos_list) and pos_list[j] - cluster[-1] <= window:
            cluster.append(pos_list[j])
            j += 1
        if len(cluster) >= min_diffs:
            muts = {p: diffs[p] for p in cluster}
            regions = {get_region(p) for p in cluster}
            modules.append({
                "source_variant": var_name[:30],
                "positions": cluster,
                "mutations": muts,
                "regions": list(regions),
                "primary_region": cluster_primary_region(cluster),
                "num_mutations": len(cluster),
                "span": cluster[-1] - cluster[0],
            })
        i = j

    return modules


def cluster_primary_region(positions):
    """确定模块的主要功能区域"""
    counts = {}
    for p in positions:
        r = get_region(p)
        counts[r] = counts.get(r, 0) + 1
    return max(counts, key=counts.get) if counts else "other"


# ══════════════════════════════════════════════════════════════════════════════
# 嫁接评分与生成
# ══════════════════════════════════════════════════════════════════════════════
def score_graft(graft, conservation_profile=None):
    """评估嫁接模块质量 (0-1)"""
    score = 0.0
    evidence_weights = {"strong": 1.0, "medium": 0.7, "classical": 0.9, "reference": 0.3}
    evidence = graft.get("evidence", "medium")
    score += evidence_weights.get(evidence, 0.5) * 0.5

    # 结构可行性：检查是否有 Level 1 冲突
    l1_hit = any(p in LEVEL1 for p in graft.get("positions", []))
    if l1_hit:
        score -= 0.5

    # 区域多样性加分
    regions = set()
    for p in graft.get("positions", []):
        regions.add(get_region(p))
    if len(regions) > 1:
        score += 0.1

    # 突变数量
    n = graft.get("num_mutations", 1)
    if 2 <= n <= 4:
        score += 0.1

    return max(0.0, min(1.0, score))


def generate_grafted_candidates(sfgfp, grafts, max_per_graft=5):
    """从嫁接特征生成候选序列"""
    candidates = []
    seen_seqs = set()

    for graft in grafts:
        positions = graft.get("positions", {})
        if isinstance(positions, list):
            # 从 diff 模块来的
            mutations = graft.get("mutations", {})
        else:
            # 从文献来的
            mutations = positions
            positions = list(positions.keys())

        # 过滤约束
        clean_muts = {}
        skip = False
        for pos, aa in mutations.items():
            if pos in LEVEL1:
                skip = True
                break
            if pos in SGFP_CORE_REVERT and aa == SGFP_CORE_REVERT[pos]:
                skip = True
                break
            if pos in LEVEL2 and aa not in LEVEL2_ALLOWED.get(pos, []):
                skip = True
                break
            if aa not in AMINO_ACIDS:
                skip = True
                break
            clean_muts[pos] = aa

        if skip or not clean_muts:
            continue

        seq = apply_mutations(sfgfp, clean_muts)
        if seq in seen_seqs or seq == sfgfp:
            continue
        seen_seqs.add(seq)

        # 突变字符串
        mut_parts = []
        for pos in sorted(clean_muts.keys()):
            mut_parts.append(f"{sfgfp[pos-1]}{pos}{clean_muts[pos]}")
        mut_str = ":".join(mut_parts)

        l2_pos = [p for p in clean_muts if p in LEVEL2]
        regions_set = {get_region(p) for p in clean_muts}

        candidates.append({
            "seq_id": "",
            "sequence": seq,
            "mutation_str": mut_str,
            "num_mutations": len(clean_muts),
            "positions_mutated": ",".join(str(p) for p in sorted(clean_muts)),
            "constraint_max": max(2 if p in LEVEL2 else 3 for p in clean_muts) if clean_muts else 3,
            "level2_warning": len(l2_pos) > 0,
            "level2_positions": ",".join(str(p) for p in l2_pos) if l2_pos else "",
            "regions": ";".join(regions_set),
            "source_scheme": "graft",
            "graft_source": graft.get("source", "")[:80],
            "graft_class": graft.get("class", ""),
            "graft_evidence": graft.get("evidence", ""),
            "graft_score": round(score_graft(graft), 4),
        })

    return candidates


def generate_combined_grafts(sfgfp, grafts, candidates, max_combos=300):
    """组合两个嫁接特征"""
    # 取 top grafts
    scored_grafts = [(score_graft(g), g) for g in grafts]
    scored_grafts.sort(key=lambda x: -x[0])
    top_grafts = [g for _, g in scored_grafts[:15]]

    combos = []
    seen_mut_strs = {c["mutation_str"] for c in candidates}

    for i in range(len(top_grafts)):
        for j in range(i + 1, len(top_grafts)):
            g1, g2 = top_grafts[i], top_grafts[j]

            # 不能有重叠位点
            p1 = set(g1.get("positions", list(g1.get("mutations", {}).keys())))
            p2 = set(g2.get("positions", list(g2.get("mutations", {}).keys())))
            if p1 & p2:
                continue

            # 合并突变
            m1 = g1.get("mutations", g1.get("positions", {}))
            m2 = g2.get("mutations", g2.get("positions", {}))
            if isinstance(m1, list):
                m1 = g1.get("mutations", {})
            if isinstance(m2, list):
                m2 = g2.get("mutations", {})
            combined = {}
            for pos, aa in list(m1.items()) + list(m2.items()):
                if pos in LEVEL1:
                    continue
                if pos in SGFP_CORE_REVERT and aa == SGFP_CORE_REVERT[pos]:
                    continue
                combined[pos] = aa

            if not combined:
                continue

            seq = apply_mutations(sfgfp, combined)
            mut_parts = []
            for pos in sorted(combined.keys()):
                mut_parts.append(f"{sfgfp[pos-1]}{pos}{combined[pos]}")
            mut_str = ":".join(mut_parts)

            if mut_str in seen_mut_strs or seq == sfgfp:
                continue
            seen_mut_strs.add(mut_str)

            l2_pos = [p for p in combined if p in LEVEL2]
            regions_set = {get_region(p) for p in combined}

            combos.append({
                "seq_id": "",
                "sequence": seq,
                "mutation_str": mut_str,
                "num_mutations": len(combined),
                "positions_mutated": ",".join(str(p) for p in sorted(combined)),
                "constraint_max": max(2 if p in LEVEL2 else 3 for p in combined),
                "level2_warning": len(l2_pos) > 0,
                "level2_positions": ",".join(str(p) for p in l2_pos) if l2_pos else "",
                "regions": ";".join(regions_set),
                "source_scheme": "graft_combined",
                "graft_source": f"{g1.get('source','')[:30]} + {g2.get('source','')[:30]}",
                "graft_class": "combined",
                "graft_evidence": "medium",
                "graft_score": round((score_graft(g1) + score_graft(g2)) / 2, 4),
            })

    combos.sort(key=lambda x: -x["graft_score"])
    return combos[:max_combos]


def filter_and_dedup(candidates, sfgfp, exclusion_set):
    """约束过滤 + 去重"""
    seen = set()
    passed = []
    for c in candidates:
        seq = c["sequence"]
        if seq in seen or seq == sfgfp:
            continue
        if seq in exclusion_set:
            continue
        # Level 1 检查
        ok = True
        for p in LEVEL1:
            if seq[p - 1] != sfgfp[p - 1]:
                ok = False
                break
        if not ok:
            continue
        # sfGFP 核心逆转
        for p, aa in SGFP_CORE_REVERT.items():
            if seq[p - 1] == aa:
                ok = False
                break
        if not ok:
            continue
        seen.add(seq)
        passed.append(c)
    return passed


# ══════════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════════
def run_phase2():
    log.info("=" * 60)
    log.info("STRATEGY D — Phase 2: Feature Grafting")
    log.info("=" * 60)

    # 1. 加载数据
    sfgfp = load_sfgfp()
    log.info("sfGFP WT: %d aa", len(sfgfp))
    exclusion_set = load_exclusion()
    ref_seqs = load_all_gfp_sequences()
    log.info("Reference sequences: %d", len(ref_seqs))

    # 2. 从参考序列提取特征模块
    all_modules = []
    for name, seq in ref_seqs.items():
        if "sfGFP" in name:
            continue
        modules = extract_feature_modules(sfgfp, seq, name)
        for m in modules:
            m["source"] = f"Ref:{name[:25]}"
        all_modules.extend(modules)
    log.info("Extracted %d feature modules from reference sequences", len(all_modules))

    # 3. 整合文献特征 + 序列特征
    all_grafts = []

    # 文献特征（转为统一格式）
    for graft_name, graft_info in FEATURE_GRAFTS.items():
        # 过滤：移除已在 sfGFP 中的突变
        clean_positions = {}
        for pos, aa in graft_info["positions"].items():
            if 1 <= pos <= len(sfgfp) and sfgfp[pos - 1] != aa:
                clean_positions[pos] = aa
        if clean_positions:
            all_grafts.append({
                "source": f"{graft_name} ({graft_info['source']})",
                "positions": list(clean_positions.keys()),
                "mutations": clean_positions,
                "regions": list({get_region(p) for p in clean_positions}),
                "primary_region": cluster_primary_region(list(clean_positions.keys())),
                "num_mutations": len(clean_positions),
                "span": max(clean_positions.keys()) - min(clean_positions.keys()) if clean_positions else 0,
                "class": graft_info.get("class", ""),
                "evidence": graft_info.get("evidence", "medium"),
                "note": graft_info.get("note", ""),
            })

    # 序列比对特征（去重 + 去共性）
    seen_sigs = set()
    for m in all_modules:
        sig = tuple(sorted(m["mutations"].items()))
        if sig not in seen_sigs:
            seen_sigs.add(sig)
            m["class"] = m["primary_region"]
            m["evidence"] = "sequence"
            m["source"] = m.get("source_variant", "") if "source_variant" in m else m.get("source", "")
            all_grafts.append(m)

    log.info("Total unique grafts: %d (literature + sequence)", len(all_grafts))

    # 4. 生成候选
    singles = generate_grafted_candidates(sfgfp, all_grafts)
    combos = generate_combined_grafts(sfgfp, all_grafts, singles)

    all_candidates = singles + combos
    log.info("Candidates before filtering: %d (singles: %d, combos: %d)",
             len(all_candidates), len(singles), len(combos))

    # 5. 过滤
    all_candidates = filter_and_dedup(all_candidates, sfgfp, exclusion_set)
    log.info("After filtering: %d", len(all_candidates))

    # 6. 编号
    for i, c in enumerate(all_candidates):
        c["seq_id"] = f"SD_G_{i:04d}"

    # 7. 保存
    os.makedirs(RESULTS_DIR, exist_ok=True)

    rows = []
    for c in all_candidates:
        rows.append({
            "seq_id": c["seq_id"],
            "sequence": c["sequence"],
            "mutation_str": c["mutation_str"],
            "num_mutations": c["num_mutations"],
            "positions_mutated": c["positions_mutated"],
            "constraint_max": c["constraint_max"],
            "level2_warning": c["level2_warning"],
            "level2_positions": c["level2_positions"],
            "regions": c["regions"],
            "source_scheme": c["source_scheme"],
            "graft_source": c.get("graft_source", ""),
            "graft_class": c.get("graft_class", ""),
            "graft_evidence": c.get("graft_evidence", ""),
            "graft_score": c.get("graft_score", ""),
        })

    csv_path = os.path.join(RESULTS_DIR, "strategy_D_feature_grafts.csv")
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    log.info("Saved %d graft candidates → %s", len(rows), csv_path)

    # 8. 保存嫁接目录
    catalog = []
    for g in all_grafts:
        catalog.append({
            "source": g.get("source", ""),
            "positions": list(g.get("positions", [])),
            "mutations": g.get("mutations", {}),
            "class": g.get("class", ""),
            "evidence": g.get("evidence", ""),
            "note": g.get("note", ""),
        })
    json_path = os.path.join(RESULTS_DIR, "strategy_D_graft_catalog.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    log.info("Graft catalog → %s", json_path)

    # 统计
    schemes = {}
    for c in all_candidates:
        s = c["source_scheme"]
        schemes[s] = schemes.get(s, 0) + 1
    for k, v in schemes.items():
        log.info("  %s: %d", k, v)

    log.info("=" * 60)
    log.info("Phase 2 complete! %d graft candidates", len(all_candidates))
    log.info("=" * 60)

    return all_candidates


if __name__ == "__main__":
    run_phase2()
