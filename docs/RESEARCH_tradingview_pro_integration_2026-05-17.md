# TradingView Pro/Premium — что можно добавить/улучшить

Обзор capabilities платного TV-аккаунта и **конкретные** интеграции в bot7.
Ranked by trader-value, не по техническому интересу.

## Что у нас есть сейчас (без TV)

| Источник | Что даёт | Ограничения |
|---|---|---|
| Binance REST `data_loader` | 1m OHLCV для BTC/ETH/XRP | задержка ~5-30 сек, no taker breakdown |
| Bybit WS `market_1m.csv` | BTC 1m в реальном времени + volume | только BTC, только Bybit |
| `deriv_live.json` (5-min poll) | funding/OI/taker_buy_pct/LS-ratio | 5-min granularity, no order flow detail |
| `liquidations.csv` (WS) | Bybit+Binance liq events | 2 exchange, not OKX/BitMEX direct |
| `manual_levels.json` | POC/VAH/VAL via local computation | approx VPVR без TV intraday session split |

## TV Pro/Premium капабилити vs bot7 ROI

### 🟢 Highest ROI: TV → bot7 webhook signals

**TV Pro имеет `alert(message, alert.freq_once_per_bar_close)` функцию +
webhook URL поле в alert dialog.** Custom Pine indicator может проверять
сложные condition (например: BTC pierces VAL + RSI div + funding extreme)
и POSTить JSON на наш endpoint:

```
POST http://our-ngrok-url/tv/alert
Content-Type: application/json
{"ticker": "BTCUSDT", "indicator": "smc_liq_sweep", "direction": "long",
 "price": 78400, "entry": 78420, "stop": 78250, "tp": 78900}
```

Эта инфра у нас в backlog (`docs/HANDOFF §4.2 — TV webhook receiver`). С
TV Pro это станет реально полезным:
- Pine v6 на TV side имеет full access to historical/realtime data
- Можно использовать TV's встроенные indicators (которые мы не реплицируем
  локально): proper CVD на trade tape, Order Flow Footprint, Anchored VPVR
  по нашим custom anchor points, etc.
- TV сам считает heavy compute, bot7 только consumes готовый сигнал.

**Действие:** реализовать минимальный HTTP receiver в `services/tv_webhook/` +
ngrok/cloudflared tunnel. Endpoint persistит в `state/tv_alerts.jsonl` для
audit + триггерит bot_brain если signal hi-conf. ~3-4ч работы.

### 🟢 Better CVD (real trade tape, not approximation)

Сейчас CVD строим из `taker_buy_pct` per 5-min snapshot × Bybit-only 1m volume.
**Approximation.** TV Pro:
- Pine `ta.cum` + per-trade aggression flag → **real per-trade CVD** с millisecond precision
- Multi-exchange aggregated CVD (Binance + Coinbase + Bybit on same chart)
- Built-in **CVD Divergence Detector** indicator (free in marketplace)

Из Phase 3.4 research мы уже знаем — CVD opposite-div +12 пп lift. С proper
TV CVD lift может быть выше из-за более чистого signal. Webhook со
сработавшим `CVD divergence + liq_cluster` отдаёт высокоточный edge.

**Действие:** Pine script "liq-cluster confirmer" → fire'ит когда наш bot
detects liq_cluster AND TV CVD has divergence → webhook → R1.7 в bot_brain.

### 🟢 BTC.D / USDT.D / TOTAL2 — regime indicators

TV даёт реалтайм индексы BTC dominance / USDT dominance / TOTAL crypto cap.
Это **leading indicators** для altcoin moves:
- BTC.D rising + price up → BTC sucks liquidity = ETH/XRP lag → grid на alt'ах меньше fills
- USDT.D rising → de-risk-off mode → каскады likely

Сейчас у нас `deriv_live.global.btc_dominance_pct` каждые 5 мин из CG/CMC.
TV даёт это в real-time + интегрирует в Pine alerts.

**Действие:** Pine script "regime monitor" → fire'ит когда BTC.D resyncs (>+0.5%/h)
→ webhook → adjusts bot_brain confidence scores (например R3 vol-high resize
triggers more aggressively when BTC.D spikes).

### 🟡 Anchored VPVR (more accurate volume profile)

Local volume_profile (`services/volume_nodes.py`) считает 24h rolling VPVR.
TV даёт:
- **Anchored VPVR** на event start (e.g. ATH, прошлый каскад, FOMC date)
- **Session VPVR** (Asia/EU/NY separately)
- **Fixed Range VPVR** на ручной диапазон

Range Hunter уже использует VAL/VAH для snap'а — proper TV VPVR может
ulучшить snap quality + дать **session-specific levels** (например:
"Asia low = strong support, NY break of это = caps move").

**Действие:** TG-bridge для TV-Pine VPVR alerts (мы уже имеем `manual_levels.json`
TV-bridge на основе TG-сообщений — расширить чтобы accept TV webhook
format напрямую).

### 🟡 Order Flow Footprint (TV Premium $$$/мес)

Real bid/ask volume at each price level. Aggressive market orders highlighted.
- **Absorption** (большой market order на цене не двинул цену = strong support/resistance)
- **Imbalance** (95%+ on one side = exhaustion signal)
- **Delta divergence** (footprint показывает CVD per bar)

Это **professional** уровень info которой у нас вообще нет. Каждый
absorption event на VAL/VAH = high-conviction setup.

**Минус**: Premium тариф (~$60/мес). Зато data feed которую мы реплицировать
не можем — единственный access к BitMEX/CME footprint depth via TV.

**Действие:** Если accept стоимость — Pine script "absorption alert at VAL/VAH"
+ webhook → R1.8 (absorption confirms reversal signals).

### 🟡 Bar Replay для backtest (Pro feature)

TV Pro имеет **Bar Replay** mode — можно скроллить historical bars вперёд и
видеть как Pine indicator реагирует tick-by-tick. Для нашей R&D — позволяет
**визуально** валидировать pre-cascade signals на specific dates (например
2024 cascade events).

Сейчас мы делаем "path-aware backtest" в Python — это правильно для метрик,
но визуальная проверка отдельных fires в TV полезна для качественного
sanity-check ("когда правило сработало, было ли это очевидно?").

**Действие:** при анализе false positives R1.5/R1.6 в pause_audit — копировать
timestamps в TV chart, визуально посмотреть что было.

### 🔴 Smart Money Concepts (SMC) indicators

ICT/SMC community indicators (liquidity sweeps, FVG, Order Blocks, BoS, ChoCh)
популярны в crypto trading. На TV много free Pine implementations.

Honest assessment: SMC mostly **subjective pattern recognition** без чёткого
statistical edge. Скорее окно overlay для оператора, не algorithmic signal.

**Действие:** низкий приоритет. Может быть useful если ты лично хочешь TV-chart
overlay для manual trade decisions, но **не для bot7 integration**.

### 🔴 CME COT data, options open interest, gamma exposure

Polymarket / Deribit options ladder, gamma walls, put/call ratio. Доступно на
TV Premium. Влияет на **macro** moves (e.g. monthly expiry = strong magnets),
но крайне medium-frequency для нашего intraday grid/pre-cascade work.

**Действие:** low priority unless we move to swing-trading.

## Ranked recommendation

1. **TV webhook receiver** (~3-4ч) — открывает все Pine-based integrations,
   blocker для остального
2. **Pine "liq-cluster confirmer with proper CVD"** (~2ч после #1) — boost
   R1.5/R1.6 precision через real CVD
3. **Pine "BTC.D regime monitor"** (~1-2ч) — feeds bot_brain confidence
4. **Pine "VPVR session levels"** (~2ч) — replaces our local volume_profile
   с TV-quality data
5. **Absorption/Footprint** — **только если апгрейд до Premium**
6. **Bar Replay** — для R&D sanity-check, не code work

## Action plan

Sequence (~10-12 часов суммарно):
1. Реализовать `services/tv_webhook/` — Flask или aiohttp endpoint, JWT-auth,
   persist в `state/tv_alerts.jsonl`, wire в `bot_brain.executor` как новый
   входной сигнал.
2. ngrok/cloudflared tunnel настройка (один раз) + sticky URL.
3. Написать первый Pine script ("liq_cluster_confirmer.pine") + опробовать
   alert → webhook flow.
4. Iterate — добавлять Pine scripts по выявленным edges.

После #1 multimedia integration становится bandwidth-bound (каждый новый Pine
скрипт — ~1-2ч).

## Caveats / риски

- **TV Pine vendor lock-in**: если TV меняет API/Pine версии — нужно переписывать.
- **Latency**: webhook → tunnel → bot7 имеет ~100-500ms задержку. Для intraday
  pre-cascade signal'ов (lead-time 10-30 мин) это норм. Для scalping — нет.
- **Rate limits**: TV throttles alerts ~5/sec. Не подходит для high-freq signals
  (но наши liq_cluster fires ~7-10/день — far below limit).
- **Cost**: Pro ~$15/мес, Pro+ ~$30, Premium ~$60. ROI зависит от того
  сколько edges actually surface; первые 2-3 integrations нужны до явного payback.
