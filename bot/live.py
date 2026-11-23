"""One live/paper run. Schedule it every trading day ~15 minutes after the open.
It only trades on the first run of each new month; other days it just checks in.

Safety rules:
  - dry run unless --execute; real money also needs allow_live_trading = true
  - kill switch file halts everything
  - deterministic client_order_id per month/symbol/side, so a rerun or retry can't double an order
  - sells run first and must fill before buys; buys are scaled down to the cash actually available
  - stale or missing data for a symbol: that symbol isn't traded; if too many are missing, no rebalance
  - daily loss circuit breaker: sells still run, buys wait for the next run
  - the month is only marked done when every order filled, so a failed run retries next day
  - use a dedicated account: the bot sizes off total account equity
"""
import csv
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .broker import BrokerError
from .config import Config
from .notify import Notifier
from .strategy import target_weights

log = logging.getLogger("bot")


def _load_state(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save_state(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)  # atomic


def _log_trade(log_dir: Path, row: dict):
    log_dir.mkdir(parents=True, exist_ok=True)
    f = log_dir / "trades.csv"
    fields = ["time", "mode", "symbol", "side", "qty", "price", "value", "reason"]
    new = not f.exists()
    with f.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow({"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **row})


def get_closes(client, cfg: Config, today: pd.Timestamp, notifier: Notifier) -> pd.DataFrame:
    """Completed daily closes for every symbol that has fresh, sufficient data."""
    start = (today - pd.Timedelta(days=450)).strftime("%Y-%m-%d")
    need = max(cfg.strategy.trend_sma, *cfg.strategy.momentum_lookbacks, cfg.strategy.vol_lookback) + 1
    cols, problems = {}, []
    for s in cfg.all_symbols:
        try:
            df = client.daily_bars(s, start, today.strftime("%Y-%m-%d"))
        except BrokerError as e:
            problems.append(f"{s}: data error {e}")
            continue
        df = df[df.index < today]  # only fully completed days
        if s != cfg.cash_symbol and len(df) < need:
            problems.append(f"{s}: only {len(df)} bars")
            continue
        if len(df) == 0 or (today - df.index[-1]).days > cfg.live.max_bar_age_days:
            problems.append(f"{s}: data is stale or empty")
            continue
        cols[s] = df["close"]
    if problems:
        notifier.send("Data issues, these symbols won't be traded:\n" + "\n".join(problems))
    return pd.DataFrame(cols).sort_index()


def plan_orders(weights: pd.Series, cash_weight: float, positions: dict, prices: dict, equity: float,
                cfg: Config, tradable: set) -> list[dict]:
    """Turn target weights into orders. Returns [{symbol, side, qty, value}] with sells first."""
    targets = {s: float(w) for s, w in weights.items()}
    if cfg.cash_symbol in tradable:
        targets[cfg.cash_symbol] = cash_weight
    managed = (set(cfg.all_symbols) & set(positions)) | set(targets)
    orders = []
    for s in managed:
        if s not in tradable:
            continue  # no fresh data: leave as is
        price = prices[s]
        cur_qty = float(positions[s]["qty"]) if s in positions else 0.0
        diff_val = targets.get(s, 0.0) * equity - cur_qty * price
        full_exit = targets.get(s, 0.0) == 0 and cur_qty > 0
        if abs(diff_val) < cfg.risk.min_trade_pct * equity and not full_exit:
            continue
        if full_exit:
            qty = cur_qty
        else:
            raw = abs(diff_val) / price
            qty = math.floor(raw * 1000) / 1000 if cfg.live.fractional else math.floor(raw)
            if diff_val < 0:
                qty = min(qty, cur_qty)
        if qty <= 0:
            continue
        orders.append({"symbol": s, "side": "sell" if diff_val < 0 else "buy", "qty": qty, "value": qty * price})
    return sorted(orders, key=lambda o: (o["side"] != "sell", -o["value"]))


def run_once(cfg: Config, client, notifier: Notifier, execute=False, force=False,
             base_dir: str | Path = ".") -> list[str]:
    base = Path(base_dir)
    state_path, log_dir = base / cfg.live.state_file, base / cfg.live.log_dir
    mode = ("LIVE" if not client.is_paper else "PAPER") if execute else "DRY-RUN"
    actions: list[str] = []

    if (base / cfg.live.kill_switch_file).exists():
        notifier.send(f"Kill switch file '{cfg.live.kill_switch_file}' found. Not trading.")
        return actions
    if not client.is_paper and not cfg.live.allow_live_trading:
        raise RuntimeError("Non-paper URL but allow_live_trading = false. Refusing to run.")
    if force and execute:
        raise RuntimeError("--force (ignore market hours / monthly schedule) is only allowed in dry-run.")

    clock = client.clock()
    if not clock["is_open"] and not force:
        log.info("Market closed, nothing to do.")
        return actions
    today = pd.Timestamp(clock["timestamp"]).tz_convert("America/New_York").normalize().tz_localize(None)
    month = today.strftime("%Y-%m")
    state = _load_state(state_path)

    acct = client.account()
    equity, last_equity = float(acct["equity"]), float(acct["last_equity"])
    day_pnl = equity / last_equity - 1 if last_equity > 0 else 0.0

    if state.get("last_rebalance") == month and not force:
        log.info(f"Already rebalanced for {month}. Equity ${equity:,.0f} ({day_pnl:+.2%} today).")
        state["last_check"] = today.strftime("%Y-%m-%d")
        if execute:
            _save_state(state_path, state)
        return actions
    if acct.get("trading_blocked") or acct.get("account_blocked"):
        notifier.send("Account is blocked from trading. Stopping.")
        return actions

    positions = client.positions()
    busy = {o["symbol"] for o in client.open_orders() if o["symbol"] in cfg.all_symbols}
    if busy:
        notifier.send(f"Open orders already working for {sorted(busy)}. Waiting for them; will retry next run.")
        return actions

    closes = get_closes(client, cfg, today, notifier)
    risk_ok = [s for s in cfg.symbols if s in closes]
    if len(risk_ok) < len(cfg.symbols) / 2:
        notifier.send(f"Only {len(risk_ok)}/{len(cfg.symbols)} symbols have usable data. "
                      "Skipping this rebalance; will retry next run.")
        return actions

    w = target_weights(closes[risk_ok], cfg.strategy).iloc[0]
    w = w[w > 0]
    cash_w = max(0.0, 1 - w.sum() - cfg.risk.cash_buffer_pct)
    prices = {s: float(positions[s]["current_price"]) if s in positions else float(closes[s].dropna().iloc[-1])
              for s in closes.columns}
    orders = plan_orders(w, cash_w, positions, prices, equity, cfg, set(closes.columns))

    target_txt = ", ".join(f"{s} {v:.0%}" for s, v in w.sort_values(ascending=False).items()) or "none"
    log.info("Targets for %s: %s, %s %.0f%%", month, target_txt, cfg.cash_symbol, cash_w * 100)

    allow_buys = day_pnl > -cfg.risk.max_daily_loss_pct
    all_filled = True
    for side in ("sell", "buy"):
        batch = [o for o in orders if o["side"] == side]
        if not batch:
            continue
        if side == "buy":
            if not allow_buys:
                notifier.send(f"Circuit breaker: account {day_pnl:+.1%} today. Buys wait for the next run.")
                all_filled = False
                break
            if execute:  # scale buys to cash actually available after sells
                avail = float(client.account()["cash"]) - cfg.risk.cash_buffer_pct * equity * 0.5
                need = sum(o["value"] for o in batch) * (1 + cfg.costs.slippage_bps / 1e4)
                if need > avail > 0:
                    k = avail / need
                    for o in batch:
                        o["qty"] = math.floor(o["qty"] * k * 1000) / 1000 if cfg.live.fractional \
                            else math.floor(o["qty"] * k)
                        o["value"] = o["qty"] * prices[o["symbol"]]
        for o in batch:
            if o["qty"] <= 0:
                continue
            desc = f"{side.upper()} {o['symbol']} x{o['qty']:g} (~${o['value']:,.0f})"
            actions.append(desc)
            if not execute:
                log.info("DRY-RUN would: %s", desc)
                continue
            try:
                sent = client.submit_order(symbol=o["symbol"], qty=f"{o['qty']:g}", side=side, type="market",
                                           time_in_force="day", client_order_id=f"reb-{month}-{o['symbol']}-{side}")
                f = client.wait_for_fill(sent["id"])
            except BrokerError as e:
                notifier.send(f"ORDER FAILED {desc}: {e}")
                all_filled = False
                continue
            if f["status"] != "filled":
                notifier.send(f"{desc}: status {f['status']}, not filled. Will retry next run.")
                all_filled = False
                continue
            fill_px = float(f["filled_avg_price"])
            _log_trade(log_dir, {"mode": mode, "symbol": o["symbol"], "side": side, "qty": f["filled_qty"],
                                 "price": fill_px, "value": round(float(f["filled_qty"]) * fill_px, 2),
                                 "reason": f"rebalance {month}"})
        if side == "sell" and not all_filled:
            notifier.send("Some sells didn't fill. Skipping buys to avoid running short of cash.")
            break

    if execute and all_filled:
        state.update(last_rebalance=month, last_targets={**w.round(4).to_dict(), cfg.cash_symbol: round(cash_w, 4)})
        _save_state(state_path, state)
    lines = [f"[{mode}] {month} rebalance. Equity ${equity:,.0f} ({day_pnl:+.2%} today)",
             f"Targets: {target_txt}, {cfg.cash_symbol} {cash_w:.0%}"]
    lines += [f" - {a}" for a in actions] or [" - no trades needed"]
    if execute and not all_filled:
        lines.append("Not complete; will retry next run.")
    notifier.send("\n".join(lines))
    return actions
