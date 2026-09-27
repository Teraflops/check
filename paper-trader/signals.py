"""Bullish Signal Detector.

Takes OHLCV candles and flags bullish signals on the latest candle (or any
candle, for backtesting). Analysis only: nothing here places orders.

Usage:
    report = detect(df, timeframe="1h")
    print(report.summary())

`df` needs columns open, high, low, close, volume (oldest row first). A
DatetimeIndex (UTC) is only needed for the VWAP rule.

Indicators are computed once for the whole frame with causal (no look-ahead)
calculations, so `evaluate(ind, i)` gives the same answer at row i that
`detect(df.iloc[:i+1])` would.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TREND, MOMENTUM, VOLATILITY, VOLUME = "trend", "momentum", "volatility", "volume"
CATEGORIES = (TREND, MOMENTUM, VOLATILITY, VOLUME)

INTRADAY = {"1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h"}


@dataclass
class Params:
    # Trend
    sma_fast: int = 50
    sma_slow: int = 200
    sma_slope_lookback: int = 5
    ema_fast: int = 9
    ema_mid: int = 21
    ema_slow: int = 50
    # Momentum
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    hist_rising_candles: int = 2
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    divergence_lookback: int = 20
    swing_window: int = 2          # candles each side that must be higher for a swing low
    stoch_period: int = 14
    stoch_k: int = 3
    stoch_d: int = 3
    stoch_level: float = 20.0
    # Volatility
    bb_period: int = 20
    bb_std: float = 2.0
    squeeze_lookback: int = 120
    squeeze_recent: int = 10       # the lowest width must have occurred within this many candles
    # Volume
    breakout_lookback: int = 20
    volume_period: int = 20
    volume_mult: float = 1.5
    obv_lookback: int = 10
    obv_flat_pct: float = 1.0      # price change <= this % over the OBV window counts as flat/down


@dataclass
class Signal:
    name: str
    category: str
    cluster: str      # correlated signals share a cluster and count once as confirmation
    fired: bool
    reason: str
    skipped: bool = False


@dataclass
class Report:
    timeframe: str
    signals: list = field(default_factory=list)

    @property
    def fired(self):
        return [s for s in self.signals if s.fired]

    @property
    def score(self):
        return len(self.fired)

    @property
    def by_category(self):
        return {c: sum(1 for s in self.fired if s.category == c) for c in CATEGORIES}

    @property
    def independent_confirmations(self):
        return len({s.cluster for s in self.fired})

    @property
    def strong_setup(self):
        c = self.by_category
        return c[TREND] >= 1 and c[MOMENTUM] >= 1 and c[VOLUME] >= 1

    def summary(self):
        c = self.by_category
        lines = [
            f"Timeframe {self.timeframe}: bullish score {self.score} "
            f"(trend {c[TREND]}, momentum {c[MOMENTUM]}, volatility {c[VOLATILITY]}, volume {c[VOLUME]}; "
            f"{self.independent_confirmations} independent)",
            "STRONG SETUP: trend + momentum + volume agree" if self.strong_setup else "No strong setup",
        ]
        for s in self.fired:
            lines.append(f"  + [{s.category}] {s.name}: {s.reason}")
        skipped = [s.name for s in self.signals if s.skipped]
        if skipped:
            lines.append(f"  (skipped, not enough data/not applicable: {', '.join(skipped)})")
        return "\n".join(lines)


# ---------------------------------------------------------------- indicators

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0).where(gain.notna())


def atr(df, n=14):
    prev = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def compute_indicators(df, p=None):
    p = p or Params()
    close, vol = df["close"].astype(float), df["volume"].astype(float)
    ind = pd.DataFrame(index=df.index)
    ind["open"], ind["high"], ind["low"], ind["close"], ind["volume"] = (
        df["open"].astype(float), df["high"].astype(float), df["low"].astype(float), close, vol)

    ind["sma_fast"] = close.rolling(p.sma_fast).mean()
    ind["sma_slow"] = close.rolling(p.sma_slow).mean()
    ind["ema_fast"] = ema(close, p.ema_fast)
    ind["ema_mid"] = ema(close, p.ema_mid)
    ind["ema_slow"] = ema(close, p.ema_slow)

    macd = ema(close, p.macd_fast) - ema(close, p.macd_slow)
    ind["macd"] = macd
    ind["macd_signal"] = ema(macd, p.macd_signal)
    ind["macd_hist"] = macd - ind["macd_signal"]

    ind["rsi"] = rsi(close, p.rsi_period)
    lo = ind["rsi"].rolling(p.stoch_period).min()
    hi = ind["rsi"].rolling(p.stoch_period).max()
    stoch = ((ind["rsi"] - lo) / (hi - lo).replace(0, np.nan) * 100)
    ind["stoch_k"] = stoch.rolling(p.stoch_k).mean()
    ind["stoch_d"] = ind["stoch_k"].rolling(p.stoch_d).mean()

    mid = close.rolling(p.bb_period).mean()
    sd = close.rolling(p.bb_period).std(ddof=0)
    ind["bb_mid"], ind["bb_upper"], ind["bb_lower"] = mid, mid + p.bb_std * sd, mid - p.bb_std * sd
    ind["bb_width"] = (ind["bb_upper"] - ind["bb_lower"]) / mid

    ind["vol_avg"] = vol.rolling(p.volume_period).mean().shift()      # average of the prior candles
    ind["prior_high"] = ind["high"].rolling(p.breakout_lookback).max().shift()
    ind["obv"] = (np.sign(close.diff()).fillna(0) * vol).cumsum()

    if isinstance(df.index, pd.DatetimeIndex):
        tp = (ind["high"] + ind["low"] + close) / 3
        day = df.index.floor("D")
        ind["vwap"] = (tp * vol).groupby(day).cumsum() / vol.groupby(day).cumsum().replace(0, np.nan)
    else:
        ind["vwap"] = np.nan

    ind["atr"] = atr(ind, 14)
    return ind


# ---------------------------------------------------------------- rules

def _crossed_above(a, b, i):
    return i >= 1 and a[i - 1] <= b[i - 1] and a[i] > b[i]


def _need(name, cat, cluster, have, need):
    return Signal(name, cat, cluster, False, f"insufficient data (need {need} candles, have {have})", skipped=True)


def _valid(*vals):
    return all(v is not None and np.isfinite(v) for v in vals)


def _swing_lows(low, start, end, w):
    """Indices in [start, end] that are swing lows confirmed by `w` candles each side (all <= end)."""
    out = []
    for j in range(max(start, w), end - w + 1):
        window = low[j - w:j + w + 1]
        if low[j] == window.min() and (window[:w] > low[j]).all():
            out.append(j)
    return out


def columns(ind):
    """Indicator frame as a dict of numpy arrays; pass this to evaluate() in loops for speed."""
    return ind if isinstance(ind, dict) else {c: ind[c].to_numpy() for c in ind.columns}


def evaluate(ind, i=None, timeframe="1h", p=None):
    """Evaluate every rule at row i (default: latest row)."""
    p = p or Params()
    col = columns(ind)
    i = len(col["close"]) - 1 if i is None else i
    have = i + 1
    c, hi, lo, v = col["close"], col["high"], col["low"], col["volume"]
    sig = []

    # --- Trend
    if have < p.sma_slow + 1:
        sig.append(_need("Golden cross", TREND, "sma", have, p.sma_slow + 1))
    else:
        f, s = col["sma_fast"], col["sma_slow"]
        fired = _crossed_above(f, s, i)
        sig.append(Signal("Golden cross", TREND, "sma", fired,
                          f"SMA{p.sma_fast} {f[i]:.6g} crossed above SMA{p.sma_slow} {s[i]:.6g}" if fired
                          else f"SMA{p.sma_fast} {f[i]:.6g} vs SMA{p.sma_slow} {s[i]:.6g}, no cross"))

    if have < p.sma_slow + p.sma_slope_lookback:
        sig.append(_need("Price above long-term trend", TREND, "sma", have, p.sma_slow + p.sma_slope_lookback))
    else:
        s = col["sma_slow"]
        slope_up = s[i] > s[i - p.sma_slope_lookback]
        fired = c[i] > s[i] and slope_up
        sig.append(Signal("Price above long-term trend", TREND, "sma", fired,
                          f"close {c[i]:.6g} {'>' if c[i] > s[i] else '<='} SMA{p.sma_slow} {s[i]:.6g}, "
                          f"slope {'rising' if slope_up else 'falling'}"))

    if have < p.ema_mid + 1:
        sig.append(_need("EMA crossover", TREND, "ema", have, p.ema_mid + 1))
    else:
        fired = _crossed_above(col["ema_fast"], col["ema_mid"], i)
        sig.append(Signal("EMA crossover", TREND, "ema", fired,
                          f"EMA{p.ema_fast} crossed above EMA{p.ema_mid}" if fired else "no EMA cross"))

    if have < p.ema_slow:
        sig.append(_need("EMA stack", TREND, "ema", have, p.ema_slow))
    else:
        a, b, d = col["ema_fast"][i], col["ema_mid"][i], col["ema_slow"][i]
        fired = a > b > d
        sig.append(Signal("EMA stack", TREND, "ema", fired,
                          f"EMA{p.ema_fast} {a:.6g} > EMA{p.ema_mid} {b:.6g} > EMA{p.ema_slow} {d:.6g}" if fired
                          else "EMAs not stacked upward"))

    # --- Momentum
    macd_need = p.macd_slow + p.macd_signal
    if have < macd_need + 1:
        sig.append(_need("MACD bullish cross", MOMENTUM, "macd", have, macd_need + 1))
        sig.append(_need("MACD histogram turning up", MOMENTUM, "macd", have, macd_need + p.hist_rising_candles))
    else:
        fired = _crossed_above(col["macd"], col["macd_signal"], i)
        sig.append(Signal("MACD bullish cross", MOMENTUM, "macd", fired,
                          "MACD crossed above signal line" if fired else "no MACD cross"))
        h = col["macd_hist"]
        k = p.hist_rising_candles
        rising = i >= k and all(h[i - j] > h[i - j - 1] for j in range(k))
        fired = h[i] < 0 and rising
        sig.append(Signal("MACD histogram turning up", MOMENTUM, "macd", fired,
                          f"histogram {h[i]:.3g} < 0 and rising {k}+ candles" if fired
                          else f"histogram {h[i]:.3g}, {'rising' if rising else 'not rising'}"))

    r = col["rsi"]
    if have < p.rsi_period + 2 or not _valid(r[i], r[i - 1]):
        sig.append(_need("RSI oversold recovery", MOMENTUM, "oscillator", have, p.rsi_period + 2))
    else:
        fired = r[i - 1] < p.rsi_oversold <= r[i]
        sig.append(Signal("RSI oversold recovery", MOMENTUM, "oscillator", fired,
                          f"RSI {r[i - 1]:.1f} -> {r[i]:.1f} crossed back above {p.rsi_oversold:g}" if fired
                          else f"RSI {r[i]:.1f}"))

    if have < p.rsi_period + p.divergence_lookback:
        sig.append(_need("RSI bullish divergence", MOMENTUM, "oscillator", have, p.rsi_period + p.divergence_lookback))
    else:
        lows = [j for j in _swing_lows(lo, i - p.divergence_lookback + 1, i, p.swing_window) if _valid(r[j])]
        fired, reason = False, "fewer than two swing lows"
        if len(lows) >= 2:
            j1, j2 = lows[-2], lows[-1]
            fired = lo[j2] < lo[j1] and r[j2] > r[j1]
            reason = (f"price low {lo[j1]:.6g} -> {lo[j2]:.6g} ({'lower' if lo[j2] < lo[j1] else 'not lower'}), "
                      f"RSI {r[j1]:.1f} -> {r[j2]:.1f} "
                      f"({'higher' if r[j2] > r[j1] else 'not higher'})")
        sig.append(Signal("RSI bullish divergence", MOMENTUM, "oscillator", fired, reason))

    k_, d_ = col["stoch_k"], col["stoch_d"]
    if not (i >= 1 and _valid(k_[i], d_[i], k_[i - 1], d_[i - 1])):
        sig.append(_need("Stochastic RSI cross", MOMENTUM, "oscillator", have,
                         p.rsi_period + p.stoch_period + p.stoch_k + p.stoch_d))
    else:
        cross = _crossed_above(k_, d_, i)
        fired = cross and k_[i] < p.stoch_level and d_[i] < p.stoch_level
        sig.append(Signal("Stochastic RSI cross", MOMENTUM, "oscillator", fired,
                          f"%K {k_[i]:.1f} crossed above %D {d_[i]:.1f} below {p.stoch_level:g}" if fired
                          else f"%K {k_[i]:.1f} / %D {d_[i]:.1f}"))

    # --- Volatility
    lb = col["bb_lower"]
    if have < p.bb_period + 1:
        sig.append(_need("Bollinger bounce", VOLATILITY, "bollinger", have, p.bb_period + 1))
    else:
        fired = c[i - 1] <= lb[i - 1] and c[i] > lb[i]
        sig.append(Signal("Bollinger bounce", VOLATILITY, "bollinger", fired,
                          f"close {c[i - 1]:.6g} at/below lower band, now {c[i]:.6g} back above {lb[i]:.6g}" if fired
                          else "no lower-band bounce"))

    if have < p.squeeze_lookback + p.bb_period:
        sig.append(_need("Bollinger squeeze breakout", VOLATILITY, "bollinger", have, p.squeeze_lookback + p.bb_period))
    else:
        w = col["bb_width"][i - p.squeeze_lookback:i]          # prior candles, excluding the breakout candle
        min_age = p.squeeze_lookback - 1 - int(np.nanargmin(w))
        ub = col["bb_upper"]
        breakout = c[i] > ub[i] and c[i - 1] <= ub[i - 1]
        fired = min_age < p.squeeze_recent and breakout
        sig.append(Signal("Bollinger squeeze breakout", VOLATILITY, "bollinger", fired,
                          f"tightest band width in {p.squeeze_lookback} candles {min_age + 1} candles ago, "
                          f"close broke above upper band" if fired
                          else f"squeeze low {min_age + 1} candles ago, breakout={'yes' if breakout else 'no'}"))

    # --- Volume
    if have < max(p.breakout_lookback, p.volume_period) + 1:
        sig.append(_need("High-volume breakout", VOLUME, "breakout", have, max(p.breakout_lookback, p.volume_period) + 1))
    else:
        ph, va = col["prior_high"][i], col["vol_avg"][i]
        fired = c[i] > ph and v[i] > p.volume_mult * va
        sig.append(Signal("High-volume breakout", VOLUME, "breakout", fired,
                          f"close {c[i]:.6g} > {p.breakout_lookback}-candle high {ph:.6g}, volume {v[i] / va:.1f}x avg"
                          if fired else f"close vs prior high {c[i] / ph - 1:+.2%}, volume {v[i] / va:.1f}x avg"))

    vw = col["vwap"][i]
    if timeframe not in INTRADAY or not _valid(vw):
        s = Signal("Above VWAP", VOLUME, "vwap", False,
                   "not applicable (VWAP needs an intraday timeframe with timestamps)", skipped=True)
        sig.append(s)
    else:
        fired = c[i] > vw
        sig.append(Signal("Above VWAP", VOLUME, "vwap", fired, f"close {c[i]:.6g} {'>' if fired else '<='} VWAP {vw:.6g}"))

    if have < p.obv_lookback + 1:
        sig.append(_need("OBV rising", VOLUME, "obv", have, p.obv_lookback + 1))
    else:
        obv = col["obv"][i - p.obv_lookback + 1:i + 1]
        slope = np.polyfit(np.arange(len(obv)), obv, 1)[0]
        chg = (c[i] / c[i - p.obv_lookback + 1] - 1) * 100
        fired = slope > 0 and chg <= p.obv_flat_pct
        sig.append(Signal("OBV rising", VOLUME, "obv", fired,
                          f"OBV rising while price {chg:+.2f}% (accumulation)" if fired
                          else f"OBV slope {'up' if slope > 0 else 'down'}, price {chg:+.2f}%"))

    return Report(timeframe=timeframe, signals=sig)


def detect(df, timeframe="1h", p=None):
    """Compute all signals on the latest candle of `df`."""
    p = p or Params()
    return evaluate(compute_indicators(df, p), None, timeframe, p)
