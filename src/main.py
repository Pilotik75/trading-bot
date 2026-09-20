"""CLI-Einstiegspunkt: lädt historische Daten, führt den Backtest aus und
schreibt Kennzahlen, Trade-Log und eine Equity-Curve pro Symbol ins Output-Verzeichnis.

Beispiel:
    python -m src.main --symbol BTC/USDT,ETH/USDT --since 2024-06-01T00:00:00Z --until 2024-06-08T00:00:00Z
"""

import argparse
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import yaml

from src.backtest import Backtester
from src.data import fetch_ohlcv, load_csv
from src.metrics import compute_metrics

TIMEFRAME_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720,
    "1d": 1440,
}


def load_config(path="config.yaml"):
    if os.path.exists(path):
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


def bars_per_year(timeframe):
    minutes = TIMEFRAME_MINUTES.get(timeframe, 1)
    return (365 * 24 * 60) / minutes


def parse_args():
    cfg = load_config()
    p = argparse.ArgumentParser(description="Volumen-Ausbruch Backtest (Krypto, 1-Minuten-Kerzen)")
    p.add_argument("--symbol", default=cfg.get("symbol", "BTC/USDT"),
                    help="Ein oder mehrere Symbole, kommagetrennt, z.B. BTC/USDT,ETH/USDT")
    p.add_argument("--timeframe", default=cfg.get("timeframe", "1m"))
    p.add_argument("--since", default=cfg.get("since", "2024-06-01T00:00:00Z"))
    p.add_argument("--until", default=cfg.get("until"))
    p.add_argument("--capital", type=float, default=cfg.get("capital", 10000))
    p.add_argument("--risk-pct", type=float, default=cfg.get("risk_pct", 0.02))
    p.add_argument("--max-leverage", type=float, default=cfg.get("max_leverage", 2.5))
    p.add_argument("--lookback", type=int, default=cfg.get("lookback", 15))
    p.add_argument("--volume-multiplier", type=float, default=cfg.get("volume_multiplier", 1.5))
    p.add_argument("--atr-period", type=int, default=cfg.get("atr_period", 14))
    p.add_argument("--atr-multiplier", type=float, default=cfg.get("atr_multiplier", 1.5))
    p.add_argument("--ema-fast", type=int, default=cfg.get("ema_fast", 9))
    p.add_argument("--cooldown-bars", type=int, default=cfg.get("cooldown_bars", 0),
                    help="Kerzen Sperrfrist nach einem Trade, bevor ein neuer eröffnet werden darf")
    p.add_argument("--breakout-confirm-bars", type=int, default=cfg.get("breakout_confirm_bars", 3),
                    help="Kerzen, die der Preis jenseits des Ausbruchs-Levels bleiben muss, bevor "
                         "tatsächlich eingestiegen wird (filtert sofort zurückfallende Fehlausbrüche)")
    p.add_argument("--partial-tp-r-multiple", type=float, default=cfg.get("partial_tp_r_multiple", 2.0),
                    help="R-Vielfaches der Stop-Distanz, bei dem ein Teil der Position geschlossen "
                         "wird (Gewinn deckt die Stop-Loss-Kosten); Rest-Stop wandert danach auf Breakeven")
    p.add_argument("--trend-timeframe", default=cfg.get("trend_timeframe", "1h"),
                    help="Höherer Zeitrahmen für den Trendfilter, z.B. 15m, 1h, 4h")
    p.add_argument("--trend-ema", type=int, default=cfg.get("trend_ema", 50),
                    help="EMA-Periode auf dem höheren Zeitrahmen zur Trendbestimmung")
    p.add_argument("--vol-lookback", type=int, default=cfg.get("vol_lookback", 100),
                    help="Kerzen für den langfristigen ATR-Schnitt (Volatilitäts-Regime-Filter)")
    p.add_argument("--vol-expansion-multiplier", type=float, default=cfg.get("vol_expansion_multiplier", 1.2),
                    help="Nur handeln, wenn ATR > n x langfristiger ATR-Schnitt (echte Volatilitätsexpansion)")
    p.add_argument("--no-shorts", action="store_true", default=not cfg.get("allow_shorts", True))
    p.add_argument("--fee-pct", type=float, default=cfg.get("fee_pct", 0.0004))
    p.add_argument("--output-dir", default=cfg.get("output_dir", "results"))
    p.add_argument("--no-cache", action="store_true", help="Erzwingt Neu-Download statt lokalem CSV-Cache")
    p.add_argument("--csv", default=cfg.get("csv"),
                    help="Lädt OHLCV-Daten aus einer lokalen CSV statt über ccxt (Spalten: "
                         "timestamp, open, high, low, close, volume). Umgeht den Netzwerkabruf; "
                         "bei mehreren --symbol wird dieselbe Datei für alle verwendet.")
    return p.parse_args()


def run_for_symbol(symbol, args):
    if args.csv:
        print(f"Lade Daten für {symbol} aus lokaler CSV: {args.csv} ...")
        df = load_csv(args.csv)
        if args.since:
            df = df[df["timestamp"] >= pd.to_datetime(args.since, utc=True)]
        if args.until:
            df = df[df["timestamp"] < pd.to_datetime(args.until, utc=True)]
        df = df.reset_index(drop=True)
    else:
        print(f"Lade Daten für {symbol} ({args.timeframe}, {args.since} bis {args.until or 'jetzt'})...")
        df = fetch_ohlcv(
            symbol, args.timeframe, since=args.since, until=args.until, use_cache=not args.no_cache
        )
    if df.empty:
        print(f"Keine Daten für {symbol} erhalten.")
        return None
    print(f"{len(df)} Kerzen geladen.")

    bt = Backtester(
        capital=args.capital,
        risk_pct=args.risk_pct,
        max_leverage=args.max_leverage,
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
    )
    equity_df = bt.run(df)
    metrics = compute_metrics(bt.trades, equity_df, args.capital, bars_per_year(args.timeframe))

    os.makedirs(args.output_dir, exist_ok=True)
    safe_symbol = symbol.replace("/", "")

    trades_df = pd.DataFrame([t.__dict__ for t in bt.trades])
    trades_path = os.path.join(args.output_dir, f"trades_{safe_symbol}.csv")
    trades_df.to_csv(trades_path, index=False)

    equity_path = os.path.join(args.output_dir, f"equity_{safe_symbol}.csv")
    equity_df.to_csv(equity_path, index=False)

    plt.figure(figsize=(10, 5))
    plt.plot(equity_df["timestamp"], equity_df["equity"])
    plt.title(f"Equity Curve — {symbol}")
    plt.xlabel("Zeit")
    plt.ylabel("Kapital")
    plt.tight_layout()
    plot_path = os.path.join(args.output_dir, f"equity_{safe_symbol}.png")
    plt.savefig(plot_path)
    plt.close()

    print(f"\n=== Ergebnis {symbol} ===")
    for key, value in metrics.items():
        print(f"  {key}: {value:.2f}" if isinstance(value, float) else f"  {key}: {value}")
    print(f"  Trades:  {trades_path}")
    print(f"  Equity:  {equity_path}")
    print(f"  Plot:    {plot_path}")

    return metrics


def main():
    args = parse_args()
    symbols = [s.strip() for s in args.symbol.split(",") if s.strip()]
    for symbol in symbols:
        run_for_symbol(symbol, args)


if __name__ == "__main__":
    main()
