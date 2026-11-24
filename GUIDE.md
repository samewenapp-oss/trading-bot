# How to Actually Make Money With This Bot

The bot is the small part. Whether you make money depends mostly on four things: how much you put in, how long you leave it, taxes, and whether you stick with it when it looks bad.

## 1. What to realistically expect

- **About 7-9% a year** over the long run, after real-world friction. Some years +20%, some years -10%.
- **Drawdowns of 15-20%** will happen. That's $1,000 becoming $800 for a while.
- **It lags in strong bull markets.** Expect years where SPY makes +25% and the bot makes +7%.
- **Honest comparison:** just buying an S&P 500 index fund historically made slightly *more* (~10-11%/yr), but with crashes of 50%. The bot's real value is smaller crashes, which makes it easier not to panic-sell.

## 2. The math that actually matters

At 8% a year:

| You put in | After 10 years | After 20 years |
|---|---|---|
| $1,000 once | ~$2,200 | ~$4,700 |
| $10,000 once | ~$22,000 | ~$47,000 |
| $200/month | ~$36,000 (put in $24k) | ~$114,000 (put in $48k) |

**Regular deposits plus time** is where the money comes from. A smarter strategy matters far less than that.

## 3. The plan

1. **Now:** finish setup (private repo, Alpaca paper keys, Telegram, GitHub secrets, dry-run test). Steps are in the README.
2. **Dec to Feb: paper trade.** Each month, check that:
   - trades happened on the first trading day
   - fill prices were close to expected
   - no error alerts came in

   Three months won't prove the strategy works. It proves the *bot* works.
3. **March: go live small** ($50-500). Ask Claude Code to "switch to live." It resets the bot's state and turns on the live-trading switch; you swap in live Alpaca keys.
4. **After that:** add money on a schedule, monthly if you can. Automate the transfer from your bank. New money gets invested at the next monthly rebalance.

## 4. Taxes (this matters a lot in California)

- The bot sells winners every month, so most gains are **short-term**, taxed like your paycheck. In California that's federal plus state, potentially 30%+ of the gains.
- In a normal account, that could cut returns by roughly 1-3% a year. The exact figure depends on your income.
- **Best fix:** run it in an IRA (Roth if you qualify), where trades aren't taxed. Check whether Alpaca supports IRAs for API trading before you fund, or ask a tax person.

## 5. Rules that decide whether you actually make money

- **Don't change the rules** after a bad month. That turns a tested strategy into an untested one.
- **Don't quit in a lagging year.** The bot's value only shows up across a full cycle (5+ years).
- **Don't check daily and react.** The Telegram message is for spotting errors, not for trading decisions.
- **Pause the bot and investigate if:**
  - it falls more than ~25% from its peak (worse than anything in the backtest), or
  - you get repeated error alerts.

  To pause: GitHub app > repo > Actions > trading-bot > Disable workflow.

## 6. Do these before investing at all

- **Pay off high-interest debt first.** Paying off a 25% credit card is a guaranteed 25% return; no bot beats that.
- **Keep an emergency fund** (3-6 months of expenses) in savings.
- **Only invest money you won't need for 5+ years.** A drawdown when you need the cash forces you to sell at the bottom.

## 7. Don't

- Add leverage, options, or crypto to "make more."
- Stack extra strategies or copy Reddit bots.
- Put in money you can't afford to see drop 20%.

## Bottom line

This bot won't make you rich quickly. Feeding it money every month for years will build real wealth with smaller crashes than the stock market. That's what actually works.
