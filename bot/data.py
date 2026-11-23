from pathlib import Path

import numpy as np
import pandas as pd

COLS = ["open", "high", "low", "close", "volume"]


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df[[c for c in COLS if c in df.columns]].dropna()
    return df[~df.index.duplicated(keep="last")].sort_index()


def load_yfinance(symbols, start, end=None, cache_dir="data/cache") -> dict[str, pd.DataFrame]:
    """Split/dividend-adjusted daily bars from Yahoo. Cached to CSV so reruns are fast and repeatable."""
    import yfinance as yf

    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    out = {}
    for s in symbols:
        raw = yf.download(s, start=start, end=end, auto_adjust=True, progress=False)
        if raw is None or raw.empty:
            print(f"warning: no data for {s}, skipping")
            continue
        df = _clean(raw)
        df.to_csv(Path(cache_dir) / f"{s}.csv")
        out[s] = df
    return out


def load_csv_dir(symbols, path="data/cache") -> dict[str, pd.DataFrame]:
    out = {}
    for s in symbols:
        f = Path(path) / f"{s}.csv"
        if f.exists():
            out[s] = _clean(pd.read_csv(f, index_col=0, parse_dates=True))
        else:
            print(f"warning: {f} not found, skipping {s}")
    return out


def synthetic(symbols, n_days=3000, seed=0) -> dict[str, pd.DataFrame]:
    """Random-walk prices with drifting regimes. For testing the plumbing ONLY.
    Results on this data say nothing about real markets."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2012-01-02", periods=n_days)
    out = {}
    for s in symbols:
        regime = np.repeat(rng.normal(0, 0.0008, n_days // 120 + 1), 120)[:n_days]
        rets = regime + rng.normal(0, 0.012, n_days)
        close = 100 * np.exp(np.cumsum(rets))
        open_ = close * np.exp(rng.normal(0, 0.003, n_days))
        high = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.006, n_days)))
        low = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.006, n_days)))
        out[s] = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": 1_000_000}, index=idx
        )
    return out
