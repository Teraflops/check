#!/usr/bin/env python3
"""Coinbase volume-surge scanner.

Every interval (default 60s) this pulls 1-minute candles for every liquid
Coinbase spot pair in the chosen quote currency and flags coins where trading
volume is suddenly being added compared with their own recent baseline.

Uses only Coinbase's public market-data endpoints, so no API key is needed,
and only the Python standard library.
"""

import argparse
import csv
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

PRODUCTS_URL = "https://api.coinbase.com/api/v3/brokerage/market/products?product_type=SPOT&limit=1000"
# An explicit start/end window per scan also avoids stale, cached responses.
CANDLES_URL = "https://api.exchange.coinbase.com/products/{pid}/candles?granularity=60&start={start}&end={end}"
USER_AGENT = "volume-scanner/1.0"


class RateLimiter:
    """Spaces requests so we stay under Coinbase's public rate limit."""

    def __init__(self, per_second):
        self.gap = 1.0 / per_second
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            delay = self.next_at - now
            self.next_at = max(now, self.next_at) + self.gap
        if delay > 0:
            time.sleep(delay)


def http_json(url, limiter=None, retries=3):
    for attempt in range(retries):
        if limiter:
            limiter.wait()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            if e.code in (400, 404):
                return None
            time.sleep(1 + attempt)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(1 + attempt)
    return None


def load_universe(quote, min_24h_usd):
    """Online spot pairs in `quote` whose 24h notional volume is at least min_24h_usd."""
    data = http_json(PRODUCTS_URL)
    if not data:
        return []
    out = []
    for p in data.get("products", []):
        if p.get("quote_currency_id") != quote or p.get("status") != "online":
            continue
        if p.get("trading_disabled") or p.get("is_disabled"):
            continue
        try:
            price = float(p["price"])
            notional = price * float(p["volume_24h"])
        except (KeyError, TypeError, ValueError):
            continue
        if notional >= min_24h_usd:
            out.append({
                "product_id": p["product_id"],
                "change_24h": float(p.get("price_percentage_change_24h") or 0),
                "volume_24h_usd": notional,
            })
    return out


@dataclass
class Signal:
    product_id: str
    price: float
    ratio_1m: float        # last closed minute vs baseline minute
    ratio_5m: float        # last 5 closed minutes vs 5 baseline minutes
    usd_5m: float          # notional traded in the last 5 minutes
    buy_share_5m: float    # share of 5m volume traded in up-candles (0-1)
    price_change_5m: float # % change over the last 5 minutes
    change_24h: float
    score: float


def analyze(candles, now_minute, recent=5, baseline=60):
    """Compute volume-surge metrics from raw exchange candles.

    `candles` rows are [time, low, high, open, close, volume]. Minutes with no
    trades are missing from the API response, so they are filled with zero
    volume. The still-forming current minute is ignored.
    Returns a dict of metrics, or None when there is not enough history.
    """
    by_min = {int(c[0]): c for c in candles}
    closed_end = now_minute - 60  # start time of the last fully closed minute
    span = recent + baseline
    minutes = [closed_end - 60 * i for i in range(span)][::-1]
    if sum(1 for m in minutes if m in by_min) < 10:
        return None

    vols, rows = [], []
    last_close = None
    for m in minutes:
        c = by_min.get(m)
        if c:
            last_close = c[4]
            vols.append(float(c[5]))
            rows.append(c)
        else:
            vols.append(0.0)
            rows.append(None)
    if last_close is None:
        return None

    base_vols = vols[:baseline]
    recent_vols = vols[baseline:]
    # Median resists earlier spikes; the mean floor keeps quiet coins from dividing by ~0.
    base = max(statistics.median(base_vols), statistics.fmean(base_vols) * 0.5, 1e-12)

    recent_rows = [r for r in rows[baseline:] if r]
    up_vol = sum(float(r[5]) for r in recent_rows if r[4] >= r[3])
    tot_vol = sum(float(r[5]) for r in recent_rows)
    first_open = recent_rows[0][3] if recent_rows else last_close
    usd_5m = sum(float(r[5]) * float(r[4]) for r in recent_rows)

    return {
        "price": float(last_close),
        "ratio_1m": recent_vols[-1] / base,
        "ratio_5m": sum(recent_vols) / (base * recent),
        "usd_5m": usd_5m,
        "buy_share_5m": up_vol / tot_vol if tot_vol else 0.0,
        "price_change_5m": (last_close / first_open - 1) * 100 if first_open else 0.0,
    }


def score(m):
    """Rank surges: volume multiple, weighted toward buyer-led, rising moves."""
    direction = 0.5 + m["buy_share_5m"]            # 0.5 (all selling) .. 1.5 (all buying)
    momentum = 1 + max(min(m["price_change_5m"], 10), -10) / 20
    return m["ratio_5m"] * direction * momentum


def scan(universe, limiter, workers):
    now_minute = int(time.time()) // 60 * 60
    start = now_minute - 70 * 60
    end = now_minute + 60

    def one(p):
        candles = http_json(CANDLES_URL.format(pid=p["product_id"], start=start, end=end), limiter)
        if not candles:
            return None
        m = analyze(candles, now_minute)
        if not m:
            return None
        return Signal(product_id=p["product_id"], change_24h=p["change_24h"], score=score(m), **m)

    with ThreadPoolExecutor(workers) as ex:
        return [s for s in ex.map(one, universe) if s]


def fmt_usd(x):
    if x >= 1e6:
        return f"${x / 1e6:.2f}M"
    if x >= 1e3:
        return f"${x / 1e3:.1f}k"
    return f"${x:.0f}"


def print_table(signals, hits, top, stamp):
    print(f"\n=== {stamp}  scanned {len(signals)} pairs, {len(hits)} surging ===")
    rows = hits[:top] if hits else sorted(signals, key=lambda s: -s.ratio_5m)[:min(top, 5)]
    if not hits:
        print("No surges this minute. Highest 5m volume multiples:")
    print(f"{'PAIR':<14}{'5m x':>7}{'1m x':>7}{'5m $vol':>10}{'buy%':>6}{'5m %':>8}{'24h %':>8}  price")
    for s in rows:
        print(f"{s.product_id:<14}{s.ratio_5m:>7.1f}{s.ratio_1m:>7.1f}{fmt_usd(s.usd_5m):>10}"
              f"{s.buy_share_5m * 100:>6.0f}{s.price_change_5m:>+8.2f}{s.change_24h:>+8.2f}  {s.price:g}")


def append_alerts(path, stamp, alerts):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time_utc"] + list(asdict(alerts[0]).keys()))
        for s in alerts:
            w.writerow([stamp] + [round(v, 6) if isinstance(v, float) else v for v in asdict(s).values()])


def main():
    ap = argparse.ArgumentParser(description="Flag Coinbase coins where volume is surging, every minute.")
    ap.add_argument("--quote", default="USD", help="quote currency to scan (default USD)")
    ap.add_argument("--interval", type=int, default=60, help="seconds between scans (default 60)")
    ap.add_argument("--min-24h-usd", type=float, default=250_000, help="skip pairs with less 24h notional volume")
    ap.add_argument("--ratio", type=float, default=3.0, help="5m volume multiple vs baseline to flag (default 3)")
    ap.add_argument("--min-usd-5m", type=float, default=10_000, help="minimum notional in the last 5m to flag")
    ap.add_argument("--min-buy-share", type=float, default=0.0, help="only flag when this share of 5m volume is buying (0-1)")
    ap.add_argument("--cooldown", type=int, default=10, help="minutes before re-alerting the same pair")
    ap.add_argument("--top", type=int, default=15, help="rows to print per scan")
    ap.add_argument("--alerts", default="alerts.csv", help="CSV file that alerts are appended to")
    ap.add_argument("--rps", type=float, default=8, help="max API requests per second")
    ap.add_argument("--once", action="store_true", help="run a single scan and exit")
    args = ap.parse_args()

    limiter = RateLimiter(args.rps)
    universe, universe_at = [], 0.0
    last_alert = {}

    while True:
        started = time.time()
        if not universe or started - universe_at > 900:
            fresh = load_universe(args.quote, args.min_24h_usd)
            if fresh:
                universe, universe_at = fresh, started
            if not universe:
                print("Could not load product list; retrying next cycle.", file=sys.stderr)

        if universe:
            signals = scan(universe, limiter, workers=4)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            hits = sorted(
                (s for s in signals
                 if s.ratio_5m >= args.ratio and s.usd_5m >= args.min_usd_5m
                 and s.buy_share_5m >= args.min_buy_share),
                key=lambda s: -s.score,
            )
            print_table(signals, hits, args.top, stamp)
            fresh_alerts = [s for s in hits if started - last_alert.get(s.product_id, 0) >= args.cooldown * 60]
            if fresh_alerts:
                append_alerts(args.alerts, stamp, fresh_alerts)
                for s in fresh_alerts:
                    last_alert[s.product_id] = started
                print(f"New alerts: {', '.join(s.product_id for s in fresh_alerts)} -> {args.alerts}")

        if args.once:
            return
        time.sleep(max(1.0, args.interval - (time.time() - started)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
