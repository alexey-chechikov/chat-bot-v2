"""Контракт индикатора docs/tv_pine_scripts/bot7_regime_grids.pine (Pine здесь не исполняется — проверяется исходник).
Разбор GPT к a25c763: при справочной SMA/других дневках алерты и метки не должны выдавать себя за режим ботов;
подпись входов — на ближайшем (видимом) входе."""
from __future__ import annotations

import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[3] / "docs" / "tv_pine_scripts" / "bot7_regime_grids.pine").read_text(
    encoding="utf-8")


def _assign(name: str) -> str:
    m = re.search(rf"^{name}\s*=\s*(.+)$", SRC, re.M)
    assert m, name
    return m.group(1)


def test_as_bot_means_bot_rule():
    assert re.sub(r"\s+", " ", _assign("asBot")).startswith('isBot and srcMode == "авто" and smaLen == 100')


def test_alerts_markers_and_background_gated_by_as_bot():
    for name in ("near", "flipOn", "flipOff"):
        assert _assign(name).startswith("asBot and"), name
    assert re.search(r"^bgcolor\(showBg and asBot and", SRC, re.M)
    conds = re.findall(r"^alertcondition\(([^,]+),", SRC, re.M)
    assert conds == ["near", "flipOn or flipOff"]                   # других условий алертов нет
    assert re.findall(r"^plotshape\((\w+),", SRC, re.M) == ["flipOn", "flipOff"]


def test_entry_label_on_nearest_entry():
    assert "eTop = array.max(ent)" in SRC
    assert re.search(r"label\.new\(bar_index \+ 2, eTop, \"входы сеток", SRC)
    assert not re.search(r"label\.new\(bar_index \+ 2, array\.min\(ent\)", SRC)


def test_parser_knows_all_tokens_of_bot_line():
    for pre in "ugxkwzetans":
        assert re.search(rf'pre == "{pre}"', SRC), pre
