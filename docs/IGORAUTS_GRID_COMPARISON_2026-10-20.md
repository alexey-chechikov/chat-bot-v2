# Сравнение торговых сеток igorauts с нашим WEEX — 20.10.2026

Вывод: **у автора стоит заимствовать инженерные механизмы нового OKX-бота, но оснований считать его торговую стратегию прибыльнее нашей нет**. В старом WEEX-проекте найдены опасные переходы состояния; переносить его целиком не следует. У нас уже есть существенная часть защиты исполнения, но остаются конкретные пробелы.

## Что и как проверено

Только статическое чтение опубликованных исходников и тестов, без запуска/импорта чужого кода, установки зависимостей, доступа к бирже, Mac, ключам, аккаунтам и живым состояниям. Реальная работа экземпляров и заявленные автором числа тестов/результаты торговли независимо не подтверждались. В наших ботах ничего не изменено.

| Проект | Зафиксированная версия | Роль |
|---|---|---|
| [igorauts/okxbot](https://github.com/igorauts/okxbot/tree/416da1864185683c7691d6b693c07739d2b0680e) | 416da18, движок 0.7.16 | Основной актуальный объект сравнения |
| [igorauts/okx-eth-grid-bot](https://github.com/igorauts/okx-eth-grid-bot/tree/489ea4da58559e2fdc0f9eef45ebb7682ebfc500) | 489ea4d, 0.5.9 | Предыдущая реализация OKX ETH |
| [igorauts/weex-strk-grid-bot](https://github.com/igorauts/weex-strk-grid-bot/tree/23238337455fcae094c1bf0a675dc777d173f1f0) | 2323833 | Отдельная реализация WEEX STRK |
| [Наш chat-bot-v2](https://github.com/alexey-chechikov/chat-bot-v2/tree/e346b3ffcbbf526e6472a443f10b93313bb77a1d) | e346b3f, ветка alexey/mac-2026-05-29 | Актуальный опубликованный WEEX engine/client/Runner, профильные тесты и симуляторы |

Наличие функции в коде не доказывает её включение на живом экземпляре. Отсутствие в проверенном контуре не доказывает отсутствие отдельного внешнего сервиса. Старые выводы по 2959c7a сверены с новым e346b3f: поздние комиссии и прежняя межсеточная гонка уже исправлены.

## 1. Торговая логика: похожая идея, разные ограничения

Актуальный OKX — LONG-only, cross/net, одинаковый размер BUY, post-only покупки ниже BID и attached TP. У него больше одновременно стоящих уровней и отдельная логика распределения реальных/виртуальных TP. Наш движок умеет LONG/SHORT, несколько независимых сеток, шаг/цель на сетку и опциональное закрытие стороны при смене SMA-режима. Это разные конфигурационные возможности, а не доказательство преимущества одного метода.

Источники: [OKX BUY и attached TP](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_bot.py#L2627-L2646), [геометрия сетки](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_bot.py#L2884-L2943), [наш режим и сопровождение обеих сторон](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/engine.py#L1286-L1318).

Минимальный TP у OKX рассчитывается с запасом к двум maker-комиссиям, но это не гарантирует net прибыль: аварийный MARKET, funding и проскальзывание относятся к другой экономике. [Формула TP](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_bot.py#L2874-L2882).

В актуальном дереве igorauts не обнаружен воспроизводимый backtest/paper simulator стратегии. DRY RUN печатает кандидатов и выходит, а не моделирует их исполнения. У нас симуляторы есть, но очередь, задержки, funding и обычные partial fills в них полноценно не воспроизводятся. Поэтому сравнение доходности потребовало бы одинаковых данных, бюджета, начальных позиций и полной модели затрат.

Источники: [OKX DRY RUN](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_bot.py#L3503-L3507), [наш DryExchange](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/engine.py#L2048-L2132), [ограничения fast model](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/research/weex/fast_grid.py#L1-L9).

## 2. Что у него полезно и как это соотносится с нашим кодом

### Общая очередь API и измерение задержек — наиболее полезное дополнение

У OKX есть межпроцессная FIFO для запросов позиций/истории, общая квота, ограниченное ожидание и консервативное восстановление повреждённого состояния квоты. Отдельный singleflight объединяет одновременные запросы fills одного ордера. Телеметрия измеряет HTTP, ожидание квоты, сверку, POST и полный проход; очередь записи ограничена, при перегрузке диагностические записи пропускаются вместо блокирования торговли.

У нас последовательный Runner и точечные throttles уже есть, но это не общая очередь запросов с бюджетом. Из предложений следует начать с измерений: fill→обнаружение→учёт→TP→пополнение, P50/P95/P99, число ожидающих unknown, время без полного количества BUY. Затем решать, какие чтения объединять и какие защитные операции обслуживать прежде фоновой статистики. Не возвращать бесконтрольную параллельную раздачу капитала сеткам.

Источники: [OKX FIFO](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_positions_fifo.py#L27-L54), [квота](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_positions_fifo.py#L133-L166), [singleflight](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_fill_singleflight.py#L16-L48), [неблокирующая телеметрия](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_latency.py#L15-L62), [наш Runner](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/loop.py#L82-L116).

### Сверка позиции и защитных выходов как обязательный инвариант

Новый OKX отдельно проверяет объяснимость net position локальными циклами и соответствие остатка позиции реальным SELL, виртуальным TP и ещё не защищённым partial BUY. WS будит обработчик, но не считается подтверждением исполнения. Это сильнее простого признака «цикл жив».

Наша модель сложнее: несколько владельцев на одной стороне/символе и ручные позиции. Проверка каждой сетки по всей биржевой позиции не докажет общий баланс владельцев: одной и той же позиции может хватать каждой сетке по отдельности. Нужен отдельный агрегированный инвариант по symbol/side с категориями tracked bots / manual or unknown / transfers и явным состоянием неполноты. При неполноте блокировать новые входы, продолжая доказуемое сопровождение существующих выходов. Фактические ключи/позиции для этой проверки в рамках аудита не читались.

Источники: [OKX position reconciliation](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_bot.py#L3130-L3179), [coverage audit](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_bot.py#L2318-L2336), [признанное ограничение нашей сверки общей позиции](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/engine.py#L1426-L1465).

### Долговечный учёт исполнений и полнота истории

OKX хранит fills в SQLite с уникальностью order/bill ID и отказывается принимать изменившуюся версию уже записанного исполнения. Неполные fills не превращаются в complete PnL. У нас уже есть cumulative fill cursors, адресный fee book, журнал исполнений, ownership и передача лотов. Однако API orderTrades ограничен 100 строками без pagination; полнота комиссии при насыщенном ответе не доказана. При внешнем закрытии оценка PnL в нашей сверке также может использовать текущую цену вместо actual fill.

Стоит перенести принцип полного ledger с устойчивым ID исполнения и отдельным статусом полноты. Сам SQLite не делает расчёт правильным: нужны правила duplicate/conflict, currency и доказанного окончания выборки.

Источники: [OKX FillStore](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_bot.py#L900-L949), [наши исправленные комиссии](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/engine.py#L479-L572), [лимит orderTrades](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_api/client.py#L193-L203).

### Инцидент закрывается подтверждённым восстановлением

У OKX Telegram отделяет одно открытие STATE MISMATCH от повторных симптомов. BACK TO NORMAL появляется только после трёх разных свежих совпадающих samples. Само молчание алертов не считается исправлением. У нас уже есть liveness, unknown-счётчики, outbox и журнал; полезно дополнить их именно жизненным циклом инцидента и контролем свежести данных/подтверждений.

Источники: [OKX incident/recovery](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_telegram_events.py#L239-L325), [observer различает journal count и exchange confirmation](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_execution_observer.py#L253-L293), [наш tick health](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/engine.py#L1082-L1108).

### Общий аварийный SOFT и безопасное обновление

У OKX отдельные признаки проблем с маржой от биржи создают общий persistent SOFT latch для совместно настроенных процессов. Это реакция на отказ/отмену биржи, а не прогноз ликвидации и не полноценный margin-ratio guard. Полезный принцип — общий запрет новых входов с явным ручным возобновлением, не автоматическое уничтожение позиции.

В репозитории также есть модули планирования обновления, проверки bundle и durable start-fence. Они прямо помечены как строительные блоки, не готовый автоматически применяемый LIVE installer. Не приписываем им неподтверждённое развёртывание. Для наших обновлений полезен контракт: заморозить запуск, сохранить state/журналы, проверить версии, после старта сверить ордера/позицию; не откатывать продвинувшееся торговое состояние старой копией.

Источники: [общий SOFT](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_bot.py#L844-L887), [rollout contract](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_rollout_transaction.py#L1-L8), [start-fence scope](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_rollout_fencing.py#L1-L24).

## 3. Что у нас уже есть и не нужно изобретать заново

- Pending записывается до POST, неизвестные ответы не освобождают резерв, повторный вход блокируется до сверки. [Наш submit](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/engine.py#L661-L713), [resolver](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/engine.py#L870-L950).
- Курсоры накопленного исполнения и принадлежность CID различают сетки, partial fill не должен учитываться повторно. [Курсоры](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/engine.py#L509-L539).
- Поздний учёт чужой комиссии исправлен: обе ветки используют адресный фильтр; негодный ответ не помечается успешной проверкой. [Исправление](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/engine.py#L479-L572), [регрессии](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/tests/services/weex_grid/test_weex_gpt1018b.py#L17-L41).
- Старый межсеточный parallel race исправлен: обход последовательный, free пересчитывается перед каждой сеткой. В бюджете учитываются tracked lots, entry, pending, stray. Ручные позиции намеренно не входят в этот бюджет, поэтому называть его полным account risk cap нельзя. [Runner](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/loop.py#L82-L140), [portfolio](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/portfolio.py#L47-L84).

## 4. Конкретный оставшийся пробел нашего cap

**Статический условный сценарий, не подтверждённый живой инцидент и не выполненный тест.** Одна both-сетка восстанавливает принадлежащий ей входной orphan, которого не было в исходном учёте. Часть уже исполнена. `_orphans` прибавляет в `_room_used` только оставшуюся неисполненную часть. `_take_entry_fill` добавляет обнаруженный fill в lot, но `_room_used` не увеличивает. До следующего пересчёта портфеля противоположный вход может использовать незарезервированное место.

Для иллюстрации бюджет $201, previously untracked LONG orig=$120, filled=$40, remaining=$80. Если новый SHORT около $120.24, проверка свободного места может пройти, хотя gross commitment около $240.24. Это требует конкретного состояния orphan и двух разрешённых сторон; текущие живые настройки не проверялись.

Источники: [orphan reserve](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/engine.py#L988-L1000), [новый lot](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/engine.py#L1344-L1372), [формула room](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/engine.py#L624-L631), [порядок одного tick](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/engine.py#L1256-L1318).

Дальнейшая проверка: отдельная регрессия both + untracked partial orphan, контроль полной и частичной отмены, известного fill cursor и повторного snapshot. Требуемый инвариант — весь впервые обнаруженный риск учитывается ровно один раз до нового входа. Не добавлять второй резерв обычному fill уже зарезервированного ордера. Изменений engine и деплоя этим обзором не сделано.

## 5. Что не следует копировать

### Старый WEEX STRK — слабее по торговой безопасности

- Pending submit записывается после POST и лишь для timeout. Unknown другого вида или crash между принятием заявки биржей и записью могут потерять durable intent. [Путь submit](https://github.com/igorauts/weex-strk-grid-bot/blob/23238337455fcae094c1bf0a675dc777d173f1f0/bot06.py#L3712-L3773).
- Resolver освобождает pending после отсутствия в первых 100 historical orders. Полнота выборки не доказана. [Ограниченная история](https://github.com/igorauts/weex-strk-grid-bot/blob/23238337455fcae094c1bf0a675dc777d173f1f0/bot06.py#L7301-L7321), [освобождение](https://github.com/igorauts/weex-strk-grid-bot/blob/23238337455fcae094c1bf0a675dc777d173f1f0/bot06.py#L7540-L7568).
- `TRIGGERED`/положительный triggerTime классифицируется как DONE до доказательства terminal SELL и закрытого объёма. Такая ветка может начать rearm раньше фактического выхода. [Классификация](https://github.com/igorauts/weex-strk-grid-bot/blob/23238337455fcae094c1bf0a675dc777d173f1f0/bot06.py#L4803-L4838), [DONE_OFFLINE](https://github.com/igorauts/weex-strk-grid-bot/blob/23238337455fcae094c1bf0a675dc777d173f1f0/bot06.py#L5639-L5657).
- Cancel ACK/WS cancellation могут удалить parent без полноценной обработки уже исполненной части. [DELETE success](https://github.com/igorauts/weex-strk-grid-bot/blob/23238337455fcae094c1bf0a675dc777d173f1f0/bot06.py#L3862-L3877), [WS cancellation](https://github.com/igorauts/weex-strk-grid-bot/blob/23238337455fcae094c1bf0a675dc777d173f1f0/bot06.py#L6851-L6859).
- SELL matcher подбирает одну сделку по quantity/окну времени/близости цены вместо доказанной ID-цепочки; отсутствие комиссии может стать нулём. Нельзя переносить это в финансовый учёт. [Matcher](https://github.com/igorauts/weex-strk-grid-bot/blob/23238337455fcae094c1bf0a675dc777d173f1f0/bot06.py#L2185-L2290), [fee default](https://github.com/igorauts/weex-strk-grid-bot/blob/23238337455fcae094c1bf0a675dc777d173f1f0/bot06.py#L1720-L1747).

При этом идеи пакетного rearm и подтверждённой нижней очистки заслуживают отдельного изучения, если когда-нибудь понадобится много одновременно стоящих уровней. [Batch rearm](https://github.com/igorauts/weex-strk-grid-bot/blob/23238337455fcae094c1bf0a675dc777d173f1f0/bot06.py#L4433-L4512). Это не исправляет перечисленные нарушения жизненного цикла.

### Новый OKX — полезен, но не эталон полной экономики и риска

- DD измеряет худший total PnL относительно нуля, а не peak-to-trough equity. В 0.7.16 sampler использует приблизительную цену входа BUY LIMIT и локальный ledger. Funding исключён. Показатель нельзя выдавать за полноценную максимальную просадку капитала. [Формула DD](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_bot.py#L362-L388), [sampler](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_bot.py#L4186-L4236), [funding вне scope](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/RELEASE_NOTES_v0716.md#L29).
- Нет подтверждённого автоматического equity-DD выключателя. У нас тоже нет такого account-wide механизма в просмотренном контуре; дневной стоп — одной сетки и запрещает новые входы, а не гарантирует максимальный убыток. [Наш daily stop](https://github.com/alexey-chechikov/chat-bot-v2/blob/e346b3ffcbbf526e6472a443f10b93313bb77a1d/services/weex_grid/engine.py#L1331-L1342).
- Виртуальные TP зависят от работающего процесса, связи и успешного REST. Ветка virtual_escape может закрыть MARKET после ранее зафиксированного пересечения TP без ограничения худшей цены в ордере. [Реализация](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_bot.py#L2032-L2081). Биржевой attached TP также не является гарантией цены исполнения.
- HARD удаляет защитные TP и оставляет позицию; это не эквивалент безопасного закрытия. [Shutdown modes](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/okx_bot.py#L1276-L1334).
- Исторические движки, README и тестовые runners разных версий лежат рядом. Основной run_checks запускает 0.6.10, а активный engine — 0.7.16. Нельзя суммировать исторические тесты как подтверждение текущего executable. [Runner](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/run_checks.sh#L5-L9), [активная версия](https://github.com/igorauts/okxbot/blob/416da1864185683c7691d6b693c07739d2b0680e/engine_manifest.json#L54-L65).

## 6. Предлагаемый порядок работ для нас

| Порядок | Работа | Критерий готовности |
|---|---|---|
| 1 | Закрыть partial-orphan cap и полноту fee history | Регрессии на partial/full/cursor/repeated snapshot и насыщенный ответ; никакого двойного резерва и ложной complete-комиссии |
| 2 | Агрегированная сверка владельцев и защищённого остатка | Совпадение по symbol/side, unknown явно выделен; при mismatch новые входы запрещены, доказуемые выходы обслуживаются |
| 3 | Диагностика исполнения и общая очередь API | Путь fill→TP/refill измеряется по фазам; единая квота и контролируемое ожидание, деградация не создаёт дублей и не ломает shared capital reservation |
| 4 | Полная net-экономика и правильная просадка | Actual fills/fees/funding/realized/unrealized/legacy basket и transfers разделены; peak-to-trough equity считается отдельно от loss-from-zero, неполное — null/unknown |
| 5 | Единая проверка стратегии и исполнения | Parity live/simulator на общей трассе; adverse selection, очередь и задержки не подменены касанием свечи; сравнение при равном бюджете и стартовой позиции |

Это рекомендации по результатам анализа, не изменение протокола недельного сравнения, параметров торговли или автоматизаций. Доходность другого автора не установлена. Наша исследовательская серия CoinGlass и чужой торговый engine — разные задачи; рост числа мониторов или показателей сам по себе не создаёт преимущества.
