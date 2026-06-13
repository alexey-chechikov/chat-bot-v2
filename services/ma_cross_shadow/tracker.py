"""IO + луп MA-cross shadow: фетч 4ч (Bybit public) → assess_latest → журнал →
дозаполнение forward-исходов. Тихо (без TG, без ордеров)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from services.ma_cross_shadow.signal import assess_latest

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
JOURNAL = ROOT / "state" / "ma_cross_shadow.jsonl"
STATE = ROOT / "state" / "ma_cross_shadow_state.json"

SYMBOLS = ("BTCUSDT", "SOLUSDT", "XRPUSDT")
# 600 баров: seed-вес EMA200 ≈ 0.25% (при 260 было ~7.5% → флипал фильтр ② у линии,
# ревью Вина 2026-06-12). Bybit limit 1000. 600×4ч ≈ 100 дней — хватает и cross-to-cross.
BARS = 600
POLL_INTERVAL_SEC = 1800        # 30 мин (4ч-бары не спешат)
# 1 бар = 4ч (метка «6h» врала на 2ч — Вин). cross-to-cross = главный бенчмарк (см. detect).
HORIZONS_BARS = {"4h": 1, "12h": 3, "24h": 6, "48h": 12}
FEE_PCT = 0.10                  # %/реверс (как в бэктесте Win/Mac)
BYBIT_KLINE = "https://api.bybit.com/v5/market/kline"


def _fetch_4h(symbol: str, limit: int = BARS) -> list[list[float]] | None:
    """Bybit 4h, хронологически: [[ts_ms, o, h, l, c], ...]. None при ошибке."""
    import requests
    try:
        r = requests.get(BYBIT_KLINE, params={
            "category": "linear", "symbol": symbol, "interval": "240", "limit": limit + 1,
        }, timeout=12)
        r.raise_for_status()
        lst = r.json().get("result", {}).get("list", [])
        rows = [[int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4])] for x in lst]
        rows.sort(key=lambda x: x[0])
        return rows[:-1]  # дропаем незакрытый текущий бар
    except Exception:
        logger.exception("ma_shadow.fetch_failed symbol=%s", symbol)
        return None


def _read_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(s: dict) -> None:
    try:
        STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        logger.exception("ma_shadow.state_write_failed")


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


def _write_journal(recs: list[dict]) -> None:
    try:
        with JOURNAL.open("w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("ma_shadow.journal_write_failed")


def _close_prev_cross(recs: list[dict], symbol: str, new_close: float) -> None:
    """Главный бенчмарк (ревью Вина): новый кросс закрывает предыдущий сигнал символа
    полем outcome_cross = удержание до обратного кросса (как в бэктесте +117пп/PF 2.5)."""
    for r in reversed(recs):
        if r["symbol"] == symbol and "outcome_cross" not in r:
            d = 1 if r["dir"] == "LONG" else -1
            r["outcome_cross"] = round(d * (new_close / r["entry"] - 1) * 100 - FEE_PCT, 3)
            return


def detect(now: datetime | None = None) -> list[dict]:
    """Один проход: по каждому символу проверить последний закрытый 4ч-бар на кросс,
    записать новый сигнал (дедуп по ts бара) + закрыть предыдущий cross-to-cross."""
    now = now or datetime.now(timezone.utc)
    state = _read_state()
    seen = state.setdefault("last_bar_ts", {})
    recs = _read_journal()
    fired = []
    changed = False
    for sym in SYMBOLS:
        rows = _fetch_4h(sym)
        if not rows or len(rows) < 215:
            continue
        bar_ts = rows[-1][0]
        if seen.get(sym) == bar_ts:
            continue  # этот бар уже обработан
        seen[sym] = bar_ts
        highs = [r[2] for r in rows]
        lows = [r[3] for r in rows]
        closes = [r[4] for r in rows]
        sig = assess_latest(highs, lows, closes)
        if sig is None:
            continue
        # параллельный MA100-уклон (текущий грубый свитч) для head-to-head на ревью 26.06:
        # знак (close − SMA100) на баре кросса. Win/Mac: H5-уклон бьёт его (DD↓, флипов 5×↓).
        sma100 = sum(closes[-100:]) / 100
        ma100_lean = "LONG" if closes[-1] > sma100 else "SHORT"
        _close_prev_cross(recs, sym, sig["entry"])  # обратный кросс закрывает прошлый
        bar_iso = datetime.fromtimestamp(bar_ts / 1000, tz=timezone.utc).isoformat(timespec="seconds")
        entry = {
            "signal_id": f"mac_{sym}_{bar_ts}",
            "ts_utc": now.isoformat(timespec="seconds"),
            "bar_ts_utc": bar_iso,
            "symbol": sym,
            "dir": "LONG" if sig["direction"] == 1 else "SHORT",
            "passed_h5": sig["passed"],
            "skip_reasons": sig["reasons"],
            "entry": sig["entry"],
            "ema14": sig["ema14"], "ema77": sig["ema77"], "ema200": sig["ema200"],
            "slope77": sig["slope77"], "prev_leg_bars": sig["prev_leg_bars"],
            "stretch_pct": sig["stretch_pct"],
            "ma100_lean": ma100_lean,  # параллельный текущий свитч (head-to-head)
            "outcomes": {},          # forward 4/12/24/48ч
            # outcome_cross добавится, когда придёт обратный кросс
        }
        recs.append(entry)
        fired.append(entry)
        changed = True
        logger.info("ma_shadow.signal %s %s passed=%s entry=%s%s", sym, entry["dir"],
                    sig["passed"], sig["entry"],
                    "" if sig["passed"] else f" skip={sig['reasons']}")
    if changed:
        _write_journal(recs)
    _write_state(state)
    return fired


def fill_outcomes(now: datetime | None = None) -> int:
    """Дозаполнить forward-исходы по записанным сигналам, где прошёл горизонт.
    Переписывает журнал. Возвращает число обновлённых записей."""
    now = now or datetime.now(timezone.utc)
    recs = _read_journal()
    if not recs:
        return 0
    # текущие цены по символам (закрытие последнего бара)
    px_cache: dict[str, list[list[float]]] = {}
    updated = 0
    for r in recs:
        sym = r["symbol"]
        need = [h for h in HORIZONS_BARS if h not in r.get("outcomes", {})]
        if not need:
            continue
        if sym not in px_cache:
            px_cache[sym] = _fetch_4h(sym) or []
        rows = px_cache[sym]
        if not rows:
            continue
        try:
            bar_ts = int(datetime.fromisoformat(r["bar_ts_utc"]).timestamp() * 1000)
        except ValueError:
            continue
        # индекс бара сигнала в свежем ряду
        idx = next((k for k, x in enumerate(rows) if x[0] == bar_ts), None)
        if idx is None:
            continue
        d = 1 if r["dir"] == "LONG" else -1
        for h, hb in HORIZONS_BARS.items():
            if h in r["outcomes"]:
                continue
            j = idx + hb
            if j < len(rows):
                ret = d * (rows[j][4] / r["entry"] - 1) * 100
                r["outcomes"][h] = round(ret, 3)
                updated += 1
    if updated:
        _write_journal(recs)
    return updated


async def ma_cross_shadow_loop(stop_event, *, interval_sec: int = POLL_INTERVAL_SEC) -> None:
    import asyncio
    logger.info("ma_cross_shadow.start interval=%ds symbols=%s (тихий форвард-сбор, без TG)",
                interval_sec, list(SYMBOLS))
    while not stop_event.is_set():
        try:
            detect()
            fill_outcomes()
        except Exception:
            logger.exception("ma_cross_shadow.tick_failed")
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            continue
    logger.info("ma_cross_shadow.stopped")
