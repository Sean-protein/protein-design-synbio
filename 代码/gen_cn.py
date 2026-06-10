import os, sys, pandas as pd, numpy as np, json
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
import warnings
warnings.filterwarnings("ignore")

BASE = r"C:\Users\fengs\Desktop\蛋白质设计-合成生物学创新赛-Claude"
INTEGRATED = os.path.join(BASE, "output", "integrated_csv")
OUTPUT = os.path.join(BASE, "output")
print(f"Loading from {INTEGRATED}")
