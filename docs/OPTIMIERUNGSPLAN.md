# Optimierungsplan Virtuelles Depot (Stand 2026-07-23)

Basis: Ist-Analyse vom 23.07. — System läuft technisch sauber (09:00-Lauf heute
fehlerfrei, Healthcheck 10/10, alle Daten frisch), aber es gibt klare
Schwachstellen in Robustheit, Regelwerk und Wirksamkeitsmessung.

## Befund

**Performance:** Depot −2,0 % seit Benchmark-Anker 09.07. vs. DAX +0,15 % /
MSCI World +0,23 % → ~2,2 pp Underperformance in 2 Wochen. Ursache unklar
(keine Attribution vorhanden).

**Risiko Aktien-Depot (10.000 €):**
- Top-5-Positionen = 74 % des Depots; Nvidia 19,5 %. Es gibt einen
  Sektor-Cap (30 %), aber **keinen Einzelpositions-Cap**.
- Lockheed Martin −17 % → nahe am −20%-Hard-Stop; fixer Stop lässt
  Verlierer lange laufen (dynamische Stop-Distanz war als Phase-3-Bonus
  vorgesehen, nie umgesetzt).
- Cash 25,88 € → kein Puffer, jede Kaufempfehlung erfordert Verkauf.

**ETF-Sleeve (5.000 €):** 17 Positionen, davon 8 unter 200 € (kleinste 53 €)
→ Fragmentierung trotz De-Frag-Fix vom 18.07.; Mini-Positionen erzeugen
Rauschen ohne Renditebeitrag.

**Technik/Prozess:**
- **Keine Tests.** Der 9-Tage-Crash (null-trend) und der Clean-Energy-Fehlkauf
  wären mit Regressionstests aufgefallen.
- Logs nur in /tmp (flüchtig, weg nach Reboot).
- Roadmap Phase 1 (Momentum 12-1) ist der einzige offene Roadmap-Punkt.
- build_dashboard.py 1.705 Zeilen, update_depot.py 1.160 Zeilen — Monolithen.
- Signal-Kalibrierung (sentiment_history.jsonl) läuft erst seit kurzem
  (85 Zeilen), Forward-Returns noch überwiegend leer — noch nie ausgewertet.

## Block A — Fehlerbeseitigung & Robustheit (zuerst)

1. **Regressionstests (pytest)** für die Engine-Kernlogik:
   Fixture-JSONs + Tests für `update_depot.py` (Stop-Loss beide Stufen,
   Sektor-Abbau, total_score inkl. Earnings/Materialität/Recency, Crash-Fälle
   wie trend=null), `update_etf_depot.py` (Konviktions-Floor, Top-up,
   Mindestgröße), `consistency.py`. Einbindung als Pre-Commit-Schritt in die
   Refresh-Shellskripte (Abbruch bei Rot statt Handel mit kaputter Logik).
2. **Persistente Logs:** /tmp/pf_*.log → `logs/` im Projekt mit
   Datumsrotation (z. B. 30 Tage), damit Ausfälle auch nach Reboot
   nachvollziehbar sind. .gitignore-Eintrag.
3. **ETF-Mindestposition hart durchsetzen:** Neu-/Restkäufe unter ~200 €
   blockieren; bestehende Mini-Positionen (<150 €, aktuell 5 Stück)
   in die nächsthöher gerankte gehaltene Position konsolidieren.

## Block B — Regelwerk-Verbesserungen

4. **Einzelpositions-Cap Aktien-Depot** (Vorschlag 20 %): Trim-Regel analog
   Sektor-Abbau (Überschuss verkaufen, schwächste zuerst ist hier nicht nötig —
   einfach auf Cap zurückstutzen), Kauf-Cap ebenfalls 20 %.
5. **Momentum 12-1 (Roadmap Phase 1):** `momentum_12_1` in
   compute_indicators.py + gestaffelte Punkte in compute_chart_score;
   Ranking-Diff vor Scharfschaltung zeigen.
6. **Dynamische Stop-Distanz:** 2×`volatility_20d` als engerer dritter Stop
   zusätzlich zu −20 %/−12 % (Vola-Daten existieren schon aus Phase 3).
   Low-Vol-Titel stoppen dann früher als −20 %.
7. **Cash-Puffer-Regel:** Zielband z. B. 2–5 % Cash statt Vollinvestition,
   damit Kaufsignale nicht immer Zwangsverkäufe auslösen.

## Block C — Wirksamkeit messen (laufend)

8. **Performance-Attribution seit 09.07.:** Aus transaktionshistorie.json +
   Kursdaten: welche Trades/Regeln haben die −2,2 pp vs. DAX verursacht
   (Stop-Whipsaws? Kauf-Timing? Einzeltitel?). Einmalige Analyse als Report,
   danach monatlich.
9. **Signal-Evaluation:** Sobald sentiment_history.jsonl ~4 Wochen gefüllte
   forward_return_5d hat: Korrelation Score↔Return je Faktor (Sentiment,
   Earnings, Chart, Funda). Konsequenz: Gewichte anpassen oder Faktor raus.
   Gleiches Logging für den ETF-Composite ergänzen.

## Block D — Wartbarkeit (danach, optional)

10. **Modularisierung:** update_depot.py und build_dashboard.py in Module
    aufteilen (Scoring / Regeln / IO getrennt) — erst NACH Block A
    (Tests zuerst, dann gefahrlos refactoren).
11. Dashboard: Daten (JSON) von Markup trennen statt 337-KB-index.html
    pro Lauf neu zu generieren; Git-History wird dadurch schlanker.

## Reihenfolge & Aufwand

A1–A3 zuerst (Robustheit vor neuen Features), dann B4–B7 einzeln mit
Ranking-/Verhaltens-Diff vor Scharfschaltung (Workflow wie in ROADMAP.md),
C8 parallel als Einmal-Analyse, C9 ab ~Mitte August (Datenlage), D zuletzt.
Jeder Punkt einzeln committet und rollback-fähig.
