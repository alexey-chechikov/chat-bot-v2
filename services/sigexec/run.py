"""Запуск исполнителя: данные → сигналы → биржа, по кругу.

  python -m services.sigexec.run --config state/sigexec_config.json            — цикл
  python -m services.sigexec.run --config … --once                              — один проход
  python -m services.sigexec.run --config … --status                            — положение и заявки
  python -m services.sigexec.run --config … --close-all                         — закрыть эпизоды (своё, не чужое)

Конфиг: {"exchange": {"name": "sim|weex|bybit|okx", "symbol", "paper": true, "testnet": false, "hedge": true},
         "feed": {"symbol": "BTCUSDT"}, "executor": {...executor.DEFAULT_CFG...}, "telegram": false, "poll_s": 5}
paper=true — имитатор с ценой выбранной биржи (публичный стакан, без ключей): заявки не уходят на биржу.
Каждый проход: дозагрузка часов (новый час — пересчёт сигналов), шаг исполнителя. Частота — poll_s, пока есть живые
лимитки или работа; иначе 30 с и обязательный проход в первые секунды нового часа."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.sigexec import strategy  # noqa: E402
from services.sigexec.executor import Executor, Halt  # noqa: E402
from services.sigexec.feed import BinanceSpotHours, FeedError, HourFeed  # noqa: E402

log = logging.getLogger("sigexec")


VENUES = ("sim", "weex", "bybit", "okx")


def env_of(xc: dict) -> str:
    """paper — без биржи (цены площадки); demo — демо-счёт / тестнет; live — боевой. Сочетания проверяются до клиента."""
    name, paper, test = xc.get("name"), bool(xc.get("paper", True)), bool(xc.get("testnet", False))
    if name not in VENUES:
        raise Halt(f"биржа {name!r} не поддерживается")
    if paper and test:
        raise Halt("paper и testnet вместе: paper — без биржи, testnet — демо-счёт биржи; выбрать одно")
    if name == "weex" and test:
        raise Halt("WEEX: демо-счёта в адаптере нет — testnet:true не поддерживается (иначе ушло бы на боевой)")
    if name == "sim" and not paper:
        raise Halt("sim бывает только paper")
    return "paper" if paper else ("demo" if test else "live")


def state_tag(cfg: dict) -> str:
    """Учёт привязан к бирже, среде, счёту и символу: демо и боевой никогда не делят один файл (разбор aadc2a4, P1-6)."""
    xc = cfg["exchange"]
    acc = str(xc.get("account", "main"))
    if not acc.replace("-", "").isalnum():
        raise Halt(f"account {acc!r}: буквы, цифры, дефис")
    hedge = "-hedge" if cfg.get("executor", {}).get("sizing") == "hedge" else ""   # страховка и лонги системы — разные учёты
    return f"{xc['name']}-{env_of(xc)}-{acc}-{xc.get('symbol', 'BTCUSDT')}{hedge}"


def check_executor_cfg(cfg: dict) -> dict:
    """WEEX: стороны BTCUSDT общие с сетками и ручными сделками, SHORT — оператора (release_sides): только LONG и общий счёт.
    Страховка сеток (executor.sizing="hedge", 14.11) — наоборот, только SHORT, и только если оператор сам разрешил делить
    с ним сторону SHORT: exchange.share_short_with_operator=true (его решение, по умолчанию нет)."""
    xc, ecfg = cfg["exchange"], dict(cfg["executor"], symbol=cfg["exchange"].get("symbol", "BTCUSDT"))
    if xc["name"] == "weex" and env_of(xc) == "live":
        sides = set(ecfg.get("allowed_sides", ["LONG", "SHORT"]))
        if ecfg.get("sizing") == "hedge":
            if sides != {"SHORT"}:
                raise Halt("WEEX живой, страховка: allowed_sides должен быть [\"SHORT\"]")
            if xc.get("share_short_with_operator") is not True:
                raise Halt("WEEX живой, страховка: сторона BTC SHORT — оператора; нужен exchange.share_short_with_operator=true "
                           "(его решение)")
        elif sides != {"LONG"}:
            raise Halt("WEEX живой: allowed_sides должен быть [\"LONG\"] — BTC SHORT за оператором")
        ecfg["shared_account"] = True
    return ecfg


def make_exchange(xc: dict, state_dir: Path):
    name = xc["name"]
    env = env_of(xc)
    if env == "paper":
        from services.sigexec.exchange.paper import PaperExchange
        acc = xc.get("account", "main")
        return PaperExchange(xc.get("symbol", "BTCUSDT"), venue=name, state_file=state_dir / f"sigexec_paperbook_{name}-{acc}-{xc.get('symbol', 'BTCUSDT')}.json")
    if name == "bybit":
        from services.sigexec.exchange.bybit import BybitExchange
        return BybitExchange.from_env(testnet=xc.get("testnet", False), hedge=xc.get("hedge", True))
    if name == "okx":
        from services.sigexec.exchange.okx import OkxExchange
        return OkxExchange.from_env(demo=xc.get("testnet", False), hedge=xc.get("hedge", True))
    if name == "weex":
        from services.sigexec.exchange.weex import WeexExchange
        return WeexExchange.from_env()
    raise Halt(f"биржа {name!r} не поддерживается")


def notifier(enabled: bool):
    if not enabled:
        return lambda text: print(text, flush=True)
    from services.telegram_alert_client import TelegramAlertClient
    cl = TelegramAlertClient.instance()
    return lambda text: cl.send("🤖 sigexec\n" + text)


class Runner:
    def __init__(self, cfg: dict, state_dir: Path, exchange=None, feed=None, notify=None, exposure=None):
        self.cfg = cfg
        self.state_dir = Path(state_dir)
        xc = cfg["exchange"]
        self.tag = state_tag(cfg)                     # флаги проверены ДО создания клиента биржи
        ecfg = check_executor_cfg(cfg)
        self.boost = float(cfg.get("strategy", {}).get("boost_432", 1.0))
        if not 1.0 <= self.boost <= 3.0:
            raise Halt(f"strategy.boost_432 {self.boost}: допустимо 1.0–3.0")
        self.ex = exchange or make_exchange(xc, self.state_dir)
        self.feed = feed or HourFeed(self.state_dir / f"sigexec_hours_{cfg['feed'].get('symbol', 'BTCUSDT')}.csv", BinanceSpotHours(cfg["feed"].get("symbol", "BTCUSDT")))
        self.say = notify or notifier(cfg.get("telegram", False))
        if exposure is None and ecfg.get("sizing") == "hedge":
            from services.sigexec import hedge
            try:
                exposure = hedge.make(cfg.get("hedge"))
            except ValueError as e:
                raise Halt(f"страховка: {e}") from None
        self.exe = Executor(self.ex, ecfg, self.state_dir / f"sigexec_{self.tag}_state.json", self.state_dir / f"sigexec_{self.tag}_journal.jsonl", self.say,
                            exposure=exposure)
        self.ev: dict | None = None
        self.feed_err_t = 0.0

    def tick(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        new = 0
        try:
            new = self.feed.update(now)
        except FeedError as e:
            if now - self.feed_err_t > 3600:
                self.say(f"⚠️ данные: {e}")
                self.feed_err_t = now
        fresh = self.feed.fresh(now)
        if (new or self.ev is None) and len(self.feed.t):
            self.ev = strategy.evaluate(*self.feed.arrays(), slots=tuple(self.exe.cfg["slots"]), boost_432=self.boost)
        if hasattr(self.ex, "refresh_price"):
            self.ex.refresh_price()
        desired = self.ev["desired"] if (fresh and self.ev) else None
        self.exe.step(desired, self.ev["events"] if (new and self.ev) else [])
        if hasattr(self.ex, "save"):
            self.ex.save()
        return {"new_hours": new, "fresh": fresh, "last_hour": int(self.feed.t[-1]) if len(self.feed.t) else None}

    def close_all(self, timeout_s: float = 600.0, poll_s: float = 3.0) -> bool:
        """Входы запрещены, эпизоды — в выход рыночным; проходы, пока нет эпизодов и незавершённых заявок. → подтверждено ли."""
        self.exe.close_all()
        t_end = time.time() + timeout_s
        while time.time() < t_end:
            self.tick()
            if self.exe.flat():
                self.say("✅ закрыть всё: эпизодов нет, своих незавершённых заявок нет; входы запрещены до --reopen")
                return True
            time.sleep(poll_s)
        self.say(f"⛔ закрыть всё НЕ подтверждено за {timeout_s:.0f} с: {json.dumps(self.exe.status(), ensure_ascii=False)[:300]}")
        return False

    def busy(self) -> bool:
        return any(r["status"] in ("SENDING", "UNKNOWN", "UNRESOLVED") or (r["kind"] == "LIMIT" and r["status"] in ("NEW", "PARTIAL"))
                   for r in self.exe.st["orders"].values()) or any(S["ep"] and S["ep"]["phase"] in ("entering", "exiting") for S in self.exe.st["slots"].values())

    def forever(self) -> None:
        poll = float(self.cfg.get("poll_s", 5))
        while True:
            t0 = time.time()
            try:
                self.tick(t0)
            except Halt as e:
                self.say(f"⛔ исполнитель остановлен: {e}")
                raise
            except Exception as e:  # noqa: BLE001 — цикл живёт; ошибка в журнал и в сообщение
                log.exception("sigexec.tick_failed")
                self.say(f"⚠️ проход упал: {e!r}"[:300])
            now = time.time()
            nxt_hour = (int(now) // 3600 + 1) * 3600 + 3
            sleep = poll if self.busy() else min(30.0, max(1.0, nxt_hour - now))
            time.sleep(max(0.5, sleep - (now - t0)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--state-dir", default=str(ROOT / "state"))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--close-all", action="store_true")
    ap.add_argument("--reopen", action="store_true")
    ap.add_argument("--resolve", nargs="+", metavar=("CID", "absent|filled"), help="решение по UNRESOLVED: CID absent | CID filled QTY PX")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = json.loads(Path(a.config).read_text())
    if a.status:                                     # только чтение файла учёта — работает рядом с живым процессом
        p = Path(a.state_dir) / f"sigexec_{state_tag(cfg)}_state.json"
        st = json.loads(p.read_text()) if p.exists() else {}
        print(json.dumps({"exchange": cfg["exchange"], "state": str(p), "closing": st.get("closing"),
                          "episodes": {s: (S["ep"] and {k: S["ep"].get(k) for k in ("phase", "side", "tag", "sig_px", "goal_main", "goal_add", "boost")})
                                       for s, S in st.get("slots", {}).items()},
                          "unresolved": [c for c, r in st.get("orders", {}).items() if r["status"] == "UNRESOLVED"]}, ensure_ascii=False, indent=1))
        return 0
    r = Runner(cfg, Path(a.state_dir))
    if a.resolve:
        cid, verdict, *rest = a.resolve
        r.exe.resolve(cid, verdict, *(float(x) for x in rest))
        return 0
    if a.reopen:
        r.exe.reopen()
        return 0
    if a.close_all:
        return 0 if r.close_all() else 2
    if a.once:
        print(json.dumps(r.tick(), ensure_ascii=False))
        print(json.dumps(r.exe.status(), ensure_ascii=False, indent=1))
        return 0
    r.forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
