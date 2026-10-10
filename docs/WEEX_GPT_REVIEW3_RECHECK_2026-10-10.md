# WEEX Review3: независимая перепроверка исправлений

Дата: 10 октября 2026 года. Репозиторий `alexey-chechikov/chat-bot-v2`, ветка `alexey/mac-2026-05-29`. Закреплённый исходный коммит **c844df6fbe4e7092b8b508489586f2239070754f**, торговые исправления — из `3173dfb`. Старый контроль: **9cc641e8e0c6746eefe1a6e1440a233f1f9041d1**. Проверены ответы `WEEX_GPT_REVIEW3_ANSWERS_2026-10-10.md`, engine/loop/client, тесты сетки и `pnl_reconcile.py`.

Все проверки офлайн, с имитаторами. Ключи и `.env.local` не читались, приватных запросов и сделок не было. Рабочий код и состояние работающих ботов не менялись. Заявление о живом совпадении с биржей и 683 тестах всего проекта здесь не подтверждается: это данные автора, отдельно от воспроизведённой проверки 61 теста сетки.

## Результат

**Исходные пять сценариев исправлены.** Независимый первый прогон дал **61 passed**, включая все 10 новых тестов. Дополнительно подтверждены сохранение сироты перед отменой с падением/довыполнением, реальная гонка команды с проходом, сброс кэша баланса и ненулевой код сверки при расхождении/неполноте.

При этом обнаружены **пять дополнительных комбинаций событий**: два P1 и три P2. Они не доказывают расхождение на текущем счёте; это воспроизводимые оставшиеся дефекты проверенного кода. Два дефекта досверки комиссий дают регрессию относительно 9cc в соответствующих контролях.

## Подтверждённые изменения

| Исправление | Независимое подтверждение | Граница доказательства |
|---|---|---|
| Сирота сохраняется до отмены | Исходный тест проходит; дополнительное исполнение .0004 → .0008 → .0012 с crash/restart учитывается ровно один раз | Дополнительная потеря привязки TP — отдельный случай ниже |
| live→dry продолжает сопровождение | `_live_leftovers` учитывает strays и fee_book; тест позднего исполнения сироты проходит | Неустранённый pending может блокировать известный вход |
| Неполный поиск не очищает pending | Заполненные 10 страниц сохраняют намерение, блокируют новые постановки, уведомляют один раз | Правильность временного окна и сопровождение других ордеров не проверяются этим тестом |
| Удалённая сторона продолжает жить | Поздний fill снятой LONG-стороны учтён, TP поставлен, новых LONG-входов нет | То же ограничение pending |
| Курсор живого ордера и миграция | Оба regression-теста проходят; комиссия не добавляется повторно после часа и после миграции fee_done | Временная глубина и прогресс общей досверки — отдельные дефекты |
| Поздняя комиссия за первой сотней | Исходный тест с 150 более новыми сделками проходит | На длинной/плотной истории не обеспечен прогресс |
| Стоящий вход после снижения cap | Проверяется по своей цене и количеству; точный пограничный тест проходит | Это не ограничение убытка уже набранной позиции |
| Команда /weex start и цикл | Сильный дополнительный тест вызывает настоящие Runner.tick и command: новый код ждёт проход, затем сохраняет halted=false | Один процесс; несколько владельцев состояния этим RLock не синхронизируются |
| Баланс после ошибки | После успешных $3300 и ошибки чтения кэш и результат равны None | Это проверка обработки ошибки, не сверка equity счёта |
| Независимая BTC-сверка | Совпадение → exit0; комиссия отличается на $0.02 → exit1; переполненное секундное окно → exit1; API exception не становится успехом | Funding и полный капитал счёта исключены самим скриптом |

## 1. [P1] Неподтверждённый тейк мешает остановить известный вход

Код: [engine.py:763](https://github.com/alexey-chechikov/chat-bot-v2/blob/c844df6fbe4e7092b8b508489586f2239070754f/services/weex_grid/engine.py#L763). `_side` возвращается, если `_resolve_pending` не закончен, до учёта/отмены известного входа и проверки enabled.

Последовательность: вход .0012 частично исполнен на .0004; ответ постановки TP потерян; поиск pending не даёт полного результата; оператор ставит `enabled=false`, как делает `/weex stop`.

**Получено:** известный вход остаётся NEW, cancel не вызван. После ещё одного исполнения на бирже позиция .0012, а в лотах бота пока .0004. Это не утверждение о безвозвратной потере: после разрешения pending учёт может догнать биржу. Но во время неопределённости stop не снимает известный вход и риск продолжает увеличиваться. Сочетание возможно также при live→dry и снятии стороны.

**Исправить:** барьер pending должен запрещать конфликтующие новые постановки, а сопровождение известных ордеров должно продолжаться: чтение и учёт fills, отмена входа при остановке/лимите/снятии стороны. Нельзя поверх неизвестного TP ставить второй конфликтующий TP. Тест: partial entry + timeout TP + incomplete history + stop; затем позднее исполнение входа.

Доказательство: `risk_probes.py:pending_stop_probe`, `risk_probes.json.pending_stop`.

## 2. [P1, при потере привязки TP] Дополнительная часть до восстановления учитывается повторно

Код: [engine.py:535](https://github.com/alexey-chechikov/chat-bot-v2/blob/c844df6fbe4e7092b8b508489586f2239070754f/services/weex_grid/engine.py#L535), fallback обработки сироты — строки 558–585.

Исходный тест автора теряет привязку после уже учтённой части и восстанавливает её при неизменном cumulative executedQty. Добавлен следующий шаг: до восстановления биржа исполняет ещё часть.

| Величина | Биржа / правильный результат | Получено ботом |
|---|---:|---:|
| Исходный вход | .0012 | .0012 |
| Уже учтённый TP до потери привязки | .0004 | .0004 |
| Новая фактическая часть TP | .0002 | .0006 повторно засчитано как новое |
| Остаток после всех fills | .0006 | .0002 |
| Новый realized | $0.05988 | $0.17964 |
| Новый оборот закрытия | $20.01988 | $60.05964 |

Условие `lot qty == origQty − current executedQty` больше не совпадает: лот .0008, текущий остаток заявки .0006. Fallback получает filled=0 и считает весь cumulative .0006 заново. После restart расхождение сохраняется. Контроль с сохранённой привязкой даёт точные .0006 и правильные деньги.

**Ограничение:** самопроизвольное возникновение потери привязки не доказано. Это расширение ровно того состояния, которое уже имитирует regression-тест автора. Обычный путь с сохранённой mapping в этом probe корректен.

**Исправить:** долговечный курсор исполненного количества по orderId должен переживать потерю связи с лотом. При восстановлении считать только `current cumulative − already accounted`; неоднозначность сопоставления не разрешать угадыванием по одному текущему количеству. Сохранить происхождение лота/ордера, не оставлять открытый остаток без соответствующего учёта. Тест: потеря mapping после partial, новый partial до сканирования, restart и повторная сверка.

Доказательство: `lifecycle_probe.py:lost_tp_then_new_partial`, `lifecycle_results.json`; контроль `lost_mapping=false`.

## 3. [P2, при рассогласовании часов] История pending ищется по локальному времени

Код: [engine.py:430](https://github.com/alexey-chechikov/chat-bot-v2/blob/c844df6fbe4e7092b8b508489586f2239070754f/services/weex_grid/engine.py#L430); timestamp намерения — строки 401–402; серверный offset подписи — client.py:70–78.

Клиент синхронизирует подпись запроса с биржей через `_offset_ms`, но время намерения и фильтры истории используют локальные часы. Поэтому принятая заявка может оказаться вне окна ±120 секунд, хотя подпись запроса валидна.

**Probe:** часы биржи на 180 секунд впереди; вход .0012 принят и полностью исполнен, ответ потерян. В открытых ордерах его уже нет. История честно фильтруется по серверному времени и возвращает пустое локальное окно. Через 130 локальных секунд pending очищается, исполненная позиция в учёте равна 0, создаётся второй вход.

Это условие разницы часов больше двух минут, не проблема часового пояса и не утверждение о текущих часах VPS. Штатный DryExchange.order_history игнорирует start/end, поэтому исходный тест эту границу не обнаруживает.

**Исправить:** сохранять время намерения в сопоставимой серверной шкале, учитывать неопределённость синхронизации; локальную длительность TTL отсчитывать монотонными часами. Старые pending без достоверной шкалы не очищать по одному узкому окну. Адресный поиск по clientOrderId, если доступен в адаптере, предпочтительнее неподтверждённого заключения «не дошёл».

Доказательство: `risk_probes.py:clock_offset_pending_probe`, `risk_probes.json.clock_offset_pending`.

## 4. [P2] Старый живой курсор создаёт запрещённое окно комиссии

Код: [engine.py:289](https://github.com/alexey-chechikov/chat-bot-v2/blob/c844df6fbe4e7092b8b508489586f2239070754f/services/weex_grid/engine.py#L289). По [официальному WEEX userTrades](https://www.weex.com/api-doc/contract/Transaction_API/GetTradeDetails) интервал startTime/endTime не может превышать семь суток; это же ограничение записано в клиенте.

Старейший живой курсор теперь сохраняется правильно, но общая досверка отправляет единое окно `oldest−600 … now+60`. Деление начинается только после успешного ответа. Если ордер живёт больше недели, исходный запрос уже превышает разрешённый интервал и исключение ловится до деления.

**Получено:** живой восьмидневный курсор вызывает один запрос на **8.007638889 суток**. Поздняя комиссия другого свежего завершённого ордера $0.05 остаётся $0. После удаления старого курсора та же комиссия учитывается. Старый 9cc в этом же fake учитывает свежие $0.05, хотя имеет независимый ранее обнаруженный дефект истечения живого курсора.

**Исправить:** разбивать по допустимой длительности ДО запроса API; сохранять прогресс и дедупликацию. Простое удаление старых курсоров вернёт прежний дефект.

Доказательство: `fees_probe.py:seven_day_probe`, `fees_probe.json.seven_day_limit`; fake соблюдает документированный максимум окна, это не ответ приватного WEEX API.

## 5. [P2] Лимит 64 запросов выбрасывает свежие уже полученные данные

Код: [engine.py:265](https://github.com/alexey-chechikov/chat-bot-v2/blob/c844df6fbe4e7092b8b508489586f2239070754f/services/weex_grid/engine.py#L265), плюс общий запуск диапазона в 289–303.

Рекурсия идёт в старую половину первой и заменяет родительские строки дочерними. При исчерпании бюджета новая половина возвращает пустой неполный результат; найденные в первых 100 записях свежие комиссии теряются из результата. Следующий проход без сохранённого continuation вновь начинает старое начало.

**Получено:** 8001 сделка за пять суток, старый живой курсор, свежая поздняя комиссия $0.05 уже присутствует в корневом ответе. Проходы на t=0, +60, +120 секунд выполняют по 64 запроса; комиссия каждый раз остаётся $0. После удаления старого курсора она учитывается. Старый 9cc в том же fake учитывает свежие $0.05.

**Исправить:** сохранять и дедуплицировать уже полученные родительские строки даже при неполноте; отдельно хранить продолжение незавершённого обхода либо проверять комиссии ограниченными адресными окнами. Полнота, прогресс и уже доказанные суммы — разные состояния. Нужен тест нескольких последовательных проходов, а не только одного окна с 150 сделками.

Доказательство: `fees_probe.py:budget_probe`, `fees_probe.json.request_budget_starvation`.

## Что уточнить в доказательстве «10 старых падают / 10 новых проходят»

Сырой перенос нового test_weex_grid_review3.py на старый snapshot действительно дал **10 failed**. Однако три первоначальных падения вызваны изменёнными тестовыми интерфейсами: новый аргумент now_fn у DryExchange, отсутствующее поле time в его сделках и отсутствующий STATE_LOCK.

Для отделения этих причин старому production-коду оставлены прежние функции, заменён только имитатор на новый и добавлен тестовый RLock без оборачивания старых entrypoints. Результат: **9 failed по поведенческим assertions, 1 passed**. Прошёл как раз тест, проверяющий работу самого RLock: он не вызывает ни Runner.tick, ни command и не обнаружил бы удаление guard при сохранении переменной.

Отдельный сильный probe вызывает оба настоящих entrypoint. Старый 9cc: command заканчивается до tick, затем tick перезаписывает halted=true. Новый: command ждёт tick, затем halted=false. Таким образом само исправление гонки подтверждено, но regression-тест следует усилить.

Первый немодифицированный прогон новой сетки: **61 passed**. При повторных запусках в этой Windows-среде возникали отдельные PermissionError/WinError5 на os.replace; это не failures торговых assertions. Финальный контроль с тестовой обёрткой, повторяющей только исходную атомарную запись при PermissionError, дал **61 passed** и прежние **9 failed / 1 passed** на старом коде. Обёртка отмечена флагом --io-retry; production/snapshot не изменены. Этот запуск проверяет торговую логику, не надёжность файловой системы Windows. Источник обёртки включён в приложение.

## Что остаётся прежним

Funding в денежном учёте, полная equity-сверка счёта, разделение ручной позиции и атрибуция старого/нового inventory ещё не реализованы — автор это явно признаёт. Успех BTC pnl_reconcile проверяет атрибутированные исполнения и trading commissions на mid, не весь счёт, ETH/XAU или цену реального закрытия. Он не доказывает положительное ожидание сетки.

Приоритет исправлений: **pending не должен блокировать остановку известных входов**, затем долговечный order-fill cursor при восстановлении TP. После этого — шкала времени и возобновляемая комиссионная досверка. Торговые эксперименты и матожидание требуют отдельной проверки; текущая перепроверка их не заменяет.

## Воспроизводимые приложения

Ниже включены исходники офлайн-пробников и их JSON-результаты. Они утверждают наблюдаемый контрпример; exit0 означает, что контрпример воспроизведён. После исправления их нужно превратить в regression-тесты, утверждающие правильный результат. Пути snapshot в пробниках относятся к локальному набору исходников, закреплённых source_manifest.json; при переносе сохранить эту структуру. `run_offline_tests.py` также использует предыдущий архив 9cc для сравнительного запуска, не загружает старый код самостоятельно.

<details>
<summary>run_offline_tests.py</summary>

```python
"""Run grid tests in isolated source snapshots with credentials/network blocked."""
import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import threading
import urllib.request

HERE = Path(__file__).resolve().parent

if len(sys.argv) > 1 and sys.argv[1] == '--worker':
    root, selector, result = Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
    sys.path.insert(0, str(root))
    from services.weex_api import client
    def blocked(*args, **kwargs):
        raise AssertionError('Offline audit: credentials and HTTP are blocked')
    client.load_credentials = blocked
    urllib.request.urlopen = blocked
    worker_flags = sys.argv[5:]
    if '--io-retry' in worker_flags:
        from services.weex_grid import engine
        original_atomic_write = engine.atomic_write
        def retry_atomic_write(*args, **kwargs):
            for attempt in range(7):
                try:
                    return original_atomic_write(*args, **kwargs)
                except PermissionError:
                    if attempt == 6:
                        raise
                    time.sleep(.01 * (2**attempt))
        engine.atomic_write = retry_atomic_write
    if '--adapt-old-fixtures' in worker_flags:
        from services.weex_grid import engine, loop
        spec = importlib.util.spec_from_file_location('_audit_new_dry', HERE/'snapshot/services/weex_grid/engine.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        engine.DryExchange = module.DryExchange
        # The existing lock test only tests this object. Old entrypoints remain unguarded.
        loop.STATE_LOCK = threading.RLock()
    import pytest
    raise SystemExit(pytest.main([selector, '-q', '--tb=short',
        '--basetemp='+str(result.parent/(result.stem+'_temp')),
        '--junitxml='+str(result)]))

old_source = HERE.parent/'weex_review2_20261010'
old_target = HERE/'old_9cc_with_review3_tests'
old_manifest = json.loads((old_source/'source_manifest.json').read_text(encoding='utf-8'))
for record in old_manifest['files']:
    name = record['path']
    if not (name.startswith(('services/', 'tests/')) or name in ('conftest.py', 'pytest.ini')):
        continue
    source, dest = old_source/'snapshot'/name, old_target/name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
test_name = 'tests/services/weex_grid/test_weex_grid_review3.py'
shutil.copyfile(HERE/'snapshot'/test_name, old_target/test_name)
logs = HERE/'verification'
logs.mkdir(exist_ok=True)
summary = []
run_id = str(time.time_ns())
worker_env = dict(os.environ)
worker_env['PYTHONIOENCODING'] = 'utf-8'
for label, root, selector, extra in [('current_61_io_retry', HERE/'snapshot', 'tests/services/weex_grid', ['--io-retry']),
                              ('old_adapted_fixtures_io_retry', old_target, test_name, ['--adapt-old-fixtures', '--io-retry'])]:
    start = time.monotonic()
    result = logs/(label+'_'+run_id+'.xml')
    run = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker',
                          str(root), selector, str(result), *extra], cwd=root,
                         env=worker_env, capture_output=True, timeout=90)
    (logs/(label+'_'+run_id+'.stdout.txt')).write_bytes(run.stdout)
    (logs/(label+'_'+run_id+'.stderr.txt')).write_bytes(run.stderr)
    summary.append({'label': label, 'exit_code': run.returncode,
                    'seconds': round(time.monotonic()-start, 3), 'junit': str(result)})
(logs/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
print(json.dumps(summary, indent=2))
```

</details>

<details>
<summary>risk_probes.py</summary>

```python
"""Offline review3 probes. No credentials, exchange access, or application writes."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

BASE = Path(__file__).resolve().parent
SNAPSHOT = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "snapshot"
sys.path.insert(0, str(SNAPSHOT))
from services.weex_grid import engine as eg
from services.weex_grid import loop as lp


class Px:
    mid = 100_000.0
    def __call__(self):
        return self.mid - .05, self.mid + .05


def fresh(name: str, **changes):
    folder = BASE / ("risk_probe_" + name)
    folder.mkdir(exist_ok=True)
    state = folder / "state.json"
    journal = folder / "journal.jsonl"
    state.unlink(missing_ok=True)
    journal.unlink(missing_ok=True)
    clock = {"t": 1_800_000_000.0}
    px = Px()
    exchange = eg.DryExchange(px, now_fn=lambda: clock["t"])
    cfg = {**eg.DEFAULT, "enabled": True, "dry_run": True, "sides": ["LONG"],
           "order_qty": "0.0012", "stress_budget_frac": 0.0, **changes}
    grid = eg.Grid(exchange, cfg, state_path=state, journal_path=journal,
                   now_fn=lambda: clock["t"])
    return grid, exchange, clock, px


def pending_stop_probe():
    grid, ex, clock, _ = fresh("pending_stop")
    grid.tick()
    entry = grid.st["LONG"]["entry"]
    ex.orders[entry["id"]].update(executedQty="0.0004", avgPrice=str(entry["price"]))
    real_place = ex.place_limit
    def missing_tp_response(*args, **kwargs):
        if kwargs.get("reduce_only"):
            raise TimeoutError("simulated unknown TP placement result")
        return real_place(*args, **kwargs)
    ex.place_limit = missing_tp_response
    grid.tick()
    assert grid.st["LONG"]["pending"]["kind"] == "t"
    # Precisely the persisted setting changed by /weex stop.
    grid.cfg["enabled"] = False
    full = [{"orderId": f"manual{i}", "clientOrderId": f"manual{i}"} for i in range(100)]
    ex.order_history = lambda *args, **kwargs: full
    cancellations = []
    real_cancel = ex.cancel
    ex.cancel = lambda oid: (cancellations.append(oid), real_cancel(oid))[1]
    clock["t"] += 300
    grid.tick()
    first = {"enabled": grid.cfg["enabled"], "entry_status": ex.orders[entry["id"]]["status"],
             "cancel_calls": cancellations[:], "pending": bool(grid.st["LONG"]["pending"]),
             "accounted_qty": sum(float(l["qty"]) for l in grid.st["LONG"]["lots"])}
    # The still-live entry fills more while the side is frozen by a TP intent.
    ex.orders[entry["id"]].update(status="FILLED", executedQty="0.0012")
    clock["t"] += 10
    grid.tick()
    first["exchange_qty_after_additional_fill"] = 0.0012
    first["accounted_qty_after_additional_fill"] = sum(float(l["qty"]) for l in grid.st["LONG"]["lots"])
    assert not cancellations and first["entry_status"] == "NEW"
    assert first["accounted_qty_after_additional_fill"] == .0004
    return first


def clock_offset_pending_probe():
    grid, ex, clock, _ = fresh("clock_offset")
    real_place = ex.place_limit
    offset_seconds = 180
    initial = True
    def accept_fill_lose_reply(*args, **kwargs):
        nonlocal initial
        reply = real_place(*args, **kwargs)
        row = ex.orders[reply["orderId"]]
        row["time"] = int((clock["t"] + offset_seconds) * 1000)
        if initial:
            initial = False
            row.update(status="FILLED", executedQty=row["origQty"], avgPrice=row["price"])
            raise TimeoutError("accepted and filled, response lost")
        return reply
    # Respect server-time history filtering (DryExchange.order_history ignores it).
    def history(symbol, limit=100, page=0, start_ms=None, end_ms=None):
        rows = [{"orderId": oid, **row} for oid, row in reversed(list(ex.orders.items()))
                if (start_ms is None or row["time"] >= start_ms)
                and (end_ms is None or row["time"] <= end_ms)]
        return rows[page * limit:(page + 1) * limit]
    ex.place_limit = accept_fill_lose_reply
    ex.order_history = history
    grid.tick()
    first_cid = grid.st["LONG"]["pending"]["cid"]
    clock["t"] += 130
    grid.tick()
    recorded = sum(float(l["qty"]) for l in grid.st["LONG"]["lots"])
    filled_qty = sum(float(row["executedQty"]) for row in ex.orders.values() if not row["reduceOnly"])
    result = {"server_local_offset_seconds": offset_seconds, "first_cid": first_cid,
              "intent_cleared": grid.st["LONG"]["pending"] is None,
              "exchange_filled_qty": filled_qty, "recorded_qty": recorded,
              "new_entry_count": len([row for row in ex.orders.values() if not row["reduceOnly"]])}
    assert result["intent_cleared"] and filled_qty == .0012 and recorded == 0
    assert result["new_entry_count"] == 2
    return result


def balance_failure_probe():
    grid, ex, clock, _ = fresh("balance")
    assert grid.equity() == 3300
    clock["t"] += 61
    def fail():
        raise RuntimeError("simulated balance endpoint failure")
    ex.futures_balance = fail
    result = {"returned_equity": grid.equity(), "cached_equity": grid._equity}
    assert result == {"returned_equity": None, "cached_equity": None}
    return result


def actual_command_lock_probe():
    folder = BASE / "risk_probe_lock"
    folder.mkdir(exist_ok=True)
    cfg = folder / "config.json"
    state = folder / "state.json"
    journal = folder / "journal.jsonl"
    cfg.write_text(json.dumps({**eg.DEFAULT, "enabled": False}), encoding="utf-8")
    state.write_text(json.dumps({"halted": True, "halt_reason": "old halt"}), encoding="utf-8")
    old_paths = (eg.CONFIG, eg.STATE, eg.JOURNAL, eg.GRIDS, eg.load_config.__defaults__, eg.save_config.__defaults__)
    eg.CONFIG, eg.STATE, eg.JOURNAL, eg.GRIDS = cfg, state, journal, ("BTC",)
    eg.load_config.__defaults__ = (cfg, None)
    eg.save_config.__defaults__ = (cfg,)
    started, release, command_finished = threading.Event(), threading.Event(), threading.Event()
    sequence, errors = [], []
    runner = lp.Runner()
    def paused_tick(name):
        started.set()
        if not release.wait(2):
            raise RuntimeError("probe timeout")
        eg.atomic_write(state, json.dumps({"halted": True, "halt_reason": "old halt"}))
        sequence.append("tick persisted old halt")
    runner.tick_one = paused_tick
    def command():
        try:
            lp.command("start")
            sequence.append("start completed")
        except BaseException as exc:
            errors.append(str(exc))
        finally:
            command_finished.set()
    t_tick = threading.Thread(target=runner.tick)
    t_command = threading.Thread(target=command)
    try:
        t_tick.start()
        assert started.wait(2)
        t_command.start()
        blocked = not command_finished.wait(.1)
        release.set()
        t_tick.join(2)
        t_command.join(2)
        result = {"command_blocked_until_tick_finished": blocked, "sequence": sequence,
                  "final_halted": json.loads(state.read_text())["halted"], "errors": errors}
        assert not errors
        result["race_resolved"] = (blocked and result["final_halted"] is False
                                    and sequence == ["tick persisted old halt", "start completed"])
        return result
    finally:
        release.set()
        (eg.CONFIG, eg.STATE, eg.JOURNAL, eg.GRIDS,
         eg.load_config.__defaults__, eg.save_config.__defaults__) = old_paths


if __name__ == "__main__":
    if "--lock-only" in sys.argv:
        result = {"snapshot": str(SNAPSHOT), "actual_command_lock": actual_command_lock_probe()}
        target = BASE / "risk_lock_control.json"
    else:
        result = {"snapshot": str(SNAPSHOT), "pending_stop": pending_stop_probe(),
                  "clock_offset_pending": clock_offset_pending_probe(),
                  "balance_failure": balance_failure_probe(), "actual_command_lock": actual_command_lock_probe()}
        assert result["actual_command_lock"]["race_resolved"]
        target = BASE / "risk_probes.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
```

</details>

<details>
<summary>lifecycle_probe.py</summary>

```python
"""Offline lifecycle review probes. Assertions reproduce observations, not fixes.

Load only the pinned snapshot engine, never live config/state or WeexClient.
All fills and exchange responses are fake. No network calls are permitted.
"""
from __future__ import annotations

import importlib.util
import json
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("review3_lifecycle_engine", HERE / "snapshot/services/weex_grid/engine.py")
eg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eg)

if '--io-retry' in sys.argv:
    original_atomic_write = eg.atomic_write
    def retry_atomic_write(*args, **kwargs):
        for attempt in range(7):
            try:
                return original_atomic_write(*args, **kwargs)
            except PermissionError:
                if attempt == 6:
                    raise
                time.sleep(.01 * (2**attempt))
    eg.atomic_write = retry_atomic_write


def network_forbidden(*args, **kwargs):
    raise AssertionError("Network access forbidden in offline lifecycle probe")


socket.socket.connect = network_forbidden
socket.create_connection = network_forbidden


class Px:
    def __init__(self):
        self.mid = 100_000.0

    def __call__(self):
        return self.mid - .05, self.mid + .05


def make(tag):
    path = HERE / "lifecycle_cases" / tag
    path.mkdir(parents=True, exist_ok=True)
    # All paths are fixed children of our research artifact directory.
    (path / "st.json").unlink(missing_ok=True)
    (path / "j.jsonl").unlink(missing_ok=True)
    clock = {"t": 1_800_000_000.0}
    px = Px()
    cfg = {**eg.DEFAULT, "enabled": True, "dry_run": True,
           "sides": ["LONG"], "order_qty": "0.0012"}
    ex = eg.DryExchange(px, now_fn=lambda: clock["t"])

    def now():
        clock["t"] += 10
        return clock["t"]

    g = eg.Grid(ex, cfg, state_path=path / "st.json", journal_path=path / "j.jsonl", now_fn=now)
    return g, ex, px


def lost_tp_then_new_partial(lost_mapping: bool):
    g, ex, px = make("lost_tp_new_partial" if lost_mapping else "control_mapping_kept")
    g.tick()
    px.mid = 99_790
    g.tick()  # entry .0012 filled at 99800, TP at 100099.4
    lot = g.st["LONG"]["lots"][0]
    tp_id = lot["tp_order"]["id"]
    tp = ex.orders[tp_id]
    tp.update(executedQty="0.0004", avgPrice=tp["price"])
    g.tick()  # record only .0004; remaining lot .0008
    assert abs(float(lot["qty"]) - .0008) < 1e-12
    prior_realized = g.st["LONG"]["realized"]
    prior_turnover = g.st["LONG"]["turnover"]
    if lost_mapping:
        lot["tp_order"] = None
        g.save()
    # Actual additional .0002 TP execution after prior partial was recorded.
    tp.update(executedQty="0.0006", avgPrice=tp["price"])
    g2 = eg.Grid(ex, g.cfg, state_path=g.state_path, journal_path=g.journal_path, now_fn=g.now)
    g2.cfg["enabled"] = False  # close-only: eliminate new inventory as a confound
    g2.tick()
    recorded = sum(float(l["qty"]) for l in g2.st["LONG"]["lots"])
    actual = next(float(p["size"]) for p in ex.futures_positions() if p["side"] == "LONG")
    realized_delta = g2.st["LONG"]["realized"] - prior_realized
    turnover_delta = g2.st["LONG"]["turnover"] - prior_turnover
    expected_delta = .0002 * (float(tp["price"]) - lot["entry"])
    if lost_mapping:
        assert abs(recorded - .0002) < 1e-12
        assert abs(actual - .0006) < 1e-12
        assert abs(realized_delta - 3 * expected_delta) < 1e-10
    else:
        assert abs(recorded - actual) < 1e-12
        assert abs(realized_delta - expected_delta) < 1e-10
    g3 = eg.Grid(ex, g2.cfg, state_path=g.state_path, journal_path=g.journal_path, now_fn=g.now)
    g3.tick()
    assert abs(sum(float(l["qty"]) for l in g3.st["LONG"]["lots"]) - recorded) < 1e-12
    return {"lost_mapping": lost_mapping, "tp_id": tp_id,
            "recorded_partial_before_loss": .0004, "additional_actual_partial": .0002,
            "exchange_remaining": actual, "bot_remaining": recorded,
            "new_realized_expected": expected_delta, "new_realized_recorded": realized_delta,
            "new_turnover_expected": .0002 * float(tp["price"]), "new_turnover_recorded": turnover_delta,
            "same_result_after_restart_and_repeat": True}


class Crash(BaseException):
    pass


def stray_partial_cancel_crash():
    """Initial durable stray plus partial+late fill across another cancellation crash."""
    g, ex, px = make("stray_partial_cancel_crash")
    g.tick()
    ex.orders["x9"] = {"clientOrderId": "b7gBLex9", "side": "BUY", "positionSide": "LONG",
                       "price": "99000", "origQty": "0.0012", "status": "CANCELING",
                       "executedQty": "0.0004", "avgPrice": "99000", "reduceOnly": False}
    real_cancel = ex.cancel
    ex.cancel = lambda oid: {} if oid == "x9" else real_cancel(oid)
    # Detect orphan, save it before cancellation, then record first partial.
    g.tick()
    assert abs(sum(float(l["qty"]) for l in g.st["LONG"]["lots"]) - .0004) < 1e-12

    def late_and_crash(oid):
        if oid == "x9":
            ex.orders[oid].update(status="FILLED", executedQty="0.0012")
            raise Crash()
        return real_cancel(oid)

    ex.orders["x9"].update(executedQty="0.0008")
    ex.cancel = late_and_crash
    try:
        g.tick()
    except Crash:
        pass
    else:
        raise AssertionError("Crash injection did not run")
    ex.cancel = real_cancel
    g2 = eg.Grid(ex, g.cfg, state_path=g.state_path, journal_path=g.journal_path, now_fn=g.now)
    g2.tick()
    qty = sum(float(l["qty"]) for l in g2.st["LONG"]["lots"])
    assert abs(qty - .0012) < 1e-12
    assert not g2.st["LONG"]["strays"]
    g3 = eg.Grid(ex, g.cfg, state_path=g.state_path, journal_path=g.journal_path, now_fn=g.now)
    g3.tick()
    assert abs(sum(float(l["qty"]) for l in g3.st["LONG"]["lots"]) - qty) < 1e-12
    return {"bot_remaining": qty, "exchange_executed": .0012,
            "stray_removed_after_terminal": True, "same_result_after_restart_and_repeat": True}


if __name__ == "__main__":
    result = {"snapshot": "c844df6 (trading code 3173dfb)",
              "control_mapping_kept": lost_tp_then_new_partial(False),
              "lost_mapping_then_additional_partial": lost_tp_then_new_partial(True),
              "stray_partial_cancel_crash": stray_partial_cancel_crash()}
    raw = json.dumps(result, ensure_ascii=False, indent=2)
    (HERE / "lifecycle_results.json").write_text(raw + "\n", encoding="utf-8")
    print(raw)
```

</details>

<details>
<summary>fees_probe.py</summary>

```python
"""Offline Review3 fee/reconcile probes. No credentials, HTTP, or live files."""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import logging
from pathlib import Path
import runpy
import sys
import tempfile
import time
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE / 'snapshot'
sys.path.insert(0, str(ROOT))
from services.weex_api import client as api
from services.weex_grid import engine as eg


def blocked(*args, **kwargs):
    raise AssertionError('Offline probe: credentials and HTTP are blocked')


api.load_credentials = blocked
urllib.request.urlopen = blocked
logging.disable(logging.CRITICAL)
NOW = 1_800_000_000.0
old_spec = importlib.util.spec_from_file_location('old_fee_engine',
    HERE.parent / 'weex_review2_20261010/snapshot/services/weex_grid/engine.py')
old_eg = importlib.util.module_from_spec(old_spec)
old_spec.loader.exec_module(old_eg)


def grid(path, exchange, engine=eg):
    return engine.Grid(exchange, {**engine.DEFAULT, 'sides': ['LONG']},
                   state_path=path / 'state.json', journal_path=path / 'journal.jsonl',
                   now_fn=lambda: NOW)


def seven_day_probe(path):
    class StrictWindow:
        def __init__(self):
            self.calls = []

        def user_trades(self, symbol, order_id=None, start_ms=None, end_ms=None):
            self.calls.append([start_ms, end_ms])
            if start_ms is not None and end_ms - start_ms > 7 * 86_400_000:
                raise api.WeexError('startTime/endTime cannot exceed 7 days (offline fake)')
            return [{'id': 'late-fill', 'orderId': 'late', 'commission': '0.05',
                     'time': int((NOW - 20) * 1000)}]

    ex = StrictWindow()
    g = grid(path, ex)
    s = g.st['LONG']
    s['entry'] = {'id': 'old-live', 'price': 100000, 'qty': '0.0012'}
    s['fee_book'] = {'old-live': {'done': 0.1, 't': NOW - 8 * 86400, 't0': NOW - 8 * 86400},
                     'late': {'done': 0.0, 't': NOW - 20, 't0': NOW - 20}}
    initial_side = copy.deepcopy(s)
    g._settle_fees()
    with_old = {'fee': s['fees'], 'request_days': (ex.calls[-1][1] - ex.calls[-1][0]) / 86400000,
                'calls': len(ex.calls), 'late_cursor_retained': 'late' in s['fee_book']}
    del s['fee_book']['old-live']
    s['entry'] = None
    g.st['fee_checked'] = 0
    g._settle_fees()
    assert with_old['fee'] == 0 and s['fees'] == 0.05
    (path / 'old').mkdir()
    old_g = grid(path / 'old', StrictWindow(), engine=old_eg)
    old_g.st['LONG'] = initial_side
    old_g._settle_fees()
    assert old_g.st['LONG']['fees'] == 0.05
    return {'with_live_8_day_cursor': with_old, 'after_removing_old_cursor_fee': s['fees'],
            'old_9cc_fee_in_same_fake': old_g.st['LONG']['fees']}


def budget_probe(path):
    class DenseWindow:
        def __init__(self):
            self.calls = []
            span = 5 * 86400
            self.rows = [{'id': f'm{i}', 'orderId': f'm{i}', 'commission': '0',
                          'time': int((NOW - span + i * span / 8000) * 1000)} for i in range(8000)]
            self.rows.append({'id': 'late-fill', 'orderId': 'late', 'commission': '0.05',
                              'time': int((NOW - 20) * 1000)})

        def user_trades(self, symbol, order_id=None, start_ms=None, end_ms=None):
            self.calls.append([start_ms, end_ms])
            return sorted([r for r in self.rows if (start_ms is None or start_ms <= r['time'])
                           and (end_ms is None or r['time'] <= end_ms)],
                          key=lambda r: -r['time'])[:100]

    ex = DenseWindow()
    g = grid(path, ex)
    clock = [NOW]
    g.now = lambda: clock[0]
    s = g.st['LONG']
    s['entry'] = {'id': 'old-live', 'price': 100000, 'qty': '0.0012'}
    s['fee_book'] = {'old-live': {'done': 0.1, 't': NOW - 5 * 86400, 't0': NOW - 5 * 86400},
                     'late': {'done': 0.0, 't': NOW - 20, 't0': NOW - 20}}
    initial_side = copy.deepcopy(s)
    root_rows = sorted(ex.rows, key=lambda r: -r['time'])[:100]
    assert any(r['orderId'] == 'late' for r in root_rows)
    passes = []
    for _ in range(3):
        g.st['fee_checked'] = 0
        before = len(ex.calls)
        g._settle_fees()
        passes.append({'seconds_since_first_pass': clock[0] - NOW,
                       'requests': len(ex.calls) - before, 'fee': s['fees']})
        clock[0] += 60
    assert all(p['requests'] == 64 and p['fee'] == 0 for p in passes)
    del s['fee_book']['old-live']
    s['entry'] = None
    g.st['fee_checked'] = 0
    g._settle_fees()
    assert s['fees'] == 0.05
    (path / 'old').mkdir()
    old_g = grid(path / 'old', DenseWindow(), engine=old_eg)
    old_g.st['LONG'] = initial_side
    old_g._settle_fees()
    assert old_g.st['LONG']['fees'] == 0.05
    return {'same_window_passes': passes, 'after_removing_old_cursor_fee': s['fees'],
            'rows': len(ex.rows), 'history_span_days': 5,
            'average_rows_per_day': len(ex.rows) / 5,
            'initial_root_response_contains_late_fee': True,
            'old_9cc_fee_in_same_fake': old_g.st['LONG']['fees']}


def reconcile_probe(path, label):
    path.mkdir()
    journal = path / 'journal.jsonl'
    state = path / 'state.json'
    journal.write_text(json.dumps({'ts': '2026-10-09T00:00:00+00:00'}) + '\n', encoding='utf-8')
    rows = [{'id': 'f1', 'orderId': 'o1', 'side': 'BUY', 'positionSide': 'LONG',
             'price': '100000', 'qty': '0.0012', 'commission': '0.0192',
             'time': int((NOW - 100) * 1000)}]
    if label == 'incomplete':
        rows = [{**rows[0], 'id': f'f{i}'} for i in range(100)]
    s = {'LONG': eg.new_side_state(), 'SHORT': eg.new_side_state()}
    s['LONG']['lots'] = [{'entry': 100000., 'qty': str(0.0012 * len(rows))}]
    s['LONG']['fees'] = 0.0192 * len(rows) + (0.02 if label == 'mismatch' else 0)
    state.write_text(json.dumps(s), encoding='utf-8')

    class FakeClient:
        def sync_time(self): return 0
        def book(self, symbol): return 99999., 100001.
        def user_trades(self, symbol, start_ms=None, end_ms=None):
            if label == 'api_error': raise api.WeexError('offline fake API error')
            return sorted([r for r in rows if start_ms <= r['time'] <= end_ms],
                          key=lambda r: -r['time'])[:100]
        def order_info(self, oid): return {'clientOrderId': 'b7gBLe1'}

    old_client, old_state, old_journal, old_time = api.WeexClient, eg.STATE, eg.JOURNAL, time.time
    api.WeexClient, eg.STATE, eg.JOURNAL, time.time = FakeClient, state, journal, lambda: NOW
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            try:
                runpy.run_path(str(ROOT / 'research/weex/pnl_reconcile.py'), run_name='__main__')
            except SystemExit as exc:
                result = {'exit_code': exc.code}
            except Exception as exc:
                result = {'unhandled_exception': type(exc).__name__, 'detail': str(exc)}
    finally:
        api.WeexClient, eg.STATE, eg.JOURNAL, time.time = old_client, old_state, old_journal, old_time
    result['output'] = output.getvalue()
    return result


with tempfile.TemporaryDirectory(prefix='fees_probe_', dir=HERE) as temporary:
    base = Path(temporary)
    for label in ['seven_days', 'budget']:
        (base / label).mkdir()
    results = {'seven_day_limit': seven_day_probe(base / 'seven_days'),
               'request_budget_starvation': budget_probe(base / 'budget'),
               'reconcile': {label: reconcile_probe(base / label, label)
                             for label in ['matching', 'mismatch', 'incomplete', 'api_error']}}
    assert results['reconcile']['matching']['exit_code'] == 0
    assert results['reconcile']['mismatch']['exit_code'] == 1
    assert results['reconcile']['incomplete']['exit_code'] == 1
    assert results['reconcile']['api_error']['unhandled_exception'] == 'WeexError'
(HERE / 'fees_probe.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
sys.stdout.buffer.write((json.dumps(results, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
```

</details>

<details>
<summary>source_manifest.json</summary>

```json
{
  "commit": "c844df6fbe4e7092b8b508489586f2239070754f",
  "files": [
    {
      "path": "conftest.py",
      "blob": "b01732c6888248ae1824fa0acb2f3e01ceacd103",
      "bytes": 813
    },
    {
      "path": "docs/WEEX_GPT_REVIEW3_ANSWERS_2026-10-10.md",
      "blob": "9cf6aec77388e4e0301c8e275464b7e9f8924cdb",
      "bytes": 5292
    },
    {
      "path": "pytest.ini",
      "blob": "bba2e296a6868878892129a49a93730967c4c94e",
      "bytes": 109
    },
    {
      "path": "research/weex/pnl_reconcile.py",
      "blob": "c7b71929cacf0bf26d58e3f1b8eb7808bddecc6f",
      "bytes": 4429
    },
    {
      "path": "services/__init__.py",
      "blob": "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391",
      "bytes": 0
    },
    {
      "path": "services/weex_api/__init__.py",
      "blob": "d9e6bffe55afb5de29a67485aeb12b535b558341",
      "bytes": 279
    },
    {
      "path": "services/weex_api/client.py",
      "blob": "fb27c5c203b634047050cf2da0c1fb30d4dc897b",
      "bytes": 7954
    },
    {
      "path": "services/weex_grid/__init__.py",
      "blob": "552c24e92f7c4750e1889100608c39c6c876e3d4",
      "bytes": 1215
    },
    {
      "path": "services/weex_grid/engine.py",
      "blob": "ac69a28daae830c8e6030e024632eaacfc30b27d",
      "bytes": 59166
    },
    {
      "path": "services/weex_grid/loop.py",
      "blob": "f619d0f7361c9633d98424cc03fc00fb2de43a1a",
      "bytes": 16319
    },
    {
      "path": "tests/__init__.py",
      "blob": "427be2d332ac5eec849623132938d4165fb0bc26",
      "bytes": 101
    },
    {
      "path": "tests/conftest.py",
      "blob": "2a855d9fdb8debae0b082088580a4c41e499e33c",
      "bytes": 144
    },
    {
      "path": "tests/services/__init__.py",
      "blob": "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391",
      "bytes": 0
    },
    {
      "path": "tests/services/weex_grid/test_weex_grid_engine.py",
      "blob": "611a5f7520fe0777895f0a10b2da6164f2a7fa1a",
      "bytes": 8933
    },
    {
      "path": "tests/services/weex_grid/test_weex_grid_multi.py",
      "blob": "bb908b3f488434836d90a569a87b10b940a24298",
      "bytes": 4624
    },
    {
      "path": "tests/services/weex_grid/test_weex_grid_review2.py",
      "blob": "369f4b5d4622474174bb3e173ee33e4c06a9f198",
      "bytes": 11530
    },
    {
      "path": "tests/services/weex_grid/test_weex_grid_review3.py",
      "blob": "abe1149d9225f852ad2028fe2bf22426e2729fec",
      "bytes": 11368
    },
    {
      "path": "tests/services/weex_grid/test_weex_grid_robust.py",
      "blob": "845cd78379ec096d401aa4c6971f802b97a30514",
      "bytes": 9913
    },
    {
      "path": "tests/services/weex_grid/test_weex_grid_set.py",
      "blob": "adbfcd415650e329ca5f621d1badcfa4f04167f0",
      "bytes": 2353
    }
  ]
}
```

</details>

<details>
<summary>verification/summary.json</summary>

```json
[
  {
    "label": "current_61_io_retry",
    "exit_code": 0,
    "seconds": 4.157,
    "junit": "C:\\bot7\\research\\weex_review3_20261010\\verification\\current_61_io_retry_1791592589711378300.xml"
  },
  {
    "label": "old_adapted_fixtures_io_retry",
    "exit_code": 1,
    "seconds": 3.343,
    "junit": "C:\\bot7\\research\\weex_review3_20261010\\verification\\old_adapted_fixtures_io_retry_1791592589711378300.xml"
  }
]
```

</details>

<details>
<summary>risk_probes.json</summary>

```json
{
  "snapshot": "C:\\bot7\\research\\weex_review3_20261010\\snapshot",
  "pending_stop": {
    "enabled": false,
    "entry_status": "NEW",
    "cancel_calls": [],
    "pending": true,
    "accounted_qty": 0.0004,
    "exchange_qty_after_additional_fill": 0.0012,
    "accounted_qty_after_additional_fill": 0.0004
  },
  "clock_offset_pending": {
    "server_local_offset_seconds": 180,
    "first_cid": "b7gBLe18000000001",
    "intent_cleared": true,
    "exchange_filled_qty": 0.0012,
    "recorded_qty": 0,
    "new_entry_count": 2
  },
  "balance_failure": {
    "returned_equity": null,
    "cached_equity": null
  },
  "actual_command_lock": {
    "command_blocked_until_tick_finished": true,
    "sequence": [
      "tick persisted old halt",
      "start completed"
    ],
    "final_halted": false,
    "errors": [],
    "race_resolved": true
  }
}
```

</details>

<details>
<summary>risk_lock_control.json</summary>

```json
{
  "snapshot": "C:\\bot7\\research\\weex_review2_20261010\\snapshot",
  "actual_command_lock": {
    "command_blocked_until_tick_finished": false,
    "sequence": [
      "start completed",
      "tick persisted old halt"
    ],
    "final_halted": true,
    "errors": [],
    "race_resolved": false
  }
}
```

</details>

<details>
<summary>lifecycle_results.json</summary>

```json
{
  "snapshot": "c844df6 (trading code 3173dfb)",
  "control_mapping_kept": {
    "lost_mapping": false,
    "tp_id": "dry2",
    "recorded_partial_before_loss": 0.0004,
    "additional_actual_partial": 0.0002,
    "exchange_remaining": 0.0006,
    "bot_remaining": 0.0006,
    "new_realized_expected": 0.05987999999999884,
    "new_realized_recorded": 0.05988000000000174,
    "new_turnover_expected": 20.01988,
    "new_turnover_recorded": 20.01988,
    "same_result_after_restart_and_repeat": true
  },
  "lost_mapping_then_additional_partial": {
    "lost_mapping": true,
    "tp_id": "dry2",
    "recorded_partial_before_loss": 0.0004,
    "additional_actual_partial": 0.0002,
    "exchange_remaining": 0.0006,
    "bot_remaining": 0.0002,
    "new_realized_expected": 0.05987999999999884,
    "new_realized_recorded": 0.1796399999999965,
    "new_turnover_expected": 20.01988,
    "new_turnover_recorded": 60.05964,
    "same_result_after_restart_and_repeat": true
  },
  "stray_partial_cancel_crash": {
    "bot_remaining": 0.0012000000000000001,
    "exchange_executed": 0.0012,
    "stray_removed_after_terminal": true,
    "same_result_after_restart_and_repeat": true
  }
}
```

</details>

<details>
<summary>fees_probe.json</summary>

```json
{
  "seven_day_limit": {
    "with_live_8_day_cursor": {
      "fee": 0.0,
      "request_days": 8.00763888888889,
      "calls": 1,
      "late_cursor_retained": true
    },
    "after_removing_old_cursor_fee": 0.05,
    "old_9cc_fee_in_same_fake": 0.05
  },
  "request_budget_starvation": {
    "same_window_passes": [
      {
        "seconds_since_first_pass": 0.0,
        "requests": 64,
        "fee": 0.0
      },
      {
        "seconds_since_first_pass": 60.0,
        "requests": 64,
        "fee": 0.0
      },
      {
        "seconds_since_first_pass": 120.0,
        "requests": 64,
        "fee": 0.0
      }
    ],
    "after_removing_old_cursor_fee": 0.05,
    "rows": 8001,
    "history_span_days": 5,
    "average_rows_per_day": 1600.2,
    "initial_root_response_contains_late_fee": true,
    "old_9cc_fee_in_same_fake": 0.05
  },
  "reconcile": {
    "matching": {
      "exit_code": 0,
      "output": "цена 100,000.0; сделок с 2026-10-09T00:00: 1 (сетки 1, ручных 0)\nLONG: биржа — сделок 1, остаток 0.0012, до комиссий $+0.0000, комиссии $0.0192, после $-0.0192\nLONG: бот   — остаток 0.0012, закрыто $+0.0000 + мешок $+0.0000 = $+0.0000, комиссии $0.0192, после $-0.0192\nLONG: расхождение — деньги $+0.0000, комиссии $+0.0000, объём +0.0000\nSHORT: биржа — сделок 0, остаток 0.0000, до комиссий $+0.0000, комиссии $0.0000, после $+0.0000\nSHORT: бот   — остаток 0.0000, закрыто $+0.0000 + мешок $+0.0000 = $+0.0000, комиссии $0.0000, после $+0.0000\nSHORT: расхождение — деньги $+0.0000, комиссии $+0.0000, объём +0.0000\nИТОГ: совпадает (деньги и комиссии ±$0.01, объём точно)\n"
    },
    "mismatch": {
      "exit_code": 1,
      "output": "цена 100,000.0; сделок с 2026-10-09T00:00: 1 (сетки 1, ручных 0)\nLONG: биржа — сделок 1, остаток 0.0012, до комиссий $+0.0000, комиссии $0.0192, после $-0.0192\nLONG: бот   — остаток 0.0012, закрыто $+0.0000 + мешок $+0.0000 = $+0.0000, комиссии $0.0392, после $-0.0392\nLONG: расхождение — деньги $+0.0000, комиссии $+0.0200, объём +0.0000\nSHORT: биржа — сделок 0, остаток 0.0000, до комиссий $+0.0000, комиссии $0.0000, после $+0.0000\nSHORT: бот   — остаток 0.0000, закрыто $+0.0000 + мешок $+0.0000 = $+0.0000, комиссии $0.0000, после $+0.0000\nSHORT: расхождение — деньги $+0.0000, комиссии $+0.0000, объём +0.0000\nИТОГ: ЕСТЬ РАСХОЖДЕНИЕ/НЕПОЛНО\n"
    },
    "incomplete": {
      "exit_code": 1,
      "output": "цена 100,000.0; сделок с 2026-10-09T00:00: 100 (сетки 100, ручных 0)\nLONG: биржа — сделок 100, остаток 0.1200, до комиссий $+0.0000, комиссии $1.9200, после $-1.9200\nLONG: бот   — остаток 0.1200, закрыто $+0.0000 + мешок $+0.0000 = $+0.0000, комиссии $1.9200, после $-1.9200\nLONG: расхождение — деньги $-0.0000, комиссии $-0.0000, объём -0.0000\nSHORT: биржа — сделок 0, остаток 0.0000, до комиссий $+0.0000, комиссии $0.0000, после $+0.0000\nSHORT: бот   — остаток 0.0000, закрыто $+0.0000 + мешок $+0.0000 = $+0.0000, комиссии $0.0000, после $+0.0000\nSHORT: расхождение — деньги $+0.0000, комиссии $+0.0000, объём +0.0000\nВЫБОРКА НЕПОЛНА: 1 секундных окон со 100 сделками — сверка недостоверна\nИТОГ: ЕСТЬ РАСХОЖДЕНИЕ/НЕПОЛНО\n"
    },
    "api_error": {
      "unhandled_exception": "WeexError",
      "detail": "offline fake API error",
      "output": ""
    }
  }
}
```

</details>

### JUnit итог финального сравнительного запуска

```json
[
  {
    "label": "current_61_io_retry",
    "tests": "61",
    "failures": "0",
    "errors": "0"
  },
  {
    "label": "old_adapted_fixtures_io_retry",
    "tests": "10",
    "failures": "9",
    "errors": "0"
  }
]
```
