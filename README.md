# Family Deal Finder

Vacation deals for **2 adults + twins from Skopje**: family-first and discount-first.
It's a personal tool with no paid services and no Telegram.

## What it does

1. Reads the hotels we track (`data/hotels.toml`) and the price sightings (`data/offers.toml`).
2. Builds a **price history** for each offer, stored in `data/trips.db` on this PC.
3. Works out the **drive time from Skopje** with the free OSRM router (cached), plus a border buffer.
4. Applies the **hard family rules**:
   - Reach: a direct flight from SKP or a drive of 5h or less.
   - Summer: sandy beach within 150 m, plus breakfast and dinner.
   - Winter: a separate bedroom, so the twins sleep in cots in the other room.
   - 2 cots that take the twins **at their age on the trip date**.
5. Scores each offer:
   - **Family Fit (0–100):** sleep setup, beach or activities, travel, kids' facilities, food, health, logistics, reviews. This is multiplied by a confidence factor, which goes up as facts are verified.
   - **Deal quality (0–100):** our own price history first, then a comparison with similar offers, then the agency's "was" price at half weight. A "discount" that isn't cheaper than before is flagged `fake?`.
   - The rating is capped while a must-have is still unknown. Unknown must-haves show as "ask" in the checklist, so you know what to check with the hotel.
6. Writes `docs/data.json` for the dashboard (`docs/index.html`). It has Summer, Winter and Watchlist tabs, filters, price history, the family checklist and a "What's new" panel.
7. **Email digest:** new good deals, price drops of 7% or more, and offers ending within 3 days. Each alert goes out once. Without a `.email` file the digest is only written to `data/digest.txt`.

## Use it

```powershell
pip install -r requirements.txt
python -m trips.run                  # update everything
.\open_dashboard.ps1                 # open the dashboard at http://localhost:8810
python -m unittest discover -s tests -t .
```

**Record a new price:** copy an entry in `data/offers.toml`, change `seen` to today, and set the new `price_eur`. The next run adds it to the price history.

**Record what a hotel confirmed in writing:** set the fact in `data/hotels.toml` (e.g. `cots_max = 2`, `cot_age_max = 4`) and add its name to `verified`.

**Twins' age:** set `kids_birthdate` in `config.toml`. Until it's set, the engine assumes the oldest age the twins could be, which is the safe side for cot limits.

### Email digest (optional)

Create a git-ignored `.email` file with these lines (use a Gmail **app password**):

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-app-password
MAIL_TO=you@gmail.com
```

## Sources

| Source | Status |
|---|---|
| **Manual sightings** (`data/offers.toml`) | ✅ Live. Seeded with Fibula Black Friday prices from 25.11.2026. |
| Fibula (fibula.com.mk) | ⛔ **Not scraped.** Its prices load from a private API host, and its robots.txt disallows `/api/` and `/search?`. The proper route is to ask Fibula for B2B/XML access. |
| **Travelland** (travelland.rs) | ✅ **Automatic.** robots.txt allows all paths. It reads Bansko, Borovets, Pamporovo, Kassandra and Sithonia. Cards give a "from" price per person per night, plus the old price, the discount % and a "valid until" date. They don't give the board or the kids' price, so offers are stored as 2 adults × nights with the board unknown. Halkidiki 2027 said "offers coming soon" on 25.11.2026; it's picked up automatically once published. |
| **Olympic** (olympic.rs) | ✅ **Automatic.** robots.txt allows all paths. It runs on the same platform as Travelland. It reads Bansko, Borovets, Kopaonik, Kassandra and Sithonia. Cards give a "from" price (per day, per person per day, or per stay), the old price, an "early booking" badge, a "valid until" date, and the board when shown. Cards that say "on request" (no price) are skipped. There's no date window, so check-in is the page's default date. On 25.11.2026 it found **32 priced Halkidiki 2027 offers**. |
| **Hotels' own websites** (Sani, Porto Carras, St. Ivan Rilski) | ✅ **Automatic.** Reads each hotel's offers page and picks out campaigns: discount %, deadline and short text (e.g. "Black Friday, save 40%"). They show as 🏨 chips on that hotel's cards, and a new campaign triggers an alert. To add a hotel, put `[[sources.hotel_direct.pages]]` with its hotel id in config.toml. WebHotelier booking engines block robots, so we leave them alone. |
| **Oliver's Travels** (villas) | ✅ **Automatic.** Halkidiki whole villas: guests, bedrooms, weekly price range (the low end is used) and "% off" tags. Prices are converted from GBP. These are self-catering, so they're kept but capped: "no breakfast/dinner". |
| **Micazu** (rentals from owners) | ✅ **Automatic.** Bansko apartments rented directly from the owner: persons, bedrooms, nightly or weekly rates, cleaning fee, and whether a cot or high chair is available. Only rates that cover the check-in date are used. |
| Falcon (falcon.rs) | 🔜 robots.txt allows it. Its 2027 price tables were still empty on 25.11.2026. |
| Hotels' own pages | 🔜 For child and cot policies. |
| SerpApi Google Hotels (free tier) | 🔜 Price cross-check with real child ages. |
| Booking.com, Airbnb, Vrbo, Wizz Air | ❌ Excluded: their terms forbid scraping. |
| Marriott Homes & Villas | ❌ robots.txt blocks every date, guest and search parameter. |
| WebHotelier (`*.reserve-online.net`, many Greek hotels' booking engine) | ❌ Blocks robots (403), so it's left alone. |

The rules for every automatic source live in `trips/sources/__init__.py`: respect robots.txt, go slowly, stop at a bot wall and never get around it, store facts only, and link back to the source.

## Roadmap

- **v1 (this):** engine, price history, family rules, deal check, dashboard, email digest, manual sightings.
- **v2:** first automatic agency source (Falcon/Travelland), map with a 5h drive ring, scheduled runs, publishing to GitHub Pages.
- **v3:** more winter resorts (Borovets, Pamporovo, Kopaonik), SerpApi cross-check, "book now or wait" from price history, comparing a package with booking flight and hotel separately.
