"""IO + луп alt-momentum shadow: дневной ребаланс, журнал, дозаполнение 24ч-исхода,
тег режима (BTC.D). Тихо — без TG-спама (итог копится для cross-cycle ревью)."""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from services.alt_momentum_shadow.signal import select, portfolio_return

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
JOURNAL = ROOT / "state" / "alt_momentum_shadow.jsonl"
STATE = ROOT / "state" / "alt_momentum_shadow_state.json"
DERIV = ROOT / "state" / "deriv_live.json"

UA = {"User-Agent": "Mozilla/5.0"}
N_ALTS = 20
K = 4                  # лонг топ-K / шорт низ-K
LOOKBACK_BARS = 6      # 24ч на 4ч-барах
HOLD_BARS = 6          # холд 24ч
POLL_INTERVAL_SEC = 3600
STABLE = {"USDC", "USDE", "DAI", "TUSD", "FDUSD", "USDT", "USD1"}


def _get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20))


def _top_alts(n=N_ALTS):
    rows = _get("https://api.bybit.com/v5/market/tickers?category=linear").get("result", {}).get("list", [])
    perps = []
    for r in rows:
        s = r.get("symbol", "")
        if not s.endswith("USDT") or s[:-4] in ({"BTC"} | STABLE):
            continue
        try:
            perps.append((s, float(r.get("turnover24h") or 0)))
        except ValueError:
            pass
    perps.sort(key=lambda x: -x[1])
    return [s for s, _ in perps[:n]]


def _closes(sym, n=40):
    d = _get(f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}&interval=240&limit={n}")
    lst = d.get("result", {}).get("list", [])
    return {int(x[0]): float(x[4]) for x in lst}


def _btc_dominance() -> float | None:
    try:
        raw = DERIV.read_text(encoding="utf-8")
        import re
        m = re.search(r'"btc_dominance_pct"\s*:\s*([0-9.]+)', raw)
        return float(m.group(1)) if m else None
    except OSError:
        return None


def _read_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(s):
    try:
        STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        logger.exception("alt_momentum.state_write_failed")


def _read_journal() -> list[dict]:
    if not JOURNAL.exists():
        return []
    out = []
    for ln in JOURNAL.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return out


def _write_journal(recs):
    with JOURNAL.open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _excess_now(btc, series) -> dict:
    """{sym: доход_альта(LOOKBACK) − доход_BTC(LOOKBACK), %} по последнему общему бару."""
    bt = sorted(btc)
    if len(bt) < LOOKBACK_BARS + 1:
        return {}
    out = {}
    for sym, sc in series.items():
        common = sorted(set(btc) & set(sc))
        if len(common) < LOOKBACK_BARS + 1:
            continue
        i = common[-1]
        j = common[-1 - LOOKBACK_BARS]
        out[sym] = 100 * ((sc[i] / sc[j] - 1) - (btc[i] / btc[j] - 1))
    return out


def rebalance(now: datetime | None = None) -> dict | None:
    """Дневной ребаланс: ранжируем, фиксируем портфель + entry-цены + режим."""
    now = now or datetime.now(timezone.utc)
    state = _read_state()
    today = now.date().isoformat()
    if state.get("last_rebalance") == today:
        return None
    btc = _closes("BTCUSDT")
    alts = _top_alts()
    series = {}
    entry_px = {}
    for s in alts:
        try:
            c = _closes(s)
            if c:
                series[s] = c
                entry_px[s] = c[max(c)]
            time.sleep(0.08)
        except Exception:
            pass
    excess = _excess_now(btc, series)
    longs, shorts = select(excess, K)
    if not longs or not shorts:
        return None
    dom = _btc_dominance()
    prev_dom = state.get("last_dom")
    dom_trend = ("rising" if prev_dom and dom and dom > prev_dom + 0.1 else
                 "falling" if prev_dom and dom and dom < prev_dom - 0.1 else "flat")
    rec = {
        "id": f"am_{today}", "date": today, "ts_utc": now.isoformat(timespec="seconds"),
        "longs": [(s, round(entry_px[s], 6), round(excess[s], 2)) for s in longs],
        "shorts": [(s, round(entry_px[s], 6), round(excess[s], 2)) for s in shorts],
        "btc_entry": round(btc[max(btc)], 1),
        "btc_dominance": dom, "dom_trend": dom_trend,
        "regime": "dominance(моментум↓)" if dom_trend == "rising" else "alt-active(моментум↑)",
        "outcome": None,
    }
    recs = _read_journal()
    recs.append(rec)
    _write_journal(recs)
    state["last_rebalance"] = today
    state["last_dom"] = dom
    _write_state(state)
    logger.info("alt_momentum.rebalance L=%s S=%s dom=%.1f(%s)",
                longs, shorts, dom or 0, dom_trend)
    return rec


def fill_outcomes(now: datetime | None = None) -> int:
    """Дозаполнить 24ч-исход портфелей, где прошёл холд."""
    now = now or datetime.now(timezone.utc)
    recs = _read_journal()
    if not recs:
        return 0
    btc = _closes("BTCUSDT")
    updated = 0
    cache: dict[str, dict] = {}
    for r in recs:
        if r.get("outcome") is not None:
            continue
        try:
            entry_ts = datetime.fromisoformat(r["ts_utc"])
        except ValueError:
            continue
        if (now - entry_ts).total_seconds() < HOLD_BARS * 4 * 3600:
            continue  # холд ещё не прошёл
        bt = sorted(btc)
        if not bt:
            continue
        btc_ret = btc[bt[-1]] / r["btc_entry"] - 1

        def leg_excess(items):
            xs = []
            for sym, epx, _eb in items:
                if sym not in cache:
                    try:
                        cache[sym] = _closes(sym)
                    except Exception:
                        cache[sym] = {}
                c = cache[sym]
                if c:
                    xs.append(100 * ((c[max(c)] / epx - 1) - btc_ret))
            return xs

        le = leg_excess(r["longs"]); se = leg_excess(r["shorts"])
        pr = portfolio_return(le, se)
        if pr:
            r["outcome"] = pr
            updated += 1
    if updated:
        _write_journal(recs)
    return updated


async def alt_momentum_shadow_loop(stop_event, *, interval_sec=POLL_INTERVAL_SEC):
    import asyncio
    logger.info("alt_momentum_shadow.start interval=%ds top-%d L/S=%d (форвард, без денег)",
                interval_sec, N_ALTS, K)
    while not stop_event.is_set():
        try:
            rebalance()
            fill_outcomes()
        except Exception:
            logger.exception("alt_momentum_shadow.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("alt_momentum_shadow.stopped")
