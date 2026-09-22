"""Beispiel-Strategie: RSI Mean-Reversion.

Regeln:
- Kauf, wenn der RSI (14 Kerzen) unter 30 fällt (Markt gilt als "überverkauft",
  Wette auf eine Erholung).
- Verkauf, wenn der RSI über 70 steigt (Markt gilt als "überkauft").
- Stop-Loss: 3 % unter dem Einstiegspreis.
- Einsatz: 1 % des Kontostands pro Trade.

Gegenteiliges Prinzip zur SMA-Crossover-Strategie: Statt einem Trend zu
folgen, wettet diese Strategie auf eine Rückkehr zum Durchschnitt.
"""

import pandas as pd

from strategien.basis import Strategie


class BeispielRsiMeanReversion(Strategie):
    name = "Beispiel: RSI Mean-Reversion (14)"
    einsatz_pct = 0.01     # 1 % vom Konto pro Trade
    stop_loss_pct = 0.03   # 3 % Stop-Loss unter Einstieg

    rsi_periode = 14
    rsi_kaufen_unter = 30
    rsi_verkaufen_ueber = 70

    def _rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gewinn = delta.clip(lower=0)
        verlust = -delta.clip(upper=0)
        avg_gewinn = gewinn.rolling(self.rsi_periode).mean()
        avg_verlust = verlust.rolling(self.rsi_periode).mean()
        rs = avg_gewinn / avg_verlust.replace(0, 1e-10)
        return 100 - (100 / (1 + rs))

    def kaufsignal(self, daten: pd.DataFrame) -> bool:
        if len(daten) < self.rsi_periode + 1:
            return False
        rsi = self._rsi(daten["close"])
        return bool(rsi.iloc[-1] < self.rsi_kaufen_unter)

    def verkaufssignal(self, daten: pd.DataFrame) -> bool:
        if len(daten) < self.rsi_periode + 1:
            return False
        rsi = self._rsi(daten["close"])
        return bool(rsi.iloc[-1] > self.rsi_verkaufen_ueber)

    def stop_loss_preis(self, einstiegspreis: float, daten: pd.DataFrame) -> float:
        return einstiegspreis * (1 - self.stop_loss_pct)
