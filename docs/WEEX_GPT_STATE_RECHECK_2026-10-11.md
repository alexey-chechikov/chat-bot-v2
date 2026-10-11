# Повторная проверка исправлений WEEX 11.10.2026

Проверен ответ `docs/WEEX_GPT_STATE_REVIEW_ANSWERS_2026-10-11.md` и публичный код коммита **1537794bee0c8b1610f4ea808d2bd4e7a1b9595b**, ветка `alexey/mac-2026-05-29`, репозиторий `alexey-chechikov/chat-bot-v2`. Сравнение — с исходным `3b33428f6a54414ca50d8d932101410e440e5931`. Это проверка опубликованных исправлений, без ключей, живого state, ордеров, денежных переводов или изменений производственного кода.

**Основные исправления реальны. Однако общий потолок ещё обходится в нормальных сценариях восстановления, трендовый движок имеет незакрытые сценарии потери защиты, а новые исторические цифры не воспроизводят исполнение биржевого hard stop.** Ниже отделены исправленные случаи, оставшиеся дефекты и ограничения доказательств. Оставшийся дефект не означает, что конкретный уже исправленный тест неверен, и не доказывает, что этот сценарий происходил на живом счёте.

## Что подтверждено

Мой офлайн-прогон **107 профильных тестов прошёл**: сетка/портфель, тренд, TradeGPT и служба сигналов. Это не независимый повтор заявленных 720 тестов всего проекта. Дополнительные пробники исполняют закреплённый исходник с синтетическими биржей, историей и данными; их результаты приложены.

- **Размер тренда:** при E=100, Chandelier=98, биржевом trigger=96.53 и бюджете $50 теперь q=14.005, потеря до trigger с двумя фактическими fee 0.048% ≈ **$49.918503**, до slippage/funding/gap. Старый пример $89 устранён. Это плановый риск, а не абсолютный предел исполнения.
- **Частичный собственный и внешний выход:** закрытые 0.4 из 1 дают gross PnL −$4, в эпизоде остаются 0.6 и принятый стоп на 0.6. Обычный собственный partial path после перезапуска не списывается второй раз.
- **Возраст сигнала:** `since=2026-01-01T00:00Z` теперь даёт время закрытия исходного бара `2026-01-01T04:00Z`, а не дату обнаружения.
- **Обычный общий лимит:** standing/pending/stray входы сетки включены, нечитаемый JSON вызывает отказ допуска, новое место вычитается внутри прохода и пересчитывается между сетками/монетами. Это исправляет прежний обычный сценарий двойного расходования room. Ниже — отдельные оставшиеся обходы.
- **Журнал:** next-minute функция, ведущая/внутренняя дыра и явные причины TP/SL/TIME исправлены. Caller, конечное покрытие и старый cache требуют отдельного исправления.
- **Исследование тренда:** добавлены initial zero, mark имеющихся открытых path по 4ч-close и год от конца данных. Это лучше прежнего exits-only расчёта; исполнение hard stop пока отсутствует.

## Что исправить перед живым включением тренда и новых режимов

Приоритет P1 ниже означает блокер живого выпуска, а не утверждение о случившемся убытке. Все суммы — детерминированные контрпримеры, не результаты живого счёта.

### R1 · P1 · Успешный ответ теряет владельца ордера при аварии

`services/weex_trend/engine.py:175–195`: `_send` получает успешный orderId, очищает `pending` и сохраняет state **до** того, как вызывающий код прикрепляет `entry_order` / `exit_order` / `stop`. Авария после этого сохранения оставляет ни намерения, ни ID принятого ордера.

Probe `crash_ack_entry`: реальный для имитатора вход уже исполнен, на бирже q=14.005; на диске `pending=None`, `entry_order=None`. После restart и трёх tick эпизод остаётся `opening`, **защитных стопов 0**. `_on_opening` ждёт ссылку, которую уже нечем восстановить. Этот риск одинаково существует для успешных ответов других видов ордеров.

**Спецификация исправления:** durable intent хранится до атомарного сохранения adoption в эпизод; pending и ссылка на ID меняются одной записью. У adopted операции сохраняются cid/kind/qty/side и факт обработки fills. Тесты падения до POST, после fill/ACK, после adoption и до очистки intent; после каждого restart ордер принят в учёт ровно один раз, исполненная позиция защищена либо уменьшается по аварийному сценарию, дубликатов нет.

### R2 · P1 · Неполная история ошибочно доказывает отсутствие входа

`services/weex_trend/engine.py:197–235`: поиск читает максимум пять страниц по 100, не подтверждает полноту и через 120 секунд очищает неизвестное намерение. Логика, уже защищённая в сетке, не перенесена в тренд.

Probe `incomplete_history`: пять страниц полностью заняты другими ордерами, нужный исполненный вход — на шестой (page=5). Через 130 секунд resolver считает поиск завершённым, удаляет эпизод и pending; **14.005 остаются на бирже без стопа**.

**Спецификация:** неполнота, переполнение страниц и timeout не превращаются в доказанную отмену. Пока исход неизвестен, сохранять intent, блокировать новые увеличивающие риск входы, сверять позиции/fills и продолжать безопасное восстановление. Очистка допустима лишь при подтверждённом terminal исходе с обработанными fills либо доказанной полной выборке. Тесты page overflow, gaps, API failure, позднего найденного fill и повторного запуска.

### R3 · P1 · Отказ защитного стопа оставляет позицию в штатном OPEN

`services/weex_trend/engine.py:343–356`: явный reject стопа вызывает только уведомление. Нет гарантированного перехода к уменьшению риска.

Probe `rejected_stop`: entry принят, stop отклонён; цена уже 96.5 ниже задуманного 96.53, после трёх tick q=14.005 всё ещё открыта, стопов и market exits нет. Свечная служба до очередного закрытия 4ч может продолжать публиковать тот же эпизод.

**Спецификация:** состояние PROTECTION_FAILED / EXIT_ONLY; запрет новых входов; немедленно попытаться bounded reduceOnly закрытие подтверждённого остатка. Частичное/неизвестное исполнение ведётся до terminal, не объявляется FLAT. Если неизвестен исход самой постановки стопа, сначала сохранить намерение и исключить дубли, сопровождение остатка не бросать. Тест reject, timeout, partial emergency exit и повторного запуска. Уведомление не заменяет исполнение защиты.

### R4 · P1 · Неизвестная отмена старого стопа забывается

`services/weex_trend/engine.py:247–253,343–353,445–458`: старый stop заменён в эпизоде новым, cancel старого не дошёл, ошибка только залогирована. После завершения эпизода старый условный ордер остаётся активным без владельца.

Probe `stop_cancel_unknown`: старый trigger96.53 остаётся после закрытия первой сделки и закрывает следующую LONG-позицию, у которой intended stop90. ReduceOnly предотвращает переворот, но не чуждое новой стратегии преждевременное закрытие.

**Спецификация:** persistent retiring/stray algo registry до подтверждённого terminal состояния, проверка позднего trigger/actualOrderId и его fills/fees; новое событие не допускается на стороне с неразрешёнными прежними exit orders. Adoption replacement сохранить до cancel прежнего. Тест cancel rejected/timeout, crash, late trigger и новый эпизод.

### R5 · P1 · Восстановленный сиротский вход не уменьшает текущий room

`services/weex_grid/engine.py:368–402,529–585,642–652`: runner вычислил free по старому state, затем `_orphans` принимает уже стоящий вход. `_room_used` не учитывает эту прибавку; `_entry_res` даёт ордеру кредит как будто он уже входил в исходный snapshot used.

Probe `orphan_adoption_then_other_side`: cap$15, сирота LONG$9.98, новый SHORT$10.02 — итог **$20** ещё исполнимых входов. Учёт после tick уже показывает20, но второй POST успел пройти.

**Спецификация:** каждый admission использует актуальный единый ledger; orphan adoption и обнаруженный fill перемещают/добавляют резерв до следующего POST. Replacement-credit разрешён только для резерва, доказанно присутствовавшего в исходном used, без двойного зачёта. При newly discovered превышении — запрет набора и отмена увеличивающих риск входов с учётом поздних fills. Тест именно неизвестного ранее ордера, а не заранее записанного standing entry.

### R6 · P1 · Удалённая монета выпадает из учёта и сопровождения

`services/weex_grid/loop.py:125–130`, `services/weex_trend/loop.py:45–60`: оба перечисляют только текущие `symbols(cfg)`. Удалить XRP из списка новых сигналов можно при его старом открытом эпизоде; файл и ордера останутся, проход и portfolio перестанут их видеть.

Probe `removed_trend_symbol`: старый XRP$750, cap$1000; runner сообщает free$1000, разрешает новые BTC$800. Реально занято **$1550**.

**Спецификация:** отдельно configured entry universe и persistent owned universe. Все живые/неизвестные эпизоды и заявки учитываются и сопровождаются до завершения, даже после удаления инструмента или ошибки конфига. Новые входы на удалённом инструменте запрещены. Удалять запись владения только после полного reconcile. Тест смены списка при OPEN/OPENING/CLOSING/UNKNOWN и restart.

### R7 · P1 · Трендовый OPENING резервируется по Chandelier вместо цены входа

`services/weex_trend/engine.py:307–318`, `services/weex_grid/portfolio.py:69–72`: opening уже содержит qty, поэтому **резерв не нулевой**. Но entry_px ещё нет и резерв использует `chand`; для LONG это недооценка принятого входа.

Probe `trend_opening_chand_reserve`: q0.361, fill2500.01, chand2400 → actual$902.50361, reserved$866.40. Следующая сетка получает лишнее место и ставит$120: **$1022.50361 при cap$1000**.

**Спецификация:** до POST сохранять reference/bounded entry price и резерв worst-fill notional, не stop level. После подтверждения использовать фактический filled value плюс ещё исполнимый остаток. Для market исполнения без верхней границы нельзя обещать абсолютный gross ceiling: нужен buffer/реально bounded order и post-fill admission halt. Проверить normal ACK и lost ACK, LONG/SHORT, price jump, multi-symbol проход.

### Дополнительное: валидный JSON ещё не означает валидный учёт

P2, синтетически повреждённая схема, не утверждение о production: `qty='NaN'` даёт used/free=NaN и позволяет два входа$20 при cap$15. Standing entry без qty молча оценивается в0 и даёт такой же обход. Нужны schema/version validation, finite/nonnegative numbers, обязательные price/qty для ещё живых ордеров и fail-closed account admission до восстановления. Проверка только JSON-синтаксиса этого не обеспечивает.

### Дополнительное: комиссии тренда теряются при временной ошибке

P2, `services/weex_trend/engine.py:159–164`: `_fee` возвращает0 при ошибке, и episode может завершиться без отложенной досверки. Probe `delayed_commissions`: после восстановления API настоящие fees$1.411704 доступны, но после трёх restart/tick state всё ещё fees0. Нужны persistent unresolved fees/fill cursors и досверка terminal ordеrs, с учётом cumulative delta ровно один раз; нет данных ≠ доказанная нулевая комиссия.

## Новые +1867 / +209 / DD−624 пока нельзя считать результатом live-правил

Размер до hard trigger и более полная marked equity исправлены. Но `research/weex/trend_risk_size.py:38–55` использует hard stop **только в denominator размера**, а выход исполняет лишь по close за Chandelier. Касание биржевого trigger внутри бара не закрывает виртуальную позицию.

Два независимых от raw-cache контрпримера при E100, peak101, ATR1, Chandelier98, hard96.53, risk$50, fee0.1%, notional$1400.560224:

1. Следующий OHLC100/100/94/94 → модель закрывает по94 и пишет **−$85.434174**. Идеальное исполнение hard96.53 в этой же fee-модели дало бы−$50. Превышение риска в реальности возможно при gaps/slippage, но здесь оно не симулируется — trigger вообще не исполняется.
2. Следующий low95/close100, затем close105 → hard96.53 уже пройден, модель сохраняет позицию и показывает **+$68.627451** вместо раннего стопа около−$50. Значит отсутствие hard fills меняет и знак, и набор последующих эпизодов; это не поправка одной цифры.

**Нужная проверка:** live-equivalent replay входа после закрытия сигнальной свечи, старого биржевого trigger внутри следующего бара, close-based signal exit, очередности установки нового trailing stop, gaps/slippage и actual fees/funding. Внутри 4ч OHLC порядок экстремумов неоднозначен: использовать меньший таймфрейм/quote stream либо объявленный консервативный порядок. Нельзя задним числом поставить обновлённый стоп до момента его вычисления.

Вход на последнем баре с `path={}` также исчезает: `if pos is not None and pos['path']` пропускает его. Entry fee и остаток должны попадать в equity сразу на доступном времени. Binance index здесь — open-time 4ч; сигнал по close доступен на4ч позже. В календарной сверке нужны bar_close_ts и модель исполнения после него.

Необходимого публичного raw-cache/manifest всё ещё нет. **+1867/+209/−624/−79 независимо не вычислены.** −624 теперь 4ч-close DD с плавающим результатом, но не intrabar/liquidation DD и не риск всего live-счёта. Утверждение о худшей сделке−79 приrisk50 не доказывает корректность исполнения стопа. Как изменятся доходность и DD после правильных hard fills, здесь не вычислено.

## Журнал TradeGPT: два существенных остатка причинности и полноты

**J1. Время forwarded сообщения.** `services/telegram_runtime.py:3634–3635` передаёт `forward_date or date`, то есть исходную публикацию; `entry_time` отсчитывает новую минуту от этого времени. Probe: публикация30с, получение630с → entry60с вместо доступной660с. Это допустимый anchor для явно обозначенного исследования исходных публикаций, но не для результата стратегии, доступной получателю. Хранить published_at, received_at и executed_at отдельно; доступный пользователю вход считать от received_at с latency. Отдельно тестировать caller, а не только функцию с одним t0.

**J2. Обрезанный конец истории выдаётся за TIME.** `tradegpt.py:145–146,174–181` проверяет разрывы имеющегося prefix, но не достижение конца72ч. При календарном expired и единственной первой минуте вместо4320 код кэширует **+0.4%, TIME**. Перед terminal TIME требуется полное покрытие до expiry и закрытый конечный бар. Обрезанный ответ — INCOMPLETE с повторной загрузкой, а не завершённая прибыльная сделка.

Обнаруженная «дыра» сейчас навсегда исключает событие из todo. Даже когда данные восстановлены, klines больше не вызывается: calls1→1, результат остаётсяNone/дыра. Для автоматической дозагрузки incomplete не terminal; отдельно показывать недостающие события и их долю, а не считать очищенную выборку репрезентативной.

Автоматической миграции старых p0/outcomes к новой минуте и reasons нет: probe сохраняет старый p0=90 и+0.9%, хотя новая entry price100. Требуются calc_version и явный пересчёт либо LEGACY-раздел. Публичный код не доказывает, что приватные шесть записей оставлены старыми: их могли пересчитать вручную, как написано в ответе. Сами шесть событий и результат5/1 без приватного журнала здесь не подтверждены.

## Решение и следующий эксперимент

**Решение по постоянному набору BTC не изменилось: `/weex stop`.** Команда снимает новые входы и сохраняет сопровождение старых лотов; достижение ими тейков и срок закрытия не гарантированы. `/weex stop` сам по себе не создаёт стоп-риск старого мешка. Команду живому экземпляру я не отправлял и не подтверждаю её исполнение.

Офлайн-исследование первого режима можно продолжать. Заморозить прежнюю спецификацию: ETH/XRP закрытый4ч-пробой30 баров, ADX14≥20, TTL15мин, пропуск ухода цены>0.05%, стоп≥0.5%, биржевой trigger на том же S без дополнительного буфера, TP2R, удержание≤8ч, размер по fees/slippage/funding и общему бюджету. Сравнивать с no-ADX на тех же size/exit/cost, затем временными контролями; не выбирать новую версию по уже просмотренному окну. Это другой тест, его результатом не служит +1867 прежнего Chandelier-выхода.

До live нужны закрытые R1–R7, полноценный денежный account-risk controller и доказательства net expectancy по причинному контракту. Субаккаунт/общий контроллер ручных сделок, funding и account reconciliation остаются открытыми по самому опубликованному ответу. Запись стакана без ордеров и тест диапазонных эпизодов на истории могут идти независимо.

## Исходники и воспроизведение

Закреплённые исходники: [trend engine](https://github.com/alexey-chechikov/chat-bot-v2/blob/1537794bee0c8b1610f4ea808d2bd4e7a1b9595b/services/weex_trend/engine.py), [grid engine](https://github.com/alexey-chechikov/chat-bot-v2/blob/1537794bee0c8b1610f4ea808d2bd4e7a1b9595b/services/weex_grid/engine.py), [portfolio](https://github.com/alexey-chechikov/chat-bot-v2/blob/1537794bee0c8b1610f4ea808d2bd4e7a1b9595b/services/weex_grid/portfolio.py), [trend research](https://github.com/alexey-chechikov/chat-bot-v2/blob/1537794bee0c8b1610f4ea808d2bd4e7a1b9595b/research/weex/trend_risk_size.py), [journal](https://github.com/alexey-chechikov/chat-bot-v2/blob/1537794bee0c8b1610f4ea808d2bd4e7a1b9595b/services/signal_journal/tradegpt.py), [Telegram caller](https://github.com/alexey-chechikov/chat-bot-v2/blob/1537794bee0c8b1610f4ea808d2bd4e7a1b9595b/services/telegram_runtime.py#L3634).

Офлайн-проверки подтверждают причинные сценарии кода, а не частоту их возникновения или будущую доходность. В trend probe вместо atomic replace используется простая запись task-only state: проверяется порядок durable state-machine действий и restart, не надёжность файловой системы при потере питания. В основном тестовом harness retry только PermissionError компенсирует Windows-окружение; credentials/network заблокированы. Snapshot и production source не изменены. Условно повреждённая схема отделена от штатных сценариев. Полные scripts/results, manifest и список107 тестов приложены ниже.


## Приложение: scripts, результаты и manifest

Сохранить блоки с указанными именами в одной папке. В соседней папке `weex_publish_20261010`
нужен публичный клон, содержащий коммит1537794bee0c8b1610f4ea808d2bd4e7a1b9595b;
либо исправить REPO в fetch_snapshot.py. Python/numpy/pandas/pytest — версии ниже.
Выполнить `python -X utf8 fetch_snapshot.py`, затем `trend_recheck_probes.py`,
`grid_cap_probes.py` и `journal_trend_probe.py` из папки пробников. Для исходных тестов
из рабочей папки `snapshot`: `python -X utf8 ../run_tests.py`.
Не добавлять ключи, .env.local или живое state в snapshot.

Snapshot source не патчится. Fake APIs, synthetic histories/OHLC, in-memory journal,
task-only state и тестовые замены сохранения описаны в коде. Assert подтверждает дефект
по закреплённому исходнику, а не положительное ожидание стратегии. Scripts не являются
готовыми production patches. SHA256 ниже считается по UTF-8 с переносами LF.


<details>
<summary>fetch_snapshot.py</summary>

SHA256: `2aac83c5c73c6741893188676aa16c06d95a77a670b509463168bc28ce09556e`

```python
"""Public source snapshot; excludes live state, credentials and execution."""
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parent/'weex_publish_20261010'
SHA = '1537794bee0c8b1610f4ea808d2bd4e7a1b9595b'
prefixes = ['services/weex_grid', 'services/weex_trend', 'services/weex_api',
            'services/signal_journal/tradegpt.py', 'services/short_gate',
            'research/weex', 'research/tradegpt', 'research/carry', 'research/trend_expand',
            'tests/services/weex_grid', 'tests/services/weex_trend',
            'tests/services/signal_journal', 'tests/services/trend_signals',
            'tools/trend_state.py', 'services/trend_signals/loop.py']
fixed = ['docs/WEEX_STATE_FOR_GPT_2026-10-11.md', 'CLAUDE.md', 'AGENTS.md',
         'services/__init__.py', 'tests/__init__.py', 'tests/services/__init__.py',
         'conftest.py', 'tests/conftest.py', 'pytest.ini',
         'docs/WEEX_GPT_STATE_REVIEW_ANSWERS_2026-10-11.md', 'services/telegram_runtime.py']
names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', SHA, '--', *prefixes, *fixed], cwd=REPO).decode().splitlines()
target = HERE/'snapshot'
records = []
for name in names:
    if not name.endswith(('.py', '.md', '.ini', '.txt', '.jsonl')):
        continue
    data = subprocess.check_output(['git', 'show', f'{SHA}:{name}'], cwd=REPO)
    path = target/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    records.append({'path': name, 'bytes': len(data),
        'git_blob': subprocess.check_output(['git', 'rev-parse', f'{SHA}:{name}'], cwd=REPO).decode().strip()})
(HERE/'source_manifest.json').write_text(json.dumps({'commit': SHA, 'files': records}, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'snapshot': str(target), 'commit': SHA, 'files': len(records)}))
```

</details>


<details>
<summary>trend_recheck_probes.py</summary>

SHA256: `4fdda54458e2f549102192623b196c90be9742a455c2621334fdb6b592a3a052`

```python
"""Deterministic offline probes for pinned1537794. No real client/credentials."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "snapshot"))
from services.weex_trend import engine as te
from services.trend_signals import loop as sl


def write(path, content):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content, encoding="utf-8")


te.atomic_write = write  # isolates persistence decisions from sandbox os.replace
OUT = HERE / "trend_probe_tmp"
OUT.mkdir(exist_ok=True)
res = {}


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def new(label, exchange_type=te.DryTrendExchange, **extra_cfg):
    folder = OUT / label
    folder.mkdir(exist_ok=True)
    clock, px = {"t": 1800000000.}, {"mid": 100.}
    ex = exchange_type(lambda: (px["mid"], px["mid"]), now_fn=lambda: clock["t"])
    cfg = {**te.DEFAULT, "risk_usd": 50., "max_notional_usd": 3000.,
           "enabled": True, "dry_run": False, "poll_sec": 0, **extra_cfg}
    signal_path = folder / "signal.json"
    signal = {"side": "LONG", "stop": 98., "entry_ts": iso(clock["t"])}
    write(signal_path, json.dumps({"ETHUSDT": signal}))
    t = te.Trend(ex, cfg, folder / "state.json", folder / "journal.jsonl", signal_path,
                 now_fn=lambda: clock["t"])
    t.st = {"symbol": "ETHUSDT", "episode": None, "pending": None, "last_episode": None,
            "realized": 0., "fees": 0., "n_trades": 0, "n_wins": 0, "seq": 0, "last_tick": 0.}
    return t, ex, clock, px, signal


def reopen(t, ex, clock):
    return te.Trend(ex, t.cfg, t.state_path, t.journal_path, t.signals_path,
                    now_fn=lambda: clock["t"])


# Corrections: ordinary hard-stop sizing, partial exit, partial outside, event time.
t, ex, clock, px, sig = new("fixed_risk")
t._maybe_open(sig, 100.)
t._on_opening(t.st["episode"], sig, 100.)
ep = t.st["episode"]
q, trigger = float(ep["qty"]), float(ep["stop"]["trigger"])
risk = q * (100. - trigger) + q * (100. + trigger) * .00048
assert risk <= 50.
res["fixed_risk"] = {"qty": q, "trigger": trigger, "loss_plus_fees_at_trigger": risk}

t, ex, clock, px, sig = new("fixed_partial")
ex.pos["LONG"] = .6
ex.orders["exit"] = {"status": "CANCELED", "executedQty": ".4", "avgPrice": "90"}
ex.trades["exit"] = [{"commission": ".01728"}]
ep = {"status": "closing", "side": "LONG", "qty": "1.000", "entry_px": 100., "chand": 98.,
      "entry_fee": .048, "t_open": clock["t"], "exit_order": {"id": "exit"}, "sig_entry_ts": sig["entry_ts"]}
t.st["episode"] = ep
t._on_closing(ep, 90.)
t.save()
assert float(t.st["episode"]["qty"]) == .6 and t.st["realized"] == -4.
assert len(ex.open_algo_orders("ETHUSDT")) == 1
clock["t"] += 60
after_restart = reopen(t, ex, clock)
after_restart.tick()
assert after_restart.st["realized"] == -4. and float(after_restart.st["episode"]["qty"]) == .6
res["fixed_partial"] = {"remaining": ep["qty"], "booked_gross": t.st["realized"],
                        "protective_qty": ex.open_algo_orders("ETHUSDT")[0]["quantity"],
                        "booked_gross_after_restart": after_restart.st["realized"]}

t, ex, clock, px, sig = new("fixed_outside")
ex.pos["LONG"] = .6
ep = {"status": "open", "side": "LONG", "qty": "1.000", "entry_px": 100., "chand": 98.,
      "entry_fee": .048, "t_open": clock["t"], "sig_entry_ts": sig["entry_ts"]}
t.st["episode"] = ep
t._closed_outside(ep, .6, 90.)
t.save()
assert float(ep["qty"]) == .6 and t.st["realized"] == -4.
assert len(ex.open_algo_orders("ETHUSDT")) == 1
res["fixed_outside"] = {"remaining": ep["qty"], "booked_gross": t.st["realized"],
                        "protective_qty": ex.open_algo_orders("ETHUSDT")[0]["quantity"]}

stamp = sl._signal_ts({"since": "2026-01-01T00:00:00Z"})
assert stamp == "2026-01-01T04:00:00+00:00"
res["fixed_signal_time"] = stamp


# Crash after successful acknowledgment and after pending=None is saved, but BEFORE
# the caller can attach entry_order. Durable intent and order ownership both vanish.
class Crash(BaseException):
    pass


t, ex, clock, px, sig = new("crash_ack_entry")
ordinary_save = t.save


def crash_save():
    ordinary_save()
    ep = t.st.get("episode")
    if ex.pos["LONG"] > 0 and t.st["pending"] is None and ep and not ep.get("entry_order"):
        raise Crash("process terminated after clearing pending acknowledgment")


t.save = crash_save
try:
    t._maybe_open(sig, 100.)
except Crash:
    pass
disk = json.loads(t.state_path.read_text(encoding="utf-8"))
r = reopen(t, ex, clock)
for _ in range(3):
    clock["t"] += 60
    r.tick()
assert r.st["episode"]["status"] == "opening" and r.st["pending"] is None
assert not r.st["episode"].get("entry_order") and not ex.open_algo_orders("ETHUSDT")
res["crash_ack_entry"] = {"exchange_position": ex.pos["LONG"], "disk_pending": disk["pending"],
                         "disk_entry_order": disk["episode"].get("entry_order"),
                         "after_restart_and_three_ticks_status": r.st["episode"]["status"], "protective_stops": 0}


# A known incomplete five-page search is treated as proof of absence after 120s.
class DenseHistory(te.DryTrendExchange):
    def order_history(self, symbol, limit=100, page=0, start_ms=None, end_ms=None):
        if page < 5:
            return [{"orderId": f"noise-{page}-{i}", "clientOrderId": f"manual-{page}-{i}"}
                    for i in range(100)]
        return super().order_history(symbol, limit=100, page=0)


t, ex, clock, px, sig = new("incomplete_history", DenseHistory)
real_market = ex.place_market


def lost_market(**kw):
    real_market(**kw)
    raise TimeoutError("response lost after actual fill")


ex.place_market = lost_market
t._maybe_open(sig, 100.)
assert t.st["pending"] is not None and ex.pos["LONG"] > 0
clock["t"] += 130
resolved = t._resolve_pending()
assert resolved and t.st["pending"] is None and t.st["episode"] is None
assert len(ex.order_history("ETHUSDT", page=5)) == 1
res["incomplete_history"] = {"pages_read": 5, "rows_each": 100, "actual_order_on_page": 5,
                             "resolver_says_done": resolved, "episode": None, "pending": None,
                             "orphan_exchange_qty": ex.pos["LONG"], "protective_stops": 0}


# Explicitly rejected exchange stop still leaves a full market position live.
class RejectStops(te.DryTrendExchange):
    def place_stop_market(self, **kw):
        return {"success": False, "code": "STOP_REJECTED"}


t, ex, clock, px, sig = new("rejected_stop", RejectStops)
t._maybe_open(sig, 100.)
t._on_opening(t.st["episode"], sig, 100.)
t.save()
px["mid"] = 96.5  # below the intended emergency trigger, during the current 4h bar
for _ in range(3):
    clock["t"] += 60
    reopen(t, ex, clock).tick()
stored = json.loads(t.state_path.read_text(encoding="utf-8"))
assert stored["episode"]["status"] == "open" and not stored["episode"].get("stop")
assert ex.pos["LONG"] > 0 and len(ex.orders) == 1
res["rejected_stop"] = {"state_status": stored["episode"]["status"], "known_stop": None,
                        "intended_hard_trigger": 96.53, "current_price": 96.5,
                        "live_qty_after_three_ticks": ex.pos["LONG"], "market_exit_orders": 0}


# Failed/unknown old-stop cancellation is logged and forgotten. It remains active
# after current episode finishes and can close the next position early.
t, ex, clock, px, sig = new("stop_cancel_unknown")
ex.pos["LONG"] = 1.
ep = {"status": "open", "side": "LONG", "qty": "1.000", "entry_px": 100., "chand": 98.,
      "entry_fee": .048, "t_open": clock["t"], "sig_entry_ts": sig["entry_ts"]}
t.st["episode"] = ep
t._place_stop(ep, 98.)
t.save()
old_stop = ep["stop"]["id"]
real_cancel = ex.cancel_algo


def unknown_cancel(aid):
    if aid == old_stop:
        raise TimeoutError("old cancel did not arrive")
    return real_cancel(aid)


ex.cancel_algo = unknown_cancel
t._place_stop(ep, 99.)
t.save()
new_stop = ep["stop"]["id"]
ex.pos["LONG"] = 0.  # current episode closed by its confirmed market exit
t._finish(ep, 110., .0528, "confirmed market exit")
t.save()
active_after_finish = [a["algoId"] for a in ex.open_algo_orders("ETHUSDT")]
assert active_after_finish == [old_stop]
# New unrelated episode intends a stop at 90, while forgotten old trigger=96.53.
ex.place_market("ETHUSDT", "BUY", "LONG", "1.000", "new-episode")
ex.place_stop_market("ETHUSDT", "SELL", "LONG", "1.000", "90", "new-episode-stop")
px["mid"] = 96.5
ex.book("ETHUSDT")
assert ex.pos["LONG"] == 0
res["stop_cancel_unknown"] = {"old_stop": old_stop, "tracked_replacement": new_stop,
                              "active_after_episode_finished": active_after_finish,
                              "next_episode_intended_stop": 90., "old_trigger": 96.53,
                              "next_episode_qty_after_old_trigger": ex.pos["LONG"]}


# Commission retrieval failure is stored as permanent zero, not an unresolved debt.
t, ex, clock, px, sig = new("delayed_commissions")
real_trades = ex.user_trades


def unavailable_trades(*args, **kwargs):
    raise TimeoutError("userTrades not available yet")


ex.user_trades = unavailable_trades
t._maybe_open(sig, 100.)
t._on_opening(t.st["episode"], sig, 100.)
px["mid"] = 110.
t._on_open(t.st["episode"], None, 110.)
t._on_closing(t.st["episode"], 110.)
t.save()
expected_fees = sum(float(tr["commission"]) for rows in ex.trades.values() for tr in rows)
ex.user_trades = real_trades
for _ in range(3):
    clock["t"] += 60
    reopen(t, ex, clock).tick()
stored = json.loads(t.state_path.read_text(encoding="utf-8"))
assert stored["fees"] == 0 and expected_fees > 0
res["delayed_commissions"] = {"actual_fees_available_after_recovery": expected_fees,
                             "fees_after_three_ticks": stored["fees"], "episode": stored["episode"]}


(HERE / "trend_recheck_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
print(json.dumps(res, indent=2))
```

</details>


<details>
<summary>trend_recheck_results.json</summary>

SHA256: `0230afc0939b8e128d8e1c0e5da255bb535c2cbe2fb32321938606920f5080f1`

```json
{
  "fixed_risk": {
    "qty": 14.005,
    "trigger": 96.53,
    "loss_plus_fees_at_trigger": 49.91850327199998
  },
  "fixed_partial": {
    "remaining": "0.600",
    "booked_gross": -4.0,
    "protective_qty": "0.600",
    "booked_gross_after_restart": -4.0
  },
  "fixed_outside": {
    "remaining": "0.600",
    "booked_gross": -4.0,
    "protective_qty": "0.600"
  },
  "fixed_signal_time": "2026-01-01T04:00:00+00:00",
  "crash_ack_entry": {
    "exchange_position": 14.005,
    "disk_pending": null,
    "disk_entry_order": null,
    "after_restart_and_three_ticks_status": "opening",
    "protective_stops": 0
  },
  "incomplete_history": {
    "pages_read": 5,
    "rows_each": 100,
    "actual_order_on_page": 5,
    "resolver_says_done": true,
    "episode": null,
    "pending": null,
    "orphan_exchange_qty": 14.005,
    "protective_stops": 0
  },
  "rejected_stop": {
    "state_status": "open",
    "known_stop": null,
    "intended_hard_trigger": 96.53,
    "current_price": 96.5,
    "live_qty_after_three_ticks": 14.005,
    "market_exit_orders": 0
  },
  "stop_cancel_unknown": {
    "old_stop": "da1",
    "tracked_replacement": "da2",
    "active_after_episode_finished": [
      "da1"
    ],
    "next_episode_intended_stop": 90.0,
    "old_trigger": 96.53,
    "next_episode_qty_after_old_trigger": 0.0
  },
  "delayed_commissions": {
    "actual_fees_available_after_recovery": 1.4117040000000003,
    "fees_after_three_ticks": 0.0,
    "episode": null
  }
}
```

</details>


<details>
<summary>grid_cap_probes.py</summary>

SHA256: `7dd726f64bebbd04318eeb3807dd4a9fb00b82bf6d1218b2618cc95f624733d5`

```python
"""Offline cap counterexamples on pinned WEEX code; no keys/network/live state."""
from __future__ import annotations
import json
import math
import sys
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SRC = HERE / "snapshot"
sys.path.insert(0, str(SRC))
from services.weex_grid import engine as eg, portfolio
from services.weex_grid.loop import Runner
from services.weex_trend import engine as te
from services.weex_trend.loop import files as trend_files
from tests.services.weex_grid.test_weex_grid_engine import make, Px, bot_open
from tests.services.weex_trend.test_weex_trend import setup, tick

OUT = HERE / "grid_cap_probe_files"
OUT.mkdir(exist_ok=True)

def folder(name):
    p = OUT / name
    p.mkdir(exist_ok=True)
    # All files are task-created synthetic files, each case starts clean.
    for f in p.glob("*.json*"):
        f.unlink()
    return p

def entries(ex):
    return [o for o in bot_open(ex) if not o["reduceOnly"]]

def committed(ex):
    return sum(float(o["origQty"]) * float(o["price"]) for o in entries(ex))

res = {"commit": "1537794bee0c8b1610f4ea808d2bd4e7a1b9595b", "cases": {}}

# A live orphan is discovered after the runner computed free from pre-adoption state.
p = folder("orphan")
g, ex = make(p, Px(), portfolio_free_usd=15., stress_budget_frac=0., daily_loss_stop_usd=0.)
ex.place_limit("BTCUSDT", "BUY", "LONG", "0.0001", "99800", "b7gBLorphan")
g.tick()
res["cases"]["orphan_adoption_then_other_side"] = {
    "cap": 15., "initial_state_used": 0., "actual_entry_commitments_after_tick": committed(ex),
    "persisted_used_after_tick": portfolio.used_usd([g.state_path], []),
    "open_entries": entries(ex), "room_used": g._room_used}
assert committed(ex) > 15.

# A removed trend symbol disappears from portfolio enumeration, despite live state.
p = folder("removed_symbol")
eth, xrp = p / "weex_trend_state.json", p / "weex_trend_xrp_state.json"
eth.write_text(json.dumps({"episode": None}), encoding="utf-8")
xrp.write_text(json.dumps({"episode": {"status": "open", "qty": "500", "entry_px": 1.5, "side": "LONG"}}), encoding="utf-8")
gridpath = p / "st.json"
with patch.object(te, "STATE", eth), patch.object(te, "load_config", return_value={"symbols": ["ETHUSDT"]}), \
     patch.object(portfolio, "load", return_value={"enabled": True, "gross_cap_usd": 1000.}), \
     patch("services.weex_grid.loop.run_files", return_value=(gridpath, p / "j.jsonl")):
    free = Runner()._portfolio_free()
g, ex = make(p, Px(), order_qty="0.004", max_notional_usd=2000., portfolio_free_usd=free,
             stress_budget_frac=0., daily_loss_stop_usd=0.)
g.tick()
actual_used = portfolio.used_usd([gridpath], [eth, xrp])
res["cases"]["removed_trend_symbol"] = {"cap": 1000., "known_old_xrp_cost": 750., "runner_reported_free": free,
    "new_grid_commitments": committed(ex), "used_including_removed_xrp": actual_used}
assert free == 1000. and actual_used > 1000.

# Real Trend opening stage persists qty and chand, but not the current entry price.
p = folder("trend_opening")
clock, tpx, tex, mt, sig = setup(p, risk_usd=50., max_notional_usd=100000., portfolio_free_usd=1000.)
sig("LONG", stop=2400.)
tick(mt, clock, 1)
state = json.loads((p / "st.json").read_text())
reserved = portfolio.used_usd([], [p / "st.json"])
actual_qty = tex.pos["LONG"]
actual_notional = actual_qty * float(next(iter(tex.orders.values()))["avgPrice"])
gp = folder("grid_after_trend_opening")
g, ex = make(gp, Px(), order_qty="0.0006", portfolio_free_usd=1000.-reserved,
             stress_budget_frac=0., daily_loss_stop_usd=0.)
g.tick()
res["cases"]["trend_opening_chand_reserve"] = {
    "cap": 1000., "opening_episode": state["episode"], "reserved": reserved,
    "actual_filled_qty": actual_qty, "actual_filled_notional": actual_notional,
    "new_grid_commitments": committed(ex), "actual_combined_commitment": actual_notional + committed(ex)}
assert actual_notional + committed(ex) > 1000.

# Parsed but nonfinite prices/quantities are not fail-closed: NaN propagates as free.
p = folder("nan_state")
tp = p / "bad_trend.json"
tp.write_text(json.dumps({"episode": {"qty": "NaN", "entry_px": 100.}}), encoding="utf-8")
with patch.object(portfolio, "load", return_value={"enabled": True, "gross_cap_usd": 15.}):
    free, used, cap = portfolio.free_usd([], [tp])
g, ex = make(p, Px(), portfolio_free_usd=free, stress_budget_frac=0., daily_loss_stop_usd=0.)
g.tick()
res["cases"]["nonfinite_state"] = {"cap": cap, "used_is_nan": math.isnan(used), "free_is_nan": math.isnan(free),
    "new_orders_should_be_zero": len(entries(ex)), "new_entry_commitments": committed(ex)}
assert math.isnan(free) and len(entries(ex)) == 2

# A known standing order whose local qty field is absent is silently valued as $0.
p = folder("missing_order_qty")
g, ex = make(p, Px(), sides=["LONG"], portfolio_free_usd=15., stress_budget_frac=0., daily_loss_stop_usd=0.)
g.tick()
g.st["LONG"]["entry"].pop("qty")
g.save()
used = portfolio.used_usd([g.state_path], [])
g.cfg.update(sides=["LONG", "SHORT"], portfolio_free_usd=15.-used)
g.tick()
res["cases"]["missing_order_qty"] = {"cap": 15., "persisted_used_before_tick": used,
    "actual_entry_commitments_after_tick": committed(ex), "open_entries": entries(ex)}
assert used == 0. and committed(ex) > 15.

(HERE / "grid_cap_probe_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
sys.stdout.buffer.write(json.dumps(res, ensure_ascii=False, indent=2).encode("utf-8"))
```

</details>


<details>
<summary>grid_cap_probe_results.json</summary>

SHA256: `7292488f16329a8f46e18208b8c74ab898a99f5785a2325a5c8647d4b04d4dbd`

```json
{
  "commit": "1537794bee0c8b1610f4ea808d2bd4e7a1b9595b",
  "cases": {
    "orphan_adoption_then_other_side": {
      "cap": 15.0,
      "initial_state_used": 0.0,
      "actual_entry_commitments_after_tick": 20.0,
      "persisted_used_after_tick": 20.0,
      "open_entries": [
        {
          "orderId": "dry1",
          "clientOrderId": "b7gBLorphan",
          "side": "BUY",
          "positionSide": "LONG",
          "price": "99800",
          "origQty": "0.0001",
          "status": "NEW",
          "executedQty": "0",
          "avgPrice": "0",
          "reduceOnly": false
        },
        {
          "orderId": "dry2",
          "clientOrderId": "b7gBSe18000000201",
          "side": "SELL",
          "positionSide": "SHORT",
          "price": "100200.0",
          "origQty": "0.0001",
          "status": "NEW",
          "executedQty": "0",
          "avgPrice": "0",
          "reduceOnly": false
        }
      ],
      "room_used": 10.020000000000001
    },
    "removed_trend_symbol": {
      "cap": 1000.0,
      "known_old_xrp_cost": 750.0,
      "runner_reported_free": 1000.0,
      "new_grid_commitments": 800.0,
      "used_including_removed_xrp": 1550.0
    },
    "trend_opening_chand_reserve": {
      "cap": 1000.0,
      "opening_episode": {
        "status": "opening",
        "sig_entry_ts": "2027-01-15T08:00:00+00:00",
        "side": "LONG",
        "qty": "0.361",
        "chand": 2400.0,
        "t_open": 1800000060.0,
        "entry_order": {
          "id": "dt1",
          "cid": "b7tEE18000000601"
        }
      },
      "reserved": 866.4,
      "actual_filled_qty": 0.361,
      "actual_filled_notional": 902.5036100000001,
      "new_grid_commitments": 120.0,
      "actual_combined_commitment": 1022.5036100000001
    },
    "nonfinite_state": {
      "cap": 15.0,
      "used_is_nan": true,
      "free_is_nan": true,
      "new_orders_should_be_zero": 2,
      "new_entry_commitments": 20.0
    },
    "missing_order_qty": {
      "cap": 15.0,
      "persisted_used_before_tick": 0.0,
      "actual_entry_commitments_after_tick": 20.0,
      "open_entries": [
        {
          "orderId": "dry1",
          "clientOrderId": "b7gBLe18000000201",
          "side": "BUY",
          "positionSide": "LONG",
          "price": "99800.0",
          "origQty": "0.0001",
          "status": "NEW",
          "executedQty": "0",
          "avgPrice": "0",
          "reduceOnly": false
        },
        {
          "orderId": "dry2",
          "clientOrderId": "b7gBSe18000000801",
          "side": "SELL",
          "positionSide": "SHORT",
          "price": "100200.0",
          "origQty": "0.0001",
          "status": "NEW",
          "executedQty": "0",
          "avgPrice": "0",
          "reduceOnly": false
        }
      ]
    }
  }
}
```

</details>


<details>
<summary>journal_trend_probe.py</summary>

SHA256: `5878d1e777f1d197edb52c11641ef64230edc0a370496b20412228ae6a8065d9`

```python
"""Offline probes against SHA1537794, using synthetic bars and in-memory fake journal."""
import ast
import copy
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SNAP = HERE / "snapshot"
spec = importlib.util.spec_from_file_location("pinned_journal", SNAP / "services/signal_journal/tradegpt.py")
tg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tg)
out = {}


def setup_row(row, bars):
    box = {"rows": [copy.deepcopy(row)], "calls": 0, "bars": bars}
    tg._read = lambda: copy.deepcopy(box["rows"])
    tg._write = lambda rows: box.update(rows=copy.deepcopy(rows))
    tg.price_at = lambda sym, ts: 100.0
    def fake_klines(sym, a, b):
        box["calls"] += 1
        return box["bars"]
    tg.klines = fake_klines
    return box


row = {"ts": datetime.fromtimestamp(30, timezone.utc).isoformat(), "symbol": "TESTUSDT", "side": "LONG"}
out["nextminute_repair"] = {"source30_seconds_entry": tg.entry_time(30),
                            "on_boundary_entry": tg.entry_time(60)}
assert out["nextminute_repair"]["source30_seconds_entry"] == 60
out["forwarded_publication_not_receipt"] = {
    "message_forward_date_seconds": 30,
    "message_date_receipt_seconds": 630,
    "caller_selected_ts": 30,
    "source_entry_seconds": tg.entry_time(30),
    "executable_nextminute_after_receipt_seconds": tg.entry_time(630),
    "source_entry_precedes_receipt_seconds": 630 - tg.entry_time(30),
    "source_caller": "telegram_runtime.py3633 forward_date or date",
}
out["internal_gap_repair"] = tg.barrier([(60000, 100, 100.2, 99.8, 100),
                                         (180000, 100, 101.2, 99.8, 101)],
                                        1, 100, 1, 3, False, start_ms=60000)
assert out["internal_gap_repair"] == (None, "дыра")

# Contiguous prefix reaches neither barrier but misses the remaining72h window.
box = setup_row(row, [(60000, 100, 100.6, 99.8, 100.5)])
r = tg.update_outcomes(now=60 + tg.MAX_H * 3600 + 1)
out["trailing_gap_falsely_finalized"] = {"bars_received": 1, "expected_minutes": tg.MAX_H * 60,
                                        "cached_return_pct": r[0]["tp1_sl3"],
                                        "cached_reason": r[0]["tp1_sl3_why"]}
assert r[0]["tp1_sl3_why"] == "TIME"
assert abs(r[0]["tp1_sl3"] - 0.4) < 1e-10

# Internal gap is detected but saved as a terminal reason, preventing repair.
box = setup_row(row, [(60000, 100, 100.2, 99.8, 100),
                      (180000, 100, 100.2, 99.8, 100)])
tg.update_outcomes(now=300)
calls_before = box["calls"]
box["bars"] = [(60000, 100, 100.2, 99.8, 100),
                (120000, 100, 100.1, 96, 97),
                (180000, 97, 100.2, 97.1, 100)]
tg.update_outcomes(now=400)
out["hole_does_not_retry"] = {"calls_before_repair": calls_before, "calls_after_repair": box["calls"],
                               "result_after_repair": box["rows"][0].get("tp1_sl3"),
                               "why_after_repair": box["rows"][0].get("tp1_sl3_why")}
assert box["calls"] == calls_before
assert box["rows"][0]["tp1_sl3_why"] == "дыра"

# Old cached prices and outcomes remain; the new model version never invalidates them.
legacy = {**row, "p0": 90.0, "p1": 91.0, "p4": 92.0, "p24": 93.0,
          "tp1_sl3": 0.9, "tp1_sl5": 0.9, "tp2_sl5": 1.9}
box = setup_row(legacy, [(60000, 100, 100.2, 99.8, 100)])
tg.update_outcomes(now=60 + 80 * 3600)
out["legacy_outcome_not_migrated"] = {"old_p0": 90.0, "new_minute_price": 100.0,
                                      "retained_p0": box["rows"][0]["p0"],
                                      "retained_return_pct": box["rows"][0]["tp1_sl3"],
                                      "retained_reason": box["rows"][0].get("tp1_sl3_why")}
assert box["rows"][0]["p0"] == 90

# Extract research trades() only; no loaders/downloaders executed.
p = SNAP / "research/weex/trend_risk_size.py"
tree = ast.parse(p.read_text(encoding="utf-8-sig"))
fn = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "trades")
def frame(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"],
                        index=pd.date_range("2026-01-01", periods=len(rows), freq="4h", tz="UTC"))
box = {"bars": None}
ns = {"np": np, "pd": pd, "FEE": 0.1, "BUF": 1.5, "load": lambda sym: box["bars"],
      "_atr": lambda d: pd.Series(1.0, index=d.index),
      "_adx": lambda d: (pd.Series(25.0, index=d.index), None, None)}
exec(compile(ast.Module(body=[fn], type_ignores=[]), str(p), "exec"), ns)
base = [[98, 99, 97, 98], [98, 99, 97, 98], [99, 101, 99, 100]]

# Hard initial trigger96.53 reached before close94; simulator does not execute it.
box["bars"] = frame(base + [[100, 100, 94, 94]])
tr, ix = ns["trades"]("TEST", lb=2)
t = tr[0]
notional = min(50 / (t["sd"] / 100), 3000)
out["trend_risk50_close_can_exceed_budget"] = {
    "entry": 100, "chandelier": 98, "hard_trigger": 96.53,
    "risk_sd_pct": t["sd"], "notional": notional,
    "source_exit_price": 94, "source_net_usd": t["pnl"] * notional / 100,
    "ideal_hard_trigger_net_usd_same_fee_model": -50.0,
    "note": "Gap/slippage can exceed50, but this simulator omits hard-stop fills entirely",
}
assert out["trend_risk50_close_can_exceed_budget"]["source_net_usd"] < -80

# Intrabar stop is touched, price recovers; source remains open and profits.
box["bars"] = frame(base + [[100, 100.2, 95, 100], [100, 106, 100, 105]])
tr, ix = ns["trades"]("TEST", lb=2)
t = tr[0]
notional = min(50 / (t["sd"] / 100), 3000)
out["trend_ignores_hard_stop_and_books_recovery"] = {
    "bar_low": 95, "hard_trigger": 96.53, "source_open_end": t["open"],
    "source_return_pct": t["pnl"], "source_net_usd": t["pnl"] * notional / 100,
    "ideal_trigger_exit_usd_same_fee_model": -50.0,
}
assert out["trend_ignores_hard_stop_and_books_recovery"]["source_net_usd"] > 60

# A position opened on final bar has path={}, so disappears despite final marking claim.
box["bars"] = frame(base)
tr, ix = ns["trades"]("TEST", lb=2)
out["trend_final_bar_entry_disappears"] = {
    "signal_and_entry_on_last_bar": True, "source_trade_count": len(tr),
    "entry_fee_and_final_open_inventory_included": False,
}
assert len(tr) == 0

(HERE / "journal_trend_probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=True, indent=2))
```

</details>


<details>
<summary>journal_trend_probe.json</summary>

SHA256: `4488d6f21bd0a87b1936a89102c587c11509f9e7f7dd6999fb3a8e580d520c25`

```json
{
  "nextminute_repair": {
    "source30_seconds_entry": 60,
    "on_boundary_entry": 120
  },
  "forwarded_publication_not_receipt": {
    "message_forward_date_seconds": 30,
    "message_date_receipt_seconds": 630,
    "caller_selected_ts": 30,
    "source_entry_seconds": 60,
    "executable_nextminute_after_receipt_seconds": 660,
    "source_entry_precedes_receipt_seconds": 570,
    "source_caller": "telegram_runtime.py3633 forward_date or date"
  },
  "internal_gap_repair": [
    null,
    "дыра"
  ],
  "trailing_gap_falsely_finalized": {
    "bars_received": 1,
    "expected_minutes": 4320,
    "cached_return_pct": 0.4,
    "cached_reason": "TIME"
  },
  "hole_does_not_retry": {
    "calls_before_repair": 1,
    "calls_after_repair": 1,
    "result_after_repair": null,
    "why_after_repair": "дыра"
  },
  "legacy_outcome_not_migrated": {
    "old_p0": 90.0,
    "new_minute_price": 100.0,
    "retained_p0": 90.0,
    "retained_return_pct": 0.9,
    "retained_reason": null
  },
  "trend_risk50_close_can_exceed_budget": {
    "entry": 100,
    "chandelier": 98,
    "hard_trigger": 96.53,
    "risk_sd_pct": 3.569999999999999,
    "notional": 1400.5602240896362,
    "source_exit_price": 94,
    "source_net_usd": -85.43417366946787,
    "ideal_hard_trigger_net_usd_same_fee_model": -50.0,
    "note": "Gap/slippage can exceed50, but this simulator omits hard-stop fills entirely"
  },
  "trend_ignores_hard_stop_and_books_recovery": {
    "bar_low": 95,
    "hard_trigger": 96.53,
    "source_open_end": true,
    "source_return_pct": 4.900000000000005,
    "source_net_usd": 68.62745098039224,
    "ideal_trigger_exit_usd_same_fee_model": -50.0
  },
  "trend_final_bar_entry_disappears": {
    "signal_and_entry_on_last_bar": true,
    "source_trade_count": 0,
    "entry_fee_and_final_open_inventory_included": false
  }
}
```

</details>


<details>
<summary>run_tests.py</summary>

SHA256: `1ef1bdc73fe79f2dbd5bd73ca16815d9b262e33857b84c776883ab594e6674d5`

```python
"""Offline source tests; no credentials/HTTP, optional Windows I/O retry."""
import json
from pathlib import Path
import socket
import sys
import time
import urllib.request
import pytest

HERE = Path(__file__).resolve().parent
(HERE/'snapshot/state').mkdir(exist_ok=True)
sys.path.insert(0, str(HERE/'snapshot'))
from services.weex_grid import engine as eg
from services.weex_trend import engine as te
from services.weex_api import client

def forbidden(*args, **kwargs):
    raise AssertionError('Offline audit forbids credentials and network')
client.load_credentials = forbidden
urllib.request.urlopen = forbidden
socket.create_connection = forbidden
socket.socket.connect = forbidden
original_write = eg.atomic_write
def retry_write(*args, **kwargs):
    for i in range(7):
        try:
            return original_write(*args, **kwargs)
        except PermissionError:
            if i == 6:
                raise
            time.sleep(.01*2**i)
eg.atomic_write = retry_write
te.atomic_write = retry_write
run = str(time.time_ns())
log = HERE/'verification'
log.mkdir(exist_ok=True)
code = pytest.main(['tests/services/weex_grid', 'tests/services/weex_trend', 'tests/services/signal_journal', 'tests/services/trend_signals', '-q', '--tb=short',
                    '--basetemp='+str(log/('temp_'+run)), '--junitxml='+str(log/('tests_'+run+'.xml'))])
(log/'summary.json').write_text(json.dumps({'exit_code': code, 'io_retry_in_harness_only': True,
    'junit': str(log/('tests_'+run+'.xml'))}, indent=2)+'\n', encoding='utf-8')
raise SystemExit(code)
```

</details>


<details>
<summary>verification/public_summary.json</summary>

SHA256: `e34f48afe31c9839eacbf766cd2624825a82d4407486a8d7ebc28d3c2ac23bbf`

```json
{
  "exit_code": 0,
  "io_retry_in_harness_only": true,
  "junit": "C:\\bot7\\research\\weex_state_recheck_20261011\\verification\\tests_1791718045161436500.xml",
  "tests": 107,
  "failures": 0,
  "errors": 0,
  "skipped": 0,
  "python": "3.10.12",
  "platform": "Windows-10-10.0.26200-SP0",
  "packages": {
    "numpy": "2.2.6",
    "pandas": "2.3.3",
    "pytest": "9.0.3"
  },
  "test_cases": [
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_first_tick_places_both_entries"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_fill_then_take_profit"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_refill_after_take_like_ginarea"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_trailing_when_flat"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_max_lots_and_notional"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_daily_loss_stop_halts_and_cancels"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_disable_removes_entries_keeps_takes"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_foreign_orders_untouched"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_restart_no_duplicates"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_fill_during_trailing_cancel_is_recorded"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_take_uses_lot_qty_after_size_change"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_wrong_size_take_is_replaced"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_phantom_lot_dropped_when_position_gone"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_entry_replaced_after_size_change"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_exchange_error_does_not_break_tick"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_engine",
      "name": "test_stress_budget_blocks_entry"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_multi",
      "name": "test_eth_created_off_and_dry"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_multi",
      "name": "test_eth_set_does_not_touch_btc"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_multi",
      "name": "test_command_routes_by_name"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_multi",
      "name": "test_gold_grid_off_with_sweep_params"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_multi",
      "name": "test_eth_qty_limit"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_multi",
      "name": "test_disabled_dry_grid_makes_no_requests"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_multi",
      "name": "test_eth_short_grid_cycle"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review2",
      "name": "test_broken_config_raises_instead_of_btc_default"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review2",
      "name": "test_config_symbol_must_match_template"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review2",
      "name": "test_runner_halts_broken_grid_without_touching_others"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review2",
      "name": "test_corrupt_state_halts_and_keeps_takes"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review2",
      "name": "test_state_of_other_symbol_rejected"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review2",
      "name": "test_save_is_atomic_and_complete"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review2",
      "name": "test_partial_external_close_keeps_remainder"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review2",
      "name": "test_pending_found_beyond_first_history_page"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review2",
      "name": "test_orphan_take_adopted_and_partial_fill_recorded"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review2",
      "name": "test_partial_entry_reserve_uses_its_remaining"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review2",
      "name": "test_live_partial_take_reflected"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review2",
      "name": "test_late_commission_settled"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review2",
      "name": "test_slots_count_parent_orders_not_fragments"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review2",
      "name": "test_cap_checked_at_final_price"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review3",
      "name": "test_stray_persisted_before_cancel"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review3",
      "name": "test_live_to_dry_keeps_tracking_strays"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review3",
      "name": "test_incomplete_pending_search_never_expires"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review3",
      "name": "test_side_removed_from_config_still_tracked"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review3",
      "name": "test_fee_cursor_of_live_partial_order_does_not_expire"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review3",
      "name": "test_legacy_fee_done_migrated"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review3",
      "name": "test_late_fee_found_behind_100_newer_trades"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review3",
      "name": "test_lost_take_mapping_after_recorded_partial_not_double"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review3",
      "name": "test_standing_entry_dropped_when_cap_lowered_below_it"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review3",
      "name": "test_command_waits_for_running_tick"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review4",
      "name": "test_unknown_take_does_not_block_stop"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review4",
      "name": "test_lost_take_mapping_then_new_partial_counted_once"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review4",
      "name": "test_clock_skew_pending_still_found"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review4",
      "name": "test_late_fee_settled_with_week_old_live_cursor_and_dense_history"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_review4",
      "name": "test_start_command_waits_for_real_tick"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_robust",
      "name": "test_lost_response_does_not_duplicate_entry"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_robust",
      "name": "test_lost_response_filled_order_recorded_once"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_robust",
      "name": "test_lost_response_not_placed_expires"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_robust",
      "name": "test_orphan_entry_adopted_when_side_has_none"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_robust",
      "name": "test_orphan_entry_tracked_until_terminal_when_cancel_lags"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_robust",
      "name": "test_partial_entry_gets_take_while_order_live"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_robust",
      "name": "test_partial_take_then_cancel_closes_only_rest"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_robust",
      "name": "test_external_close_is_not_free"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_robust",
      "name": "test_cap_counts_cost_not_only_value"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_robust",
      "name": "test_live_to_dry_cancels_live_entries"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_set",
      "name": "test_target_and_usd"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_set",
      "name": "test_stops_off_and_cap"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_set",
      "name": "test_engine_respects_disabled_stops"
    },
    {
      "class": "tests.services.weex_grid.test_weex_grid_set",
      "name": "test_limits_and_unknown"
    },
    {
      "class": "tests.services.weex_grid.test_weex_portfolio",
      "name": "test_grid_entry_blocked_by_portfolio"
    },
    {
      "class": "tests.services.weex_grid.test_weex_portfolio",
      "name": "test_grid_entry_allowed_with_room"
    },
    {
      "class": "tests.services.weex_grid.test_weex_portfolio",
      "name": "test_used_counts_live_grid_lots_and_trend"
    },
    {
      "class": "tests.services.weex_grid.test_weex_portfolio",
      "name": "test_trend_size_cut_by_portfolio"
    },
    {
      "class": "tests.services.weex_grid.test_weex_review5",
      "name": "test_trend_risk_is_to_exchange_stop"
    },
    {
      "class": "tests.services.weex_grid.test_weex_review5",
      "name": "test_trend_partial_exit_keeps_rest_protected"
    },
    {
      "class": "tests.services.weex_grid.test_weex_review5",
      "name": "test_trend_partial_outside_reduction_keeps_episode"
    },
    {
      "class": "tests.services.weex_grid.test_weex_review5",
      "name": "test_used_counts_entries_pending_strays"
    },
    {
      "class": "tests.services.weex_grid.test_weex_review5",
      "name": "test_unreadable_state_blocks_not_zero"
    },
    {
      "class": "tests.services.weex_grid.test_weex_review5",
      "name": "test_grid_room_not_reused_within_tick"
    },
    {
      "class": "tests.services.weex_grid.test_weex_review5",
      "name": "test_grid_standing_entry_kept_with_tight_room"
    },
    {
      "class": "tests.services.weex_grid.test_weex_review5",
      "name": "test_trend_runner_recomputes_room_per_symbol"
    },
    {
      "class": "tests.services.weex_trend.test_weex_trend",
      "name": "test_fresh_short_signal_opens_with_risk_sizing"
    },
    {
      "class": "tests.services.weex_trend.test_weex_trend",
      "name": "test_notional_cap_limits_size"
    },
    {
      "class": "tests.services.weex_trend.test_weex_trend",
      "name": "test_old_signal_is_skipped"
    },
    {
      "class": "tests.services.weex_trend.test_weex_trend",
      "name": "test_signal_exit_closes_and_cancels_stop"
    },
    {
      "class": "tests.services.weex_trend.test_weex_trend",
      "name": "test_emergency_stop_closes_and_no_reentry_same_episode"
    },
    {
      "class": "tests.services.weex_trend.test_weex_trend",
      "name": "test_trailing_moves_emergency_stop_only_favourably"
    },
    {
      "class": "tests.services.weex_trend.test_weex_trend",
      "name": "test_lost_entry_response_no_double_entry"
    },
    {
      "class": "tests.services.weex_trend.test_weex_trend",
      "name": "test_disabled_keeps_managing_open_position"
    },
    {
      "class": "tests.services.weex_trend.test_weex_trend",
      "name": "test_xrp_lot_step_ten"
    },
    {
      "class": "tests.services.weex_trend.test_weex_trend",
      "name": "test_runner_files_per_symbol"
    },
    {
      "class": "tests.services.weex_trend.test_weex_trend",
      "name": "test_broken_state_halts"
    },
    {
      "class": "tests.services.weex_trend.test_weex_trend",
      "name": "test_unreadable_signals_file_does_nothing"
    },
    {
      "class": "tests.services.signal_journal.test_tradegpt",
      "name": "test_parse_operator_sample"
    },
    {
      "class": "tests.services.signal_journal.test_tradegpt",
      "name": "test_long_and_not_tradegpt"
    },
    {
      "class": "tests.services.signal_journal.test_tradegpt",
      "name": "test_barrier_rules"
    },
    {
      "class": "tests.services.signal_journal.test_tradegpt",
      "name": "test_barrier_gap_not_counted"
    },
    {
      "class": "tests.services.signal_journal.test_tradegpt",
      "name": "test_entry_is_next_full_minute_after_receipt"
    },
    {
      "class": "tests.services.signal_journal.test_tradegpt",
      "name": "test_virtual_trades_in_journal"
    },
    {
      "class": "tests.services.signal_journal.test_tradegpt",
      "name": "test_record_dedup_and_summary"
    },
    {
      "class": "tests.services.trend_signals.test_trend_signals",
      "name": "test_forming_4h_bar_is_dropped"
    },
    {
      "class": "tests.services.trend_signals.test_trend_signals",
      "name": "test_tg_symbols_journal_all_send_only_allowed"
    },
    {
      "class": "tests.services.trend_signals.test_trend_signals",
      "name": "test_only_validated_assets_are_watched"
    },
    {
      "class": "tests.services.trend_signals.test_trend_signals",
      "name": "test_entry_signal_journaled_and_sent"
    },
    {
      "class": "tests.services.trend_signals.test_trend_signals",
      "name": "test_no_duplicate_entry_while_in_position"
    },
    {
      "class": "tests.services.trend_signals.test_trend_signals",
      "name": "test_exit_computes_pnl_without_button"
    },
    {
      "class": "tests.services.trend_signals.test_trend_signals",
      "name": "test_exhaustion_fires_once_per_episode"
    },
    {
      "class": "tests.services.trend_signals.test_trend_signals",
      "name": "test_disabled_config_silences"
    },
    {
      "class": "tests.services.trend_signals.test_trend_signals",
      "name": "test_summarize_reads_journal"
    },
    {
      "class": "tests.services.trend_signals.test_trend_signals",
      "name": "test_entry_ts_is_signal_bar_close_not_discovery"
    }
  ]
}
```

</details>


<details>
<summary>source_manifest.json</summary>

SHA256: `ad4d8f5ee85d2fcf30cb50d0e5be9ec5c8181d32c8b0a5231a8d140e6ecc7028`

```json
{
  "commit": "1537794bee0c8b1610f4ea808d2bd4e7a1b9595b",
  "files": [
    {
      "path": "CLAUDE.md",
      "bytes": 9206,
      "git_blob": "5c9bc1a03abc91eb21b1c50c2eb1a1c4d0b842e7"
    },
    {
      "path": "conftest.py",
      "bytes": 813,
      "git_blob": "b01732c6888248ae1824fa0acb2f3e01ceacd103"
    },
    {
      "path": "docs/WEEX_GPT_STATE_REVIEW_ANSWERS_2026-10-11.md",
      "bytes": 8877,
      "git_blob": "fe85b8572865d9b6a5f3941fe0de054facff6a86"
    },
    {
      "path": "docs/WEEX_STATE_FOR_GPT_2026-10-11.md",
      "bytes": 12286,
      "git_blob": "fc985cb2eed604daa78a734b2ff024ddb3bd66dc"
    },
    {
      "path": "pytest.ini",
      "bytes": 109,
      "git_blob": "bba2e296a6868878892129a49a93730967c4c94e"
    },
    {
      "path": "research/carry/carry_check.py",
      "bytes": 4110,
      "git_blob": "81a72a3592b647e7dbcc64aa62eb68ffb9e47734"
    },
    {
      "path": "research/carry/funding_rotation.py",
      "bytes": 5756,
      "git_blob": "5b878df20c0479566f9103ad63eae4cf5131f553"
    },
    {
      "path": "research/tradegpt/backtest.py",
      "bytes": 6724,
      "git_blob": "f23150a78b997b8a75829e42226da366930badf6"
    },
    {
      "path": "research/tradegpt/barrier.py",
      "bytes": 4493,
      "git_blob": "d550b14b13f38545b7bbae56922d32901a3272eb"
    },
    {
      "path": "research/tradegpt/claims_check.py",
      "bytes": 5803,
      "git_blob": "793fd6458d252196dfc717c73b37d5d0f61e34fb"
    },
    {
      "path": "research/tradegpt/record_pasted.py",
      "bytes": 642,
      "git_blob": "ebf13bdce57763cd2d1f5e6cdc0b7f8cc3cfbcf2"
    },
    {
      "path": "research/trend_expand/scan.py",
      "bytes": 5520,
      "git_blob": "7c13e016ffbe822064fe8e4d5b8fe2a55e211e0b"
    },
    {
      "path": "research/weex/btc_intensity.py",
      "bytes": 2342,
      "git_blob": "8c56479f4783eb68d4cfc0e7ee28e4e39a47d4cd"
    },
    {
      "path": "research/weex/btc_wide.py",
      "bytes": 2522,
      "git_blob": "1e2f5db6595b8b7c928657bfe23613c84547fdaa"
    },
    {
      "path": "research/weex/card_now.py",
      "bytes": 325,
      "git_blob": "c6211134ec96ceb2ee2369265562d1396b380416"
    },
    {
      "path": "research/weex/check_connection.py",
      "bytes": 1139,
      "git_blob": "9d68d126fb3793b28c0176b7c883c52f8dc30ef1"
    },
    {
      "path": "research/weex/contract_specs.py",
      "bytes": 784,
      "git_blob": "3a01a4401432170335dd02e0d3235dcf6ecfa25f"
    },
    {
      "path": "research/weex/eth_auto_oos.py",
      "bytes": 1926,
      "git_blob": "54d9c0b8d03b85b8accbd80b509c6c1c9663f478"
    },
    {
      "path": "research/weex/eth_auto_recheck.py",
      "bytes": 3159,
      "git_blob": "312a7ba850f7294c37e0c23addc8478397d843c2"
    },
    {
      "path": "research/weex/eth_auto_sim2.py",
      "bytes": 8424,
      "git_blob": "c905c3a20cbcefc89fcb608f3e075f0555848109"
    },
    {
      "path": "research/weex/eth_ginarea_last.py",
      "bytes": 1743,
      "git_blob": "05e6715c9c626101996a8b160cb32329ce945922"
    },
    {
      "path": "research/weex/eth_trend_levels.py",
      "bytes": 841,
      "git_blob": "37a4708a8a81fad5366655f97c64a51fd2d2b731"
    },
    {
      "path": "research/weex/exchange_info.py",
      "bytes": 563,
      "git_blob": "bb77c59415646bb17bc4bb90220f478e224c10c5"
    },
    {
      "path": "research/weex/fast_grid.py",
      "bytes": 13064,
      "git_blob": "74151e0de88c847a934d9a589a90f362415f4b00"
    },
    {
      "path": "research/weex/fetch_1m.py",
      "bytes": 2046,
      "git_blob": "62b4b68284f677a2556dfd494d2f55f60a7487f8"
    },
    {
      "path": "research/weex/fetch_ginarea_docs.py",
      "bytes": 1333,
      "git_blob": "f928292419e30b79e883ecfded5355f87c88ca37"
    },
    {
      "path": "research/weex/gate_cap_check.py",
      "bytes": 1406,
      "git_blob": "9349010b36b9ec43010408653730f5c34512f526"
    },
    {
      "path": "research/weex/gate_compare.py",
      "bytes": 4721,
      "git_blob": "864f83cce15cc36d20c567fca6e9649c2a95756a"
    },
    {
      "path": "research/weex/ginarea_dyn_events.py",
      "bytes": 1215,
      "git_blob": "77f70d2a463aa265b6e797cbd5fa671c1d697ce2"
    },
    {
      "path": "research/weex/ginarea_dyn_extract.py",
      "bytes": 2893,
      "git_blob": "4463220f76b4e29a1deb017a801c1322181a87ee"
    },
    {
      "path": "research/weex/ginarea_params_last.py",
      "bytes": 888,
      "git_blob": "275d244b24ed812b5be273fae69e4973de421e6c"
    },
    {
      "path": "research/weex/ginarea_refill_check.py",
      "bytes": 3095,
      "git_blob": "61a154160c676ee3ff5ba3277a44d706dafe5dad"
    },
    {
      "path": "research/weex/gold_venue_check.py",
      "bytes": 2528,
      "git_blob": "7de682f771e60a504373b1d3ab8ebebb890d1cb6"
    },
    {
      "path": "research/weex/idle_debug.py",
      "bytes": 2043,
      "git_blob": "3461d85a3eb933ebf42a32e8fb9f7f26faf26802"
    },
    {
      "path": "research/weex/income_check.py",
      "bytes": 2341,
      "git_blob": "0c0aea0d1458d155fceed215158715e4fd37f5ac"
    },
    {
      "path": "research/weex/live_check.py",
      "bytes": 2482,
      "git_blob": "bf1fcca6059d9dfaff48beb18a27ee55e0b76a8d"
    },
    {
      "path": "research/weex/make_gpt_bundle.py",
      "bytes": 5234,
      "git_blob": "b2fdd55cda27946cc2ab9d3e1160c2667827ac20"
    },
    {
      "path": "research/weex/my_fees.py",
      "bytes": 609,
      "git_blob": "7ad03509ee4ec3d8f142d2a39d08dbaf1c85f877"
    },
    {
      "path": "research/weex/orphan_check.py",
      "bytes": 1571,
      "git_blob": "e2779f2b76c72a98d0d22eef9202800b422fe0c5"
    },
    {
      "path": "research/weex/pnl_reconcile.py",
      "bytes": 4429,
      "git_blob": "c7b71929cacf0bf26d58e3f1b8eb7808bddecc6f"
    },
    {
      "path": "research/weex/price_path.py",
      "bytes": 1284,
      "git_blob": "f6a2598849a61d12c2a55d1efed3a0518bfc08f7"
    },
    {
      "path": "research/weex/refill_compare.py",
      "bytes": 4590,
      "git_blob": "28763a7d9f4288be28823b13d3c810276ee8882b"
    },
    {
      "path": "research/weex/request_rate.py",
      "bytes": 3065,
      "git_blob": "8ba3a0e463a1b46301e7847b6fc41f2e383a3fc8"
    },
    {
      "path": "research/weex/run_out_1_validate_fast.txt",
      "bytes": 626,
      "git_blob": "a4da0930d557c8c0579684b9bd0e6d07d63aa79f"
    },
    {
      "path": "research/weex/run_out_2_ginarea_refill.txt",
      "bytes": 5408,
      "git_blob": "69d95c39be206ad891348123d25905042f6bcc50"
    },
    {
      "path": "research/weex/run_out_4_sweep_live_sizes.txt",
      "bytes": 4047,
      "git_blob": "4e5c5410c7d7f7534f1ee25918ea5c420cf05014"
    },
    {
      "path": "research/weex/run_out_5_sweep_method_fixed.txt",
      "bytes": 4047,
      "git_blob": "cd28a2d729faa702f2bb6732f66de433bbc78bc1"
    },
    {
      "path": "research/weex/sweep_BTCUSDT_both_0.2-0.3-0.5-0.75_q0.0012.jsonl",
      "bytes": 13129,
      "git_blob": "167aa70d27cf7ab303f2659c8cf92b8719643800"
    },
    {
      "path": "research/weex/sweep_ETHUSDT_short_0.2-0.3-0.5-0.75-1.0.jsonl",
      "bytes": 18709,
      "git_blob": "ce280f8a516b765ffa2bef74b25f09f53a81b5bb"
    },
    {
      "path": "research/weex/sweep_XAUUSDT_both_0.5-0.75-1.0_q0.023.jsonl",
      "bytes": 7301,
      "git_blob": "e539cf00747f5e4b3ea0c195f9277210c8d9b6a5"
    },
    {
      "path": "research/weex/sweep_grid.py",
      "bytes": 3884,
      "git_blob": "6689256b8d96b6309eac836c715a7cb2f1b0fd7c"
    },
    {
      "path": "research/weex/trail_1s_check.py",
      "bytes": 3026,
      "git_blob": "153b07407700594ad39cdcbf270e88dec2ad76f8"
    },
    {
      "path": "research/weex/trail_exit_compare.py",
      "bytes": 2384,
      "git_blob": "6adef7ab0c8391fcab7655bb879990e7b205f61f"
    },
    {
      "path": "research/weex/trend_live_stats.py",
      "bytes": 1444,
      "git_blob": "8a091989a8fb56994befa9fe726a188ba0c4449d"
    },
    {
      "path": "research/weex/trend_risk_size.py",
      "bytes": 5337,
      "git_blob": "2cf292b65cc0276d3da4d86918b334251ad4268b"
    },
    {
      "path": "research/weex/trend_sides.py",
      "bytes": 5672,
      "git_blob": "b9b6d6bf5c8dd0b859a9e48d5dea2f7ea40f15be"
    },
    {
      "path": "research/weex/validate_fast.py",
      "bytes": 1672,
      "git_blob": "188f5bc4e1bde31086e10730dc6f333e9a59b473"
    },
    {
      "path": "research/weex/volume_grid_summary.py",
      "bytes": 1691,
      "git_blob": "77a724ea6a9cad1e0acbbf12d398be6bbad4b2c6"
    },
    {
      "path": "research/weex/volume_grid_sweep.py",
      "bytes": 2899,
      "git_blob": "04803449032869056932b77934b8577a17a0da2d"
    },
    {
      "path": "services/__init__.py",
      "bytes": 0,
      "git_blob": "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    },
    {
      "path": "services/short_gate/__init__.py",
      "bytes": 63,
      "git_blob": "e860362e3ebb60d44d8bd2192e08d8637b828ff7"
    },
    {
      "path": "services/short_gate/loop.py",
      "bytes": 10606,
      "git_blob": "16d7d4b0bf40fd825dc5174f2741654ceb38a958"
    },
    {
      "path": "services/signal_journal/tradegpt.py",
      "bytes": 11939,
      "git_blob": "adb42a8b1a4a00429b940bd0e2a93f2d045b36d0"
    },
    {
      "path": "services/telegram_runtime.py",
      "bytes": 196094,
      "git_blob": "9c786b2bc7b89e26197102993dc94c3651cc0313"
    },
    {
      "path": "services/trend_signals/loop.py",
      "bytes": 11744,
      "git_blob": "af0c2d67f19a9ad3c62ab3258a58a8e49a1bca80"
    },
    {
      "path": "services/weex_api/__init__.py",
      "bytes": 279,
      "git_blob": "d9e6bffe55afb5de29a67485aeb12b535b558341"
    },
    {
      "path": "services/weex_api/client.py",
      "bytes": 10293,
      "git_blob": "d4dc0dd4178388f7136dd476066df65b38313ab6"
    },
    {
      "path": "services/weex_grid/__init__.py",
      "bytes": 1215,
      "git_blob": "552c24e92f7c4750e1889100608c39c6c876e3d4"
    },
    {
      "path": "services/weex_grid/engine.py",
      "bytes": 63811,
      "git_blob": "0b5ce3bbc13590211c079b9278566e90163d4c61"
    },
    {
      "path": "services/weex_grid/loop.py",
      "bytes": 22346,
      "git_blob": "f3d5fc2ab0defe00d139736d62649961d9aad4fb"
    },
    {
      "path": "services/weex_grid/portfolio.py",
      "bytes": 4677,
      "git_blob": "d9d953a2e6f510967d319fa6897895f0b2be7ce3"
    },
    {
      "path": "services/weex_trend/__init__.py",
      "bytes": 107,
      "git_blob": "38adfb60d03813c1df80c9933836004d2bb915b1"
    },
    {
      "path": "services/weex_trend/engine.py",
      "bytes": 32324,
      "git_blob": "f0ab128e443b6a79b0deddae81f7f5be21c8c1e5"
    },
    {
      "path": "services/weex_trend/loop.py",
      "bytes": 8922,
      "git_blob": "40797b98a43832bd68ffea1a9c191ab9a0c0f626"
    },
    {
      "path": "tests/__init__.py",
      "bytes": 101,
      "git_blob": "427be2d332ac5eec849623132938d4165fb0bc26"
    },
    {
      "path": "tests/conftest.py",
      "bytes": 144,
      "git_blob": "2a855d9fdb8debae0b082088580a4c41e499e33c"
    },
    {
      "path": "tests/services/__init__.py",
      "bytes": 0,
      "git_blob": "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    },
    {
      "path": "tests/services/signal_journal/test_tradegpt.py",
      "bytes": 5419,
      "git_blob": "d6811fbcb0d14baad03f70927b2317b3863a942d"
    },
    {
      "path": "tests/services/trend_signals/__init__.py",
      "bytes": 0,
      "git_blob": "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    },
    {
      "path": "tests/services/trend_signals/test_trend_signals.py",
      "bytes": 6980,
      "git_blob": "8e611b0b2c9d7cb4d733c56a52cc171ce1b50bbc"
    },
    {
      "path": "tests/services/weex_grid/test_weex_grid_engine.py",
      "bytes": 8933,
      "git_blob": "611a5f7520fe0777895f0a10b2da6164f2a7fa1a"
    },
    {
      "path": "tests/services/weex_grid/test_weex_grid_multi.py",
      "bytes": 4624,
      "git_blob": "bb908b3f488434836d90a569a87b10b940a24298"
    },
    {
      "path": "tests/services/weex_grid/test_weex_grid_review2.py",
      "bytes": 11530,
      "git_blob": "369f4b5d4622474174bb3e173ee33e4c06a9f198"
    },
    {
      "path": "tests/services/weex_grid/test_weex_grid_review3.py",
      "bytes": 11368,
      "git_blob": "abe1149d9225f852ad2028fe2bf22426e2729fec"
    },
    {
      "path": "tests/services/weex_grid/test_weex_grid_review4.py",
      "bytes": 8717,
      "git_blob": "a3cb0b8a777507b9411a185559a81ead7ca4da5a"
    },
    {
      "path": "tests/services/weex_grid/test_weex_grid_robust.py",
      "bytes": 9913,
      "git_blob": "845cd78379ec096d401aa4c6971f802b97a30514"
    },
    {
      "path": "tests/services/weex_grid/test_weex_grid_set.py",
      "bytes": 2353,
      "git_blob": "adbfcd415650e329ca5f621d1badcfa4f04167f0"
    },
    {
      "path": "tests/services/weex_grid/test_weex_portfolio.py",
      "bytes": 2133,
      "git_blob": "20267f3c90533f6689a73dc19fd3601f4cae29ac"
    },
    {
      "path": "tests/services/weex_grid/test_weex_review5.py",
      "bytes": 7149,
      "git_blob": "00a029a9891bda3711ed00341569ff8f0b741af1"
    },
    {
      "path": "tests/services/weex_trend/test_weex_trend.py",
      "bytes": 9266,
      "git_blob": "2259d4e45bd7a29627c5ad10993820fb29167669"
    },
    {
      "path": "tools/trend_state.py",
      "bytes": 12928,
      "git_blob": "2e24eb0343a96131599e993ae2f062c0e51d8af0"
    }
  ]
}
```

</details>
