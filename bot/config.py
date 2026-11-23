import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StrategyParams:
    trend_sma: int = 200
    momentum_lookbacks: list[int] = field(default_factory=lambda: [21, 63, 126, 252])
    vol_lookback: int = 60
    top_n: int = 5


@dataclass
class RiskParams:
    cash_buffer_pct: float = 0.02
    min_trade_pct: float = 0.01
    max_daily_loss_pct: float = 0.03


@dataclass
class CostParams:
    slippage_bps: float = 5.0
    commission_bps: float = 0.0


@dataclass
class BacktestParams:
    start: str = "2008-01-01"
    initial_equity: float = 10000.0
    out_of_sample_frac: float = 0.3
    execution_delay_days: int = 1


@dataclass
class LiveParams:
    state_file: str = "state/state.json"
    log_dir: str = "logs"
    kill_switch_file: str = "STOP"
    allow_live_trading: bool = False
    max_bar_age_days: int = 5
    fractional: bool = True


@dataclass
class Config:
    symbols: list[str] = field(default_factory=lambda: ["SPY"])
    cash_symbol: str = "BIL"
    strategy: StrategyParams = field(default_factory=StrategyParams)
    risk: RiskParams = field(default_factory=RiskParams)
    costs: CostParams = field(default_factory=CostParams)
    backtest: BacktestParams = field(default_factory=BacktestParams)
    live: LiveParams = field(default_factory=LiveParams)

    @property
    def all_symbols(self) -> list[str]:
        return self.symbols + ([self.cash_symbol] if self.cash_symbol else [])


def load_config(path: str | Path = "config.toml") -> Config:
    raw = tomllib.loads(Path(path).read_text())
    uni = raw.get("universe", {})
    return Config(
        symbols=uni.get("symbols", ["SPY"]),
        cash_symbol=uni.get("cash_symbol", "BIL"),
        strategy=StrategyParams(**raw.get("strategy", {})),
        risk=RiskParams(**raw.get("risk", {})),
        costs=CostParams(**raw.get("costs", {})),
        backtest=BacktestParams(**raw.get("backtest", {})),
        live=LiveParams(**raw.get("live", {})),
    )
