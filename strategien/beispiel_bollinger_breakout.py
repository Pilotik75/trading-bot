"""Beispiel-Strategie: Bollinger-Band-Breakout.

Regeln:
- Kauf, wenn der Kurs nach oben aus dem oberen Bollinger-Band ausbricht
  (Kurs war darunter, ist jetzt darüber) - Wette auf einen Ausbruch mit
  Schwung nach oben.
- Verkauf, wenn der Kurs wieder unter das mittlere Band (den gleitenden
  Durchschnitt) fällt.
- Stop-Loss: 2 % unter dem Einstiegspreis.
- Einsatz: 1 % des Kontostands pro Trade.
"""

import pandas as pd

from strategien.basis import Strategie


class BeispielBollingerBreakout(Strategie):
    name = "Beispiel: Bollinger-Breakout (20, 2.0)"
    einsatz_pct = 0.01     # 1 % vom Konto pro Trade
    stop_loss_pct = 0.02   # 2 % Stop-Loss unter Einstieg

    periode = 20
    std_multiplikator = 2.0

    def _baender(self, daten: pd.DataFrame):
        mitte = daten["close"].rolling(self.periode).mean()
        std = daten["close"].rolling(self.periode).std()
        oben = mitte + self.std_multiplikator * std
        return mitte, oben

    def kaufsignal(self, daten: pd.DataFrame) -> bool:
        if len(daten) < self.periode + 1:
            return False
        _, oben = self._baender(daten)
        war_darunter = daten["close"].iloc[-2] <= oben.iloc[-2]
        jetzt_darueber = daten["close"].iloc[-1] > oben.iloc[-1]
        return bool(war_darunter and jetzt_darueber)

    def verkaufssignal(self, daten: pd.DataFrame) -> bool:
        if len(daten) < self.periode + 1:
            return False
        mitte, _ = self._baender(daten)
        return bool(daten["close"].iloc[-1] < mitte.iloc[-1])

    def stop_loss_preis(self, einstiegspreis: float, daten: pd.DataFrame) -> float:
        return einstiegspreis * (1 - self.stop_loss_pct)
