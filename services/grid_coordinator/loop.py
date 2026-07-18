"""Grid Coordinator: индикатор истощения движения для grid-ботов.

Каждые 5 минут проверяет 5 независимых сигналов:

UPSIDE EXHAUSTION (для SHORT-ботов оператора):
  1. RSI(14) 1h >= 75 AND RSI снижается (RSI(t) < RSI(t-2))
  2. MFI(14) 1h >= 75 (Money Flow Index — подтверждает истощение покупателей)
  3. Volume z-score 1h < 0 на новом хайе цены (no volume confirmation)
  4. OI 1h change > +1.0% AND funding > 0.04%/8h (longs over-crowded)
  5. BTC↔ETH 30h Pearson corr >= 0.7 AND ETH RSI >= 70 (sync пик)

DOWNSIDE EXHAUSTION (для LONG-ботов):
  Симметрично: RSI <= 25 + растёт, MFI <= 25, vol_z < 0 на лоу,
  OI rising + funding < -0.04%, BTC↔ETH corr + ETH RSI <= 30.

Если 3+ из 5 совпадают — шлёт TG-карточку.

2026-05-29 ВАЖНО (docs/STRATEGIES/GC_DOWN_DIAGNOSTIC.md): бэктест на 22-дневном
live-точном окне показал, что DOWNSIDE-сигнал — это НЕ разворот, а ПРОДОЛЖЕНИЕ
движения вниз. Фейдить его (LONG) убыточно во всех срезах и тем хуже, чем выше
score; зеркальный SHORT — +EV, WR/PF растут со score (1h score>=5: WR 78%,
PF 10.7 против 39% безусловного фона). Поэтому down-карточка переименована в
«🔻 НИЗ — ИМПУЛЬС ВНИЗ» и советует защитить LONG-сетки / рассмотреть SHORT, а не
«закрыть и откупить на откате». Paper-emit для down теперь SHORT (continuation).

2026-05-29 UP-сторона перевалидирована тем же методом (docs/STRATEGIES/
GC_UP_DIAGNOSTIC.md): UP — тоже ПРОДОЛЖЕНИЕ, не разворот. SHORT-фейд −EV (score≥3
WR 17%, EV −0.40%), зеркальный LONG бьёт медвежий baseline, forward-drift
положительный и растёт со score (%UP@4h 58/75/100 для 3/4/5). Edge СЛАБЫЙ /
regime-contingent (22-дн окно было net −8.9%), поэтому карточка переименована в
«🔝 ВЕРХ — ИМПУЛЬС ВВЕРХ» с пометкой low-conviction, а paper-emit для up
переключён SHORT→LONG (continuation). Перепроверить на ranging/bull окне.

Cooldown 30 мин между алертами одного направления.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DERIV_LIVE_PATH = ROOT / "state" / "deriv_live.json"
DEDUP_PATH = ROOT / "state" / "grid_coordinator_dedup.json"
JOURNAL_PATH = ROOT / "state" / "grid_coordinator_fires.jsonl"

POLL_INTERVAL_SEC = 300        # 5 min
COOLDOWN_SEC = 3600             # 60 min между алертами одного направления
# 2026-05-13: было 30min, но 08:00 и 08:30 на 13.05 прислали оба → одно событие
# (3/6 сигналов с теми же значениями). 60min убирает этот класс дубликатов.

# Пороги
RSI_OVERBOUGHT = 65.0           # was 75 — operator pointed to extrema where RSI was 68.5; 65 catches them
RSI_OVERSOLD = 35.0             # was 25 — symmetric
MFI_OVERBOUGHT = 70.0           # was 75 — slight loosening for symmetry
MFI_OVERSOLD = 30.0             # was 25
OI_RISING_PCT = 0.3             # was 1.0 — high-vol; |OI| moves >=0.3% are 81 events / 28d
FUNDING_HIGH_8H = 0.00003       # ≈0.003%/8h — actual 2026 BTC funding rarely above 0.005%
VOL_SPIKE_Z = 1.5               # NEW: capitulation/blow-off requires vol z-score >= 1.5
ETH_CORR_LOOKBACK = 30
ETH_CORR_THRESHOLD = 0.70
ETH_RSI_HIGH = 70.0
ETH_RSI_LOW = 30.0

# ── Bottom-exhaustion (2026-06-25, ревью Вина): на ЭКСТРЕМЕ (RSI<20, MFI<15)
# моментум РАЗВОРАЧИВАЕТСЯ, не продолжается. GC «continuation»-эдж валиден на
# RSI~35, но на капитуляции (RSI 11-17) бот орал «86% вниз» в самом дне (59 438,
# через 30мин отскок). Складываем ингредиенты дна (экстрим + OI-делеверидж +
# funding-squeeze + кластер свипов) и ИНВЕРТИРУЕМ заголовок в «выдыхается».
EXTREME_RSI = 20.0
EXTREME_MFI = 15.0
OI_DELEVERAGE_PCT = 1.0          # OI 1ч <= -1% = делеверидж (лонги выходят)
FUNDING_SQUEEZE_8H = 0.00005     # funding <= -0.005%/8h = шорты платят = squeeze
LIQ_CSV_PATH = ROOT / "market_live" / "liquidations.csv"
SWEEP_CLUSTER_BTC = 15.0         # ∑ long-ликвидаций за окно = капитуляционный кластер
SWEEP_WINDOW_MIN = 30


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_g = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_l = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_g / avg_l.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def _mfi(high: pd.Series, low: pd.Series, close: pd.Series,
         volume: pd.Series, period: int = 14) -> pd.Series:
    typical = (high + low + close) / 3.0
    raw = typical * volume
    delta = typical.diff()
    pos = raw.where(delta > 0, 0.0).rolling(period, min_periods=1).sum()
    neg = raw.where(delta < 0, 0.0).rolling(period, min_periods=1).sum().replace(0, 1e-9)
    return 100 - (100 / (1 + pos / neg))


def _vol_z(volume: pd.Series, period: int = 20) -> pd.Series:
    m = volume.rolling(period, min_periods=1).mean()
    s = volume.rolling(period, min_periods=1).std().replace(0, 1.0)
    return (volume - m) / s


def _read_deriv() -> dict:
    if not DERIV_LIVE_PATH.exists():
        return {}
    try:
        return json.loads(DERIV_LIVE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _load_dedup() -> dict:
    if not DEDUP_PATH.exists():
        return {}
    try:
        return json.loads(DEDUP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_dedup(d: dict) -> None:
    try:
        DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEDUP_PATH.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("grid_coordinator.dedup_save_failed")


def _journal(rec: dict) -> None:
    try:
        JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except OSError:
        logger.exception("grid_coordinator.journal_failed")


def evaluate_exhaustion(btc: pd.DataFrame, eth: pd.DataFrame | None,
                       deriv: dict, xrp: pd.DataFrame | None = None) -> dict:
    """Возвращает dict со счётчиками сигналов:
       {'upside_score': 0..6, 'downside_score': 0..6, 'details': {...}}

    2026-05-10: добавлен 6-й сигнал XRP lead (MFI). XRP исторически опережает
    BTC на 1-4ч в exhaustion-фазах (см. detect_short_mfi_multi_ga). XRP MFI
    overbought/oversold добавляется к score.
    """
    if btc is None or len(btc) < 35:
        return {"upside_score": 0, "downside_score": 0, "details": {"reason": "btc_thin"}}

    close = btc["close"].astype(float)
    high = btc["high"].astype(float)
    low = btc["low"].astype(float)
    volume = btc["volume"].astype(float)

    rsi_btc = _rsi(close)
    mfi_btc = _mfi(high, low, close, volume)
    vz = _vol_z(volume)

    rsi_now = float(rsi_btc.iloc[-1])
    rsi_2bar_ago = float(rsi_btc.iloc[-3]) if len(rsi_btc) >= 3 else rsi_now
    mfi_now = float(mfi_btc.iloc[-1])
    vz_now = float(vz.iloc[-1])

    # Цена на новом хайе/лоу за 24h?
    last24h_high = float(high.iloc[-24:].max())
    last24h_low = float(low.iloc[-24:].min())
    close_now = float(close.iloc[-1])
    is_new_high = close_now >= last24h_high * 0.999
    is_new_low = close_now <= last24h_low * 1.001

    btc_deriv = deriv.get("BTCUSDT", {}) if isinstance(deriv, dict) else {}
    oi_change = float(btc_deriv.get("oi_change_1h_pct") or 0)
    funding = float(btc_deriv.get("funding_rate_8h") or 0)

    # ETH
    eth_rsi_now = None
    btc_eth_corr = 0.0
    if eth is not None and len(eth) >= ETH_CORR_LOOKBACK:
        eth_close = eth["close"].astype(float)
        eth_rsi = _rsi(eth_close)
        eth_rsi_now = float(eth_rsi.iloc[-1])
        # Pearson на последних 30 барах
        n = min(len(close), len(eth_close), ETH_CORR_LOOKBACK)
        if n >= 10:
            a = close.iloc[-n:].reset_index(drop=True)
            b = eth_close.iloc[-n:].reset_index(drop=True)
            try:
                btc_eth_corr = float(a.corr(b))
            except Exception:
                btc_eth_corr = 0.0

    # XRP — lead indicator. XRP MFI overbought/oversold suggests BTC will follow.
    xrp_mfi_now = None
    if xrp is not None and len(xrp) >= 20:
        xrp_high = xrp["high"].astype(float)
        xrp_low = xrp["low"].astype(float)
        xrp_close = xrp["close"].astype(float)
        xrp_volume = xrp["volume"].astype(float)
        xrp_mfi = _mfi(xrp_high, xrp_low, xrp_close, xrp_volume)
        xrp_mfi_now = float(xrp_mfi.iloc[-1])

    # UPSIDE EXHAUSTION CHECKS
    up_signals = {}
    up_signals["rsi_high"] = (rsi_now >= RSI_OVERBOUGHT)
    up_signals["mfi_high"] = (mfi_now >= MFI_OVERBOUGHT)
    # 2026-05-10 STRUCTURAL FIX: blow-off top = ВЫСОКИЙ объём на росте, не "no confirm".
    # Capitulation buying flushes longs into the high before reversal.
    up_signals["volume_spike_at_high"] = (vz_now >= VOL_SPIKE_Z and rsi_now >= RSI_OVERBOUGHT)
    # 2026-05-10 STRUCTURAL FIX: на blow-off top OI падает (deleverage) ИЛИ funding высокий.
    # Старая логика "OI растёт + funding высокий" — это профиль open shorts, не exhaustion.
    up_signals["deleverage_or_funding_top"] = (
        oi_change <= -OI_RISING_PCT or funding >= FUNDING_HIGH_8H
    )
    up_signals["eth_sync_high"] = (
        btc_eth_corr >= ETH_CORR_THRESHOLD and eth_rsi_now is not None
        and eth_rsi_now >= ETH_RSI_HIGH
    )
    # XRP lead — 6th signal (2026-05-10)
    up_signals["xrp_mfi_high"] = (xrp_mfi_now is not None and xrp_mfi_now >= MFI_OVERBOUGHT)
    upside_score = sum(1 for v in up_signals.values() if v)

    # DOWNSIDE EXHAUSTION CHECKS
    down_signals = {}
    down_signals["rsi_low"] = (rsi_now <= RSI_OVERSOLD)
    down_signals["mfi_low"] = (mfi_now <= MFI_OVERSOLD)
    # 2026-05-10: capitulation low = high volume spike on the downside.
    down_signals["volume_spike_at_low"] = (vz_now >= VOL_SPIKE_Z and rsi_now <= RSI_OVERSOLD)
    # На капитуляции OI падает (longs закрывают) ИЛИ funding flips negative.
    down_signals["deleverage_or_funding_bottom"] = (
        oi_change <= -OI_RISING_PCT or funding <= -FUNDING_HIGH_8H
    )
    down_signals["eth_sync_low"] = (
        btc_eth_corr >= ETH_CORR_THRESHOLD and eth_rsi_now is not None
        and eth_rsi_now <= ETH_RSI_LOW
    )
    down_signals["xrp_mfi_low"] = (xrp_mfi_now is not None and xrp_mfi_now <= MFI_OVERSOLD)
    downside_score = sum(1 for v in down_signals.values() if v)

    return {
        "upside_score": upside_score,
        "downside_score": downside_score,
        "details": {
            "rsi_btc_now": round(rsi_now, 1),
            "rsi_2bar_ago": round(rsi_2bar_ago, 1),
            "mfi_btc_now": round(mfi_now, 1),
            "vol_z_now": round(vz_now, 2),
            "is_new_24h_high": is_new_high,
            "is_new_24h_low": is_new_low,
            "oi_change_1h_pct": oi_change,
            "funding_rate_8h": funding,
            "eth_rsi_now": round(eth_rsi_now, 1) if eth_rsi_now is not None else None,
            "btc_eth_corr_30h": round(btc_eth_corr, 3),
            "xrp_mfi_now": round(xrp_mfi_now, 1) if xrp_mfi_now is not None else None,
            "btc_close": round(close_now, 1),
            "up_signals": up_signals,
            "down_signals": down_signals,
        },
    }


def _recent_long_liq_btc(now: datetime) -> float:
    """∑ BTC long-ликвидаций (форс-продажи = капитуляция) за SWEEP_WINDOW_MIN."""
    if not LIQ_CSV_PATH.exists():
        return 0.0
    cutoff = now - timedelta(minutes=SWEEP_WINDOW_MIN)
    total = 0.0
    try:
        size = LIQ_CSV_PATH.stat().st_size
        with LIQ_CSV_PATH.open("rb") as fh:
            if size > 400_000:
                fh.seek(size - 400_000); fh.readline()
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
        for ln in lines:
            p = ln.split(",")
            if len(p) != 5 or p[0] == "ts_utc":
                continue
            try:
                ts = datetime.fromisoformat(p[0])
                side = p[2]; qty = float(p[3])
            except (ValueError, IndexError):
                continue
            if ts >= cutoff and side == "long" and qty > 0:
                total += qty
    except OSError:
        pass
    return total


def evaluate_bottom_exhaustion(details: dict, now: datetime) -> dict:
    """ИНВЕРСИЯ чтения на экстремуме: складываем ингредиенты капитуляционного дна.
    Гейт — экстрим (RSI<20 И MFI<15, оба обязательны, редкое событие). Затем
    подтверждения: OI-делеверидж, funding-squeeze, кластер long-свипов. Fired при
    экстриме + ≥2 подтверждениях = реальная капитуляция, не просто перепроданность."""
    rsi = details.get("rsi_btc_now")
    mfi = details.get("mfi_btc_now")
    if rsi is None or mfi is None:
        return {"fired": False}
    if not (rsi <= EXTREME_RSI and mfi <= EXTREME_MFI):
        return {"fired": False, "extreme": False}
    oi = float(details.get("oi_change_1h_pct") or 0)
    funding = float(details.get("funding_rate_8h") or 0)
    long_liq = _recent_long_liq_btc(now)
    deleverage = oi <= -OI_DELEVERAGE_PCT
    squeeze = funding <= -FUNDING_SQUEEZE_8H
    sweep = long_liq >= SWEEP_CLUSTER_BTC
    confirms = sum([deleverage, squeeze, sweep])
    return {"fired": confirms >= 2, "extreme": True, "confirms": confirms,
            "deleverage": deleverage, "squeeze": squeeze, "sweep": sweep,
            "long_liq_btc": round(long_liq, 1), "oi": oi, "funding": funding,
            "rsi": rsi, "mfi": mfi, "btc_close": details.get("btc_close")}


def _live_gc_edge_line() -> str:
    """Живая P(ниже через 4ч) по скользящим 60д собственных down-fires.

    Аудит 2026-07-18: статичный «≈73%» из бэктеста жил в карточке 1.5 месяца
    после смерти эджа. Число теперь только из edge_stats (данные < 24ч)."""
    try:
        from services.pre_cascade_alert.edge_stats import format_line, get_stats
        return "Живой эдж: " + format_line(get_stats(), "gc_down_4h",
                                           "P(ниже 4ч)") + "."
    except Exception:
        logger.exception("grid_coordinator.edge_stats_failed")
        return "Живой эдж: статистика недоступна."


def _format_exhaustion_card(bx: dict) -> str:
    bits = []
    if bx.get("deleverage"):
        bits.append(f"  • OI делеверидж {bx['oi']:+.2f}% (лонги выходят)")
    if bx.get("squeeze"):
        bits.append(f"  • funding засквизен {bx['funding']*100:+.4f}% (шорты платят)")
    if bx.get("sweep"):
        bits.append(f"  • кластер long-свипов {bx['long_liq_btc']:.0f} BTC (форс-продажи = капитуляция)")
    px = bx.get("btc_close")
    head = f"BTC: ${px:,.0f}  " if px else ""
    return (
        f"📈 ПАДЕНИЕ ВЫДЫХАЕТСЯ — сетап на ОТСКОК ({bx['confirms']}/3 подтверждений)\n"
        f"\n"
        f"{head}RSI={bx['rsi']}  MFI={bx['mfi']}  (ЭКСТРИМ перепроданности)\n"
        f"Сложились ингредиенты дна:\n"
        + "\n".join(bits) + "\n"
        f"\n"
        f"⚠️ НЕ прогноз точного дна (заранее не определить — стена), а ИНВЕРСИЯ\n"
        f"чтения: на экстремуме моментум РАЗВОРАЧИВАЕТСЯ, не продолжается.\n"
        f"→ Сними/не добавляй шорт. Если играешь отскок — ядро сетапа funding-\n"
        f"squeeze LONG (ист. 70%), вход по ПОДТВЕРЖДЕНИЮ (слом 15m вверх /\n"
        f"dump_reversal стрельнёт), НЕ на ноже.\n"
        f"Это рекомендация — бот не торгует, решение оператора."
    )


def _format_card(direction: str, score: int, details: dict) -> str:
    if direction == "up":
        emoji = "🔝"
        # 2026-05-29 backtest (GC_UP_DIAGNOSTIC.md): the UP side mirrors the DOWN
        # finding — it is NOT a reversal/exhaustion but an upside-CONTINUATION
        # signal. The old SHORT fade was -EV (score>=3 deduped EV -0.40%, WR 17%);
        # the mirror LONG beats the (bearish-window) base rate and forward drift
        # after a fire is positive & rises with score (%UP@4h 58/75/100 for 3/4/5).
        # Edge is WEAK / regime-contingent (22d window was net -8.9%), so the card
        # is re-framed to continuation but flagged low-conviction. Paper-emit
        # flipped SHORT->LONG to collect correctly-signed live outcomes.
        title = f"ВЕРХ — ИМПУЛЬС ВВЕРХ ({score}/6 сигналов)"
        # 2026-06-15 (ревью Вина): НЕ квотируем точный % на крошечной выборке — «≈100% (n=3)»
        # вводило в заблуждение, и сигнал строится на rsi/mfi_high = ПЕРЕКУПЛЕННОСТЬ (бот
        # увереннее у вершины). Up-импульс = слабый перевес, не вероятность; честный текст.
        action = (
            f"⬆️ Слабый перевес вверх ({score}/6, n мал — НЕ статистика; окно бэктеста медвежье). "
            f"Сигнал на rsi/mfi_high = ПЕРЕКУПЛЕННОСТЬ → не гнаться за входом наверху.\n"
            "→ SHORT-сетки под риском (подтяни/закрой). LONG-вход — только с реклеймом "
            "структуры (BTC>EMA200·4ч), НЕ по этому сигналу."
        )
        sigs = details.get("up_signals", {})
    else:
        emoji = "🔻"
        # 2026-05-29 backtest (GC_DOWN_DIAGNOSTIC.md): down-exhaustion is NOT a
        # reversal — it's a downside-CONTINUATION signal. Fading it (LONG) loses
        # in every slice and worsens with score; the mirror SHORT is +EV with
        # WR/PF rising monotonically (1h score>=5: WR 78%, PF 10.7; vs 39% base).
        # Re-labelled + re-framed from the old "истощение/закрой LONG, откупи на
        # откате" which had the polarity inverted.
        title = f"НИЗ — ИМПУЛЬС ВНИЗ ({score}/6 сигналов)"
        # Аудит 2026-07-18: статичные «73/78/86%» из бэктеста 05-29 умерли на
        # живых fires (60д: 48.5% ниже@4ч, июль 38%; score>=5: 45%, mean +0.24%
        # ВВЕРХ). Mirror-short подсказка снята — на live она убыточна. Карточка
        # остаётся индикатором полярности (тайминг защиты контр-ноги сеток),
        # вероятность печатаем ЖИВУЮ из собственного журнала fires.
        action = (
            f"⬇️ Полярность: продолжение вниз (не разворот). {_live_gc_edge_line()}\n"
            "→ Защити/сократи LONG-сетки (полярность, не прогноз — "
            "живой эдж направления см. выше)."
        )
        sigs = details.get("down_signals", {})

    triggered = [k for k, v in sigs.items() if v]
    btc_close = details.get("btc_close")
    rsi = details.get("rsi_btc_now")
    mfi = details.get("mfi_btc_now")
    vz = details.get("vol_z_now")
    oi = details.get("oi_change_1h_pct")
    fund = details.get("funding_rate_8h", 0) * 100  # to %
    eth_rsi = details.get("eth_rsi_now")
    xrp_mfi = details.get("xrp_mfi_now")
    corr = details.get("btc_eth_corr_30h")

    return (
        f"{emoji} {title}\n"
        f"\n"
        f"BTC: ${btc_close:,.0f}  RSI={rsi}  MFI={mfi}  vol_z={vz}\n"
        f"OI 1h: {oi:+.2f}%  funding 8h: {fund:+.4f}%\n"
        f"ETH RSI: {eth_rsi}  XRP MFI: {xrp_mfi}  corr={corr}\n"
        f"\n"
        f"Сигналы: {', '.join(triggered) if triggered else 'нет'}\n"
        f"\n"
        f"{action}\n"
        f"Это рекомендация — бот не торгует, решение оператора."
    )


def _check_cooldown(direction: str, dedup: dict, now: datetime) -> bool:
    last = dedup.get(direction)
    if not last:
        return True
    try:
        last_ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
        return (now - last_ts).total_seconds() >= COOLDOWN_SEC
    except (ValueError, AttributeError):
        return True


async def grid_coordinator_loop(stop_event: asyncio.Event, *, send_fn=None,
                                 interval_sec: int = POLL_INTERVAL_SEC) -> None:
    """Async loop. Every 5 min: проверка истощения движения для grid-ботов."""
    if send_fn is None:
        logger.warning("grid_coordinator.no_send_fn — alerts только в журнале")
    logger.info(
        "grid_coordinator.start interval=%ds threshold=3/5 cooldown=%ds",
        interval_sec, COOLDOWN_SEC,
    )

    while not stop_event.is_set():
        try:
            from core.data_loader import load_klines
            btc = load_klines(symbol="BTCUSDT", timeframe="1h", limit=50)
            eth = load_klines(symbol="ETHUSDT", timeframe="1h", limit=50)
            try:
                xrp = load_klines(symbol="XRPUSDT", timeframe="1h", limit=50)
            except Exception:
                xrp = None  # gracefully degrade if XRP fetch fails
            deriv = _read_deriv()
            now = datetime.now(timezone.utc)

            ev = evaluate_exhaustion(btc, eth, deriv, xrp=xrp)
            up = ev["upside_score"]
            down = ev["downside_score"]
            details = ev["details"]

            dedup = _load_dedup()
            fired = False

            # ── Bottom-exhaustion (ревью Вина): на ЭКСТРЕМЕ инвертируем «86% вниз»
            # в «выдыхается». Гасит противоречивую down-карточку в тот же тик, чтобы
            # трейдер на дне не получал два встречных сигнала.
            bx = evaluate_bottom_exhaustion(details, now)
            suppress_down = False
            if bx.get("fired"):
                suppress_down = True
                if _check_cooldown("bottom_ex", dedup, now):
                    card = _format_exhaustion_card(bx)
                    logger.info("grid_coordinator.BOTTOM_EXHAUSTION confirms=%d rsi=%s mfi=%s",
                                bx["confirms"], bx["rsi"], bx["mfi"])
                    if send_fn:
                        try:
                            send_fn(card)
                        except Exception:
                            logger.exception("grid_coordinator.exhaustion_send_failed")
                    dedup["bottom_ex"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                    _journal({"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "direction": "bottom_exhaustion", "confirms": bx["confirms"],
                              "details": details})
                    _save_dedup(dedup)

            # Score-escalation: повторный alert на том же уровне игнорируется
            # на cooldown'е; если score вырос (3→4→5) — alert даже на cooldown.
            # 2026-05-29: reset-on-sub-threshold убран (см. continue ниже) — он
            # давал flicker-дубли при колебании score на грани порога.
            for direction, score in (("up", up), ("down", down)):
                last_score = int(dedup.get(f"{direction}_score") or 0)
                if score < 3:
                    # 2026-06-19 (запрос оператора «понимание что падение остановилось»):
                    # если импульс БЫЛ сильным (≥5) и СХЛОПНУЛСЯ (<3) — пинг «выдохся».
                    # Не прогноз разворота (стена), а реактивное подтверждение, что
                    # импульс закончился = момент, где отскок начался. Один раз на спад.
                    if last_score >= 5 and not dedup.get(f"{direction}_exhausted_for", 0) == last_score:
                        word = "ВНИЗ (падение остановилось)" if direction == "down" else "ВВЕРХ (рост остановился)"
                        px = details.get("btc_close") or details.get("price")
                        msg = (f"🔄 ИМПУЛЬС {word} — выдохся (score {last_score}/6→{score}/6).\n"
                               f"BTC ${px:,.0f}. Реактивное подтверждение, НЕ прогноз: импульс закончился, "
                               f"начался откат. Для гридов: пауза-на-контр-ноге можно снять."
                               if px else
                               f"🔄 ИМПУЛЬС {word} — выдохся (score {last_score}/6→{score}/6).")
                        if send_fn:
                            try:
                                send_fn(msg)
                            except Exception:
                                logger.exception("grid_coordinator.exhausted_send_failed")
                        dedup[f"{direction}_exhausted_for"] = last_score
                        _save_dedup(dedup)
                    # 2026-05-29: do NOT reset last_score on a sub-threshold dip —
                    # that let a boundary oscillation bypass cooldown (see intraday
                    # loop flicker fix). Escalation baseline persists; after cooldown
                    # `_check_cooldown` already permits a fresh fire.
                    continue
                dedup[f"{direction}_exhausted_for"] = 0  # импульс снова активен → сброс
                # На экстреме bottom-exhaustion заменяет «86% вниз» — не шлём оба.
                if direction == "down" and suppress_down:
                    logger.info("grid_coordinator.down_card_suppressed_by_exhaustion score=%d", score)
                    continue
                on_cd = not _check_cooldown(direction, dedup, now)
                # 2026-06-15 (ревью Вина): up-импульс СЛАБЫЙ — НЕ эскалируем на росте
                # score в перекупленность (давал 5× спам в вершину 3→4→5). Эскалация
                # на cooldown'е только для down (реальный эдж: WR 78% PF 10.7).
                if on_cd and (direction == "up" or score <= last_score):
                    continue
                text = _format_card(direction, score, details)
                logger.info("grid_coordinator.%s_EXHAUSTION score=%d (prev=%d)",
                            direction.upper(), score, last_score)
                if send_fn:
                    try:
                        send_fn(text)
                    except Exception:
                        logger.exception("grid_coordinator.send_failed")
                dedup[direction] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                dedup[f"{direction}_score"] = score
                _journal({"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "direction": direction, "score": score, "details": details})
                # Paper-trade. 2026-05-23 audit disabled down→LONG (fade) as a
                # 26% WR / −$77 bleeder. 2026-05-29 backtest (GC_DOWN_DIAGNOSTIC.md)
                # found WHY: down-exhaustion is a CONTINUATION signal, not a
                # reversal — the polarity was inverted. The mirror SHORT is +EV
                # (1h score>=5: WR 78%, PF 10.7 vs 39% unconditional base), so
                # down now emits SHORT (continuation), not LONG (fade).
                # 2026-05-29 (GC_UP_DIAGNOSTIC.md): the UP side mirrors this —
                # also a continuation signal (fade SHORT -EV; LONG beats the
                # bearish-window base, drift positive & rising with score). Edge
                # is WEAK/regime-contingent, but the polarity is clear, so up now
                # emits LONG (continuation) too — flip from the old SHORT fade.
                # Both directions now emit the CONTINUATION trade:
                #   down -> SHORT (price keeps falling), up -> LONG (price keeps rising).
                try:
                    trade_side = "SHORT" if direction == "down" else "LONG"
                    ctx_kind = "continuation"
                    from services.paper_signal_tracker.journal import (
                        read_btc_last_price, record_paper_signal,
                    )
                    last_price = read_btc_last_price()
                    if last_price and last_price > 0:
                        record_paper_signal(
                            source="grid_coord", side=trade_side,
                            entry=float(last_price),
                            stop_pct=-0.5, tp_pct=0.75, hold_h=4,
                            context=f"{direction}_{ctx_kind}_score{score}",
                            now=now,
                        )
                except Exception:
                    logger.exception("grid_coordinator.paper_signal_failed")
                fired = True

            if fired:
                _save_dedup(dedup)
            else:
                logger.debug("grid_coordinator.tick up=%d down=%d (no fire)", up, down)

        except Exception:
            logger.exception("grid_coordinator.tick_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass


# 2026-05-10: 15m intraday-flush detector (downside-only).
# Night research showed 15m TF too noisy for upside (PF -6%), but operator's
# missed extrema (21 Apr 19:46, 29 Apr 18:10) were intraday flushes. Run
# 15m grid_coordinator parallel to 1h, but ONLY emit downside score>=4 alerts.
INTRADAY_DEDUP_PATH = ROOT / "state" / "grid_coordinator_intraday_dedup.json"
INTRADAY_INTERVAL_SEC = 60   # check every 1 min on 15m TF
# 2026-05-13: было 15min cooldown — в живом логе оператора было 17 алертов
# 🔻 НИЗ ИСТОЩАЕТСЯ за 6 часов (≈1 каждые 21 мин). Поднял до 30 мин и
# добавил score-escalation: повторный alert только если счётчик ВЫРОС
# (4→5 или 5→6), а не повторяется на одном уровне.
INTRADAY_COOLDOWN_SEC = 1800
INTRADAY_DOWNSIDE_THRESHOLD = 4


def _load_intraday_dedup() -> dict:
    if not INTRADAY_DEDUP_PATH.exists(): return {}
    try:
        return json.loads(INTRADAY_DEDUP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_intraday_dedup(d: dict) -> None:
    try:
        INTRADAY_DEDUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        INTRADAY_DEDUP_PATH.write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass


async def grid_coordinator_intraday_loop(stop_event, *, send_fn=None,
                                          interval_sec: int = INTRADAY_INTERVAL_SEC) -> None:
    """15m TF parallel loop, downside-only (intraday capitulation lows).

    Different cooldown (15m) and threshold (>=4) than the 1h main loop to
    reduce noise while catching fast flushes the 1h misses.
    """
    logger.info(
        "grid_coordinator.intraday.start interval=%ds tf=15m threshold=down>=%d cooldown=%ds",
        interval_sec, INTRADAY_DOWNSIDE_THRESHOLD, INTRADAY_COOLDOWN_SEC,
    )
    while not stop_event.is_set():
        try:
            from core.data_loader import load_klines
            btc_15m = load_klines(symbol="BTCUSDT", timeframe="15m", limit=60)
            eth_15m = load_klines(symbol="ETHUSDT", timeframe="15m", limit=60)
            try:
                xrp_15m = load_klines(symbol="XRPUSDT", timeframe="15m", limit=60)
            except Exception:
                xrp_15m = None
            deriv = _read_deriv()
            now = datetime.now(timezone.utc)

            ev = evaluate_exhaustion(btc_15m, eth_15m, deriv, xrp=xrp_15m)
            down = ev["downside_score"]
            details = ev["details"]

            dedup = _load_intraday_dedup()
            last = dedup.get("down")
            last_score = int(dedup.get("down_score") or 0)
            on_cooldown = False
            if last:
                try:
                    last_ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
                    on_cooldown = (now - last_ts).total_seconds() < INTRADAY_COOLDOWN_SEC
                except (ValueError, AttributeError):
                    pass

            # Score-escalation + flicker fix (2026-05-29). Within cooldown we fire
            # ONLY on a strict score increase vs the last alert. The old code also
            # reset last_score→0 whenever score dipped below threshold, which let a
            # boundary oscillation (4→3→4 within minutes) bypass cooldown and
            # re-fire — that produced 72 same-score dupes <30min apart in the live
            # journal (the operator's paired cards). Removing that reset is enough:
            # after cooldown expires `not on_cooldown` already permits a fresh fire,
            # so a persistent condition still re-pings every 30 min, but flicker no
            # longer does.
            should_fire = (down >= INTRADAY_DOWNSIDE_THRESHOLD
                           and (not on_cooldown or down > last_score))

            if should_fire:
                text = "⚡ 15m " + _format_card("down", down, details)
                logger.info("grid_coordinator.intraday.DOWNSIDE_FLUSH score=%d (prev=%d)",
                            down, last_score)
                if send_fn:
                    try:
                        send_fn(text)
                    except Exception:
                        logger.exception("grid_coordinator.intraday.send_failed")
                dedup["down"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                dedup["down_score"] = down
                _save_intraday_dedup(dedup)
                _journal({"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "tf": "15m", "direction": "down", "score": down,
                          "details": details})
        except Exception:
            logger.exception("grid_coordinator.intraday.tick_failed")

        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass
