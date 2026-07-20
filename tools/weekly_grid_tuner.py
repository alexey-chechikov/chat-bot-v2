"""Weekly Grid Tuner (C-прототип, 2026-07-18) — недельный аудит DYN-сеток.

По каждому боту за неделю: net, макс-транзит-мешок, симметрия, время-на-
неправой-стороне, EXIT-FAST (истинные/ложные), % времени не-Active —
всё против baseline его собственной истории. Эмитит ПРЕДЛОЖЕНИЯ правок
(текст, оператор одобряет руками) — ничего не мутирует, read-only.

Правило проекта: сигнал без живого числа в карту решений не входит —
этот скрипт и есть источник живых чисел для карты B.

Запуск:
  .venv/bin/python3 tools/weekly_grid_tuner.py [--week-end 2026-07-18]
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "ginarea_live" / "snapshots.csv"
APP_LOG = ROOT / "logs" / "launchd_app_runner.err"

DYN = {
    "4499423673": "BTC-DYN", "6233908669": "ETH-DYN", "6116013349": "SOL-DYN",
    "4643987212": "XRP-DYN", "4922851123": "LTC-DYN", "5085651183": "BCH-DYN",
    "5288594904": "LINK-DYN",
}
# имя в тексте EXIT-FAST пинга → alias
PING_NAME_MAP = {
    "btc DINAMIK": "BTC-DYN", "TEST ETH": "ETH-DYN", "SOL  DYNAMIK": "SOL-DYN",
    "XRP  XRP D Auto": "XRP-DYN", "LTC": "LTC-DYN", "BCH": "BCH-DYN",
    "Link": "LINK-DYN",
}
BAG_NOISE_USD = 5.0        # |мешок| ниже — шум, не «неправая сторона»
EF_TRUE_DELTA_USD = 50.0   # мешок ухудшился на столько за 6ч после пинга = истинный
EF_WINDOW_H = 6.0
LOG_TZ_OFFSET_H = 2        # лог пишется в локальном времени (UTC+2)


def load_snapshots(start: datetime, end: datetime) -> pd.DataFrame:
    cols = ["ts_utc", "bot_id", "status", "position", "profit",
            "current_profit", "in_filled_count", "out_filled_count"]
    df = pd.read_csv(SNAPSHOTS, usecols=cols)
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], format="ISO8601", utc=True)
    df = df[(df["ts_utc"] >= start) & (df["ts_utc"] < end)].copy()
    df["bot_key"] = df["bot_id"].astype("Int64").astype(str)
    df = df[df["bot_key"].isin(DYN)]
    for c in ["status", "position", "profit", "current_profit",
              "in_filled_count", "out_filled_count"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["bag"] = df["current_profit"] - df["profit"]
    return df.sort_values("ts_utc")


def exit_fast_pings(start: datetime, end: datetime) -> list[tuple[datetime, str]]:
    """(ts_utc, alias) EXIT-FAST пингов из лога app_runner."""
    out: list[tuple[datetime, str]] = []
    rx = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*alt_guard\.ping .*EXIT-FAST ([^:]+):")
    try:
        with APP_LOG.open(encoding="utf-8", errors="replace") as f:
            for ln in f:
                if "EXIT-FAST" not in ln or "alt_guard.ping" not in ln:
                    continue
                m = rx.match(ln)
                if not m:
                    continue
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc) - timedelta(hours=LOG_TZ_OFFSET_H)
                if not (start <= ts < end):
                    continue
                name = m.group(2).strip()
                alias = next((a for n, a in PING_NAME_MAP.items() if n in name), None)
                if alias:
                    out.append((ts, alias))
    except OSError:
        pass
    return out


def classify_ping(g: pd.DataFrame, ts: datetime) -> str:
    """истинный = мешок ухудшился ещё на EF_TRUE_DELTA за 6ч (срез спасал);
    ложный = фейк-слом (мешок не ушёл глубже; срез = дешёвая страховка)."""
    at = g[g["ts_utc"] <= ts]
    if at.empty:
        return "н/д"
    bag0 = at["bag"].iloc[-1]
    fwd = g[(g["ts_utc"] > ts) & (g["ts_utc"] <= ts + timedelta(hours=EF_WINDOW_H))]
    if fwd.empty:
        return "н/д"
    return "истинный" if fwd["bag"].min() < bag0 - EF_TRUE_DELTA_USD else "ложный"


PARAMS_CSV = ROOT / "ginarea_live" / "params.csv"
GEOM_RATIO_WARN = 1.3   # размах/ширина выше — окно узко для волы символа


def border_geometry(start: datetime, end: datetime) -> dict[str, dict]:
    """{alias: {width_pct, so, day_range_pct, ratio}} из истории границ.

    Границы border.from/to ездят за ценой → середина = прокси цены, ширина =
    рабочий коридор. ratio = дневной размах цены / ширина коридора: >1.3 =
    окно узко, грид постоянно догоняет тренд и усредняется против (ETH-урок
    2026-07-20: ratio 2.0, транзит −644$). Правило: so ≈ ½ дневного размаха."""
    import json as _json
    out: dict[str, dict] = {}
    try:
        df = pd.read_csv(PARAMS_CSV, usecols=["ts_utc", "bot_id",
                                              "raw_params_json"])
    except Exception:
        return out
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], format="ISO8601", utc=True,
                                  errors="coerce")
    df = df.dropna(subset=["ts_utc"])
    df = df[(df["ts_utc"] >= start) & (df["ts_utc"] < end)]
    df["bot_key"] = df["bot_id"].astype("Int64").astype(str)
    df = df[df["bot_key"].isin(DYN)].sort_values("ts_utc")
    for bid, g in df.groupby("bot_key"):
        rec = []
        for _, r in g.iterrows():
            try:
                p = _json.loads(r["raw_params_json"])
            except Exception:
                continue
            b = p.get("border") or {}
            f, t = b.get("from"), b.get("to")
            if f and t and t > f:
                rec.append({"ts": r["ts_utc"], "mid": (f + t) / 2,
                            "width": t - f, "so": p.get("so")})
        if not rec:
            continue
        h = pd.DataFrame(rec).set_index("ts").sort_index()
        width_pct = ((h["width"]) / h["mid"] * 100).median()
        daily = h["mid"].resample("1D")
        day_range = ((daily.max() - daily.min()) / daily.mean() * 100).dropna()
        dr = day_range.median()
        out[DYN[bid]] = {
            "width_pct": round(width_pct, 2),
            "so": h["so"].iloc[-1],
            "day_range_pct": round(dr, 2),
            "ratio": round(dr / width_pct, 1) if width_pct else None,
        }
    return out


def bot_metrics(g: pd.DataFrame, days: float) -> dict:
    if g.empty:
        return {}
    net = g["profit"].iloc[-1] - g["profit"].iloc[0]
    wrong = g[g["bag"] < -BAG_NOISE_USD]
    daily_net = (g.set_index("ts_utc")["profit"].resample("1D").last().diff().dropna())
    up_days = daily_net[daily_net > 0]
    down_days = daily_net[daily_net < 0]
    return {
        "net": round(net, 1),
        "net_per_day": round(net / days, 1),
        "worst_bag": round(g["bag"].min(), 1),
        "best_bag": round(g["bag"].max(), 1),
        "wrong_side_pct": round(len(wrong) / len(g) * 100, 1),
        "wrong_side_mean": round(wrong["bag"].mean(), 1) if len(wrong) else 0.0,
        "out_fills_per_day": round(
            (g["out_filled_count"].iloc[-1] - g["out_filled_count"].iloc[0]) / days, 1),
        "not_active_pct": round((g["status"] != 2).mean() * 100, 1),
        "up_day_avg": round(up_days.mean(), 1) if len(up_days) else 0.0,
        "down_day_avg": round(down_days.mean(), 1) if len(down_days) else 0.0,
    }


def proposals(alias: str, w: dict, b: dict, ef: list[str],
              geom: dict | None = None) -> list[str]:
    out: list[str] = []
    if not w:
        return ["нет данных за неделю"]
    if geom and geom.get("ratio") and geom["ratio"] > GEOM_RATIO_WARN:
        so = geom.get("so")
        sugg = f" → so≈{geom['day_range_pct'] / 2:.2f} (½ размаха)" if so else ""
        out.append(f"границы узки: размах/ширина {geom['ratio']} "
                   f"(размах {geom['day_range_pct']}%/д vs коридор "
                   f"{geom['width_pct']}%), so={so}{sugg}")
    if b:
        if b.get("worst_bag", 0) < -BAG_NOISE_USD and \
                w["worst_bag"] < 2.0 * b["worst_bag"]:
            out.append(f"мешок ×{w['worst_bag'] / b['worst_bag']:.1f} к baseline "
                       f"({w['worst_bag']} vs {b['worst_bag']}) → поджать max_size "
                       "или equity-стоп")
        if b.get("net_per_day", 0) > 0 and w["net_per_day"] < 0.5 * b["net_per_day"]:
            out.append(f"харвест упал: {w['net_per_day']}$/д vs baseline "
                       f"{b['net_per_day']}$/д → сверить gs/target с текущим ATR")
        if b.get("wrong_side_pct", 0) > 0 and \
                w["wrong_side_pct"] > 1.5 * b["wrong_side_pct"]:
            out.append(f"время-на-неправой {w['wrong_side_pct']}% vs baseline "
                       f"{b['wrong_side_pct']}% → нога систематически против; "
                       "кандидат на H5-cap")
    if w["not_active_pct"] > 5:
        out.append(f"бот не-Active {w['not_active_pct']}% недели "
                   f"(мешок в моменте {w['worst_bag']}$) → выяснить причину простоя")
    n_true = ef.count("истинный")
    n_false = ef.count("ложный")
    if n_false >= 3 and n_true == 0:
        out.append(f"EXIT-FAST {n_false} ложных / 0 истинных → поднять подтверждение "
                   "(бары/объём) для символа")
    if not ef and w["worst_bag"] < -150:
        out.append(f"EXIT-FAST молчал при мешке {w['worst_bag']}$ → "
                   "медленный для символа, кандидат на H5-cap")
    if abs(w.get("down_day_avg", 0)) > 3 * max(w.get("up_day_avg", 0), 1):
        out.append(f"асимметрия дней: средний минус-день {w['down_day_avg']}$ vs "
                   f"плюс-день +{w['up_day_avg']}$ → проверить soft-stop")
    return out or ["в норме — правок не предлагаю"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week-end", default=None,
                    help="конец недели (YYYY-MM-DD, UTC); дефолт — сегодня 00:00")
    args = ap.parse_args()
    if args.week_end:
        week_end = datetime.fromisoformat(args.week_end).replace(tzinfo=timezone.utc)
    else:
        week_end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                                      microsecond=0)
    week_start = week_end - timedelta(days=7)
    base_start = datetime(2026, 6, 29, tzinfo=timezone.utc)  # старт DYN-пачки
    if base_start >= week_start:
        base_start = week_start - timedelta(days=14)

    snaps = load_snapshots(min(base_start, week_start), week_end)
    pings = exit_fast_pings(week_start, week_end)
    geom = border_geometry(week_start, week_end)
    base_days = (week_start - base_start).total_seconds() / 86400
    week_days = 7.0

    print(f"WEEKLY GRID TUNER — неделя {week_start:%d.%m} → {week_end:%d.%m} UTC "
          f"(baseline {base_start:%d.%m} → {week_start:%d.%m}, {base_days:.0f}д)")
    print("правило классификации EXIT-FAST: «истинный» = мешок ушёл ещё на "
          f"{EF_TRUE_DELTA_USD:.0f}$ глубже за {EF_WINDOW_H:.0f}ч после пинга\n")

    header = (f"{'бот':9s} {'net':>7s} {'$/д':>6s} {'яма':>7s} {'пик':>6s} "
              f"{'непр.%':>6s} {'ср.минус':>8s} {'out/д':>5s} {'стоп%':>5s} {'EF':>12s}")
    print(header)
    print("-" * len(header))
    all_props: dict[str, list[str]] = {}
    for bid, alias in DYN.items():
        g = snaps[snaps["bot_key"] == bid]
        gw = g[g["ts_utc"] >= week_start]
        gb = g[g["ts_utc"] < week_start]
        w = bot_metrics(gw, week_days)
        b = bot_metrics(gb, base_days)
        ef_cls = [classify_ping(g, ts) for ts, a in pings if a == alias]
        ef_str = (f"{ef_cls.count('истинный')}✓/{ef_cls.count('ложный')}✗"
                  if ef_cls else "—")
        if w:
            print(f"{alias:9s} {w['net']:>7.1f} {w['net_per_day']:>6.1f} "
                  f"{w['worst_bag']:>7.1f} {w['best_bag']:>6.1f} "
                  f"{w['wrong_side_pct']:>6.1f} {w['wrong_side_mean']:>8.1f} "
                  f"{w['out_fills_per_day']:>5.1f} {w['not_active_pct']:>5.1f} "
                  f"{ef_str:>12s}")
        all_props[alias] = proposals(alias, w, b, ef_cls, geom.get(alias))

    if geom:
        print("\nГЕОМЕТРИЯ ГРАНИЦ (размах/ширина >1.3 = окно узко для символа):")
        gh = f"{'бот':9s} {'коридор%':>8s} {'so':>5s} {'размах/д%':>9s} {'размах/шир':>10s}"
        print(gh)
        for alias in DYN.values():
            gg = geom.get(alias)
            if gg:
                flag = " ⚠️" if gg.get("ratio") and gg["ratio"] > GEOM_RATIO_WARN else ""
                print(f"{alias:9s} {gg['width_pct']:>8.2f} {str(gg['so']):>5s} "
                      f"{gg['day_range_pct']:>9.2f} {str(gg['ratio']):>10s}{flag}")

    print("\nПРЕДЛОЖЕНИЯ (оператор одобряет, бот сам НЕ применяет):")
    for alias, props in all_props.items():
        for p in props:
            print(f"  {alias}: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
