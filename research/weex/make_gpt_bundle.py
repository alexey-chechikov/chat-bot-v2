"""Пакет для внешней проверки (ChatGPT): ответы на разборы + описание логики + ПОЛНЫЙ код сеток, тренда,
портфеля, клиента биржи, тестов, прогонщиков + живые конфиги/учёт/журналы + выводы прогонов.
Ключи API не попадают: они только в .env.local, который сюда не читается; файл с похожей строкой — отказ.
Результат: docs/WEEX_GRID_CODE_FOR_GPT_<дата>.md — в .gitignore (там живой учёт и журнал; репо публичный).
Состав обновлён 12.10 (ревью скилов: был на 10.10 — без тренда, портфеля, ETH, регрессий по режиму).

    .venv/bin/python3 research/weex/make_gpt_bundle.py [YYYY-MM-DD]     (по умолчанию — сегодня; существующий не перезаписывает)"""
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATE = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
OUT = ROOT / "docs" / f"WEEX_GRID_CODE_FOR_GPT_{DATE}.md"
if OUT.exists():
    sys.exit(f"{OUT.name} уже есть — не перезаписываю (другая дата или удалить вручную)")

# последние ответы на разборы (по дате в имени) + описание логики
ANSWERS = sorted((ROOT / "docs").glob("WEEX_*ANSWERS_*.md"), key=lambda p: (p.stem[-10:], p.name))[-3:]
DOCS = [str(p.relative_to(ROOT)) for p in ANSWERS] + ["docs/WEEX_GRID_LOGIC_FOR_GPT_2026-10-09.md"]
CODE = [
    ("Движок сетки (решения, учёт, режим SMA, передача стороны, имитатор биржи)", "services/weex_grid/engine.py"),
    ("Цикл, несколько сеток, команды /weex", "services/weex_grid/loop.py"),
    ("Общий потолок счёта (портфель)", "services/weex_grid/portfolio.py"),
    ("Трендовый бот (холостой)", "services/weex_trend/engine.py"),
    ("Цикл трендового бота", "services/weex_trend/loop.py"),
    ("Клиент биржи WEEX (подпись, чтение, ордера)", "services/weex_api/client.py"),
    ("Тесты: базовые сценарии движка", "tests/services/weex_grid/test_weex_grid_engine.py"),
    ("Тесты: сценарии из разбора 10.10", "tests/services/weex_grid/test_weex_grid_robust.py"),
    ("Тесты: несколько сеток и команды", "tests/services/weex_grid/test_weex_grid_multi.py"),
    ("Тесты: /weex set", "tests/services/weex_grid/test_weex_grid_set.py"),
    ("Тесты: второй разбор", "tests/services/weex_grid/test_weex_grid_review2.py"),
    ("Тесты: третий разбор", "tests/services/weex_grid/test_weex_grid_review3.py"),
    ("Тесты: четвёртый разбор", "tests/services/weex_grid/test_weex_grid_review4.py"),
    ("Тесты: пятый разбор", "tests/services/weex_grid/test_weex_review5.py"),
    ("Тесты: режим SMA100", "tests/services/weex_grid/test_weex_regime.py"),
    ("Тесты: разбор живого режима (L1–L8)", "tests/services/weex_grid/test_weex_regime_gpt.py"),
    ("Тесты: передача стороны и ручной шорт оператора", "tests/services/weex_grid/test_weex_release.py"),
    ("Тесты: общий потолок", "tests/services/weex_grid/test_weex_portfolio.py"),
    ("Тесты: трендовый бот", "tests/services/weex_trend/test_weex_trend.py"),
    ("Быстрый прогон для развёрток", "research/weex/fast_grid.py"),
    ("Сетка по режиму SMA100 (бэктест, контроль по отрезкам)", "research/weex/regime_grid.py"),
    ("Размер живых сеток по режиму", "research/weex/size_check.py"),
    ("Сверка быстрого прогона с движком", "research/weex/validate_fast.py"),
    ("Прогон самого движка на минутках (используется сверкой)", "research/weex/refill_compare.py"),
    ("Сверка прибыли сетки со сделками биржи", "research/weex/pnl_reconcile.py"),
    ("Общее проверочных скриптов: чтение сделок, владелец ордера, реестр", "research/weex/weex_monitor_common.py"),
    ("Тесты проверочных скриптов: обвязка (поддельная биржа)", "tests/research_weex/harness.py"),
    ("Тесты: account_now", "tests/research_weex/test_rw_account_now.py"),
    ("Тесты: orphan_check", "tests/research_weex/test_rw_orphan_check.py"),
    ("Тесты: pnl_reconcile", "tests/research_weex/test_rw_pnl_reconcile.py"),
    ("Тесты: errors_today", "tests/research_weex/test_rw_errors_today.py"),
    ("Ордера бота против учёта в обе стороны", "research/weex/orphan_check.py"),
    ("Счёт, жив ли цикл, сохранность переданной стороны", "research/weex/account_now.py"),
    ("Перекачка обрезанных минут frozen", "research/weex/repair_frozen_1m.py"),
    ("Движок GinArea по отрезкам режима", "tools/ginarea_regime_check.py"),
]
STATE = [
    ("Живой конфиг BTC", "state/weex_grid_config.json"),
    ("Живой конфиг ETH", "state/weex_grid_eth_config.json"),
    ("Конфиг золота (холостой)", "state/weex_grid_xau_config.json"),
    ("Общий потолок", "state/weex_portfolio_config.json"),
    ("Конфиг тренда (холостой)", "state/weex_trend_config.json"),
    ("Живой учёт BTC (лоты, ордера)", "state/weex_grid_state.json"),
    ("Живой учёт ETH", "state/weex_grid_eth_state.json"),
    ("Журнал исполнений BTC с 09.10", "state/weex_grid_journal.jsonl"),
    ("Журнал исполнений ETH с 11.10", "state/weex_grid_eth_journal.jsonl"),
]
SECRET = re.compile(r"(WEEX_API_(KEY|SECRET|PASSPHRASE)\s*=\s*\S{6,})", re.I)


def block(path: str, lang: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    if SECRET.search(text):
        raise SystemExit(f"в {path} похоже на ключ — пакет не собран")
    return f"```{lang}\n{text.rstrip()}\n```\n"


parts = [f"# Сетка WEEX — полный пакет для проверки ({DATE})\n",
         "Внутри: последние ответы на разборы, описание логики, полный исходный код (сетки, тренд, портфель, клиент "
         "биржи, тесты, прогонщики), живые конфиги, учёт и журнал исполнений, итоги пересчёта. Ключей API "
         "нет — они только в .env.local на машине оператора.\n",
         "## Оглавление\n"]
for i, d in enumerate(DOCS, 1):
    parts.append(f"{i}. {Path(d).name}")
parts.append(f"{len(DOCS) + 1}. Исходный код ({len(CODE)} файлов)")
parts.append(f"{len(DOCS) + 2}. Живые конфиги, учёт и журнал")
parts.append(f"{len(DOCS) + 3}. Выводы прогонов\n")
for d in DOCS:
    parts.append("\n---\n")
    parts.append((ROOT / d).read_text(encoding="utf-8"))
parts.append("\n---\n\n# Исходный код\n")
for title, path in CODE:
    n = len((ROOT / path).read_text(encoding="utf-8").splitlines())
    parts.append(f"\n## {title} — `{path}` ({n} строк)\n")
    parts.append(block(path, "python"))
parts.append("\n---\n\n# Живые конфиги, учёт и журнал (на момент сборки)\n")
for title, path in STATE:
    parts.append(f"\n## {title} — `{path}`\n")
    parts.append(block(path, "json"))
runs = sorted((ROOT / "research" / "weex").glob("run_out_*.txt"))
if runs:
    parts.append("\n---\n\n# Выводы прогонов (как напечатано скриптами)\n")
    for p in runs:
        parts.append(f"\n## {p.name}\n```\n{p.read_text(encoding='utf-8').rstrip()}\n```\n")
OUT.write_text("\n".join(parts), encoding="utf-8")
print(OUT, f"{OUT.stat().st_size / 1024:.0f} КБ")
