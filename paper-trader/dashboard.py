#!/usr/bin/env python3
"""Render the paper agent's state as a self-contained HTML dashboard.

    python3 dashboard.py --out dashboard.html

Reads state.json and equity.csv written by agent.py. The full agent state is
embedded in the page (<script id="agent-state">) so a fresh machine can
restore the paper account from a published dashboard with --restore.
"""

import argparse
import csv
import html
import json
import os
import re
import sys
from datetime import datetime, timezone

import coinbase_data as cd

CAT_ORDER = ("trend", "momentum", "volatility", "volume")


def esc(x):
    return html.escape(str(x), quote=True)


def fmt_px(x):
    if x is None:
        return "–"
    x = float(x)
    if x >= 1000:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:.4f}"
    return f"{x:.6g}"


def money(x, sign=False):
    return f"{'+' if sign and x >= 0 else '−' if x < 0 else ''}${abs(x):,.2f}"


def pct(x):
    return f"{'+' if x >= 0 else '−'}{abs(x):.2f}%"


def ago(iso, now):
    try:
        t = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    mins = int((now - t).total_seconds() // 60)
    if mins < 60:
        return f"{mins}m ago"
    if mins < 48 * 60:
        return f"{mins // 60}h {mins % 60}m ago"
    return f"{mins // 1440}d ago"


def short_time(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%b %d %H:%M UTC")
    except (TypeError, ValueError):
        return esc(iso)


def tone(x):
    return "gain" if x > 0 else "loss" if x < 0 else "flat"


# ------------------------------------------------------------------ pieces

def equity_chart(points, start_equity):
    """Inline SVG area chart of equity over time."""
    if len(points) < 2:
        return '<p class="muted">The equity curve appears after the second cycle.</p>'
    if len(points) > 400:
        step = len(points) / 400
        points = [points[int(i * step)] for i in range(400)] + [points[-1]]
    W, H, L, R, T, B = 720, 220, 56, 12, 14, 30
    ts = [p[0].timestamp() for p in points]
    vs = [p[1] for p in points]
    lo, hi = min(vs + [start_equity]), max(vs + [start_equity])
    pad = max((hi - lo) * 0.15, start_equity * 0.002)
    lo, hi = lo - pad, hi + pad
    t0, t1 = ts[0], ts[-1] if ts[-1] > ts[0] else ts[0] + 1

    def x(t):
        return L + (t - t0) / (t1 - t0) * (W - L - R)

    def y(v):
        return T + (hi - v) / (hi - lo) * (H - T - B)

    line = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in zip(ts, vs))
    area = f"{x(ts[0]):.1f},{H - B} {line} {x(ts[-1]):.1f},{H - B}"
    ticks = []
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        ticks.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                     f'<text class="axis" x="{L - 8}" y="{y(v) + 4:.1f}" text-anchor="end">${v:,.0f}</text>')
    for frac, anchor in ((0, "start"), (0.5, "middle"), (1, "end")):
        t = t0 + (t1 - t0) * frac
        label = datetime.fromtimestamp(t, timezone.utc).strftime("%b %d %H:%M")
        ticks.append(f'<text class="axis" x="{x(t):.1f}" y="{H - 8}" text-anchor="{anchor}">{label}</text>')
    base = f'<line class="baseline" x1="{L}" x2="{W - R}" y1="{y(start_equity):.1f}" y2="{y(start_equity):.1f}"/>' \
           f'<text class="axis" x="{W - R}" y="{y(start_equity) - 5:.1f}" text-anchor="end">start ${start_equity:,.0f}</text>'
    last_t, last_v = ts[-1], vs[-1]
    cls = tone(last_v - start_equity)
    return f'''<svg class="chart {cls}" viewBox="0 0 {W} {H}" role="img" aria-label="Equity over time, now ${last_v:,.2f}">
  {''.join(ticks)}{base}
  <polygon class="area" points="{area}"/>
  <polyline class="line" points="{line}"/>
  <circle class="dot" cx="{x(last_t):.1f}" cy="{y(last_v):.1f}" r="4"/>
</svg>'''


def r_ladder(stop, entry, now, target):
    """Horizontal scale from stop to target (or 3R) with entry and current price marked."""
    top = target or entry + 3 * (entry - stop)
    span = top - stop or 1

    def at(v):
        return max(0.0, min(100.0, (v - stop) / span * 100))

    risk = entry - stop
    r_now = (now - entry) / risk if risk else 0
    return f'''<div class="ladder" aria-label="Price {fmt_px(now)} is {r_now:+.2f}R between stop {fmt_px(stop)} and target {fmt_px(top)}">
  <div class="track"><div class="fill {tone(r_now)}" style="left:{min(at(entry), at(now)):.1f}%;width:{abs(at(now) - at(entry)):.1f}%"></div>
    <span class="tick entry" style="left:{at(entry):.1f}%"></span><span class="tick now {tone(r_now)}" style="left:{at(now):.1f}%"></span></div>
  <div class="ladder-labels"><span>Stop {fmt_px(stop)}<small>−1R</small></span><span class="mid">Entry {fmt_px(entry)}</span><span class="end">Target {fmt_px(top)}<small>+{(top - entry) / risk if risk else 3:.0f}R</small></span></div>
</div>'''


def signal_list(signals, fallback=""):
    if not signals:
        return f'<p class="muted">{esc(fallback) or "No signal detail recorded."}</p>'
    items = []
    for s in sorted(signals, key=lambda s: CAT_ORDER.index(s["category"]) if s["category"] in CAT_ORDER else 9):
        items.append(f'<li><span class="chip {esc(s["category"])}">{esc(s["category"])}</span>'
                     f'<div><b>{esc(s["name"])}</b><span class="why">{esc(s["reason"])}</span></div></li>')
    return f'<ul class="signals">{"".join(items)}</ul>'


def explain(scan_row):
    """Scan reason, naming the missing categories for rows logged before reasons did."""
    reason = scan_row.get("reason", "")
    if reason == "no strong setup":
        cats = scan_row.get("categories") or {}
        missing = [c for c in ("trend", "momentum", "volume") if not cats.get(c)]
        if missing:
            reason += ": missing " + " and ".join(missing) + " signal" + ("s" if len(missing) > 1 else "")
    return reason


def cat_chips(cats):
    out = []
    for c in CAT_ORDER:
        n = (cats or {}).get(c, 0)
        out.append(f'<span class="mini {c}{" on" if n else ""}" title="{c}: {n}">{c[0].upper()}{n}</span>')
    return "".join(out)


# ------------------------------------------------------------------ page

def render(state, equity_rows, now, live_prices=None):
    pf = state["portfolio"]
    risk = state.get("risk", {})
    exit_cfg = state.get("exit_cfg", {})
    cfg = state.get("config", {})
    start = float(risk.get("starting_equity", 1000))
    marks = dict(pf.get("marks", {}))
    marks.update(live_prices or {})
    positions = pf["positions"]
    trades = pf["trades"]
    open_value = sum(p["qty"] * marks.get(k, p["entry_price"]) for k, p in positions.items())
    equity = pf["cash"] + open_value
    total_pnl = equity - start
    realized = sum(t["pnl"] for t in trades)
    unreal = sum(p["qty"] * marks.get(k, p["entry_price"]) + p["proceeds"] - p["cost"] for k, p in positions.items())
    wins = [t for t in trades if t["pnl"] > 0]
    gross_w = sum(t["pnl"] for t in wins)
    gross_l = -sum(t["pnl"] for t in trades if t["pnl"] <= 0)
    pf_txt = f"{gross_w / gross_l:.2f}" if gross_l else ("∞" if gross_w else "–")
    open_risk = sum(max(0.0, (p["entry_price"] - p["stop"]) * p["qty"]) for p in positions.values())
    peak = max([start] + [float(r["equity"]) for r in equity_rows])
    dd = max(0.0, (peak - equity) / peak * 100) if peak else 0
    halted = pf.get("halted")
    day_limit = pf.get("day_start_equity", start) * (1 - risk.get("daily_loss_limit", 0.03))
    day_blocked = equity < day_limit
    updated = state.get("updated") or now.isoformat()

    status = ("halted", "Kill switch on: trading stopped after a 15% drawdown") if halted else \
             ("warn", "Daily loss limit reached: no new trades until 00:00 UTC") if day_blocked else \
             ("ok", "Trading normally")

    points = []
    for r in equity_rows:
        try:
            points.append((datetime.fromisoformat(r["time"]), float(r["equity"])))
        except (KeyError, ValueError):
            pass

    # ---- open positions
    pos_html = []
    for pid, p in sorted(positions.items(), key=lambda kv: kv[1]["entry_time"]):
        now_px = marks.get(pid, p["entry_price"])
        value = p["qty"] * now_px
        pnl = value + p["proceeds"] - p["cost"]
        risk_u = p["risk_per_unit"]
        r_now = (now_px - p["entry_price"]) / risk_u if risk_u else 0
        target = p.get("target") or 0
        stop_kind = "initial stop" if p["stop"] <= p["initial_stop"] + 1e-12 else \
                    "breakeven stop" if p["stop"] <= p["entry_price"] * 1.02 else "trailing stop"
        plan = [
            f'<li><b>Stop loss at {fmt_px(p["stop"])}</b> ({stop_kind}, {pct((p["stop"] / p["entry_price"] - 1) * 100)} from entry). '
            f'If any 5-minute candle trades there, the whole position is sold. Maximum loss {money(-(p["entry_price"] - p["stop"]) * p["qty"])} plus fees.</li>',
        ]
        if target:
            plan.append(f'<li><b>Take profit at {fmt_px(target)}</b> ({pct((target / p["entry_price"] - 1) * 100)}). '
                        f'That is {exit_cfg.get("fixed_tp_r", 3):g}× the risk, so one win pays for {exit_cfg.get("fixed_tp_r", 3):g} losses.</li>')
        if exit_cfg.get("time_stop_bars"):
            plan.append(f'<li><b>Time stop</b> if it hasn\'t reached +{exit_cfg.get("time_stop_min_r", 0.5):g}R '
                        f'after {exit_cfg["time_stop_bars"] * 5 // 60} hours.</li>')
        plan.append('<li>No breakeven or trailing stop. In testing, those were shaken out by normal pullbacks '
                    'and lost money.</li>')
        pos_html.append(f'''
<article class="position">
  <header>
    <div><h3>{esc(pid.replace("-USD", ""))}<span class="pair">/USD</span></h3>
      <p class="muted">Bought {short_time(p["entry_time"])} · {ago(p["entry_time"], now)} · {money(p["cost"])} position</p></div>
    <div class="pnl {tone(pnl)}"><span class="big">{money(pnl, True)}</span><span>{pct(pnl / p["cost"] * 100)} · {r_now:+.2f}R</span></div>
  </header>
  {r_ladder(p["initial_stop"], p["entry_price"], now_px, target)}
  <div class="cols">
    <section><h4>Why it was bought</h4>{signal_list(p.get("entry_signals"), p.get("entry_reason"))}</section>
    <section><h4>Exit plan</h4><ul class="plan">{"".join(plan)}</ul></section>
  </div>
</article>''')
    if not pos_html:
        pos_html.append('<p class="empty">No open positions. The agent is waiting for a strong setup.</p>')

    # ---- closed trades
    trade_html = []
    for t in reversed(trades[-25:]):
        trade_html.append(f'''
<article class="trade {tone(t["pnl"])}">
  <header>
    <h3>{esc(t["product_id"].replace("-USD", ""))}</h3>
    <span class="pill {tone(t["pnl"])}">{esc(t["exit_reason"])}</span>
    <span class="pnl {tone(t["pnl"])}">{money(t["pnl"], True)} · {pct(t["return_pct"])} · {t["r"]:+.2f}R</span>
  </header>
  <p class="muted">{short_time(t["entry_time"])} → {short_time(t["exit_time"])} · bought {fmt_px(t["entry_price"])}, sold avg {fmt_px(t["avg_exit_price"])}</p>
  <div class="cols">
    <section><h4>Why it was bought</h4>{signal_list(t.get("entry_signals"), t.get("entry_reason"))}</section>
    <section><h4>Why it was sold</h4><p class="reason">{esc(t.get("exit_detail") or t["exit_reason"])}</p></section>
  </div>
</article>''')
    if not trade_html:
        trade_html.append('<p class="empty">No closed trades yet. Each exit will appear here with the rule that triggered it.</p>')

    # ---- watchlist scan
    scan = state.get("last_scan", {})
    order = {"buy": 0, "holding": 1, "blocked": 2, "pass": 3}
    rows = []
    for pid, s in sorted(scan.items(), key=lambda kv: (order.get(kv[1]["decision"], 9), -kv[1]["score"])):
        fired = ", ".join(f["name"] for f in s.get("fired", [])) or "none"
        rows.append(f'''<tr class="{esc(s["decision"])}">
  <th scope="row">{esc(pid.replace("-USD", ""))}</th>
  <td class="num">{s["score"]}</td>
  <td class="chips">{cat_chips(s.get("categories"))}</td>
  <td><span class="pill {esc(s["decision"])}">{esc({"buy": "bought", "holding": "holding", "blocked": "blocked", "pass": "passed"}.get(s["decision"], s["decision"]))}</span></td>
  <td class="why">{esc(explain(s))}<span class="fired">Signals: {esc(fired)}</span></td>
</tr>''')
    scan_html = f'''<div class="table-wrap"><table>
<thead><tr><th scope="col">Coin</th><th scope="col" class="num">Score</th><th scope="col">Categories</th><th scope="col">Decision</th><th scope="col">Reason</th></tr></thead>
<tbody>{"".join(rows) or '<tr><td colspan="5" class="muted">No coins evaluated yet.</td></tr>'}</tbody></table></div>'''

    # ---- decision log
    ev_html = []
    for e in reversed(state.get("events", [])[-40:]):
        kind = e["kind"]
        extra = ""
        if kind == "exit":
            extra = f' <span class="pnl {tone(e.get("pnl", 0))}">{money(e.get("pnl", 0), True)} ({pct(e.get("return_pct", 0))})</span>'
        ev_html.append(f'''<li class="{esc(kind)}"><time>{short_time(e["time"])}</time>
  <div><b>{esc({"entry": "Bought", "exit": "Sold", "partial": "Partial sell", "skip": "Skipped"}.get(kind, kind))} {esc(e["product_id"].replace("-USD", ""))}</b>{extra}
  <p>{esc(e["message"])}</p></div></li>''')
    log_html = f'<ol class="log">{"".join(ev_html)}</ol>' if ev_html else '<p class="empty">No decisions logged yet.</p>'

    win_rate = f"{len(wins) / len(trades) * 100:.0f}%" if trades else "–"
    tf = cfg.get("timeframe", "1h")
    state_json = json.dumps(state, separators=(",", ":")).replace("</", "<\\/")
    eq_json = json.dumps(equity_rows[-2000:], separators=(",", ":")).replace("</", "<\\/")

    return f'''<title>Paper Desk</title>
<meta name="description" content="Autonomous Coinbase paper-trading agent: positions, decisions and reasoning.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root {{
  --bg: #eef1f4; --surface: #ffffff; --sunk: #f5f7f9; --ink: #16202a; --muted: #5a6776; --line: #d9dfe6;
  --accent: #3547c4; --accent-soft: #e6e9fb;
  --gain: #11795a; --gain-soft: #dcf2e9; --loss: #b9363a; --loss-soft: #f9e1e1; --warn: #9a6512; --warn-soft: #f8ecd6;
  --trend: #3547c4; --momentum: #8a3fb8; --volatility: #9a6512; --volume: #11795a;
  --sans: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --cond: "IBM Plex Sans Condensed", "Arial Narrow", system-ui, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
    --bg: #0d1217; --surface: #141b22; --sunk: #10161c; --ink: #e4e9ef; --muted: #8e9aa8; --line: #26313c;
    --accent: #8f9dff; --accent-soft: #1d2447;
    --gain: #45c795; --gain-soft: #12302a; --loss: #f07a7c; --loss-soft: #3a1d20; --warn: #e3ae55; --warn-soft: #34281a;
    --trend: #8f9dff; --momentum: #cf95f0; --volatility: #e3ae55; --volume: #45c795;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --bg: #0d1217; --surface: #141b22; --sunk: #10161c; --ink: #e4e9ef; --muted: #8e9aa8; --line: #26313c;
  --accent: #8f9dff; --accent-soft: #1d2447;
  --gain: #45c795; --gain-soft: #12302a; --loss: #f07a7c; --loss-soft: #3a1d20; --warn: #e3ae55; --warn-soft: #34281a;
  --trend: #8f9dff; --momentum: #cf95f0; --volatility: #e3ae55; --volume: #45c795;
}}
* {{ box-sizing: border-box; }}
body {{ background: var(--bg); color: var(--ink); font: 15px/1.55 var(--sans); }}
.wrap {{ max-width: 1120px; margin: 0 auto; padding: 28px 20px 64px; display: grid; gap: 28px; }}
h1, h2, h3, h4 {{ font-family: var(--cond); margin: 0; text-wrap: balance; }}
h2 {{ font-size: 13px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); font-weight: 600; }}
h3 {{ font-size: 22px; font-weight: 700; }}
h4 {{ font-size: 12px; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); font-weight: 600; margin-bottom: 8px; }}
p {{ margin: 0; }}
.muted {{ color: var(--muted); font-size: 13px; }}
.num, .big, .kpi b, time, .ladder-labels, .pnl, td.num {{ font-family: var(--mono); font-variant-numeric: tabular-nums; }}
.gain {{ color: var(--gain); }} .loss {{ color: var(--loss); }} .flat {{ color: var(--muted); }}

.masthead {{ display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 16px; }}
.masthead h1 {{ font-size: clamp(30px, 5vw, 44px); font-weight: 700; letter-spacing: -.01em; line-height: 1; }}
.masthead h1 span {{ color: var(--accent); }}
.masthead .sub {{ color: var(--muted); margin-top: 8px; max-width: 60ch; }}
.status {{ display: flex; flex-direction: column; align-items: flex-end; gap: 6px; font-size: 13px; color: var(--muted); }}
.state {{ display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 999px; font-weight: 600; font-size: 13px; }}
.state::before {{ content: ""; width: 8px; height: 8px; border-radius: 50%; background: currentColor; }}
.state.ok {{ background: var(--gain-soft); color: var(--gain); }}
.state.warn {{ background: var(--warn-soft); color: var(--warn); }}
.state.halted {{ background: var(--loss-soft); color: var(--loss); }}
.paper {{ font-family: var(--cond); font-weight: 600; letter-spacing: .08em; text-transform: uppercase; font-size: 12px;
  border: 1.5px solid var(--accent); color: var(--accent); padding: 2px 8px; border-radius: 4px; }}

.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1px; background: var(--line);
  border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }}
.kpi {{ background: var(--surface); padding: 16px 18px; display: grid; gap: 4px; }}
.kpi span {{ font-size: 12px; color: var(--muted); letter-spacing: .04em; }}
.kpi b {{ font-size: 24px; font-weight: 500; }}
.kpi small {{ color: var(--muted); font-size: 12px; }}

.panel {{ background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 18px 20px; display: grid; gap: 14px; }}
.panel-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }}
.chart {{ width: 100%; height: auto; display: block; }}
.chart .grid {{ stroke: var(--line); stroke-width: 1; }}
.chart .baseline {{ stroke: var(--muted); stroke-dasharray: 4 4; stroke-width: 1; }}
.chart .axis {{ fill: var(--muted); font: 11px var(--mono); }}
.chart .line {{ fill: none; stroke: var(--accent); stroke-width: 2; stroke-linejoin: round; }}
.chart .area {{ fill: var(--accent-soft); opacity: .8; }}
.chart .dot {{ fill: var(--accent); stroke: var(--surface); stroke-width: 2; }}

.section {{ display: grid; gap: 12px; }}
.position, .trade {{ background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 18px 20px; display: grid; gap: 16px; }}
.position > header, .trade > header {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: start; gap: 12px; }}
.trade > header {{ align-items: center; justify-content: flex-start; }}
.trade > header .pnl {{ margin-left: auto; }}
.pair {{ color: var(--muted); font-weight: 500; font-size: 16px; }}
.position .pnl {{ text-align: right; display: grid; font-size: 13px; }}
.position .pnl .big {{ font-size: 22px; }}
.trade {{ border-left: 4px solid var(--line); }}
.trade.gain {{ border-left-color: var(--gain); }} .trade.loss {{ border-left-color: var(--loss); }}
.trade.gain, .trade.loss {{ color: var(--ink); }}

.ladder {{ display: grid; gap: 6px; }}
.track {{ position: relative; height: 10px; border-radius: 5px;
  background: linear-gradient(90deg, var(--loss-soft) 0 25%, var(--sunk) 25% 100%); border: 1px solid var(--line); }}
.track .fill {{ position: absolute; top: 0; bottom: 0; border-radius: 5px; }}
.track .fill.gain {{ background: var(--gain); opacity: .45; }} .track .fill.loss {{ background: var(--loss); opacity: .45; }}
.track .tick {{ position: absolute; top: -5px; width: 2px; height: 18px; transform: translateX(-1px); background: var(--muted); }}
.track .tick.now {{ width: 12px; height: 12px; top: -2px; border-radius: 50%; transform: translateX(-6px); background: currentColor;
  box-shadow: 0 0 0 2px var(--surface); }}
.ladder-labels {{ display: flex; justify-content: space-between; gap: 8px; font-size: 12px; color: var(--muted); }}
.ladder-labels small {{ margin-left: 6px; opacity: .8; }}

.cols {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; }}
.signals, .plan {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }}
.signals li {{ display: grid; grid-template-columns: 92px 1fr; gap: 10px; align-items: start; }}
.signals b {{ display: block; font-weight: 600; font-size: 14px; }}
.signals .why {{ display: block; color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }}
.plan li {{ padding-left: 14px; border-left: 2px solid var(--line); font-size: 14px; }}
.reason {{ font-size: 14px; max-width: 65ch; }}
.chip {{ font: 600 11px var(--cond); letter-spacing: .08em; text-transform: uppercase; padding: 3px 8px; border-radius: 4px;
  text-align: center; background: var(--sunk); border: 1px solid var(--line); }}
.chip.trend {{ color: var(--trend); }} .chip.momentum {{ color: var(--momentum); }}
.chip.volatility {{ color: var(--volatility); }} .chip.volume {{ color: var(--volume); }}

.pill {{ display: inline-block; font: 600 12px var(--cond); letter-spacing: .04em; padding: 2px 9px; border-radius: 999px;
  background: var(--sunk); color: var(--muted); border: 1px solid var(--line); white-space: nowrap; }}
.pill.gain, .pill.buy {{ background: var(--gain-soft); color: var(--gain); border-color: transparent; }}
.pill.loss {{ background: var(--loss-soft); color: var(--loss); border-color: transparent; }}
.pill.holding {{ background: var(--accent-soft); color: var(--accent); border-color: transparent; }}
.pill.blocked {{ background: var(--warn-soft); color: var(--warn); border-color: transparent; }}

.table-wrap {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; min-width: 640px; }}
th, td {{ text-align: left; padding: 10px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
thead th {{ font: 600 12px var(--cond); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }}
tbody th {{ font-family: var(--cond); font-size: 16px; }}
td.num {{ text-align: right; }} th.num {{ text-align: right; }}
td.why {{ color: var(--ink); max-width: 46ch; }}
td.why .fired {{ display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }}
tr.pass td, tr.pass th {{ color: var(--muted); }}
.chips {{ white-space: nowrap; }}
.mini {{ display: inline-block; font: 500 11px var(--mono); padding: 1px 5px; margin-right: 3px; border-radius: 3px;
  color: var(--muted); background: var(--sunk); border: 1px solid var(--line); }}
.mini.on.trend {{ color: var(--trend); border-color: currentColor; }} .mini.on.momentum {{ color: var(--momentum); border-color: currentColor; }}
.mini.on.volatility {{ color: var(--volatility); border-color: currentColor; }} .mini.on.volume {{ color: var(--volume); border-color: currentColor; }}

.log {{ list-style: none; margin: 0; padding: 0; display: grid; }}
.log li {{ display: grid; grid-template-columns: 130px 1fr; gap: 14px; padding: 12px 0; border-bottom: 1px solid var(--line); }}
.log li:last-child {{ border-bottom: 0; }}
.log time {{ font-size: 12px; color: var(--muted); padding-top: 2px; }}
.log li > div {{ padding-left: 12px; border-left: 3px solid var(--line); }}
.log li.entry > div {{ border-left-color: var(--accent); }} .log li.exit > div {{ border-left-color: var(--gain); }}
.log li.skip > div {{ border-left-color: var(--warn); }}
.log p {{ color: var(--muted); font-size: 14px; margin-top: 2px; max-width: 75ch; }}
.log .pnl {{ font-size: 13px; margin-left: 6px; }}

.rules {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px 24px; font-size: 14px; }}
.rules div {{ display: grid; gap: 2px; }}
.rules span {{ color: var(--muted); font-size: 12px; }}
.empty {{ color: var(--muted); padding: 18px 20px; border: 1px dashed var(--line); border-radius: 10px; background: var(--surface); }}
footer {{ color: var(--muted); font-size: 12px; max-width: 80ch; }}
@media (max-width: 560px) {{
  .log li {{ grid-template-columns: 1fr; gap: 4px; }}
  .signals li {{ grid-template-columns: 1fr; gap: 4px; }}
  .signals .chip {{ justify-self: start; }}
  .status {{ align-items: flex-start; }}
}}
</style>

<div class="wrap">
  <header class="masthead">
    <div>
      <h1>Paper <span>Desk</span></h1>
      <p class="sub">An autonomous agent trading a simulated ${start:,.0f} account on live Coinbase prices. It never places real orders.</p>
    </div>
    <div class="status">
      <span class="paper">Paper account</span>
      <span class="state {status[0]}">{esc(status[1])}</span>
      <span>Updated {short_time(updated)} · refreshes hourly</span>
    </div>
  </header>

  <section class="kpis" aria-label="Account summary">
    <div class="kpi"><span>Equity</span><b>{money(equity)}</b><small class="{tone(total_pnl)}">{money(total_pnl, True)} · {pct(total_pnl / start * 100)}</small></div>
    <div class="kpi"><span>Realized P&amp;L</span><b class="{tone(realized)}">{money(realized, True)}</b><small>{len(trades)} closed trade{"s" if len(trades) != 1 else ""}</small></div>
    <div class="kpi"><span>Open P&amp;L</span><b class="{tone(unreal)}">{money(unreal, True)}</b><small>{len(positions)} of {risk.get("max_open", 3)} slots used</small></div>
    <div class="kpi"><span>Win rate</span><b>{win_rate}</b><small>profit factor {pf_txt}</small></div>
    <div class="kpi"><span>Capital at risk</span><b>{money(open_risk)}</b><small>if every stop is hit</small></div>
    <div class="kpi"><span>Drawdown</span><b class="{"loss" if dd > 5 else ""}">{dd:.2f}%</b><small>kill switch at {risk.get("max_drawdown", 0.15) * 100:.0f}%</small></div>
  </section>

  <section class="panel" aria-labelledby="eq-h">
    <div class="panel-head"><h2 id="eq-h">Equity</h2><span class="muted">cash {money(pf["cash"])} · in positions {money(open_value)}</span></div>
    {equity_chart(points, start)}
  </section>

  <section class="section" aria-labelledby="open-h">
    <h2 id="open-h">Open positions</h2>
    {"".join(pos_html)}
  </section>

  <section class="section" aria-labelledby="closed-h">
    <h2 id="closed-h">Closed trades</h2>
    {"".join(trade_html)}
  </section>

  <section class="panel" aria-labelledby="scan-h">
    <div class="panel-head"><h2 id="scan-h">Latest scan</h2><span class="muted">Top {len(state.get("universe", [])) or 25} USD pairs by volume · {esc(tf)} candles · buys need trend + momentum + volume, 3+ independent signals, price above a rising SMA200</span></div>
    {scan_html}
  </section>

  <section class="panel" aria-labelledby="log-h">
    <h2 id="log-h">Decision log</h2>
    {log_html}
  </section>

  <section class="panel" aria-labelledby="rules-h">
    <h2 id="rules-h">Rules the agent follows</h2>
    <div class="rules">
      <div><span>Signals</span>{esc(tf)} candles, checked every 5 minutes</div>
      <div><span>Stop loss</span>{exit_cfg.get("stop_atr", 2):g}× ATR below entry (1–5% of price)</div>
      <div><span>Take profit</span>Everything at {exit_cfg.get("fixed_tp_r", 3):g}R, i.e. {exit_cfg.get("fixed_tp_r", 3):g}× the risk</div>
      <div><span>Risk per trade</span>{risk.get("risk_per_trade", 0.01) * 100:g}% of equity</div>
      <div><span>Position size cap</span>{risk.get("max_position_pct", 0.25) * 100:g}% of equity, {risk.get("max_open", 3)} positions max</div>
      <div><span>Daily loss limit</span>−{risk.get("daily_loss_limit", 0.03) * 100:g}%: no new trades that day</div>
      <div><span>Kill switch</span>−{risk.get("max_drawdown", 0.15) * 100:g}% from peak: all trading stops</div>
      <div><span>Simulated costs</span>{risk.get("fee_rate", 0.005) * 100:g}% fee + {risk.get("slippage", 0.0005) * 100:g}% slippage per side</div>
    </div>
  </section>

  <footer>Paper trading only. Prices from Coinbase's public market data. The exit rules were chosen from a 30-day backtest
  (+14.4% at 0.5% fees, positive in both halves). A buy-and-hold of the same coins made +55% over that strong month,
  and past results don't predict future ones.</footer>
</div>
<script type="application/json" id="agent-state">{state_json}</script>
<script type="application/json" id="equity-log">{eq_json}</script>
'''


def restore(html_path, state_path, equity_path):
    """Recreate state.json / equity.csv from a previously published dashboard."""
    text = open(html_path, encoding="utf-8").read()
    st = re.search(r'<script type="application/json" id="agent-state">(.*?)</script>', text, re.S)
    eq = re.search(r'<script type="application/json" id="equity-log">(.*?)</script>', text, re.S)
    if not st:
        sys.exit("No embedded agent state found in " + html_path)
    state = json.loads(st.group(1).replace("<\\/", "</"))
    with open(state_path, "w") as f:
        json.dump(state, f, indent=1)
    rows = json.loads(eq.group(1).replace("<\\/", "</")) if eq else []
    if rows:
        with open(equity_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    print(f"Restored {state_path} ({len(state['portfolio']['positions'])} open, "
          f"{len(state['portfolio']['trades'])} closed) and {len(rows)} equity rows")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default="state.json")
    ap.add_argument("--equity-log", default="equity.csv")
    ap.add_argument("--out", default="dashboard.html")
    ap.add_argument("--restore", metavar="DASHBOARD_HTML", help="rebuild state.json/equity.csv from a saved dashboard")
    ap.add_argument("--no-live", action="store_true", help="don't refresh prices of open positions")
    args = ap.parse_args()

    if args.restore:
        restore(args.restore, args.state, args.equity_log)
        return
    with open(args.state) as f:
        state = json.load(f)
    rows = []
    if os.path.exists(args.equity_log):
        with open(args.equity_log, newline="") as f:
            rows = list(csv.DictReader(f))
    live = {}
    if not args.no_live:
        for pid in state["portfolio"]["positions"]:
            px = cd.last_price(pid)
            if px:
                live[pid] = px
    page = render(state, rows, datetime.now(timezone.utc), live)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Wrote {args.out} ({len(page) // 1024} KB)")


if __name__ == "__main__":
    main()
