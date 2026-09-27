"""Synthetic-data tests: each rule has a series that should fire and one that shouldn't.

Short indicator periods are passed through Params so the series stay small and
readable; the rules themselves are the same ones used with default periods.
"""

import numpy as np
import pandas as pd
import pytest

from signals import Params, Report, Signal, compute_indicators, detect, evaluate


def candles(closes, volumes=None, index=None):
    c = np.asarray(closes, float)
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({
        "open": o, "high": np.maximum(o, c) * 1.001, "low": np.minimum(o, c) * 0.999, "close": c,
        "volume": np.full(len(c), 100.0) if volumes is None else np.asarray(volumes, float),
    }, index=index)


def sig(df, name, p=None, timeframe="1h"):
    p = p or Params()
    report = evaluate(compute_indicators(df, p), None, timeframe, p)
    return next(s for s in report.signals if s.name == name)


RISING = [10 + i * 0.5 for i in range(30)]
FALLING = [30 - i * 0.5 for i in range(30)]

# ------------------------------------------------------------------ trend

def test_golden_cross():
    p = Params(sma_fast=2, sma_slow=4)
    assert sig(candles([10, 10, 10, 10, 9, 8, 7, 12]), "Golden cross", p).fired
    assert not sig(candles(RISING), "Golden cross", p).fired     # fast already above slow


def test_price_above_long_term_trend():
    p = Params(sma_slow=5, sma_slope_lookback=2)
    assert sig(candles(RISING), "Price above long-term trend", p).fired
    assert not sig(candles(FALLING), "Price above long-term trend", p).fired


def test_ema_crossover():
    p = Params(ema_fast=2, ema_mid=4)
    assert sig(candles([10, 10, 10, 9, 8, 7, 6, 5, 12]), "EMA crossover", p).fired
    assert not sig(candles(RISING), "EMA crossover", p).fired


def test_ema_stack():
    p = Params(ema_fast=2, ema_mid=3, ema_slow=5)
    assert sig(candles(RISING), "EMA stack", p).fired
    assert not sig(candles(FALLING), "EMA stack", p).fired

# ------------------------------------------------------------------ momentum

MACD_P = Params(macd_fast=3, macd_slow=6, macd_signal=3, hist_rising_candles=2)
DECLINE = [100 - i for i in range(20)]


def test_macd_bullish_cross():
    assert sig(candles(DECLINE + [85]), "MACD bullish cross", MACD_P).fired
    assert not sig(candles(DECLINE), "MACD bullish cross", MACD_P).fired


def test_macd_histogram_turning_up():
    assert sig(candles([100] * 20 + [95, 90, 85, 84.5, 84.2]), "MACD histogram turning up", MACD_P).fired
    accelerating_drop = [100 - i * i * 0.05 for i in range(25)]
    assert not sig(candles(accelerating_drop), "MACD histogram turning up", MACD_P).fired


def test_rsi_oversold_recovery():
    p = Params(rsi_period=3)
    assert sig(candles([10, 10, 10, 9, 8, 7, 6, 5, 4, 3, 4.5]), "RSI oversold recovery", p).fired
    assert not sig(candles([10, 10, 10, 9, 8, 7, 6, 5, 4, 3, 2.5]), "RSI oversold recovery", p).fired


DIV_P = Params(rsi_period=3, divergence_lookback=12, swing_window=1)


def test_rsi_bullish_divergence():
    # sharp drop to 7 (very low RSI), then a slow grind to a lower low at 6.9 (higher RSI)
    s = sig(candles([10] * 10 + [7, 8, 9, 8.5, 8, 7.5, 6.9, 7.5, 8]), "RSI bullish divergence", DIV_P)
    assert s.fired, s.reason


def test_rsi_divergence_needs_lower_price_low():
    s = sig(candles([10] * 10 + [7, 8, 9, 8.5, 8, 7.5, 7.2, 7.5, 8]), "RSI bullish divergence", DIV_P)
    assert not s.fired and "not lower" in s.reason


STOCH_P = Params(rsi_period=3, stoch_period=5, stoch_k=2, stoch_d=2, stoch_level=20)


def _choppy_decline():
    seq = [20.0]
    for i in range(40):
        seq.append(seq[-1] * (1.01 if i % 4 == 0 else 0.99))
    return seq


def test_stoch_rsi_cross_below_20():
    seq = _choppy_decline()
    seq.append(seq[-1] * 1.003)
    assert sig(candles(seq), "Stochastic RSI cross", STOCH_P).fired


def test_stoch_rsi_cross_above_20_does_not_count():
    seq = _choppy_decline()
    seq.append(seq[-1] * 1.01)          # %K jumps to 50: a cross, but not from oversold
    assert not sig(candles(seq), "Stochastic RSI cross", STOCH_P).fired

# ------------------------------------------------------------------ volatility

def test_bollinger_bounce():
    # with n candles one outlier can move at most (n-1)/sqrt(n) std devs, so n=5 can't pierce a 2-sd band
    p = Params(bb_period=10)
    flat = [10, 10.1, 9.9] * 4
    assert sig(candles(flat + [8, 9.8]), "Bollinger bounce", p).fired
    assert not sig(candles(flat + [10.1, 10]), "Bollinger bounce", p).fired


SQ_P = Params(bb_period=10, squeeze_lookback=25, squeeze_recent=5)
SQUEEZE = [10 + (2 if i % 2 else -2) for i in range(25)] + [10 + (0.01 if i % 2 else -0.01) for i in range(12)]


def test_bollinger_squeeze_breakout():
    assert sig(candles(SQUEEZE + [10.5]), "Bollinger squeeze breakout", SQ_P).fired


def test_squeeze_without_breakout():
    assert not sig(candles(SQUEEZE + [10.0]), "Bollinger squeeze breakout", SQ_P).fired


def test_breakout_without_recent_squeeze():
    wide = [10 + (2 if i % 2 else -2) for i in range(37)]
    assert not sig(candles(wide + [14]), "Bollinger squeeze breakout", SQ_P).fired

# ------------------------------------------------------------------ volume

VOL_P = Params(breakout_lookback=5, volume_period=5)


def test_high_volume_breakout():
    closes = [10] * 10 + [11]
    assert sig(candles(closes, [100] * 10 + [300]), "High-volume breakout", VOL_P).fired
    assert not sig(candles(closes, [100] * 11), "High-volume breakout", VOL_P).fired      # no volume
    assert not sig(candles([10] * 11, [100] * 10 + [300]), "High-volume breakout", VOL_P).fired  # no breakout


def test_above_vwap_intraday():
    idx = pd.date_range("2026-09-27", periods=12, freq="1h", tz="UTC")
    assert sig(candles(RISING[:12], index=idx), "Above VWAP", timeframe="1h").fired
    assert not sig(candles(FALLING[:12], index=idx), "Above VWAP", timeframe="1h").fired


def test_vwap_skipped_on_daily():
    idx = pd.date_range("2026-09-01", periods=12, freq="1D", tz="UTC")
    s = sig(candles(RISING[:12], index=idx), "Above VWAP", timeframe="1d")
    assert s.skipped and not s.fired


def test_obv_rising_on_flat_price():
    p = Params(obv_lookback=6)
    closes = [10, 10.02, 10, 10.02, 10, 10.02, 10, 10.02]
    vols = [100, 500, 100, 500, 100, 500, 100, 500]     # heavy volume on up candles
    assert sig(candles(closes, vols), "OBV rising", p).fired


def test_obv_rising_with_rallying_price_is_not_accumulation():
    p = Params(obv_lookback=6)
    assert not sig(candles(RISING[:8], [100] * 8), "OBV rising", p).fired

# ------------------------------------------------------------------ scoring / robustness

def test_insufficient_data_skips_sma200_rules_without_crashing():
    df = candles(RISING[:30] * 2)                # 60 candles, default periods
    report = detect(df, "1h")
    skipped = {s.name for s in report.signals if s.skipped}
    assert {"Golden cross", "Price above long-term trend", "Bollinger squeeze breakout"} <= skipped
    assert len(report.signals) == 14


def test_tiny_input_does_not_crash():
    report = detect(candles([10, 11]), "1h")
    assert report.score == 0 and not report.strong_setup


def _report(*fired):
    cats = {"t": "trend", "m": "momentum", "v": "volume", "x": "volatility"}
    return Report("1h", [Signal(f"s{i}", cats[k], cl, True, "") for i, (k, cl) in enumerate(fired)])


def test_strong_setup_needs_trend_momentum_and_volume():
    assert _report(("t", "sma"), ("m", "macd"), ("v", "obv")).strong_setup
    assert not _report(("t", "sma"), ("m", "macd"), ("x", "bollinger")).strong_setup


def test_correlated_oscillators_count_once():
    r = _report(("m", "oscillator"), ("m", "oscillator"), ("m", "oscillator"))
    assert r.score == 3
    assert r.independent_confirmations == 1
    assert not r.strong_setup


def test_summary_lists_fired_signals():
    p = Params(sma_fast=2, sma_slow=4)
    text = detect(candles([10, 10, 10, 10, 9, 8, 7, 12]), "1h", p).summary()
    assert "Golden cross" in text and "bullish score" in text


def test_evaluate_matches_detect_on_truncated_frame():
    rng = np.random.default_rng(1)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
    df = candles(closes, rng.uniform(50, 150, 400))
    ind = compute_indicators(df)
    for i in (250, 320, 399):
        a = [s.fired for s in evaluate(ind, i).signals]
        b = [s.fired for s in detect(df.iloc[:i + 1]).signals]
        assert a == b, i
