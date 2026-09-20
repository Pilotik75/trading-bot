"""Fade-Strategie: Volumenspitze + Range-Ausbruch werden nicht mehr gefolgt, sondern
gegen den kurzfristigen Ausbruch und mit dem übergeordneten Trend gehandelt (Mean-Reversion),
gefiltert durch ein Volatilitäts-Regime. Ausstieg weiterhin bei Gegenbewegung.

Begründung: Backtests auf echten 1m-BTC/USDT-Daten zeigten, dass das reine Folgen von
Volumen-Ausbrüchen auf 1-Minuten-Krypto-Daten keinen positiven Edge hat (~20-23%
Trefferquote, symmetrisch long/short) - die Ausbrüche kehren meist sofort um, statt sich
fortzusetzen. Diese Version handelt stattdessen die Umkehr: Bei einem Aufwärts-Ausbruch
während eines übergeordneten Abwärtstrends wird geshortet (und umgekehrt), nur wenn zugleich
eine echte Volatilitätsexpansion vorliegt (kein normales Rauschen).
"""

import pandas as pd


def add_indicators(df, lookback=20, atr_period=14, ema_fast=9, vol_lookback=100):
    """Berechnet die für die Strategie nötigen Indikatoren.

    Alle Referenzwerte (avg_volume, range_high/low, atr_long_avg) werden um eine Kerze
    verschoben (shift(1)), damit ein Signal nur auf bereits abgeschlossenen Kerzen
    basiert und kein Blick in die Zukunft (Lookahead-Bias) entsteht.
    """
    df = df.copy()

    df["avg_volume"] = df["volume"].rolling(lookback).mean().shift(1)
    df["range_high"] = df["high"].rolling(lookback).max().shift(1)
    df["range_low"] = df["low"].rolling(lookback).min().shift(1)

    prev_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr"] = true_range.rolling(atr_period).mean()
    df["atr_long_avg"] = df["atr"].rolling(vol_lookback).mean().shift(1)

    df["ema_fast"] = df["close"].ewm(span=ema_fast, adjust=False).mean()

    return df


def add_trend_filter(df, trend_timeframe="1h", trend_ema=50):
    """Bestimmt den übergeordneten Trend ('up'/'down') auf einem höheren Zeitrahmen.

    Verwendet ausschließlich bereits vollständig abgeschlossene Kerzen des höheren
    Zeitrahmens (durch shift(1) auf die resampleten Daten) - kein Lookahead-Bias.
    """
    df = df.copy()

    resampled = df.set_index("timestamp")["close"].resample(trend_timeframe).last().dropna()
    htf_ema = resampled.ewm(span=trend_ema, adjust=False).mean()

    higher = pd.DataFrame({"htf_close": resampled, "htf_ema": htf_ema}).shift(1)
    higher = higher.reset_index().rename(columns={"timestamp": "htf_timestamp"})

    merged = pd.merge_asof(
        df.sort_values("timestamp"),
        higher.sort_values("htf_timestamp"),
        left_on="timestamp",
        right_on="htf_timestamp",
        direction="backward",
    )

    merged["trend"] = None
    merged.loc[merged["htf_close"] > merged["htf_ema"], "trend"] = "up"
    merged.loc[merged["htf_close"] <= merged["htf_ema"], "trend"] = "down"

    return merged.drop(columns=["htf_timestamp", "htf_close", "htf_ema"])


def entry_signal(row, volume_multiplier=2.0, allow_shorts=True, vol_expansion_multiplier=1.2):
    """Gibt {'breakout_side', 'trade_side'} oder None zurück.

    breakout_side: Richtung des Ausbruchs (für die Bestätigungslogik in backtest.py).
    trade_side: tatsächlich zu handelnde Richtung - das Gegenteil des Ausbruchs (Fade),
    nur wenn der übergeordnete Trend diese Richtung stützt und eine echte
    Volatilitätsexpansion vorliegt.
    """
    required = ("avg_volume", "range_high", "range_low", "atr", "atr_long_avg", "trend")
    if any(pd.isna(row[key]) for key in required):
        return None
    if row["avg_volume"] <= 0 or row["atr"] <= 0 or row["atr_long_avg"] <= 0:
        return None

    volume_spike = row["volume"] > row["avg_volume"] * volume_multiplier
    volatility_expansion = row["atr"] > row["atr_long_avg"] * vol_expansion_multiplier
    if not (volume_spike and volatility_expansion):
        return None

    breakout_side = None
    if row["close"] > row["range_high"]:
        breakout_side = "long"
    elif row["close"] < row["range_low"]:
        breakout_side = "short"
    if breakout_side is None:
        return None

    trend = row["trend"]
    if breakout_side == "long" and trend == "down":
        trade_side = "short"
    elif breakout_side == "short" and trend == "up":
        trade_side = "long"
    else:
        return None

    if trade_side == "short" and not allow_shorts:
        return None

    return {"breakout_side": breakout_side, "trade_side": trade_side}


def reversal_exit(row, position_side):
    """Erkennt eine Gegenbewegung: Schlusskurs kreuzt die schnelle EMA entgegen der Position."""
    if pd.isna(row["ema_fast"]):
        return False
    if position_side == "long":
        return row["close"] < row["ema_fast"]
    if position_side == "short":
        return row["close"] > row["ema_fast"]
    return False
