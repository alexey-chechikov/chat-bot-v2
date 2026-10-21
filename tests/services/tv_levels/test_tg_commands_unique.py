"""21.10: /tv не работал — старый обработчик commands=['tv_status', 'tv'] зарегистрирован раньше нового /tv, telebot
отдаёт команду первому подходящему. Каждая команда Telegram — ровно в одном обработчике."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "services" / "telegram_runtime.py"
# давние дубли, найденные этим тестом 21.10 (срабатывает первый обработчик): /bots — /bot GinArea и /ginarea;
# /levels — ручные VPVR-уровни и /levels /lvl. Какой оставить — решение оператора; новые дубли тест ловит
KNOWN = {"bots": 2, "levels": 2}


def _commands() -> list[str]:
    out = []
    for node in ast.walk(ast.parse(SRC.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "message_handler":
            for kw in node.keywords:
                if kw.arg == "commands" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    out += [e.value for e in kw.value.elts if isinstance(e, ast.Constant)]
    return out


def test_each_command_has_one_handler():
    cmds = _commands()
    assert "tv" in cmds and "weex" in cmds                      # разбор действительно видит обработчики
    dup = {c: n for c, n in Counter(cmds).items() if n > 1}
    assert dup == KNOWN, dup                                    # 'tv' — ровно один обработчик (уровни)
