# rs_agencies: Serbian agencies selling Greek summer 2027

Agent `rs_agencies`, 2026-11-26. Built: **ArgusTours (argus.rs)**, which gives real 2+2 prices per unit.

## What I checked

| Agency | robots.txt | Platform / Greek summer | Verdict |
|---|---|---|---|
| **ArgusTours** argus.rs | `User-agent: *` / `Disallow:` (allows everything) | Own CMS. Its "sopstveni prevoz" (own transport) pages list the **whole season's price list in plain HTML**: object × unit × 10-night window, **price per unit ("PO SOBI")** | **Built** |
| Oktopod oktopod.rs | none (404, so everything is allowed) | Greek apartment specialist (Stavros, Asprovalta, Vrasna, Paralia, Thassos…). One page per object, with a full price table **per person** by structure (1/2, 1/3, 1/4 STD), bus package, and "−30 € per paying person for own transport" | Next candidate (see below) |
| BigBlue bigblue.rs | `Allow:*`, `Disallow: /*.asmx`, `/*.ashx` | Same B2C platform as Filip Travel and Kon Tiki (`/sr/location/…`, `cms.*/b2cdocuments`). Has "grcka-sopstveni-prevoz" | Not built: on this platform the lists load through `.asmx`/`.ashx` services, which robots.txt disallows |
| Kon Tiki kontiki.rs | robots.txt returns HTTP 500 | Same platform as BigBlue | Skipped |
| Filip Travel | `Disallow: /[A-Z]`, `/*PL=`, `/sr/hotel/greece/`, `/sr/packages/`, `Crawl-delay: 30` | The Greek hotel pages are disallowed | Not viable |
| Kompas kompas.rs | `Allow: /` | No Greek summer links on the home page | Not pursued |
| Grand Tours grandtours.rs | Yoast block: `Disallow:` (allows everything) | WordPress pages ("grcka-leto-2026") | Not pursued (2026 season, no tables seen) |
| Odeon odeontravel.rs, Ponte ponte.rs | not checked | Hotel pages for Greece exist | Not pursued |
| Eta Travel | etatravel.rs/eta.rs don't resolve. etatravel.com is a different company | n/a | n/a |

**None of these agencies uses the Olympic/Travelland `/services/list/` platform.** No home page had `data-destination` together with `/services/list/`. Argus uses `data-destination="Beč"` for something unrelated. So no config-only reuse of the existing parsers is possible.

## The ArgusTours source (`trips/sources/rs_agencies.py`)

- **What it fetches:** one GET per destination page, through PoliteSession.
- **How the page is laid out:** each month is a tab. The table head lists the windows ("01.07.<br>11.07."). Each object has a header row with a link to its page. Each unit has a row ("A4 PR (NA)") with a price row under it ("PO SOBI" plus one cell per window).
- **Sold-out and unbookable cells are skipped:** a cell marked `capacity-no`, or one without a booking link (the page's own legend says that means "booking not possible now").
- **What becomes an offer:**
  - Per object and window, the cheapest bookable unit that sleeps at least `min_beds` (default 4): A4, S4, S2+2 and so on.
  - It is stored as **occupancy "2+2"**, with the price per unit for 10 nights.
- **Board** comes from the page's service code: NA (rental) → SC, ND → BB, PP → HB, PA → FB, AI/UAL → AI.
- **Per-person prices:** none are on the page yet, but if a hotel page uses "PO OSOBI" the price is stored as 2 adults × price, "2+0".
- **Hotel fields:**
  - id is `ag-<object slug>`.
  - kind is `apartment` when the board is SC.
  - Location is resort level, from the page config.
  - The town goes into `notes`.
  - No photo: the page's images show the destination, not the object.
- **Not in the price** (the page says so; noted on each hotel): tourist tax of 2–5 € per unit per day and air-conditioning at 5–10 € per day, both paid on the spot.

## TOML block for config.toml

```toml
[sources.rs_agencies]
# argus.rs (ArgusTours) — robots.txt "User-agent: * / Disallow:" (all allowed). Own-transport
# price lists: price PER UNIT for 10 nights. Units sleeping 4 (A4, S4, S2+2) → real 2+2 prices.
enabled = true
min_beds = 4
check_in_from = "2027-06-01"
check_in_to = "2027-09-15"

[[sources.rs_agencies.pages]]
url = "https://argus.rs/aranzmani/letovanje/grcka/kasandra-sopstveni-prevoz-2027"
season = "summer"
area = "Kassandra, Halkidiki"
country = "GR"
lat = 40.02
lng = 23.43

[[sources.rs_agencies.pages]]
url = "https://argus.rs/aranzmani/letovanje/grcka/sitonija-sopstveni-prevoz-2027"
season = "summer"
area = "Sithonia, Halkidiki"
country = "GR"
lat = 40.10
lng = 23.80

[[sources.rs_agencies.pages]]
url = "https://argus.rs/aranzmani/letovanje/grcka/tasos-sopstveni-prevoz-2027"
season = "summer"
area = "Thassos"
country = "GR"
lat = 40.70
lng = 24.65

# Hotel price lists (with board) are announced but empty today ("Aranžmani nisu postavljeni").
# Cheap to keep: 1 request each, 0 offers until they open.
[[sources.rs_agencies.pages]]
url = "https://argus.rs/aranzmani/letovanje/grcka/halkidiki-hoteli-sopstveni-prevoz-2027"
season = "summer"
area = "Kassandra, Halkidiki"
country = "GR"
lat = 40.02
lng = 23.43

[[sources.rs_agencies.pages]]
url = "https://argus.rs/aranzmani/letovanje/grcka/tasos-hoteli-sopstveni-prevoz-2027"
season = "summer"
area = "Thassos"
country = "GR"
lat = 40.70
lng = 24.65
```

`olimpska-regija-sopstveni-prevoz-2027` (Olympic Riviera) parses fine: 216 prices across 7 objects. But its largest unit is S3, so it gives 0 family offers and is left out.

## Live check (2026-11-26, check-ins 1 Jun to 15 Sep 2027)

| Page | Bookable prices | Objects with a 4-bed unit | 2+2 offers |
|---|---|---|---|
| Kassandra | 427 | 2 of 5 (Grigoriou, Polihrono; Nikos, Pefkohori) | 20 |
| Sithonia | 168 | 1 of 2 (Pantazaras) | 11 |
| Thassos | 458 | 5 of 10 (Central, Christos, Kiparisiou, Nel Centro, Olga) | 48 |
| Halkidiki and Thassos hotel pages | empty for now | 0 | 0 |

That is **79 priced 2+2 offers** from 8 apartment houses, all self-catering, 10 nights. Example: Grigoriou, Polihrono, A4 apartment, check-in 1 Jun 2027, 10 nights: **349 €** for the unit. In July/August the same unit is 825 €.

## Known limits

- **Self-catering only (for now):** every unit is a rental (SC). The scorer keeps SC capped and doesn't throw it out. The board-carrying hotel lists are still empty.
- **Few objects:** 8 with a 4-bed unit, so this is a small set of real family prices, not wide coverage.
- **10-night windows only.** There is no shorter stay on these pages.
- **No discounts:** no early-booking line or "was" price, so `was_eur` and `valid_until` are None.
- **Stars and photos:** no stars except where the name says so ("Hotel Petridis 3*"), and no photo.
- **Separate bedroom unknown:** "A" units are apartments, "S" units are studios (one room). Their `room` text says which.

## Needs the integrator

- Add `rs_agencies` to `AUTO_SOURCES` in `trips/run.py`, and paste the TOML block above.
- No new fields.
- Optional: geocode each object by its town (the town is in `notes`).

## Next candidate: Oktopod (oktopod.rs)

- **Coverage:** many more apartment objects in Stavros, Asprovalta, Nea Vrasna, Paralia and Thassos.
- **Prices:** each object page has a per-person table by structure ("1/4 STD – 4 paying persons") for 7 and 10 nights, plus a rule of −30 € per paying person for own transport (the shifts marked * are excluded).
- **Turning that into 2+2:** 4 × the "1/4" price, minus 4 × 30.
- **Cost:** one request per object (about 1 MB pages), so it needs a hand-picked object list in config.
- **Robots:** no robots.txt (404).
