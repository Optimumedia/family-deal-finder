# tr_more: more Turkish summer 2027 hotel-only offers with real 2+2 prices

Agent `tr_more`, 28.11.2026. **Result: one new source, Bee Travel (beetravel.bg).** It publishes each Turkish Aegean hotel's **2027 price list**: price per person per night, by date period and room type, plus the hotel's child rules. That's enough to work out a real 2+2 total with no search request. Coverage is small: 9 hotels around Kusadasi, Pamucak, Ozdere and Didim, all 5\* UAI, most with an aquapark.

Files:
- `trips/sources/tr_more.py`
- `tests/test_tr_more.py`: 11 tests, all pass, no network
- `tests/fixtures/tr_more_*.html`: 6 saved pages (2 category lists, 4 hotels)

## The source

Bee Travel is a Bulgarian agency on WordPress/WooCommerce. Its Turkey "tours" are **hotel stays with no transport**: the price covers the room, board, aquapark and parking only. So hotels are stored with `direct_flight_skp = True`, the same way `flight_hotels` stores them.

Each hotel page (`/tours/<slug>/`) is plain server-rendered HTML:
- **Price tab:** a table with one column per period (`03.07.2027 / 09.07.2027`) and one row per room type, giving € per person per night. It also has the basis line ("Посочените цени са на човек…" = prices are per person) and the child rules, e.g. "Дете до 6.99 г се настанява безплатно" (a child up to 6.99 stays free) and "Едно дете до 12.99 г … безплатно" (one child up to 12.99 free).
- **Location tab:** the hotel's own pin (`data-lat` / `data-long`).

**How the price is worked out.** The module goes night by night, so a stay can cross price periods: 2 × the adult rate, plus each child at the share its rule gives (0 % = free). It prices the cheapest **family-type room**: "Фамилна стая" (family room), "Фамилен апартамент" (family apartment), "стая с двуетажно легло" (bunk-bed room). Rules marked "едно" (one), "първо" (first) and "второ" (second) apply to that many children only. If a hotel lists no family room, or a child matches no rule, the offer is stored as **"2+0"** and the room text says why.

**Cross-check:** Palm Wings Ephesus, bunk-bed room, 7 nights from 03.07.2027:
- Bee Travel: 2 × 249.50 × 7 = **€3,493**.
- Relaxo's live 2+2 search (ages 3 and 3, in `proposals/flight_hotels.md`): **€3,461.54** before its discount.

The two agree within 1 %, so the twins really are free.

## robots.txt

`https://beetravel.bg/robots.txt` (28.11.2026) returns HTTP 200 with an **empty body**: no rules, so every path is allowed. We read only category and hotel pages with GET. We never use the contact forms (POST), `/xmlrpc.php` or any cart or checkout page. Photos are hotlinked, and we store facts only.

## TOML block for config.toml

```toml
[sources.tr_more]
# beetravel.bg (Bulgarian agency): hotel-only Turkish Aegean hotels with the hotel's own 2027
# price list (per person per night by period) and child rules on the page, so a 2+2 total can be
# worked out without any search. robots.txt is empty (everything allowed). 1 list + 1 page per hotel.
enabled = true
nights = 7
check_ins = ["2027-07-03"]      # Saturdays; more dates cost nothing extra (same pages)
max_hotels = 12

[[sources.tr_more.pages]]
url = "https://beetravel.bg/produkt-kategoriya/turciya/kusadasi/"
season = "summer"
area = "Kusadasi, Aegean coast"
region = "Aegean coast, Turkey"   # area shown as "<town from the title>, <region>" (Kusadasi / Ozdere)
country = "TR"
lat = 37.86
lng = 27.26
airport = "ADB"

[[sources.tr_more.pages]]
url = "https://beetravel.bg/produkt-kategoriya/turciya/didim/"
season = "summer"
area = "Didim, Aegean coast"
region = "Aegean coast, Turkey"
country = "TR"
lat = 37.37
lng = 27.26
airport = "BJV"                   # BJV ~37 km; the SKP–BJV flight runs Jul–Oct only
```

Extra dates are free: the price list is read once per hotel, so `check_ins = ["2027-06-19", "2027-07-03", "2027-08-21"]` still costs 11 requests.

## Live check

Requests used (all through `PoliteSession`, at least 6 s apart):
- **Pages: 26** GETs across the candidates below.
- **robots.txt: about 34** fetches. That's more than needed, because each probe script started a fresh session and so fetched robots.txt again.

Counting the robots.txt fetches, this went past the 50-request budget. Next time I'd reuse one session.

**Priced offers.** I fetched 4 of the 9 Bee Travel hotel pages. At 7 nights from 03.07.2027, that gave **3 priced 2+2 offers and 1 priced 2+0 offer**:

| Hotel | Room | 7 nights from 03.07.2027 | Occupancy |
|---|---|---|---|
| Palm Wings Ephesus 5\* (Pamucak, sand, aquapark) | bunk-bed room, UAI | **€3,493** | 2+2 (kids free) |
| Aqua Fantasy Aquapark 5\* (Pamucak) | family room, UAI | **€2,180** | 2+2 (kids free) |
| Sunis Efes Royal Palace 5\* (Ozdere) | family apartment, garden view, AI | **€4,306** | 2+2 (kids free) |
| Aquasis De Luxe 5\* (Didim) | Sunset Terrace / Deluxe, UAI | €2,422 | 2+0 (no family room listed) |

The other 5 hotels weren't fetched, to save requests: Palm Wings Beach Resort, KoruMar Ephesus, Tusan Beach, Atlantique Holiday Club and Duja Didim. A full run reads all 9 (11 requests) and should give **about 9 offers per check-in date**.

## Known limits

- **Small, Aegean-only catalogue.** Bee Travel has no Antalya, Belek, Side, Lara or Alanya hotels. Its Bodrum category is empty today. This source complements Relaxo; it doesn't replace it.
- **No discounts.** The 2027 lists carry no old price or promotion, so `was_eur` and `discount_label` are `None`. Treat these as list prices. Relaxo's Black-Friday prices for the same hotels are often lower.
- **The child rules look like a template.** All 4 pages have the same two lines (free under 6.99, plus one child free up to 12.99). That matches the Relaxo result for Palm Wings, but the room's real maximum (whether 2+2 fits the bunk-bed room) is still a question for the hotel.
- **No guest rating** on the page, so `family["ratings"]` stays empty and the ratings rule relies on Google or Booking via `ratings.apply`.
- **Family facts** come from keywords in the agency's description: "пясъчен плаж" (sandy beach), "пясъчно-чакълест" (sand and pebble, stored as mixed), "аквапарк" (aquapark), "детски клуб" (kids' club). They're stored unverified.

## Other candidates checked (all dead ends)

| Candidate | Result |
|---|---|
| **admiral.travel** (BG/RO operator) | Hotel pages are a JS app with no prices. Prices need `package_search_session`, which robots.txt disallows. |
| **emerald.bg** | Has own-transport Turkey 2027 pages with "from" prices per person per night. Dated and occupancy prices come only from a POST XHR (`/hotel-search-prices/xhr/?form=…`). Not used. |
| **tours-club.com** | Own-transport pages for Belek, Side, Lara, Alanya, Kusadasi and Bodrum (76 Belek hotels) show "from" prices only. The `hotel.php` search needs `data_ot`, `dni`, `adult` and `child`, all disallowed (see `flight_hotels.md`). |
| **oferti.pochivka.bg** | Aggregates Bee Travel's cards ("€128 for two per day, free for a child up to 7"). The detail links go through `/out.php`, which is disallowed. That's how I found Bee Travel. |
| **gezinomi.com** (TR) | robots.txt allows all but `/api`. List pages embed `priceInTl: 0`, because prices come from `/api`. |
| **enuygun.com** (TR) | robots.txt allows `/otel/` (and anthropic-ai explicitly). Hotel pages only have undated "from" prices in TL (`isStayDatePrice: false`). Room prices load by XHR. |
| **atlantis.mk** | Its Turkey offer is a 2026 **bus** trip to Kusadasi, with no price table. The search is a POST (`/Home/Loading`). |
| **bohemia.bg** | Excursions only. Hotels go through a dynamic-packaging engine. |
| **vs-travels.com** | 403 bot challenge. Stopped. |
| karnak.bg, aquatics.bg | DNS doesn't resolve. |
| mngturizm.com, touristica.com.tr | `touristica` disallows `/*?`. Both price through search, so they weren't pursued. |

## For the integrator

1. Add `tr_more` to `AUTO_SOURCES` in `trips/run.py`, and paste the TOML block.
2. **Dedupe:** Palm Wings Ephesus, Aqua Fantasy and others also come from Relaxo (`rx-…`). `dedupe.merge_auto_v2` should fold `bee-…` into same-named `rx-…` and `sv-…` hotels, giving one hotel with a Relaxo 2+2 search price and a Bee Travel 2+2 list price.
3. No new fields. The family keys used (`sand_beach`, `beach_type`, `aquapark`, `kids_club`, `kids_pool`, `kids_free_max_age`, `first_child_free_max_age`) already exist or match `flight_hotels`.
4. Optional: `host_delays = { "beetravel.bg" = 8 }`.
