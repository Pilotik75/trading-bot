"""Strategie-Labor: generische Indikatoren + eine breite Sammlung von Signalgeneratoren
für einen systematischen Vergleich vieler Strategien (siehe scripts/run_strategy_lab.py).

Jeder Signalgenerator gibt eine Series mit {1, -1, 0} zurück (1=Long-Einstieg,
-1=Short-Einstieg, 0=kein Signal), ausgerichtet auf den Index des übergebenen df.
Alle Berechnungen verwenden nur bereits abgeschlossene Kerzen (kein Lookahead-Bias) -
ein Signal an Kerze i basiert ausschließlich auf Daten bis einschließlich Kerze i und
wird zum Schlusskurs von Kerze i ausgeführt (Standardkonvention in diesem Projekt).

Da im Backtest keine echten Level-2-/Orderbuch-Daten vorliegen (nur OHLCV), approximiert
`ofi_proxy` eine Order-Flow-Imbalance aus der Kerzenstruktur: Schlusskurs nahe dem Hoch
deutet auf dominierende Kaufaggression hin (Taker trafen den Ask), Schlusskurs nahe dem
Tief auf Verkaufsaggression - gewichtet mit dem Volumen der Kerze. Das ist eine grobe
Näherung (u.a. als "Money Flow Multiplier x Volumen" bekannt), kein Ersatz für echte
Tick-/Orderbuch-Daten.
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Basis-Indikatoren
# ---------------------------------------------------------------------------

def sma(series, period):
    return series.rolling(period).mean()


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series, fast=12, slow=26, signal=9):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line


def bollinger(series, period=20, num_std=2.0):
    mid = sma(series, period)
    std = series.rolling(period).std()
    return mid - num_std * std, mid, mid + num_std * std


def atr(df, period=14):
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def stochastic(df, k_period=14, d_period=3):
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    k = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d


def williams_r(df, period=14):
    high_max = df["high"].rolling(period).max()
    low_min = df["low"].rolling(period).min()
    return -100 * (high_max - df["close"]) / (high_max - low_min).replace(0, np.nan)


def cci(df, period=20):
    typical = (df["high"] + df["low"] + df["close"]) / 3
    ma = typical.rolling(period).mean()
    mean_dev = (typical - ma).abs().rolling(period).mean()
    return (typical - ma) / (0.015 * mean_dev.replace(0, np.nan))


def roc(series, period=10):
    return (series / series.shift(period) - 1) * 100


def keltner(df, period=20, atr_mult=2.0):
    mid = ema(df["close"], period)
    band = atr(df, period) * atr_mult
    return mid - band, mid, mid + band


def ofi_proxy(df):
    """Grobe Order-Flow-Imbalance-Näherung aus OHLCV (siehe Modul-Docstring)."""
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    return ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng * df["volume"]


def _crossover(fast, slow):
    up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    down = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    return up, down


def _empty_signal(df):
    return pd.Series(0, index=df.index)


# ---------------------------------------------------------------------------
# Signalgeneratoren
# ---------------------------------------------------------------------------

def sig_sma_crossover(df, fast=10, slow=30):
    up, down = _crossover(sma(df["close"], fast), sma(df["close"], slow))
    s = _empty_signal(df)
    s[up] = 1
    s[down] = -1
    return s


def sig_ema_crossover(df, fast=10, slow=30):
    up, down = _crossover(ema(df["close"], fast), ema(df["close"], slow))
    s = _empty_signal(df)
    s[up] = 1
    s[down] = -1
    return s


def sig_macd_crossover(df, fast=12, slow=26, signal=9):
    macd_line, signal_line = macd(df["close"], fast, slow, signal)
    up, down = _crossover(macd_line, signal_line)
    s = _empty_signal(df)
    s[up] = 1
    s[down] = -1
    return s


def sig_rsi_mean_reversion(df, period=14, oversold=30, overbought=70):
    r = rsi(df["close"], period)
    s = _empty_signal(df)
    s[(r < oversold) & (r.shift(1) >= oversold)] = 1
    s[(r > overbought) & (r.shift(1) <= overbought)] = -1
    return s


def sig_rsi_momentum(df, period=14, mid=50):
    r = rsi(df["close"], period)
    s = _empty_signal(df)
    s[(r > mid) & (r.shift(1) <= mid)] = 1
    s[(r < mid) & (r.shift(1) >= mid)] = -1
    return s


def sig_bollinger_mean_reversion(df, period=20, num_std=2.0):
    lower, _, upper = bollinger(df["close"], period, num_std)
    s = _empty_signal(df)
    s[(df["close"] < lower) & (df["close"].shift(1) >= lower.shift(1))] = 1
    s[(df["close"] > upper) & (df["close"].shift(1) <= upper.shift(1))] = -1
    return s


def sig_bollinger_breakout(df, period=20, num_std=2.0):
    lower, _, upper = bollinger(df["close"], period, num_std)
    s = _empty_signal(df)
    s[(df["close"] > upper) & (df["close"].shift(1) <= upper.shift(1))] = 1
    s[(df["close"] < lower) & (df["close"].shift(1) >= lower.shift(1))] = -1
    return s


def sig_donchian_breakout(df, period=20):
    upper = df["high"].rolling(period).max().shift(1)
    lower = df["low"].rolling(period).min().shift(1)
    s = _empty_signal(df)
    s[df["close"] > upper] = 1
    s[df["close"] < lower] = -1
    return s


def sig_donchian_fade(df, period=20):
    return -sig_donchian_breakout(df, period)


def sig_stochastic(df, k_period=14, d_period=3, oversold=20, overbought=80):
    k, _ = stochastic(df, k_period, d_period)
    s = _empty_signal(df)
    s[(k < oversold) & (k.shift(1) >= oversold)] = 1
    s[(k > overbought) & (k.shift(1) <= overbought)] = -1
    return s


def sig_atr_volatility_breakout(df, period=14, mult=1.0):
    prev_close = df["close"].shift(1)
    atr_val = atr(df, period)
    s = _empty_signal(df)
    s[df["close"] > prev_close + atr_val * mult] = 1
    s[df["close"] < prev_close - atr_val * mult] = -1
    return s


def sig_ofi_momentum(df, lookback=20, z_thresh=1.5):
    cum = ofi_proxy(df).rolling(lookback).sum()
    z = (cum - cum.rolling(lookback * 3).mean()) / cum.rolling(lookback * 3).std()
    s = _empty_signal(df)
    s[(z > z_thresh) & (z.shift(1) <= z_thresh)] = 1
    s[(z < -z_thresh) & (z.shift(1) >= -z_thresh)] = -1
    return s


def sig_ofi_fade(df, lookback=20, z_thresh=1.5):
    return -sig_ofi_momentum(df, lookback, z_thresh)


def sig_ofi_confirmed_crossover(df, fast=10, slow=30, ofi_lookback=10):
    up, down = _crossover(sma(df["close"], fast), sma(df["close"], slow))
    cum_ofi = ofi_proxy(df).rolling(ofi_lookback).sum()
    s = _empty_signal(df)
    s[up & (cum_ofi > 0)] = 1
    s[down & (cum_ofi < 0)] = -1
    return s


def sig_williams_r(df, period=14, oversold=-80, overbought=-20):
    r = williams_r(df, period)
    s = _empty_signal(df)
    s[(r < oversold) & (r.shift(1) >= oversold)] = 1
    s[(r > overbought) & (r.shift(1) <= overbought)] = -1
    return s


def sig_cci(df, period=20, oversold=-100, overbought=100):
    c = cci(df, period)
    s = _empty_signal(df)
    s[(c < oversold) & (c.shift(1) >= oversold)] = 1
    s[(c > overbought) & (c.shift(1) <= overbought)] = -1
    return s


def sig_roc_momentum(df, period=10, thresh=1.0):
    r = roc(df["close"], period)
    s = _empty_signal(df)
    s[(r > thresh) & (r.shift(1) <= thresh)] = 1
    s[(r < -thresh) & (r.shift(1) >= -thresh)] = -1
    return s


def sig_keltner_breakout(df, period=20, atr_mult=2.0):
    lower, _, upper = keltner(df, period, atr_mult)
    s = _empty_signal(df)
    s[(df["close"] > upper) & (df["close"].shift(1) <= upper.shift(1))] = 1
    s[(df["close"] < lower) & (df["close"].shift(1) >= lower.shift(1))] = -1
    return s


def sig_ofi_divergence(df, lookback=20):
    price_new_low = df["close"] <= df["close"].rolling(lookback).min()
    price_new_high = df["close"] >= df["close"].rolling(lookback).max()
    cum_ofi = ofi_proxy(df).rolling(lookback).sum()
    ofi_at_low = cum_ofi.rolling(lookback).min()
    ofi_at_high = cum_ofi.rolling(lookback).max()
    s = _empty_signal(df)
    # Kurs macht neues Tief, Order-Flow bestätigt die Schwäche nicht -> bullische Divergenz
    s[price_new_low & (cum_ofi > ofi_at_low)] = 1
    s[price_new_high & (cum_ofi < ofi_at_high)] = -1
    return s
