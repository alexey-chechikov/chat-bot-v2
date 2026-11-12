"""Ансамбль окон 432 (оператор 12.11 «да»): каждое окно — своя часть 1/N базы и свой эпизод; окно 30 совпадает со
службой; потолок общий; слот, убранный из конфига при открытом эпизоде, — останов."""
from __future__ import annotations

import numpy as np
import pytest

from services.btc_signals import engine as en
from services.sigexec import lines, strategy
from services.sigexec.exchange.base import LONG
from services.sigexec.exchange.sim import SimExchange
from services.sigexec.executor import Executor, Halt, slot_code, validate_config
from services.sigexec.strategy import ENSEMBLE_432, Desired

T = 1_800_000_000


def synth(n=24000, seed=11):
    rng = np.random.default_rng(seed)
    t = (np.arange(n) + 1) * 3600 + 1_600_000_000 // 3600 * 3600
    drift = np.where((np.arange(n) // 3000) % 2 == 0, 0.0004, -0.0002)          # чередование трендов — пробои есть
    c = 30000 * np.exp(np.cumsum(rng.normal(drift, 0.006, n)))
    o = np.r_[c[0], c[:-1]]
    return t, o, np.maximum(o, c) * 1.002, np.minimum(o, c) * 0.998, c


def test_window_30_equals_service_432():
    t, o, h, l, c = synth()
    a, _ = lines.build(t, o, h, l, c, i0_t=int(t[0]))
    e1, p1, _ = en.simulate432(a)
    e2, p2, _ = en.simulate432(a, ch=30)
    assert [(e["kind"], e["t"]) for e in e1] == [(e["kind"], e["t"]) for e in e2] and p1 == p2


def test_evaluate_ensemble_parts():
    t, o, h, l, c = synth()
    r = strategy.evaluate(t, o, h, l, c, slots=("system",) + ENSEMBLE_432)
    assert set(r["desired"]) == {"system", *ENSEMBLE_432}
    a, _ = lines.build(t, o, h, l, c, i0_t=int(t[0]))
    for s in ENSEMBLE_432:
        _, pw, _ = en.simulate432(a, ch=int(s[4:]))
        d = r["desired"][s]
        assert (d is None) == (pw is None)
        if d:
            assert d.main_frac == pytest.approx(1 / 6) and d.entry_t == pw["entry_t"] and d.tag == f"432/{s[4:]}"
    assert sum(1 for s in ENSEMBLE_432 if r["desired"][s]) >= 0


def test_windows_differ_on_history():
    t, o, h, l, c = synth()
    a, _ = lines.build(t, o, h, l, c, i0_t=int(t[0]))
    n = {w: sum(1 for e in en.simulate432(a, ch=w)[0] if e["kind"] == "вход") for w in (20, 30, 45)}
    assert n[20] != n[45] or n[20] != n[30]


def test_slot_names_and_codes():
    assert validate_config({"slots": ["system", *ENSEMBLE_432]})["slots"][1] == "432w20"
    assert slot_code("432w35") == "q35" and slot_code("system") == "s" and slot_code("432") == "q"
    with pytest.raises(Halt):
        validate_config({"slots": ["432x"]})
    with pytest.raises(Halt):
        validate_config({"slots": ["432w20", "432w20"]})


def part(slot, frac):
    return Desired(slot=slot, entry_t=T, side=1, tag=f"432/{slot[4:]}", w=1.0, sig_px=70000.0, main_frac=frac, add_lv=None, add_frac=0.0,
                   add_done=False, target=None, exit_by_t=T + 80 * 3600, exit_text="")


def test_executor_parts_have_own_episodes_and_share_cap(tmp_path):
    ex = SimExchange(price=70000.0)
    ex._t = T + 5
    e = Executor(ex, {"enabled": True, "base_usd": 1200.0, "cap_usd": 700.0, "slots": list(ENSEMBLE_432), "entry": {"kind": "market"},
                      "exit": {"kind": "market"}}, tmp_path / "s.json", tmp_path / "j.jsonl")
    d = {s: part(s, 1 / 6) for s in ENSEMBLE_432}               # 6 × $200 = $1 200 при потолке $700
    for _ in range(3):
        e.step(d)
        ex.tick_clock(5)
    eps = [S["ep"] for S in e.st["slots"].values() if S["ep"]]
    assert 3 <= len(eps) <= 4                                    # потолок пустил 3 части по $200 и остаток
    assert ex.pos[LONG] * 70000 <= 700 * 1.002
    cids = [r["cid"] for r in e.st["orders"].values() if r["role"] == "entry"]
    assert all(c.startswith("b7xq") for c in cids)
    d2 = dict(d)
    d2["432w20"] = None                                          # окно 20 вышло, остальные держат
    for _ in range(3):
        e.step(d2)
        ex.tick_clock(5)
    assert e.st["slots"]["432w20"]["ep"] is None


def test_removed_slot_with_open_episode_halts(tmp_path):
    ex = SimExchange(price=70000.0)
    ex._t = T + 5
    cfg = {"enabled": True, "base_usd": 600.0, "slots": ["432w20", "432w30"], "entry": {"kind": "market"}}
    e = Executor(ex, cfg, tmp_path / "s.json", tmp_path / "j.jsonl")
    e.step({"432w20": part("432w20", 0.5), "432w30": part("432w30", 0.5)})
    e.close()
    with pytest.raises(Halt, match="эпизоды слотов"):
        Executor(ex, dict(cfg, slots=["432w30"]), tmp_path / "s.json", tmp_path / "j.jsonl")
