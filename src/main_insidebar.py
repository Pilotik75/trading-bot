"""CLI-Einstiegspunkt für die reine Inside-Bar-Ausbruchs-Strategie (siehe backtest_insidebar.py).

Eigenständig von src/main.py (Fade-Strategie), damit beide Strategien unabhängig
voneinander verglichen werden können.

Beispiel:
    python -m src.main_insidebar --csv data/btcusdt_1m_sample.csv --min-inside-bars 2
"""

import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.backtest_insidebar import InsideBarBacktester
from src.data import fetch_ohlcv, load_csv
from src.metrics import compute_metrics
from src.main import TIMEFRAME_MINUTES, bars_per_year


def parse_args():
    p = argparse.ArgumentParser(description="Inside-Bar-Ausbruchs-Backtest (Krypto)")
    p.add_argument("--symbol", default="BTC/USDT")
    p.add_argument("--timeframe", default="1m")
    p.add_argument("--since", default=None)
    p.add_argument("--until", default=None)
    p.add_argument("--capital", type=float, default=10000)
    p.add_argument("--risk-pct", type=float, default=0.02)
    p.add_argument("--max-leverage", type=float, default=2.5)
    p.add_argument("--min-inside-bars", type=int, default=2,
                    help="Mindestanzahl Inside Bars vor einem gültigen Ausbruchssignal")
    p.add_argument("--target-range-multiple", type=float, default=1.0,
                    help="Take-Profit als Vielfaches der Mother-Bar-Range (Measured Move)")
    p.add_argument("--cooldown-bars", type=int, default=0)
    p.add_argument("--no-shorts", action="store_true")
    p.add_argument("--fee-pct", type=float, default=0.0004)
    p.add_argument("--output-dir", default="results")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--csv", default=None,
                    help="Lädt OHLCV-Daten aus einer lokalen CSV statt über ccxt")
    return p.parse_args()


def main():
    args = parse_args()

    if args.csv:
        print(f"Lade Daten für {args.symbol} aus lokaler CSV: {args.csv} ...")
        df = load_csv(args.csv)
        if args.since:
            df = df[df["timestamp"] >= pd.to_datetime(args.since, utc=True)]
        if args.until:
            df = df[df["timestamp"] < pd.to_datetime(args.until, utc=True)]
        df = df.reset_index(drop=True)
    else:
        print(f"Lade Daten für {args.symbol} ({args.timeframe})...")
        df = fetch_ohlcv(
            args.symbol, args.timeframe, since=args.since, until=args.until,
            use_cache=not args.no_cache,
        )

    if df.empty:
        print("Keine Daten erhalten.")
        return

    print(f"{len(df)} Kerzen geladen.")

    bt = InsideBarBacktester(
        capital=args.capital,
        risk_pct=args.risk_pct,
        max_leverage=args.max_leverage,
        min_inside_bars=args.min_inside_bars,
        target_range_multiple=args.target_range_multiple,
        allow_shorts=not args.no_shorts,
        fee_pct=args.fee_pct,
        cooldown_bars=args.cooldown_bars,
    )
    equity_df = bt.run(df)
    metrics = compute_metrics(bt.trades, equity_df, args.capital, bars_per_year(args.timeframe))

    os.makedirs(args.output_dir, exist_ok=True)
    safe_symbol = args.symbol.replace("/", "")

    trades_df = pd.DataFrame([t.__dict__ for t in bt.trades])
    trades_path = os.path.join(args.output_dir, f"trades_insidebar_{safe_symbol}.csv")
    trades_df.to_csv(trades_path, index=False)

    equity_path = os.path.join(args.output_dir, f"equity_insidebar_{safe_symbol}.csv")
    equity_df.to_csv(equity_path, index=False)

    plt.figure(figsize=(10, 5))
    plt.plot(equity_df["timestamp"], equity_df["equity"])
    plt.title(f"Equity Curve (Inside Bar) — {args.symbol}")
    plt.xlabel("Zeit")
    plt.ylabel("Kapital")
    plt.tight_layout()
    plot_path = os.path.join(args.output_dir, f"equity_insidebar_{safe_symbol}.png")
    plt.savefig(plot_path)
    plt.close()

    print(f"\n=== Ergebnis (Inside Bar) {args.symbol} ===")
    for key, value in metrics.items():
        print(f"  {key}: {value:.2f}" if isinstance(value, float) else f"  {key}: {value}")
    print(f"  Trades:  {trades_path}")
    print(f"  Equity:  {equity_path}")
    print(f"  Plot:    {plot_path}")


if __name__ == "__main__":
    main()
