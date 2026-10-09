"""Карточка /weex прямо сейчас (холостой режим) — проверка, что команда собирается."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.weex_grid.loop import command  # noqa: E402

print(command(""))
