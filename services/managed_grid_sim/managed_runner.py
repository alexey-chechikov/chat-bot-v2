from __future__ import annotations

import hashlib
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

from .intervention_actions import InterventionExecutor
from .intervention_rules import InterventionRule
from .models import (
    BotState,
    InterventionEvent,
    InterventionType,
    ManagedRunResult,
    MarketSnapshot,
    RegimeLabel,
    TrendType,
)
from .regime_classifier import RegimeClassifier


def _ensure_engine_path() -> None:
    # Prefer the repo-local copy of backtest_lab/engine_v2 (portable across
    # machines — Win + Mac); fall back to the original Codex checkout on the
    # Windows dev box. First candidate that actually contains the engine wins.
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        repo_root,
        Path(r"C:\Users\Kemper\Documents\Codex\2026-04-20-new-chat\src"),
    ]
    for candidate in candidates:
        if (candidate / "backtest_lab" / "engine_v2" / "bot.py").exists():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            return


def load_engine_bindings() -> tuple[Any, Any, Any, Any, Any]:
    _ensure_engine_path()
    import importlib

    bot_mod = importlib.import_module("backtest_lab.engine_v2.bot")
    contracts_mod = importlib.import_module("backtest_lab.engine_v2.contracts")
    BotConfig = bot_mod.BotConfig
    GinareaBot = bot_mod.GinareaBot
    OHLCBar = bot_mod.OHLCBar
    Side = contracts_mod.Side
    LINEAR = contracts_mod.LINEAR
    INVERSE = contracts_mod.INVERSE

    return BotConfig, GinareaBot, OHLCBar, Side, {"linear": LINEAR, "inverse": INVERSE}


@dataclass(frozen=True, slots=True)
class ManagedRunConfig:
    bot_configs: list[dict[str, Any]]
    bars: list[Any]
    intervention_rules: list[InterventionRule]
    regime_classifier: RegimeClassifier
    run_id: str
    strict_mode: bool = False


class ManagedGridSimRunner:
    def __init__(self, engine_loader: Any | None = None) -> None:
        self.engine_loader = engine_loader or load_engine_bindings

    def run(self, config: ManagedRunConfig) -> ManagedRunResult:
        start = monotonic()
        bots = self._init_bots(config.bot_configs)
        executor = InterventionExecutor(bots, bot_factory=self._build_bot_from_flat_config)
        intervention_log: list[InterventionEvent] = []
        state_history: dict[str, list[BotState]] = {bot_id: [] for bot_id in bots}
        equity_curve: list[float] = []
        last_trend_type = TrendType.UNCERTAIN

        for idx, bar in enumerate(config.bars):
            for bot in list(bots.values()):
                bot.step(bar, idx)

            regime, trend_type = config.regime_classifier.classify(config.bars[: idx + 1])
            last_trend_type = trend_type
            snapshot = self._build_snapshot(idx, bar, config.regime_classifier, config.bars[: idx + 1], regime, trend_type)

            for bot_id, bot in list(bots.items()):
                bot_state = self._build_bot_state(bot_id, bot, snapshot)
                recent = state_history.setdefault(bot_id, [])
                recent.append(bot_state)
                if len(recent) > 120:
                    recent.pop(0)

                for rule in config.intervention_rules:
                    try:
                        decision = rule.evaluate(snapshot, bot_state, recent)
                        if decision is None:
                            continue
                        event = executor.apply(bot_id, decision, bar, snapshot=snapshot)
                        intervention_log.append(event)
                    except Exception:
                        if config.strict_mode:
                            raise

            equity_curve.append(self._portfolio_equity_usd(bots, float(bar.close)))

        duration = monotonic() - start
        final_price = float(config.bars[-1].close) if config.bars else 0.0
        realized = sum(float(bot.realized_pnl) for bot in bots.values())
        unrealized = sum(float(bot.unrealized_pnl(final_price)) for bot in bots.values())
        total_volume = sum(
            float(getattr(bot, "in_qty_notional", 0.0) + getattr(bot, "out_qty_notional", 0.0))
            for bot in bots.values()
        )
        total_trades = sum(len(getattr(bot, "closed_orders", [])) for bot in bots.values())
        max_dd_usd, max_dd_pct = self._max_drawdown(equity_curve)
        sharpe = self._sharpe(equity_curve)
        counts: dict[InterventionType, int] = {}
        for event in intervention_log:
            counts[event.intervention_type] = counts.get(event.intervention_type, 0) + 1

        return ManagedRunResult(
            run_id=config.run_id,
            config_hash=self._hash_bot_configs(config.bot_configs),
            bot_configs=config.bot_configs,
            trend_type=last_trend_type,
            final_realized_pnl_usd=realized,
            final_unrealized_pnl_usd=unrealized,
            total_volume_usd=total_volume,
            max_drawdown_pct=max_dd_pct,
            max_drawdown_usd=max_dd_usd,
            sharpe_ratio=sharpe,
            total_trades=total_trades,
            total_interventions=len(intervention_log),
            interventions_by_type=counts,
            intervention_log=intervention_log,
            bar_count=len(config.bars),
            sim_duration_seconds=duration,
        )

    def _init_bots(self, bot_configs: list[dict[str, Any]]) -> dict[str, Any]:
        return {cfg["bot_id"]: self._build_bot_from_flat_config(cfg) for cfg in bot_configs}

    def _build_bot_from_flat_config(self, cfg: dict[str, Any]) -> Any:
        BotConfig, GinareaBot, _, Side, contracts = self.engine_loader()
        side_name = str(cfg["side"]).lower()
        side = Side.SHORT if side_name == "short" else Side.LONG
        contract = contracts[str(cfg["contract_type"]).lower()]
        bot_cfg = BotConfig(
            bot_id=str(cfg["bot_id"]),
            alias=str(cfg.get("alias", cfg["bot_id"])),
            side=side,
            contract=contract,
            order_size=float(cfg["order_size"]),
            order_count=int(cfg["order_count"]),
            grid_step_pct=float(cfg["grid_step_pct"]),
            target_profit_pct=float(cfg["target_profit_pct"]),
            min_stop_pct=float(cfg["min_stop_pct"]),
            max_stop_pct=float(cfg["max_stop_pct"]),
            instop_pct=float(cfg["instop_pct"]),
            boundaries_lower=float(cfg.get("boundaries_lower", 0.0)),
            boundaries_upper=float(cfg.get("boundaries_upper", 0.0)),
            indicator_period=int(cfg.get("indicator_period", 30)),
            indicator_threshold_pct=float(cfg.get("indicator_threshold_pct", 0.3)),
            dsblin=bool(cfg.get("dsblin", False)),
            leverage=int(cfg.get("leverage", 100)),
            cap_pos_btc=cfg.get("cap_pos_btc"),
        )
        bot = GinareaBot(bot_cfg)
        bot.is_active = not bool(cfg.get("dsblin", False))
        return bot

    def _build_snapshot(
        self,
        idx: int,
        bar: Any,
        classifier: RegimeClassifier,
        bars_window: list[Any],
        regime: RegimeLabel,
        trend_type: TrendType,
    ) -> MarketSnapshot:
        return MarketSnapshot(
            bar_idx=idx,
            ts=self._parse_bar_ts(bar.ts),
            ohlcv=(float(bar.open), float(bar.high), float(bar.low), float(bar.close), float(getattr(bar, "volume", 0.0))),
            regime=regime,
            trend_type=trend_type,
            delta_price_5m_pct=classifier.delta_pct(bars_window, min(5, len(bars_window) - 1)),
            delta_price_1h_pct=classifier.delta_pct(bars_window, min(60, len(bars_window) - 1)),
            delta_price_4h_pct=classifier.delta_pct(bars_window, min(240, len(bars_window) - 1)),
            atr_normalized=classifier.atr_normalized(bars_window),
            pdh=max(float(item.high) for item in bars_window[-288:]) if bars_window else None,
            pdl=min(float(item.low) for item in bars_window[-288:]) if bars_window else None,
            volume_ratio_to_avg=classifier.volume_ratio(bars_window),
            bars_since_last_pivot=min(len(bars_window) - 1, 30),
        )

    def _build_bot_state(self, bot_id: str, bot: Any, snapshot: MarketSnapshot) -> BotState:
        price = snapshot.ohlcv[3]
        unrealized = float(bot.unrealized_pnl(price))
        position_native = float(bot.position_size())
        contract = getattr(bot.cfg, "contract", None)
        position_usd = float(contract.notional_usd(position_native, price)) if contract is not None else 0.0
        open_orders = list(getattr(bot, "active_orders", []))
        hold_minutes = 0
        if open_orders:
            earliest = min(int(getattr(order, "opened_bar_idx", snapshot.bar_idx)) for order in open_orders)
            hold_minutes = (snapshot.bar_idx - earliest) * 5
        return BotState(
            bot_id=bot_id,
            bot_alias=str(getattr(bot.cfg, "alias", bot_id)),
            side=getattr(getattr(bot.cfg, "side", None), "name", str(getattr(bot.cfg, "side", ""))).lower(),
            contract_type=getattr(getattr(getattr(bot.cfg, "contract", None), "contract_type", None), "value", "unknown"),
            is_active=bool(getattr(bot, "is_active", True)),
            position_size_native=position_native,
            position_size_usd=position_usd,
            avg_entry_price=float(bot.avg_entry()),
            unrealized_pnl_usd=unrealized,
            hold_time_minutes=hold_minutes,
            bar_count_in_drawdown=0 if unrealized >= 0 else hold_minutes // 5,
            max_unrealized_pnl_usd=max(unrealized, 0.0),
            min_unrealized_pnl_usd=min(unrealized, 0.0),
            params_current=self._cfg_public_dict(bot.cfg),
            params_original=self._cfg_public_dict(bot.cfg),
        )

    def _cfg_public_dict(self, cfg: Any) -> dict[str, Any]:
        data = {}
        for key in vars(cfg):
            value = getattr(cfg, key)
            if hasattr(value, "name") and hasattr(value, "value"):
                data[key] = getattr(value, "value", getattr(value, "name", str(value)))
            elif hasattr(value, "contract_type"):
                data[key] = getattr(value.contract_type, "value", str(value))
            else:
                data[key] = value
        return data

    def _portfolio_equity_usd(self, bots: dict[str, Any], price: float) -> float:
        return sum(float(bot.realized_pnl) + float(bot.unrealized_pnl(price)) for bot in bots.values())

    def _max_drawdown(self, equity_curve: list[float]) -> tuple[float, float]:
        if not equity_curve:
            return 0.0, 0.0
        peak = equity_curve[0]
        max_dd = 0.0
        max_dd_pct = 0.0
        for point in equity_curve:
            peak = max(peak, point)
            dd = peak - point
            max_dd = max(max_dd, dd)
            if peak != 0:
                max_dd_pct = max(max_dd_pct, dd / abs(peak) * 100.0)
        return max_dd, max_dd_pct

    def _sharpe(self, equity_curve: list[float]) -> float:
        if len(equity_curve) < 2:
            return 0.0
        returns = [b - a for a, b in zip(equity_curve, equity_curve[1:])]
        if not returns or all(value == 0 for value in returns):
            return 0.0
        std = statistics.pstdev(returns)
        if std == 0:
            return 0.0
        return statistics.mean(returns) / std

    def _hash_bot_configs(self, configs: list[dict[str, Any]]) -> str:
        return hashlib.sha1(json.dumps(configs, sort_keys=True).encode("utf-8")).hexdigest()[:12]

    def _parse_bar_ts(self, ts: str) -> datetime:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
