"""Volumen-Ausbruch-Strategie: Einstieg bei Volumenspitze + Range-Ausbruch,
Ausstieg bei Gegenbewegung (Reversal gegen die Positionsrichtung)."""

import pandas as pd


def add_indicators(df, lookback=20, atr_period=14, ema_fast=9):
    """Berechnet die für die Strategie nötigen Indikatoren.

    Alle Referenzwerte (avg_volume, range_high/low) werden um eine Kerze
    verschoben (shift(1)), damit ein Signal nur auf be­reits abgeschlossenen
    Kerzen basiert und kein Blick in die Zukunft (Lookahead-Bias) entsteht.
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

    df["ema_fast"] = df["close"].ewm(span=ema_fast, adjust=False).mean()

    return df


def entry_signal(row, volume_multiplier=2.0, allow_shorts=True):
    """Gibt 'long', 'short' oder None zurück, basierend auf Volumenspitze + Ausbruch."""
    if pd.isna(row["avg_volume"]) or pd.isna(row["range_high"]) or pd.isna(row["atr"]):
        return None
    if row["avg_volume"] <= 0 or row["atr"] <= 0:
        return None

    volume_spike = row["volume"] > row["avg_volume"] * volume_multiplier
    if not volume_spike:
        return None

    if row["close"] > row["range_high"]:
        return "long"
    if allow_shorts and row["close"] < row["range_low"]:
        return "short"
    return None


def reversal_exit(row, position_side):
    """Erkennt eine Gegenbewegung: Schlusskurs kreuzt die schnelle EMA entgegen der Position."""
    if pd.isna(row["ema_fast"]):
        return False
    if position_side == "long":
        return row["close"] < row["ema_fast"]
    if position_side == "short":
        return row["close"] > row["ema_fast"]
    return False
