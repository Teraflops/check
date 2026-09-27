#!/usr/bin/env python3
"""Autonomous paper-trading agent.

Every 5 minutes (just after each 5m candle closes) it:
  1. Advances every open paper position through the newly closed 5m candles:
     stop loss, partial take-profit, breakeven, trailing stop, EMA-cross and
     time-stop exits (see engine.py). Missed candles are replayed, so a
     restart can't skip a stop.
  2. Evaluates the bullish signal detector on each watched coin's latest
     closed candle on the signal timeframe and opens a paper long when a
     strong setup appears and the risk limits allow it.
  3. Saves state and appends to trades.csv / equity.csv.

Paper trading only: it never sends orders to Coinbase.

    python3 agent.py                 # run forever
    python3 agent.py --once          # one cycle
    python3 agent.py --status        # show positions and performance
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd

import coinbase_data as cd
from engine import EntryConfig, ExitConfig, Portfolio, RiskConfig, bearish_ema_cross, entry_decision, stats
from signals import Params, columns, compute_indicators, evaluate

BASE_SECS = 300
TF_SECS = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "6h": 21600}

log = logging.getLogger("agent")


def exit_profile(name, tf):
    per_signal_bar = TF_SECS[tf] // BASE_SECS
    base = ExitConfig(stop_atr=2.0, tp1_r=0, trail_atr=0, signal_exit=False, time_stop_bars=0)
    profiles = {
        # Chosen from backtests (see README): 2x ATR stop, full exit at 3R. Positive in both
        # halves of the test month at 0.5% and 0.25% fees; breakeven/partial variants were worse.
        "safe": replace(base, name="safe", fixed_tp_r=3.0),
        "aggressive": replace(base, name="aggressive", fixed_tp_r=4.0),
        "time_stop": replace(base, name="time_stop", fixed_tp_r=3.0, time_stop_bars=24 * per_signal_bar),
        "partial_trail": replace(base, name="partial_trail", tp1_r=2.0, trail_atr=3.0, trail_after_r=1.0),
        "trail": replace(base, name="trail", trail_atr=3.0, trail_after_r=1.0),
    }
    return profiles[name]


class Agent:
    def __init__(self, args):
        self.args = args
        self.params = Params()
        risk = RiskConfig(starting_equity=args.equity, fee_rate=args.fee, max_open=args.max_open,
                          risk_per_trade=args.risk)
        self.pf = Portfolio(risk, exit_profile(args.exit, args.timeframe), EntryConfig(), self.params)
        self.universe, self.universe_at = [], 0.0
        self.last_signal = {}         # product -> last evaluated signal candle (iso)
        self.logged_trades = 0
        self.load()

    # ------------------------------------------------------------ persistence
    def load(self):
        if os.path.exists(self.args.state):
            with open(self.args.state) as f:
                d = json.load(f)
            self.pf.load(d["portfolio"])
            self.last_signal = d.get("last_signal", {})
            self.logged_trades = len(self.pf.trades)
            log.info("Resumed: equity $%.2f, %d open, %d closed trades",
                     self.pf.equity(), len(self.pf.positions), len(self.pf.trades))
        else:
            log.info("New paper account with $%.2f", self.pf.risk.starting_equity)

    def save(self, now):
        tmp = self.args.state + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"portfolio": self.pf.to_dict(), "last_signal": self.last_signal,
                       "config": {"timeframe": self.args.timeframe, "exit": self.args.exit}}, f, indent=1)
        os.replace(tmp, self.args.state)
        new = self.pf.trades[self.logged_trades:]
        if new:
            _append_csv(self.args.trades, new)
            self.logged_trades = len(self.pf.trades)
        _append_csv(self.args.equity_log, [{
            "time": now.isoformat(), "equity": round(self.pf.equity(), 4), "cash": round(self.pf.cash, 4),
            "open_positions": len(self.pf.positions), "halted": self.pf.halted}])

    # ------------------------------------------------------------ cycle
    def signal_frame(self, pid):
        df = cd.candles(pid, self.args.timeframe, 350)
        if len(df) < 60:
            return None, None
        ind = compute_indicators(df, self.params)
        return ind, columns(ind)

    def manage(self, pid, now):
        pos = self.pf.positions[pid]
        ind, col = self.signal_frame(pid)
        atr_v = col["atr"][-1] if col else pos.atr
        k = len(col["close"]) - 1 if col else None
        sig_time = ind.index[-1].isoformat() if ind is not None else None
        new_signal_bar = sig_time and sig_time != self.last_signal.get(pid)
        bearish = bool(new_signal_bar and bearish_ema_cross(col, k))
        if sig_time:
            self.last_signal[pid] = sig_time

        bars = cd.candles(pid, "5m", 60)
        last = pd.Timestamp(pos.last_bar or pos.entry_time)
        bars = bars[bars.index > last]
        for n, (t, b) in enumerate(bars.iterrows()):
            is_last = n == len(bars) - 1
            had_tp1 = pos.tp1_done
            reason = self.pf.on_bar(pid, t.to_pydatetime(), b.open, b.high, b.low, b.close, atr_v,
                                    signal_exit=bearish and is_last)
            if pid not in self.pf.positions:
                tr = self.pf.trades[-1]
                log.info("EXIT  %-10s %s @ %.6g  P&L $%+.2f (%+.2f%%, %+.2fR)", pid, reason,
                         tr["avg_exit_price"], tr["pnl"], tr["return_pct"], tr["r"])
                return
            pos.last_bar = t.isoformat()
            if pos.tp1_done and not had_tp1:
                log.info("TP1   %-10s sold %.0f%% @ target, stop -> breakeven %.6g",
                         pid, self.pf.exit_cfg.tp1_fraction * 100, pos.stop)

    def scan_entries(self, now):
        candidates = []
        for pid in self.universe:
            if not self.pf.can_open(pid)[0]:
                continue
            ind, col = self.signal_frame(pid)
            if ind is None:
                continue
            sig_time = ind.index[-1].isoformat()
            if sig_time == self.last_signal.get(pid):
                continue                                   # already judged this candle
            self.last_signal[pid] = sig_time
            report = evaluate(col, None, self.args.timeframe, self.params)
            ok, reason = entry_decision(report, self.pf.entry_cfg, col["close"][-1], col["atr"][-1])
            if ok:
                candidates.append((report.score, pid, col["atr"][-1], reason, report))
        for score, pid, atr_v, reason, report in sorted(candidates, key=lambda x: -x[0]):
            price = cd.last_price(pid)
            if not price:
                continue
            pos, why = self.pf.open(pid, now, price, atr_v, reason)
            if pos:
                # replay the candle we entered in too, so a fast drop right after entry hits the stop
                pos.last_bar = (pd.Timestamp(now).floor("5min") - pd.Timedelta(minutes=5)).isoformat()
                log.info("ENTRY %-10s @ %.6g  qty %.6g ($%.2f)  stop %.6g (-%.2f%%)  %s", pid, pos.entry_price,
                         pos.qty, pos.qty * pos.entry_price, pos.stop,
                         (1 - pos.stop / pos.entry_price) * 100, reason)
            else:
                log.info("skip  %-10s %s", pid, why)

    def cycle(self):
        now = datetime.now(timezone.utc)
        if not self.universe or time.time() - self.universe_at > 3600:
            fresh = cd.top_products(n=self.args.products, min_24h_usd=self.args.min_24h_usd)
            if fresh:
                self.universe, self.universe_at = fresh, time.time()
        for pid in list(self.pf.positions):
            try:
                self.manage(pid, now)
            except Exception:
                log.exception("error managing %s", pid)
        for pid in list(self.pf.positions):
            price = cd.last_price(pid)
            if price:
                self.pf.marks[pid] = price
        self.pf.tick_cooldowns()
        self.pf.update_risk_state(now)
        try:
            self.scan_entries(now)
        except Exception:
            log.exception("error scanning entries")
        self.pf.update_risk_state(now)
        self.save(now)
        eq = self.pf.equity()
        log.info("equity $%.2f (%+.2f%%)  cash $%.2f  open %s%s", eq,
                 (eq / self.pf.risk.starting_equity - 1) * 100, self.pf.cash,
                 ", ".join(self.pf.positions) or "none", "  [HALTED: max drawdown]" if self.pf.halted else "")

    def run(self):
        log.info("Paper agent: %s signals, '%s' exits, %d coins, every %ds. Ctrl+C to stop.",
                 self.args.timeframe, self.args.exit, self.args.products, self.args.interval)
        while True:
            self.cycle()
            if self.args.once:
                return
            # wake 20s after the next 5-minute boundary so the candle is published
            sleep = self.args.interval - time.time() % self.args.interval + 20
            time.sleep(sleep)

    def status(self):
        pf = self.pf
        eq = pf.equity()
        print(f"Equity ${eq:.2f} ({(eq / pf.risk.starting_equity - 1) * 100:+.2f}%)  cash ${pf.cash:.2f}"
              f"{'  HALTED' if pf.halted else ''}")
        for pid, p in pf.positions.items():
            mark = pf.marks.get(pid, p.entry_price)
            print(f"  OPEN {pid:<10} entry {p.entry_price:.6g}  now {mark:.6g} ({(mark / p.entry_price - 1) * 100:+.2f}%)"
                  f"  stop {p.stop:.6g}  qty {p.qty:.6g}{'  TP1 taken' if p.tp1_done else ''}")
        if pf.trades:
            s = stats(pf.trades, pf.risk.starting_equity)
            print(f"Closed trades {s['trades']}, win rate {s['win_rate']:.1f}%, P&L ${s['pnl']:+.2f}, "
                  f"profit factor {s['profit_factor']:.2f}, avg {s['avg_r']:+.2f}R")
            for t in pf.trades[-10:]:
                print(f"  {t['exit_time'][:16]} {t['product_id']:<10} {t['return_pct']:+6.2f}%  {t['exit_reason']}")


def _append_csv(path, rows):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if new:
            w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--timeframe", default="1h", choices=list(TF_SECS), help="signal timeframe (default 1h)")
    ap.add_argument("--exit", default="safe", choices=["safe", "aggressive", "time_stop", "partial_trail", "trail"],
                    help="exit profile (default safe: 2x ATR stop, take profit at 3R)")
    ap.add_argument("--interval", type=int, default=300, help="seconds between cycles (default 300)")
    ap.add_argument("--products", type=int, default=25, help="watch the top-N USD pairs by volume")
    ap.add_argument("--min-24h-usd", type=float, default=1_000_000)
    ap.add_argument("--equity", type=float, default=1000.0, help="starting paper equity in USD")
    ap.add_argument("--risk", type=float, default=0.01, help="fraction of equity risked per trade")
    ap.add_argument("--max-open", type=int, default=3)
    ap.add_argument("--fee", type=float, default=0.005, help="simulated fee per side")
    ap.add_argument("--state", default="state.json")
    ap.add_argument("--trades", default="trades.csv")
    ap.add_argument("--equity-log", default="equity.csv")
    ap.add_argument("--log", default="agent.log")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    handlers = [logging.StreamHandler(sys.stdout)]
    if not args.status:
        handlers.append(logging.FileHandler(args.log))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
                        handlers=handlers)
    logging.Formatter.converter = time.gmtime

    agent = Agent(args)
    if args.status:
        agent.status()
        return
    try:
        agent.run()
    except KeyboardInterrupt:
        log.info("Stopped.")


if __name__ == "__main__":
    main()
