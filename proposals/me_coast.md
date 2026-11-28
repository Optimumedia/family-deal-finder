# me_coast: Montenegro coast hotels' 2027 price lists via Plan A Travel

Agent: `me_coast` · checked 2026-11-28

## What the source is
**Plan A Travel** (planatravel.rs) is a licensed Serbian agency (OTP 222/2021, cat. A) in Belgrade and Velika Plana. It sells Montenegrin hotels "sopstveni prevoz": you drive there and pay for the stay only.

Each hotel page carries the hotel's **2027 price list as a plain HTML table**, for example "Cenovnik br.1, 05.11.2026.". The table has:
- periods
- a price per person per night (or per person for a fixed 9-night stay)
- board codes PP/ND/AL
- room capacity

Under the table, the page writes out the **child reductions for two adults** and the board supplements.

Area pages put a **"leto 2027" sticker** on the hotels whose new list is already published. The module reads only those hotels, so a run costs about one request per area plus one per priced hotel (about 15 requests today).

- Module: `trips/sources/me_coast.py`
- Tests: `tests/test_me_coast.py` (25 tests, all pass, no network)
- Fixtures: `tests/fixtures/me_coast_*.html`: 3 area lists and 8 hotel pages, including a page with no list yet and a pebble-beach page

### How 2+2 prices are worked out
A 2+2 price is built only from rules the page states:
- "Dvoje dece … (dele ležaj) u 1/2+1 sobi - 50%" (two kids share the extra bed in the 1/2+1 room, 50% off)
- "koeficjent obračuna je 2,8" (2+2 is billed as 2.8 persons)
- "u sopstvenom plaća 70%" (a child in its own bed pays 70%)
- early-booking "dvoje dece … GRATIS" (two kids free with early booking)
- a room for 4 or more people plus "Deca od 2 do 12 - 50%" (kids aged 2–12 get 50% off)

Rules for one adult, and rules for the 3rd, 4th or 5th person, are ignored. When several rules fit, the dearer one is used.

A B&B (ND) row plus the stated half-board supplement becomes an HB total, with kids at the stated share of the supplement. When no 2+2 rule fits, the cheapest room gives a 2+0 offer.

Early booking ("Rani booking -15% do 31.12.2026, popust uključen u cenu", i.e. 15% off until that date, already in the price) fills `was_eur`, `discount_label` and `valid_until`.

## robots.txt (https://www.planatravel.rs/robots.txt, 2026-11-28)
```
User-agent: *
Allow: /*.js*  (… css/png/jpg/gif/webp)
Disallow: /administrator/
Disallow: /api/
Disallow: /bin/
Disallow: /cache/
Disallow: /cli/
Disallow: /components/
Disallow: /images/thumbnails/
Disallow: /includes/
… /installation/ /language/ /layouts/ /libraries/ /logs/ /media/ /modules/ /plugins/ /tmp/
```
These are only Joomla system folders. The `/letovanje/crna-gora/...` pages are allowed, and the PoliteSession check passes. There is no bot wall or Content-Signal.

## TOML block for config.toml
```toml
[sources.me_coast]
# planatravel.rs (Plan A Travel) — hotels' own 2027 price lists, own transport. robots.txt allows these pages.
# Only hotels with the "leto 2027" sticker on the area page are read (1 request per area + 1 per priced hotel).
enabled = true
only_stickered = true

[[sources.me_coast.pages]]
# ~4h45 via Prizren–Kukës–Shkodër–Sukobin (transit only, 3 borders). Velika plaža: sand.
url = "https://www.planatravel.rs/letovanje/crna-gora/ulcinjska-rivijera/ulcinj.html"
season = "summer"
area = "Ulcinj / Velika Plaža, Montenegro"
country = "ME"
lat = 41.90
lng = 19.27
nights = 7
check_ins = ["2027-06-20", "2027-07-04"]
sand_beach = true

[[sources.me_coast.pages]]
# ~5h05 (Ulcinj → Bar coast road). Mixed sand/pebble: left to the hotel page.
url = "https://www.planatravel.rs/letovanje/crna-gora/barska-rivijera/dobre-vode.html"
season = "summer"
area = "Dobre Vode, Montenegro"
country = "ME"
lat = 42.05
lng = 19.13
nights = 7
check_ins = ["2027-06-20", "2027-07-04"]

[[sources.me_coast.pages]]
# ~5h15. Sutomore: sand + fine gravel; the page decides (Sato says sandy, Korali says pebble).
url = "https://www.planatravel.rs/letovanje/crna-gora/barska-rivijera/sutomore.html"
season = "summer"
area = "Sutomore, Montenegro"
country = "ME"
lat = 42.143
lng = 19.047
nights = 7
check_ins = ["2027-06-20", "2027-07-04"]

[[sources.me_coast.pages]]
# ~5h10. Bar town beaches are mostly pebble (no sand_beach default).
url = "https://www.planatravel.rs/letovanje/crna-gora/barska-rivijera/bar.html"
season = "summer"
area = "Bar, Montenegro"
country = "ME"
lat = 42.10
lng = 19.09
nights = 7
check_ins = ["2027-06-20", "2027-07-04"]

[[sources.me_coast.pages]]
# ~5h30 (borderline). Petrovac: fine reddish gravel/sand mix; Lučice cove is sandy.
url = "https://www.planatravel.rs/letovanje/crna-gora/budvanska-rivijera/petrovac.html"
season = "summer"
area = "Petrovac, Montenegro"
country = "ME"
lat = 42.205
lng = 18.943
nights = 7
check_ins = ["2027-06-20", "2027-07-04"]

[[sources.me_coast.pages]]
# ~5h45 (edge of the tolerance). Bečići beach: hotels describe it as sandy (fine sand/gravel).
url = "https://www.planatravel.rs/letovanje/crna-gora/budvanska-rivijera/becici.html"
season = "summer"
area = "Bečići, Montenegro"
country = "ME"
lat = 42.282
lng = 18.870
nights = 7
check_ins = ["2027-06-20", "2027-07-04"]
sand_beach = true

[[sources.me_coast.pages]]
url = "https://www.planatravel.rs/letovanje/crna-gora/budvanska-rivijera/rafailovici.html"
season = "summer"
area = "Rafailovići, Montenegro"
country = "ME"
lat = 42.278
lng = 18.877
nights = 7
check_ins = ["2027-06-20", "2027-07-04"]
sand_beach = true

[[sources.me_coast.pages]]
# second page of Rafailovići cards (10 per page)
url = "https://www.planatravel.rs/letovanje/crna-gora/budvanska-rivijera/rafailovici.html?start=10"
season = "summer"
area = "Rafailovići, Montenegro"
country = "ME"
lat = 42.278
lng = 18.877
nights = 7
check_ins = ["2027-06-20", "2027-07-04"]
sand_beach = true
```
Ada Bojana is left out on purpose: its only hotel is the naturist village "NN Ada Bojana". Optional page keys are `exclude = ["slug"]`, `max_hotels` (default 15), and `hotel = true` (the url is a single hotel page).

## Live check (2026-11-28, about 40 requests in total including probing, ≥6 s apart)
**Six hotels have a published 2027 list today, and all are in Bečići and Petrovac. They give 6 priced offers, 5 of them real 2+2.** Prices are for check-in 4 July 2027, 7 nights, twins aged 3:

| Hotel | Board | Occupancy | Price | How the kids are priced |
|---|---|---|---|---|
| Splendid 5*, Bečići | HB (B&B + supplement) | 2+2 | €2,597 (was €2,926, −15% EB until 31.12.2026) | kids free on B&B, 50% of the HB supplement |
| Vile Oliva 4*, Petrovac | AI | 2+2 | €1,823 (−10% EB until 28.02.2027) | coefficient 2.8 |
| Castellastva 4*, Petrovac | HB | 2+2 | €1,974 | 02 App, kids share the extra bed at 50% |
| Palas 4*, Petrovac (beachfront) | HB | 2+2 | €1,890 | 1/2+1 room, kids share the extra bed at 50% |
| Hotel Bečići 2*, Bečići | HB, fixed 9 nights from 26.06 | 2+2 | €1,598 | own beds at 70% |
| Montenegro Beach Resort 4*, Bečići | HB | 2+0 | €1,554 (−15% EB) | rooms sleep only 2+1 |

Ulcinj (3 hotels), Sutomore (2), Bar (2), Dobre Vode (2) and Rafailovići page 1 (10) have **no 2027 list yet**: no sticker, and the 9 such pages I opened had no table. They cost only their area request until the stickers appear, probably over the winter as the lists come out.

## Known limits
- **Only Bečići and Petrovac are priced today.** These are the farthest areas (OSRM through Albania is roughly 5h30–5h45, plus the border buffer). The sandy, near areas (Ulcinj, Velika plaža) have no list yet. Expect the offer count to grow from Jan to Mar 2027.
- **Small catalogue:** about 37 Montenegro hotels across these areas. Ulcinj has only Azul Beach (already covered by Olympic and Travelland), Vila Elkom and Apartmani Elysium.
- **Child-rule parsing is regex-based on Serbian text.** It errs high: it takes the dearest matching rule, and kids pay the adult price in 4+ rooms with no rule. Odd wording drops to 2+0. Position rules ("četvrta osoba GRATIS", a free 4th person) are not used, so some 2+2 prices could be lower than shown.
- **Rooms that sleep only 2+1 give 2+0.** The exception is when the page states a two-kids rule (Splendid's early booking).
- **Tourist tax is extra**, about €0.5–1 per child per day. Prices are "informativne" (indicative), paid in RSD at the NBS rate.
- **Sand is read per hotel from the text:** "peščan" means sand and "šljunkovit" means pebble. A sandy beach mentioned 300 m or more away is ignored. A page's `sand_beach` fills the gap only when the hotel text is silent.

## Checked and not viable
- **belvi.rs:** robots allows it, but the 2027 Montenegro pages carry no prices in the HTML. They come from `/api/`, which is disallowed.
- **timetravel.rs and dreamland.travel:** SEO aggregator pages with only "od 488€" ("from €488") teasers. Dreamland's robots.txt uses Content-Signal.
- **lordtravel.rs and forzatravel.rs:** found, but not opened (request budget). They are 2026 first-minute pages, and Forza uses session-style shop URLs.
- **Hotels' own "cjenovnik 2027" pages:** a search found none published yet.
- **Not retried:** filiptravel.rs (403 in the al_me_coast check) and Kontiki and Big Blue (no Montenegro 2027 price pages turned up in search).

## For the integrator
1. **Drive times:** the router takes Skopje → Prizren → Kukës → Shkodër (Albania only as transit, 3 borders). The single 30-minute `border_buffer_minutes` probably underestimates this. A per-page `borders = 3` would help (same point as in al_me_coast.md).
2. **`check_ins` list:** the module honours a `check_ins` list, like gr_hotel_prices. Fixed-stay tables snap to the departure that contains the date.
3. **A 2+2 "kids free" deal that expires:** Splendid's 2+2 price depends on its early booking ending 31.12.2026. After that date the offer turns 2+0 by itself.
