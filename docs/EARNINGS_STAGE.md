# KI-Earnings-/Guidance-Stufe (#1)

Ein **forward-looking** Signal-Layer, getrennt vom (rückblickenden, news-basierten)
Sentiment. Während das Sentiment die Tagesstimmung aus Schlagzeilen misst,
bewertet diese Stufe den **jüngsten Quartals-/Jahresbericht + Ausblick**:
Guidance-Richtung, Margen-/Wachstumstrend und Management-Ton. Das ist ein
langsamer zerfallendes Signal (gilt ~ein Quartal), das die Wertpapier-Auswahl
um die fundamentale Vorwärts-Perspektive ergänzt.

Kernprinzip bleibt wie überall: **Das LLM liefert nur einen geklemmten Score,
die Mathematik bleibt deterministisch in `update_depot.py`.**

## Einordnung in die Pipeline

Der Earnings-Refresh (`src/earnings_refresh.sh`) läuft als eigener wöchentlicher
Command-Cron (analog `fundamentals_refresh.sh`), **vor** der Handelswoche. Er
schreibt `data/earnings_scores.json`. Der 09:00-Manager (`update_depot.py`)
liest die Datei danach. Fehlt sie oder ist sie veraltet, rechnet die Engine
**ohne** diesen Summanden weiter — nichts bricht (gleiche Defensive wie beim
Sentiment).

## Datenvertrag `data/earnings_scores.json`

```json
{
  "generated_at": "2026-07-22 20:00",
  "scores": {
    "<ISIN>": {
      "earnings_score": 2,               // Ganzzahl -3..+3, forward-looking
      "confidence": 0.8,                 // 0.0-1.0, wie belastbar das Urteil ist
      "guidance_richtung": "angehoben",  // angehoben | bestaetigt | gesenkt | keine
      "horizon": "Geschaeftsjahr 2026",  // worauf sich die Guidance bezieht (Freitext)
      "report_datum": "2026-05-07",      // Datum des zugrunde liegenden Berichts (YYYY-MM-DD)
      "begruendung": "Kurztext, warum (1 Satz, konkret)."
    }
  }
}
```

`confidence`, `guidance_richtung`, `horizon`, `report_datum` sind **optional mit
Default** — fehlen sie, rechnet `update_depot.py` unverändert weiter (kein Bruch
bei älteren Dateien). Nur `earnings_score` ist tragend.

### Wirkung im Scoring
- **Eigener Summand:** `round(earnings_score × confidence × EARNINGS_WEIGHT)`
  wird zu `chart + funda + sentiment` addiert. `EARNINGS_WEIGHT = 0.8` dämpft
  das Signal bewusst — es soll **ergänzen**, nicht Chart/Sentiment überstimmen.
- **Kein Veto, kein Zwangsverkauf.** Wie beim Sentiment bewegt dieser Layer nur
  den Score; die eigentliche Kauf-/Verkaufsentscheidung bleibt bei der Engine
  bzw. dem Agenten.
- **Skala** identisch zum Sentiment (−3..+3), damit die Größenordnungen
  vergleichbar bleiben.

## Score-Leitfaden

- **+3/+2:** Guidance **angehoben**, Zahlen deutlich über Erwartung, Margen-/
  Auftragslage klar verbessert, optimistischer Management-Ton.
- **+1/0:** Guidance bestätigt, Zahlen im Rahmen, keine klare Richtung.
- **−1/−2:** Guidance **gesenkt** oder Zahlen unter Erwartung, Margendruck,
  vorsichtiger Ausblick.
- **−3:** Gewinnwarnung, Guidance drastisch gesenkt/zurückgezogen, struktureller
  Bruch im Ausblick.

`confidence` niedrig, wenn der letzte Bericht alt ist (>1 Quartal), die Guidance
vage bleibt oder Quellen widersprüchlich sind; hoch bei frischem Bericht mit
klarer, konsistent berichteter Guidance.

## Prompt für den Agent-Schritt

> Aufgabe: Erzeuge/aktualisiere `data/earnings_scores.json`. Vertrag: **diese
> Datei** (`docs/EARNINGS_STAGE.md`) — LIES SIE ZUERST.
>
> Universum: alle ISINs aus `data/fundamentalanalyse_ergebnisse.json`.
>
> Für **jede** ISIN: Recherchiere per web_search den **jüngsten** Quartals-/
> Jahresbericht und die aktuelle **Guidance** (Ausblick) des Unternehmens.
> Bewerte **forward-looking** — nicht die Tagesstimmung, sondern was der letzte
> Bericht + Ausblick für die kommenden 1-4 Quartale bedeutet. Vergib
> `earnings_score` (−3..+3) nach dem Leitfaden oben, `guidance_richtung`
> (angehoben|bestaetigt|gesenkt|keine), `horizon` (worauf sich die Guidance
> bezieht), `report_datum` (Datum des Berichts, YYYY-MM-DD) und `confidence`.
> Findest du keinen belastbaren Bericht: `earnings_score: 0`, `confidence` niedrig,
> `guidance_richtung: "keine"`, kurze begruendung ("kein aktueller Bericht
> gefunden"). Erfinde keine Zahlen.
>
> WICHTIG: Dies ist ein EINMALIGER CLI-Turn ohne Folge-Turn. Spawne KEINE
> Subagents und rufe NIEMALS sessions_yield auf — recherchiere jede ISIN direkt
> und sequenziell im selben Turn. Schreibe das Ergebnis exakt im Vertragsformat
> nach `data/earnings_scores.json` (UTF-8, indent=2, ensure_ascii=false),
> `generated_at` im Format YYYY-MM-DD HH:MM. Antworte am Ende nur mit:
> FERTIG N ISINs.

## Warum getrennt vom Sentiment?

Sentiment und Earnings haben unterschiedliche **Halbwertszeiten**: Schlagzeilen
verfallen in Tagen (deshalb der Recency-Decay in der Sentiment-Stufe), eine
Guidance gilt bis zum nächsten Bericht. Ein gemeinsamer Score würde das eine vom
anderen verwaschen. Getrennt lassen sich beide unabhängig kalibrieren und im
Dashboard getrennt nachvollziehen.
