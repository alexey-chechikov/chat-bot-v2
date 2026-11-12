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


def make_exchange(xc: dict, state_dir: Path):
    name = xc["name"]
    if xc.get("paper", True) or name == "sim":
        from services.sigexec.exchange.paper import PaperExchange
        return PaperExchange(xc.get("symbol", "BTCUSDT"), venue=name, state_file=state_dir / f"sigexec_paper_{name}.json")
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
    def __init__(self, cfg: dict, state_dir: Path, exchange=None, feed=None, notify=None):
        self.cfg = cfg
        self.state_dir = Path(state_dir)
        xc = cfg["exchange"]
        tag = f"{xc['name']}{'_paper' if xc.get('paper', True) else ''}"
        self.ex = exchange or make_exchange(xc, self.state_dir)
        self.feed = feed or HourFeed(self.state_dir / f"sigexec_hours_{cfg['feed'].get('symbol', 'BTCUSDT')}.csv", BinanceSpotHours(cfg["feed"].get("symbol", "BTCUSDT")))
        ecfg = dict(cfg["executor"], symbol=xc.get("symbol", "BTCUSDT"))
        self.say = notify or notifier(cfg.get("telegram", False))
        self.exe = Executor(self.ex, ecfg, self.state_dir / f"sigexec_{tag}_state.json", self.state_dir / f"sigexec_{tag}_journal.jsonl", self.say)
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
            self.ev = strategy.evaluate(*self.feed.arrays(), slots=tuple(self.exe.cfg["slots"]))
        if hasattr(self.ex, "refresh_price"):
            self.ex.refresh_price()
        desired = self.ev["desired"] if (fresh and self.ev) else None
        self.exe.step(desired, self.ev["events"] if (new and self.ev) else [])
        if hasattr(self.ex, "save"):
            self.ex.save()
        return {"new_hours": new, "fresh": fresh, "last_hour": int(self.feed.t[-1]) if len(self.feed.t) else None}

    def busy(self) -> bool:
        return any(r["status"] in ("SENDING", "UNKNOWN") or (r["kind"] == "LIMIT" and r["status"] in ("NEW", "PARTIAL"))
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
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = json.loads(Path(a.config).read_text())
    r = Runner(cfg, Path(a.state_dir))
    if a.status:
        print(json.dumps({"exchange": cfg["exchange"], "slots": r.exe.status(), "desired": {k: (v.to_dict() if v else None) for k, v in ((r.ev or {}).get("desired") or {}).items()}},
                         ensure_ascii=False, indent=1))
        return 0
    if a.close_all:
        r.exe.close_all()
        r.tick()
        return 0
    if a.once:
        print(json.dumps(r.tick(), ensure_ascii=False))
        print(json.dumps(r.exe.status(), ensure_ascii=False, indent=1))
        return 0
    r.forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
