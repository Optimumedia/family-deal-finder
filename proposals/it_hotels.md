# it_hotels: Italian family beach resorts near BRI / NAP / AHO, hotel-only 2+2 prices

Files:
- module: `trips/sources/it_hotels.py`
- tests: `tests/test_it_hotels.py` (no network; they also parse the TOML block below, so the block stays valid)
- fixtures: `tests/fixtures/it_hotels_{porto_giardino,baia_domizia,le_tonnare,mclub_golfo}.json` (pypdf text of page 1 of each sheet, the price table only) and `it_hotels_media_giardino.json` (a real media-search answer). All saved 2026-11-28.

## What I checked, and why the source is an agency's PDFs

I was looking for hotel-only summer 2027 prices for 2 adults + 2 kids aged 3, near the Italian airports SKP flies to directly. I checked these sources on 2026-11-28:

- **The hotels' own websites.** Torre Canne, Monopoli/Capitolo, Savelletri/Rosa Marina, Ostuni Marina, Mondello, Cefalù, Alghero/San Giovanni, Le Bombarde and Stintino all came up empty. Web searches for "listino prezzi 2026/2027" with "mezza pensione" and "riduzioni bambini" found only booking engines and OTA pages. No hotel published a listino I could read.
- **Bluserena** (GranSerena at Torre Canne publishes catalogue PDFs). Its robots.txt is served behind an **Incapsula bot wall**, so it is not usable.
- **Italian portals.** They are Voyage Privé, Logitravel, Volagratis and Alpitour: dynamic engines with no price lists, so none is usable.
- **Radio Radio Viaggi** (viaggi.radioradio.it), a Rome agency, **is usable**. It publishes one PDF price sheet per resort per summer. Page 1 is the price table, and it has a **"solo soggiorno" (hotel only)** column next to the ferry package. Per-night sheets are hotel-only, and the flight is a separate add-on. Each sheet also gives the "listino ufficiale" (the hotel's list price), the 3rd and 4th bed child reductions (3/13 years, "età non compiuta", so a 3-year-old is in the band) and the mandatory local fees.

### robots.txt (viaggi.radioradio.it, 2026-11-28)
```
User-agent: *
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php
Sitemap: https://viaggi.radioradio.it/wp-sitemap.xml
```
The source reads only `/wp-content/uploads/…pdf` and `/wp-json/wp/v2/media?search=…`. Both are allowed.

## Hotels (2026 sheets; the 2027 sheets aren't out yet)

| key | resort | area | airport, straight-line distance | board | twins |
|---|---|---|---|---|---|
| porto-giardino | Porto Giardino 4* | Capitolo, Monopoli | BRI ~55 km | AI | 3rd bed -90%, 4th bed -50% |
| baia-domizia | Baia Domizia Resort 4* | Baia Domizia, Domitian coast | NAP ~55 km | HB | 3rd/4th bed -50% |
| le-tonnare | Le Tonnare di Stintino 4* | Stintino | AHO ~32 km | FB | 3rd bed free, 4th bed -50%, plus €7/person/day tessera club |
| mclub-golfo | MClub del Golfo 4* | Platamona, Sorso | AHO ~25 km | AI | 3rd bed free (€50/night forfait from 31.07 to 21.08), 4th bed (a bunk) -50% |

**Rejected:**
- **Cefalù** (Santa Lucia, Cefalù Sporting Club): about 83 km straight-line from PMO and 100–115 km by road, which is over the 80 km route limit. Santa Lucia's beach is also down about 100 steps, and the Sporting Club is 400 m from the sea.
- **Santa Sabina and Riva Marina** (Carovigno): about 95–110 km from BRI.
- **Marina Manna** (Valledoria): 75 km from AHO.
- **Mondello and the Domitian coast north of Baia Domizia**: no sheet found.

## Config block (add to config.toml)

```toml
[sources.it_hotels]
# Italian family resorts near BRI / NAP / AHO: hotel-only ("solo soggiorno") 2+2 prices from the
# resort price sheets (PDF) that Radio Radio Viaggi publishes. robots.txt disallows only /wp-admin/.
# `discover` looks for a newer sheet with one /wp-json/wp/v2/media?search= call per hotel; without
# one, `pdf` (last summer's) is read, its dates are moved to the coming summer and the offers say
# "2026 price list". Every `check` phrase must still be in the sheet, otherwise the hotel is skipped.
# Needs pypdf (pip install pypdf).
enabled = true
discover = true
season = "summer"
country = "IT"
nights = 7
kid_ages = [3, 13]           # the sheets' 3rd/4th bed band ("3/13 anni", age not yet reached)

[[sources.it_hotels.pages]]
key = "porto-giardino"
name = "Porto Giardino"
stars = 4
file_key = "puglia-porto-giardino"
search = "porto giardino"
pdf = "https://viaggi.radioradio.it/wp-content/uploads/2026/01/2026-puglia-porto-giardino-IN4.pdf"
area = "Capitolo, Monopoli (Apulia)"
lat = 40.905
lng = 17.355
months = [6, 7, 8, 9]
unit = "night"               # per person per night; a 7-night stay is priced night by night
columns = ["price", "was", "kid3", "kid4", "teen"]
board = "AI"
room = "Family room (2 areas), twins in 3rd/4th bed"
notes = "Sandy lido ~100 m (cove 50 m). Mini club 05.07–30.08. Bari airport ~50 km."
[sources.it_hotels.pages.family]
sand_beach = true
beach_m = 100
family_room = true
kids_club = true

[[sources.it_hotels.pages]]
key = "baia-domizia"
name = "Baia Domizia Resort"
stars = 4
file_key = "campania-baia-domizia"
search = "baia domizia"
pdf = "https://viaggi.radioradio.it/wp-content/uploads/2026/01/2026-campania-baia-domizia-IN4-1.pdf"
area = "Baia Domizia (Campania)"
lat = 41.215
lng = 13.790
months = [6, 7, 8, 9]
unit = "night"
columns = ["price", "was", "fb", "fb_was", "kid34"]
board = "HB"
room = "standard room, twins in 3rd/4th bed"
notes = "Resort on its own sandy beach (Blue Flag). Naples airport ~50 min. Stays preferably Saturday; 9–23.08 min 7 nights."
[sources.it_hotels.pages.family]
sand_beach = true
beachfront = true
half_board = true

[[sources.it_hotels.pages]]
key = "le-tonnare"
name = "Le Tonnare di Stintino Beach Resort"
stars = 4
file_key = "sardegna-le-tonnare"
search = "tonnare"
pdf = "https://viaggi.radioradio.it/wp-content/uploads/2026/01/2026-sardegna-le-tonnare-IN4.pdf"
area = "Stintino (Sardinia)"
lat = 40.917
lng = 8.225
months = [7, 8, 9]           # AHO flights mid-July to mid-September
unit = "stay"                # per person per 7 nights
columns = ["ship", "price", "was", "kid3", "teen"]
board = "FB"
room = "standard room, twins in 3rd/4th bed"
notes = "Beach in front (sand and pebbles); La Pelosa a few km. Mini club 3–12 (out of nappies). Alghero airport 48 km."
[sources.it_hotels.pages.family]
beachfront = true
beach_type = "mixed"
kids_club = true
[[sources.it_hotels.pages.kid_rules]]
bed = "kid4"
reduction = 0.5
check = "rid. 4°/5° letto 3/18 anni(*) 50%"
[[sources.it_hotels.pages.extras]]
per = "person_night"
eur = 7
min_age = 3
from = "06-12"
to = "09-11"
check = "obbligatoria dal 12/06 al 11/09 € 7 a persona al giorno dai 3 anni"

[[sources.it_hotels.pages]]
key = "mclub-golfo"
name = "MClub del Golfo"
stars = 4
file_key = "sardegna-mclub-del-golfo"
search = "mclub golfo"
pdf = "https://viaggi.radioradio.it/wp-content/uploads/2026/01/2026-sardegna-mclub-del-golfo-IN4.pdf"
area = "Platamona, Sorso (Sardinia)"
lat = 40.810
lng = 8.470
months = [7, 8, 9]
unit = "stay"
columns = ["ship", "price", "was", "kid3"]
board = "AI"
room = "standard room, twins in 3rd bed + 4th bed (bunk)"
notes = "White-sand beach a few metres away. Tessera club included. 4th bed is a bunk. Sorso tourist tax €2.50/adult/day (kids under 12 exempt). Alghero airport ~40 km."
[sources.it_hotels.pages.family]
sand_beach = true
beach_m = 50
[[sources.it_hotels.pages.kid_rules]]
bed = "kid4"
reduction = 0.5
check = "4° letto (**)3/13 anni 50%"
[[sources.it_hotels.pages.extras]]
per = "kid_night"
eur = 50
from = "07-31"
to = "08-20"
check = "quota forfait obbligatoria di € 50 a notte"
```

## Live check (2026-11-28)

- **Requests:** about 35 live requests in total. That covers development (4 robots.txt files, 6 PDFs, the sitemaps, 2 category pages, 2 dead offer pages, 2 media searches) and one full module run of 8 requests (4 media searches + 4 PDFs, 0 blocked, 0 errors).
- **2026 sheets:** all four are still downloadable. That run, with the block above and `today` = 2026-11-28, gave **37 priced 2+2 offers, 0 rejected by `validate`**:
  - Porto Giardino: 10 offers
  - Baia Domizia: 8 offers
  - Le Tonnare: 10 offers
  - MClub del Golfo: 9 offers
- **Example, Le Tonnare 17.07, 7 nights FB:** 2 × €917 + 0 + €458.50 + €196 tessera = **€2,488.50**, against €2,821 at the official list price.
- **2027 sheets:** not published yet. The summer 2026 offer pages have been taken down (they now return 404), and the region pages are empty off-season. The 2026 sheets were uploaded in January 2026, so the 2027 sheets should appear around January–April 2027. Discovery picks them up automatically, as `2027-<file_key>-IN4.pdf`.

## Known limits

- **Every offer is a last-year price until the 2027 sheets appear.** The room says "2026 price list" and the hotel notes say so too. `was_eur` is the hotel's list price on the same sheet, so the "discount" is the agency's price against that list, not a sale.
- **Guest ratings** (4.3 Google / 8.2 Booking) are not on the sheets. All four hotels need a rating check before they are trusted. `ratings` is left empty, so the rating check stays "unknown".
- **Tourist tax and optional supplements are not included.** That covers sea view, front-row beach and cots. "Infant 0/3" cot rules don't apply to 3-year-olds.
- **Rules not modelled:** early-booking discounts ("prenota prima", 5–10% before 31.03/30.04) and weekday rules (Baia Domizia charges +20% for Friday or Sunday stays).
- **Layout dependence:** the sheets come from several tour operators, so each hotel needs its `columns` set by hand. A changed layout (a different cell count) gives 0 rows, which is logged, not mispriced.
- **pypdf is not in requirements.txt.** Without it the source logs a warning and is skipped.

## Needs the integrator

1. Add `pypdf>=4` to `requirements.txt`. It is installed on the PC already (6.x).
2. Import `it_hotels` in `trips/run.py` and add it to `AUTO_SOURCES`.
3. Optionally add `PoliteSession.get_bytes()`. `it_hotels._pdf_bytes` reuses the session's own robots, delay and stats internals to fetch bytes, because `get()` returns decoded text.
4. Check the four hotels' Google and Booking ratings, and drop any below the rule.
5. In about February 2027, check that discovery found the 2027 sheets. If a `check` phrase warns, re-read the sheet and update `kid_rules`, `extras` or `columns`.
