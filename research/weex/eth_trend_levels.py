"""Где у трендовой системы ETH вход: 5-дневный максимум/минимум (30 баров 4ч) и ADX сейчас."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.trend_state import analyze  # noqa: E402

prof = json.loads((ROOT / "state" / "asset_profiles.json").read_text())["assets"].get("ETHUSDT", {})
s = analyze("ETHUSDT", prof)
print(f"ETH {s['px']:,.2f} (закрытие последней 4ч), позиция системы: {s['pos']}, ADX {s['adx']:.1f} (нужно ≥ 20)")
print(f"вход ЛОНГ: закрытие 4ч выше {s['hh']:,.2f} ({(s['hh'] / s['px'] - 1) * 100:+.1f}%)")
print(f"вход ШОРТ: закрытие 4ч ниже {s['ll']:,.2f} ({(s['ll'] / s['px'] - 1) * 100:+.1f}%)")
