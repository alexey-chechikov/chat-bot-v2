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
JOURNAL = ROOT / "state" / "scalp_liq_journal.jsonl"   # исходы свипов — проверяемый эдж
MARKET_1M = ROOT / "market_live" / "market_1m.csv"

WINDOW_MIN = 3          # окно кластера
THRESHOLD_BTC = 1.5     # ∑ ликвидаций одной стороны за окно = свип (выше grid-порога 0.5)
COOLDOWN_SEC = 900      # 15 мин на сторону — журналирование (данные копим полностью)
POLL_INTERVAL_SEC = 90
HORIZONS_MIN = {"15м": 15, "30м": 30, "60м": 60}   # отбой через сколько мерим

# TG-гейт (2026-07-07): при пороге 1.5 уходило до 47 карточек/день с медианой 18 мин —
# оператор читал это как «одно и то же каждые полчаса». Журналим по-прежнему всё ≥1.5
# (исследовательские данные), но в TG шлём только крупняк и нечасто; эскалация ≥2×
# пробивает cooldown, чтобы 20 BTC после 10 BTC не молчал.
# 2026-07-14: оператор — «карточек и так перебор»; гейт 5.0/2ч давал 5.1/день на
# свипастой неделе → поднято до 10 BTC / 3ч (~2.5-3/день, только крупные каскады).
SEND_MIN_QTY_BTC = 10.0
SEND_COOLDOWN_SEC = 10800
SEND_ESCALATION_MULT = 2.0
STATS_MIN_N = 30        # живая стата в карточке только при достаточной выборке


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


def _live_stats(side: str) -> dict | None:
    """Живой эдж стороны из собственного журнала: доля ПРОДОЛЖЕНИЯ @30м.

    Исход в журнале записан со знаком «в пользу отбоя», поэтому continuation = v < 0.
    2026-07-07, 222 свипа: отбой после long-liq всего 37% @30м, после short-liq 42% —
    классическое чтение «свип → разворот» живыми данными опровергнуто, свип = continuation.
    """
    try:
        lines = JOURNAL.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    vals = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if r.get("side") != side:
            continue
        v = (r.get("outcomes") or {}).get("30м")
        if isinstance(v, (int, float)):
            vals.append(v)
    if len(vals) < STATS_MIN_N:
        return None
    cont = sum(1 for v in vals if v < 0)
    return {"n": len(vals), "cont_wr": cont / len(vals) * 100.0,
            "avg_move": -sum(vals) / len(vals)}


def build_card(side: str, qty: float, price: float, ctx: dict,
               stats: dict | None = None) -> str:
    # long-liq = лонги выбиты (форс-продажи) — по живому журналу цена ЧАЩЕ ПРОДОЛЖАЕТ вниз
    # short-liq = шорты выбиты (сквиз) — чаще продолжает вверх. Continuation, не reversal.
    if side == "long":
        head = f"💥 LIQ-СВИП: {qty:.2f} BTC ЛОНГОВ выбито @ ${price:,.0f}"
        read = "лонги горят → давление ВНИЗ обычно ПРОДОЛЖАЕТСЯ (это НЕ зона лонга)"
        move = "вниз"
    else:
        head = f"💥 LIQ-СВИП: {qty:.2f} BTC ШОРТОВ выбито @ ${price:,.0f}"
        read = "шорты горят (сквиз) → движение ВВЕРХ обычно ПРОДОЛЖАЕТСЯ (это НЕ зона шорта)"
        move = "вверх"
    L = [head, read]
    if stats:
        L.append(f"   живой журнал ({stats['n']} свипов): продолжение {move} "
                 f"{stats['cont_wr']:.0f}% @30м, в среднем ещё {stats['avg_move']:+.2f}%")
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
    L.append("   это предупреждение для гридов/мешков, НЕ сигнал входа; контр-тренд — "
             "только ПОСЛЕ разворота дельты в стакане CScalp. Сверь с /levels.")
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


def _btc_price_now() -> float | None:
    """Последний close BTC из локального коллектора."""
    if not MARKET_1M.exists():
        return None
    try:
        size = MARKET_1M.stat().st_size
        with MARKET_1M.open("rb") as fh:
            if size > 4000:
                fh.seek(size - 4000); fh.readline()
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
        for line in reversed(lines):
            p = line.split(",")
            if len(p) >= 5 and p[0].startswith("20"):
                return float(p[4])
    except (OSError, ValueError):
        pass
    return None


def _journal_append(rec: dict) -> None:
    try:
        with JOURNAL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("scalp_liq.journal_failed")


def fill_outcomes(now: datetime | None = None) -> int:
    """Дозаполнить исход свипа: отбила ли цена в ожидаемую сторону через 15/30/60м.
    long-liq (свип поддержки) → ждём ВВЕРХ; short-liq → ВНИЗ. Знак = в пользу свипа."""
    now = now or datetime.now(timezone.utc)
    if not JOURNAL.exists():
        return 0
    recs = []
    for ln in JOURNAL.read_text(encoding="utf-8").splitlines():
        try:
            recs.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    px_now = _btc_price_now()
    if px_now is None:
        return 0
    updated = 0
    for r in recs:
        need = [h for h in HORIZONS_MIN if h not in (r.get("outcomes") or {})]
        if not need:
            continue
        try:
            ts = datetime.fromisoformat(r["ts"])
        except (ValueError, KeyError):
            continue
        age = (now - ts).total_seconds() / 60.0
        d = 1 if r["side"] == "long" else -1   # ожидаемое направление отбоя
        for h, hm in HORIZONS_MIN.items():
            if h in (r.get("outcomes") or {}):
                continue
            if age >= hm:
                ret = d * (px_now / r["price"] - 1) * 100
                r.setdefault("outcomes", {})[h] = round(ret, 3)
                updated += 1
    if updated:
        with JOURNAL.open("w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return updated


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
        logger.warning("scalp_liq.sweep %s %.2fBTC @%.0f", side, qsum, vwap)
        state[f"last_{side}"] = now.isoformat(timespec="seconds")
        _journal_append({"id": f"sl_{int(now.timestamp())}_{side}",
                         "ts": now.isoformat(timespec="seconds"), "side": side,
                         "qty": round(qsum, 3), "price": round(vwap, 1),
                         "ctx": ctx, "outcomes": {}})

        # TG-гейт: только крупняк, не чаще SEND_COOLDOWN_SEC на сторону;
        # эскалация ≥2× последней отправленной qty пробивает cooldown
        if qsum < SEND_MIN_QTY_BTC:
            continue
        last_sent = state.get(f"last_sent_{side}")
        if last_sent:
            try:
                in_cd = (now - datetime.fromisoformat(last_sent)).total_seconds() < SEND_COOLDOWN_SEC
            except ValueError:
                in_cd = False
            if in_cd and qsum < SEND_ESCALATION_MULT * (state.get(f"last_sent_qty_{side}") or 0):
                continue
        text = build_card(side, qsum, vwap, ctx, stats=_live_stats(side))
        if send_fn:
            try:
                send_fn(text)
            except Exception:
                logger.exception("scalp_liq.send_failed")
        state[f"last_sent_{side}"] = now.isoformat(timespec="seconds")
        state[f"last_sent_qty_{side}"] = round(qsum, 3)
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
            fill_outcomes()
        except Exception:
            logger.exception("scalp_liq.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("scalp_liq.stopped")
