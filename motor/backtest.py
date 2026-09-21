"""Backtest-Engine.

Läuft für jede Strategie identisch ab: Die Strategie liefert nur die
Signale (Kaufsignal, Verkaufssignal, Stop-Loss-Preis, Positionsgröße),
der Motor kümmert sich um Kontostand, Gebühren und Auswertung. Dadurch
braucht eine neue Strategie keine eigene Backtest-Logik.
"""

import importlib
import inspect
import pkgutil
from dataclasses import dataclass, field

import pandas as pd

import strategien as strategien_paket
from strategien.basis import Strategie


@dataclass
class Trade:
    einstieg_zeit: object
    einstieg_preis: float
    menge: float
    stop_preis: float = 0.0
    kontostand_vor_trade: float = 0.0
    ausstieg_zeit: object = None
    ausstieg_preis: float = None
    grund: str = ""
    gewinn: float = 0.0


@dataclass
class BacktestErgebnis:
    strategie_name: str
    start_kapital: float
    end_kapital: float
    trades: list = field(default_factory=list)

    @property
    def anzahl_trades(self) -> int:
        return len(self.trades)

    @property
    def trefferquote(self) -> float:
        if not self.trades:
            return 0.0
        gewinner = sum(1 for t in self.trades if t.gewinn > 0)
        return gewinner / len(self.trades) * 100

    @property
    def gewinn_gesamt(self) -> float:
        return self.end_kapital - self.start_kapital

    @property
    def gewinn_pct(self) -> float:
        if self.start_kapital == 0:
            return 0.0
        return self.gewinn_gesamt / self.start_kapital * 100

    def zusammenfassung(self) -> str:
        return (
            f"{self.strategie_name}\n"
            f"  Trades:       {self.anzahl_trades}\n"
            f"  Trefferquote: {self.trefferquote:.1f} %\n"
            f"  Gewinn:       {self.gewinn_gesamt:.2f} USDT ({self.gewinn_pct:+.2f} %)\n"
            f"  Endkapital:   {self.end_kapital:.2f} USDT"
        )


def backtest_ausfuehren(
    strategie: Strategie,
    daten: pd.DataFrame,
    start_kapital: float = 1000.0,
    gebuehr_pct: float = 0.001,
) -> BacktestErgebnis:
    """Führt einen Backtest einer einzelnen Strategie gegen gespeicherte
    Kerzen aus. `gebuehr_pct` wird pro Trade-Seite (Kauf und Verkauf
    getrennt) abgezogen, Standard 0.001 = 0.1 %."""
    kontostand = start_kapital
    position: Trade | None = None
    trades: list[Trade] = []

    for i in range(2, len(daten)):
        fenster = daten.iloc[: i + 1]
        kerze = daten.iloc[i]
        preis = float(kerze["close"])

        if position is None:
            if strategie.kaufsignal(fenster):
                menge = strategie.positionsgroesse(kontostand, preis)
                if menge <= 0:
                    continue
                kosten = menge * preis
                gebuehr = kosten * gebuehr_pct
                if kosten + gebuehr > kontostand:
                    continue

                kontostand_vor = kontostand
                kontostand -= kosten + gebuehr
                position = Trade(
                    einstieg_zeit=kerze["timestamp"],
                    einstieg_preis=preis,
                    menge=menge,
                    stop_preis=strategie.stop_loss_preis(preis, fenster),
                    kontostand_vor_trade=kontostand_vor,
                )
        else:
            stop_ausgeloest = float(kerze["low"]) <= position.stop_preis
            verkaufssignal = strategie.verkaufssignal(fenster)

            if stop_ausgeloest or verkaufssignal:
                ausstiegspreis = position.stop_preis if stop_ausgeloest else preis
                erloes = position.menge * ausstiegspreis
                gebuehr = erloes * gebuehr_pct
                kontostand += erloes - gebuehr

                position.ausstieg_zeit = kerze["timestamp"]
                position.ausstieg_preis = ausstiegspreis
                position.grund = "Stop-Loss" if stop_ausgeloest else "Verkaufssignal"
                position.gewinn = kontostand - position.kontostand_vor_trade
                trades.append(position)
                position = None

    # Offene Position am Ende zum letzten Kurs schließen, damit die
    # Auswertung vollständig ist.
    if position is not None:
        letzter_preis = float(daten.iloc[-1]["close"])
        erloes = position.menge * letzter_preis
        gebuehr = erloes * gebuehr_pct
        kontostand += erloes - gebuehr

        position.ausstieg_zeit = daten.iloc[-1]["timestamp"]
        position.ausstieg_preis = letzter_preis
        position.grund = "Ende des Backtests"
        position.gewinn = kontostand - position.kontostand_vor_trade
        trades.append(position)

    return BacktestErgebnis(
        strategie_name=strategie.name,
        start_kapital=start_kapital,
        end_kapital=kontostand,
        trades=trades,
    )


def alle_strategien_laden() -> list[Strategie]:
    """Findet automatisch jede Strategie-Klasse in strategien/*.py."""
    gefundene = []
    for _, modulname, _ in pkgutil.iter_modules(strategien_paket.__path__):
        if modulname == "basis":
            continue
        modul = importlib.import_module(f"strategien.{modulname}")
        for _, klasse in inspect.getmembers(modul, inspect.isclass):
            if (
                issubclass(klasse, Strategie)
                and klasse is not Strategie
                and klasse.__module__ == modul.__name__
            ):
                gefundene.append(klasse())
    return gefundene


def alle_strategien_vergleichen(
    daten: pd.DataFrame,
    start_kapital: float = 1000.0,
    gebuehr_pct: float = 0.001,
) -> list[BacktestErgebnis]:
    """Testet jede gefundene Strategie mit denselben Daten und sortiert
    das Ergebnis nach Gewinn (bester zuerst)."""
    ergebnisse = [
        backtest_ausfuehren(strategie, daten, start_kapital, gebuehr_pct)
        for strategie in alle_strategien_laden()
    ]
    ergebnisse.sort(key=lambda e: e.gewinn_gesamt, reverse=True)
    return ergebnisse
