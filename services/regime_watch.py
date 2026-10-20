"""Режим рынка: утренняя карточка + событийный сигнал трендового входа.

Основание — docs/RESEARCH/SUSTAINED_MOVES.md (2 года часовых баров, 118 эпизодов):

  ЗАТЯЖНОЕ ДВИЖЕНИЕ (>=6% за >=5 дней) обнаруживается правилом
  «цена выше SMA20д N дней подряд»: 18/30 эпизодов BTC, остаток хода 6.89%,
  ложных 0.3/мес. Зарождение эпизода НЕ предсказуемо (лучший лифт 1.47),
  поэтому здесь только обнаружение уже идущего.

  ТРЕНДОВЫЙ ВХОД «3 дневных закрытия подряд в одну сторону» + выход
  Chandelier ATR x3 за 2 года: XRP лонг +132.4% (винрейт 69%, худшая
  сделка -2.00%, макс. просадка -3.3%), ETH лонг +56.4%, BTC лонг +31.0%.
  Обычный пробой уровня минусовой в 8 комбинациях из 12 — не используем.

Карточка — раз в сутки утром, уважает push_policy оператора.
Сигнал входа — событийный, ~2 срабатывания в месяц на пару.
Обе рассылки дедуплицируются через state/.

Проверить руками:  .venv/bin/python3 -m services.regime_watch
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
CARD_STATE = ROOT / "state" / "regime_card_sent.json"
TREND_STATE = ROOT / "state" / "trend_entry_sent.json"
LIVE_1M = ROOT / "market_live" / "market_1m.csv"

# Окно карточки — по МЕСТНОМУ времени мака (Варшава), чтобы не плавать
# при переходе на зимнее. Замер 2 лет часовых баров BTC: сессия США
# 13-21 UTC даёт 41.7% суточного хода, пик 14:00 UTC (1.85x нормы),
# 57% затяжных эпизодов стартуют в 12-21 UTC. 11:00 Варшавы — за 4.5 часа
# до этого окна и через 9 часов после дневного закрытия.
CARD_HOUR_START_LOCAL, CARD_HOUR_END_LOCAL = 8, 11      # 18.10 оператор: «к утру сводку» (было 11–13)
TREND_DAYS = 5                 # порог затяжного движения по SMA20д
TREND_SPEED_PCT_DAY = 1.53     # медианная скорость затяжного движения
GRID_COVERAGE_PCT = 6.0        # 300 ордеров x 0.02%
STREAK_DAYS = 3                # дневных закрытий подряд для трендового входа
CHANDELIER_ATR = 3.0
TREND_PAIRS = ("XRPUSDT", "ETHUSDT")   # BTC оставлен гриду


# ----------------------------------------------------------------- утилиты

def _read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        logger.exception("regime_watch.write_state_failed path=%s", path)


def _daily_bars(symbol: str, limit: int = 40) -> list[dict]:
    """Закрытые дневные бары с публичного Binance. Текущий (незакрытый) день
    отбрасываем — по нему считать «закрытие подряд» нельзя."""
    url = ("https://api.binance.com/api/v3/klines"
           f"?symbol={symbol}&interval=1d&limit={limit}")
    req = urllib.request.Request(url, headers={"User-Agent": "bot7/1.0"})
    try:
        raw = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception:
        logger.warning("regime_watch.klines_failed symbol=%s", symbol)
        return []
    bars = [{"high": float(k[2]), "low": float(k[3]), "close": float(k[4])}
            for k in raw]
    return bars[:-1] if len(bars) > 1 else bars


# ------------------------------------------------------------ режим по BTC

def btc_regime() -> dict:
    """Сколько дней подряд цена держится выше/ниже SMA20д."""
    try:
        import pandas as pd
    except ImportError:
        return {}
    if not LIVE_1M.exists():
        return {}
    size = LIVE_1M.stat().st_size
    with LIVE_1M.open("rb") as fh:
        header = fh.readline().decode("utf-8", "replace")
        fh.seek(max(fh.tell(), size - 40 * 1024 * 1024))
        fh.readline()
        body = fh.read().decode("utf-8", "replace")
    import io
    px = pd.read_csv(io.StringIO(header + body), on_bad_lines="skip",
                     low_memory=False)
    px["ts"] = pd.to_datetime(px["ts_utc"], utc=True, errors="coerce")
    px["close"] = pd.to_numeric(px["close"], errors="coerce")
    px = px.dropna(subset=["ts", "close"]).set_index("ts").sort_index()
    h = px["close"].resample("1h").last().ffill()
    if len(h) < 480 + TREND_DAYS * 24:
        return {}
    sma = h.rolling(480).mean()
    above = (h > sma).to_numpy()

    def streak(flags, want):
        k = 0
        for v in flags[::-1]:
            if bool(v) is not want:
                break
            k += 1
        return k

    up_h = streak(above, True)
    dn_h = streak(above, False)
    state = ("РОСТ" if up_h >= TREND_DAYS * 24
             else "ПАДЕНИЕ" if dn_h >= TREND_DAYS * 24 else "боковик")
    return {"state": state, "up_days": up_h / 24, "dn_days": dn_h / 24,
            "price": float(h.iloc[-1]), "sma": float(sma.iloc[-1]),
            "dev_pct": float(h.iloc[-1] / sma.iloc[-1] - 1) * 100}


# --------------------------------------------------------- трендовый вход

def trend_state(symbol: str) -> dict:
    """Три дневных закрытия подряд в одну сторону + уровень Chandelier."""
    bars = _daily_bars(symbol)
    if len(bars) < 20:
        return {}
    closes = [b["close"] for b in bars]
    up = all(closes[-i] > closes[-i - 1] for i in range(1, STREAK_DAYS + 1))
    dn = all(closes[-i] < closes[-i - 1] for i in range(1, STREAK_DAYS + 1))
    trs = []
    for i in range(1, len(bars)):
        h_, l_, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h_ - l_, abs(h_ - pc), abs(l_ - pc)))
    atr = sum(trs[-14:]) / len(trs[-14:])
    hh = max(b["high"] for b in bars[-STREAK_DAYS:])
    ll = min(b["low"] for b in bars[-STREAK_DAYS:])
    return {"symbol": symbol, "close": closes[-1], "atr": atr,
            "fire_long": up, "fire_short": dn,
            "stop_long": hh - CHANDELIER_ATR * atr,
            "stop_short": ll + CHANDELIER_ATR * atr}


# ------------------------------------------------------------- построение

def _sma_exit(symbol: str, n: int = 100) -> Optional[tuple[float, float]]:
    """(цена сейчас, порог): лонги сеток WEEX закроются по рынку, если сегодняшний день UTC закроется НИЖЕ порога.
    То же правило, что engine.regime_up: close > SMA{n}, включающей этот close ⇔ close > среднее прошлых n−1 закрытий.
    Дневки Binance spot; цена — закрытие формирующейся дневки (последняя сделка)."""
    from services.weex_grid import engine as eg
    rows = eg._fetch_daily(symbol, n + 2)
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    closes = [float(r[4]) for r in rows if int(r[6]) < now_ms][-(n - 1):]
    if len(closes) < n - 1 or not rows:
        return None
    return float(rows[-1][4]), sum(closes) / len(closes)


def _ts(v) -> float:
    try:
        return datetime.fromisoformat(str(v)).timestamp()
    except ValueError:
        return 0.0


def _grid_rows(prices: dict, since: float) -> list[tuple[str, float, int, float, int]]:
    """(подпись, закрыто за сутки $ после комиссий, циклов, мешок $, лотов) по живым сеткам WEEX и сеткам с лотами."""
    from services.weex_grid import engine as eg
    from services.weex_grid.loop import run_files
    out = []
    for name in eg.GRIDS:
        cfg = eg.peek_config(name)
        if not cfg:
            continue
        st_path, jr_path = run_files(name, False)
        try:
            st = json.loads(st_path.read_text(encoding="utf-8")) if st_path.exists() else {}
        except (OSError, ValueError):
            st = {}
        mid = prices.get(cfg["symbol"])
        bag, nlots = 0.0, 0
        for side, d in (("LONG", 1), ("SHORT", -1)):
            for lot in (st.get(side) or {}).get("lots") or []:
                nlots += 1
                if mid:
                    bag += d * float(lot["qty"]) * (mid - float(lot["entry"]))
        live = not cfg["dry_run"] and cfg["enabled"]
        if not live and not nlots:
            continue
        closed, cycles = 0.0, 0
        try:
            for line in jr_path.read_text(encoding="utf-8").splitlines() if jr_path.exists() else []:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if _ts(r.get("ts")) < since:
                    continue
                closed -= float(r.get("fee") or 0)
                if "pnl" in r:
                    closed += float(r.get("pnl") or 0)
                    cycles += str(r.get("kind", "")).startswith("тейк")
        except OSError:
            pass
        label = name                                            # BTC, ETH, B34…
        out.append((f"{label} {cfg['step_pct']:g}/{cfg['target_pct']:g}", closed, cycles, bag, nlots))
    return out


def build_card(now: Optional[datetime] = None) -> str:
    """Карточка дня под WEEX (оператор 18.10): расстояние до выключателя SMA100 и живые сетки — закрыто за сутки и
    мешок сейчас. Прежние строки SMA20д/шорт-гейта/гридов GinArea убраны: GinArea остановлена с 07.10, шорт-сеток нет,
    «гриды: 0 живых» при пяти живых сетках WEEX вводило в заблуждение."""
    now = now or datetime.now(timezone.utc)
    prices: dict[str, float] = {}
    sma = []
    for sym in ("BTCUSDT", "ETHUSDT"):
        try:
            got = _sma_exit(sym)
        except Exception:                                       # noqa: BLE001
            logger.exception("regime_card.sma_failed %s", sym)
            got = None
        if not got:
            sma.append(f"{sym[:3]} SMA100 не прочитана — режим неизвестен")
            continue
        px, thr = got
        prices[sym] = px
        sma.append(f"{sym[:3]} ниже {thr:,.0f} ({thr / px - 1:+.1%})")
    lines = [f"☀️ {now.astimezone():%d.%m} · сетки WEEX — за сутки · мешок сейчас (без фандинга)"]
    try:
        rows = _grid_rows(prices, now.timestamp() - 86_400)
    except Exception:                                           # noqa: BLE001
        logger.exception("regime_card.grids_failed")
        rows = []
    if not rows:
        lines.append("живых сеток нет")
    for label, closed, cycles, bag, nlots in rows:
        lines.append(f"{label}: {closed:+,.2f}$ · {cycles} цикл. · мешок {bag:+,.2f}$ ({nlots} лот.)")
    if rows:
        lines.append(f"Итого: {sum(r[1] for r in rows):+,.2f}$ · мешок {sum(r[3] for r in rows):+,.2f}$")
    lines.append("🛡 Лонги закроются, если день закроется: " + " · ".join(sma))
    return "\n".join(lines) + _market_brief()


def _market_brief() -> str:
    """18.10 (оператор): вывод на день по данным панелей CoinGlass (публичные первоисточники), что изменилось со
    вчера, статистика 2 лет и проверка вчерашнего вывода — services/market_brief. Сбой не ломает карточку."""
    try:
        from services.market_brief import history, brief
        for sym in brief.SYMS:
            try:
                history.update(sym)                             # дописать вчерашний день в историю
            except Exception:                                   # noqa: BLE001
                logger.exception("regime_card.brief_history_failed %s", sym)
        return "\n\n" + brief.build()
    except Exception:                                           # noqa: BLE001
        logger.exception("regime_card.brief_failed")
        return ""


def build_trend_alert(st: dict, side: str) -> str:
    name = st["symbol"].replace("USDT", "")
    if side == "long":
        return (f"📈 ТРЕНД {name} · ЛОНГ\n"
                f"три дневных закрытия подряд вверх, цена {st['close']:,.4f}\n"
                f"стоп Chandelier ATR×3: {st['stop_long']:,.4f} "
                f"({(1 - st['stop_long'] / st['close']) * 100:.1f}% ниже)\n"
                f"замер 2г: винрейт 69% (XRP) / 57% (ETH), "
                f"худшая сделка −2.0%, ~2 сделки в месяц")
    return (f"📉 ТРЕНД {name} · ШОРТ\n"
            f"три дневных закрытия подряд вниз, цена {st['close']:,.4f}\n"
            f"стоп Chandelier ATR×3: {st['stop_short']:,.4f} "
            f"({(st['stop_short'] / st['close'] - 1) * 100:.1f}% выше)")


# ---------------------------------------------------------------- отправка

def _card_push_enabled() -> bool:
    """Оператор 12.08 попросил именно эту карточку раз в сутки утром.
    Глобальный scheduled_push=false её не глушит — для неё отдельный ключ
    regime_card в state/report_delivery.json. Если ключа нет, падаем
    на глобальную политику."""
    cfg = _read_state(ROOT / "state" / "report_delivery.json")
    if "regime_card" in cfg:
        return bool(cfg["regime_card"])
    from services.reports.push_policy import scheduled_push_enabled
    return scheduled_push_enabled()


DELIVERY_LOG = ROOT / "state" / "coinglass" / "delivery_log.jsonl"


def _log_delivery(day: str, card: str, res: dict | None = None) -> None:
    """Доказательство доставки для GPT: время отправки, SHA карточки и блока CoinGlass, какой снимок в нём, сколько
    отправок прошло (send_fn бросает, если ни одной). Без чатов: id сообщений только хешем. Сбой записи не ломает
    отправку."""
    try:
        import hashlib
        import json
        from services.coinglass_web import section as cg
        rec = {"date": day, "sent_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "card_sha256": hashlib.sha256(card.encode("utf-8")).hexdigest(),
               "coinglass_block_in_card": "🧲 CoinGlass" in card, **cg.LAST}
        if res:
            rec.update(sent_ok=res.get("sent_ok"), recipients=res.get("recipients"),
                       message_ids_sha256=hashlib.sha256(json.dumps(res.get("message_ids")).encode()).hexdigest())
        DELIVERY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(DELIVERY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:                                           # noqa: BLE001
        logger.exception("regime_card.delivery_log_failed")


def maybe_send_regime_card(*, send_fn: Optional[Callable] = None,
                           now: Optional[datetime] = None) -> bool:
    if send_fn is not None and not _card_push_enabled():
        send_fn = None
    now = now or datetime.now(timezone.utc)
    local = now.astimezone()          # мак стоит на Варшаве
    if not (CARD_HOUR_START_LOCAL <= local.hour < CARD_HOUR_END_LOCAL):
        return False
    day = local.strftime("%Y-%m-%d")
    if _read_state(CARD_STATE).get("date") == day:
        return False
    card = build_card(now)
    if send_fn is None:
        logger.info("regime_card.dry_run\n%s", card)
        _write_state(CARD_STATE, {"date": day})
        return True
    try:
        res = send_fn(card)
        _write_state(CARD_STATE, {"date": day})
        logger.info("regime_card.sent date=%s", day)
        _log_delivery(day, card, res if isinstance(res, dict) else None)
        return True
    except Exception:
        logger.exception("regime_card.send_failed")
        return False


def maybe_send_trend_entry(*, send_fn: Optional[Callable] = None,
                           now: Optional[datetime] = None) -> int:
    """Событийный сигнал. Один раз на пару+сторону+день.
    18.10 (оператор «да»): в TG только при regime_card-соседнем ключе trend_entry=true в state/report_delivery.json —
    тренд ETH/XRP вне периода отбора «Не квалифицирован» (docs/TREND_4H_RECHECK_RESULTS_2026-10-15.md); журнал пишется."""
    if send_fn is not None and not _read_state(ROOT / "state" / "report_delivery.json").get("trend_entry", False):
        send_fn = None
    now = now or datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    seen = _read_state(TREND_STATE)
    sent = 0
    for sym in TREND_PAIRS:
        st = trend_state(sym)
        if not st:
            continue
        for side, fire in (("long", st["fire_long"]),
                           ("short", st["fire_short"])):
            if not fire:
                continue
            key = f"{sym}:{side}"
            if seen.get(key) == day:
                continue
            msg = build_trend_alert(st, side)
            if send_fn is None:
                logger.info("trend_entry.dry_run %s\n%s", key, msg)
            else:
                try:
                    send_fn(msg)
                except Exception:
                    logger.exception("trend_entry.send_failed key=%s", key)
                    continue
            seen[key] = day
            sent += 1
    if sent:
        _write_state(TREND_STATE, seen)
    return sent


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    print(build_card())
    print()
    for _s in TREND_PAIRS:
        _st = trend_state(_s)
        if not _st:
            print(f"{_s}: нет данных")
            continue
        print(f"{_s}: цена {_st['close']:,.4f}  лонг={_st['fire_long']}  "
              f"шорт={_st['fire_short']}  стоп-лонг {_st['stop_long']:,.4f}")
