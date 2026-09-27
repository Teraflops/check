# Autonomous Paper-Trading Agent (Coinbase)

An agent that runs every 5 minutes, scans the top Coinbase USD pairs with the
**Bullish Signal Detector**, opens *paper* long positions on strong setups and
manages every position with a tested exit strategy and hard risk limits.

**Paper trading only.** Nothing here can place a real order. Market data comes
from Coinbase's public Advanced Trade market-data endpoints. These are the same
product and candle data the Coinbase MCP tools return, called directly so the
agent can run unattended without a Claude session. No API key needed.

> No strategy is profitable all the time. The goal is that losses stay
> small and capped while winners are allowed to pay for them. Read the
> backtest section before trusting any of it.

## Files

| File | What it does |
|---|---|
| `signals.py` | Bullish Signal Detector: 14 rules in 4 categories, scoring, strong-setup flag, readable summary. Analysis only |
| `engine.py` | Paper portfolio: entry filter, position sizing, exit logic, kill switches. Shared by the agent and the backtester |
| `agent.py` | The autonomous loop (every 5 min) |
| `backtest.py` | Replays past Coinbase candles through the same engine and compares exit strategies |
| `dashboard.py` | Renders the agent's state, decisions and reasoning as an HTML dashboard |
| `coinbase_data.py` | Coinbase public market-data client (candles, products, prices) |
| `tests/` | 43 unit tests: every signal rule fires and doesn't fire on synthetic data; every exit rule |

## Quick start

```bash
cd paper-trader
pip install -r requirements.txt

python3 agent.py              # run forever, a cycle every 5 minutes
python3 agent.py --status     # positions, closed trades, P&L (from another terminal)
python3 backtest.py --halves  # re-run the exit-strategy comparison on the last 30 days
python3 -m pytest -q          # tests
```

Keep it running after you log out:

```bash
nohup python3 agent.py > /dev/null 2>&1 &     # logs go to agent.log
# or, in tmux:  tmux new -s agent 'python3 agent.py'
```

State is saved to `state.json` after every cycle. Stop and restart at any time.
On restart it replays any 5m candles it missed, so a stop that was hit while it
was down still gets applied. Delete `state.json`, `trades.csv` and `equity.csv`
to start a fresh paper account.

## Dashboard

```bash
python3 dashboard.py --out dashboard.html   # render from state.json + equity.csv
```

A self-contained HTML page with the account summary, the equity curve, and every
open position on a stop → entry → target scale. Each position shows **why it was
bought** (each detector signal that fired, with its numbers) and its **exit plan**.
Each closed trade shows **why it was sold** in plain English (for example "Price
fell to X, reaching the stop at Y (2x ATR below the Z entry)…"). It also has the
latest scan of every watched coin, with its score, which categories fired and why
it was passed or bought, plus a decision log of entries, exits and skipped setups.

The page embeds the full agent state, so a fresh machine can pick up the same
paper account:

```bash
python3 dashboard.py --restore dashboard.html   # recreates state.json and equity.csv
```

## What each 5-minute cycle does

1. **Manage open positions** on every newly closed 5m candle: stop loss → take
   profit → (optional) breakeven/trailing → EMA-cross/time-stop exits.
2. **Look for entries**: for each of the top 25 USD pairs by volume (stablecoins
   excluded), when a new signal-timeframe candle has closed, run the detector.
   Open a paper long only if **all** of these hold:
   - **strong setup**: at least one trend, one momentum and one volume signal;
   - score ≥ 3 from ≥ 3 independent clusters, so correlated signals like
     RSI + Stoch RSI count once;
   - price above a *rising* SMA200 (no bottom-fishing in downtrends);
   - ATR < 5% of price (skips coins too volatile to size safely).
3. **Save** `state.json`, append closed trades to `trades.csv` and equity to
   `equity.csv`, and log to `agent.log`.

## The exit strategy, and how it was chosen

Default (`--exit safe`), on **1h signals**:

- **Stop loss: 2 × ATR(14) below entry**, clamped to 1–5% of price. It's placed
  at entry and never widened.
- **Take profit: sell everything at 3R**, i.e. 3× the distance to the stop
  (a 3:1 reward:risk).
- Gaps are handled conservatively. A candle that touches both stop and target
  counts as a loss, and a gap below the stop fills at the open, not the stop.

Risk limits, all configurable in `RiskConfig`:

| Rule | Default |
|---|---|
| Risk per trade (loss if the stop is hit) | 1% of equity |
| Max size per position | 25% of equity |
| Max open positions | 3 |
| Daily loss limit: no new trades until next UTC day | −3% |
| **Kill switch**: stop trading entirely | −15% from peak equity |
| Cooldown after a losing trade on a coin | 12 cycles (1 hour) |
| Fees / slippage simulated | 0.5% per side / 0.05% |

### Backtest: 30 days, top-20 USD pairs, 0.5% fee per side

Test window 2026-08-28 → 2026-09-27. The same entries are used for every row,
so the only difference is the exit. "Halves" are the first and second 15 days
run separately, as a stability check.

| Signal TF | Exit | Trades | Win % | Return | Profit factor | Max DD | Halves |
|---|---|---|---|---|---|---|---|
| 5m | best of 9 variants | 54–88 | – | −13.5% to −15.7% | < 0.6 | hit kill switch | all negative |
| 15m | best of 9 variants | 51–86 | – | −10.8% to −14.9% | < 0.7 | hit kill switch | mostly negative |
| 1h | 1R target (tight) | 70 | 41% | −15.3% | 0.22 | 15.3% | −15.2 / −15.2 |
| 1h | 2R target | 88 | 46% | +13.8% | 1.30 | 11.0% | +2.1 / +6.8 |
| **1h** | **3R target — `safe` (default)** | **52** | **42%** | **+14.4%** | **1.48** | **12.8%** | **+3.1 / +5.8** |
| 1h | 4R target — `aggressive` | 36 | 44% | +28.1% | 2.30 | 10.9% | +11.6 / +8.0 |
| 1h | 3R + breakeven at 1.5R | 61 | 20% | −5.8% | 0.81 | 15.7% | +0.4 / −0.4 |
| 1h | 3R + 24-candle time stop | 60 | 38% | +11.8% | 1.33 | 10.4% | +5.3 / +0.6 |
| 1h | ATR trailing stop | 57 | 44% | −4.3% | 0.84 | 15.2% | +1.0 / +2.1 |
| 1h | EMA-cross exit | 36 | 22% | −5.5% | 0.69 | 15.7% | −5.5 / +20.9 |
| 1h | partial 2R + breakeven + trail | 79 | 42% | +6.2% | 1.17 | 12.7% | +4.3 / −1.3 |

Buy & hold of the same 20 coins over the same window: **+55%** (median +40%).

What the results say:

- **Fees decide everything on short timeframes.** A 0.5% + 0.5% round trip is
  bigger than a typical 5m/15m move, so every 5m and 15m variant lost and
  tripped the kill switch. That's why the agent checks every 5 minutes but
  takes signals from **1h** candles.
- **Tight targets and breakeven stops lose money.** They cut winners short or
  get shaken out by normal pullbacks, while losers still cost a full 1R. With
  a ~42% win rate, the strategy only works if winners are ≥ 2–3× the losers.
- **3R was chosen over 4R** because it has 50% more trades behind it and made
  money in both halves. 4R did better in this one strongly trending month,
  which is likely luck of the regime. Use `--exit aggressive` if you want it.
- **Lower fees roughly double results.** At 0.25%/side, as with maker limit
  orders, the 3R exit returned +21.9% (PF 1.81). Test with `python3 backtest.py --fee 0.0025`.

Honest caveats:

- It's one month, and a strong bull month: the strategy made far less than
  simply holding.
- The coin list is *today's* top-volume pairs, which flatters the past
  (survivorship bias).
- A strategy that made +14% in one month can easily lose in a choppy or
  falling market. That is what the stop, the daily loss limit and the kill
  switch are for.
- Paper fills assume you get the candle prices; real fills on thin coins can
  be worse.

Run the agent on paper for weeks, across different market conditions, before
drawing conclusions.

## Agent options

```
--timeframe 1h      signal timeframe (5m, 15m, 30m, 1h, 2h, 6h)
--exit safe         safe | aggressive | time_stop | partial_trail | trail
--products 25       number of top USD pairs to watch
--equity 1000       starting paper equity (USD)
--risk 0.01         fraction of equity risked per trade
--max-open 3        max simultaneous positions
--fee 0.005         simulated fee per side
--once              run one cycle and exit
--status            print positions and performance
```

## Using the detector on its own

```python
import coinbase_data as cd
from signals import detect, Params

df = cd.candles("BTC-USD", "1h", 300)
print(detect(df, "1h").summary())
print(detect(df, "1h", Params(rsi_period=10, volume_mult=2.0)).summary())   # every period/threshold is a parameter
```

With fewer than 200 candles, the SMA200 rules are reported as skipped instead
of crashing. VWAP is only evaluated on intraday timeframes, and resets each
UTC day.
