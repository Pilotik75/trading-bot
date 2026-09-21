"""Basisklasse für alle Handelsstrategien.

Jede neue Strategie erbt von `Strategie` und legt eigene Regeln fest für:
- Kaufsignal
- Verkaufssignal
- Stop-Loss
- Einsatz pro Trade (Positionsgröße)

Der Motor (motor/backtest.py, motor/live.py) kennt nur diese Schnittstelle
und muss für eine neue Strategie nicht verändert werden.
"""

from abc import ABC, abstractmethod

import pandas as pd


class Strategie(ABC):
    # Anzeigename, taucht im Vergleich der Strategien auf.
    name: str = "Unbenannte Strategie"

    # Anteil des Kontostands, der pro Trade eingesetzt wird (1 % = 0.01).
    einsatz_pct: float = 0.01

    @abstractmethod
    def kaufsignal(self, daten: pd.DataFrame) -> bool:
        """True, wenn auf Basis der Kerzen gekauft werden soll.

        `daten` enthält alle Kerzen bis inklusive der aktuellen (letzten
        Zeile). Zukünftige Kerzen sind nicht enthalten (kein Blick in die
        Zukunft / kein Lookahead-Bias).
        """

    @abstractmethod
    def verkaufssignal(self, daten: pd.DataFrame) -> bool:
        """True, wenn eine offene Position regulär verkauft werden soll
        (unabhängig vom Stop-Loss, der vom Motor separat geprüft wird)."""

    @abstractmethod
    def stop_loss_preis(self, einstiegspreis: float, daten: pd.DataFrame) -> float:
        """Berechnet den Preis, bei dem eine offene Position per
        Stop-Loss geschlossen wird."""

    def positionsgroesse(self, kontostand: float, einstiegspreis: float) -> float:
        """Wie viel BTC pro Trade gekauft wird.

        Standard: `einsatz_pct` des Kontostands wird als Einsatz genutzt.
        Kann in einer Strategie überschrieben werden, z. B. für eine
        risikobasierte Positionsgröße.
        """
        einsatz = kontostand * self.einsatz_pct
        return einsatz / einstiegspreis
