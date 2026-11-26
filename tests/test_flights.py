import unittest

from trips import flights

CAA = "https://www.caa.gov.mk/wp-content/uploads/2026/05/Time-Table-Summer-2026.pdf"


def cfg(**over):
    fl = {
        "enabled": True,
        "max_transfer_km": 90,
        "seasons": ["summer"],
        "trip_months": [6, 7, 8, 9],
        "routes": [
            {"airport": "AYT", "name": "Antalya", "lat": 36.900, "lng": 30.793, "months": [4, 5, 6, 7, 8, 9, 10],
             "frequency": "daily", "max_transfer_km": 130, "confidence": "confirmed", "evidence": CAA},
            {"airport": "BJV", "name": "Bodrum", "lat": 37.250, "lng": 27.664, "months": [7, 8, 9, 10],
             "frequency": "weekly (Wed)", "confidence": "likely", "evidence": CAA},
            {"airport": "ADB", "name": "Izmir", "lat": 38.292, "lng": 27.157, "months": [4, 5, 6, 7, 8, 9, 10],
             "frequency": "daily", "confidence": "confirmed", "evidence": CAA},
            {"airport": "AHO", "name": "Alghero", "lat": 40.632, "lng": 8.291, "months": [7, 8, 9],
             "frequency": "2/week", "confidence": "likely", "evidence": CAA},
            {"airport": "XXX", "name": "Rumour", "lat": 35.0, "lng": 25.0, "months": [6, 7, 8],
             "confidence": "possible"},
        ],
    }
    fl.update(over)
    return {"flights": fl}


def hotel(hid, lat, lng, season="summer", **kw):
    return {"id": hid, "name": hid, "season": season, "lat": lat, "lng": lng, "direct_flight_skp": False, **kw}


class TestFlights(unittest.TestCase):
    def test_alanya_uses_per_airport_limit(self):
        hs = {"a": hotel("a", 36.54, 32.00)}             # Alanya, ~115 km from AYT
        self.assertEqual(flights.apply(hs, cfg()), 1)
        self.assertTrue(hs["a"]["direct_flight_skp"])
        f = hs["a"]["flight"]
        self.assertEqual(f["airport"], "AYT")
        self.assertTrue(100 <= f["transfer_km"] <= 130)
        self.assertEqual(f["months"], [6, 7, 8, 9])

    def test_too_far_stays_unmarked(self):
        hs = {"g": hotel("g", 40.02, 23.43)}             # Halkidiki: no route near
        self.assertEqual(flights.apply(hs, cfg()), 0)
        self.assertFalse(hs["g"]["direct_flight_skp"])
        self.assertNotIn("flight", hs["g"])

    def test_default_limit_applies_without_override(self):
        c = cfg()
        c["flights"]["routes"][0].pop("max_transfer_km")  # AYT falls back to 90 km
        hs = {"a": hotel("a", 36.54, 32.00)}
        self.assertEqual(flights.apply(hs, c), 0)

    def test_month_must_be_flown(self):
        hs = {"b": hotel("b", 37.03, 27.43)}             # Bodrum town, Bodrum flies Jul–Oct only
        offers = [{"hotel_id": "b", "check_in": "2027-06-10"}]
        self.assertEqual(flights.apply(hs, cfg(), offers), 0)
        offers.append({"hotel_id": "b", "check_in": "2027-07-14"})
        self.assertEqual(flights.apply(hs, cfg(), offers), 1)
        self.assertEqual(hs["b"]["flight"]["months"], [7])

    def test_nearest_airport_wins(self):
        hs = {"k": hotel("k", 37.86, 27.26)}             # Kusadasi: Izmir ~50 km, Bodrum ~70 km
        flights.apply(hs, cfg(), [{"hotel": "k", "check_in": "2027-07-01"}])
        self.assertEqual(hs["k"]["flight"]["airport"], "ADB")

    def test_offer_without_dates_uses_trip_months(self):
        hs = {"s": hotel("s", 40.56, 8.32)}              # Alghero beach
        flights.apply(hs, cfg(), [{"hotel_id": "other", "check_in": "2027-07-01"}])
        self.assertEqual(hs["s"]["flight"]["months"], [7, 8, 9])

    def test_possible_routes_ignored_by_default(self):
        hs = {"r": hotel("r", 35.05, 25.05)}
        self.assertEqual(flights.apply(hs, cfg()), 0)
        self.assertEqual(flights.apply(hs, cfg(min_confidence="possible")), 1)

    def test_winter_and_disabled(self):
        hs = {"w": hotel("w", 36.54, 32.00, season="winter")}
        self.assertEqual(flights.apply(hs, cfg()), 0)
        hs = {"a": hotel("a", 36.54, 32.00)}
        self.assertEqual(flights.apply(hs, cfg(enabled=False)), 0)
        self.assertEqual(flights.apply(hs, {}), 0)

    def test_never_unmarks_and_accepts_list(self):
        hs = [hotel("p", 40.02, 23.43, direct_flight_skp=True), hotel("q", None, None)]
        flights.apply(hs, cfg())
        self.assertTrue(hs[0]["direct_flight_skp"])
        self.assertFalse(hs[1]["direct_flight_skp"])

    def test_config_block_parses(self):
        import tomllib
        from pathlib import Path
        text = Path(__file__).resolve().parent.parent.joinpath("proposals", "flight_hotels.md").read_text(encoding="utf-8")
        block = text.split("```toml\n[flights]", 1)[1].split("```", 1)[0]
        c = tomllib.loads("[flights]" + block)
        rts = flights.routes(c)
        self.assertEqual({r["airport"] for r in rts},
                         {"AYT", "ADB", "BJV", "NAP", "BRI", "BCN", "LCA", "MLA", "PMO", "AHO"})
        for r in rts:
            self.assertTrue(r["evidence"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
