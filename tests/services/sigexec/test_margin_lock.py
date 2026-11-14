"""Проверка маржи перед увеличением и блокировка счёта по отпечатку ключа (14.11, «Не сделано» ответа на b056816)."""
from __future__ import annotations

import pytest

from services.sigexec import run as rn
from services.sigexec.exchange.base import SHORT, ExchangeError
from services.sigexec.exchange.sim import SimExchange
from services.sigexec.exchange.weex import WeexExchange

from .test_review_ead2ca4 import Expo, d_cs, mk, run

T0 = 1_800_000_000


def test_margin_unknown_waits_entry_not_done(tmp_path):
    ex = SimExchange(price=70000.0)
    ex.margin = ExchangeError("баланс не прочитался")
    e, ex, _ = mk(tmp_path, ex=ex)
    run(e, ex, {"system": d_cs()}, n=3)
    ep = e.st["slots"]["system"]["ep"]
    assert ep is not None and ep["phase"] == "entering" and ex.pos[SHORT] == 0     # вход ждёт, не «сделан» с нулём
    ex.margin = (5000.0, 100.0)
    run(e, ex, {"system": d_cs()}, n=2)
    assert ex.pos[SHORT] == pytest.approx(0.10)


def test_margin_short_cuts_volume(tmp_path):
    ex = SimExchange(price=70000.0)
    ex.margin = (30.0, 100.0)                            # $30 × 100 / 1.5 = $2 000 → 0.0285 BTC
    e, ex, _ = mk(tmp_path, ex=ex)
    run(e, ex, {"system": d_cs()}, n=1)
    assert ex.pos[SHORT] == pytest.approx(0.0285, abs=1e-4)


def test_margin_none_means_no_check(tmp_path):
    e, ex, _ = mk(tmp_path)
    run(e, ex, {"system": d_cs()}, n=1)
    assert ex.pos[SHORT] == pytest.approx(0.10)


class FakeC:
    def __init__(self, bal, cfg):
        self.bal, self.cfg = bal, cfg

    def futures_balance(self):
        return self.bal

    def get(self, base, path, params):
        return self.cfg


def test_weex_margin_free_reads_cross_only():
    good = WeexExchange(FakeC([{"asset": "USDT", "availableBalance": "857.7"}],
                              [{"symbol": "BTCUSDT", "marginType": "CROSSED", "crossLeverage": "100"}]))
    assert good.margin_free("BTCUSDT") == (857.7, 100.0)
    for bal, cfg in (([{"asset": "USDT"}], [{"marginType": "CROSSED", "crossLeverage": "100"}]),
                     ([{"asset": "USDT", "availableBalance": "1"}], [{"marginType": "ISOLATED", "crossLeverage": "100"}]),
                     ({}, []), ([{"asset": "USDT", "availableBalance": "-5"}], [{"marginType": "CROSSED", "crossLeverage": "100"}])):
        with pytest.raises(ExchangeError):
            WeexExchange(FakeC(bal, cfg)).margin_free("BTCUSDT")


def test_account_lock_by_key_not_by_label(tmp_path):
    a = rn.account_lock("KEY-1", "weex", "live", "BTCUSDT", "hedge", lock_dir=tmp_path)
    with pytest.raises(rn.Halt):
        rn.account_lock("KEY-1", "weex", "live", "BTCUSDT", "hedge", lock_dir=tmp_path)   # другое имя учёта — тот же ключ
    b = rn.account_lock("KEY-1", "weex", "live", "BTCUSDT", "base", lock_dir=tmp_path)    # лонги и страховка — разные роли
    c = rn.account_lock("KEY-2", "weex", "live", "BTCUSDT", "hedge", lock_dir=tmp_path)
    assert a and b and c and rn.account_lock(None, "weex", "live", "BTCUSDT", "hedge", lock_dir=tmp_path) is None
    assert not any("KEY" in p.name for p in tmp_path.iterdir())                           # ключ в имени не пишется
    for fd in (a, b, c):
        fd.close()
