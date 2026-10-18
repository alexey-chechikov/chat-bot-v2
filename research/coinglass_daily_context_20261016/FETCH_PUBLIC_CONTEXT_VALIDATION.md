# Finite public fetcher — offline validation, 16.10.2026

```text
python -B -m unittest -v test_fetch_public_context
Ran 25 tests in 0.422s
OK
```

Тесты используют только выдуманные ответы FakeClient и локальные temporary
files. PublicClient transport в его unit test замокан; ни одного рыночного
HTTP-запроса в этой подзадаче не выполнено. Просмотрены только официальные docs.
Негативные CLI-тесты намеренно печатают ошибки без --run-network/при overwrite.

После независимого path QA добавлены pre-GET/pre-write проверки resolved root,
evidence parent и всех вложенных paths, включая Windows reparse/junction attrs.
Три дополнительных mocked tests подтверждают отказ до создания клиента/любого
write. Реальный root/preflight path проверен read-only: PASS. Сетевого запуска
и записи в реальный preflight в этой подзадаче не было.

Окончательные SHA256:

```text
fetch_public_context.py       74C979E12C7AC095053120BE5B71A000650AB58DCB29F652E6C9B19FED495E98
test_fetch_public_context.py  4C26665D4BD75D37190D27F28B936BB6EBD1C973FE3310208076E6326E6D936C
```

План:5 GET либо6 с --include-premium. Жёсткий budget6, timeout8s на сокет,
max2MiB body. Нет retries, pagination, redirect-following, auth headers, proxy
environment reading, account endpoints, WebSocket, фоновой службы или Mac.

Готовая команда root и контракт выхода изложены в FETCH_PUBLIC_CONTEXT.md.
Integration test проверяет совместимость source/evidence schema через
archive_daily.build_report; Warsaw timezone function в этом тесте замокана
фиксированным UTC+2 только для структурной проверки. Настоящий runtime tzdata
и реальный current-day guard остаются ответственностью отдельного archive.

Старые и чужие archive_daily.py/README/публичные записи не менялись. Созданы
только fetch_public_context.py, test_fetch_public_context.py и два FETCH_*.md.
Raw реального рынка/public_sources.json будут созданы лишь после одобренного
одноразового запуска root. Commit/push/публикаций не было.
