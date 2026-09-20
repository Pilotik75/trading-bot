"""Performance-Kennzahlen für einen Backtest-Lauf."""

import numpy as np


def compute_metrics(trades, equity_df, initial_capital, bars_per_year=60 * 24 * 365):
    if not trades or equity_df.empty:
        return {
            "num_trades": 0,
            "win_rate_pct": 0.0,
            "total_return_pct": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "final_equity": initial_capital,
        }

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    final_equity = equity_df["equity"].iloc[-1]
    total_return_pct = (final_equity / initial_capital - 1) * 100

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    equity = equity_df["equity"]
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    max_drawdown_pct = drawdown.min() * 100

    returns = equity.pct_change().dropna()
    sharpe = 0.0
    if len(returns) > 1 and returns.std() > 0:
        sharpe = returns.mean() / returns.std() * np.sqrt(bars_per_year)

    return {
        "num_trades": len(trades),
        "win_rate_pct": len(wins) / len(trades) * 100,
        "total_return_pct": total_return_pct,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_drawdown_pct,
        "sharpe": sharpe,
        "final_equity": final_equity,
    }
