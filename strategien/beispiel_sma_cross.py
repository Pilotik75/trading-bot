"""Beispiel-Strategie: Gleitender-Durchschnitt-Crossover (SMA Crossover).

Regeln:
- Kauf, wenn der schnelle Durchschnitt (10 Kerzen) von unten nach oben
  durch den langsamen Durchschnitt (30 Kerzen) kreuzt (Aufwärtstrend
  beginnt).
- Verkauf, wenn der schnelle Durchschnitt wieder unter den langsamen
  Durchschnitt fällt.
- Stop-Loss: 2 % unter dem Einstiegspreis.
- Einsatz: 1 % des Kontostands pro Trade.

Das ist eine einfache Trendfolge-Strategie zum Ausprobieren des Motors -
kein Versprechen auf Gewinn, sondern ein Startpunkt zum Kopieren für
eigene Strategien.
"""

import pandas as pd

from strategien.basis import Strategie


class BeispielSmaCross(Strategie):
    name = "Beispiel: SMA Crossover (10/30)"
    einsatz_pct = 0.01     # 1 % vom Konto pro Trade
    stop_loss_pct = 0.02   # 2 % Stop-Loss unter dem Einstieg

    schnell = 10
    langsam = 30

    def _mit_durchschnitten(self, daten: pd.DataFrame) -> pd.DataFrame:
        daten = daten.copy()
        daten["sma_schnell"] = daten["close"].rolling(self.schnell).mean()
        daten["sma_langsam"] = daten["close"].rolling(self.langsam).mean()
        return daten

    def kaufsignal(self, daten: pd.DataFrame) -> bool:
        if len(daten) < self.langsam + 1:
            return False
        d = self._mit_durchschnitten(daten)
        vorher_unten = d["sma_schnell"].iloc[-2] <= d["sma_langsam"].iloc[-2]
        jetzt_oben = d["sma_schnell"].iloc[-1] > d["sma_langsam"].iloc[-1]
        return bool(vorher_unten and jetzt_oben)

    def verkaufssignal(self, daten: pd.DataFrame) -> bool:
        if len(daten) < self.langsam + 1:
            return False
        d = self._mit_durchschnitten(daten)
        vorher_oben = d["sma_schnell"].iloc[-2] >= d["sma_langsam"].iloc[-2]
        jetzt_unten = d["sma_schnell"].iloc[-1] < d["sma_langsam"].iloc[-1]
        return bool(vorher_oben and jetzt_unten)

    def stop_loss_preis(self, einstiegspreis: float, daten: pd.DataFrame) -> float:
        return einstiegspreis * (1 - self.stop_loss_pct)
