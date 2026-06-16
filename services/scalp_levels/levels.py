"""Сбор и ранжирование уровней плотности. Чистые функции + сборка TG-карты."""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
LIQ_CSV = ROOT / "market_live" / "liquidations.csv"

BYBIT_KLINE = "https://api.bybit.com/v5/market/kline"
# округление круглых чисел по цене символа (шаг психологического уровня)
ROUND_STEP = {"BTCUSDT": 1000.0, "ETHUSDT": 100.0, "XRPUSDT": 0.05, "SOLUSDT": 5.0}
CONFLUENCE_PCT = 0.15   # уровни ближе этого% = одна стенка (конфлюенс)
NEAR_PCT = 4.0          # показываем уровни в пределах ±этого% от цены
LIQ_WINDOW_H = 6.0      # окно для liq-кластеров, ч
LIQ_BINS = 60


def _fetch(symbol: str, interval: str, limit: int):
    import requests
    r = requests.get(BYBIT_KLINE, params={"category": "linear", "symbol": symbol,
                     "interval": interval, "limit": limit + 1}, timeout=12)
    r.raise_for_status()
    lst = r.json().get("result", {}).get("list", [])
    rows = [{"ts": int(x[0]), "open": float(x[1]), "high": float(x[2]),
             "low": float(x[3]), "close": float(x[4]), "volume": float(x[5])} for x in lst]
    rows.sort(key=lambda r: r["ts"])
    return rows[:-1]  # дропаем незакрытый бар


def _round_levels(px: float, step: float, n: int = 3) -> list[float]:
    base = round(px / step) * step
    return [base + k * step for k in range(-n, n + 1) if base + k * step > 0]


def _liq_clusters(now: datetime, px: float) -> list[tuple[float, float]]:
    """Кластеры ликвидаций за окно → [(price, qty_sum)] топ по объёму."""
    if not LIQ_CSV.exists():
        return []
    cutoff = now - timedelta(hours=LIQ_WINDOW_H)
    pts = []
    try:
        size = LIQ_CSV.stat().st_size
        with LIQ_CSV.open("rb") as fh:
            if size > 3_000_000:
                fh.seek(size - 3_000_000); fh.readline()
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
        for rec in csv.reader(lines):
            if len(rec) != 5 or rec[0] == "ts_utc":
                continue
            try:
                ts = datetime.fromisoformat(rec[0])
                price = float(rec[4]); qty = float(rec[3])
            except (ValueError, IndexError):
                continue
            if ts >= cutoff and price > 0 and qty > 0 and abs(price / px - 1) <= NEAR_PCT / 100 * 2:
                pts.append((price, qty))
    except OSError:
        return []
    if not pts:
        return []
    lo = min(p for p, _ in pts); hi = max(p for p, _ in pts)
    if hi <= lo:
        return []
    width = (hi - lo) / LIQ_BINS
    bins: dict[int, float] = {}
    for price, qty in pts:
        bins[int((price - lo) / width)] = bins.get(int((price - lo) / width), 0) + qty
    clusters = [(lo + (b + 0.5) * width, q) for b, q in bins.items()]
    clusters.sort(key=lambda c: -c[1])
    return clusters[:5]


def _bot_borders() -> list[tuple[float, str]]:
    """Границы грид-ботов BTC из выгрузки трекера = реальные лесенки ордеров."""
    try:
        from services.morning_brief import tracker_reader as tr
        params = tr.read_params()
    except Exception:
        return []
    out = []
    for bid, p in params.items():
        try:
            raw = json.loads(p.get("raw_params_json") or "{}")
        except json.JSONDecodeError:
            continue
        b = raw.get("border") or {}
        name = (p.get("bot_name") or "")[:10]
        for key in ("top", "bottom", "from", "to"):
            v = b.get(key)
            if v and 40000 < float(v) < 200000:   # только BTC-границы
                out.append((float(v), f"бот {name}"))
    return out


def collect(symbol: str = "BTCUSDT", now: datetime | None = None) -> dict:
    """Собрать все уровни. → dict(px, levels=[{price, dist_pct, src, tags}])."""
    from services.volume_nodes import compute_volume_profile
    now = now or datetime.now(timezone.utc)
    bars5 = _fetch(symbol, "5", 288)       # ~1 день 5m для VPVR + структуры
    d1 = _fetch(symbol, "D", 3)            # вчера/позавчера
    if not bars5:
        return {"px": None, "levels": []}
    px = bars5[-1]["close"]
    raw: list[tuple[float, str]] = []

    vp = compute_volume_profile(bars5)
    if vp:
        raw += [(vp["poc"], "POC"), (vp["vah"], "VAH"), (vp["val"], "VAL")]
        raw += [(h, "HVN") for h in (vp.get("hvn") or [])[:4]]
    if len(d1) >= 2:
        raw += [(d1[-2]["high"], "вчера H"), (d1[-2]["low"], "вчера L")]
    raw += [(r, "круглый") for r in _round_levels(px, ROUND_STEP.get(symbol, 100.0))]
    if symbol == "BTCUSDT":
        raw += _bot_borders()
    raw += [(p, f"liq {q:.0f}") for p, q in _liq_clusters(now, px)]

    # только близкие, конфлюенс-склейка
    near = [(p, s) for p, s in raw if p > 0 and abs(p / px - 1) * 100 <= NEAR_PCT]
    near.sort(key=lambda x: x[0])
    merged: list[dict] = []
    for price, src in near:
        if merged and abs(price / merged[-1]["price"] - 1) * 100 <= CONFLUENCE_PCT:
            merged[-1]["srcs"].append(src)
            merged[-1]["price"] = (merged[-1]["price"] + price) / 2
        else:
            merged.append({"price": price, "srcs": [src]})
    levels = []
    for m in merged:
        levels.append({"price": m["price"], "dist_pct": (m["price"] / px - 1) * 100,
                       "srcs": m["srcs"], "confluence": len(m["srcs"]) >= 2})
    return {"px": px, "symbol": symbol, "levels": levels}


def build_card(symbol: str = "BTCUSDT") -> str:
    d = collect(symbol)
    px = d["px"]
    if px is None:
        return f"📊 {symbol}: уровни недоступны (нет данных)."
    sym = symbol.replace("USDT", "")
    above = sorted([x for x in d["levels"] if x["dist_pct"] > 0.03], key=lambda x: x["dist_pct"])
    below = sorted([x for x in d["levels"] if x["dist_pct"] < -0.03], key=lambda x: -x["dist_pct"])

    def fmt(x):
        star = "🧱" if x["confluence"] else "·"
        p = x["price"]
        ps = f"{p:,.0f}" if p >= 100 else f"{p:.4f}"
        return f"  {star} {ps} ({x['dist_pct']:+.2f}%) — {', '.join(x['srcs'][:3])}"

    L = [f"📊 КАРТА ПЛОТНОСТИ {sym} · цена {px:,.0f}" if px >= 100 else
         f"📊 КАРТА ПЛОТНОСТИ {sym} · цена {px:.4f}",
         "🧱 = конфлюенс (несколько источников = сильная стенка)\n",
         "↑ СВЕРХУ (сопротивление / стенки на продажу):"]
    L += [fmt(x) for x in above[:6]] or ["  —"]
    L.append("↓ СНИЗУ (поддержка / стенки на покупку):")
    L += [fmt(x) for x in below[:6]] or ["  —"]
    L.append("\n— карта для CScalp-экрана; пробой 🧱 = сила, отбой от 🧱 = вход. Не сделка.")
    return "\n".join(L)
