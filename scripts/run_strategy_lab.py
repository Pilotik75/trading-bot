"""Systematischer Vergleich von ~100 Strategievarianten (klassische Indikatoren +
Order-Flow-Imbalance-Proxy) gegen die echten 5m-BTC/USDT-Daten.

Lehre aus der letzten Parameter-Sweep-Runde (README, Abschnitt "Hinweise"): der beste
Aggregat-Wert ist oft die am stärksten überfittete Kombination. Deshalb wird hier direkt
mit Split-Validierung gerankt (Minimum aus Profit-Faktor erste/zweite Hälfte), nicht nach
dem reinen Gesamt-Profit-Faktor.

Nutzung:
    python scripts/run_strategy_lab.py [--csv data/btcusdt_5m_sample.csv] [--output results/strategy_lab.csv]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from src.backtest_generic import SignalBacktester
from src.data import load_csv
from src.metrics import compute_metrics
from src import strategy_lab as sl

BARS_PER_YEAR_5M = 365 * 24 * 12


def build_configs():
    """Erzeugt die Liste der zu testenden (name, signal_fn, backtest_kwargs) Tupel."""
    configs = []

    def add(name, fn, **bt_kwargs):
        configs.append((name, fn, bt_kwargs))

    for fast, slow in [(5, 20), (10, 30), (10, 50), (20, 50), (20, 100), (50, 200)]:
        add(f"sma_cross_{fast}_{slow}", lambda d, f=fast, s=slow: sl.sig_sma_crossover(d, f, s))
    for fast, slow in [(5, 20), (10, 30), (10, 50), (20, 50), (20, 100)]:
        add(f"ema_cross_{fast}_{slow}", lambda d, f=fast, s=slow: sl.sig_ema_crossover(d, f, s))

    for fast, slow, sig in [(12, 26, 9), (5, 35, 5), (8, 21, 5), (19, 39, 9)]:
        add(f"macd_{fast}_{slow}_{sig}", lambda d, f=fast, s=slow, g=sig: sl.sig_macd_crossover(d, f, s, g))

    for period, os_, ob_ in [(14, 30, 70), (14, 20, 80), (7, 30, 70), (21, 30, 70), (14, 25, 75)]:
        add(f"rsi_meanrev_{period}_{os_}_{ob_}", lambda d, p=period, o=os_, b=ob_: sl.sig_rsi_mean_reversion(d, p, o, b))
    for period, mid in [(14, 50), (7, 50), (21, 50), (14, 45), (14, 55)]:
        add(f"rsi_mom_{period}_{mid}", lambda d, p=period, m=mid: sl.sig_rsi_momentum(d, p, m))

    for period, std in [(20, 2.0), (20, 2.5), (10, 2.0), (30, 2.0), (20, 1.5)]:
        add(f"boll_meanrev_{period}_{std}", lambda d, p=period, s=std: sl.sig_bollinger_mean_reversion(d, p, s))
    for period, std in [(20, 2.0), (20, 2.5), (10, 2.0), (30, 2.0), (20, 1.5)]:
        add(f"boll_breakout_{period}_{std}", lambda d, p=period, s=std: sl.sig_bollinger_breakout(d, p, s))

    for period in [10, 20, 30, 50, 75, 100]:
        add(f"donchian_breakout_{period}", lambda d, p=period: sl.sig_donchian_breakout(d, p))
    for period in [10, 20, 30, 50, 75, 100]:
        add(f"donchian_fade_{period}", lambda d, p=period: sl.sig_donchian_fade(d, p))

    for k, d_, os_, ob_ in [(14, 3, 20, 80), (14, 3, 10, 90), (21, 5, 20, 80), (9, 3, 20, 80), (14, 3, 25, 75)]:
        add(f"stoch_{k}_{d_}_{os_}_{ob_}", lambda d, k_=k, dd=d_, o=os_, b=ob_: sl.sig_stochastic(d, k_, dd, o, b))

    for period, mult in [(14, 0.5), (14, 1.0), (14, 1.5), (20, 1.0), (7, 1.0)]:
        add(f"atr_vol_breakout_{period}_{mult}", lambda d, p=period, m=mult: sl.sig_atr_volatility_breakout(d, p, m))

    for lookback, z in [(10, 1.0), (10, 1.5), (20, 1.5), (20, 2.0), (40, 1.5)]:
        add(f"ofi_momentum_{lookback}_{z}", lambda d, l=lookback, zz=z: sl.sig_ofi_momentum(d, l, zz))
    for lookback, z in [(10, 1.0), (10, 1.5), (20, 1.5), (20, 2.0), (40, 1.5)]:
        add(f"ofi_fade_{lookback}_{z}", lambda d, l=lookback, zz=z: sl.sig_ofi_fade(d, l, zz))
    for fast, slow, ofi_lb in [(10, 30, 10), (10, 30, 20), (20, 50, 10), (20, 50, 20), (5, 20, 10)]:
        add(f"ofi_confirmed_cross_{fast}_{slow}_{ofi_lb}",
            lambda d, f=fast, s=slow, o=ofi_lb: sl.sig_ofi_confirmed_crossover(d, f, s, o))
    for lookback in [10, 20, 30, 50, 75]:
        add(f"ofi_divergence_{lookback}", lambda d, l=lookback: sl.sig_ofi_divergence(d, l))

    for period, os_, ob_ in [(14, -80, -20), (14, -90, -10), (21, -80, -20), (7, -80, -20), (14, -70, -30)]:
        add(f"williams_r_{period}_{os_}_{ob_}", lambda d, p=period, o=os_, b=ob_: sl.sig_williams_r(d, p, o, b))
    for period, os_, ob_ in [(20, -100, 100), (20, -150, 150), (14, -100, 100), (40, -100, 100), (20, -50, 50)]:
        add(f"cci_{period}_{os_}_{ob_}", lambda d, p=period, o=os_, b=ob_: sl.sig_cci(d, p, o, b))
    for period, thresh in [(10, 0.5), (10, 1.0), (20, 1.0), (20, 2.0), (5, 0.5)]:
        add(f"roc_mom_{period}_{thresh}", lambda d, p=period, t=thresh: sl.sig_roc_momentum(d, p, t))
    for period, mult in [(20, 1.5), (20, 2.0), (10, 2.0), (30, 2.0)]:
        add(f"keltner_breakout_{period}_{mult}", lambda d, p=period, m=mult: sl.sig_keltner_breakout(d, p, m))

    for atr_mult, rr in [(1.5, 1.5), (2.0, 1.5), (2.0, 2.0), (3.0, 2.0)]:
        add(f"fade_baseline_atr{atr_mult}_rr{rr}", None, _fade_baseline=True, atr_stop_mult=atr_mult, rr_multiple=rr)

    return configs


def _fade_baseline_signal(df):
    """Vereinfachtes Fade-Signal (Volumenspitze + Ausbruch, ohne Trend-/Wick-Filter) als
    Referenzpunkt im generischen Backtest-Rahmen - nicht identisch mit backtest.py."""
    lookback = 15
    avg_vol = df["volume"].rolling(lookback).mean().shift(1)
    range_high = df["high"].rolling(lookback).max().shift(1)
    range_low = df["low"].rolling(lookback).min().shift(1)
    spike = df["volume"] > avg_vol * 1.5
    s = pd.Series(0, index=df.index)
    s[spike & (df["close"] > range_high)] = -1  # Fade: Aufwärtsausbruch -> Short
    s[spike & (df["close"] < range_low)] = 1     # Fade: Abwärtsausbruch -> Long
    return s


def evaluate(name, signal_fn, bt_kwargs, df, days):
    bt_kwargs = dict(bt_kwargs)
    is_fade_baseline = bt_kwargs.pop("_fade_baseline", False)
    fn = _fade_baseline_signal if is_fade_baseline else signal_fn

    mid = df["timestamp"].min() + (df["timestamp"].max() - df["timestamp"].min()) / 2
    h1 = df[df["timestamp"] < mid].reset_index(drop=True)
    h2 = df[df["timestamp"] >= mid].reset_index(drop=True)

    def run_on(sub):
        sig = fn(sub)
        bt = SignalBacktester(**bt_kwargs)
        eq = bt.run(sub, sig)
        return compute_metrics(bt.trades, eq, bt.initial_capital, BARS_PER_YEAR_5M)

    m_full = run_on(df)
    m_h1 = run_on(h1)
    m_h2 = run_on(h2)

    pf_full = m_full["profit_factor"] if m_full["profit_factor"] != float("inf") else None
    pf_h1 = m_h1["profit_factor"] if m_h1["profit_factor"] != float("inf") else None
    pf_h2 = m_h2["profit_factor"] if m_h2["profit_factor"] != float("inf") else None

    enough_data = m_h1["num_trades"] >= 8 and m_h2["num_trades"] >= 8
    robustness = min(pf_h1, pf_h2) if (enough_data and pf_h1 is not None and pf_h2 is not None) else None

    return {
        "name": name,
        "trades": m_full["num_trades"],
        "win_rate_pct": round(m_full["win_rate_pct"], 2),
        "profit_factor": round(pf_full, 3) if pf_full is not None else None,
        "total_return_pct": round(m_full["total_return_pct"], 2),
        "max_dd_pct": round(m_full["max_drawdown_pct"], 2),
        "sharpe": round(m_full["sharpe"], 3),
        "h1_trades": m_h1["num_trades"],
        "h1_pf": round(pf_h1, 3) if pf_h1 is not None else None,
        "h2_trades": m_h2["num_trades"],
        "h2_pf": round(pf_h2, 3) if pf_h2 is not None else None,
        "robustness_pf": round(robustness, 3) if robustness is not None else None,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="data/btcusdt_5m_sample.csv")
    p.add_argument("--output", default="results/strategy_lab.csv")
    args = p.parse_args()

    df = load_csv(args.csv)
    days = (df["timestamp"].max() - df["timestamp"].min()).days
    configs = build_configs()
    print(f"{len(configs)} Strategien werden getestet ({len(df)} Kerzen, {days} Tage)...", flush=True)

    results = []
    for i, (name, fn, bt_kwargs) in enumerate(configs, 1):
        try:
            row = evaluate(name, fn, bt_kwargs, df, days)
        except Exception as exc:
            row = {"name": name, "error": str(exc)}
        results.append(row)
        print(f"[{i}/{len(configs)}] {row}", flush=True)

    res_df = pd.DataFrame(results)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    res_df.to_csv(args.output, index=False)

    print("\n=== Top 15 nach Robustheit (min(PF H1, PF H2)) ===")
    ranked = res_df.dropna(subset=["robustness_pf"]).sort_values("robustness_pf", ascending=False)
    print(ranked.head(15).to_string(index=False))

    print(f"\nErgebnisse gespeichert: {args.output}")


if __name__ == "__main__":
    main()
