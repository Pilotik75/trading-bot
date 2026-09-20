# Krypto-Backtesting-Bot: Volumen-Ausbruch-Strategie

Python-Framework zum **Backtesten** (keine Live-Ausführung) einer Volumen-Ausbruch-Strategie
auf 1-Minuten-Kerzen für BTC/USDT und ETH/USDT.

## Strategie

- **Einstieg**: Volumenspitze (aktuelles Volumen > `volume_multiplier` × Durchschnittsvolumen der
  letzten `lookback` Kerzen) **und** Ausbruch — Schlusskurs über dem höchsten Hoch (Long) bzw.
  unter dem tiefsten Tief (Short) der letzten `lookback` Kerzen.
- **Ausstieg**: Gegenbewegung — Schlusskurs kreuzt die schnelle EMA (`ema_fast`) entgegen der
  Positionsrichtung. Zusätzlich ein ATR-basierter Stop-Loss als Sicherheitsnetz.
- **Risk-Management**: Pro Trade werden `risk_pct` (Standard 2 %, 1-3 % empfohlen) des Kapitals
  riskiert. Positionsgröße und **Hebel werden automatisch** aus der Stop-Distanz (ATR × Multiplikator)
  berechnet: `Positionswert = Risikobetrag / Stop-Distanz-in-%`. Der Hebel wird durch
  `max_leverage` gedeckelt — wird die Obergrenze erreicht, sinkt das tatsächliche Risiko
  entsprechend unter `risk_pct` (Sicherheit geht vor Zielrisiko).

Alle Indikatoren werden mit `shift(1)` berechnet, damit ein Signal nur auf bereits
abgeschlossenen Kerzen basiert (kein Lookahead-Bias).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Nutzung

```bash
python -m src.main --symbol BTC/USDT,ETH/USDT \
  --since 2024-06-01T00:00:00Z --until 2024-06-08T00:00:00Z \
  --capital 10000 --risk-pct 0.02 --max-leverage 5
```

Alle Parameter lassen sich auch dauerhaft in `config.yaml` setzen; CLI-Flags überschreiben sie.
`--help` zeigt alle Optionen.

Historische Daten werden über [ccxt](https://github.com/ccxt/ccxt) von Binance geladen (öffentliche
Endpunkte, kein API-Key nötig) und lokal in `data/` als CSV gecacht. Für eigene Daten ohne
Netzwerkzugriff: `src/data.py::load_csv(path)` erwartet die Spalten
`timestamp, open, high, low, close, volume`.

Ergebnisse pro Symbol landen in `results/`:
- `trades_<SYMBOL>.csv` — alle Trades mit Entry/Exit, Größe, Hebel, PnL, Exit-Grund
- `equity_<SYMBOL>.csv` — Kapitalverlauf über die Zeit
- `equity_<SYMBOL>.png` — Equity-Curve-Plot

Konsolenausgabe enthält: Anzahl Trades, Trefferquote, Gesamtrendite, Profit-Faktor,
maximaler Drawdown, Sharpe Ratio.

## Projektstruktur

```
src/
  data.py       # OHLCV-Daten laden (ccxt) + CSV-Cache/-Import
  strategy.py   # Indikatoren, Entry-/Exit-Signale
  risk.py       # Positionsgrößen-/Hebel-Berechnung
  backtest.py   # Event-getriebene Backtest-Engine
  metrics.py    # Performance-Kennzahlen
  main.py       # CLI
config.yaml     # Standard-Parameter
```

## Parameter (config.yaml / CLI)

| Parameter | Standard | Bedeutung |
|---|---|---|
| `lookback` | 90 | Kerzen für Range-Hoch/Tief und Volumen-Durchschnitt |
| `volume_multiplier` | 3.5 | Volumen-Spitze = Volumen > n × Durchschnitt |
| `atr_period` | 14 | Perioden für ATR-Berechnung |
| `atr_multiplier` | 1.5 | Stop-Distanz = ATR × Multiplikator |
| `ema_fast` | 9 | EMA-Periode zur Gegenbewegungs-Erkennung |
| `cooldown_bars` | 30 | Sperrfrist (in Kerzen) nach einem Trade, bevor ein neuer eröffnet wird |
| `risk_pct` | 0.02 | Kapitalrisiko pro Trade (1–3 % empfohlen) |
| `max_leverage` | 2.5 | Obergrenze für automatisch berechneten Hebel |
| `allow_shorts` | true | Short-Einstiege bei Abwärts-Ausbruch zulassen |
| `fee_pct` | 0.0004 | Gebühr pro Trade-Seite (Binance Futures Taker) |

## Hinweise

- **Reines Backtesting** — es wird keine echte Order platziert. Für Live-/Paper-Trading wäre ein
  separates Ausführungsmodul mit API-Keys nötig.
- Ergebnisse eines Backtests sind keine Garantie für zukünftige Performance. Parameter vor
  produktivem Einsatz auf mehreren Zeiträumen und mit Out-of-Sample-Daten validieren.
- **Getestet auf echten 1m-BTC/USDT-Daten (10 Monate):** Mit den ursprünglichen Standardwerten
  (`lookback=20`, `volume_multiplier=2.0`, `max_leverage=5.0`, kein Cooldown) überhandelte die
  Strategie massiv (~40 Trades/Tag) und lief durch Gebühren allein auf null. Die aktuellen
  Standardwerte (größerer Lookback, schärfere Volumen-Schwelle, Cooldown, niedrigerer Max-Hebel)
  reduzieren die Trade-Frequenz deutlich, beheben aber nicht das eigentliche Problem: Die
  Trefferquote liegt auch danach nur bei ~20–23 % (long wie short symmetrisch), d.h. der
  Volumen+Ausbruch-Einstieg selbst hat auf 1-Minuten-Krypto-Daten keinen nachweisbaren positiven
  Edge — er kauft/verkauft eher an lokalen Extremen, die sich sofort umkehren, als echte
  Trendfortsetzungen zu erwischen. Vor produktivem Einsatz braucht die Entry-Logik eine
  strukturelle Ergänzung, z.B. eine Bestätigung des Ausbruchs über mehrere Kerzen, einen
  Trendfilter auf höherem Zeitrahmen, oder ein Umdrehen der Logik (Fade statt Follow).
- In manchen Sandbox-/CI-Umgebungen ist der Zugriff auf `api.binance.com` durch die
  Netzwerk-Policy blockiert. Die Backtest-Logik selbst ist davon unabhängig (siehe `load_csv`
  für Offline-Nutzung) — auf einer Maschine mit normalem Internetzugang funktioniert der
  Datenabruf über ccxt direkt.
