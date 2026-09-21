"""Einstiegspunkt für den Bybit BTC/USDT Trading-Bot.

Befehle:
  python main.py lade-daten --von 2024-01-01 --bis 2024-06-01
  python main.py backtest --strategie beispiel_sma_cross --von 2024-01-01 --bis 2024-06-01
  python main.py backtest --alle --von 2024-01-01 --bis 2024-06-01
  python main.py live --strategie beispiel_sma_cross

Mit --help an jedem Befehl gibt es die volle Liste der Optionen, z. B.:
  python main.py backtest --help
"""

import argparse
import importlib
import inspect

from motor.backtest import alle_strategien_vergleichen, backtest_ausfuehren
from motor.daten import lade_historische_daten
from motor.live import live_handel_starten
from strategien.basis import Strategie


def _strategie_laden(name: str) -> Strategie:
    modul = importlib.import_module(f"strategien.{name}")
    for _, klasse in inspect.getmembers(modul, inspect.isclass):
        if issubclass(klasse, Strategie) and klasse is not Strategie and klasse.__module__ == modul.__name__:
            return klasse()
    raise SystemExit(f"Keine Strategie-Klasse in strategien/{name}.py gefunden.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bybit BTC/USDT Trading-Bot")
    unterbefehle = parser.add_subparsers(dest="befehl", required=True)

    p_daten = unterbefehle.add_parser("lade-daten", help="Historische Kursdaten von Bybit laden und lokal speichern")
    p_daten.add_argument("--symbol", default="BTC/USDT")
    p_daten.add_argument("--timeframe", default="1h")
    p_daten.add_argument("--von", required=True, help="Startdatum, z. B. 2024-01-01")
    p_daten.add_argument("--bis", default=None, help="Enddatum, z. B. 2024-06-01 (Standard: heute)")

    p_backtest = unterbefehle.add_parser("backtest", help="Strategie(n) gegen gespeicherte Kursdaten testen")
    p_backtest.add_argument("--strategie", default=None, help="Dateiname in strategien/ ohne .py, z. B. beispiel_sma_cross")
    p_backtest.add_argument("--alle", action="store_true", help="Alle Strategien in strategien/ testen und vergleichen")
    p_backtest.add_argument("--symbol", default="BTC/USDT")
    p_backtest.add_argument("--timeframe", default="1h")
    p_backtest.add_argument("--von", required=True)
    p_backtest.add_argument("--bis", default=None)
    p_backtest.add_argument("--kapital", type=float, default=1000.0)
    p_backtest.add_argument("--gebuehr", type=float, default=0.001, help="Gebühr pro Trade-Seite, Standard 0.001 = 0.1 %%")

    p_live = unterbefehle.add_parser("live", help="Live-Handel auf dem Bybit-Testnet (API-Keys aus .env)")
    p_live.add_argument("--strategie", required=True)
    p_live.add_argument("--symbol", default="BTC/USDT")
    p_live.add_argument("--timeframe", default="1m")
    p_live.add_argument("--intervall", type=int, default=30, help="Sekunden zwischen den Prüfungen")

    args = parser.parse_args()

    if args.befehl == "lade-daten":
        daten = lade_historische_daten(args.symbol, args.timeframe, args.von, args.bis, neu_laden=True)
        print(f"{len(daten)} Kerzen gespeichert für {args.symbol} ({args.timeframe}).")

    elif args.befehl == "backtest":
        daten = lade_historische_daten(args.symbol, args.timeframe, args.von, args.bis)
        if len(daten) == 0:
            raise SystemExit("Keine Daten gefunden. Zuerst 'python main.py lade-daten ...' ausführen.")

        if args.alle:
            ergebnisse = alle_strategien_vergleichen(daten, args.kapital, args.gebuehr)
            print(f"\nVergleich aller Strategien ({len(daten)} Kerzen, {args.symbol} {args.timeframe}):\n")
            print(f"{'Strategie':<35}{'Trades':>8}{'Trefferquote':>15}{'Gewinn':>15}")
            print("-" * 73)
            for e in ergebnisse:
                print(f"{e.strategie_name:<35}{e.anzahl_trades:>8}{e.trefferquote:>14.1f}%{e.gewinn_gesamt:>14.2f} $")
        else:
            if not args.strategie:
                raise SystemExit("Bitte --strategie <name> oder --alle angeben.")
            strategie = _strategie_laden(args.strategie)
            ergebnis = backtest_ausfuehren(strategie, daten, args.kapital, args.gebuehr)
            print()
            print(ergebnis.zusammenfassung())

    elif args.befehl == "live":
        strategie = _strategie_laden(args.strategie)
        live_handel_starten(strategie, args.symbol, args.timeframe, args.intervall)


if __name__ == "__main__":
    main()
