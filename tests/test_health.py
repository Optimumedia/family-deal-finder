import json
import logging
import tempfile
import unittest
from pathlib import Path

from trips import health as hl
from trips.http import Blocked


class FakeSession:
    def __init__(self):
        self.stats = {"pages": 0, "not_modified": 0, "blocked": 0, "errors": 0}


def history(name, counts):
    return [{"at": f"2026-11-{i + 1:02d}T13:00:00", "sources": {name: c}} for i, c in enumerate(counts)]


class HealthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.h = hl.RunHealth(history_path=self.tmp / "hist.json")

    def test_track_counts_pages_and_offers(self):
        s = FakeSession()
        with self.h.track("Olympic", s) as st:
            s.stats["pages"] += 4
            s.stats["not_modified"] += 1
            st.offers_parsed = 32
        st = self.h.sources["Olympic"]
        self.assertEqual((st.pages_fetched, st.not_modified, st.offers_parsed), (4, 1, 32))
        self.assertGreaterEqual(st.duration_s, 0)
        self.assertEqual(self.h.report([])["status"], "ok")

    def test_crash_is_caught_and_reported(self):
        with self.assertLogs("trips.health", "ERROR"):
            with self.h.track("Travelland", FakeSession()):
                raise ValueError("layout changed")
        rep = self.h.report([])
        self.assertEqual(rep["status"], "fail")
        self.assertEqual(rep["failed_sources"], ["Travelland"])
        self.assertIn("Travelland failed today", rep["problems"][0])
        self.assertIn("layout changed", rep["problems"][0])

    def test_blocked_source(self):
        s = FakeSession()
        with self.h.track("Olympic", s):
            s.stats["blocked"] += 1
            logging.getLogger("trips.sources.olympic").warning("Olympic stopped (respecting the block): 403")
        rep = self.h.report([])
        src = rep["sources"][0]
        self.assertEqual(src["status"], "blocked")
        self.assertIn("403", src["messages"][0])
        self.assertIn("refused us", rep["problems"][0])

    def test_sudden_zero_vs_7_run_average(self):
        with self.h.track("Olympic", FakeSession()) as st:
            st.offers_parsed = 0
        rep = self.h.report(history("Olympic", [1, 1, 30, 32, 31, 33, 30, 29, 32]))
        src = rep["sources"][0]
        self.assertEqual(src["status"], "zero")
        self.assertAlmostEqual(src["avg_offers_7"], (30 + 32 + 31 + 33 + 30 + 29 + 32) / 7, places=1)
        self.assertIn("usually ~31", rep["problems"][0])

    def test_zero_is_fine_for_small_or_new_source(self):
        with self.h.track("Micazu", FakeSession()) as st:
            st.offers_parsed = 0
        self.assertEqual(self.h.report(history("Micazu", [1, 0, 2]))["status"], "ok")
        self.assertEqual(hl.rolling_average([], "Micazu"), None)

    def test_rejects_make_partial(self):
        s = FakeSession()
        with self.h.track("Travelland", s) as st:
            s.stats["pages"] += 2
            st.offers_parsed = 10
        self.h.add_rejects({"Travelland": {"rejected": 6, "reasons": {"board": 6}}})
        rep = self.h.report([])
        self.assertEqual(rep["status"], "warn")
        self.assertIn("6 of 10 offers rejected", rep["problems"][0])

    def test_disabled_source_is_idle(self):
        with self.h.track("Falcon", FakeSession()):
            pass
        rep = self.h.report([])
        self.assertEqual((rep["status"], rep["sources"][0]["status"]), ("ok", "idle"))

    def test_write_files_and_history_rolls(self):
        out = self.tmp / "docs" / "health.json"
        for n in (30, 31):
            h = hl.RunHealth(history_path=self.tmp / "hist.json")
            with h.track("Olympic", FakeSession()) as st:
                st.offers_parsed = n
            h.write(out)
        h = hl.RunHealth(history_path=self.tmp / "hist.json")
        with h.track("Olympic", FakeSession()) as st:
            st.offers_parsed = 0
        with self.assertLogs("trips.health", "WARNING"):
            rep = h.write(out)
        self.assertEqual(rep["sources"][0]["status"], "zero")
        saved = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(saved["failed_sources"], ["Olympic"])
        runs = json.loads((self.tmp / "hist.json").read_text(encoding="utf-8"))["runs"]
        self.assertEqual([r["sources"]["Olympic"] for r in runs], [30, 31, 0])

    def test_blocked_exception_from_http_counts(self):
        # A source that lets http.Blocked escape is reported as blocked, and the run carries on.
        with self.assertLogs("trips.health", "WARNING"):
            with self.h.track("Olympic", FakeSession()):
                raise Blocked("403 bot challenge")
        self.assertEqual(self.h.report([])["sources"][0]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
