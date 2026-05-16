"""Advisor v0.2 — рыночный анализатор с выводами и торговыми сетапами.

Without operator position. Without liquidation distance.
WITH: regime multi-TF, momentum, flow, OI/funding, session levels,
active setup detector signals, concrete trade ideas.

Output is decision-ready: "что вижу + что значит + конкретные уровни +
условия входа/выхода + почему".
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REGIME_PATH = Path("state/regime_state.json")
LIVE_1M = Path("market_live/market_1m.csv")
SETUPS_PATH = Path("state/setups.jsonl")
PAPER_TRADES_PATH = Path("state/paper_trades.jsonl")

# Active-setup rendering. ENTRY_BUCKET_PCT collapses near-duplicate setups
# of the same type whose entry prices are within ~0.3% of each other —
# setup_detector emits the same condition every poll cycle while it's live,
# so without bucketing the operator sees 5+ identical rows.
ENTRY_BUCKET_PCT = 0.003
HIGH_CONF_THRESHOLD = 60
TOP_CLUSTERS = 5

# Watch-block thresholds (advisor_v2 _build_watch_block).
FUNDING_DEEP_NEG_PCT = -0.008  # below this → squeeze potential
FUNDING_OVERHEAT_PCT = 0.015   # above this → longs overheated
OI_FLAT_ABS_PCT = 0.5          # |Δ| below this → flat, breakout incoming
OI_DIV_Z_THRESHOLD = 1.5       # |z| above this → divergence worth tracking

# TODO(reuse): the clustering below reimplements DedupLayer.evaluate_cluster
# (services/telegram/dedup_layer.py:149+). Consider routing through it for
# consistency with telegram dedup; deferred — different output shape.


def _load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_last_price() -> tuple[float, float] | None:
    """Return (price, age_min) from market_1m.csv or None."""
    if not LIVE_1M.exists():
        return None
    try:
        with LIVE_1M.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            block = min(8192, size)
            fh.seek(-block, 2)
            data = fh.read().decode("utf-8", errors="replace")
        last = None
        last_ts = None
        for line in data.splitlines():
            if not line.strip() or line.startswith("ts_utc"):
                continue
            parts = line.split(",")
            if len(parts) >= 5:
                last_ts = parts[0]
                last = float(parts[4])
        if last is None:
            return None
        # Compute age
        try:
            ts = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            return last, age
        except Exception:
            return last, 999.0
    except (OSError, ValueError):
        return None


def _load_recent_setups(within_hours: int = 6) -> list[dict]:
    """Recent setups from setup_detector journal."""
    if not SETUPS_PATH.exists():
        return []
    cutoff = datetime.now(timezone.utc).timestamp() - within_hours * 3600
    out = []
    try:
        for line in SETUPS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                ts_str = d.get("detected_at", "")
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts.timestamp() >= cutoff:
                    out.append(d)
            except (json.JSONDecodeError, ValueError, KeyError):
                continue
    except OSError:
        pass
    return out


def _load_open_paper_trades() -> list[dict]:
    """Currently open paper trades."""
    if not PAPER_TRADES_PATH.exists():
        return []
    by_id = {}
    try:
        for line in PAPER_TRADES_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                tid = e.get("trade_id")
                if not tid:
                    continue
                if e.get("action") == "OPEN":
                    by_id[tid] = e
                elif e.get("action") in ("TP2", "SL", "EXPIRE", "CANCEL"):
                    by_id.pop(tid, None)
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return list(by_id.values())


def _classify_v2_live() -> dict:
    """Use regime_classifier_v2 multi-timeframe view + persist to regime_v2_state.json."""
    try:
        from services.regime_classifier_v2.multi_timeframe import build_and_persist_view
        v = build_and_persist_view(symbol="BTCUSDT")
        return {
            "4h": (v.bar_4h.state_v2 if v.bar_4h else None,
                   v.bar_4h.indicators if v.bar_4h else {}),
            "1h": (v.bar_1h.state_v2 if v.bar_1h else None,
                   v.bar_1h.indicators if v.bar_1h else {}),
            "15m": (v.bar_15m.state_v2 if v.bar_15m else None,
                    v.bar_15m.indicators if v.bar_15m else {}),
            "diverge": v.macro_micro_diverge,
        }
    except Exception:
        logger.exception("advisor_v2.regime_classify_failed")
        return {}


def _compute_rsi(close: "pd.Series", period: int = 14) -> "pd.Series":
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    import pandas as pd
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def _compute_taker_imbalance(df) -> float | None:
    """Real taker imbalance from Binance klines: (buy_volume - sell_volume) / total * 100.

    Klines provide `taker_buy_base` per bar (the buy-side market volume). The
    rest is sell-side. Returns +X% (more buying) or -X% (more selling).
    """
    import pandas as pd
    if df is None or df.empty:
        return None
    if "taker_buy_base" not in df.columns or "volume" not in df.columns:
        return None
    buy = pd.to_numeric(df["taker_buy_base"], errors="coerce").sum()
    total = pd.to_numeric(df["volume"], errors="coerce").sum()
    if pd.isna(total) or total <= 0:
        return None
    sell = total - buy
    return float((buy - sell) / total * 100.0)


def _session_window_utc(now_utc, session: str) -> tuple:
    """Return (start_dt, end_dt) for today's session window in UTC, per
    advisor v2 docs (Tokyo 0000-0900, London 0700-1600, NY 1300-2200).
    """
    from datetime import datetime, timedelta, timezone
    today = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    if session == "asia":
        return today, today + timedelta(hours=9)
    if session == "london":
        return today + timedelta(hours=7), today + timedelta(hours=16)
    if session == "ny_am":
        return today + timedelta(hours=13), today + timedelta(hours=22)
    return today, today + timedelta(hours=24)


def _read_features_last() -> dict:
    """Compute all features LIVE from cached OHLCV + state/deriv_live.json.

    Replaces the broken 2026-05-07 implementation that read frozen
    full_features_1y.parquet (last bar 2026-05-01, all values stale by 7+
    days). RSI, taker_imbalance, volume_acceleration, session breakouts are
    now computed from live klines via core.data_loader.load_klines.

    Sources:
      - 1h, 15m, 5m, 1m OHLCV: load_klines (cached, ~1s freshness)
      - deriv data (OI / funding / premium / L-S / taker volume): state/deriv_live.json
    """
    import pandas as pd
    from datetime import datetime, timezone

    out: dict = {}

    try:
        from core.data_loader import load_klines

        # 1h: RSI, volume, OI/price divergence z-score, RSI divergence
        df_1h = load_klines(symbol="BTCUSDT", timeframe="1h", limit=200)
        if not df_1h.empty:
            close_1h = df_1h["close"]
            rsi_series = _compute_rsi(close_1h, 14)
            last_rsi = rsi_series.iloc[-1]
            if pd.notna(last_rsi):
                out["rsi_14"] = float(last_rsi)
            # Recent RSI divergence (last 5h vs prior 5h, naive HH-LH check)
            if len(rsi_series) >= 12:
                recent_high_idx = close_1h.iloc[-5:].idxmax()
                prior_high_idx = close_1h.iloc[-10:-5].idxmax()
                if (close_1h.loc[recent_high_idx] > close_1h.loc[prior_high_idx]
                        and rsi_series.loc[recent_high_idx] < rsi_series.loc[prior_high_idx]):
                    out["rsi_divergence_5h"] = True

            # Volume accel: last 5h mean vs prior 5h mean.
            # Coerce 'volume' to numeric — load_klines may return it as object.
            vol_num = pd.to_numeric(df_1h["volume"], errors="coerce")
            if len(vol_num.dropna()) >= 10:
                recent_vol = vol_num.iloc[-5:].mean()
                prior_vol = vol_num.iloc[-10:-5].mean()
                if pd.notna(prior_vol) and prior_vol > 0:
                    out["volume_acceleration"] = float((recent_vol - prior_vol) / prior_vol * 100.0)
            # rvol_20 = current bar vol / 20-bar mean
            if len(vol_num.dropna()) >= 21:
                vol20 = vol_num.iloc[-21:-1].mean()
                if pd.notna(vol20) and vol20 > 0:
                    out["rvol_20"] = float(vol_num.iloc[-1] / vol20)

            # realized_vol_pctile_24h: percentile of current 24h std within last 7 days
            if len(df_1h) >= 168:
                returns = df_1h["close"].pct_change()
                vol_24h = returns.rolling(24).std()
                cur_vol = vol_24h.iloc[-1]
                if pd.notna(cur_vol):
                    window_7d = vol_24h.iloc[-168:].dropna()
                    if len(window_7d) > 0:
                        pctile = (window_7d <= cur_vol).mean() * 100.0
                        out["realized_vol_pctile_24h"] = float(pctile)

        # 15m: taker imbalance over last 4 bars (1h equivalent), 1 bar (15m), 1/3 bar (5m)
        df_15m = load_klines(symbol="BTCUSDT", timeframe="15m", limit=24)
        if not df_15m.empty:
            ti_1h = _compute_taker_imbalance(df_15m.iloc[-4:])
            if ti_1h is not None:
                out["taker_imbalance_1h"] = ti_1h
            ti_15m = _compute_taker_imbalance(df_15m.iloc[-1:])
            if ti_15m is not None:
                out["taker_imbalance_15m"] = ti_15m

        # 5m for finer taker
        df_5m = load_klines(symbol="BTCUSDT", timeframe="5m", limit=12)
        if not df_5m.empty:
            ti_5m = _compute_taker_imbalance(df_5m.iloc[-1:])
            if ti_5m is not None:
                out["taker_imbalance_5m"] = ti_5m

        # Session breakouts: load 24h of 5m bars, find Asia/London/NY-AM H/L for
        # today, then check if any bar after the session window broke them.
        # load_klines returns 'open_time' as datetime64[UTC] — use it directly.
        df_5m_24h = load_klines(symbol="BTCUSDT", timeframe="5m", limit=288)
        if not df_5m_24h.empty and "open_time" in df_5m_24h.columns:
            now_utc = datetime.now(timezone.utc)
            dt = df_5m_24h["open_time"]
            last_close = float(df_5m_24h["close"].iloc[-1])

            for session in ("asia", "london", "ny_am"):
                s_start, s_end = _session_window_utc(now_utc, session)
                if now_utc < s_start:
                    continue
                effective_end = min(s_end, now_utc)
                in_session = df_5m_24h[(dt >= s_start) & (dt <= effective_end)]
                if in_session.empty:
                    continue
                s_high = float(in_session["high"].max())
                s_low = float(in_session["low"].min())
                after_session = df_5m_24h[dt > effective_end]
                broke_high = False
                broke_low = False
                if not after_session.empty:
                    high_break_mask = after_session["high"] > s_high
                    if high_break_mask.any():
                        broke_high = True
                        break_dt = after_session.loc[high_break_mask, "open_time"].iloc[0]
                        out[f"bars_since_{session}_high_break"] = float(
                            (now_utc - break_dt).total_seconds() / 3600.0
                        )
                    low_break_mask = after_session["low"] < s_low
                    if low_break_mask.any():
                        broke_low = True
                        break_dt = after_session.loc[low_break_mask, "open_time"].iloc[0]
                        out[f"bars_since_{session}_low_break"] = float(
                            (now_utc - break_dt).total_seconds() / 3600.0
                        )
                # Session still running — check current close vs session range so far
                if effective_end >= now_utc - pd.Timedelta(minutes=5):
                    if last_close > s_high:
                        broke_high = True
                    if last_close < s_low:
                        broke_low = True
                if broke_high:
                    out[f"{session}_high_broken"] = True
                if broke_low:
                    out[f"{session}_low_broken"] = True

    except Exception:
        logger.exception("advisor_v2.live_features_failed")

    # LIVE deriv data (OI / funding / premium / L-S / taker volume) from state/deriv_live.json.
    # This source already worked and stays as-is.
    try:
        import json as _json
        from pathlib import Path as _Path
        live_path = _Path("state/deriv_live.json")
        if live_path.exists():
            data = _json.loads(live_path.read_text(encoding="utf-8"))
            btc = data.get("BTCUSDT", {}) or {}
            if "funding_rate_8h" in btc:
                out["funding_rate"] = float(btc["funding_rate_8h"])
                out["_funding_source"] = "deriv_live"
            if "oi_change_1h_pct" in btc:
                out["oi_delta_1h"] = float(btc["oi_change_1h_pct"])
                out["_oi_source"] = "deriv_live"
            if "premium_pct" in btc:
                out["premium_pct"] = float(btc["premium_pct"])
            for k in ("global_long_account_pct", "global_short_account_pct",
                      "top_trader_long_pct", "top_trader_short_pct",
                      "taker_buy_pct", "taker_sell_pct",
                      "bybit_long_pct", "bybit_short_pct"):
                if k in btc:
                    out[k] = btc[k]
            out["_deriv_live_ts"] = data.get("last_updated", "")
            # Long/short extreme flags (>=70% one side = crowded)
            gl = btc.get("global_long_account_pct")
            if gl is not None:
                if gl >= 70:
                    out["ls_long_extreme"] = True
                elif gl <= 30:
                    out["ls_short_extreme"] = True
    except Exception:
        logger.exception("advisor_v2.deriv_live_load_failed")

    return out


def _interpret_momentum(f: dict) -> list[str]:
    """Convert momentum indicators into trader-readable observations."""
    out = []
    rsi = f.get("rsi_14")
    if rsi is not None:
        if rsi > 70:
            out.append(f"RSI 1h {rsi:.0f} — перекуплен")
        elif rsi < 30:
            out.append(f"RSI 1h {rsi:.0f} — перепродан")
        else:
            out.append(f"RSI 1h {rsi:.0f} — нейтрально")
    if f.get("rsi_divergence_5h"):
        out.append("⚠️ RSI divergence (5h) — обнаружена")
    if f.get("cci_overbought"):
        out.append("CCI overbought — momentum exhaustion возможен")
    if f.get("cci_oversold"):
        out.append("CCI oversold — momentum exhaustion возможен")
    return out


def _interpret_flow(f: dict) -> list[str]:
    """Note: live features (since 2026-05-08 refactor) supply taker_imbalance,
    volume_acceleration, realized_vol_pctile_24h already in PERCENT (not 0..1).
    """
    out = []
    ti_1h = f.get("taker_imbalance_1h")
    ti_15m = f.get("taker_imbalance_15m")
    if ti_1h is not None:
        sign = "buy" if ti_1h > 0 else "sell"
        out.append(f"Taker 1h: {ti_1h:+.1f}% ({sign} pressure)")
    if ti_15m is not None and ti_1h is not None and (ti_15m * ti_1h < 0):
        out.append("⚠️ Flow flip — 15m расходится с 1h по направлению")
    vol_accel = f.get("volume_acceleration")
    if vol_accel is not None:
        if vol_accel < -50:
            out.append(f"Volume падает (accel {vol_accel:+.0f}%)")
        elif vol_accel > 50:
            out.append(f"Volume растёт (accel {vol_accel:+.0f}%)")
    rvp = f.get("realized_vol_pctile_24h")
    if rvp is not None:
        if rvp > 80:
            out.append(f"Vol percentile 24h: {rvp:.0f}% — высокая волатильность")
            out.append("⚠️ HIGH vol regime: Range Hunter 5m paused (require_low_vol), "
                       "mean-reversion edges деградируют. Cascade alerts работают как обычно.")
        elif rvp < 20:
            out.append(f"Vol percentile 24h: {rvp:.0f}% — низкая волатильность")
            out.append("✓ LOW vol regime: Range Hunter работает в boost-режиме (любит спокойствие).")
        else:
            out.append(f"Vol percentile 24h: {rvp:.0f}% — средняя волатильность")
    return out


def _interpret_oi_funding(f: dict) -> list[str]:
    out = []
    oi = f.get("oi_delta_1h")
    if oi is not None:
        if abs(oi) > 1.0:
            sign = "растёт" if oi > 0 else "падает"
            out.append(f"OI 1h: {oi:+.2f}% ({sign} быстро)")
        else:
            out.append(f"OI 1h: {oi:+.2f}% (flat)")
    oi_div_z = f.get("oi_price_div_1h_z")
    if oi_div_z is not None and abs(oi_div_z) > 1.5:
        sign = "цена растёт + OI падает" if oi_div_z < 0 else "цена падает + OI растёт"
        out.append(f"⚠️ OI/price divergence z={oi_div_z:+.1f} ({sign})")
    funding = f.get("funding_rate")
    if funding is not None:
        funding_8h_pct = funding * 100  # parquet stores per-period rate
        if abs(funding_8h_pct) < 0.005:
            out.append(f"Funding: {funding_8h_pct:+.4f}% (нейтрально)")
        elif funding_8h_pct < -0.008:
            out.append(f"Funding: {funding_8h_pct:+.4f}% — глубоко negative (longs платят меньше, может быть squeeze)")
        elif funding_8h_pct > 0.008:
            out.append(f"Funding: {funding_8h_pct:+.4f}% — положительный (longs платят shorts)")
        else:
            out.append(f"Funding: {funding_8h_pct:+.4f}%")
    if f.get("ls_long_extreme"):
        out.append("⚠️ LS ratio: long extreme — толпа в long, contrarian short setup")
    if f.get("ls_short_extreme"):
        out.append("⚠️ LS ratio: short extreme — толпа в short, contrarian long setup")
    # Premium (mark vs index) — новый сигнал из live deriv poll (2026-05-07)
    premium = f.get("premium_pct")
    if premium is not None:
        if abs(premium) < 0.02:
            pass  # neutral, не спамим
        elif premium > 0.05:
            out.append(f"Premium {premium:+.3f}% — perp выше spot (long bias)")
        elif premium < -0.05:
            out.append(f"Premium {premium:+.3f}% — perp ниже spot (short bias)")
    # Live source marker (для прозрачности, видеть откуда данные)
    if f.get("_funding_source") == "deriv_live":
        out.append("_(funding/OI: live Binance, обновляется каждые 5 мин)_")
    return out


def _interpret_global_market(f: dict) -> list[str]:
    """BTC.D + total mcap context (C3)."""
    out: list[str] = []
    try:
        import json as _json
        from pathlib import Path as _Path
        p = _Path("state/deriv_live.json")
        if not p.exists():
            return out
        data = _json.loads(p.read_text(encoding="utf-8"))
        g = data.get("global", {}) or {}
        btc_d = g.get("btc_dominance_pct")
        eth_d = g.get("eth_dominance_pct")
        mcap_chg = g.get("mcap_change_24h_pct")
        total = g.get("total_mcap_usd")
        if btc_d is not None:
            out.append(f"BTC.D {btc_d}%, ETH.D {eth_d}% — деньги {'в BTC' if btc_d > 55 else 'в альтах' if btc_d < 50 else 'распределены'}")
        if mcap_chg is not None:
            arrow = "↑" if mcap_chg > 0 else "↓"
            out.append(f"Total mcap 24h {arrow} {mcap_chg:+.2f}% (${total/1e12:.2f}T)" if total else f"Total mcap 24h {arrow} {mcap_chg:+.2f}%")
    except Exception:
        logger.debug("global_market failed", exc_info=True)
    return out


def _interpret_flip_history(f: dict) -> list[str]:
    """Funding/premium flip history + OI spike (A1+A2+A4)."""
    out: list[str] = []
    try:
        from services.deriv_live.flip_tracker import detect_flips, detect_oi_spike

        flips = detect_flips()
        if flips.get("funding"):
            ff = flips["funding"]
            streak = ff.get("current_streak_hours")
            sign_word = "положительный" if ff["current_sign"] == "+" else "отрицательный"
            if streak is not None:
                last_val = ff["last_flip"]["value"] * 100
                out.append(
                    f"Funding-flip: {sign_word} {streak:.1f}ч (был {last_val:+.4f}%)"
                )
        if flips.get("premium"):
            pp = flips["premium"]
            streak = pp.get("current_streak_hours")
            sign_word = "положительный (perp выше spot)" if pp["current_sign"] == "+" else "отрицательный (perp ниже spot)"
            if streak is not None:
                out.append(f"Premium-flip: {sign_word}, {streak:.1f}ч")

        spike = detect_oi_spike()
        if spike:
            arrow = "↑" if spike["direction"] == "up" else "↓"
            out.append(f"OI 15min {arrow} {spike['oi_change_15min_pct']:+.2f}% — крупные позиции {'открываются' if spike['direction'] == 'up' else 'закрываются'}")
    except Exception:
        logger.exception("advisor_v2.flip_history_failed")
    return out


def _interpret_long_short(f: dict) -> list[str]:
    """Long/Short market sentiment (Binance global + top traders + Bybit + taker)."""
    out: list[str] = []
    gl = f.get("global_long_account_pct")
    gs = f.get("global_short_account_pct")
    tl = f.get("top_trader_long_pct")
    ts_pct = f.get("top_trader_short_pct")
    tb = f.get("taker_buy_pct")
    tk_s = f.get("taker_sell_pct")
    bl = f.get("bybit_long_pct")
    bs = f.get("bybit_short_pct")

    if gl is not None and gs is not None:
        out.append(f"Binance все аккаунты: {gl}% long / {gs}% short")
    if tl is not None and ts_pct is not None:
        out.append(f"Binance топ-трейдеры (по объёму): {tl}% long / {ts_pct}% short")
    if bl is not None and bs is not None:
        out.append(f"Bybit: {bl}% long / {bs}% short")
    if tb is not None and tk_s is not None:
        out.append(f"Taker volume (последние 5 мин): {tb}% buy / {tk_s}% sell")

    # Trader-actionable insights
    if gl is not None and gl >= 60:
        out.append(f"⚠️ Толпа в LONG ({gl}%) — crowded long, риск short squeeze ВНИЗ")
    elif gs is not None and gs >= 60:
        out.append(f"⚠️ Толпа в SHORT ({gs}%) — crowded short, риск long squeeze ВВЕРХ")

    if tl is not None and gl is not None and (tl - gl) >= 5:
        out.append(f"  Топ-трейдеры более bullish ({tl}% vs толпа {gl}%) — смартмани bias UP")
    elif ts_pct is not None and gs is not None and (ts_pct - gs) >= 5:
        out.append(f"  Топ-трейдеры более bearish ({ts_pct}% vs толпа {gs}%) — смартмани bias DOWN")

    if tb is not None and tb >= 65:
        out.append(f"🔵 Taker buy {tb}% — сильное покупательское давление прямо сейчас")
    elif tk_s is not None and tk_s >= 65:
        out.append(f"🔴 Taker sell {tk_s}% — сильное продавательское давление прямо сейчас")

    return out


def _interpret_session_levels(f: dict) -> list[str]:
    out = []
    breaks = []
    if f.get("asia_high_broken"):
        breaks.append("Asia high")
    if f.get("london_high_broken"):
        breaks.append("London high")
    if f.get("ny_am_high_broken"):
        breaks.append("NY-AM high")
    if breaks:
        out.append(f"Пробиты вверх: {', '.join(breaks)}")
    breaks_low = []
    if f.get("asia_low_broken"):
        breaks_low.append("Asia low")
    if f.get("london_low_broken"):
        breaks_low.append("London low")
    if f.get("ny_am_low_broken"):
        breaks_low.append("NY-AM low")
    if breaks_low:
        out.append(f"Пробиты вниз: {', '.join(breaks_low)}")
    # Bars since fresh = setup retest opportunity
    bars_since_l_h = f.get("bars_since_london_high_break")
    if bars_since_l_h is not None and 0 < bars_since_l_h < 8:
        out.append(f"London high пробит {bars_since_l_h:.0f} баров назад — свежий retest setup")
    bars_since_ny_h = f.get("bars_since_ny_am_high_break")
    if bars_since_ny_h is not None and 0 < bars_since_ny_h < 8:
        out.append(f"NY-AM high пробит {bars_since_ny_h:.0f} баров назад — свежий retest setup")
    bars_since_l_l = f.get("bars_since_london_low_break")
    if bars_since_l_l is not None and 0 < bars_since_l_l < 8:
        out.append(f"London low пробит {bars_since_l_l:.0f} баров назад — свежий retest")
    return out


def _compute_risk_score(regime: dict, f: dict) -> dict:
    """Aggregate risk score 0-10 для трейдера.

    Считаем баллы:
    - SHORT_RISK (риск падения): bull regime divergent с micro down, taker sell ext,
      crowded long, premium negative, OI declining
    - LONG_RISK (риск squeeze вверх): crowded short, taker buy extreme, OI rising,
      funding negative deep

    Возвращает: {short_risk: 0-10, long_risk: 0-10, dominant: 'short'|'long'|'neutral', reasons: [...]}
    """
    short_risk = 0
    long_risk = 0
    short_reasons: list[str] = []
    long_reasons: list[str] = []

    # Regime
    primary_4h = (regime.get("4h") or (None, {}))[0]
    primary_15m = (regime.get("15m") or (None, {}))[0]
    is_macro_up = primary_4h in ("STRONG_UP", "SLOW_UP", "DRIFT_UP", "CASCADE_UP")
    is_macro_down = primary_4h in ("STRONG_DOWN", "SLOW_DOWN", "DRIFT_DOWN", "CASCADE_DOWN")
    is_micro_up = primary_15m in ("STRONG_UP", "SLOW_UP", "DRIFT_UP", "CASCADE_UP")
    is_micro_down = primary_15m in ("STRONG_DOWN", "SLOW_DOWN", "DRIFT_DOWN", "CASCADE_DOWN")

    if is_macro_up and is_micro_up:
        long_risk += 1
        long_reasons.append("4h+15m тренд вверх")
    if is_macro_down and is_micro_down:
        short_risk += 1
        short_reasons.append("4h+15m тренд вниз")

    # L/S extreme — contrarian
    gl = f.get("global_long_account_pct")
    gs = f.get("global_short_account_pct")
    if gl is not None and gl >= 60:
        short_risk += 2
        short_reasons.append(f"толпа в LONG {gl}% (crowded — squeeze ВНИЗ)")
    elif gs is not None and gs >= 60:
        long_risk += 2
        long_reasons.append(f"толпа в SHORT {gs}% (crowded — squeeze ВВЕРХ)")
    elif gs is not None and gs >= 55:
        long_risk += 1
        long_reasons.append(f"толпа в SHORT {gs}% (близко к crowded)")

    # Top trader bias
    tl = f.get("top_trader_long_pct")
    ts_pct = f.get("top_trader_short_pct")
    if tl is not None and gl is not None and (tl - gl) >= 5:
        long_risk += 1
        long_reasons.append("топ-трейдеры более bullish чем толпа")
    elif ts_pct is not None and gs is not None and (ts_pct - gs) >= 5:
        short_risk += 1
        short_reasons.append("топ-трейдеры более bearish чем толпа")

    # Taker pressure now
    tb = f.get("taker_buy_pct")
    tk_s = f.get("taker_sell_pct")
    if tb is not None and tb >= 65:
        long_risk += 2
        long_reasons.append(f"taker buy {tb}% — давление вверх СЕЙЧАС")
    elif tk_s is not None and tk_s >= 65:
        short_risk += 2
        short_reasons.append(f"taker sell {tk_s}% — давление вниз СЕЙЧАС")

    # Funding
    funding = f.get("funding_rate")
    if funding is not None:
        f_pct = funding * 100
        if f_pct < -0.01:
            long_risk += 1
            long_reasons.append(f"funding {f_pct:+.4f}% (shorts платят — squeeze potential)")
        elif f_pct > 0.01:
            short_risk += 1
            short_reasons.append(f"funding {f_pct:+.4f}% (longs платят — overcrowded)")

    # Premium (mark vs index)
    premium = f.get("premium_pct")
    if premium is not None:
        if premium < -0.05:
            short_risk += 1
            short_reasons.append(f"premium {premium:+.3f}% (perp ниже spot — sell pressure)")
        elif premium > 0.05:
            long_risk += 1
            long_reasons.append(f"premium {premium:+.3f}% (perp выше spot — buy pressure)")

    # OI direction
    oi = f.get("oi_delta_1h")
    if oi is not None and abs(oi) > 1.0:
        # OI растёт сильно + либо tracking тренд, либо contrarian risk
        if oi > 1.0 and is_macro_up:
            long_risk += 1
            long_reasons.append(f"OI 1h {oi:+.2f}% — тренд усиливается")
        elif oi < -1.0:
            # OI быстро падает = массовое закрытие, может быть конец движения
            pass  # neutral, не считаем

    # Cap at 10
    short_risk = min(short_risk, 10)
    long_risk = min(long_risk, 10)

    if short_risk > long_risk and short_risk >= 3:
        dominant = "short_risk"  # риск падения цены
    elif long_risk > short_risk and long_risk >= 3:
        dominant = "long_risk"  # риск squeeze вверх
    else:
        dominant = "neutral"

    return {
        "short_risk": short_risk,
        "long_risk": long_risk,
        "dominant": dominant,
        "short_reasons": short_reasons,
        "long_reasons": long_reasons,
    }


def _format_risk_block(rs: dict) -> list[str]:
    """Render risk score block."""
    out: list[str] = []
    sr = rs["short_risk"]
    lr = rs["long_risk"]
    dom = rs["dominant"]

    if dom == "short_risk":
        emoji = "🔴"
        headline = f"Риск ВНИЗ выше ({sr}/10) чем риск ВВЕРХ ({lr}/10)"
        action = "Не агрессивно докидывать LONG. Защитные настройки шортовых ботов оправданы."
    elif dom == "long_risk":
        emoji = "🟢"
        headline = f"Риск ВВЕРХ выше ({lr}/10) чем риск ВНИЗ ({sr}/10)"
        action = "Не агрессивно докидывать SHORT. Возможен squeeze rally."
    else:
        emoji = "⚪"
        headline = f"Риски сбалансированы (вверх {lr}/10, вниз {sr}/10)"
        action = "Без явного направления. Range-режим, никаких aggressive moves."

    out.append(f"{emoji} {headline}")
    out.append(f"   Действие: {action}")
    if rs["long_reasons"]:
        out.append(f"   Факторы за рост ({lr}/10):")
        for r in rs["long_reasons"][:4]:
            out.append(f"     + {r}")
    if rs["short_reasons"]:
        out.append(f"   Факторы за падение ({sr}/10):")
        for r in rs["short_reasons"][:4]:
            out.append(f"     - {r}")
    return out


def _summary_verdict(regime: dict, f: dict, setups: list[dict]) -> tuple[str, list[str]]:
    """Compute one-line verdict + supporting reasoning."""
    reasons = []
    primary_4h = (regime.get("4h") or (None, {}))[0]
    primary_1h = (regime.get("1h") or (None, {}))[0]
    primary_15m = (regime.get("15m") or (None, {}))[0]

    is_macro_up = primary_4h in ("STRONG_UP", "SLOW_UP", "DRIFT_UP", "CASCADE_UP")
    is_macro_down = primary_4h in ("STRONG_DOWN", "SLOW_DOWN", "DRIFT_DOWN", "CASCADE_DOWN")
    is_micro_up = primary_15m in ("STRONG_UP", "SLOW_UP", "DRIFT_UP", "CASCADE_UP")
    is_micro_down = primary_15m in ("STRONG_DOWN", "SLOW_DOWN", "DRIFT_DOWN", "CASCADE_DOWN")

    # High-confidence setups (conf >= 60)
    high_conf_setups = [s for s in setups if s.get("confidence_pct", 0) >= 60]
    long_setups = [s for s in high_conf_setups if s.get("setup_type", "").startswith("long_")]
    short_setups = [s for s in high_conf_setups if s.get("setup_type", "").startswith("short_")]

    # Verdict logic (decision-oriented):
    if not is_macro_up and not is_macro_down:
        # 2026-05-10 SMART-PAUSE (TZ #11): на боковике без активных setups
        # советуем НЕ торговать пока не появится breakout-сигнал. Это
        # снижает overtrading на range-фазе.
        if not high_conf_setups:
            verdict = "🟡 НЕ ТОРГУЙ — БОКОВИК БЕЗ СИГНАЛОВ"
            reasons.append("4h в RANGE/COMPRESSION — нет тренда")
            reasons.append("0 активных setup'ов с confidence ≥60% за 6h")
            reasons.append("Жди: breakout 4h-границ ИЛИ появления setup ≥60%")
        else:
            verdict = "БОКОВИК — без направления"
            reasons.append("4h в RANGE/COMPRESSION — нет тренда")
    elif is_macro_up and is_micro_up:
        verdict = "BULL CONFLUENCE — macro и micro вверх"
        reasons.append(f"4h={primary_4h}, 15m={primary_15m} — оба бычьи")
    elif is_macro_down and is_micro_down:
        verdict = "BEAR CONFLUENCE — macro и micro вниз"
        reasons.append(f"4h={primary_4h}, 15m={primary_15m} — оба медвежьи")
    elif is_macro_up and is_micro_down:
        verdict = "MACRO BULL / MICRO PULLBACK — потенциальный buy-the-dip"
        reasons.append(f"4h={primary_4h}, но 15m={primary_15m} — coiling в macro тренде")
    elif is_macro_down and is_micro_up:
        verdict = "MACRO BEAR / MICRO RALLY — потенциальный rally-to-fade"
        reasons.append(f"4h={primary_4h}, но 15m={primary_15m} — отскок в downtrend")
    else:
        verdict = "СМЕШАННЫЙ КОНТЕКСТ"
        reasons.append(f"4h={primary_4h}, 1h={primary_1h}, 15m={primary_15m}")

    # Setup confluence
    if len(long_setups) >= 2:
        reasons.append(f"+{len(long_setups)} активных LONG сетапов confidence ≥60")
    if len(short_setups) >= 2:
        reasons.append(f"+{len(short_setups)} активных SHORT сетапов confidence ≥60")

    # OI/funding confluence
    oi_div_z = f.get("oi_price_div_1h_z")
    if oi_div_z is not None:
        if oi_div_z < -1.5:
            reasons.append(f"OI/price div z={oi_div_z:.1f} — short squeeze setup possible")
        elif oi_div_z > 1.5:
            reasons.append(f"OI/price div z={oi_div_z:+.1f} — long crowdedness signal")
    if f.get("ls_long_extreme") and is_macro_up:
        reasons.append("⚠️ Long extreme в bull тренде — risk of squeeze down")
    if f.get("ls_short_extreme") and is_macro_down:
        reasons.append("⚠️ Short extreme в bear тренде — risk of squeeze up")

    return verdict, reasons


# ── Grid-bot pause advisor (TZ-PAUSE-ADVISOR 2026-05-08) ─────────────────
#
# Backtest 2026-05-08 (Codex run_pause_compare on 2y BTCUSDT canonical bots):
# always-on grid lost 98.4% (final $285 of $15k, liquidated 2024-12-05). Of
# 32 active pause configs, only 4 survived — all with movement>=2.0% over
# 60min and pullback_bars=2. Sweet spot: m=2.0% w=60min p=2 / pb=1.0% sm=20
# → final $13,473, no liquidation. m=2.5%+ or p>=3 still got liquidated.
#
# We re-evaluate the same triggers LIVE here so /advise can warn the operator
# when grid-bot pause is recommended right now.

PAUSE_MOVEMENT_PCT = 2.0
PAUSE_WINDOW_MIN = 60
PAUSE_NO_PULLBACK_BARS = 2


def _compute_pause_signal() -> dict:
    """Live evaluation of grid-bot pause triggers for SHORT and LONG sides.

    Returns a dict with keys:
      short_pause: True if SHORT bots should pause (BTC rallying against them)
      long_pause:  True if LONG bots should pause (BTC dumping against them)
      change_60m_pct, last_close, peak_60m, trough_60m, trend_bars_up, trend_bars_down

    Uses last 5m bars for the 60min window + last 4 hourly bars for trend-bars
    counting (mirrors engine_v2.state_machine algorithm).
    """
    out = {
        "short_pause": False,
        "long_pause": False,
        "change_60m_pct": None,
        "last_close": None,
        "trend_bars_up": 0,
        "trend_bars_down": 0,
    }
    try:
        from core.data_loader import load_klines
        import pandas as pd

        # 5m bars for the 60-minute window check (12 bars = exactly 60 min).
        df_5m = load_klines(symbol="BTCUSDT", timeframe="5m", limit=12)
        if df_5m is None or df_5m.empty:
            return out
        last_close = float(df_5m["close"].iloc[-1])
        oldest = float(df_5m["close"].iloc[0])
        change_pct = (last_close - oldest) / oldest * 100.0
        out["last_close"] = last_close
        out["change_60m_pct"] = change_pct
        out["peak_60m"] = float(df_5m["high"].max())
        out["trough_60m"] = float(df_5m["low"].min())

        # Hourly bars for trend-bar counter (count consecutive completed
        # hourly bars by direction, last to first).
        df_1h = load_klines(symbol="BTCUSDT", timeframe="1h", limit=8)
        if df_1h is not None and not df_1h.empty:
            # Use last 4 closed bars (skip the still-forming current one).
            closed = df_1h.iloc[-5:-1] if len(df_1h) >= 5 else df_1h.iloc[:-1]
            up_bars = 0
            down_bars = 0
            for _, bar in closed.iloc[::-1].iterrows():
                if bar["close"] > bar["open"]:
                    if down_bars == 0:
                        up_bars += 1
                    else:
                        break
                elif bar["close"] < bar["open"]:
                    if up_bars == 0:
                        down_bars += 1
                    else:
                        break
                else:
                    break
            out["trend_bars_up"] = up_bars
            out["trend_bars_down"] = down_bars

        # SHORT pause: rally against shorts.
        if change_pct >= PAUSE_MOVEMENT_PCT and out["trend_bars_up"] >= PAUSE_NO_PULLBACK_BARS:
            out["short_pause"] = True
        # LONG pause: dump against longs.
        if change_pct <= -PAUSE_MOVEMENT_PCT and out["trend_bars_down"] >= PAUSE_NO_PULLBACK_BARS:
            out["long_pause"] = True
    except Exception:
        logger.exception("advisor_v2.pause_signal_failed")
    return out


def _format_pause_block(sig: dict) -> list[str]:
    """Render the pause-advisor block lines. Returns [] when nothing to show."""
    if sig.get("change_60m_pct") is None:
        return []

    change = sig["change_60m_pct"]
    last_close = sig["last_close"]
    up_bars = sig["trend_bars_up"]
    down_bars = sig["trend_bars_down"]
    short_pause = sig.get("short_pause", False)
    long_pause = sig.get("long_pause", False)

    lines: list[str] = []

    if short_pause or long_pause:
        if short_pause:
            lines.append("🚨 ПАУЗА GRID — SHORT")
            lines.append(f"  BTC за час: {change:+.2f}% ({up_bars} бычьих свечей подряд)")
            lines.append(f"  Триггер: ≥+{PAUSE_MOVEMENT_PCT}% за 60min И ≥{PAUSE_NO_PULLBACK_BARS} bull-свечи")
            lines.append("  Рекомендация: остановить SHORT-ботов до отката ≥0.7-1.0% от пика")
            lines.append("  Backtest 2y: без паузы → ликвидация Dec-2024 ($285 из $15k)")
        if long_pause:
            lines.append("🚨 ПАУЗА GRID — LONG")
            lines.append(f"  BTC за час: {change:+.2f}% ({down_bars} медвежьих свечей подряд)")
            lines.append(f"  Триггер: ≥-{PAUSE_MOVEMENT_PCT}% за 60min И ≥{PAUSE_NO_PULLBACK_BARS} bear-свечи")
            lines.append("  Рекомендация: остановить LONG-ботов до отскока ≥0.7-1.0% от дна")
    else:
        # Quiet status — show how close we are to a trigger so operator has context.
        lines.append("✅ GRID PAUSE: триггеров нет")
        lines.append(f"  BTC за час: {change:+.2f}% (порог ±{PAUSE_MOVEMENT_PCT}%)  •  bull-свечей подряд: {up_bars} / bear-свечей: {down_bars} (порог {PAUSE_NO_PULLBACK_BARS})")

    return lines


def _read_margin_block() -> dict | None:
    """Read margin block from state_latest.json (set by state_snapshot_loop).

    Source: state/manual_overrides/margin_overrides.jsonl ← /margin operator command.
    """
    try:
        import json as _json
        from pathlib import Path as _Path
        p = _Path("docs/STATE/state_latest.json")
        if not p.exists():
            return None
        data = _json.loads(p.read_text(encoding="utf-8"))
        return data.get("margin")
    except Exception:
        return None


def build_advisor_v2_text() -> str:
    """Compose full advisor v2 message."""
    now = datetime.now(timezone.utc)
    price_info = _read_last_price()
    regime = _classify_v2_live()
    features = _read_features_last()
    setups = _load_recent_setups(within_hours=6)
    open_papers = _load_open_paper_trades()

    lines = []
    lines.append(f"🎯 ADVISOR v0.2 — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    if price_info:
        price, age_min = price_info
        if age_min > 10:
            lines.append(f"⚠️ BTC {price:,.0f} | data {age_min:.0f}min old (stale!)")
        else:
            lines.append(f"BTC {price:,.0f} | data fresh ({age_min:.0f}min)")
    else:
        lines.append("⚠️ Нет live price feed")

    # ── Verdict (top of message — decision first)
    verdict, reasoning = _summary_verdict(regime, features, setups)
    lines.append("")
    lines.append(f"━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📌 ВЕРДИКТ: {verdict}")
    for r in reasoning:
        lines.append(f"   • {r}")
    lines.append(f"━━━━━━━━━━━━━━━━━━━━")

    # ── Risk Score (D1, 2026-05-07): сводная оценка рисков по всем сигналам
    risk = _compute_risk_score(regime, features)
    lines.append("")
    lines.append("🎯 RISK SCORE")
    for x in _format_risk_block(risk):
        lines.append(f"  {x}")

    # ── Margin status (TZ-MARGIN-COEFFICIENT-INPUT-WIRE 2026-05-07).
    # state_snapshot.py picks newer of operator /margin override and BitMEX-API
    # auto-poll, so we surface whichever source was freshest. Stale > 6h = warn.
    margin_block = _read_margin_block()
    if margin_block:
        lines.append("")
        source = str(margin_block.get("source", "unknown"))
        if source == "telegram_operator":
            label = "operator /margin"
        elif source == "bitmex_api":
            label = "auto-poll BitMEX API"
        else:
            label = source or "unknown"
        lines.append(f"💰 MARGIN ({label})")
        coef = margin_block.get("coefficient")
        avail = margin_block.get("available_margin_usd")
        dist = margin_block.get("distance_to_liquidation_pct")
        age_min = margin_block.get("data_age_minutes", 0)
        if coef is not None:
            lines.append(f"  Margin coef: {coef:.4f} | Available: ${avail:,.0f} | Dist to liq: {dist:.1f}%")
        if age_min > 360:  # > 6h
            lines.append(f"  ⚠️ Margin data {age_min/60:.1f}h old — auto-poll или /margin")
        elif age_min > 60:
            lines.append(f"  Margin data {age_min:.0f}min old")

    # ── Grid-bot pause advisor (TZ-PAUSE-ADVISOR 2026-05-08).
    # Backtest-validated triggers (m=2.0% w=60min p=2 — only config that
    # survived the Dec-2024 rally on 2y data).
    pause_signal = _compute_pause_signal()
    pause_lines = _format_pause_block(pause_signal)
    if pause_lines:
        lines.append("")
        for x in pause_lines:
            lines.append(x)

    # ── Regime multi-TF
    lines.append("")
    lines.append("РЕЖИМ (multi-TF)")
    for tf in ("4h", "1h", "15m"):
        state, ind = regime.get(tf, (None, {}))
        if state is None:
            lines.append(f"  {tf}: нет данных")
            continue
        slope = ind.get("ema50_slope_pct")
        dist = ind.get("dist_to_ema200_pct")
        slope_str = f"slope {slope:+.2f}%" if slope is not None else ""
        dist_str = f"dist EMA200 {dist:+.2f}%" if dist is not None else ""
        lines.append(f"  {tf}: {state} | {slope_str} | {dist_str}".strip())
    if regime.get("diverge"):
        lines.append("  ⚠️ Macro ≠ Micro")

    # ── Momentum
    momentum = _interpret_momentum(features)
    if momentum:
        lines.append("")
        lines.append("МОМЕНТУМ")
        for m in momentum:
            lines.append(f"  • {m}")

    # ── Flow / orderflow
    flow = _interpret_flow(features)
    if flow:
        lines.append("")
        lines.append("FLOW / OBJECTIVE PRESSURE")
        for f in flow:
            lines.append(f"  • {f}")

    # ── OI / funding
    oi_funding = _interpret_oi_funding(features)
    if oi_funding:
        lines.append("")
        lines.append("OI / FUNDING / КРАУДНОСТЬ")
        for x in oi_funding:
            lines.append(f"  • {x}")

    # ── Global market (C3): BTC dominance + total mcap
    glob = _interpret_global_market(features)
    if glob:
        lines.append("")
        lines.append("РЫНОК ГЛОБАЛЬНО")
        for x in glob:
            lines.append(f"  • {x}")

    # ── SNP correlation (TZ #11 — task 2026-05-09): macro context.
    # ES=F (S&P futures) drops > 1% often precede BTC -2% within 1-2h.
    try:
        from services.advisor.snp_feed import get_snp_snapshot
        snp = get_snp_snapshot()
        if snp.last_close > 0 and not snp.error:
            lines.append("")
            lines.append("МАКРО (ES=F SP500 futures)")
            ch24 = snp.change_24h_pct
            ch1h = snp.change_1h_pct
            if ch24 is not None:
                arrow = "↑" if ch24 > 0 else "↓" if ch24 < 0 else "→"
                lines.append(f"  • SNP 24ч: {arrow} {ch24:+.2f}% | 1ч: {ch1h:+.2f}%"
                             if ch1h is not None else f"  • SNP 24ч: {arrow} {ch24:+.2f}%")
            if snp.correlation_24h is not None:
                corr = snp.correlation_24h
                strength = "сильная" if abs(corr) > 0.5 else "средняя" if abs(corr) > 0.3 else "слабая"
                direction = "положительная" if corr > 0 else "отрицательная"
                lines.append(f"  • Корреляция BTC↔SNP (24ч): {corr:+.2f} ({strength} {direction})")
            # Warn signal: SNP -1.5% in 24h often leads BTC down
            if ch24 is not None and ch24 <= -1.5:
                lines.append(f"  ⚠️ SNP резкое падение → BTC потенциально под давлением (1-2ч лаг)")
            if ch1h is not None and ch1h <= -0.8:
                lines.append(f"  ⚠️ SNP -{abs(ch1h):.2f}% за час → возможно близкое движение BTC")
            if snp.is_stale:
                lines.append(f"  (данные устарели, источник недоступен)")
    except Exception:
        logger.debug("advisor_v2.snp_feed_failed", exc_info=True)

    # ── Flip history (A1+A2+A4): funding/premium streak + OI spike
    flip = _interpret_flip_history(features)
    if flip:
        lines.append("")
        lines.append("ИСТОРИЯ FLIP / SPIKE")
        for x in flip:
            lines.append(f"  • {x}")

    # ── Long/Short ratio (рыночная дельта)
    ls = _interpret_long_short(features)
    if ls:
        lines.append("")
        lines.append("LONG/SHORT РЫНОК")
        for x in ls:
            lines.append(f"  • {x}")

    # ── Session levels
    sess = _interpret_session_levels(features)
    if sess:
        lines.append("")
        lines.append("УРОВНИ СЕССИЙ")
        for s in sess:
            lines.append(f"  • {s}")

    # ── Decision Layer PRIMARY events in last 6h (TZ-DL-ACTIVATION 2026-05-08)
    try:
        from datetime import timedelta as _td
        cutoff_dl = (datetime.now(timezone.utc) - _td(hours=6)).isoformat()
        dl_path = Path("state/decision_log/decisions.jsonl")
        recent_dl_primary: list[dict] = []
        if dl_path.exists():
            for line in dl_path.read_text(encoding="utf-8").splitlines()[-300:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("severity") != "PRIMARY":
                    continue
                if e.get("rule_id", "").startswith("CAP-"):
                    continue
                if e.get("ts", "") < cutoff_dl:
                    continue
                recent_dl_primary.append(e)
        if recent_dl_primary:
            # Dedup by rule_id (show most recent per rule)
            by_rule: dict[str, dict] = {}
            for e in recent_dl_primary:
                by_rule[e.get("rule_id", "?")] = e
            lines.append("")
            lines.append("🚦 DECISION LAYER (PRIMARY за 6h)")
            for rule_id, e in sorted(by_rule.items()):
                etype = e.get("event_type", "?")
                rec = e.get("recommendation", "") or ""
                rec_short = rec[:80] + "..." if len(rec) > 80 else rec
                lines.append(f"  {rule_id}: {etype}")
                if rec_short:
                    lines.append(f"    → {rec_short}")
    except Exception:
        logger.exception("advisor_v2.decision_layer_block_failed")

    # ── Active setups. Setup_detector fires the same condition every poll
    # cycle while it's live, producing 5+ near-duplicate rows. Cluster by
    # (setup_type, entry-bucket of ENTRY_BUCKET_PCT) and render the most
    # recent snapshot per cluster with an ×N counter.
    # Disabled detectors filter: skip setup_types в runtime_disabled / .env DISABLED_DETECTORS
    try:
        from services.setup_detector.runtime_disabled import is_detector_disabled
    except Exception:
        def is_detector_disabled(_name: str) -> bool:
            return False
    high_conf = [s for s in setups
                 if s.get("confidence_pct", 0) >= HIGH_CONF_THRESHOLD
                 and not is_detector_disabled(s.get("setup_type", ""))]
    if high_conf:
        lines.append("")
        lines.append(f"🎯 АКТИВНЫЕ СЕТАПЫ (≥{HIGH_CONF_THRESHOLD}% conf, последние 6h)")

        # Bucket grows with price so ENTRY_BUCKET_PCT stays meaningful across
        # symbols: log(entry)/log(1+pct) gives the index of a 0.3%-wide bin.
        log_step = math.log1p(ENTRY_BUCKET_PCT)

        clusters: dict[tuple[str, int], list[dict]] = {}
        for s in high_conf:
            entry = s.get("entry_price")
            if not entry or entry <= 0:
                continue
            stype = s.get("setup_type", "?")
            bucket = int(math.log(entry) / log_step)
            clusters.setdefault((stype, bucket), []).append(s)

        latest_per_cluster = [
            (max(cl, key=lambda x: x.get("ts") or ""), len(cl))
            for cl in clusters.values()
        ]
        latest_per_cluster.sort(key=lambda pair: pair[0].get("ts") or "", reverse=True)

        for s, n in latest_per_cluster[:TOP_CLUSTERS]:
            stype = s.get("setup_type", "?")
            entry = s.get("entry_price")
            sl = s.get("stop_price")
            tp1 = s.get("tp1_price")
            tp2 = s.get("tp2_price")
            conf = s.get("confidence_pct", 0)
            rr = s.get("risk_reward")
            entry_str = f"{entry:.0f}" if entry else "?"
            sl_str = f"{sl:.0f}" if sl else "?"
            tp1_str = f"{tp1:.0f}" if tp1 else "?"
            tp2_str = f"{tp2:.0f}" if tp2 else "?"
            rr_str = f"RR {rr}" if rr else ""
            count_str = f" ×{n}" if n > 1 else ""
            lines.append(
                f"  {stype}{count_str}: {entry_str} | SL {sl_str} | "
                f"TP1 {tp1_str} | TP2 {tp2_str} | conf {conf:.0f}% {rr_str}"
            )
    else:
        lines.append("")
        lines.append(f"🎯 АКТИВНЫЕ СЕТАПЫ: нет (последние 6h, conf ≥{HIGH_CONF_THRESHOLD}%)")

    # ── Open paper trades summary (улучшенный — total notional + top setups + expected PnL)
    if open_papers:
        from collections import Counter as _Counter
        lines.append("")
        lines.append(f"📊 PAPER TRADES (открыто {len(open_papers)})")
        long_n = sum(1 for t in open_papers if t.get("side") == "long")
        short_n = len(open_papers) - long_n
        total_notional = sum(float(t.get("size_usd") or 0) for t in open_papers)
        # Filter to disabled-aware setups + top 3 by count
        type_counter = _Counter(t.get("setup_type", "?") for t in open_papers)
        top_types = type_counter.most_common(3)
        # Expected PnL: ср. распределение TP1/SL × WR из исторических данных setup_type
        # Простая прокси: за win считаем (tp1-entry)*size_btc; за loss — (entry-sl)*size_btc
        exp_pnl_if_all_tp = 0.0
        exp_pnl_if_all_sl = 0.0
        for t in open_papers:
            side_sign = 1 if t.get("side") == "long" else -1
            entry = float(t.get("entry") or 0)
            tp1 = float(t.get("tp1") or entry)
            sl = float(t.get("sl") or entry)
            size = float(t.get("size_usd") or 0)
            if entry > 0 and size > 0:
                exp_pnl_if_all_tp += (tp1 - entry) / entry * size * side_sign
                exp_pnl_if_all_sl += (sl - entry) / entry * size * side_sign

        lines.append(f"  {long_n} LONG / {short_n} SHORT  ·  Notional: ${total_notional:,.0f}")
        lines.append(f"  Top setups: " + ", ".join(f"{t}×{n}" for t, n in top_types))
        lines.append(f"  EV all-TP1: ${exp_pnl_if_all_tp:+,.0f}  |  EV all-SL: ${exp_pnl_if_all_sl:+,.0f}")
        # 3 примера (вместо 5) для краткости
        for tr in open_papers[:3]:
            side = "LONG" if tr.get("side") == "long" else "SHORT"
            entry = tr.get("entry") or 0
            tp1 = tr.get("tp1") or 0
            stype = tr.get("setup_type", "?")
            lines.append(f"  {side} @ {entry:.0f} → TP1 {tp1:.0f} | {stype}")

    # ── СВЕЖИЕ СИГНАЛЫ ОТ БОТА (last 6h: RH / watchlist / cascade / confluence)
    try:
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        import json as _json
        from pathlib import Path as _Path
        _ROOT = _Path("/Users/alexeychechikov/code/bot7")
        cutoff_6h = _dt.now(_tz.utc) - _td(hours=6)
        signal_lines = []

        # Range Hunter signals per symbol/variant
        rh_recent = []
        for sym in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
            for variant in ("1m", "5m"):
                jp = _ROOT / "state" / (
                    "range_hunter_signals.jsonl" if (sym == "BTCUSDT" and variant == "1m")
                    else f"range_hunter_signals_{sym}{'_' + variant if variant != '1m' else ''}.jsonl"
                )
                if not jp.exists():
                    continue
                try:
                    for line in jp.read_text(encoding="utf-8").splitlines():
                        if not line.strip():
                            continue
                        r = _json.loads(line)
                        ts = _dt.fromisoformat(r.get("ts_signal", ""))
                        if ts >= cutoff_6h:
                            rh_recent.append({
                                "ts": ts, "sym": sym, "variant": variant,
                                "action": r.get("user_action") or "pending",
                                "exit_reason": r.get("exit_reason"),
                                "pnl": r.get("pnl_usd"),
                            })
                except (OSError, _json.JSONDecodeError, ValueError):
                    pass
        if rh_recent:
            n_total = len(rh_recent)
            n_placed = sum(1 for r in rh_recent if r["action"] == "placed")
            n_skipped = sum(1 for r in rh_recent if r["action"] == "skipped")
            pnl_resolved = sum(float(r.get("pnl") or 0) for r in rh_recent if r.get("exit_reason"))
            signal_lines.append(f"  🎯 RH: {n_total} signals (placed {n_placed}, skipped {n_skipped}), resolved PnL ${pnl_resolved:+.2f}")

        # Watchlist fires
        pj = _ROOT / "state" / "play_journal.jsonl"
        if pj.exists():
            wl_recent = []
            try:
                for line in pj.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    r = _json.loads(line)
                    ts = _dt.fromisoformat(r.get("ts_fire", ""))
                    if ts >= cutoff_6h:
                        wl_recent.append(r.get("label", "?"))
            except (OSError, _json.JSONDecodeError, ValueError):
                pass
            if wl_recent:
                from collections import Counter as _C2
                top_labels = _C2(wl_recent).most_common(3)
                signal_lines.append("  🔔 Watchlist: " + ", ".join(f"{l}×{n}" for l, n in top_labels))

        # Cascade alerts (last fired per side)
        cad = _ROOT / "state" / "cascade_alert_dedup.json"
        if cad.exists():
            try:
                cdata = _json.loads(cad.read_text(encoding="utf-8"))
                cascades_recent = []
                for key, ts_str in cdata.items():
                    try:
                        ts = _dt.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts >= cutoff_6h:
                            cascades_recent.append(key)
                    except (ValueError, TypeError):
                        continue
                if cascades_recent:
                    signal_lines.append("  ⚡ Cascade: " + ", ".join(cascades_recent))
            except (OSError, _json.JSONDecodeError):
                pass

        # Confluence
        cf = _ROOT / "state" / "confluence_fires.jsonl"
        if cf.exists():
            try:
                cf_recent = []
                for line in cf.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    r = _json.loads(line)
                    ts = _dt.fromisoformat(r.get("ts", ""))
                    if ts >= cutoff_6h:
                        cf_recent.append(r.get("direction", "?"))
                if cf_recent:
                    signal_lines.append(f"  🔥 Confluence: {len(cf_recent)} fires ({', '.join(cf_recent)})")
            except (OSError, _json.JSONDecodeError, ValueError):
                pass

        if signal_lines:
            lines.append("")
            lines.append("📡 СВЕЖИЕ СИГНАЛЫ ОТ БОТА (последние 6h)")
            lines.extend(signal_lines)
    except Exception:
        logger.exception("advisor_v2.fresh_signals_block_failed")

    # ── What to watch — only render triggers that match current state.
    watch: list[str] = []

    funding = features.get("funding_rate")
    if funding is not None:
        funding_pct = funding * 100
        # Distance to funding_squeeze_long trigger (-0.010%) — validated edge n=10, 70% pct_up 4h
        squeeze_threshold = -0.010
        dist_to_squeeze = funding_pct - squeeze_threshold
        if funding_pct < FUNDING_DEEP_NEG_PCT:
            watch.append(f"Funding flip к ≥0 (сейчас {funding_pct:+.4f}% — глубоко negative, потенциал squeeze)")
        elif funding_pct > FUNDING_OVERHEAT_PCT:
            watch.append(f"Funding flip к ≤0 (сейчас {funding_pct:+.4f}% — перегрев longs)")
        # Squeeze trigger watch: показываем расстояние если в "approach zone" (<0)
        if funding_pct < 0:
            watch.append(f"Funding squeeze trigger ({squeeze_threshold:.3f}%): осталось {abs(dist_to_squeeze):.4f}pp до fire")

    oi = features.get("oi_delta_1h")
    if oi is not None and abs(oi) < OI_FLAT_ABS_PCT:
        watch.append("OI 1h breakout (сейчас flat — пробой ±1% даст направление)")

    oi_div_z = features.get("oi_price_div_1h_z")
    if oi_div_z is not None and abs(oi_div_z) > OI_DIV_Z_THRESHOLD:
        sign = "цена↑ + OI↓ — слабое движение" if oi_div_z < 0 else "цена↓ + OI↑ — поджимают шорты"
        watch.append(f"OI/price divergence z={oi_div_z:+.1f} ({sign}) — ждать resync")

    if regime.get("diverge"):
        watch.append("Macro ≠ Micro — ждать выравнивания TF (см. блок РЕЖИМ)")

    if watch:
        lines.append("")
        lines.append("👀 ЧТО ОТСЛЕЖИВАТЬ")
        for w in watch:
            lines.append(f"  • {w}")

    # ── Persist audit entry (TZ-ADVISE-AUDIT 2026-05-07)
    try:
        from services.advisor.audit import log_advise_call
        regime_states = {tf: (regime.get(tf, (None, {}))[0]) for tf in ("4h", "1h", "15m")}
        log_advise_call(
            verdict=verdict,
            reasoning=list(reasoning),
            regime_4h=regime_states.get("4h"),
            regime_1h=regime_states.get("1h"),
            regime_15m=regime_states.get("15m"),
            macro_micro_diverge=bool(regime.get("diverge")),
            btc_price=(price_info[0] if price_info else None),
            setups_count=len(setups),
            open_paper_trades=len(open_papers),
        )
    except Exception:
        pass  # never block /advise on audit-write failure

    return "\n".join(lines)
