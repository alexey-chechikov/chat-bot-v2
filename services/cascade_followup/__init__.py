"""Cascade-followup Phase-D semi-manual emitter.

Параллельная стратегия к Range Hunter. Слушает liquidation cascade события
(те же что cascade_alert), но эмитит actionable TG-карты с inline buttons
[✅ Placed] [⏭ Skip] и трекает outcome через 4h/12h forward returns.

Покрывает варианты где live backtest (state/cascade_backtest_combined.json)
подтверждает edge:
  - SHORT 5BTC: live WR 70.8% / mean +0.331% за 4h  → trade plan LONG (fade)

MEGA / LONG-inverted можно подключать позже после накопления fills.
"""
