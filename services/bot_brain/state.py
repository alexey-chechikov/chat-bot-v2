"""Bot Brain — perception layer.

Once per minute, gather:
  - Account state (margin, available, distance-to-liq)
  - Per-symbol market state (regime, vol, funding, OI, taker, VPVR levels, recent cascades)
  - Per-bot state (position, profit, fill counts, distance-to-liq, paused-by-guard flag)

Write a single JSON line to state/bot_brain_state.jsonl. This is the SINGLE
perception stream — rules engine, manual decision support (/should_<dir>), and
backtest research all consume it.

NO TG output here. NO actions here. Just observation.
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "state"
GINAREA_DIR = ROOT / "ginarea_live"

SNAPSHOT_PATH = STATE_DIR / "bot_brain_state.jsonl"
MANAGED_PATH = STATE_DIR / "short_bots_managed.json"
AUTO_PAUSE_PATH = STATE_DIR / "short_bots_auto_pause.json"
MARGIN_PATH = STATE_DIR / "margin_automated.jsonl"
REGIME_PATH = STATE_DIR / "regime_state.json"
DERIV_PATH = STATE_DIR / "deriv_live.json"
DERIV_HISTORY_PATH = STATE_DIR / "deriv_live_history.jsonl"
CASCADE_DEDUP_PATH = STATE_DIR / "cascade_alert_dedup.json"
MANUAL_LEVELS_PATH = STATE_DIR / "manual_levels.json"
SNAPSHOTS_CSV = GINAREA_DIR / "snapshots.csv"
PARAMS_CSV = GINAREA_DIR / "params.csv"
EVENTS_CSV = GINAREA_DIR / "events.csv"
EXHAUSTION_FIRES_PATH = STATE_DIR / "grid_coordinator_fires.jsonl"
EXHAUSTION_INTRADAY_FIRES_PATH = STATE_DIR / "grid_coordinator_intraday_fires.jsonl"
LIQ_CLUSTER_FIRES_PATH = STATE_DIR / "liq_pre_cascade_fires.jsonl"
TV_ALERTS_PATH = STATE_DIR / "tv_alerts.jsonl"

# Map storage symbol used in manual_levels.json
LEVELS_SYMBOL_MAP = {
    "BTCUSDT": "BTCUSD",
    "ETHUSDT": "ETHUSDT",
    "XRPUSDT": "XRPUSDT",
}

DEFAULT_INTERVAL_SEC = 60
CASCADE_LOOKBACK_MIN = 360  # 6h window for "recent cascades"


def _read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("bot_brain.state.read_json_failed path=%s", path)
        return None


def _tail_jsonl(path: Path, n: int = 1) -> list[dict]:
    """Read last `n` JSON lines from a JSONL file. Returns [] on failure."""
    if not path.exists():
        return []
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 64 * 1024)
            f.seek(size - chunk)
            tail = f.read().decode("utf-8", errors="ignore")
        lines = [ln for ln in tail.splitlines() if ln.strip()]
        out = []
        for ln in lines[-n:]:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return out
    except OSError:
        return []


def _read_account() -> dict[str, Any]:
    rows = _tail_jsonl(MARGIN_PATH, n=1)
    if not rows:
        return {}
    r = rows[0]
    return {
        "wallet_balance_usd": r.get("wallet_balance_usd"),
        "margin_balance_usd": r.get("margin_balance_usd"),
        "available_margin_usd": r.get("available_margin_usd"),
        "used_margin_usd": r.get("used_margin_usd"),
        "distance_to_liquidation_pct": r.get("distance_to_liquidation_pct"),
        "positions_count": r.get("positions_count"),
        "btc_mark_price": r.get("btc_mark_price"),
        "snapshot_ts": r.get("ts"),
    }


def _read_cascades_recent(now: datetime, lookback_min: int = CASCADE_LOOKBACK_MIN
                           ) -> dict[str, list[dict]]:
    """For each symbol, return list of cascade events within lookback window.
    Each event: {"type": "short_5.0", "ts_iso": ..., "age_min": int}.

    cascade_alert_dedup.json holds last-seen timestamps per type — we use it as a
    "currently fresh" signal, не как полную историю. История cascades живёт в
    state/cascade_fires.jsonl или в logs/app.log, но для perception хватит того
    что мы знаем "событие X было N мин назад" (если в окне).
    """
    dedup = _read_json(CASCADE_DEDUP_PATH) or {}
    by_symbol: dict[str, list[dict]] = {"BTCUSDT": [], "ETHUSDT": [], "XRPUSDT": []}
    for cascade_type, ts_iso in dedup.items():
        if not isinstance(ts_iso, str):
            continue
        try:
            ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        except ValueError:
            continue
        age_min = (now - ts).total_seconds() / 60.0
        if age_min > lookback_min or age_min < 0:
            continue
        # cascade types are currently BTC-centric (short_5.0, long_5.0, etc).
        # Keep them on BTCUSDT for now; when ETH/XRP cascade detectors добавятся,
        # cascade_type будет иметь префикс symbol_.
        by_symbol["BTCUSDT"].append({
            "type": cascade_type,
            "ts": ts_iso,
            "age_min": round(age_min, 1),
        })
    for k in by_symbol:
        by_symbol[k].sort(key=lambda e: e["age_min"])
    return by_symbol


def _btc_price_changes() -> dict[str, Optional[float]]:
    """Return BTC price-change pct over multiple windows (1m, 5m, 15m, 60m).
    Reads market_live/market_1m.csv tail. Returns None values if data missing.

    Used by bot_brain rules as a gate: don't fire pause unless BTC actually
    moved meaningfully. Operator 2026-05-17 directive: pause only on TRULY
    STRONG one-sided moves, not micro 0.3-1% spikes."""
    market_csv = ROOT / "market_live" / "market_1m.csv"
    out: dict[str, Optional[float]] = {
        "price_change_1m_pct": None, "price_change_5m_pct": None,
        "price_change_15m_pct": None, "price_change_60m_pct": None,
        "btc_mid_now": None,
    }
    if not market_csv.exists():
        return out
    try:
        # Tail last 70 minutes (covers 60m + buffer); CSV is 1 line/min
        with market_csv.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            # ~80 bytes per line × 80 lines = 6.4KB; pull 16KB to be safe
            chunk = min(size, 16 * 1024)
            f.seek(size - chunk)
            tail = f.read().decode("utf-8", errors="ignore")
        lines = [ln for ln in tail.splitlines() if ln.strip() and not ln.startswith("ts_utc")]
        if len(lines) < 2:
            return out
        # Parse close prices
        closes = []
        for line in lines:
            parts = line.split(",")
            if len(parts) >= 5:
                try:
                    closes.append(float(parts[4]))
                except ValueError:
                    continue
        if not closes:
            return out
        now_close = closes[-1]
        out["btc_mid_now"] = round(now_close, 2)
        # Compute pct change vs N minutes ago (each line is 1m)
        for window_min, key in [(1, "price_change_1m_pct"), (5, "price_change_5m_pct"),
                                  (15, "price_change_15m_pct"), (60, "price_change_60m_pct")]:
            if len(closes) > window_min and closes[-window_min - 1] > 0:
                pct = (now_close - closes[-window_min - 1]) / closes[-window_min - 1] * 100.0
                out[key] = round(pct, 3)
    except OSError:
        logger.exception("bot_brain.btc_price_changes_failed")
    return out


def _read_market(now: datetime) -> dict[str, dict]:
    """Per-symbol market state aggregated from existing services + state."""
    regime_state = _read_json(REGIME_PATH) or {}
    deriv = _read_json(DERIV_PATH) or {}
    levels = _read_json(MANUAL_LEVELS_PATH) or {}
    cascades_by_sym = _read_cascades_recent(now)
    btc_price_changes = _btc_price_changes()

    try:
        from services.volatility_regime import current_regime
    except Exception:
        current_regime = None

    out: dict[str, dict] = {}
    for symbol in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
        d = deriv.get(symbol, {}) or {}
        rs = (regime_state.get("symbols", {}) or {}).get(symbol, {}) or {}
        lv_key = LEVELS_SYMBOL_MAP[symbol]
        lv = levels.get(lv_key, {}) or {}

        mid = d.get("mark_price")
        vol_regime = None
        vol_pct = None
        if current_regime is not None:
            try:
                vol_regime, vol_pct = current_regime(symbol)
            except Exception:
                logger.exception("bot_brain.vol_regime_failed symbol=%s", symbol)

        val = lv.get("val")
        vah = lv.get("vah")
        poc = lv.get("poc")
        dist_val_pct = None
        dist_vah_pct = None
        if mid and val:
            dist_val_pct = round((mid - val) / mid * 100.0, 3)
        if mid and vah:
            dist_vah_pct = round((vah - mid) / mid * 100.0, 3)

        # Attach BTC price-change windows only to BTCUSDT entry (others may be added later)
        price_changes = btc_price_changes if symbol == "BTCUSDT" else {
            "price_change_1m_pct": None, "price_change_5m_pct": None,
            "price_change_15m_pct": None, "price_change_60m_pct": None,
        }
        out[symbol] = {
            "mid": mid,
            "regime_primary": rs.get("current_primary"),
            "regime_age_bars": rs.get("regime_age_bars"),
            "vol_regime": vol_regime,
            "vol_pct": round(vol_pct, 2) if isinstance(vol_pct, (int, float)) else None,
            "funding_rate_8h": d.get("funding_rate_8h"),
            "oi_change_1h_pct": d.get("oi_change_1h_pct"),
            "premium_pct": d.get("premium_pct"),
            "taker_buy_pct": d.get("taker_buy_pct"),
            "global_ls_ratio": d.get("global_ls_ratio"),
            "top_trader_ls_ratio": d.get("top_trader_ls_ratio"),
            "val": val,
            "vah": vah,
            "poc": poc,
            "dist_val_pct": dist_val_pct,
            "dist_vah_pct": dist_vah_pct,
            "cascades_recent": cascades_by_sym.get(symbol, []),
            # Price-movement windows for rule-gating (BTCUSDT only currently)
            "price_change_1m_pct": price_changes.get("price_change_1m_pct"),
            "price_change_5m_pct": price_changes.get("price_change_5m_pct"),
            "price_change_15m_pct": price_changes.get("price_change_15m_pct"),
            "price_change_60m_pct": price_changes.get("price_change_60m_pct"),
        }
    return out


def _read_bot_params_latest() -> dict[str, dict]:
    """Latest row per bot_id from ginarea_live/params.csv. Extracts grid_top/bottom
    + gs (grid step) for use in R4 (drift) and analytics. Tail-scan for efficiency."""
    out: dict[str, dict] = {}
    if not PARAMS_CSV.exists():
        return out
    try:
        with PARAMS_CSV.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 256 * 1024)
            f.seek(size - chunk)
            tail = f.read().decode("utf-8", errors="ignore")
        lines = tail.splitlines()
        if lines:
            lines = lines[1:]  # drop possibly-truncated first line
        with PARAMS_CSV.open("r", encoding="utf-8") as f:
            header = next(csv.reader(f))
        reader = csv.reader(lines)
        for row in reader:
            if len(row) != len(header):
                continue
            rec = dict(zip(header, row))
            bid = rec.get("bot_id")
            if not bid:
                continue
            grid_top = _safe_float(rec.get("border_top"))
            grid_bottom = _safe_float(rec.get("border_bottom"))
            gs = _safe_float(rec.get("grid_step"))
            out[bid] = {
                "grid_top": grid_top,
                "grid_bottom": grid_bottom,
                "grid_step_pct": gs,
                "max_orders": _safe_float(rec.get("max_opened_orders")),
                "active_p": str(rec.get("raw_params_json", ""))[:20],  # placeholder
                "params_ts": rec.get("ts_utc"),
            }
    except OSError:
        logger.exception("bot_brain.params_csv_read_failed")
    return out


def _read_exhaustion_fires_recent(now: datetime, max_age_min: float = 60.0
                                    ) -> dict[str, list[dict]]:
    """Recent exhaustion fires from grid_coordinator_fires.jsonl + intraday.
    Returns dict by direction → list of {ts, age_min, score, symbol(=BTCUSDT)}."""
    out: dict[str, list[dict]] = {"up": [], "down": []}
    for path in (EXHAUSTION_FIRES_PATH, EXHAUSTION_INTRADAY_FIRES_PATH):
        if not path.exists():
            continue
        try:
            with path.open("rb") as f:
                f.seek(0, 2)
                size = f.tell()
                chunk = min(size, 64 * 1024)
                f.seek(size - chunk)
                tail = f.read().decode("utf-8", errors="ignore")
            for line in tail.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_iso = rec.get("ts")
                if not ts_iso:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                age = (now - ts).total_seconds() / 60.0
                if age > max_age_min or age < 0:
                    continue
                d = rec.get("direction") or "?"
                bucket = "up" if d == "up" else "down" if d == "down" else None
                if bucket:
                    out[bucket].append({
                        "ts": ts_iso, "age_min": round(age, 1),
                        "score": rec.get("score"),
                    })
        except OSError:
            continue
    for k in out:
        out[k].sort(key=lambda e: e["age_min"])
    return out


def _read_liq_cluster_fires_recent(now: datetime, max_age_min: float = 30.0
                                     ) -> list[dict]:
    """Recent liq-cluster fires from liq_pre_cascade_fires.jsonl.
    Validated pre-cascade signal: precision 43.8% / recall 65.3% within 30 min
    (audit 2026-05-17, scripts/pre_cascade_audit.py).

    Returns: list of {ts, side, qty_btc, age_min}.
    side='long' means long-liq cluster → expects LONG cascade continuation.
    side='short' means short-liq cluster → expects SHORT cascade."""
    if not LIQ_CLUSTER_FIRES_PATH.exists():
        return []
    out = []
    try:
        with LIQ_CLUSTER_FIRES_PATH.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 32 * 1024)
            f.seek(size - chunk)
            tail = f.read().decode("utf-8", errors="ignore")
        for line in tail.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_iso = rec.get("ts")
            if not ts_iso:
                continue
            try:
                ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            age = (now - ts).total_seconds() / 60.0
            if age > max_age_min or age < 0:
                continue
            out.append({
                "ts": ts_iso,
                "side": rec.get("side"),
                "qty_btc": rec.get("qty_btc"),
                "age_min": round(age, 1),
            })
    except OSError:
        logger.exception("bot_brain.state.liq_cluster_read_failed")
    out.sort(key=lambda e: e["age_min"])
    return out


def _read_tv_alerts_recent(now: datetime, max_age_min: float = 15.0) -> list[dict]:
    """Recent TV-webhook alerts (last 15 min by default) from tv_alerts.jsonl.
    Used by R1.7 combo rule: liq_cluster + recent TV CVD-divergence alert.
    Returns list of {ts, payload, age_min}."""
    if not TV_ALERTS_PATH.exists():
        return []
    out = []
    try:
        with TV_ALERTS_PATH.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 64 * 1024)
            f.seek(size - chunk)
            tail = f.read().decode("utf-8", errors="ignore")
        for line in tail.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_iso = rec.get("ingest_ts")
            if not ts_iso:
                continue
            try:
                ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            age = (now - ts).total_seconds() / 60.0
            if age > max_age_min or age < 0:
                continue
            out.append({
                "ingest_ts": ts_iso,
                "payload": rec.get("payload") or {},
                "age_min": round(age, 1),
            })
    except OSError:
        logger.exception("bot_brain.state.tv_alerts_read_failed")
    out.sort(key=lambda e: e["age_min"])
    return out


def _bot_pnl_24h(bot_id: str, current_profit: Optional[float]) -> Optional[float]:
    """Compute realized PnL over last 24h for a bot by walking back bot_brain_state.jsonl.
    Returns delta = current_profit - profit_24h_ago, or None if insufficient history."""
    if current_profit is None or not SNAPSHOT_PATH.exists():
        return None
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        target_profit: Optional[float] = None
        # Scan from start (file is small enough — 1 line/min × 24h = 1440 lines/day)
        with SNAPSHOT_PATH.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    snap = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_iso = snap.get("ts")
                if not ts_iso:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_iso)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if ts < cutoff:
                    continue
                # First snapshot >= cutoff → use it as baseline (close to 24h ago)
                for b in snap.get("bots", []):
                    if b.get("bot_id") == bot_id:
                        p = _safe_float(b.get("current_profit_usd"))
                        if p is not None:
                            target_profit = p
                        break
                if target_profit is not None:
                    break  # earliest in-window match
        if target_profit is None:
            return None
        return round(current_profit - target_profit, 4)
    except OSError:
        return None


def _read_bot_snapshots_latest() -> dict[str, dict]:
    """Return latest row per bot_id from ginarea_live/snapshots.csv.

    snapshots.csv columns:
      ts_utc, bot_id, bot_name, alias, status, position, profit, current_profit,
      in_filled_count, in_filled_qty, out_filled_count, out_filled_qty,
      trigger_count, trigger_qty, average_price, trade_volume, balance,
      liquidation_price, schema_version
    """
    out: dict[str, dict] = {}
    if not SNAPSHOTS_CSV.exists():
        return out
    try:
        # File can be large (80MB+). Read only last ~256KB which covers many minutes.
        with SNAPSHOTS_CSV.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 256 * 1024)
            f.seek(size - chunk)
            tail = f.read().decode("utf-8", errors="ignore")
        # Drop possibly-truncated first line
        lines = tail.splitlines()
        if lines:
            lines = lines[1:]
        reader = csv.reader(lines)
        # Need header — read it once from top of file
        with SNAPSHOTS_CSV.open("r", encoding="utf-8") as f:
            header = next(csv.reader(f))
        for row in reader:
            if len(row) != len(header):
                continue
            rec = dict(zip(header, row))
            bid = rec.get("bot_id")
            if not bid:
                continue
            out[bid] = rec  # later rows overwrite earlier → ends at latest
    except OSError:
        logger.exception("bot_brain.snapshots_csv_read_failed")
    return out


def _safe_float(v: Any) -> Optional[float]:
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _read_bots(market_btc_mid: Optional[float]) -> list[dict]:
    """Per-managed-bot state from short_bots_managed.json + ginarea snapshots
    + params + auto_pause flags + 24h PnL."""
    managed = _read_json(MANAGED_PATH) or {}
    auto_pause = _read_json(AUTO_PAUSE_PATH) or {}
    paused_dict = auto_pause.get("paused", {}) or {}
    snapshots = _read_bot_snapshots_latest()
    params_map = _read_bot_params_latest()

    out: list[dict] = []
    for entry in managed.get("managed_bots", []):
        bid = str(entry.get("bot_id"))
        snap = snapshots.get(bid, {})
        params = params_map.get(bid, {})
        liq_price = _safe_float(snap.get("liquidation_price"))
        position = _safe_float(snap.get("position"))
        dist_to_liq_pct = None
        # Compute dist_to_liq only when:
        #   1) liq_price > 0 (non-empty)
        #   2) position meaningful (>= 0.001 BTC; micro-positions give phantom liq prices)
        #   3) liq_price within sanity range (0.5×–2×) of mid (otherwise GinArea-phantom)
        #   4) liq direction matches bot side (SHORT: liq above mid, LONG: liq below)
        if (liq_price and liq_price > 0 and position is not None and abs(position) >= 0.001
                and market_btc_mid and market_btc_mid > 0
                and 0.5 * market_btc_mid <= liq_price <= 2.0 * market_btc_mid):
            side = entry.get("side")
            if side == "short" and liq_price > market_btc_mid:
                dist_to_liq_pct = round((liq_price - market_btc_mid) / market_btc_mid * 100.0, 2)
            elif side == "long" and liq_price < market_btc_mid:
                dist_to_liq_pct = round((market_btc_mid - liq_price) / market_btc_mid * 100.0, 2)

        paused_info = paused_dict.get(bid) or paused_dict.get(entry.get("tier"))

        current_profit = _safe_float(snap.get("current_profit"))
        pnl_24h = _bot_pnl_24h(bid, current_profit)

        # drift_from_mid_pct: where current mid sits relative to grid mid
        grid_top = params.get("grid_top")
        grid_bottom = params.get("grid_bottom")
        drift_pct = None
        if grid_top and grid_bottom and market_btc_mid:
            grid_mid = (grid_top + grid_bottom) / 2.0
            if grid_mid > 0:
                drift_pct = round((market_btc_mid - grid_mid) / grid_mid * 100.0, 2)

        out.append({
            "bot_id": bid,
            "tier": entry.get("tier"),
            "alias": entry.get("alias"),
            "side": entry.get("side"),
            "testbed": bool(entry.get("testbed", False)),
            "status": snap.get("status"),
            "position_btc": position,
            "current_profit_usd": current_profit,
            "pnl_24h_usd": pnl_24h,
            "in_filled_count": _safe_float(snap.get("in_filled_count")),
            "out_filled_count": _safe_float(snap.get("out_filled_count")),
            "balance": _safe_float(snap.get("balance")),
            "liquidation_price": liq_price,
            "dist_to_liq_pct": dist_to_liq_pct,
            "average_price": _safe_float(snap.get("average_price")),
            "trade_volume": _safe_float(snap.get("trade_volume")),
            "grid_top": grid_top,
            "grid_bottom": grid_bottom,
            "grid_step_pct": params.get("grid_step_pct"),
            "drift_from_mid_pct": drift_pct,
            "snapshot_ts": snap.get("ts_utc"),
            "paused_by_guard": paused_info is not None,
            "paused_reason": (paused_info or {}).get("reason") if isinstance(paused_info, dict) else None,
            "paused_until": (paused_info or {}).get("paused_until") if isinstance(paused_info, dict) else None,
        })
    return out


def collect_snapshot(now: Optional[datetime] = None) -> dict[str, Any]:
    if now is None:
        now = datetime.now(timezone.utc)
    account = _read_account()
    market = _read_market(now)
    btc_mid = market.get("BTCUSDT", {}).get("mid")
    bots = _read_bots(btc_mid)
    exhaustion = _read_exhaustion_fires_recent(now)
    liq_clusters = _read_liq_cluster_fires_recent(now)
    tv_alerts = _read_tv_alerts_recent(now)
    # Attach to BTCUSDT market (currently the only symbol they fire on)
    if "BTCUSDT" in market:
        market["BTCUSDT"]["exhaustion_fires_recent"] = exhaustion
        market["BTCUSDT"]["liq_cluster_fires_recent"] = liq_clusters
        market["BTCUSDT"]["tv_alerts_recent"] = tv_alerts
    return {
        "ts": now.isoformat(timespec="seconds"),
        "version": 2,
        "account": account,
        "market": market,
        "bots": bots,
    }


def append_snapshot(snap: dict, *, path: Path = SNAPSHOT_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(snap, ensure_ascii=False, default=str) + "\n")
    except OSError:
        logger.exception("bot_brain.append_snapshot_failed")


async def run_loop(stop_event: asyncio.Event, *, interval_sec: int = DEFAULT_INTERVAL_SEC,
                   path: Path = SNAPSHOT_PATH) -> None:
    """Async loop — collect + append snapshot every interval_sec until stop_event."""
    logger.info("bot_brain.state.start interval=%ds path=%s", interval_sec, path)
    while not stop_event.is_set():
        try:
            snap = collect_snapshot()
            append_snapshot(snap, path=path)
        except Exception:
            logger.exception("bot_brain.state.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("bot_brain.state.stopped")


if __name__ == "__main__":
    # CLI smoke test
    import sys
    snap = collect_snapshot()
    json.dump(snap, sys.stdout, indent=2, default=str, ensure_ascii=False)
    sys.stdout.write("\n")
