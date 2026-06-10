"""
Convert training data files to CSV and integrate with comprehensive_GFP_dataset.
Output: consolidated CSV + individual cleaned CSVs.
"""
import pandas as pd
import json
import os
import re
import warnings
warnings.filterwarnings('ignore')

BASE = r"C:\Users\fengs\Desktop\蛋白质设计-合成生物学创新赛-Claude"
TRAIN = os.path.join(BASE, "训练数据")
OUTPUT = os.path.join(BASE, "output")
INTEGRATED = os.path.join(OUTPUT, "integrated_csv")
os.makedirs(INTEGRATED, exist_ok=True)

print("=" * 60)
print("STEP 1: Convert all training data files to CSV")
print("=" * 60)

# --- 1. AAseqs of 5 GFP proteins (TXT → CSV) ---
print("\n[1/8] Converting AAseqs TXT to CSV...")
with open(os.path.join(TRAIN, "AAseqs of 5 GFP proteins_20260511.txt"), "r", encoding="utf-8") as f:
    content = f.read()

# Parse FASTA-like format
entries = re.findall(r'>(\w+)\n([A-Z]+)\n(?:#\s*(.+))?', content)
seq_data = []
for name, seq, note in entries:
    seq_data.append({"Protein": name, "Sequence": seq, "Recommended_PDB": note.strip() if note else ""})
df_seqs = pd.DataFrame(seq_data)
df_seqs.to_csv(os.path.join(INTEGRATED, "01_reference_sequences.csv"), index=False, encoding="utf-8-sig")
print(f"  -> {len(df_seqs)} protein sequences saved")

# --- 2. GFP_data.xlsx → CSV (2 sheets) ---
print("\n[2/8] Converting GFP_data.xlsx to CSV...")
gfp_xl = pd.ExcelFile(os.path.join(TRAIN, "GFP_data.xlsx"))
# Sheet: brightness
df_brightness = pd.read_excel(gfp_xl, "brightness")
df_brightness.columns = ["aaMutations", "GFP_type", "Brightness"]
df_brightness.to_csv(os.path.join(INTEGRATED, "02_brightness_full.csv"), index=False, encoding="utf-8-sig")
print(f"  -> brightness: {len(df_brightness)} rows saved")

# Sheet: beforetopseqs
df_beforetop = pd.read_excel(gfp_xl, "beforetopseqs")
df_beforetop.columns = ["Year", "Sequence"]
df_beforetop.to_csv(os.path.join(INTEGRATED, "02b_historical_top_sequences.csv"), index=False, encoding="utf-8-sig")
print(f"  -> beforetopseqs: {len(df_beforetop)} rows saved")

# --- 3. amino_acid_genotypes_to_brightness.tsv (already have CSV) ---
print("\n[3/8] Copying amino_acid_genotypes_to_brightness (TSV→CSV)...")
df_aag = pd.read_csv(os.path.join(TRAIN, "amino_acid_genotypes_to_brightness.tsv"), sep="\t")
df_aag.columns = ["aaMutations", "uniqueBarcodes", "medianBrightness", "std"]
df_aag.to_csv(os.path.join(INTEGRATED, "03_genotype_brightness_sarkisyan.csv"), index=False, encoding="utf-8-sig")
print(f"  -> {len(df_aag)} rows saved")

# --- 4. fpbase_proteins_basic_gfp.csv (clean and copy) ---
print("\n[4/8] Cleaning FPbase proteins data...")
df_fpbase = pd.read_csv(os.path.join(TRAIN, "fpbase_proteins_basic_gfp.csv"))
# Clean column names
df_fpbase.columns = [c.strip() for c in df_fpbase.columns]
df_fpbase = df_fpbase.dropna(how='all')  # drop fully empty rows
df_fpbase.to_csv(os.path.join(INTEGRATED, "04_fpbase_gfp_variants.csv"), index=False, encoding="utf-8-sig")
print(f"  -> {len(df_fpbase)} rows saved")

# --- 5. Beta amyloid peptide-gfp_Thermo.csv (clean) ---
print("\n[5/8] Cleaning Beta amyloid thermal data...")
df_beta = pd.read_csv(os.path.join(TRAIN, "Beta amyloid peptide-gfp_Thermo.csv"))
# Drop fully empty rows
df_beta = df_beta.dropna(how='all')
df_beta.to_csv(os.path.join(INTEGRATED, "05_beta_amyloid_gfp_thermo.csv"), index=False, encoding="utf-8-sig")
print(f"  -> {len(df_beta)} rows saved")

# --- 6. 4_P42212_gfp_protherm.csv → ProTherm data ---
print("\n[6/8] Copying ProTherm GFP data...")
# Detect encoding
with open(os.path.join(TRAIN, "4_P42212_gfp_protherm.csv"), "rb") as f:
    raw = f.read()
enc = "gbk"  # Chinese characters in author names
df_protherm = pd.read_csv(os.path.join(TRAIN, "4_P42212_gfp_protherm.csv"), encoding=enc)
df_protherm.to_csv(os.path.join(INTEGRATED, "06_protherm_gfp_thermal.csv"), index=False, encoding="utf-8-sig")
print(f"  -> {len(df_protherm)} rows saved")

# Also convert 9temp.tsv to CSV (mixed encoding, use latin-1)
df_9temp = pd.read_csv(os.path.join(TRAIN, "9temp.tsv"), sep="\t", encoding="latin-1")
df_9temp.to_csv(os.path.join(INTEGRATED, "06b_protherm_gfp_thermal_tsv.csv"), index=False, encoding="utf-8-sig")
print(f"  -> {len(df_9temp)} rows (from TSV) saved")

# --- 7. P42212_gfp_aaMutations_Uniport.json → CSV ---
print("\n[7/8] Extracting UniProt mutation data...")
with open(os.path.join(TRAIN, "P42212_gfp_aaMutations_Uniport.json"), "r", encoding="utf-8") as f:
    uniprot = json.load(f)

mutation_data = []
for feat in uniprot.get("features", []):
    loc = feat.get("location", {})
    start = loc.get("start", {}).get("value", "")
    end = loc.get("end", {}).get("value", "")
    orig_seq = feat.get("alternativeSequence", {}).get("originalSequence", "")
    alt_seqs = feat.get("alternativeSequence", {}).get("alternativeSequences", [])
    desc = feat.get("description", "")
    evidences = feat.get("evidences", [])
    pubmed_ids = [e.get("id", "") for e in evidences]

    mutation_data.append({
        "Type": feat.get("type", ""),
        "Position_Start": start,
        "Position_End": end,
        "Original_AA": orig_seq,
        "Alternative_AA": ";".join(alt_seqs),
        "Description": desc,
        "PubMed_IDs": ";".join(pubmed_ids)
    })

df_mut = pd.DataFrame(mutation_data)
df_mut.to_csv(os.path.join(INTEGRATED, "07_uniprot_p42212_mutations.csv"), index=False, encoding="utf-8-sig")
print(f"  -> {len(df_mut)} mutations saved")

# --- 8. submission_template.csv → copy with note ---
print("\n[8/8] Copying submission template...")
df_template = pd.read_csv(os.path.join(TRAIN, "submission_template.csv"))
df_template.to_csv(os.path.join(INTEGRATED, "08_submission_template.csv"), index=False, encoding="utf-8-sig")
print(f"  -> template saved ({len(df_template)} rows)")

print("\n" + "=" * 60)
print("STEP 2: Read comprehensive_GFP_dataset and integrate")
print("=" * 60)

comp_xl = pd.ExcelFile(os.path.join(BASE, "comprehensive_GFP_dataset.xlsx"))
comp_sheets = {}
for sn in comp_xl.sheet_names:
    df = pd.read_excel(comp_xl, sn)
    comp_sheets[sn] = df
    csv_path = os.path.join(INTEGRATED, f"comprehensive_{sn}.csv")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"  -> Sheet '{sn}': {len(df)} rows -> {csv_path}")

print("\n" + "=" * 60)
print("STEP 3: Create integrated master CSV")
print("=" * 60)

# Use comprehensive Brightness_Training_Data as the base (it already integrates brightness)
master = comp_sheets["Brightness_Training_Data"].copy()
master.rename(columns={
    "GFP type": "GFP_type",
    "Data_Source": "Data_Source",
    "Sequence_Length": "Sequence_Length"
}, inplace=True)

# Merge with FPbase optical properties (on variant name matching where possible)
fpbase_ref = comp_sheets["FPbase_GFP_Variants"].copy()
fpbase_ref.rename(columns={
    "Variant_Name": "FPbase_Variant",
    "Ex_lambda_nm": "Ex_max_nm",
    "Em_lambda_nm": "Em_max_nm",
    "Extinction_Coefficient": "Extinction_Coeff",
    "Quantum_Yield": "Quantum_Yield",
    "Brightness_ECxQY": "Brightness_ECxQY",
    "Oligomeric_State": "Oligomeric_State",
    "Key_Mutations": "FPbase_Key_Mutations",
    "Reference": "FPbase_Reference",
    "Relative_Brightness_vs_avGFP": "Relative_Brightness_vs_avGFP"
}, inplace=True)
fpbase_ref.to_csv(os.path.join(INTEGRATED, "comprehensive_FPbase_GFP_Variants_cleaned.csv"),
                  index=False, encoding="utf-8-sig")

# Merge full FPbase raw data (optical properties)
fpbase_full = df_fpbase[["Name", "Ex max (nm)", "Em max (nm)", "Extinction Coefficient",
                          "Quantum Yield", "Brightness", "pKa", "Oligomerization",
                          "Maturation (min)", "Lifetime (ns)", "Molecular Weight (kDa)", "Year"]].copy()
fpbase_full.columns = ["FPbase_Name", "Ex_max_nm", "Em_max_nm", "Extinction_Coeff",
                        "Quantum_Yield", "Brightness_ECxQY", "pKa", "Oligomerization",
                        "Maturation_min", "Lifetime_ns", "MW_kDa", "Year_Reported"]
fpbase_full.to_csv(os.path.join(INTEGRATED, "04_fpbase_cleaned.csv"), index=False, encoding="utf-8-sig")

# Thermal stability merged dataset
thermal = comp_sheets["Thermal_Stability_Data"].copy()
thermal.rename(columns={
    "Protein_Variant": "Protein_Variant",
    "Delta_Tm_C": "Delta_Tm_C",
    "Tm_C": "Tm_C",
    "Delta_Delta_G_kcal_mol": "DDG_kcal_mol",
    "Key_Mutations": "Thermal_Key_Mutations",
    "Experimental_Method": "Thermal_Method",
    "Reference": "Thermal_Reference"
}, inplace=True)
thermal.to_csv(os.path.join(INTEGRATED, "comprehensive_Thermal_Stability_cleaned.csv"),
               index=False, encoding="utf-8-sig")

# UniProt mutations cleaned
uniprot_clean = df_mut[df_mut["Type"] == "Mutagenesis"].copy()
uniprot_clean.to_csv(os.path.join(INTEGRATED, "07_uniprot_mutagenesis_only.csv"), index=False, encoding="utf-8-sig")

# Candidate positions
candidates = comp_sheets["Candidate_Positions"].copy()
candidates.rename(columns={
    "Position_1based": "Position",
    "Region": "Region",
    "Importance": "Importance",
    "Known_Beneficial_Mutations": "Known_Beneficial",
    "Mutations_to_Avoid": "Mutations_to_Avoid",
    "Notes": "Notes"
}, inplace=True)
candidates.to_csv(os.path.join(INTEGRATED, "comprehensive_Candidate_Positions_cleaned.csv"),
                  index=False, encoding="utf-8-sig")

# Literature GFP properties
lit = comp_sheets["Literature_GFP_Properties"].copy()
lit.to_csv(os.path.join(INTEGRATED, "comprehensive_Literature_GFP_Properties_cleaned.csv"),
           index=False, encoding="utf-8-sig")

# Reference sequences
ref_seqs = comp_sheets["Reference_Sequences"].copy()
ref_seqs.to_csv(os.path.join(INTEGRATED, "comprehensive_Reference_Sequences_cleaned.csv"),
                index=False, encoding="utf-8-sig")

# Additional sequences from training data
add_seqs = df_seqs.copy()
add_seqs.columns = ["Protein", "Sequence", "Recommended_PDB"]

# Brightness summary statistics
print("\n--- Brightness Summary ---")
bright = master["Brightness"].dropna()
print(f"  Total variants: {len(master)}")
print(f"  Mean brightness: {bright.mean():.4f}")
print(f"  Median brightness: {bright.median():.4f}")
print(f"  Std brightness: {bright.std():.4f}")
print(f"  Min brightness: {bright.min():.4f}")
print(f"  Max brightness: {bright.max():.4f}")
print(f"  Variants with brightness > 2x WT: {(bright > 2 * 3.72).sum()}")
print(f"  Variants with brightness > 3x WT: {(bright > 3 * 3.72).sum()}")

# Create a comprehensive summary CSV (key integration)
summary_rows = []

# 1. Brightness data summary
summary_rows.append({
    "Category": "Brightness_Data",
    "Metric": "Total_Variants",
    "Value": len(master),
    "Source": "GFP_data.xlsx & Sarkisyan 2016"
})
summary_rows.append({
    "Category": "Brightness_Data",
    "Metric": "Mean_Brightness",
    "Value": round(bright.mean(), 4),
    "Source": "GFP_data.xlsx & Sarkisyan 2016"
})
summary_rows.append({
    "Category": "Brightness_Data",
    "Metric": "Max_Brightness",
    "Value": round(bright.max(), 4),
    "Source": "GFP_data.xlsx & Sarkisyan 2016"
})

# 2. FPbase data summary
summary_rows.append({
    "Category": "FPbase_Data",
    "Metric": "Total_GFP_Variants",
    "Value": len(df_fpbase),
    "Source": "fpbase.org"
})
summary_rows.append({
    "Category": "FPbase_Data",
    "Metric": "Variants_with_Brightness",
    "Value": df_fpbase["Brightness"].dropna().astype(float).count() if "Brightness" in df_fpbase.columns else 0,
    "Source": "fpbase.org"
})

# 3. Thermal stability
summary_rows.append({
    "Category": "Thermal_Stability",
    "Metric": "Total_Measurements",
    "Value": len(thermal),
    "Source": "ProTherm / Literature"
})

# 4. Mutations
summary_rows.append({
    "Category": "Mutations",
    "Metric": "UniProt_Annotated_Mutations",
    "Value": len(df_mut),
    "Source": "UniProt P42212"
})

# 5. Reference sequences
summary_rows.append({
    "Category": "Reference_Sequences",
    "Metric": "Total_Sequences",
    "Value": len(ref_seqs) + len(add_seqs),
    "Source": "Comprehensive + Training Data"
})

# 6. Candidate positions
summary_rows.append({
    "Category": "Candidate_Positions",
    "Metric": "Total_Positions",
    "Value": len(candidates),
    "Source": "Expert Curation"
})

df_summary = pd.DataFrame(summary_rows)
df_summary.to_csv(os.path.join(INTEGRATED, "00_data_summary.csv"), index=False, encoding="utf-8-sig")

print("\n" + "=" * 60)
print("STEP 4: Generate final consolidated CSV files")
print("=" * 60)

# Final integrated dataset: combine all variant-level data
# Main variant-property table
variant_table = master.copy()
variant_table.to_csv(os.path.join(INTEGRATED, "INTEGRATED_MASTER_variants.csv"), index=False, encoding="utf-8-sig")
print(f"  INTEGRATED_MASTER_variants.csv: {len(variant_table)} rows")

# FPbase full data
fpbase_full.to_csv(os.path.join(INTEGRATED, "INTEGRATED_FPbase_optical_properties.csv"), index=False, encoding="utf-8-sig")
print(f"  INTEGRATED_FPbase_optical_properties.csv: {len(fpbase_full)} rows")

# Thermal stability
thermal.to_csv(os.path.join(INTEGRATED, "INTEGRATED_thermal_stability.csv"), index=False, encoding="utf-8-sig")
print(f"  INTEGRATED_thermal_stability.csv: {len(thermal)} rows")

# All reference sequences combined
all_ref_seqs = pd.concat([
    ref_seqs[["Protein", "Sequence"]],
    add_seqs[["Protein", "Sequence"]]
], ignore_index=True)
all_ref_seqs.to_csv(os.path.join(INTEGRATED, "INTEGRATED_all_reference_sequences.csv"), index=False, encoding="utf-8-sig")
print(f"  INTEGRATED_all_reference_sequences.csv: {len(all_ref_seqs)} rows")

# Mutation knowledge base
mutation_kb = df_mut.copy()
mutation_kb.to_csv(os.path.join(INTEGRATED, "INTEGRATED_mutation_knowledge_base.csv"), index=False, encoding="utf-8-sig")
print(f"  INTEGRATED_mutation_knowledge_base.csv: {len(mutation_kb)} rows")

# Candidate positions
candidates.to_csv(os.path.join(INTEGRATED, "INTEGRATED_candidate_positions.csv"), index=False, encoding="utf-8-sig")
print(f"  INTEGRATED_candidate_positions.csv: {len(candidates)} rows")

# Literature insights
lit.to_csv(os.path.join(INTEGRATED, "INTEGRATED_literature_insights.csv"), index=False, encoding="utf-8-sig")
print(f"  INTEGRATED_literature_insights.csv: {len(lit)} rows")

# Create the FULL INTEGRATION single CSV with multiple sections
# Use a multi-section format with clear section headers
with open(os.path.join(OUTPUT, "consolidated_GFP_dataset.csv"), "w", encoding="utf-8-sig") as f:
    f.write("# ========================================\n")
    f.write("# CONSOLIDATED GFP PROTEIN DESIGN DATASET\n")
    f.write("# ========================================\n")
    f.write("# Section: DATA_SUMMARY\n")
    f.write("# ========================================\n")
    df_summary.to_csv(f, index=False)
    f.write("\n")

    f.write("# ========================================\n")
    f.write("# Section: REFERENCE_SEQUENCES\n")
    f.write("# ========================================\n")
    all_ref_seqs.to_csv(f, index=False)
    f.write("\n")

    f.write("# ========================================\n")
    f.write("# Section: BRIGHTNESS_VARIANTS\n")
    f.write("# Columns: GFP_type, aaMutations, Brightness, Data_Source, Sequence_Length\n")
    f.write("# ========================================\n")
    variant_table.to_csv(f, index=False)
    f.write("\n")

    f.write("# ========================================\n")
    f.write("# Section: FPBASE_OPTICAL_PROPERTIES\n")
    f.write("# ========================================\n")
    fpbase_full.to_csv(f, index=False)
    f.write("\n")

    f.write("# ========================================\n")
    f.write("# Section: THERMAL_STABILITY\n")
    f.write("# ========================================\n")
    thermal.to_csv(f, index=False)
    f.write("\n")

    f.write("# ========================================\n")
    f.write("# Section: MUTATION_KNOWLEDGE_BASE\n")
    f.write("# ========================================\n")
    mutation_kb.to_csv(f, index=False)
    f.write("\n")

    f.write("# ========================================\n")
    f.write("# Section: CANDIDATE_POSITIONS\n")
    f.write("# ========================================\n")
    candidates.to_csv(f, index=False)
    f.write("\n")

    f.write("# ========================================\n")
    f.write("# Section: LITERATURE_INSIGHTS\n")
    f.write("# ========================================\n")
    lit.to_csv(f, index=False)

print(f"\n  FINAL: consolidated_GFP_dataset.csv generated!")
print(f"\n  All individual CSV files in: {INTEGRATED}")

# Print summary for analysis
print("\n" + "=" * 60)
print("DATA INTEGRATION COMPLETE - SUMMARY STATISTICS")
print("=" * 60)
print(f"""
Files Converted: 10
Total Reference Sequences: {len(all_ref_seqs)}
Total Brightness Variants: {len(variant_table)}
Total FPbase GFP Variants: {len(fpbase_full)}
Total Thermal Measurements: {len(thermal)}
Total Annotated Mutations: {len(mutation_kb)}
Total Candidate Positions: {len(candidates)}
Total Literature Insights: {len(lit)}
""")

# Save key stats for analysis
stats = {
    "mean_brightness": float(bright.mean()),
    "median_brightness": float(bright.median()),
    "std_brightness": float(bright.std()),
    "max_brightness": float(bright.max()),
    "min_brightness": float(bright.min()),
    "wt_brightness_avGFP": 3.719212132,
    "total_variants": len(master),
    "total_fpbase": len(df_fpbase),
    "total_thermal": len(thermal),
    "total_mutations": len(df_mut),
    "total_candidates": len(candidates),
    "total_reference_seqs": len(all_ref_seqs),
}
with open(os.path.join(OUTPUT, "stats.json"), "w") as f:
    json.dump(stats, f, indent=2)

print("\nSaved stats.json for analysis report generation.")
print("Done!")
