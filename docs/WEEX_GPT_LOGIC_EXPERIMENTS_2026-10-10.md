# WEEX: торговая логика и первые причинные эксперименты — 10.10.2026

Это продолжение предложений по торговой логике, отдельно от проверки operational-дефектов. Кодовая основа численного A/B — [9cc641e8](https://github.com/alexey-chechikov/chat-bot-v2/commit/9cc641e8e0c6746eefe1a6e1440a233f1f9041d1). При финальной проверке ветки уже опубликован [3173dfb](https://github.com/alexey-chechikov/chat-bot-v2/commit/3173dfbe9cc0e5d4fa137a9065db6540e0361041) с очередными исправлениями надёжности. `fast_grid.py` в нём совпадает с9cc по Git blob SHA; торговые выходы всё ещё POST_ONLY, а `post_only=False` в adapter всё ещё GTC. Полная перепроверка operational-исправлений3173 не является предметом этого эксперимента. Рабочие торговые правила и код бота этой работой не менялись.

## Статус семи предложений

По [ответам автора](https://github.com/alexey-chechikov/chat-bot-v2/blob/9cc641e8e0c6746eefe1a6e1440a233f1f9041d1/docs/WEEX_GPT_REVIEW2_ANSWERS_2026-10-10.md), реализованы parent-slots: один исходный order считается одним economic slot независимо от числа partial fills. Это проверено на новом движке; денежный риск остаётся отдельным ограничением. Прирост ожидания за счёт этого не измерен.

Пройденный TP, persistent refill tickets, общий резерв риска после TP, возраст/дистанция/occupied-hours/funding, разные цели сторон и сбор исполнения пока не реализованы как торговые изменения. Ниже — новый A/B и конкретная спецификация следующего экономического эксперимента.

## 1. Новые входы при уже существующем inventory: проверено A/B

Данные: ранее использованные218880 минут Binance futures BTCUSDT, 07.05–05.10.2026. Параметры заранее оставлены исходными: q=.0012, step=.2%, target=.21%, cap=$4000/сторону, max50, maker=.016%/исполнение. Очередь WEEX, funding, rebate и проскальзывание отсутствуют; нового OOS здесь нет.

Срезы выбраны по25/50/75% длины данных. На каждом срезе копируется одно и то же непрерывное состояние и используется одна конечная цена:

- A: старые TP и все новые entry продолжаются.
- B: старые TP продолжаются, новые entry после среза запрещены.

PnL второй части начинается с mark последней минуты до среза. Старым лотам не приписывается повторно доход от исходного entry. В этой модели old-TP фиксированы и одинаковы; проверено, что A−B точно равен закрытой прибыли новых лотов плюс их конечному мешку минус их комиссии.

| Срез UTC,00:00 | A: PnL после среза | B: только старые TP | Вклад новых лотов A−B |
|---|---:|---:|---:|
| 14.06.2026 | −$86.58 | +$886.80 | **−$973.38** |
| 22.07.2026 | −$172.49 | −$187.59 | **+$15.10** |
| 29.08.2026 | −$177.78 | −$391.80 | **+$214.02** |

Это результат только после соответствующего среза, не отдельная доходность стратегии за всю историю. В Варшаве каждый срез приходится на02:00 того же дня.

Базовая инструментированная модель точно совпала с текущей `fast_grid`:6179TP и **−$563.71030765** за все152дня. В первой ветке после14июня новые лоты дали примерно+$626.30 gross закрыто, но конечный новый мешок−$1503.49 и новые fees≈$96.19 — полный вклад **−$973.38**. Тысячи прибыльных кругов не сделали эти новые входы выгодными на данном отрезке.

**Вывод для изменения логики:** простое постоянное выключение новых входов не проходит как универсальное улучшение: первая пауза помогла, две другие потеряли прибыль. Отдельный entry-admission можно исследовать по состоянию inventory и его денежной стоимости, но его критерий требуется зафиксировать на старом блоке и проверить на новом. Из этих трёх дат нельзя выбирать14июня и объявлять рабочий сигнал.

Пауза не закрывает старый риск: в B после июльского среза на конце осталось38SHORT-лотов, после августовского50. A и B не имеют одинаковой последующей экспозиции; это реальное следствие разрешения новых входов. Для выбора admission нужно дополнительно сравнение с меньшим постоянным размером и случайными непрерывными паузами той же загрузки. Срезы пересекаются и не являются тремя независимыми торговыми выборками.

## 2. Первый конкретный кандидат: фиксация пройденного TP

Текущее правило переносит пересекающий стакан TP к best ask/bid ради POST_ONLY. Потом цена нового ордера остаётся прежней, хотя исходная чистая цель ещё достижима.

Воспроизведено на текущем Grid: entry100,target.3%,TP100.3; poll100.99/101.01 ставитSELL101.01. Возврат bid100.49 не закрывает лот. Затем mid99 даёт−1.016 с входной fee. При **условной**, не проверенной для аккаунта taker fee.05% немедленный выход100.99 дал бы+.923505, выход100.49+.423755. Исходный maker-net TP был+.267952. Это контрпример механизма; частота и средний эффект неизвестны.

Сравнить три отдельные политики: текущий maker-only, passive repricing исходного TP и ограниченный reduceOnly LIMIT IOC. Входная политика сохраняется, новые входы после высвобождения cap входят в полный экономический результат.

При исходном округлённом maker-TP Pm и комиссиях выхода fm/ft условие сохранения его net-цели:

- LONG: `p_exec >= Pm*(1-fm)/(1-ft)`; SELL limit округлить вверх по tick.
- SHORT: `p_exec <= Pm*(1+fm)/(1+ft)`; BUY limit округлить вниз.

Entry fee одинаковая для сравниваемого остатка и сокращается. Это сравнение с net исходного maker-выхода, а не обещание окупить уже накопленный funding всем циклом. Ledger исходных/поздних fees и funding всё равно нужен.

Для entry100,target.3%, **условных** fm=.00016 и ft=.0005:

| Сторона | Исходный TP | Net maker q1 | Порог IOC | Тик.01 |
|---|---:|---:|---:|---:|
| LONG |100.3|+.267952|100.334119|SELL limit100.34|
| SHORT |99.7|+.268048|99.666119|BUY limit99.66|

Нельзя просто заменить `post_only=True` наFalse: нынешний adapter передаётGTC, а неIOC. Нужен явный timeInForce. [Официальный WEEX Trade API](https://www.weex.com/api-doc/catalog/core-trading-futures/api/rest-api/transaction-api) поддерживает LIMIT IOC и reduceOnly, но это не гарантия полного исполнения.

Перед заменой: устойчиво записать transition, подтвердить terminal старого TP, принять поздние fills/fees, обновить исполнимую котировку и remaining qty, затем проверить threshold заново. Не ставить новый выход параллельно с неизвестным старым. Остаток после одного IOC возвращается в maker-политику.

Для первого shadow-эксперимента предлагаются заранее фиксируемые параметры: quote age≤1с, видимая глубина на допустимых ценах≥2×remaining, один IOC/episode. Это гипотезы для sensitivity, не измеренные оптимальные значения. IOC limit должен сохранять чистую цель на худшей допустимой цене; optimistic best bid/ask не заменяет фактический fill.

Оценка: полный PnL с конечным inventory и всеми расходами, доход/occupied-hours, event DD, распределение fill/неналива и request/cancel latency. Контроли — maker-only и passive repricing; дополнительно одинаковое число replacements в сопоставимых spread/depth условиях. Заранее заданные критерии отказа: свежий fullPnL не лучше контроля и CI включает0; преимущество исчезает при наблюдаемойp95 задержке/консервативной очереди; event DD или occupied-hours хуже>10% без подтверждённого улучшения fullPnL. Последний10% — proposed risk gate, не результат исследования.

Нужны WEEX quote/depth/order lifecycle и фактические тарифы. [Market API](https://www.weex.com/api-doc/catalog/core-trading-futures/api/rest-api/market-api) предоставляет matching-engine timestamps, bid/ask quantities и depth. 152дня Binance OHLC этого исполнения не проверяют.

## 3. Следующий допуск входа: цена старой позиции

Сначала только измерение: возраст всех лотов, distance доTP, occupied-notional-hours, net/gross, часы cap-blocked и реальные settlement fees/funding. Закрытые и всё ещё открытые лоты учитывать вместе, с цензурированием. Предыдущая диагностика показала median закрытых26мин против oldest open≈97дней и distance≈32.6%; среднее только по успешным TP вводит в заблуждение.

Затем отдельно исследовать правило разрешения нового inventory по общему денежному/стресс-бюджету и стоимости удержания. Это не предсказатель направления и не принудительный time-stop. Из A/B выше не следует, что любая пауза полезна; такое admission обязано быть лучше простого меньшего размера при сопоставимых risk/load и пройти новую историю. Доказанного порога age/distance в этой работе нет.

## Уточнение предыдущего аргумента про refill

Старый пример100/99 при step.2% показывает разреженную книгу с разрывом примерно5шагов. Он не доказывает типичный быстрый повторный набор. Для соседних100/99.8 и target.3% нижнийTP100.0994; после его исполнения новый desired99.8 остаётся ниже рынка. Поэтому persistent tickets остаются отдельной гипотезой для полного replay, а изменение обычного refill пока не имеет подтверждённого преимущества. Более сильный непосредственный пример относится к пройденному maker-TP, описанному выше.

## Практический порядок

Отдельно завершить проверку опубликованных operational-исправлений3173, чтобы сравнение было достоверным. Для торговой логики — trace age/net/gross/funding и shadow сравнение трёх exit-policy. Затем отдельно inventory-admission с matched-state A/B и контролем загрузки. Разные цели сторон и persistent refill требуют самостоятельных временных проверок; брать лучшие ячейки из старой таблицы нельзя считать доказанным улучшением.

Реализованный parent-slot исправляет зависимость лимита от fragmentation. Предложенный hybrid выход конкретен и проверяем, его прибыльность не измерена. Новый A/B уже опровергает универсальное правило «запретить все новые входы при старом мешке». Подтверждённого положительного матожидания нового торгового правила пока нет.

## Воспроизводимость

Числа, скрипты и подробная exit-спецификация включены ниже в GitHub-пакет. Для A/B требуется исходный minute CSV с опубликованным SHA256; путь адаптируется к своему checkout. Snapshot — код9cc641e8. Локальные live keys/state не нужны.


---

# Подробная спецификация выхода

# Минимальный эксперимент: фиксация уже пройденного тейка

Дата: 2026-10-10. Основа: current snapshot `C:\bot7\research\weex_review2_20261010\snapshot`, [commit 9cc641e8e0c6746eefe1a6e1440a233f1f9041d1](https://github.com/alexey-chechikov/chat-bot-v2/commit/9cc641e8e0c6746eefe1a6e1440a233f1f9041d1). Все проверки ниже офлайн, без ключей и без отправки ордеров. Это спецификация торгового эксперимента, не обещание увеличения матожидания.

**Идея:** Входы сохранить maker; при уже достижимой чистой цели сравнить три политики выхода: текущий неподвижный maker, осторожное passive repricing и ограниченный reduce-only LIMIT IOC.

**Механизм:** Обычный maker-выход после резкого движения может оказаться выше/ниже исходной цели и зависнуть при возврате. Hybrid фиксирует уже доступную прибыль, оплачивая taker-тариф лишь если цена компенсирует его относительно исходного maker-TP. Passive repricing возвращает завышенный выход к текущему стакану; экономит комиссию, но теряет очередь и не гарантирует исполнение. Контрагент платит текущую рыночную цену; нового directional edge это правило не создаёт.

**Отличие от опровергнутого:** Ближе всего строка §3 «Лимитки вместо маркета»: её нельзя игнорировать из-за adverse selection. Здесь вход, сигнал, сторона, размер и исходная цель одинаковы; меняется исполнение уже заработанного выхода. Налив и неналив учитываются честно; нельзя считать одно касание maker-цены исполнением.

**Тест на наших данных:** Сначала timestamped WEEX quotes/depth/trades + полный жизненный цикл ордеров, cancel/request/response timestamps, fills/maker flags, фактические комиссии и funding. Quote data само по себе недостаточно для определения maker-очереди. Заранее зафиксировать параметры; старый/средний/свежий период по §4, свежий отдельно с полного state и с нуля. Текущий maker — контроль; passive repricing — отдельная абляция; IOC-only trigger — отдельная абляция. Для плацебо одинаковую частоту replacements/IOC применить к случайным доступным событиям с совпадающими spread, depth и net-buffer. Полный PnL с мешком, fees, funding, подтверждённым cashback; equity-DD по всем событиям, occupied-dollar-hours, захват чистой цели и фактическая цена fill. Парные варианты с одинаковым состоянием и входной политикой; новые входы после освобождения лимита входят в полный итог. Месячный bootstrap, ≥100 независимых/кластерно учитываемых exit-эпизодов, доверительный интервал преимущества исключает ноль, соседние параметры устойчивы. Сначала simulation/trace и demo-контроль; live-сверка требует отдельно разрешённой оператором фазы.

**Ожидаемый эффект:** Порядок среднего эффекта неизвестен без исполнения. Синтетический контрпример LONG q1: entry100, TP100.3; исходный net maker-TP +0.267952. Poll100.99/101.01 ставит101.01, возврат bid100.49 не закрывает, затем mid99 даёт −1.016 с входной комиссией. IOC по100.99 при условной taker.0005 дал бы +0.923505; по100.49 +0.423755. Это доказательство механизма потери доступного выхода, а не частоты или ожидаемого прироста PnL.

**Критерий отказа:** (1) После ≥100 эпизодов и временного разреза свежий полный PnL хуже контроля либо 95% CI преимущества включает0 — политика не проходит. (2) Преимущество исчезает при p95 наблюдаемой задержке + консервативной maker-очереди/частичном IOC + фактических тарифах и funding — отказ. (3) Максимальная event-equity просадка или занятый капитал×время хуже контроля >10% без статистически подтверждённого улучшения полного PnL — откат к baseline. Порог10% — предложенный заранее risk gate, не результат исследования. Не ждать100эпизодов при любом нарушении qty/fee accounting: остановить эксперимент и исправить измерение.

**Реализация:** Отдельный параметр exit_policy со старым maker baseline по умолчанию. Сохраняемый replacement-state с original_net_target, old/new orderId, remaining_qty и pending. До отмены записать переход, подтвердить terminal старого ордера, принять поздние fills/fees, заново прочитать свежий стакан, посчитать оставшееся количество и проверить достижимость; только затем IOC либо новый maker. Не отправлять новый выход пока прежний исход неизвестен. Сложность средняя; существующий `post_only=False` выдаёт GTC, а не IOC, поэтому нужен явный `time_in_force` в research adapter.

**Главный риск:** IOC не гарантирует полный fill; стакан устаревает между решением и запросом, passive replacement теряет очередь, новые входы после быстрого освобождения капитала могут увеличить мешок. Даже правильный выход не устраняет трендовый tail risk сетки.

## Точное условие и консервативный лимит

Обозначения: Pm — исходная цена maker-TP после округления, fm — ожидаемая фактическая maker-комиссия выхода, ft — консервативная taker-комиссия выхода. Entry fee одинаковая в сравниваемых вариантах и сокращается; funding до решения также одинаковый. Не вычитать неподтверждённый cashback. В абсолютном original_net_target всё равно хранить entry fee и уже накопленный funding для прозрачности. Funding будущего ожидания нельзя выдавать за гарантированный выигрыш.

- LONG: `p_exec*(1-ft) >= Pm*(1-fm)`. Минимальный допустимый SELL IOC limit — `ceil_tick(Pm*(1-fm)/(1-ft))`.
- SHORT: `p_exec*(1+ft) <= Pm*(1+fm)`. Максимальный допустимый BUY IOC limit — `floor_tick(Pm*(1+fm)/(1+ft))`.

Entry100, target0.3%, условные fm0.00016 и ft0.0005:

| Сторона | Исходный TP | Net maker-TP q1 | Предельная цена IOC | При тике0.01 |
|---|---:|---:|---:|---:|
| LONG |100.3|+0.267952|100.3341190595|SELL limit100.34|
| SHORT |99.7|+0.268048|99.6661189405|BUY limit99.66|

Для конкретного символа использовать его реальный tick/qty-step. IOC разрешается лишь при свежей котировке и достаточном видимом объёме на допустимых ценах. Если цель нужно покрывать на худшей допустимой цене, учитывать именно limit, а не optimistic best bid/ask/VWAP. Первое исследовательское правило: quote age≤1с, подтверждение свежего snapshot после cancel, ≥2×остаток в видимой доступной глубине, один IOC на episode, остаток вернуть в maker по исходной цели с учётом actual fills. Эти ограничения — заранее фиксируемые параметры для sensitivity-проверки, не доказательство безопасности или прибыльности. Если данных/fee нет, оставить baseline.

Passive repricing: LONG новый SELL POST_ONLY `ceil_tick(max(Pm, current_ask))`; SHORT BUY `floor_tick(min(Pm, current_bid))`. На каждом poll ограничить уменьшение/увеличение завышенной цены одним replacement после terminal старого выхода; hysteresis≥1tick, min_interval1poll. Если POST_ONLY reject из-за движения стакана — обновить quote на следующем цикле без market fallback. По примеру101.01→100.51 шанс выхода появляется снова, но при дальнейшем падении до99 fill всё равно не гарантирован.

## Сохранение стоимости и курсоров в текущем коде

`engine.py:566–594`: entry fill записывается отдельным лотом с entry, qty, исходным tp, parent, t; fee уходит в side aggregate и `fee_book[entry_order_id]`, а не в отдельный lot.entry_fee. `596–628`: exit qty/value cursors принадлежат конкретному TP-ордеру, partial уменьшает lot.qty; terminal удаляет tp_order у остатка. Новая заявка получает новые qty/value cursors; переносить cumulative fills старого orderId на новый нельзя. Исходный lot.entry/tp/parent при замене сохраняются. В fee_book остаётся комиссия старого orderId, но текущая часовая уборка курсора — уже выявленный дефект, от которого эксперимент зависит. Для расчёта per-lot net цели нужен ledger allocation входных fees/funding; для сравнительного hurdle того же лота entry-fee algebraically cancels.

## Поправка к прежнему refill-пробнику

Предыдущий `mechanics_probe.ref_reset_at_cap` вручную seeded LONG100 и99 при step0.2%. Это разрыв примерно5шагов; без хронологии он не доказывает типичное заполнение уровней. При соседних100→99.8 и target0.3% нижний TP100.0994; после его исполнения ref100 даёт desired99.8 BELOW рынка. Немедленное смещение к bid здесь не следует. Пример100/99 остаётся возможным контрпримером поведения разреженного inventory после исчезновения промежуточных лотов, но частота и денежный эффект неизвестны. Постоянные tickets — отдельная гипотеза: сравнить полные causal paths с одинаковым cap, steps, risk admission и fees; нельзя объявлять этот refill исправлением или улучшением.

## Что позволяют официальные данные WEEX

[Trade API](https://www.weex.com/api-doc/catalog/core-trading-futures/api/rest-api/transaction-api): LIMIT поддерживает IOC/FOK/GTC/POST_ONLY и reduceOnly. [Market API](https://www.weex.com/api-doc/catalog/core-trading-futures/api/rest-api/market-api): bookTicker содержит matching-engine time и bidQty/askQty; depth даёт цены/количества и updateId. [Account API](https://www.weex.com/api-doc/catalog/core-trading-futures/api/rest-api/account-api) даёт account commission rate. Наличие API не подтверждает тариф данного аккаунта, очередь или исполнение ордера.

152 дня Binance OHLC не содержат WEEX spread/depth, очередь, частичные исполнения, порядок тиков внутри минуты, POST_ONLY-rejections, cancel latency, actualfees/funding. Такой прогон годится для грубого inventory path, но нельзя объявлять им проверенным WEEX hybrid exit. Shadow replay также требует консервативной модели неизмеренных maker fills; окончательная сверка — реальный журнал разрешённой фазы.

Арифметика и текущая fake-exchange трасса: `exit_spec_probe.py`, результат `exit_spec.json`.


## ab_inventory.json

```json
{
  "source": "C:\\bot7\\research\\expectancy_20261006\\public_data\\binance_futures_BTCUSDT_1m.csv",
  "source_sha256": "e10c39164c6111c151b45d8cffce3bfd1cdbe86221e8dbebad02a84c5b0394f2",
  "fast_grid": "C:\\bot7\\research\\weex_review2_20261010\\snapshot\\research\\weex\\fast_grid.py",
  "fast_grid_sha256": "420b2d6b5dd45032a14ce2e4c6f28d66928a1827b90dec2dcc5bbd9193250963",
  "rows": 218880,
  "first_utc": "2026-05-07T00:00:00+00:00",
  "last_bar_utc": "2026-10-05T23:59:00+00:00",
  "end_mark": 85717.2,
  "non_60s_gaps": 0,
  "frozen_config": {
    "order_qty": 0.0012,
    "step": 0.2,
    "target": 0.21,
    "cap_usd": 4000.0,
    "max_orders": 50,
    "fee": 0.00016
  },
  "baseline": {
    "equity": -563.7103076496701,
    "realized_gross": 1109.567591904071,
    "fees": 169.79208861874486,
    "bag": -1503.4858109349962,
    "tps": 6179,
    "entries": 6238,
    "turnover": 1061200.5538671608,
    "lots": {
      "LONG": 9,
      "SHORT": 50
    },
    "qty": {
      "LONG": 0.010800000000000004,
      "SHORT": 0.05999999999999999
    }
  },
  "pinned_fast_grid_result": {
    "тейков": 6179,
    "оборот": 1061200.5538671608,
    "закрыто": 1109.567591904071,
    "комиссии": 169.79208861874486,
    "мешок": -1503.4858109349962,
    "худший мешок": -1590.8179236636581,
    "по сторонам": {
      "LONG": 413.49,
      "SHORT": -977.2
    },
    "итог": -563.7103076496701,
    "просадка капитала": -798.7894413906467,
    "по месяцам": [
      [
        "2026-05",
        -64.22
      ],
      [
        "2026-06",
        -453.59
      ],
      [
        "2026-07",
        166.0
      ],
      [
        "2026-08",
        -38.71
      ],
      [
        "2026-09",
        -110.94
      ],
      [
        "2026-10",
        -62.25
      ]
    ]
  },
  "comparisons": [
    {
      "cut_fraction": 0.25,
      "cut_index": 54720,
      "cut_utc": "2026-06-14T00:00:00+00:00",
      "baseline_mark_utc": "2026-06-13T23:59:00+00:00",
      "baseline_mark_price": 64418.2,
      "inherited_state": {
        "equity": -477.1314227944105,
        "realized_gross": 468.21681122835247,
        "fees": 72.45434268346891,
        "bag": -872.8938913392941,
        "tps": 2633,
        "entries": 2718,
        "turnover": 452839.6417716819,
        "lots": {
          "LONG": 42,
          "SHORT": 43
        },
        "qty": {
          "LONG": 0.05039999999999999,
          "SHORT": 0.05159999999999999
        }
      },
      "A_continuing": {
        "post_cut_net": -86.57888485525956,
        "attribution": {
          "inherited": {
            "realized_from_cut_mark": 887.9479231399773,
            "bag_from_cut_mark": 0.0,
            "fees": 1.1472411704098755,
            "net": 886.8006819695674
          },
          "post_cut_entries": {
            "realized_gross": 626.2967488750307,
            "bag": -1503.4858109349962,
            "fees": 96.1905047648669,
            "net": -973.3795668248323
          }
        }
      },
      "B_no_new_entries": {
        "post_cut_net": 886.8006819695674,
        "attribution": {
          "inherited": {
            "realized_from_cut_mark": 887.9479231399773,
            "bag_from_cut_mark": 0.0,
            "fees": 1.1472411704098755,
            "net": 886.8006819695674
          },
          "post_cut_entries": {
            "realized_gross": 0.0,
            "bag": 0.0,
            "fees": 0.0,
            "net": 0.0
          }
        },
        "end_totals": {
          "equity": 409.6692591751569,
          "realized_gross": 483.2708430290357,
          "fees": 73.60158385387876,
          "bag": 0,
          "tps": 2718,
          "entries": 2718,
          "turnover": 460009.89908674365,
          "lots": {
            "LONG": 0,
            "SHORT": 0
          },
          "qty": {
            "LONG": 6.5052130349130266e-18,
            "SHORT": 6.5052130349130266e-18
          }
        },
        "post_cut_minute_close_drawdown": -233.69975999999997
      },
      "A_minus_B": -973.379566824827,
      "post_cut_new_entries": 3520,
      "post_cut_A_tps": 3546,
      "post_cut_B_tps": 85
    },
    {
      "cut_fraction": 0.5,
      "cut_index": 109440,
      "cut_utc": "2026-07-22T00:00:00+00:00",
      "baseline_mark_utc": "2026-07-21T23:59:00+00:00",
      "baseline_mark_price": 66522.4,
      "inherited_state": {
        "equity": -391.22108036820987,
        "realized_gross": 687.1684293286817,
        "fees": 105.85723448663227,
        "bag": -972.5322752102593,
        "tps": 4042,
        "entries": 4134,
        "turnover": 661607.7155414554,
        "lots": {
          "LONG": 42,
          "SHORT": 50
        },
        "qty": {
          "LONG": 0.05039999999999999,
          "SHORT": 0.05999999999999999
        }
      },
      "A_continuing": {
        "post_cut_net": -172.48922728146022,
        "attribution": {
          "inherited": {
            "realized_from_cut_mark": 688.4723099360866,
            "bag_from_cut_mark": -875.2828800000008,
            "fees": 0.7836199501224983,
            "net": -187.59419001403666
          },
          "post_cut_entries": {
            "realized_gross": 412.12770269200337,
            "bag": -333.87150577743813,
            "fees": 63.15123418198909,
            "net": 15.104962732576148
          }
        }
      },
      "B_no_new_entries": {
        "post_cut_net": -187.59419001403626,
        "attribution": {
          "inherited": {
            "realized_from_cut_mark": 688.4723099360866,
            "bag_from_cut_mark": -875.2828800000008,
            "fees": 0.7836199501224983,
            "net": -187.59419001403666
          },
          "post_cut_entries": {
            "realized_gross": 0.0,
            "bag": 0.0,
            "fees": 0.0,
            "net": 0.0
          }
        },
        "end_totals": {
          "equity": -578.8152703822461,
          "realized_gross": 697.4398892120668,
          "fees": 106.64085443675475,
          "bag": -1169.6143051575582,
          "tps": 4096,
          "entries": 4134,
          "turnover": 666505.3402297212,
          "lots": {
            "LONG": 0,
            "SHORT": 38
          },
          "qty": {
            "LONG": 6.5052130349130266e-18,
            "SHORT": 0.045599999999999995
          }
        },
        "post_cut_minute_close_drawdown": -543.4496410387834
      },
      "A_minus_B": 15.104962732576041,
      "post_cut_new_entries": 2104,
      "post_cut_A_tps": 2137,
      "post_cut_B_tps": 54
    },
    {
      "cut_fraction": 0.75,
      "cut_index": 164160,
      "cut_utc": "2026-08-29T00:00:00+00:00",
      "baseline_mark_utc": "2026-08-28T23:59:00+00:00",
      "baseline_mark_price": 77805.9,
      "inherited_state": {
        "equity": -385.9311903329708,
        "realized_gross": 840.8209039044376,
        "fees": 129.09333296370716,
        "bag": -1097.6587612737012,
        "tps": 4861,
        "entries": 4940,
        "turnover": 806833.3310231825,
        "lots": {
          "LONG": 29,
          "SHORT": 50
        },
        "qty": {
          "LONG": 0.0348,
          "SHORT": 0.05999999999999999
        }
      },
      "A_continuing": {
        "post_cut_net": -177.77911731669928,
        "attribution": {
          "inherited": {
            "realized_from_cut_mark": 83.32559414102475,
            "bag_from_cut_mark": -474.6780000000001,
            "fees": 0.44655534626256393,
            "net": -391.79896120523796
          },
          "post_cut_entries": {
            "realized_gross": 262.8979314686515,
            "bag": -8.625887271338637,
            "fees": 40.252200308773645,
            "net": 214.01984388853924
          }
        }
      },
      "B_no_new_entries": {
        "post_cut_net": -391.7989612052379,
        "attribution": {
          "inherited": {
            "realized_from_cut_mark": 83.32559414102475,
            "bag_from_cut_mark": -474.6780000000001,
            "fees": 0.44655534626256393,
            "net": -391.79896120523796
          },
          "post_cut_entries": {
            "realized_gross": 0.0,
            "bag": 0.0,
            "fees": 0.0,
            "net": 0.0
          }
        },
        "end_totals": {
          "equity": -777.7301515382087,
          "realized_gross": 846.6696604354187,
          "fees": 129.53988830996974,
          "bag": -1494.8599236636576,
          "tps": 4890,
          "entries": 4940,
          "turnover": 809624.3019373235,
          "lots": {
            "LONG": 0,
            "SHORT": 50
          },
          "qty": {
            "LONG": 6.5052130349130266e-18,
            "SHORT": 0.05999999999999999
          }
        },
        "post_cut_minute_close_drawdown": -720.6445210387838
      },
      "A_minus_B": 214.01984388853862,
      "post_cut_new_entries": 1298,
      "post_cut_A_tps": 1318,
      "post_cut_B_tps": 29
    }
  ],
  "limitations": [
    "Binance futures proxy, not WEEX fills or queue.",
    "Previously examined history, not new OOS.",
    "Funding, cash rebate, slippage and taker cost excluded.",
    "OHLC colour path: O-L-H-C on up bars, O-H-L-C on down bars.",
    "Touch fills and one new entry per side per path point are model assumptions.",
    "No cut chosen by profitability; cuts fixed at 25/50/75% bar count.",
    "B cancels hypothetical new-entry opportunities but retains old TPs unchanged.",
    "All old-lot profit is marked from cut price, not historical entry."
  ]
}
```


## exit_spec.json

```json
{
  "scope": "Offline formulas and current 9cc snapshot fake-exchange trace; not WEEX execution or expectation estimate",
  "conditional_rates_not_verified_account_tariff": {
    "maker": "0.00016",
    "taker": "0.0005"
  },
  "unit_qty": 1,
  "baseline_net_long": "0.267952",
  "baseline_net_short": "0.268048",
  "long_ioc_worst_price_floor": "100.3341190595297648824412206",
  "short_ioc_worst_price_ceiling": "99.66611894052973513243378311",
  "tick_001_long_sell_limit": "100.34",
  "tick_001_short_buy_limit": "99.66",
  "long_exit_at_100_99_net": "0.923505",
  "long_exit_at_100_49_net": "0.423755",
  "current_engine_trace": {
    "posted_tp": 101.01,
    "tp_after_bid_100_49": 101.01,
    "open_qty": 1.0,
    "marked_at_mid_99_after_entry_fee": -1.016
  },
  "adjacent_refill_control": {
    "step_pct": 0.2,
    "upper_entry": 100,
    "adjacent_lower_entry": 99.8,
    "lower_tp_unrounded": 100.0994,
    "desired_after_lower_tp": 99.8,
    "conclusion": "At lower-TP fill, desired99.8 is below market, so no immediate bid-clamping follows."
  }
}
```


## ab_inventory.py

```python
"""Frozen-policy BTC inventory experiment; offline only, no exchange clients.

A continues the pinned grid; B at predefined quartile boundaries disables all
new entries and retains the exact same inherited lots and their original TPs.
Boundary equity is marked immediately before the first cut minute, using the
previous minute close. Every inherited lot is attributed from that mark, not
from its historical entry. Parameters are not tuned.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import importlib.util
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "expectancy_20261006/public_data/binance_futures_BTCUSDT_1m.csv"
FAST = ROOT.parent / "weex_review2_20261010/snapshot/research/weex/fast_grid.py"
CONFIG = dict(order_qty=.0012, step=.2, target=.21, cap_usd=4000., max_orders=50, fee=.00016)


@dataclass(frozen=True)
class Lot:
    uid: int
    entry: float
    qty: float
    tp: float
    birth: int


@dataclass
class Side:
    d: int
    lots: list[Lot] = field(default_factory=list)
    ref: float | None = None
    realized: float = 0.
    fees: float = 0.
    turnover: float = 0.
    tps: int = 0
    entries: int = 0
    cost: float = 0.
    qty: float = 0.


def iso(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).isoformat()


def bag(state, px):
    return sum(s.d * lot.qty * (px - lot.entry) for s in state.values() for lot in s.lots)


def totals(state, px):
    realized = sum(s.realized for s in state.values())
    fees = sum(s.fees for s in state.values())
    return dict(equity=realized - fees + bag(state, px), realized_gross=realized,
                fees=fees, bag=bag(state, px), tps=sum(s.tps for s in state.values()),
                entries=sum(s.entries for s in state.values()),
                turnover=sum(s.turnover for s in state.values()),
                lots={name: len(s.lots) for name, s in state.items()},
                qty={name: s.qty for name, s in state.items()})


def advance(state, candle, i, allow_entries, events):
    o, h, l, c = candle
    points = (o, l, h, c) if c >= o else (o, h, l, c)
    for px in points:
        for name, s in state.items():
            keep = []
            for lot in s.lots:
                if (s.d > 0 and px >= lot.tp) or (s.d < 0 and px <= lot.tp):
                    gross = s.d * lot.qty * (lot.tp - lot.entry)
                    fee = CONFIG["fee"] * lot.qty * lot.tp
                    s.realized += gross
                    s.fees += fee
                    s.turnover += lot.qty * lot.tp
                    s.tps += 1
                    s.cost -= lot.qty * lot.entry
                    s.qty -= lot.qty
                    if events is not None:
                        events.append(dict(i=i, kind="exit", side=name, d=s.d, uid=lot.uid,
                                           birth=lot.birth, entry=lot.entry, price=lot.tp,
                                           qty=lot.qty, fee=fee, gross=gross))
                else:
                    keep.append(lot)
            s.lots = keep
            if s.lots:
                s.ref = min(x.entry for x in s.lots) if s.d > 0 else max(x.entry for x in s.lots)
            elif s.ref is None:
                s.ref = px
            else:
                s.ref = max(s.ref, px) if s.d > 0 else min(s.ref, px)
            lvl = s.ref * (1 - s.d * CONFIG["step"] / 100)
            touch = px <= lvl if s.d > 0 else px >= lvl
            if allow_entries and len(s.lots) < CONFIG["max_orders"] and touch:
                q = CONFIG["order_qty"]
                if max(s.cost, s.qty * px) + q * lvl <= CONFIG["cap_usd"]:
                    uid = s.entries * 2 + (0 if s.d > 0 else 1)
                    lot = Lot(uid, lvl, q, lvl * (1 + s.d * CONFIG["target"] / 100), i)
                    s.lots.append(lot)
                    s.cost += q * lvl
                    s.qty += q
                    fee = CONFIG["fee"] * q * lvl
                    s.fees += fee
                    s.turnover += q * lvl
                    s.entries += 1
                    if events is not None:
                        events.append(dict(i=i, kind="entry", side=name, d=s.d, uid=uid,
                                           birth=i, entry=lvl, price=lvl, qty=q, fee=fee, gross=0.))


def attribution(events, end_state, cut, cut_px, end_px):
    old, new = {k: 0. for k in ("realized_from_cut_mark", "bag_from_cut_mark", "fees")}, \
               {k: 0. for k in ("realized_gross", "bag", "fees")}
    for e in events:
        if e["i"] < cut:
            continue
        if e["birth"] < cut:
            assert e["kind"] == "exit"
            old["realized_from_cut_mark"] += e["d"] * e["qty"] * (e["price"] - cut_px)
            old["fees"] += e["fee"]
        else:
            new["realized_gross"] += e["gross"]
            new["fees"] += e["fee"]
    for s in end_state.values():
        for lot in s.lots:
            if lot.birth < cut:
                old["bag_from_cut_mark"] += s.d * lot.qty * (end_px - cut_px)
            else:
                new["bag"] += s.d * lot.qty * (end_px - lot.entry)
    old["net"] = old["realized_from_cut_mark"] + old["bag_from_cut_mark"] - old["fees"]
    new["net"] = new["realized_gross"] + new["bag"] - new["fees"]
    return dict(inherited=old, post_cut_entries=new)


def main():
    rows = list(csv.DictReader(SOURCE.open(encoding="utf-8")))
    ts = [int(r["ts"]) // 1000 for r in rows]
    candles = [tuple(float(r[k]) for k in ("open", "high", "low", "close")) for r in rows]
    cuts = [len(rows) * n // 4 for n in (1, 2, 3)]
    state_a = dict(LONG=Side(1), SHORT=Side(-1))
    snapshots, events_a = {}, []
    for i, candle in enumerate(candles):
        if i in cuts:
            snapshots[i] = copy.deepcopy(state_a)
        advance(state_a, candle, i, True, events_a)
    end_px = candles[-1][-1]
    baseline = totals(state_a, end_px)
    assert baseline["tps"] == 6179
    assert math.isclose(baseline["equity"], -563.71030764967, abs_tol=1e-6)
    print("Instrumented baseline", json.dumps(baseline), flush=True)

    # A second implementation, the actual pinned fast_grid, must reproduce A.
    import numpy as np
    spec = importlib.util.spec_from_file_location("pinned_fast_grid_ab", FAST)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    data = (np.array(ts), *(np.array([x[j] for x in candles]) for j in range(4)))
    exact = module.run(data, **CONFIG)
    assert exact["тейков"] == baseline["tps"]
    assert math.isclose(exact["итог"], baseline["equity"], abs_tol=1e-6)
    print("Pinned fast_grid cross-check passed", flush=True)

    comparisons = []
    for cut in cuts:
        initial = snapshots[cut]
        cut_px = candles[cut - 1][-1]
        start = totals(initial, cut_px)
        state_b, events_b = copy.deepcopy(initial), []
        peak_b, dd_b = 0., 0.
        for i in range(cut, len(candles)):
            advance(state_b, candles[i], i, False, events_b)
            change = totals(state_b, candles[i][-1])["equity"] - start["equity"]
            peak_b = max(peak_b, change)
            dd_b = min(dd_b, change - peak_b)
        end_b = totals(state_b, end_px)
        aa = attribution(events_a, state_a, cut, cut_px, end_px)
        bb = attribution(events_b, state_b, cut, cut_px, end_px)
        delta_a = baseline["equity"] - start["equity"]
        delta_b = end_b["equity"] - start["equity"]
        assert math.isclose(aa["inherited"]["net"] + aa["post_cut_entries"]["net"], delta_a, abs_tol=1e-6)
        assert math.isclose(bb["inherited"]["net"], delta_b, abs_tol=1e-6)
        assert math.isclose(aa["inherited"]["net"], bb["inherited"]["net"], abs_tol=1e-6)
        assert math.isclose(delta_a - delta_b, aa["post_cut_entries"]["net"], abs_tol=1e-6)
        assert abs(bb["post_cut_entries"]["net"]) < 1e-8
        row = dict(cut_fraction=cut / len(candles), cut_index=cut, cut_utc=iso(ts[cut]),
                   baseline_mark_utc=iso(ts[cut - 1]), baseline_mark_price=cut_px,
                   inherited_state=start, A_continuing=dict(post_cut_net=delta_a, attribution=aa),
                   B_no_new_entries=dict(post_cut_net=delta_b, attribution=bb, end_totals=end_b,
                                         post_cut_minute_close_drawdown=dd_b),
                   A_minus_B=delta_a - delta_b,
                   post_cut_new_entries=baseline["entries"] - start["entries"],
                   post_cut_A_tps=baseline["tps"] - start["tps"],
                   post_cut_B_tps=end_b["tps"] - start["tps"])
        comparisons.append(row)
        print(json.dumps(row), flush=True)
    out = dict(source=str(SOURCE), source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
               fast_grid=str(FAST), fast_grid_sha256=hashlib.sha256(FAST.read_bytes()).hexdigest(),
               rows=len(rows), first_utc=iso(ts[0]), last_bar_utc=iso(ts[-1]), end_mark=end_px,
               non_60s_gaps=sum(b-a != 60 for a, b in zip(ts, ts[1:])),
               frozen_config=CONFIG, baseline=baseline, pinned_fast_grid_result=exact,
               comparisons=comparisons,
               limitations=["Binance futures proxy, not WEEX fills or queue.",
                            "Previously examined history, not new OOS.",
                            "Funding, cash rebate, slippage and taker cost excluded.",
                            "OHLC colour path: O-L-H-C on up bars, O-H-L-C on down bars.",
                            "Touch fills and one new entry per side per path point are model assumptions.",
                            "No cut chosen by profitability; cuts fixed at 25/50/75% bar count.",
                            "B cancels hypothetical new-entry opportunities but retains old TPs unchanged.",
                            "All old-lot profit is marked from cut price, not historical entry."])
    (ROOT / "ab_inventory.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Причинный A/B: продолжать сетку или только сопровождать старые лоты", "",
             "Параметры заморожены: BTC, LONG+SHORT, q=0.0012, шаг 0.2%, цель 0.21%, "
             "потолок $4000 на сторону, максимум 50 лотов, maker 0.016% на каждое исполнение. "
             "Источник — ранее изученные 218880 минут Binance futures; не новый OOS и не исполнение WEEX.", "",
             f"Контроль: исходная fast_grid и инструментированная реализация совпали: "
             f"{baseline['tps']} тейков, полный PnL ${baseline['equity']:.2f} без funding.", "",
             "В момент каждого среза копируется одно и то же непрерывное состояние. "
             "A продолжает старые тейки и все новые входы. B сохраняет те же старые тейки, "
             "но запрещает новые входы. Начальная оценка — close минуты перед срезом, "
             "до первой сделки среза. Конечная цена одинакова. Унаследованные лоты "
             "считаются от цены среза; их старая прибыль/убыток повторно не присваивается новой части.", "",
             "| Срез UTC | A: полный PnL после среза | B: только старые TP | A−B: вклад новых лотов | Новые входы A |",
             "|---|---:|---:|---:|---:|"]
    for r in comparisons:
        lines.append(f"| {r['cut_utc']} | ${r['A_continuing']['post_cut_net']:.2f} | "
                     f"${r['B_no_new_entries']['post_cut_net']:.2f} | ${r['A_minus_B']:.2f} | "
                     f"{r['post_cut_new_entries']} |")
    lines += ["", "A−B в этой модели точно равен нетто-вкладу новых post-cut лотов: "
              "их закрытая прибыль плюс конечный мешок минус входные/выходные комиссии. "
              "Их наличие не меняет старые TP, поэтому вклад унаследованных лотов одинаков "
              "в A и B — это проверено утверждениями в скрипте.", "",
              "Это причинная проверка выключателя новых входов в данном симуляторе, "
              "а не доказательство положительного матожидания или оптимального сигнала паузы. "
              "Если A−B отрицателен, новые лоты ухудшили этот конкретный отрезок; "
              "если положителен — отказ от новых входов стоил прибыли. "
              "Пауза не закрывает мешок и не устраняет риск движения цены по старой позиции.", "",
              "Ограничения: funding/возврат комиссий/проскальзывание не включены; "
              "нет очереди maker и реальных задержек. Данные уже использовались для предыдущих проверок. "
              "Квартильные срезы заданы заранее, торговые параметры не перебирались."]
    (ROOT / "ab_inventory.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

```


## exit_spec_probe.py

```python
"""Offline arithmetic and current-engine trace. No network, credentials, or live client."""
from __future__ import annotations

import json
import sys
import tempfile
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SNAPSHOT = Path(r"C:\bot7\research\weex_review2_20261010\snapshot")
sys.path.insert(0, str(SNAPSHOT))
from services.weex_grid.engine import DEFAULT, DryExchange, Grid


def run():
    e, fm, ft = Decimal("100"), Decimal(".00016"), Decimal(".0005")
    tp_long, tp_short, tick = Decimal("100.3"), Decimal("99.7"), Decimal(".01")
    long_bound = tp_long * (1 - fm) / (1 - ft)
    short_bound = tp_short * (1 + fm) / (1 + ft)
    long_limit = (long_bound / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    short_limit = (short_bound / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
    baseline_long = tp_long - e - e * fm - tp_long * fm
    baseline_short = e - tp_short - e * fm - tp_short * fm
    assert long_limit - e - e * fm - long_limit * ft >= baseline_long
    assert e - short_limit - e * fm - short_limit * ft >= baseline_short
    assert (long_limit - tick) - e - e * fm - (long_limit - tick) * ft < baseline_long
    assert e - (short_limit + tick) - e * fm - (short_limit + tick) * ft < baseline_short

    with tempfile.TemporaryDirectory(dir=ROOT) as td:
        box = {"quote": (100.99, 101.01)}
        exchange = DryExchange(lambda: box["quote"], maker_fee=float(fm))
        config = {**DEFAULT, "enabled": False, "dry_run": False, "sides": ["LONG"],
                  "price_tick": .01, "qty_step": .01, "order_qty": "1", "target_pct": .3,
                  "stress_budget_frac": 0, "daily_loss_stop_usd": 0}
        g = Grid(exchange, cfg=config, state_path=Path(td) / "state.json",
                 journal_path=Path(td) / "journal.jsonl", now_fn=lambda: 10000.)
        s = g.st["LONG"]
        s["fees"] = float(e * fm)
        s["lots"] = [{"entry": 100., "qty": "1.00", "tp": 100.3,
                      "tp_order": None, "t": 1., "parent": "entry_original"}]
        g.tick()
        placed = s["lots"][0]["tp_order"]["price"]
        assert placed == 101.01
        box["quote"] = (100.49, 100.51)
        g.tick()
        unchanged = s["lots"][0]["tp_order"]["price"]
        assert unchanged == 101.01
        open_qty = sum(float(l["qty"]) for l in s["lots"])
        box["quote"] = (98.99, 99.01)
        g.tick()
        marked = g.bot_pnl(99.)
        assert abs(marked + 1.016) < 1e-10

    result = {
        "scope": "Offline formulas and current 9cc snapshot fake-exchange trace; not WEEX execution or expectation estimate",
        "conditional_rates_not_verified_account_tariff": {"maker": str(fm), "taker": str(ft)},
        "unit_qty": 1,
        "baseline_net_long": str(baseline_long),
        "baseline_net_short": str(baseline_short),
        "long_ioc_worst_price_floor": str(long_bound),
        "short_ioc_worst_price_ceiling": str(short_bound),
        "tick_001_long_sell_limit": str(long_limit),
        "tick_001_short_buy_limit": str(short_limit),
        "long_exit_at_100_99_net": str(Decimal("100.99") * (1-ft) - e * (1+fm)),
        "long_exit_at_100_49_net": str(Decimal("100.49") * (1-ft) - e * (1+fm)),
        "current_engine_trace": {"posted_tp": placed, "tp_after_bid_100_49": unchanged,
                                 "open_qty": open_qty, "marked_at_mid_99_after_entry_fee": marked},
        "adjacent_refill_control": {"step_pct": .2, "upper_entry": 100,
                                    "adjacent_lower_entry": 99.8, "lower_tp_unrounded": 100.0994,
                                    "desired_after_lower_tp": 99.8,
                                    "conclusion": "At lower-TP fill, desired99.8 is below market, so no immediate bid-clamping follows."},
    }
    (ROOT / "exit_spec.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()

```
