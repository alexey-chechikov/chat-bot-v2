"""Пакет для внешней проверки (ChatGPT): ответы на разбор + описание логики + ПОЛНЫЙ код сетки,
клиента биржи, тестов, прогонщика + живые конфиги/учёт/журнал + выводы прогонов.
Ключи API не попадают: они только в .env.local, который сюда не читается.
Результат: docs/WEEX_GRID_CODE_FOR_GPT_<дата>.md"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-10-10"
OUT = ROOT / "docs" / f"WEEX_GRID_CODE_FOR_GPT_{DATE}.md"

DOCS = ["docs/WEEX_GPT_REVIEW_ANSWERS_2026-10-10.md", "docs/WEEX_GRID_LOGIC_FOR_GPT_2026-10-09.md"]
CODE = [
    ("Движок сетки (решения, учёт, имитатор биржи)", "services/weex_grid/engine.py"),
    ("Цикл, несколько сеток, команды /weex", "services/weex_grid/loop.py"),
    ("Клиент биржи WEEX (подпись, чтение, ордера)", "services/weex_api/client.py"),
    ("Тесты: базовые сценарии движка", "tests/services/weex_grid/test_weex_grid_engine.py"),
    ("Тесты: сценарии из разбора 10.10", "tests/services/weex_grid/test_weex_grid_robust.py"),
    ("Тесты: несколько сеток и команды", "tests/services/weex_grid/test_weex_grid_multi.py"),
    ("Тесты: /weex set", "tests/services/weex_grid/test_weex_grid_set.py"),
    ("Быстрый прогон для развёрток", "research/weex/fast_grid.py"),
    ("Развёртка шаг×цель с половинами окна", "research/weex/sweep_grid.py"),
    ("Сверка быстрого прогона с движком", "research/weex/validate_fast.py"),
    ("Прогон самого движка на минутках (используется сверкой)", "research/weex/refill_compare.py"),
    ("Сверка правила опорной цены с журналом GinArea", "research/weex/ginarea_refill_check.py"),
    ("Сверка прибыли сетки со сделками биржи", "research/weex/pnl_reconcile.py"),
    ("Поиск своих ордеров без записи в учёте", "research/weex/orphan_check.py"),
]
STATE = [
    ("Живой конфиг BTC", "state/weex_grid_config.json"),
    ("Конфиг ETH (выкл)", "state/weex_grid_eth_config.json"),
    ("Конфиг золота (холостой)", "state/weex_grid_xau_config.json"),
    ("Живой учёт BTC (лоты, ордера)", "state/weex_grid_state.json"),
    ("Журнал исполнений BTC с 09.10", "state/weex_grid_journal.jsonl"),
]
SECRET = re.compile(r"(WEEX_API_(KEY|SECRET|PASSPHRASE)\s*=\s*\S{6,})", re.I)


def block(path: str, lang: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    if SECRET.search(text):
        raise SystemExit(f"в {path} похоже на ключ — пакет не собран")
    return f"```{lang}\n{text.rstrip()}\n```\n"


parts = [f"# Сетка WEEX — полный пакет для проверки ({DATE})\n",
         "Внутри: ответы на разбор 10.10, описание логики, полный исходный код (движок, цикл, клиент "
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
