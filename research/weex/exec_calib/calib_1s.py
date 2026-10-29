"""Калибровка модели исполнения сеток WEEX на секундах Binance (задача 28.10, перезапуск 29.10; разбор GPT
docs/WEEX_GPT_CRITICAL_REVIEW_2026-10-28.md §4.2, §4.3 п.4, §8, ответ 9).

ВОПРОС. Почему на мелких сетках B49/B89 биржа взяла на 17/19% больше тейков, чем бэктест на минутах (191 против 163,
95 против 80), а у BTC 0.6/1.4 совпадение точное. Частичных исполнений в окне нет (каждый тейк — своя заявка целиком).

ПРАВИЛА (записаны ДО прогона 29.10; под результат не меняются; всё, что не здесь, — чувствительность с пометкой).
Первая попытка 28.10 оборвалась на скачивании (архивы 18–21.10, результатов не было); тогда архив 28.10 ещё не вышел и
правила делили окно на два. 29.10 10:02 UTC архив 28.10 опубликован (HEAD 200) → окно одно, как в задаче.
1. Окно: с W0 = 18.10 16:16:00 UTC (первая полная минута после старта недели T0 = 16:15:21) по 2026-10-28 14:40:00 UTC
   (не включая). Сетки B34, B49, B89 и BTC (0.6/1.4), символ BTCUSDT. Старт — лоты и стоящий вход снимка
   state/grid_compare_start_20261018T161521Z.json; расписание размеров/потолков — week_reconcile.SCHEDULE.
2. Данные: Binance spot BTCUSDT klines 1s, daily zip + .CHECKSUM с data.binance.vision за 2026-10-18 … 2026-10-28.
   SHA-256 архива сверяется с .CHECKSUM; при несовпадении — одна перекачка; снова не совпал — прогон останавливается
   (окно без дня не считается). Время open_time: > 1e14 — микросекунды (÷1e6), иначе миллисекунды (÷1e3); число отметок,
   не кратных целой секунде, и дубли секунд — в отчёт. Сверка с копией frozen 1m (scratchpad wk1028/BTCUSDT_1m_2y.csv)
   по каждой минуте окна: закрытие последней секунды минуты = close 1m (главная доля), также open первой секунды,
   max high, min low; число минут копии без секунд и наоборот.
3. Правила модели — те же, что week_reconcile.sim(): следующий вход от НИЖНЕГО лота на шаг ниже (округление вниз к тику);
   без лотов — вход от максимума цены (подтяжка); лимитка исполняется по своей цене при касании; тейк каждого лота по его
   цели (округление вверх); потолок max(себестоимость, объём×цена) + вход ≤ cap и лотов < max; размеры по расписанию;
   мейкер 0.016% на каждое исполнение. Фандинг не считается (в сравнении его нет). Цены — Binance spot (не WEEX-перп).
   - M1  — минута 4 точками O, L/H, H/L, C — week_reconcile.sim() как есть на копии 1m (контроль: 163 тейка B49,
     80 B89; не совпало — так и пишется, сравнение остальных моделей всё равно печатается);
   - S1  — каждая секунда 4 точками O, L/H, H/L, C этой секунды — тот же week_reconcile.sim();
   - S1L — те же секунды; стоящие лимитки (вход и тейки) исполняются при касании в любой точке любой секунды; НОВЫЕ
     заявки — тейк только что купленного лота, следующий вход после исполнения входа, перестановка входа после тейка
     нижнего лота, вход после освобождения потолка, подтяжка входа без лотов, новый размер по расписанию — появляются
     только на ближайшем такте цикла: такты W0 + k·40 с. На такте (первая секунда данных с t ≥ такта) заявки
     ставятся по правилам sim() от состояния на начало такта (цена наблюдения — закрытие предыдущей секунды) и действуют
     с первой точки этой секунды; потолок и объём входа — на момент такта; до следующего такта вход один (после
     исполнения нового нет). Чувствительность: такт 20 с и 60 с — отдельной строкой. Других задержек, пропусков касания,
     фаз и коэффициентов нет.
4. Проверка кода до чтения результатов: движок S1L с тактом «сразу» (заявки после каждой точки) обязан дать то же, что
   week_reconcile.sim(), — входы, тейки, лоты точно, закрыто/комиссии/объём/объём лотов — до 1e-6 — на M1 и на S1, все
   четыре сетки. Не совпало у сетки — её S1L не публикуется.
5. Биржа: week_reconcile.live() по журналам state/ (только чтение) в том же окне: входы и тейки (заявки), объём $,
   закрыто $ (pnl журнала), комиссии (включая поздние), лоты на конце (снимок + входы − тейки).
6. «Ближе к бирже» — меньше сумма |модель − биржа| / биржа по ТЕЙКАМ четырёх сеток (главная мера); те же суммы по
   входам и по закрыто $ — справка. «Насколько 4-точечная минута занижает оборот мелкого шага» — (M1 − S1L40)/S1L40 по
   тейкам и по объёму $ у B34/B49/B89 (и (M1 − биржа)/биржа); доля разрыва «биржа − M1», которую закрывает S1L40, —
   (S1L40 − M1)/(биржа − M1).
7. Справка (не для подгонки): удержание лота от входа до тейка (для лотов, купленных в окне) у биржи и моделей по
   корзинам <60 с, 60–300 с, 5–60 мин, >1 ч; интервалы между соседними входами < 20/40/60 с у биржи и моделей
   (у биржи — по времени строк журнала, т.е. по циклу, в котором исполнение увидено).
Запуск: OMP_NUM_THREADS=2 nice -n 20 <venv>/python3 -I research/weex/exec_calib/calib_1s.py → calib_result.json.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/alexeychechikov/code/bot7/research/weex")
import week_reconcile as wr  # noqa: E402

HERE = "/Users/alexeychechikov/code/bot7/research/weex/exec_calib/"
DATA = HERE + "data/"
OUT = HERE + "calib_result.json"
COPY = ("/private/tmp/claude-501/-Users-alexeychechikov/1447ae84-81fe-465b-ad50-d8cc845df051/scratchpad/wk1028/"
        "BTCUSDT_1m_2y.csv")
BASE = "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1s/"
DAYS = [f"2026-10-{d:02d}" for d in range(18, 29)]
END = wr.ts("2026-10-28T14:40:00+00:00")
GRIDS = ("B34", "B49", "B89", "BTC")
LAT = 40
SENS = (20, 60)
BUCKETS = ((0, 60, "<60с"), (60, 300, "60–300с"), (300, 3600, "5–60мин"), (3600, math.inf, ">1ч"))


def log(*a) -> None:
    print(*a, flush=True)


def sha_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head() -> str:
    root = "/Users/alexeychechikov/code/bot7/.git/"
    head = open(root + "HEAD", encoding="utf-8").read().strip()
    if not head.startswith("ref: "):
        return head
    ref = head[5:]
    if os.path.exists(root + ref):
        return open(root + ref, encoding="utf-8").read().strip()
    for line in open(root + "packed-refs", encoding="utf-8"):
        if line.strip().endswith(" " + ref):
            return line.split()[0]
    return head


def _download(url: str, path: str) -> None:
    last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                body = r.read()
            with open(path + ".part", "wb") as f:
                f.write(body)
            os.replace(path + ".part", path)
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            time.sleep(3)
    raise RuntimeError(f"{url}: {last}")


def fetch(day: str) -> dict:
    name = f"BTCUSDT-1s-{day}.zip"
    out = {"day": day, "file": name, "redownloaded": False}
    for attempt in range(2):
        for suf in (".CHECKSUM", ""):
            path = DATA + name + suf
            if attempt == 1 or not os.path.exists(path):
                _download(BASE + name + suf, path)
        want = open(DATA + name + ".CHECKSUM", encoding="utf-8").read().split()[0].lower()
        got = sha_file(DATA + name)
        out.update(sha256=got, checksum=want, status="ok" if got == want else "checksum mismatch")
        if got == want:
            return out
        out["redownloaded"] = True
    return out


def load_1s(files: list) -> tuple[pd.DataFrame, dict]:
    frames, meta = [], {}
    for f in files:
        with zipfile.ZipFile(DATA + f["file"]) as z:
            inner = z.namelist()
            raw = pd.read_csv(z.open(inner[0]), header=None, usecols=[0, 1, 2, 3, 4], dtype=str)
        first = pd.to_numeric(raw[0], errors="coerce")
        hdr = int(first.isna().sum())
        raw = raw[first.notna()]
        t = pd.to_numeric(raw[0]).to_numpy(np.int64)
        unit = 1_000_000 if t[0] > 1e14 else 1000
        meta[f["day"]] = {"inner": inner, "rows": int(len(t)), "header_rows": hdr,
                          "unit": "мкс" if unit == 1_000_000 else "мс",
                          "not_whole_second": int((t % unit != 0).sum()),
                          "first": datetime.fromtimestamp(int(t.min() // unit), timezone.utc).isoformat(),
                          "last": datetime.fromtimestamp(int(t.max() // unit), timezone.utc).isoformat()}
        frames.append(pd.DataFrame({"t": t // unit,
                                    "open": pd.to_numeric(raw[1]).to_numpy(float),
                                    "high": pd.to_numeric(raw[2]).to_numpy(float),
                                    "low": pd.to_numeric(raw[3]).to_numpy(float),
                                    "close": pd.to_numeric(raw[4]).to_numpy(float)}))
    d = pd.concat(frames, ignore_index=True).sort_values("t", kind="stable")
    meta["_dup_seconds"] = int(d["t"].duplicated().sum())
    d = d.drop_duplicates("t", keep="first").reset_index(drop=True)
    return d, meta


def check_vs_copy(d: pd.DataFrame, cp: pd.DataFrame) -> dict:
    x = d[(d["t"] >= wr.W0) & (d["t"] < END)]
    m = x.assign(m=x["t"] // 60 * 60).groupby("m").agg(o=("open", "first"), h=("high", "max"), l=("low", "min"),
                                                       c=("close", "last"), n=("t", "size"))
    c = cp[(cp["s"] >= wr.W0) & (cp["s"] < END)].set_index("s")
    j = m.join(c, how="inner")
    return {"minutes_copy": int(len(c)), "minutes_1s": int(len(m)), "minutes_joined": int(len(j)),
            "close": float((np.abs(j["c"] - j["close"]) < 1e-9).mean()),
            "open": float((np.abs(j["o"] - j["open"]) < 1e-9).mean()),
            "high": float((np.abs(j["h"] - j["high"]) < 1e-9).mean()),
            "low": float((np.abs(j["l"] - j["low"]) < 1e-9).mean()),
            "seconds_in_window": int(len(x)), "seconds_expected": int(END - wr.W0),
            "seconds_per_minute_min": int(j["n"].min()), "seconds_per_minute_median": float(j["n"].median()),
            "minutes_in_copy_without_seconds": int(len(set(c.index) - set(m.index))),
            "minutes_with_seconds_not_in_copy": int(len(set(m.index) - set(c.index)))}


def rows_1s(d: pd.DataFrame, t0: float, t1: float):
    x = d[(d["t"] >= t0) & (d["t"] < t1)]
    o, h, l, c = (x[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    up = c >= o
    pts = np.c_[o, np.where(up, l, h), np.where(up, h, l), c].tolist()
    return x["t"].to_numpy(np.int64).tolist(), pts


def run(name: str, g: dict, cfg: dict, tms, pts, lat: int | None) -> dict:
    """Движок S1L. lat=None — заявки сразу после каждой точки (правила week_reconcile.sim() точка в точку);
    lat=L — новые заявки только на тактах W0 + k·L (см. правило 3)."""
    step, tgt, tick = cfg["step_pct"] / 100, cfg["target_pct"] / 100, float(cfg["price_tick"])
    sched = wr.SCHEDULE[name]
    inst = lat is None
    # лот: [вход, объём, цель, тейк стоит?, время входа (None — лот снимка)]
    lots = [[float(x["entry"]), float(x["qty"]), float(x["tp"]), True, None] for x in g["sides"]["LONG"]["lots"]]
    e0 = g["sides"]["LONG"].get("entry_order")
    st = {"pending": float(e0["price"]) if e0 else None,
          "pending_q": float(e0["qty"]) if e0 and e0.get("qty") is not None else None,
          "ref": None}
    order = None                                   # стоящий вход (цена, объём)
    ent = tk = 0
    vol = real = fee = 0.0
    holds, etimes = [], []
    si = -1
    last_k = None
    p_prev = None
    min_tp = min((x[2] for x in lots), default=math.inf)
    dirty = True
    q = cap = mx = None

    def place(p_obs: float, lots_: list, q_: float, cap_: float, mx_: int):
        if lots_:
            st["ref"] = min(x[0] for x in lots_)
            lvl = wr.round_tick(st["ref"] * (1 - step), tick, up=False)
            st["pending"] = None
        else:
            st["ref"] = p_obs if st["ref"] is None else max(st["ref"], p_obs)
            lvl = st["pending"] if st["pending"] else wr.round_tick(st["ref"] * (1 - step), tick, up=False)
        cost, qty = sum(x[0] * x[1] for x in lots_), sum(x[1] for x in lots_)
        qf = st["pending_q"] if st["pending"] is not None and lvl == st["pending"] and st["pending_q"] else q_
        if len(lots_) < mx_ and max(cost, qty * lvl) + qf * lvl <= cap_:
            return (lvl, qf)
        return None

    for t, row in zip(tms, pts):
        nsi = si
        while nsi + 1 < len(sched) and t >= sched[nsi + 1][0]:
            nsi += 1
        if nsi != si:
            si = nsi
            q, cap, mx = float(sched[si][1]), sched[si][2], sched[si][3]
            dirty = True
        if not inst:
            k = int((t - wr.W0) // lat)
            if last_k is None or k > last_k:
                last_k = k
                for x in lots:
                    x[3] = True
                min_tp = min((x[2] for x in lots), default=math.inf)
                order = place(p_prev if p_prev is not None else row[0], lots, q, cap, mx)
        for p in row:
            if p >= min_tp:
                keep = []
                for lot in lots:
                    if lot[3] and p >= lot[2]:
                        real += lot[1] * (lot[2] - lot[0])
                        fee += lot[1] * lot[2] * wr.MAKER
                        vol += lot[1] * lot[2]
                        tk += 1
                        if lot[4] is not None:
                            holds.append(t - lot[4])
                    else:
                        keep.append(lot)
                lots = keep
                min_tp = min((x[2] for x in lots if x[3]), default=math.inf)
                dirty = True
            if inst and (dirty or not lots):
                order = place(p, lots, q, cap, mx)
                dirty = False
            if order is not None and p <= order[0]:
                lvl, qf = order
                tp = wr.round_tick(lvl * (1 + tgt), tick, up=True)
                lots.append([lvl, qf, tp, inst, t])
                if inst:
                    min_tp = min(min_tp, tp)
                fee += qf * lvl * wr.MAKER
                vol += qf * lvl
                ent += 1
                etimes.append(t)
                st["pending"] = st["pending_q"] = None
                order = None
                dirty = True
        p_prev = row[3]
    return {"ent": ent, "tk": tk, "vol": vol, "real": real, "fee": fee, "lots": len(lots),
            "qty": sum(x[1] for x in lots), "cost": sum(x[0] * x[1] for x in lots), "holds": holds,
            "etimes": etimes}


def buckets(holds: list) -> dict:
    return {lab: int(sum(1 for h in holds if a <= h < b)) for a, b, lab in BUCKETS}


def gaps(etimes: list) -> dict:
    g = np.diff(np.asarray(sorted(etimes), dtype=float))
    if not len(g):
        return {"n_gaps": 0}
    return {"n_gaps": int(len(g)), "lt20": int((g < 20).sum()), "lt40": int((g < 40).sum()),
            "lt60": int((g < 60).sum()), "min": float(g.min()), "p10": float(np.percentile(g, 10)),
            "median": float(np.median(g))}


def live_extra(name: str, t_end: float, tick: float) -> dict:
    """Удержание лотов биржи (вход в окне → тейк) и интервалы между соседними входами (по времени строк журнала)."""
    ent, tps, seen = [], [], {"вход": set(), "тейк": set()}
    for line in open(wr.ST + wr.JOURNAL[name], encoding="utf-8"):
        r = json.loads(line)
        if r.get("dry") or r.get("side") != "LONG" or r.get("kind") not in ("вход", "тейк"):
            continue
        t = wr.ts(r["ts"])
        if t > t_end:
            continue
        oid = r.get("order_id")
        if oid is not None:
            if oid in seen[r["kind"]]:
                continue
            seen[r["kind"]].add(oid)
        if r["kind"] == "вход":
            ent.append([t, float(r["price"]), False])
        elif t >= wr.W0:
            tps.append((t, float(r.get("entry") or 0)))
    ent.sort()
    holds, old = [], 0
    for t, e in sorted(tps):
        cand = [x for x in ent if not x[2] and x[0] <= t and abs(x[1] - e) < tick / 2]
        if not cand:
            old += 1
            continue
        x = cand[-1]
        x[2] = True
        if x[0] >= wr.W0:
            holds.append(t - x[0])
        else:
            old += 1
    return {"holds": holds, "old_lot_tps": old, "etimes": [x[0] for x in ent if x[0] >= wr.W0]}


def pack(x: dict, pe: float, extra: dict | None = None) -> dict:
    d = {k: (round(float(v), 6) if isinstance(v, float) else v) for k, v in x.items()
         if k in ("ent", "tk", "vol", "real", "fee", "lots", "qty")}
    if "bag" in x:
        d["bag"] = round(float(x["bag"]), 4)
    elif "cost" in x:
        d["bag"] = round(x["qty"] * pe - x["cost"], 4)
    if "holds" in x:
        d["holds"] = buckets(x["holds"])
    if "etimes" in x:
        d["entry_gaps"] = gaps(x["etimes"])
    if extra:
        d.update(extra)
    return d


def same(a: dict, b: dict) -> tuple[bool, float]:
    ok = all(a[k] == b[k] for k in ("ent", "tk", "lots"))
    md = max(abs(a[k] - b[k]) for k in ("real", "fee", "vol", "qty"))
    return bool(ok and md < 1e-6), float(md)


def main() -> None:
    t_start = time.time()
    res = {"rules_doc": "см. docstring calib_1s.py", "created_utc": datetime.now(timezone.utc).isoformat(),
           "git_head": git_head(),
           "window": {"W0": datetime.fromtimestamp(wr.W0, timezone.utc).isoformat(),
                      "end": datetime.fromtimestamp(END, timezone.utc).isoformat()},
           "inputs": {"week_reconcile.py": sha_file("/Users/alexeychechikov/code/bot7/research/weex/week_reconcile.py"),
                      "snapshot": sha_file(wr.SNAP), "copy_1m": sha_file(COPY), "calib_1s.py": sha_file(__file__),
                      "journals": {n: sha_file(wr.ST + wr.JOURNAL[n]) for n in GRIDS}}}
    files = []
    for day in DAYS:
        f = fetch(day)
        files.append(f)
        log(f"архив {day}: {f['status']}{' (перекачан)' if f['redownloaded'] else ''}")
    res["archives"] = files
    bad = [f["day"] for f in files if f.get("status") != "ok"]
    if bad:
        res["stopped"] = f"архивы не прошли .CHECKSUM: {bad}"
        json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        raise SystemExit(res["stopped"])
    d, meta = load_1s(files)
    res["archives_meta"] = meta
    log("секунды:", json.dumps({k: (v["unit"], v["rows"], v["not_whole_second"]) if k[0] != "_" else v
                               for k, v in meta.items()}, ensure_ascii=False))
    cp = pd.read_csv(COPY)
    cp["s"] = cp["ts"] // 1000
    res["check_1s_vs_1m"] = check_vs_copy(d, cp)
    log("сверка 1s → 1m:", json.dumps(res["check_1s_vs_1m"], ensure_ascii=False))
    if int(d["t"].min()) > wr.W0 or int(d["t"].max()) < END - 60:
        res["stopped"] = "секунды не покрывают окно"
        json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        raise SystemExit(res["stopped"])

    wr.SRC["BTCUSDT"] = COPY
    m_t, m_p, m_c = wr.load("BTCUSDT", END)
    pe = float(m_c[-1])
    s_t, s_p = rows_1s(d, wr.W0, END)
    del d
    res["rows"] = {"M1_minutes": len(m_t), "S1_seconds": len(s_t), "pe": pe,
                   "last_minute": datetime.fromtimestamp(int(m_t[-1]), timezone.utc).isoformat()}
    log("строк:", res["rows"])
    snap = json.load(open(wr.SNAP))
    checks, out = {}, {}
    m_tl = m_t.tolist()
    for name in GRIDS:
        g = snap["grids"][name]
        cfg = g["config"]
        tick = float(cfg["price_tick"])
        o = {}
        tt = time.time()
        m1 = wr.sim(name, g, cfg, m_t, m_p, m_c, {})
        e_m1 = run(name, g, cfg, m_tl, m_p, None)
        e_s1 = run(name, g, cfg, s_t, s_p, None)
        lv = wr.live(name, g, END, pe)
        ex = live_extra(name, END, tick)
        o["биржа"] = pack(lv, pe, {"holds": buckets(ex["holds"]), "old_lot_tps": ex["old_lot_tps"],
                                   "entry_gaps": gaps(ex["etimes"]), "unmatched_qty": lv["unmatched_qty"],
                                   "gap_rows_T0_W0": lv["gap_rows"]})
        o["M1"] = pack(m1, pe, {"holds": buckets(e_m1["holds"]), "entry_gaps": gaps(e_m1["etimes"])})
        lat_res = {L: run(name, g, cfg, s_t, s_p, L) for L in (LAT,) + SENS}
        log(f"{name}: M1/движок/S1L за {time.time() - tt:.0f} с; M1 тейков {m1['tk']}, биржа {lv['tk']}; "
            f"S1L40 тейков {lat_res[LAT]['tk']} (до проверки S1 = sim())")
        tt = time.time()
        s1 = wr.sim(name, g, cfg, s_t, s_p, [pe], {})
        t_s1 = time.time() - tt
        checks[name] = {"M1": same(m1, e_m1), "S1": same(s1, e_s1)}
        ok = all(v[0] for v in checks[name].values())
        o["S1"] = pack(s1, pe, {"holds": buckets(e_s1["holds"]), "entry_gaps": gaps(e_s1["etimes"])})
        for L in (LAT,) + SENS:
            tag = f"S1L{L}" + ("" if L == LAT else " (чувствительность)")
            o[tag] = pack(lat_res[L], pe) if ok else {"не публикуется": "движок ≠ sim()"}
        out[name] = o
        log(f"{name}: sim() на секундах {t_s1:.0f} с; движок = sim(): {ok} "
            f"(M1 {checks[name]['M1'][1]:.1e}, S1 {checks[name]['S1'][1]:.1e})")
    res["engine_equals_sim"] = {n: {k: {"ok": v[0], "max_abs_diff": v[1]} for k, v in c.items()}
                                for n, c in checks.items()}
    res["control_M1"] = {"B49_tk": out["B49"]["M1"]["tk"], "B89_tk": out["B89"]["M1"]["tk"],
                         "ok": out["B49"]["M1"]["tk"] == 163 and out["B89"]["M1"]["tk"] == 80}
    res["grids"] = out

    # правило 6
    models = [m for m in out["B49"] if m != "биржа" and "tk" in out["B49"][m]]
    summ = {}
    for metric in ("tk", "ent", "real"):
        summ[metric] = {}
        for m in models:
            if not all("tk" in out[n].get(m, {}) for n in GRIDS):
                continue
            summ[metric][m] = round(sum(abs(out[n][m][metric] - out[n]["биржа"][metric]) / abs(out[n]["биржа"][metric])
                                        for n in GRIDS if out[n]["биржа"][metric]), 4)
    res["closeness_sum_rel_err"] = summ
    under = {}
    for name in GRIDS:
        a = out[name]
        s1l, m1, lv = a.get(f"S1L{LAT}", {}), a["M1"], a["биржа"]
        if "tk" not in s1l:
            continue
        under[name] = {"tk_M1_vs_S1L40": round((m1["tk"] - s1l["tk"]) / s1l["tk"], 4) if s1l["tk"] else None,
                       "vol_M1_vs_S1L40": round((m1["vol"] - s1l["vol"]) / s1l["vol"], 4) if s1l["vol"] else None,
                       "tk_M1_vs_live": round((m1["tk"] - lv["tk"]) / lv["tk"], 4) if lv["tk"] else None,
                       "vol_M1_vs_live": round((m1["vol"] - lv["vol"]) / lv["vol"], 4) if lv["vol"] else None,
                       "tk_S1L40_vs_live": round((s1l["tk"] - lv["tk"]) / lv["tk"], 4) if lv["tk"] else None,
                       "gap_closed_tk": round((s1l["tk"] - m1["tk"]) / (lv["tk"] - m1["tk"]), 4)
                       if lv["tk"] != m1["tk"] else None}
    res["understatement"] = under
    res["runtime_sec"] = round(time.time() - t_start, 1)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

    log(f"\n{'сетка':<5} {'модель':<26} {'входы':>6} {'тейки':>6} {'объём $':>9} {'закрыто':>8} {'комисс.':>7} "
        f"{'лотов':>5} {'мешок':>8} | {'<60с':>5} {'1-5м':>5} {'5-60м':>5} {'>1ч':>5} | вх<40с")
    for name in GRIDS:
        for m, x in out[name].items():
            if "tk" not in x:
                log(f"{name:<5} {m:<26} {x}")
                continue
            hb = x.get("holds") or {}
            eg = (x.get("entry_gaps") or {}).get("lt40", "")
            log(f"{name:<5} {m:<26} {x['ent']:6d} {x['tk']:6d} {x['vol']:9,.0f} {x['real']:+8.2f} "
                f"{-x['fee']:+7.2f} {x['lots']:5d} {x['bag']:+8.2f} | "
                + " ".join(f"{hb.get(b[2], ''):>5}" for b in BUCKETS) + f" | {eg}")
    log("\nконтроль M1 163/80:", res["control_M1"])
    log("сумма отн. ошибок:", json.dumps(summ, ensure_ascii=False))
    log("занижение M1:", json.dumps(under, ensure_ascii=False))
    log(f"\nготово за {res['runtime_sec']} с → {OUT}")


if __name__ == "__main__":
    main()
