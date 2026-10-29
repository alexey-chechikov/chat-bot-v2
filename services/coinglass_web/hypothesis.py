"""Рабочая гипотеза на 2–6 ч — первый экран карточки (разбор GPT a7d799b §5; оператор: «предполагаемый вывод вместо
перечня индикаторов»).

Версия hy-1 (28.10.2026). Вход — решение теневой машины sc-1 (services/coinglass_web/scenarios.py) по последнему
закрытому часу и ряды того же кадра compare.frame. Только известное к моменту показа: закрытые часы и отдельно —
цена незакрытого часа (подписана как «сейчас»), без будущих минимумов и максимумов.

Карточка:
1. Заголовок: «BTC · 16:00 Варшава · рабочая гипотеза на 2–6 ч».
2. Вывод — один-два предложения: предпочтительный сценарий по состоянию sc-1, с силой потока и реакцией цены.
3. Почему — до трёх наблюдений: место цены относительно уровней, поток против реакции цены, ликвидации (только при
   полном окне; пропуск — «нет данных», не ноль).
4. Что против — до двух: противоречащий поток, пробитая, но не подтверждённая граница, пробелы данных, давность.
5. Подтверждение / отмена — условия по ЗАКРЫТЫМ часам (касание ≠ закрепление).
6. Что изменилось с прошлого показа — по журналу state/coinglass/hypothesis_log.jsonl.
Вероятность не пишется: гипотеза не откалибрована. OI стороны инициатора не показывает — в выводе не используется.
Формулировки наблюдательные: «совместимо с…», без «обязательно» и без обещаний тейка или дохода.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from services.coinglass_web import compare, scenarios

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "state" / "coinglass" / "hypothesis_log.jsonl"
VERSION = "hy-1"
H1 = pd.Timedelta(hours=1)
LEVEL_RU = {"support": "опора", "extreme": "экстремум", "H": "верх диапазона", "L": "низ диапазона"}
# сводка ретро sc-1 на 180 днях (research/coinglass_compare/scenario_replay_result.json, 28.10) — для честной оговорки
STALL_NOTE = "на 180 днях такое предупреждение предшествовало слому редко (BTC 5 из 63, ETH 2–4 из 45)"


def _p(x) -> str:
    if x is None:
        return "нет данных"
    return f"{x:,.0f}".replace(",", " ") if abs(x) >= 100 else f"{x:,.2f}".replace(",", " ")


def _coverage(df: pd.DataFrame, col: str, end: pd.Timestamp, hours: int) -> int:
    if col not in df:
        return 0
    idx = pd.date_range(end - hours * H1, end - H1, freq="1h")
    return int(df[col].reindex(idx).notna().sum())


def _flow(f: dict) -> dict:
    """Сила потока 6 ч к порогу 80% обычных окон и реакция цены в ATR."""
    d6, thr, mv, atr = f.get("d6"), f.get("d6_thr"), f.get("mv6"), f.get("atr")
    out = {"known": d6 is not None and thr is not None and thr > 0, "dir": 0, "strong": False, "ratio": None,
           "resp_atr": (mv / atr) if (mv is not None and atr) else None}
    if out["known"]:
        out["ratio"] = abs(d6) / thr
        out["strong"] = out["ratio"] > 1
        out["dir"] = 1 if d6 > 0 else (-1 if d6 < 0 else 0)
    return out


def build(rec: dict | None, sym: str, df: pd.DataFrame, now: datetime, prev: dict | None = None) -> dict:
    """Гипотеза по решению sc-1 и кадру df (индекс — начало часа UTC). prev — прошлая показанная гипотеза."""
    coin = sym.replace("USDT", "")
    T = pd.Timestamp(now)
    closed_end = T.floor("1h")
    hdr = f"{coin} · {T.tz_convert(compare.WARSAW):%H:%M} Варшава · рабочая гипотеза на 2–6 ч"
    if rec is None:
        return {"v": VERSION, "sym": sym, "header": hdr, "code": "NO_DATA", "conclusion":
                "Не могу выбрать сценарий: нет решения по закрытым часам (данные CoinGlass/Binance не пришли).",
                "why": [], "against": [], "confirm": None, "cancel": None, "change": None, "levels": {}}
    s = rec["state"]["flow"] if rec["state"]["flow"] != "DATA_UNKNOWN" else rec["state"]["price"]
    f, mv, box, pend = rec.get("f") or {}, rec.get("move"), rec.get("box"), rec.get("pend")
    fl = _flow(f)
    close = f.get("close")
    bar_end = pd.Timestamp(rec["bar"]) + H1
    age = int((T - bar_end).total_seconds() // 60)
    now_px = None
    if "px_close" in df and closed_end in df.index and pd.notna(df.at[closed_end, "px_close"]):
        now_px = float(df.at[closed_end, "px_close"])       # незакрытый час — «сейчас», не закрытие
    why, against = [], []
    conf = canc = None
    levels = {}
    # ── поток против реакции цены
    if fl["known"]:
        side = "покупки" if fl["dir"] > 0 else "продажи"
        resp = fl["resp_atr"]
        rtxt = f", цена за 6 ч {resp:+.1f} ATR".replace("-", "−") if resp is not None else ""
        if fl["strong"]:
            if resp is not None and resp * fl["dir"] >= scenarios.P["weak_atr"]:
                flow_txt = f"тейкеры 6 ч: сильные {side} (×{fl['ratio']:.1f} к порогу обычных окон){rtxt} — цена идёт за потоком"
            else:
                flow_txt = (f"тейкеры 6 ч: сильные {side} (×{fl['ratio']:.1f}){rtxt} — цена не идёт за потоком "
                            "(совместимо с поглощением)")
        else:
            gen = "покупок" if fl["dir"] > 0 else "продаж"
            flow_txt = (f"тейкеры 6 ч: перевес {gen}, но ниже порога сильных окон (×{fl['ratio']:.1f} к 80-му "
                        f"перцентилю){rtxt}")
    else:
        flow_txt = None
        against.append("поток тейкеров за 6 ч неизвестен (неполное окно) — силу движения не оцениваю")
    # ── ликвидации: только полное окно 6 ч
    liq_txt = None
    if _coverage(df, "liq_all_long", closed_end, 6) == 6 and _coverage(df, "liq_all_short", closed_end, 6) == 6:
        idx = pd.date_range(closed_end - 6 * H1, closed_end - H1, freq="1h")
        ll, ls = float(df["liq_all_long"].reindex(idx).abs().sum()), float(df["liq_all_short"].reindex(idx).abs().sum())
        if ls > 2 * ll and ls > 0:
            liq_txt = (f"ликвидации шортов за 6 ч {compare._usd(ls)} против лонгов {compare._usd(ll)} — совместимо с "
                       "импульсом на закрытии шортов, не с новым спросом")
        elif ll > 2 * ls and ll > 0:
            liq_txt = (f"ликвидации лонгов за 6 ч {compare._usd(ll)} против шортов {compare._usd(ls)} — совместимо с "
                       "вынужденными продажами")
    else:
        k = min(_coverage(df, "liq_all_long", closed_end, 24), _coverage(df, "liq_all_short", closed_end, 24))
        against.append(f"ликвидации: есть {k} из 24 ч — этим рядом вывод не усиливаю")
    # ── сценарий по состоянию
    d = mv["dir"] if mv and s in ("UP_CONFIRMED", "DOWN_CONFIRMED", "STALL_WARNING") else 0
    if s in ("UP_CONFIRMED", "DOWN_CONFIRMED") and mv:
        up = mv["dir"] > 0
        levels = {"support": mv["support"], "extreme": mv["extreme"]}
        word, opp = ("вверх", "ниже") if up else ("вниз", "выше")
        if fl["known"] and fl["strong"] and fl["dir"] == mv["dir"]:
            strength = "поток это поддерживает"
        elif fl["known"] and fl["strong"] and fl["dir"] == -mv["dir"]:
            strength = "но поток уже против движения"
        else:
            strength = "усиления потока не видно — продолжение требует подтверждения ценой"
        concl = (f"Рабочая гипотеза — сохранение движения {word}, пока держится опора {_p(mv['support'])}; {strength}.")
        why.append(f"подтверждён выход {word} по правилу двух часов (это не обещание дальнейшего хода); "
                   f"экстремум {_p(mv['extreme'])}, опора {_p(mv['support'])}")
        conf = f"закрытие часа {'выше' if up else 'ниже'} {_p(mv['extreme'])} (касание не считается)"
        canc = f"два закрытых часа подряд {opp} {_p(mv['support'])}"
        if "за опорой — ждёт подтверждения" in rec.get("tags", []):
            against.insert(0, f"последний час закрылся {opp} опоры {_p(mv['support'])}: если следующий тоже — слом")
        elif fl["resp_atr"] is not None and fl["resp_atr"] * mv["dir"] <= -scenarios.P["weak_atr"] and close:
            gap = abs(mv["support"] - close) / close * 100
            resp = f"{fl['resp_atr']:+.1f}".replace("-", "−")
            against.append(f"цена за 6 ч идёт против движения ({resp} ATR), до опоры {_p(mv['support'])} — {gap:.1f}%")
        if fl["known"] and fl["strong"] and fl["dir"] == -mv["dir"]:
            against.insert(0, flow_txt)
            flow_txt = None
    elif s == "STALL_WARNING" and mv:
        up = mv["dir"] > 0
        levels = {"support": mv["support"], "extreme": mv["extreme"]}
        concl = (f"Рабочая гипотеза — пауза в движении {'вверх' if up else 'вниз'}: нового экстремума нет или поток "
                 f"не двигает цену. Предупреждение слабое: {STALL_NOTE}.")
        why.append(f"экстремум {_p(mv['extreme'])} не обновлён; опора {_p(mv['support'])}")
        conf = f"продолжение — закрытие часа {'выше' if up else 'ниже'} {_p(mv['extreme'])}"
        canc = f"слом — два закрытых часа {'ниже' if up else 'выше'} {_p(mv['support'])}"
    elif s in ("STRUCTURE_BROKEN", "COOLDOWN"):
        md = scenarios._move_dir(rec)
        concl = ("Рабочая гипотеза — откат или консолидация: структура движения "
                 f"{'вверх' if md and md > 0 else 'вниз' if md else ''} сломана двумя закрытыми часами. "
                 "Новый диапазон определится после паузы.")
        if rec.get("cool_until"):
            why.append(f"пауза после слома до {pd.Timestamp(rec['cool_until']).tz_convert(compare.WARSAW):%H:%M} Варшава")
        conf = "новая коробка 24 ч после паузы и выход из неё по правилу двух часов"
        canc = "возврат за сломанную опору и новый экстремум в прежнюю сторону"
    elif s in ("RANGE", "RANGE_BUY_PRESSURE", "RANGE_SELL_PRESSURE") and box:
        levels = {"H": box["H"], "L": box["L"]}
        tilt = {"RANGE_BUY_PRESSURE": " с давлением покупателей — попытка выхода вверх возможна, но не подтверждена",
                "RANGE_SELL_PRESSURE": " с давлением продавцов — попытка выхода вниз возможна, но не подтверждена"}
        concl = (f"Рабочая гипотеза — торговля внутри диапазона {_p(box['L'])}–{_p(box['H'])}"
                 f"{tilt.get(s, '')}, пока закрытые часы не подтвердят выход.")
        why.append(f"флет: ширина {box.get('width_pct', 0):.1f}%, эффективность хода за 24 ч ER "
                   f"{(f.get('er') or 0):.2f}")
        conf = f"выход вверх — два закрытых часа выше {_p(box['H'])}"
        canc = f"выход вниз — два закрытых часа ниже {_p(box['L'])}"
        if pend:
            edge = box["H"] if pend["side"] > 0 else box["L"]
            against.insert(0, f"последний час закрылся {'выше' if pend['side'] > 0 else 'ниже'} {_p(edge)} — выход ждёт "
                              "второго часа (одно закрытие — ещё не закрепление)")
    elif s == "NO_STRUCTURE":
        concl = ("Не могу выбрать направление: нет ни флета, ни подтверждённого движения — опорная коробка "
                 + (f"{_p(box['L'])}–{_p(box['H'])}." if box else "не задана."))
        if box:
            levels = {"H": box["H"], "L": box["L"]}
            conf = f"вверх — два закрытых часа выше {_p(box['H'])}"
            canc = f"вниз — два закрытых часа ниже {_p(box['L'])}"
    else:
        concl = "Не могу выбрать сценарий: не хватает полных часовых данных цены (25 ч для ER и 15 ч для ATR)."
    if flow_txt and len(why) < 3:
        why.append(flow_txt)
    if liq_txt and len(why) < 3:
        why.append(liq_txt)
    if close is not None:
        px = f"закрытие часа {_p(close)}" + (f", сейчас {_p(now_px)} (час не закрыт)" if now_px is not None else "")
        why.insert(0, px)
    if age > 90:
        against.append(f"решение по часу, закрытому {age} мин назад — данные несвежие")
    change = None
    if prev:
        if prev.get("code") != s:
            change = (f"было: {scenarios.RU.get(prev.get('code'), prev.get('code'))} ({prev.get('shown_warsaw')}) → "
                      f"стало: {scenarios.RU.get(s, s)}")
        else:
            moved = [f"{LEVEL_RU.get(k, k)} {_p(prev['levels'][k])} → {_p(v)}" for k, v in levels.items()
                     if prev.get("levels", {}).get(k) is not None and abs(prev["levels"][k] - v) > 1e-9]
            change = ("состояние то же, сдвинулись уровни: " + "; ".join(moved)) if moved else \
                f"с {prev.get('shown_warsaw')} без изменений"
    return {"v": VERSION, "sym": sym, "header": hdr, "code": s, "dir": d, "conclusion": concl, "why": why[:3],
            "against": against[:2], "confirm": conf, "cancel": canc, "change": change, "levels": levels,
            "bar": rec["bar"], "age_min": age, "now_px": now_px, "close": close}


def last_shown(sym: str, path: Path | None = None, before=None) -> dict | None:
    """Последняя показанная оператору гипотеза символа (до момента before)."""
    for r in reversed(compare._read_jsonl(path or LOG)):
        if r.get("sym") == sym and r.get("kind") == "shown" and r.get("v") == VERSION:
            if before is None or pd.Timestamp(r["shown_at"]) < pd.Timestamp(before):
                return r
    return None


def log_shown(h: dict, now: datetime, path: Path | None = None) -> None:
    """Записать показанную гипотезу (для «что изменилось» и будущей сверки условий подтверждения/отмены)."""
    T = pd.Timestamp(now)
    rec = {"kind": "shown", "v": VERSION, "sym": h["sym"], "shown_at": T.isoformat(timespec="seconds"),
           "shown_warsaw": f"{T.tz_convert(compare.WARSAW):%d.%m %H:%M}", "bar": h.get("bar"), "code": h["code"],
           "levels": h.get("levels") or {}, "confirm": h.get("confirm"), "cancel": h.get("cancel"),
           "close": h.get("close"), "now_px": h.get("now_px")}
    compare._write(path or LOG, [rec])


def lines(h: dict) -> list[str]:
    """Короткий текст для подписи Telegram."""
    out = [f"🧭 {h['header']}", h["conclusion"]]
    if h["why"]:
        out.append("Почему: " + "; ".join(h["why"]) + ".")
    if h["against"]:
        out.append("Против: " + "; ".join(h["against"]) + ".")
    if h.get("confirm") or h.get("cancel"):
        out.append("Подтвердит: " + (h["confirm"] or "—") + ". Отменит: " + (h["cancel"] or "—") + ".")
    if h.get("change"):
        out.append("С прошлого показа: " + h["change"] + ".")
    return out
