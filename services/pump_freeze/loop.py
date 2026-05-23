"""Pump-freeze async loop — bidirectional + multi-symbol.

For each bot in APPLIES_TO_BOTS:
  (side, symbol): freeze on an adverse ±1.5%/30m move in THAT symbol's bars.
  side='short' → freeze on up-pump; side='long' → freeze on down-dump.
  Legacy string value (no symbol) defaults to BTCUSDT.

ML resume-gate stays BTC-only — the trained GBM is BTC-trained, ETH/XRP
get reactive-only protection until per-symbol catalogs/models exist (Phase B/C).
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from services.pump_freeze.config import (
    APPLIES_TO_BOTS,
    ML_GATE_ENABLED,
    MIN_POSITION_USD_TO_TRIGGER,
    PUMP_COOLDOWN_MIN,
    REFREEZE_RETURN_PCT,
    RESUME_RETRACEMENT_PCT,
    RESUME_STALL_MIN,
    RESUME_TIMEOUT_HOURS,
    TICK_INTERVAL_SEC,
)
from services.pump_freeze.detector import detect_move, should_resume
from services.pump_freeze.freezer import (
    freeze,
    frozen_info,
    get_extreme_during_freeze,
    get_last_extreme_ts,
    is_frozen,
    last_resume_info,
    last_resume_ts,
    position_usd_abs,
    resume,
    update_extreme,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MARKET_1M_CSV = ROOT / "market_live" / "market_1m.csv"
SNAPSHOTS_CSV = ROOT / "ginarea_live" / "snapshots.csv"
MANAGED_JSON = ROOT / "state" / "short_bots_managed.json"


_SPOT_KLINES_URL = "https://api.binance.com/api/v3/klines"


def _parse_scope_value(v) -> tuple[str, str]:
    """APPLIES_TO_BOTS value -> (side, symbol).

    Backward-compat: a bare string is the legacy BTC form -> (side, "BTCUSDT");
    a tuple/list is the multi-symbol form -> (side, symbol).
    """
    if isinstance(v, str):
        return v, "BTCUSDT"
    return v[0], v[1]


def _fetch_klines_binance(symbol: str, limit: int = 35) -> list:
    """Fetch the most-recent `limit` 1m klines from Binance spot.
    Returns [(ts, high, low, close), ...] — matching _load_recent_bars's shape.
    Empty list on failure (loop treats it as "insufficient bars", no-op)."""
    url = f"{_SPOT_KLINES_URL}?symbol={symbol}&interval=1m&limit={limit}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            raw = json.load(r)
    except Exception:  # noqa: BLE001
        return []
    out: list = []
    for k in raw:
        try:
            ts = datetime.utcfromtimestamp(int(k[0]) / 1000).replace(tzinfo=timezone.utc)
            out.append((ts, float(k[2]), float(k[3]), float(k[4])))
        except (ValueError, IndexError):
            continue
    return out


def _fetch_klines_binance_rich(symbol: str, needed: int = 1600) -> list:
    """Deep paginated 1m kline fetch returning (ts,open,high,low,close,volume).
    Binance limit is 1000/call — chains 2 calls for the ~1600-bar feature
    window. Returns chronological. Empty list on any failure."""
    def _parse(raw):
        rows = []
        for k in raw:
            try:
                ts = datetime.utcfromtimestamp(int(k[0]) / 1000).replace(tzinfo=timezone.utc)
                rows.append((ts, float(k[1]), float(k[2]), float(k[3]),
                             float(k[4]), float(k[5])))
            except (ValueError, IndexError):
                continue
        return rows

    n1 = min(needed, 1000)
    url1 = f"{_SPOT_KLINES_URL}?symbol={symbol}&interval=1m&limit={n1}"
    try:
        with urllib.request.urlopen(url1, timeout=10) as r:
            recent = _parse(json.load(r))
    except Exception:  # noqa: BLE001
        return []
    if not recent:
        return []
    rem = needed - len(recent)
    before: list = []
    if rem > 0:
        oldest_ms = int(recent[0][0].timestamp() * 1000)
        end_ms = oldest_ms - 60_000
        n2 = min(rem, 1000)
        start_ms = end_ms - n2 * 60_000
        url2 = (f"{_SPOT_KLINES_URL}?symbol={symbol}&interval=1m"
                f"&startTime={start_ms}&endTime={end_ms}&limit={n2}")
        try:
            with urllib.request.urlopen(url2, timeout=10) as r:
                before = _parse(json.load(r))
        except Exception:  # noqa: BLE001
            before = []
    out = before + recent
    out.sort(key=lambda x: x[0])
    return out


def _load_recent_bars(needed_min: int = 35, symbol: str = "BTCUSDT") -> list:
    """Recent 1m bars (ts, high, low, close) for `symbol`.

    BTCUSDT — reads market_live/market_1m.csv (the bot's collector writes it;
    pump_freeze has always used this feed).
    ETHUSDT / XRPUSDT — fetched directly from Binance spot klines, since no
    local per-symbol bar store exists yet. Cheap (limit=35 -> ~5KB) and called
    at most once per symbol per 60s tick.
    """
    if symbol == "BTCUSDT":
        if not MARKET_1M_CSV.exists():
            return []
        bars: list = []
        try:
            with MARKET_1M_CSV.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        ts = datetime.fromisoformat(row["ts_utc"].replace("Z", "+00:00"))
                        hi = float(row["high"]); lo = float(row["low"]); cl = float(row["close"])
                        bars.append((ts, hi, lo, cl))
                    except (KeyError, ValueError):
                        continue
        except OSError:
            return []
        return bars[-needed_min:] if len(bars) > needed_min else bars
    return _fetch_klines_binance(symbol, needed_min)


def _read_bot_meta(bot_id: str) -> tuple[Optional[float], str, str]:
    """Latest raw position + alias + tier."""
    pos = None
    if SNAPSHOTS_CSV.exists():
        try:
            with SNAPSHOTS_CSV.open("rb") as f:
                f.seek(0, 2); size = f.tell()
                f.seek(max(0, size - 200_000))
                tail = f.read().decode("utf-8", errors="ignore")
            lines = tail.splitlines()[1:]
            with SNAPSHOTS_CSV.open("r", encoding="utf-8") as fh:
                header = next(csv.reader(fh))
            for row in csv.reader(lines):
                if len(row) != len(header):
                    continue
                r = dict(zip(header, row))
                if str(r.get("bot_id", "")).split(".")[0] != bot_id:
                    continue
                try:
                    pos = float(r.get("position", "") or 0)
                except ValueError:
                    pass
        except OSError:
            pass
    alias, tier = bot_id, bot_id
    if MANAGED_JSON.exists():
        try:
            mgd = json.loads(MANAGED_JSON.read_text(encoding="utf-8"))
            for entry in mgd.get("managed_bots", []):
                if str(entry.get("bot_id")) == bot_id:
                    alias = entry.get("alias", bot_id)
                    tier = entry.get("tier", bot_id)
                    break
        except (OSError, json.JSONDecodeError):
            pass
    return pos, alias, tier


def _api_pause(bot_id: int) -> dict:
    from services.short_bots_guard.control import _build_api
    api, err = _build_api()
    if api is None:
        raise RuntimeError(f"api_build_failed: {err}")
    return api.pause_bot(bot_id)


def _api_resume(bot_id: int) -> dict:
    from services.short_bots_guard.control import _build_api
    api, err = _build_api()
    if api is None:
        raise RuntimeError(f"api_build_failed: {err}")
    return api.resume_bot(bot_id)


def _median(xs: list) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2.0


def _load_feature_bars(needed: int = 1600, symbol: str = "BTCUSDT") -> list:
    """Rich 1m bars (ts, open, high, low, close, volume) for the ML feature
    pipeline — longer history + open/volume.

    BTCUSDT — reads market_live/market_1m.csv (bot's collector writes it).
    ETHUSDT / XRPUSDT — fetched directly from Binance (2 paginated calls
    for the ~1600-bar window). Called ~once per freeze on a frozen bot
    (after horizon_min=60 elapses), so the ~1-2s network hit is acceptable.
    """
    if symbol != "BTCUSDT":
        return _fetch_klines_binance_rich(symbol, needed)
    if not MARKET_1M_CSV.exists():
        return []
    bars: list = []
    try:
        with MARKET_1M_CSV.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    ts = datetime.fromisoformat(row["ts_utc"].replace("Z", "+00:00"))
                    bars.append((ts, float(row["open"]), float(row["high"]),
                                 float(row["low"]), float(row["close"]),
                                 float(row["volume"])))
                except (KeyError, ValueError):
                    continue
    except OSError:
        return []
    return bars[-needed:] if len(bars) > needed else bars


def _funding_at(freeze_ts: datetime, symbol: str = "BTCUSDT") -> Optional[float]:
    """funding_rate_8h for `symbol` from deriv_live_history.jsonl — the record
    nearest freeze_ts. Funding is 8h-constant so ~5min log resolution is
    ample. None if unavailable. deriv_live_history records all three symbols
    (BTC/ETH/XRP), so this works transparently for the multi-symbol case."""
    path = ROOT / "state" / "deriv_live_history.jsonl"
    if not path.exists():
        return None
    best: Optional[tuple] = None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts = datetime.fromisoformat(
                    rec["last_updated"].replace("Z", "+00:00"))
                fr = (rec.get(symbol) or {}).get("funding_rate_8h")
                if fr is None:
                    continue
                d = abs((ts - freeze_ts).total_seconds())
                if best is None or d < best[0]:
                    best = (d, float(fr))
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                continue
    except OSError:
        return None
    return best[1] if best else None


def _compute_bar_features(bars: list, freeze_ts: datetime,
                          window: int = 30) -> dict:
    """The 8 bar-derived reliable features — computed to match
    build_event_catalog.py profile_event() column-for-column.

    `bars`: (ts, open, high, low, close, volume), chronological. Returns {}
    when the freeze anchor or required history is missing; omits any single
    feature it cannot compute (→ score_event None → gate dormant — safe).
    """
    feats: dict = {}
    if len(bars) < window + 3:
        return feats
    # anchor = last bar at/before freeze_ts
    a = None
    for i in range(len(bars) - 1, -1, -1):
        if bars[i][0] <= freeze_ts:
            a = i
            break
    if a is None or a < window:
        return feats
    op = [b[1] for b in bars]
    hi = [b[2] for b in bars]
    lo = [b[3] for b in bars]
    cl = [b[4] for b in bars]
    vol = [b[5] for b in bars]
    n = len(bars)
    ws = a - window
    trig = cl[a]
    if trig <= 0 or cl[ws] <= 0:
        return feats

    feats["move_pct"] = (trig - cl[ws]) / cl[ws] * 100.0

    wick = [hi[i] - lo[i] for i in range(ws, a + 1)]
    body = [abs(cl[i] - op[i]) for i in range(ws, a + 1)]
    feats["wick_ratio"] = (sum(wick) / len(wick)) / (sum(body) / len(body) + 1e-9)

    w = cl[ws:a + 1]
    d2 = [w[i + 2] - 2 * w[i + 1] + w[i] for i in range(len(w) - 2)]
    feats["accel"] = sum(abs(x) for x in d2) / len(d2) if d2 else 0.0

    win_vol = sum(vol[ws:a + 1])
    look = vol[max(0, a - 1440):a]
    base = _median(look) * window if look else 0.0
    if base > 0:
        feats["vol_spike"] = win_vol / base

    for h in (5, 15, 30, 60):
        j = min(a + h, n - 1)
        feats[f"move_t{h}"] = (cl[j] - trig) / trig * 100.0

    return feats


def build_live_features(bot_id: str, freeze_ts: datetime,
                        symbol: str = "BTCUSDT") -> dict:
    """Live feature vector for the ML resume-gate — 9 of the 10 reliable
    features from PUMP_FILTER_FEATURE_CONTRACT.md, matching
    build_event_catalog.py column-for-column. Symbol-aware: BTC reads the
    local 1m feed, ETH/XRP fetch from Binance.

    OMITTED: n_triggers — catalog-only quantity with no clean live equivalent;
    any model whose feature_order includes it stays dormant by design.
    """
    feats = _compute_bar_features(_load_feature_bars(symbol=symbol), freeze_ts)
    if not feats:
        return {}
    fr = _funding_at(freeze_ts, symbol)
    if fr is not None:
        feats["funding_at_anchor"] = fr
    return feats


def _ml_gate_check(bot_id: str, side: str, freeze_ts: datetime,
                   now: datetime, bars: list,
                   symbol: str = "BTCUSDT") -> Optional[str]:
    """Return a resume-reason string if the ML-gate confidently calls the
    frozen event a whipsaw; else None (→ reactive logic decides).

    Symbol-aware: for non-BTC symbols build_live_features() returns {} →
    score None → the gate stays dormant on ETH/XRP until per-symbol models
    (Phase B/C) are trained. The BTC bot path is unchanged.
    """
    if not ML_GATE_ENABLED:
        return None
    from services.pump_freeze import resume_model
    if not resume_model.model_available(symbol):
        return None
    age_min = (now - freeze_ts).total_seconds() / 60.0
    if age_min < resume_model.horizon_min(symbol):
        return None
    feats = build_live_features(bot_id, freeze_ts, symbol)
    score = resume_model.score_event(feats, symbol)
    if score is None:
        return None
    if resume_model.gate_decision(score, symbol) == "whipsaw":
        return f"ml_gate: whipsaw P={score:.2f} @age{age_min:.0f}m sym={symbol}"
    return None


def tick(*, send_fn: Optional[Callable] = None,
         now: Optional[datetime] = None) -> dict:
    if now is None:
        now = datetime.now(timezone.utc)

    # Per-tick per-symbol caches: each symbol's bars + detected events are
    # computed at most once even if several bots share it.
    bars_cache: dict = {}
    events_cache: dict = {}

    def _bars_for(sym: str) -> list:
        if sym not in bars_cache:
            bars_cache[sym] = _load_recent_bars(symbol=sym)
        return bars_cache[sym]

    def _events_for(sym: str) -> dict:
        if sym not in events_cache:
            bs = _bars_for(sym)
            if len(bs) < 31:
                events_cache[sym] = {"up": None, "down": None}
            else:
                events_cache[sym] = {
                    "up": detect_move(bs, direction="up"),
                    "down": detect_move(bs, direction="down"),
                }
        return events_cache[sym]

    frozen_count = 0
    resumed_count = 0
    for bot_id, raw_val in APPLIES_TO_BOTS.items():
        side, symbol = _parse_scope_value(raw_val)
        bars = _bars_for(symbol)
        if len(bars) < 31:
            continue
        current_price = bars[-1][3]

        raw_pos, alias, tier = _read_bot_meta(bot_id)
        if raw_pos is None:
            continue

        if is_frozen(bot_id):
            update_extreme(bot_id, current_price, side, now=now)
            fz = frozen_info(bot_id)
            try:
                freeze_ts = datetime.fromisoformat(fz["freeze_ts"])
            except (KeyError, ValueError):
                continue
            done, reason = should_resume(
                freeze_extreme_price=get_extreme_during_freeze(bot_id),
                current_price=current_price,
                freeze_ts=freeze_ts, now=now, side=side,
                retrace_pct=RESUME_RETRACEMENT_PCT,
                timeout_hours=RESUME_TIMEOUT_HOURS,
                last_extreme_ts=get_last_extreme_ts(bot_id),
                stall_min=RESUME_STALL_MIN,
            )
            # ML resume-gate (Phase 4): if reactive says hold, a confident
            # whipsaw verdict resumes early. BTC-only; non-BTC dormant until
            # per-symbol models (Phase B/C).
            if not done:
                ml_reason = _ml_gate_check(bot_id, side, freeze_ts, now,
                                            bars, symbol)
                if ml_reason:
                    done, reason = True, ml_reason
            if done:
                resume(bot_id=bot_id, alias=alias, tier=tier, side=side,
                       current_price=current_price, resume_reason=reason,
                       extreme_during_freeze=get_extreme_during_freeze(bot_id),
                       resume_api_fn=_api_resume, send_fn=send_fn, now=now)
                resumed_count += 1
            continue

        # Direction relevant to this bot — picked from per-symbol events
        evs = _events_for(symbol)
        event = evs["up"] if side == "short" else evs["down"]
        if event is None:
            continue

        # Re-freeze gate (2026-05-22 pullback research): time-cooldown заменён
        # price-based gate. После resume не фризим заново на том же откате —
        # ждём пока цена вернётся ≥REFREEZE_RETURN_PCT% к extreme движения
        # (возврат к hi для SHORT / к lo для LONG). Это «дыхание»: пауза на
        # росте к hi, работа на откате. Time-cooldown душил повторный freeze
        # на затяжном тренде, оставляя бота незащищённым.
        if PUMP_COOLDOWN_MIN > 0:
            last_resume = last_resume_ts(bot_id)
            if last_resume is not None:
                elapsed_min = (now - last_resume).total_seconds() / 60.0
                if elapsed_min < PUMP_COOLDOWN_MIN:
                    continue

        ri = last_resume_info(bot_id)
        if ri is not None:
            resume_price = float(ri.get("resume_price", 0) or 0)
            if resume_price > 0:
                if side == "short":
                    back_pct = (current_price - resume_price) / resume_price * 100.0
                else:
                    back_pct = (resume_price - current_price) / resume_price * 100.0
                # цена ещё не вернулась к extreme-стороне — не re-freeze
                if back_pct < REFREEZE_RETURN_PCT:
                    continue

        pos_usd = position_usd_abs(raw_pos, side, current_price)
        if pos_usd < MIN_POSITION_USD_TO_TRIGGER:
            continue

        freeze(bot_id=bot_id, alias=alias, tier=tier, side=side,
               event=event, raw_position=raw_pos, position_usd=pos_usd,
               pause_api_fn=_api_pause, send_fn=send_fn, now=now)
        frozen_count += 1

    return {"frozen": frozen_count, "resumed": resumed_count}


async def pump_freeze_loop(stop_event: asyncio.Event, *,
                            send_fn: Optional[Callable] = None,
                            interval_sec: int = TICK_INTERVAL_SEC) -> None:
    logger.info("pump_freeze.loop.start interval=%ds applies_to=%s",
                interval_sec, list(APPLIES_TO_BOTS.items()))
    while not stop_event.is_set():
        try:
            r = tick(send_fn=send_fn)
            if r["frozen"] or r["resumed"]:
                logger.info("pump_freeze.tick frozen=%d resumed=%d",
                            r["frozen"], r["resumed"])
        except Exception:
            logger.exception("pump_freeze.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()),
                                    timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("pump_freeze.loop.stopped")
