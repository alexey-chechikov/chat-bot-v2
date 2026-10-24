"""21.10: /tv не работал — старый обработчик commands=['tv_status', 'tv'] зарегистрирован раньше нового /tv, telebot
отдаёт команду первому подходящему. Каждая команда Telegram — ровно в одном обработчике.
21.10 (вечер): давние дубли разведены — /bots → карточки живых сеток WEEX (раньше первым ловил /bot GinArea-тиров),
/levels → карта плотности (раньше первыми ловили ручные VPVR-уровни, теперь они /vpvr)."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "services" / "telegram_runtime.py"


def _handlers() -> list[tuple[str, list[str]]]:
    """(имя функции-обработчика, её команды) в порядке файла."""
    out = []
    for node in ast.walk(ast.parse(SRC.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and getattr(dec.func, "attr", "") == "message_handler":
                for kw in dec.keywords:
                    if kw.arg == "commands" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        out.append((node.name, [e.value for e in kw.value.elts if isinstance(e, ast.Constant)]))
    return out


def _commands() -> list[str]:
    return [c for _, cmds in _handlers() for c in cmds]


def test_each_command_has_one_handler():
    cmds = _commands()
    assert "tv" in cmds and "weex" in cmds                      # разбор действительно видит обработчики
    dup = {c: n for c, n in Counter(cmds).items() if n > 1}
    assert dup == {}, dup


def test_bots_and_levels_routed_to_live_cards():
    owner = {c: name for name, cmds in _handlers() for c in cmds}
    assert owner["bots"] == "handle_bots"                       # карточки сеток WEEX, не GinArea
    assert owner["levels"] == "handle_levels" and owner["lvl"] == "handle_levels"   # карта плотности
    assert owner["vpvr"] == "handle_vpvr_levels" and owner["bot"] == "handle_bot"
    src = SRC.read_text(encoding="utf-8")
    body = src[src.index("def handle_bots("):src.index("# ── /panel")]
    assert "command('')" in body                                # только чтение: аргументы не передаются в /weex
