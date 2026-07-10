# Fundamentalanalyse-Stufe

Diese Stufe pflegt die **qualitativen Kennzahlen** je Wertpapier: KGV,
Wachstumsraten, Bewertung, Risiko-Einschätzung und einen kompakten
Begründungstext. Sie ergänzt die deterministische Chartanalyse und das
News-Sentiment.

## Aktualisierungsrhythmus

- **Wöchentlich**, Sonntag 20:00 (vor der Handelswoche), via
  `src/fundamentals_refresh.sh`.
- Der Refresh macht `web_search`-Abfragen pro ISIN, extrahiert Kennzahlen
  und schreibt die komplette Datei neu.
- **Backup**: Vor dem Überschreiben wird die alte Datei nach
  `data/fundamentalanalyse_ergebnisse.backup.json` kopiert. Rollback per
  `cp` möglich.
- Fällt der Refresh aus (Credits/Timeout), rechnet der 09:00-Manager mit
  dem letzten Stand weiter — nichts bricht.

## Datenvertrag `data/fundamentalanalyse_ergebnisse.json`

```json
{
  "sektoren": {
    "<Sektorname>": [
      {
        "wertpapier": "Rheinmetall",
        "isin": "DE0007030009",
        "begruendung": "1–2 Sätze konkrete Fundamental-Aussage.",
        "kgv": "28",                     // String oder Zahl; "n/a" wenn unbekannt
        "dividendenrendite": 1.2,        // Zahl in %; 0.0 wenn keine
        "umsatzwachstum_yoy": 17.27,     // Zahl in % YoY
        "gewinnwachstum_yoy": 29.63,     // Zahl in % YoY
        "eigenkapitalquote": 25.06,      // Zahl in %
        "bewertung": "Attraktiv",        // Attraktiv | Neutral | Unattraktiv | Spekulativ
        "risiko": "Niedrig",             // Niedrig | Mittel | Hoch
        "datum": "2026-07-10",           // YYYY-MM-DD, generierungsdatum
        "aktueller_kurs": 1013.20,       // vom Manager überschrieben, nur informativ
        "empfehlung": "Kaufen"           // Kaufen | Halten | Verkaufen | N/A
      }
    ]
  }
}
```

## Regeln für den Refresh-Agent

1. **Positionen erhalten + Sektor-Minimum**: Alle bestehenden ISINs bleiben
   drin. Zusätzlich soll jeder Sektor **mindestens 10 Wertpapiere** enthalten
   – wenn ein Sektor darunter liegt, ergänzt der Refresh passende EU-handelbare
   Kandidaten (EUR-Listing an XETRA/Euronext/Frankfurt). Nur ISINs mit
   verifizierbarem EUR-Handel; keine reinen US-Werte, keine Platzhalter.
   Wenn keine 10 sauberen Kandidaten existieren, soweit möglich ergänzen.
2. **Cross-Sektor-Duplikate**: Kommt eine ISIN in mehreren Sektoren vor
   (z. B. Airbus in „Verteidigung" und „Satellitentechnik"), dürfen
   `kgv`, `umsatzwachstum_yoy`, `gewinnwachstum_yoy`, `eigenkapitalquote`,
   `dividendenrendite` **nicht divergieren** (Unternehmens-Kennzahlen sind
   sektor-unabhängig). `bewertung`, `risiko`, `empfehlung` und
   `begruendung` dürfen je Sektor-Rolle unterschiedlich sein.
3. **Platzhalter**: Einträge, deren aktuelle `begruendung` mit
   „Ergänzt zur Vervollständigung" beginnt und für die kein sinnvoller
   Recherche-Zugang möglich ist, bleiben Platzhalter mit
   `empfehlung: "N/A"`.
4. **Delisted / nicht handelbar**: Wenn ein Wertpapier delisted ist,
   `empfehlung: "N/A"`, Text erwähnt den Status.
5. **Bewertung ableiten**: Basierend auf KGV vs. Branche + Wachstum +
   Marktposition. „Attraktiv" ≈ Kaufen-Kandidat, „Neutral" ≈ Halten,
   „Unattraktiv" ≈ zu teuer, „Spekulativ" ≈ Turnaround/hohes Risiko.
6. **Risiko**: „Niedrig" bei etablierten Marktführern mit stabilem
   Cashflow. „Mittel" bei zyklischen Werten. „Hoch" bei Wachstumswerten
   ohne Gewinn, hoher Verschuldung oder Turnaround-Situationen.
7. **Text**: 1–2 Sätze, konkret, ohne Kursnennung (Kurse ändern sich
   täglich, Text soll eine Woche halten). Referenzen auf SMA/RSI **nicht**
   in Fundamental-Text — das gehört in die Chartanalyse.
8. **datum**: heutiges Datum in `YYYY-MM-DD`.
9. **aktueller_kurs**: unangetastet lassen (wird vom Manager täglich
   überschrieben).

## Wirkung im Scoring (`update_depot.py`)

- `empfehlung = "kaufen"` → +3 Fundamental-Score
- `empfehlung = "verkaufen"` → −5 Fundamental-Score
- `bewertung = "attraktiv"` → +2, `"neutral"` → +1, `"unattraktiv"` → −1
- `risiko = "niedrig"` → +2, `"mittel"` → +1, `"hoch"` → −1
- `gewinnwachstum_yoy > 20` → +2, `> 5` → +1, `< 0` → −1
- Platzhalter-Einträge (Text „Vervollständigung"/„Ergänzt zur"/„Platzhalter")
  werden per `is_funda_placeholder` neutralisiert (Score 0).
