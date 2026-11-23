import itertools

import numpy as np
import pandas as pd
import pytest

from bot.backtest import metrics, run_backtest
from bot.config import Config, CostParams, StrategyParams
from bot.data import synthetic
from bot.live import run_once
from bot.strategy import target_weights

SYMS = ["AAA", "BBB", "CCC", "DDD"]


def small_cfg(**costs):
    return Config(symbols=SYMS, cash_symbol="CASH",
                  strategy=StrategyParams(trend_sma=50, momentum_lookback=40, vol_lookback=20, top_n=2),
                  costs=CostParams(**costs))


def trend_closes(n=300, end="2026-01-30", slopes=(0.5, 0.2, -0.2, 0.1)):
    idx = pd.bdate_range(end=end, periods=n)
    rng = np.random.default_rng(1)
    cols = {s: 100 * (1 + k / 100) ** np.arange(n) * (1 + rng.normal(0, 0.003, n)) for s, k in zip(SYMS, slopes)}
    cols["CASH"] = 100 + 0.002 * np.arange(n)
    return pd.DataFrame(cols, index=idx)


# ---------- strategy ----------

def test_weights_have_no_lookahead():
    c = synthetic(SYMS, n_days=500)
    closes = pd.DataFrame({s: df["close"] for s, df in c.items()})
    p = small_cfg().strategy
    d = closes.index[300]
    full = target_weights(closes, p, [d])
    cut = target_weights(closes.loc[:d], p, [d])
    pd.testing.assert_frame_equal(full, cut)


def test_weights_pick_top_uptrends_only():
    closes = trend_closes()[SYMS]
    w = target_weights(closes, small_cfg().strategy).iloc[0]
    assert w["CCC"] == 0  # downtrend never held
    assert set(w[w > 0].index) == {"AAA", "BBB"}  # top 2 by momentum
    assert w.sum() == pytest.approx(1.0)


def test_empty_slots_go_to_cash():
    closes = trend_closes(slopes=(0.5, -0.2, -0.3, -0.1))[SYMS]
    w = target_weights(closes, small_cfg().strategy).iloc[0]
    assert w.sum() == pytest.approx(0.5)  # 1 of 2 slots filled


# ---------- backtest ----------

def test_backtest_runs_and_costs_hurt():
    data = synthetic(SYMS + ["CASH"], n_days=1500, seed=3)
    cfg = small_cfg(slippage_bps=0)
    cfg.backtest.start = "2012-01-01"
    cheap = run_backtest(data, cfg)
    cfg.costs.slippage_bps = 50
    pricey = run_backtest(data, cfg)
    assert len(cheap.trades) > 10
    assert pricey.equity.iloc[-1] < cheap.equity.iloc[-1]
    assert (cheap.equity > 0).all()


def test_backtest_never_levered():
    data = synthetic(SYMS + ["CASH"], n_days=1500, seed=5)
    cfg = small_cfg()
    cfg.backtest.start = "2012-01-01"
    res = run_backtest(data, cfg)
    assert (res.weights.sum(axis=1) <= 1 + 1e-9).all()


def test_metrics_drawdown():
    eq = pd.Series([100, 120, 90, 130], index=pd.bdate_range("2020-01-01", periods=4))
    assert metrics(eq)["max_drawdown"] == pytest.approx(-0.25)


# ---------- live, with a fake broker ----------

class FakeClient:
    is_paper = True

    def __init__(self, closes, cash=10000.0, ts="2026-02-02T10:00:00-05:00"):
        self.closes, self.cash, self.ts = closes, cash, ts
        self.pos, self.orders, self.submitted = {}, {}, []
        self._ids = itertools.count(1)
        self.last_equity = None

    def px(self, s):
        return float(self.closes[s].iloc[-1])

    def equity(self):
        return self.cash + sum(q * self.px(s) for s, q in self.pos.items())

    def clock(self):
        return {"is_open": True, "timestamp": self.ts}

    def account(self):
        e = self.equity()
        return {"equity": str(e), "last_equity": str(self.last_equity or e), "cash": str(self.cash)}

    def positions(self):
        return {s: {"symbol": s, "qty": str(q), "current_price": str(self.px(s))} for s, q in self.pos.items()}

    def open_orders(self):
        return [o for o in self.orders.values() if o["status"] == "new"]

    def daily_bars(self, symbol, start, end):
        return pd.DataFrame({"close": self.closes[symbol]})

    def submit_order(self, **p):
        if any(o["client_order_id"] == p["client_order_id"] for o in self.orders.values()):
            raise AssertionError("duplicate client_order_id")
        s, q = p["symbol"], float(p["qty"])
        sign = 1 if p["side"] == "buy" else -1
        self.cash -= sign * q * self.px(s)
        assert self.cash > -1e-6, "went into margin"
        self.pos[s] = self.pos.get(s, 0) + sign * q
        if abs(self.pos[s]) < 1e-9:
            del self.pos[s]
        oid = str(next(self._ids))
        o = {**p, "id": oid, "status": "filled", "filled_avg_price": str(self.px(s)), "filled_qty": p["qty"]}
        self.orders[oid] = o
        self.submitted.append(o)
        return o

    def wait_for_fill(self, oid, **kw):
        return self.orders[oid]


class SilentNotifier:
    def __init__(self):
        self.msgs = []

    def send(self, t):
        self.msgs.append(t)


def test_dry_run_sends_nothing(tmp_path):
    c = FakeClient(trend_closes())
    actions = run_once(small_cfg(), c, SilentNotifier(), execute=False, base_dir=tmp_path)
    assert any(a.startswith("BUY AAA") for a in actions)
    assert c.submitted == []
    assert not (tmp_path / "state/state.json").exists()


def test_rebalance_hits_targets_and_runs_once_per_month(tmp_path):
    c = FakeClient(trend_closes())
    n = SilentNotifier()
    run_once(small_cfg(), c, n, execute=True, base_dir=tmp_path)
    eq = c.equity()
    assert set(c.pos) == {"AAA", "BBB"}  # no CASH: both slots filled
    assert sum(q * c.px(s) for s, q in c.pos.items()) / eq == pytest.approx(0.98, abs=0.03)
    before = len(c.submitted)
    run_once(small_cfg(), c, n, execute=True, base_dir=tmp_path)  # same month again
    assert len(c.submitted) == before
    assert "trades.csv" in [p.name for p in (tmp_path / "logs").iterdir()]


def test_next_month_rotates_out_of_downtrend(tmp_path):
    c = FakeClient(trend_closes())
    n = SilentNotifier()
    run_once(small_cfg(), c, n, execute=True, base_dir=tmp_path)
    # March: BBB rolls over hard, DDD takes its slot
    c.closes = trend_closes(end="2026-02-27", slopes=(0.5, -0.4, -0.2, 0.3))
    c.ts = "2026-03-02T10:00:00-05:00"
    before = len(c.submitted)
    run_once(small_cfg(), c, n, execute=True, base_dir=tmp_path)
    assert "BBB" not in c.pos
    assert "DDD" in c.pos
    assert c.submitted[before]["side"] == "sell"  # sells go first


def test_kill_switch(tmp_path):
    (tmp_path / "STOP").write_text("")
    c = FakeClient(trend_closes())
    assert run_once(small_cfg(), c, SilentNotifier(), execute=True, base_dir=tmp_path) == []
    assert c.submitted == []


def test_stale_data_blocks_rebalance(tmp_path):
    c = FakeClient(trend_closes(end="2025-12-01"))
    n = SilentNotifier()
    run_once(small_cfg(), c, n, execute=True, base_dir=tmp_path)
    assert c.submitted == []
    assert any("Skipping this rebalance" in m for m in n.msgs)
    assert not (tmp_path / "state/state.json").exists()  # month not marked done, retries tomorrow


def test_circuit_breaker_blocks_buys_and_retries(tmp_path):
    c = FakeClient(trend_closes())
    c.last_equity = 11000  # account "down 9% today"
    n = SilentNotifier()
    run_once(small_cfg(), c, n, execute=True, base_dir=tmp_path)
    assert c.submitted == []
    assert any("Circuit breaker" in m for m in n.msgs)
    c.last_equity = None  # next day, calm
    run_once(small_cfg(), c, n, execute=True, base_dir=tmp_path)
    assert set(c.pos) == {"AAA", "BBB"}


def test_ignores_positions_outside_universe(tmp_path):
    c = FakeClient(trend_closes())
    c.pos["TSLA"] = 5
    c.closes["TSLA"] = 200.0
    run_once(small_cfg(), c, SilentNotifier(), execute=True, base_dir=tmp_path)
    assert c.pos["TSLA"] == 5
    assert all(o["symbol"] != "TSLA" for o in c.submitted)
