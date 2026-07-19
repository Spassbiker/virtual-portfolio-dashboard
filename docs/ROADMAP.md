# Roadmap: Erweiterte Analysemethoden

Ziel: Composite-Score (`update_depot.py:total_score`) um Momentum, robustere
Fundamentaldaten und echte Diversifikationsmessung erweitern — ohne neue
Datenquelle/Zusatzkosten, jede Phase einzeln testbar und rollback-fähig.

Reihenfolge nach Aufwand/Nutzen: 1 → 2 → 5 (billig, hoher Hebel), danach 3, dann 4.

## Phase 1 — Momentum-Faktor ⏳
- `compute_indicators.py`: 12-1-Monats-Return aus der 1y-Historie (Kurs vor 21
  Handelstagen ÷ Kurs vor 252 Handelstagen − 1) → Feld `momentum_12_1`.
- `compute_chart_score`: gestaffelte Punkte, analog RSI-Logik.
- Test: Ranking-Diff vor/nach, Plausibilitätscheck starke Läufer.

## Phase 2 — EV/EBITDA + PEG + ROE ✅
- `fetch_valuation.py`: ein `quoteSummary`-Call je ISIN
  (`defaultKeyStatistics,financialData`) → `ev_ebitda`, `peg_ratio`, `roe`
  deterministisch ins Funda-JSON (ergänzt LLM-Felder, ersetzt sie nicht).
- `compute_funda_score`: PEG < 1 Bonus, ROE > 15% Bonus, EV/EBITDA sektorunabhängig grob geclampt.
- Kein LLM-Aufruf nötig, ein HTTP-Call pro ISIN.

## Phase 5 — Korrelationsmatrix (Depotebene) ✅
- `correlation_report.py`: 90-Tage-Tagesrenditen je Position, paarweise
  Korrelation.
- Ergänzt (nicht ersetzt) den Sektor-Klumpen-Check in `risk_report.py`:
  Warnung bei Cluster >0.7 Korrelation, das X% des Depots ausmacht.
- Grund für Priorität vor Sharpe/VaR: verbessert echte Entscheidungen
  (Kaufen/Sizing/Warnen), nicht nur Reporting.

## Phase 3 — ATR-basiertes Position-Sizing ⏳
- High/Low in `fetch_history` mitladen, ATR(14) berechnen.
- `budget_for_score`/`_make_buy_record`: Positionsgröße invers zur
  ATR-Volatilität skalieren (Risk-Parity statt Euro-Parity je Trade).
- Bonus: dynamische Stop-Distanz (2×ATR) zusätzlich zum bestehenden
  −20%/−12%-Stop.

## Phase 4 — Piotroski F-Score ⏳
- `fetch_piotroski.py`: Bilanz/GuV/Cashflow via `quoteSummary`
  (`incomeStatementHistory,balanceSheetHistory,cashflowStatementHistory`),
  9 Kriterien → Score 0-9 ins Funda-JSON.
- `compute_funda_score`: F≥7 Bonus, F≤2 Malus/Warnflag.
- Zuletzt, weil Datenparsing am fragilsten ist.

## Nicht umgesetzt (bewusst zurückgestellt)
DCF, Dividend-Discount, Graham-Number, Altman Z-Score, Bollinger/ADX/Stochastik,
Sharpe/Sortino/VaR auf Aktienseite, Earnings-Kalender, Analysten-Konsens,
Insider-Trades, Short-Interest. Grund: geringerer Hebel pro Aufwand oder
zusätzliche Datenquelle/Kosten nötig. Bei Bedarf jederzeit nachziehbar.

## Workflow je Phase
1. Implementieren + lokal gegen aktuelle `data/*.json` testen (kein Live-Schreiben
   in den Cron-Pfad ohne Review).
2. Ranking-Diff zeigen (welche ISINs rutschen wie stark).
3. Git-Commit.
4. Erst nach Freigabe in den 09:00-Cron-Pfad scharf schalten.
