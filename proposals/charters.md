# charters: summer 2027 beach packages with a direct flight from Skopje

Module `trips/sources/charters.py`. Tests are in `tests/test_charters.py`, with fixtures `tests/fixtures/charters_*.html` saved on 25.11.2026. All 8 tests pass.

## 1. Direct flights from SKP: what exists

Neither the CAA nor TAV has published a timetable for summer 2027 yet. The CAA summer 2026 timetable lists **scheduled** flights only (caa.gov.mk, `Time-Table-Summer-2026-1.pdf`; I extracted its text). TAV's 2026 press release says "7 airlines … 24 charter destinations" but doesn't name them.

| Destination | Operator / flight (summer 2026) | Days, period | 2027 evidence |
|---|---|---|---|
| **Antalya** (Belek, Side, Lara, Kemer, Alanya) | SunExpress XQ630/631 | daily, 29.03–24.10.2026 | Savana sells SKP packages with departures from **02.06.2027 to 07.09.2027**. A route site shows AYT schedules filed until Aug 2027. |
| Antalya | Pegasus PC5547/5548 | Mon, Wed, Fri, Sun, 22.03–24.10.2026 | as above |
| **Izmir** (gateway for Kusadasi, Cesme) | Pegasus PC1571/1572 and SunExpress XQ896/897 | daily, 29.03–24.10.2026 | Savana sells "by plane from Skopje" Kusadasi packages with **weekly departures from 02.04.2027** |
| **Bodrum** | AJet VF1213/1214 | weekly (day 3), 01.07–22.10.2026 | seasonal. No 2027 schedule yet. |
| Larnaca (Cyprus) | Wizz W6 4767/4768 | Mon, Fri, 30.03–23.10.2026 | Savana has a Larnaca destination |
| Palermo / Alghero (Italian islands) | Wizz W6 4775/4776 and W6 4777/4778 | 15.07–11.09 and 18.07–12.09.2026 | outside this task |
| **Hurghada** | Air Cairo charter. A route site lists its last flight on 21.10.2025. | — | **Not confirmed for 2027.** It's not in the 2026 timetable, and Savana's Egypt page has no packages. |
| Sharm el-Sheikh, Crete (Heraklion/Chania), Rhodes, Kos, Zakynthos, Corfu, Monastir, Dalaman, Gazipasa | Savana's flight-ticket sitemap has SKP route pages for these, but they are fare-search pages and may be connecting flights. Aegean flew SKP–Corfu in 2024, but it isn't in the 2026 timetable. | — | **Not confirmed.** Re-check the CAA summer 2027 PDF when it appears (usually in March). |

**Conclusion:** for 2027, the Antalya region and the Izmir/Kusadasi coast are certain. Bodrum is likely (an AJet scheduled route). Egypt and the Greek islands are unconfirmed.

## 2. Source: Savana Travel (online.savana.travel)

Savana Travel is a Skopje agency (+389 2 5122 333). It runs on the Travitude/"acqua" booking platform. Its listing pages are **packages with the flight from Skopje included** ("Пакет аранжман со авион од Skopje"). Each card gives:

- hotel, stars and photo
- the "from" price for **2 adults** for the whole stay, with the flight
- the old price, when the offer is discounted
- a price for each stay length (6 and 7 nights)

The page's map script gives each hotel's lat/lng. The departure-date dropdown gives the season window.

robots.txt (`https://www.online.savana.travel/robots.txt`) allows everything for any user agent, apart from these lines:
```
User-agent: *
Content-Signal: search=yes,ai-train=no,use=reference
Allow: /
...
User-agent: *
Disallow: /admin
Disallow: /catalog
Disallow: /*print=yes
Disallow: /*get_search_rooms
Disallow: /packages_explorer
Disallow: /packages/explorer
Disallow: /*change_language*
```
We read only `/vacations/.../from-skopje/vacations/with-plane/` and its `/2/` page. We never use the search engine (`/packages/results/`). The site is behind Cloudflare, but there was no challenge for our user agent. `PoliteSession` stops if one appears. We store facts only and don't use the content for AI training.

Every hotel is stored with `direct_flight_skp = True`, `border = False` and `kind = "hotel"`. Ids are `sv-<slug>`.

## TOML block to add to config.toml

```toml
[sources.charters]
# Savana Travel (Skopje): flight-from-Skopje + hotel packages. "From" price for 2 adults
# for the whole stay (flight included); board and exact date are not on the card.
enabled = true
max_list_pages = 3          # 20 cards per page

[[sources.charters.pages]]
url = "https://www.online.savana.travel/vacations/turkey/antalya/from-skopje/vacations/with-plane/"
season = "summer"
area = "Antalya region, Turkey"
region = "Antalya region, Turkey"   # area shown as "<town from slug>, <region>"
country = "TR"
lat = 36.88
lng = 30.70
nights = 7
check_in = "2027-06-20"
direct_flight_skp = true

[[sources.charters.pages]]
url = "https://www.online.savana.travel/vacations/turkey/kusadasi/from-skopje/vacations/with-plane/"
season = "summer"
area = "Kusadasi, Turkey"
region = "Aegean coast, Turkey"
country = "TR"
lat = 37.86
lng = 27.26
nights = 7
check_in = "2027-06-20"
direct_flight_skp = true
```

## Live check (25.11.2026)

The check used 4 list pages and the robots.txt. It found **47 priced offers**, all for 2 adults with the flight included:

- **Antalya region: 22.** 17 in Alanya, 4 in Kemer and 1 in Side. Prices run from €812 (6 nights, 3★ Kemer) to €1,324, and all 22 carry an old price (13–25% off).
- **Kusadasi: 25.** From €620 for 7 nights, with no discounts.

## Known limits

- **Board is not on the listing**, so it is stored as `"?"`. Most Antalya packages are all-inclusive, which counts as breakfast + dinner, but the card doesn't say so. The engine will show "ask". The board is only available through the site's search engine, which we don't call.
- **Price date:** the "from" price isn't tied to a date. The check-in is the configured default, or the first departure date the page offers if that is later. The room text says "dates on request".
- **Nights:** this is the stay length the "from" price belongs to: 6 for Antalya, 7 for Kusadasi. The 7-night price is also on the card (`stays` in the parsed card) if the integrator prefers it.
- **Price for 2 adults only** (`occupancy = "2+0"`). There's no price for the kids, though infants usually fly for a small fee.
- **No Belek or Lara hotels** are in Savana's Antalya list right now. Mostly mid-range Alanya and Kemer hotels are listed.
- **Kusadasi:** the arrival airport isn't stated. It's probably Izmir, which has daily direct flights from SKP.
- **Two Kusadasi slugs** don't follow the "-N-stars-town-turkey" pattern. Those hotels fall back to the page area.
- Some cards point their photo at a bare IP:8080 file server. Those photos are dropped (`image = None`).
- **Not reachable here:** Egypt, Crete and other Greek islands. Savana has no 2027 packages for them, and Fibula's API is excluded.

## For the integrator

- Add `charters` to `AUTO_SOURCES` in `trips/run.py`.
- The page key `region` is new. It's optional and falls back to `area`.
- Hotels carry `kind = "hotel"`.
- Re-check the CAA summer 2027 timetable in March 2027. If Hurghada, Bodrum or Crete charters appear, add Savana pages when its `/vacations/egypt/` or `/vacations/greece/` pages show "with-plane from-skopje" listings. The same parser should work, since it's the same platform.
