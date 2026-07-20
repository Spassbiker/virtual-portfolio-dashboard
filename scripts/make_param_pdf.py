#!/usr/bin/env python3
"""Erzeugt docs/parameter-erklaerung.pdf aus strukturierten Inhalten.
Reiner Standard-Python-Generator (keine externen Libs, kein Browser).
Helvetica (Standard-14-Font), A4, WinAnsi/cp1252-Encoding."""
import os, zlib

# ---------- Helvetica AFM-Breiten (Einheiten/1000) ----------
_W = {
 ' ':278,'!':278,'"':355,'#':556,'$':556,'%':889,'&':667,"'":191,'(':333,')':333,
 '*':389,'+':584,',':278,'-':333,'.':278,'/':278,'0':556,'1':556,'2':556,'3':556,
 '4':556,'5':556,'6':556,'7':556,'8':556,'9':556,':':278,';':278,'<':584,'=':584,
 '>':584,'?':556,'@':1015,'A':667,'B':667,'C':722,'D':722,'E':667,'F':611,'G':778,
 'H':722,'I':278,'J':500,'K':667,'L':556,'M':833,'N':722,'O':778,'P':667,'Q':778,
 'R':722,'S':667,'T':611,'U':722,'V':667,'W':944,'X':667,'Y':667,'Z':611,'[':278,
 '\\':278,']':278,'^':469,'_':556,'`':333,'a':556,'b':556,'c':500,'d':556,'e':556,
 'f':278,'g':556,'h':556,'i':222,'j':222,'k':500,'l':222,'m':833,'n':556,'o':556,
 'p':556,'q':556,'r':333,'s':500,'t':278,'u':556,'v':500,'w':722,'x':500,'y':500,
 'z':500,'{':334,'|':260,'}':334,'~':584,
 'ä':556,'ö':556,'ü':556,'ß':556,'Ä':667,'Ö':778,
 'Ü':722,'–':556,'—':1000,'€':556,'×':584,'²':333,
 '„':556,'“':556,'’':191,'°':400,
}
def cw(ch, bold=False):
    w = _W.get(ch, 556)
    return w*1.045 if bold else w  # Bold minimal breiter -> konservativ

# ---------- Zeichen-Ersetzungen (nicht in cp1252) ----------
_REPL = {'→':'->','≤':'<=','≥':'>=','≈':'~','‑':'-',
         ' ':' ','…':'...','▶':'>','•':'-'}
def clean(s):
    for k,v in _REPL.items(): s = s.replace(k,v)
    # alles was cp1252 nicht kann -> '?'
    out=[]
    for ch in s:
        try: ch.encode('cp1252'); out.append(ch)
        except: out.append('?')
    return ''.join(out)

def text_width(s, size, bold=False):
    return sum(cw(c,bold) for c in s)*size/1000.0

def wrap(s, size, maxw, bold=False):
    words = s.split(' ')
    lines=[]; cur=''
    for w in words:
        t = (cur+' '+w).strip()
        if text_width(t,size,bold) <= maxw or not cur:
            cur=t
        else:
            lines.append(cur); cur=w
    if cur: lines.append(cur)
    return lines

# ---------- PDF-Grundgerüst ----------
PAGE_W, PAGE_H = 595.28, 841.89   # A4
ML, MR, MT, MB = 56, 56, 60, 56
CW = PAGE_W-ML-MR

pages=[]           # jede: list of content-strings
cur=[]; y=[PAGE_H-MT]
def newpage():
    global cur
    if cur: pages.append(cur)
    cur=[]; y[0]=PAGE_H-MT
def esc(s): return s.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
def draw(x, ypos, s, size, font='F1'):
    cur.append(f"BT /{font} {size} Tf {x:.2f} {ypos:.2f} Td ({esc(clean(s))}) Tj ET")
def rect(x,ypos,w,h,rgb):
    r,g,b=rgb
    cur.append(f"{r:.3f} {g:.3f} {b:.3f} rg {x:.2f} {ypos:.2f} {w:.2f} {h:.2f} re f 0 0 0 rg")
def hline(ypos,rgb=(0.8,0.83,0.9)):
    r,g,b=rgb
    cur.append(f"{r:.3f} {g:.3f} {b:.3f} RG 0.6 w {ML:.2f} {ypos:.2f} m {PAGE_W-MR:.2f} {ypos:.2f} l S 0 0 0 RG")

def need(h):
    if y[0]-h < MB: newpage()

def para(s, size=10.5, font='F1', lead=None, indent=0, color=None, gap=0, bold=False):
    lead = lead or size*1.32
    for ln in wrap(s, size, CW-indent, bold=bold):
        need(lead)
        if color: cur.append(f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg")
        draw(ML+indent, y[0]-size, ln, size, font)
        if color: cur.append("0 0 0 rg")
        y[0]-=lead
    y[0]-=gap

# ---------- Inhalt ----------
ACCENT=(0.30,0.64,1.0); MUT=(0.42,0.47,0.56); DARK=(0.10,0.13,0.20)

def h1(s):
    need(40); draw(ML,y[0]-22,s,22,'F2'); y[0]-=30
def h2(num,s):
    need(46); y[0]-=6; hline(y[0]); y[0]-=18
    cur.append(f"{DARK[0]:.3f} {DARK[1]:.3f} {DARK[2]:.3f} rg")
    draw(ML,y[0]-15,f"{num}. {s}",15,'F2'); cur.append("0 0 0 rg"); y[0]-=24
def lead(s):
    para(s,9.8,'F1',color=MUT,gap=6)
def param(name, tech, desc, ex=None):
    need(30)
    # Name (fett, accent) + tech
    need(15)
    cur.append(f"{ACCENT[0]:.3f} {ACCENT[1]:.3f} {ACCENT[2]:.3f} rg")
    draw(ML,y[0]-11,name,11,'F2'); cur.append("0 0 0 rg")
    nx = ML+text_width(name,11,True)+8
    cur.append(f"{MUT[0]:.3f} {MUT[1]:.3f} {MUT[2]:.3f} rg")
    draw(nx,y[0]-10,tech,8.5,'F3'); cur.append("0 0 0 rg")
    y[0]-=16
    para(desc,10,'F1',indent=2,gap=2)
    if ex:
        # leicht eingerückter grauer Beispielblock
        for ln in wrap(ex,9.3,CW-24,False):
            need(12.5)
            draw(ML+12,y[0]-9.3,ln,9.3,'F1'); y[0]-=12.5
    y[0]-=7

# --- Titel ---
h1("Dashboard-Parameter - einfach erklaert")
para("Nachschlagewerk zu allen Kennzahlen der Analyse. Ohne Fachchinesisch. "
     "Abgeleitet aus dem echten Analyse-Code (Stand-Konfiguration).",10,'F1',color=MUT,gap=8)

# 1 Chart
h2(1,"Chartanalyse (technisch)")
lead("Werte aus dem Kursverlauf - sagen etwas ueber Trend und Timing, nicht ueber die Qualitaet des Unternehmens.")
param("Aktueller Kurs","aktueller_kurs","Der letzte gehandelte Boersenpreis der Aktie.")
param("Trend","trend","Grobe Richtung des Kurses: Aufwaertstrend, Seitwaerts oder Abwaertstrend. Ergibt sich aus dem Verhaeltnis von Kurs zu den gleitenden Durchschnitten (SMA).")
param("Signal / Empfehlung","signal, empfehlung","Technische Kurzampel: Kaufen / Halten / Verkaufen. Fasst RSI, MACD und Trend zu einem Vorschlag zusammen.")
param("RSI (14)","rsi_14","Relative-Staerke-Index (0-100): misst, ob eine Aktie kurzfristig ueberkauft (zu heiss gelaufen) oder ueberverkauft (zu stark abgestraft) ist.",
      "Faustregel: > 70 = ueberkauft (Vorsicht) - 30-70 = neutral - < 30 = ueberverkauft (evtl. Chance).")
param("MACD","macd","Momentum-Indikator aus zwei Durchschnitten. Zeigt, ob die Bewegung an Schwung gewinnt oder verliert. Angezeigt als Positiv, Neutral oder Negativ.")
param("SMA 50 / SMA 200","sma_50, sma_200","Gleitende Durchschnittskurse der letzten 50 bzw. 200 Handelstage. Sie glaetten das Auf und Ab.",
      "Kurs ueber beiden Linien = Aufwaertstrend. SMA50 kreuzt ueber SMA200 (Golden Cross) = bullisch, umgekehrt (Death Cross) = baerisch.")
param("Unterstuetzung / Widerstand","unterstuetzung, widerstand","Unterstuetzung = Kursbereich, an dem die Aktie oft nach unten abprallt (Boden). Widerstand = Bereich, an dem sie oft nach oben abprallt (Decke).")
param("Momentum (12-1)","momentum_12_1","Kursentwicklung der letzten 12 Monate ohne den juengsten Monat (in %). Klassisches Trendstaerke-Mass: was zuletzt lief, laeuft oft weiter.",
      "+184 % = die Aktie hat sich stark aufgeladen. Hoher Wert = starkes Momentum.")
param("Volatilitaet (20 Tage)","volatility_20d","Wie stark der Kurs zuletzt taeglich schwankt (in %). Hoch = nervoeser/riskanter, niedrig = ruhiger.")
param("Legacy-Werte","legacy_rsi_14, legacy_sma_50 ...","Die vorherigen Werte vom letzten Lauf - nur fuer den Vergleich 'wie war es gestern' und den Konsistenz-Check. Keine eigene Bewertung.")

# 2 Funda
h2(2,"Fundamentalanalyse (Unternehmenszahlen)")
lead("Beschreiben die Qualitaet und Bewertung des Unternehmens selbst - unabhaengig vom kurzfristigen Chart.")
param("KGV","kgv","Kurs-Gewinn-Verhaeltnis: wie viele Jahresgewinne man beim Kauf bezahlt. Grob: niedrig = guenstig, hoch = teuer (bzw. hohe Wachstumserwartung).",
      "KGV 18 = man zahlt das 18-fache des Jahresgewinns.")
param("Dividendenrendite","dividendenrendite","Jaehrliche Dividende im Verhaeltnis zum Kurs (in %) - die 'Verzinsung' durch Ausschuettungen.")
param("Umsatzwachstum (YoY)","umsatzwachstum_yoy","Wie stark der Umsatz gegenueber dem Vorjahr gewachsen ist (YoY = year over year, in %).")
param("Gewinnwachstum (YoY)","gewinnwachstum_yoy","Wachstum des Gewinns gegenueber dem Vorjahr (in %). Wichtiger Treiber im Scoring: > 20 % gibt Pluspunkte, Rueckgang Minuspunkte.")
param("Eigenkapitalquote","eigenkapitalquote","Anteil des Eigenkapitals an der Bilanz (in %). Hoch = solide finanziert / wenig Schulden, niedrig = mehr Fremdkapital-Risiko.")
param("Bewertung","bewertung","Gesamturteil zur Attraktivitaet des Preises: Attraktiv, Neutral, Unattraktiv oder Spekulativ.")
param("Risiko","risiko","Einschaetzung des Unternehmensrisikos: Niedrig, Mittel oder Hoch. Niedriges Risiko gibt Pluspunkte im Score.")
param("EV/EBITDA","ev_ebitda","Unternehmenswert im Verhaeltnis zum operativen Gewinn. Alternative zum KGV, schwerer manipulierbar. Niedrig = guenstig; ein negativer Wert ist ein Warnsignal (kein operativer Gewinn).")
param("PEG-Ratio","peg_ratio","KGV geteilt durch das Gewinnwachstum - setzt den Preis ins Verhaeltnis zum Wachstum. Faustregel: < 1 = guenstig fuers Wachstum, > 3 = teuer.")
param("ROE","roe","Eigenkapitalrendite (in %) - wie profitabel das Unternehmen mit dem Kapital der Eigentuemer wirtschaftet. > 20 % = sehr gut, negativ = Verlust.")
param("Piotroski F-Score","piotroski","Bilanz-Qualitaets-Score 0-9 (9 Kriterien: Profitabilitaet, Verschuldung, Effizienz). 7-9 = solide/verbessert, <= 2 = Warnsignal / moegliche Value-Falle.")

# 3 Sentiment
h2(3,"KI-Sentiment (Nachrichtenlage)")
lead("Eine KI liest aktuelle Schlagzeilen und bewertet die Stimmung - als Ergaenzung zu Chart und Zahlen.")
param("Sentiment-Score","sentiment_score","Stimmungsnote von -3 (sehr negativ) bis +3 (sehr positiv), 0 = neutral. Basiert auf der Nachrichtenlage.")
param("Confidence","confidence","Wie gut die Bewertung belegt ist (0-1). Wenige/vage Meldungen = niedrige Confidence. Sie daempft den Score: ein schwach belegtes Urteil zaehlt weniger.",
      "Score +2 x Confidence 0,5 = wirksame +1 im Gesamt-Score.")
param("Veto","veto","Not-Bremse: bei einem gravierenden negativen Ereignis (z. B. Bilanzskandal) kann die KI ein Veto setzen und einen Kauf blockieren - egal wie gut die anderen Zahlen sind.")
param("Event-Kategorie","event_kategorie","Art des ausloesenden Ereignisses (z. B. Quartalszahlen, Uebernahme, Sonstiges). Nur zur Einordnung.")
param("Begruendung","begruendung","Ein bis zwei Saetze der KI, warum diese Stimmungsnote vergeben wurde.")

# 4 Score
h2(4,"Score & Handelslogik")
lead("Der Score ist die zentrale Zahl. Er fasst alle drei Analysen zusammen und entscheidet ueber Kauf/Halten/Verkauf.")
param("Gesamt-Score","score","Summe aus drei Bausteinen (je hoeher, desto attraktiver der Kauf):",
      "Chart-Score (Trend, RSI, MACD, SMA, Momentum) ~ -13..+15  +  Funda-Score (Empfehlung, Bewertung, Risiko, Wachstum, PEG, ROE, EV/EBITDA, Piotroski) ~ -14..+17  +  KI-Sentiment x Confidence  =  Gesamt-Score.")
param("Kauf-Schwelle (adaptiv)","BUY_FLOOR = 6, Top-20 %","Gekauft wird nur, wer ueber der Schwelle liegt. Diese ist dynamisch: mindestens Score 6, in starken Maerkten automatisch hoeher (nur die besten ~20 % der Kandidaten). So bleibt die Latte hoch, wenn viel Gutes zur Auswahl steht.")
param("Verkaufs- & Rebalancing-Schwelle","SELL = 4, REBALANCE = 8","Faellt eine Position unter Score 4, wird verkauft. Fuer Kapitalbeschaffung koennen schwache 'Halten'-Positionen unter Score 8 abgebaut werden.")
param("Watch-Kandidat","watch-kandidat","Neu entdeckte Werte (Opportunity-Scan) ohne ausreichende Kurshistorie. Bleiben im Beobachtungs-Universum, werden aber erst gekauft, wenn genug Daten (u. a. 200 Tage fuer SMA200) vorliegen.")

# 5 Depot
h2(5,"Depot & Positionen")
lead("Kennzahlen zu den tatsaechlich gehaltenen Werten.")
param("Stueck","stueck","Anzahl der gehaltenen Aktien dieser Position.")
param("Kaufkurs / Boersenkurs","kaufkurs, boersenkurs","Kaufkurs = Preis beim Kauf. Boersenkurs = aktueller Preis. Die Differenz ist der Gewinn/Verlust pro Aktie.")
param("Investiert / Boersenwert","investiert, boersenwert","Investiert = eingesetztes Kapital (Stueck x Kaufkurs). Boersenwert = aktueller Wert (Stueck x Boersenkurs).")
param("Gewinn/Verlust","gewinn_verlust","Boersenwert minus investiertes Kapital - der aktuelle Buchgewinn/-verlust dieser Position in Euro.")
param("Portfoliowert / Barbestand / Gesamtvermoegen","portfoliowert, aktueller_barbestand, gesamtvermoegen","Portfoliowert = Wert aller Aktien. Barbestand = freies Cash. Gesamtvermoegen = beides zusammen. Es gibt zwei getrennte Toepfe: das 10.000-Euro-Aktien-Depot und das 5.000-Euro-ETF-Depot.")

# 6 Risk
h2(6,"Risiko: Klumpen, Korrelation, Stop-Loss")
lead("Ueberwachen, dass das Depot nicht zu einseitig oder zu verlustanfaellig wird.")
param("Klumpenrisiko","anteil_pct, limits","Wie viel Prozent des Depots auf eine einzelne Aktie oder einen Sektor entfallen. Warnung bei Position > 20 % oder Sektor > 30 % - dann liegen zu viele Eier in einem Korb.",
      "'Sektor Luft- und Raumfahrt macht 36,2 % aus (Limit 30 %)' = Uebergewicht. Ab 60 % werden neue Kaeufe im Sektor ganz blockiert.")
param("Korrelation / Cluster","korrelation, cluster","Gruppen von Aktien, die sich aehnlich bewegen (z. B. zwei Ruestungswerte). Auch verschiedene Firmen wirken im Crash wie eine - das Cluster zeigt dieses versteckte Konzentrationsrisiko.")
param("Beta","beta","Wie stark eine Aktie im Vergleich zum Gesamtmarkt (DAX) schwankt. Beta 1,0 = wie der Markt, > 1 = staerker, < 1 = ruhiger. Wird automatisch aus ~1 Jahr Kursdaten berechnet.")
param("Stop-Loss (zweistufig, marktbereinigt)","stop_ref_kurs, dax_ref","Automatischer Verkaufsschutz gegen Verluste, in zwei Stufen:",
      "1) Absoluter Hard-Stop -20 %: faellt eine Position mehr als 20 % unter Kaufkurs, wird immer verkauft (Katastrophenschutz).  2) Relativer Stop -12 %: greift, wenn die Position im Minus ist UND ihren erwarteten (beta-bereinigten) Kursverlauf ggue. dem DAX um mehr als 12 % unterbietet. So fliegt man bei einem allgemeinen Marktdip nicht raus, echte Firmen-Schwaeche wird aber frueh erkannt.")

# 7 Benchmark
h2(7,"Benchmark (Vergleich mit dem Markt)")
lead("Zeigt, ob das Depot besser oder schlechter laeuft als der breite Markt. Reine Performance ohne Vergleich sagt wenig aus.")
param("Rendite Depot vs. DAX vs. MSCI World","rendite_pct","Prozentuale Entwicklung seit dem Anker-Datum - fuer das eigene Depot, den DAX (deutscher Leitindex) und den MSCI World (weltweit).",
      "'Depot -2,63 % | DAX -1,14 % | MSCI -0,66 %' = das Depot lief etwas schlechter als der Markt (leichte Underperformance).")
param("Anker","anker","Der fixe Startpunkt (Datum + Indexstaende + Vermoegen), auf den sich alle Vergleichsrenditen beziehen. Haelt den Vergleich fair und stabil.")

need(20); y[0]-=4; hline(y[0]); y[0]-=14
para("Erstellt aus dem tatsaechlichen Analyse-Code des Dashboards. Schwellen (Kauf 6, Verkauf 4, Stop -20 %/-12 % usw.) entsprechen der aktuellen Konfiguration und koennen sich aendern.",8.5,'F1',color=MUT)

newpage()

# ---------- PDF-Objekte serialisieren ----------
objs=[]
def add(o): objs.append(o); return len(objs)
# 1 Catalog,2 Pages,3.. Fonts + pages/contents
font_reg=None
# Wir bauen: Catalog, Pages, 3 Fonts, dann pro Seite Content+Page
n_pages=len(pages)
# Objektnummern planen
# 1: Catalog, 2: Pages, 3: F1, 4: F2, 5: F3
# ab 6: für jede Seite: content-stream und page-objekt (2 pro Seite)
def fontobj(name, base):
    return (f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} "
            f"/Encoding /WinAnsiEncoding >>").encode('latin-1')

parts=[]
def obj_bytes(num, body):
    if isinstance(body,str): body=body.encode('latin-1')
    return (f"{num} 0 obj\n".encode()+body+b"\nendobj\n")

page_obj_nums=[]
content_obj_nums=[]
base=6
for i in range(n_pages):
    content_obj_nums.append(base+i*2)
    page_obj_nums.append(base+i*2+1)

kids=" ".join(f"{n} 0 R" for n in page_obj_nums)
catalog=f"<< /Type /Catalog /Pages 2 0 R >>"
pagestree=f"<< /Type /Pages /Count {n_pages} /Kids [{kids}] >>"

out=bytearray()
out+=b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
offsets={}
def emit(num, body):
    offsets[num]=len(out)
    out.extend(obj_bytes(num, body))

emit(1, catalog)
emit(2, pagestree)
emit(3, fontobj('F1','Helvetica'))
emit(4, fontobj('F2','Helvetica-Bold'))
emit(5, fontobj('F3','Courier'))

for i,pg in enumerate(pages):
    stream="\n".join(pg).encode('latin-1')
    comp=zlib.compress(stream)
    cnum=content_obj_nums[i]; pnum=page_obj_nums[i]
    body=(f"<< /Length {len(comp)} /Filter /FlateDecode >>\nstream\n").encode('latin-1')+comp+b"\nendstream"
    offsets[cnum]=len(out); out.extend(f"{cnum} 0 obj\n".encode()+body+b"\nendobj\n")
    page=(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
          f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
          f"/Contents {cnum} 0 R >>")
    emit(pnum, page)

# xref
xref_pos=len(out)
maxnum=max(offsets)
out+=f"xref\n0 {maxnum+1}\n".encode()
out+=b"0000000000 65535 f \n"
for num in range(1,maxnum+1):
    off=offsets.get(num,0)
    out+=f"{off:010d} 00000 n \n".encode()
out+=f"trailer\n<< /Size {maxnum+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode()

dest=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"docs","parameter-erklaerung.pdf")
with open(dest,'wb') as f: f.write(out)
print("OK", dest, len(out),"bytes,", n_pages,"Seiten")
