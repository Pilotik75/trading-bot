# Krypto-Backtesting-Bot: Volumen-Fade-Strategie

Python-Framework zum **Backtesten** (keine Live-Ausführung) einer Mean-Reversion-Strategie für
BTC/USDT und ETH/USDT. Handelt Volumen-Ausbrüche **gegen** ihre eigene Richtung (Fade), aber nur
mit dem übergeordneten Trend und bei echter Volatilitätsexpansion. Standard-Zeitrahmen ist
**5-Minuten** (deutlich robuster als 1-Minuten, siehe "Hinweise" unten) — der `timeframe`-Parameter
bleibt frei wählbar.

## Strategie

- **Einstiegs-Kandidat**: Volumenspitze (aktuelles Volumen > `volume_multiplier` × Durchschnittsvolumen
  der letzten `lookback` Kerzen) **und** Ausbruch — Schlusskurs über dem höchsten Hoch bzw. unter
  dem tiefsten Tief der letzten `lookback` Kerzen — **und** eine echte Volatilitätsexpansion
  (aktueller ATR > `vol_expansion_multiplier` × ATR-Durchschnitt der letzten `vol_lookback`
  Kerzen, filtert normales Rauschen ohne Volatilitätsschub).
- **Trendfilter (Fade statt Follow)**: Der übergeordnete Trend wird auf einem höheren Zeitrahmen
  (`trend_timeframe`, Standard 1h) über eine EMA (`trend_ema`) bestimmt — nur bereits
  abgeschlossene Kerzen des höheren Zeitrahmens werden verwendet (kein Lookahead-Bias). Ein
  Aufwärts-Ausbruch wird nur gehandelt, wenn der übergeordnete Trend **abwärts** zeigt (→ Short,
  Wette auf Umkehr), ein Abwärts-Ausbruch nur bei übergeordnetem **Aufwärtstrend** (→ Long,
  "Dip kaufen"). Ausbrüche in Trendrichtung werden übersprungen (kein Trade).
- **Ausbruchs-Bestätigung**: Der Kandidat wird erst zum echten Trade, wenn der Preis
  `breakout_confirm_bars` Kerzen in Folge jenseits des ursprünglichen Ausbruchs-Levels bleibt.
  Fällt der Preis vorher zurück, verfällt der Kandidat ohne Trade.
- **Erschöpfungs-/Ablehnungskerze**: Zusätzlich muss die Bestätigungskerze selbst ein klassisches
  Preisaktions-Umkehrsignal zeigen — ein Docht gegen die Ausbruchsrichtung, mindestens so groß wie
  der Kerzenkörper (`wick_body_ratio`). Das filtert echte Erschöpfung (Käufer/Verkäufer wurden
  zurückgedrängt) von Ausbrüchen, die einfach nur weiterlaufen — deutlich weniger, aber
  höherwertigere Fade-Setups.
- **Teilausstieg beim ersten Schub**: Erreicht der Preis `partial_tp_r_multiple` × Stop-Distanz in
  die Gewinnzone, wird so viel der Position geschlossen, dass der realisierte Gewinn genau die
  potenziellen Stop-Loss-Kosten deckt. Der Stop der Restposition wandert danach auf den
  Einstiegspreis (Breakeven) — der Rest läuft ab diesem Punkt risikofrei weiter.
- **Ausstieg der Restposition**: Bis der Teilausstieg ausgelöst hat, zählt nur der Stop-Loss (die
  Mean-Reversion braucht Zeit zum Wirken — ein sofortiger Momentum-Exit direkt nach Entry würde die
  Position killen, bevor sich der Preis erholen konnte). Erst nachdem der Teilausstieg bestätigt
  hat, dass sich der Preis erholt, wird zusätzlich die Gegenbewegung scharf geschaltet:
  Schlusskurs kreuzt die schnelle EMA (`ema_fast`) entgegen der Positionsrichtung.
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
python -m src.main --symbol BTC/USDT --timeframe 5m --csv data/btcusdt_5m_sample.csv
```

`--timeframe 1m` funktioniert weiterhin, ist aber Backtests zufolge deutlich schwächer (siehe
"Hinweise" unten).

Alle Parameter lassen sich auch dauerhaft in `config.yaml` setzen; CLI-Flags überschreiben sie.
`--help` zeigt alle Optionen.

Zum Vergleich existiert außerdem eine eigenständige **Inside-Bar-Ausbruchs-Strategie** (siehe
Abschnitt "Hinweise" unten für die Ergebnisse) mit eigenem Entrypoint:

```bash
python -m src.main_insidebar --symbol BTC/USDT --csv data/btcusdt_1m_sample.csv \
  --min-inside-bars 3 --target-range-multiple 1.5
```

Sowie eine **Multi-Timeframe-Variante der Fade-Strategie**: Ausbruchserkennung auf einem höheren
Signal-Zeitrahmen, Einstieg und Positionsüberwachung (Stop-Loss, Teilausstieg, Gegenbewegung)
aber auf 1-Minuten-Basis für präziseres Timing (siehe "Hinweise" unten für die Ergebnisse):

```bash
python -m src.main_mtf --symbol BTC/USDT --csv data/btcusdt_1m_sample.csv \
  --signal-timeframe 5min --trend-timeframe 1h
```

Historische Daten werden über [ccxt](https://github.com/ccxt/ccxt) von Binance geladen (öffentliche
Endpunkte, kein API-Key nötig) und lokal in `data/` als CSV gecacht. Für eigene Daten ohne
Netzwerkzugriff: `src/data.py::load_csv(path)` erwartet die Spalten
`timestamp, open, high, low, close, volume`.

Ergebnisse pro Symbol landen in `results/`:
- `trades_<SYMBOL>.csv` — alle Trades mit Entry/Exit, Größe, Hebel, PnL, Exit-Grund, sowie
  `partial_time/price/size/pnl` für den Teilausstieg (leer, falls kein Teilausstieg erfolgte)
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
| `lookback` | 15 | Kerzen für Range-Hoch/Tief und Volumen-Durchschnitt |
| `volume_multiplier` | 1.5 | Volumen-Spitze = Volumen > n × Durchschnitt |
| `atr_period` | 14 | Perioden für ATR-Berechnung |
| `atr_multiplier` | 2.0 | Stop-Distanz = ATR × Multiplikator |
| `ema_fast` | 9 | EMA-Periode zur Gegenbewegungs-Erkennung |
| `cooldown_bars` | 0 | Sperrfrist (in Kerzen) nach einem Trade, bevor ein neuer eröffnet wird |
| `breakout_confirm_bars` | 3 | Kerzen, die der Preis jenseits des Levels bleiben muss, bevor eingestiegen wird |
| `partial_tp_r_multiple` | 1.5 | R-Vielfaches der Stop-Distanz für den Teilausstieg (Breakeven-Trigger) |
| `trend_timeframe` | "1h" | Höherer Zeitrahmen für den Trendfilter |
| `trend_ema` | 50 | EMA-Periode auf dem höheren Zeitrahmen |
| `vol_lookback` | 100 | Kerzen für den langfristigen ATR-Schnitt (Volatilitäts-Regime) |
| `vol_expansion_multiplier` | 1.2 | Nur handeln, wenn ATR > n × langfristiger ATR-Schnitt |
| `wick_body_ratio` | 1.0 | Mindestverhältnis Docht/Körper der Bestätigungskerze gegen den Ausbruch |
| `risk_pct` | 0.02 | Kapitalrisiko pro Trade (1–3 % empfohlen) |
| `max_leverage` | 2.5 | Obergrenze für automatisch berechneten Hebel |
| `allow_shorts` | true | Short-Einstiege bei Abwärts-Ausbruch zulassen |
| `fee_pct` | 0.0004 | Gebühr pro Trade-Seite (Binance Futures Taker) |

## Hinweise

- **Reines Backtesting** — es wird keine echte Order platziert. Für Live-/Paper-Trading wäre ein
  separates Ausführungsmodul mit API-Keys nötig.
- Ergebnisse eines Backtests sind keine Garantie für zukünftige Performance. Parameter vor
  produktivem Einsatz auf mehreren Zeiträumen und mit Out-of-Sample-Daten validieren.
- **Entwicklungsverlauf auf echten 1m-BTC/USDT-Daten (10 Monate, 432k Kerzen):**
  1. Ursprüngliche Follow-Strategie (Ausbrüche in ihre eigene Richtung handeln), Standardwerte:
     ~40 Trades/Tag, Trefferquote ~20-23 % (long wie short symmetrisch), Profit-Faktor ~0.44-0.56 —
     lief auf null. Symmetrisches Verhalten long/short deutete auf keinen echten Edge hin, eher
     Mean-Reversion des Marktes gegen die eigene Ausbruchs-Logik.
  2. Umgestellt auf **Fade** (gegen den Ausbruch, mit dem 1h-Trend) + Volatilitäts-Regime-Filter:
     Trefferquote stieg zunächst kaum (~22.6 %), weil der EMA-Reversal-Exit eine Fade-Position
     fast sofort wieder killte — man kauft bewusst gegen die gerade laufende Bewegung, das
     Momentum zeigt direkt nach Entry fast immer noch dagegen. Bug behoben: Der Reversal-Exit
     greift jetzt erst, nachdem der 2R-Teilausstieg bestätigt hat, dass sich der Preis erholt.
  3. Mit dem Fix: **1868 Trades, Trefferquote 33.7 %, Profit-Faktor 0.67** (deutliche Verbesserung
     gegenüber der Follow-Strategie, aber noch nicht profitabel). Bottleneck laut Trade-Log: 64 %
     der Trades werden vom Stop-Loss beendet, bevor die Mean-Reversion das 2R-Teilausstiegsziel
     erreicht — nur 36 % kommen so weit.
  4. Stop/Target-Sweep (36 Kombinationen `atr_multiplier` × `partial_tp_r_multiple`): breiterer
     Stop + weiteres Ziel verbessern den Profit-Faktor durchgehend (bis 0.89 bei `atr_mult=8,
     partial_r=4`), aber die Trade-Zahl sinkt dabei auf ~1/Tag (300 Trades) — Risiko, nur Rauschen
     in diesem einen Datenfenster zu fitten statt einen echten Edge zu finden. Als reines
     Parameter-Tuning ohne strukturelle Änderung nicht übernommen.
  5. **Erschöpfungs-/Ablehnungskerzen-Filter** (`wick_body_ratio`, Standardwert 1.0) als
     strukturelle Verbesserung statt weiterem Parameter-Tuning: Nur Bestätigungskerzen mit einem
     Docht mindestens in Körpergröße gegen die Ausbruchsrichtung werden gefadet. Bei unveränderten
     Stop/Target-Werten (1.5×ATR / 2R): **459 Trades, Trefferquote 34.9 %, Profit-Faktor 0.70,
     Gesamtrendite -57.5 %** (Endkapital 4.250 statt 311 bei sonst gleichen Einstellungen) — der
     Effekt kommt hauptsächlich über Selektivität (drastisch weniger, aber höherwertige Setups),
     nicht über eine stark veränderte Trefferquote. Immer noch nicht profitabel (Profit-Faktor < 1),
     aber die bislang beste strukturelle Verbesserung.

  6. **Vergleichstest: reine Inside-Bar-Ausbruchs-Strategie** (`src/main_insidebar.py`,
     eigenständiges Modul, nicht Teil der Fade-Pipeline): Kompression aus `min_inside_bars`
     aufeinanderfolgenden Kerzen innerhalb einer Mother Bar, danach Ausbruch **in** dessen
     Richtung gehandelt (Follow, kein Trend-/Volatilitäts-/Ablehnungsfilter), Stop an der
     gegenüberliegenden Mother-Bar-Seite, Take-Profit als Measured-Move-Ziel
     (`target_range_multiple` × Range-Höhe). 12 Parameterkombinationen getestet — selbst am
     selektivsten Punkt (`min_inside_bars=8`, `target_range_multiple=2.0`: 1359 Trades, 35.0 %
     Trefferquote) nur **Profit-Faktor 0.67, Gesamtrendite -94.4 %** — deutlich schlechter als die
     Fade-Strategie. Inside-Bar-Kompression ist auf 1m-Krypto-Daten extrem häufig (kein seltenes,
     bedeutungsvolles Signal wie auf Tages-/Wochenkerzen), und als Follow-Strategie reproduziert
     sie dasselbe Grundproblem wie die ursprüngliche Volumen-Ausbruch-Strategie (Schritt 1): Auf
     1m-Krypto-Rauschen hat reines Ausbruchs-Folgen keinen nachweisbaren Edge, unabhängig von der
     Selektivität des Filters.

  7. **Timeframe-Test: 5-Minuten-Kerzen statt 1-Minuten** (dieselbe Fade-Strategie, dieselben
     Standardparameter, keine Neu-Optimierung): echte BTC/USDT-5m-Daten (6 Monate, 51.840 Kerzen).
     **64 Trades, Trefferquote 42.2 %, Profit-Faktor 1.16, Gesamtrendite -0.86 %, Max-Drawdown
     -8.1 %** — zum ersten Mal ein Profit-Faktor über 1 und kein Totalverlust. Zur Kontrolle in
     zwei Hälften gesplittet (kein Parameter-Retuning): erste Hälfte PF 1.02, zweite Hälfte
     PF 1.40 — der Effekt zeigt sich in beiden Fenstern, ist also kein Zufallsartefakt eines
     einzelnen Zeitraums. Naheliegende Erklärung: Auf 5m ist das Verhältnis von echtem
     Preissignal zu Marktmikrostruktur-Rauschen deutlich günstiger als auf 1m, und die geringere
     Trade-Zahl reduziert die kumulative Gebührenlast drastisch (64 vs. 1868 Trades im
     vergleichbaren 1m-Test). Datenbasis mit 179 Tagen / 64 Trades aber weiterhin klein — echte
     Bestätigung bräuchte einen längeren Zeitraum.
  8. **Multi-Timeframe: Ausbruchserkennung auf 5m/1h, Einstieg + Überwachung auf 1m**
     (`src/backtest_mtf.py`/`src/main_mtf.py`, eigenständige Engine): Kandidat, Bestätigung,
     Ablehnungskerze und Trend-/Volatilitätsfilter laufen auf dem Signal-Zeitrahmen (per
     `merge_asof` lookahead-frei auf die 1m-Zeitachse projiziert), aber Einstieg erfolgt exakt auf
     der 1m-Kerze, die mit dem Abschluss der auslösenden Signal-Kerze zusammenfällt, und Stop-Loss/
     Teilausstieg/Gegenbewegung werden ab dann auf **jeder** 1m-Kerze geprüft (Gegenbewegungs-EMA
     läuft dafür direkt auf 1m-Daten). Getestet auf den echten 1m-Daten (10 Monate):
     - Signal=5m, Trend=1h: **117 Trades (0.39/Tag), Trefferquote 35.9 %, Profit-Faktor 1.00,
       Gesamtrendite -10.7 %** — nahe am nativen 5m-Test (PF 1.16), etwas schwächer, plausibel
       durch die reaktivere 1m-Gegenbewegungs-EMA (nervösere Exits als die 5m-EMA im nativen Test).
       Bottleneck weiterhin dasselbe Muster: 64 % der Trades enden im vollen Stop-Loss.
     - Signal=1h, Trend=4h: nur **6 Trades in 6 Monaten** — die Kombination aus stündlichem
       Ausbruch, 3 Bestätigungsstunden, Ablehnungskerze und 4h-Trendfilter ist zu selten für eine
       belastbare Aussage.
  9. **Parameter-Sweep auf 5m** (60 Kombinationen `atr_multiplier` × `partial_tp_r_multiple` ×
     `wick_body_ratio`, aktuelle Standardwerte als Ausgangspunkt): Der beste Aggregat-Treffer
     (`atr_mult=4.0, partial_r=4.0`: PF 1.30, +20.4 %) entpuppte sich beim Split-Test (erste vs.
     zweite Hälfte des Zeitraums) als **Overfitting-Falle** — erste Hälfte PF 2.02, zweite Hälfte
     PF 0.64 (Verlust). Der Gewinn kam fast vollständig aus einer einzelnen guten Phase, nicht aus
     einem robusten Edge; dasselbe Muster bei `atr_mult=5.0, partial_r=3.0` (PF 1.92 vs. 0.47).
     Stattdessen gezielt nach einer in **beiden** Hälften profitablen Kombination gesucht:
     **`atr_multiplier=2.0, partial_tp_r_multiple=1.5`** — H1 PF 1.34, H2 PF 1.17, aggregiert
     **64 Trades, Trefferquote 50.0 %, Profit-Faktor 1.27, Gesamtrendite +3.7 %, Max-Drawdown
     -10.1 %**. Konsistent besser als der bisherige Default (PF 1.16/1.02/1.40) und deutlich
     robuster als der reine Aggregat-Bestwert. Als neue Standardwerte übernommen
     (`config.yaml`/`src/backtest.py`).

**Offene Punkte für echte Profitabilität:** Längerer 5m-Datensatz zur saubereren Out-of-Sample-
Validierung (bisher wurde alles auf demselben 6-Monats-Fenster optimiert, mit Split-Test als
Notbehelf — ein drittes, komplett ungesehenes Fenster wäre die eigentliche Bestätigung). Die
Inside-Bar-Strategie legt außerdem nahe, dass Follow-Ansätze auf kurzen Zeitrahmen grundsätzlich
benachteiligt sind — Fade auf 5m bleibt der vielversprechendste Ansatz. **Wichtige Lektion aus dem
Sweep:** Bei kleinen Trade-Zahlen (hier 40-70) immer gegen mehrere Zeitfenster prüfen, nicht nur
den Aggregat-Profit-Faktor optimieren — der beste Einzelwert ist oft der am stärksten überfittete.
- In manchen Sandbox-/CI-Umgebungen ist der Zugriff auf `api.binance.com` durch die
  Netzwerk-Policy blockiert. Die Backtest-Logik selbst ist davon unabhängig (siehe `load_csv`
  für Offline-Nutzung) — auf einer Maschine mit normalem Internetzugang funktioniert der
  Datenabruf über ccxt direkt.
