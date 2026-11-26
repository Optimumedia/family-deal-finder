# Family Deal Finder

Holiday deals for **2 adults + our twins, from Skopje**. It looks at travel agencies, hotels' own
websites and holiday rentals, keeps only what fits our family, and checks whether a "discount" is
really cheaper than before. It costs nothing to run and never books anything: every offer links
to the page where you book.

**Open it:** `.\open_dashboard.ps1` (on this PC, at http://localhost:8810), or the published GitHub Pages copy.

---

## What the dashboard shows

- **Tabs:** **Summer** (beach holidays), **Winter** (ski holidays) and **Shortlist** (the hotels you
  marked with the heart). From the Shortlist you can **Compare** hotels side by side.
- **One row per hotel.** It shows the best offer for us, with the other agencies' prices for the
  same hotel underneath. Click a row for the full details: photo, map, route from Skopje, price
  history and the family checklist.
- **The rating** (Once-in-a-lifetime 💎, Exceptional 🔥, Great ⭐, Good 👍, Worth a look 👀) combines:
  - **Family fit:** how well the hotel suits the twins (sleeping, beach or ski, meals, drive, kids' facilities).
  - **Deal quality:** how good the price is compared with what we have seen before.
- **Hard rules.** A hotel is left out ("Doesn't fit") if it breaks one of these:
  - It's more than about a 5-hour drive and has no direct flight from Skopje.
  - In summer: no sandy beach close by, or no breakfast + dinner.
  - In winter: no separate bedroom.
  - It can't take 2 cots for the twins at their age on the trip date.

  To see the hotels that were left out, tick **Show ruled-out hotels** in Filters.
- **Filters:** a real family price only, has a discount, ends within 7 days, breakfast + dinner,
  maximum drive time, area and type (hotel / villa / apartment).
- **What's new:** price drops and new offers since your last visit.
- **Yellow bar at the top:** one of the sources couldn't be read in the latest check (see
  [When a source fails](#when-a-source-fails)).

## How to read the prices

Always check **who the price is for**, shown under each price:

| Shown as | Means | What to do |
|---|---|---|
| **2+2 family** | The price for 2 adults + the twins. This is the real price we would pay. | Compare these with each other. |
| **2 adults** (warning colour) | The agency only showed a price for 2 adults. The twins' cost is not included. | Don't compare it with a 2+2 price. Ask the agency for a quote for 2 adults + two 3-year-olds. |

Other things to check:

- **Price** is the **total for the whole stay** (all nights), in euros.
- **Board:**
  - BB = breakfast
  - HB = half board (breakfast + dinner)
  - FB = full board
  - AI = all inclusive
  - SC = self-catering
  - "not stated" = the agency didn't say. Check on the agency's page.
- **Dates:** the check-in date and number of nights the price is for. Other dates cost differently.
- **"Book now" / "Can wait":** based on our own price history. For example, an offer ending soon at its lowest price says Book now, and a falling price says Can wait. With little history it says nothing.

## How the checks work

**Discounts.** Agencies often show a "was" price that was never charged. So we record every price we see,
and judge discounts against **our own history**:

- **"Verified −X% vs our recorded price"** (green): it really is cheaper than the prices we
  recorded before.
- **"not confirmed yet"** (grey): there's only the agency's "was" price, or too little
  history. It counts for half until our history confirms it.
- **"fake?"** (red): it's called a discount, but it isn't cheaper than before.

Each price we record is one "check". The more checks an offer has, the more the price history means.

**Family facts.** Each fact on a hotel's checklist is one of:

- **✓ (confirmed)**: the hotel confirmed it in writing.
- **hollow mark**: agency or website info, not yet confirmed by the hotel.
- **ask**: we don't know yet. The details panel suggests the question to send to the hotel.

While a must-have (for example, 2 cots) is still "ask", the rating is held below "Great". So a
hotel can only be Great or better once it's confirmed.

**When a hotel replies,** put the fact in `data/hotels.toml` (for example `cots_max = 2`,
`cot_age_max = 4`) and add its name to the `verified` list, like `verified = ["cots_max", "cot_age_max"]`.

**Checking every offer.** Every offer is checked before it's saved. An offer is thrown away (and
logged) if:

- its price per night is impossible
- its date is in the past or too far ahead
- its board is unknown
- its link isn't https

So one broken website can't spoil the price history.

## Adding Fibula prices

Fibula, the main Skopje agency, doesn't allow automatic reading of its prices, so we add them by
hand. The helper below checks everything before saving it and builds the price history for you.

Open PowerShell in the project folder (`family-deal-finder`) and run one of these.

**The easy way: it asks one question at a time.**

```powershell
python -m trips.add_offer --interactive
```

1. It asks you to paste a result line from Fibula, for example
   `Xenios Anastasia Resort & Spa ... HB ... 1.721 € ВКУПНО ОД 1.205 €`.
   It fills in the hotel, the price (1205), the "was" price (1721) and the board (HB) from it.
2. Press **Enter** to accept a suggested value, shown in `[brackets]`.
3. It then asks for anything still missing: check-in date (`20.06.2027` is fine), nights, room,
   whether the price is for 2+2 or 2 adults, and the link.
4. It shows a summary. Type `y` to save.

**In one line:**

```powershell
python -m trips.add_offer --paste "Xenios Anastasia Resort & Spa ... HB ... 1.721 € ВКУПНО ОД 1.205 €" --check-in 20.06.2027 --nights 7 --room "Standard Room Limited View" --url "https://www.fibula.com.mk/promo/black-friday/grcija"
python -m trips.add_offer --hotel "Sani Beach" --check-in 20.06.2027 --nights 7 --board HB --price 5990 --was 6800 --valid-until 30.11.2026
```

Useful extras:

- `--occupancy 2+0` when Fibula only showed a price for 2 adults. The default is `2+2`.
- `--label "Early Booking -30% + Black Friday -5%"` for the discount text.
- `--dry-run` shows what would be saved, without saving.

**Re-checking prices, to build the history:**

```powershell
python -m trips.add_offer --list                       # offers whose last price is more than 7 days old
python -m trips.add_offer --list --all                 # every offer, with its number
python -m trips.add_offer --again 3 --price 1180       # today's price for offer no. 3
```

`--again` copies everything from that offer and only changes the price and today's date. If the
old promotion has ended, its "was" price and label aren't copied. Add `--was`, `--label` or
`--valid-until` if Fibula shows new ones.

**Good to know:**

- **Hotel names don't have to be exact.** "Xenios Posidi Paradise" finds Xenios Possidi Paradise.
  If the name is only *similar* to a hotel we track, it stops and asks "Did you mean …?" Use the
  suggested `--hotel <id>`, or add `--new-hotel` if it really is a different hotel.
- **New hotels** are added to `data/hotels.toml` as a short entry. The area and approximate map
  position are copied from a hotel we already know in the same town (for example `--area Possidi`).
  If the town is new to us, add `--season summer --area "Town, Region" --lat .. --lng ..` (from
  Google Maps). Its family facts start as "ask", so check them with the hotel.
- **One price per offer per day.** If you typed the wrong price today, fix `price_eur` in
  `data/offers.toml` itself.
- **Nothing broken is ever saved.** If something is wrong (a date in the past, a price like €40 for a
  week, an unknown board), it says what's wrong and saves nothing.
- **When it appears:** the new price shows on the dashboard after the next run, or right away with
  `python -m trips.run --offline`.

## Schedule

The PC runs the check by itself at **13:00 and 17:30** (it's usually on 12:00–19:00). Each run:

1. reads the sources
2. checks and stores the prices
3. scores everything
4. publishes the dashboard
5. emails the digest, if email is set up

If the PC is off at those times, that check is simply skipped.

- **Set it up** once: `.\setup_schedule.ps1`.
- **Run it now:** `.\run_local.ps1`. A full run takes about 20 minutes, because it waits politely
  between pages.

**Email digest (optional).** It lists new good deals, price drops of 7% or more, and offers
ending within 3 days. Each alert is sent only once. Create a git-ignored `.email` file with these
lines (use a Gmail *app password*):

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-app-password
MAIL_TO=you@gmail.com
```

Without the file, the digest is only written to `data/digest.txt`.

## When a source fails

Websites change or go down. That's normal and nothing breaks:

1. The other sources still update and the dashboard is still published. The failed source keeps
   its offers from the previous check.
2. The dashboard shows a **yellow bar** naming the source.
3. `docs/health.json` shows the details for each source: pages read, offers found, blocks and errors.

**What to do:**

- **Once:** nothing. It's usually fixed by the next run.
- **Several runs in a row:** open the site in a browser.
  - If it has moved or changed design, the reader for that site needs updating (`trips/sources/<site>.py`).
  - If it says "blocked" in `docs/health.json`, the site doesn't want robots. We respect that and
    never get around it, so turn that source off in `config.toml`.
- **Fibula** is never read automatically, so it can't fail. Just re-check it with
  `python -m trips.add_offer --list` about once a week.

**Did the scheduled run work?** In Task Scheduler, the "Last Run Result" means:

| Code | Means |
|---|---|
| 0 | fine |
| 3 | a source failed, but the rest was published |
| 4 | skipped, because the previous run was still going |
| 5 | `git pull --rebase` failed |
| 6 | the commit failed |
| 7 | the push failed |
| anything else | Python crashed |

The log is in `data\logs\run-YYYY-MM-DD.log`.

---

## Technical notes

```powershell
pip install -r requirements.txt
python -m trips.run                 # full run (about 20 min, reads every site)
python -m trips.run --offline       # rebuild from the local database, no internet
$env:PYTHONIOENCODING="utf-8"; python -m unittest discover -s tests -t .
```

- **Run order:** sources → merge → enrich → validate → database → score → export.
  - The price history lives in `data/trips.db`.
  - The dashboard reads `docs/data.json`.
  - Every rule and weight is in `config.toml`.
  - The twins' birthdate is in the git-ignored `config.local.toml`. Without it, the engine
    assumes the oldest age they could be, which is the safe side for cot limits.
- **Drive times:** from the free OSRM router (cached), plus 30 minutes for each border crossing.
  If the router is down, a straight-line estimate is used. It's marked as an estimate and
  retried on the next run.
- **Publishing:** commits only `docs/data.json` and `docs/health.json`, and only when they
  changed. `data\run.lock` stops two runs at once.
- **Being polite:**
  - an honest User-Agent
  - robots.txt obeyed
  - at least 5 seconds between pages on the same site
  - unchanged pages cost the site only a "304 Not Modified"

  The rules are in `trips/sources/__init__.py`. Booking.com, Airbnb, Vrbo, Expedia and Fibula's
  private API are never used.

### Sources

| Source | How |
|---|---|
| Fibula (fibula.com.mk) | **By hand** with `trips.add_offer`. Its robots.txt disallows its price API. |
| Travelland, Olympic (Serbian agencies) | Automatic: Halkidiki, Bansko, Borovets, Pamporovo, Kopaonik. |
| Other Macedonian agencies, Bulgarian ski sites, charters | Automatic, where robots.txt allows it. |
| Hotels' own websites (Sani, Porto Carras, St. Ivan Rilski, …) | Automatic: their campaigns show as 🏨 chips. |
| Oliver's Travels (villas), Micazu (owner apartments), other rentals | Automatic. Self-catering, so capped in summer. |
| Booking.com, Airbnb, Vrbo, Expedia, Wizz Air, Marriott Homes & Villas, WebHotelier engines | ❌ Never: their terms or robots.txt forbid it. |
