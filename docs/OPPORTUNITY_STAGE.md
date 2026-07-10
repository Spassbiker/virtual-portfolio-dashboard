# Opportunity-Scan + Watch-Modus + adaptive Kaufschwelle

Diese Stufe wurde am 2026-07-10 ergänzt. Sie öffnet das Universum für neue
Wertpapiere jenseits des wöchentlichen Fundamental-Refreshs, ohne dass
frisch aufgenommene Papiere sofort blind gekauft werden.

## Zusammenspiel der drei Bausteine

```
                 ┌───────────────────────────────────────────┐
Werktags 08:30 → │ src/opportunity_scan.sh                    │
                 │  LLM screent Marktnews/Momentum            │
                 │  → 0–3 neue ISINs als Watch-Kandidat       │
                 │    in Funda + Chart (Skelett)              │
                 └───────────────────────────────────────────┘
                                    │
Werktags 09:00 →                    ▼
                 ┌───────────────────────────────────────────┐
                 │ compute_indicators.py                      │
                 │  Watch-ISIN bekommt SMA/RSI/MACD sobald    │
                 │  Historie da ist                           │
                 └───────────────────────────────────────────┘
                                    │
                                    ▼
                 ┌───────────────────────────────────────────┐
                 │ update_depot.py                            │
                 │  – Watch-Kandidaten NICHT gekauft          │
                 │    (fehlende Historie / Marker-Text)       │
                 │  – Adaptive Kaufschwelle:                  │
                 │      max(BUY_FLOOR=6, 80er-Perzentil       │
                 │      aller aktiven Kandidatenscores)       │
                 │  – Fallback = 8 bei <10 aktiven Kandidaten │
                 └───────────────────────────────────────────┘
                                    │
                                    ▼
                 ┌───────────────────────────────────────────┐
                 │ prune_analysis.py                          │
                 │  Sektor-Cap = 15 (ehemals 10)              │
                 │  Priorität: Depot > Watch > Kaufen >       │
                 │             Halten > Verkaufen             │
                 │  Watch-Kandidaten dürfen ohne Chart-Eintrag │
                 │  überleben (bis compute_indicators auffüllt)│
                 └───────────────────────────────────────────┘
```

## Opportunity-Scan (`src/opportunity_scan.sh`)

- **Cadence**: werktags 08:30 (`Portfolio_Opportunity_Scan_CMD`, Berlin).
- **Payload**: LLM-Agent mit `--session-key portfolio-opportunity`,
  Prompt fokussiert auf Marktmomentum, Sektorrotation, Katalysatoren.
- **Output**: max. **3 neue ISINs** pro Lauf, eingefügt in
  `data/fundamentalanalyse_ergebnisse.json` UND als Skelett in
  `data/chartanalyse_ergebnisse.json`.
- **Marker**: `begruendung` beginnt mit „Watch-Kandidat aus Opportunity-Scan: …"
  — Downstream-Code erkennt daran den Watch-Status.
- **Fail-Safe**: Backup vor Lauf, JSON-/ISIN-Diff-Sanity nach Lauf, bei Fehler
  wird das Backup wiederhergestellt. Der 09:00-Manager läuft unabhängig davon.

## Watch-Modus (`update_depot.py`)

Ein Papier ist Watch, wenn eine der folgenden Bedingungen gilt:

1. `begruendung` (Chart oder Funda) enthält einen Marker aus
   `WATCH_MARKERS = ("watch-kandidat", "opportunity-scan")`.
2. Chart-Eintrag hat kein `sma_200` (=`None`/0).
3. Chart-Eintrag hat keinen `indicators_source` (nie durch
   `compute_indicators.py` gelaufen).

Watch-Kandidaten:

- werden **nicht** als Kauf-Kandidaten gewertet (auch bei hohem Score),
- bleiben aber im Universum (nicht durch `prune_analysis.py` gekickt),
- werden im 09:00-Tagesreport als „Watch-Modus: N Kandidat(en) …" gelistet.

Der Watch-Status hebt sich automatisch auf, sobald `compute_indicators.py`
eine belastbare Historie geliefert hat (SMA200 + indicators_source gesetzt).
Ist der Marker-Text noch drin, kann der wöchentliche Fundamental-Refresh
den Text bei nächster Recherche überschreiben.

## Adaptive Kaufschwelle (`update_depot.py`)

Vorher: `BUY_THRESHOLD = 8` (fix). Neu:

```python
BUY_FLOOR = 6                # Mindestschwelle, auch in schwachem Markt
BUY_PERCENTILE = 0.80        # nur Top-20 % der Scores werden Kandidat
BUY_FALLBACK_THRESHOLD = 8   # Fallback bei zu wenigen Datenpunkten
BUY_MIN_CANDIDATES = 10
```

Ablauf pro Lauf:

1. Alle Nicht-Verkaufen-Nicht-Watch-Nicht-Veto-Scores sammeln.
2. Wenn `< BUY_MIN_CANDIDATES` → Schwelle = `BUY_FALLBACK_THRESHOLD`.
3. Sonst → Schwelle = `max(BUY_FLOOR, 80er-Perzentil)`.

Effekt:

- Starker Markt (viele hohe Scores): Latte hebt sich automatisch, nur die
  besten kommen rein — kein Übercalpital-Einsatz in mittelmäßige Werte.
- Schwacher Markt (wenige hohe Scores): Latte fällt auf `BUY_FLOOR`, damit
  überhaupt gekauft wird, aber niemals unter 6.
- Positionsgröße (`budget_for_score`) verwendet die dynamische Schwelle als
  Referenz, damit die Bonus-Rechnung (100 €/Punkt darüber) sich mitzieht.

Die gewählte Schwelle wird im 09:00-Report als eigene Summary-Zeile
sichtbar, damit man Marktphasen an der Schwelle ablesen kann.
