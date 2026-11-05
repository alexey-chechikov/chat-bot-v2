"""Копия снимка минуток и фандинга в scratchpad (frozen дописывается каждый час — прогоны только на копии)."""
import shutil
from pathlib import Path

SRC = Path("/Users/alexeychechikov/code/bot7/backtests/frozen")
DST = Path("/private/tmp/claude-501/-Users-alexeychechikov/279942d8-034f-4a29-bc43-ed7d07642e98/scratchpad/cw")
DST.mkdir(parents=True, exist_ok=True)
for n in ("BTCUSDT_1m_2017_2024.csv", "BTCUSDT_1m_2y.csv", "BTCUSDT_funding_full.csv"):
    shutil.copyfile(SRC / n, DST / n)
    print(n, (DST / n).stat().st_size)
