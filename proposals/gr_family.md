# gr_family: 24 more Greek family hotels for `gr_hotel_prices` (config-only)

**Result:** no new parser. The existing `gr_hotel_prices` module already reads Grčka Info owner price
lists correctly. The missing piece was hotel coverage, so this is a list of `[[sources.gr_hotel_prices.pages]]`
entries to **append** to config.toml. All 24 hotels give real **2+2** stay totals (2 adults + 2 small kids)
for 7 nights from 2027-06-20.

Files: `tests/test_gr_family.py` (9 tests, 1 expected failure that documents a parser gap), fixtures
`tests/fixtures/gr_family_{golden_beach,siokas,esperia,porto_matina,akti_belvedere,saint_george,list_sithonia_hotels}.html`
(saved 2026-11-28).

## Agencies: checked again, still not viable
`rs_agencies.md` and `mk_agencies.md` already cover these, and nothing has changed:
- BigBlue / Kon Tiki / Filip Travel share one B2C platform. Its lists load through `.asmx`/`.ashx`, which robots.txt disallows. Filip also disallows `/sr/hotel/greece/`, and Kon Tiki's robots.txt returns HTTP 500.
- Eurotours.mk doesn't resolve.
- Fibula's private API is excluded.

Even where these agencies show prices, they are 2-adult "from" prices. Grčka Info publishes the owner's
table per occupancy variant ("Adults: 2, Children: 2"), which is exactly the gap. So I spent the request
budget there.

## Source and robots.txt
grckainfo.com robots.txt (unchanged since 2026-11-26):
```
User-agent: *
Disallow: /cgi-bin/  /API/  /class/  /controllers/  /migracija/  /vendor/  /api/  /api-layer/  /login/
Allow: /login/media/
Allow: /uploads/
Disallow: /hotels/search/
Disallow: /sr/search/
```
I used only the region and town lists `/sr/smestaji/<region>/<id>/` and the hotel pages `/en/accommodation/<slug>/<id>/`.
Both are allowed. To find the hotels, I used the site's own filters on the lists: `tip[0]=105` (Hotels) and
`udaljenost[0]=1` (beach up to 200 m). The Polupansion (HB) filter turned out too sparse to use: only 7 hits.

The lists I read:
- regions: Kassandra 209, Sithonia 210, Thassos 217, Kavala 233
- towns: Paralia 333, Leptokarija 335, Nei Pori 337, Asprovalta 342, Stavros 344

The region pages `olimpska-regija/231` and `solunska-regija/232` return empty lists, so use the town IDs for those coasts.
The Kavala list has only one city hotel. I found no Nea Peramos or Keramoti hotel on the site.

**Live requests:** 48 in total (3 robots.txt, 17 list pages, 28 hotel pages), spaced 6–8 s apart. There were no blocks.

## Live check (run offline with today's `gr_hotel_prices` code)
- 28 hotel pages read → **24 hotels kept, 50 priced offers, all occupancy 2+2**.
- **18 are HB or AI:** 15 HB and 3 AI (Village Mare).
- The rest are BB, RO or "?".
- 4 hotels were dropped:
  - Sun Hotel: no 2+2 room
  - Core Hotel and Beach Hotel Kapahi: no price table
  - Hotel Haris: its own text says 250 m from the sea

Cheapest 2+2 totals for 7 nights:

| Hotel | Board | Total |
|---|---|---|
| Porto Matina (Metamorfosi) | HB | €917 |
| Siokas (Nei Pori) | HB | €1,008 |
| Golden Beach (Metamorfosi) | HB | €1,155 |
| Paradise Kriopigi | HB | €1,155 |
| Esperia (Pefkari, Thassos) | HB | €1,330 |
| Village Mare | AI | €1,869 |
| Anthemus (Nikiti) | HB | €2,842 |

Anthemus, Village Mare and Palladium are in data.json today only as 2+0 prices from Olympic.

## TOML block: append after the existing `[[sources.gr_hotel_prices.pages]]` entries
They are ordered in three tiers: HB/AI first (8), then BB (10), then board not stated (6). Drop the third tier if you only want meals included.
```toml
[[sources.gr_hotel_prices.pages]]
# Anthemus Sea Beach Hotel & Spa: beachfront chip; HB in price
url = "https://grckainfo.com/en/accommodation/anthemus-sea-beach-hotel-and-spa/4155/"
area = "Nikiti, Sithonia, Halkidiki"
lat = 40.145
lng = 23.736

[[sources.gr_hotel_prices.pages]]
# Golden Beach Hotel: HB family rooms 2+2; beach distance not stated (site filter: up to 200 m)
url = "https://grckainfo.com/en/accommodation/golden-beach-hotel/3751/"
area = "Metamorfosi, Sithonia, Halkidiki"
lat = 40.228
lng = 23.605

[[sources.gr_hotel_prices.pages]]
# Hotel Esperia: 10 m from beach; HB per apartment
url = "https://grckainfo.com/en/accommodation/hotel-esperia/1663/"
area = "Pefkari, Thassos"
lat = 40.618
lng = 24.597

[[sources.gr_hotel_prices.pages]]
# Hotel Siokas: on a wide sandy beach; HB
url = "https://grckainfo.com/en/accommodation/hotel-siokas/1501/"
area = "Nei Pori, Olympic Riviera"
lat = 39.978
lng = 22.651

[[sources.gr_hotel_prices.pages]]
# Porto Matina Hotel: beachfront chip; HB studio
url = "https://grckainfo.com/en/accommodation/porto-matina-hotel/3651/"
area = "Metamorfosi, Sithonia, Halkidiki"
lat = 40.228
lng = 23.606

[[sources.gr_hotel_prices.pages]]
# Village Mare Hotel: all inclusive; family rooms with bunk bed
url = "https://grckainfo.com/en/accommodation/village-mare-hotel/4802/"
area = "Metamorfosi, Sithonia, Halkidiki"
lat = 40.229
lng = 23.583

[[sources.gr_hotel_prices.pages]]
# Akti Belvedere Color & Essence: beachfront chip; HB supplement 35/25 EUR not yet read by the parser (shows RO)
url = "https://grckainfo.com/en/accommodation/akti-belvedere-color-and-essence/2920/"
area = "Skala Rachoni, Thassos"
lat = 40.792
lng = 24.630

[[sources.gr_hotel_prices.pages]]
# Hotel Paradise Kriopigi: 160 m (borderline); HB included
url = "https://grckainfo.com/en/accommodation/hotel-paradise-kriopigi/4775/"
area = "Kriopigi, Kassandra, Halkidiki"
lat = 40.047
lng = 23.474

[[sources.gr_hotel_prices.pages]]
# Alexander Inn: 80 m; BB only
url = "https://grckainfo.com/en/accommodation/alexander-inn/3877/"
area = "Stavros, Thessaloniki coast"
lat = 40.671
lng = 23.691

[[sources.gr_hotel_prices.pages]]
# Ammon Garden Hotel: 100 m; BB only
url = "https://grckainfo.com/en/accommodation/ammon-garden-hotel/3016/"
area = "Pefkochori, Kassandra, Halkidiki"
lat = 39.987
lng = 23.619

[[sources.gr_hotel_prices.pages]]
# By the Sea Luxury Suites: beachfront chip; BB only
url = "https://grckainfo.com/en/accommodation/by-the-sea-luxury-suites/2410/"
area = "Limenas, Thassos"
lat = 40.777
lng = 24.697

[[sources.gr_hotel_prices.pages]]
# Hotel Palladium Sithonia: 30 m; BB only
url = "https://grckainfo.com/en/accommodation/hotel-palladium-sithonia/3252/"
area = "Kalamitsi, Sithonia, Halkidiki"
lat = 39.993
lng = 23.991

[[sources.gr_hotel_prices.pages]]
# Hotel Thalassokipos: BB only; distance not stated (site filter: up to 200 m)
url = "https://grckainfo.com/en/accommodation/hotel-thalassokipos/1932/"
area = "Vourvourou, Sithonia, Halkidiki"
lat = 40.229
lng = 23.760

[[sources.gr_hotel_prices.pages]]
# Vozina Hotel: 150 m; BB only
url = "https://grckainfo.com/en/accommodation/vozina-hotel/4140/"
area = "Metamorfosi, Sithonia, Halkidiki"
lat = 40.230
lng = 23.603

[[sources.gr_hotel_prices.pages]]
# Xenonas Apollon: 50 m; BB only
url = "https://grckainfo.com/en/accommodation/xenonas-apollon/4244/"
area = "Sarti, Sithonia, Halkidiki"
lat = 40.081
lng = 23.979

[[sources.gr_hotel_prices.pages]]
# Saint George Hotel: 100 m; BB, meal 15 EUR/person/day not yet read
url = "https://grckainfo.com/en/accommodation/saint-george-hotel/3457/"
area = "Asprovalta, Thessaloniki coast"
lat = 40.721
lng = 23.707

[[sources.gr_hotel_prices.pages]]
# Plaza Hotel: 40 m; room only, breakfast 7 EUR
url = "https://grckainfo.com/en/accommodation/plaza-hotel/4899/"
area = "Hanioti, Kassandra, Halkidiki"
lat = 40.002
lng = 23.575

[[sources.gr_hotel_prices.pages]]
# Kristal Hotel: 100 m; board not stated, breakfast 7.5 EUR
url = "https://grckainfo.com/en/accommodation/kristal-hotel/3810/"
area = "Skala Prinos, Thassos"
lat = 40.761
lng = 24.564

[[sources.gr_hotel_prices.pages]]
# Aeollos Hotel: 20 m; board not stated (studios/suites)
url = "https://grckainfo.com/en/accommodation/aeollos-hotel/4190/"
area = "Pefkochori, Kassandra, Halkidiki"
lat = 39.988
lng = 23.620

[[sources.gr_hotel_prices.pages]]
# ASTRO Hotel Apartments: 150 m; apartments, self-catering
url = "https://grckainfo.com/en/accommodation/astro-hotel-apartments/1001/"
area = "Paralia Katerinis, Olympic Riviera"
kind = "apartment"
lat = 40.266
lng = 22.596

[[sources.gr_hotel_prices.pages]]
# Corali Hotel: beachfront chip; apartments, board not stated
url = "https://grckainfo.com/en/accommodation/corali-hotel/5736/"
area = "Sarti, Sithonia, Halkidiki"
kind = "apartment"
lat = 40.091
lng = 23.979

[[sources.gr_hotel_prices.pages]]
# Sithon Apartment Hotel: 50 m; apartment hotel, board not stated
url = "https://grckainfo.com/en/accommodation/sithon-apartment-hotel/5350/"
area = "Sarti, Sithonia, Halkidiki"
kind = "apartment"
lat = 40.081
lng = 23.979

[[sources.gr_hotel_prices.pages]]
# Hotel Konstantinoupolis: 100 m; board not stated
url = "https://grckainfo.com/en/accommodation/hotel-konstantinoupolis/1443/"
area = "Asprovalta, Thessaloniki coast"
lat = 40.714
lng = 23.703

[[sources.gr_hotel_prices.pages]]
# Hotel Golden Sand: board not stated; distance not stated (site filter: up to 200 m)
url = "https://grckainfo.com/en/accommodation/hotel-golden-sand/2400/"
area = "Golden Beach (Chrysi Ammoudia), Thassos"
lat = 40.731
lng = 24.760

```

## Selection criteria and known limits
- **Beach:** every hotel is in the site's "up to 200 m" filter. The hotel's own text or the beachfront chip puts 20 of them at ≤150 m.
  - Golden Beach, Thalassokipos and Golden Sand state no distance. They are in the 200 m filter only.
  - Paradise Kriopigi says 160 m, which is borderline.
- **Sand:** taken from the site's paragraph about each town's beach: all sandy. Metamorfosi, Pefkari and Kapahi say "sand and pebbles".
- **Ratings: no Google or Booking score is stated.** The site shows only its own reviews, and nearly all say "No reviews yet". So none of these hotels can be checked against the 4.3 / 8.2 rule from the page. The integrator's rating step (or a manual check) must clear them before they are promoted.
- **Stars:** not on the pages. Left unset.
- **More hotels exist:** I read only page 1 of the Sithonia and Thassos hotel lists. Page 2 (`/210/2/?udaljenost%5B0%5D=1&tip%5B0%5D=105`, `/217/2/…`) can be checked the same way.
- **Owner list prices, not live availability.** There are no "was" prices, and the tourist tax is extra.

## For the integrator (small fixes in `gr_hotel_prices.py`; I did not edit it)
1. **`_hb_supplement` misses** `Half board - 35€/per day, children 0-12 years - 25 €/per day` (Akti Belvedere): there is no "adult" or "person" word.
   - Accept `half board\s*-\s*{MONEY}\s*/?\s*per day` as the adult rate.
   - The test `ParserGaps.test_akti_belvedere_hb_supplement` (currently an expected failure) gives the target: HB €1,960. Drop its `@expectedFailure` when the fix lands.
2. **A "Meal per person 15EUR/per day" line** (Saint George) is a dinner supplement for a BB price. Reading it would turn Saint George into an HB offer: €1,050 + 15 × 4 × 7.
3. **`beach_m` is None on all 28 new pages.** The "From Beach : N m" label isn't on them. The hotel's own text has it ("just 100 meters from the beach", "30m away from the beautiful Kalamitsi beach"). The regex in `gr_apartments._beach_facts` could be reused for this.
4. **No `trips/run.py` change** is needed: same module and id prefix (`gih-<id>`). Dedupe should merge Anthemus, Village Mare and Palladium with the Olympic records.
