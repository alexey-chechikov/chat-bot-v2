# Ревью исполнителя BTC и 432 · 12.11.2026

Проверен коммит [239b426](https://github.com/alexey-chechikov/chat-bot-v2/commit/239b426692448413afc1924c996a6325cbe87e9a) ветки `alexey/sigexec-20261112`. **Боевой запуск заблокирован.** Сначала исправить восстановление незавершённых заявок, аварийное закрытие и расчёт объёма. Затем проверить жизненный цикл ордеров в изолированном демо OKX или тестнете Bybit. В ревью использовались локальные данные, имитатор и поддельные HTTP-ответы.

## Дефекты, блокирующие запуск

| Приоритет | Сценарий и результат | Исправление |
| --- | --- | --- |
| P1 | **Повторный MARKET после потери процесса.** `_send` сохраняет `SENDING` и `UNKNOWN`, а `_work` записывает `work.cur` лишь после возврата `_send`. После прерывания у новой копии есть незавершённый выход в реестре, но `cur=None`. При `Incomplete` следующий шаг отправляет второй MARKET, ещё до истечения 120 с. В симуляции первый закрыл свои 0,0071 BTC, второй уменьшил чужой лонг с 0,0100 до 0,0029 BTC. Штатный тест рестарта вручную сохраняет `cur`. | Получать незавершённую работу из сохранённого реестра по эпизоду и роли. Проверять уникальность активного намерения до отправки. Тестировать остановку непосредственно после `SENDING`, после принятия заявки и после сохранения `UNKNOWN`. [Код отправки](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/executor.py#L146-L163) · [Код работы](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/executor.py#L338-L386) |
| P1 | **OKX превращает тайм-аут в финальный отказ.** OKX передаёт `50004` как HTTP 400 с неопределённым исходом заявки. `_call` выбрасывает `Rejected` до разбора тела. Учёт ставит `REJECTED`, пропускает последующую сверку и может отправить другой CID на следующем проходе. | Извлекать биржевой код из `HTTPError`, учитывать `50004` как `Unknown` и сохранять CID для сверки. При неразбираемом ответе на отправку с неопределённым исходом сохранять намерение. [Адаптер](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/exchange/okx.py#L75-L83) · [OKX REST error codes](https://www.okx.com/docs-v5/en/#error-code-rest-api) |
| P1 | **Добор повторно открывает позицию после аварийного стопа.** На 70 000 открывается 0,0071 BTC. На 61 000 стоп закрывает позицию, но живой добор оставляет эпизод в `open`. При отскоке до 72 100 старый добор открывает 0,0069 BTC. | При исполнении аварийного стопа переводить эпизод в завершение, прекращать увеличение, снимать добор и сверять его возможные исполнения до закрытия остатка. [Переход состояния](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/executor.py#L232-L247) |
| P1 | **Аварийная защита отсутствует во время частичного входа.** На имитаторе 0,0028 BTC остаются в `entering` без стопа. Если на открытом эпизоде стоп отклонён и уровень уже пройден, штатный выход выставляет `LIMIT NEW` и оставляет 0,0071 BTC открытыми. По умолчанию `chase` ждёт до 300 с перед рыночным исполнением. | Защищать фактически исполненный объём в фазе входа. Для аварии использовать отдельный переход, запрещающий новый риск и направляющий сверенный остаток в `MARKET` без ожидания `chase`. Проверить частичные исполнения, отмену конкурирующих заявок и изменение размера защиты. [Вход](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/executor.py#L237-L245) · [Аварийная ветка](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/executor.py#L422-L437) · [Тактика выхода](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/executor.py#L451-L459) |
| P1 | **Потолок и объём добора нарушаются.** После IOC-добора 0,0034 из 0,0069 BTC повторный стоп запрашивает полные 0,0069 BTC, итоговый добор 0,0103 BTC, номинал около $1 239 при потолке $1 000. При отмене лимитного входа первого слота перед заменой второй слот занимает освободившееся место. Первый продолжает вход, общий объём 0,0284 BTC, около $1 991 при потолке $1 000. Размер MARKET тоже зафиксирован по цене сигнала, поэтому одиночный вход при движении цены может выйти за расчётный номинал. | Выставлять остаток `goal_add − filled_add`. Держать резерв входа до окончания работы, включая промежуток отмена → замена. Пересчитывать размер перед каждой увеличивающей заявкой. Определить, ограничивает ли `cap_usd` номинал при исполнении или оценку по опорной цене. Для строгого предела при исполнении нужен также предел цены. [Резерв](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/executor.py#L263-L296) · [Добор](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/executor.py#L399-L420) |
| P1 | **Учёт не привязан к счёту и среде.** Для одного `--state-dir` OKX demo и боевой OKX используют один state и журнал. То же у Bybit. Два экземпляра могут загрузить один снимок и отправлять заявки независимо. WEEX игнорирует `testnet:true` при `paper:false` и выбирает боевой клиент. | Привязать состояние к бирже, среде, счёту, символу и владельцу, захватывать эксклюзивную блокировку до загрузки, отклонять неподдерживаемые сочетания флагов до создания клиента. Для демо выделить отдельный счёт и каталог. [Runner](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/run.py#L33-L68) · [WEEX API domain](https://www.weex.com/api-doc/products/futures/QuickStart/APIDomain) |
| P1 для общего счёта | **`reduceOnly` ограничивает общую сторону счёта.** В симуляции цель закрывает 0,0142 BTC, затем до следующего опроса исполняется независимый стоп и уменьшает чужой шорт с 0,0500 до 0,0358 BTC. При ручном закрытии собственный дефицит может быть скрыт чужим остатком. `allowed_sides` по умолчанию допускает обе стороны, включая BTC SHORT на WEEX, если конфиг не задаёт исключение. | Проверять на отдельном счёте или субсчёте. Зафиксировать WEEX BTC `allowed_sides=["LONG"]`, если этот запуск вообще потребуется. Проверить взаимное исключение цели и стопа на конкретной бирже, включая два слота на одной стороне. [Стоп и цель](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/executor.py#L422-L448) · [Разрешённые стороны](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/executor.py#L33-L47) |

## Адаптеры и сверка

- **OKX.** Размер `sz` в контрактах с коэффициентом `ctVal`, `orderPx=-1` и инверсия отрицательного `fee` согласуются с базовым контрактом USDT-SWAP. При `effective` адаптер читает только `ordId`. Поддельный ответ с `ordIdList=["child"]` оставляет `NEW` с нулевым исполнением. Если дочерняя заявка найдена и ещё активна, отмена всё равно посылается родителю. В поддельном HTTP родитель возвращает `51416`, дочерняя остаётся `live`, выход ждёт. Учитывать и отменять дочернюю заявку по её `ordId`, сверять её статус и исполнения отдельно от алгоритма. [Код](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/exchange/okx.py#L148-L189) · [OKX algo order details](https://www.okx.com/docs-v5/en/#order-book-trading-algo-trading-get-algo-order-details) · [Коды OKX](https://www.okx.com/docs-v5/en/#error-code-rest-api)
- **WEEX.** Обычный поиск умеет делить окно и возвращать `Incomplete` при насыщении. Для STOP поддельное `{"hasMore":true,"orders":[…]}` теряет `hasMore` на уровне клиента. Если CID отсутствует на первой странице, адаптер возвращает `None`, что позволяет повторить условную заявку. Проверять полноту списка и искать все страницы либо возвращать `Incomplete`. Отдельно проверить терминальные статусы алгоритма, отмену дочерней заявки и полноту `userTrades`. Пустое тело отправки `{}` уже считается `Unknown`. [История](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/weex_api/client.py#L180-L188) · [Поиск стопа](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/exchange/weex.py#L142-L162)
- **Bybit.** `triggerDirection=1` для BUY и `2` для SELL, `positionIdx=1/2` для сторон в hedge соответствуют API. `StopOrder` документирован для запросов поиска. В `POST cancel` поле `orderFilter` описано для spot, в коде оно посылается и для linear STOP. Сверить на тестнете. Для linear адаптер берёт устаревшее `cumExecFee`. Ответ только с `cumFeeDetail.USDT=0.42` даёт `fee=0, fee_known=True`. [Постановка](https://bybit-exchange.github.io/docs/v5/order/create-order) · [Отмена](https://bybit-exchange.github.io/docs/v5/order/cancel-order) · [Поиск и поля](https://bybit-exchange.github.io/docs/v5/order/open-order)
- **Сверка.** Один `audit_bad` общий для обеих сторон. Дефицит LONG на первом опросе и только SHORT на втором приводят к записи внешнего закрытия SHORT сразу. `_external` также пишет в журнал до сохранения учёта. Хранить счётчик по стороне и сохранять учёт до записи подтверждения. [Код](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/executor.py#L497-L534)
- **Аварийная команда.** `--close-all` делает один обычный `tick`. Во время него свободный слот может открыть новый эпизод, а выход может только поставить первую лимитку или ждать завершения отмен. Закрытие требует блокировки входов, единственного исполнителя и проверки конечного состояния. До отдельного теста нельзя считать успешный код завершения подтверждением закрытия. [Команда](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/run.py#L129-L132) · [Условие нового входа](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/executor.py#L223-L231)

## Ответы на четыре вопроса

1. **Да.** Проверено прерыванием процесса сразу после сохранения `UNKNOWN` и рестартом с `Incomplete`. Рыночный выход отправляется повторно. На OKX есть второй путь без рестарта через HTTP 400 с `50004`.
2. **Нет.** `None` через 120 с показывает отсутствие записи в доступном ответе. Bybit документирует задержку истории и сброс недавних конечных ордеров в realtime при рестарте. Для `51603` OKX не указывает предельную задержку появления заявки. На имитаторе скрытие уже исполненного выхода в поиске на 121 секунду приводит к `ABSENT` и второму закрытию. Использовать приватные события заявок и исполнений с восстановлением после разрыва, поиск по CID/OID, открытые заявки, исполнения и сверку позиции. При неразрешённом исходе блокировать конкурирующую работу и сообщать оператору. Повтор с тем же CID допустим только при документированной идемпотентности нужного метода. [Bybit realtime](https://bybit-exchange.github.io/docs/v5/order/open-order) · [Bybit history](https://bybit-exchange.github.io/docs/v5/order/order-list) · [OKX REST error codes](https://www.okx.com/docs-v5/en/#error-code-rest-api)
3. **Гарантия немедленного исполнения заранее пройденного уровня не подтверждена.** OKX `trigger` с `orderPx=-1` и WEEX `STOP_MARKET` описывают рыночную заявку после срабатывания. Для состояния на момент приёма заявки нужна проверка уровня до, ровно на и после пересечения, включая движение между чтением цены и ответом на постановку. Сравнивать с тем же источником, что и триггер (`last` / `CONTRACT_PRICE`). Текущий локальный предохранитель смотрит bid/ask. На Bybit направление триггера верно, коды `110092/110093` отражают неверное расположение уровня относительно текущей цены. [OKX place algo](https://www.okx.com/docs-v5/en/#order-book-trading-algo-trading-post-place-algo-order) · [WEEX trigger price](https://www.weex.com/help/articles/5498356165785) · [Bybit error codes](https://bybit-exchange.github.io/docs/v5/error)
4. **+$75 против бэктестной базы, около +$54 против немедленного MARKET.** Замер подставляет предыдущую сделку Binance spot вместо bid/ask торговой площадки и по минутному экстремуму зачисляет полный maker-fill. Он не знает момента подтверждения, места в очереди, частичного исполнения или отмены. Даже 2,5 BTC на лучшей цене дают только снимок. Реальный проход сквозь уровень на той же площадке, пока заявка подтверждённо стояла, даёт более сильное свидетельство. Возможны исполнения на касании из-за проторгованного объёма и отмен перед нами. Исполнившиеся maker-заявки и пропуски отбираются движением цены, поэтому сравнивать нужно весь эпизод, включая остаток, догон, комиссии, adverse selection после fill и выход. Следующая проверка — одинаковые сигналы и вневыборочное сравнение с MARKET по записям стакана и сделок той же площадки с временами ack/cancel. [Замер](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/research/sigexec_20261112/limit_tactics.py#L80-L145)

## Данные и границы исторической проверки

- При непрерывном ряде после первого закрытого H4 `j` выбирает последнюю закрытую H4 к концу часа, `B4p` — к его началу. Ранг сравнивает с предыдущими значениями, медиана для веса сдвинута на одну H4. На первой H4 есть пограничное заглядывание через ограничение индекса снизу: синяя в первый час равна 140 на ряде `[100,110,130,140,150]` и 100 на префиксе из первого часа. Убрать сигналы до появления доступной закрытой H4 и покрыть сравнением префиксов. [Линии](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/lines.py#L86-L123)
- `HourFeed` принимает пропущенный час и отмечает ряд свежим. В тесте 20 000 свечей с разрывом 7 200 с дают `fresh=True`. Последующие загрузки начинаются после последней свечи, пропуск сам не заполняется. Валидировать сетку времени, дозагружать недостающий час до пересчёта. Если поток уже помечен несвежим, `step(None)` снимает последнюю подтверждённую цель шорта. При переходе цены за прежнюю цель шорт остаётся открыт. Зафиксировать поведение при устаревании данных. [Кэш](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/feed.py#L79-L104) · [Цель](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/executor.py#L438-L448)
- Полугодовой тест подаёт события одного прогона движка, с MARKET на входе и выходе и потолком в десять баз. Он сравнивает закрытые сделки с допуском. Для паритета живого режима отдельно нужны инкрементальная подача в `Runner`, штатные тактики, устойчивость к разрывам и проверка отсутствия лишних эпизодов. [Replay](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/services/sigexec/replay.py#L56-L97) · [Тест](https://github.com/alexey-chechikov/chat-bot-v2/blob/239b426/tests/services/sigexec/test_lines_adapters.py#L210-L225)

## Проверка перед демо

Сначала превратить воспроизведения P1 в тесты ожидаемого безопасного поведения. Затем на отдельном demo/testnet аккаунте в hedge-режиме проверить минимум и шаг объёма, post-only с частичным исполнением, добор, стоп, цель, отмену до/после срабатывания, потерянный ответ, рестарт, финальный остаток и комиссии. Тестировать закрытие только при заблокированных входах, с подтверждением нулевой позиции и отсутствия незавершённых заявок. Выбор OKX demo или Bybit testnet зависит от доступных ключей оператора и целевой биржи.

## Локальные результаты и воспроизведение

- 43 штатных теста прошли без изменений. Полугодовой replay с локальными frozen-минутками прошёл после повторов `Path.replace` при временном `WinError 5` в тестовом процессе (27 повторов). Без повторов прогон на Windows останавливался на записи состояния. Код ветки для проверки не менялся. Общий прогон проекта на 1 591 тест в рамках этого ревью не повторялся.
- 22 проверки ниже подтвердили наблюдения на точном коммите. Сохранить блок как `repro_sigexec_239b426.py` в корне checkout `239b426` и запустить `python -m pytest -q repro_sigexec_239b426.py`. Утверждения фиксируют наблюдаемое поведение, включая ошибочные результаты.

```python
"""Offline reproductions against 239b426. Assertions describe the observed defects."""

import io
import json
from urllib.error import HTTPError

import numpy as np
import pytest

from services.sigexec import lines, run
from services.sigexec.exchange.base import LONG, SHORT, SELL, OrderReq, Rejected, Unknown
from services.sigexec.exchange.bybit import parse_order
from services.sigexec.exchange.okx import OkxExchange
from services.sigexec.exchange.sim import SimExchange
from services.sigexec.exchange.weex import WeexExchange
from services.sigexec.executor import Executor
from services.sigexec.feed import H1, MIN_HOURS, HourFeed
from services.sigexec.strategy import Desired
from services.weex_api.client import WeexClient


T = 1_800_000_000


def signal(slot="system", **overrides):
    values = dict(slot=slot, entry_t=T, side=1, tag="probe", w=1, sig_px=70000,
                  main_frac=0.5, add_lv=72000, add_frac=0.5, add_done=False,
                  target=None, exit_by_t=None, exit_text="")
    return Desired(**(values | overrides))


def build(path, exchange=None, **overrides):
    exchange = exchange or SimExchange()
    exchange._t = T + 5
    cfg = {"enabled": True, "base_usd": 1000, "cap_usd": 5000} | overrides
    return Executor(exchange, cfg, path / "state.json", path / "journal.jsonl"), exchange


def orders(executor, role):
    return [record for record in executor.st["orders"].values() if record["role"] == role]


def test_duplicate_market_exit_after_process_loss(tmp_path):
    executor, exchange = build(tmp_path, entry={"kind": "market"}, exit={"kind": "market"})
    desired = {"system": signal(add_lv=None, add_frac=0)}
    executor.step(desired)
    executor.step(desired)
    exchange.external_trade(LONG, 0.01)
    exchange.fail_next("place", "unknown_placed")
    write_journal = executor._jr

    def lose_process(record):
        if record.get("role") == "exit":
            raise SystemExit("process lost immediately after durable UNKNOWN")
        write_journal(record)

    executor._jr = lose_process
    with pytest.raises(SystemExit):
        executor.step({})
    saved = json.loads(executor.state_path.read_text(encoding="utf-8"))
    assert saved["slots"]["system"]["ep"]["work"]["cur"] is None
    assert [row["status"] for row in saved["orders"].values() if row["role"] == "exit"] == ["UNKNOWN"]
    assert exchange.pos[LONG] == pytest.approx(0.01)
    restarted = Executor(exchange, executor.cfg, executor.state_path, executor.journal_path)
    exchange.fail_next("order", "incomplete")
    restarted.step({})
    assert [(row["kind"], row["status"]) for row in orders(restarted, "exit")] == [
        ("MARKET", "UNKNOWN"), ("MARKET", "FILLED"),
    ]
    assert exchange.pos[LONG] == pytest.approx(0.0029)


def test_breached_emergency_level_uses_chase(tmp_path):
    executor, exchange = build(tmp_path, entry={"kind": "market"})
    desired = {"system": signal(add_lv=None, add_frac=0)}
    executor.step(desired)
    exchange.fail_next("place", "reject")
    executor.step(desired)
    exchange.move(60000)
    executor.step(desired)
    assert [(row["kind"], row["status"]) for row in orders(executor, "exit")] == [("LIMIT", "NEW")]
    assert exchange.pos[LONG] == pytest.approx(0.0071)


def test_pending_add_reopens_position_after_emergency_stop(tmp_path):
    executor, exchange = build(tmp_path, entry={"kind": "market"})
    desired = {"system": signal()}
    executor.step(desired)
    executor.step(desired)
    exchange.move(61000)
    executor.step(desired)
    executor.step(desired)
    assert exchange.pos[LONG] == 0
    assert executor.st["slots"]["system"]["ep"]["phase"] == "open"
    assert [row["status"] for row in orders(executor, "add")] == ["UNTRIGGERED"]
    exchange.move(72100)
    executor.step(desired)
    assert exchange.pos[LONG] == pytest.approx(0.0069)


def test_target_and_stop_can_both_close_same_side(tmp_path):
    executor, exchange = build(tmp_path, entry={"kind": "market"})
    desired = {"system": signal(side=-1, main_frac=1, add_lv=None, add_frac=0, target=68000)}
    exchange.external_trade(SHORT, 0.05)
    executor.step(desired)
    executor.step(desired)
    exchange.move(67000)
    assert exchange.pos[SHORT] == pytest.approx(0.05)
    exchange.move(80000)
    assert exchange.pos[SHORT] == pytest.approx(0.0358)
    executor.step(desired)
    assert sum(row["filled"] for row in orders(executor, "target") + orders(executor, "stop")) == pytest.approx(0.0284)


def test_stale_feed_cancels_confirmed_target(tmp_path):
    executor, exchange = build(tmp_path, entry={"kind": "market"})
    desired = {"system": signal(side=-1, add_lv=None, add_frac=0, target=68000)}
    executor.step(desired)
    executor.step(desired)
    assert [row["status"] for row in orders(executor, "target")] == ["NEW"]
    executor.step(None)
    assert [row["status"] for row in orders(executor, "target")] == ["CANCELED"]
    exchange.move(67000)
    assert exchange.pos[SHORT] == pytest.approx(0.0071)


def test_120_seconds_missing_replaces_filled_exit(tmp_path):
    executor, exchange = build(tmp_path, entry={"kind": "market"}, exit={"kind": "market"})
    desired = {"system": signal(add_lv=None, add_frac=0)}
    executor.step(desired)
    executor.step(desired)
    exchange.external_trade(LONG, 0.01)
    exchange.fail_next("place", "unknown_placed")
    executor.step({})
    cid = orders(executor, "exit")[0]["cid"]
    visible_order = exchange.order
    exchange.order = lambda symbol, key, *args: None if key == cid else visible_order(symbol, key, *args)
    exchange.tick_clock(121)
    executor.step({})
    assert [row["status"] for row in orders(executor, "exit")] == ["ABSENT", "FILLED"]
    assert exchange.pos[LONG] == pytest.approx(0.0029)


def test_partial_entry_has_no_exchange_stop(tmp_path):
    executor, exchange = build(tmp_path)
    desired = {"system": signal(add_lv=None, add_frac=0)}
    executor.step(desired)
    exchange.partial_next(0.4)
    exchange.move(69990)
    executor.step(desired)
    assert executor.st["slots"]["system"]["ep"]["phase"] == "entering"
    assert exchange.pos[LONG] == pytest.approx(0.0028)
    assert not orders(executor, "stop")


def test_partial_add_stop_reissues_full_size(tmp_path):
    executor, exchange = build(tmp_path, cap_usd=1000, entry={"kind": "market"})
    desired = {"system": signal()}
    executor.step(desired)
    executor.step(desired)
    exchange.partial_next(0.5)
    exchange.move(72100)
    exchange.move(71000)
    executor.step(desired)
    assert [(row["qty"], row["filled"]) for row in orders(executor, "add")] == [
        (0.0069, 0.0034), (0.0069, 0.0),
    ]
    exchange.move(72100)
    executor.step(desired)
    assert sum(row["filled"] for row in orders(executor, "add")) == pytest.approx(0.0103)
    assert sum(row["filled"] * row["avg"] for row in orders(executor, "entry") + orders(executor, "add")) > 1200


def test_cap_loses_reservation_on_entry_cancel(tmp_path):
    executor, exchange = build(tmp_path, cap_usd=1000,
                               entry={"kind": "chase", "wait_s": 10, "reprice_s": 300})
    desired = {"system": signal(main_frac=1, add_lv=None, add_frac=0)}
    executor.step(desired)
    exchange.tick_clock(11)
    both = desired | {"432": signal(slot="432", main_frac=1, add_lv=None, add_frac=0)}
    executor.step(both)
    assert [(row["kind"], row["status"]) for row in orders(executor, "entry")] == [
        ("LIMIT", "CANCELED"), ("LIMIT", "NEW"),
    ]
    executor.step(both)
    exchange.move(69990)
    executor.step(both)
    assert exchange.pos[LONG] == pytest.approx(0.0284)
    assert sum(row["filled"] * row["avg"] for row in orders(executor, "entry")) > 1900


def test_market_can_fill_above_cap_sized_at_signal_price(tmp_path):
    executor, exchange = build(tmp_path, SimExchange(price=77000), cap_usd=1000, entry={"kind": "market"})
    executor.step({"432": signal(slot="432", main_frac=1, add_lv=None, add_frac=0)})
    fill, = orders(executor, "entry")
    assert fill["filled"] * fill["avg"] == pytest.approx(1093.51, abs=0.01)


def test_okx_timeout_with_http_400_becomes_final_reject():
    def http(method, url, headers, data):
        if "/public/instruments" in url:
            return {"code": "0", "data": [{"ctVal": "0.01", "tickSz": "0.1", "lotSz": "0.01", "minSz": "0.01"}]}
        raise HTTPError(url, 400, "Bad Request", {}, io.BytesIO(b'{"code":"50004","msg":"Endpoint request timeout","data":[]}'))

    exchange = OkxExchange(http=http)
    req = OrderReq(cid="test", symbol="BTCUSDT", side=SELL, pos_side=LONG,
                   kind="MARKET", qty=0.01, reduce_only=True)
    with pytest.raises(Rejected, match="HTTP 400"):
        exchange.place(req)


def test_weex_testnet_uses_production_factory(tmp_path, monkeypatch):
    production = object()
    monkeypatch.setattr(WeexExchange, "from_env", lambda: production)
    assert run.make_exchange({"name": "weex", "paper": False, "testnet": True}, tmp_path) is production


def test_demo_and_live_share_state(tmp_path):
    cfg = {"exchange": {"name": "okx", "paper": False}, "feed": {}, "executor": {}}
    demo_cfg = cfg | {"exchange": cfg["exchange"] | {"testnet": True}}
    demo = run.Runner(demo_cfg, tmp_path, exchange=SimExchange(), feed=object())
    live = run.Runner(cfg, tmp_path, exchange=SimExchange(), feed=object())
    assert demo.exe.state_path == live.exe.state_path
    assert demo.exe.journal_path == live.exe.journal_path


def test_two_writers_lose_first_entry_from_ledger(tmp_path):
    first, exchange = build(tmp_path, entry={"kind": "market"})
    second = Executor(exchange, first.cfg, first.state_path, first.journal_path)
    desired = {"system": signal(add_lv=None, add_frac=0)}
    first.step(desired)
    exchange.tick_clock(1)
    second.step(desired)
    assert exchange.pos[LONG] == pytest.approx(0.0142)
    persisted = Executor(exchange, first.cfg, first.state_path, first.journal_path)
    assert sum(row["filled"] for row in orders(persisted, "entry")) == pytest.approx(0.0071)


def test_close_all_tick_can_open_an_idle_slot(tmp_path):
    executor, exchange = build(tmp_path, entry={"kind": "market"})
    desired = {"system": signal(add_lv=None, add_frac=0)}
    executor.step(desired)
    executor.step(desired)
    executor.close_all()
    executor.step(desired | {"432": signal(slot="432", add_lv=None, add_frac=0)})
    assert [row["kind"] for row in orders(executor, "exit")] == ["LIMIT"]
    assert len(orders(executor, "entry")) == 2
    assert exchange.pos[LONG] == pytest.approx(0.0142)


def test_okx_effective_algo_child_list_is_ignored():
    def http(method, url, headers, data):
        if "/public/instruments" in url:
            return {"code": "0", "data": [{"ctVal": "0.01", "tickSz": "0.1", "lotSz": "0.01", "minSz": "0.01"}]}
        assert "/trade/order-algo" in url
        return {"code": "0", "data": [{"state": "effective", "algoId": "a", "ordIdList": ["child"]}]}

    order = OkxExchange(http=http).order("BTCUSDT", "test", "STOP")
    assert (order.status, order.filled) == ("NEW", 0)


def test_okx_cancel_targets_parent_after_child_starts():
    cancel_calls = []

    def http(method, url, headers, data):
        if "/public/instruments" in url:
            return {"code": "0", "data": [{"ctVal": "0.01", "tickSz": "0.1", "lotSz": "0.01", "minSz": "0.01"}]}
        if method == "POST":
            cancel_calls.append((url.rsplit("/", 1)[-1], json.loads(data)))
            return {"code": "1", "data": [{"sCode": "51416", "sMsg": "Triggered"}]}
        if "/trade/order-algo" in url:
            return {"code": "0", "data": [{"state": "effective", "algoId": "parent", "ordId": "child"}]}
        assert "ordId=child" in url
        return {"code": "0", "data": [{"state": "live", "ordId": "child", "accFillSz": "0"}]}

    exchange = OkxExchange(http=http)
    assert exchange.order("BTCUSDT", "test", "STOP").status == "NEW"
    with pytest.raises(Unknown, match="51416"):
        exchange.cancel("BTCUSDT", "test", "STOP", "parent")
    assert cancel_calls == [("cancel-algos", [{"instId": "BTC-USDT-SWAP", "algoId": "parent"}])]
    assert exchange.order("BTCUSDT", "test", "STOP").status == "NEW"

def test_weex_partial_algo_history_is_taken_as_absence(monkeypatch):
    client = object.__new__(WeexClient)
    monkeypatch.setattr(client, "open_algo_orders", lambda symbol: [])
    monkeypatch.setattr(client, "get", lambda *args: {"hasMore": True, "orders": [{"clientAlgoId": "another"}]})
    assert WeexExchange(client).order("BTCUSDT", "missing", "STOP") is None


def test_bybit_ignores_current_fee_field():
    order = parse_order({"orderStatus": "Filled", "cumExecQty": "0.01", "avgPrice": "70000",
                         "cumFeeDetail": {"USDT": "0.42"}})
    assert (order.fee, order.fee_known) == (0.0, True)


def test_audit_counts_two_different_sides_as_two_deficits(tmp_path):
    executor, exchange = build(tmp_path, entry={"kind": "market"})
    desired = {"system": signal(add_lv=None, add_frac=0),
               "432": signal(slot="432", side=-1, add_lv=None, add_frac=0)}
    executor.step(desired)
    executor.step(desired)
    exchange.external_trade(LONG, -0.005)
    executor.step(desired)
    assert not orders(executor, "external")
    exchange.external_trade(LONG, 0.005)
    exchange.external_trade(SHORT, -0.005)
    executor.step(desired)
    external, = orders(executor, "external")
    assert external["ep"] == f"432:{T}"
    assert external["filled"] == pytest.approx(0.005)


def test_gap_in_hourly_feed_is_fresh(tmp_path):
    class Source:
        def fetch(self, start, now):
            return [(t, 100, 101, 99, 100) for t in range(H1, (MIN_HOURS + 2) * H1, H1)
                    if t != (MIN_HOURS - 5) * H1]

    feed = HourFeed(tmp_path / "hours.csv", Source())
    now = (MIN_HOURS + 1) * H1
    assert feed.update(now) == MIN_HOURS
    assert max(np.diff(feed.t)) == 2 * H1
    assert feed.fresh(now)


def test_first_hour_uses_future_first_h4_close():
    t = np.arange(1, 6) * H1
    px = np.array([100, 110, 130, 140, 150])
    complete, _ = lines.build(t, px, px, px, px)
    prefix, _ = lines.build(t[:1], px[:1], px[:1], px[:1], px[:1])
    assert (complete["B4p"][0], prefix["B4p"][0]) == (140, 100)
```
