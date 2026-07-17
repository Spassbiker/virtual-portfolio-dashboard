"""ETF-Sentiment-Klassifizierung: welcher ETF bekommt welche Sentiment-Logik.

Hintergrund (2026-07-11): Aktien-Sentiment bewertet Firmen-News 1:1. Für ETFs
funktioniert das nicht überall gleich gut - ein Themen-ETF (z.B. Uranium) hat
eine klare Sentiment-Story, ein breiter Sektor-ETF (z.B. MSCI World Energy)
braucht eher ein Sektor-Signal, und Faktor-ETFs (Momentum/Quality/MinVol) haben
gar keine sinnvolle News-Sentiment-Story - die bleiben bewusst außen vor.

Typ A = Themen-ETF: thematische News-Suche (Uran, Cybersecurity, Semiconductor...).
Typ B = breiter Sektor-ETF: Sektor-News-Suche (Energy, Materials, Utilities...).
Kein Eintrag hier = Typ C (Faktor-ETF) oder unklassifiziert -> kein Sentiment.

Wichtig zur Query-Wahl: Yahoos Such-Endpoint (siehe fetch_etf_news.py) matcht
zuverlässig nur auf kurze, einzelne englische Schlagworte, die er intern als
Kategorie/Entity kennt (z.B. "uranium", "defense", "cybersecurity"). Mehrwort-
oder deutsche Queries fallen bei diesem Endpoint erfahrungsgemäß auf einen
generischen Trending-Feed zurück (identische Treffer über alle Themen hinweg -
reines Rauschen). Deshalb bewusst ein Wort pro Thema, gegen Yahoo-Suche
verifiziert (siehe Kommentare). fetch_etf_news.py filtert zusätzlich per
Duplikat-Erkennung gegen diesen Fallback ab.
"""

ETF_THEMES = {
    # --- Typ A: Themen-ETFs -------------------------------------------------
    "IE00B1XNHC34": {"typ": "A", "ticker": "IQQH.DE", "thema": "clean energy"},   # iShares Global Clean Energy Transition
    "IE000NDWFGA5": {"typ": "A", "ticker": "URNU.DE", "thema": "uranium"},        # Global X Uranium
    "IE0002Y8CX98": {"typ": "A", "ticker": "WDEF.MI", "thema": "Rheinmetall"},   # WisdomTree Europe Defence -> Europa-Proxy: "defense" liefert US-News (Kratos), "Rheinmetall" liefert Europa-/NATO-Defense-News. Multi-Wort ("European defense") scheitert an Yahoos Suche.
    "IE000YYE6WK5": {"typ": "A", "ticker": "DFEN.DE", "thema": "defense"},        # VanEck Defense (global/US-lastig, "defense" passt hier)
    "IE000OJ5TQP4": {"typ": "A", "ticker": "ASWC.DE", "thema": "drone"},          # HANetf Future of Defence (Next-Gen/Drohnen)
    "IE000YU9K6K2": {"typ": "A", "ticker": "JEDI.DE", "thema": "space"},          # VanEck Space Innovators
    "IE00BYPLS672": {"typ": "A", "ticker": "USPY.DE", "thema": "cybersecurity"},  # L&G Cyber Security
    "IE00BYVQ9F29": {"typ": "A", "ticker": "NQSE.DE", "thema": "nasdaq"},         # iShares NASDAQ US Tech
    "IE00BYZK4552": {"typ": "A", "ticker": "2B76.DE", "thema": "robotics"},       # iShares Automation & Robotics
    "IE00BMC38736": {"typ": "A", "ticker": "VVSM.DE", "thema": "semiconductors"}, # VanEck Semiconductor

    # --- Typ B: breite Sektor-ETFs -------------------------------------------
    "IE00BM67HN09": {"typ": "B", "ticker": "XDWS.DE", "thema": "energy"},         # iShares MSCI World Energy Sector
    "IE00BM67HS53": {"typ": "B", "ticker": "XDWM.DE", "thema": "materials"},      # Xtrackers MSCI World Materials
    "IE00B4LN9N13": {"typ": "B", "ticker": "2B7C.DE", "thema": "industrial"},     # iShares S&P 500 Industrials Sector
    "IE00BM67HV82": {"typ": "B", "ticker": "XDWI.DE", "thema": "industrial"},     # Xtrackers MSCI World Industrials
    "IE000CK5G8J7": {"typ": "B", "ticker": "CBUX.DE", "thema": "infrastructure"}, # iShares Global Infrastructure
    "IE00BM67HT60": {"typ": "B", "ticker": "XDWT.DE", "thema": "technology"},     # iShares MSCI World Information Technology
    "DE000A0H08H3": {"typ": "B", "ticker": "EXH3.DE", "thema": "utilities"},      # iShares STOXX Europe 600 Utilities
    "IE00BM67HQ30": {"typ": "B", "ticker": "XDWU.DE", "thema": "utilities"},      # Xtrackers MSCI World Utilities
    "LU1834988864": {"typ": "B", "ticker": "LUTI.DE", "thema": "utilities"},      # Lyxor/Amundi STOXX Europe 600 Utilities

    # --- Typ C (Faktor-ETFs): bewusst kein Eintrag -> kein Sentiment --------
    # IE00BL25JP72 XDEM.DE Momentum, IE00BP3QZ601 IS3Q.DE Quality,
    # IE00BL25JN58 XDEB.DE MinVol - Regime-/Faktor-Signale statt News-Sentiment.
}
