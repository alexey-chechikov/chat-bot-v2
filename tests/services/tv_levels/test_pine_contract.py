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
    """25.10 (аудит GPT 481385e A5): ближайший — по |p − close|, а не max/min (вход выше цены после её падения сквозь
    уровень делал «ближайшим» дальний). Контрпример GPT: входы 99/101/90 при цене 100.4 → 101, а не max=101 случайно;
    при 99/90 и цене 95 → 99 (max), при 99/90 и цене 92 → 90 (max дал бы 99)."""
    body = re.search(r"^f_nearest\(arr\) =>\n((?:    .*\n)+)", SRC, re.M)
    assert body and "math.abs(v - close) < math.abs(best - close)" in body.group(1)
    assert "eNear = f_nearest(ent)" in SRC and "tNear = f_nearest(tps)" in SRC
    assert re.search(r"label\.new\(bar_index \+ 2, eNear, tag \+ \"входы сеток WEEX", SRC)
    assert re.search(r"label\.new\(bar_index \+ 2, tNear, tag \+ \"тейки сеток WEEX", SRC)
    assert "array.max(ent)" not in SRC and "array.min(tps)" not in SRC


def test_stale_bot_levels_marked():
    """25.10 (аудит GPT A5): уровни бота старше staleH — серым и с пометкой «снимок N ч назад»."""
    assert re.search(r'^staleH\s*=\s*input\.float\(12\.0', SRC, re.M)
    assert "syncT  = na(vOk) ? u : vOk" in SRC                     # возраст — от сверки с биржей, не от сборки строки
    assert "unk    = not na(vOk) and vOk <= 0" in SRC
    assert "stale  = unk or (not na(ageNow) and ageNow > staleH)" in SRC
    assert 'tag    = unk ? "сверка неизвестна · " : stale ? "снимок "' in SRC
    for name in ("cEnt", "cTp", "cAvg"):
        assert _assign(f"    {name}").lstrip().startswith("stale ? color.new(color.gray"), name
    assert "partial or stale ? color.orange" in SRC and "ageH > 12" not in SRC


def test_coinglass_zones_off_by_default_and_labelled_atr_only():
    """25.10 (аудит GPT): шанс у зоны — частота касания по расстоянию/ATR, сила CoinGlass в нём не участвует; зоны —
    только по галочке «исследование», подпись говорит это прямо."""
    assert re.search(r'^showCG\s*=\s*input\.bool\(false,', SRC, re.M)
    assert re.search(r"^    if showCG and not expired", SRC, re.M)
    assert "% по ATR от утра, сила зоны не учтена" in SRC and '" · шанс "' not in SRC


def test_parser_knows_all_tokens_of_bot_line():
    for pre in "uvgxkwzetans":
        assert re.search(rf'pre == "{pre}"', SRC), pre
