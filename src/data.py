"""Historische OHLCV-Daten von Krypto-Exchanges laden (via ccxt), mit lokalem CSV-Cache."""

import os
import time

import ccxt
import pandas as pd

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def fetch_ohlcv(
    symbol,
    timeframe="1m",
    since=None,
    until=None,
    limit_per_call=1000,
    cache_dir="data",
    exchange_id="binance",
    use_cache=True,
):
    """Lädt OHLCV-Daten für ein Symbol zwischen since und until (ISO8601-Strings oder ms).

    Paginiert automatisch über den gesamten Zeitraum, da Exchanges pro Aufruf
    nur eine begrenzte Anzahl Kerzen liefern. Ergebnisse werden lokal gecacht.
    """
    os.makedirs(cache_dir, exist_ok=True)
    safe_symbol = symbol.replace("/", "")
    cache_file = os.path.join(
        cache_dir, f"{exchange_id}_{safe_symbol}_{timeframe}_{since}_{until}.csv"
    )
    if use_cache and os.path.exists(cache_file):
        return pd.read_csv(cache_file, parse_dates=["timestamp"])

    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({"enableRateLimit": True})

    since_ms = exchange.parse8601(since) if isinstance(since, str) else since
    until_ms = exchange.parse8601(until) if isinstance(until, str) else until

    all_rows = []
    cursor = since_ms
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=limit_per_call)
        if not batch:
            break
        all_rows.extend(batch)

        last_ts = batch[-1][0]
        next_cursor = last_ts + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor

        if until_ms and cursor >= until_ms:
            break
        if len(batch) < limit_per_call:
            break

        time.sleep(exchange.rateLimit / 1000)

    df = pd.DataFrame(all_rows, columns=OHLCV_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

    if until_ms:
        until_dt = pd.to_datetime(until_ms, unit="ms", utc=True)
        df = df[df["timestamp"] < until_dt]

    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)

    if use_cache:
        df.to_csv(cache_file, index=False)

    return df


def load_csv(path):
    """Lädt OHLCV-Daten aus einer eigenen CSV-Datei (Spalten: timestamp, open, high, low, close, volume)."""
    df = pd.read_csv(path, parse_dates=["timestamp"])
    missing = set(OHLCV_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"CSV fehlen Spalten: {missing}")
    return df.sort_values("timestamp").reset_index(drop=True)


def resample_ohlcv(df, timeframe):
    """Aggregiert feingranulare OHLCV-Daten (z.B. 1m) auf einen gröberen Zeitrahmen (z.B. 5m, 1h).

    label='right' sorgt dafür, dass jede aggregierte Kerze mit ihrem Schlusszeitpunkt indiziert
    wird (nicht dem Öffnungszeitpunkt) - wichtig, damit ein per merge_asof(direction='backward')
    darauf gemapptes feingranulares Signal nur bereits vollständig abgeschlossene gröbere Kerzen
    sieht (kein Lookahead-Bias).
    """
    resampled = (
        df.set_index("timestamp")
        .resample(timeframe, label="right", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
        .reset_index()
    )
    return resampled
