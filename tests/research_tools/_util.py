"""Загрузка исследовательских скриптов (они не пакеты) по пути файла.

load()      — обычный импорт модуля под уникальным именем.
load_defs() — только import/def/class/присваивания, без остального кода верхнего уровня: старый
              research/weex/fetch_1m.py качал Binance прямо при импорте — так его можно проверить без сети.
"""
from __future__ import annotations

import ast
import importlib.util
import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_seq = itertools.count()


def load(relpath: str):
    path = ROOT / relpath
    name = f"_rt_{path.stem}_{next(_seq)}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_defs(relpath: str, **inject) -> dict:
    path = ROOT / relpath
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    kinds = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)
    body = [n for n in tree.body if isinstance(n, kinds)]
    ns: dict = {"__name__": f"_rt_defs_{path.stem}_{next(_seq)}", "__file__": str(path)}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), ns)   # noqa: S102
    ns.update(inject)
    return ns
