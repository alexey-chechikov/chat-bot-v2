"""Forensics of GRID-BLEED onsets — what do indicators DO at the break?

The operator's challenge (2026-06-05): stop giving 'flat is undetectable' verdicts and
instead DISSECT the break points. Take the windows where the short/long grid does NOT
survive, look at volume / liquidations / moving-average curves / funding AT the moment
the trend breaks, and derive concrete rules: when to turn the bot OFF (exit), when to
turn it back ON (restart), and which detects confirm or deny the scenario.

Key idea I missed before: I tested STEADY-STATE separation (is the average ER/ADX
different in flat vs trend — no). But the TRANSITION is an EVENT: a range break + a
volume burst + an ATR expansion + a liquidation cascade. An event can be caught even
when the steady-state level cannot. That is an EXIT TRIGGER, not a predictor.

Everything is strictly CAUSAL (bar i uses data <= close[i]; you act on i+1 open).
Light computation on frozen 2y data — this is analysis, not a simulation.
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PX = ROOT / "backtests" / "frozen" / "BTCUSDT_1h_2y.csv"
FUND = ROOT / "data" / "historical" / "binance_funding_BTCUSDT.csv"
LIQ = ROOT / "data" / "historical" / "bybit_liquidations_2024.parquet"

# --- The bleed onsets (grid's ENEMY -> EXIT) and a calm range (grid's FRIEND -> ON) ---
BLEED = [
    ("SHORT bleed -6056 (+60% rally)", "2024-10-01", "2025-01-10", "up"),
    ("Q4 cliff DG -4824",              "2025-11-05", "2025-12-25", "down"),
    ("Killer crash 85k->60k -4234",    "2025-12-28", "2026-03-01", "down"),
]
CALM = ("Range +3467 (grid friend)", "2026-02-05", "2026-05-05")


def load_4h():
    df = pd.read_csv(PX)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts")
    return df.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()


def add_funding(df):
    f = pd.read_csv(FUND)
    f["ts"] = pd.to_datetime(f["ts_ms"], unit="ms", utc=True)
    f = f.set_index("ts")["funding_rate_8h"]
    df["funding"] = f.reindex(df.index, method="ffill")
    return df


def add_liq(df):
    """4h liquidation intensity (BTC qty). Buy-liq = shorts blown (up-spikes),
    Sell-liq = longs blown (down-spikes). Cascade = confirmation of a real move."""
    try:
        lq = pd.read_parquet(LIQ)
    except Exception:
        df["liq_buy"] = np.nan
        df["liq_sell"] = np.nan
        return df, (None, None)
    lq["ts"] = pd.to_datetime(lq["ts_ms"], unit="ms", utc=True)
    lq = lq.set_index("ts")
    buy = lq.loc[lq["side"] == "Buy", "qty"].resample("4h").sum()
    sell = lq.loc[lq["side"] == "Sell", "qty"].resample("4h").sum()
    df["liq_buy"] = buy.reindex(df.index).fillna(0)
    df["liq_sell"] = sell.reindex(df.index).fillna(0)
    return df, (lq.index.min(), lq.index.max())


def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def er(close, n=24):
    return (close - close.shift(n)).abs() / close.diff().abs().rolling(n).sum()


def panel(df):
    """Causal indicator panel, all decided at bar i's close."""
    c = df["close"]
    df["atr"] = atr(df)
    df["atr_base"] = df["atr"].rolling(60).median()           # ~10-day baseline
    df["atr_exp"] = df["atr"] / df["atr_base"]                # ATR expansion ratio
    df["vol_med"] = df["volume"].rolling(60).median()
    df["vol_spike"] = df["volume"] / df["vol_med"]
    up = df["high"].rolling(20).max().shift(1)
    dn = df["low"].rolling(20).min().shift(1)
    df["brk_up"] = (c > up).astype(int)
    df["brk_dn"] = (c < dn).astype(int)
    df["er"] = er(c)
    df["ma100"] = c.rolling(100).mean()
    df["stretch"] = (c - df["ma100"]) / df["atr"]             # ATRs from the MA
    df["roc18"] = (c / c.shift(18) - 1) * 100                 # ~3-day momentum %
    df["liq_med"] = (df["liq_buy"] + df["liq_sell"]).rolling(60).median()
    df["liq_spike"] = (df["liq_buy"] + df["liq_sell"]) / df["liq_med"].replace(0, np.nan)
    return df


COLS = ["close", "roc18", "atr_exp", "vol_spike", "brk_up", "brk_dn",
        "er", "stretch", "funding", "liq_spike"]


def show(df, name, a, b, liq_cov):
    sub = df.loc[a:b]
    print(f"\n{'='*92}\n{name}   {a} -> {b}")
    has_liq = liq_cov[0] is not None and pd.Timestamp(b, tz="UTC") >= liq_cov[0] \
        and pd.Timestamp(a, tz="UTC") <= liq_cov[1]
    hdr = f"{'date':16}{'close':>9}{'roc18%':>8}{'atrEXP':>7}{'volX':>6}" \
          f"{'brkU':>5}{'brkD':>5}{'ER':>6}{'strch':>7}{'fund':>9}{'liqX':>7}"
    print(hdr)
    # daily sample (every 6 bars = 1 day) to keep it readable
    for ts in sub.index[::6]:
        r = sub.loc[ts]
        liqx = f"{r['liq_spike']:6.1f}" if has_liq and pd.notna(r['liq_spike']) else "    --"
        print(f"{ts:%Y-%m-%d %H:%M}{r['close']:9.0f}{r['roc18']:8.1f}{r['atr_exp']:7.2f}"
              f"{r['vol_spike']:6.1f}{int(r['brk_up']):5}{int(r['brk_dn']):5}{r['er']:6.2f}"
              f"{r['stretch']:7.1f}{r['funding']*1e4:8.2f}{liqx}")


def calm_stats(df, a, b):
    sub = df.loc[a:b]
    s = {}
    for col in ["atr_exp", "vol_spike", "er", "liq_spike"]:
        v = sub[col].replace([np.inf, -np.inf], np.nan).dropna()
        s[col] = (v.median(), v.quantile(0.90))
    s["stretch_abs90"] = sub["stretch"].abs().quantile(0.90)
    return s


def main():
    df = load_4h()
    df = add_funding(df)
    df, liq_cov = add_liq(df)
    df = panel(df)
    print(f"Data: {df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d}  ({len(df)} 4h bars)")
    print(f"Liquidation coverage: {liq_cov[0]} -> {liq_cov[1]}")

    # calm baseline first
    cs = calm_stats(df, CALM[1], CALM[2])
    print(f"\n--- CALM baseline ({CALM[0]}) median / 90th-pct ---")
    for k in ["atr_exp", "vol_spike", "er", "liq_spike"]:
        print(f"  {k:10}: median {cs[k][0]:.2f}   p90 {cs[k][1]:.2f}")
    print(f"  stretch_abs : p90 {cs['stretch_abs90']:.1f}")
    show(df, *CALM, liq_cov)

    for name, a, b, _dir in BLEED:
        show(df, name, a, b, liq_cov)

    # ---- candidate EXIT trigger backtest ----
    # Rule: a confirmed trend BREAK = Donchian break + ATR expanding + volume burst.
    print(f"\n{'='*92}\nEXIT TRIGGER candidate: (brkUp|brkDn) AND atr_exp>{1.4} AND vol_spike>{1.8}")
    fire = ((df["brk_up"] | df["brk_dn"]).astype(bool)
            & (df["atr_exp"] > 1.4) & (df["vol_spike"] > 1.8))
    # how fast does it fire inside each bleed window, and does it false-fire in calm?
    for name, a, b, _ in BLEED:
        win = fire.loc[a:b]
        first = win[win].index.min() if win.any() else None
        print(f"  {name[:34]:34} first fire: "
              f"{first:%Y-%m-%d %H:%M}" if first is not None else
              f"  {name[:34]:34} first fire: NONE")
    cf = fire.loc[CALM[1]:CALM[2]]
    print(f"  CALM false-fires: {int(cf.sum())} bars out of {len(cf)} "
          f"({100*cf.mean():.1f}% of the time grid would be wrongly OFF)")

    # ---- candidate RESTART trigger ----
    print(f"\nRESTART candidate: ER<0.30 for 12 bars (2d) AND atr_exp<1.1 AND no fresh break")
    calmflag = (df["er"] < 0.30) & (df["atr_exp"] < 1.1) \
        & (~(df["brk_up"] | df["brk_dn"]).astype(bool))
    streak = calmflag.groupby((~calmflag).cumsum()).cumsum()
    restart = streak >= 12
    print(f"  restart-ON share of calm window: {100*restart.loc[CALM[1]:CALM[2]].mean():.0f}%")
    print(f"  restart-ON share of bleed windows (should be LOW):")
    for name, a, b, _ in BLEED:
        print(f"    {name[:34]:34} {100*restart.loc[a:b].mean():.0f}%")


if __name__ == "__main__":
    main()
