# TradingView alerts — spec to configure (2026-05-29)

Our webhook ingests typed signals, **paper-tracks every one** (source=`tv_<type>`,
resolved per-symbol) and gates the TG card by the PnL-aware `paper_wr_gate`. So:
the more (valid) alerts TV sends, the faster we learn which type actually has edge —
losers auto-mute, winners stay. Configure the alerts below.

## Endpoint
```
POST  http://<bot-host>:8770/tv/<TOKEN>/alert
Content-Type: application/json
```
Token is in `state/tv_webhook_token.txt`. Put the URL in the TradingView alert
"Webhook URL" field; put the JSON below in the alert **Message** field.

## Required payload fields
| field | meaning | example |
|---|---|---|
| `signal_type` | one of the types below (exact string) | `squeeze_breakout_up` |
| `ticker` | instrument | `{{ticker}}` → `BTCUSDT` / `ETHUSDT` / `XRPUSDT` |
| `price` | entry price (paper entry) | `{{close}}` |
| `timeframe` | chart TF in minutes | `{{interval}}` → `25` / `60` |
| `direction` | `bullish`/`bearish` (when applicable) | `bullish` |
| `liq_side` | `LONGS`/`SHORTS` (liq_cascade only) | `SHORTS` |

`direction` overrides the type's inherent side; for one-directional types
(squeeze_up, bos_bullish…) it can be omitted.

## Signal types to enable (exact `signal_type` strings)

| signal_type | side | tickers | timeframes |
|---|---|---|---|
| `squeeze_breakout_up` | LONG | BTC, ETH, XRP | 25, 60 |
| `squeeze_breakout_down` | SHORT | BTC, ETH, XRP | 25, 60 |
| `bos_bullish` | LONG | BTC, ETH, XRP | 60 |
| `bos_bearish` | SHORT | BTC, ETH, XRP | 60 |
| `vol_rejection` | from `direction` | BTC, ETH, XRP | 60 |
| `exhaustion_top` | SHORT | BTC, ETH, XRP | 25, 60 |
| `exhaustion_bottom` | LONG | BTC, ETH, XRP | 25, 60 |
| `liq_cascade` | from `liq_side` | BTC | 1, 5 |
| `range_boundary` | from `boundary_side` | BTC | 60, 1D |
| `spx_drop` / `spx_pump` | SHORT / LONG BTC | SPX→BTC | 5, 15 |

## Ready-to-paste alert MESSAGE bodies (TradingView)

Squeeze breakout (one alert per direction; set on each ticker & TF):
```json
{"signal_type":"squeeze_breakout_up","ticker":"{{ticker}}","price":{{close}},"timeframe":"{{interval}}"}
```
```json
{"signal_type":"squeeze_breakout_down","ticker":"{{ticker}}","price":{{close}},"timeframe":"{{interval}}"}
```

Break of structure (1h):
```json
{"signal_type":"bos_bullish","ticker":"{{ticker}}","price":{{close}},"timeframe":"{{interval}}"}
```
```json
{"signal_type":"bos_bearish","ticker":"{{ticker}}","price":{{close}},"timeframe":"{{interval}}"}
```

Volume rejection (direction-driven — set `direction` in each alert):
```json
{"signal_type":"vol_rejection","ticker":"{{ticker}}","price":{{close}},"timeframe":"{{interval}}","direction":"bearish"}
```

Exhaustion (treat as CONTINUATION per our findings, but recorded & measured):
```json
{"signal_type":"exhaustion_top","ticker":"{{ticker}}","price":{{close}},"timeframe":"{{interval}}"}
```
```json
{"signal_type":"exhaustion_bottom","ticker":"{{ticker}}","price":{{close}},"timeframe":"{{interval}}"}
```

Liq cascade (BTC):
```json
{"signal_type":"liq_cascade","ticker":"{{ticker}}","price":{{close}},"timeframe":"{{interval}}","liq_side":"SHORTS"}
```

## How the edge gets measured
Each alert → `record_paper_signal(source="tv_<type>", symbol=ticker, side=…,
stop -0.75% / tp +1.5% / hold 8h)`. After ~20 closed outcomes per (type, side)
the `paper_wr_gate` verdict appears in `state/paper_wr_gate.json`:
- WR≥40% AND PF≥0.9 → keeps emitting to TG
- else → auto-muted (still recorded, so it can recover)

Review which `tv_*` buckets are healthy via the weekly paper-signal report.
Promote the proven ones (e.g. tighten cooldown, raise to PRIMARY) and drop the dead.
