"""Детект liq-свипа + обогащение OI/funding/taker → скальп-пинг."""
from __future__ import annotations

import csv
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
LIQ_CSV = ROOT / "market_live" / "liquidations.csv"
DERIV = ROOT / "state" / "deriv_live.json"
STATE = ROOT / "state" / "scalp_liq_state.json"

WINDOW_MIN = 3          # окно кластера
THRESHOLD_BTC = 1.5     # ∑ ликвидаций одной стороны за окно = свип (выше grid-порога 0.5)
COOLDOWN_SEC = 900      # 15 мин на сторону
POLL_INTERVAL_SEC = 90


def _read_recent(now: datetime) -> list[tuple[str, float, float]]:
    """[(side, qty, price)] валидных ликвидаций за окно."""
    if not LIQ_CSV.exists():
        return []
    cutoff = now - timedelta(minutes=WINDOW_MIN)
    out = []
    try:
        size = LIQ_CSV.stat().st_size
        with LIQ_CSV.open("rb") as fh:
            if size > 500_000:
                fh.seek(size - 500_000); fh.readline()
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
        for rec in csv.reader(lines):
            if len(rec) != 5 or rec[0] == "ts_utc":
                continue
            try:
                ts = datetime.fromisoformat(rec[0])
                side = rec[2]; qty = float(rec[3]); price = float(rec[4])
            except (ValueError, IndexError):
                continue
            if ts >= cutoff and qty > 0 and price > 0 and side in ("long", "short"):
                out.append((side, qty, price))
    except OSError:
        pass
    return out


def _cluster(liqs) -> dict:
    """{side: (qty_sum, vwap)} по сторонам."""
    agg = {}
    for side in ("long", "short"):
        rows = [(q, p) for s, q, p in liqs if s == side]
        if not rows:
            continue
        qsum = sum(q for q, _ in rows)
        vwap = sum(q * p for q, p in rows) / qsum
        agg[side] = (qsum, vwap)
    return agg


def _deriv_ctx() -> dict:
    try:
        raw = DERIV.read_text(encoding="utf-8")
    except OSError:
        return {}
    m = re.search(r'"BTCUSDT"\s*:\s*\{(.*?)\}', raw, re.DOTALL)
    blob = m.group(1) if m else raw

    def f(key):
        mm = re.search(rf'"{key}"\s*:\s*(-?[0-9.eE+-]+)', blob)
        try:
            return float(mm.group(1)) if mm else None
        except ValueError:
            return None
    return {"oi_1h": f("oi_change_1h_pct"), "funding": f("funding_rate_8h"),
            "taker": f("taker_buy_pct"), "ls": f("global_ls_ratio")}


def build_card(side: str, qty: float, price: float, ctx: dict) -> str:
    # long-liq = лонги выбиты (форс-продажи, цена вниз) → свип ПОДДЕРЖКИ, жди отбой ВВЕРХ
    # short-liq = шорты выбиты (форс-покупки, цена вверх) → свип СОПРОТИВЛЕНИЯ, жди откат ВНИЗ
    if side == "long":
        head = f"💥 LIQ-СВИП: {qty:.2f} BTC ЛОНГОВ выбито @ ${price:,.0f}"
        read = "свип ПОДДЕРЖКИ (форс-продажи) → классич. зона отбоя ВВЕРХ"
    else:
        head = f"💥 LIQ-СВИП: {qty:.2f} BTC ШОРТОВ выбито @ ${price:,.0f}"
        read = "свип СОПРОТИВЛЕНИЯ (форс-покупки) → классич. зона отката ВНИЗ"
    L = [head, read]
    oi = ctx.get("oi_1h"); fund = ctx.get("funding"); tk = ctx.get("taker")
    cbits = []
    if oi is not None:
        cbits.append(f"OI 1ч {oi:+.2f}% ({'делеверидж→истощение' if oi < -0.3 else 'набор→тренд' if oi > 0.3 else 'нейтр'})")
    if fund is not None:
        cbits.append(f"funding {fund*100:+.4f}%")
    if tk is not None:
        cbits.append(f"taker buy {tk:.0f}%")
    if cbits:
        L.append("   " + " · ".join(cbits))
    L.append("   сверь с /levels (какая 🧱 свипнута); вход — по стакану CScalp, не по пингу.")
    return "\n".join(L)


def _read_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(s):
    try:
        STATE.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def detect(send_fn, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    liqs = _read_recent(now)
    if not liqs:
        return []
    clusters = _cluster(liqs)
    state = _read_state()
    fired = []
    ctx = None
    for side, (qsum, vwap) in clusters.items():
        if qsum < THRESHOLD_BTC:
            continue
        last = state.get(f"last_{side}")
        if last:
            try:
                if (now - datetime.fromisoformat(last)).total_seconds() < COOLDOWN_SEC:
                    continue
            except ValueError:
                pass
        if ctx is None:
            ctx = _deriv_ctx()
        text = build_card(side, qsum, vwap, ctx)
        logger.warning("scalp_liq.sweep %s %.2fBTC @%.0f", side, qsum, vwap)
        if send_fn:
            try:
                send_fn(text)
            except Exception:
                logger.exception("scalp_liq.send_failed")
        state[f"last_{side}"] = now.isoformat(timespec="seconds")
        fired.append(text)
    _write_state(state)
    return fired


async def scalp_liq_loop(stop_event, *, send_fn=None, interval_sec=POLL_INTERVAL_SEC):
    import asyncio
    logger.info("scalp_liq.start interval=%ds threshold=%.1fBTC/%dmin tg=%s",
                interval_sec, THRESHOLD_BTC, WINDOW_MIN, "ON" if send_fn else "off")
    while not stop_event.is_set():
        try:
            detect(send_fn)
        except Exception:
            logger.exception("scalp_liq.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("scalp_liq.stopped")
