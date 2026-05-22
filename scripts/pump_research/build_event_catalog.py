"""Phase 1 — pump/dump event catalog from the master feature CSV.

Detects bidirectional one-way moves with the SAME logic as the production
detector (services/pump_freeze/detector.py): abs move >= threshold over a
window, NO pullback filter (whipsaws included — they are the t=0 default
freeze per PUMP_DUMP_FILTER_V2.md).

For every event builds an enriched profile used by Phase 2 to measure how
early trend vs whipsaw can be told apart:
  - amplitude: move over detect window + peak move of the whole event
  - duration: minutes to peak, minutes to return (if it returned)
  - volume:   window volume / trailing-24h median volume   (spike factor)
  - OI:       delta over the move + at horizons t+5/15/30/60
  - taker:    buy-share in window + at horizons
  - funding:  rate at peak
  - shape:    wick ratio, price acceleration (2nd diff)
  - outcome:  trend / whipsaw / partial  (forward 4h AND 24h)

Output: state/pump_event_catalog.csv  — one row per event.

Run:
    python scripts/pump_research/build_event_catalog.py
    python scripts/pump_research/build_event_catalog.py --threshold 1.5
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / "data" / "pump_research" / "BTCUSDT_pump_features_1m.csv"
OUT = ROOT / "state" / "pump_event_catalog.csv"

# Production detector defaults — services/pump_freeze/config.py
THRESHOLD_PCT = 1.5      # abs move over window
WINDOW_MIN = 30          # detection window
COOLDOWN_MIN = 60        # suppress re-triggers per direction
EVENT_GAP_HOURS = 2      # consecutive triggers within this gap = one event

HORIZONS = (5, 15, 30, 60)   # minutes after detection for early-feature snapshots
LOOKAHEAD_MIN = 240          # 4h outcome window
TREND_CONTINUE_PCT = 1.0     # further move beyond trigger to call it trend
WHIPSAW_RETURN_PCT = 1.0     # return toward window-start to call it whipsaw


def load_master() -> pd.DataFrame:
    df = pd.read_csv(MASTER, dtype={"ts": "int64"})
    df = df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    # 5 leading bars lack OI (Bybit OI starts at 00:05) — backfill the gap.
    df["open_interest"] = df["open_interest"].bfill()
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df


def detect_triggers(df: pd.DataFrame, direction: str,
                     threshold: float, window: int,
                     cooldown: int) -> list[int]:
    """Bar indices where an abs move >= threshold over `window` fired.
    direction: 'up' | 'down'. Mirror of detect_move() — no pullback filter.
    """
    close = df["close"].values
    n = len(close)
    triggers: list[int] = []
    cooldown_until = -1
    for i in range(window, n):
        if i < cooldown_until:
            continue
        ref = close[i - window]
        if ref <= 0:
            continue
        move = (close[i] - ref) / ref * 100.0
        hit = move >= threshold if direction == "up" else move <= -threshold
        if hit:
            triggers.append(i)
            cooldown_until = i + cooldown
    return triggers


def group_events(triggers: list[int], df: pd.DataFrame,
                 direction: str) -> list[dict]:
    """Collapse consecutive triggers (<EVENT_GAP_HOURS apart) into one event;
    the event's anchor index = the first trigger (the moment a bot would
    actually freeze)."""
    if not triggers:
        return []
    ts = df["ts"].values
    gap_ms = EVENT_GAP_HOURS * 3600 * 1000
    events: list[dict] = []
    cur = [triggers[0]]
    for t in triggers[1:]:
        if ts[t] - ts[cur[-1]] <= gap_ms:
            cur.append(t)
        else:
            events.append({"direction": direction, "anchor": cur[0],
                           "triggers": list(cur)})
            cur = [t]
    events.append({"direction": direction, "anchor": cur[0],
                   "triggers": list(cur)})
    return events


def profile_event(df: pd.DataFrame, ev: dict, window: int) -> dict:
    """Enriched feature + outcome row for one event."""
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    vol = df["volume"].values
    oi = df["open_interest"].values
    taker = df["taker_buy_pct"].values
    funding = df["funding_rate"].values
    n = len(close)

    a = ev["anchor"]
    direction = ev["direction"]
    sign = 1.0 if direction == "up" else -1.0

    win_start = a - window
    trigger_price = close[a]
    start_price = close[win_start]
    move_pct = (trigger_price - start_price) / start_price * 100.0

    # --- volume spike: window vol vs trailing-24h median ---
    win_vol = vol[win_start:a + 1].sum()
    look = vol[max(0, a - 1440):a]
    base_vol = np.median(look) * window if len(look) else np.nan
    vol_spike = win_vol / base_vol if base_vol and base_vol > 0 else np.nan

    # --- in-window descriptive ---
    oi_delta_win = oi[a] - oi[win_start]
    taker_win = np.nanmean(taker[win_start:a + 1])
    wick = high[win_start:a + 1] - low[win_start:a + 1]
    body = np.abs(close[win_start:a + 1] - df["open"].values[win_start:a + 1])
    wick_ratio = float(np.nanmean(wick) / (np.nanmean(body) + 1e-9))
    # acceleration: 2nd diff of close over the window (mean abs)
    accel = float(np.nanmean(np.abs(np.diff(close[win_start:a + 1], n=2))))

    row = {
        "direction": direction,
        "anchor_ts": df["ts"].values[a],
        "anchor_dt": str(df["dt"].values[a]),
        "trigger_price": round(float(trigger_price), 2),
        "move_pct": round(float(move_pct), 3),
        "n_triggers": len(ev["triggers"]),
        "vol_spike": round(float(vol_spike), 2) if vol_spike == vol_spike else np.nan,
        "oi_delta_win": round(float(oi_delta_win), 1),
        "taker_win": round(float(taker_win), 4),
        "wick_ratio": round(wick_ratio, 3),
        "accel": round(accel, 4),
        "funding_at_anchor": round(float(funding[a]), 6),
    }

    # --- early-horizon snapshots (Phase 2 discrimination material) ---
    for h in HORIZONS:
        j = min(a + h, n - 1)
        row[f"move_t{h}"] = round((close[j] - trigger_price) / trigger_price * 100.0, 3)
        row[f"oi_delta_t{h}"] = round(float(oi[j] - oi[a]), 1)
        row[f"taker_t{h}"] = round(float(np.nanmean(taker[a:j + 1])), 4)

    # --- outcome over 4h: peak continuation & return ---
    end = min(a + LOOKAHEAD_MIN, n)
    seg_high = high[a:end]
    seg_low = low[a:end]
    if direction == "up":
        fwd_extreme_pct = (seg_high.max() - trigger_price) / trigger_price * 100.0
        ret_thr = trigger_price * (1 - WHIPSAW_RETURN_PCT / 100.0)
        cont_thr = trigger_price * (1 + TREND_CONTINUE_PCT / 100.0)
        ret_bar = next((k for k in range(len(seg_low)) if seg_low[k] <= ret_thr), -1)
        cont_bar = next((k for k in range(len(seg_high)) if seg_high[k] >= cont_thr), -1)
    else:
        fwd_extreme_pct = (seg_low.min() - trigger_price) / trigger_price * 100.0
        ret_thr = trigger_price * (1 + WHIPSAW_RETURN_PCT / 100.0)
        cont_thr = trigger_price * (1 - TREND_CONTINUE_PCT / 100.0)
        ret_bar = next((k for k in range(len(seg_high)) if seg_high[k] >= ret_thr), -1)
        cont_bar = next((k for k in range(len(seg_low)) if seg_low[k] <= cont_thr), -1)

    row["fwd_extreme_pct"] = round(float(fwd_extreme_pct), 3)
    row["bars_to_return"] = int(ret_bar)
    row["bars_to_continue"] = int(cont_bar)

    if ret_bar >= 0 and (cont_bar < 0 or ret_bar < cont_bar):
        outcome = "whipsaw"
    elif cont_bar >= 0 and ret_bar < 0:
        outcome = "trend"
    elif cont_bar >= 0 and ret_bar >= 0:
        outcome = "trend" if cont_bar < ret_bar else "whipsaw"
    else:
        outcome = "partial"
    row["outcome"] = outcome

    # 24h verdict cross-check
    j24 = min(a + 1440, n - 1)
    m24 = sign * (close[j24] - trigger_price) / trigger_price * 100.0
    row["move_24h_signed"] = round(float(m24), 3)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=THRESHOLD_PCT)
    ap.add_argument("--window", type=int, default=WINDOW_MIN)
    ap.add_argument("--cooldown", type=int, default=COOLDOWN_MIN)
    args = ap.parse_args()

    print(f"Loading {MASTER.name} ...")
    df = load_master()
    years = (df["ts"].iloc[-1] - df["ts"].iloc[0]) / (365.25 * 86400 * 1000)
    print(f"  {len(df):,} bars  {df['dt'].iloc[0]} .. {df['dt'].iloc[-1]}  "
          f"(~{years:.2f}y)")

    rows: list[dict] = []
    for direction in ("up", "down"):
        trig = detect_triggers(df, direction, args.threshold,
                               args.window, args.cooldown)
        evs = group_events(trig, df, direction)
        print(f"  {direction:4}: {len(trig)} triggers -> {len(evs)} events")
        for ev in evs:
            if ev["anchor"] - args.window < 0:
                continue
            rows.append(profile_event(df, ev, args.window))

    cat = pd.DataFrame(rows).sort_values("anchor_ts").reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cat.to_csv(OUT, index=False)

    print(f"\n=== CATALOG: {len(cat)} events  (~{len(cat)/years:.0f}/year) ===")
    for d in ("up", "down"):
        sub = cat[cat["direction"] == d]
        if sub.empty:
            continue
        oc = sub["outcome"].value_counts()
        print(f"  {d:4} {len(sub):>4}: " + "  ".join(
            f"{k}={oc.get(k,0)}({100*oc.get(k,0)/len(sub):.0f}%)"
            for k in ("trend", "whipsaw", "partial")))
    print(f"\nWritten: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
