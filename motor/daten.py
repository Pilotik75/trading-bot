"""Historische Kursdaten laden.

Ruft OHLCV-Kerzen (Open/High/Low/Close/Volume) über ccxt von Bybit ab und
speichert sie lokal als CSV-Datei im Ordner `daten/` (Cache). Der Backtest
liest diese gespeicherten Daten, statt bei jedem Lauf neu von der Börse
abzufragen.
"""

import os
import time

import ccxt
import pandas as pd

ORDNER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "daten"
)


def _dateiname(symbol: str, timeframe: str) -> str:
    sicher = symbol.replace("/", "")
    return os.path.join(ORDNER, f"{sicher}_{timeframe}.csv")


def lade_historische_daten(
    symbol: str,
    timeframe: str,
    von: str,
    bis: str = None,
    neu_laden: bool = False,
) -> pd.DataFrame:
    """Lädt OHLCV-Daten für den Backtest.

    Nutzt die lokale CSV-Datei, falls vorhanden. Mit `neu_laden=True` (oder
    wenn noch keine Datei existiert) werden die Daten frisch über ccxt von
    Bybit abgerufen und danach gespeichert.
    """
    os.makedirs(ORDNER, exist_ok=True)
    pfad = _dateiname(symbol, timeframe)

    df = None
    if os.path.exists(pfad) and not neu_laden:
        df = pd.read_csv(pfad, parse_dates=["timestamp"])
        if not _deckt_zeitraum_ab(df, von, bis):
            df = None  # Cache deckt den angeforderten Zeitraum nicht ab.

    if df is None:
        df = _von_bybit_laden(symbol, timeframe, von, bis)
        df.to_csv(pfad, index=False)

    return _zeitraum_filtern(df, von, bis)


def _deckt_zeitraum_ab(df: pd.DataFrame, von: str, bis: str) -> bool:
    """Prüft, ob die gecachten Daten den angeforderten Zeitraum abdecken -
    sonst würde man unbemerkt mit weniger Daten als gewünscht arbeiten."""
    if df.empty:
        return False
    if von and df["timestamp"].min() > pd.Timestamp(von):
        return False
    bis_soll = pd.Timestamp(bis) if bis else pd.Timestamp.now()
    if df["timestamp"].max() < bis_soll - pd.Timedelta(days=1):
        return False
    return True


def _zeitraum_filtern(df: pd.DataFrame, von: str, bis: str) -> pd.DataFrame:
    if von:
        df = df[df["timestamp"] >= pd.Timestamp(von)]
    if bis:
        df = df[df["timestamp"] <= pd.Timestamp(bis)]
    return df.reset_index(drop=True)


def _von_bybit_laden(symbol: str, timeframe: str, von: str, bis: str = None) -> pd.DataFrame:
    exchange = ccxt.bybit({"enableRateLimit": True})

    seit_ms = exchange.parse8601(pd.Timestamp(von).strftime("%Y-%m-%dT%H:%M:%SZ"))
    bis_ms = (
        exchange.parse8601(pd.Timestamp(bis).strftime("%Y-%m-%dT%H:%M:%SZ"))
        if bis
        else exchange.milliseconds()
    )

    alle_kerzen = []
    while seit_ms < bis_ms:
        kerzen = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=seit_ms, limit=1000)
        if not kerzen:
            break
        alle_kerzen.extend(kerzen)
        neuer_seit_ms = kerzen[-1][0] + 1
        if neuer_seit_ms <= seit_ms:
            break
        seit_ms = neuer_seit_ms
        time.sleep(exchange.rateLimit / 1000)

    df = pd.DataFrame(alle_kerzen, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df.drop_duplicates(subset="timestamp").reset_index(drop=True)
