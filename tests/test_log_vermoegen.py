"""Regressionstests für den Vermögens-Logger (log_vermoegen.py, V1).

Reine Funktionstests ohne Datei-IO: build_entry/anchor_entry/upsert werden
mit Fixture-Dicts geprüft. Kritisch ist die Idempotenz (zweiter Lauf am
selben Tag überschreibt statt doppelt) — sonst verzerrt jeder Doppel-Lauf
die Equity-Kurve.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import log_vermoegen as lv


def make_depot_data():
    return {
        "depot": {
            "gesamtvermoegen": 9571.85,
            "aktueller_barbestand": 25.88,
            "benchmark": {
                "anker": {"datum": "2026-07-09", "dax": 25118.27, "msci": 125.71, "vermoegen": 9769.26},
                "aktuell": {"dax": 24906.18, "msci": 124.99, "vermoegen": 9571.85},
            },
        },
        "etf_depot": {"gesamtvermoegen": 5100.5, "aktueller_barbestand": 12.3},
    }


class TestBuildEntry(unittest.TestCase):
    def test_entry_hat_alle_felder(self):
        e = lv.build_entry(make_depot_data(), "2026-07-23")
        self.assertEqual(e["datum"], "2026-07-23")
        self.assertEqual(e["depot_gesamt"], 9571.85)
        self.assertEqual(e["etf_gesamt"], 5100.5)
        self.assertEqual(e["cash_depot"], 25.88)
        self.assertEqual(e["cash_etf"], 12.3)
        self.assertEqual(e["dax"], 24906.18)
        self.assertEqual(e["msci"], 124.99)

    def test_fehlendes_etf_depot_faellt_auf_null(self):
        data = make_depot_data()
        del data["etf_depot"]
        e = lv.build_entry(data, "2026-07-23")
        self.assertEqual(e["etf_gesamt"], 0)

    def test_fehlende_benchmark_liefert_none(self):
        data = make_depot_data()
        del data["depot"]["benchmark"]
        e = lv.build_entry(data, "2026-07-23")
        self.assertIsNone(e["dax"])
        self.assertIsNone(e["msci"])


class TestAnchorEntry(unittest.TestCase):
    def test_anker_wird_uebernommen(self):
        a = lv.anchor_entry(make_depot_data())
        self.assertEqual(a["datum"], "2026-07-09")
        self.assertEqual(a["depot_gesamt"], 9769.26)
        self.assertEqual(a["dax"], 25118.27)
        # ETF-Stand am Anker-Tag ist nicht überliefert.
        self.assertIsNone(a["etf_gesamt"])

    def test_ohne_anker_kein_eintrag(self):
        data = make_depot_data()
        data["depot"]["benchmark"] = {}
        self.assertIsNone(lv.anchor_entry(data))


class TestUpsert(unittest.TestCase):
    def test_gleicher_tag_wird_ueberschrieben(self):
        h = [{"datum": "2026-07-23", "depot_gesamt": 1.0}]
        out = lv.upsert(h, {"datum": "2026-07-23", "depot_gesamt": 2.0})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["depot_gesamt"], 2.0)

    def test_neue_tage_chronologisch(self):
        h = [{"datum": "2026-07-23"}]
        out = lv.upsert(h, {"datum": "2026-07-09"})
        self.assertEqual([r["datum"] for r in out], ["2026-07-09", "2026-07-23"])


if __name__ == "__main__":
    unittest.main()
