"""Share-based monthly backtest with costs.

Timing (no lookahead): weights are computed from the month-end close, then traded at the
close `execution_delay_days` later. Between rebalances, holdings drift with prices.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Config
from .strategy import month_ends, target_weights


@dataclass
class BacktestResult:
    equity: pd.Series
    weights: pd.DataFrame      # target weights at each signal date (risk ETFs only)
    trades: pd.DataFrame       # date, symbol, value, cost
    benchmarks: dict


def run_backtest(data: dict[str, pd.DataFrame], cfg: Config) -> BacktestResult:
    sp, rk = cfg.strategy, cfg.risk
    cost_rate = (cfg.costs.slippage_bps + cfg.costs.commission_bps) / 1e4
    risk_syms = [s for s in cfg.symbols if s in data]
    cash_sym = cfg.cash_symbol if cfg.cash_symbol in data else None
    syms = risk_syms + ([cash_sym] if cash_sym else [])

    closes_all = pd.DataFrame({s: data[s]["close"] for s in syms}).sort_index()
    closes = closes_all.loc[cfg.backtest.start:]
    signal_dates = month_ends(closes.index)[:-1]  # last "month end" may be today, not a real one
    W = target_weights(closes_all[risk_syms], sp, signal_dates)

    # map each signal to its trade date
    idx = closes.index
    trade_on = {}
    for d in signal_dates:
        i = idx.get_loc(d) + cfg.backtest.execution_delay_days
        if i < len(idx):
            trade_on[idx[i]] = d

    px = closes.ffill().to_numpy()
    shares = np.zeros(len(syms))
    cash = float(cfg.backtest.initial_equity)
    eq_pts, trades = [], []
    for i, day in enumerate(idx):
        p = px[i]
        valid = np.isfinite(p)
        equity = cash + np.nansum(shares * np.where(valid, p, 0))
        if day in trade_on:
            w = W.loc[trade_on[day]].reindex(risk_syms).fillna(0).to_numpy()
            target = np.zeros(len(syms))
            target[: len(risk_syms)] = w
            if cash_sym and valid[-1]:
                target[-1] = max(0.0, 1 - w.sum() - rk.cash_buffer_pct)
            target_val = target * equity
            cur_val = shares * np.where(valid, p, 0)
            diff = np.where(valid, target_val - cur_val, 0)
            # skip tiny trades, but always fully exit a position whose target is 0
            do = (np.abs(diff) >= rk.min_trade_pct * equity) | ((target == 0) & (cur_val > 0))
            for j in np.argsort(diff):  # sells (negative) first
                if not do[j] or diff[j] == 0:
                    continue
                cost = abs(diff[j]) * cost_rate
                shares[j] += diff[j] / p[j]
                cash -= diff[j] + cost
                trades.append((day, syms[j], diff[j], cost))
            equity = cash + np.nansum(shares * np.where(valid, p, 0))
        eq_pts.append(equity)

    equity = pd.Series(eq_pts, index=idx, name="strategy")
    return BacktestResult(equity, W, pd.DataFrame(trades, columns=["date", "symbol", "value", "cost"]),
                          _benchmarks(closes, cfg))


def _benchmarks(closes: pd.DataFrame, cfg: Config) -> dict:
    out = {}
    r = closes.pct_change(fill_method=None)
    if "SPY" in closes:
        out["SPY"] = (1 + r["SPY"].fillna(0)).cumprod() * cfg.backtest.initial_equity
    if "SPY" in closes and "IEF" in closes:
        mix = 0.6 * r["SPY"].fillna(0) + 0.4 * r["IEF"].fillna(0)  # daily-rebalanced 60/40
        out["60/40"] = (1 + mix).cumprod() * cfg.backtest.initial_equity
    return out


def metrics(equity: pd.Series) -> dict:
    equity = equity.dropna()
    if len(equity) < 2:
        return {}
    rets = equity.pct_change().dropna()
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    dd = equity / equity.cummax() - 1
    return {
        "total_return": equity.iloc[-1] / equity.iloc[0] - 1,
        "cagr": (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1,
        "max_drawdown": dd.min(),
        "sharpe": (rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0,
    }


def report(res: BacktestResult, cfg: Config) -> str:
    eq = res.equity
    series = {"strategy": eq, **res.benchmarks}
    split = eq.index[int(len(eq) * (1 - cfg.backtest.out_of_sample_frac))]
    pct = lambda x: f"{x * 100:.1f}%"
    names = list(series)
    lines = [f"Backtest {eq.index[0].date()} -> {eq.index[-1].date()}, costs "
             f"{cfg.costs.slippage_bps + cfg.costs.commission_bps}bps per trade, "
             f"trade delay {cfg.backtest.execution_delay_days} day(s)"]
    for title, sl in [("FULL PERIOD", slice(None)), (f"FIRST PART (to {split.date()})", slice(None, split)),
                      (f"LAST PART (from {split.date()})", slice(split, None))]:
        ms = {n: metrics(s[sl]) for n, s in series.items()}
        lines += ["", f"== {title} ==", f"{'':14}" + "".join(f"{n:>10}" for n in names)]
        for key, label, fmt in [("cagr", "return/yr", pct), ("max_drawdown", "max drawdown", pct),
                                ("sharpe", "sharpe", lambda x: f"{x:.2f}")]:
            lines.append(f"{label:14}" + "".join(f"{fmt(ms[n][key]):>10}" for n in names))

    yearly = pd.DataFrame({n: s.resample("YE").last() for n, s in series.items()})
    first = pd.DataFrame({n: [s.iloc[0]] for n, s in series.items()}, index=[eq.index[0]])
    yearly = pd.concat([first, yearly]).pct_change().iloc[1:]
    yearly.index = pd.DatetimeIndex(yearly.index).year
    lines += ["", "== RETURN BY YEAR ==", (yearly * 100).round(1).to_string()]

    t = res.trades
    if len(t):
        years = (eq.index[-1] - eq.index[0]).days / 365.25
        turnover = t["value"].abs().sum() / eq.mean() / years
        lines += ["", f"Trades: {len(t)} ({len(t) / years:.0f}/yr), turnover {turnover:.1f}x/yr, "
                      f"total costs ${t['cost'].sum():,.0f}"]
    held = (res.weights > 0).sum(axis=1)
    lines.append(f"Avg ETFs held: {held.mean():.1f} of {cfg.strategy.top_n}, "
                 f"avg in cash ETF: {(1 - res.weights.sum(axis=1)).mean() * 100:.0f}%")
    return "\n".join(lines)
