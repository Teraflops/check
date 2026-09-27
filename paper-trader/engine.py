"""Paper-trading engine: entries from the signal detector, risk sizing, exits.

Shared by the live agent and the backtester so both trade identically.
All fills are simulated; nothing here talks to an exchange.

Exit logic runs on every base (5m) bar of an open position, in this order:
  1. Stop loss (initial, breakeven or trailing): if the bar's low touches the
     stop we exit at the stop, or at the open if the bar gapped below it.
     Checked first, so a bar that touches both stop and target counts as a loss.
  2. Fixed take-profit (if configured): exit everything at the target.
  3. Partial take-profit: sell a fraction at tp1_r x risk, then move the stop to
     breakeven (entry plus round-trip fees) so the rest can't turn into a loss.
  4. Breakeven (optional): once the trade reaches breakeven_at_r, move the stop
     to entry plus fees.
     Trailing stop (chandelier): once the trade is trail_after_r in profit, the
     stop follows the highest high minus trail_atr x ATR. It only moves up.
  5. Signal exit: EMA(fast) crosses below EMA(mid) on the signal timeframe.
  6. Time stop: if the trade hasn't reached time_stop_min_r after
     time_stop_bars, exit at the close. Dead trades tie up capital.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from signals import Params


@dataclass
class ExitConfig:
    name: str = "partial_trail"
    stop_atr: float = 2.0
    min_stop_pct: float = 1.0
    max_stop_pct: float = 5.0
    fixed_tp_r: float = 0.0          # 0 = off; else exit everything at this multiple of risk
    tp1_r: float = 1.5               # 0 = off
    tp1_fraction: float = 0.5
    breakeven_after_tp1: bool = True
    breakeven_at_r: float = 0.0      # 0 = off; else move stop to breakeven once the trade reaches this R
    trail_atr: float = 3.0           # 0 = off
    trail_after_r: float = 1.0
    signal_exit: bool = True
    time_stop_bars: int = 0          # in base bars; 0 = off
    time_stop_min_r: float = 0.5


@dataclass
class EntryConfig:
    require_strong: bool = True       # trend + momentum + volume must agree
    min_score: int = 3
    min_independent: int = 3          # distinct correlation clusters
    require_uptrend: bool = True      # "Price above long-term trend" must fire
    max_atr_pct: float = 5.0          # skip coins whose ATR is above this % of price


@dataclass
class RiskConfig:
    starting_equity: float = 1000.0
    risk_per_trade: float = 0.01      # fraction of equity lost if the initial stop is hit
    max_position_pct: float = 0.25
    max_open: int = 3
    fee_rate: float = 0.005           # per side; Coinbase charged ~0.5% on your W buys
    slippage: float = 0.0005          # per market fill
    daily_loss_limit: float = 0.03    # stop opening trades for the rest of the UTC day
    max_drawdown: float = 0.15        # kill switch: halt all new trades
    cooldown_bars: int = 12           # base bars to wait after a losing exit on a product


def entry_decision(report, entry_cfg, close, atr_value):
    """Return (ok, reason) for opening a long based on a signals.Report."""
    names = {s.name for s in report.fired}
    if entry_cfg.require_strong and not report.strong_setup:
        return False, "no strong setup"
    if report.score < entry_cfg.min_score:
        return False, f"score {report.score} < {entry_cfg.min_score}"
    if report.independent_confirmations < entry_cfg.min_independent:
        return False, f"{report.independent_confirmations} independent confirmations < {entry_cfg.min_independent}"
    if entry_cfg.require_uptrend and "Price above long-term trend" not in names:
        return False, "not above a rising SMA200"
    if not atr_value or atr_value <= 0:
        return False, "no ATR"
    if atr_value / close * 100 > entry_cfg.max_atr_pct:
        return False, f"too volatile (ATR {atr_value / close:.1%})"
    fired = ", ".join(s.name for s in report.fired)
    return True, f"score {report.score} [{fired}]"


def bearish_ema_cross(col, i):
    f, m = col["ema_fast"], col["ema_mid"]
    return i >= 1 and f[i - 1] >= m[i - 1] and f[i] < m[i]


@dataclass
class Position:
    product_id: str
    entry_time: str
    entry_price: float
    qty: float
    initial_qty: float
    stop: float
    initial_stop: float
    risk_per_unit: float
    atr: float
    entry_reason: str = ""
    tp1_done: bool = False
    highest: float = 0.0
    bars: int = 0
    max_r: float = 0.0
    cost: float = 0.0                 # cash paid including entry fee
    proceeds: float = 0.0             # cash received from exits after fees
    last_bar: str = ""                # last base bar processed (live agent bookkeeping)
    exits: list = field(default_factory=list)

    def r_multiple(self, price):
        return (price - self.entry_price) / self.risk_per_unit


class Portfolio:
    def __init__(self, risk=None, exits=None, entry=None, params=None):
        self.risk = risk or RiskConfig()
        self.exit_cfg = exits or ExitConfig()
        self.entry_cfg = entry or EntryConfig()
        self.params = params or Params()
        self.cash = self.risk.starting_equity
        self.positions = {}
        self.trades = []
        self.peak = self.risk.starting_equity
        self.day = None
        self.day_start_equity = self.risk.starting_equity
        self.halted = False
        self.cooldown = {}            # product -> bars remaining
        self.marks = {}               # product -> last price

    # ------------------------------------------------------------ accounting
    def equity(self):
        return self.cash + sum(p.qty * self.marks.get(k, p.entry_price) for k, p in self.positions.items())

    def update_risk_state(self, now):
        eq = self.equity()
        self.peak = max(self.peak, eq)
        day = now.date().isoformat()
        if day != self.day:
            self.day, self.day_start_equity = day, eq
        if eq < self.peak * (1 - self.risk.max_drawdown):
            self.halted = True

    def can_open(self, product_id):
        if self.halted:
            return False, "kill switch: max drawdown hit"
        if self.equity() < self.day_start_equity * (1 - self.risk.daily_loss_limit):
            return False, "daily loss limit hit"
        if product_id in self.positions:
            return False, "already holding"
        if len(self.positions) >= self.risk.max_open:
            return False, "max open positions"
        if self.cooldown.get(product_id, 0) > 0:
            return False, "cooling down after a loss"
        return True, ""

    # ------------------------------------------------------------ trading
    def open(self, product_id, now, price, atr_value, reason=""):
        ok, why = self.can_open(product_id)
        if not ok:
            return None, why
        r, e = self.risk, self.exit_cfg
        fill = price * (1 + r.slippage)
        dist = min(max(e.stop_atr * atr_value, fill * e.min_stop_pct / 100), fill * e.max_stop_pct / 100)
        eq = self.equity()
        qty = eq * r.risk_per_trade / dist
        qty = min(qty, eq * r.max_position_pct / fill, self.cash / (fill * (1 + r.fee_rate)))
        if qty * fill < 1:                               # Coinbase minimum order is ~$1
            return None, "position too small"
        cost = qty * fill * (1 + r.fee_rate)
        self.cash -= cost
        pos = Position(product_id, _iso(now), fill, qty, qty, fill - dist, fill - dist, dist, atr_value,
                       entry_reason=reason, highest=fill, cost=cost)
        self.positions[product_id] = pos
        self.marks[product_id] = price
        return pos, "opened"

    def _sell(self, pos, qty, price, now, reason):
        qty = min(qty, pos.qty)
        cash = qty * price * (1 - self.risk.fee_rate)
        self.cash += cash
        pos.qty -= qty
        pos.proceeds += cash
        pos.exits.append({"time": _iso(now), "qty": qty, "price": price, "reason": reason})
        if pos.qty <= pos.initial_qty * 1e-9:
            self._close(pos, now, reason)

    def _close(self, pos, now, reason):
        del self.positions[pos.product_id]
        pnl = pos.proceeds - pos.cost
        exit_value = sum(x["qty"] * x["price"] for x in pos.exits) / pos.initial_qty
        self.trades.append({
            "product_id": pos.product_id, "entry_time": pos.entry_time, "exit_time": _iso(now),
            "entry_price": pos.entry_price, "avg_exit_price": exit_value, "qty": pos.initial_qty,
            "pnl": pnl, "return_pct": pnl / pos.cost * 100, "r": pnl / (pos.risk_per_unit * pos.initial_qty),
            "bars": pos.bars, "exit_reason": reason, "entry_reason": pos.entry_reason,
        })
        if pnl < 0:
            self.cooldown[pos.product_id] = self.risk.cooldown_bars

    def exit_all(self, product_id, price, now, reason):
        pos = self.positions.get(product_id)
        if pos:
            self._sell(pos, pos.qty, price * (1 - self.risk.slippage), now, reason)

    def on_bar(self, product_id, now, o, h, l, c, atr_value=None, signal_exit=False):
        """Advance an open position by one base bar. Returns the exit reason if it closed."""
        pos = self.positions.get(product_id)
        if not pos:
            return None
        e, slip = self.exit_cfg, self.risk.slippage
        pos.bars += 1
        self.marks[product_id] = c

        # 1. stop
        if l <= pos.stop:
            kind = "trailing stop" if pos.stop > pos.initial_stop and pos.stop > pos.entry_price else (
                "breakeven stop" if pos.stop > pos.initial_stop else "stop loss")
            self._sell(pos, pos.qty, min(o, pos.stop) * (1 - slip), now, kind)
            return kind
        # 2. fixed target
        if e.fixed_tp_r:
            target = pos.entry_price + e.fixed_tp_r * pos.risk_per_unit
            if h >= target:
                self._sell(pos, pos.qty, max(o, target), now, f"take profit {e.fixed_tp_r:g}R")
                return f"take profit {e.fixed_tp_r:g}R"
        # 3. partial target
        if e.tp1_r and not pos.tp1_done:
            target = pos.entry_price + e.tp1_r * pos.risk_per_unit
            if h >= target:
                self._sell(pos, pos.initial_qty * e.tp1_fraction, max(o, target), now, f"partial take profit {e.tp1_r:g}R")
                pos.tp1_done = True
                if e.breakeven_after_tp1:
                    pos.stop = max(pos.stop, pos.entry_price * (1 + 2 * self.risk.fee_rate))
                if product_id not in self.positions:
                    return "partial take profit"
        # 4. breakeven / trailing
        pos.highest = max(pos.highest, h)
        pos.max_r = max(pos.max_r, pos.r_multiple(h))
        if e.breakeven_at_r and pos.max_r >= e.breakeven_at_r:
            pos.stop = max(pos.stop, pos.entry_price * (1 + 2 * self.risk.fee_rate))
        if e.trail_atr and pos.max_r >= e.trail_after_r:
            pos.stop = max(pos.stop, pos.highest - e.trail_atr * (atr_value or pos.atr))
        # 5. signal exit
        if e.signal_exit and signal_exit:
            self._sell(pos, pos.qty, c * (1 - slip), now, "EMA bearish cross")
            return "EMA bearish cross"
        # 6. time stop
        if e.time_stop_bars and pos.bars >= e.time_stop_bars and pos.max_r < e.time_stop_min_r:
            self._sell(pos, pos.qty, c * (1 - slip), now, "time stop")
            return "time stop"
        return None

    def tick_cooldowns(self):
        for k in list(self.cooldown):
            self.cooldown[k] -= 1
            if self.cooldown[k] <= 0:
                del self.cooldown[k]

    # ------------------------------------------------------------ persistence
    def to_dict(self):
        return {
            "cash": self.cash, "peak": self.peak, "day": self.day, "day_start_equity": self.day_start_equity,
            "halted": self.halted, "cooldown": self.cooldown, "marks": self.marks,
            "positions": {k: asdict(p) for k, p in self.positions.items()}, "trades": self.trades,
        }

    def load(self, d):
        self.cash, self.peak, self.day = d["cash"], d["peak"], d["day"]
        self.day_start_equity, self.halted = d["day_start_equity"], d["halted"]
        self.cooldown, self.marks, self.trades = d["cooldown"], d["marks"], d["trades"]
        self.positions = {k: Position(**p) for k, p in d["positions"].items()}


def stats(trades, start_equity, equity_curve=None):
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in trades if t["pnl"] <= 0)
    pnl = sum(t["pnl"] for t in trades)
    out = {
        "trades": n,
        "win_rate": len(wins) / n * 100 if n else 0.0,
        "pnl": pnl,
        "return_pct": pnl / start_equity * 100,
        "profit_factor": gross_win / gross_loss if gross_loss else float("inf") if gross_win else 0.0,
        "avg_r": sum(t["r"] for t in trades) / n if n else 0.0,
        "worst_trade_pct": min((t["return_pct"] for t in trades), default=0.0),
    }
    if equity_curve:
        peak, dd = equity_curve[0], 0.0
        for v in equity_curve:
            peak = max(peak, v)
            dd = max(dd, (peak - v) / peak)
        out["max_drawdown_pct"] = dd * 100
    return out


def _iso(t):
    if isinstance(t, str):
        return t
    if isinstance(t, (int, float)):
        t = datetime.fromtimestamp(t, timezone.utc)
    return t.isoformat()
