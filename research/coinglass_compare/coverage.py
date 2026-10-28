"""Фактическое покрытие источников на маке для сравнительной аналитики (задание GPT f2559762, п.3 «сначала измерить»).

По каждому журналу: первая/последняя метка, число записей, пропуски дольше ожидаемого шага, задержка последней записи
от «сейчас». Только чтение. Печатает таблицу markdown (в docs/…_ANSWERS_2026-10-28.md).

    .venv/bin/python3 research/coinglass_compare/coverage.py
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.now(timezone.utc)
TS = re.compile(r'"last_updated": "([^"]+)"')


def _dt(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def gaps(ts: list[datetime], step_s: float) -> tuple[int, float]:
    """Число разрывов длиннее 2 шагов и самый длинный разрыв в часах."""
    n, worst = 0, 0.0
    for a, b in zip(ts, ts[1:]):
        d = (b - a).total_seconds()
        if d > 2 * step_s:
            n += 1
            worst = max(worst, d / 3600)
    return n, worst


def row(name: str, ts: list[datetime], step_s: float, extra: str = "") -> str:
    if not ts:
        return f"| {name} | — | — | 0 | — | — | {extra} |"
    ts = sorted(ts)
    n, worst = gaps(ts, step_s)
    lag = (NOW - ts[-1]).total_seconds() / 60
    return (f"| {name} | {ts[0]:%d.%m %H:%M} | {ts[-1]:%d.%m %H:%M} | {len(ts):,} | ".replace(",", " ")
            + f"{n} (макс {worst:.1f} ч) | {lag:.0f} мин | {extra} |")


def deriv() -> str:
    ts, fields = [], set()
    with open(ROOT / "state" / "deriv_live_history.jsonl", encoding="utf-8") as f:
        for line in f:
            m = TS.search(line[:80])
            if m:
                ts.append(_dt(m.group(1)))
        # набор полей BTC — по последней строке
    last = json.loads(line)
    fields = sorted(last.get("BTCUSDT", {}))
    return row("deriv_live 5 мин (Binance premiumIndex/OI/L-S/тейкер, Bybit)", ts, 300,
               "поля BTC: " + ", ".join(fields))


def liq_raw() -> list[str]:
    out = []
    for ex in ("binance", "bybit", "okx"):
        ts, recv_lag, units = [], [], set()
        for p in sorted((ROOT / "market_live" / "liq_raw").glob(f"{ex}_*.jsonl")):
            with open(p, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("symbol") != "BTCUSDT" or not r.get("exchange_ts_ms"):
                        continue
                    ts.append(datetime.fromtimestamp(r["exchange_ts_ms"] / 1000, timezone.utc))
                    recv_lag.append(r["recv_ms"] - r["exchange_ts_ms"])
                    units.add(r.get("qty_unit"))
        recv_lag.sort()
        med = recv_lag[len(recv_lag) // 2] if recv_lag else None
        # события, а не ряд: «разрыв» = час без единой ликвидации (может быть и тишина рынка)
        out.append(row(f"ликвидации {ex} BTCUSDT (liq_raw, время биржи)", ts, 3600,
                       f"приём − биржа, медиана {med} мс; единица qty: {','.join(sorted(map(str, units)))}"))
    return out


def liq_csv() -> str:
    ts = []
    with open(ROOT / "market_live" / "liquidations.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                ts.append(_dt(r["ts_utc"]))
            except (ValueError, KeyError):
                continue
    return row("ликвидации BTC liquidations.csv (время приёма, 3 биржи)", ts, 3600, "до 13–18.10 — единственный источник")


def kl() -> str:
    ts = []
    with open(ROOT / "market_live" / "market_1h.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ts.append(_dt(r["ts_utc"]))
    return row("свечи 1ч market_1h.csv (BTCUSDT)", ts, 3600)


def cg_snapshots() -> str:
    ts, ok = [], 0
    with open(ROOT / "state" / "coinglass" / "snapshots.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            ts.append(_dt(r["ts"]))
            ok += (r.get("status") or {}).get("liquidations") == "ok"
    return row("CoinGlass снимки страниц (зоны, ликвидации 1/4/12/24 ч)", ts, 3600,
               f"ликвидации разобраны в {ok} снимках; ночью 00–06 Варшавы сбора нет")


def cg_tv() -> list[str]:
    out = []
    for sym in ("BTCUSDT", "ETHUSDT"):
        p = ROOT / "state" / "coinglass" / "tv" / f"{sym}_1h.jsonl"
        bars = set()
        if p.exists():
            with open(p, encoding="utf-8") as f:
                for line in f:
                    bars.add(_dt(json.loads(line)["bar"]))
        out.append(row(f"CoinGlass суперчарт {sym} 1ч (exportData)", sorted(bars), 3600,
                       "Whale Index 2, ликвидации всех/Coin-залогом, L/S аккаунтов и топов, фандинг, OI, объём"))
    return out


def main() -> None:
    print(f"Замер {NOW:%Y-%m-%d %H:%M} UTC\n")
    print("| источник | первая | последняя | записей | разрывы > 2 шагов | задержка | заметки |")
    print("|---|---|---|---|---|---|---|")
    for line in (deriv(), *liq_raw(), liq_csv(), kl(), cg_snapshots(), *cg_tv()):
        print(line)


if __name__ == "__main__":
    main()
