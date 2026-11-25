# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Delegated: plain static HTML/CSS/vanilla JS in `docs/`, served by GitHub Pages, reading `docs/data.json`. No build step, so the twice-daily local run (Python → data.json → git push) keeps publishing it with nothing else to maintain, at €0. Third-party code only from cdnjs (Leaflet 1.9.4 for the map).

## Users

Two parents in Skopje, North Macedonia, planning family holidays for themselves and their twins (born October 2023). They use it **mostly on a laptop** in planning sessions, comparing many offers side by side, and sometimes open it on a phone. It's personal: not shared with other people, though the page is public on GitHub Pages.

## Product Purpose

It finds vacation offers that fit this specific family and shows whether a discount is real. The engine collects offers from travel agencies, hotels' own websites, villa rentals and owner rentals. It applies the family's hard rules, scores Family Fit and Deal quality, records a price history, and drafts questions to send to hotels. Success: the parents can book a summer beach holiday and a winter ski holiday that fit the twins, at a discount they know is real, without trawling ten sites.

## Positioning

It's like Booking.com, but built around one family's non-negotiables instead of an inventory:
- Reachable from Skopje: a direct flight or at most 5 hours' drive.
- 2 cots that take the twins at their age on the travel date.
- Breakfast and dinner in summer; a separate bedroom in winter.
- Discounts checked against its own recorded price history, not the agency's "was" price.

No OTA does any of these.

## Operating Context

- Data refreshes at 13:00 and 17:30 when the home PC is on.
- Fibula (the main Skopje agency) is entered by hand, because its prices sit behind robots-blocked APIs.
- Each card links to the source offer, where booking happens. The dashboard never books.
- Seasons: Summer (Halkidiki, Olympic Riviera, Thassos: sandy beaches, half board) and Winter (Bansko, Borovets, Pamporovo, Kopaonik: 1-bedroom apartments, 2 cots, ski kindergarten).

## Capabilities and Constraints

**Sources:**
- Agencies: Olympic and Travelland (automatic), Fibula (manual).
- Hotels' own offers pages: campaigns.
- Oliver's Travels villas and Micazu owner rentals.

**Each offer has:**
- price and "was" price
- board: BB / HB / FB / AI / SC (self-catering) / unknown
- occupancy: 2+2 (real family price) or 2+0 (2 adults only, kids' price unknown)
- discount label and valid-until date
- price history
- drive time from Skopje
- family checklist: yes / no / unknown, verified or not
- tier, score, and questions for the hotel

**Hard rules:**
- Hotels that break a must-have are excluded.
- Unknown must-haves cap the rating.

**Constraints:**
- Never scrape sites whose robots.txt or terms forbid it.
- Many prices are "from" prices for 2 adults without board. That uncertainty must stay visible, not be dressed up.
- The twins' birthdate stays in git-ignored `config.local.toml` and is never published.

## Brand Commitments

The name is "Family Deal Finder". Its voice is honest and plain: it says when something is unverified, unknown, or "for 2 adults only". It has no logo or brand assets.

Standing visual preference (chosen 2026-11-25): the familiar travel-site pattern (Booking.com-style results), executed better rather than a novelty world. White ground with sea teal and coral, not Booking's navy, blue and yellow. Quality bar: Airbnb, Booking.com, Kayak.

## Evidence on Hand

- Real data in `docs/data.json`: about 149 offers across summer and winter.
- Agency hotel photos are hotlinked from the agencies' own image servers. They're never re-hosted, and each card links back to the source.
- There are no testimonials, reviews or partner relationships, and none should be invented.

## Product Principles

1. **Family fit before price:** a cheap offer that can't take the twins isn't a deal.
2. **Honesty over polish:** show unknowns, "2 adults only" and unverified discounts openly.
3. **Real discounts only:** our own price history outranks any "was" price.
4. **One glance, then depth:** the comparison is scannable, with the detail one step away.
5. **The parents stay in control:** nothing is booked or sent for them.

## Accessibility & Inclusion

No specific requirement was stated. Baseline: readable at laptop distance, works on a phone, keyboard accessible, WCAG AA contrast. Light only, by choice: the user asked for a white ground (2026-11-25), so there's deliberately no dark theme.
