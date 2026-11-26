"""BulgariaSki (bulgariaski.com) hotel price lists: parser tests on saved pages. No network."""
import unittest
from datetime import date
from pathlib import Path

from trips import run
from trips.sources import bgski

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 25)
PAGE = {"url": "https://www.bulgariaski.com/bansko/hotels/", "season": "winter", "area": "Bansko, Bulgaria",
        "country": "BG", "lat": 41.83, "lng": 23.48, "nights": 5, "check_in": "2027-01-15"}


def read(name):
    return (FIX / name).read_text(encoding="utf-8", errors="ignore")


def table(rows: str, heads: str = '<th>LS&nbsp;<i data-tooltip title="01/12/2026-01/04/2027" class="x"></i></th>'):
    return ('<h1 itemprop="itemreviewed">Test Hotel<!--&nbsp;--><img src="https://www.bulgariaski.com/img/star.png">'
            '</h1><table class="pricelist"><thead><tr><th>Room type</th><th>Meal</th>' + heads +
            '</tr><tbody>' + rows + '</tbody></table>')


class PriceList(unittest.TestCase):
    def test_casa_karina_table(self):
        seasons, rows = bgski.parse_pricelist(read("bgski_casa_karina.html"))
        self.assertEqual(len(seasons), 4)
        self.assertEqual(seasons[2][1], (date(2027, 1, 4), date(2027, 3, 14)))     # MS second range
        one = next(r for r in rows if r["room"] == "One-bedroom apartment")
        self.assertEqual((one["meal"], one["rates"]), ("HB", [110, 141, 152, 185]))

    def test_stay_spans_two_seasons(self):
        seasons, rows = bgski.parse_pricelist(read("bgski_regnum.html"))
        fam = next(r for r in rows if r["room"].startswith("1-bedroom family"))
        # MS (190) until 15 Jan, HS (236) from 15 Jan: 13→18 Jan = 2 × 190 + 3 × 236
        self.assertEqual(bgski.stay_price(fam["rates"], seasons, date(2027, 1, 13), 5), 2 * 190 + 3 * 236)
        self.assertIsNone(bgski.stay_price(fam["rates"], seasons, date(2027, 4, 10), 5))   # past the list

    def test_hotel_facts(self):
        h = bgski.parse_hotel(read("bgski_casa_karina.html"), TODAY)
        self.assertEqual((h["name"], h["stars"], h["hotel_no"]), ("Casa Karina Aparthotel", 4, "10703"))
        self.assertTrue(h["image"].startswith("https://www.bulgariaski.com/hotel-images/big/10703_"))
        self.assertEqual(h["max_1bed"], "2 adults + 1 child or 3 adults")
        self.assertEqual((h["kids_from"], h["cot_eur"], h["per_person"]), (2, 2.6, False))

    def test_city_tax_per_person_is_not_a_per_person_rate(self):
        h = bgski.parse_hotel(read("bgski_pirin_golf.html"), TODAY)
        self.assertFalse(h["per_person"])
        _, offers = bgski.to_hotel_and_offers(h, "u", PAGE, CFG, TODAY)
        self.assertEqual((offers[0]["room"], offers[0]["price_eur"]), ("One-bedroom Suite Superior", 5 * 314))


class Promos(unittest.TestCase):
    def test_only_future_deadlines(self):
        self.assertEqual(bgski.promos(read("bgski_royal_park.html"), TODAY),
                         [{"pct": 10, "valid_until": "2026-11-30", "kind": "Early booking"}])
        self.assertEqual(bgski.promos(read("bgski_regnum.html"), TODAY), [])          # 30 Sept / 31 Oct passed

    def test_sept_is_read_as_a_month(self):
        p = bgski.promos(read("bgski_regnum.html"), date(2026, 9, 1))
        self.assertEqual(p[0], {"pct": 25, "valid_until": "2026-09-30", "kind": "Early booking"})

    def test_conditional_promo_ignored(self):
        html = ('<div class="list-promo green"><div><a href="x">- 15% discount until 10 Dec 2026 '
                '(not valid for period 23 Dec 2026 - 03 Jan 2027);</a></div></div>')
        self.assertEqual(bgski.promos(html, TODAY), [])


class Offers(unittest.TestCase):
    def test_one_bedroom_offer_with_discount(self):
        h = bgski.parse_hotel(read("bgski_royal_park.html"), TODAY)
        hotel, offers = bgski.to_hotel_and_offers(h, "https://www.bulgariaski.com/bansko/royal_park.shtml", PAGE,
                                                  CFG, TODAY)
        self.assertEqual(hotel["id"], "bs-11319")
        self.assertEqual(hotel["kind"], "apartment")
        self.assertIs(hotel["family"]["separate_bedroom"], True)
        self.assertEqual(len(offers), 1)
        o = offers[0]
        self.assertEqual((o["room"], o["board"], o["occupancy"]), ("One-bedroom apartment", "BB", "2+0"))
        self.assertEqual(o["was_eur"], 5 * 101)                       # MS 03/01–26/02 at 101 €/night
        self.assertEqual(o["price_eur"], round(5 * 101 * 0.9, 2))
        self.assertEqual((o["discount_label"], o["valid_until"]), ("Early booking -10%", "2026-11-30"))

    def test_cheapest_bedroom_row(self):
        h = bgski.parse_hotel(read("bgski_regnum.html"), TODAY)
        _, offers = bgski.to_hotel_and_offers(h, "u", PAGE, CFG, TODAY)
        self.assertEqual(offers[0]["room"], "1-bedroom family apartment with kitchenette")
        self.assertEqual(offers[0]["price_eur"], 5 * 236)             # 15 Jan onwards is HS
        self.assertIsNone(offers[0]["was_eur"])

    def test_check_in_not_in_the_past(self):
        h = bgski.parse_hotel(read("bgski_casa_karina.html"), TODAY)
        _, offers = bgski.to_hotel_and_offers(h, "u", {**PAGE, "check_in": "2026-01-10"}, CFG, TODAY)
        self.assertEqual(offers[0]["check_in"], TODAY.isoformat())
        self.assertEqual(offers[0]["price_eur"], 5 * 110)            # 25–30 Nov is still SS (…–01/12/2026)

    def test_rooms_only_hotel_gives_nothing(self):
        h = bgski.parse_hotel(table("<tr><th >Double Room</th><td>HB</td><td>90 &euro;</td></tr>"
                                    "<tr><th >Studio</th><td>HB</td><td>80 &euro;</td></tr>"), TODAY)
        self.assertEqual(bgski.to_hotel_and_offers(h, "u", PAGE, CFG, TODAY), (None, []))

    def test_suite_fallback_keeps_bedroom_unknown(self):
        h = bgski.parse_hotel(table("<tr><th >Double Room</th><td>BB</td><td>90 &euro;</td></tr>"
                                    "<tr><th >Family suite</th><td>BB</td><td>150 &euro;</td></tr>"), TODAY)
        hotel, offers = bgski.to_hotel_and_offers(h, "https://www.bulgariaski.com/bansko/test.html", PAGE, CFG, TODAY)
        self.assertNotIn("separate_bedroom", hotel["family"])
        self.assertEqual(hotel["kind"], "hotel")
        self.assertEqual(hotel["id"], "bs-test")
        self.assertEqual((offers[0]["room"], offers[0]["price_eur"]), ("Family suite", 750))

    def test_one_offer_per_meal(self):
        h = bgski.parse_hotel(table("<tr><th >One-bedroom apartment</th><td>RO</td><td>60 &euro;</td></tr>"
                                    "<tr><th >One-bedroom apartment</th><td>HB</td><td>100 &euro;</td></tr>"
                                    "<tr><th >Two-bedroom apartment</th><td>HB</td><td>140 &euro;</td></tr>"), TODAY)
        _, offers = bgski.to_hotel_and_offers(h, "u", PAGE, CFG, TODAY)
        self.assertEqual([(o["board"], o["price_eur"]) for o in offers], [("HB", 500), ("RO", 300)])


class Links(unittest.TestCase):
    def test_list_page_links(self):
        html = read("bgski_list_bansko.html")
        every = bgski.hotel_links(html, "bansko", None)
        self.assertGreaterEqual(len(every), 50)
        apt = dict(bgski.hotel_links(html, "bansko"))
        self.assertIn("https://www.bulgariaski.com/bansko/regnum_apartments.html", apt)
        self.assertNotIn("https://www.bulgariaski.com/bansko/kempinski.shtml", apt)
        self.assertTrue(all("-tab-" not in u for u in apt))

    def test_disabled(self):
        self.assertEqual(bgski.fetch({"sources": {}}, TODAY), ([], []))


if __name__ == "__main__":
    unittest.main()
