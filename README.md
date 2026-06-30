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

Das Dashboard ist als cleane "Single-Page Application" (SPA) in einer einzigen HTML-Datei geschrieben. Es beinhaltet drei Tabs:
- **Chartanalyse:** Zeigt die Kauf-/Halten-/Verkauf-Empfehlungen der Charttechnik je Sektor.
- **Fundamentalanalyse:** Eine detaillierte Übersicht aller wichtigen Kennzahlen und Fundamentaldaten der 50 Wertpapiere.
- **Depot Status:** Live-Ansicht des Kassenbestands, des Portfoliowerts und der vollzogenen autonomen Transaktionen des Portfoliomanagers.
