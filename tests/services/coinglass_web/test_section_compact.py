"""Компактный блок CoinGlass в карточке (оператор 20.10): стрелки зон, сравнение со вчера, без таблицы v1."""
import json
from datetime import datetime, timezone

from services.coinglass_web import outcomes, section


def snap(ts, zs, zl):
    return {"ts": ts, "run_id": ts, "levels_captured": ts, "levels": {
        "price": 81500.0, "near": {"short_pct": 40, "long_pct": 60, "short_pp_24h": -5},
        "zones_short": [{"lo": zs[0], "hi": zs[1], "strength": zs[2], "dist_pct": 2.4}],
        "zones_long": [{"lo": zl[0], "hi": zl[1], "strength": zl[2], "dist_pct": -1.5}]},
        "liquidations": {"long_24h": 32.1e6, "short_24h": 7.1e6, "vs_7d": 0.52}}


def test_compact_section(tmp_path, monkeypatch):
    monkeypatch.setattr(section, "DIR", tmp_path)
    monkeypatch.setattr(outcomes, "update", lambda now: None)
    monkeypatch.setattr(section, "c1_line", lambda: "C1 (годовая проверка, разбор 23.10.2027): утр 2/365")
    rows = [snap("2026-10-19T06:00:10+00:00", (83152, 83456, 434), (79000, 79500, 931)),
            snap("2026-10-20T06:00:10+00:00", (83152, 83792, 679), (79908, 80591, 720))]
    (tmp_path / "snapshots.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    t = section.section(datetime(2026, 10, 20, 6, 5, tzinfo=timezone.utc))
    lines = t.splitlines()
    assert lines[0].startswith("🧲 CoinGlass · BTC, снимок")
    assert lines[1].startswith("↑ шорты 83,152–83,792") and "вчера та же, сила 434" in lines[1]
    assert lines[2].startswith("↓ лонги 79,908–80,591") and "вчера 79,000–79,500 (сила 931)" in lines[2]
    assert "шорты 40% / лонги 60% (-5 п.п. за сутки)" in t and "лонги $32.1M · шорты $7.1M (0.52×" in t
    assert "v1" not in t and len(lines) == 6
