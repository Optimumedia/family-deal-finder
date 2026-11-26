# flight_hotels: direct-flight routes from SKP and hotel-only summer prices

Agent `flight_hotels`, 26.11.2026. The new rule: in summer a package isn't needed. A hotel-only price counts if a **direct flight from SKP** lands near the hotel, and the parents book that flight themselves.

What I built:
1. **`trips/flights.py`** turns a config list of SKP direct routes into `direct_flight_skp = True` plus `flight = {airport, transfer_km, months, …}` on every summer hotel that's close enough to a route's airport, in a month the route flies. Tests are in `tests/test_flights.py` (10).
2. **`trips/sources/flight_hotels.py`** is Relaxo.bg hotel-only prices for the Turkish coast. Each price is a **real 2+2 total for 7 nights**, with the twins' ages sent. Tests are in `tests/test_flight_hotels.py` (14), with fixtures in `tests/fixtures/flight_hotels_*.html` (6 pages).

All 24 tests pass, and neither module needs network access.

---

## Part 1: `trips/flights.py`

`apply(hotels, cfg, offers=None) -> int` changes hotels in place and returns how many it marked.

- **Input:** `hotels` is the `{id: hotel}` dict from `db.hotels()`. A list also works.
- **Trip months:** these are the hotel's offer check-in months when `offers` is given (`hotel_id` or `hotel` + `check_in`). Otherwise `trip_months` is used.
- **Distance:** a hotel is marked when a route's airport is within that route's `max_transfer_km` (straight line; the default is 90 km). The route must also fly in at least one trip month. The nearest airport wins.
- **Confidence:** routes marked `confidence = "possible"` are ignored unless `min_confidence = "possible"`.
- **Seasons:** only the listed `seasons` are touched (default `["summer"]`).
- **Never unmarks:** a hotel a source already flagged as direct (for example a Savana flight package) stays direct.
- **Distance is straight-line.** A road transfer is about 1.2–1.4× longer. Alanya is about 115 km straight-line from AYT, so AYT gets 130.

### Proposed `trips/run.py` diff

`build()` runs it before scoring, so `score.rate` sees the flag. The dashboard item also carries the flight note.

```diff
-from . import conditions, db, dedupe, digest, enrich, family_prices, geo, geocode, health, ratings, score, validate
+from . import conditions, db, dedupe, digest, enrich, family_prices, flights, geo, geocode, health, ratings, score, validate
 from .http import PoliteSession
-from .sources import al_me_coast, bg_more, bgski, charters, gr_apartments, hotel_direct, kopaonik, manual, micazu, mk_agencies, oliverstravels, olympic, rentals, rs_agencies, travelland
+from .sources import al_me_coast, bg_more, bgski, charters, flight_hotels, gr_apartments, hotel_direct, kopaonik, manual, micazu, mk_agencies, oliverstravels, olympic, rentals, rs_agencies, travelland

 # Sources that find hotels/villas and prices (agencies, villa sites, owner rentals).
-AUTO_SOURCES = (travelland, olympic, mk_agencies, bgski, charters, kopaonik, rs_agencies, al_me_coast, bg_more, gr_apartments, oliverstravels, rentals, micazu)
+AUTO_SOURCES = (travelland, olympic, mk_agencies, bgski, charters, kopaonik, rs_agencies, al_me_coast, bg_more, gr_apartments, oliverstravels, rentals, micazu, flight_hotels)
@@ def build(con, cfg: dict, today: date, offline: bool = False) -> tuple[list[dict], list[dict]]:
     hotels = db.hotels(con)
     geocode.apply(hotels, cfg, today, offline=offline)   # hotel-level pins (off unless [geocode] enabled)
     ratings.apply(hotels, cfg, today, offline=offline)   # Google rating via the official Places API (needs a key)
+    offers = db.offers(con)
+    flights.apply(hotels, cfg, offers)                   # direct SKP flight to an airport near the hotel, in the trip month
     home = (cfg["family"]["home_lat"], cfg["family"]["home_lng"])
@@
     estimated = set() if offline else set(geo.last_estimated)
-    offers = db.offers(con)
     lim = validate.limits(cfg)
@@
             "season": h["season"], "lat": h.get("lat"), "lng": h.get("lng"), "notes": h.get("notes"),
+            "flight": h.get("flight"),          # {"airport", "name", "transfer_km", "months", ...} or None
             "drive_estimate": h["id"] in estimated,   # straight-line guess: the router was down this run
```

Two points for the integrator:

- **Per-offer month:** `apply` works per hotel, so a hotel with one June and one July offer near Bodrum (July–October) is marked direct for both. If that matters, pass a per-offer check to `score.rate` later. That's a small change, but it touches `score.py`, so I didn't make it.
- **Drive-time lookups:** marked hotels still get one (cached). That's harmless, since `score` treats direct as reachable whatever the drive time is.

### `[flights]` block for config.toml

```toml
[flights]
# Direct flights from Skopje (SKP). A summer hotel within max_transfer_km (straight line) of a
# route's airport, in a month the route flies, counts as "direct flight" (hotel-only is fine:
# the parents book the flight). Routes from the CAA summer-2026 timetable + 2027 agency programmes.
# Re-check the CAA "Time-Table-Summer-2027" PDF when it appears (usually March).
enabled = true
max_transfer_km = 90            # default; per-route overrides below
seasons = ["summer"]
trip_months = [6, 7, 8, 9]      # for hotels without offer dates
min_confidence = "likely"       # confirmed | likely | possible

[[flights.routes]]
airport = "AYT"
name = "Antalya"
lat = 36.900
lng = 30.793
months = [4, 5, 6, 7, 8, 9, 10]
frequency = "daily (SunExpress XQ630/631; Pegasus 4/week)"
max_transfer_km = 130           # Lara ~15, Belek ~30, Side ~65, Alanya ~115 km
confidence = "confirmed"        # Savana sells SKP flight packages 02.06–07.09.2027
evidence = "https://www.online.savana.travel/vacations/turkey/antalya/from-skopje/vacations/with-plane/"

[[flights.routes]]
airport = "ADB"
name = "Izmir"
lat = 38.292
lng = 27.157
months = [4, 5, 6, 7, 8, 9, 10]
frequency = "daily (Pegasus PC1571/1572, SunExpress XQ896/897)"
max_transfer_km = 90            # Kusadasi ~50, Cesme ~75, Ozdere ~45 km
confidence = "confirmed"        # Savana Kusadasi "by plane from Skopje" weekly from 02.04.2027
evidence = "https://www.online.savana.travel/vacations/turkey/kusadasi/from-skopje/vacations/with-plane/"

[[flights.routes]]
airport = "BJV"
name = "Bodrum"
lat = 37.250
lng = 27.664
months = [7, 8, 9, 10]
frequency = "weekly, Wednesday (AJet VF1213/1214, 01.07–22.10.2026)"
max_transfer_km = 60            # Bodrum town ~30, Bitez ~35, Turgutreis ~50 km
confidence = "likely"           # scheduled 2026, no 2027 filing yet
evidence = "https://www.caa.gov.mk/wp-content/uploads/2026/05/Time-Table-Summer-2026.pdf"

[[flights.routes]]
airport = "NAP"
name = "Naples"
lat = 40.886
lng = 14.291
months = [4, 5, 6, 7, 8, 9, 10]
frequency = "3/week, Mon/Wed/Fri (Wizz W6 4817/4818)"
max_transfer_km = 70            # Sorrento ~35, Maiori ~40 km
confidence = "confirmed"        # Atlantik Turs sells 14.07–01.09.2027 "direct flight from Skopje"
evidence = "https://atlantikturs.com/leto-2027"

[[flights.routes]]
airport = "BRI"
name = "Bari"
lat = 41.139
lng = 16.761
months = [4, 5, 6, 7, 8, 9, 10]
frequency = "3/week, Tue/Thu/Sat (Wizz W6 4811/4812)"
max_transfer_km = 80            # Polignano ~45, Monopoli ~55, Torre Canne ~70 km
confidence = "likely"
evidence = "https://www.caa.gov.mk/wp-content/uploads/2026/05/Time-Table-Summer-2026.pdf"

[[flights.routes]]
airport = "BCN"
name = "Barcelona"
lat = 41.297
lng = 2.078
months = [4, 5, 6, 7, 8, 9, 10]
frequency = "3/week, Tue/Thu/Sat (Wizz W6 4737/4738)"
max_transfer_km = 100           # Maresme ~40-60, Salou ~85, Cambrils ~95 km
confidence = "likely"
evidence = "https://www.caa.gov.mk/wp-content/uploads/2026/05/Time-Table-Summer-2026.pdf"

[[flights.routes]]
airport = "LCA"
name = "Larnaca"
lat = 34.875
lng = 33.625
months = [4, 5, 6, 7, 8, 9, 10]
frequency = "2/week, Mon/Fri (Wizz W6 4767/4768)"
max_transfer_km = 70            # Ayia Napa ~40, Protaras ~50 km
confidence = "likely"
evidence = "https://www.caa.gov.mk/wp-content/uploads/2026/05/Time-Table-Summer-2026.pdf"

[[flights.routes]]
airport = "MLA"
name = "Malta"
lat = 35.857
lng = 14.477
months = [4, 5, 6, 7, 8, 9, 10]
frequency = "3/week, Mon/Wed/Fri (Wizz W6 4765/4766)"
max_transfer_km = 40            # whole island; Mellieha ~25 km
confidence = "likely"
evidence = "https://www.caa.gov.mk/wp-content/uploads/2026/05/Time-Table-Summer-2026.pdf"

[[flights.routes]]
airport = "PMO"
name = "Palermo"
lat = 38.176
lng = 13.091
months = [7, 8, 9]              # 15.07–11.09 only
frequency = "seasonal, mid-July to mid-September (Wizz W6 4775/4776)"
max_transfer_km = 80
confidence = "likely"
evidence = "https://www.caa.gov.mk/wp-content/uploads/2026/05/Time-Table-Summer-2026.pdf"

[[flights.routes]]
airport = "AHO"
name = "Alghero"
lat = 40.632
lng = 8.291
months = [7, 8, 9]              # 18.07–12.09 only
frequency = "seasonal, mid-July to mid-September (Wizz W6 4777/4778)"
max_transfer_km = 60            # Alghero Lido ~10, Stintino ~45 km
confidence = "likely"
evidence = "https://www.caa.gov.mk/wp-content/uploads/2026/05/Time-Table-Summer-2026.pdf"
```

Sources for the routes are `proposals/flights2.md` and `proposals/charters.md`. The CAA PDF lists only scheduled flights, and summer 2027 timetables aren't published yet.

The months for Palermo and Alghero include July, but those flights start only mid-July. A hotel with a 1–14 July offer will therefore be marked anyway, so check the date by hand.

---

## Part 2: `trips/sources/flight_hotels.py` (Relaxo.bg)

### The source

**Relaxo.bg** is a licensed Sofia tour operator (РК-01-8418, per its own JSON-LD). Its "Хотели в Турция" pages sell **rooms with own transport** ("Собствен транспорт"), which means hotel only, with no flight or bus. Bulgarians drive or fly there themselves. Each hotel page has a plain **GET search form** (`/oferta/<slug>/rezultati?date_from&date_to&rooms[0][adults]&rooms[0][children]&rooms[0][child_ages]`). It answers with server-rendered HTML: one row per room type, giving the **total for the stay and the whole party**, board, availability, the price without early booking, and the current promotion.

So **real 2+2 family totals** are available. For example, Palm Wings Ephesus (Kusadasi, sandy and beachfront) comes to €2,335.76 for 7 nights UAI for 2 adults + 2 children aged 3. That's down from €3,461.54 (Black Friday −32%, until 28.11). The page also states the child rule: "1-во дете (0–11 г.) БЕЗПЛАТНО" (first child aged 0–11 free).

### robots.txt (`https://relaxo.bg/robots.txt`, 26.11.2026)

```
User-agent: *
Allow: /
Disallow: /locale/
Disallow: /go/
```

The Googlebot block also has `Disallow: /ai/`, and the file explicitly allows AI agents (ClaudeBot and others) under the same rules. Nothing we use is disallowed. That covers the list pages `/oferti-za/<resort>`, the hotel pages `/oferta/<slug>` and the hotel's own result page `/oferta/<slug>/rezultati?…`. We never call `/go/` (their ad and outbound redirects), the checkout (POST) or any XHR.

All requests go through `PoliteSession`. There was no bot wall: Cloudflare Turnstile appears only on the newsletter form. We store facts only, with hotlinked photos.

### What a run fetches

- **Per resort:** 1 list page. From it, the `max_hotels` own-transport cards with the cheapest "from" price are picked, or an explicit `hotels = [slugs]` list.
- **Per picked hotel:** 1 detail page and 1 result page per check-in date.
  - **Detail page:** Google-Maps pin, sand / pebble / mixed beach, beachfront, mini club, kids' pool, Relaxo rating, bookable window, promotion end.
  - **Result page:** the 2+2 price. The cheapest available room is kept.
- **Twins' ages:** taken from `score.kids_age_on(cfg, check_in)`, or from `child_ages` if set.
- **Occupancy:** an offer is "2+2" only if the result header echoes "2 възрастни + 2 деца". Otherwise it's "2+0" and links to the hotel page.
- **Hotel fields:** `id = "rx-<slug>"`, `direct_flight_skp = True`, `border = False`, `kind = "hotel"`. The board is the room's own board (UAI/AI/HB → AI/HB …).
- **Discounts:** `was_eur` is the price without early booking. `discount_label` is "Black Friday −32%" or "Early booking −48%". `valid_until` is the promotion end, only for a time-limited promotion.
- **Cost:** with 7 resorts × `max_hotels = 4` × 1 date, that's 7 + 7×4×2 = **63 requests**, about 8 minutes at 6–10 s.

### TOML block for config.toml

```toml
[sources.flight_hotels]
# relaxo.bg (Sofia tour operator) — hotel-only ("собствен транспорт") Turkish beach hotels near
# AYT / ADB / BJV (direct SKP flights). robots.txt disallows only /locale/ and /go/. The hotel's own
# result page gives a real total for 2 adults + 2 children (ages sent) for the stay.
# Kemer is left out on purpose (pebble beaches).
enabled = true
max_hotels = 4              # per resort: cheapest "from" price first (or list `hotels = [slugs]`)
nights = 7
check_ins = ["2027-07-03"]  # Saturdays; add dates for more offers (+1 request per hotel per date)
detail = true               # hotel page: pin, sandy beach, kids' club, rating, bookable window

[[sources.flight_hotels.pages]]
url = "https://relaxo.bg/oferti-za/lara"
season = "summer"
area = "Lara, Antalya coast"
country = "TR"
lat = 36.85
lng = 30.85
airport = "AYT"

[[sources.flight_hotels.pages]]
url = "https://relaxo.bg/oferti-za/belek"
season = "summer"
area = "Belek, Antalya coast"
country = "TR"
lat = 36.86
lng = 31.06
airport = "AYT"

[[sources.flight_hotels.pages]]
url = "https://relaxo.bg/oferti-za/side"
season = "summer"
area = "Side, Antalya coast"
country = "TR"
lat = 36.77
lng = 31.39
airport = "AYT"

[[sources.flight_hotels.pages]]
url = "https://relaxo.bg/oferti-za/alaniia"
season = "summer"
area = "Alanya, Antalya coast"
country = "TR"
lat = 36.54
lng = 32.00
airport = "AYT"

[[sources.flight_hotels.pages]]
url = "https://relaxo.bg/oferti-za/kushadasa"
season = "summer"
area = "Kusadasi, Aegean coast"
country = "TR"
lat = 37.86
lng = 27.26
airport = "ADB"

[[sources.flight_hotels.pages]]
url = "https://relaxo.bg/oferti-za/cheshme"
season = "summer"
area = "Cesme, Aegean coast"
country = "TR"
lat = 38.32
lng = 26.30
airport = "ADB"

[[sources.flight_hotels.pages]]
url = "https://relaxo.bg/oferti-za/bodrum"
season = "summer"
area = "Bodrum peninsula, Turkey"
country = "TR"
lat = 37.03
lng = 27.43
airport = "BJV"
```

Recommended addition under `[sources]`: `host_delays = { "relaxo.bg" = 8 }`, if `host_delays` is already a table there.

### Live check (26.11.2026)

I used **34 live requests** in total: robots files, the source survey below, 7 resort lists, 4 hotel pages and 4 result pages.

**Resort lists:**

| Resort | Own-transport hotels |
|---|---|
| Belek | 36 |
| Bodrum | 36 (21 with a "from" price) |
| Side | 36 |
| Lara | 27 |
| Kusadasi | 22 |
| Alanya | 36 |
| Cesme | 3 (1 priced) |

**Result pages.** I priced 4 hotels at 7 nights from 03.07.2027 for 2+2 (ages 3 and 3). That gave **4 priced 2+2 offers**:

| Hotel | Room | Price, 7 nights | Discount |
|---|---|---|---|
| Palm Wings Ephesus 5\* (Kusadasi) | Large Bunkbed Room, UAI | **€2,335.76** | was €3,461.54 |
| Limak Arcadia Sport 5\* (Belek) | Economy Room, UAI | **€2,358.45** | was €2,983.68, Black Friday −20% |
| Orange County Belek 5\* (Belek) | Standard Room Land View, UAI | **€2,484.39** | was €4,771.22, early booking −48% |
| Dream World Palace 5\* (Side) | Family Room, AI | **€2,259.48** | early booking −27% |

A full run with the block above would give up to 28 offers (7 × 4) per check-in date.

### Other candidates I checked (and why not)

| Candidate | Result |
|---|---|
| **Orient 99** (orient99.com; robots: only `Disallow: /reservation_calc.html`) | Has "собствен транспорт" early-booking pages for Kusadasi, Bodrum, Belek, Side, Alanya, Lara and Cesme. But the price table is filled by the disallowed `reservation_calc` widget. The static page has only a "from" price per person per night, with no date or occupancy. Relaxo is strictly better, and its prices match (Palm Wings: 53 € on both). |
| Tours-club.com | robots disallows `*dni=*`, `*adult=*`, `*child=*`, `*birthday*`: the occupancy parameters. Not used. |
| vs-travels.com, aventura.bg | vs-travels robots is a long content-signal file (not pursued). aventura.bg robots answers 522. |
| Relaxo **Malta** (`/oferti-za/malta`) | 0 hotel cards. Relaxo's Italy, Spain and Malta sections are tours, not hotel-only. |
| Olympic / Travelland / Argus hotel-only for TR, IT, ES, CY, MT | Not pursued. Earlier rounds found Argus's Turkey offer to be bus packages, and `tr_hotels.md` found the Serbian sites carry Turkey only as BEG flight packages. |

## Known limits

- **Turkey only.** Apulia (Bari), Costa Daurada / Maresme (Barcelona), Sardinia (Alghero), Malta (Mellieha) and Cyprus (Ayia Napa, Protaras) have **no source yet**. Relaxo sells no hotel-only there, and Booking/Expedia are excluded. Italian and Spanish hotels' own 2027 price lists ("listino prezzi 2027") are mostly published in January–March, so they're worth a separate round then. `flights.apply` will still mark any such hotel that gets entered by hand.
- **One check-in date per run** (configurable). Prices are early-booking or Black-Friday prices for that week. Other weeks need more dates, at +1 request per hotel per date.
- **Room choice:** we keep the cheapest available room, which may be a "Large Bunkbed" or "Economy" room. The room name is in `room`. Whether two cots fit is still a question for the hotel. The "Family Room" price is usually 20–30% more.
- **Family facts** (sandy beach, beachfront, mini club) come from the agency's amenity chips, so they're stored unverified (`verified = []`). Relaxo's rating comes from an unnamed review platform, with counts like Google's. It's stored as `source = "Relaxo.bg"`, and the ratings rule then applies.
- **Medical insurance** and the city tax (where charged) aren't in the price. The flight isn't included (by design), and transfers aren't either.
- **Prices are in EUR,** and Relaxo also shows BGN. Payment is in BGN (30% deposit).

## For the integrator

- Add `trips/flights.py` to `build()` and `flight_hotels` to `AUTO_SOURCES`, as in the diff above.
- Paste the two TOML blocks.
- Hotels may carry a **new optional field `flight`**, which the dashboard can show (e.g. "✈ SKP→AYT, ~30 km transfer, Jun–Sep"). The hotel-level family keys used (`kids_club`, `kids_pool`, `animation`) are new but harmless. `sand_beach`, `beach_type`, `beachfront`, `first_child_free_max_age` and `ratings` are existing keys.
- `dedupe.merge_auto_v2` should fold Relaxo hotels into same-named Savana (`sv-…`) Antalya and Kusadasi hotels. That gives one hotel with both a flight-package price (2+0) and a hotel-only 2+2 price.
