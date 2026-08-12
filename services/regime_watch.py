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
CARD_HOUR_START_LOCAL, CARD_HOUR_END_LOCAL = 11, 13
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

def build_card(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    lines = [f"☀️ {now:%d.%m}"]
    r = btc_regime()
    if not r:
        lines.append("режим: нет данных")
        return "\n".join(lines)
    lines.append(f"BTC {r['price']:,.0f} · SMA20д {r['sma']:,.0f} · "
                 f"{r['dev_pct']:+.2f}%")
    if r["state"] == "РОСТ":
        lines.append(f"режим: РОСТ, {r['up_days']:.0f}-й день над SMA20д")
        lines.append("  ▸ не открывать новый шорт-грид")
        lines.append("  ▸ медианный остаток хода вверх 6.89%")
        lines.append(f"  ▸ книга заполнится за "
                     f"~{GRID_COVERAGE_PCT / TREND_SPEED_PCT_DAY:.0f} дн")
    elif r["state"] == "ПАДЕНИЕ":
        lines.append(f"режим: ПАДЕНИЕ, {r['dn_days']:.0f}-й день под SMA20д")
        lines.append("  ▸ шорт-гриду попутно")
    else:
        d = max(r["up_days"], r["dn_days"])
        side = "над" if r["up_days"] >= r["dn_days"] else "под"
        lines.append(f"режим: боковик · {d:.1f} дн {side} SMA20д "
                     f"(порог {TREND_DAYS})")

    try:
        from tools.grid_health import analyse
        rows = [x for x in analyse(7) if x["status"] == 2]
        jam = [x for x in rows if any("ЗАКЛИНИЛА" in f for f in x["flags"])]
        lines.append(f"гриды: {len(rows)} живых · "
                     + (f"ЗАКЛИНИЛО {len(jam)}" if jam else "заклинивших нет"))
        for x in jam:
            lines.append(f"  ⚠️ {x['name']}: "
                         + "; ".join(f for f in x["flags"] if "ЗАКЛИН" in f))
        rat = [x["margin_ratio"] for x in rows
               if x["margin_ratio"] == x["margin_ratio"]]
        if rat:
            lines.append(f"маржа парка: {min(rat)*100:.0f}–{max(rat)*100:.0f}% "
                         f"от закона")
    except Exception:
        logger.exception("regime_watch.grid_health_failed")
    return "\n".join(lines)


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
        send_fn(card)
        _write_state(CARD_STATE, {"date": day})
        logger.info("regime_card.sent date=%s", day)
        return True
    except Exception:
        logger.exception("regime_card.send_failed")
        return False


def maybe_send_trend_entry(*, send_fn: Optional[Callable] = None,
                           now: Optional[datetime] = None) -> int:
    """Событийный сигнал. Один раз на пару+сторону+день."""
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
