"""Теневая система сценариев для сеток (поручение GPT e53a117 §3–6; оператор 28.10: «сетки сами запускаются при сетапе,
закрываются и ждут следующего»). ТОЛЬКО журнал гипотетических решений: торговых команд нет, параметры и правила
живых сеток не меняются, режим SMA100 и защиты сеток работают как раньше.

Версия sc-1 — кандидат GPT §4 без подбора, зафиксирован 28.10.2026 до оцениваемого периода (первая запись журнала).
Пороги меняются только новой версией, записанной до следующего периода.

Часы — закрытые бары 1ч UTC на календарной сетке, пропуск = пропуск, ничего не дорисовывается.
1. Качество. Цена (Binance OHLC; нет — свечи CoinGlass, те же Binance): 25 ч для ER24 и 15 ч для ATR14 без пропусков,
   иначе DATA_UNKNOWN. Поток (вариант «flow»): покупки и продажи тейкеров CoinGlass за 6 ч без пропусков и ≥ 84
   полных прошлых окон, иначе этот вариант — DATA_UNKNOWN (ценовой продолжает).
2. ER24 = |C[t]−C[t−24]| / Σ|ΔC| за 24 ч; флет — ER24 ≤ 0.25; знаменатель 0 — неопределённо.
3. Коробка: при старте и после паузы — H/L последних 24 закрытых часов, «флет» при ER24 ≤ 0.25, иначе «опорная».
   Границы хранятся с временем и ID и пробоем не сдвигаются; перестройка — отдельное событие (опорная → флет, когда
   ER24 ≤ 0.25 и нет ожидающего выхода).
4. Поток: D6 = (Σbuy − Σsell)/(Σbuy + Σsell) за 6 ч (продажи у CoinGlass со знаком минус для рисования — берутся по
   модулю; сверено: delta = buy + sell). Сильный — |D6| выше 80-го процентиля |D6| окон, кончившихся за прошлые 168 ч
   до начала текущего окна (≥ 84 окон).
5. Реакция цены: ход за 6 ч в ATR14; сильный поток при ходе в его сторону < 0.5 ATR — метка «реакция слабая»
   (кандидат поглощения; диагностика, не приказ).
6. Выход из коробки: закрытие за границей и следующий закрытый час на той же стороне → UP/DOWN_CONFIRMED; возврат
   внутрь — «ложный выход», коробка прежняя.
7. Движение хранит экстремум и опору. Опора роста — сломанная верхняя граница, затем минимум отката перед каждым
   новым максимумом (опора только поднимается); падение — зеркально. Закрытие за опорой и следующий час не вернулся →
   STRUCTURE_BROKEN, затем COOLDOWN 2 полных часа, затем новая коробка. Пауза движения: ER24 ≤ 0.25 не раньше чем
   через 24 ч после подтверждения → новая коробка-флет.
8. Затухание (STALL_WARNING) — предупреждение, не нарушение: вариант flow — сильный поток в сторону движения при ходе
   за 6 ч < 0.5 ATR в ту же сторону; вариант price — 12 закрытых часов без нового экстремума.
Состояния: DATA_UNKNOWN, NO_STRUCTURE (опорная коробка — не флет), RANGE, RANGE_BUY_PRESSURE, RANGE_SELL_PRESSURE,
UP_CONFIRMED, DOWN_CONFIRMED, STALL_WARNING, STRUCTURE_BROKEN, COOLDOWN.
Метки: поглощение-кандидат, ликвидационный импульс, выход/слом ждёт подтверждения.

Теневые действия — для лонг- и шорт-сеток отдельно, пять решений: разрешить новые входы, продолжать, запретить набор,
закрыть остаток (кандидат), запустить новую (кандидат). Жёсткие лимиты и режим SMA100 живых сеток — приоритет и этим
не затрагиваются; потеря данных CoinGlass ничего не закрывает — только не даёт новых разрешений.

Журнал state/coinglass/scenario_shadow.jsonl (только добавление):
- decision — по последнему закрытому часу на момент прогона; forward, если принято в течение часа после закрытия
  бара (ночные часы, обработанные утром, — retro, в счёт вперёд не идут);
- event — переходы (с часом бара и временем обнаружения);
- outcome — через 6/24 ч после решения, по сохранённым в решении цене и ATR.
Рабочее состояние машины — state/coinglass/scenario_state.json.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from services.coinglass_web import compare

ROOT = Path(__file__).resolve().parents[2]
JOURNAL = ROOT / "state" / "coinglass" / "scenario_shadow.jsonl"
STATE = ROOT / "state" / "coinglass" / "scenario_state.json"
VERSION = "sc-1"
P = {"er_n": 24, "er_flat": 0.25, "atr_n": 14, "d6_n": 6, "d6_pct": 0.80, "base_h": 168, "base_min": 84,
     "weak_atr": 0.5, "cooldown_h": 2, "stall_noprog_h": 12, "pause_after_h": 24, "horizons_h": (6, 24),
     "range_min_width_pct": 1.2}       # ширина коробки, где помещаются 2 шага живой сетки 0.6% — исследовательская
H1 = pd.Timedelta(hours=1)
STATES = ("DATA_UNKNOWN", "NO_STRUCTURE", "RANGE", "RANGE_BUY_PRESSURE", "RANGE_SELL_PRESSURE", "UP_CONFIRMED",
          "DOWN_CONFIRMED", "STALL_WARNING", "STRUCTURE_BROKEN", "COOLDOWN")
RU = {"DATA_UNKNOWN": "данных не хватает", "NO_STRUCTURE": "нет флета и нет подтверждённого движения",
      "RANGE": "флет", "RANGE_BUY_PRESSURE": "флет, давят покупатели", "RANGE_SELL_PRESSURE": "флет, давят продавцы",
      "UP_CONFIRMED": "рост подтверждён", "DOWN_CONFIRMED": "падение подтверждено",
      "STALL_WARNING": "движение затухает (предупреждение)", "STRUCTURE_BROKEN": "структура движения сломана",
      "COOLDOWN": "пауза после слома"}


# ─────────────────────────────── признаки по часам ───────────────────────────────

def features(df: pd.DataFrame) -> pd.DataFrame:
    """Признаки каждого часа (метка — начало бара), только прошлое и сам бар; календарная сетка."""
    if df.empty:
        return pd.DataFrame()
    idx = pd.date_range(df.index.min(), df.index.max(), freq="1h")
    d = df.reindex(idx)
    c, hi, lo = d["px_close"], d["px_high"], d["px_low"]
    n = P["er_n"]
    den = c.diff().abs().rolling(n, min_periods=n).sum()
    er = (c - c.shift(n)).abs() / den.where(den > 0)
    tr = pd.concat([hi - lo, (hi - c.shift(1)).abs(), (lo - c.shift(1)).abs()], axis=1)
    tr = tr.max(axis=1, skipna=False)
    atr = tr.rolling(P["atr_n"], min_periods=P["atr_n"]).mean()
    price_ok = (c.rolling(n + 1, min_periods=n + 1).count() == n + 1) & \
               (hi.rolling(n, min_periods=n).count() == n) & (lo.rolling(n, min_periods=n).count() == n) & atr.notna()
    f = pd.DataFrame(index=idx)
    f["close"], f["high"], f["low"] = c, hi, lo
    f["er"], f["atr"], f["price_ok"] = er, atr, price_ok
    f["hh24"], f["ll24"] = hi.rolling(n, min_periods=n).max(), lo.rolling(n, min_periods=n).min()
    f["mv6"] = c - c.shift(6)
    k = P["d6_n"]
    if "taker_buy" in d and "taker_sell" in d:
        buy, sell = d["taker_buy"].abs(), d["taker_sell"].abs()
        b6, s6 = buy.rolling(k, min_periods=k).sum(), sell.rolling(k, min_periods=k).sum()
        f["d6"] = (b6 - s6) / (b6 + s6).where((b6 + s6) > 0)
        f["net6"] = b6 - s6
        span = P["base_h"] - k + 1                               # окна, кончившиеся в t−168 … t−6
        f["d6_thr"] = f["d6"].abs().shift(k).rolling(span, min_periods=P["base_min"]).quantile(P["d6_pct"])
    else:
        f["d6"] = f["net6"] = f["d6_thr"] = np.nan
    f["flow_ok"] = f["d6"].notna() & f["d6_thr"].notna()
    f["strong"] = f["flow_ok"] & (f["d6"].abs() > f["d6_thr"])
    for side in ("long", "short"):
        col = f"liq_all_{side}"
        f[f"liq_{side}"] = d[col].abs() if col in d else np.nan
        f[f"liq_{side}_spike"] = compare._spike(f[f"liq_{side}"]).notna()
    f["oi6"] = (d["oi_coins"] / d["oi_coins"].shift(6) - 1) * 100 if "oi_coins" in d else np.nan
    for col in ("bid_ask_delta", "ls_acc", "ls_top_pos", "wi2", "fr_pct"):
        f[col] = d[col] if col in d else np.nan
    f["lo_a"], f["lo_b"] = lo.rolling(6, min_periods=6).min().shift(6), lo.rolling(6, min_periods=6).min()
    f["hi_a"], f["hi_b"] = hi.rolling(6, min_periods=6).max().shift(6), hi.rolling(6, min_periods=6).max()
    return f


def _num(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


# ─────────────────────────────── машина состояний ───────────────────────────────

def _ts(t) -> str:
    return pd.Timestamp(t).isoformat()


def _new_box(m: dict, t, f, sym: str, why: str) -> dict:
    flat = f["er"] is not None and not np.isnan(f["er"]) and f["er"] <= P["er_flat"]
    hi, lo = float(f["hh24"]), float(f["ll24"])
    mid = (hi + lo) / 2
    box = {"id": f"{sym}:{pd.Timestamp(t):%Y-%m-%dT%H}:box", "kind": "flat" if flat else "ref", "H": hi, "L": lo,
           "set_bar": _ts(t), "width_pct": (hi - lo) / mid * 100 if mid else None, "why": why}
    box["suitable"] = bool(flat and box["width_pct"] is not None and box["width_pct"] >= P["range_min_width_pct"])
    m["box"], m["pend"] = box, None
    return box


def step(m: dict, t, f: dict, sym: str = "") -> dict:
    """Один закрытый час t (начало бара) с признаками f. Меняет m (рабочее состояние). → запись часа: состояния
    обоих вариантов, события, метки, коробка и движение после шага."""
    t = pd.Timestamp(t)
    ev, tags = [], []
    if not f["price_ok"]:
        m["pend"] = m["brk"] = None
        if m.get("struct") != "DATA_UNKNOWN":
            ev.append({"e": "DATA_GAP"})
        m["struct"] = "DATA_UNKNOWN"
        return _rec(m, t, f, "DATA_UNKNOWN", "DATA_UNKNOWN", "DATA_UNKNOWN", ev, tags)
    c, hb, lb = float(f["close"]), float(f["high"]), float(f["low"])
    struct = None
    cool = m.get("cool_until")
    if cool and t < pd.Timestamp(cool):
        struct = "COOLDOWN"
    else:
        if cool:
            m["cool_until"] = None
        mv = m.get("move")
        if mv:
            d = mv["dir"]
            if m.get("brk"):
                if (c - mv["support"]) * d < 0:                 # второй час за опорой — слом подтверждён
                    ev.append({"e": "STRUCTURE_BROKEN", "dir": d, "support": mv["support"], "extreme": mv["extreme"],
                               "move_start": mv["start"]})
                    m["move"] = m["box"] = m["brk"] = None
                    m["cool_until"] = _ts(t + (P["cooldown_h"] + 1) * H1)
                    m["broken_dir"] = d
                    struct = "STRUCTURE_BROKEN"
                else:
                    ev.append({"e": "BREAK_RECLAIMED", "dir": d, "support": mv["support"]})
                    m["brk"] = None
            if struct is None:
                if (c - mv["support"]) * d < 0:
                    m["brk"] = _ts(t)
                    tags.append("за опорой — ждёт подтверждения")
                ext_now = hb if d > 0 else lb
                if (ext_now - mv["extreme"]) * d > 0:
                    pull = mv.get("pull")
                    if pull is not None and (pull - mv["support"]) * d > 0:
                        ev.append({"e": "SUPPORT_MOVED", "dir": d, "from": mv["support"], "to": pull})
                        mv["support"] = pull
                    mv["extreme"], mv["ext_bar"], mv["pull"] = ext_now, _ts(t), None
                    mv["stall_p"] = mv["stall_f"] = False
                else:
                    pb = lb if d > 0 else hb
                    mv["pull"] = pb if mv.get("pull") is None else (min(mv["pull"], pb) if d > 0 else max(mv["pull"], pb))
                er = f["er"]
                if (er is not None and not np.isnan(er) and er <= P["er_flat"] and not m.get("brk")
                        and t - pd.Timestamp(mv["start"]) >= P["pause_after_h"] * H1):
                    box = _new_box(m, t, f, sym, "пауза движения")
                    ev.append({"e": "RANGE_SET", "box": dict(box)})
                    m["move"] = None
                    struct = "RANGE"
                else:
                    struct = "UP_CONFIRMED" if d > 0 else "DOWN_CONFIRMED"
        if struct is None:                                      # коробка: флет или опорная
            box = m.get("box")
            if box is None:
                box = _new_box(m, t, f, sym, "старт" if not m.get("broken_dir") else "после паузы")
                ev.append({"e": "RANGE_SET" if box["kind"] == "flat" else "REF_SET", "box": dict(box)})
            elif box["kind"] == "ref" and not m.get("pend") and f["er"] is not None and not np.isnan(f["er"]) \
                    and f["er"] <= P["er_flat"]:
                box = _new_box(m, t, f, sym, "стал флетом")
                ev.append({"e": "RANGE_SET", "box": dict(box)})
            pend = m.get("pend")
            if pend:
                side = pend["side"]
                edge = box["H"] if side > 0 else box["L"]
                if (c - edge) * side > 0:
                    ext = max(hb, pend["ext"]) if side > 0 else min(lb, pend["ext"])
                    m["move"] = {"dir": side, "start": _ts(t), "extreme": ext, "ext_bar": _ts(t), "support": edge,
                                 "pull": None, "last_box": box["id"], "stall_p": False, "stall_f": False}
                    ev.append({"e": "BREAKOUT_CONFIRMED", "dir": side, "edge": edge, "box": box["id"],
                               "box_kind": box["kind"]})
                    m["box"], m["pend"], m["broken_dir"] = None, None, None
                    struct = "UP_CONFIRMED" if side > 0 else "DOWN_CONFIRMED"
                else:
                    ev.append({"e": "FALSE_BREAK", "dir": side, "edge": edge, "box": box["id"]})
                    m["pend"] = None
            if struct is None:
                if c > box["H"]:
                    m["pend"] = {"side": 1, "bar": _ts(t), "ext": hb}
                    tags.append("выход вверх — ждёт подтверждения")
                elif c < box["L"]:
                    m["pend"] = {"side": -1, "bar": _ts(t), "ext": lb}
                    tags.append("выход вниз — ждёт подтверждения")
                struct = "RANGE" if box["kind"] == "flat" else "NO_STRUCTURE"
    m["struct"] = struct
    # ── надстройки: ценовая и поток ──
    s_price, s_flow = struct, struct
    mv = m.get("move")
    if struct in ("UP_CONFIRMED", "DOWN_CONFIRMED") and mv:
        d = mv["dir"]
        if t - pd.Timestamp(mv["ext_bar"]) >= P["stall_noprog_h"] * H1:
            s_price = "STALL_WARNING"
            if not mv.get("stall_p"):
                mv["stall_p"] = True
                ev.append({"e": "STALL", "variant": "price", "dir": d, "extreme": mv["extreme"]})
    if not f["flow_ok"]:
        s_flow = "DATA_UNKNOWN"
    else:
        d6, strong = float(f["d6"]), bool(f["strong"])
        prog = (f["mv6"] / f["atr"]) if f["atr"] else np.nan
        if strong and not np.isnan(prog) and np.sign(d6) * prog < P["weak_atr"]:
            tags.append("реакция слабая на " + ("покупки" if d6 > 0 else "продажи") + " (кандидат поглощения)")
        if struct == "RANGE" and strong:
            s_flow = "RANGE_BUY_PRESSURE" if d6 > 0 else "RANGE_SELL_PRESSURE"
        elif struct in ("UP_CONFIRMED", "DOWN_CONFIRMED") and mv:
            d = mv["dir"]
            if strong and np.sign(d6) == d and not np.isnan(prog) and prog * d < P["weak_atr"]:
                s_flow = "STALL_WARNING"
                if not mv.get("stall_f"):
                    mv["stall_f"] = True
                    ev.append({"e": "STALL", "variant": "flow", "dir": d, "extreme": mv["extreme"]})
    if f.get("liq_long_spike") or f.get("liq_short_spike"):
        tags.append("ликвидационный импульс: " + ", ".join(
            x for x, k in (("лонги", "liq_long_spike"), ("шорты", "liq_short_spike")) if f.get(k)))
    return _rec(m, t, f, struct, s_price, s_flow, ev, tags)


def _rec(m, t, f, struct, s_price, s_flow, ev, tags) -> dict:
    mv = m.get("move")
    return {"bar": _ts(t), "struct": struct, "state": {"price": s_price, "flow": s_flow}, "events": ev, "tags": tags,
            "box": dict(m["box"]) if m.get("box") else None, "pend": dict(m["pend"]) if m.get("pend") else None,
            "move": ({k: mv[k] for k in ("dir", "start", "extreme", "ext_bar", "support")} if mv else None),
            "cool_until": m.get("cool_until"),
            "f": {k: _num(f.get(k)) for k in ("close", "atr", "er", "d6", "d6_thr", "net6", "mv6", "oi6",
                                               "liq_long", "liq_short", "bid_ask_delta", "ls_acc", "wi2", "fr_pct",
                                               "lo_a", "lo_b", "hi_a", "hi_b")}}


def replay(df: pd.DataFrame, sym: str = "", m: dict | None = None, until=None) -> tuple[list[dict], dict]:
    """Все закрытые часы df по порядку (только прошлое на каждом шаге) → (записи часов, рабочее состояние)."""
    m = {} if m is None else m
    f = features(df)
    out = []
    for t, row in f.iterrows():
        if until is not None and t >= until:
            break
        out.append(step(m, t, row.to_dict(), sym))
    return out, m


# ─────────────────────────────── теневые действия ───────────────────────────────

def _move_dir(rec: dict) -> int | None:
    if rec.get("move"):
        return rec["move"]["dir"]
    for e in rec.get("events", []):
        if e["e"] == "STRUCTURE_BROKEN":
            return e["dir"]
    return None


def actions(rec: dict, variant: str, grid: int) -> dict:
    """Пять теневых решений для сетки направления grid (+1 лонг, −1 шорт) по состоянию варианта."""
    s = rec["state"][variant]
    ev = {e["e"] for e in rec.get("events", [])}
    md = _move_dir(rec)
    box = rec.get("box") or {}
    a = {"entries": "без изменений", "continue": "да", "residual": "держать", "start": "—", "why": RU.get(s, s)}
    if s == "DATA_UNKNOWN":
        a.update(entries="без изменений (новых разрешений нет)", why="данных не хватает — защиты сеток работают как были")
    elif s == "COOLDOWN":
        a.update(entries="запретить набор", why="пауза после слома структуры")
    elif s == "STRUCTURE_BROKEN":
        if md == grid:
            a.update({"entries": "запретить набор", "continue": "нет", "residual": "кандидат закрыть остаток",
                      "why": "движение в сторону сетки сломано"})
        else:
            a.update(why="сломано движение против сетки")
    elif s == "STALL_WARNING":
        if md == grid:
            a.update(entries="запретить набор", why="движение в сторону сетки затухает; тейки остаются")
        else:
            a.update(why="затухает движение против сетки")
    elif s in ("UP_CONFIRMED", "DOWN_CONFIRMED"):
        d = 1 if s == "UP_CONFIRMED" else -1
        if d == grid:
            a.update(entries="разрешить")
            if "BREAKOUT_CONFIRMED" in ev:
                a["start"] = "кандидат запуска (новое подтверждённое движение)"
        else:
            a.update(entries="запретить набор", why="подтверждено движение против сетки")
    elif s in ("RANGE", "RANGE_BUY_PRESSURE", "RANGE_SELL_PRESSURE"):
        if box.get("suitable"):
            a.update(entries="разрешить")
            if "RANGE_SET" in ev:
                a["start"] = f"кандидат запуска (флет {box['width_pct']:.1f}% ≥ {P['range_min_width_pct']}%)"
        else:
            a.update(why=f"флет узкий ({(box.get('width_pct') or 0):.1f}% < {P['range_min_width_pct']}%)")
    return a


# ─────────────────────────────── журнал ───────────────────────────────

def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(path: Path, st: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, default=float), encoding="utf-8")
    os.replace(tmp, path)


def _outcome(f: pd.DataFrame, t0: pd.Timestamp, ref: float, atr: float | None, hrs: int) -> dict | None:
    """Ход цены после решения по закрытым часам t0+1 … t0+hrs: доходность, максимум вверх и вниз (% и ATR)."""
    idx = pd.date_range(t0 + H1, t0 + hrs * H1, freq="1h")
    w = f.reindex(idx)
    if w["close"].isna().any():
        return None
    up = (w["high"].max() / ref - 1) * 100
    dn = (1 - w["low"].min() / ref) * 100
    out = {"ret_pct": (float(w["close"].iloc[-1]) / ref - 1) * 100, "max_up_pct": float(up), "max_down_pct": float(dn)}
    if atr:
        out.update(max_up_atr=float((w["high"].max() - ref) / atr), max_down_atr=float((ref - w["low"].min()) / atr))
    return out


def update(sym: str, df: pd.DataFrame, now: datetime, *, available_at: str | None = None, journal: Path = JOURNAL,
           state_path: Path = STATE) -> dict:
    """Обработать новые закрытые часы символа, записать решение по последнему, события и созревшие исходы.
    Первый запуск — прогрев по всей таблице (события помечены warmup и в счёт вперёд не идут)."""
    T = pd.Timestamp(now)
    closed = T.floor("1h")
    st = _load_state(state_path)
    sm = st.get(sym) or {}
    m = sm.get("m") or {}
    last = pd.Timestamp(sm["last_bar"]) if sm.get("last_bar") else None
    warm = last is None
    f = features(df)
    rows, latest = [], None
    have = compare._read_jsonl(journal)
    seen = {r["id"] for r in have if r.get("kind") == "decision" and r.get("sym") == sym and r.get("v") == VERSION}
    for t, row in f.iterrows():
        if t >= closed or (last is not None and t <= last):
            continue
        rec = step(m, t, row.to_dict(), sym)
        last = t
        lag_min = round((T - (t + H1)).total_seconds() / 60, 1)
        for e in rec["events"]:
            rows.append({"kind": "event", "v": VERSION, "sym": sym, "bar": rec["bar"], "detected_at": T.isoformat(
                timespec="seconds"), "lag_min": lag_min, "warmup": warm, **e})
        latest = (t, rec, lag_min)
    if latest is not None:
        t, rec, lag_min = latest
        did = f"{sym}:{rec['bar']}:{VERSION}"
        if did not in seen and t + H1 == closed:
            rows.append({"kind": "decision", "v": VERSION, "id": did, "sym": sym, "bar": rec["bar"],
                         "feature_cutoff": _ts(t + H1), "decision_at": T.isoformat(timespec="seconds"),
                         "available_at": available_at, "lag_min": lag_min, "forward": lag_min < 60,
                         "warmup": warm, "struct": rec["struct"], "state": rec["state"], "tags": rec["tags"],
                         "events": [e["e"] for e in rec["events"]], "box": rec["box"], "pend": rec["pend"],
                         "move": rec["move"], "cool_until": rec["cool_until"], "f": rec["f"],
                         "actions": {v: {"long": actions(rec, v, 1), "short": actions(rec, v, -1)}
                                     for v in ("price", "flow")}})
    done = {(r["ref"], r["h"]) for r in have if r.get("kind") == "outcome" and r.get("sym") == sym}
    breaks = [pd.Timestamp(x["bar"]) for x in have + rows if x.get("kind") == "event" and x.get("sym") == sym
              and x.get("v") == VERSION and x.get("e") == "STRUCTURE_BROKEN"]
    n_out = 0
    for r in have:                                              # исходы — только решений, записанных раньше
        if r.get("kind") != "decision" or r.get("sym") != sym or r.get("v") != VERSION:
            continue
        t0 = pd.Timestamp(r["bar"])
        for hrs in P["horizons_h"]:
            if (r["id"], f"{hrs}h") in done or t0 + (hrs + 1) * H1 > closed:
                continue
            o = _outcome(f, t0, r["f"]["close"], r["f"].get("atr"), hrs)
            if o is None:
                continue
            br = sorted(b for b in breaks if t0 < b <= t0 + hrs * H1)
            rows.append({"kind": "outcome", "v": VERSION, "sym": sym, "ref": r["id"], "h": f"{hrs}h",
                         "checked_at": T.isoformat(timespec="seconds"), "forward": r.get("forward"),
                         "state": r["state"], "structure_broken_at": br[0].isoformat() if br else None, **o})
            n_out += 1
    compare._write(journal, rows)
    if last is not None:
        st[sym] = {"last_bar": _ts(last), "m": m, "v": VERSION}
        _save_state(state_path, st)
    return {"events": sum(1 for r in rows if r["kind"] == "event"), "outcomes": n_out,
            "decision": next((r["state"] for r in rows if r["kind"] == "decision"), None)}


def latest_decision(sym: str, journal: Path | None = None, before=None) -> dict | None:
    """Последнее решение символа (до момента before, если задан)."""
    for r in reversed(compare._read_jsonl(journal or JOURNAL)):
        if r.get("kind") == "decision" and r.get("sym") == sym and r.get("v") == VERSION:
            if before is None or pd.Timestamp(r["bar"]) + H1 <= pd.Timestamp(before):
                return r
    return None


# ─────────────────────────────── карточка оператора ───────────────────────────────

def _f(x, d=0, sign=False):
    if x is None:
        return "нет данных"
    s = f"{x:+,.{d}f}" if sign else f"{x:,.{d}f}"
    return s.replace(",", " ").replace("-", "−")


def facts(rec: dict, coin: str) -> list[dict]:
    """Наблюдения часа по блокам: {block, text, dir} (dir: +1 за рост, −1 за падение, 0 — без направления)."""
    f = rec["f"]
    out = []
    if f.get("d6") is not None:
        strong = f["d6_thr"] is not None and abs(f["d6"]) > f["d6_thr"]
        thr = f" (порог {f['d6_thr']:.3f})" if f["d6_thr"] is not None else " (базы мало)"
        out.append({"block": "исполненные сделки", "dir": int(np.sign(f["d6"])) if strong else 0,
                    "text": (f"тейкеры 6 ч: чистая дельта {_f(f['net6'], 0, True)} {coin}, D6 {f['d6']:+.3f} — "
                             + ("сильнее 80% обычных окон" if strong else "в пределах обычного") + thr)
                    .replace("-", "−")})
    if f.get("bid_ask_delta") is not None:
        out.append({"block": "заявки стакана", "dir": int(np.sign(f["bid_ask_delta"])),
                    "text": f"стакан ±1% (заявки, не сделки): {'на покупку' if f['bid_ask_delta'] > 0 else 'на продажу'}"
                            f" больше на {_f(abs(f['bid_ask_delta']))} {coin}"})
    if f.get("mv6") is not None and f.get("atr"):
        x = f["mv6"] / f["atr"]
        out.append({"block": "реакция цены", "dir": int(np.sign(x)) if abs(x) >= P["weak_atr"] else 0,
                    "text": f"цена за 6 ч {_f(f['mv6'], 0, True)} ({x:+.1f} ATR)"})
    if None not in (f.get("lo_a"), f.get("lo_b"), f.get("hi_a"), f.get("hi_b")):
        up = f["lo_b"] > f["lo_a"] and f["hi_b"] > f["hi_a"]
        dn = f["lo_b"] < f["lo_a"] and f["hi_b"] < f["hi_a"]
        out.append({"block": "реакция цены", "dir": 1 if up else (-1 if dn else 0),
                    "text": "минимумы и максимумы последних 6 ч " + ("выше" if up else "ниже" if dn else "вперемешку с")
                            + " предыдущих 6 ч"})
    if f.get("er") is not None:
        out.append({"block": "реакция цены", "dir": 0, "flat": f["er"] <= P["er_flat"],
                    "text": f"эффективность хода за 24 ч ER {f['er']:.2f} ({'флет' if f['er'] <= P['er_flat'] else 'направленно'})"})
    if f.get("oi6") is not None:
        out.append({"block": "OI и ликвидации", "dir": 0,
                    "text": f"OI Binance за 6 ч {f['oi6']:+.2f}% (сторону инициатора OI не показывает)".replace("-", "−")})
    if f.get("liq_long") is not None and f.get("liq_short") is not None:
        ll, ls = f["liq_long"], f["liq_short"]
        dom = -1 if ll > 2 * ls else (1 if ls > 2 * ll else 0)
        out.append({"block": "OI и ликвидации", "dir": dom,
                    "text": f"ликвидации за час: лонги {compare._usd(ll)}, шорты {compare._usd(ls)}"})
    for col, name, fmt in (("ls_acc", "толпа L/S", "{:.2f}"), ("wi2", "Whale Index 2", "{:+.1f}"),
                           ("fr_pct", "фандинг", "{:.4f}%")):
        if f.get(col) is not None:
            out.append({"block": "позиционирование", "dir": 0, "text": f"{name} {fmt.format(f[col])}".replace("-", "−")})
    return out


def card(rec: dict, sym: str, now: datetime, variant: str = "flow") -> dict:
    """Карточка: состояние, время наблюдения и давность, 3 поддерживающих факта, 2 противоречия, границы, условие
    следующего перехода, теневое действие. Вероятность не показывается: сценарий не откалиброван."""
    coin = sym.replace("USDT", "")
    s = rec["state"][variant]
    if s == "DATA_UNKNOWN" and variant == "flow" and rec["state"]["price"] != "DATA_UNKNOWN":
        variant, s = "price", rec["state"]["price"]
    md = _move_dir(rec)
    sd = {"RANGE_BUY_PRESSURE": 1, "RANGE_SELL_PRESSURE": -1, "UP_CONFIRMED": 1, "DOWN_CONFIRMED": -1}.get(s, 0)
    if s in ("STALL_WARNING", "STRUCTURE_BROKEN") and md:
        sd = -md
    fs = facts(rec, coin)
    if sd:
        sup = [x for x in fs if x["dir"] == sd][:3]
        con = [x for x in fs if x["dir"] == -sd][:2]
    else:                                                       # флет и прочее без направления
        sup = [x for x in fs if x["dir"] == 0 and x.get("flat", True)][:3]
        con = [x for x in fs if x["dir"] != 0 or x.get("flat") is False][:2]
    box, mv, pend = rec.get("box"), rec.get("move"), rec.get("pend")
    n = lambda x: _f(x, 0 if x and abs(x) >= 100 else 2)   # noqa: E731
    if s in ("COOLDOWN", "STRUCTURE_BROKEN") and rec.get("cool_until"):
        nxt = (f"Пауза до {pd.Timestamp(rec['cool_until']).tz_convert(compare.WARSAW):%d.%m %H:%M} Варшава, затем "
               "новая коробка по 24 ч и новая проверка.")
    elif mv:
        d = mv["dir"]
        nxt = (f"Опора {n(mv['support'])}: закрытие часа {'ниже' if d > 0 else 'выше'} и следующий час не вернулся → "
               f"слом структуры. {'Новый максимум выше' if d > 0 else 'Новый минимум ниже'} {n(mv['extreme'])} — "
               "продолжение.")
    elif pend and box:
        edge = box["H"] if pend["side"] > 0 else box["L"]
        nxt = (f"Час закрылся {'выше' if pend['side'] > 0 else 'ниже'} {n(edge)}: если следующий час закроется там же — "
               f"{'рост' if pend['side'] > 0 else 'падение'} подтверждён, иначе ложный выход.")
    elif box:
        nxt = (f"Выход вверх: закрытие часа выше {n(box['H'])} и следующий час выше; вниз: ниже {n(box['L'])} и "
               "следующий час ниже.")
    else:
        nxt = "Ждём полные часовые данные."
    T = pd.Timestamp(now)
    cutoff = pd.Timestamp(rec["bar"]) + H1
    return {"sym": sym, "variant": variant, "state": s, "state_ru": RU.get(s, s), "struct": rec["struct"],
            "bar": rec["bar"], "observed_until": cutoff.isoformat(),
            "observed_warsaw": f"{cutoff.tz_convert(compare.WARSAW):%d.%m %H:%M}",
            "age_min": int((T - cutoff).total_seconds() // 60), "support": [x["text"] for x in sup],
            "contra": [x["text"] for x in con], "facts": fs, "tags": rec.get("tags", []),
            "box": box, "move": mv, "next": nxt,
            "actions": {"long": actions(rec, variant, 1), "short": actions(rec, variant, -1)},
            "note": "Теневой режим sc-1: решения только в журнал, живые сетки не трогаются. Вероятность не показываю — "
                    "сценарий не откалиброван (журнал с 28.10)."}


def current(sym: str, df: pd.DataFrame, now: datetime, journal: Path | None = None) -> tuple[dict | None, str]:
    """Последнее решение для карточки: из журнала, если оно по последнему или предпоследнему закрытому часу; иначе —
    расчёт по графику (прогрев с начала таблицы), с пометкой."""
    T = pd.Timestamp(now)
    r = latest_decision(sym, journal, before=T)
    if r is not None and pd.Timestamp(r["bar"]) >= T.floor("1h") - 2 * H1:
        return r, "журнал"
    recs, _m = replay(df, sym, until=T.floor("1h"))
    return (recs[-1] if recs else None), "расчёт по графику (журнал не свежий)"


# ─────────────────────────────── оценка (ретро и вперёд) ───────────────────────────────

def evaluate(recs: list[dict]) -> dict:
    """По записям часов (replay или журнал): предупреждения до слома, ложные паузы, опережение, выходы из коробки,
    давление во флете → направление следующего выхода. Одинаково для обоих вариантов — ценового и с потоком."""
    bars = [pd.Timestamp(r["bar"]) for r in recs]
    pos = {t: i for i, t in enumerate(bars)}
    close = np.array([np.nan if r["f"]["close"] is None else r["f"]["close"] for r in recs])
    atr = np.array([np.nan if r["f"]["atr"] is None else r["f"]["atr"] for r in recs])
    breaks = [(pd.Timestamp(r["bar"]), e) for r in recs for e in r["events"] if e["e"] == "STRUCTURE_BROKEN"]
    out = {"hours": len(recs), "breaks": len(breaks)}
    for variant in ("price", "flow"):
        st = [r["state"][variant] for r in recs]
        out[f"states_{variant}"] = {s: st.count(s) for s in STATES if st.count(s)}
        warns = [(pd.Timestamp(r["bar"]), e) for r in recs for e in r["events"]
                 if e["e"] == "STALL" and e.get("variant") == variant]
        hit, false_pause, leads = 0, 0, []
        for t, e in warns:
            b = next((bt for bt, be in breaks if bt > t and bt <= t + 24 * H1 and be["dir"] == e["dir"]), None)
            if b is not None:
                hit += 1
                leads.append((b - t) / H1)
                continue
            i = pos[t]
            j = min(len(recs) - 1, i + 24)
            if i + 1 <= j and not np.isnan(atr[i]):
                seg = close[i + 1:j + 1]
                adv = (np.nanmax(seg) - e["extreme"]) / atr[i] if e["dir"] > 0 else (e["extreme"] - np.nanmin(seg)) / atr[i]
                false_pause += bool(adv >= 1.0)
        warned = 0
        for bt, be in breaks:
            if any(t < bt and t >= bt - 24 * H1 and e["dir"] == be["dir"] for t, e in warns):
                warned += 1
        out[f"stall_{variant}"] = {"warnings": len(warns), "break_within_24h": hit,
                                   "false_pause_1atr": false_pause, "breaks_warned_24h": warned,
                                   "lead_h_median": float(np.median(leads)) if leads else None}
    conf = [(pd.Timestamp(r["bar"]), e) for r in recs for e in r["events"] if e["e"] == "BREAKOUT_CONFIRMED"]
    false = [1 for r in recs for e in r["events"] if e["e"] == "FALSE_BREAK"]
    out["breakouts"] = {"confirmed": len(conf), "false": len(false)}
    # давление во флете → направление следующего подтверждённого выхода из той же коробки
    nxt = {}
    for t, e in conf:
        nxt.setdefault(e["box"], e["dir"])
    tally = {}
    for r in recs:
        s = r["state"]["flow"]
        if s in ("RANGE", "RANGE_BUY_PRESSURE", "RANGE_SELL_PRESSURE") and r.get("box"):
            d = nxt.get(r["box"]["id"])
            if d is None:
                continue
            k = tally.setdefault(s, {"hours": 0, "up_next": 0})
            k["hours"] += 1
            k["up_next"] += d > 0
    out["range_pressure_next_breakout"] = tally
    # то же по КОРОБКАМ (часы одной коробки зависимы) и без последних 6 ч перед выходом (там давление — уже сам выход)
    when = {}
    for t, e in conf:
        when.setdefault(e["box"], (t, e["dir"]))
    boxes = {}
    for r in recs:
        b = r.get("box")
        if not b or b["kind"] != "flat" or b["id"] not in when:
            continue
        tb, d = when[b["id"]]
        if pd.Timestamp(r["bar"]) > tb - 6 * H1:
            continue
        k = boxes.setdefault(b["id"], {"dir": d, "buy": 0, "sell": 0})
        s = r["state"]["flow"]
        k["buy"] += s == "RANGE_BUY_PRESSURE"
        k["sell"] += s == "RANGE_SELL_PRESSURE"
    by = {"покупатели": [0, 0], "продавцы": [0, 0], "без давления": [0, 0]}
    for k in boxes.values():
        g = "покупатели" if k["buy"] > k["sell"] else ("продавцы" if k["sell"] > k["buy"] else "без давления")
        by[g][0] += 1
        by[g][1] += k["dir"] > 0
    out["boxes_pressure_lead6h"] = {g: {"boxes": n, "up_next": u} for g, (n, u) in by.items()}
    # длительность флета (часы от установки до выхода или перестройки) и ход после подтверждённого выхода (24 ч, ATR)
    dur, cont, against = [], [], []
    sets = {}
    for r in recs:
        for e in r["events"]:
            if e["e"] == "RANGE_SET":
                sets[e["box"]["id"]] = pd.Timestamp(r["bar"])
    for bid, t in sets.items():
        if bid in when:
            dur.append((when[bid][0] - t) / H1)
    for t, e in conf:
        i = pos[t]
        j = min(len(recs) - 1, i + 24)
        if i + 1 > j or np.isnan(atr[i]):
            continue
        seg = close[i + 1:j + 1]
        if e["dir"] > 0:
            cont.append((np.nanmax(seg) - close[i]) / atr[i])
            against.append((close[i] - np.nanmin(seg)) / atr[i])
        else:
            cont.append((close[i] - np.nanmin(seg)) / atr[i])
            against.append((np.nanmax(seg) - close[i]) / atr[i])
    out["flat_hours_to_breakout_median"] = float(np.median(dur)) if dur else None
    out["after_breakout_24h_atr"] = {"n": len(cont), "with_median": float(np.median(cont)) if cont else None,
                                     "against_median": float(np.median(against)) if against else None}
    return out
