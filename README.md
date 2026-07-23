# Virtual Portfolio Dashboard

Dieses Repository beinhaltet das dynamische HTML-Dashboard zur Übersicht der automatisierten Portfoliomanagement-Agenten.

Verwaltet werden **zwei getrennte Töpfe**: ein **10.000-€-Aktien-Depot** (regelbasierter Composite-Score, Stop-Loss, autonome Trades) und ein separates **5.000-€-ETF-Sleeve** (ranking-basierte, passive Diversifikation je Sektor). Die Handelslogik läuft als reine Shell-/Python-Crons (09:00-Lauf + 17:35-Schlusskurse), unabhängig von einer LLM-Session.

Der Composite-Score je Aktie speist sich aus mehreren Bausteinen:
1. **Chartanalyse (technisch):** Trend, RSI, MACD, SMA-Lage, Momentum (12-1) und 20-Tage-Volatilität.
2. **Fundamentalanalyse:** Peer-Vergleich je Sektor plus deterministische Kennzahlen (EV/EBITDA, PEG, ROE, Piotroski F-Score).
3. **KI-Sentiment & Earnings:** News-Stimmung (gewichtet mit Confidence × Materialität × Recency) und ein forward-looking Guidance-Score aus den letzten Quartalszahlen.
4. **Risiko & Regelwerk:** Positions-/Sektor-Caps, Korrelations-Cluster, dreistufiger Stop-Loss, vola-basiertes Sizing.

## 🚀 GitHub Pages Einrichtung

Damit das Dashboard für dich unter einer URL (wie eine echte Webseite) auf GitHub erreichbar ist, kannst du **GitHub Pages** nutzen.

1. **Repository anlegen:** Erstelle ein neues Repository auf deinem GitHub Account (z.B. `virtual-portfolio`).
2. **Dateien hochladen:** Lade das **komplette Repository** (Main-Branch) hoch – `index.html` **und** den `data/`-Ordner, da das Dashboard die JSON-Daten zur Laufzeit per `fetch()` nachlädt.
3. **Pages aktivieren:**
   - Gehe im Repository auf **Settings** (Einstellungen).
   - Wähle links in der Seitenleiste **Pages**.
   - Wähle unter *Build and deployment* -> *Source* den Branch `main` (oder `master`) und als Ordner `/ (root)`.
   - Klicke auf **Save**.
4. **Dashboard aufrufen:** Nach ca. 1-2 Minuten ist dein Dashboard unter `https://spassbiker.github.io/virtual-portfolio-dashboard/` online!

## 📊 Aufbau der `index.html`

Das Dashboard ist eine "Single-Page Application" (SPA), generiert von `src/build_dashboard.py`. Die Daten werden **zur Laufzeit per `fetch()`** aus `data/*.json` geladen (nicht mehr ins HTML eingebettet), daher braucht die Seite HTTP(S) – die Pages-URL oder lokal `python3 -m http.server`, `file://` funktioniert nicht. Es ist in vier Bereiche gegliedert:
- **🏠 Übersicht:** Gesamtvermögen, **Vermögensverlauf** (indexierte Equity-Kurve Depot/ETF/DAX/MSCI), Sektor-Allokation + Korrelations-Cluster, **Stop-Loss-Warnungen**, Performance vs. DAX/MSCI World, Top-Mover, **Handelsaktivität & Kosten** und Top-Empfehlungen.
- **💼 Portfolio:** Aktien-Depot (inkl. **Stop-Abstand-Ampel** je Position), ETF-Sleeve und Transaktionshistorie (je als Unter-Tab).
- **🎯 Empfehlungen:** Composite-Score-Ranking für Aktien und ETFs (je als Unter-Tab).
- **🔬 Analyse:** Chartanalyse, Fundamentalanalyse, KI-Sentiment und **Attribution** (inkl. Signal-Monitor) – je als Unter-Tab.

Oben zeigen **Datenfrische-Badges** das Alter jeder Quelle (Warnung bei Cron-Ausfall). Enthält einen Dark-Mode-Umschalter (im Browser gespeichert) sowie alle Charts als Inline-SVG. Eine ausführliche Erklärung aller Kennzahlen steht in `docs/parameter-erklaerung.html` (+ PDF).

## 🧪 Tests

- **Python-Engine:** `python3 -m unittest discover -s tests` (72 Tests; läuft als Gate im 09:00-Cron – rote Tests ⇒ keine Trades).
- **Dashboard-Rendering:** `node scripts/dom_smoke_test.js` (jsdom-Runtime-Check aller Sektionen; jsdom unter `~/.dashtest/node_modules`).
