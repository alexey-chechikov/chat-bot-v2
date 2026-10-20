"""Прогноз РАЗМАХА на сутки (не направления) для утренней сводки — версия dr-2 (19.10.2026, по разбору GPT
docs/COINGLASS_HANDOVER_PASS_AND_DAY_RANGE_REVIEW_2026-10-19.md).

Контракт dr-2:
  - прогноз выдаётся в момент T (сборка карточки). Опорная цена P — close последней ЗАКРЫТОЙ минуты до T (минута A−2);
    окно исхода — от A = первой полной минуты после T до следующего местного 08:00 Варшавы (1380/1440/1500 минут при
    переводе часов). ATR14 — простое среднее 14 TR по 15 часам, закрытым до начала часа T;
  - история — 730 дней из замороженных минуток Binance UM в ТОЙ ЖЕ фазе: A_j = 08:00 + (A − 08:00), P_j — close минуты
    A_j−2, часы ATR с тем же сдвигом, окно до местного 08:00 следующего дня;
  - коридор — квантиль 90% хода вверх и 90% хода вниз ПО ОТДЕЛЬНОСТИ (это не 90% всего коридора); в карточке —
    фактическое совместное покрытие на проверке вне выборки по каждой монете;
  - шанс коснуться уровня — частота, с которой цена проходила то же расстояние в ATR. Это геометрия и волатильность:
    сила/плотность зоны CoinGlass в расчёт не входит, добавочной ценности карты это не доказывает (её проверяет C1);
  - зоны — только из снимка, полученного ДО T (не старше 70 мин), с run_id, временем получения и SHA записи снимка;
  - dr-3: прогноз записывается, только если фактическое время фиксации (fixed_utc) раньше A; иначе пересчёт целиком
    с нового среза (до 3 раз), затем пропуск с причиной; сначала догружаются проверки, срез T — свежий на монету;
    проверка метода подписана своей фазой (08:01) отдельной строкой; кеш базы привязан к SHA, прежние базы
    и манифесты архивируются по SHA перед пересборкой (база и валидация dr-2 и dr-3 одни и те же);
  - каждый запуск проверяет все созревшие и ещё не оценённые прогнозы; сбой → запись pending с причиной и повтор;
    зрелость — по фактическому текущему времени; сводка: выдано / проверено / ждут / пропущено;
  - записи прежней версии (без "algo") не переписываются и в статистику dr-2 не входят.
Файлы state/coinglass/: day_range_base_<SYM>.npz + day_range_manifest.json (строятся один раз из frozen, с SHA и
проверкой вне выборки), day_range_log.jsonl (прогнозы, проверки, pending).
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

from services.coinglass_web.collector import DIR, ROOT

ALGO = "dr-3"                              # dr-3 (19.10): дедлайн фиксации до A, подпись фазы проверки, кеш по SHA
WARSAW = ZoneInfo("Europe/Warsaw")
SYMS = ("BTCUSDT", "ETHUSDT")
LOG = DIR / "day_range_log.jsonl"
MANIFEST = DIR / "day_range_manifest.json"
Q = 0.90                                  # квантиль КАЖДОЙ стороны коридора (не всего коридора)
MIN, HOUR = 60_000, 3_600_000
HOUR_LOCAL = 8
N_DAYS = 730
LATE_MIN = 15                             # выдан позже 08:15 — помечается поздним (окно короче)
DISTS = (0.5, 1, 2, 3, 4, 6, 8)           # расстояния в ATR для проверки калибровки


def _get(url: str):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}),
                                             timeout=20).read())


def klines(sym: str, interval: str, start_ms: int, end_ms: int) -> list:
    """Binance USDⓈ-M свечи [start, end) по openTime."""
    out, t, step = [], start_ms, {"1m": MIN, "1h": HOUR}[interval]
    while t < end_ms:
        rows = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval={interval}&limit=1500"
                    f"&startTime={t}&endTime={end_ms - 1}")
        if not rows:
            break
        out += [r for r in rows if int(r[0]) < end_ms]
        t = int(rows[-1][0]) + step
    return out


def atr14(h: list, lo: list, c: list) -> float:
    """Простое среднее 14 TR по 15 свечам (первая — только для previous close). Не Уайлдер."""
    tr = [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, 15)]
    return sum(tr) / 14


def anchor_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, HOUR_LOCAL, tzinfo=WARSAW).timestamp() * 1000)


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- замороженная база (один раз)
def _base_path(sym: str):
    return DIR / f"day_range_base_{sym}.npz"


def _hist(B: dict, k_min: int, h_off: int, days=None) -> tuple[np.ndarray, np.ndarray]:
    """Ходы вверх/вниз в ATR для каждого дня базы в фазе (k_min минут после 08:00, часы ATR до 08:00+h_off)."""
    ts = B["ts"]
    up, dn = [], []
    for d in (days if days is not None else B["days"]):
        d = date.fromisoformat(str(d))
        an = anchor_ms(d)
        a, end, H = an + k_min * MIN, anchor_ms(d + timedelta(days=1)), an + h_off * HOUR
        ia, ie, ip, ih = (int(np.searchsorted(ts, x)) for x in (a, end, a - 2 * MIN, H - 15 * HOUR))
        n = len(ts)
        if max(ia, ip, ih + 899) >= n or ie > n or ie - ia != (end - a) // MIN or ts[ia] != a \
                or ts[ie - 1] != end - MIN or ts[ip] != a - 2 * MIN or ts[ih] != H - 15 * HOUR \
                or ts[ih + 899] != H - MIN:
            up.append(np.nan)
            dn.append(np.nan)
            continue
        hs = [float(B["high"][ih + 60 * m:ih + 60 * m + 60].max()) for m in range(15)]
        ls = [float(B["low"][ih + 60 * m:ih + 60 * m + 60].min()) for m in range(15)]
        cs = [float(B["close"][ih + 60 * m + 59]) for m in range(15)]
        atr, p = atr14(hs, ls, cs), float(B["close"][ip])
        up.append((float(B["high"][ia:ie].max()) - p) / atr)
        dn.append((p - float(B["low"][ia:ie].min())) / atr)
    return np.array(up), np.array(dn)


def _validate(B: dict) -> dict:
    """Вне выборки в фазе 08:01 (типичная выдача): первая половина дней — подбор, вторая — проверка."""
    up, dn = _hist(B, 1, 0)
    ok = ~(np.isnan(up) | np.isnan(dn))
    days = [d for d, o in zip(B["days"], ok) if o]
    up, dn = up[ok], dn[ok]
    half = len(days) // 2
    tu, td, vu, vd = up[:half], dn[:half], up[half:], dn[half:]
    qu, qd = float(np.quantile(tu, Q)), float(np.quantile(td, Q))
    pr, ac, day_of = [], [], []
    for i in range(len(vu)):
        for tr_arr, real in ((tu, vu[i]), (td, vd[i])):
            for dd in DISTS:
                pr.append(float(np.mean(tr_arr >= dd)))
                ac.append(float(real >= dd))
                day_of.append(i)
    pr, ac, day_of = np.array(pr), np.array(ac), np.array(day_of)
    base_rate = float(np.mean([np.mean(a >= dd) for a in (tu, td) for dd in DISTS]))
    bins = []
    for lo_, hi_ in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)):
        m = (pr >= lo_) & (pr < hi_)
        if m.sum():
            bins.append({"promised": round(float(pr[m].mean()), 3), "realized": round(float(ac[m].mean()), 3),
                         "queries": int(m.sum()), "days": int(len(set(day_of[m].tolist())))})
    return {"phase": "08:01, часы ATR до 08:00", "train": [days[0], days[half - 1]], "test": [days[half], days[-1]],
            "n_train_days": half, "n_test_days": len(days) - half,
            "marginal_up_inside": round(float(np.mean(vu <= qu)), 3),
            "marginal_down_inside": round(float(np.mean(vd <= qd)), 3),
            "joint_inside": round(float(np.mean((vu <= qu) & (vd <= qd))), 3),
            "touch_bins": bins, "queries": int(len(pr)), "distances_atr": list(DISTS),
            "brier_model": round(float(np.mean((pr - ac) ** 2)), 4),
            "brier_baseline_const": round(float(np.mean((base_rate - ac) ** 2)), 4),
            "baseline_definition": "одна частота касания по всем расстояниям и сторонам на подборе (без учёта "
                                   "расстояния)",
            "note": "запросы зависимы внутри дня (2 стороны × 7 расстояний); единица независимости — день"}


def build_base(syms=SYMS) -> dict:
    """Минутки frozen → npz на монету; последние N_DAYS полных дней [08:00−15ч; 08:00 след. дня); пропуски считаются."""
    import pandas as pd
    man = {"algo": ALGO, "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "symbols": {}}
    for sym in syms:
        src = ROOT / "backtests" / "frozen" / f"{sym}_UM_1m.csv"
        d = pd.read_csv(src, usecols=["ts", "open", "high", "low", "close"]).drop_duplicates("ts").sort_values("ts")
        ts = d.ts.to_numpy(dtype=np.int64)
        cutoff = datetime.fromtimestamp(ts[-1] / 1000, timezone.utc)
        day = cutoff.astimezone(WARSAW).date() - timedelta(days=1)
        days, skipped = [], []
        while len(days) < N_DAYS and len(skipped) < 120:
            a0, a1 = anchor_ms(day) - 15 * HOUR, anchor_ms(day + timedelta(days=1))
            i0, i1 = int(np.searchsorted(ts, a0)), int(np.searchsorted(ts, a1))
            if a1 <= ts[-1] and i1 - i0 == (a1 - a0) // MIN and ts[i0] == a0 and ts[i1 - 1] == a1 - MIN:
                days.append(day.isoformat())
            elif a1 <= ts[-1]:
                skipped.append(day.isoformat())
            day -= timedelta(days=1)
        days = days[::-1]
        lo_ms = anchor_ms(date.fromisoformat(days[0])) - 16 * HOUR
        m = ts >= lo_ms
        path = _base_path(sym)
        _archive(path, f"{sym}_")                               # прежняя база — в архив по SHA, не теряется
        np.savez(path, ts=ts[m], open=d.open.to_numpy()[m], high=d.high.to_numpy()[m], low=d.low.to_numpy()[m],
                 close=d.close.to_numpy()[m], days=np.array(days))
        B = _load(sym, verify=False)
        man["symbols"][sym] = {"source": src.name, "source_sha256": sha_bytes(src.read_bytes()),
                               "npz_sha256": sha_bytes(path.read_bytes()), "cutoff_utc": cutoff.isoformat(),
                               "days": [days[0], days[-1]], "n_days": len(days), "skipped_incomplete": skipped,
                               "validation": _validate(B)}
    _archive(MANIFEST, "manifest_")
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    man["manifest_sha256"] = sha_bytes(MANIFEST.read_bytes())
    _B.clear()
    return man


def _archive(path, prefix: str) -> None:
    """Перед перезаписью — копия по SHA в day_range_archive/: старые прогнозы остаются воспроизводимыми."""
    if path.exists():
        arch = DIR / "day_range_archive"
        arch.mkdir(parents=True, exist_ok=True)
        dst = arch / f"{prefix}{sha_bytes(path.read_bytes())}{path.suffix}"
        if not dst.exists():
            dst.write_bytes(path.read_bytes())


_B: dict = {}                             # sym → (npz_sha256, база): кеш привязан к SHA из манифеста


def _load(sym: str, verify: bool = True, want: str | None = None) -> dict:
    """База монеты, согласованная с манифестом (SHA `want` из уже прочитанного манифеста): SHA файла сверяется;
    кеш привязан к SHA — сменился SHA в манифесте → перечитать, файл не тот → отказ."""
    path = _base_path(sym)
    if not verify:
        z = np.load(path)
        B = {k: z[k] for k in z.files}
        B["days"] = [str(x) for x in B["days"]]
        return B
    want = want or json.loads(MANIFEST.read_text(encoding="utf-8"))["symbols"][sym]["npz_sha256"]
    if sym in _B and _B[sym][0] == want:
        return _B[sym][1]
    if sha_bytes(path.read_bytes()) != want:
        raise RuntimeError(f"day_range: SHA базы {sym} не совпадает с манифестом")
    B = _load(sym, verify=False)
    B["npz_sha256"] = want
    _B[sym] = (want, B)
    return B


def manifest() -> dict:
    if not MANIFEST.exists():
        build_base()
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    m["manifest_sha256"] = sha_bytes(MANIFEST.read_bytes())
    return m


# ---------------------------------------------------------------- журнал
def _read() -> list[dict]:
    return [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()] if LOG.exists() else []


def _append(rec: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _mine(kind: str) -> list[dict]:
    return [r for r in _read() if r.get("algo") == ALGO and r.get("kind") == kind]


# ---------------------------------------------------------------- зоны, известные до выдачи
def zones_known(issued: datetime, max_age_min: int = 70) -> dict | None:
    """Последний снимок CoinGlass, полученный ДО момента выдачи и не старше 70 мин: ближние края первых зон
    + происхождение (run_id, время получения, SHA записи снимка)."""
    p = DIR / "snapshots.jsonl"
    t_iss = issued.timestamp()
    best, best_line = None, None
    for line in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        try:
            s = json.loads(line)
        except ValueError:
            continue
        cap = s.get("levels_captured")
        if not s.get("levels") or not cap:
            continue
        t = datetime.fromisoformat(cap).timestamp()
        if t_iss - max_age_min * 60 <= t < t_iss:
            best, best_line = s, line
    if best is None:
        return None
    lv, z = best["levels"], []
    zs, zl = (lv.get("zones_short") or [None])[0], (lv.get("zones_long") or [None])[0]
    if zs:
        z.append(("зоны шортов сверху", float(zs["lo"])))
    if zl:
        z.append(("зоны лонгов снизу", float(zl["hi"])))
    return {"levels": z, "run_id": best.get("run_id", best.get("ts")), "levels_captured": best["levels_captured"],
            "snapshot_record_sha256": sha_bytes(best_line.encode("utf-8"))}


# ---------------------------------------------------------------- прогноз
def issue_day(issued: datetime) -> date:
    loc = issued.astimezone(WARSAW)
    return loc.date() if loc.hour >= HOUR_LOCAL else loc.date() - timedelta(days=1)


def forecast(sym: str, issued: datetime | None = None, zones: dict | None = None,
             clock=lambda: datetime.now(timezone.utc), tries: int = 3) -> dict | None:
    """Прогноз со срезом данных T на окно [A; следующее 08:00), A — первая полная минута после T.
    dr-3 (разбор GPT c52f01b): запись допускается, только если фактическое время фиксации (clock после расчёта)
    раньше A; иначе расчёт целиком повторяется с новым T (новые A, P_ref, фаза истории), до `tries` раз, затем —
    пропуск с причиной. Один прогноз на (день, монету, версию)."""
    day = issue_day(issued or clock())
    for r in _mine("forecast"):
        if r["date"] == day.isoformat() and r["sym"] == sym:
            return r
    t = issued or clock()
    for attempt in range(1, tries + 1):
        rec = _compute(sym, t, zones)
        if rec is None:
            return None
        fixed = clock()
        if fixed.timestamp() * 1000 < rec["A_ms"]:
            rec.update(fixed_utc=fixed.astimezone(timezone.utc).isoformat(timespec="milliseconds"), attempt=attempt)
            rec["record_sha256"] = sha_bytes(json.dumps(rec, ensure_ascii=False, sort_keys=True).encode("utf-8"))
            _append(rec)
            return rec
        t = clock()                                             # не успели до A — пересчёт целиком с нового среза
    _append({"algo": ALGO, "kind": "skip", "date": day.isoformat(), "sym": sym,
             "reason": f"не зафиксирован до начала окна за {tries} попытки",
             "at_utc": clock().isoformat(timespec="seconds")})
    return None


def _compute(sym: str, issued: datetime, zones: dict | None) -> dict | None:
    day = issue_day(issued)
    t_ms = int(issued.timestamp() * 1000)
    a = (t_ms // MIN + 1) * MIN                                    # первая полная минута после выдачи
    an, end = anchor_ms(day), anchor_ms(day + timedelta(days=1))
    H = (t_ms // HOUR) * HOUR                                      # часы ATR закрыты до начала часа выдачи
    k_min, h_off = (a - an) // MIN, (H - an) // HOUR
    if a >= end - 60 * MIN:
        return None
    pk = [r for r in klines(sym, "1m", a - 2 * MIN, a - MIN) if int(r[0]) == a - 2 * MIN]
    hrs = klines(sym, "1h", H - 15 * HOUR, H)
    if not pk or len(hrs) != 15 or any(int(hrs[i][0]) != H - (15 - i) * HOUR for i in range(15)) \
            or int(hrs[-1][6]) >= t_ms:
        return None
    p = float(pk[0][4])
    atr = atr14([float(x[2]) for x in hrs], [float(x[3]) for x in hrs], [float(x[4]) for x in hrs])
    man = manifest()                                            # одна пара манифест/база на весь расчёт
    B = _load(sym, want=man["symbols"][sym]["npz_sha256"])
    up, dn = _hist(B, int(k_min), int(h_off))
    up, dn = up[~np.isnan(up)], dn[~np.isnan(dn)]
    lv = []
    for name, price in ((zones or {}).get("levels") or []):
        side = "up" if price > p else "dn"
        dist = abs(price - p) / atr
        lv.append({"name": name, "price": price, "side": side, "dist_atr": round(dist, 3),
                   "chance": round(float(np.mean((up if side == "up" else dn) >= dist)), 3)})
    rec = {"algo": ALGO, "kind": "forecast", "date": day.isoformat(), "sym": sym,
           "issued_utc": issued.astimezone(timezone.utc).isoformat(timespec="milliseconds"),   # срез данных T
           "late": issued.timestamp() * 1000 > an + LATE_MIN * MIN, "A_ms": a, "end_ms": end,
           "window_min": (end - a) // MIN, "phase": {"k_min": int(k_min), "h_off": int(h_off)},
           "P_ref": p, "P_ref_minute_ms": a - 2 * MIN, "atr": atr, "atr_hours_open_ms": [int(x[0]) for x in hrs],
           "corridor": [p - float(np.quantile(dn, Q)) * atr, p + float(np.quantile(up, Q)) * atr], "q_each_side": Q,
           "median_move": [float(np.median(dn)) * atr, float(np.median(up)) * atr], "history_days": int(len(up)),
           "levels": lv, "zones_source": {k: v for k, v in (zones or {}).items() if k != "levels"} or None,
           "base_npz_sha256": B["npz_sha256"], "manifest_sha256": man["manifest_sha256"]}
    return rec


# ---------------------------------------------------------------- проверка (все созревшие)
def _check_one(f: dict) -> dict:
    rows = klines(f["sym"], "1m", f["A_ms"], f["end_ms"])
    n = (f["end_ms"] - f["A_ms"]) // MIN
    if len(rows) != n or any(int(r[0]) != f["A_ms"] + i * MIN for i, r in enumerate(rows)):
        raise ValueError(f"минут {len(rows)} из {n}")
    h, lw = max(float(r[2]) for r in rows), min(float(r[3]) for r in rows)
    lo, hi = f["corridor"]
    return {"algo": ALGO, "kind": "check", "date": f["date"], "sym": f["sym"], "minutes": n, "high": h, "low": lw,
            "inside": h <= hi and lw >= lo, "broke_up": h > hi, "broke_down": lw < lo,
            "levels": [{**x, "touched": (h >= x["price"]) if x["side"] == "up" else (lw <= x["price"])}
                       for x in f["levels"]],
            "checked_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def resolve_all(clock=lambda: datetime.now(timezone.utc)) -> int:
    """Каждый созревший и ещё не оценённый прогноз — проверить; сбой → pending с причиной (повтор при следующем
    запуске). Зрелость — по фактическому времени в момент проверки."""
    done = {(r["date"], r["sym"]) for r in _mine("check")}
    new = 0
    for f in _mine("forecast"):
        if (f["date"], f["sym"]) in done or clock().timestamp() * 1000 < f["end_ms"] + MIN:
            continue
        try:
            _append(_check_one(f))
            new += 1
        except Exception as exc:                                # noqa: BLE001
            _append({"algo": ALGO, "kind": "pending", "date": f["date"], "sym": f["sym"],
                     "reason": f"{type(exc).__name__}: {exc}"[:160],
                     "at_utc": clock().isoformat(timespec="seconds")})
    return new


def stats(sym: str, clock=lambda: datetime.now(timezone.utc)) -> dict:
    fc = [r for r in _mine("forecast") if r["sym"] == sym]
    ch = {r["date"]: r for r in _mine("check") if r["sym"] == sym}
    now_ms = clock().timestamp() * 1000
    mature = [f for f in fc if now_ms >= f["end_ms"] + MIN]
    issued_days = {f["date"] for f in fc}
    missing = 0
    if fc:                                                     # прошедшие дни без прогноза (сегодня ещё не пропуск)
        d, last = date.fromisoformat(min(issued_days)), issue_day(clock()) - timedelta(days=1)
        while d <= last:
            missing += d.isoformat() not in issued_days
            d += timedelta(days=1)
    lv = [x for r in ch.values() for x in r["levels"]]
    return {"issued": len(fc), "resolved": len(ch), "pending": sum(1 for f in mature if f["date"] not in ch),
            "waiting": len(fc) - len(mature), "missing_days": missing, "late": sum(1 for f in fc if f["late"]),
            "inside": sum(r["inside"] for r in ch.values()), "levels": len(lv),
            "promised": (sum(x["chance"] for x in lv) / len(lv)) if lv else None,
            "realized": (sum(x["touched"] for x in lv) / len(lv)) if lv else None}


# ---------------------------------------------------------------- блок карточки
def _p(x: float, sym: str) -> str:
    return f"{x:,.0f}" if sym.startswith("BTC") else f"{x:,.1f}"


def lines(issued: datetime | None = None, zones: dict | None = None,
          clock=lambda: datetime.now(timezone.utc)) -> list[str]:
    try:                                                        # сначала все созревшие проверки, потом срез T
        resolve_all(clock)
    except Exception:                                           # noqa: BLE001
        pass
    man = manifest()
    out, body, head = [], [], None
    for sym in SYMS:
        name = sym[:3]
        t = issued or clock()                                   # свежий срез на каждую монету
        z = (zones_known(t) if zones is None else zones) if sym == "BTCUSDT" else None
        try:
            f = forecast(sym, t, z, clock)
        except Exception as exc:                                # noqa: BLE001
            body.append(f"{name}: не посчитано ({type(exc).__name__})")
            continue
        issued = None
        if f is None:
            body.append(f"{name}: прогноз не выдан (нет закрытых свечей Binance или не успел до начала окна)")
            continue
        lo, hi = f["corridor"]
        dn, up = f["median_move"]
        if head is None:
            a_loc = datetime.fromtimestamp(f["A_ms"] / 1000, timezone.utc).astimezone(WARSAW)
            head = f"с {a_loc:%H:%M} до 08:00" + (" — выдан поздно, окно короче" if f["late"] else "")
        body.append(f"{name} {_p(f['P_ref'], sym)} → коридор {_p(lo, sym)}–{_p(hi, sym)} · обычный ход "
                    f"+{_p(up, sym)} / −{_p(dn, sym)}")
        for x in f["levels"]:
            pct = (x["price"] / f["P_ref"] - 1) * 100
            arrow = "↑" if x["side"] == "up" else "↓"
            nm = {"зоны шортов сверху": "зона шортов", "зоны лонгов снизу": "зона лонгов"}.get(x["name"], x["name"])
            body.append(f"   {arrow} {nm} {_p(x['price'], sym)} ({pct:+.1f}%): шанс {x['chance'] * 100:.0f}%")
        if f["levels"]:
            body.append("   (шанс — по расстоянию в ATR, сила зоны не учитывается)")
    out.append("📏 Прогноз на сутки · размах, не направление" + (f" · {head}" if head else ""))
    out += body
    yday = (issue_day(clock()) - timedelta(days=1)).isoformat()
    ych = []
    for c in (r for r in _mine("check") if r["date"] == yday):
        how = "удержан" if c["inside"] else " и ".join(w for w, b in (("пробит вверх", c["broke_up"]),
                                                                     ("пробит вниз", c["broke_down"])) if b)
        tl = ", ".join(f"{'↑' if x['side'] == 'up' else '↓'} {'задета' if x['touched'] else 'нет'} "
                       f"(шанс был {x['chance'] * 100:.0f}%)" for x in c["levels"])
        ych.append(f"{c['sym'][:3]} коридор {how}" + (f", {tl}" if tl else ""))
    if ych:
        out.append("Вчера: " + " · ".join(ych))
    s = stats("BTCUSDT", clock)
    if s["issued"]:
        tail = (f" · касания обещано {s['promised'] * 100:.0f}% → сбылось {s['realized'] * 100:.0f}% "
                f"({s['levels']} ур.)") if s["levels"] else ""
        out.append(f"Счёт BTC: проверено {s['resolved']} из {s['issued']}"
                   + (f" · коридор держался {s['inside']}/{s['resolved']}" if s["resolved"] else "") + tail
                   + (f" · не проверено {s['pending']}" if s["pending"] else "")
                   + (f" · дней без прогноза {s['missing_days']}" if s["missing_days"] else "")
                   + (" — мало дней" if s["resolved"] < 30 else ""))
    v = {s: man["symbols"][s]["validation"] for s in SYMS}
    b = v["BTCUSDT"]["touch_bins"]
    out.append(f"Метод (для выдачи в 08:01, {v['BTCUSDT']['n_test_days']} утр "
               f"{v['BTCUSDT']['test'][0][:4]}–{v['BTCUSDT']['test'][1][:4]}): коридор удержан "
               + " / ".join(f"{s[:3]} {v[s]['joint_inside'] * 100:.0f}%" for s in SYMS)
               + "; касания " + "/".join(f"{x['promised'] * 100:.0f}" for x in b)
               + " → " + "/".join(f"{x['realized'] * 100:.0f}" for x in b)
               + "%; другая фаза не измерялась")
    return out
