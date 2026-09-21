"""Live-Handel auf dem Bybit-Testnet.

Nutzt dieselben Strategie-Signale wie der Backtest (kaufsignal,
verkaufssignal, stop_loss_preis, positionsgroesse), platziert aber
echte Orders über ccxt - allerdings ausschließlich gegen das
Bybit-Testnet (Fake-Guthaben, kein echtes Geld).

Sicherheits-Hinweis: `exchange.set_sandbox_mode(True)` ist fest
einprogrammiert und wird nicht über Konfiguration abschaltbar gemacht,
damit dieser Bot nicht versehentlich mit echtem Geld handeln kann.
"""

import os
import time
from datetime import datetime, timezone

import ccxt
import pandas as pd
from dotenv import load_dotenv

from strategien.basis import Strategie


def _exchange_erstellen() -> ccxt.bybit:
    load_dotenv()
    api_key = os.getenv("BYBIT_API_KEY")
    api_secret = os.getenv("BYBIT_API_SECRET")
    if not api_key or not api_secret:
        raise SystemExit(
            "Fehler: BYBIT_API_KEY / BYBIT_API_SECRET fehlen in der .env-Datei.\n"
            "Kopiere .env.example zu .env und trage deine Bybit-TESTNET-Schlüssel ein "
            "(https://testnet.bybit.com)."
        )

    exchange = ccxt.bybit(
        {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )
    exchange.set_sandbox_mode(True)  # Nur Testnet - bewusst nicht konfigurierbar.
    return exchange


def live_handel_starten(
    strategie: Strategie,
    symbol: str = "BTC/USDT",
    timeframe: str = "1m",
    ueberpruef_intervall_sek: int = 30,
) -> None:
    exchange = _exchange_erstellen()
    print(f"Live-Modus (Bybit TESTNET) gestartet: {strategie.name} auf {symbol} ({timeframe})")
    print("Beenden mit Strg+C.\n")

    position = None  # dict: menge, einstiegspreis, stop_preis

    while True:
        try:
            kerzen = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=200)
            daten = pd.DataFrame(kerzen, columns=["timestamp", "open", "high", "low", "close", "volume"])
            daten["timestamp"] = pd.to_datetime(daten["timestamp"], unit="ms")

            preis = float(daten.iloc[-1]["close"])
            zeit = datetime.now(timezone.utc).strftime("%H:%M:%S")

            if position is None:
                if strategie.kaufsignal(daten):
                    guthaben = exchange.fetch_balance()
                    usdt_frei = guthaben.get("USDT", {}).get("free", 0) or 0
                    menge = strategie.positionsgroesse(usdt_frei, preis)
                    if menge > 0:
                        exchange.create_market_buy_order(symbol, menge)
                        stop_preis = strategie.stop_loss_preis(preis, daten)
                        position = {"menge": menge, "einstiegspreis": preis, "stop_preis": stop_preis}
                        print(f"[{zeit}] KAUF: {menge:.6f} {symbol} @ {preis:.2f} USDT (Stop-Loss: {stop_preis:.2f})")
                    else:
                        print(f"[{zeit}] Kaufsignal, aber Guthaben zu gering für einen Trade.")
                else:
                    print(f"[{zeit}] Kein Signal. Preis: {preis:.2f} USDT")
            else:
                stop_ausgeloest = preis <= position["stop_preis"]
                verkaufssignal = strategie.verkaufssignal(daten)

                if stop_ausgeloest or verkaufssignal:
                    exchange.create_market_sell_order(symbol, position["menge"])
                    grund = "Stop-Loss" if stop_ausgeloest else "Verkaufssignal"
                    print(f"[{zeit}] VERKAUF ({grund}): {position['menge']:.6f} {symbol} @ {preis:.2f} USDT")
                    position = None
                else:
                    print(f"[{zeit}] Position offen. Preis: {preis:.2f} USDT (Stop: {position['stop_preis']:.2f})")

        except ccxt.NetworkError as fehler:
            print(f"Netzwerkfehler, versuche es weiter: {fehler}")
        except ccxt.ExchangeError as fehler:
            print(f"Börsenfehler: {fehler}")

        time.sleep(ueberpruef_intervall_sek)
