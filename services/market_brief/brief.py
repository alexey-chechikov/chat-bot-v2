"""Утренняя сводка рынка (оператор 18.10): вывод на день, что изменилось со вчера, статистика 2 лет по каждому сигналу
и проверка вчерашнего вывода. Данные — публичные первоисточники панелей CoinGlass (Binance OI, L/S, агрессор, фандинг) и
наш сборщик ликвидаций Bybit/OKX/Binance. Карта ликвидаций CoinGlass (модель) сюда не входит — её нет без API.

Честность: прогноз направления по таким признакам у нас опровергнут многократно (CLAUDE.md). Поэтому в вывод попадает
только то, что на истории отличается от обычного дня с 95% интервалом; иначе так и пишется — «как обычный день».
Условия заданы заранее (4 штуки), пороги — квантили истории, не подбираются по результату.
"""
from __future__ import annotations

import csv
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.market_brief.history import DIR, _get, read_features

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
LOG = DIR / "brief_log.jsonl"
SYMS = ("BTCUSDT", "ETHUSDT")
LIQ = {"BTCUSDT": ROOT / "market_live" / "liquidations.csv", "ETHUSDT": ROOT / "market_live" / "liquidations_ETHUSDT.csv"}
BIG = 0.03                                                       # «большой ход» за сутки — |доходность| > 3%
# поправка на множественные проверки: каждый день 4 условия × 2 монеты × 2 исхода = 16 сравнений; при 95% на каждое
# почти ежедневно было бы одно случайное «отличие». Бонферрони: 0.05/16 → z ≈ 2.95
Z = 2.95


# ---------------------------------------------------------------- статистика (чистые функции)
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, int(q * (len(s) - 1))))]


def label_days(rows: list[dict]) -> list[dict]:
    """Дневные строки → условия дня и исход СЛЕДУЮЩЕГО дня. Пороги — квантили всей истории (20/80%)."""
    def f(r, k):
        try:
            return float(r[k])
        except (KeyError, TypeError, ValueError):
            return None
    tak = [f(r, "taker_ratio") for r in rows if f(r, "taker_ratio") is not None]
    fun = [f(r, "funding_day") for r in rows if f(r, "funding_day") is not None]
    dls = [f(b, "top_ls") - f(a, "top_ls") for a, b in zip(rows, rows[1:])
           if f(a, "top_ls") is not None and f(b, "top_ls") is not None]
    th = {"tak": (quantile(tak, .2), quantile(tak, .8)) if tak else (None, None),
          "fun": (quantile(fun, .2), quantile(fun, .8)) if fun else (None, None),
          "dls": (quantile(dls, .2), quantile(dls, .8)) if dls else (None, None)}
    out = []
    for i, r in enumerate(rows[:-1]):
        nxt = f(rows[i + 1], "ret_1d")
        if nxt is None or f(r, "ret_1d") is None:
            continue
        prev_ls = f(rows[i - 1], "top_ls") if i else None
        out.append({"day": r["day"], "next": nxt,
                    "cond": conditions(f(r, "ret_1d"), f(r, "oi_chg_pct"), f(r, "funding_day"), f(r, "taker_ratio"),
                                       (f(r, "top_ls") - prev_ls) if (prev_ls is not None and f(r, "top_ls") is not None)
                                       else None, th)})
    return out, th


def conditions(ret, oi_chg, funding, taker, dls, th) -> dict[str, str]:
    c = {}
    if ret is not None and oi_chg is not None:
        p = "цена↑" if ret > 0.005 else "цена↓" if ret < -0.005 else "цена≈"
        o = "OI↑" if oi_chg > 0.5 else "OI↓" if oi_chg < -0.5 else "OI≈"
        c["oi_price"] = f"{o} {p}"
    lo, hi = th["fun"]
    if funding is not None and lo is not None:
        c["funding"] = "фандинг высокий" if funding > hi else "фандинг низкий" if funding < lo else "фандинг обычный"
    lo, hi = th["tak"]
    if taker is not None and lo is not None:
        c["taker"] = "агрессор — покупатели" if taker > hi else "агрессор — продавцы" if taker < lo else "агрессор ровный"
    lo, hi = th["dls"]
    if dls is not None and lo is not None:
        c["top_ls"] = "топ-трейдеры добавили лонгов" if dls > hi else ("топ-трейдеры сократили лонги" if dls < lo
                                                                     else "топ-трейдеры без изменений")
    return c


def stat(labeled: list[dict], key: str, value: str) -> dict:
    """Следующий день после дней с условием key=value против всех дней: доля роста, доля большого хода (>3%)."""
    sub = [x["next"] for x in labeled if x["cond"].get(key) == value]
    base = [x["next"] for x in labeled]
    n, nb = len(sub), len(base)
    up, upb = sum(v > 0 for v in sub), sum(v > 0 for v in base)
    big, bigb = sum(abs(v) > BIG for v in sub), sum(abs(v) > BIG for v in base)
    lo_u, hi_u = wilson(up, n, Z)
    lo_b, hi_b = wilson(big, n, Z)
    pb_u, pb_b = (upb / nb if nb else 0), (bigb / nb if nb else 0)
    return {"n": n, "up": up / n if n else None, "up_base": pb_u, "up_diff": n >= 30 and not (lo_u <= pb_u <= hi_u),
            "big": big / n if n else None, "big_base": pb_b, "big_diff": n >= 30 and not (lo_b <= pb_b <= hi_b)}


# ---------------------------------------------------------------- живые данные (последние 48 ч)
def _series(path: str, sym: str, field: str) -> list[float]:
    rows = _get(f"https://fapi.binance.com{path}?symbol={sym}&period=1h&limit=49")
    return [float(r[field]) for r in rows]


def live(sym: str) -> dict:
    kl = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1h&limit=49")
    px = [float(k[4]) for k in kl]
    oi = _series("/futures/data/openInterestHist", sym, "sumOpenInterest")
    top = _series("/futures/data/topLongShortPositionRatio", sym, "longShortRatio")
    # агрессор — среднее 5-минутных отношений, как в истории (daily metrics); часовые дают другую шкалу (18.10: ETH 1.04
    # по часам попадал в «продавцы» по 5-минутным порогам)
    url = f"https://fapi.binance.com/futures/data/takerlongshortRatio?symbol={sym}&period=5m&limit=288"
    t_today = _get(url)
    t_yday = _get(url + f"&endTime={int(t_today[0]['timestamp']) - 1}") if t_today else []
    ratio = [float(r["buySellRatio"]) for r in t_yday] + [float(r["buySellRatio"]) for r in t_today]
    fr = _get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&limit=6")
    rates = [float(r["fundingRate"]) for r in fr]
    out = {"price": px[-1]}
    for tag, sl in (("today", slice(-25, None)), ("yday", slice(-49, -24))):
        p, o, t = px[sl], oi[sl], top[sl]
        rt = ratio[-288:] if tag == "today" else ratio[:-288]
        out[tag] = {"ret": p[-1] / p[0] - 1 if p else None, "oi_chg_pct": (o[-1] / o[0] - 1) * 100 if o else None,
                    "top_ls": t[-1] if t else None, "dls": (t[-1] - t[0]) if t else None,
                    "taker": sum(rt) / len(rt) if rt else None,
                    "funding": sum(rates[-3:]) if tag == "today" else sum(rates[-6:-3])}
    out["liq"] = liquidations(sym)
    return out


def liquidations(sym: str, hours: int = 24) -> dict:
    p = LIQ.get(sym)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    lng, sht, by_px = 0.0, 0.0, {}
    if not p or not p.exists():
        return {"long_usd": None, "short_usd": None, "cluster": None}
    with open(p, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                t = datetime.fromisoformat(r["ts_utc"])
                if t < since:
                    continue
                usd = float(r["qty"]) * float(r["price"])
            except (KeyError, ValueError):
                continue
            if r["side"] == "long":
                lng += usd
                b = round(float(r["price"]), -2 if sym == "BTCUSDT" else 0)
                by_px[b] = by_px.get(b, 0.0) + usd
            else:
                sht += usd
    cl = max(by_px.items(), key=lambda kv: kv[1]) if by_px else None
    return {"long_usd": lng, "short_usd": sht, "cluster": cl}


# ---------------------------------------------------------------- текст
def _pct(x, d=1):
    return "—" if x is None else f"{x * 100:+.{d}f}%"


def block(sym: str, now: dict, labeled: list[dict], th: dict) -> tuple[list[str], dict, list[str]]:
    t, y = now["today"], now["yday"]
    ct = conditions(t["ret"], t["oi_chg_pct"], t["funding"], t["taker"], t["dls"], th)
    cy = conditions(y["ret"], y["oi_chg_pct"], y["funding"], y["taker"], y["dls"], th)
    lines = [f"{sym[:3]} {now['price']:,.0f} ({_pct(t['ret'])} за сутки)"]
    expl = {"OI↑ цена↑": "входят новые позиции по росту", "OI↓ цена↑": "рост на закрытии шортов",
            "OI↑ цена↓": "входят новые позиции по падению", "OI↓ цена↓": "падение на закрытии лонгов"}
    op = ct.get("oi_price", "")
    lines.append(f"• OI {t['oi_chg_pct']:+.1f}% при цене {_pct(t['ret'])} — {expl.get(op, 'без выраженного потока')} "
                 f"(вчера: OI {y['oi_chg_pct']:+.1f}%, цена {_pct(y['ret'])})")
    lines.append(f"• фандинг {t['funding'] * 100:.3f}%/сутки — {ct.get('funding', '?').split()[-1]} "
                 f"(вчера {y['funding'] * 100:.3f}%)")
    lines.append(f"• агрессор покупки/продажи {t['taker']:.2f} — {ct.get('taker', '?').split('— ')[-1]} "
                 f"(вчера {y['taker']:.2f})")
    lines.append(f"• топ-трейдеры L/S {t['top_ls']:.2f} ({t['dls']:+.2f} за сутки; вчера {y['dls']:+.2f})")
    lq = now["liq"]
    if lq["long_usd"] is not None:
        cl = f", больше всего лонгов ликвидировано у {lq['cluster'][0]:,.0f}" if lq["cluster"] else ""
        lines.append(f"• ликвидации за сутки (Bybit/OKX/Binance): лонги ${lq['long_usd'] / 1e6:.1f}M, "
                     f"шорты ${lq['short_usd'] / 1e6:.1f}M{cl}")
    stats, notes, plain = [], [], []
    for key in ("oi_price", "funding", "taker", "top_ls"):
        v = ct.get(key)
        if not v:
            continue
        s = stat(labeled, key, v)
        if s["n"] < 30 or not (s["up_diff"] or s["big_diff"]):
            plain.append(f"{v} (n {s['n']})")
            continue
        stats.append(f"  после «{v}» (n {s['n']}): рост {s['up'] * 100:.0f}% (обычно {s['up_base'] * 100:.0f}%), "
                     f"ход >3% {s['big'] * 100:.0f}% (обычно {s['big_base'] * 100:.0f}%)")
        if s["up_diff"]:
            notes.append(f"{sym[:3]}: после «{v}» рост бывал {'чаще' if s['up'] > s['up_base'] else 'реже'} обычного "
                         f"({s['up'] * 100:.0f}% против {s['up_base'] * 100:.0f}%)")
        if s["big_diff"]:
            notes.append(f"{sym[:3]}: после «{v}» большой ход бывал {'чаще' if s['big'] > s['big_base'] else 'реже'} "
                         f"({s['big'] * 100:.0f}% против {s['big_base'] * 100:.0f}%)")
    if plain:
        stats.append("  статистика 2 лет: следующие сутки как обычный день после — " + ", ".join(plain))
    return lines + stats, {"cond": ct, "price": now["price"]}, notes


def yesterday_check() -> list[str]:
    """Вчерашний (последний прошлый) вывод → что случилось с ценой с момента той сводки."""
    if not LOG.exists():
        return []
    prev = None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for line in LOG.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("date") != today:
            prev = r
    if not prev:
        return []
    out = [f"Проверка сводки {prev['date']}:"]
    for sym, rec in prev.get("symbols", {}).items():
        try:
            px = float(_get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}")["price"])
        except Exception:                                       # noqa: BLE001
            continue
        out.append(f"  {sym[:3]}: было {rec['price']:,.0f} → {px:,.0f} ({_pct(px / rec['price'] - 1)}); "
                   f"вывод был: {rec.get('verdict', '—')}")
    return out


def build() -> str:
    now_utc = datetime.now(timezone.utc)
    lines, notes, log = [f"🧭 Рынок на день · {now_utc:%d.%m}"], [], {"date": now_utc.strftime("%Y-%m-%d"),
                                                                       "symbols": {}}
    bodies = []
    for sym in SYMS:
        try:
            labeled, th = label_days(read_features(sym))
            body, rec, nt = block(sym, live(sym), labeled, th)
        except Exception as exc:                                # noqa: BLE001
            logger.exception("market_brief.symbol_failed %s", sym)
            bodies.append(f"{sym[:3]}: данные не прочитаны ({type(exc).__name__})")
            continue
        bodies += body
        notes += nt
        rec["verdict"] = "; ".join(n for n in nt if n.startswith(sym[:3])) or "как обычный день"
        log["symbols"][sym] = rec
    lines.append("Вывод: " + ("; ".join(notes) + ". Направление этим не задаётся — это про размах."
                              if notes and all("большой ход" in n for n in notes) else "; ".join(notes) if notes else
                              "по этим данным следующие сутки как обычный день — ни по направлению, ни по размаху. "
                              "Контекст, не сигнал входа."))
    lines += bodies
    try:                                                        # 18.10: цифры CoinGlass со страницы (сбор раз в час)
        from services.coinglass_web.section import section
        lines.append(section())
    except Exception:                                           # noqa: BLE001
        logger.exception("market_brief.coinglass_failed")
    lines += yesterday_check()
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        if not any(json.loads(x).get("date") == log["date"] for x in
                   (LOG.read_text(encoding="utf-8").splitlines() if LOG.exists() else []) if x.strip()):
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(log, ensure_ascii=False) + "\n")
    except (OSError, ValueError):
        logger.exception("market_brief.log_failed")
    return "\n".join(lines)
