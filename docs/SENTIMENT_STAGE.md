# KI-Sentiment-Stufe (Stufe 1 + 2)

Diese Stufe ergänzt das deterministische Scoring um eine **qualitative
LLM-Bewertung** aus aktuellen Nachrichten. Kernprinzip: Das LLM sitzt **nur auf
der qualitativen Seite** (Text → Stimmung). Die harte Mathematik (RSI, MACD,
Steuern, Ordergröße) bleibt zu 100 % deterministisch in Python.

## Pipeline-Reihenfolge

```
1. update_prices.py            Live-Kurse
2. compute_indicators.py       RSI/MACD/SMA (deterministisch)
3. (Fundamentalanalyse)        funda-Kennzahlen
4. fetch_news.py               Schlagzeilen  ->  data/news_raw.json          [Python]
5. AGENT-SCHRITT               news_raw.json ->  data/sentiment_scores.json  [LLM]
6. update_depot.py --recommend Score+Sentiment+Veto -> data/trade_recommendations.json  [Python, ändert Depot NICHT]
7. AGENT-ENTSCHEIDUNG          entscheidet autonom, bucht Trades -> data/depot_status.json  [LLM]
```

Schritte 5 und 7 sind die LLM-Schritte. Das regelbasierte System liefert in
Schritt 6 nur einen **Vorschlag** (`--recommend`) — die finale Kauf-/
Verkaufsentscheidung trifft der autonome Portfoliomanager-Agent in Schritt 7.
Er darf den Vorschlägen folgen, abweichen oder eigene Trades ergänzen.

Fehlt `sentiment_scores.json`, rechnet Schritt 6 rein deterministisch
(Chart + Funda) weiter — nichts bricht. Wer den Vorschlag 1:1 buchen will,
kann `update_depot.py` ohne `--recommend` laufen lassen (deterministische
Ausführung mit korrekter Gebühren-/Steuerrechnung).

## Datenvertrag `data/sentiment_scores.json`

```json
{
  "generated_at": "2026-07-05 09:40",
  "scores": {
    "<ISIN>": {
      "sentiment_score": 2,        // Ganzzahl -3..+3, wird in update_depot geklemmt
      "veto": false,               // true blockiert NUR Käufe, erzeugt nie welche
      "confidence": 0.8,           // 0.0-1.0, wie belastbar das Urteil ist (siehe unten)
      "event_kategorie": "Guidance", // Zahlen | Guidance | M&A | Analyst | Sonstiges | Keine
      "begruendung": "Kurztext, warum (1 Satz, konkret)."
    }
  }
}
```

`confidence` und `event_kategorie` sind **optional mit Default** (0.7 bzw.
"Sonstiges") — fehlen sie in einer älteren `sentiment_scores.json`, rechnet
`update_depot.py` unverändert weiter. Kein Bruch bei älteren Dateien.

### Wirkung im Scoring
- **Stufe 1:** Das Sentiment wird über **drei Achsen** gewichtet und als
  dritter Summand zu `chart + funda` addiert:
  `round(sentiment_score × confidence × materiality × recency)`.
  - `confidence` (0–1): wie belastbar das LLM-Urteil ist (subjektiv, s. o.).
  - `materiality` (Event-Materialität, #2): harte Katalysatoren wiegen voll,
    weiche Signale gedämpft — `Zahlen`/`Guidance`/`M&A` = 1.0, `Analyst` = 0.8,
    `Sonstiges` = 0.7, `Keine` = 0.0. Unbekannte Kategorie → 1.0 (kein Effekt).
  - `recency` (Zeit-Decay, #2): objektiver Verfall aus dem Datum der frischesten
    Schlagzeile in `news_raw.json` — `0.5^(Alter_in_Tagen / 5)`, geklemmt auf
    `[0.5, 1.0]`. Kein datiertes Signal → 1.0. Ergänzt die (subjektive)
    Confidence um einen harten Zeitmaßstab: eine Woche alte News wirkt noch halb.
  So wirkt ein schwach belegtes, weiches oder altes Urteil automatisch schwächer
  als ein gut belegter, harter, frischer Katalysator.
- **Stufe 2:** `veto: true` entfernt die ISIN aus den Kaufkandidaten. Ein Veto
  kann eine Position **nicht** erzwingen und keinen Verkauf auslösen — es bremst
  nur Neukäufe. Bestehende Positionen bleiben unberührt (Verkauf entscheidet
  weiter der harte Score / das Verkaufen-Signal).
- **Review-Flag:** `sentiment_score <= -2` **auf einer gehaltenen Position**
  setzt ein `review_flag` im Dashboard (kein Zwangsverkauf, nur Sichtbarkeit —
  die Verkaufsentscheidung bleibt beim harten Score / Agenten).
- **Event-Kategorie:** seit #2 **materialitäts-wirksam** — sie steuert den
  `materiality`-Faktor oben (harte vs. weiche Ereignisse) und bleibt zusätzlich
  im Dashboard filterbar/nachvollziehbar (z.B. "warum war das ein -3?" →
  "Zahlen" statt Rätselraten). Deshalb die Kategorie sorgfältig wählen.

## Prompt für den Agent-Schritt (Schritt 5)

> Lies `data/news_raw.json`. Für **jede** ISIN darin: bewerte die Schlagzeilen
> als Nachrichtenstimmung der letzten Tage für genau dieses Unternehmen.
> Jede Schlagzeile hat ein Feld `quelle` — `adhoc` sind Pflichtmitteilungen
> (DGAP/EQS, via ISIN-Zuordnung garantiert relevant), `google_news`/`yahoo`
> sind Presseartikel (Relevanz bereits vorgefiltert, aber nicht garantiert).
>
> Vergib einen `sentiment_score` von **−3 bis +3**:
> - **+3/+2**: klar positive, kursrelevante News (starke Zahlen, Großauftrag,
>   angehobener Ausblick).
> - **+1/0**: leicht positiv / neutral / nur generische Marktnews.
> - **−1/−2**: belastende News (schwache Zahlen, gesenkter Ausblick, Downgrade).
> - **−3**: schwerwiegend negativ (Gewinnwarnung, Skandal, Ermittlungen).
>
> Setze `veto: true` **nur** bei einem konkreten, akuten Grund, einen Kauf
> jetzt zu vermeiden (z. B. laufende Gewinnwarnung, Übernahme in Schwebe,
> Bilanzskandal). Im Zweifel `false`.
>
> Vergib `confidence` (0.0–1.0): wie belastbar ist dieses Urteil?
> - **0.9–1.0**: mind. eine Ad-hoc-Meldung (`quelle: adhoc`) oder mehrere
>   übereinstimmende, frische (≤2 Tage) Presseartikel.
> - **0.5–0.7**: ein bis zwei plausible, aber nicht ganz frische/eindeutige
>   Artikel.
> - **0.2–0.4**: nur vage/generische Erwähnungen, wenig kursrelevanter Gehalt.
> - **0.0–0.1**: keine verwertbaren Schlagzeilen (dann `sentiment_score: 0`).
>
> Setze `event_kategorie` auf genau eine von: `Zahlen` (Quartals-/Jahreszahlen),
> `Guidance` (Prognoseänderung), `M&A` (Übernahme/Fusion/Verkauf), `Analyst`
> (Kursziel-/Rating-Änderung), `Sonstiges` (anderes kursrelevantes Ereignis),
> `Keine` (keine relevanten News). Bei mehreren Themen: die kursrelevanteste
> Kategorie wählen.
>
> Ignoriere Schlagzeilen, die offensichtlich ein anderes Unternehmen betreffen
> (die Presse-Suche liefert gelegentlich generische Marktartikel — diese
> neutral mit 0 bewerten). Erfinde keine Fakten; bewerte nur, was in den
> Schlagzeilen steht.
>
> Schreibe das Ergebnis exakt im Vertragsformat nach
> `data/sentiment_scores.json`. Jede `begruendung` in einem knappen Satz.

## Warum kein API-Key im Python-Code?

Der Portfoliomanager läuft ohnehin als OpenClaw-Agent-Cron — das ist bereits
ein LLM. Der Agent erledigt Schritt 5 direkt, ohne separaten kostenpflichtigen
API-Zugang. Das hält die Kosten bei null und die Determinismus-Grenze sauber.
