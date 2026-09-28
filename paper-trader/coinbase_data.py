"""Market data from Coinbase Advanced Trade public endpoints.

These are the same market-data endpoints the Coinbase MCP's products/candles
tools read, called directly so the agent can run unattended without a Claude
session. Read-only; no API key needed.
"""

import json
import threading
import time
import urllib.error
import urllib.request

import pandas as pd

BASE = "https://api.coinbase.com/api/v3/brokerage/market"
GRANULARITY = {
    "1m": ("ONE_MINUTE", 60), "5m": ("FIVE_MINUTE", 300), "15m": ("FIFTEEN_MINUTE", 900),
    "30m": ("THIRTY_MINUTE", 1800), "1h": ("ONE_HOUR", 3600), "2h": ("TWO_HOUR", 7200),
    "6h": ("SIX_HOUR", 21600), "1d": ("ONE_DAY", 86400),
}
MAX_CANDLES = 350
STABLES = {"USDC", "USDT", "DAI", "PYUSD", "EURC", "PAX", "GUSD", "USDS", "USD1", "FDUSD", "TUSD"}

_lock = threading.Lock()
_next = [0.0]


def _get(url, retries=4, rps=8):
    for attempt in range(retries):
        with _lock:
            now = time.monotonic()
            wait = _next[0] - now
            _next[0] = max(now, _next[0]) + 1 / rps
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "paper-trader/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            time.sleep(2 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(2 * (attempt + 1))
    return None


def top_products(quote="USD", n=25, min_24h_usd=1_000_000):
    """Most-traded online spot pairs in `quote`, excluding stablecoins."""
    data = _get(f"{BASE}/products?product_type=SPOT&limit=1000")
    rows = []
    for p in (data or {}).get("products", []):
        if p.get("quote_currency_id") != quote or p.get("status") != "online":
            continue
        if p.get("trading_disabled") or p.get("base_currency_id") in STABLES:
            continue
        try:
            usd = float(p["price"]) * float(p["volume_24h"])
        except (KeyError, TypeError, ValueError):
            continue
        if usd >= min_24h_usd:
            rows.append((usd, p["product_id"]))
    return [pid for _, pid in sorted(rows, reverse=True)[:n]]


def candles(product_id, timeframe="5m", count=300, end=None):
    """Up to `count` closed candles ending at `end` (unix seconds, default now), oldest first.

    Returns a DataFrame indexed by UTC candle start time with open/high/low/close/volume.
    The still-forming candle is dropped.
    """
    gran, secs = GRANULARITY[timeframe]
    end = int(end or time.time()) // secs * secs          # start of the forming candle
    frames, stop = [], end
    remaining = count
    while remaining > 0:
        n = min(remaining, MAX_CANDLES)
        start = stop - n * secs
        data = _get(f"{BASE}/products/{product_id}/candles?granularity={gran}&start={start}&end={stop - 1}&limit={n}")
        rows = (data or {}).get("candles") or []
        if not rows:
            break
        frames.append(pd.DataFrame(rows))
        remaining -= n
        stop = start
    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.concat(frames).drop_duplicates("start")
    df.index = pd.to_datetime(df.pop("start").astype(int), unit="s", utc=True)
    df = df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()
    return df[df.index < pd.Timestamp(end, unit="s", tz="UTC")]


def last_price(product_id):
    data = _get(f"{BASE}/products/{product_id}")
    try:
        return float(data["price"])
    except (TypeError, KeyError, ValueError):
        return None
