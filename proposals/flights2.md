# flights2: direct-flight beach destinations from SKP beyond Antalya/Kusadasi

**Result: no new source module.** I couldn't find an allowed, machine-readable source that sells priced packages from Skopje for the new destinations. One real summer 2027 offer turned up: Atlantik Turs, Amalfi coast. Its prices are inside a JPEG, so the offer is listed below for manual entry instead of a scraper. Checked on 26.11.2026, with about 25 polite requests in total, 6–8 s apart, through `PoliteSession`.

## 1. Direct routes from SKP (evidence)

Source: the CAA summer 2026 timetable (`https://www.caa.gov.mk/wp-content/uploads/2026/05/Time-Table-Summer-2026.pdf`, the 11.05.2026 version). I extracted its text. This timetable lists **scheduled flights only**. TAV's 2026 press release says "7 airlines … 24 charter destinations" but doesn't name any of them. Neither the CAA nor TAV has published a summer 2027 schedule yet.

| Destination (beach use) | Flight, summer 2026 | Status for 2027 |
|---|---|---|
| **Bodrum** (Gümbet, Turgutreis, Bitez) | AJet VF1213/1214, day 3 (Wed), 01.07–22.10.2026, overnight rotation | Likely (scheduled, 2nd season). No 2027 filing found. Savana has **no** Bodrum packages (see §2). |
| **Naples** (Amalfi coast: Maiori, Minori; Sorrento) | Wizz W6 4817/4818, days 1/3/5, 31.03–23.10.2026 | **Confirmed in use for 2027**: Atlantik Turs sells 14.07–01.09.2027 Wednesday departures "со директен лет од Скопје". |
| **Bari** (Puglia: Polignano, Monopoli, Torre Canne sandy beaches) | Wizz W6 4811/4812, days 2/4/6, 31.03–24.10.2026 | Scheduled all year. No package seller found. |
| **Barcelona** (Costa Maresme, Costa Dorada: Salou, Cambrils sandy beaches) | Wizz W6 4737/4738, days 2/4/6, 31.03–24.10.2026 | Scheduled. No package seller found. |
| Larnaca (Cyprus) | Wizz W6 4767/4768, days 1/5 | Scheduled. Savana lists Larnaca only as "individual" (no flight package). |
| Malta | Wizz W6 4765/4766, days 1/3/5 | Scheduled. Few sandy beaches. |
| Palermo / Alghero | Wizz, mid-July to mid-September 2026 only | Seasonal. Covered by another task. |
| **Dalaman** | — | Not in the timetable. No evidence. |
| **Malaga** (and any other Spanish beach airport besides Barcelona) | — | Not in the timetable; flightconnections doesn't list it either. **No direct flight.** |
| **Hurghada / Sharm** | Air Cairo charter. Its last recorded SKP flight was 21.10.2025 (per the charters research). | Not in the 2026 schedule. Savana's `/vacations/egypt/hurghada/from-skopje/vacations/with-plane/` has 0 cards. AS Travel's Hurghada page shows "Нема хотели слободни". **Not confirmed.** |
| **Crete / Rhodes / Corfu** | Aegean flew SKP–Corfu in summer 2024 only. Crete and Rhodes appear only on fare-search pages. | **Not confirmed.** |
| **Tunisia** (Monastir/Djerba) | Monastir was a charter in 2025, per press. Not in the 2026 schedule. | **Not confirmed.** AS Travel's Tunisia page is empty. |

Re-check the CAA "Time-Table-Summer-2027" PDF when it appears (usually in March) and TAV's April press release for named charters.

## 2. Sources checked

| Source | robots.txt (quoted) | Finding |
|---|---|---|
| **Savana Travel**, other destinations | `User-agent: *` `Allow: /` … `Disallow: /catalog`, `/packages_explorer`, `/*print=yes` (unchanged) | `/vacations/turkey/` lists only **Antalya and Kusadasi** "with-plane". `/vacations/greece/` is bus or individual only. Guessed Bodrum and Hurghada `…/from-skopje/vacations/with-plane/` URLs return the page shell with **0 cards**. The `<resort>-vacation/` landing pages (Bodrum, Hurghada, Heraklion, Chania, Sousse-Monastir, Mallorca …) are generic and list no packages. There's nothing to add beyond what `charters` already covers. |
| **AS Travel** (astravel.com.mk) | `User-agent: *` `Disallow: /checkout.php`, `/login.php`, `/*?*min_price=`, `/*?*max_price=`, `/*?*orderby=` … `Allow: /` | Has categories for Egypt-Hurghada (`/egipet-hurgada-c351`), Spain (`c350`), Tunisia (`c352`) and Turkey (`c353`). All four are empty search shells ("Нема хотели слободни за избраниот датум"). Prices only appear after a date search. Not viable. |
| **Atlantik Turs** (atlantikturs.com) | robots.txt is empty (0 bytes), so everything is allowed | `/leto-2027` holds **one** flight-beach programme: Maiori (Amalfi coast), Hotel Riviera 3\*, 7 nights BB, flight SKP–NAP–SKP, checked bag, transfers. The price list is the image `/images/gallery/cenovnik-final--1369x632.jpeg`, with no price in the HTML. "Грција – сопствен закуп" is its own-allotment Greece programme, not a flight package. The "Турција чартер 2025" page is stale. |
| AtlantiS (atlantis.mk) | No `Disallow` rules | Its menu has only Bulgaria and winter items, city tours, and "greece-hotels" (on request). No flight beach packages. |
| Explora (explora.mk) | `User-agent: *` `Allow: /` | Italy and Turkey destination pages hold city breaks only (Rome, Milan, Istanbul). No beach packages. |
| Pilot Travel, Kompas, Sama, Noa, Sv. Nikola | see `proposals/mk_agencies.md` | Unchanged: there are no server-side summer flight prices. |

## 3. Atlantik Turs Amalfi offer, for manual entry

Facts from the price-list image (read in a browser-equivalent fetch, 26.11.2026). Prices are **per person**, early booking. The promo price needs a 30% deposit by **25.12.2026**.

| Departure (Wed), 7 nights | Room without balcony | Room with balcony | Apartment |
|---|---|---|---|
| 14.07.2027 | 799 € (regular 899) | 839 (939) | 939 (1,039) |
| 21.07.2027 | 809 (909) | 849 (949) | 949 (1,049) |
| 04.08.2027 | 839 (939) | 879 (979) | 979 (1,079) |
| 25.08.2027 | 849 (949) | 889 (989) | 989 (1,089) |

- **Kids:** children 3–14 get 30% off. The hotel accepts **only children over 3**. The twins will be 3 years 9 months in July 2027, so they qualify.
- **Tourist tax:** €3 per person per day, paid at the agency.
- **Family estimate:** 2 adults + 2 children aged 3 in the apartment on 14.07 comes to about 2×939 + 2×657.30 ≈ **€3,193**. This is derived from the stated rule, not quoted. The entry below stays "2+0".
- **Board:** BB only (breakfast). That's weaker than the project's HB preference.
- **Beach:** Maiori has the coast's longest beach (grey volcanic sand), 50 m from the hotel.

Suggested entries for the integrator (`data/hotels.toml` and `data/offers.toml`):

```toml
[[hotel]]
id = "at-riviera-maiori"
name = "Hotel Riviera Maiori"
stars = 3
season = "summer"
area = "Maiori, Amalfi coast, Italy"
country = "IT"
lat = 40.648
lng = 14.641
direct_flight_skp = true      # Wizz SKP–NAP, then about 1h30 transfer (included)
border = false
kind = "hotel"
notes = "Atlantik Turs (Kavadarci/Skopje) own-allotment package, flight SKP–Naples included. Children only over 3; kids 3–14 −30%. Hotel on floors 5–6 of a building (lift)."
[hotel.family]
beach_m = 50
verified = []

[[offer]]
hotel = "at-riviera-maiori"
source = "Atlantik Turs (manual)"
url = "https://atlantikturs.com/leto-2027-na-edna-od-naјubavite-plazhi-vo-italiјa–bregot-na-amalfi-so-direkten-let-od-skopјe"
seen = "2026-11-26"
check_in = "2027-07-14"
nights = 7
board = "BB"
room = "Room without balcony, flight SKP–NAP + transfers included (apartment 939 € pp)"
occupancy = "2+0"
price_eur = 1598
was_eur = 1798
discount_label = "Early booking -11%"
valid_until = "2026-12-25"
```

There's no `image` line: the agency's only photo is a 320×220 thumbnail, so leave it out or add the hotel's own photo URL.

## 4. TOML block for config.toml

None. No new automatic source is proposed, and `[sources.charters]` needs no new pages: Savana has no flight packages for Bodrum, Egypt, Greece or Tunisia.

## 5. Live offer count

- 0 priced offers from an automatic source.
- 1 hotel with 12 price points (4 dates × 3 room types) from Atlantik Turs, as an image, for manual entry.

## 6. Known limits and follow-ups for the integrator

- Bari, Naples and Barcelona are real year-round Wizz routes. A family could go flight-only plus a self-booked hotel, but there's no allowed Skopje-sold priced package to track. Wizz scraping is excluded.
- **March 2027:** check the CAA summer 2027 timetable. If Hurghada, Crete or Monastir charters appear, check Savana `/vacations/<country>/<resort>/from-skopje/vacations/with-plane/` again (the `charters` parser fits as-is) and AS Travel's category pages.
- **Atlantik Turs** may add more "Лето 2027" flight programmes, so watch `https://atlantikturs.com/leto-2027`. A future module would need OCR for the price images, which isn't worth it for one hotel.
- No tests or fixtures were written, since there's no parser.
