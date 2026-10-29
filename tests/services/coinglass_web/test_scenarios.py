"""Теневая система сценариев sc-1 (services/coinglass_web/scenarios.py): машина состояний, признаки без будущего,
теневые действия, журнал решений и исходов, карточка. Без сети."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from services.coinglass_web import scenarios

T0 = pd.Timestamp("2026-10-01 00:00", tz="UTC")
FLAT = [100 + 0.5 * np.sin(i * np.pi / 3) for i in range(120)]   # период 6 ч: ER24 = 0, коробка ≈ 99.52–100.48


def _df(closes, buy=1000.0, sell=1000.0) -> pd.DataFrame:
    idx = pd.date_range(T0, periods=len(closes), freq="1h")
    c = np.array(closes, dtype=float)
    o = np.r_[c[0], c[:-1]]
    df = pd.DataFrame({"px_close": c, "px_open": o, "px_high": np.maximum(o, c) + 0.05,
                       "px_low": np.minimum(o, c) - 0.05}, index=idx)
    df["taker_buy"] = buy
    df["taker_sell"] = -np.asarray(sell, dtype=float) if np.ndim(sell) else -float(sell)
    return df


def _events(recs):
    return [(r["bar"], e["e"]) for r in recs for e in r["events"]]


def _at(recs, i):
    return recs[i]


def test_flat_box_breakout_needs_second_close():
    recs, _m = scenarios.replay(_df(FLAT + [101.0, 101.3]))
    names = [e for _b, e in _events(recs)]
    assert "RANGE_SET" in names
    assert recs[119]["state"]["price"] == "RANGE" and recs[119]["box"]["kind"] == "flat"
    assert recs[120]["state"]["price"] == "RANGE" and recs[120]["pend"]["side"] == 1   # первый час за границей
    assert recs[121]["state"]["price"] == "UP_CONFIRMED"
    assert ("BREAKOUT_CONFIRMED" in [e["e"] for e in recs[121]["events"]])


def test_false_break_keeps_the_same_box():
    recs, _m = scenarios.replay(_df(FLAT + [101.0, 100.2]))
    box_before = recs[119]["box"]["id"]
    assert [e["e"] for e in recs[121]["events"]] == ["FALSE_BREAK"]
    assert recs[121]["state"]["price"] == "RANGE" and recs[121]["box"]["id"] == box_before


def test_structure_break_then_cooldown_then_new_box():
    path = FLAT + [101.0, 101.3, 101.6, 101.9, 101.5, 102.2, 101.2, 101.0] + [101.0] * 6
    recs, _m = scenarios.replay(_df(path))
    i = 120
    assert recs[i + 5]["move"]["support"] > 101.4                  # после отката и нового максимума опора поднялась
    assert recs[i + 6]["state"]["price"] == "UP_CONFIRMED"        # первый час под опорой — только метка
    assert any("за опорой" in t for t in recs[i + 6]["tags"])
    assert recs[i + 7]["state"]["price"] == "STRUCTURE_BROKEN"
    assert recs[i + 8]["state"]["price"] == "COOLDOWN" and recs[i + 9]["state"]["price"] == "COOLDOWN"
    assert recs[i + 10]["state"]["price"] in ("RANGE", "NO_STRUCTURE")
    assert any(e["e"] in ("RANGE_SET", "REF_SET") and e["box"]["why"] == "после паузы" for e in recs[i + 10]["events"])


def test_gap_is_data_unknown_and_resets_pending_breakout():
    path = FLAT + [101.0, np.nan, 101.3]
    recs, _m = scenarios.replay(_df(path))
    assert recs[121]["state"]["price"] == "DATA_UNKNOWN" and recs[121]["pend"] is None
    assert "DATA_GAP" in [e["e"] for e in recs[121]["events"]]
    assert recs[122]["state"]["price"] == "DATA_UNKNOWN"         # окно 25 ч с пропуском — неизвестно, не «рост»


def test_features_have_no_lookahead():
    df = _df(FLAT + [101.0, 101.3, 101.6, 101.9], buy=np.linspace(900, 1500, 124), sell=1000.0)
    f1 = scenarios.features(df)
    df2 = df.copy()
    df2.iloc[110:] = df2.iloc[110:] * 1.5
    f2 = scenarios.features(df2)
    pd.testing.assert_frame_equal(f1.iloc[:110], f2.iloc[:110])


def test_flow_stall_differs_from_price_variant():
    up = [101.0, 101.3] + [101.3 + 0.02 * k for k in range(1, 10)]   # медленный рост: каждый час новый максимум
    n = len(FLAT) + len(up)
    buy = np.full(n, 1000.0)
    buy[118:] = 3000.0                                            # сильные покупки без продвижения
    recs, _m = scenarios.replay(_df(FLAT + up, buy=buy))
    last = recs[-1]
    assert last["state"]["price"] == "UP_CONFIRMED"
    assert last["state"]["flow"] == "STALL_WARNING"
    assert any(e["e"] == "STALL" and e["variant"] == "flow" for r in recs for e in r["events"])


def test_actions_split_entries_residual_and_start():
    path = FLAT + [101.0, 101.3, 101.6, 101.9, 101.5, 102.2, 101.2, 101.0] + [101.0] * 6
    recs, _m = scenarios.replay(_df(path))
    conf, broken, cool = recs[121], recs[127], recs[128]
    assert scenarios.actions(conf, "price", 1)["start"].startswith("кандидат запуска")
    assert scenarios.actions(conf, "price", -1)["entries"] == "запретить набор"
    a_long, a_short = scenarios.actions(broken, "price", 1), scenarios.actions(broken, "price", -1)
    assert a_long["residual"] == "кандидат закрыть остаток" and a_long["entries"] == "запретить набор"
    assert a_short["residual"] == "держать"
    assert scenarios.actions(cool, "price", 1)["entries"] == "запретить набор"
    unknown = dict(conf, state={"price": "DATA_UNKNOWN", "flow": "DATA_UNKNOWN"})
    assert scenarios.actions(unknown, "flow", 1)["residual"] == "держать"   # потеря данных ничего не закрывает


def _mins(df: pd.DataFrame) -> pd.DataFrame:
    """Минуты из часовых закрытий (ступенькой) — для исхода от исполнения в тестах без сети."""
    idx = pd.date_range(df.index[0], df.index[-1] + pd.Timedelta(hours=3), freq="1min")
    px = df["px_close"].reindex(idx, method="ffill")
    return pd.DataFrame({"open": px, "high": px, "low": px, "close": px}, index=idx)


def test_update_writes_one_decision_per_bar_and_outcome_later(tmp_path):
    j, s = tmp_path / "shadow.jsonl", tmp_path / "state.json"
    df = _df(FLAT + [100.0] * 10)
    last = df.index[-1]
    now = (last + pd.Timedelta(hours=1, minutes=10)).to_pydatetime()
    r1 = scenarios.update("BTCUSDT", df, now, journal=j, state_path=s)
    r2 = scenarios.update("BTCUSDT", df, now, journal=j, state_path=s)   # тот же час — нового решения нет
    recs = [json.loads(x) for x in j.read_text().splitlines()]
    dec = [r for r in recs if r["kind"] == "decision"]
    assert r1["decision"] and r2["decision"] is None and len(dec) == 1
    assert dec[0]["forward"] and dec[0]["lag_min"] == 10.0 and dec[0]["bar"] == last.isoformat()
    assert all(r["warmup"] for r in recs if r["kind"] == "event")        # прогрев помечен
    assert set(dec[0]["actions"]) == {"price", "flow"} and set(dec[0]["actions"]["price"]) == {"long", "short"}
    df2 = _df(FLAT + [100.0] * 17)
    later = (df2.index[-1] + pd.Timedelta(hours=1, minutes=5)).to_pydatetime()
    mins = _mins(df2)
    scenarios.update("BTCUSDT", df2, later, journal=j, state_path=s,
                     minute_px=lambda sym, a, b: mins[(mins.index >= a) & (mins.index < b)])
    recs = [json.loads(x) for x in j.read_text().splitlines()]
    outs = [r for r in recs if r["kind"] == "outcome"]
    assert len(outs) == 1 and outs[0]["ref"] == dec[0]["id"] and outs[0]["h"] == "6h"
    assert outs[0]["outcome_v"] == scenarios.OUTCOME_V and outs[0]["execution_at"] == dec[0]["execution_at"]
    assert not [r for r in recs if r["kind"] == "event" and not r["warmup"] and r["e"] == "RANGE_SET"]


def test_card_has_state_facts_limits_and_no_probability():
    path = FLAT + [101.0, 101.3, 101.6]
    df = _df(path)
    recs, _m = scenarios.replay(df, "BTCUSDT")
    now = (df.index[-1] + pd.Timedelta(minutes=70)).to_pydatetime()
    c = scenarios.card(recs[-1], "BTCUSDT", now, variant="price")
    assert c["state"] == "UP_CONFIRMED" and c["age_min"] == 10
    assert len(c["support"]) <= 3 and len(c["contra"]) <= 2
    assert "Опора" in c["next"] and "Вероятность не показываю" in c["note"]
    assert set(c["actions"]) == {"long", "short"}


def test_evaluate_counts_breaks_and_warnings():
    path = FLAT + [101.0, 101.3, 101.6, 101.9, 101.5, 102.2, 101.2, 101.0] + [101.0] * 6
    recs, _m = scenarios.replay(_df(path))
    ev = scenarios.evaluate(recs)
    assert ev["breaks"] == 1 and ev["breakouts"]["confirmed"] >= 1
    assert set(ev["stall_price"]) >= {"warnings", "break_within_24h", "false_pause_1atr", "breaks_warned_24h"}
