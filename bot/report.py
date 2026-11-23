"""Phone-friendly status: a short Telegram message every run, plus a chart on Fridays."""
import logging
import os
from pathlib import Path

import pandas as pd

log = logging.getLogger("bot")


def start_tracking(state: dict, client, today: pd.Timestamp, equity: float):
    """Remember where we started, so we can compare against SPY over the same period."""
    if "start_date" in state:
        return
    state["start_date"] = today.strftime("%Y-%m-%d")
    state["start_equity"] = equity
    try:
        spy = client.daily_bars("SPY", (today - pd.Timedelta(days=10)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
        state["start_spy"] = float(spy[spy.index < today]["close"].iloc[-1])
    except Exception as e:
        log.warning("could not record starting SPY price: %s", e)


def _spy_now(client, today) -> float | None:
    try:
        bars = client.daily_bars("SPY", (today - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
                                 (today + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
        return float(bars["close"].iloc[-1])
    except Exception:
        return None


def status_text(client, cfg, state: dict, today: pd.Timestamp, equity: float, day_pnl: float, mode: str) -> str:
    lines = [f"{mode} trend bot, {today:%a %b %d}",
             f"Equity ${equity:,.0f} ({day_pnl:+.1%} today)"]
    if state.get("start_equity"):
        mine = equity / state["start_equity"] - 1
        spy_now = _spy_now(client, today)
        spy_txt = f" | SPY {spy_now / state['start_spy'] - 1:+.1%}" if spy_now and state.get("start_spy") else ""
        lines.append(f"Since {state['start_date']}: {mine:+.1%}{spy_txt}")

    positions = client.positions()
    managed = {s: p for s, p in positions.items() if s in cfg.all_symbols}
    if managed:
        lines.append("Holdings:")
        for s, p in sorted(managed.items(), key=lambda kv: -float(kv[1].get("market_value", 0))):
            mv = float(p.get("market_value", 0))
            pl = float(p.get("unrealized_plpc", 0))
            lines.append(f"  {s:5} {mv / equity:4.0%}  {pl:+.1%}")
    else:
        lines.append("Holdings: none yet")
    nxt = (today + pd.offsets.MonthBegin(1)).strftime("%b")
    lines.append(f"Next rebalance: first trading day of {nxt}")
    return "\n".join(lines)


def equity_chart(client, state: dict, out: Path) -> Path | None:
    """Bot equity vs SPY since start. Returns the PNG path, or None if there isn't enough history."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        h = client.portfolio_history()
        eq = pd.Series(h["equity"], index=pd.to_datetime(h["timestamp"], unit="s").normalize()).dropna()
        eq = eq[eq > 0]
        if "start_date" in state:
            eq = eq[eq.index >= pd.Timestamp(state["start_date"])]
        if len(eq) < 3:
            return None
        spy = client.daily_bars("SPY", eq.index[0].strftime("%Y-%m-%d"),
                                (eq.index[-1] + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))["close"]
        fig, ax = plt.subplots(figsize=(6, 3.6), dpi=150)
        ax.plot(eq.index, (eq / eq.iloc[0] - 1) * 100, label="Bot", color="#2563eb", lw=2)
        if len(spy):
            ax.plot(spy.index, (spy / spy.iloc[0] - 1) * 100, label="SPY", color="#9ca3af", lw=1.5)
        ax.axhline(0, color="#e5e7eb", lw=1)
        ax.set_ylabel("% since start")
        ax.legend(frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        fig.autofmt_xdate()
        fig.tight_layout()
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out)
        plt.close(fig)
        return out
    except Exception as e:
        log.warning("chart failed: %s", e)
        return None


def send_report(client, cfg, notifier, state, today, equity, day_pnl, mode, log_dir: Path):
    text = status_text(client, cfg, state, today, equity, day_pnl, mode)
    notifier.send(text)
    summary = os.getenv("GITHUB_STEP_SUMMARY")  # shows on the run page in the GitHub app
    if summary:
        with open(summary, "a") as fh:
            fh.write("```\n" + text + "\n```\n")
    if today.dayofweek == 4:  # Friday
        png = equity_chart(client, state, log_dir / "equity.png")
        if png:
            notifier.send_photo(png, "Weekly: bot vs SPY since start")
