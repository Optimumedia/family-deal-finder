# Brief for search-expansion agents

Project: `C:\Users\HP Omni Book 14\family-deal-finder` (Python 3.14, git repo — **do not run git commands**).
Product: finds holiday offers for a family from Skopje, North Macedonia (2 adults + twins born Oct 2023).
Hard rules:
- Reachable from Skopje: a **direct flight from SKP**, or at most a **5h drive** (about 45 min of borderline tolerance is OK).
- Summer: sandy beach and breakfast + dinner preferred.
- Winter: a 1-bedroom apartment (separate bedroom) with cots and family activities.
- Real discounts matter.

Read first: `README.md`, `PRODUCT.md`, `config.toml`, and these existing sources: `trips/sources/olympic.py` and `trips/sources/travelland.py` (both agencies), `trips/sources/hotel_direct.py`, `trips/sources/oliverstravels.py`, `trips/sources/micazu.py`. Also read `trips/http.py` (PoliteSession) and `trips/sources/pagetext.py`.

## Rules (non-negotiable)
- Obey robots.txt. Use `trips.http.PoliteSession`, which checks robots.txt and stops on bot walls.
- Never use a path robots.txt disallows (e.g. `/api/`, `/search?`), never log in, and never get around a CAPTCHA, Cloudflare challenge or 403.
- Excluded: Booking.com, Airbnb, Vrbo, Expedia, Wizz Air scraping, Marriott Homes, WebHotelier (`*.reserve-online.net`), and Fibula's private API.
- Keep requests low: develop against saved pages, and fetch live only to save fixtures and confirm structure. Space requests at least 5 s apart.
- Store facts only: name, price, dates, board, room, occupancy, discount, valid-until, photo URL (hotlinked) and source URL. Copy no descriptions.

## What you may write (ONLY these, never edit existing files)
- `trips/sources/<yourname>.py`: a module with `fetch(cfg, today, session=None) -> (hotels, offers)`, shaped exactly like `olympic.py` and `travelland.py`:
  - Hotel dicts: `id` (prefix unique to your source), `name`, `stars`, `season` ("summer" or "winter"), `area`, `country`, `lat`, `lng` (resort-level is fine), `direct_flight_skp` (bool), `border` (bool), `kind` ("hotel", "villa" or "apartment"), `family` (`{"verified": []}` plus any facts the page states), `image` (an https URL, or None), and `notes`.
  - Offer dicts: `hotel`, `source`, `url`, `seen` (today ISO), `check_in`, `nights`, `board` (HB/FB/AI/BB/RO/SC/?), `room`, `occupancy` ("2+2" only when the price covers 2 adults + 2 small kids, else "2+0"), `price_eur` (total for the stay), `was_eur`, `discount_label`, `valid_until`.
  - Read your settings from `cfg["sources"].get("<yourname>", {})` with an `enabled` flag and a `pages` list. Pages carry season, area, country, lat, lng, nights and check_in, like the existing ones.
  - If yours is a campaign-type source (no prices), match `hotel_direct.fetch` instead.
- `tests/test_<yourname>.py` plus `tests/fixtures/<yourname>_*.html|json`: parser tests on saved pages, with no network.
- `proposals/<yourname>.md`: a short report:
  - what the source is and robots.txt status (quote the relevant lines)
  - the exact `[sources.<yourname>]` TOML block to add to config.toml, with real page URLs
  - how many priced offers a live check found
  - known limits
  - anything that needs the integrator (e.g. a new field)

Run your tests with: `PYTHONIOENCODING=utf-8 python -m unittest tests.test_<yourname> -v` from the project root.

**If your area has no viable allowed source,** write only `proposals/<yourname>.md` explaining what you checked and why it isn't viable. A sound "no" is a valid result.
Keep your final report under 250 words: the files written, live offer count, and the TOML block's location.
