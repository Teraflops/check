# Coinbase Volume Scanner

Checks every Coinbase spot coin once a minute and flags the ones where trading
volume is suddenly being added compared with that coin's own recent normal.

- No API key needed: uses Coinbase's public market-data endpoints.
- No dependencies: Python 3.9+ standard library only.
- Read-only: it never places orders.

## Run

```bash
cd volume-scanner
python3 volume_scanner.py            # scan every 60s until Ctrl+C
python3 volume_scanner.py --once     # single scan
```

A full scan of ~150 USD pairs takes about 20–25 seconds.

Sample output:

```
=== 2026-09-27 02:57:24 UTC  scanned 157 pairs, 5 surging ===
PAIR             5m x   1m x   5m $vol  buy%    5m %   24h %  price
FIL-USD          13.4   10.4   $123.8k    84   +0.24  +10.61  1.1496
USELESS-USD      17.4   68.6   $115.9k    21   -0.20   +0.70  0.28528
New alerts: FIL-USD, USELESS-USD -> alerts.csv
```

| Column | Meaning |
|---|---|
| `5m x` | Volume in the last 5 closed minutes ÷ the coin's normal 5-minute volume |
| `1m x` | Same, for the last closed minute only |
| `5m $vol` | Dollar value traded in the last 5 minutes |
| `buy%` | Share of that volume traded in rising candles (high = buyers driving it) |
| `5m %` / `24h %` | Price change over 5 minutes / 24 hours |

"Normal" is the median 1-minute volume over the preceding 60 minutes. Minutes
with no trades count as zero, and the still-forming current minute is ignored.
Rows are ranked by a score that favours large volume multiples with buying
pressure and rising price.

New surges are appended to `alerts.csv`. The same pair isn't re-alerted for
10 minutes.

## Options

| Flag | Default | Description |
|---|---|---|
| `--quote` | `USD` | Quote currency to scan (e.g. `USDC`) |
| `--interval` | `60` | Seconds between scans |
| `--min-24h-usd` | `250000` | Skip pairs with less 24h dollar volume |
| `--ratio` | `3` | 5m volume multiple needed to flag a surge |
| `--min-usd-5m` | `10000` | Minimum dollars traded in the last 5 minutes to flag |
| `--min-buy-share` | `0` | Only flag surges where at least this share (0–1) is buying, e.g. `0.6` |
| `--cooldown` | `10` | Minutes before the same pair can alert again |
| `--top` | `15` | Rows printed per scan |
| `--alerts` | `alerts.csv` | CSV file for alerts |
| `--rps` | `8` | Max API requests per second (Coinbase's public limit is 10) |
| `--once` | off | Run one scan and exit |

Example: only buyer-led surges on liquid coins:

```bash
python3 volume_scanner.py --min-24h-usd 1000000 --ratio 4 --min-buy-share 0.6
```

## Tests

```bash
python3 -m unittest -v
```

A volume surge shows activity, not direction. Selling surges get flagged too;
use `buy%` and `5m %` to tell them apart. This is not trading advice.
