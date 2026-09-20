"""Event-getriebene Backtest-Engine für die reine Inside-Bar-Ausbruchs-Strategie.

Regeln:
- Entry: Ausbruch aus einer Inside-Bar-Konsolidierung (siehe strategy_insidebar.py),
  in Ausbruchsrichtung (Follow).
- Stop-Loss: gegenüberliegende Seite der Mother-Bar-Range (klassischer, musterinhärenter
  Stop - keine ATR-Berechnung nötig).
- Take-Profit: "Measured Move" - Mother-Bar-Rangehöhe * `target_range_multiple`, projiziert
  vom Einstiegspreis in Ausbruchsrichtung.
- Keine weiteren Filter (Trend/Volatilität/Ablehnungskerze) - bewusst die einfache,
  eigenständige Variante zum Vergleich mit der Fade-Strategie.
"""

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from .risk import calculate_position_size
from .strategy_insidebar import detect_breakouts


@dataclass
class Trade:
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    size: float
    leverage: float
    stop_price: float
    target_price: float
    risk_amount: float
    mother_range: float
    inside_bars: int
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0


class InsideBarBacktester:
    def __init__(
        self,
        capital=10_000.0,
        risk_pct=0.02,
        max_leverage=2.5,
        min_inside_bars=2,
        target_range_multiple=1.0,
        allow_shorts=True,
        fee_pct=0.0004,
        cooldown_bars=0,
    ):
        self.initial_capital = capital
        self.capital = capital
        self.risk_pct = risk_pct
        self.max_leverage = max_leverage
        self.min_inside_bars = min_inside_bars
        self.target_range_multiple = target_range_multiple
        self.allow_shorts = allow_shorts
        self.fee_pct = fee_pct
        self.cooldown_bars = cooldown_bars

        self.trades: List[Trade] = []
        self.equity_curve = []
        self.position: Optional[Trade] = None
        self._bars_since_exit = cooldown_bars

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        df = detect_breakouts(df, self.min_inside_bars)

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
        signal = row["breakout"]
        if signal is None or (signal == "short" and not self.allow_shorts):
            return

        mother_range = row["mother_high"] - row["mother_low"]
        if pd.isna(mother_range) or mother_range <= 0:
            return

        entry_price = row["close"]
        stop_price = row["mother_low"] if signal == "long" else row["mother_high"]
        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            return

        direction = 1 if signal == "long" else -1
        target_price = entry_price + direction * mother_range * self.target_range_multiple

        sizing = calculate_position_size(
            self.capital, entry_price, stop_distance, signal,
            self.risk_pct, self.max_leverage,
        )

        entry_fee = sizing.position_value * self.fee_pct
        self.capital -= entry_fee

        self.position = Trade(
            side=signal,
            entry_time=row["timestamp"],
            entry_price=entry_price,
            size=sizing.size,
            leverage=sizing.leverage,
            stop_price=stop_price,
            target_price=target_price,
            risk_amount=sizing.risk_amount,
            mother_range=mother_range,
            inside_bars=int(row["inside_bars"]) if not pd.isna(row["inside_bars"]) else 0,
        )

    def _check_exit(self, row):
        pos = self.position
        if pos.side == "long":
            stop_hit = row["low"] <= pos.stop_price
            target_hit = row["high"] >= pos.target_price
        else:
            stop_hit = row["high"] >= pos.stop_price
            target_hit = row["low"] <= pos.target_price

        # Konservativ: trifft eine Kerze beide, zählt der Stop (wie in backtest.py).
        if stop_hit:
            self._close_position(row["timestamp"], pos.stop_price, "stop_loss")
        elif target_hit:
            self._close_position(row["timestamp"], pos.target_price, "target")

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
