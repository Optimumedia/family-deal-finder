"""trips.add_offer: paste parsing, fuzzy hotel lookup, hotel stubs, --again, --list, interactive mode.
Everything works on temporary copies; the real data files are only read."""
import json
import shutil
import tempfile
import tomllib
import unittest
from datetime import date
from pathlib import Path

from trips import add_offer as ao
from trips import db, run, validate
from trips.sources import manual

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 26)
PASTE = "Xenios Anastasia Resort & Spa ... HB ... 1.721 € ВКУПНО ОД 1.205 €"

HOTELS = '''# header
# ---------------------------------------------------------------- SUMMER ----

[[hotel]]
id = "xenios-anastasia"
name = "Xenios Anastasia Resort & Spa"
stars = 5
season = "summer"
area = "Nea Skioni, Kassandra, Halkidiki"
country = "GR"
lat = 39.950
lng = 23.535
direct_flight_skp = false
border = true
[hotel.family]
sand_beach = true
verified = []

[[hotel]]
id = "xenios-possidi-paradise"
name = "Xenios Possidi Paradise"
stars = 4
season = "summer"
area = "Possidi, Kassandra, Halkidiki"
country = "GR"
lat = 39.966
lng = 23.375
direct_flight_skp = false
border = true
[hotel.family]
verified = []

# ---------------------------------------------------------------- WINTER ----

[[hotel]]
id = "royal-park-bansko"
name = "Royal Park Hotel & Apartments"
stars = 4
season = "winter"
area = "Bansko, Bulgaria"
country = "BG"
lat = 41.828
lng = 23.476
direct_flight_skp = false
border = true
[hotel.family]
verified = []
'''

OFFERS = '''# header comment stays
[[offer]]
hotel = "xenios-anastasia"
source = "Fibula (manual)"
url = "https://www.fibula.com.mk/promo/black-friday/grcija"
seen = "2026-11-25"
check_in = "2027-06-20"
nights = 7
board = "HB"
room = "Standard Room Limited View"
occupancy = "2+2"
price_eur = 1205
was_eur = 1721
discount_label = "Early Booking -30% + Black Friday -5%"
valid_until = "2026-11-28"

[[offer]]
hotel = "royal-park-bansko"
source = "Fibula (manual)"
url = "https://www.fibula.com.mk/promo/black-friday/bugarija-zima"
seen = "2026-11-10"
check_in = "2027-01-29"
nights = 5
board = "BB"
room = "Standard Room (DBL)"
occupancy = "2+0"
price_eur = 425
discount_label = "Ski -20%"
valid_until = "2026-11-20"

[[offer]]
hotel = "royal-park-bansko"
source = "Fibula (manual)"
url = "https://www.fibula.com.mk/x"
seen = "2026-10-01"
check_in = "2026-11-20"
nights = 5
board = "BB"
occupancy = "2+0"
price_eur = 400
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "hotels.toml").write_text(HOTELS, encoding="utf-8")
        (d / "offers.toml").write_text(OFFERS, encoding="utf-8")
        (d / "config.toml").write_text("", encoding="utf-8")
        (d / "data.json").write_text(json.dumps({"items": [
            {"hotel_id": "olympic-hotel-lion-borovets", "name": "Hotel Lion Borovets", "stars": 4,
             "area": "Borovets, Bulgaria", "season": "winter", "lat": 42.266, "lng": 23.606}]}), encoding="utf-8")
        self.d = d
        self.lines = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, answers=None):
        it = iter(answers or [])
        files = ["--offers-file", str(self.d / "offers.toml"), "--hotels-file", str(self.d / "hotels.toml"),
                 "--config", str(self.d / "config.toml"), "--data-file", str(self.d / "data.json")]
        self.lines = []
        return ao.main(list(args) + files, today=TODAY, ask=lambda _p: next(it), out=self.lines.append)

    def offers(self):
        return manual.load(self.d / "offers.toml")

    def text(self, name="offers.toml"):
        return (self.d / name).read_text(encoding="utf-8")


class Parsing(unittest.TestCase):
    hotels = manual.load_hotels(ROOT / "data" / "hotels.toml")    # the real file, read only

    def test_fibula_line(self):
        p = ao.parse_paste(PASTE, self.hotels)
        self.assertEqual((p["price_eur"], p["was_eur"], p["board"], p["hotel"]), (1205, 1721, "HB", "xenios-anastasia"))

    def test_amount_formats(self):
        for s, want in (("1.721", 1721), ("1.205,50", 1205.5), ("1,721", 1721), ("980", 980), ("99,5", 99.5),
                        ("2.354,00", 2354)):
            self.assertEqual(ao.parse_amount(s), want, s)

    def test_more_paste_shapes(self):
        p = ao.parse_paste("Lagomandra Beach & Suites 4* полупансион 7 ноќи од 20.06.2027 Early Booking -15% "
                           "Black Friday -5% 2.150 € 1.828 €", self.hotels)
        self.assertEqual(p["hotel"], "lagomandra-beach")
        self.assertEqual((p["price_eur"], p["was_eur"], p["board"], p["nights"]), (1828, 2150, "HB", 7))
        self.assertEqual(p["check_in"], "2027-06-20")
        self.assertEqual(p["discount_label"], "Early Booking -15% + Black Friday -5%")
        self.assertEqual(ao.parse_paste("€ 980 All Inclusive")["board"], "AI")
        unknown = ao.parse_paste("Hotel Nowhere 4* ... BB ... 640 €", self.hotels)
        self.assertEqual((unknown["hotel_name"], unknown["price_eur"], unknown["board"]), ("Hotel Nowhere", 640, "BB"))
        self.assertNotIn("was_eur", ao.parse_paste("Sani Beach 7 980 €"))    # "7 980" is not 7,980

    def test_fuzzy_hotel(self):
        self.assertEqual(ao.find_hotel("Xenios Posidi Paradise", self.hotels)[0]["id"], "xenios-possidi-paradise")
        self.assertEqual(ao.find_hotel("sani-beach", self.hotels)[0]["id"], "sani-beach")
        self.assertEqual(ao.find_hotel("XENIOS ANASTASIA RESORT & SPA", self.hotels)[0]["id"], "xenios-anastasia")
        h, close = ao.find_hotel("Xenios Possidi Holidays", self.hotels)     # a different hotel: never guessed
        self.assertIsNone(h)
        self.assertIn("xenios-possidi-paradise", [c["id"] for c in close])

    def test_dates_boards_occupancy(self):
        self.assertEqual(ao.parse_date("20.06.2027"), date(2027, 6, 20))
        self.assertEqual(ao.parse_date("2027-06-20"), date(2027, 6, 20))
        self.assertEqual(ao.parse_board("hb"), "HB")
        self.assertEqual(ao.parse_board("?"), "?")
        self.assertEqual(ao.parse_occupancy("2"), "2+0")
        with self.assertRaises(ao.AddError):
            ao.parse_board("XX")
        with self.assertRaises(ao.AddError):
            ao.parse_date("next summer")


class Adding(Base):
    def test_add_from_paste_appends_valid_entry(self):
        before = self.text()
        rc = self.run_cli("--paste", PASTE, "--check-in", "20.06.2027", "--nights", "7", "--room", "Family Room",
                          "--label", "Early Booking -30%", "--valid-until", "30.11.2026")
        self.assertEqual(rc, 0, self.lines)
        self.assertTrue(self.text().startswith(before.rstrip("\n")))          # existing text untouched
        o = self.offers()[-1]
        self.assertEqual((o["hotel"], o["price_eur"], o["was_eur"], o["board"], o["seen"], o["valid_until"]),
                         ("xenios-anastasia", 1205, 1721, "HB", "2026-11-26", "2026-11-30"))
        self.assertEqual(validate.problems(o, TODAY), [])
        self.assertIn('\n\n[[offer]]\nhotel = "xenios-anastasia"\nsource = "Fibula (manual)"\n', self.text())

    def test_rejects_invalid_and_leaves_file_alone(self):
        before = self.text()
        rc = self.run_cli("--hotel", "xenios-anastasia", "--check-in", "2026-01-10", "--nights", "7",
                          "--board", "HB", "--price", "1200")
        self.assertEqual(rc, 2)
        self.assertIn("past", self.lines[-1])
        self.assertEqual(self.text(), before)
        self.assertEqual(self.run_cli("--hotel", "xenios-anastasia", "--check-in", "2027-06-20", "--nights", "7",
                                      "--board", "HB", "--price", "40"), 2)          # €6/night: per-person price
        self.assertEqual(self.text(), before)

    def test_same_day_duplicate_refused(self):
        args = ("--hotel", "xenios-anastasia", "--check-in", "2027-06-20", "--nights", "7", "--board", "HB",
                "--room", "Standard Room Limited View", "--price", "1190", "--seen", "2026-11-25")
        self.assertEqual(self.run_cli(*args), 2)
        self.assertIn("already has a price", self.lines[-1])

    def test_close_name_needs_new_hotel_flag(self):
        args = ["--hotel", "Xenios Possidi Holidays", "--area", "Possidi", "--check-in", "2027-06-20",
                "--nights", "7", "--board", "HB", "--price", "990"]
        self.assertEqual(self.run_cli(*args), 2)
        self.assertIn("Did you mean", self.lines[-1])
        self.assertEqual(self.run_cli(*args, "--new-hotel"), 0, self.lines)
        h = {x["id"]: x for x in manual.load_hotels(self.d / "hotels.toml")}["xenios-possidi-holidays"]
        self.assertEqual((h["season"], h["area"], h["country"], h["lat"], h["lng"], h["family"]["verified"]),
                         ("summer", "Possidi, Kassandra, Halkidiki", "GR", 39.966, 23.375, []))
        txt = self.text("hotels.toml")       # summer stub goes before the WINTER section
        self.assertLess(txt.index("xenios-possidi-holidays"), txt.index("WINTER"))
        self.assertEqual(self.offers()[-1]["hotel"], "xenios-possidi-holidays")

    def test_new_winter_hotel_from_auto_found_area(self):
        rc = self.run_cli("--hotel", "Hotel Zora", "--area", "Borovets", "--season", "winter", "--check-in",
                          "2027-01-20", "--nights", "5", "--board", "HB", "--price", "700", "--occupancy", "2+0")
        self.assertEqual(rc, 0, self.lines)
        h = manual.load_hotels(self.d / "hotels.toml")[-1]
        self.assertEqual((h["id"], h["area"], h["country"], h["lat"]), ("hotel-zora", "Borovets, Bulgaria", "BG", 42.266))

    def test_new_hotel_without_location_asks_for_it(self):
        rc = self.run_cli("--hotel", "Qwerty Palace", "--check-in", "2027-06-20", "--nights", "7",
                          "--board", "HB", "--price", "990")
        self.assertEqual(rc, 2)
        self.assertIn("--area", self.lines[-1])
        self.assertEqual(self.text("hotels.toml"), HOTELS)

    def test_dry_run_saves_nothing(self):
        self.assertEqual(self.run_cli("--dry-run", "--paste", PASTE, "--check-in", "2027-06-20", "--nights", "7"), 0)
        self.assertEqual(self.text(), OFFERS)

    def test_engine_scores_the_new_entries(self):
        self.run_cli("--new-hotel", "--hotel", "Xenios Possidi Holidays", "--area", "Possidi", "--check-in",
                     "2027-06-20", "--nights", "7", "--board", "HB", "--price", "990")
        con = db.connect(self.d / "t.db")
        try:
            for h in manual.load_hotels(self.d / "hotels.toml"):
                db.upsert_hotel(con, h)
            good, rejects = validate.split(manual.load(self.d / "offers.toml"), TODAY)
            for o in good:
                db.add_sighting(con, o)
            cfg = run.load_config(ROOT / "config.toml", local=None)
            items, _ = run.build(con, cfg, TODAY, offline=True)
        finally:
            con.close()
        new = [i for i in items if i["hotel_id"] == "xenios-possidi-holidays"]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["price_eur"], 990)
        self.assertIn("Sandy beach", new[0]["family"]["unknown_musts"])   # unknown until the hotel confirms


class AgainAndList(Base):
    def test_list_shows_only_stale_future_offers(self):
        self.assertEqual(self.run_cli("--list"), 0)
        out = "\n".join(self.lines)
        self.assertIn("2. Royal Park Hotel & Apartments", out)        # seen 16 days ago
        self.assertNotIn("Xenios", out)                                 # seen yesterday
        self.assertNotIn("20.11.2026", out)                             # trip date already passed
        self.run_cli("--list", "--all")
        self.assertIn("1. Xenios Anastasia", "\n".join(self.lines))

    def test_again_records_todays_price_and_builds_history(self):
        self.assertEqual(self.run_cli("--again", "2", "--price", "399"), 0, self.lines)
        last = self.offers()[-1]
        self.assertEqual((last["seen"], last["price_eur"], last["room"], last["occupancy"]),
                         ("2026-11-26", 399, "Standard Room (DBL)", "2+0"))
        self.assertNotIn("discount_label", last)                 # its promotion ended on 20.11: not copied
        g = ao.groups(self.offers())
        self.assertEqual([len(x["sightings"]) for x in g], [1, 2, 1])
        self.run_cli("--list")
        self.assertIn("Nothing to re-check", self.lines[-1])

    def test_again_by_key_keeps_live_promotion(self):
        key = db.offer_key(self.offers()[0])
        self.assertEqual(self.run_cli("--again", key, "--price", "1.180"), 0, self.lines)
        last = self.offers()[-1]
        self.assertEqual((last["price_eur"], last["was_eur"], last["valid_until"]), (1180, 1721, "2026-11-28"))
        self.assertEqual(db.offer_key(last), key)
        self.assertEqual(self.run_cli("--again", key, "--price", "1170"), 2)    # one price per day
        self.assertIn("already has a price", self.lines[-1])

    def test_again_errors(self):
        self.assertEqual(self.run_cli("--again", "9", "--price", "100"), 2)
        self.assertEqual(self.run_cli("--again", "royal-park", "--price", "100"), 2)    # matches 2 offers
        self.assertIn("matches 2", self.lines[-1])
        self.assertEqual(self.run_cli("--again", "1"), 2)                             # no price
        self.assertEqual(self.text(), OFFERS)


class Interactive(Base):
    def test_prompts_with_paste_defaults(self):
        answers = [PASTE, "",          # paste, accept the hotel found in it
                   "20.06.2027", "7", "", "Family Room", "",   # check-in, nights, board [HB], room, occupancy [2+2]
                   "", "", "", "", "",  # price [1205], was [1721], label, valid until, url [default]
                   "y"]
        self.assertEqual(self.run_cli("--interactive", answers=answers), 0, self.lines)
        o = self.offers()[-1]
        self.assertEqual((o["hotel"], o["price_eur"], o["was_eur"], o["board"], o["room"], o["occupancy"]),
                         ("xenios-anastasia", 1205, 1721, "HB", "Family Room", "2+2"))

    def test_new_hotel_and_bad_input_reasked(self):
        answers = ["",                       # no paste
                   "Hotel Lion Borovets",     # not curated, but auto-found: becomes a stub
                   "", "", "", "", "",        # season, area, lat, lng (copied), stars skip
                   "soon", "2027-01-20", "5", "XX", "HB", "", "2+0", "700", "", "", "", "", "y"]
        self.assertEqual(self.run_cli("-i", answers=answers), 0, self.lines)
        self.assertTrue(any("is not a date" in line for line in self.lines))
        h = manual.load_hotels(self.d / "hotels.toml")[-1]
        self.assertEqual((h["name"], h["season"], h["area"], h["lat"]),
                         ("Hotel Lion Borovets", "winter", "Borovets, Bulgaria", 42.266))
        self.assertEqual(self.offers()[-1]["hotel"], h["id"])
        self.assertNotEqual(h["id"], "olympic-hotel-lion-borovets")

    def test_answer_no_saves_nothing(self):
        answers = [PASTE, "", "20.06.2027", "7", "", "", "", "", "", "", "", "", "n"]
        self.assertEqual(self.run_cli("-i", answers=answers), 1)
        self.assertEqual(self.text(), OFFERS)


class RealFiles(unittest.TestCase):
    def test_real_offers_file_still_loads_and_all_entries_have_numbers(self):
        offers = manual.load(ROOT / "data" / "offers.toml")
        self.assertEqual(len(ao.groups(offers)), len({db.offer_key(o) for o in offers}))
        tomllib.loads((ROOT / "data" / "offers.toml").read_text(encoding="utf-8"))

    def test_render_round_trips(self):
        o = {"hotel": "x", "source": "Fibula (manual)", "url": "https://a.b/c", "seen": "2026-11-26",
             "check_in": "2027-06-20", "nights": 7, "board": "HB", "room": 'Room "A" \\ B', "occupancy": "2+2",
             "price_eur": 1205.5, "was_eur": None, "discount_label": "−30% ВКУПНО"}
        back = tomllib.loads(ao.render_offer(o))["offer"][0]
        self.assertEqual(back, {k: v for k, v in o.items() if v is not None})


if __name__ == "__main__":
    unittest.main()
