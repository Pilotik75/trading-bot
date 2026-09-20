"""Reine Inside-Bar-Kompressions-/Ausbruchs-Strategie.

Muster: Eine "Mother Bar" wird von einer oder mehreren "Inside Bars" gefolgt - Kerzen,
deren Hoch/Tief vollständig innerhalb der Mother Bar liegen (Konsolidierung/Kompression).
Bricht der Preis anschließend aus der Mother-Bar-Range aus, wird in Ausbruchsrichtung
gehandelt (Follow, nicht Fade) - die Idee: Nach einer Phase geringer Volatilität folgt oft
eine echte, gerichtete Bewegung.

Im Gegensatz zur Fade-Strategie (strategy.py) kommen hier keine zusätzlichen Filter
(Trend, Volatilitäts-Regime, Ablehnungskerze) zum Einsatz - bewusst die "reine" Variante.
"""

import pandas as pd


def detect_breakouts(df, min_inside_bars=2):
    """Erkennt Inside-Bar-Kompressionen und den anschließenden Ausbruch.

    Für jede Kerze wird geprüft, ob sie der Ausbruch aus einer mindestens
    `min_inside_bars` Kerzen langen Konsolidierung ist. Gibt den df mit einer neuen
    Spalte 'breakout' ('long'/'short'/None) sowie 'mother_high'/'mother_low' (Range der
    Konsolidierung, für Stop/Target) zurück.

    Die Mother Bar ist die Kerze unmittelbar vor der ersten Inside Bar; ihre Range bleibt
    über die gesamte Konsolidierung fix (keine "wandernde" Range). Eine Kerze, die weder
    innerhalb der Mother Bar liegt noch eindeutig darüber/darunter ausbricht (z.B. eine
    "Outside Bar"), beendet die Konsolidierung ohne Signal - die Kerze selbst wird zur
    neuen potenziellen Mother Bar.
    """
    n = len(df)
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()

    breakout = [None] * n
    mother_high_arr = [float("nan")] * n
    mother_low_arr = [float("nan")] * n
    inside_count_arr = [0] * n

    mother_high = None
    mother_low = None
    inside_count = 0

    for i in range(1, n):
        if mother_high is None:
            mother_high, mother_low = high[i - 1], low[i - 1]
            inside_count = 0

        is_inside = high[i] <= mother_high and low[i] >= mother_low
        if is_inside:
            inside_count += 1
            inside_count_arr[i] = inside_count
            continue

        breaks_up = close[i] > mother_high
        breaks_down = close[i] < mother_low
        if inside_count >= min_inside_bars and (breaks_up or breaks_down):
            breakout[i] = "long" if breaks_up else "short"
            mother_high_arr[i] = mother_high
            mother_low_arr[i] = mother_low

        # Konsolidierung endet hier - diese Kerze wird neue potenzielle Mother Bar.
        mother_high, mother_low = high[i], low[i]
        inside_count = 0

    df = df.copy()
    df["breakout"] = breakout
    df["mother_high"] = mother_high_arr
    df["mother_low"] = mother_low_arr
    df["inside_bars"] = inside_count_arr
    return df
