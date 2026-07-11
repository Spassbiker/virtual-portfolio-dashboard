# Virtual Portfolio Dashboard

Dieses Repository beinhaltet das dynamische HTML-Dashboard zur Übersicht der automatisierten Portfoliomanagement-Agenten. 

Es greift auf die Analysen von drei Sub-Agenten zurück:
1. **Agent Marktanalyse & Chartanalyse:** Kurz-, mittel- und langfristige Charttrends.
2. **Agent Fundamentalanalyse:** Kennzahlenvergleich nach Commerzbank-Methodik (KGV, KBV, KUV, KCV, Dividende).
3. **Agent Portfoliomanager:** Autonomes Management des virtuellen Depots (Startkapital 100.000 EUR) auf Basis der Frankfurter Börse.

## 🚀 GitHub Pages Einrichtung

Damit das Dashboard für dich unter einer URL (wie eine echte Webseite) auf GitHub erreichbar ist, kannst du **GitHub Pages** nutzen.

1. **Repository anlegen:** Erstelle ein neues Repository auf deinem GitHub Account (z.B. `virtual-portfolio`).
2. **Dateien hochladen:** Lade die Datei `index.html` direkt in dieses Repository (Main-Branch) hoch.
3. **Pages aktivieren:**
   - Gehe im Repository auf **Settings** (Einstellungen).
   - Wähle links in der Seitenleiste **Pages**.
   - Wähle unter *Build and deployment* -> *Source* den Branch `main` (oder `master`) und als Ordner `/ (root)`.
   - Klicke auf **Save**.
4. **Dashboard aufrufen:** Nach ca. 1-2 Minuten ist dein Dashboard unter `https://spassbiker.github.io/virtual-portfolio-dashboard/` online!

## 📊 Aufbau der `index.html`

Das Dashboard ist als cleane "Single-Page Application" (SPA) in einer einzigen HTML-Datei geschrieben, generiert von `src/build_dashboard.py`. Es ist in vier Bereiche gegliedert:
- **🏠 Übersicht:** Startseite mit Gesamtvermögen, Sektor-Allokation (inkl. Limit-Warnungen), Performance vs. DAX/MSCI World, Top-Mover und Top-Empfehlungen.
- **💼 Portfolio:** Aktien-Depot, ETF-Sleeve und Transaktionshistorie (je als Unter-Tab).
- **🎯 Empfehlungen:** Composite-Score-Ranking für Aktien und ETFs (je als Unter-Tab).
- **🔬 Analyse:** Chartanalyse, Fundamentalanalyse und KI-Sentiment (je als Unter-Tab).

Enthält einen Dark-Mode-Umschalter (Präferenz wird im Browser gespeichert) sowie Sektor- und Performance-Charts als Inline-SVG.
