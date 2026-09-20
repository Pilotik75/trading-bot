"""Multi-Timeframe-Variante der Fade-Strategie: Ausbruchsmuster (Kandidat, Bestätigung,
Ablehnungskerze, Trend/Volatilitätsfilter) werden auf einem höheren "Signal-Zeitrahmen"
(z.B. 5m oder 1h) erkannt, aber Einstieg sowie die gesamte Positionsüberwachung (Stop-Loss,
Teilausstieg, Gegenbewegung) laufen auf 1-Minuten-Basis - für präziseres Timing als beim
reinen Warten auf den nächsten 5m-/1h-Kerzenschluss.

Funktionsweise:
1. Die 1m-Rohdaten werden auf den Signal-Zeitrahmen aggregiert (data.resample_ohlcv) und die
   üblichen Fade-Indikatoren darauf berechnet (strategy.add_indicators/add_trend_filter).
   Durch label='right' beim Resampling ist jede aggregierte Kerze mit ihrem Schlusszeitpunkt
   indiziert - ein Signal, das per merge_asof(direction='backward') auf die 1m-Zeitachse
   projiziert wird, sieht an jedem 1m-Balken nur bereits vollständig abgeschlossene
   Signal-Zeitrahmen-Kerzen (kein Lookahead-Bias).
2. Kandidaten-/Bestätigungs-/Ablehnungskerzen-Logik wird nur an den 1m-Balken ausgewertet, an
   denen gerade eine neue Signal-Zeitrahmen-Kerze abgeschlossen wurde ("is_new_signal_bar").
   `breakout_confirm_bars` zählt also Signal-Zeitrahmen-Kerzen, nicht 1m-Kerzen.
3. Sobald ein Trade ausgelöst wird, erfolgt der Einstieg exakt auf dem 1m-Balken, der mit dem
   Abschluss der auslösenden Signal-Zeitrahmen-Kerze zusammenfällt. Ab dann werden Stop-Loss,
   Teilausstieg (2R -> Breakeven) und Gegenbewegung auf JEDEM 1m-Balken geprüft (nicht erst beim
   nächsten Signal-Zeitrahmen-Kerzenschluss) - die Gegenbewegungs-EMA wird dafür direkt auf den
   1m-Daten berechnet (`ema_fast`, Einheit: 1m-Kerzen).
"""

from typing import List, Optional

import pandas as pd

from .backtest import Trade
from .data import resample_ohlcv
from .risk import calculate_position_size
from .strategy import add_indicators, add_trend_filter, entry_signal, has_rejection_wick


class MultiTimeframeBacktester:
    def __init__(
        self,
        capital=10_000.0,
        risk_pct=0.02,
        max_leverage=2.5,
        signal_timeframe="5m",
        lookback=15,
        volume_multiplier=1.5,
        atr_period=14,
        atr_multiplier=1.5,
        ema_fast=9,
        allow_shorts=True,
        fee_pct=0.0004,
        cooldown_bars=0,
        breakout_confirm_bars=3,
        partial_tp_r_multiple=2.0,
        trend_timeframe="1h",
        trend_ema=50,
        vol_lookback=100,
        vol_expansion_multiplier=1.2,
        wick_body_ratio=1.0,
    ):
        self.initial_capital = capital
        self.capital = capital
        self.risk_pct = risk_pct
        self.max_leverage = max_leverage
        self.signal_timeframe = signal_timeframe
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
        self.trend_timeframe = trend_timeframe
        self.trend_ema = trend_ema
        self.vol_lookback = vol_lookback
        self.vol_expansion_multiplier = vol_expansion_multiplier
        self.wick_body_ratio = wick_body_ratio

        self.trades: List[Trade] = []
        self.equity_curve = []
        self.position: Optional[Trade] = None
        self._bars_since_exit = cooldown_bars
        self._pending = None

    def _prepare(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        signal_df = resample_ohlcv(df_1m, self.signal_timeframe)
        signal_df = add_indicators(signal_df, self.lookback, self.atr_period, self.ema_fast, self.vol_lookback)
        signal_df = add_trend_filter(signal_df, self.trend_timeframe, self.trend_ema)

        signal_cols = [
            "timestamp", "open", "high", "low", "close", "volume",
            "avg_volume", "range_high", "range_low", "atr", "atr_long_avg", "trend",
        ]
        signal_df = signal_df[signal_cols].rename(columns={"timestamp": "sig_timestamp"})
        for col in ["open", "high", "low", "close", "volume"]:
            signal_df = signal_df.rename(columns={col: f"sig_{col}"})

        merged = pd.merge_asof(
            df_1m.sort_values("timestamp"),
            signal_df.sort_values("sig_timestamp"),
            left_on="timestamp", right_on="sig_timestamp", direction="backward",
        )
        merged["is_new_signal_bar"] = merged["timestamp"] == merged["sig_timestamp"]
        merged["exec_ema_fast"] = merged["close"].ewm(span=self.ema_fast, adjust=False).mean()
        return merged

    def run(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        df = self._prepare(df_1m)

        for _, row in df.iterrows():
            if self.position is not None:
                self._check_partial_tp(row)
            if self.position is not None:
                self._check_exit(row)

            if self.position is None:
                if self._bars_since_exit < self.cooldown_bars:
                    if row["is_new_signal_bar"]:
                        self._bars_since_exit += 1
                        self._pending = None
                elif row["is_new_signal_bar"]:
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

    def _signal_row(self, row):
        """Baut eine 'row'-ähnliche Sicht mit den Signal-Zeitrahmen-Spaltennamen, wie sie
        strategy.entry_signal/has_rejection_wick erwarten (ohne das 'sig_'-Präfix)."""
        return {
            "avg_volume": row["avg_volume"], "range_high": row["range_high"],
            "range_low": row["range_low"], "atr": row["atr"], "atr_long_avg": row["atr_long_avg"],
            "trend": row["trend"], "volume": row["sig_volume"], "close": row["sig_close"],
            "open": row["sig_open"], "high": row["sig_high"], "low": row["sig_low"],
        }

    def _check_candidate(self, row):
        if pd.isna(row["atr"]) or row["atr"] <= 0:
            self._pending = None
            return

        sig_row = self._signal_row(row)

        if self._pending is None:
            signal = entry_signal(sig_row, self.volume_multiplier, self.allow_shorts, self.vol_expansion_multiplier)
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
                self._execute_entry(row, sig_row)
            return

        pending = self._pending
        held = (
            (sig_row["close"] > pending["level"]) if pending["breakout_side"] == "long"
            else (sig_row["close"] < pending["level"])
        )
        if not held:
            self._pending = None
            return

        pending["confirm_count"] += 1
        if pending["confirm_count"] >= self.breakout_confirm_bars:
            self._execute_entry(row, sig_row)

    def _execute_entry(self, row, sig_row):
        signal = self._pending["trade_side"]
        breakout_side = self._pending["breakout_side"]
        self._pending = None

        if not has_rejection_wick(sig_row, breakout_side, self.wick_body_ratio):
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
            remaining_size=sizing.size,
        )

    def _check_partial_tp(self, row):
        pos = self.position
        if pos.partial_time is not None:
            return

        direction = 1 if pos.side == "long" else -1
        stop_distance = abs(pos.entry_price - pos.stop_price)
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

        pos.stop_price = pos.entry_price

    def _check_exit(self, row):
        pos = self.position
        stop_hit = (row["low"] <= pos.stop_price) if pos.side == "long" else (row["high"] >= pos.stop_price)
        if stop_hit:
            reason = "breakeven_stop" if pos.partial_time is not None else "stop_loss"
            self._close_position(row["timestamp"], pos.stop_price, reason)
            return

        if pos.partial_time is not None and reversal_exit_1m(row, pos.side):
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


def reversal_exit_1m(row, position_side):
    """Wie strategy.reversal_exit, aber gegen die 1m-EMA (exec_ema_fast) statt der
    Signal-Zeitrahmen-EMA - reagiert schneller, passend zur 1m-Positionsüberwachung."""
    if pd.isna(row["exec_ema_fast"]):
        return False
    if position_side == "long":
        return row["close"] < row["exec_ema_fast"]
    if position_side == "short":
        return row["close"] > row["exec_ema_fast"]
    return False
