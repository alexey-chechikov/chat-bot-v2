"""Цикл трендового бота: вызывается из цикла сеток WEEX (services/weex_grid/loop.py) каждые 10 с,
сам решает раз в poll_sec. Монеты — cfg["symbols"] (10.10: ETH, затем XRP по «делай все»), у каждой свой
учёт и журнал; per_symbol — свои шаги объёма/цены. Холостой режим — отдельный учёт *_dry и имитатор
(сбрасываются при перезапуске). Команды — через /weex тренд …"""
from __future__ import annotations

import json
import logging
import time

from services.weex_trend import engine as te

logger = logging.getLogger(__name__)


def files(dry: bool, symbol: str = "ETHUSDT"):
    """ETH — исходные файлы (weex_trend_state.json …), остальные монеты — weex_trend_<монета>_*."""
    st, jr = te.STATE, te.JOURNAL
    if symbol != "ETHUSDT":
        tag = symbol.replace("USDT", "").lower()
        st = st.with_name(f"weex_trend_{tag}_state.json")
        jr = jr.with_name(f"weex_trend_{tag}_journal.jsonl")
    if dry:
        st, jr = st.with_name(st.stem + "_dry.json"), jr.with_name(jr.stem + "_dry.jsonl")
    return st, jr


def symbol_cfg(cfg: dict, symbol: str) -> dict:
    return {**cfg, "symbol": symbol, **(cfg.get("per_symbol") or {}).get(symbol, {})}


def symbols(cfg: dict) -> list[str]:
    return list(cfg.get("symbols") or [cfg.get("symbol", "ETHUSDT")])


class TrendRunner:
    def __init__(self, client_fn, send_fn=None):
        self.client_fn = client_fn
        self.send = send_fn
        self.dry_ex: dict[str, te.DryTrendExchange] = {}
        self.last_halt = 0.0

    def tick(self, portfolio_free: float | None = None) -> None:
        try:
            cfg = te.load_config()
        except te.GridHalt as exc:
            self._halt(exc)
            return
        for sym in symbols(cfg):
            try:
                c = symbol_cfg(cfg, sym)
                if not c["dry_run"] and portfolio_free is not None:
                    c["portfolio_free_usd"] = portfolio_free    # общий потолок счёта — только живому режиму
                self._tick_symbol(c)
            except te.GridHalt as exc:
                self._halt(exc)

    def _halt(self, exc: Exception) -> None:
        logger.error("weex_trend.halt err=%s", exc)
        if self.send and time.time() - self.last_halt > 1800:
            self.last_halt = time.time()
            self.send(f"🛑 Трендовый бот WEEX остановлен: {str(exc)[:250]}. Ордера на бирже не трогаю.")

    def _tick_symbol(self, cfg: dict) -> None:
        sym = cfg["symbol"]
        dry = bool(cfg["dry_run"])
        st_path, jr_path = files(dry, sym)
        if dry and not cfg["enabled"] and not (st_path.exists() and json.loads(st_path.read_text()).get("episode")):
            self._live_leftover(cfg)
            return
        real = self.client_fn()
        if dry:
            if sym not in self.dry_ex:
                st_path.unlink(missing_ok=True)                 # учебная позиция жила в памяти имитатора
                self.dry_ex[sym] = te.DryTrendExchange(lambda: real.book(sym), symbol=sym)
            client = self.dry_ex[sym]
        else:
            client = real
        te.Trend(client, cfg, state_path=st_path, journal_path=jr_path, send_fn=self.send).tick()
        if dry:
            self._live_leftover(cfg)

    def _live_leftover(self, cfg: dict) -> None:
        """Переключили live→dry с открытой живой позицией: живая ведётся до выхода (enabled=false — без
        новых входов), иначе позиция осталась бы без основного выхода."""
        st_path, jr_path = files(False, cfg["symbol"])
        if not st_path.exists():
            return
        try:
            st = json.loads(st_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise te.StateCorrupt(f"живой учёт {st_path.name} не читается: {exc}") from exc
        if not (st.get("episode") or st.get("pending")):
            return
        te.Trend(self.client_fn(), {**cfg, "dry_run": False, "enabled": False}, state_path=st_path,
                 journal_path=jr_path, send_fn=self.send).tick()


def card() -> str:
    from services.weex_api.client import WeexClient
    cfg = te.load_config()
    real = WeexClient()
    real.sync_time()
    out = []
    for sym in symbols(cfg):
        c = symbol_cfg(cfg, sym)
        st_path, _ = files(bool(c["dry_run"]), sym)
        client = te.DryTrendExchange(lambda s=sym: real.book(s), symbol=sym) if c["dry_run"] else real
        out.append(te.Trend(client, c, state_path=st_path,
                            journal_path=te.JOURNAL.with_name("_unused.jsonl")).card())
    return "\n\n".join(out)


SET_KEYS = {"риск": "risk_usd", "risk": "risk_usd", "потолок": "max_notional_usd", "cap": "max_notional_usd",
            "буфер": "emergency_buffer_pct", "buffer": "emergency_buffer_pct"}
LIMITS = {"risk_usd": (1.0, 500.0), "max_notional_usd": (10.0, 20_000.0), "emergency_buffer_pct": (0.3, 10.0)}
KNOWN = {"ETH": "ETHUSDT", "ETHUSDT": "ETHUSDT", "XRP": "XRPUSDT", "XRPUSDT": "XRPUSDT"}


def command(arg: str) -> str:
    """/weex тренд [start|stop|live|dry|set риск 33 потолок 1500 буфер 1.5|монеты ETH XRP]; без аргумента —
    карточки. Режим и риск общие для всех монет."""
    raw = (arg or "").strip()
    a = raw.lower()
    try:
        cfg = te.load_config()
        if a.startswith("монеты") or a.startswith("coins"):
            want = [KNOWN.get(t.upper()) for t in raw.split()[1:]]
            if not want or None in want:
                return "Формат: /weex тренд монеты ETH XRP (доступны ETH, XRP)."
            cfg["symbols"] = list(dict.fromkeys(want))
            te.save_config(cfg)
            return f"✅ Трендовый бот: монеты {', '.join(s.replace('USDT', '') for s in cfg['symbols'])}."
        if a.startswith("set"):
            toks = raw.replace("=", " ").replace(",", ".").split()[1:]
            if len(toks) < 2 or len(toks) % 2:
                return "Формат: /weex тренд set риск 33 потолок 1500 буфер 1.5"
            for k, v in zip(toks[::2], toks[1::2]):
                key = SET_KEYS.get(k.lower())
                if not key:
                    return f"Не знаю «{k}». Есть: риск, потолок, буфер."
                val = float(v.replace("$", ""))
                lo, hi = LIMITS[key]
                if not lo <= val <= hi:
                    return f"{key} = {val:g} вне [{lo:g}; {hi:g}] — не меняю."
                cfg[key] = val
            te.save_config(cfg)
            return (f"✅ Тренд: риск ${cfg['risk_usd']:.0f} на сделку, потолок ${cfg['max_notional_usd']:,.0f}, "
                    f"аварийный стоп на {cfg['emergency_buffer_pct']}% за Chandelier (все монеты).")
        names = ", ".join(s.replace("USDT", "") for s in symbols(cfg))
        if a in ("start", "старт"):
            cfg["enabled"] = True
            te.save_config(cfg)
            return f"▶️ Трендовый бот ({names}) включён ({'холостой' if cfg['dry_run'] else 'ЖИВОЙ'})."
        if a in ("stop", "стоп"):
            cfg["enabled"] = False
            te.save_config(cfg)
            return "⏸ Трендовый бот: новых входов нет; открытые позиции ведутся до выхода по своим правилам."
        if a in ("live", "живая", "живой"):
            cfg["dry_run"] = False
            te.save_config(cfg)
            return (f"🔴 Трендовый бот ({names}) в ЖИВОМ режиме" +
                    ("" if cfg["enabled"] else " (включить — /weex тренд start)") + ".")
        if a in ("dry", "холостой"):
            cfg["dry_run"] = True
            te.save_config(cfg)
            return "🧪 Трендовый бот в холостом режиме."
        return card()
    except te.GridHalt as exc:
        return f"🛑 Трендовый бот не тронут: {exc}."
