"""
Usage:
  python main.py backtest                      # download data from Yahoo and backtest
  python main.py backtest --source csv         # reuse cached CSVs in data/cache
  python main.py backtest --source synthetic   # fake data, plumbing test only
  python main.py live                          # dry run: shows what it WOULD do
  python main.py live --force                  # dry run now, ignoring market hours and the monthly schedule
  python main.py live --execute                # actually place orders (paper account by default)
"""
import argparse
import logging
import os
import sys

import pandas as pd
from pathlib import Path

from bot.backtest import report, run_backtest
from bot.config import load_config
from bot.notify import Notifier


def _load_dotenv(path=".env"):
    p = Path(path)
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cmd_backtest(args, cfg):
    from bot import data

    if args.source == "yfinance":
        d = data.load_yfinance(cfg.all_symbols, "2006-01-01")
    elif args.source == "csv":
        d = data.load_csv_dir(cfg.all_symbols, args.csv_dir)
    else:
        print("!! SYNTHETIC DATA: tests the code, says nothing about real markets !!\n")
        d = data.synthetic(cfg.all_symbols)
    if not d:
        sys.exit("No data loaded.")
    res = run_backtest(d, cfg)
    print(report(res, cfg))
    Path("logs").mkdir(exist_ok=True)
    res.trades.to_csv("logs/backtest_trades.csv", index=False)
    res.weights.to_csv("logs/backtest_weights.csv")
    pd.DataFrame({"strategy": res.equity, **res.benchmarks}).to_csv("logs/backtest_equity.csv")
    print("\nSaved logs/backtest_trades.csv, backtest_weights.csv, backtest_equity.csv")


def cmd_live(args, cfg):
    from bot.broker import PAPER_URL, AlpacaClient
    from bot.live import run_once

    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not (key and secret):
        sys.exit("Set ALPACA_API_KEY and ALPACA_SECRET_KEY (see .env.example).")
    client = AlpacaClient(key, secret, os.getenv("ALPACA_BASE_URL", PAPER_URL))
    notifier = Notifier()
    try:
        run_once(cfg, client, notifier, execute=args.execute, force=args.force)
    except Exception as e:
        notifier.send(f"BOT ERROR, run aborted: {type(e).__name__}: {e}")
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest")
    b.add_argument("--source", choices=["yfinance", "csv", "synthetic"], default="yfinance")
    b.add_argument("--csv-dir", default="data/cache")
    lv = sub.add_parser("live")
    lv.add_argument("--execute", action="store_true", help="actually send orders")
    lv.add_argument("--force", action="store_true", help="dry-run even if market is closed")
    args = ap.parse_args()

    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("logs/run.log")])
    _load_dotenv()
    cfg = load_config(args.config)
    {"backtest": cmd_backtest, "live": cmd_live}[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
