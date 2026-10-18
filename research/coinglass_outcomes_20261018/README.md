# CoinGlass: исправление досверки аналитики, кандидат на review

18.10.2026. Реализованы конечная 96h история и отдельный offline evaluator. Реальные рыночные запросы новым helper не запускались; автоматизация, старые VERIFIED_FILES, архивы, заметки, журнал пилота и боты не изменены. По [согласованному порядку](../../docs/COINGLASS_G0_AND_WORKFLOW_REPLY_2026-10-18.md) сначала независимое review чтением, затем отдельное включение.

## Что исправлено

- Один конечный public fetch: максимум шесть GET, 384 закрытых 15m свечи spot/perpetual и 385 OI-точек. Из того же ответа выделяется прежний суточный tail96/97 с теми же семантическими определениями. Новая история отделена от суточного контекста. Funding остаётся24h, текущий premium не является свечой. Никакой скрытой дозагрузки или повторов.
- Числовой analysis и человеческий analyst_note — отдельные записи. Для текста anchor строго ceil(max(note-created, analysis-created)/15m). Первый legacy note без analysis_id связывается только с единственным analysis того же input_run; неоднозначность остаётся missing.
- Проверяются фактические frozen semantics и их hash, endpoint/product/symbol/interval/units исходной истории, а также SHA всех связанных старых daily inputs уже при первом допуске. Нельзя приклеить старый hash к другому активу или изменённому отчёту.
- Каждый горизонт требует всю точную закрытую сетку. PENDING, MISSING, CONFLICT и MATURE различаются; zero не заменяет missing. Дополнительная15m граница допуска относится к ожиданию нового refresh, а не к разрешению незакрытых свечей.
- Противоречащие версии OHLC исключают соответствующую цену навсегда для данной совокупности входов. Declared conflict из collector сохраняется, даже если плохие копии уже удалены из observations. Конфликт только объёма между сохранёнными версиями свечи не уничтожает неизменную цену: price=MATURE, flow=CONFLICT. Конфликтующие дубликаты внутри одного ответа collector исключаются целиком и консервативно дают price=CONFLICT, даже если OHLC совпали. OI и flow могут отсутствовать независимо от достоверной цены; F при нулевом объёме null.
- Новая история или созревание горизонта создают supplement без нового daily run. Тот же набор входов и та же фаза возвращают существующий supplement. Ранее прочитанные файлы нельзя изменить или удалить из входного набора. Старые report/note/supplement не переписываются.
- Все заметки досверяются, в обзоре явно указываются последняя и непосредственно предыдущая по времени человеческие записи. Произвольные текстовые условия не исполняются и автоматически не оцениваются: ценовой путь не выдаётся за проверку повествования.

## Файлы и интерфейс

`history_fetch.py`: [детали fetch и официальные ограничения API](FETCH_README.md). ABI `collect(client, include_premium=True, clock=..., synthetic=False)` возвращает `(history, daily_fragment, evidence)`. Историческая доступность API OI ограничена последним месяцем; выбранное окно96h не гарантирует покрытие более длинного перерыва. Задержка CoinGlass остаётся неизвестной.

`evaluator.py`: runtime только stdlib, без импорта старых helpers, аккаунта или сетевого клиента. Читает ожидаемые public daily report, analysis report, analyst-note JSON и явные history roots. Не читает JPEG/DOM/raw evidence, narrative markdown или path из note.analysis_path. Ссылки на analysis разрешаются только внутри выбранной папки analytics. Symlink/junction/reparse и произвольные выходы за выбранный root отклоняются; JSON ограничен32MiB.

Выход: новый `supplement_<input-and-phase-sha>/report.json`, `summary.md`, `integrity.json`. ID зависит от code SHA, content hashes входов, фаз созревания и допуска истории. Времена создания фактические. Неполное соединение/неудачный clock не становятся ложным отсутствием событий или полноценной историей. При завершённом supplement код сверяет его целостность перед reuse.

## Проверка без сети

Из этой новой папки, Python3.11+:

```text
python -X utf8 -B -m unittest -v test_evaluator test_history_fetch qa_independent.test_integrity_independent
```

Root выполнил83 теста:82PASS, одинSKIP создания настоящего Windows symlink без соответствующей привилегии. Отдельные mocked reparse/path проверки прошли. Все данные вымышленные. Проверены поздний note, три записи и правильный предшественник, обычный день/трёхдневный перерыв, границы свечей, противоречия, контекст без OI, idempotence, первое SHA-связывание, tampered supplement, безопасная публикация и collector→evaluator integration. Transient WinError5 rename обработан ограниченным retry только для собственного staging; permission changes и замены destination нет.

## После независимого review: порядок активации

Это инструкции для будущего включения, не выполненные команды и не изменение расписания.

1. Сверить код/документы по новому manifest и получить review. Не запускать оба старый и новый сетевые fetch в одном daily job: новый заменяет прежний public fetch, сохраняет общий предел6GET. Browser-контекст остаётся прежними четырьмя страницами. До включения действует прежний процесс с честно отмеченными ограничениями.
2. Один раз получить history в новой `local/history_<actualms>` папке командой из FETCH_README.md. Его `public_sources.json` соединить с четырьмя CoinGlass источниками того же фактического конечного сбора и архивировать прежним archive_daily.py. Raw history/evidence остаются локально; использовать существующий сегодняшний пакет повторно, не создавать дубликат сайта ради evaluator.
3. Запустить evaluator отдельно. Сохранять все прежние history inputs, чтобы обнаруженные конфликты и SHA не терялись. Окончание старого периода вне96h не чинится свечным forward-fill.

```powershell
& 'C:\Users\Kemper\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -X utf8 -B 'C:\bot7\research\coinglass_outcomes_20261018\evaluator.py' --local-root 'C:\bot7\research\coinglass_daily_context_20261016\local' --history-root 'C:\bot7\research\coinglass_outcomes_20261018\local' --outroot 'C:\bot7\research\coinglass_outcomes_20261018\local\supplements'
```

History root может быть конкретной папкой с history.json либо контейнером с непосредственными history_/preflight_/run_<milliseconds> детьми. Схема synthetic=true от реальной досверки исключается. Evaluator пишет только в собственный outroot; дата-папки старого архива/analytics/notes не являются местом назначения.

4. Для независимой минутной проверки опционально добавить `--public-export <новый_JSON_путь>`. Export содержит только opaque ID записи, anchorUTC, рынок, горизонт, статус, open/close/return, покрытие и SHA. Нет текста заметки, screenshot, файловых путей, ключей, ордеров и raw CoinGlass. Export пишется exclusive create. Передавать в GitHub только этот минимальный aggregate после фактического расчёта; сейчас реальных outcome aggregates в пакете нет.
5. Проверяющий пересчитывает те же моменты по своему уже записанному Binance1m: open минуты anchor и close последней минуты каждого горизонта, отдельно spot/perpetual. Это независимые получение/реализация для того же рынка, не другая статистически независимая рыночная траектория. Возвращает расхождения anchor/market/horizon/own values. Полный код на хосте с торговыми ключами запускать не требуется.

Старые MISSING остаются старым результатом проверки. Последующий supplement может честно восстановить ценовое покрытие, но не отсутствовавший снимок CoinGlass и не прежнюю доступность данных. Включение требует отдельно обновить проверенные manifests/protocol/automation целиком после review; этот коммит не объявляет такую активацию уже сделанной.
