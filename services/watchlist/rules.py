"""Rule parsing + evaluation."""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = ROOT / "state" / "watchlist.json"

# Поддерживаемые поля и где их брать
# Все читается из state/deriv_live.json (BTCUSDT) + market_live/market_1m.csv (price)
SUPPORTED_FIELDS = {
    "funding": "funding_rate_8h в %",
    "long_pct": "Binance global_long_account_pct",
    "short_pct": "Binance global_short_account_pct",
    "top_long_pct": "Binance top_trader_long_pct",
    "top_short_pct": "Binance top_trader_short_pct",
    "taker_buy": "taker_buy_pct",
    "taker_sell": "taker_sell_pct",
    "premium": "premium_pct",
    "oi_change_1h": "oi_change_1h_pct",
    "btc_d": "BTC dominance %",
    "price": "BTC mark price USD",
    "cascade_long_5min": "long-cascade BTC за 5 мин",
    "cascade_short_5min": "short-cascade BTC за 5 мин",
    "top_minus_global_long": "top_trader_long_pct - global_long_pct (pp). "
                              "Negative = top traders шортят пока retail лонгует "
                              "→ контрарианский LONG-сигнал (n=55, 71% pct_up 24h)",
}


@dataclass
class Rule:
    id: str
    field: str
    op: str  # ">", "<", ">=", "<="
    threshold: float
    enabled: bool = True
    last_fired: Optional[str] = None  # iso ts
    fire_count: int = 0
    label: Optional[str] = None  # пользовательский тэг
    symbol: str = "BTCUSDT"  # multi-asset support: BTCUSDT (default) / ETHUSDT / XRPUSDT
    disabled_reason: Optional[str] = None  # explanation when enabled=False (e.g. backtest verdict)
    execution_note: Optional[str] = None   # non-disabling note (e.g. "maker-only after refactor")

    def matches(self, value: float) -> bool:
        if self.op == ">":
            return value > self.threshold
        if self.op == "<":
            return value < self.threshold
        if self.op == ">=":
            return value >= self.threshold
        if self.op == "<=":
            return value <= self.threshold
        return False


def parse_rule(text: str) -> Rule | None:
    """Parse 'field op threshold' (e.g. 'funding > 0.01' or 'long_pct >= 60').

    Returns Rule or None if invalid.
    """
    text = text.strip()
    m = re.match(r"^\s*(\w+)\s*(>=|<=|>|<)\s*(-?\d+\.?\d*)\s*$", text)
    if not m:
        return None
    field, op, thresh = m.groups()
    if field not in SUPPORTED_FIELDS:
        return None
    return Rule(
        id=uuid.uuid4().hex[:8],
        field=field,
        op=op,
        threshold=float(thresh),
    )


def load_rules() -> list[Rule]:
    if not RULES_PATH.exists():
        return []
    try:
        data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        rules = []
        allowed = set(Rule.__dataclass_fields__.keys())
        for d in data.get("rules", []):
            # Filter to known dataclass fields — tolerate extras so future metadata
            # additions can't silently delete rules through the save/load cycle.
            filtered = {k: v for k, v in d.items() if k in allowed}
            try:
                rules.append(Rule(**filtered))
            except (TypeError, ValueError):
                logger.exception("watchlist.rule_load_skipped id=%s", d.get("id"))
                continue
        return rules
    except (OSError, json.JSONDecodeError):
        return []


def save_rules(rules: list[Rule]) -> None:
    RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = {"rules": [asdict(r) for r in rules]}
        RULES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        logger.exception("watchlist.save_failed")


def add_rule(text: str) -> Rule | None:
    rule = parse_rule(text)
    if rule is None:
        return None
    rules = load_rules()
    rules.append(rule)
    save_rules(rules)
    return rule


def remove_rule(rule_id: str) -> bool:
    rules = load_rules()
    new = [r for r in rules if r.id != rule_id]
    if len(new) == len(rules):
        return False
    save_rules(new)
    return True


def toggle_rule(rule_id: str) -> Rule | None:
    rules = load_rules()
    for r in rules:
        if r.id == rule_id:
            r.enabled = not r.enabled
            save_rules(rules)
            return r
    return None


def _read_value(field: str, symbol: str = "BTCUSDT") -> float | None:
    """Read current value of a field from live state.

    symbol: BTCUSDT / ETHUSDT / XRPUSDT — для derivative полей из deriv_live.json.
    Cascade/price/special fields ignore symbol (всегда BTC).
    """
    import csv as _csv
    deriv_path = ROOT / "state" / "deriv_live.json"
    market_1m = ROOT / "market_live" / "market_1m.csv"
    liq_csv = ROOT / "market_live" / "liquidations.csv"

    # Liquidations (cascade fields) — special handling
    if field in ("cascade_long_5min", "cascade_short_5min"):
        if not liq_csv.exists():
            return 0.0
        from datetime import timedelta as _td
        side_filter = "long" if field == "cascade_long_5min" else "short"
        cutoff = datetime.now(timezone.utc) - _td(minutes=5)
        total = 0.0
        try:
            with liq_csv.open(newline="", encoding="utf-8") as f:
                for row in _csv.DictReader(f):
                    ts_s = row.get("ts_utc", "")
                    if not ts_s:
                        continue
                    try:
                        ts = datetime.fromisoformat(ts_s.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if ts < cutoff:
                        continue
                    if (row.get("side") or "").lower() != side_filter:
                        continue
                    try:
                        qty = float(row.get("qty") or 0)
                    except (ValueError, TypeError):
                        continue
                    if qty > 0:
                        total += qty
        except OSError:
            return None
        return total

    # Price from market_1m last close
    if field == "price":
        if not market_1m.exists():
            return None
        try:
            last_close = 0.0
            with market_1m.open(newline="", encoding="utf-8") as f:
                for row in _csv.DictReader(f):
                    try:
                        last_close = float(row.get("close") or 0)
                    except (ValueError, KeyError):
                        pass
            return last_close if last_close > 0 else None
        except OSError:
            return None

    # Everything else from deriv_live.json
    if not deriv_path.exists():
        return None
    try:
        data = json.loads(deriv_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    btc = data.get(symbol.upper(), {}) or {}
    glob = data.get("global", {}) or {}

    if field == "funding":
        v = btc.get("funding_rate_8h")
        return v * 100 if v is not None else None
    if field == "long_pct":
        return btc.get("global_long_account_pct")
    if field == "short_pct":
        return btc.get("global_short_account_pct")
    if field == "top_long_pct":
        return btc.get("top_trader_long_pct")
    if field == "top_short_pct":
        return btc.get("top_trader_short_pct")
    if field == "taker_buy":
        return btc.get("taker_buy_pct")
    if field == "taker_sell":
        return btc.get("taker_sell_pct")
    if field == "premium":
        return btc.get("premium_pct")
    if field == "oi_change_1h":
        return btc.get("oi_change_1h_pct")
    if field == "btc_d":
        return glob.get("btc_dominance_pct")
    # Synthetic field: smart-money divergence (top - global longs in percentage points)
    if field == "top_minus_global_long":
        top_l = btc.get("top_trader_long_pct")
        glob_l = btc.get("global_long_account_pct")
        if top_l is None or glob_l is None:
            return None
        return float(top_l) - float(glob_l)
    return None


# Rules disabled by path-aware audit 2026-05-17 (scripts/watchlist_path_aware_backtest.py).
# state/watchlist.json is gitignored so per-rule `enabled=false` does NOT propagate
# across machines / fresh clones. This hardcoded set guarantees a fresh deploy on
# Mac OR Windows skips these broken rules even if state file is regenerated.
# To re-enable a rule after re-validation: remove its ID from this set + verify by
# re-running scripts/watchlist_path_aware_backtest.py with new data.
HARDCODED_DISABLED_IDS = {
    # taker_imbalance_long across all 3 symbols — -EV in any execution
    "a1b2c3d4",  # BTC own taker > 58: mean PnL -0.061%/trade, sum -$10K
    "eth00002",  # ETH cross-asset taker > 58: -0.049%/trade
    "xrp00002",  # XRP cross-asset taker > 58: -0.057%/trade
    # topshort_divergence_long — anti-edge -35 п.п. vs baseline
    "c9d0e1f2",  # n=17, mean PnL -0.26%/trade, paper "71% pct_up" inverted
}


def evaluate_rules(rules: list[Rule]) -> list[tuple[Rule, float]]:
    """Return list of (rule, value) for rules that match. Skips disabled.
    Hardcoded broken-rule set takes precedence over JSON `enabled` flag —
    safety net against gitignored watchlist.json drift between machines."""
    fired: list[tuple[Rule, float]] = []
    for rule in rules:
        if not rule.enabled:
            continue
        if rule.id in HARDCODED_DISABLED_IDS:
            continue
        v = _read_value(rule.field, symbol=getattr(rule, "symbol", "BTCUSDT"))
        if v is None:
            continue
        if rule.matches(v):
            fired.append((rule, v))
    return fired


def format_rule_summary(rules: list[Rule]) -> str:
    if not rules:
        return "Watchlist пуст. Добавь правило: /watch add <field> <op> <value>\n\nПоддерживаемые поля:\n" + "\n".join(
            f"  {k} — {v}" for k, v in SUPPORTED_FIELDS.items()
        )
    lines = [f"Watchlist ({len(rules)} правил):"]
    for r in rules:
        flag = "✓" if r.enabled else "✗"
        last = f" last_fired {r.last_fired[11:16]}" if r.last_fired else ""
        fc = f" (сработал {r.fire_count}×)" if r.fire_count else ""
        lines.append(f"  [{r.id}] {flag} {r.field} {r.op} {r.threshold}{last}{fc}")
    return "\n".join(lines)
