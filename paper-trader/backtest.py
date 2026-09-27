#!/usr/bin/env python3
"""Replay historical Coinbase candles through the same engine the live agent
uses and compare exit strategies side by side.

Entries are identical across variants (the signal detector's strong setups),
so differences in the results come from the exit logic alone.

    python3 backtest.py --days 30 --products 20 --timeframes 5m 15m 1h
"""

import argparse
import math
import os
import time
from dataclasses import replace

import numpy as np
import pandas as pd

import coinbase_data as cd
from engine import EntryConfig, ExitConfig, Portfolio, RiskConfig, bearish_ema_cross, entry_decision, stats
from signals import Params, columns, compute_indicators, evaluate

BASE_TF = "5m"
BASE_SECS = 300
TF_SECS = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200}
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cache")


def exit_variants(tf):
    per_signal_bar = TF_SECS[tf] // BASE_SECS
    time_stop = 24 * per_signal_bar            # 24 signal candles
    base = ExitConfig(stop_atr=2.0, tp1_r=0, trail_atr=0, signal_exit=False, time_stop_bars=0)
    return [
        replace(base, name="fixed 1R target (tight)", stop_atr=1.0, fixed_tp_r=1.0),
        replace(base, name="fixed 2R target", fixed_tp_r=2.0),
        replace(base, name="fixed 3R target  [agent 'safe']", fixed_tp_r=3.0),
        replace(base, name="fixed 4R target  [agent 'aggressive']", fixed_tp_r=4.0),
        replace(base, name="3R target + breakeven at 1.5R", fixed_tp_r=3.0, breakeven_at_r=1.5),
        replace(base, name="3R target + 24-candle time stop", fixed_tp_r=3.0, time_stop_bars=time_stop),
        replace(base, name="ATR trailing stop", trail_atr=3.0, trail_after_r=1.0),
        replace(base, name="EMA-cross exit", signal_exit=True),
        replace(base, name="partial 2R + breakeven + trail", tp1_r=2.0, trail_atr=3.0, trail_after_r=1.0),
    ]


def load_history(pid, days, warmup_hours):
    os.makedirs(CACHE, exist_ok=True)
    count = days * 288 + warmup_hours * 12
    path = os.path.join(CACHE, f"{pid}_{count}.csv")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 6 * 3600:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    else:
        df = cd.candles(pid, BASE_TF, count)
        df.to_csv(path)
    return df


def fill_gaps(df, index):
    """Reindex to a full 5m grid; minutes without trades become flat zero-volume bars."""
    df = df.reindex(index)
    close = df["close"].ffill()
    for c in ("open", "high", "low"):
        df[c] = df[c].fillna(close)
    df["close"] = close
    df["volume"] = df["volume"].fillna(0)
    return df


def resample(df, tf):
    if tf == BASE_TF:
        return df
    return df.resample(tf.replace("m", "min"), label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()


def run(data, tf, exit_cfg, test_start, risk=None, entry=None, params=None):
    params = params or Params()
    pf = Portfolio(risk or RiskConfig(), exit_cfg, entry or EntryConfig(), params)
    tf_secs = TF_SECS[tf]
    index = next(iter(data.values())).index
    base = {pid: {c: df[c].to_numpy() for c in ("open", "high", "low", "close")} for pid, df in data.items()}
    sig = {}
    for pid, df in data.items():
        ind = compute_indicators(resample(df, tf), params)
        sig[pid] = (columns(ind), {int(t.timestamp()): k for k, t in enumerate(ind.index)})

    pending, curve, last_atr = [], [], {}
    ts = ((index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy()   # unit-agnostic epoch secs
    for j, t in enumerate(index):
        if t < test_start:
            continue
        now = t.to_pydatetime()
        # queued entries fill at this bar's open
        for _, pid, atr_v, reason in sorted(pending, reverse=True):
            o = base[pid]["open"][j]
            if np.isfinite(o):
                pf.open(pid, now, o, atr_v, reason)
        pending = []

        closes_signal = (ts[j] + BASE_SECS) % tf_secs == 0
        sig_start = ts[j] + BASE_SECS - tf_secs
        for pid in data:
            b = base[pid]
            if not np.isfinite(b["close"][j]):
                continue
            pf.marks[pid] = b["close"][j]
            col, pos_of = sig[pid]
            k = pos_of.get(sig_start) if closes_signal else None
            if k is not None:
                last_atr[pid] = col["atr"][k]
            atr_v = last_atr.get(pid)
            if pid in pf.positions:
                pf.on_bar(pid, now, b["open"][j], b["high"][j], b["low"][j], b["close"][j],
                          atr_v, signal_exit=k is not None and bearish_ema_cross(col, k))
            elif k is not None and pf.can_open(pid)[0]:
                c = col["close"][k]
                if pf.entry_cfg.require_uptrend and not c > col["sma_slow"][k]:
                    continue                                   # cheap pre-filter
                report = evaluate(col, k, tf, params)
                ok, reason = entry_decision(report, pf.entry_cfg, c, atr_v)
                if ok:
                    pending.append((report.score, pid, atr_v, reason))
        pf.tick_cooldowns()
        pf.update_risk_state(now)
        curve.append(pf.equity())

    # close anything still open at the last price so results are comparable
    for pid in list(pf.positions):
        pf.exit_all(pid, pf.marks[pid], index[-1].to_pydatetime(), "end of backtest")
    curve.append(pf.equity())
    return pf, curve


def _run_stats(data, tf, ex, start, risk, params):
    pf, curve = run(data, tf, ex, start, risk=risk, params=params)
    return pf.trades, risk.starting_equity, curve


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--products", type=int, default=20, help="top-N USD pairs by 24h volume")
    ap.add_argument("--timeframes", nargs="+", default=["5m", "15m", "1h"])
    ap.add_argument("--halves", action="store_true", help="also report each half of the window (stability check)")
    ap.add_argument("--fee", type=float, default=0.005, help="fee per side (0.005 = 0.5%%)")
    ap.add_argument("--out", default="backtest_results.csv")
    args = ap.parse_args()

    params = Params()
    warmup_hours = math.ceil((params.sma_slow + params.squeeze_lookback) * max(TF_SECS[t] for t in args.timeframes) / 3600) + 2
    products = cd.top_products(n=args.products)
    print(f"Loading {args.days}d of 5m candles (+{warmup_hours}h warm-up) for {len(products)} products...")
    raw = {pid: load_history(pid, args.days, warmup_hours) for pid in products}
    raw = {k: v for k, v in raw.items() if len(v) > 1000}
    start = min(df.index[0] for df in raw.values())
    end = max(df.index[-1] for df in raw.values())
    index = pd.date_range(start, end, freq="5min", tz="UTC")
    data = {pid: fill_gaps(df, index) for pid, df in raw.items()}
    test_start = end - pd.Timedelta(days=args.days)
    print(f"Test window {test_start:%Y-%m-%d %H:%M} -> {end:%Y-%m-%d %H:%M} UTC, fee {args.fee:.2%}/side\n")

    risk = RiskConfig(fee_rate=args.fee)
    rows = []
    for tf in args.timeframes:
        for ex in exit_variants(tf):
            pf, curve = run(data, tf, ex, test_start, risk=risk, params=params)
            s = stats(pf.trades, risk.starting_equity, curve)
            rows.append({"timeframe": tf, "exit": ex.name, **s})
            line = (f"{tf:>4} | {ex.name:<40} trades {s['trades']:>4}  win {s['win_rate']:5.1f}%  "
                    f"return {s['return_pct']:+6.2f}%  PF {s['profit_factor']:5.2f}  avgR {s['avg_r']:+5.2f}  "
                    f"maxDD {s['max_drawdown_pct']:5.2f}%  worst {s['worst_trade_pct']:+6.2f}%")
            if args.halves:
                mid = test_start + (end - test_start) / 2
                first = {k: v[v.index <= mid] for k, v in data.items()}
                h = [stats(*_run_stats(first, tf, ex, test_start, risk, params)),
                     stats(*_run_stats(data, tf, ex, mid, risk, params))]
                rows[-1].update(first_half_pct=h[0]["return_pct"], second_half_pct=h[1]["return_pct"])
                line += f"  halves {h[0]['return_pct']:+5.1f}% / {h[1]['return_pct']:+5.1f}%"
            print(line)
        print()

    # buy-and-hold of the same basket over the test window, for context
    holds = {pid: (df["close"].iloc[-1] / df.loc[df.index >= test_start, "close"].iloc[0] - 1) * 100
             for pid, df in data.items()}
    print(f"Equal-weight buy & hold of the same {len(data)} coins over the window: {np.mean(list(holds.values())):+.2f}% "
          f"(median {np.median(list(holds.values())):+.2f}%)")
    print("  " + ", ".join(f"{k.replace('-USD', '')} {v:+.0f}%" for k, v in sorted(holds.items(), key=lambda x: -x[1])))
    pd.DataFrame(rows).to_csv(args.out, index=False)
    print(f"Saved {args.out}")


if __name__ == "__main__":
    main()
