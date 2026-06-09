"""Тесты утренней карточки на РЕАЛЬНЫХ форматах данных трекера/сканера.

CSV-строки взяты из живых ginarea_live/snapshots.csv и params.csv (2026-06-09):
пустые поля, эмодзи в именах, schema_version=3, raw_params_json с кавычками.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from services.morning_brief import tracker_reader as tr
from services.morning_brief import regime as rg
from services.morning_brief.card import build_card

# реальные строки snapshots.csv (хвост 2026-06-09, T2/LONG-D добавлены по той же схеме)
SNAP_HEADER = ",".join(tr.SNAPSHOTS_HEADERS)
SNAP_ROWS_REAL = """\
2026-06-09T21:01:58+00:00,6287583200,🐉SHORT-T2🐉,,2,0,500.0,500.0,100,,80,,0,,0,100000.0,25000.0,190631.8,3
2026-06-09T21:01:58+00:00,5871471592,🐉хедж лонг на шорте-T1🐉   GIN_c,,12,0.637,351.04590999999954,-2048.6231544420007,644,,320,,214,,74543.36172684455,345363.93328999996,24327.338759,190631.8,3
2026-06-09T22:00:58+00:00,5871471592,🐉хедж лонг на шорте-T1🐉   GIN_c,,12,0.637,351.04590999999954,-2048.6231544420007,644,,320,,214,,74543.36172684455,345363.93328999996,24327.338759,190631.8,3
2026-06-09T22:00:58+00:00,6287583200,🐉SHORT-T2🐉,,2,0,612.5,612.5,120,,95,,0,,0,120000.0,25000.0,190631.8,3
2026-06-09T22:00:58+00:00,5086761417,🐉ЭФИР ШОРТ 1.4%,,2,0,47.2700120001,-150.5,222,,182,,0,,0,41706.2526,26587.283187,0,3
2026-06-09T22:00:58+00:00,4549046435,🐉SHORT-T1🐉   GIN_c_c,,0,0,0,0,0,,0,,0,,0,0,,190631.8,3
2026-06-09T22:00:58+00:00,5826914272,MegaHard_100_2026-06-04_10:54:18,,2,0,95.0,95.0,30,,25,,0,,0,5000.0,1000.0,0,3
"""

# реальная строка params.csv (SHORT-T2, raw json сокращён до валидного)
PARAMS_HEADER = ",".join(tr.PARAMS_HEADERS)
PARAMS_ROWS_REAL = """\
2026-06-09T20:45:51+00:00,6287583200,🐉SHORT-T2🐉,,,2,0.05,,220,65800,,0.018,0.006,0.02,0.34,10,175,0,True,False,"{""border"": {""bottom"": null, ""top"": 65800}}",3
"""

NOW = datetime(2026, 6, 9, 22, 5, 0, tzinfo=timezone.utc)


@pytest.fixture()
def live_dir(tmp_path: Path) -> Path:
    (tmp_path / "snapshots.csv").write_text(SNAP_HEADER + "\n" + SNAP_ROWS_REAL, encoding="utf-8")
    (tmp_path / "params.csv").write_text(PARAMS_HEADER + "\n" + PARAMS_ROWS_REAL, encoding="utf-8")
    return tmp_path


def test_read_snapshots_latest_day0_and_types(live_dir: Path):
    res = tr.read_snapshots(path=live_dir / "snapshots.csv", now=NOW)
    bots = res["bots"]
    t2 = bots["6287583200"]
    assert t2["latest"]["profit"] == pytest.approx(612.5)
    assert t2["latest"]["status"] == tr.STATUS_ACTIVE
    # day0 = первый снапшот текущих суток мск (21:01 UTC 09.06 = 00:01 мск 10.06)
    assert t2["day0"]["profit"] == pytest.approx(500.0)
    hedge = bots["5871471592"]["latest"]
    assert hedge["status"] == tr.STATUS_STOPPED
    assert hedge["current_profit"] == pytest.approx(-2048.6231544420007)
    assert hedge["position"] == pytest.approx(0.637)
    # пустой liquidation_price ('' у ЭФИР) → None... здесь 0 → 0.0
    assert res["stale_min"] == pytest.approx(4.03, abs=0.5)


def test_read_params_border(live_dir: Path):
    p = tr.read_params(path=live_dir / "params.csv")
    assert p["6287583200"]["border_top"] == pytest.approx(65800)
    assert p["6287583200"]["border_bottom"] is None
    assert p["6287583200"]["total_tp"] == pytest.approx(175)


def test_close_level():
    assert rg.close_level("short", 63900) == pytest.approx(64539.0)
    assert rg.close_level("long", 63900) == pytest.approx(63261.0)


def _fake_scan() -> dict:
    a = dict(vr=1.5, step=0.6, target=0.7, mult=1.4, ordcnt=20, span=12.0,
             size=8.31, maxsz=41.55, baseoff=1.8, sl=-175, tp=175)
    m = dict(price=42.1, atrp=1.2, rng24=9.1, t7=10.0, t1=2.0, er=0.21)
    return dict(hour_utc=6, tilt="🔴 ПЛОХОЙ час (утро-UTC, направленно — осторожно с новыми)",
                btc=dict(price=63100.0, atrp=0.8, notional=315.0),
                rows=[
                    dict(sym="HYPEUSDT", m=m, a=a, liqrel=0.4, danger=False, thin=False, score=30.0),
                    dict(sym="WLDUSDT", m=dict(m, t7=80.0), a=a, liqrel=0.3, danger=True, thin=False, score=10.0),
                ])


def _data(live_dir: Path) -> dict:
    return {
        "errors": [],
        "now_msk": NOW.astimezone(tr.MSK),
        "regime": dict(px=63100.0, t200=63900.0, above=-1.25, zone="SHORT-зона",
                       atr=0.8, z=0.3, voloff=False),
        "snap": tr.read_snapshots(path=live_dir / "snapshots.csv", now=NOW),
        "params": tr.read_params(path=live_dir / "params.csv"),
        "managed": [
            {"bot_id": "6287583200", "tier": "T2", "alias": "SHORT-T2", "side": "short"},
            {"bot_id": "5154651487", "tier": "LONG-D", "alias": "BTC-LONG-D-хедж", "side": "long"},
        ],
        "scan": _fake_scan(),
    }


def test_build_card_full(live_dir: Path):
    card = build_card(_data(live_dir))
    assert len(card) < 4096
    # core: шорт в SHORT-зоне держим, уровень закрытия = красная +1%
    assert "SHORT-T2 🟢 в зоне" in card
    assert "закрой при 64,539" in card
    # managed без данных трекера — пометка + алерт про протухший список
    assert "BTC-LONG-D-хедж: не виден трекером" in card
    assert "обнови state/short_bots_managed.json" in card
    # стопнутый бот с висящей позицией (хедж лонг, поз 0.637, мешок −2048) виден
    assert "МЕШКИ НА СТОПЕ" in card
    assert "хедж лонг на шорте-T1" in card
    assert "стоп-мешки" in card
    # прочие активные: ЭФИР с мешком −150 → алерт "у SL"
    assert "у SL" in card
    # кандидаты: только ✅ (WLD danger → не попадает)
    assert "HYPEUSDT" in card
    assert "WLDUSDT" not in card
    assert "step 0.6" in card and "орд 20" in card and "TP/SL ±$175" in card
    # риск-футер
    assert "SL±$175/бот" in card
    # плохой час подсвечен
    assert "ПЛОХОЙ час" in card


def test_build_card_voloff_and_degraded(live_dir: Path):
    d = _data(live_dir)
    d["regime"]["voloff"] = True
    d["regime"]["z"] = 3.1
    d["scan"] = None
    d["errors"] = ["альт-сканер упал: timeout"]
    card = build_card(d)
    assert "VOL-OFF" in card
    assert "альт-сканер упал" in card
    assert len(card) < 4096


def test_day_limit_alert(live_dir: Path):
    d = _data(live_dir)
    # подменяем day0 T2 так, чтобы дневной net был −400 (realized −400, мешок без Δ)
    snap = d["snap"]
    snap["bots"]["6287583200"]["day0"]["profit"] = 1012.5
    snap["bots"]["6287583200"]["day0"]["current_profit"] = 612.5
    card = build_card(d)
    assert "СТОП-ДЕНЬ" in card
    assert "дневной лимит пробит" in card
