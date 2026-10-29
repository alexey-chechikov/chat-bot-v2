"""research/indicator_atlas/atlas.py — контрпримеры GPT a7d799b (§3, P1): «тейкеры покупают сильно» при сплошь
отрицательном потоке; пропуск ликвидаций превращался в «ликвидаций не было»."""
import numpy as np
import pandas as pd

from research.indicator_atlas import atlas


def atlas_frame():
    idx = pd.date_range("2026-10-01", periods=220, freq="1h", tz="UTC")
    df = pd.DataFrame({"close": 100., "high": 101., "low": 99., "volume_usd": 1000.,
                       "taker_buy": 40., "taker_sell": -140., "taker_delta": -100.,
                       "bid_ask_delta": -100., "liq_all_long": np.nan, "liq_all_short": np.nan}, index=idx)
    for col in atlas.LEVELS.values():
        df[col] = 1.
    df.loc[idx[-6:], ["taker_buy", "taker_sell", "taker_delta", "bid_ask_delta"]] = [50., -60., -10., -10.]
    return df


def test_atlas_negative_flow_is_not_strong_buying():
    f = atlas.features(atlas_frame())
    assert f["tak6"].iloc[-1] < 0
    assert not atlas.tokens(f)["тейкеры покупают сильно 6ч"].iloc[-1]


def test_atlas_missing_liquidations_remain_unknown():
    f = atlas.features(atlas_frame())
    assert pd.isna(f["liqL6"].iloc[-1]), f["liqL6"].iloc[-1]


def test_atlas_book_green_means_positive_not_just_not_red():
    df = atlas_frame()
    df.loc[df.index[-6:], "bid_ask_delta"] = 0.0             # ровно ноль — не «зелёный»
    t = atlas.tokens(atlas.features(df))
    assert not t["стакан зелёный 5+/6"].iloc[-1]


def test_atlas_up_requires_positive_move():
    f = pd.DataFrame({"r24p": [0.95], "pos24": [0.9], "er24": [0.5], "r24": [-0.5], "w24p": [0.6]},
                     index=pd.date_range("2026-10-01", periods=1, freq="1h", tz="UTC"))
    assert atlas.context(f).iloc[0] != "UP"
