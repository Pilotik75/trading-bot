"""Event-getriebene Backtest-Engine für die Fade-Strategie.

Ablauf pro Trade:
1. Kandidat: Volumenspitze + Ausbruch über/unter die Range + Volatilitätsexpansion,
   gegen den übergeordneten Trend gefadet (siehe strategy.entry_signal).
2. Bestätigung: Preis muss `breakout_confirm_bars` Kerzen in Folge jenseits des
   ursprünglichen Ausbruchs-Levels bleiben, bevor die (gefadete) Position tatsächlich
   eröffnet wird (filtert Ausbrüche, die sofort wieder in die Range zurückfallen).
   Zusätzlich muss die Bestätigungskerze selbst eine Ablehnungs-/Erschöpfungskerze sein
   (`wick_body_ratio`, siehe strategy.has_rejection_wick) - nur echte Erschöpfungssignale
   werden gefadet, nicht jeder x-beliebige bestätigte Ausbruch.
3. Stop-Straffung: Erreicht der Preis schon vorher `stop_tighten_r_multiple` x
   Stop-Distanz in die Gewinnzone (typischerweise vor dem Teilausstieg), wird der Stop
   von der vollen Anfangs-Distanz auf `stop_tighten_to_r_multiple` x Stop-Distanz
   nachgezogen - reduziert den maximalen Verlust für Trades, die sich zunächst erholen,
   dann aber doch scheitern, bevor sie den Teilausstieg erreichen.
4. Teilausstieg beim ersten Schub: Erreicht der Preis `partial_tp_r_multiple` x
   Stop-Distanz in die Gewinnzone, wird so viel der Position geschlossen, dass der
   realisierte Gewinn genau die potenziellen Stop-Loss-Kosten deckt. Der Stop der
   Restposition wird danach auf den Einstiegspreis (Breakeven) gezogen, d.h. der Rest
   läuft ab diesem Punkt risikofrei.
5. Exit der Restposition: Stop-Loss oder Gegenbewegung (Reversal), wie zuvor.
"""

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from .risk import calculate_position_size
from .strategy import add_indicators, add_trend_filter, entry_signal, has_rejection_wick, reversal_exit


@dataclass
class Trade:
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    size: float                          # ursprüngliche Positionsgröße bei Entry
    leverage: float
    stop_price: float
    risk_amount: float
    stop_distance: float = 0.0           # ursprüngliche Stop-Distanz bei Entry (fix, für R-Berechnungen)
    stop_tightened: bool = False
    remaining_size: float = 0.0
    partial_time: Optional[pd.Timestamp] = None
    partial_price: Optional[float] = None
    partial_size: float = 0.0
    partial_pnl: float = 0.0
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0                     # kumulierter realisierter PnL (Partial + Final)
    pnl_pct: float = 0.0


class Backtester:
    def __init__(
        self,
        capital=10_000.0,
        risk_pct=0.02,
        max_leverage=2.5,
        lookback=20,
        volume_multiplier=2.0,
        atr_period=14,
        atr_multiplier=4.0,
        ema_fast=9,
        allow_shorts=True,
        fee_pct=0.0004,
        cooldown_bars=0,
        breakout_confirm_bars=3,
        partial_tp_r_multiple=1.0,
        stop_tighten_r_multiple=None,
        stop_tighten_to_r_multiple=-0.5,
        trend_timeframe="1h",
        trend_ema=50,
        vol_lookback=100,
        vol_expansion_multiplier=1.2,
        wick_body_ratio=1.0,
        confluence_fn=None,
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
        self.breakout_confirm_bars = max(1, breakout_confirm_bars)
        self.partial_tp_r_multiple = partial_tp_r_multiple
        self.stop_tighten_r_multiple = stop_tighten_r_multiple
        self.stop_tighten_to_r_multiple = stop_tighten_to_r_multiple
        self.trend_timeframe = trend_timeframe
        self.trend_ema = trend_ema
        self.vol_lookback = vol_lookback
        self.vol_expansion_multiplier = vol_expansion_multiplier
        self.wick_body_ratio = wick_body_ratio
        # Optionaler zusätzlicher Bestätigungsfilter: callable(row, trade_side) -> bool.
        # Läuft auf der Bestätigungskerze, zusätzlich zu Ablehnungskerze/Trend/Volumen - z.B.
        # ein klassischer Indikator (RSI, Stochastic, ...), der in dieselbe Richtung zeigen muss.
        self.confluence_fn = confluence_fn

        self.trades: List[Trade] = []
        self.equity_curve = []
        self.position: Optional[Trade] = None
        self._bars_since_exit = cooldown_bars
        self._pending = None  # Kandidat, der noch auf Bestätigung wartet

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        df = add_indicators(df, self.lookback, self.atr_period, self.ema_fast, self.vol_lookback)
        df = add_trend_filter(df, self.trend_timeframe, self.trend_ema)

        for _, row in df.iterrows():
            if self.position is not None:
                self._check_stop_tighten(row)
            if self.position is not None:
                self._check_partial_tp(row)
            if self.position is not None:
                self._check_exit(row)

            if self.position is None:
                if self._bars_since_exit < self.cooldown_bars:
                    self._bars_since_exit += 1
                    self._pending = None
                else:
                    self._check_candidate(row)

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
        return (price - pos.entry_price) * direction * pos.remaining_size

    def _check_candidate(self, row):
        if pd.isna(row["atr"]) or row["atr"] <= 0:
            self._pending = None
            return

        if self._pending is None:
            signal = entry_signal(row, self.volume_multiplier, self.allow_shorts, self.vol_expansion_multiplier)
            if signal is None:
                return
            level = row["range_high"] if signal["breakout_side"] == "long" else row["range_low"]
            self._pending = {
                "breakout_side": signal["breakout_side"],
                "trade_side": signal["trade_side"],
                "level": level,
                "confirm_count": 1,
            }
            if self.breakout_confirm_bars == 1:
                self._execute_entry(row)
            return

        pending = self._pending
        held = (
            (row["close"] > pending["level"]) if pending["breakout_side"] == "long"
            else (row["close"] < pending["level"])
        )
        if not held:
            self._pending = None
            return

        pending["confirm_count"] += 1
        if pending["confirm_count"] >= self.breakout_confirm_bars:
            self._execute_entry(row)

    def _execute_entry(self, row):
        signal = self._pending["trade_side"]
        breakout_side = self._pending["breakout_side"]
        self._pending = None

        if not has_rejection_wick(row, breakout_side, self.wick_body_ratio):
            return

        if self.confluence_fn is not None and not self.confluence_fn(row, signal):
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
            stop_distance=stop_distance,
            remaining_size=sizing.size,
        )

    def _check_stop_tighten(self, row):
        pos = self.position
        if self.stop_tighten_r_multiple is None or pos.stop_tightened or pos.partial_time is not None:
            return

        direction = 1 if pos.side == "long" else -1
        trigger_price = pos.entry_price + direction * self.stop_tighten_r_multiple * pos.stop_distance

        favorable_extreme = row["high"] if pos.side == "long" else row["low"]
        reached = favorable_extreme >= trigger_price if pos.side == "long" else favorable_extreme <= trigger_price
        if not reached:
            return

        new_stop = pos.entry_price + direction * self.stop_tighten_to_r_multiple * pos.stop_distance
        # Nur nachziehen, wenn das den Stop tatsächlich näher an den Preis bringt.
        improves = new_stop > pos.stop_price if pos.side == "long" else new_stop < pos.stop_price
        if improves:
            pos.stop_price = new_stop
        pos.stop_tightened = True

    def _check_partial_tp(self, row):
        pos = self.position
        if pos.partial_time is not None:
            return

        direction = 1 if pos.side == "long" else -1
        stop_distance = pos.stop_distance
        target_price = pos.entry_price + direction * self.partial_tp_r_multiple * stop_distance

        favorable_extreme = row["high"] if pos.side == "long" else row["low"]
        reached = favorable_extreme >= target_price if pos.side == "long" else favorable_extreme <= target_price
        if not reached:
            return

        price_move = abs(target_price - pos.entry_price)
        if price_move <= 0:
            return

        qty = min(pos.risk_amount / price_move, pos.remaining_size)
        if qty <= 0:
            return

        pnl = direction * (target_price - pos.entry_price) * qty
        pnl -= qty * target_price * self.fee_pct

        self.capital += pnl
        pos.remaining_size -= qty
        pos.partial_time = row["timestamp"]
        pos.partial_price = target_price
        pos.partial_size = qty
        pos.partial_pnl = pnl
        pos.pnl += pnl

        # Restposition ist nun "risikofrei": Stop auf Einstiegspreis nachziehen.
        pos.stop_price = pos.entry_price

    def _check_exit(self, row):
        pos = self.position
        stop_hit = (row["low"] <= pos.stop_price) if pos.side == "long" else (row["high"] >= pos.stop_price)
        if stop_hit:
            if pos.partial_time is not None:
                reason = "breakeven_stop"
            elif pos.stop_tightened:
                reason = "tightened_stop"
            else:
                reason = "stop_loss"
            self._close_position(row["timestamp"], pos.stop_price, reason)
            return

        # Der EMA-Reversal-Exit prüft kurzfristiges Momentum gegen die Position. Bei einer
        # Fade-Position ist das direkt nach Entry meist noch der Fall (man kauft ja bewusst
        # gegen die gerade laufende Bewegung) - das würde die Position sofort wieder killen,
        # bevor die Mean-Reversion überhaupt wirken konnte. Daher erst aktiv, nachdem der
        # Teilausstieg bestätigt hat, dass sich der Preis tatsächlich erholt hat.
        if pos.partial_time is not None and reversal_exit(row, pos.side):
            self._close_position(row["timestamp"], row["close"], "reversal")

    def _close_position(self, timestamp, price, reason):
        pos = self.position
        direction = 1 if pos.side == "long" else -1
        pnl = (price - pos.entry_price) * direction * pos.remaining_size

        exit_fee = pos.remaining_size * price * self.fee_pct
        pnl -= exit_fee

        self.capital += pnl

        pos.exit_time = timestamp
        pos.exit_price = price
        pos.exit_reason = reason
        pos.pnl += pnl
        pos.pnl_pct = pos.pnl / self.initial_capital

        self.trades.append(pos)
        self.position = None
        self._bars_since_exit = 0
