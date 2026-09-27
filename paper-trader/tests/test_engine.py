from datetime import datetime, timedelta, timezone

import pytest

from engine import ExitConfig, Portfolio, RiskConfig

T0 = datetime(2026, 9, 27, tzinfo=timezone.utc)
NO_COSTS = RiskConfig(fee_rate=0.0, slippage=0.0)


def pf(exits=None, risk=None):
    return Portfolio(risk or NO_COSTS, exits or ExitConfig(signal_exit=False))


def bar(p, pid, o, h, l, c, n=1, **kw):
    return p.on_bar(pid, T0 + timedelta(minutes=5 * n), o, h, l, c, **kw)


def test_position_size_risks_one_percent():
    p = pf(risk=RiskConfig(fee_rate=0, slippage=0, max_position_pct=1.0))
    pos, _ = p.open("X-USD", T0, 100.0, atr_value=1.0)       # stop 2 ATR = $2 below
    assert pos.stop == pytest.approx(98.0)
    assert pos.qty * 2.0 == pytest.approx(10.0)              # 1% of $1000
    assert p.cash == pytest.approx(1000 - pos.qty * 100)


def test_position_capped_at_max_position_pct():
    p = pf()
    pos, _ = p.open("X-USD", T0, 100.0, atr_value=0.01)      # tiny ATR -> min stop 1%
    assert pos.qty * 100 == pytest.approx(250.0)             # capped at 25% of equity


def test_stop_loss_exits_at_stop():
    p = pf()
    p.open("X-USD", T0, 100.0, 1.0)
    assert bar(p, "X-USD", 99.5, 99.6, 97.5, 98.2) == "stop loss"
    t = p.trades[-1]
    assert t["avg_exit_price"] == pytest.approx(98.0)
    assert t["r"] == pytest.approx(-1.0)


def test_gap_below_stop_fills_at_open():
    p = pf()
    p.open("X-USD", T0, 100.0, 1.0)
    bar(p, "X-USD", 95.0, 96.0, 94.0, 95.5)
    assert p.trades[-1]["avg_exit_price"] == pytest.approx(95.0)


def test_stop_checked_before_target_in_same_bar():
    p = pf(ExitConfig(signal_exit=False, fixed_tp_r=2.0, tp1_r=0))
    p.open("X-USD", T0, 100.0, 1.0)
    assert bar(p, "X-USD", 100, 105, 97, 101) == "stop loss"


def test_partial_take_profit_then_breakeven_stop():
    p = pf(ExitConfig(signal_exit=False, tp1_r=1.5, tp1_fraction=0.5, trail_atr=0))
    pos, _ = p.open("X-USD", T0, 100.0, 1.0)
    bar(p, "X-USD", 101, 103.5, 100.5, 103)                  # 1.5R = 103
    assert pos.tp1_done and pos.qty == pytest.approx(pos.initial_qty / 2)
    assert pos.stop == pytest.approx(100.0)                  # breakeven (no fees here)
    assert bar(p, "X-USD", 102, 102, 99.5, 100, n=2) == "breakeven stop"
    assert p.trades[-1]["pnl"] > 0                           # locked in the partial gain


def test_breakeven_covers_round_trip_fees():
    p = pf(ExitConfig(signal_exit=False, tp1_r=1.5, trail_atr=0), RiskConfig(fee_rate=0.005, slippage=0))
    pos, _ = p.open("X-USD", T0, 100.0, 1.0)
    bar(p, "X-USD", 101, 104, 100.5, 103)
    assert pos.stop == pytest.approx(101.0)


def test_trailing_stop_follows_highs_and_never_drops():
    p = pf(ExitConfig(signal_exit=False, tp1_r=0, trail_atr=3.0, trail_after_r=1.0))
    pos, _ = p.open("X-USD", T0, 100.0, 1.0)
    bar(p, "X-USD", 100, 101, 99, 100.5, atr_value=1.0)      # +0.5R: no trailing yet
    assert pos.stop == pytest.approx(98.0)
    bar(p, "X-USD", 101, 106, 100.5, 105, n=2, atr_value=1.0)
    assert pos.stop == pytest.approx(103.0)                  # 106 - 3 ATR
    bar(p, "X-USD", 105, 105.5, 103.5, 104, n=3, atr_value=1.0)
    assert pos.stop == pytest.approx(103.0)                  # lower high doesn't lower the stop
    assert bar(p, "X-USD", 104, 104, 102, 102.5, n=4, atr_value=1.0) == "trailing stop"
    assert p.trades[-1]["pnl"] > 0


def test_fixed_target():
    p = pf(ExitConfig(signal_exit=False, fixed_tp_r=2.0, tp1_r=0, trail_atr=0))
    p.open("X-USD", T0, 100.0, 1.0)
    assert bar(p, "X-USD", 101, 104.5, 100.5, 104) == "take profit 2R"
    assert p.trades[-1]["avg_exit_price"] == pytest.approx(104.0)


def test_signal_exit():
    p = pf(ExitConfig(signal_exit=True, tp1_r=0, trail_atr=0))
    p.open("X-USD", T0, 100.0, 1.0)
    assert bar(p, "X-USD", 100, 100.5, 99.5, 99.8, signal_exit=True) == "EMA bearish cross"


def test_time_stop_only_for_stalled_trades():
    cfg = ExitConfig(signal_exit=False, tp1_r=0, trail_atr=0, time_stop_bars=3, time_stop_min_r=0.5)
    p = pf(cfg)
    p.open("X-USD", T0, 100.0, 1.0)
    for n in (1, 2):
        assert bar(p, "X-USD", 100, 100.4, 99.8, 100, n=n) is None
    assert bar(p, "X-USD", 100, 100.4, 99.8, 100, n=3) == "time stop"

    p = pf(cfg)
    p.open("X-USD", T0, 100.0, 1.0)
    bar(p, "X-USD", 100, 102, 99.8, 101.5)                   # reached +1R -> keep it
    for n in (2, 3):
        assert bar(p, "X-USD", 101, 101.5, 100.5, 101, n=n) is None


def test_max_open_positions():
    p = pf(risk=RiskConfig(fee_rate=0, slippage=0, max_open=2))
    assert p.open("A-USD", T0, 10, 0.1)[0]
    assert p.open("B-USD", T0, 10, 0.1)[0]
    pos, why = p.open("C-USD", T0, 10, 0.1)
    assert pos is None and why == "max open positions"


def test_cooldown_after_loss():
    p = pf(risk=RiskConfig(fee_rate=0, slippage=0, cooldown_bars=2))
    p.open("X-USD", T0, 100.0, 1.0)
    bar(p, "X-USD", 99, 99, 97, 97.5)
    assert p.open("X-USD", T0, 100, 1.0)[1] == "cooling down after a loss"
    p.tick_cooldowns(), p.tick_cooldowns()
    assert p.open("X-USD", T0, 100, 1.0)[0]


def test_daily_loss_limit_and_kill_switch():
    p = pf(risk=RiskConfig(fee_rate=0, slippage=0, daily_loss_limit=0.03, max_drawdown=0.05))
    p.update_risk_state(T0)
    p.cash -= 40                                             # -4% today
    assert p.can_open("X-USD") == (False, "daily loss limit hit")
    p.update_risk_state(T0 + timedelta(days=1))              # new day resets the daily limit
    assert p.can_open("X-USD")[0]
    p.cash -= 20                                             # now -6% from peak
    p.update_risk_state(T0 + timedelta(days=1))
    assert p.halted and p.can_open("X-USD") == (False, "kill switch: max drawdown hit")


def test_state_round_trip():
    p = pf()
    p.open("X-USD", T0, 100.0, 1.0)
    q = pf()
    q.load(p.to_dict())
    assert q.positions["X-USD"].stop == p.positions["X-USD"].stop
    assert q.equity() == pytest.approx(p.equity())


def test_breakeven_at_r_without_partial_sale():
    p = pf(ExitConfig(signal_exit=False, tp1_r=0, trail_atr=0, fixed_tp_r=3.0, breakeven_at_r=1.5))
    pos, _ = p.open("X-USD", T0, 100.0, 1.0)
    bar(p, "X-USD", 101, 103.2, 100.5, 103)                  # reached 1.6R
    assert pos.qty == pos.initial_qty and pos.stop == pytest.approx(100.0)
    assert bar(p, "X-USD", 102, 102, 99.9, 100, n=2) == "breakeven stop"
