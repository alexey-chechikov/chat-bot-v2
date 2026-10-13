"""НЕ ЗАПУСКАЕТСЯ ни одной службой (проверено 13.10.2026). Живой сбор ликвидаций — market_collector/liquidations.py
(launchd com.bot7.market-collector). Парсеры здесь — старые: Bybit ждёт updateTime/symbol/side/size/price вместо
документированных T/s/S/v/p, OKX считает sz×bkPx без ctVal, Hyperliquid ждёт несуществующий флаг liquidation
(разбор GPT docs/ATLAS_DATA_PARSER_REPRO_2026-10-13.zip). Использовать нельзя; оставлено ради
tests/test_collectors_parsers.py и scripts/smoke_collectors.py до решения об удалении."""
