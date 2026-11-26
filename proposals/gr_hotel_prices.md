# gr_hotel_prices: Greek family hotels' own price lists (2+2, half board)

Files:
- module: `trips/sources/gr_hotel_prices.py`
- tests: `tests/test_gr_hotel_prices.py` (19 tests, no network)
- fixtures: `tests/fixtures/gr_hotel_prices_{thalassies,mallas,royal_paradise,alkioni,akrothalassia,simeon}.html`, saved 2026-11-26

## What the source is, and why it is not the hotels' own websites

The plan was to read price lists that hotels publish on their own websites. On 2026-11-26 I checked about 25 family hotels in Halkidiki, the Olympic Riviera and Thassos from `docs/data.json`:

- Porfi, Sousouras, Loutra Beach, Mallas, Village Mare, Koviou, Yakinthos
- Poseidon Palace, Tosca, Alea, Aethria, Ralitsa, Kamari Beach, Achillion
- Simeon, Naias, Calypso, Alkyonis, Potidea Palace, Sun Beach, Portes
- Secret Paradise, Acrotel, Anthemus, Lagomandra, Aegean Melathron, Kassandra Palace, Thalassies

For each hotel I fetched robots.txt and the home page and looked for price links. I also read the sitemap and tried the paths `/prices`, `/en/prices`, `/price-list`, `/pricelist` and `/cenovnik`.

**None of them publishes a price list.** The sites that answered sell through WebHotelier (`reserve-online.net`, which is excluded) or another booking engine. Many of the domains don't exist at all. Web searches in English, Greek ("τιμοκατάλογος") and Serbian ("cenovnik") found no hotel-site price lists either.

These same small hotels do publish their owner's price list on **Grčka Info** (grckainfo.com), a Serbian portal for Balkan families. The page note says: "These are the official prices of property owner". Each hotel page is server-rendered HTML and gives:

- **Rooms and rates:** one block per room type and occupancy variant (for example "Adults: 2, Children: 2"). Each block has its own table of nightly rates by period. The 2027 season (April to October) is already published.
- **A "Notes" box:**
  - the price basis ("per room/per night with breakfast", "per 2 persons")
  - the half-board supplement ("Half board - 16 EUR per day per adult, 15EUR per day per child (2-9.99 years old)")
  - the child ages ("Children over 11.99 years are considered adults", "0 to 1,99 - free")
  - the tourist tax and the minimum stay
- **Hotel facts:** JSON-LD coordinates at hotel level, a photo, amenity labels (on the beach, half board, baby cot, playground) and the beach distance ("From Beach : 100 m").

**Overlap with `gr_apartments`:** the parallel `gr_apartments` source reads the same site through its Serbian region lists, looking for apartments and studios. This module covers a different set: hotels, chosen one by one in config. It also does work that `gr_apartments` doesn't:

- adds the HB supplement to give an HB total
- applies child age bands, so kids past the stated age are priced as adults
- handles pages priced per 2 persons
- prices meals that are bought separately

It uses its own id prefix (`gih-<page id>`) and its own source label, `Grčka Info (hotel price list)`. If `gr_apartments` also lists one of these hotels, `dedupe` should merge the two records: the names match and the coordinates are the same to within a few metres.

### robots.txt (grckainfo.com, 2026-11-26)
```
User-agent: *
Disallow: /cgi-bin/
Disallow: /API/
Disallow: /class/
Disallow: /controllers/
Disallow: /migracija/
Disallow: /vendor/
Disallow: /api/
Disallow: /api-layer/
Disallow: /login/
Allow: /login/media/
Allow: /uploads/
Disallow: /hotels/search/
Disallow: /sr/search/
```
The `/en/accommodation/<slug>/<id>/` pages are allowed. Only the `meta-*` agents have extra rules: no `/en/search/` and no reservation pages. This module fetches one page per configured hotel through `PoliteSession`. It never touches search or reservation URLs.

## How offers are built

- **2+2 rooms:** for each room type, the module takes the smallest occupancy variant that holds 2 adults + 2 kids. The twins' age on check-in comes from `score.kids_age_on`. If the page says children count as adults at that age, the room needs 4 adult places. Example: Alkioni says "All persons over 1 year of age are considered adults", so only rooms with 4 adult places qualify.
- **Price:** the sum of each night's published rate. A stay may cross two price periods. If any night has no published rate, there is no offer.
- **Board:** taken from the room name, or else from the price note.
- **HB totals:** a BB or room-only price becomes **HB** when the page states an HB supplement, or separate breakfast and dinner prices.
  - The total is room price + supplement × nights × (2 adults + 2 kids).
  - Each twin pays the child rate whose age range covers them.
  - A twin pays nothing when a free-meals rule covers them.
  - Otherwise a twin pays the adult rate, which errs high.
  - The room text spells out the calculation.
- **Pages priced per person or per 2 persons** (Royal Paradise): the kids are charged through a separate rule list, so these pages never give a 2+2 price. The module keeps the cheapest room for 2 adults as a "2+0" offer.
- **How many offers:** up to `max_rooms` (default 3) of the cheapest fitting room types per hotel and check-in date. `check_ins = [...]` is allowed per page or for the whole source.
- **Family facts set:** `beachfront`, `beach_m`, `half_board`, `cots_mentioned`, `playground`, `kids_free_max_age`, `first_child_free_max_age`. A free-meal rule inside the HB list is not taken to mean "child stays free".
- **Notes:** tourist tax, minimum stay, the age at which children count as adults, and "prices are dynamic" go into `notes`.

## Live check

Settings: check-in 2027-06-20, 7 nights, run on 2026-11-26. No birthdate was configured, so the twins were taken as 4.6 years old.

Result: **11 hotels, 22 priced offers.**

| Offers | Occupancy | Board | Notes |
|---|---|---|---|
| 15 | 2+2 | HB | |
| 6 | 2+2 | ? | Alkioni rooms and Achillion apartments state no meals |
| 1 | 2+0 | HB | Royal Paradise |

Examples of 2+2 totals:

| Hotel | Room | Total |
|---|---|---|
| Toroni Blue Sea | Standard Room HB | €1,001 |
| Al Mare | Room HB | €1,456 |
| Mallas | Superior Junior Suite BB + HB (adults €16/day, kids €15/day) | €1,529 |
| Thalassies | Room HB | €1,681 |

Rachoni Bay (page 4026) and Ilio Mare (page 4399) are in the sitemap, but their pages returned 404, so they were left out.

## TOML block for config.toml
```toml
[sources.gr_hotel_prices]
# Family hotels' owner price lists, as published on Grčka Info (grckainfo.com) hotel pages in English.
# robots.txt allows /en/accommodation/ (it disallows /api/, /login/, /hotels/search/, /sr/search/).
# Per room type: the smallest occupancy variant that takes 2 adults + 2 kids ("2+2"); BB / room-only
# prices get the stated half-board supplement added (HB total). One page = one hotel.
enabled = true
season = "summer"
country = "GR"
nights = 7
check_in = "2027-06-20"
max_rooms = 3                # cheapest fitting room types kept per hotel and check-in

[[sources.gr_hotel_prices.pages]]
url = "https://grckainfo.com/en/accommodation/thalassies-hotel/2413/"
area = "Limenaria, Thassos"
lat = 40.626
lng = 24.572

[[sources.gr_hotel_prices.pages]]
url = "https://grckainfo.com/en/accommodation/boutique-hotel-thalassies-nouveau/2409/"
area = "Limenaria, Thassos"
lat = 40.626
lng = 24.573

[[sources.gr_hotel_prices.pages]]
url = "https://grckainfo.com/en/accommodation/grand-beach-hotel/4338/"
area = "Limenaria, Thassos"
lat = 40.626
lng = 24.562

[[sources.gr_hotel_prices.pages]]
url = "https://grckainfo.com/en/accommodation/royal-paradise-beach-resort-and-spa/4378/"
area = "Potos, Thassos"
stars = 5
lat = 40.595
lng = 24.620

[[sources.gr_hotel_prices.pages]]
url = "https://grckainfo.com/en/accommodation/hotel-al-mare/1384/"
area = "Polichrono, Kassandra, Halkidiki"
stars = 3
lat = 40.027
lng = 23.506

[[sources.gr_hotel_prices.pages]]
url = "https://grckainfo.com/en/accommodation/hotel-mallas/1145/"
area = "Nea Kallikratia, Kassandra, Halkidiki"
stars = 3
lat = 40.311
lng = 23.062

[[sources.gr_hotel_prices.pages]]
url = "https://grckainfo.com/en/accommodation/hotel-alkioni-by-the-sea/2760/"
area = "Siviri, Kassandra, Halkidiki"
stars = 3
lat = 40.038
lng = 23.359

[[sources.gr_hotel_prices.pages]]
url = "https://grckainfo.com/en/accommodation/simeon-hotel/3329/"
area = "Metamorfosi, Sithonia, Halkidiki"
stars = 3
lat = 40.229
lng = 23.606

[[sources.gr_hotel_prices.pages]]
url = "https://grckainfo.com/en/accommodation/toroni-blue-sea-hotel-spa/1395/"
area = "Toroni, Sithonia, Halkidiki"
lat = 39.982
lng = 23.905

[[sources.gr_hotel_prices.pages]]
url = "https://grckainfo.com/en/accommodation/akrothalassia-hotel/5783/"
area = "Leptokaria, Olympic Riviera"
lat = 40.048
lng = 22.576

[[sources.gr_hotel_prices.pages]]
url = "https://grckainfo.com/en/accommodation/achillion-hotel-apartments/1141/"
area = "Paralia Katerinis, Olympic Riviera"
kind = "apartment"
lat = 40.268
lng = 22.597
```

The stars for Royal Paradise (5) come from data.json (Travelland). The 3-star values come from the Olympic listings or the hotel's own text. Delete any you don't trust.

## Known limits

- **Not live availability:** these are the owner's published prices. The page itself says "Published prices have not yet been confirmed and may change", and Alkioni says its prices are dynamic. Tourist tax is extra: it is noted, not added.
- **No discounts:** the list has no "was" prices, so only our own price history can show a real drop.
- **Kids' meal prices:** taken only from rules that state an age range. Kids with no stated rate are charged the adult rate, which errs high and is flagged in the room text. A "50% discount" rule is read as a percentage of the adult rate.
- **Board "?":** stays "?" when neither the room nor the note states a board (apartments, Alkioni).
- **Hand-picked hotels:** this module never crawls lists. To add a hotel, find its `/en/accommodation/<slug>/<id>/` URL in `https://grckainfo.com/xmls/sitemap.xml`, or through a link on the site, and add a page entry. The site lists more family hotels in these areas; I fetched only the 13 pages needed to check the page structure.
- **Stars:** not on the page. Set `stars` in config when known.
- **Serbian-only notes:** the price basis and board are read from the English notes. If a page's notes are only in Serbian, the basis falls back to "unit" and the board comes from the room name. The parser also reads the Serbian "Odrasli/Deca" labels and `dd.mm.yyyy` periods.

## For the integrator

- Add `gr_hotel_prices` to the imports and to `AUTO_SOURCES` in `trips/run.py`. No new fields are needed: the hotel and offer dicts have the usual shape and use only existing `family` keys.
- Decide how this source and `gr_apartments` should split grckainfo.com: same site, different pages and purpose. If both run in one `PoliteSession`, requests to the host are already spaced.
- When I ran the full suite, three tests failed in `tests.test_family_fit.Tiers`. This module isn't imported there, so the failures are probably from another agent's work in progress.
