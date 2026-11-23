# Trend Rotation Bot

A monthly trend-following bot for ETFs. It backtests with costs first, then trades an Alpaca **paper** account.

## The strategy

On the first trading day of each month:

1. Look at 10 ETFs: US stocks (SPY, QQQ, IWM), international (EFA, EEM), bonds (TLT, IEF), gold (GLD), commodities (DBC), real estate (VNQ).
2. An ETF qualifies only if it's above its 200-day average (it's in an uptrend).
3. Hold up to 5 of the strongest qualifiers, ranked by the average of their 1, 3, 6 and 12-month returns. Calmer ETFs get bigger positions.
4. Any empty slots go into BIL (a T-bill ETF), so idle money still earns interest.

That's it. About 50 trades a year. It doesn't need to watch the market.

## Backtest results (real data, 2008 to Nov 2026, after costs)

| | Return/yr | Worst drop | Sharpe |
|---|---|---|---|
| **This bot** | **9.2%** | **-17%** | **0.83** |
| SPY buy-and-hold | 10.9% | -52% | 0.62 |
| 60/40 stocks/bonds | 8.2% | -31% | 0.75 |

How to read this:
- **The edge is the drawdowns, not extra return.** You get close to stock-market returns while avoiding most of the crash. In 2008 it made +1.8% while SPY lost 36%. In 2022 it lost 11% while SPY lost 18%.
- **It lags in strong bull markets.** 2019: +7% vs SPY +31%. 2023: +6% vs +26%. You'll be tempted to quit in those years.
- **It has weakened recently.** Since 2021, its Sharpe is about the same as SPY's (0.77 vs 0.80).
- **Longest stretch below a previous peak: about 2 years.**

How I checked it wasn't a fluke:
- It works with any trend length from 150 to 300 days, not just the 200 I picked.
- Momentum is averaged over 4 lookbacks. Using only 6-month returns backtested better (Sharpe 0.91), but 3, 9 and 12 months alone were much worse, so that result was partly luck. The blend is steadier on every test.
- 5-6 holdings work well; 2-3 holdings do much worse (too concentrated).
- At 4x the trading costs (20 bps), it still holds up.
- On a different set of 12 ETFs it still works: 8.1%/yr, Sharpe 0.79.
- Trades are simulated a day *after* each signal, so it never trades on information it couldn't have had.

Backtests still overstate real results. Expect a bit less live.

## What was tested and rejected

- **Daily breakout with trailing stops** (the first version): 2.2%/yr. Stops cut winners short and half the money sat idle.
- **Buying short dips in uptrending index ETFs** (RSI-2): about 3%/yr alone, weak before 2020, and it falls apart at higher trading costs. Mixing it 20-50% with this bot didn't improve risk-adjusted returns (Sharpe 0.83 to 0.85), it just cut returns.

## Safety features

| Problem | How it's handled |
|---|---|
| Running twice | Rebalances once per month; reruns do nothing |
| Order confirmation lost | Fixed order IDs; it looks the order up instead of resubmitting |
| Running out of cash | Sells go first and must fill; buys get scaled down to the cash actually available |
| Stale or missing data | That ETF isn't traded; if over half are missing, no rebalance and it retries the next day |
| Bad day | If the account is down 3%+ today, sells run but buys wait a day |
| Partial failure | The month only counts as done once every order fills; otherwise it retries the next day |
| Emergency | Create a file named `STOP` in the folder |
| Accidental real money | Dry run unless `--execute`; real money also needs `allow_live_trading = true` and a non-paper URL |
| Other holdings | Never touched. But it sizes off total account equity, so **use a dedicated account** |

## Setup

```bash
cd trading-bot
```

```bash
python3 -m venv .venv && source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
python -m pytest -q
```

## Step 1: Backtest

```bash
python main.py backtest
```

To check how fragile it is, set `slippage_bps = 20` or `trend_sma = 150` in `config.toml` and rerun. Change one thing at a time. If you tune settings until the backtest looks perfect, you're just fitting the past.

## Step 2: Paper trade (3+ months)

1. Get free paper keys at alpaca.markets and put them in `.env` (copy `.env.example`).
2. See what it would buy today (sends nothing):

```bash
python main.py live --force
```

3. Run it with paper orders every weekday at 9:45am New York time. It only trades on the first run of each month; other days it just checks in.

```bash
crontab -e
```

```
CRON_TZ=America/New_York
45 9 * * 1-5 cd /path/to/trading-bot && .venv/bin/python main.py live --execute >> logs/cron.log 2>&1
```

## Step 3: Real money (only if paper matches the backtest)

Use a dedicated account. A tax-advantaged one (IRA) is best, because monthly rotation creates short-term gains, which are taxed heavily in a regular account. Set `ALPACA_BASE_URL=https://api.alpaca.markets`, use live keys, and set `allow_live_trading = true`.

## Files

- `config.toml`: all rules and limits
- `bot/strategy.py`: the weight calculation (the backtest and the live bot both use it)
- `bot/backtest.py`: share-based simulator with costs, drift, and benchmarks
- `bot/live.py`: the daily paper/live run
- `bot/broker.py`: Alpaca REST client
- `tests/`: unit tests plus a fake broker for the live logic

## Known limits

- Long only. No leverage.
- Live signals use Alpaca's free IEX data, which can differ slightly from the Yahoo data used in backtests.
- Fractional shares are on by default. If Alpaca rejects fractional orders for an ETF, set `fractional = false` (whole shares only, so small accounts will be lumpy).
- No stop-losses between month-ends. A crash in the middle of a month is only acted on at the next rebalance. That was true in the backtest too, which includes 2008 and March 2020.
