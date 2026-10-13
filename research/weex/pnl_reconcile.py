"""Сверка прибыли сетки по сделкам биржи (только чтение).

ВСЕ сделки символа с момента запуска сетки (окна по времени, окно с 100 сделками делится пополам —
не только последние 100), разделение на сетку (clientOrderId b7g…) и ручные; по каждой стороне:
деньги по исполнениям + остаток по текущей цене против учёта бота, отдельно ДО и ПОСЛЕ комиссий.
Не сверяет фандинг и полный капитал счёта (там ручные позиции) — это отдельная задача.

    .venv/bin/python3 research/weex/pnl_reconcile.py [BTC|ETH|XAU]     (по умолчанию BTC)

ИТОГ и код выхода — только по сторонам бота (cfg.sides). Сторона из release_sides (передана оператору) в ИТОГ не
входит: учёт её забыл, расхождение ожидаемо; по ней проверяется одно — ни одной сделки b7g после «передано
оператору» (ревью скилов 12.10: раньше ИТОГ был «расхождение» всегда, настоящее по LONG терялось)."""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.weex_api.client import WeexClient  # noqa: E402
from services.weex_grid import engine as eg  # noqa: E402

ARGS = [a.upper() for a in sys.argv[1:]]
if ARGS and ARGS[0] not in eg.GRIDS:
    print(f"сетка «{sys.argv[1]}» неизвестна — есть {', '.join(eg.GRIDS)}")
    sys.exit(2)
NAME = ARGS[0] if ARGS else "BTC"
CFG_PATH, STATE_PATH, JOURNAL_PATH = eg.grid_files(NAME)
cfg = json.loads(CFG_PATH.read_text())
SYM = cfg["symbol"]
if not STATE_PATH.exists() or not JOURNAL_PATH.exists():
    print(f"{NAME}: живого учёта/журнала нет (сетка холостая) — сверять нечего")
    sys.exit(2)
journal = [json.loads(x) for x in JOURNAL_PATH.read_text(encoding="utf-8").splitlines() if x.strip()]
if not journal:
    print(f"{NAME}: живой журнал пуст — сверять нечего")
    sys.exit(2)
st = json.loads(STATE_PATH.read_text())
RELEASED = [s for s in cfg.get("release_sides") or [] if s not in cfg.get("sides", [])]
# стороны бота: из sides + не переданные, которые движок ещё ведёт (лоты/вход/strays/закрытие после смены sides)
SIDES = [s for s in ("LONG", "SHORT") if s not in RELEASED and (s in cfg.get("sides", []) or any(
    st.get(s, {}).get(k) for k in ("entry", "lots", "strays", "pending", "flatten")))]

c = WeexClient()
c.sync_time()
bid, ask = c.book(SYM)
mid = (bid + ask) / 2
first = journal[0]["ts"]
handed = {}
for r in journal:
    if r.get("kind") == "передано оператору":
        handed.setdefault(r["side"], []).append(r["ts"])
start = int((datetime.fromisoformat(first).timestamp() - 3600) * 1000)
end = int(time.time() * 1000) + 60_000


INCOMPLETE = []


def fetch(a: int, b: int) -> list[dict]:
    """Окно с 100 сделками делится пополам до 1 с; переполненное секундное окно — неполная выборка
    (перепроверка GPT 10.10: деление останавливалось на 60 с и молча теряло сделки)."""
    rows = c.user_trades(SYM, start_ms=a, end_ms=b) or []
    if len(rows) < 100:
        return rows
    if b - a <= 1000:
        INCOMPLETE.append((a, b))
        return rows
    m = (a + b) // 2
    return fetch(a, m) + fetch(m + 1, b)


trades, a = [], start
while a < end:
    b = min(a + 6 * 86_400_000, end)
    trades += fetch(a, b)
    a = b + 1
trades = list({str(t["id"]): t for t in trades}.values())
cid_of, UNREAD = {}, []
for t in trades:
    oid = str(t["orderId"])
    if oid not in cid_of:
        info = c.order_info(oid) or {}
        # ответ без совпавшего orderId (пустой/ошибка) — владелец не установлен (раунд 2 ревью: иначе сделка бота
        # молча становилась «ручной» и пропадала из сверки)
        cid_of[oid] = str(info.get("clientOrderId", "")) if str(info.get("orderId")) == oid else None
        if cid_of[oid] is None:
            UNREAD.append(oid)
grid = [t for t in trades if (cid_of[str(t["orderId"])] or "").startswith(eg.PREFIX)]
manual = [t for t in trades if cid_of[str(t["orderId"])] is not None and not cid_of[str(t["orderId"])].startswith(eg.PREFIX)]
print(f"{NAME} {SYM}: цена {mid:,.4f}; сделок с {first[:16]}: {len(trades)} (сетки {len(grid)}, ручных {len(manual)}"
      + (f", владелец не прочитан у {len(UNREAD)} ордеров" if UNREAD else "") + ")")
for t in manual:
    print("  ручная:", t["side"], t["positionSide"], t["price"], t["qty"])

ok = not UNREAD
if not SIDES and not RELEASED:
    print("сторон бота нет — сверять нечего")
    sys.exit(2)
for side in SIDES:
    d = 1 if side == "LONG" else -1
    ts = [t for t in grid if t["positionSide"] == side]
    cash = sum((1 if t["side"] == "SELL" else -1) * float(t["price"]) * float(t["qty"]) for t in ts)
    net = sum((1 if t["side"] == "BUY" else -1) * float(t["qty"]) for t in ts)
    fee = sum(float(t["commission"]) for t in ts)
    exch = cash + net * mid
    s = st[side]
    bag = sum(d * float(l["qty"]) * (mid - l["entry"]) for l in s["lots"])
    held = sum(float(l["qty"]) for l in s["lots"])
    bot = s["realized"] + bag
    diff, fdiff, qdiff = bot - exch, s["fees"] - fee, held - abs(net)
    ok &= abs(diff) < 0.01 and abs(fdiff) < 0.01 and abs(qdiff) < 1e-9
    print(f"{side}: биржа — сделок {len(ts)}, остаток {abs(net):.4f}, до комиссий ${exch:+.4f}, комиссии ${fee:.4f}, "
          f"после ${exch - fee:+.4f}")
    print(f"{side}: бот   — остаток {held:.4f}, закрыто ${s['realized']:+.4f} + мешок ${bag:+.4f} = ${bot:+.4f}, "
          f"комиссии ${s['fees']:.4f}, после ${bot - s['fees']:+.4f}")
    print(f"{side}: расхождение — деньги ${diff:+.4f}, комиссии ${fdiff:+.4f}, объём {qdiff:+.4f}")
for side in RELEASED:
    times = handed.get(side, [])
    if not times:
        n = len([t for t in grid if t["positionSide"] == side])
        print(f"{side}: в release_sides, записи «передано оператору» нет (передача без лотов записи не оставляет); "
              f"сделок бота на стороне за весь журнал {n} — {'проверить, когда' if n else 'ок'}")
        ok &= n == 0
        continue
    t0 = int(datetime.fromisoformat(times[0]).timestamp() * 1000)
    after = [t for t in grid if t["positionSide"] == side and int(t["time"]) > t0]
    print(f"{side}: передано оператору {times[0][:16]} (записей {len(times)}); сделок бота на стороне после передачи "
          f"{len(after)} → {'ПРОБЛЕМА' if after or len(times) > 1 else 'ок'}; деньги не сверяются (учёт сторону забыл)")
    ok &= not after and len(times) == 1
if INCOMPLETE:
    print(f"ВЫБОРКА НЕПОЛНА: {len(INCOMPLETE)} секундных окон со 100 сделками — сверка недостоверна")
print("ИТОГ:", f"совпадает по {'+'.join(SIDES)} (деньги и комиссии ±$0.01, объём точно)" if ok and not INCOMPLETE
      else "ЕСТЬ РАСХОЖДЕНИЕ/НЕПОЛНО")
sys.exit(0 if ok and not INCOMPLETE else 1)          # ненулевой код — для автоматической проверки
