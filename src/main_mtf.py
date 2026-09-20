"""CLI-Einstiegspunkt für die Multi-Timeframe-Fade-Strategie (siehe backtest_mtf.py):
Ausbruchserkennung auf einem höheren Signal-Zeitrahmen, Einstieg und Positionsüberwachung
auf 1-Minuten-Basis.

Beispiel:
    python -m src.main_mtf --csv data/btcusdt_1m_sample.csv --signal-timeframe 5min --trend-timeframe 1h
    python -m src.main_mtf --csv data/btcusdt_1m_sample.csv --signal-timeframe 1h --trend-timeframe 4h
"""

import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.backtest_mtf import MultiTimeframeBacktester
from src.data import fetch_ohlcv, load_csv
from src.metrics import compute_metrics


def parse_args():
    p = argparse.ArgumentParser(description="Multi-Timeframe Fade-Backtest (Signal auf höherem TF, Ausführung auf 1m)")
    p.add_argument("--symbol", default="BTC/USDT")
    p.add_argument("--since", default=None)
    p.add_argument("--until", default=None)
    p.add_argument("--capital", type=float, default=10000)
    p.add_argument("--risk-pct", type=float, default=0.02)
    p.add_argument("--max-leverage", type=float, default=2.5)
    p.add_argument("--signal-timeframe", default="5min",
                    help="Zeitrahmen für die Ausbruchserkennung, z.B. 5min, 1h")
    p.add_argument("--lookback", type=int, default=15)
    p.add_argument("--volume-multiplier", type=float, default=1.5)
    p.add_argument("--atr-period", type=int, default=14)
    p.add_argument("--atr-multiplier", type=float, default=1.5)
    p.add_argument("--ema-fast", type=int, default=9, help="EMA-Periode in 1m-Kerzen für die Gegenbewegungs-Erkennung")
    p.add_argument("--cooldown-bars", type=int, default=0, help="Sperrfrist in Signal-Zeitrahmen-Kerzen")
    p.add_argument("--breakout-confirm-bars", type=int, default=3, help="Signal-Zeitrahmen-Kerzen bis zur Bestätigung")
    p.add_argument("--partial-tp-r-multiple", type=float, default=2.0)
    p.add_argument("--trend-timeframe", default="1h")
    p.add_argument("--trend-ema", type=int, default=50)
    p.add_argument("--vol-lookback", type=int, default=100)
    p.add_argument("--vol-expansion-multiplier", type=float, default=1.2)
    p.add_argument("--wick-body-ratio", type=float, default=1.0)
    p.add_argument("--no-shorts", action="store_true")
    p.add_argument("--fee-pct", type=float, default=0.0004)
    p.add_argument("--output-dir", default="results")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--csv", default=None, help="Lädt 1m-OHLCV-Daten aus einer lokalen CSV statt über ccxt")
    return p.parse_args()


def main():
    args = parse_args()

    if args.csv:
        print(f"Lade 1m-Daten für {args.symbol} aus lokaler CSV: {args.csv} ...")
        df = load_csv(args.csv)
        if args.since:
            df = df[df["timestamp"] >= pd.to_datetime(args.since, utc=True)]
        if args.until:
            df = df[df["timestamp"] < pd.to_datetime(args.until, utc=True)]
        df = df.reset_index(drop=True)
    else:
        print(f"Lade 1m-Daten für {args.symbol}...")
        df = fetch_ohlcv(args.symbol, "1m", since=args.since, until=args.until, use_cache=not args.no_cache)

    if df.empty:
        print("Keine Daten erhalten.")
        return

    print(f"{len(df)} 1m-Kerzen geladen.")

    bt = MultiTimeframeBacktester(
        capital=args.capital,
        risk_pct=args.risk_pct,
        max_leverage=args.max_leverage,
        signal_timeframe=args.signal_timeframe,
        lookback=args.lookback,
        volume_multiplier=args.volume_multiplier,
        atr_period=args.atr_period,
        atr_multiplier=args.atr_multiplier,
        ema_fast=args.ema_fast,
        allow_shorts=not args.no_shorts,
        fee_pct=args.fee_pct,
        cooldown_bars=args.cooldown_bars,
        breakout_confirm_bars=args.breakout_confirm_bars,
        partial_tp_r_multiple=args.partial_tp_r_multiple,
        trend_timeframe=args.trend_timeframe,
        trend_ema=args.trend_ema,
        vol_lookback=args.vol_lookback,
        vol_expansion_multiplier=args.vol_expansion_multiplier,
        wick_body_ratio=args.wick_body_ratio,
    )
    equity_df = bt.run(df)
    metrics = compute_metrics(bt.trades, equity_df, args.capital, 365 * 24 * 60)

    os.makedirs(args.output_dir, exist_ok=True)
    safe_symbol = args.symbol.replace("/", "")
    safe_tf = args.signal_timeframe.replace("/", "")

    trades_df = pd.DataFrame([t.__dict__ for t in bt.trades])
    trades_path = os.path.join(args.output_dir, f"trades_mtf_{safe_tf}_{safe_symbol}.csv")
    trades_df.to_csv(trades_path, index=False)

    equity_path = os.path.join(args.output_dir, f"equity_mtf_{safe_tf}_{safe_symbol}.csv")
    equity_df.to_csv(equity_path, index=False)

    plt.figure(figsize=(10, 5))
    plt.plot(equity_df["timestamp"], equity_df["equity"])
    plt.title(f"Equity Curve (MTF, Signal={args.signal_timeframe}, Exec=1m) — {args.symbol}")
    plt.xlabel("Zeit")
    plt.ylabel("Kapital")
    plt.tight_layout()
    plot_path = os.path.join(args.output_dir, f"equity_mtf_{safe_tf}_{safe_symbol}.png")
    plt.savefig(plot_path)
    plt.close()

    print(f"\n=== Ergebnis (MTF, Signal={args.signal_timeframe}, Exec=1m) {args.symbol} ===")
    for key, value in metrics.items():
        print(f"  {key}: {value:.2f}" if isinstance(value, float) else f"  {key}: {value}")
    print(f"  Trades:  {trades_path}")
    print(f"  Equity:  {equity_path}")
    print(f"  Plot:    {plot_path}")


if __name__ == "__main__":
    main()
