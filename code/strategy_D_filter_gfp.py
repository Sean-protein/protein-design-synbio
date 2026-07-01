"""过滤 GFP 序列：长度 200-300，无歧义字符"""
from Bio import SeqIO

recs = list(SeqIO.parse("/data2/fenghaohui/gfp_strategy_D/data/gfp_uniprot.fasta", "fasta"))
good = [r for r in recs if 200 <= len(str(r.seq)) <= 300]

with open("/data2/fenghaohui/gfp_strategy_D/data/gfp_filtered.fasta", "w") as f:
    for r in good:
        f.write(f">{r.id[:40]}\n{str(r.seq)}\n")

print(f"Total:{len(recs)}  Filtered:{len(good)}  Done")
