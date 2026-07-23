"""Regressionstests für die ETF-Sleeve-Engine (update_etf_depot.py).

Kein Netz, keine echten Datenfiles: get_live_price wird gepatcht, der Zustand
über EtfRunState-Fixtures aufgebaut. Abgedeckt sind die Regeln, die reale
Fehlkäufe/Fragmentierung verursacht haben (Clean-Energy-Fehlkauf, Mini-Lots).

Ausführen: python3 -m unittest discover -s tests -q
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import update_etf_depot as etf


def make_row(isin, composite, bucket, name="Test ETF"):
    return {"isin": isin, "wertpapier": name, "ticker": "TST.DE",
            "composite": composite, "bucket": bucket,
            "momentum": {"score": 50}, "risiko": {"score": 50},
            "sentiment": {"score": 50}, "struktur": {"score": 50}}


def make_position(isin, sektor="Tech", stueck=10, kaufkurs=20.0, kurs=20.0,
                  composite=70.0, bucket="SATELLITE", name="Test ETF", **over):
    p = {
        "sektor": sektor, "wertpapier": name, "isin": isin, "ticker": "TST.DE",
        "stueck": stueck, "kaufkurs": kaufkurs, "boersenkurs": kurs,
        "peak_kurs": max(kaufkurs, kurs),
        "investiert": round(stueck * kaufkurs, 2),
        "boersenwert": round(stueck * kurs, 2),
        "gewinn_verlust": round(stueck * (kurs - kaufkurs), 2),
        "composite": composite, "bucket": bucket,
    }
    p.update(over)
    return p


class EtfTestCase(unittest.TestCase):
    def setUp(self):
        self.prices = {}
        self._orig = etf.get_live_price
        etf.get_live_price = lambda isin, fallback=None: self.prices.get(isin, fallback)

    def tearDown(self):
        etf.get_live_price = self._orig

    def make_state(self, positions, cash=500.0, ranking_rows=None):
        lookup = {}
        for sektor, row in (ranking_rows or []):
            lookup[(sektor, row["isin"])] = row
        return etf.EtfRunState(
            current_cash=cash, positions=positions, transactions=[],
            initial_tx_count=0, ranking_lookup=lookup,
        )


class TestKonsolidierung(EtfTestCase):
    def test_duplikat_slots_werden_zusammengefuehrt(self):
        summary = []
        positions = [
            make_position("IE00TEST0001", sektor="Tech", stueck=5, kaufkurs=10.0),
            make_position("IE00TEST0001", sektor="Defense", stueck=5, kaufkurs=20.0),
        ]
        merged = etf.consolidate_by_isin(positions, summary)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["stueck"], 10)
        self.assertEqual(merged[0]["investiert"], 150.0)
        self.assertEqual(merged[0]["kaufkurs"], 15.0)
        self.assertEqual(merged[0]["sektor"], "Defense")  # größerer Slot gewinnt
        self.assertTrue(summary)

    def test_ohne_duplikate_unveraendert(self):
        summary = []
        positions = [make_position("IE00TEST0001"), make_position("IE00TEST0002")]
        merged = etf.consolidate_by_isin(positions, summary)
        self.assertEqual(len(merged), 2)
        self.assertEqual(summary, [])


class TestVerkaufsregeln(EtfTestCase):
    def test_meiden_bucket_verkauft(self):
        p = make_position("IE00TEST0010", composite=40.0, bucket="BEOBACHTEN")
        state = self.make_state([p], ranking_rows=[
            ("Tech", make_row("IE00TEST0010", 40.0, "MEIDEN"))])
        self.prices["IE00TEST0010"] = 20.0
        etf.phase_strategic_sell(state)
        self.assertEqual(state.positions, [])
        self.assertIn("MEIDEN", state.transactions[0]["begruendung"])

    def test_hard_stop(self):
        p = make_position("IE00TEST0011", kaufkurs=20.0)
        state = self.make_state([p], ranking_rows=[
            ("Tech", make_row("IE00TEST0011", 72.0, "SATELLITE"))])
        self.prices["IE00TEST0011"] = 15.0    # -25%
        etf.phase_strategic_sell(state)
        self.assertEqual(state.positions, [])
        self.assertIn("Hard-Stop", state.transactions[0]["notiz"])

    def test_soft_stop_beobachten_im_minus(self):
        p = make_position("IE00TEST0012", kaufkurs=20.0)
        state = self.make_state([p], ranking_rows=[
            ("Tech", make_row("IE00TEST0012", 50.0, "BEOBACHTEN"))])
        self.prices["IE00TEST0012"] = 19.2    # -4% <= -3%
        etf.phase_strategic_sell(state)
        self.assertEqual(state.positions, [])
        self.assertIn("Soft-Stop", state.transactions[0]["notiz"])

    def test_trailing_stop_nicht_fuer_core(self):
        # Composite >= 75 (CORE) ist vom Trailing-Stop ausgenommen
        p = make_position("IE00TEST0013", kaufkurs=20.0, kurs=20.0, peak_kurs=24.0)
        state = self.make_state([p], ranking_rows=[
            ("Tech", make_row("IE00TEST0013", 80.0, "CORE"))])
        self.prices["IE00TEST0013"] = 20.0    # -16.7% vom Peak 24
        etf.phase_strategic_sell(state)
        self.assertEqual(len(state.positions), 1)

    def test_trailing_stop_fuer_satellite(self):
        p = make_position("IE00TEST0014", kaufkurs=20.0, kurs=20.0, peak_kurs=24.0)
        state = self.make_state([p], ranking_rows=[
            ("Tech", make_row("IE00TEST0014", 65.0, "SATELLITE"))])
        self.prices["IE00TEST0014"] = 20.0    # -16.7% vom Peak
        etf.phase_strategic_sell(state)
        self.assertEqual(state.positions, [])
        self.assertIn("Trailing-Stop", state.transactions[0]["notiz"])


class TestKaufregeln(EtfTestCase):
    def test_konviktions_floor_blockiert_schwache_neuzugaenge(self):
        state = self.make_state([], cash=1000.0, ranking_rows=[
            ("Tech", make_row("IE00TEST0020", 65.0, "SATELLITE")),   # < 70 -> nein
            ("Tech", make_row("IE00TEST0021", 72.0, "SATELLITE")),   # >= 70 -> ja
        ])
        self.prices.update({"IE00TEST0020": 20.0, "IE00TEST0021": 20.0})
        etf.phase_plan(state)
        target_isins = [i for _, i, _ in state.target]
        self.assertNotIn("IE00TEST0020", target_isins)
        self.assertIn("IE00TEST0021", target_isins)

    def test_gehaltene_isin_wird_nicht_neu_gekauft(self):
        p = make_position("IE00TEST0022")
        state = self.make_state([p], ranking_rows=[
            ("Defense", make_row("IE00TEST0022", 90.0, "CORE"))])
        self.prices["IE00TEST0022"] = 20.0
        etf.phase_plan(state)
        self.assertEqual(state.target, [])

    def test_budget_for(self):
        self.assertEqual(etf.budget_for(60.0), etf.BASE_BUDGET)
        self.assertEqual(etf.budget_for(200.0), etf.MAX_BUDGET)

    def test_sektor_cap_blockiert_kauf(self):
        # Tech hätte nach Kauf > 30% -> übersprungen
        positions = [make_position("IE00TEST0023", sektor="Tech", stueck=10, kurs=20.0),
                     make_position("IE00TEST0024", sektor="Energie", stueck=25, kurs=20.0)]
        row = make_row("IE00TEST0025", 90.0, "CORE")
        state = self.make_state(positions, cash=400.0,
                                ranking_rows=[("Tech", row)])
        state.target = [("Tech", "IE00TEST0025", row)]
        state.live_prices[("Tech", "IE00TEST0025")] = 20.0
        etf.phase_buy(state)
        self.assertEqual(len(state.positions), 2)
        self.assertTrue(any("Sektor-Cap" in s for s in state.summary))


class TestTopUp(EtfTestCase):
    def test_topup_nur_starke_core(self):
        pos_stark = make_position("IE00TEST0030", sektor="Tech", composite=80.0, bucket="CORE")
        pos_schwach = make_position("IE00TEST0031", sektor="Energie", composite=70.0)
        # Füllpositionen, damit der Sektor-Cap (30%) das Top-up nicht blockiert.
        filler1 = make_position("IE00TEST0038", sektor="Utility", stueck=25, composite=60.0)
        filler2 = make_position("IE00TEST0039", sektor="Rohstoffe", stueck=25, composite=60.0)
        state = self.make_state([pos_stark, pos_schwach, filler1, filler2],
                                cash=250.0, ranking_rows=[
            ("Tech", make_row("IE00TEST0030", 80.0, "CORE")),
            ("Energie", make_row("IE00TEST0031", 70.0, "SATELLITE")),
        ])
        self.prices.update({"IE00TEST0030": 20.0, "IE00TEST0031": 20.0})
        etf.phase_topup(state)
        buys = [t for t in state.transactions if t["typ"] == "Kauf"]
        self.assertEqual(len(buys), 1)
        self.assertEqual(buys[0]["isin"], "IE00TEST0030")

    def test_kein_topup_bei_zu_wenig_cash(self):
        pos = make_position("IE00TEST0032", composite=80.0, bucket="CORE")
        state = self.make_state([pos], cash=etf.MIN_CASH_RESERVE + 10.0)
        etf.phase_topup(state)
        self.assertEqual(state.transactions, [])


class TestSektorAbbau(EtfTestCase):
    def test_teilverkauf_bis_cap(self):
        positions = [
            make_position("IE00TEST0040", sektor="Tech", stueck=40, kurs=20.0,
                          composite=62.0),                      # 800€ Tech
            make_position("IE00TEST0041", sektor="Tech", stueck=10, kurs=20.0,
                          composite=75.0),                      # 200€ Tech
            make_position("IE00TEST0042", sektor="Energie", stueck=30, kurs=20.0),  # 600€
        ]
        state = self.make_state(positions)   # Tech = 62.5% > 30%
        etf.phase_sector_reduction(state)
        total = sum(p.get("boersenwert", 0) for p in state.positions)
        tech = sum(p.get("boersenwert", 0) for p in state.positions
                   if p.get("sektor") == "Tech")
        self.assertLessEqual(tech / total, etf.SECTOR_CAP + 1e-9)
        # Schwächster Composite (62) wird per TEILverkauf angefasst, nicht der 75er.
        self.assertEqual(state.transactions[0]["isin"], "IE00TEST0040")
        self.assertLess(state.transactions[0]["stueck"], 40)


class TestVerkaufsRecord(EtfTestCase):
    def test_teilverkauf_steuer_anteilig(self):
        p = make_position("IE00TEST0050", stueck=10, kaufkurs=10.0)
        tx, net = etf._make_sell_record(p, 15.0, "t", "t", units=4)
        # 4 Stück: Erlös 60, Einstand-Anteil 40 -> Gewinn 20 -> Steuer 5.28
        self.assertEqual(tx["stueck"], 4)
        self.assertAlmostEqual(tx["gewinn_verlust"], 20.0)
        self.assertAlmostEqual(tx["steuern"], round(20.0 * etf.CAP_GAINS_TAX, 2))


if __name__ == "__main__":
    unittest.main()
