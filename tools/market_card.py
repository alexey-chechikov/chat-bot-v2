"""РЫНОК — структурная карточка без прогнозов.

Оператор 2026-07-22: «не нужно угадывание направления — нужно: вышли из
рейнджа / рост продолжается / не разворот / цели такие-то / отмена такая-то».

Всё здесь — факты и арифметика, никаких вероятностей:
  структура  — границы диапазона из свечей, где цена относительно них
  цели       — проекция высоты диапазона от границы (геометрия)
  отмена     — сама граница (уровень, где сценарий мёртв)
  механика   — OI/тейкеры/объём: новые деньги или закрытие позиций
  толпа      — global L/S против top-trader L/S (расхождение = факт)
  боль       — где реально ликвидировало за 24ч (кластеры цен)
  альты      — сила/слабость и раскорреляция с BTC

Запуск: .venv/bin/python3 tools/market_card.py [--symbol BTCUSDT]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MARKET = {"BTCUSDT": ROOT / "market_live" / "market_1m.csv"}
LIQ = {"BTCUSDT": ROOT / "market_live" / "liquidations.csv",
       "ETHUSDT": ROOT / "market_live" / "liquidations_ETHUSDT.csv",
       "XRPUSDT": ROOT / "market_live" / "liquidations_XRPUSDT.csv"}
DERIV = ROOT / "state" / "deriv_live.json"
FROZEN = {s: ROOT / "backtests" / "frozen" / f"{s}_1m_2y.csv"
          for s in ("BTCUSDT", "ETHUSDT", "XRPUSDT")}

RANGE_LOOKBACK_H = 72
RANGE_VALID_FRAC = 0.70      # доля времени внутри границ, ниже — не диапазон
OI_NEW_MONEY_PCT = 0.3       # |OI 1ч| выше — трактуем как поток, а не шум
EDGE_ZONE_PCT = 1.0          # ближе этого к границе — «у края»


def score_fuel(px_chg_1h: float, oi: float | None, taker: float | None,
               vol_ratio: float, funding_pct: float) -> tuple[int, list[str]]:
    """ОБЕСПЕЧЕННОСТЬ движения деньгами: оплачено новыми позициями (+) или
    это закрытие старых — вынос/разгрузка, топливо конечно (−).

    Ядро — СВЯЗКА OI×тейкеры, а не отдельные баллы: рост тейкер-покупок при
    падающем OI это не «подтверждение силы», а тот же самый вынос шортов.
    Раздельные баллы гасили главный сигнал (поймано на живом выводе
    2026-07-22). Объём и фандинг — только модификаторы, знак не переворачивают.
    """
    why: list[str] = []
    if oi is None or taker is None:
        return 0, ["±0  нет данных по OI/тейкерам"]

    buying = taker > 1.1
    selling = taker < 0.9
    oi_up = oi >= OI_NEW_MONEY_PCT
    oi_dn = oi <= -OI_NEW_MONEY_PCT

    if oi_up and buying:
        base = 3
        why.append(f"+3  OI {oi:+.2f}% и тейкеры {taker} — заходят НОВЫЕ ЛОНГИ, "
                   f"движение вверх оплачено")
    elif oi_up and selling:
        base = 3
        why.append(f"+3  OI {oi:+.2f}% и тейкеры {taker} — заходят НОВЫЕ ШОРТЫ, "
                   f"движение вниз оплачено")
    elif oi_dn and buying:
        base = -3
        why.append(f"−3  OI {oi:+.2f}% при покупках {taker} — это ЗАКРЫТИЕ "
                   f"ШОРТОВ, а не спрос. Топливо кончится вместе с шортами")
    elif oi_dn and selling:
        base = -3
        why.append(f"−3  OI {oi:+.2f}% при продажах {taker} — ЛОНГИ РАЗГРУЖАЮТ, "
                   f"а не открывают шорты. Это истощение, не слом")
    elif oi_up:
        base = 1
        why.append(f"+1  OI {oi:+.2f}% растёт, но тейкеры нейтральны ({taker})")
    elif oi_dn:
        base = -1
        why.append(f"−1  OI {oi:+.2f}% падает при нейтральных тейкерах ({taker})")
    else:
        base = 0
        why.append(f"±0  OI {oi:+.2f}% — потока нет, движение без денег")

    # модификаторы: усиливают/ослабляют, но не переворачивают вывод
    mod = 0
    if vol_ratio >= 1.3:
        mod += 1
        why.append(f"+1  объём {vol_ratio:.1f}× от среднего часа — участники активны")
    elif vol_ratio <= 0.7:
        mod -= 1
        why.append(f"−1  объём {vol_ratio:.1f}× — затухание")

    up = px_chg_1h >= 0
    if abs(funding_pct) >= 0.01:
        if (funding_pct > 0 and up) or (funding_pct < 0 and not up):
            mod -= 1
            why.append(f"−1  фандинг {funding_pct:+.4f}% — толпа уже в этой "
                       f"стороне, перегрев")
        else:
            mod += 1
            why.append(f"+1  фандинг {funding_pct:+.4f}% — платят против "
                       f"движения, это топливо")

    total = base + mod
    if base > 0:
        total = max(total, 1)      # модификатор не отменяет «новые деньги»
    elif base < 0:
        total = min(total, -1)     # и не превращает вынос в силу
    return total, why


def score_structure(px: float, rng: dict, liq: list[dict],
                    g_ls: float | None, t_ls: float | None) -> tuple[int, list[str]]:
    """СТРУКТУРНОЕ положение: где мы и кому уже сделали больно.
    + = позиция в пользу продолжения вверх, − = вниз, 0 = нейтрально."""
    pts, why = 0, []
    hi, lo = rng["hi"], rng["lo"]
    if px > hi:
        pts += 2
        why.append(f"+2  цена ВЫШЕ диапазона (${hi:,.0f}) — структура сломана вверх")
    elif px < lo:
        pts -= 2
        why.append(f"−2  цена НИЖЕ диапазона (${lo:,.0f}) — структура сломана вниз")
    else:
        up_d = (hi - px) / px * 100
        dn_d = (px - lo) / px * 100
        if up_d <= EDGE_ZONE_PCT:
            why.append(f"±0  у ВЕРХНЕЙ границы ({up_d:.2f}%) — зона решения")
        elif dn_d <= EDGE_ZONE_PCT:
            why.append(f"±0  у НИЖНЕЙ границы ({dn_d:.2f}%) — зона решения")
        else:
            why.append(f"±0  в середине диапазона — краёв не видно")

    if liq:
        tot_l = sum(c["long"] for c in liq)
        tot_s = sum(c["short"] for c in liq)
        if tot_l > tot_s * 1.5:
            pts -= 1
            why.append(f"−1  за 24ч вынесли в основном ЛОНГИ ({tot_l:.0f} vs "
                       f"{tot_s:.0f}) — покупателей уже наказали")
        elif tot_s > tot_l * 1.5:
            pts += 1
            why.append(f"+1  за 24ч вынесли в основном ШОРТЫ ({tot_s:.0f} vs "
                       f"{tot_l:.0f}) — продавцов уже наказали")

    if g_ls and t_ls:
        if g_ls > 1.3 and t_ls < g_ls * 0.8:
            pts -= 1
            why.append(f"−1  толпа в лонгах ({g_ls}), крупные сдержаннее "
                       f"({t_ls}) — расхождение, топливо для выноса вниз")
        elif g_ls < 0.95 and t_ls > g_ls * 1.2:
            pts += 1
            why.append(f"+1  толпа в шортах ({g_ls}), крупные в лонгах "
                       f"({t_ls}) — топливо для выноса вверх")
    return pts, why


def verdict(fuel: int, struct: int, rng: dict, px: float,
            px_chg_1h: float) -> tuple[str, str, str]:
    """(название ситуации, что это значит, что делает вывод неверным)."""
    hi, lo = rng["hi"], rng["lo"]
    at_top = 0 <= (hi - px) / px * 100 <= EDGE_ZONE_PCT
    at_bot = 0 <= (px - lo) / px * 100 <= EDGE_ZONE_PCT
    broke_up, broke_dn = px > hi, px < lo

    if broke_up or broke_dn:
        d = "вверх" if broke_up else "вниз"
        lvl = hi if broke_up else lo
        if fuel >= 2:
            return (f"ПРОБОЙ {d.upper()} ОПЛАЧЕН ДЕНЬГАМИ",
                    "Выход из диапазона обеспечен новыми позициями — "
                    "это продолжение, а не разворот. Контр-нога грида под ударом.",
                    f"возврат {'под' if broke_up else 'над'} ${lvl:,.0f}")
        if fuel <= -2:
            return (f"ЛОЖНЫЙ ВЫХОД {d.upper()} (вынос)",
                    "Цена за границей, но на закрытии чужих позиций, а не на "
                    "новых деньгах. Такие выходы обычно возвращаются в диапазон.",
                    f"закрепление за ${lvl:,.0f} с ростом OI")
        return (f"ВЫХОД {d.upper()} БЕЗ ПОДТВЕРЖДЕНИЯ",
                "Структура сломана, но поток нейтральный — ждём, кто придёт.",
                f"возврат {'под' if broke_up else 'над'} ${lvl:,.0f}")

    if at_top:
        if fuel <= -2:
            return ("ПОДХОД К ВЕРХУ НА ВЫНОСЕ",
                    "К границе идут на закрытии шортов, а не на покупках. "
                    "Топливо кончается вместе с шортами — граница скорее удержит. "
                    "Гриду это на руку.",
                    f"часовое закрытие за ${hi:,.0f} с ростом OI")
        if fuel >= 2:
            return ("ДАВЛЕНИЕ НА ВЕРХНЮЮ ГРАНИЦУ ДЕНЬГАМИ",
                    "Подход обеспечен новыми лонгами — вероятен вынос границы. "
                    "Шорт-ногу грида поджать.",
                    f"откат в середину диапазона без пробоя")
        return ("У ВЕРХНЕЙ ГРАНИЦЫ, ПОТОКА НЕТ",
                "Зона решения, но денег ни с одной стороны. Обычно отбой.",
                f"появление объёма и OI на пробое ${hi:,.0f}")

    if at_bot:
        if fuel <= -2:
            return ("ПОДХОД К НИЗУ НА РАЗГРУЗКЕ",
                    "Вниз идут на закрытии лонгов, а не на новых продажах. "
                    "Это истощение, а не слом — низ скорее удержит.",
                    f"часовое закрытие за ${lo:,.0f} с ростом OI")
        if fuel >= 2:
            return ("ДАВЛЕНИЕ НА НИЖНЮЮ ГРАНИЦУ ДЕНЬГАМИ",
                    "Новые шорты давят вниз — вероятен пробой. "
                    "Лонг-ногу грида поджать.",
                    f"откат в середину диапазона без пробоя")
        return ("У НИЖНЕЙ ГРАНИЦЫ, ПОТОКА НЕТ",
                "Зона решения без денег. Обычно отбой.",
                f"появление объёма и OI на пробое ${lo:,.0f}")

    if abs(fuel) <= 1:
        return ("БОКОВИК, ДЕНЕГ НЕТ",
                "Ни покупатели, ни продавцы не приносят новых позиций. "
                "Импульсу взяться неоткуда — идеальный режим для гридов, "
                "худший для направленных входов.",
                f"выход за ${lo:,.0f}/${hi:,.0f} с ростом OI и объёма")
    d = "вверх" if px_chg_1h >= 0 else "вниз"
    return (f"ДВИЖЕНИЕ {d.upper()} ВНУТРИ ДИАПАЗОНА",
            "Поток есть, но границы целы — это ход внутри структуры, "
            "не смена режима.",
            f"достижение границы без объёма")


def volume_poc(d1: pd.DataFrame, hours: int = 72, bins: int = 40) -> float | None:
    """POC — цена с максимальным объёмом за окно (магнит)."""
    w = d1.tail(hours * 60)
    if w.empty:
        return None
    b = pd.cut(w["c"], bins=bins)
    g = w.groupby(b, observed=True)["v"].sum()
    if g.empty:
        return None
    top = g.idxmax()
    return float((top.left + top.right) / 2)


def load_1m(symbol: str) -> pd.DataFrame:
    p = MARKET.get(symbol)
    if p and p.exists():
        d = pd.read_csv(p, names=["ts", "o", "h", "l", "c", "v"], skiprows=1)
        d["dt"] = pd.to_datetime(d["ts"], utc=True, format="ISO8601")
    else:
        d = pd.read_csv(FROZEN[symbol])
        unit = "ms" if d["ts"].iloc[-1] > 1e12 else "s"
        d["dt"] = pd.to_datetime(d["ts"], unit=unit, utc=True)
        d = d.rename(columns={"open": "o", "high": "h", "low": "l",
                              "close": "c", "volume": "v"})
    return d.set_index("dt").sort_index()


def hourly(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("1h").agg({"o": "first", "h": "max", "l": "min",
                                  "c": "last", "v": "sum"}).dropna()


def detect_range(h1: pd.DataFrame) -> dict:
    w = h1.tail(RANGE_LOOKBACK_H)
    hi = float(w["h"].quantile(0.90))
    lo = float(w["l"].quantile(0.10))
    inside = float(((w["c"] >= lo) & (w["c"] <= hi)).mean())
    return {"hi": hi, "lo": lo, "height": hi - lo, "inside_frac": inside,
            "valid": inside >= RANGE_VALID_FRAC, "bars": len(w)}


def liq_clusters(symbol: str, hours: int = 24, buckets: int = 4) -> list[dict]:
    """Где реально ликвидировало за N часов — кластеры по цене."""
    p = LIQ.get(symbol)
    if not p or not p.exists():
        return []
    try:
        d = pd.read_csv(p)
    except Exception:
        return []
    d = d.dropna(subset=["price", "qty"])
    if d.empty:
        return []
    d["ts_utc"] = pd.to_datetime(d["ts_utc"], utc=True, errors="coerce")
    d = d[d["ts_utc"] >= datetime.now(timezone.utc) - timedelta(hours=hours)]
    d["price"] = pd.to_numeric(d["price"], errors="coerce")
    d["qty"] = pd.to_numeric(d["qty"], errors="coerce")
    d = d.dropna(subset=["price", "qty"])
    if len(d) < 10:
        return []
    d["bucket"] = pd.cut(d["price"], bins=buckets)
    out = []
    for b, g in d.groupby("bucket", observed=True):
        out.append({"lo": b.left, "hi": b.right, "qty": float(g["qty"].sum()),
                    "long": float(g[g["side"] == "long"]["qty"].sum()),
                    "short": float(g[g["side"] == "short"]["qty"].sum())})
    out.sort(key=lambda r: -r["qty"])
    return out[:3]


def fmt(symbol: str) -> str:
    d1 = load_1m(symbol)
    h1 = hourly(d1)
    px = float(d1["c"].iloc[-1])
    now = d1.index[-1]
    rng = detect_range(h1)
    L: list[str] = []

    L.append(f"📐 РЫНОК {symbol.replace('USDT','')} ${px:,.0f}   "
             f"({now:%d.%m %H:%M} UTC)")

    # ── структура
    hi, lo, height = rng["hi"], rng["lo"], rng["height"]
    hpct = height / px * 100
    if not rng["valid"]:
        L.append(f"\nСТРУКТУРА: диапазона нет — цена внутри границ только "
                 f"{rng['inside_frac']*100:.0f}% времени (тренд/расширение)")
    else:
        L.append(f"\nДИАПАЗОН {rng['bars']}ч: ${lo:,.0f} — ${hi:,.0f} "
                 f"(высота {hpct:.1f}%, внутри {rng['inside_frac']*100:.0f}% времени)")

    if px > hi:
        L.append(f"  ВЫШЛИ ВВЕРХ на {(px/hi-1)*100:.2f}% от границы")
        scen = ("вверх", hi + height, hi)
    elif px < lo:
        L.append(f"  ВЫШЛИ ВНИЗ на {(lo/px-1)*100:.2f}% от границы")
        scen = ("вниз", lo - height, lo)
    else:
        up_d, dn_d = (hi - px) / px * 100, (px - lo) / px * 100
        L.append(f"  ВНУТРИ: до верха {up_d:.2f}%, до низа {dn_d:.2f}%")
        scen = None

    # ── механика
    deriv = {}
    try:
        deriv = json.loads(DERIV.read_text(encoding="utf-8")).get(symbol, {})
    except Exception:
        pass
    oi = deriv.get("oi_change_1h_pct")
    taker = deriv.get("taker_buy_sell_ratio")
    fund = (deriv.get("funding_rate_8h") or 0) * 100
    # объём: скользящие 60 мин против среднего часа за сутки. По часовым
    # барам считать нельзя — последний бар незакрыт и даёт ложный «0.0×»
    # (поймано на живом выводе 2026-07-22).
    v60 = float(d1["v"].tail(60).sum())
    v24 = float(d1["v"].tail(24 * 60).sum()) / 24.0
    vol_ratio = v60 / max(v24, 1e-9)
    L.append(f"\nПОТОК: OI 1ч {oi:+.2f}%  тейкеры {taker}  "
             f"объём {vol_ratio:.1f}×  фандинг {fund:+.4f}%"
             if oi is not None else f"\nПОТОК: объём {vol_ratio:.1f}×")

    if oi is not None and taker:
        if oi > OI_NEW_MONEY_PCT and taker > 1.1:
            L.append("  → приходят НОВЫЕ ЛОНГИ (OI↑ + покупки) = движение обеспечено")
        elif oi > OI_NEW_MONEY_PCT and taker < 0.9:
            L.append("  → приходят НОВЫЕ ШОРТЫ (OI↑ + продажи) = давление вниз обеспечено")
        elif oi < -OI_NEW_MONEY_PCT and taker > 1.1:
            L.append("  → ЗАКРЫТИЕ ШОРТОВ (OI↓ + покупки) = вынос, а не спрос. "
                     "Топливо кончается на выносе")
        elif oi < -OI_NEW_MONEY_PCT and taker < 0.9:
            L.append("  → ЗАКРЫТИЕ ЛОНГОВ (OI↓ + продажи) = разгрузка, а не новые продажи")
        else:
            L.append("  → потока нет, движение без денег")

    # ── сценарий
    L.append("\nСЦЕНАРИЙ:")
    if scen:
        direction, target, invalid = scen
        L.append(f"  Пробой {direction} → цель ${target:,.0f} "
                 f"({(target/px-1)*100:+.1f}%)")
        L.append(f"  ОТМЕНА: возврат {'под' if direction=='вверх' else 'над'} "
                 f"${invalid:,.0f}")
    elif rng["valid"]:
        L.append(f"  Пока внутри — работает край. Включается по закрытию часа:")
        L.append(f"    ↑ за ${hi:,.0f} → цель ${hi+height:,.0f}, "
                 f"отмена — возврат под ${hi:,.0f}")
        L.append(f"    ↓ за ${lo:,.0f} → цель ${lo-height:,.0f}, "
                 f"отмена — возврат над ${lo:,.0f}")
    else:
        w = h1.tail(RANGE_LOOKBACK_H)
        L.append(f"  Тренд: удержание ${float(w['l'].tail(24).min()):,.0f} "
                 f"продолжает сценарий, пробой — ломает")

    # ── толпа
    g_ls = deriv.get("global_ls_ratio")
    t_ls = deriv.get("top_trader_ls_ratio")
    if g_ls and t_ls:
        L.append(f"\nПОЗИЦИИ: толпа L/S {g_ls}  крупные L/S {t_ls}")
        if g_ls > 1.5 and t_ls < g_ls * 0.75:
            L.append("  ⚠️ толпа в лонгах, крупные заметно сдержаннее — "
                     "расхождение (топливо для выноса вниз)")
        elif g_ls < 0.9 and t_ls > 1.1:
            L.append("  ⚠️ толпа в шортах, крупные в лонгах — "
                     "расхождение (топливо для выноса вверх)")

    # ── боль
    cl = liq_clusters(symbol)
    if cl:
        L.append("\nГДЕ ЛИКВИДИРОВАЛО за 24ч:")
        for c in cl:
            dom = "лонги" if c["long"] > c["short"] else "шорты"
            L.append(f"  ${c['lo']:,.0f}–${c['hi']:,.0f}: {c['qty']:.1f} "
                     f"({dom} — {max(c['long'], c['short']):.1f})")

    # ── уровни
    w7 = h1.tail(168)
    poc = volume_poc(d1)
    lvl = (f"\nУРОВНИ 7д: хай ${float(w7['h'].max()):,.0f} "
           f"({(float(w7['h'].max())/px-1)*100:+.1f}%)  "
           f"лой ${float(w7['l'].min()):,.0f} "
           f"({(float(w7['l'].min())/px-1)*100:+.1f}%)")
    if poc:
        lvl += (f"\n  POC 72ч ${poc:,.0f} ({(poc/px-1)*100:+.1f}%) — "
                f"{'магнит выше' if poc > px else 'магнит ниже'}")
    L.append(lvl)

    # ── ВЫВОД ПО БАЛЛАМ (оператор 2026-07-22: «пусть сделает вывод по
    # баллам из факторов, а не просто перечислит статистику»)
    # цена час назад — по 1m-ряду, не по незакрытому часовому бару
    px_1h = float(d1["c"].iloc[-61]) if len(d1) > 61 else px
    chg_1h = (px / px_1h - 1) * 100
    f_pts, f_why = score_fuel(chg_1h, oi, taker, vol_ratio, fund)
    s_pts, s_why = score_structure(px, rng, cl, g_ls, t_ls)
    name, meaning, invalid = verdict(f_pts, s_pts, rng, px, chg_1h)

    out = ["\n" + "─" * 34, f"🎯 ВЫВОД: {name}",
           f"\nДеньги за движением: {f_pts:+d}   Структура: {s_pts:+d}"]
    for w in f_why + s_why:
        out.append(f"   {w}")
    out.append(f"\n{meaning}")
    out.append(f"\n❌ Вывод неверен, если: {invalid}")
    L.append("\n".join(out))
    return "\n".join(L)


def alts_block() -> str:
    """Сила альтов и раскорреляция с BTC — на 1ч барах за 48ч."""
    out = ["\n🔀 АЛЬТЫ (48ч):"]
    try:
        btc = hourly(load_1m("BTCUSDT")).tail(48)
    except Exception:
        return ""
    for sym in ("ETHUSDT", "XRPUSDT"):
        try:
            a = hourly(load_1m(sym)).tail(48)
        except Exception:
            continue
        j = pd.concat([btc["c"].rename("b"), a["c"].rename("a")], axis=1).dropna()
        if len(j) < 24:
            continue
        corr = j["b"].pct_change().corr(j["a"].pct_change())
        b_chg = (j["b"].iloc[-1] / j["b"].iloc[0] - 1) * 100
        a_chg = (j["a"].iloc[-1] / j["a"].iloc[0] - 1) * 100
        rel = a_chg - b_chg
        mark = ""
        if corr < 0.7:
            mark = "  ← РАСКОРРЕЛИРОВАН (живёт своей жизнью)"
        out.append(f"  {sym.replace('USDT',''):4s} {a_chg:+.1f}% vs BTC {b_chg:+.1f}% "
                   f"→ {rel:+.1f}% отн.  corr {corr:.2f}{mark}")
    return "\n".join(out) if len(out) > 1 else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    args = ap.parse_args()
    print(fmt(args.symbol))
    print(alts_block())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
