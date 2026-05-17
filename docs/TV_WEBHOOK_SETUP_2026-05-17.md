# TradingView Webhook → bot7 — Setup Guide

Endpoint: `POST /tv/<TOKEN>/alert` on port 8770 (local). Pine alerts on TV
side fire JSON body → bot persists to `state/tv_alerts.jsonl` + (future)
triggers `bot_brain` rules.

## 1. Локальный сервер запущен ✅

`services/tv_webhook/server.py` уже подключён в `app_runner.py`. После
restart смотри в `logs/app.log`:
```
tv_webhook.start port=8770 endpoint=/tv/<token>/alert
```

### Token

Сгенерён автоматически на первом старте и сохранён в:
```
/Users/alexeychechikov/code/bot7/state/tv_webhook_token.txt
```

**Этот файл gitignored** — никогда не коммитится. Если потеряешь — удали и
restart, сгенерится новый (старые TV alerts с тем token перестанут работать,
вернут 403).

Команда показать твой текущий token:
```bash
cat /Users/alexeychechikov/code/bot7/state/tv_webhook_token.txt
```

## 2. Tunnel для публичного доступа

TradingView с своих серверов должна попадать на наш Mac. Нужен туннель.

### Option A: cloudflared (рекомендуется — постоянный URL)

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8770
```

Получишь URL вида `https://random-name.trycloudflare.com`. **Запиши его** —
вставлять в TradingView alert URL поле.

Чтобы URL не менялся при перезапуске → авторизация в Cloudflare + named tunnel:
```bash
cloudflared tunnel login
cloudflared tunnel create bot7-tv
cloudflared tunnel route dns bot7-tv tv.your-domain.com
cloudflared tunnel run bot7-tv
```

### Option B: ngrok (ephemeral URL, проще)

```bash
brew install --cask ngrok
ngrok config add-authtoken <your-ngrok-token>
ngrok http 8770
```

URL вида `https://abcd-1234.ngrok-free.app` — меняется при каждом перезапуске.
Free тариф достаточен.

## 3. Pine script — пример alert

В TV → Pine Editor → создать новый скрипт. Базовый шаблон CVD-divergence alert:

```pine
//@version=6
indicator("bot7 CVD divergence (1m)", overlay=false)

// Compute CVD from per-bar buy/sell volume proxy
delta = volume * (close > open ? 1 : -1)
cvd = ta.cum(delta)
plot(cvd, "CVD", color.blue)

// Detect divergence over last 60 bars
lookback = 60
price_high = ta.highest(close, lookback)
price_low = ta.lowest(close, lookback)
cvd_high = ta.highest(cvd, lookback)
cvd_low = ta.lowest(cvd, lookback)

// Bearish divergence: price made new high, CVD didn't
bearish_div = close >= price_high * 0.999 and cvd < cvd_high * 0.995
// Bullish divergence: price made new low, CVD didn't
bullish_div = close <= price_low * 1.001 and cvd > cvd_low * 1.005

plotshape(bearish_div, "Bear Div", color=color.red, location=location.top)
plotshape(bullish_div, "Bull Div", color=color.green, location=location.bottom)

alertcondition(bearish_div, "CVD Bearish Divergence", "bearish_div")
alertcondition(bullish_div, "CVD Bullish Divergence", "bullish_div")
```

### Создание Alert

1. Apply script на BTCUSDT 1m chart
2. Right-click → "Add Alert"
3. Condition: выбрать `CVD Bearish Divergence` (или Bullish)
4. Frequency: `Once Per Bar Close`
5. Webhook URL: вставь свой tunnel URL + path:
   ```
   https://YOUR-TUNNEL/tv/N_OEuAl53g5t1MBV3g0TXxmr5C7xOuDC3hsHkK3A70Y/alert
   ```
6. Message (JSON body):
   ```json
   {"ticker":"{{ticker}}","indicator":"cvd_divergence","direction":"bearish","price":{{close}},"timeframe":"1m","ts":"{{time}}"}
   ```
   Для bullish: `"direction":"bullish"` + другой alertcondition.

7. Save Alert.

### Test alert delivery

Когда условие сработает на TV — alert POSTит JSON на наш endpoint. Проверь:
```bash
tail -5 /Users/alexeychechikov/code/bot7/state/tv_alerts.jsonl
```
Должна появиться новая строка с `payload.indicator = "cvd_divergence"`.

## 4. Что дальше после первого Pine script

После того как этот flow работает, можно добавлять:
1. **BTC.D regime monitor** — Pine на BTC.D chart, alert при крупных move'ах
2. **Anchored VPVR alert** — Pine с проверкой touch'а POC/VAH/VAL на сессионном VPVR
3. **Multi-symbol screener** — Pine + watchlist для одновременного отслеживания
   BTC/ETH/XRP/SOL setups
4. **Funding heatmap** — если есть Premium tier
5. **Order Flow Footprint** — Pro+ tier $$/мес, footprint absorption alerts

В bot_brain потом добавляется R1.7-tv-confirmed: liq_cluster + recent TV alert
of opposite-CVD-divergence (per RESEARCH_cvd_divergence_2026-05-17 — +13 пп
edge). Сейчас blocked на запуск Pine + tunnel.

## 5. Безопасность

- **Token-auth обязателен**: без правильного token /tv/<wrong>/alert → 403
- **rate-limit**: TV throttles ~5/sec на свою сторону, дополнительно не лимитим
- **Payload size**: max 16KB, больше — 413
- **Tunnel** должен быть HTTPS (cloudflared / ngrok дают по умолчанию)
- Token хранится в **state/tv_webhook_token.txt** (gitignored, perms 0600)
- Если token утёк — удалить файл, restart, обновить URL во всех TV alerts

## 6. Troubleshooting

- **403 в логах**: неправильный token в TV URL. Сверь со `cat state/tv_webhook_token.txt`
- **413**: TV прислала слишком большое сообщение — обрежь Pine message
- **Connection refused**: туннель не работает или порт 8770 занят
- **Nothing in tv_alerts.jsonl**: webhook не дошёл — проверь tunnel URL accessible
  с внешнего узла (`curl -v https://tunnel/health` должен дать 200)
