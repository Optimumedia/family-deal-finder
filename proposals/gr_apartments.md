# gr_apartments: Grčka Info (grckainfo.com) per-unit family prices

## Source
Grčka Info is a Serbian-language portal for Balkan families. It has about 4,000 private apartments, studios and small hotels in Greece. Each property page has an HTML price table **per unit, per occupancy variant, per period**, for example:

```
Studio   Odrasli: 2, Deca: 2
Period                       Cena po noći
01.05.2027. – 20.06.2027.    90.00 €
21.06.2027. – 30.06.2027.    100.00 €
```

The basis is stated under "Napomene" ("Cene su izražene u € po smeštajnoj jedinici/dnevno", meaning per unit, per day). The rates come from the owners. They are not Booking-fed, and booking is by request or email. 2027 tables are already published.

Other sources checked:
- **nikana.gr** (Sarti agency): robots.txt allows the pages, but prices sit behind its booking engine (`/booking` is disallowed). The HTML only has "od 50 € po noćenju" ("from €50 a night"). Not viable.

## robots.txt (fetched 2026-11-26)
```
User-agent: *
Disallow: /cgi-bin/  /API/  /class/  /controllers/  /migracija/  /vendor/  /api/  /api-layer/  /login/
Allow: /login/media/
Allow: /uploads/
Disallow: /hotels/search/
Disallow: /sr/search/
```
The module only uses `/sr/smestaji/<place>/<id>/[n/]?udaljenost[0]=1` lists and `/sr/smestaj/<name>/<id>/` property pages, and both are allowed. It never uses `/sr/search/`. The site has no bot wall and the live check got no 403s. Images are hotlinked from `/uploads/`.

## How it reads
1. **List pages.** It reads the site's own region and town lists, filtered with the site's "Do 200 m" beach-distance filter (`udaljenost[0]=1`). Only cards with "Do N osoba" ≥ 4 are opened. An optional `towns` setting narrows the region lists.
2. **Picking the family price.** For each unit type, it takes the occupancy variant with the smallest capacity that still fits 2 adults + 2 kids: "Odrasli: 2, Deca: 2", "Odrasli: 4" or "3 + 1". So the family never pays for a 5th bed. Units for more than `max_unit_guests` guests (default 6) are skipped, which drops lines like "apartment for 2 families, 9 adults".
3. **Price.** `price_eur` is the sum of the nightly rates over the stay, so a stay can cross two periods. If any night has no published rate, the offer is dropped. Occupancy is always "2+2".
4. **Board.**
   - BB, HB, FB or AI when the unit name says so ("Soba - 4 osobe HB", "Standard soba - BB").
   - Otherwise SC (kitchen or apartment).
   - Otherwise "?".
5. **Facts read from each page:**
   - From the page's JSON-LD: coordinates and photo.
   - From the amenity chips: cot on request → `cots_mentioned`, "Smeštaj na plaži" (on the beach) → `beachfront`, `half_board`, `playground`, "Odvojena spavaća soba" (separate bedroom) → `separate_bedroom`.
   - From the property's own description: `beach_m` ("290 metara od plaže", "na udaljenosti od samo 30m") and sand or pebble.
   - If the description doesn't say sand or pebble, it is taken from the site's paragraph about the town's beach, and the notes say so.
   - Studio and "N sobe" unit names set `separate_bedroom`.
   - Notes record the tourist tax, special offers and minimum stay.

## TOML block for config.toml
```toml
[sources.gr_apartments]
# Grčka Info (grckainfo.com): owners' per-unit price tables (EUR/unit/night) for private
# apartments, studios and small hotels. robots.txt disallows only /api/, /login/, /sr/search/.
# Lists use the site's own "beach up to 200 m" filter; only units for 4+ are opened.
enabled = true
max_list_pages = 2        # 12 cards per list page
max_properties = 12       # property pages opened per list (each one is a request)
max_unit_guests = 6       # skip "2 families / 9 adults" units

[[sources.gr_apartments.pages]]
url = "https://grckainfo.com/sr/smestaji/halkidiki-sitonija/210/?udaljenost%5B0%5D=1"
towns = ["Sarti", "Nikiti", "Neos Marmaras"]
max_list_pages = 6
max_properties = 15
beach_filter_m = 200
season = "summer"
area = "Sithonia, Halkidiki"
country = "GR"
lat = 40.10
lng = 23.80
nights = 7
check_in = "2027-06-20"

[[sources.gr_apartments.pages]]
url = "https://grckainfo.com/sr/smestaji/halkidiki-kasandra/209/?udaljenost%5B0%5D=1"
towns = ["Pefkohori", "Hanioti", "Polihrono"]
max_list_pages = 6
max_properties = 15
beach_filter_m = 200
season = "summer"
area = "Kassandra, Halkidiki"
country = "GR"
lat = 40.02
lng = 23.43
nights = 7
check_in = "2027-06-20"

[[sources.gr_apartments.pages]]
url = "https://grckainfo.com/sr/smestaji/paralia/333/?udaljenost%5B0%5D=1"
beach_filter_m = 200
season = "summer"
area = "Paralia, Olympic Riviera"
country = "GR"
lat = 40.27
lng = 22.60
nights = 7
check_in = "2027-06-20"

[[sources.gr_apartments.pages]]
url = "https://grckainfo.com/sr/smestaji/leptokarija/335/?udaljenost%5B0%5D=1"
beach_filter_m = 200
season = "summer"
area = "Leptokaria, Olympic Riviera"
country = "GR"
lat = 40.06
lng = 22.56
nights = 7
check_in = "2027-06-20"

[[sources.gr_apartments.pages]]
url = "https://grckainfo.com/sr/smestaji/nei-pori/337/?udaljenost%5B0%5D=1"
beach_filter_m = 200
season = "summer"
area = "Nei Pori, Olympic Riviera"
country = "GR"
lat = 39.97
lng = 22.62
nights = 7
check_in = "2027-06-20"

[[sources.gr_apartments.pages]]
url = "https://grckainfo.com/sr/smestaji/stavros/344/?udaljenost%5B0%5D=1"
beach_filter_m = 200
season = "summer"
area = "Stavros, Thessaloniki region"
country = "GR"
lat = 40.665
lng = 23.70
nights = 7
check_in = "2027-06-20"

[[sources.gr_apartments.pages]]
url = "https://grckainfo.com/sr/smestaji/asprovalta/342/?udaljenost%5B0%5D=1"
beach_filter_m = 200
season = "summer"
area = "Asprovalta, Thessaloniki region"
country = "GR"
lat = 40.72
lng = 23.71
nights = 7
check_in = "2027-06-20"

[[sources.gr_apartments.pages]]
url = "https://grckainfo.com/sr/smestaji/tasos/228/?udaljenost%5B0%5D=1"
max_list_pages = 3
beach_filter_m = 200
season = "summer"
area = "Thassos"
country = "GR"
lat = 40.70
lng = 24.65
nights = 7
check_in = "2027-06-20"
```

`check_ins = ["2027-06-20", "2027-09-04"]` can replace `check_in` to price several stays from the same page fetch, at no extra cost. A whole run with this block makes about 130 requests, which takes about 15 minutes at the 6 s + jitter delay.

## Live check (2026-11-26)
- **Setup:** 8 lists, at most 5 properties each, 7 nights from 20.06.2027.
- **Requests:** 46, with 0 blocked and 0 errors.
- **Result:** 38 properties and **80 priced 2+2 offers** (after the board and big-unit fixes, replayed on the saved pages).
- **Board:** 64 SC, 6 BB, 3 HB, 7 "?".
- **Beach facts:** 33 properties have sand confirmed, and 34 have a stated beach distance or a beachfront chip.
- **Validation:** every offer passes `validate.problems`.
- **Example prices (7 nights):**
  - Likno Apartments, Neos Marmaras (2-room apartment, 30 m to the beach): €525
  - Hotel Siokas, Nei Pori, room for 2 + 2 kids with HB: €1,008
  - Mpasisas Apartments, Paralia (2 bedrooms): €350

## Known limits
- The site has thousands of properties, but `max_list_pages` and `max_properties` sample only the first ones in the site's order (TOP-listed first). To widen coverage, raise them.
- "Specijalne ponude" (last minute, early booking) are free text. They are only flagged in the notes and never applied, so `was_eur` is set only when a rate cell shows two prices.
- The "Do 200 m" filter is the site's claim. When a page gives no number, the module stores `family.beach_max_m = 200`, not `beach_m`.
- Sand from the town paragraph is a town-level fact, and the notes flag it.
- A unit name with no board and no kitchen chip (e.g. a hotel room) gets board "?".
- Tourist tax (usually €2 per unit per day) is not included in the price.
- "Contact for the price" units, and periods with no rate, are skipped.

## For the integrator
- Add `gr_apartments` to `trips/run.py`: the import and `AUTO_SOURCES`.
- New optional field `family.beach_max_m`: an upper bound from the site's filter. The scorer ignores it today. It could count as "≤200 m, check" instead of an unknown.
- Tests: `PYTHONIOENCODING=utf-8 python -m unittest tests.test_gr_apartments -v` (15 tests). The fixtures are `tests/fixtures/gr_apartments_*.html`.
