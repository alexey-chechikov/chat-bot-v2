"""Опись данных разбора 09.11 для отчёта GPT: файл, строк, первая и последняя метка, sha256 (16). Данные не в git."""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path("/Users/alexeychechikov/code/bot7")
FILES = [
    ("backtests/frozen/BTCUSDT_1m_2017_2024.csv", "Binance спот BTCUSDT 1м (ts, o, h, l, c, v)"),
    ("backtests/frozen/BTCUSDT_1m_2y.csv", "Binance спот BTCUSDT 1м, дописывается каждый час"),
    ("backtests/frozen/BTCUSDT_funding_full.csv", "Binance USDT-M фандинг, дописывается каждый час с 09.11"),
    ("backtests/frozen/BTCUSDT_UM_1m_early.csv", "Binance USDT-M 1м с taker_buy, 2020–2024"),
    ("backtests/frozen/BTCUSDT_UM_1m.csv", "Binance USDT-M 1м с taker_buy, 2024–12.10.2026"),
    ("backtests/frozen/ext_spot_BTCUSDT_1h.csv", "Binance спот 1ч с taker_base (data.binance.vision, сбор Вина)"),
    ("backtests/frozen/ext_metrics_BTCUSDT.csv", "Binance futures metrics 4ч: OI, лонг/шорт, тейкеры (сбор Вина)"),
    ("backtests/frozen/ext_cm_btc.csv", "CoinMetrics community, день: MVRV, адреса, хешрейт, транзакции, выпуск, ROI30d"),
    ("backtests/frozen/ext_stable.csv", "DefiLlama, капитализация стейблкоинов, день"),
    ("backtests/frozen/ext_dvol_BTC.csv", "Deribit DVOL 1ч"),
    ("backtests/frozen/ext_spx_d.csv", "Yahoo ^GSPC, день"),
    ("backtests/frozen/ext_xau_d.csv", "Yahoo GC=F (золото, ближний фьючерс), день"),
    ("backtests/frozen/ext_dxy_d.csv", "Yahoo DX-Y.NYB, день"),
    ("research/coinglass_compare/data/BTCUSDT_1h.csv", "CoinGlass экспорт суперграфика 1ч, 29.04–28.10.2026"),
]


def first_last(p: Path) -> tuple[int, str, str]:
    with p.open("rb") as fh:
        head = fh.readline()
        first = fh.readline().decode("utf-8", "replace").split(",")[0].strip()
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(size - 4096, 0))
        tail = [x for x in fh.read().decode("utf-8", "replace").splitlines() if x.strip()]
    n = sum(1 for _ in p.open("rb")) - 1
    _ = head
    return n, first, tail[-1].split(",")[0].strip()


def main():
    print("| файл | что | строк | первая | последняя | sha256 (16) |")
    print("|---|---|---|---|---|---|")
    for rel, what in FILES:
        p = ROOT / rel
        if not p.exists():
            print(f"| `{rel}` | {what} | нет файла | | | |")
            continue
        n, a, b = first_last(p)
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        print(f"| `{rel}` | {what} | {n} | {a} | {b} | {h} |")


if __name__ == "__main__":
    main()
