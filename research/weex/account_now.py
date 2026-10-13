"""Только чтение: счёт WEEX, жив ли цикл сеток, сохранность переданной оператору стороны (ревью скилов 12.10).

card_now.py баланса не показывает. Здесь:
  1) депозит и все позиции (включая ручные) — средняя = openValue/size, фандинг — cumFundingFee (поля сверены по
     сырому ответу /capi/v3/account/position/allPosition 12.10); ответ не списком/не словарём → «НЕ ПРОЧИТАНО», код 2;
  2) жив ли цикл — для каждой сетки, которую цикл ведёт живьём: не dry_run (в том числе после /weex stop, enabled=false
     — тейки и закрытие по режиму продолжаются) или холостой с живыми остатками в учёте. Учёт пишется каждый проход
     (~10 с); после ошибки прохода пауза до 60 с — поэтому до 60 с «жив», 60–180 с «пауза? перепроверить», старше
     180 с — ПРОБЛЕМА. Флаг halted в учёте (стоп сетки, например после 3 отказов закрытия) — ПРОБЛЕМА;
  3) режим SMA: вчерашнее закрытие против SMA и порог СЕГОДНЯШНЕГО дневного закрытия UTC, который меняет режим;
  4) сторона из release_sides: объём на бирже, ордера и algo-ордера бота на ней (0), СДЕЛКИ бота (b7g по
     clientOrderId, ответ order_info сверяется по orderId) на ней после «передано оператору» (0) — по бирже, а не по
     журналу бота; записей передачи — не больше одной (передача без лотов записи не оставляет — предупреждение).

    .venv/bin/python3 research/weex/account_now.py      (код 1 — проблема, 2 — не прочитано)
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.weex_api.client import WeexClient  # noqa: E402
from services.weex_grid import engine as eg  # noqa: E402

FRESH_SEC, STALE_SEC = 60, 180
LEFTOVER_KEYS = ("entry", "lots", "strays", "pending", "flatten")


def rows_or_exit(x, what: str) -> list:
    if isinstance(x, list):
        return x
    if isinstance(x, dict) and isinstance(x.get("data"), list):
        return x["data"]
    if isinstance(x, dict) and ("balance" in x or "asset" in x):
        return [x]
    print(f"{what}: НЕ ПРОЧИТАНО — ответ {str(x)[:200]}")
    sys.exit(2)


def trades_since(c: WeexClient, sym: str, start: int) -> tuple[list, bool]:
    """Сделки символа с start: окна ≤6 суток, окно со 100 сделками делится пополам; переполненное секундное окно —
    неполная выборка (второй элемент True)."""
    end = int(time.time() * 1000) + 60_000
    incomplete = []

    def fetch(a: int, b: int) -> list:
        r = c.user_trades(sym, start_ms=a, end_ms=b) or []
        if len(r) < 100:
            return r
        if b - a <= 1000:
            incomplete.append(a)
            return r
        m = (a + b) // 2
        return fetch(a, m) + fetch(m + 1, b)

    out, a = [], start
    while a < end:
        b = min(a + 6 * 86_400_000, end)
        out += fetch(a, b)
        a = b + 1
    return list({str(t["id"]): t for t in out}.values()), bool(incomplete)


def sma_distance(sym: str, n: int, c: WeexClient) -> str:
    """engine.regime_up: режим дня d+1 = close(d) > SMA{n}(d). Порог сегодняшнего закрытия:
    close > (сумма прошлых n−1 закрытий)/(n−1) ⇔ close > SMA{n}, включающей этот close."""
    try:
        now_ms = time.time() * 1000
        rows = [r for r in eg._fetch_daily(sym, n + 5) if int(r[6]) < now_ms]
        closes = [float(r[4]) for r in rows][-n:]
        if len(closes) < n:
            return f"SMA{n}: мало данных"
        sma = sum(closes) / n
        thr = sum(closes[-(n - 1):]) / (n - 1)
        bid, ask = c.book(sym)
        mid = (bid + ask) / 2
        up = closes[-1] > sma
        what = (f"лонги закроются по рынку, если сегодняшний день UTC закроется НИЖЕ {thr:,.2f}" if up else
                f"лонги снова разрешатся, если сегодняшний день UTC закроется ВЫШЕ {thr:,.2f}")
        return (f"режим {'ЛОНГ' if up else 'ВНЕ РЫНКА (ниже SMA)'}: SMA{n} {sma:,.2f}, вчерашнее закрытие "
                f"{closes[-1]:,.2f} ({closes[-1] / sma - 1:+.1%}); цена {mid:,.2f}; {what} ({thr / mid - 1:+.1%} от цены)")
    except Exception as e:                                       # noqa: BLE001
        return f"SMA{n}: не прочитано ({e})"


def owner(c: WeexClient, oid: str, cache: dict) -> str | None:
    """clientOrderId ордера; ответ без совпавшего orderId (пустой/ошибка) → None = «не прочитан»."""
    if oid not in cache:
        info = c.order_info(oid) or {}
        cache[oid] = str(info.get("clientOrderId", "")) if str(info.get("orderId")) == oid else None
    return cache[oid]


def main() -> None:
    c = WeexClient()
    c.sync_time()
    problem = unread = False
    for b in rows_or_exit(c.futures_balance(), "баланс"):
        vals = {k: b.get(k) for k in ("balance", "availableBalance", "unrealizePnl", "frozen") if b.get(k) is not None}
        print("баланс", b.get("asset"), vals)
    size_of = {}
    for p in rows_or_exit(c.futures_positions(), "позиции"):
        size = float(p.get("size") or 0)
        if not size:
            continue
        size_of[(p.get("symbol"), p.get("side"))] = size
        print("позиция", p.get("symbol"), p.get("side"), "объём", p["size"],
              "средняя", round(float(p.get("openValue") or 0) / size, 4), "PnL", p.get("unrealizePnl"),
              "фандинг", p.get("cumFundingFee"))
    for name in eg.GRIDS:
        cfg_path, st_path, journal = eg.grid_files(name)
        cfg = json.loads(cfg_path.read_text())
        sym = cfg["symbol"]
        st = json.loads(st_path.read_text()) if st_path.exists() else None
        leftovers = bool(st) and any(st.get(s, {}).get(k) for s in ("LONG", "SHORT") for k in LEFTOVER_KEYS)
        led_live = not cfg.get("dry_run") or leftovers
        if not led_live:
            continue
        if int(cfg.get("regime_sma") or 0) > 0:
            print(f"{name} {sym}: {sma_distance(sym, int(cfg['regime_sma']), c)}")
        age = time.time() - st_path.stat().st_mtime if st_path.exists() else None
        mode = f"enabled={cfg.get('enabled')} dry_run={cfg.get('dry_run')}"
        if age is None or age > STALE_SEC:
            verdict, bad = "ПРОБЛЕМА: сетка не ходит", True
        elif age > FRESH_SEC:
            verdict, bad = "пауза (после ошибки прохода до 60 с) — перепроверить через минуту", False
        else:
            verdict, bad = "цикл жив", False
        if st and st.get("halted"):
            verdict, bad = f"ПРОБЛЕМА: сетка остановлена (halted) — {st.get('halt_reason')}", True
        problem |= bad
        print(f"{name} {sym}: ведётся живьём ({mode}), учёт обновлён "
              f"{'никогда' if age is None else f'{age:.0f} с назад'} → {verdict}")
        released = cfg.get("release_sides") or []
        if not released:
            continue
        handed: dict[str, list] = {}
        jp = Path(journal)
        first_ts = None
        if jp.exists():
            for line in jp.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                first_ts = first_ts or r.get("ts")
                if r.get("side") in released and r.get("kind") == "передано оператору":
                    handed.setdefault(r["side"], []).append(r["ts"])
        mine = [o for o in c.open_orders(sym) if str(o.get("clientOrderId", "")).startswith(eg.PREFIX)
                and o.get("positionSide") in released]
        algo = [a for a in (c.open_algo_orders(sym) or []) if str(a.get("clientAlgoId", "")).startswith("b7")
                and a.get("positionSide") in released]
        since = min([v[0] for v in handed.values()] + ([first_ts] if first_ts else []), default=None)
        fills, incomplete = (trades_since(c, sym, int(datetime.fromisoformat(since).timestamp() * 1000))
                             if since else ([], False))
        cache: dict = {}
        for s in released:
            times = handed.get(s, [])
            t0 = int(datetime.fromisoformat(times[0]).timestamp() * 1000) if times else None
            bot_after, last_bot, n_unread = [], None, 0
            for t in fills:
                if t.get("positionSide") != s:
                    continue
                cid = owner(c, str(t["orderId"]), cache)
                if cid is None:
                    n_unread += 1
                    continue
                if not cid.startswith(eg.PREFIX):
                    continue
                last_bot = max(last_bot or 0, int(t["time"]))
                if t0 is not None and int(t["time"]) > t0:
                    bot_after.append(t)
            n_ord = len([o for o in mine if o.get("positionSide") == s])
            n_algo = len([a for a in algo if a.get("positionSide") == s])
            bad = len(times) > 1 or n_ord or n_algo or bot_after
            unread |= bool(n_unread or incomplete)
            problem |= bool(bad)
            when = times[0][:16] if times else "записи нет (передана без лотов?)"
            print(f"{name} {sym} {s} передан оператору {when} (записей {len(times)}): позиция на бирже "
                  f"{size_of.get((sym, s), 0):g} — сверить с прошлым значением (память project_portfolio_now); "
                  f"ордеров бота {n_ord}, algo бота {n_algo}, сделок бота после передачи "
                  f"{len(bot_after) if times else 'н/д'}"
                  + ("" if times else f"; последняя сделка бота на стороне "
                     f"{datetime.fromtimestamp(last_bot / 1000):%m-%d %H:%M}" if last_bot else "")
                  + (f"; не прочитано ордеров {n_unread}" if n_unread else "")
                  + ("; ВЫБОРКА СДЕЛОК НЕПОЛНА" if incomplete else "")
                  + f" → {'ПРОБЛЕМА' if bad else ('не прочитано — перепроверить' if n_unread or incomplete else 'бот сторону не трогал')}")
    print("ИТОГ:", "ЕСТЬ ПРОБЛЕМА" if problem else ("НЕ ВСЁ ПРОЧИТАНО" if unread else "ок"))
    sys.exit(1 if problem else (2 if unread else 0))


if __name__ == "__main__":
    main()
