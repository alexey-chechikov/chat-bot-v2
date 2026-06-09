"""Утренний брифинг: BTC-режим + core-боты (из ginarea-tracker) + альт-кандидаты + риск.

Сборка по HANDOFF_ALT_GRID_INTEGRATION_WIN_2026-06-08:
A. режим BTC (цена vs красная TEMA200 4h + vol-off) → действие по core-ботам с уровнем;
B. альт-сканер tools/_alt_grid_scan.py → кандидаты + MegaHard-настройки под 12% + SL±$175;
C. состояние ботов из выгрузки ginarea-tracker (ginarea_live/*.csv, БЕЗ GinArea API —
   одна сессия = одна машина, сессию держит трекер);
D. ассемблер → одна TG-карточка через tv_webhook/tg_notify.

Entry: scripts/morning_card.py (LaunchAgent com.bot7.morning-brief, 08:00 CEST = 09:00 мск).
"""
