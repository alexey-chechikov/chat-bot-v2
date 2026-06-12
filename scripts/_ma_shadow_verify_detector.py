"""Сверка live-детектора assess_latest со скользящим окном по историческим 4ч —
должен находить те же кроссы, что верифицированный движок (79 базовых / 44 H5)."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path("/Users/alexeychechikov/code/bot7")
sys.path.insert(0, str(ROOT))
from services.ma_cross_shadow.signal import assess_latest

parts = [pd.read_csv(ROOT / "state" / f"pattern_memory_BTCUSDT_1h_{y}.csv",
                     usecols=["open_time", "open", "high", "low", "close"])
         for y in (2024, 2025, 2026)]
df = pd.concat(parts)
df["open_time"] = pd.to_datetime(df["open_time"])
df = df.set_index("open_time").sort_index()
o = df.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index()
H, L, C = o["high"].tolist(), o["low"].tolist(), o["close"].tolist()

crosses = passed = 0
for i in range(215, len(C)):
    s = assess_latest(H[:i + 1], L[:i + 1], C[:i + 1])
    if s:
        crosses += 1
        passed += int(s["passed"])
print(f"детектор нашёл кроссов: {crosses}, прошли H5: {passed}")
print("(верифиц. движок на тех же данных: 79 базовых / 44 после H5)")
