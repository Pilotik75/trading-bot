"""Event-getriebene Backtest-Engine für die Volumen-Ausbruch-Strategie."""

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from .risk import calculate_position_size
from .strategy import add_indicators, entry_signal, reversal_exit


@dataclass
class Trade:
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    size: float
    leverage: float
    stop_price: float
    risk_amount: float
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0


class Backtester:
    def __init__(
        self,
        capital=10_000.0,
        risk_pct=0.02,
        max_leverage=5.0,
        lookback=20,
        volume_multiplier=2.0,
        atr_period=14,
        atr_multiplier=1.5,
        ema_fast=9,
        allow_shorts=True,
        fee_pct=0.0004,
        cooldown_bars=0,
    ):
        self.initial_capital = capital
        self.capital = capital
        self.risk_pct = risk_pct
        self.max_leverage = max_leverage
        self.lookback = lookback
        self.volume_multiplier = volume_multiplier
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.ema_fast = ema_fast
        self.allow_shorts = allow_shorts
        self.fee_pct = fee_pct
        self.cooldown_bars = cooldown_bars

        self.trades: List[Trade] = []
        self.equity_curve = []
        self.position: Optional[Trade] = None
        self._bars_since_exit = cooldown_bars

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        df = add_indicators(df, self.lookback, self.atr_period, self.ema_fast)

        for _, row in df.iterrows():
            if self.position is not None:
                self._check_exit(row)
            if self.position is None:
                if self._bars_since_exit < self.cooldown_bars:
                    self._bars_since_exit += 1
                else:
                    self._check_entry(row)

            equity = self.capital
            if self.position is not None:
                equity += self._unrealized_pnl(row["close"])
            self.equity_curve.append({"timestamp": row["timestamp"], "equity": equity})

        if self.position is not None:
            last_row = df.iloc[-1]
            self._close_position(last_row["timestamp"], last_row["close"], "end_of_data")

        return pd.DataFrame(self.equity_curve)

    def _unrealized_pnl(self, price):
        pos = self.position
        direction = 1 if pos.side == "long" else -1
        return (price - pos.entry_price) * direction * pos.size

    def _check_entry(self, row):
        signal = entry_signal(row, self.volume_multiplier, self.allow_shorts)
        if signal is None or pd.isna(row["atr"]) or row["atr"] <= 0:
            return

        stop_distance = row["atr"] * self.atr_multiplier
        sizing = calculate_position_size(
            self.capital, row["close"], stop_distance, signal,
            self.risk_pct, self.max_leverage,
        )

        entry_fee = sizing.position_value * self.fee_pct
        self.capital -= entry_fee

        self.position = Trade(
            side=signal,
            entry_time=row["timestamp"],
            entry_price=row["close"],
            size=sizing.size,
            leverage=sizing.leverage,
            stop_price=sizing.stop_price,
            risk_amount=sizing.risk_amount,
        )

    def _check_exit(self, row):
        pos = self.position
        stop_hit = (row["low"] <= pos.stop_price) if pos.side == "long" else (row["high"] >= pos.stop_price)
        if stop_hit:
            self._close_position(row["timestamp"], pos.stop_price, "stop_loss")
            return

        if reversal_exit(row, pos.side):
            self._close_position(row["timestamp"], row["close"], "reversal")

    def _close_position(self, timestamp, price, reason):
        pos = self.position
        direction = 1 if pos.side == "long" else -1
        pnl = (price - pos.entry_price) * direction * pos.size

        exit_fee = pos.size * price * self.fee_pct
        pnl -= exit_fee

        self.capital += pnl

        pos.exit_time = timestamp
        pos.exit_price = price
        pos.exit_reason = reason
        pos.pnl = pnl
        pos.pnl_pct = pnl / self.initial_capital

        self.trades.append(pos)
        self.position = None
        self._bars_since_exit = 0
