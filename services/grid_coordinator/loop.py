"""Grid Coordinator: индикатор истощения движения для grid-ботов.

Каждые 5 минут проверяет 5 независимых сигналов:

UPSIDE EXHAUSTION (для SHORT-ботов оператора):
  1. RSI(14) 1h >= 75 AND RSI снижается (RSI(t) < RSI(t-2))
  2. MFI(14) 1h >= 75 (Money Flow Index — подтверждает истощение покупателей)
  3. Volume z-score 1h < 0 на новом хайе цены (no volume confirmation)
  4. OI 1h change > +1.0% AND funding > 0.04%/8h (longs over-crowded)
  5. BTC↔ETH 30h Pearson corr >= 0.7 AND ETH RSI >= 70 (sync пик)

DOWNSIDE EXHAUSTION (для LONG-ботов):
  Симметрично: RSI <= 25 + растёт, MFI <= 25, vol_z < 0 на лоу,
  OI rising + funding < -0.04%, BTC↔ETH corr + ETH RSI <= 30.

Если 3+ из 5 совпадают — шлёт TG-карточку:
  «🔝 ВЕРХ ИСТОЩАЕТСЯ — рассмотри закрытие SHORT-сеток (3/5 сигналов)»
  «🔻 НИЗ ИСТОЩАЕТСЯ — рассмотри закрытие LONG-сеток»

Cooldown 30 мин между алертами одного направления.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DERIV_LIVE_PATH = ROOT / "state" / "deriv_live.json"
DEDUP_PATH = ROOT / "state" / "grid_coordinator_dedup.json"
JOURNAL_PATH = ROOT / "state" / "grid_coordinator_fires.jsonl"

POLL_INTERVAL_SEC = 300        # 5 min
COOLDOWN_SEC = 3600             # 60 min между алертами одного направления
# 2026-05-13: было 30min, но 08:00 и 08:30 на 13.05 прислали оба → одно событие
# (3/6 сигналов с теми же значениями). 60min убирает этот класс дубликатов.

# Пороги
RSI_OVERBOUGHT = 65.0           # was 75 — operator pointed to extrema where RSI was 68.5; 65 catches them
RSI_OVERSOLD = 35.0             # was 25 — symmetric
MFI_OVERBOUGHT = 70.0           # was 75 — slight loosening for symmetry
MFI_OVERSOLD = 30.0             # was 25
OI_RISING_PCT = 0.3             # was 1.0 — high-vol; |OI| moves >=0.3% are 81 events / 28d
FUNDING_HIGH_8H = 0.00003       # ≈0.003%/8h — actual 2026 BTC funding rarely above 0.005%
VOL_SPIKE_Z = 1.5               # NEW: capitulation/blow-off requires vol z-score >= 1.5
ETH_CORR_LOOKBACK = 30
ETH_CORR_THRESHOLD = 0.70
ETH_RSI_HIGH = 70.0
ETH_RSI_LOW = 30.0


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_g = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_l = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_g / avg_l.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def _mfi(high: pd.Series, low: pd.Series, close: pd.Series,
         volume: pd.Series, period: int = 14) -> pd.Series:
    typical = (high + low + close) / 3.0
    raw = typical * volume
    delta = typical.diff()
    pos = raw.where(delta > 0, 0.0).rolling(period, min_periods=1).sum()
    neg = raw.where(delta < 0, 0.0).rolling(period, min_periods=1).sum().replace(0, 1e-9)
    return 100 - (100 / (1 + pos / neg))


def _vol_z(volume: pd.Series, period: int = 20) -> pd.Series:
    m = volume.rolling(period, min_periods=1).mean()
    s = volume.rolling(period, min_periods=1).std().replace(0, 1.0)
    return (volume - m) / s


def _read_deriv() -> dict:
    if not DERIV_LIVE_PATH.exists():
        return {}
    try:
        return json.loads(DERIV_LIVE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _load_dedup() -> dict:
    if not DEDUP_PATH.exists():
        return {}
    try:
        return json.loads(DEDUP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_dedup(d: dict) -> None:
    try:
        DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEDUP_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("grid_coordinator.dedup_save_failed")


def _journal(rec: dict) -> None:
    try:
        JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except OSError:
        logger.exception("grid_coordinator.journal_failed")


def evaluate_exhaustion(btc: pd.DataFrame, eth: pd.DataFrame | None,
                       deriv: dict, xrp: pd.DataFrame | None = None) -> dict:
    """Возвращает dict со счётчиками сигналов:
       {'upside_score': 0..6, 'downside_score': 0..6, 'details': {...}}

    2026-05-10: добавлен 6-й сигнал XRP lead (MFI). XRP исторически опережает
    BTC на 1-4ч в exhaustion-фазах (см. detect_short_mfi_multi_ga). XRP MFI
    overbought/oversold добавляется к score.
    """
    if btc is None or len(btc) < 35:
        return {"upside_score": 0, "downside_score": 0, "details": {"reason": "btc_thin"}}

    close = btc["close"].astype(float)
    high = btc["high"].astype(float)
    low = btc["low"].astype(float)
    volume = btc["volume"].astype(float)

    rsi_btc = _rsi(close)
    mfi_btc = _mfi(high, low, close, volume)
    vz = _vol_z(volume)

    rsi_now = float(rsi_btc.iloc[-1])
    rsi_2bar_ago = float(rsi_btc.iloc[-3]) if len(rsi_btc) >= 3 else rsi_now
    mfi_now = float(mfi_btc.iloc[-1])
    vz_now = float(vz.iloc[-1])

    # Цена на новом хайе/лоу за 24h?
    last24h_high = float(high.iloc[-24:].max())
    last24h_low = float(low.iloc[-24:].min())
    close_now = float(close.iloc[-1])
    is_new_high = close_now >= last24h_high * 0.999
    is_new_low = close_now <= last24h_low * 1.001

    btc_deriv = deriv.get("BTCUSDT", {}) if isinstance(deriv, dict) else {}
    oi_change = float(btc_deriv.get("oi_change_1h_pct") or 0)
    funding = float(btc_deriv.get("funding_rate_8h") or 0)

    # ETH
    eth_rsi_now = None
    btc_eth_corr = 0.0
    if eth is not None and len(eth) >= ETH_CORR_LOOKBACK:
        eth_close = eth["close"].astype(float)
        eth_rsi = _rsi(eth_close)
        eth_rsi_now = float(eth_rsi.iloc[-1])
        # Pearson на последних 30 барах
        n = min(len(close), len(eth_close), ETH_CORR_LOOKBACK)
        if n >= 10:
            a = close.iloc[-n:].reset_index(drop=True)
            b = eth_close.iloc[-n:].reset_index(drop=True)
            try:
                btc_eth_corr = float(a.corr(b))
            except Exception:
                btc_eth_corr = 0.0

    # XRP — lead indicator. XRP MFI overbought/oversold suggests BTC will follow.
    xrp_mfi_now = None
    if xrp is not None and len(xrp) >= 20:
        xrp_high = xrp["high"].astype(float)
        xrp_low = xrp["low"].astype(float)
        xrp_close = xrp["close"].astype(float)
        xrp_volume = xrp["volume"].astype(float)
        xrp_mfi = _mfi(xrp_high, xrp_low, xrp_close, xrp_volume)
        xrp_mfi_now = float(xrp_mfi.iloc[-1])

    # UPSIDE EXHAUSTION CHECKS
    up_signals = {}
    up_signals["rsi_high"] = (rsi_now >= RSI_OVERBOUGHT)
    up_signals["mfi_high"] = (mfi_now >= MFI_OVERBOUGHT)
    # 2026-05-10 STRUCTURAL FIX: blow-off top = ВЫСОКИЙ объём на росте, не "no confirm".
    # Capitulation buying flushes longs into the high before reversal.
    up_signals["volume_spike_at_high"] = (vz_now >= VOL_SPIKE_Z and rsi_now >= RSI_OVERBOUGHT)
    # 2026-05-10 STRUCTURAL FIX: на blow-off top OI падает (deleverage) ИЛИ funding высокий.
    # Старая логика "OI растёт + funding высокий" — это профиль open shorts, не exhaustion.
    up_signals["deleverage_or_funding_top"] = (
        oi_change <= -OI_RISING_PCT or funding >= FUNDING_HIGH_8H
    )
    up_signals["eth_sync_high"] = (
        btc_eth_corr >= ETH_CORR_THRESHOLD and eth_rsi_now is not None
        and eth_rsi_now >= ETH_RSI_HIGH
    )
    # XRP lead — 6th signal (2026-05-10)
    up_signals["xrp_mfi_high"] = (xrp_mfi_now is not None and xrp_mfi_now >= MFI_OVERBOUGHT)
    upside_score = sum(1 for v in up_signals.values() if v)

    # DOWNSIDE EXHAUSTION CHECKS
    down_signals = {}
    down_signals["rsi_low"] = (rsi_now <= RSI_OVERSOLD)
    down_signals["mfi_low"] = (mfi_now <= MFI_OVERSOLD)
    # 2026-05-10: capitulation low = high volume spike on the downside.
    down_signals["volume_spike_at_low"] = (vz_now >= VOL_SPIKE_Z and rsi_now <= RSI_OVERSOLD)
    # На капитуляции OI падает (longs закрывают) ИЛИ funding flips negative.
    down_signals["deleverage_or_funding_bottom"] = (
        oi_change <= -OI_RISING_PCT or funding <= -FUNDING_HIGH_8H
    )
    down_signals["eth_sync_low"] = (
        btc_eth_corr >= ETH_CORR_THRESHOLD and eth_rsi_now is not None
        and eth_rsi_now <= ETH_RSI_LOW
    )
    down_signals["xrp_mfi_low"] = (xrp_mfi_now is not None and xrp_mfi_now <= MFI_OVERSOLD)
    downside_score = sum(1 for v in down_signals.values() if v)

    return {
        "upside_score": upside_score,
        "downside_score": downside_score,
        "details": {
            "rsi_btc_now": round(rsi_now, 1),
            "rsi_2bar_ago": round(rsi_2bar_ago, 1),
            "mfi_btc_now": round(mfi_now, 1),
            "vol_z_now": round(vz_now, 2),
            "is_new_24h_high": is_new_high,
            "is_new_24h_low": is_new_low,
            "oi_change_1h_pct": oi_change,
            "funding_rate_8h": funding,
            "eth_rsi_now": round(eth_rsi_now, 1) if eth_rsi_now is not None else None,
            "btc_eth_corr_30h": round(btc_eth_corr, 3),
            "xrp_mfi_now": round(xrp_mfi_now, 1) if xrp_mfi_now is not None else None,
            "btc_close": round(close_now, 1),
            "up_signals": up_signals,
            "down_signals": down_signals,
        },
    }


def _format_card(direction: str, score: int, details: dict) -> str:
    if direction == "up":
        emoji = "🔝"
        title = f"ВЕРХ ИСТОЩАЕТСЯ ({score}/6 сигналов)"
        action = "Рассмотри закрытие SHORT-сеток сейчас и переоткрытие на откате."
        sigs = details.get("up_signals", {})
    else:
        emoji = "🔻"
        title = f"НИЗ ИСТОЩАЕТСЯ ({score}/6 сигналов)"
        action = "Рассмотри закрытие LONG-сеток сейчас и переоткрытие на откате."
        sigs = details.get("down_signals", {})

    triggered = [k for k, v in sigs.items() if v]
    btc_close = details.get("btc_close")
    rsi = details.get("rsi_btc_now")
    mfi = details.get("mfi_btc_now")
    vz = details.get("vol_z_now")
    oi = details.get("oi_change_1h_pct")
    fund = details.get("funding_rate_8h", 0) * 100  # to %
    eth_rsi = details.get("eth_rsi_now")
    xrp_mfi = details.get("xrp_mfi_now")
    corr = details.get("btc_eth_corr_30h")

    return (
        f"{emoji} {title}\n"
        f"\n"
        f"BTC: ${btc_close:,.0f}  RSI={rsi}  MFI={mfi}  vol_z={vz}\n"
        f"OI 1h: {oi:+.2f}%  funding 8h: {fund:+.4f}%\n"
        f"ETH RSI: {eth_rsi}  XRP MFI: {xrp_mfi}  corr={corr}\n"
        f"\n"
        f"Сигналы: {', '.join(triggered) if triggered else 'нет'}\n"
        f"\n"
        f"{action}\n"
        f"Это рекомендация — бот не торгует, решение оператора."
    )


def _check_cooldown(direction: str, dedup: dict, now: datetime) -> bool:
    last = dedup.get(direction)
    if not last:
        return True
    try:
        last_ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
        return (now - last_ts).total_seconds() >= COOLDOWN_SEC
    except (ValueError, AttributeError):
        return True


async def grid_coordinator_loop(stop_event: asyncio.Event, *, send_fn=None,
                                 interval_sec: int = POLL_INTERVAL_SEC) -> None:
    """Async loop. Every 5 min: проверка истощения движения для grid-ботов."""
    if send_fn is None:
        logger.warning("grid_coordinator.no_send_fn — alerts только в журнале")
    logger.info(
        "grid_coordinator.start interval=%ds threshold=3/5 cooldown=%ds",
        interval_sec, COOLDOWN_SEC,
    )

    while not stop_event.is_set():
        try:
            from core.data_loader import load_klines
            btc = load_klines(symbol="BTCUSDT", timeframe="1h", limit=50)
            eth = load_klines(symbol="ETHUSDT", timeframe="1h", limit=50)
            try:
                xrp = load_klines(symbol="XRPUSDT", timeframe="1h", limit=50)
            except Exception:
                xrp = None  # gracefully degrade if XRP fetch fails
            deriv = _read_deriv()
            now = datetime.now(timezone.utc)

            ev = evaluate_exhaustion(btc, eth, deriv, xrp=xrp)
            up = ev["upside_score"]
            down = ev["downside_score"]
            details = ev["details"]

            dedup = _load_dedup()
            fired = False

            # Score-escalation: повторный alert на том же уровне игнорируется
            # на cooldown'е; если score вырос (3→4→5) — alert даже на cooldown.
            # Если score упал ниже threshold — reset last_score.
            for direction, score in (("up", up), ("down", down)):
                last_score = int(dedup.get(f"{direction}_score") or 0)
                if score < 3:
                    if last_score > 0:
                        dedup[f"{direction}_score"] = 0
                    continue
                on_cd = not _check_cooldown(direction, dedup, now)
                if on_cd and score <= last_score:
                    continue
                text = _format_card(direction, score, details)
                logger.info("grid_coordinator.%s_EXHAUSTION score=%d (prev=%d)",
                            direction.upper(), score, last_score)
                if send_fn:
                    try:
                        send_fn(text)
                    except Exception:
                        logger.exception("grid_coordinator.send_failed")
                dedup[direction] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                dedup[f"{direction}_score"] = score
                _journal({"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "direction": direction, "score": score, "details": details})
                # Paper-trade: exhaustion → reversal. up_exhaustion → SHORT, down → LONG.
                # 2026-05-23 paper-audit (_paper_perf_audit.py): grid_coord LONG
                # (down_exhaustion fade) WR 25.9% / −$77 on n=27 across 2 weeks
                # — actively losing edge. Skip paper-emission of LONG side; keep
                # SHORT side recording (n=1, insufficient evidence either way,
                # let data accumulate). Re-enable when ≥20 newer LONG outcomes
                # show WR ≥45% on rolling basis.
                try:
                    trade_side = "SHORT" if direction == "up" else "LONG"
                    if trade_side == "LONG":
                        logger.info(
                            "grid_coordinator.paper_emit_skipped side=LONG "
                            "(disabled per 2026-05-23 audit — WR 26%% bleeder)"
                        )
                    else:
                        from services.paper_signal_tracker.journal import (
                            read_btc_last_price, record_paper_signal,
                        )
                        last_price = read_btc_last_price()
                        if last_price and last_price > 0:
                            record_paper_signal(
                                source="grid_coord", side=trade_side,
                                entry=float(last_price),
                                stop_pct=-0.5, tp_pct=0.75, hold_h=4,
                                context=f"{direction}_exhaustion_score{score}",
                                now=now,
                            )
                except Exception:
                    logger.exception("grid_coordinator.paper_signal_failed")
                fired = True

            if fired:
                _save_dedup(dedup)
            else:
                logger.debug("grid_coordinator.tick up=%d down=%d (no fire)", up, down)

        except Exception:
            logger.exception("grid_coordinator.tick_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass


# 2026-05-10: 15m intraday-flush detector (downside-only).
# Night research showed 15m TF too noisy for upside (PF -6%), but operator's
# missed extrema (21 Apr 19:46, 29 Apr 18:10) were intraday flushes. Run
# 15m grid_coordinator parallel to 1h, but ONLY emit downside score>=4 alerts.
INTRADAY_DEDUP_PATH = ROOT / "state" / "grid_coordinator_intraday_dedup.json"
INTRADAY_INTERVAL_SEC = 60   # check every 1 min on 15m TF
# 2026-05-13: было 15min cooldown — в живом логе оператора было 17 алертов
# 🔻 НИЗ ИСТОЩАЕТСЯ за 6 часов (≈1 каждые 21 мин). Поднял до 30 мин и
# добавил score-escalation: повторный alert только если счётчик ВЫРОС
# (4→5 или 5→6), а не повторяется на одном уровне.
INTRADAY_COOLDOWN_SEC = 1800
INTRADAY_DOWNSIDE_THRESHOLD = 4


def _load_intraday_dedup() -> dict:
    if not INTRADAY_DEDUP_PATH.exists(): return {}
    try:
        return json.loads(INTRADAY_DEDUP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_intraday_dedup(d: dict) -> None:
    try:
        INTRADAY_DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        INTRADAY_DEDUP_PATH.write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass


async def grid_coordinator_intraday_loop(stop_event, *, send_fn=None,
                                          interval_sec: int = INTRADAY_INTERVAL_SEC) -> None:
    """15m TF parallel loop, downside-only (intraday capitulation lows).

    Different cooldown (15m) and threshold (>=4) than the 1h main loop to
    reduce noise while catching fast flushes the 1h misses.
    """
    logger.info(
        "grid_coordinator.intraday.start interval=%ds tf=15m threshold=down>=%d cooldown=%ds",
        interval_sec, INTRADAY_DOWNSIDE_THRESHOLD, INTRADAY_COOLDOWN_SEC,
    )
    while not stop_event.is_set():
        try:
            from core.data_loader import load_klines
            btc_15m = load_klines(symbol="BTCUSDT", timeframe="15m", limit=60)
            eth_15m = load_klines(symbol="ETHUSDT", timeframe="15m", limit=60)
            try:
                xrp_15m = load_klines(symbol="XRPUSDT", timeframe="15m", limit=60)
            except Exception:
                xrp_15m = None
            deriv = _read_deriv()
            now = datetime.now(timezone.utc)

            ev = evaluate_exhaustion(btc_15m, eth_15m, deriv, xrp=xrp_15m)
            down = ev["downside_score"]
            details = ev["details"]

            dedup = _load_intraday_dedup()
            last = dedup.get("down")
            last_score = int(dedup.get("down_score") or 0)
            on_cooldown = False
            if last:
                try:
                    last_ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
                    on_cooldown = (now - last_ts).total_seconds() < INTRADAY_COOLDOWN_SEC
                except (ValueError, AttributeError):
                    pass

            # Score-escalation: на cooldown игнорируем если score не вырос
            # vs прошлого alert. Если down упал ниже threshold — reset last_score.
            if down < INTRADAY_DOWNSIDE_THRESHOLD:
                if last_score > 0:
                    dedup["down_score"] = 0
                    _save_intraday_dedup(dedup)
            should_fire = (down >= INTRADAY_DOWNSIDE_THRESHOLD
                           and (not on_cooldown or down > last_score))

            if should_fire:
                text = "⚡ 15m " + _format_card("down", down, details)
                logger.info("grid_coordinator.intraday.DOWNSIDE_FLUSH score=%d (prev=%d)",
                            down, last_score)
                if send_fn:
                    try:
                        send_fn(text)
                    except Exception:
                        logger.exception("grid_coordinator.intraday.send_failed")
                dedup["down"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                dedup["down_score"] = down
                _save_intraday_dedup(dedup)
                _journal({"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "tf": "15m", "direction": "down", "score": down,
                          "details": details})
        except Exception:
            logger.exception("grid_coordinator.intraday.tick_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass
