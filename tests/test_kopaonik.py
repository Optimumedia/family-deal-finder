"""Kopaonik / Stara Planina price lists (JAT Apartmani's own site, Supernova Travel): parsers on saved pages. No network."""
import unittest
from datetime import date
from pathlib import Path

from trips import run, score
from trips.sources import kopaonik

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 25)
PAGE = {"url": "https://example/price", "season": "winter", "area": "Kopaonik, Serbia", "country": "RS",
        "lat": 43.285, "lng": 20.81, "nights": 7}


def read(name):
    return (FIX / name).read_text(encoding="utf-8")


def sn(name, **page):
    parsed = kopaonik.parse_supernova(read(f"kopaonik_sn_{name}.html"), TODAY)
    return parsed, kopaonik.supernova_offers(parsed, {**PAGE, **page}, CFG, TODAY)


class Jat(unittest.TestCase):
    def setUp(self):
        self.pl = kopaonik.parse_jat_price_list(read("kopaonik_jat_price_list.html"))
        self.units = {"D": kopaonik.parse_jat_unit(read("kopaonik_jat_unit_d.html")),
                      "E": kopaonik.parse_jat_unit(read("kopaonik_jat_unit_e.html"))}

    def test_price_table(self):
        self.assertEqual([u["letter"] for u in self.pl["units"]], ["A/B", "C", "D", "E", "F"])
        self.assertEqual(self.pl["units"][2]["pax"], 4)
        self.assertEqual(len(self.pl["periods"]), 6)
        first = self.pl["periods"][0]
        self.assertEqual((first["from"], first["to"], first["promo"]), ("2026-11-29", "2026-12-27", True))
        self.assertEqual(first["rates"][2], {"night": 110.94, "week": 698.89})
        xmas = self.pl["periods"][1]
        self.assertFalse(xmas["promo"])
        self.assertEqual(xmas["rates"][2]["week"], 1224.10)       # "1,224.10 EUR"
        self.assertEqual(self.pl["half_board_eur"], 28.12)

    def test_unit_layout(self):
        self.assertIs(self.units["D"]["separate_bedroom"], False)  # "one room"
        self.assertIsNone(self.units["E"]["separate_bedroom"])     # E1 one room, E2 two rooms
        self.assertTrue(self.units["E"]["two_room_variant"])
        self.assertEqual(self.units["D"]["name"], "Studio D")
        self.assertTrue(self.units["D"]["image"].startswith("https://jatapartmani.com/"))

    def test_offers(self):
        hotels, offers = kopaonik.jat_offers(self.pl, self.units, PAGE, CFG, TODAY)
        self.assertEqual(sorted(h["id"] for h in hotels), ["kop-jat-d", "kop-jat-e", "kop-jat-f"])  # 4+ guests only
        h = next(h for h in hotels if h["id"] == "kop-jat-d")
        self.assertEqual((h["kind"], h["country"], h["border"]), ("apartment", "RS", True))
        d = [o for o in offers if o["hotel"] == "kop-jat-d"]
        self.assertEqual(len(d), 6)
        promo = d[0]
        self.assertEqual((promo["check_in"], promo["nights"], promo["board"], promo["occupancy"]),
                         ("2026-11-29", 7, "SC", "2+2"))
        self.assertEqual(promo["price_eur"], 698.89)
        self.assertEqual(promo["was_eur"], round(110.94 * 7, 2))
        self.assertIn("−10%", promo["discount_label"])
        self.assertIsNone(d[1]["was_eur"])                         # holiday weeks: no promo
        self.assertEqual(d[1]["price_eur"], round(174.87 * 7, 2))

    def test_no_promo_when_not_seven_nights(self):
        _, offers = kopaonik.jat_offers(self.pl, self.units, {**PAGE, "nights": 5}, CFG, TODAY)
        o = next(o for o in offers if o["hotel"] == "kop-jat-d")
        self.assertEqual((o["price_eur"], o["was_eur"]), (round(110.94 * 5, 2), None))

    def test_late_check_in_moves_to_today(self):
        _, offers = kopaonik.jat_offers(self.pl, self.units, PAGE, CFG, date(2026, 12, 10))
        self.assertEqual(next(o for o in offers if o["hotel"] == "kop-jat-d")["check_in"], "2026-12-10")

    def test_scores(self):
        hotels, offers = kopaonik.jat_offers(self.pl, self.units, PAGE, CFG, TODAY)
        h = next(h for h in hotels if h["id"] == "kop-jat-d")
        fit = score.family_fit(h, offers[0], CFG, 240)
        self.assertEqual(next(c for c in fit["checklist"] if c["key"] == "separate_bedroom")["state"], "no")


class Supernova(unittest.TestCase):
    def test_konaci_stay_prices(self):
        parsed, (hotels, offers) = sn("konaci")
        self.assertEqual(parsed["board"], "SC")
        apt = next(u for u in parsed["units"] if u["label"] == "2+1 APT")
        self.assertEqual(apt["pax"], 4)
        first = apt["prices"][0]
        self.assertEqual((first["from"], first["to"], first["nights"], first["basis"], first["rsd"]),
                         ("2026-11-29", "2026-12-13", 3, "stay", 20160))
        self.assertEqual(len(apt["prices"]), 14)                  # merged "13/20.DEC 14.MAR-11.APR" column skipped
        ids = {h["id"]: h for h in hotels}
        self.assertIs(ids["kop-sn-apartmani-konaci-2-1-std"]["family"]["separate_bedroom"], False)
        self.assertIsNone(ids["kop-sn-apartmani-konaci-2-1-apt"]["family"]["separate_bedroom"])
        self.assertNotIn("kop-sn-apartmani-konaci-1-1-std", ids)  # 3 guests max: too small
        o = next(o for o in offers if o["hotel"] == "kop-sn-apartmani-konaci-2-1-apt" and o["check_in"] == "2027-01-10")
        self.assertEqual((o["nights"], o["occupancy"]), (7, "2+2"))
        self.assertEqual(o["price_eur"], round(134400 / 117.2, 2))

    def test_cardaci_per_night(self):
        parsed, (_, offers) = sn("cardaci")
        u = next(u for u in parsed["units"] if u["label"] == "1/4 APARTMAN COMFORT")
        self.assertEqual(u["prices"][0]["basis"], "night")
        o = next(o for o in offers if "1-4-apartman-comfort" in o["hotel"] and o["check_in"] == "2026-12-06")
        self.assertEqual((o["nights"], o["price_eur"]), (7, round(7900 * 7 / 117.2, 2)))

    def test_marija_one_night_column_is_per_night(self):
        parsed, (_, offers) = sn("marija")
        u = next(u for u in parsed["units"] if u["label"] == "2+1 APARTMAN")
        self.assertEqual(u["prices"][0]["basis"], "night")        # "BROJ NOĆI: 1"
        self.assertEqual(u["prices"][1]["basis"], "stay")
        self.assertEqual(u["prices"][-1]["to"], "2027-03-28")     # "14.MART 28.MART"
        o = [o for o in offers if "2-1-apartman" in o["hotel"]]
        self.assertEqual((o[0]["nights"], o[0]["price_eur"]), (7, round(9600 * 7 / 117.2, 2)))
        self.assertEqual(o[0]["board"], "SC")                     # "Najam" in the notes under the table

    def test_zvoncica_daily_and_weekly_columns(self):
        parsed, (_, offers) = sn("zvoncica")
        u = next(u for u in parsed["units"] if u["label"] == "APARTMAN 2")
        self.assertEqual(u["pax"], 6)                             # "do 6"
        self.assertEqual([p["basis"] for p in u["prices"][:2]], ["night", "stay"])
        o = [o for o in offers if o["hotel"].endswith("apartman-2")]
        self.assertEqual(o[0]["price_eur"], round(13000 * 7 / 117.2, 2))
        self.assertEqual(o[1]["price_eur"], round(126000 / 117.2, 2))

    def test_stara_planina_skips_per_person_rooms(self):
        parsed, (hotels, offers) = sn("stara_planina", area="Stara Planina, Serbia", kind="hotel")
        self.assertEqual((parsed["stars"], parsed["board"]), (4, "HB"))
        labels = [u["label"] for u in parsed["units"]]
        self.assertNotIn("DVOKREVETNA SOBA", labels)              # priced per person: skipped
        self.assertIn("JUNIOR APARTMAN", labels)
        junior = next(u for u in parsed["units"] if u["label"] == "JUNIOR APARTMAN")
        self.assertEqual(junior["pax"], 4)                        # "3 adl ili 2adl i 2 chd"
        self.assertNotIn("kop-sn-hotel-stara-planina-deluxe-apartman", {h["id"] for h in hotels})
        o = offers[0]
        self.assertEqual((o["board"], o["nights"], o["check_in"]), ("HB", 7, "2026-12-10"))
        self.assertEqual(o["price_eur"], round(39650 * 7 / 117.2, 2))

    def test_srbijasume_studio_and_summer_column(self):
        parsed, (hotels, offers) = sn("srbijasume")
        self.assertEqual(parsed["stars"], 3)
        self.assertEqual([h["family"]["separate_bedroom"] for h in hotels], [False])
        self.assertTrue(all(o["check_in"] < "2027-05-01" for o in offers))

    def test_past_periods_dropped(self):
        _, (_, offers) = sn("konaci")
        parsed = kopaonik.parse_supernova(read("kopaonik_sn_konaci.html"), TODAY)
        _, later = kopaonik.supernova_offers(parsed, PAGE, CFG, date(2027, 1, 20))
        self.assertTrue(len(later) < len(offers))
        self.assertTrue(all(o["check_in"] >= "2027-01-20" for o in later))


class Fetch(unittest.TestCase):
    def test_disabled(self):
        self.assertEqual(kopaonik.fetch({"sources": {}}, TODAY), ([], []))

    def test_fake_session(self):
        pages = {"https://jatapartmani.com/en/price-list": read("kopaonik_jat_price_list.html"),
                 "https://jatapartmani.com/en/accommodation/apartman-d": read("kopaonik_jat_unit_d.html"),
                 "https://jatapartmani.com/en/accommodation/apartman-e": read("kopaonik_jat_unit_e.html"),
                 "https://jatapartmani.com/en/accommodation/apartman-f": "",
                 "https://sn/konaci": read("kopaonik_sn_konaci.html")}

        class S:
            def get(self, url):
                return pages[url]

        cfg = {**CFG, "sources": {**CFG["sources"], "kopaonik": {"enabled": True, "pages": [
            {**PAGE, "parser": "jat", "url": "https://jatapartmani.com/en/price-list"},
            {**PAGE, "parser": "supernova", "url": "https://sn/konaci", "name": "Apartmani Konaci"}]}}}
        hotels, offers = kopaonik.fetch(cfg, TODAY, session=S())
        self.assertEqual(len(hotels), 7)
        self.assertEqual(len(offers), 18 + 56)
        self.assertEqual(len({h["id"] for h in hotels}), len(hotels))


if __name__ == "__main__":
    unittest.main()
