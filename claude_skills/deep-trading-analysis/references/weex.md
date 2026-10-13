# Механика WEEX (проверено по коду и API, 09–12.10.2026)

- USDT-линейные фьючерсы, профит в USDT; хедж-режим (LONG и SHORT — отдельные позиции), кросс-маржа.
- Клиент `services/weex_api/client.py`: LIMIT POST_ONLY, MARKET, условные STOP_MARKET (algoOrder, reduceOnly),
  отмена, история ордеров (страницы, окно startTime/endTime — предел окна не записан), userTrades (до 100 за запрос,
  окно ≤7 суток — по docstring клиента). Фандинг по символу — `/capi/v3/account/income` (incomeType
  position_funding; startTime только вместе с endTime) через `client.post`, отдельного метода нет.
- Позиции `/capi/v3/account/position/allPosition` (сырой ответ сверен 12.10): side, size, openValue (средняя =
  openValue/size), cumFundingFee, unrealizePnl, leverage, marginType=CROSSED; закрытая сторона в списке отсутствует.
- Комиссии аккаунта: мейкер 0.016% (замер по исполнениям сеток), тейкер 0.048% (ставка, исполнениями не
  замерен). Бонус возвращает 100% комиссии API (пока действует); «эффективный тейкер 1 б.п.» — предложение
  партнёра, не подтверждено выплатой. В расчётах — gross.
- Лимиты (публичный exchangeInfo, rateLimits, 12.10): REQUEST_WEIGHT 500 за 10 минут, ORDERS 300 в минуту.
  Публичный websocket `wss://ws-contract.weex.com/v3/ws/public` (depth15, trade; снимок при подписке, изменения ~0.5 с).
- Шаги: BTC qty 0.0001, tick 0.1; ETH qty 0.001, tick 0.01; XRP qty 10, tick 0.0001; XAU qty 0.001, tick 0.01.
- Демо (`/capi/v3/sim/order`, символ BTCSUSDT) — отдельный рынок без отмены ордеров, для замеров не годится.
- Правила площадки: быстрые открытия/закрытия и HFT — признаки «аномальной торговли»; VIP8 требует не-API объём.
- Свои ордера бота — clientOrderId с префиксом `b7g` (сетки) / `b7t` (тренд); ручные ордера оператора — UUID
  (веб/приложение, в т.ч. его TAKE_PROFIT). Бот их не трогает, но одинаковые контракты одной стороны биржа по
  владельцу не различает. Кто закрыл позицию — `user_trades` → `order_info(orderId).clientOrderId`.
