# -*- coding: utf-8 -*-
"""FoldX 进度监视器 — 每10秒刷新，几乎不占CPU"""
import os, sys, time, pandas as pd

CSV = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                    "运行结果", "strategy_A_foldx_results.csv")
TOTAL = 3499
SKIP_EST = 468  # 超出PDB范围的固定跳过数
ACTUAL = TOTAL - SKIP_EST

print("FoldX 实时进度 (Ctrl+C 退出)")
print("=" * 55)

last_count = 0
t0 = time.time()

while True:
    if os.path.exists(CSV):
        try:
            df = pd.read_csv(CSV)
            done = len(df)
            active = done - SKIP_EST
            pct = 100 * active / ACTUAL

            now = time.time()
            elapsed = now - t0

            if last_count > 0 and elapsed > 30:
                rate = (active - last_count) / (elapsed / 60)
                eta = (ACTUAL - active) / max(rate, 0.01)
                bar_len = 30
                filled = int(bar_len * active / ACTUAL)
                bar = "█" * filled + "░" * (bar_len - filled)

                sys.stdout.write(
                    f"\r{bar} {active}/{ACTUAL} ({pct:5.1f}%) | "
                    f"{rate:5.1f}条/min | ETA {eta:5.0f}min"
                )
                sys.stdout.flush()
            else:
                sys.stdout.write(f"\r   启动中... {active}/{ACTUAL}")
                sys.stdout.flush()
                if active > 5:
                    last_count = active
                    t0 = now  # reset timer after startup

            time.sleep(10)
        except Exception as e:
            sys.stdout.write(f"\r读取中... ({e})")
            sys.stdout.flush()
            time.sleep(5)
    else:
        sys.stdout.write(f"\r等待CSV文件...")
        sys.stdout.flush()
        time.sleep(5)
