"""Generische, einfache Backtest-Engine für den systematischen Strategievergleich
(strategy_lab.py): fester ATR-Stop + festes R-Vielfaches als Take-Profit, eine Position
gleichzeitig, gleiches Risk-Management (risk.py) wie die übrigen Engines in diesem Projekt.

Bewusst ohne Bestätigungs-/Teilausstiegs-/Trendfilter-Komplexität der Fade-Engine - hier
geht es um einen fairen, einheitlichen Maßstab für viele verschiedene Signalquellen, nicht
um die bestmögliche Ausgestaltung einer einzelnen Strategie.
"""

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from .risk import calculate_position_size
from .strategy_lab import atr


@dataclass
class SimpleTrade:
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    size: float
    leverage: float
    stop_price: float
    target_price: float
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0


class SignalBacktester:
    def __init__(
        self,
        capital=10_000.0,
        risk_pct=0.02,
        max_leverage=2.5,
        atr_period=14,
        atr_stop_mult=2.0,
        rr_multiple=1.5,
        fee_pct=0.0004,
        allow_shorts=True,
    ):
        self.initial_capital = capital
        self.capital = capital
        self.risk_pct = risk_pct
        self.max_leverage = max_leverage
        self.atr_period = atr_period
        self.atr_stop_mult = atr_stop_mult
        self.rr_multiple = rr_multiple
        self.fee_pct = fee_pct
        self.allow_shorts = allow_shorts

        self.trades: List[SimpleTrade] = []
        self.equity_curve = []
        self.position: Optional[SimpleTrade] = None

    def run(self, df: pd.DataFrame, signal: pd.Series) -> pd.DataFrame:
        df = df.copy()
        df["atr"] = atr(df, self.atr_period)
        df["signal"] = signal.reindex(df.index).fillna(0)

        for _, row in df.iterrows():
            if self.position is not None:
                self._check_exit(row)
            if self.position is None and row["signal"] != 0 and not pd.isna(row["atr"]) and row["atr"] > 0:
                side = "long" if row["signal"] > 0 else "short"
                if side == "short" and not self.allow_shorts:
                    pass
                else:
                    self._enter(row, side)

            equity = self.capital
            if self.position is not None:
                equity += self._unrealized_pnl(row["close"])
            self.equity_curve.append({"timestamp": row["timestamp"], "equity": equity})

        if self.position is not None:
            last_row = df.iloc[-1]
            self._close(last_row["timestamp"], last_row["close"], "end_of_data")

        return pd.DataFrame(self.equity_curve)

    def _unrealized_pnl(self, price):
        pos = self.position
        direction = 1 if pos.side == "long" else -1
        return (price - pos.entry_price) * direction * pos.size

    def _enter(self, row, side):
        stop_distance = row["atr"] * self.atr_stop_mult
        sizing = calculate_position_size(
            self.capital, row["close"], stop_distance, side, self.risk_pct, self.max_leverage,
        )
        direction = 1 if side == "long" else -1
        target_price = row["close"] + direction * stop_distance * self.rr_multiple

        entry_fee = sizing.position_value * self.fee_pct
        self.capital -= entry_fee

        self.position = SimpleTrade(
            side=side, entry_time=row["timestamp"], entry_price=row["close"],
            size=sizing.size, leverage=sizing.leverage,
            stop_price=sizing.stop_price, target_price=target_price,
        )

    def _check_exit(self, row):
        pos = self.position
        if pos.side == "long":
            stop_hit = row["low"] <= pos.stop_price
            target_hit = row["high"] >= pos.target_price
        else:
            stop_hit = row["high"] >= pos.stop_price
            target_hit = row["low"] <= pos.target_price

        if stop_hit:
            self._close(row["timestamp"], pos.stop_price, "stop_loss")
        elif target_hit:
            self._close(row["timestamp"], pos.target_price, "target")

    def _close(self, timestamp, price, reason):
        pos = self.position
        direction = 1 if pos.side == "long" else -1
        pnl = (price - pos.entry_price) * direction * pos.size
        pnl -= pos.size * price * self.fee_pct

        self.capital += pnl
        pos.exit_time = timestamp
        pos.exit_price = price
        pos.exit_reason = reason
        pos.pnl = pnl
        pos.pnl_pct = pnl / self.initial_capital

        self.trades.append(pos)
        self.position = None
