# Vorschlag: Dashboard-Verbesserungen (Stand 2026-07-23)

Basis: Ist-Analyse nach Abschluss des Optimierungsplans (D11: fetch-basiertes
Dashboard, 4 Tabs, SVG-Charts für Sektor-Allokation + Benchmark-Vergleich).
Das Dashboard zeigt heute nur **Momentaufnahmen** — die größten Lücken sind
Zeitverlauf, Risiko-Frühwarnung und die Sichtbarkeit der bereits erzeugten
Reports (Attribution, Signal-Logging).

Designprinzip (aus den Consistency-Fixes gelernt): Alles, was Engine-Logik
berührt (Stops, Empfehlungen), wird **zur Build-Zeit in Python** aus den
Engine-Funktionen berechnet (`src/consistency.py`-Muster), nie in JS
dupliziert. Das Dashboard zeigt, was die Engine tut — keine Parallelwelt.

## V1 — Vermögensverlauf (Equity-Kurve) 🔴 höchste Priorität

**Problem:** `benchmark` vergleicht nur Anker (09.07.) vs. heute. „−2,0 % vs.
DAX −0,8 %" sagt nicht, ob der Abstand wächst oder schrumpft, ob die
Underperformance ein Einmalereignis war (Defense-Verkäufe 16./20.07., siehe
Attribution) oder ein Trend.

**Vorschlag:**
- Neuer Schritt im 09:00-Lauf: eine Zeile pro Tag nach
  `data/vermoegen_history.jsonl` appenden:
  `{datum, depot_gesamt, etf_gesamt, cash_depot, cash_etf, dax, msci}`.
  Idempotent (gleicher Tag ⇒ überschreiben statt doppeln).
- Übersicht-Tab: SVG-Liniendiagramm Depot vs. DAX vs. MSCI World,
  alle indexiert auf 100 am Benchmark-Anker. ETF-Sleeve als vierte Linie.
- Backfill: nur Ankerpunkt 09.07. + heutiger Stand (mehr Historie existiert
  nicht); Kurve füllt sich ab sofort täglich.

**Aufwand:** klein (Logger ~30 Zeilen, SVG-Renderer analog
`svgPerformanceCompare`). **Nutzen:** die eine Grafik, die die Kernfrage
„funktioniert das System?" beantwortet.

## V2 — Stop-Loss-Ampel (Risiko-Frühwarnung) 🔴

**Problem:** Es gibt drei Stop-Stufen (Hard −20 %, DAX-relativ −12 % mit
Auto-Beta, Vola-Stop 6–18 % vom Trailing-Anker), aber das Dashboard zeigt
nirgends, **wie nah** jede Position an ihrem engsten Stop steht. Lockheed
stand tagelang bei −17 % ohne sichtbare Warnung.

**Vorschlag:**
- Build-Zeit-Berechnung (Python, Engine-Funktionen aus `update_depot.py`
  importieren bzw. nach `src/consistency.py` ziehen): je Position Abstand zum
  engsten der drei Stops in Prozentpunkten + welcher Stop es ist.
- Portfolio-Tab: Spalte „Stop-Abstand" mit Ampel
  (🟢 >8 pp, 🟡 3–8 pp, 🔴 <3 pp), sortierbar.
- Übersicht-Tab: Kachel „Nächster Stop: {Titel} ({x} pp bis {Stop-Typ})",
  nur wenn 🔴/🟡 vorhanden.

**Aufwand:** mittel (Stop-Logik ist da, muss aber sauber extrahiert werden —
Tests existieren bereits und sichern das ab). **Nutzen:** hoch, echtes
Frühwarnsystem statt Überraschungs-Verkäufe im Morgenlauf.

## V3 — Datenfrische-Header 🟡

**Problem:** Der 9-Tage-Crash (null-trend) blieb unsichtbar, weil das
Dashboard veraltete Daten kommentarlos anzeigt. `healthcheck.py` existiert,
aber sein Ergebnis landet nicht im Dashboard.

**Vorschlag:**
- Build schreibt `data/meta.json`: je Datenquelle (Kurse, Chartanalyse,
  Funda, Sentiment, Earnings, ETF-Ranking) letzter Stand + Alter in Tagen.
- Dashboard-Header: kompakte Badge-Zeile; Quelle älter als Schwellwert
  (Kurse >1 Handelstag, Funda >7 Tage, Sentiment >7 Tage) ⇒ gelbes/rotes
  Badge mit Alter. Optional Healthcheck-Score (x/10) daneben.

**Aufwand:** klein. **Nutzen:** verhindert die Wiederholung des stillen
9-Tage-Ausfalls auf der Anzeige-Seite.

## V4 — Aktivitäts- & Kosten-Kachel 🟡

**Problem:** Die Attribution fand ~60 € Gebühren-Churn als relevanten
Performance-Fresser. Das Dashboard zeigt Transaktionen nur als Rohliste
(37 Stück), ohne Summen.

**Vorschlag:** Übersicht-Kachel aus `transaktionshistorie.json` (beide
Depots): Trades und Gebühren im laufenden Monat + kumuliert, realisierte
G/V-Summe. Mini-Balken Trades/Monat. Achtung: Feld heißt `gebuehr`
(Aktien-Depot); ETF-Historie ggf. angleichen.

**Aufwand:** klein. **Nutzen:** macht Churn sofort sichtbar — die
Regel-Verbesserungen (Hysterese, Caps) lassen sich daran messen.

## V5 — Attribution-Report im Analyse-Tab 🟢

**Problem:** `docs/attribution/2026-07-23.md` (und künftig monatlich per
Cron) ist nur im Repo lesbar, nicht im Dashboard.

**Vorschlag:** Build kopiert den neuesten Attribution-Report als JSON/HTML
nach `data/` und rendert ihn im Analyse-Tab (Markdown-light: Überschriften,
Listen, Tabelle). Kernzahlen (Top-3-Kontributoren positiv/negativ, Gebühren)
zusätzlich als Kacheln.

**Aufwand:** klein. **Nutzen:** mittel — Erkenntnisse landen dort, wo man
täglich hinschaut.

## V6 — Signal-Monitor (Vorbereitung Mitte August) 🟢

**Problem:** `sentiment_history.jsonl` (85 Zeilen) und
`etf_composite_history.jsonl` (22) sammeln Forward-Returns; die Auswertung
ist ab ~Mitte August fällig. Es gibt keinen Ort, der den Füllstand zeigt.

**Vorschlag:** Analyse-Tab, kleine Sektion: Zeilen gesamt, davon mit
gefülltem `forward_return_5d`, geschätztes „auswertbar ab"-Datum. Sobald die
Auswertung läuft (C9-Report): Hit-Rate/Korrelation je Faktor direkt hier
anzeigen.

**Aufwand:** klein. **Nutzen:** heute klein, ab August der Ort, an dem
über Faktor-Gewichte entschieden wird.

## Reihenfolge & Umsetzung

V1 → V3 → V2 → V4 → V5 → V6. V1/V3/V4 sind je <1 Session; V2 braucht das
saubere Herausziehen der Stop-Logik (Tests grün halten). Jeder Punkt einzeln
committet, Workflow wie gehabt: implementieren → Diff/Screenshot zeigen →
scharf schalten. Kein neuer Netz-Call, keine neue Datenquelle nötig —
alles speist sich aus vorhandenen Läufen.

---

## Umsetzungsstand 2026-07-23 (alle Punkte, je eigener Commit)

- **V1 ✅** `src/log_vermoegen.py` (idempotente Tageszeile, Anker-Seeding) in
  beide Cron-Skripte eingehängt; SVG-Linienchart mit Crosshair-Tooltip,
  Legende und kollisionsgeprüften End-Labels in der Übersicht. 4 Tests.
- **V3 ✅** Build schreibt `data/meta.json` (mtime je Quelle + Warnschwelle);
  Badges berechnen das Alter ZUR ANSICHTSZEIT — warnt auch bei totem Cron.
- **V2 ✅** `compute_stop_info()` in update_depot.py (nach Kurs aufgelöste
  Verkaufsbedingungen, engster Stop gewinnt) schreibt `stop_info` je Position;
  Dashboard zeigt Ampel-Spalte (🟢>8 / 🟡3–8 / 🔴<3 %) + Übersicht-Warnung.
  6 Tests. Anzeige-Backfill für heute ausgeführt (Lockheed 🟡 3,6 % vor
  Hard-Stop, Terna Vola-Stop 10,2 %).
- **V4 ✅** Monats-Tabelle Trades/Gebühren/Steuern/realisierte G/V aus beiden
  Transaktionshistorien (rein client-seitig, Daten waren schon geladen).
- **V5 ✅** Build kopiert neuesten `docs/attribution/*.md` nach
  `data/attribution_latest.json`; Analyse-Tab „📉 Attribution" rendert ihn
  ausrichtungserhaltend (Überschriften → HTML, Rest `<pre>`).
- **V6 ✅** Build verdichtet die Forward-Return-Logs (.jsonl) nach
  `data/signal_monitor.json`; Anzeige mit Füllstand und „auswertbar ab"
  (Aktien ~15.08., ETF ~20.08.) im Attribution-Tab.
- **Bonus:** `scripts/dom_smoke_test.js` — jsdom-Runtime-Test des kompletten
  Dashboards (fetch-Shim auf data/), 10 Checks; fängt JS-Laufzeitfehler, die
  `node --check` nicht sieht. jsdom liegt unter `~/.dashtest/node_modules`.
