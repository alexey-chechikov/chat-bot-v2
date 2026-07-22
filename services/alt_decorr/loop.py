"""Alt decorrelation-divergence detector — 25m & 1h, ETH/XRP.

Operator brief (2026-05-29): trade alts on 25m/1h when they DEcorrelate from BTC,
reusing the existing stack (the validated divergence engine from
multi_asset_confluence: BTC+ETH bull-DIV conf → PF 3.88 / WR 68% on 1h/2y).

Idea: a multi-indicator divergence ON THE ALT is higher quality when the alt is
moving on its OWN (decorrelated from BTC) rather than just dragging behind BTC —
the divergence is then idiosyncratic / alt-specific, not a BTC echo.

This detector:
  • runs the proven divergence engine on the ALT (ETH/XRP) at 25m and 1h,
  • requires the alt to be DECORRELATED from BTC (rolling return-corr < CORR_GATE),
  • bull div → LONG, bear div → SHORT,
  • emits a TG card (gated by the PnL-aware paper_wr_gate) AND records a paper
    trade (source="alt_decorr") so live history judges the edge within days and
    the gate auto-suppresses it if it decays.

25m is resampled from native 5m klines (Binance has no 25m). 1h is native.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEDUP_PATH = ROOT / "state" / "alt_decorr_dedup.json"
JOURNAL_PATH = ROOT / "state" / "alt_decorr_fires.jsonl"

ALTS = ("ETHUSDT", "XRPUSDT")
POLL_INTERVAL_SEC = 300          # 5 min
COOLDOWN_SEC = 3600              # 1h per (alt, tf, side)
CORR_GATE = 0.70                 # alt↔BTC 30-bar return-corr must be BELOW this
CORR_LOOKBACK = 30
RECENT_BARS = 2                  # div confirm bar must be within last N bars
SL_PCT = 1.0
TP_PCT = 2.0                     # RR 2.0 (CROSS_ASSET_TP1_RR)
HOLD_H = 8


def _load_tf(symbol: str, tf: str) -> pd.DataFrame | None:
    """Load klines for tf. 1h native; 25m resampled from 5m."""
    try:
        from core.data_loader import load_klines
        if tf == "1h":
            return load_klines(symbol=symbol, timeframe="1h", limit=200)
        if tf == "25m":
            df5 = load_klines(symbol=symbol, timeframe="5m", limit=1000)
            if df5 is None or df5.empty:
                return None
            d = df5.copy()
            tcol = next((c for c in ("ts", "open_time", "timestamp", "time")
                         if c in d.columns), None)
            if tcol is None:
                return None
            d[tcol] = pd.to_datetime(d[tcol], utc=True, errors="coerce")
            out = (d.dropna(subset=[tcol]).set_index(tcol).resample("25min").agg({
                "open": "first", "high": "max", "low": "min",
                "close": "last", "volume": "sum"}).dropna().reset_index())
            return out
    except Exception:
        logger.exception("alt_decorr.load_failed symbol=%s tf=%s", symbol, tf)
    return None


def _detect_bearish_div_bars(df: pd.DataFrame) -> list[int]:
    """Bearish divergence confirmation-bar indices (conf>=MIN_CONFLUENCE)."""
    from services.setup_detector.multi_divergence import (
        DIV_WINDOW_BARS, INDICATOR_PIVOT_TOLERANCE, MIN_CONFLUENCE, PIVOT_LOOKBACK,
        _agreeing_indicators_for_bearish, _build_indicators, _find_pivots,
    )
    if df is None or len(df) < 50:
        return []
    indicators = _build_indicators(df)
    pivots_by_ind = {n: _find_pivots(s) for n, s in indicators.items()}
    price_pivots = _find_pivots(df["high"]).highs
    out: list[int] = []
    for i in range(1, len(price_pivots)):
        cur, prev = price_pivots[i], price_pivots[i - 1]
        if cur - prev > DIV_WINDOW_BARS:
            continue
        if df["high"].iloc[cur] <= df["high"].iloc[prev]:
            continue
        agreeing = _agreeing_indicators_for_bearish(
            indicators, pivots_by_ind, prev, cur, INDICATOR_PIVOT_TOLERANCE)
        if len(agreeing) < MIN_CONFLUENCE:
            continue
        conf = cur + PIVOT_LOOKBACK
        if conf < len(df):
            out.append(conf)
    return out


def _corr_alt_btc(alt: pd.DataFrame, btc: pd.DataFrame) -> float:
    n = min(len(alt), len(btc), CORR_LOOKBACK + 1)
    if n < 12:
        return 1.0
    a = np.log(alt["close"].astype(float).to_numpy()[-n:])
    b = np.log(btc["close"].astype(float).to_numpy()[-n:])
    ar, br = np.diff(a), np.diff(b)
    if ar.std() == 0 or br.std() == 0:
        return 1.0
    return float(np.corrcoef(ar, br)[0, 1])


def evaluate_alt_decorr(alt_df: pd.DataFrame, btc_df: pd.DataFrame) -> dict:
    """Return signal dict for the latest bar, or {'fire': False}."""
    from services.setup_detector.multi_asset_confluence import _detect_bullish_div_bars
    if alt_df is None or btc_df is None or len(alt_df) < 50:
        return {"fire": False, "reason": "thin"}
    corr = _corr_alt_btc(alt_df, btc_df)
    last = len(alt_df) - 1
    bull = _detect_bullish_div_bars(alt_df)
    bear = _detect_bearish_div_bars(alt_df)
    recent_bull = any(last - b <= RECENT_BARS for b in bull)
    recent_bear = any(last - b <= RECENT_BARS for b in bear)
    decorrelated = corr < CORR_GATE
    side = None
    if decorrelated and recent_bull and not recent_bear:
        side = "LONG"
    elif decorrelated and recent_bear and not recent_bull:
        side = "SHORT"
    return {
        "fire": side is not None, "side": side, "corr": round(corr, 3),
        "decorrelated": decorrelated,
        "close": float(alt_df["close"].iloc[-1]),
        "bull": recent_bull, "bear": recent_bear,
    }


def _format_card(symbol: str, tf: str, ev: dict) -> str:
    arrow = "🟢 LONG" if ev["side"] == "LONG" else "🔴 SHORT"
    divkind = "бычья дивергенция" if ev["side"] == "LONG" else "медвежья дивергенция"
    return (
        f"🛰️ АЛЬТ-РАСКОРРЕЛЯЦИЯ {symbol} {tf}\n\n"
        f"{arrow}  ${ev['close']:,.4f}\n"
        f"{divkind} (conf≥2) на альте, идущем НА СВОЁМ\n"
        f"corr(alt,BTC 30б) = {ev['corr']} (<{CORR_GATE} = раскоррелирован)\n\n"
        f"Сетап: stop {SL_PCT}% / tp {TP_PCT}% (RR2) / hold {HOLD_H}ч\n"
        f"Источник: alt_decorr — на paper-треке, PnL-гейт следит. Решение оператора."
    )


PROMOTE_MIN_N = 20
PROMOTE_MIN_PF = 1.2
PAPER_SIGNALS_PATH = ROOT / "state" / "paper_signals.jsonl"


def alt_decorr_promoted() -> bool:
    """True once the live paper record for source=alt_decorr proves edge:
    n>=PROMOTE_MIN_N closed AND profit-factor>=PROMOTE_MIN_PF. Until then the
    signal stays in the shadow (ROUTINE) channel. Best-effort; False on error."""
    try:
        rows = [json.loads(l) for l in PAPER_SIGNALS_PATH.read_text(
            encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        return False
    closed = [r for r in rows if r.get("source") == "alt_decorr"
              and r.get("pnl_usd") is not None]
    if len(closed) < PROMOTE_MIN_N:
        return False
    gw = sum(r["pnl_usd"] for r in closed if r["pnl_usd"] > 0)
    gl = -sum(r["pnl_usd"] for r in closed if r["pnl_usd"] < 0)
    pf = (gw / gl) if gl > 0 else (999.0 if gw > 0 else 0.0)
    return pf >= PROMOTE_MIN_PF


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
        logger.exception("alt_decorr.dedup_save_failed")


def _journal(rec: dict) -> None:
    try:
        JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except OSError:
        logger.exception("alt_decorr.journal_failed")


async def alt_decorr_loop(stop_event: asyncio.Event, *, send_fn=None,
                          interval_sec: int = POLL_INTERVAL_SEC) -> None:
    logger.info("alt_decorr.start alts=%s tf=25m,1h corr_gate=%.2f cooldown=%ds",
                ",".join(ALTS), CORR_GATE, COOLDOWN_SEC)
    while not stop_event.is_set():
        try:
            dedup = _load_dedup()
            now = datetime.now(timezone.utc)
            fired = False
            for alt in ALTS:
                for tf in ("25m", "1h"):
                    alt_df = _load_tf(alt, tf)
                    btc_df = _load_tf("BTCUSDT", tf)
                    ev = evaluate_alt_decorr(alt_df, btc_df)
                    if not ev.get("fire"):
                        continue
                    key = f"{alt}_{tf}_{ev['side']}"
                    last = dedup.get(key)
                    if last:
                        try:
                            lt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                            if (now - lt).total_seconds() < COOLDOWN_SEC:
                                continue
                        except (ValueError, AttributeError):
                            pass
                    # PnL-aware gate (same policy as cascade/grid)
                    try:
                        from services.common.paper_wr_gate import should_emit
                        ok, why = should_emit("alt_decorr", ev["side"])
                    except Exception:
                        ok, why = True, "gate_unavailable"
                    text = _format_card(alt, tf, ev)
                    logger.info("alt_decorr.fire %s %s side=%s corr=%.3f gate=%s",
                                alt, tf, ev["side"], ev["corr"], ok)
                    # 2026-07-22: живой аудит — 12 сигналов за 2 мес, WR 58%,
                    # +2.83% брутто (8 из 12 не дошли ни до TP, ни до стопа);
                    # после комиссий ≈ ноль при n втрое ниже порога 30. Карточка
                    # сама пишет «на paper-треке» = не actionable → в TG не шлём,
                    # paper-трек ниже продолжает копить. Вернуть: n≥30 и эдж.
                    from services.common.silent_families import tg_muted
                    muted = tg_muted("alt_decorr")
                    if ok and send_fn and not muted:
                        try:
                            send_fn(text)
                        except Exception:
                            logger.exception("alt_decorr.send_failed")
                    elif muted:
                        logger.info("alt_decorr.silent_journal %s %s (n<30, эдж не доказан)",
                                    alt, tf)
                    elif not ok:
                        logger.info("alt_decorr.suppressed_gate %s %s %s", alt, tf, why)
                    # paper-track regardless of TG gate (so the edge keeps measuring)
                    try:
                        from services.paper_signal_tracker.journal import record_paper_signal
                        record_paper_signal(
                            source="alt_decorr", side=ev["side"], entry=ev["close"],
                            stop_pct=-SL_PCT, tp_pct=TP_PCT, hold_h=HOLD_H,
                            symbol=alt,
                            context=f"{alt}_{tf}_corr{ev['corr']}", now=now,
                        )
                    except Exception:
                        logger.exception("alt_decorr.paper_failed")
                    dedup[key] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                    _journal({"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "alt": alt,
                              "tf": tf, **ev})
                    fired = True
            if fired:
                _save_dedup(dedup)
        except Exception:
            logger.exception("alt_decorr.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass
