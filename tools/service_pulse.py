"""Какая автоматика реально работает, а какая молча мертва.

Появился 2026-08-17. За один день нашлись ТРИ службы, которые числились
рабочими, но по факту не делали ничего для части ботов или вовсе:
  * харвестер не обслуживал BTC SHORT — бота просто не было в конфиге;
  * автотюнер не обслуживал его же, а его пороги мешка вдобавок сравнивали
    BTC с долларами, то есть не сработали бы никогда;
  * alt_guard ведёт drift по трём ботам, два из которых остановлены
    (5330789037 стоит с 05.08).
Каждая находилась отдельно и случайно.

Проверка отвечает на один вопрос по каждой действующей службе: когда она
в последний раз СДЕЛАЛА что-то, а не просто крутилась.

    .venv/bin/python tools/service_pulse.py
    .venv/bin/python tools/service_pulse.py --days 14
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"

# ВАЖНО про устройство проверки.
#
# Первая версия (17.08) считала только ДЕЙСТВИЯ и на пяти службах из
# двенадцати выдала тревогу. Разбор показал, что четыре из пяти — ложные:
#   * alt_guard пишет ключ "date", а не "ts" — моя ошибка формата;
#   * paper_trader пишет в другой файл — тоже моя;
#   * cascade_accuracy пуст, потому что каскады ДЕТЕКТЯТСЯ и отсекаются
#     гейтом ×1.3 (1258 записей в cascade_alert_suppressed) — служба
#     работает ровно как задумано;
#   * confluence не сработал, потому что не совпали два источника, а сам
#     watchlist.loop крутится непрерывно.
#
# Отсюда устройство: «тихо» и «сломано» — РАЗНЫЕ вещи. Служба, которая
# отработала тысячу циклов и ни разу не вмешалась, здорова. Сломана та,
# чей цикл не крутится. Поэтому пульс (крутится ли) берётся из лога по
# имени логгера, а действия — из журнала, и тревога поднимается только
# при отсутствии ПУЛЬСА.

APP_LOG = ROOT / "logs" / "launchd_app_runner.err"

# 31.08: пульс по логу оказался ЛОЖНЫМ источником. Лог вырос до 330 МБ и
# очень болтлив (data_loader пишет каждую секунду), а _tail читает
# последние 4 МБ — это окно примерно в час. Любая петля, которая молчит
# дольше часа, читалась как «пульс был и пропал», и инструмент объявил
# сломанными пять живых служб сразу после планового рестарта.
#
# Надёжный пульс — mtime файла, который служба трогает КАЖДЫЙ тик, а не
# когда вмешивается. Лог оставлен запасным источником для тех, у кого
# такого файла нет. Ротации логов на маке по-прежнему нет — пока её не
# будет, на лог как на пульс полагаться нельзя.
#
# (метка, журнал действий, события-действия, префикс логгера, файл пульса)
SERVICES: list[tuple[str, Path, set[str], str, Path | None]] = [
    # Только ORDER_CLOSED. Харвестер пишет на КАЖДОЕ закрытие две строки —
    # ORDER_CLOSED и HARVESTED с одним order_id и одной суммой (проверено
    # 02.09: 810 записей = 405 ордеров, задвоены все, с 18.07). Считая оба
    # события, этот инструмент показывал вдвое больше закрытий, чем было.
    # Дневной отчёт фильтрует только ORDER_CLOSED и потому верен.
    ("харвестер", STATE / "order_harvester_journal.jsonl",
     {"ORDER_CLOSED"}, "services.order_harvester",
     STATE / "order_harvester_watch.json"),
    ("автотюнер", STATE / "grid_autotune_journal.jsonl",
     {"APPLIED", "RESTORED"}, "services.grid_autotune",
     STATE / "grid_autotune_journal.jsonl"),
    ("risk_guard", STATE / "risk_guard_journal.jsonl",
     {"KILL", "HALT", "PARTIAL_CLOSE"}, "services.risk_guard",
     STATE / "risk_guard_heartbeat.json"),
    ("hedge_shadow", STATE / "hedge_shadow_journal.jsonl",
     {"WOULD_REBALANCE"}, "services.hedge_shadow",
     STATE / "hedge_shadow_state.json"),
    ("grid_border", STATE / "grid_border_journal.jsonl",
     {"FREEZE", "RELEASE", "WOULD_FREEZE", "WOULD_RELEASE"},
     "services.grid_border", STATE / "grid_border_heartbeat.json"),
    ("bot_watch", STATE / "bot_watch_journal.jsonl", {"ALERT"},
     "services.bot_watch", STATE / "bot_watch_heartbeat.json"),
    ("short_gate", STATE / "short_gate_journal.jsonl", {"FLIP"},
     "services.short_gate", STATE / "short_gate_heartbeat.json"),
    ("alt_guard", STATE / "alt_guard_bag_journal.jsonl", set(),
     "services.alt_guard", STATE / "alt_guard_state.json"),
    ("short_bots_guard", STATE / "short_bots_audit.jsonl", set(),
     "services.short_bots_guard", STATE / "short_bots_auto_pause.json"),
    ("auto_executor", STATE / "auto_executor_outcomes.jsonl", set(),
     "services.auto_executor", None),
    ("bot_brain", STATE / "bot_brain_actions.jsonl", set(),
     "services.bot_brain", STATE / "bot_brain_state.jsonl"),
    ("alt_decorr", STATE / "alt_decorr_fires.jsonl", set(),
     "services.alt_decorr", None),
    ("confluence", STATE / "confluence_fires.jsonl", set(),
     "services.watchlist", None),
    ("cascade_alert", STATE / "cascade_accuracy.jsonl", set(),
     "services.cascade_alert", None),
    ("paper_trader", STATE / "paper_grid_ETHUSDT.jsonl", set(),
     "services.paper_trader", STATE / "paper_grid_ETHUSDT_state.json"),
    ("shadow_regime", STATE / "shadow_regime.jsonl", set(), "",
     STATE / "shadow_regime.jsonl"),
]

_TS_KEYS = ("ts", "ts_utc", "time", "timestamp", "at", "created_at", "date")


def _ts_of(rec: dict) -> datetime | None:
    for k in _TS_KEYS:
        v = rec.get(k)
        if isinstance(v, str):
            try:
                t = datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                continue
            # alt_guard пишет голую дату "2026-06-11" — она naive, и
            # сравнение с aware-датой падает TypeError.
            return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        if isinstance(v, (int, float)) and v > 1_000_000_000:
            return datetime.fromtimestamp(
                v / (1000 if v > 1e11 else 1), timezone.utc)
    return None


def _tail(path: Path, limit_bytes: int = 4_000_000) -> list[str]:
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            f.seek(max(0, size - limit_bytes))
            chunk = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = chunk.splitlines()
    return lines[1:] if size > limit_bytes and lines else lines


def _last_pulse(prefixes: dict[str, str]) -> dict[str, datetime]:
    """Когда каждая служба последний раз что-то писала в лог (= цикл жив)."""
    out: dict[str, datetime] = {}
    if not prefixes or not APP_LOG.exists():
        return out
    for ln in _tail(APP_LOG, limit_bytes=8_000_000):
        if " | " not in ln:
            continue
        parts = ln.split(" | ", 3)
        if len(parts) < 3:
            continue
        logger_name = parts[2].strip()
        for label, pref in prefixes.items():
            if pref and logger_name.startswith(pref):
                try:
                    # лог пишется в МЕСТНОМ времени, не в UTC — без этого
                    # пульс уезжает на смещение и показывает «-1ч назад»
                    naive = datetime.fromisoformat(
                        parts[0].strip().replace(",", "."))
                    ts = naive.astimezone()
                except ValueError:
                    continue
                if label not in out or ts > out[label]:
                    out[label] = ts
    return out


def scan(days: int = 7) -> int:
    now = datetime.now(timezone.utc)
    horizon = now - timedelta(days=days)
    month = now - timedelta(days=30)
    problems = 0

    pulse = _last_pulse({lbl: pref for lbl, _, _, pref, _ in SERVICES})
    # Файл пульса важнее лога: он обновляется каждым тиком, а лог — только
    # когда службе есть что сказать.
    for label, _, _, _, pfile in SERVICES:
        if pfile is None or not pfile.exists():
            continue
        try:
            mt = datetime.fromtimestamp(pfile.stat().st_mtime, timezone.utc)
        except OSError:
            continue
        if label not in pulse or mt > pulse[label]:
            pulse[label] = mt

    print(f"{'служба':18s} {'пульс':>12s} {'посл. действие':>15s} "
          f"{'за ' + str(days) + 'д':>6s} {'за 30д':>7s}  вердикт")
    for label, path, events, pref, pfile in SERVICES:
        last: datetime | None = None
        n_win = n_month = 0
        if path.exists():
            for ln in _tail(path):
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rec = json.loads(ln)
                except ValueError:
                    continue
                if events and rec.get("event") not in events:
                    continue
                ts = _ts_of(rec)
                if ts is None:
                    continue
                if last is None or ts > last:
                    last = ts
                if ts >= month:
                    n_month += 1
                    if ts >= horizon:
                        n_win += 1

        def _ago(t: datetime | None) -> str:
            if t is None:
                return "—"
            h = (now - t).total_seconds() / 3600
            return f"{h:.0f}ч" if h < 48 else f"{h/24:.0f}д"

        p = pulse.get(label)
        act = _ago(last)

        # Пульс из лога НЕ доказывает смерть: тихие службы не логируют тики
        # вовсе (17.08: alt_decorr и auto_executor — 0 строк за 21 час, хотя
        # оба живы). Поэтому отсутствие пульса — повод посмотреть глазами,
        # а не вердикт. Тревогу поднимаем только там, где пульс БЫЛ и пропал.
        # Служба может КРУТИТЬСЯ и при этом НЕ ЗАЩИЩАТЬ: frozen, disabled,
        # no_api. Живой пульс это скрывает. 02.09 риск-контур одну отметку
        # отдал со статусом frozen — причину найти не удалось, файла
        # заморозки не было ни до, ни после. Поэтому статус показываем
        # явно: если он повторится, это будет видно сразу.
        hb = None
        if pfile is not None and pfile.suffix == ".json" and pfile.exists():
            try:
                d = json.loads(pfile.read_text(encoding="utf-8"))
                hb = d.get("status") if isinstance(d, dict) else None
            except (OSError, ValueError):
                hb = None

        stale = p is not None and (now - p).total_seconds() > 6 * 3600
        if hb is not None and hb not in ("ok", "notify", "acted") \
                and not str(hb).startswith("alerts:"):
            verdict, bad = f"КРУТИТСЯ, НО НЕ РАБОТАЕТ: статус «{hb}»", True
        elif p is None:
            verdict, bad = "пульса нет — смотреть глазами", False
        elif stale and pfile is not None:
            # У этой службы есть файл, который она трогает каждым тиком.
            # Он протух — значит цикл действительно встал, а не молчит.
            verdict, bad = f"ЦИКЛ ВСТАЛ: файл пульса протух {_ago(p)} назад", True
        elif stale:
            # Пульс только по логу. Лог не ротируется и читается окном, так
            # что «пропал» тут ничего не доказывает — это повод посмотреть,
            # а не вердикт (17.08: alt_decorr и auto_executor молчали 21 час
            # живыми).
            verdict, bad = f"в логе тихо {_ago(p)} — файла пульса нет", False
        elif not path.exists():
            verdict, bad = "живёт, но журнала нет", True
        elif n_win:
            verdict, bad = "работает", False
        elif n_month:
            verdict, bad = f"жив, тихо {days}д (за месяц {n_month})", False
        else:
            verdict, bad = "жив, за месяц не вмешивался", False

        problems += 1 if bad else 0
        print(f"{label:18s} {_ago(p):>12s} {act:>15s} {n_win:>6d} "
              f"{n_month:>7d}  {verdict}")

    print(f"\nсломано: {problems}   "
          f"(«тихо» — это НЕ поломка: служба крутится и не вмешивается)")
    return problems


if __name__ == "__main__":
    d = 7
    if "--days" in sys.argv:
        try:
            d = int(sys.argv[sys.argv.index("--days") + 1])
        except (IndexError, ValueError):
            pass
    raise SystemExit(1 if scan(d) else 0)
