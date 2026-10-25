"""25.10 (аудит GPT 481385e, R1): копии петли сетки в research/weex обязаны совпадать с базовой (density_compare,
сверенной с regime_grid до цента). Путь GPT: цены 100 → 80 → 80 → 90, режим ЛОНГ → вне → вне → ЛОНГ, шаг/цель 1%,
qty 1, потолок 10 000: база 0; копии без сброса опорной цены при пустой книге давали −30.16 (покупки 99, 98.01, …
от уровня прошлого режима)."""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def mods(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pytest", "BTCUSDT"])
    # строго по файлу своего checkout: сами модули дописывают в sys.path путь основного репо, и импорт по имени на
    # проверке старого коммита брал уже исправленные копии (тест ложно проходил)
    here = Path(__file__).resolve().parents[2] / "research" / "weex"
    out = {}
    for n in ("density_compare", "drop_stop", "exhaust_stop", "cap_extend", "short_mirror"):
        spec = importlib.util.spec_from_file_location(f"rw_parity_{n}", here / f"{n}.py")
        out[n] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(out[n])
        assert Path(out[n].__file__).resolve().parent == here
    return out


def synthetic():
    ts = np.array([0, 60, 120, 180], dtype=np.int64)
    p = np.array([100.0, 80.0, 80.0, 90.0])
    reg = np.array([True, False, False, True])
    pts = np.c_[p, p, p, p]
    return (ts, p, p, p, p, reg), pts


def test_copies_match_base_on_regime_gap(mods):
    data, pts = synthetic()
    for m in mods.values():
        m.DATA, m.PTS, m.FUND = data, pts.tolist(), {}
    mods["exhaust_stop"].ER = (None, [0.0] * 4)
    mods["cap_extend"].EXTRA = ([80.0] * 4, [100.0] * 4)
    base = float(mods["density_compare"].curve((1.0, 1.0, 1.0, 10000.0, 0, False))[4][-1])
    assert base == pytest.approx(0.0, abs=1e-9)
    mods["drop_stop"].GRIDS["T"] = (1.0, 1.0, 1.0, 10000.0, 1000)
    mods["exhaust_stop"].GRIDS["T"] = (1.0, 1.0, 1.0, 10000.0, 1000)
    mods["cap_extend"].GRIDS["T"] = (1.0, 1.0, 1.0, 10000.0)
    mods["short_mirror"].GRIDS["T"] = (1.0, 1.0, 1.0, 10000.0)
    got = {"drop_stop": mods["drop_stop"].run(("T", 0.0, 0, "none"))[4],
           "exhaust_stop": mods["exhaust_stop"].run(("T", None, "none"))[3],
           "cap_extend": mods["cap_extend"].run(("T", "база"))[2],
           "short_mirror": float(mods["short_mirror"].curve(("T", 1, "above"))[3][-1])}
    for name, eq in got.items():
        assert eq == pytest.approx(base, abs=1e-4), f"{name}: {eq} вместо {base}"
