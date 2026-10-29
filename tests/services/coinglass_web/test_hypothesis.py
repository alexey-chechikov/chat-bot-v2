"""Рабочая гипотеза hy-1 — критерии приёмки GPT a7d799b §5.3: объясняет смену вывода; не знает будущего; различает
цену сейчас и закрытый час; не превращает пропуск ликвидаций в ноль; различает касание и закрепление; не обещает
тейк, доход и вероятность; OI стороны инициатора не приписывает."""
from datetime import timedelta

import numpy as np
import pandas as pd

from services.coinglass_web import hypothesis

T0 = pd.Timestamp("2026-10-28 00:00", tz="UTC")
BANNED = ("обязательно", "гарантир", "прибыл", "доход", "вероятност", "тейк исполн")


def _df(hours=30, liq=True, now_px=81500.0):
    idx = pd.date_range(T0, periods=hours, freq="1h")
    df = pd.DataFrame({"px_close": np.linspace(80000, 81400, hours)}, index=idx)
    df["liq_all_long"] = 1e5 if liq else np.nan
    df["liq_all_short"] = -4e5 if liq else np.nan
    df.loc[idx[-1], "px_close"] = now_px                       # последний ряд — незакрытый час
    return df


def _rec(state="UP_CONFIRMED", bar=None, d6=0.05, thr=0.04, mv6=600.0, tags=()):
    bar = bar or (T0 + pd.Timedelta(hours=28))
    return {"bar": bar.isoformat(), "state": {"price": state, "flow": state}, "tags": list(tags),
            "move": {"dir": 1, "extreme": 81800.0, "support": 81079.3} if "CONFIRMED" in state or state == "STALL_WARNING"
            else None,
            "box": {"L": 2281.0, "H": 2383.0, "kind": "flat", "width_pct": 4.4} if state.startswith("RANGE") else None,
            "pend": None, "cool_until": None,
            "f": {"close": 81400.0, "atr": 300.0, "er": 0.4, "d6": d6, "d6_thr": thr, "mv6": mv6, "oi6": 0.5}}


def _now():
    return (T0 + pd.Timedelta(hours=29, minutes=20)).to_pydatetime()


def _text(h):
    return " ".join([h["conclusion"], *h["why"], *h["against"], h.get("confirm") or "", h.get("cancel") or ""]).lower()


def test_up_hypothesis_has_conclusion_reasons_and_closed_hour_conditions():
    h = hypothesis.build(_rec(), "BTCUSDT", _df(), _now())
    assert h["conclusion"].startswith("Рабочая гипотеза — сохранение движения вверх")
    assert "закрытие часа выше 81 800" in h["confirm"] and "касание не считается" in h["confirm"]
    assert "два закрытых часа подряд ниже 81 079" in h["cancel"]
    assert any("сейчас 81 500 (час не закрыт)" in w for w in h["why"])     # цена сейчас ≠ закрытие часа
    assert not any(b in _text(h) for b in BANNED)
    assert "oi" not in _text(h)                                           # OI не тянем в вывод о стороне


def test_missing_liquidations_stay_unknown_not_zero():
    h = hypothesis.build(_rec(), "BTCUSDT", _df(liq=False), _now())
    assert any("ликвидации: есть 0 из 24 ч" in a for a in h["against"])
    assert not any("ликвидации шортов" in w or "ликвидации лонгов" in w for w in h["why"])


def test_no_future_bars_used():
    df = _df()
    fut = df.copy()
    extra = pd.DataFrame({"px_close": [99999.0], "liq_all_long": [9e9], "liq_all_short": [-9e9]},
                         index=[df.index[-1] + timedelta(hours=1)])
    fut = pd.concat([fut, extra])
    a = hypothesis.build(_rec(), "BTCUSDT", df, _now())
    b = hypothesis.build(_rec(), "BTCUSDT", fut, _now())
    assert a == b


def test_change_since_last_shown_is_explained():
    prev = {"code": "RANGE", "shown_warsaw": "29.10 08:00", "levels": {"H": 81000.0, "L": 79000.0}}
    h = hypothesis.build(_rec(), "BTCUSDT", _df(), _now(), prev)
    assert h["change"].startswith("было: флет (29.10 08:00) → стало: рост подтверждён")
    same = {"code": "UP_CONFIRMED", "shown_warsaw": "29.10 08:00", "levels": {"support": 80900.0, "extreme": 81800.0}}
    h2 = hypothesis.build(_rec(), "BTCUSDT", _df(), _now(), same)
    assert "опора 80 900 → 81 079" in h2["change"]


def test_flow_against_move_goes_to_against_and_weak_flow_needs_price():
    h = hypothesis.build(_rec(d6=-0.08, thr=0.04, mv6=-50.0), "BTCUSDT", _df(), _now())
    assert "поток уже против движения" in h["conclusion"] and any("сильные продажи" in a for a in h["against"])
    h2 = hypothesis.build(_rec(d6=0.01, thr=0.04), "BTCUSDT", _df(), _now())
    assert "продолжение требует подтверждения ценой" in h2["conclusion"]


def test_range_and_no_data_and_pending_breakout():
    r = _rec(state="RANGE_BUY_PRESSURE")
    r["pend"] = {"side": 1}
    h = hypothesis.build(r, "ETHUSDT", _df(), _now())
    assert "торговля внутри диапазона 2 281–2 383" in h["conclusion"] and "не подтверждена" in h["conclusion"]
    assert any("одно закрытие — ещё не закрепление" in a for a in h["against"])
    nd = hypothesis.build(None, "ETHUSDT", _df(), _now())
    assert nd["conclusion"].startswith("Не могу выбрать сценарий")


def test_price_against_confirmed_move_is_listed_with_distance_to_support():
    r = _rec(d6=0.01, thr=0.04, mv6=-300.0)                     # подтверждён рост, а цена за 6 ч −1.0 ATR
    r["f"]["close"] = 81300.0
    h = hypothesis.build(r, "BTCUSDT", _df(), _now())
    assert any("против движения (−1.0 ATR), до опоры 81 079 — 0.3%" in a for a in h["against"])


def test_stall_says_warning_is_weak():
    h = hypothesis.build(_rec(state="STALL_WARNING"), "BTCUSDT", _df(), _now())
    assert "Предупреждение слабое" in h["conclusion"] and "5 из 63" in h["conclusion"]


def test_shown_log_roundtrip(tmp_path):
    path = tmp_path / "h.jsonl"
    h = hypothesis.build(_rec(), "BTCUSDT", _df(), _now())
    hypothesis.log_shown(h, _now(), path)
    got = hypothesis.last_shown("BTCUSDT", path, before=_now() + timedelta(minutes=1))
    assert got["code"] == "UP_CONFIRMED" and got["levels"]["support"] == 81079.3
    assert hypothesis.last_shown("BTCUSDT", path, before=_now()) is None   # показ «в тот же момент» — ещё не прошлый
