# Независимая проверка WEEX после исправлений, 18.10.2026

Проверен публичный код **2959c7acae99d06d9274578f931a6e35a20785c6**, включая исправления из `f450490..5d5d85e`. Подтверждение оператора о деплое, совпадении ордеров/денег, отсутствии сирот и состоянии процессов — отдельные утверждения: доступа к Mac, счёту и журналам исполнения в этой проверке не было. Production-модули и `compare_start_snapshot.py` не запускались. Изменений движка нет.

Проверка воспроизводится стандартным Python 3.11+:

```text
python -X utf8 -B research/weex_followup_20261018/audit_followup_offline.py
```

Harness проверяет Git blob SHA1 и SHA256 шести инертных источников, затем компилирует только перечисленные методы из AST с синтетическими memory stubs. Итог: **10 сценариев, все assertions прошли, 0 network calls, 0 production imports**. Прохождение reproducer означает совпадение с описанным поведением, включая дефекты, а не safety PASS.

## Исправления, подтверждённые по коду и синтетическим проверкам

- [`engine.py:697–710`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/services/weex_grid/engine.py#L697): `None`, `{}`, список, строка, отсутствие `success`, success без orderId и не boolean success сохраняют pending и резерв. Только явное `success is False` снимает резерв; годный True+orderId привязывается.
- [`engine.py:800–804`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/services/weex_grid/engine.py#L800): сделка без orderId делает поиск неполным; pending после TTL остаётся.
- [`engine.py:494–503`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/services/weex_grid/engine.py#L494): немедленная `_fee_delta` фильтрует чужой orderId. Это исправление одной точки чтения комиссий, см. остаток ниже.
- [`engine.py:146–148`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/services/weex_grid/engine.py#L146): явные cid_tag L/S/l/s отклоняются.
- [`engine.py:772`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/services/weex_grid/engine.py#L772), [`:857`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/services/weex_grid/engine.py#L857): split-окна перекрываются в m. End-exclusive synthetic midpoint больше не теряется; реальный контракт API этим тестом не установлен.
- [`loop.py:89–94`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/services/weex_grid/loop.py#L89): Runner последователен, free пересчитывается перед каждой сеткой. Прежний межсеточный parallel counterexample устранён именно отказом от параллельного механизма.

## Остались конкретные дефекты

### P2 — чужая комиссия снова попадает через `_settle_fees`

[`engine.py:550–564`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/services/weex_grid/engine.py#L550): второй читатель user_trades не получил фильтр orderId/symbol. На том же синтетическом ответе own fee 0.01 + foreign fee 7.00 непосредственный `_fee_delta` верно учитывает 0.01; после 61 секунды `_settle_fees` доводит fees и own cursor done до 7.01. Завышение необратимо для этого курсора: используется max/только положительное добавление.

Нужно общее проверенное чтение комиссий для обеих точек, включая schema/ownership/completeness/dedup, и регрессионный тест полного цикла immediate → late settlement. Не утверждается, что API реально вернул чужую строку на живом счёте; это тот же класс неожиданного ответа, от которого защищалась первая правка.

### P2 — `None` в поздней досверке выглядит как успешная пустая проверка

Те же [`:552–571`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/services/weex_grid/engine.py#L552): `or []` превращает None в пустой список, выставляет checked и позволяет удалить старый курсор. Reproducer: t=1, done=0.01, now=5000, ответ None → курсор удалён, issue отсутствует. Комиссия, которая ещё не была доступна, больше не проверяется. Ошибка должна сохранять unresolved cursor и не подтверждать финальную досверку.

### P1 — последовательный проход не устраняет недорезервирование исполненной части сироты внутри одной сетки

[`engine.py:993–999`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/services/weex_grid/engine.py#L993) резервирует только origQty−executedQty; [`:1343–1372`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/services/weex_grid/engine.py#L1343) добавляет найденное исполнение в лот, но не в `_room_used`. Free для одного Grid фиксирован до его прохода; [`may_add:628`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/services/weex_grid/engine.py#L628) не видит эту прибавку.

Синтетическая область воспроизведения: одна сетка с обеими сторонами, без regime closure, cap/free350, ранее неучтённый LONG orig3/executed1×100. `_orphans` занимает200, `_take_entry_fill` создаёт лот100, SHORT затем принимает новый вход100. Суммарное обязательство400 >350. Следующая сетка уже увидит обновлённый диск, поэтому это **не прежний межсеточный race**. Текущие живые настройки, применимость сценария к ним и факт превышения не проверялись.

Минимальное требование — учесть весь вновь обнаруженный ранее не включённый риск ровно один раз до любых решений о новых входах этой сетки; не прибавлять заново обычные исполнения уже зарезервированного входа. Нужны тесты обеих сторон, orphan partial/full, известного fill cursor и отмены остатка. Возврат параллельности дополнительно требует общего атомарного резерва.

## Подтверждённые незакрытые ограничения

- **Fair cursor:** [`engine.py:814–828`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/services/weex_grid/engine.py#L814). 20 unknown detail перед собственным 21-м: 10 повторов, 200 запросов, собственный не посещён, foreign cache пуст. Fail-closed сохраняется; риск задержки принятия исполнения/тейка не сводится к удобству диагностики.
- **100 fills:** [`client.py:196–206`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/services/weex_api/client.py#L196) задаёт limit100 без пагинации. Fee readers считают100 строк полными и не дедуплицируют tradeId. Если исполнений101+, полная комиссия не доказана. Для текущего размера ордеров достижимость не установлена; реальная потеря комиссий не заявляется. Нужен completeness contract, насыщенный ответ не превращать в окончательную сумму.
- Сводная сверка symbol/side по всем владельцам с блокировкой входов не добавлена в цикл; отчёт автора это явно оставляет открытым. Внешняя диагностическая сверка не является автоматическим risk gate.

## `compare_start_snapshot.py`: полезная стартовая запись, но не полный frozen start сравнения

Скрипт рассмотрен **только как текст**. Приватный снимок и его содержимое не читались. Опубликованный SHA снимка позволяет оператору впоследствии подтвердить байты, но не доказывает полноту экономического состояния.

1. [`:47–55`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/research/weex/compare_start_snapshot.py#L47): сохраняется только LONG. Entry/pending сведены к boolean: нет id/cid, цены, qty, filled, резервов, strays, order_fills и fee_book. Lots сохраняют t/entry/qty, но теряют parent orderId и TP-связи. Такой файл сам по себе не восстанавливает starting execution/risk state; SHORT отсутствует целиком. Для заранее объявленного long-only comparison последнее допустимо, но не для заявления о полном живом портфеле.
2. Там же сохраняется gross realized, но нет исходных cumulative fees/turnover/transfer accounting. Недельные приращения net надо сверить с полными локальными state/journal/funding данными; отсутствующее не считать0. Начальные lot.t можно использовать как ключи, но не заменять их позднее эвристикой «все qty0.0036 — старые»: частичное закрытие меняет qty, новые лоты могут иметь тот же размер.
3. [`:63–65`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/research/weex/compare_start_snapshot.py#L63): имя содержит только дату, `write_bytes` перезаписывает существующий файл при повторном запуске. Для frozen start нужен уникальный immutable ID, exclusive create и отдельные amendments; старый опубликованный SHA сохранить.
4. [`:26–36`](https://github.com/alexey-chechikov/chat-bot-v2/blob/2959c7acae99d06d9274578f931a6e35a20785c6/research/weex/compare_start_snapshot.py#L26): created_utc фиксируется **до** двух запросов котировок и последовательных чтений меняющегося state; нет per-source as-of/read bounds или SHA state/journal. Это не доказательство одновременного атомарного снимка. Нужен журнал интервала чтения и согласованная граница учёта, без заднего датирования будущего дополнения.
5. Mid действительно mid bid/ask, а не exchange mark или стоимость ликвидации мешка. Для единого descriptive NAV mid допустим при одинаковом правиле; нужен отдельный bid/ask/execution close stress и spread. Стартовый файл не содержит bid/ask по отдельности.
6. Правила не задают точные UTC end, общий выделенный капитал/буфер/cap, baseline policy/size, starting inventory counterfactual и event handling. Это надо зарегистрировать **сейчас, до результата**, отдельным локальным amendment со временем; старый снимок не переписывать. Подготовка evaluator к25.10 не заменяет заморозку правил до25.10.

Старые BTC-лоты сохранять отдельной legacy-корзиной с идентичностями и стартовой оценкой. В фактической совокупной equity они и дальнейшие fees/funding/MTM остаются с полной сверкой; в attribution нового сравнения отдельно показать legacy и новую деятельность. Исключение прежнего накопленного PnL не должно превращаться в исключение потерь/капитала старой позиции. Парный replay — обе политики на одном пути, одинаково заранее заданные ресурсы/начальное состояние, execution assumptions. Одна неделя и четыре BTC-сетки — одна коррелированная траектория, не четыре независимых доказательства преимущества.

## Пределы результата

Источник отчёта о деплое, приватном снимке, 1187 passed и живой сверке — автор документа. Здесь независимо проверены код и перечисленные synthetic branches; suite, Mac и факт живых событий не проверялись. Никаких указаний менять/отключать боевых ботов этот отчёт не даёт. Сырой market replay проверяется отдельной задачей; результаты этой проверки не подтверждают queue/fills модели.
