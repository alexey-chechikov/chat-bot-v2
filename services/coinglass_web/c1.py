"""C1 — подтверждающая серия CoinGlass по протоколу GPT docs/COINGLASS_CONFIRMATORY_PROTOCOL_2026-10-18.md
(версия cg-c1-20261018; первый слот 19.10.2026 07:00 Варшавы, последний 18.10.2027, разбор 23.10.2027 12:00).

Реализовано по протоколу:
  - замороженная база: минутки Binance USDⓈ-M BTCUSDT, 730 дат 2024-10-18 … 2026-10-17, то же местное HH:MM; SHA npz и
    списка дат — в манифесте; строится один раз (build_base) и дальше не меняется;
  - прогноз: назначенный запуск 07:00 (первый результат до 07:10; позже — late_capture); max strength с каждой стороны,
    при равенстве — меньший разрыв до ближнего края, затем меньшая цена края; U = lo верхней, L = hi нижней;
    сильнее та сторона, у выбранной зоны которой больше strength (равные — abstain_equal_strength);
    A — первая полная минута после фиксации прогноза; P0 — open Binance в A; P0 вне (L, U) — abstain_at_anchor;
    ATR14 — простое среднее 14 TR по 15 закрытым UTC 1h (closeTime < времени фиксации), одинаково live и history;
    a = (U−P0)/ATR, b = (P0−L)/ATR; q по 730 историческим окнам той же фазы (24 корзины по 60 мин от A_j);
    q_low = side_first/730, q_high = (side_first + both + unknown)/730; запись прогноза неизменяемая, с SHA;
  - исход: ровно 1440 минут от A, 24 корзины по 60 мин от A; Y = [1,1] сильная сторона первой однозначно, [0,0] другая
    или ни одна, [0,1] both или неполное покрытие; события исхода — отдельный файл, ревизии добавлением;
  - ежедневно — только counts, качество и описательный эффект; никаких выводов о подтверждении до 23.10.2027.
Файлы: state/coinglass/c1/ — base.npz, base_manifest.json, fixes.jsonl (сторона и границы до цены A), forecasts.jsonl,
outcomes.jsonl, registry.jsonl (один статус на слот; пропущенные дописывает close_missing).
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from services.coinglass_web.collector import DIR

PROTOCOL = "cg-c1-20261018"
IMPL = "mac-c1-impl-2"           # impl-1 (слот 19.10) терял P0: один запрос через 2 с, свеча REST ещё не готова
P0_WAIT_MS = 45_000
WARSAW = ZoneInfo("Europe/Warsaw")
C1 = DIR / "c1"
FIRST_SLOT, LAST_SLOT = date(2026, 10, 19), date(2027, 10, 18)
BASE_DATES = [date(2024, 10, 18) + timedelta(days=i) for i in range(730)]        # … 2026-10-17
ROOT = Path(__file__).resolve().parents[2]
MIN = 60_000
HOUR = 3_600_000


def _get(url: str):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bot7"}),
                                             timeout=20).read())


def klines(interval: str, start_ms: int, end_ms: int) -> list:
    """Binance USDⓈ-M BTCUSDT свечи [start, end) по openTime."""
    out, t, step = [], start_ms, {"1m": MIN, "1h": HOUR}[interval]
    while t < end_ms:
        rows = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval={interval}&limit=1500"
                    f"&startTime={t}&endTime={end_ms - 1}")
        if not rows:
            break
        out += [r for r in rows if int(r[0]) < end_ms]
        t = int(rows[-1][0]) + step
    return out


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canon(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------- база (один раз)
def build_base() -> dict:
    """Минутки 2024-10-17 00:00 … 2026-10-18 12:00 UTC: frozen UM 1m + докачка REST; полная сетка обязательна."""
    import pandas as pd
    C1.mkdir(parents=True, exist_ok=True)
    npz, man = C1 / "base.npz", C1 / "base_manifest.json"
    if npz.exists() and man.exists():
        return json.loads(man.read_text(encoding="utf-8"))
    a = int(datetime(2024, 10, 17, tzinfo=timezone.utc).timestamp() * 1000)
    b = int(datetime(2026, 10, 18, 12, tzinfo=timezone.utc).timestamp() * 1000)
    src = ROOT / "backtests" / "frozen" / "BTCUSDT_UM_1m.csv"
    d = pd.read_csv(src, usecols=["ts", "open", "high", "low", "close"])
    d = d[(d.ts >= a) & (d.ts < b)]
    last = int(d.ts.max())
    extra = klines("1m", last + MIN, b)
    if extra:
        d = pd.concat([d, pd.DataFrame([[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in extra],
                                       columns=d.columns)])
    d = d.drop_duplicates("ts").sort_values("ts")
    ts = d.ts.to_numpy(dtype=np.int64)
    gaps = int((ts[-1] - ts[0]) // MIN + 1 - len(ts))
    np.savez(npz, ts=ts, open=d.open.to_numpy(), high=d.high.to_numpy(), low=d.low.to_numpy(),
             close=d.close.to_numpy())
    manifest = {"protocol": PROTOCOL, "impl": IMPL, "symbol": "BTCUSDT", "market": "Binance USD-M perpetual",
                "first_ts_utc": datetime.fromtimestamp(ts[0] / 1000, timezone.utc).isoformat(),
                "last_ts_utc": datetime.fromtimestamp(ts[-1] / 1000, timezone.utc).isoformat(),
                "rows": int(len(ts)), "missing_minutes": gaps, "npz_sha256": sha_bytes(npz.read_bytes()),
                "frozen_source": src.name, "frozen_source_sha256": sha_bytes(src.read_bytes()),
                "rest_minutes_added": len(extra), "dates": [x.isoformat() for x in BASE_DATES],
                "dates_sha256": sha_bytes(canon([x.isoformat() for x in BASE_DATES])), "tz": "Europe/Warsaw",
                "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    man.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


_BASE = None


def base() -> dict:
    """Замороженная база; SHA файла сверяется с манифестом при каждой загрузке — подмена/порча = отказ."""
    global _BASE
    if _BASE is None:
        man = json.loads((C1 / "base_manifest.json").read_text(encoding="utf-8"))
        if sha_bytes((C1 / "base.npz").read_bytes()) != man["npz_sha256"]:
            raise RuntimeError("C1: SHA base.npz не совпадает с манифестом")
        z = np.load(C1 / "base.npz")
        _BASE = {k: z[k] for k in z.files}
        _BASE["pos"] = {int(t): i for i, t in enumerate(_BASE["ts"])}
    return _BASE


# ---------------------------------------------------------------- общие расчёты
def atr14(h: list, lo: list, c: list) -> float:
    """Простое среднее 14 TR по 15 свечам (первая — только для previous close)."""
    tr = [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, 15)]
    return sum(tr) / 14


def bucket_outcome(highs, lows, upper: float, lower: float) -> str:
    """24 корзины по 60 мин от A: первая корзина, где задет барьер; обе в одной — both."""
    for k in range(24):
        hh, ll = max(highs[k * 60:(k + 1) * 60]), min(lows[k * 60:(k + 1) * 60])
        if hh >= upper and ll <= lower:
            return "both"
        if hh >= upper:
            return "upper"
        if ll <= lower:
            return "lower"
    return "none"


def select_zones(levels: dict) -> dict:
    def pick(zones, edge, price):
        valid = [z for z in zones if z.get("strength") is not None and z.get("lo") and z.get("hi")]
        if not valid:
            return None
        return sorted(valid, key=lambda z: (-z["strength"], abs(z[edge] - price), z[edge]))[0]
    p = levels["price"]
    up, dn = pick(levels.get("zones_short") or [], "lo", p), pick(levels.get("zones_long") or [], "hi", p)
    stronger = None
    if up and dn:
        stronger = "upper" if up["strength"] > dn["strength"] else "lower" if dn["strength"] > up["strength"] else None
    return {"upper_zone": up, "lower_zone": dn, "U": up["lo"] if up else None, "L": dn["hi"] if dn else None,
            "stronger": stronger, "candidates_short": levels.get("zones_short"), "candidates_long": levels.get("zones_long")}


def history_point(a_utc_ms: int) -> tuple[float, float, list, list] | None:
    """P_j, ATR_j (15 закрытых UTC-часов до A_j) и минутные high/low 1440 минут от A_j; None — неполное покрытие."""
    B = base()
    pos = B["pos"]
    i = pos.get(a_utc_ms)
    if i is None or i + 1440 > len(B["ts"]) or B["ts"][i + 1439] != a_utc_ms + 1439 * MIN:
        return None
    hour0 = (a_utc_ms // HOUR) * HOUR                               # начало часа, где лежит A_j
    hs, ls, cs = [], [], []
    for k in range(15, 0, -1):                                      # 15 часов, закрытых не позже hour0 ≤ A_j
        s = hour0 - k * HOUR
        j = pos.get(s)
        if j is None or B["ts"][j + 59] != s + 59 * MIN:
            return None
        hs.append(float(B["high"][j:j + 60].max()))
        ls.append(float(B["low"][j:j + 60].min()))
        cs.append(float(B["close"][j + 59]))
    return (float(B["open"][i]), atr14(hs, ls, cs), B["high"][i:i + 1440].tolist(), B["low"][i:i + 1440].tolist())


CODE = {"side_first": "S", "other_first": "O", "none": "N", "both": "B", "unknown": "U"}


def q_vector(a: float, b: float, hhmm: tuple[int, int], side: str) -> dict:
    """q по 730 датам; per_date — исход каждой даты (S/O/N/B/U по порядку BASE_DATES): нужен бутстрапу с общими
    весами исторических дней, сохраняется в прогнозе и не пересчитывается."""
    counts = {"side_first": 0, "other_first": 0, "none": 0, "both": 0, "unknown": 0}
    per = []
    for d in BASE_DATES:
        loc = datetime(d.year, d.month, d.day, hhmm[0], hhmm[1], tzinfo=WARSAW)
        hp = history_point(int(loc.astimezone(timezone.utc).timestamp() * 1000))
        if hp is None:
            k = "unknown"
        else:
            p, atr, hi, lo = hp
            o = bucket_outcome(hi, lo, p + a * atr, p - b * atr)
            k = o if o in ("both", "none") else ("side_first" if o == side else "other_first")
        counts[k] += 1
        per.append(CODE[k])
    n = len(BASE_DATES)
    return {**counts, "n": n, "complete": n - counts["unknown"], "q_low": counts["side_first"] / n,
            "q_high": (counts["side_first"] + counts["both"] + counts["unknown"]) / n, "per_date": "".join(per)}


# ---------------------------------------------------------------- прогноз (в момент снимка)
def _append(name: str, rec: dict) -> None:
    C1.mkdir(parents=True, exist_ok=True)
    with open(C1 / name, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _read(name: str) -> list[dict]:
    p = C1 / name
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def slot_of(run_started: datetime) -> date | None:
    loc = run_started.astimezone(WARSAW)
    if loc.hour == 7 and loc.minute < 10 and FIRST_SLOT <= loc.date() <= LAST_SLOT:
        return loc.date()
    return None


def _local(slot: date, hh: int, mm: int) -> datetime:
    return datetime(slot.year, slot.month, slot.day, hh, mm, tzinfo=WARSAW)


INSTRUMENT = {"exchange": "Binance", "symbol": "BTCUSDT", "market": "USD-M perpetual",
              "levels_source": "https://www.coinglass.com/ru/liquidation-levels",
              "price_source": "https://fapi.binance.com/fapi/v1/klines"}


def make_forecast(run_id: str, run_started: datetime, levels: dict | None, captured: datetime | None,
                  settings_observed: dict | None, now_fn=lambda: datetime.now(timezone.utc), sleep=None) -> dict | None:
    """Вызывается сборщиком сразу после разбора страницы уровней. Не назначенный запуск — None.

    Порядок: (1) слот уже выбран → ничего; (2) нет уровней → missing_snapshot, получены ≥07:10 → late_capture;
    (3) границы и сторона фиксируются и пишутся в fixes.jsonl с SHA ДО открытия минуты A; зафиксировано позже 07:10:00 —
    late_forecast; A позже 07:11 — late_anchor; (4) P0 = open A, ATR по 15 подряд закрытым часам (closeTime < фиксации),
    q по замороженной базе; запись прогноза — одна, неизменяемая, со ссылкой на SHA фиксации."""
    slot = slot_of(run_started)
    if slot is None:
        return None
    if any(r.get("slot") == slot.isoformat() for r in _read("registry.jsonl")):
        return None                                                 # первый результат слота уже выбран
    reg = {"slot": slot.isoformat(), "run_id": run_id, "run_started": run_started.isoformat(), "protocol": PROTOCOL,
           "impl": IMPL}
    if levels is None or captured is None:
        _append("registry.jsonl", {**reg, "status": "missing_snapshot", "reason": "уровни не получены/не разобраны"})
        return None
    if captured.astimezone(WARSAW) >= _local(slot, 7, 10):
        _append("registry.jsonl", {**reg, "status": "late_capture", "captured": captured.isoformat()})
        return None
    man = json.loads((C1 / "base_manifest.json").read_text(encoding="utf-8")) if (C1 / "base_manifest.json").exists() \
        else None
    sel = select_zones(levels)
    fixed = now_fn()
    a_ms = (int(fixed.timestamp() * 1000) // MIN + 1) * MIN
    a_dt = datetime.fromtimestamp(a_ms / 1000, timezone.utc)
    fix = {**reg, "forecast_id": f"c1-{slot.isoformat()}", "horizon": "24h", "levels_captured": captured.isoformat(),
           "forecast_created_at": fixed.isoformat(), "A_utc": a_dt.isoformat(),
           "A_local": a_dt.astimezone(WARSAW).isoformat(), "instrument": INSTRUMENT,
           "settings_observed": settings_observed, "interface_price": levels["price"], **{k: sel[k] for k in sel}}
    fix["fix_sha256"] = sha_bytes(canon(fix))
    _append("fixes.jsonl", fix)                                     # сторона и границы — до цены A
    rec = dict(fix)
    status = "admitted"
    if man is None:
        status = "not_ready_no_base"
    elif sel["U"] is None or sel["L"] is None:
        status = "abstain_no_zone"
    elif sel["stronger"] is None:
        status = "abstain_equal_strength"
    if fixed.astimezone(WARSAW) > _local(slot, 7, 10):
        status = "late_forecast"
    elif a_dt.astimezone(WARSAW) > _local(slot, 7, 11):
        status = "late_anchor"
    if status == "admitted":
        import time
        sleep = sleep or time.sleep
        while now_fn().timestamp() * 1000 < a_ms + 2000:            # ждём открытия минуты A
            sleep(0.5)
        # REST Binance отдаёт свечу текущей минуты через 1.4–4.3 с после её начала (замер 19.10; один запрос через 2 с
        # потерял слот 19.10). Open минуты не меняется после появления — опрос до A+45 с будущего не использует.
        p0, tries = None, 0
        while True:
            tries += 1
            k = klines("1m", a_ms, a_ms + MIN)
            if k and int(k[0][0]) == a_ms:
                p0 = float(k[0][1])
                break
            if now_fn().timestamp() * 1000 >= a_ms + P0_WAIT_MS:
                break
            sleep(1.0)
        rec.update(p0_fetch_tries=tries, p0_fetched_at=now_fn().isoformat())
        hrs = [r for r in klines("1h", a_ms - 20 * HOUR, a_ms) if int(r[6]) < int(fixed.timestamp() * 1000)][-15:]
        consecutive = len(hrs) == 15 and all(int(hrs[i][0]) - int(hrs[i - 1][0]) == HOUR for i in range(1, 15))
        if p0 is None or not consecutive:
            status = "not_ready_price"
        else:
            atr = atr14([float(r[2]) for r in hrs], [float(r[3]) for r in hrs], [float(r[4]) for r in hrs])
            rec.update(P0=p0, atr_1h=atr, atr_hours_open_utc=[int(r[0]) for r in hrs],
                       atr_hours_close_utc=[int(r[6]) for r in hrs])
            if not (sel["L"] < p0 < sel["U"]):
                status = "abstain_at_anchor"
            else:
                a, b = (sel["U"] - p0) / atr, (p0 - sel["L"]) / atr
                loc = a_dt.astimezone(WARSAW)
                q = q_vector(a, b, (loc.hour, loc.minute), sel["stronger"])
                rec.update(a_atr=a, b_atr=b, phase_local=f"{loc:%H:%M}", q=q,
                           base_npz_sha256=man["npz_sha256"], base_dates_sha256=man["dates_sha256"])
                if q["complete"] < 700:
                    status = "not_ready_base"
    rec["status"] = status
    rec["record_sha256"] = sha_bytes(canon(rec))
    _append("forecasts.jsonl", rec)
    _append("registry.jsonl", {**reg, "status": status, "forecast_id": rec["forecast_id"]})
    return rec


def close_missing(now: datetime | None = None) -> int:
    """Слоты, у которых к 07:10 нет ни одной записи (мак спал, сборщик упал до прогноза) → missing_snapshot.
    Реестр остаётся календарным: 365 слотов, ни один не пропадает молча."""
    now = now or datetime.now(timezone.utc)
    have = {r["slot"] for r in _read("registry.jsonl")} | {f["slot"] for f in _read("fixes.jsonl")}
    n, d = 0, FIRST_SLOT
    while d <= LAST_SLOT and now.astimezone(WARSAW) >= _local(d, 7, 10):
        if d.isoformat() not in have:
            _append("registry.jsonl", {"slot": d.isoformat(), "run_id": None, "protocol": PROTOCOL, "impl": IMPL,
                                       "status": "missing_snapshot", "reason": "нет запуска до 07:10",
                                       "recorded_at": now.isoformat(timespec="seconds")})
            n += 1
        d += timedelta(days=1)
    return n


# ---------------------------------------------------------------- исход (через сутки)
FREEZE = datetime(2027, 10, 22, 12, 0, tzinfo=WARSAW)            # окончательная фиксация данных


def minute_outcome(highs, lows, upper: float, lower: float) -> str:
    """Вторичный описательный исход по минутам: первая минута касания; обе в одной — both."""
    for hh, ll in zip(highs, lows):
        if hh >= upper and ll <= lower:
            return "both"
        if hh >= upper:
            return "upper"
        if ll <= lower:
            return "lower"
    return "none"


def evaluate(now: datetime | None = None) -> int:
    """Исходы созревших прогнозов (≥ A+24ч+2мин). Неполное покрытие → unknown [0,1]; восстановленное позже — новая
    ревизия добавлением. После 22.10.2027 12:00 ревизий нет."""
    now = now or datetime.now(timezone.utc)
    close_missing(now)
    if now > FREEZE:
        return 0
    done = {(o["forecast_id"], o.get("complete")) for o in _read("outcomes.jsonl")}
    new = 0
    for f in _read("forecasts.jsonl"):
        if f.get("status") != "admitted" or (f["forecast_id"], True) in done:
            continue
        a_ms = int(datetime.fromisoformat(f["A_utc"]).timestamp() * 1000)
        if now.timestamp() * 1000 < a_ms + 1440 * MIN + 120_000:
            continue
        rows = klines("1m", a_ms, a_ms + 1440 * MIN)
        complete = len(rows) == 1440 and all(int(r[0]) == a_ms + i * MIN for i, r in enumerate(rows))
        if not complete and (f["forecast_id"], False) in done:
            continue
        rec = {"forecast_id": f["forecast_id"], "protocol": PROTOCOL, "impl": IMPL, "horizon": "24h",
               "evaluated_at": now.isoformat(timespec="seconds"), "complete": complete, "minutes": len(rows)}
        if complete:
            hi, lo = [float(r[2]) for r in rows], [float(r[3]) for r in rows]
            o = bucket_outcome(hi, lo, f["U"], f["L"])
            y = (0.0, 1.0) if o == "both" else ((1.0, 1.0) if o == f["stronger"] else (0.0, 0.0))
            rec.update(outcome=o, outcome_1m=minute_outcome(hi, lo, f["U"], f["L"]), Y_low=y[0], Y_high=y[1])
        else:
            rec.update(outcome="unknown", Y_low=0.0, Y_high=1.0)
        rec["record_sha256"] = sha_bytes(canon(rec))
        _append("outcomes.jsonl", rec)
        new += 1
    return new


def summary() -> dict:
    """Ежедневно разрешено: counts, качество, описательный эффект (не подтверждение)."""
    reg = _read("registry.jsonl")
    fc = {f["forecast_id"]: f for f in _read("forecasts.jsonl") if f.get("status") == "admitted"}
    last = {}
    for o in _read("outcomes.jsonl"):
        last[o["forecast_id"]] = o
    ys = [(last[k]["Y_low"], last[k]["Y_high"], fc[k]["q"]["q_low"], fc[k]["q"]["q_high"]) for k in fc if k in last]
    st, oc = {}, {}
    for r in reg:
        st[r["status"]] = st.get(r["status"], 0) + 1
    for k in fc:
        o = last[k]["outcome"] if k in last else "pending"
        oc[o] = oc.get(o, 0) + 1
    return {"protocol": PROTOCOL, "slots": len({r["slot"] for r in reg}), "planned": 365, "status": st,
            "admitted": len(fc), "outcomes": oc, "resolved": len(ys),
            "D_low_desc": (sum(y[0] - y[3] for y in ys) / len(ys)) if ys else None,
            "D_high_desc": (sum(y[1] - y[2] for y in ys) / len(ys)) if ys else None}


# ---------------------------------------------------------------- единственный разбор 23.10.2027 (код зафиксирован заранее)
SEED, REPS, BLOCK, ALPHA, MARGIN = 20261018, 10_000, 7, 0.025, 0.05
N_SLOTS = (LAST_SLOT - FIRST_SLOT).days + 1                          # 365


def _block_indices(rng, n: int) -> np.ndarray:
    """Circular moving-block: равновероятные начала, блоки по 7, wrap-around, конкатенация, обрезка до n."""
    starts = rng.integers(0, n, size=-(-n // BLOCK))
    return ((starts[:, None] + np.arange(BLOCK)[None, :]) % n).ravel()[:n]


def bootstrap(per_date: list[str], y_low: list[float], slot_idx: list[int], n_slots: int = N_SLOTS,
              reps: int = REPS, seed: int = SEED) -> dict:
    """В каждом повторе сначала история (730 дат), затем prospective-слоты; общие веса истории пересчитывают q_high
    всех прогнозов; D_b = mean(Y_low − q_high_b) по допущенным прогнозам выбранных слотов с кратностью;
    L = quantile(D_b, 0.025, linear). Повтор без допущенных прогнозов → расчёт неопределён → подтверждения нет."""
    n_h = len(BASE_DATES)
    hmask = np.array([[ch in "SBU" for ch in s] for s in per_date], dtype=float).reshape(len(per_date), n_h)
    y, idx = np.asarray(y_low, dtype=float), np.asarray(slot_idx, dtype=int)
    rng = np.random.Generator(np.random.PCG64(seed))
    d = np.empty(reps)
    for r in range(reps):
        w = np.bincount(_block_indices(rng, n_h), minlength=n_h)
        k = np.bincount(_block_indices(rng, n_slots), minlength=n_slots)[idx]
        d[r] = (k * (y - hmask @ w / n_h)).sum() / k.sum() if k.sum() else np.nan
    defined = bool(len(y)) and bool(np.isfinite(d).all())
    return {"D_hat": float((y - hmask.sum(1) / n_h).mean()) if len(y) else None, "reps": reps, "seed": seed,
            "block_days": BLOCK, "L": float(np.quantile(d, ALPHA, method="linear")) if defined else None,
            "defined": defined, "numpy": np.__version__, "D_b": d}


def final_test(now: datetime | None = None) -> dict:
    """Единственный разбор (23.10.2027 12:00 Варшавы), только после фиксации данных 22.10.2027 12:00.
    Подтверждение — только при N допущенных ≥ 300, полном покрытии ≥ 95% и строгом L > 0.05."""
    now = now or datetime.now(timezone.utc)
    if now < FREEZE:
        return {"error": "до 22.10.2027 12:00 Варшавы разбор не проводится"}
    fc = sorted((f for f in _read("forecasts.jsonl") if f.get("status") == "admitted"), key=lambda f: f["slot"])
    last = {}
    for o in _read("outcomes.jsonl"):
        last[o["forecast_id"]] = o
    y_low = [last[f["forecast_id"]]["Y_low"] if f["forecast_id"] in last else 0.0 for f in fc]
    y_high = [last[f["forecast_id"]]["Y_high"] if f["forecast_id"] in last else 1.0 for f in fc]
    complete = sum(1 for f in fc if last.get(f["forecast_id"], {}).get("complete"))
    idx = [(date.fromisoformat(f["slot"]) - FIRST_SLOT).days for f in fc]
    bs = bootstrap([f["q"]["per_date"] for f in fc], y_low, idx)
    np.save(C1 / "bootstrap_D_b.npy", bs.pop("D_b"))
    n = len(fc)
    quality = n >= 300 and complete >= 0.95 * n
    return {"protocol": PROTOCOL, "impl": IMPL, "N_admitted": n, "complete": complete, "quality_ok": quality,
            **bs, "D_upper_desc": (sum(y_high) - sum(f["q"]["q_low"] for f in fc)) / n if n else None,
            "confirmed": bool(quality and bs["defined"] and bs["L"] > MARGIN),
            "bootstrap_file_sha256": sha_bytes((C1 / "bootstrap_D_b.npy").read_bytes())}
