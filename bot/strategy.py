"""Monthly trend rotation. The backtest and the live bot both call target_weights(),
so what you test is exactly what trades.

Rules, applied at each month-end close:
  1. An ETF qualifies only if its close is above its trend_sma-day average.
  2. Rank all ETFs by their average return over momentum_lookbacks; keep qualifiers in the top_n.
  3. Each kept ETF gets a share of a 1/top_n-per-slot budget, tilted by inverse volatility.
     Empty slots (fewer than top_n qualifiers) go to the cash ETF.
"""
import numpy as np
import pandas as pd

from .config import StrategyParams


def indicator_frames(closes: pd.DataFrame, p: StrategyParams) -> dict[str, pd.DataFrame]:
    return {
        "sma": closes.rolling(p.trend_sma).mean(),
        # average of several lookbacks: no single "lucky" number drives the ranking
        "mom": sum(closes / closes.shift(n) - 1 for n in p.momentum_lookbacks) / len(p.momentum_lookbacks),
        "vol": closes.pct_change(fill_method=None).rolling(p.vol_lookback).std(),
    }


def _weights_row(last: pd.Series, sma: pd.Series, mom: pd.Series, vol: pd.Series, p: StrategyParams) -> pd.Series:
    trend = (last > sma).fillna(False)
    in_top = mom.rank(ascending=False) <= p.top_n   # NaN momentum never ranks
    pick = trend & in_top & vol.gt(0).fillna(False)
    w = pd.Series(0.0, index=last.index)
    if pick.any():
        iv = 1 / vol[pick]
        w[pick] = iv / iv.sum() * (pick.sum() / p.top_n)
    return w


def target_weights(closes: pd.DataFrame, p: StrategyParams, dates=None) -> pd.DataFrame:
    """Weights of the risk ETFs (rows = signal dates). Each row sums to <= 1; the rest is cash.
    Uses only data up to and including each signal date."""
    ind = indicator_frames(closes, p)
    dates = closes.index[-1:] if dates is None else dates
    rows = [_weights_row(closes.loc[d], ind["sma"].loc[d], ind["mom"].loc[d], ind["vol"].loc[d], p) for d in dates]
    return pd.DataFrame(rows, index=dates) if rows else pd.DataFrame(columns=closes.columns)


def month_ends(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby(index.to_period("M")).max().values)
