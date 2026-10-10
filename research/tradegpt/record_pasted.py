"""Записать в журнал TradeGPT сигнал, присланный оператором текстом в чат (не пересылкой в бота).
Время сигнала — время записи (приблизительно: оператор вставил его сразу после получения)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.signal_journal.tradegpt import record  # noqa: E402

TEXT = sys.stdin.read() if not sys.argv[1:] else Path(sys.argv[1]).read_text(encoding="utf-8")
print(record(TEXT, time.time()))
