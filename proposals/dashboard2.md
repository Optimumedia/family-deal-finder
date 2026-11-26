# Dashboard round 2 (`dashboard2`)

**File changed:** `docs/index.html` only. No Python, config or data changes, so there are no integration diffs.

## What changed
1. **Top picks for us**: a strip above each season's list with up to 4 hotels. Each one has a real 2+2 price and is not ruled out. They are ranked by `family.score`, then `overall`, then price. Each pick has one "why" line built from `family.parts` and the checklist (meals, beach or ski school, kids' club, bedroom, drive or flight), then the deal (a verified or agency %, or a coral deadline when the signal is "book now"). The strip follows the active filters and is hidden while a search is active. When no hotel has a 2+2 price, an empty state asks you to request a 2+2 quote.
2. **Total stay / Per night** toggle: also the `p` key and `?price=night` in the URL. Every price follows it: rows, picks, drawer, offers tables, map popups and compare. The figure not shown sits one line below.
3. **Price basis legend** in the note: 2+2, 2 adults and est., with counts. Items with `family_price_est` show the estimate marked "est." (dashed tag), the `family_price_basis` text and the agency's 2-adult price. They rank between 2+2 and 2-adult prices.
4. **Compare**: you pick up to 4 from the shortlist, using toggles when more than 4 are shortlisted. Its rows are family price, per night, meals, kids' club, beach / ski school, cots, room, drive, signal, verified discount, dates, deadline and source. The best value in each row is green. A 2-adult price is never ranked against a family price, and nothing is marked best from a single known value.
5. **Map**: pins cluster by screen distance and re-cluster on zoom. Each pin is named after its town, or its region when it holds several towns, and shows a count. Colour shows the drive time: under 4h, 4–5h, over 5h, or flight. Popups show photo thumbnails, the best price with its basis, and "Zoom in". There is a legend and a row of "jump to place" buttons. Markers are focusable buttons with labels. Enter opens the popup, focus moves into it and returns to the marker on close.
6. **Edge states:**
   - Savana Travel offers (and any `direct_flight_skp` or "flight from Skopje" offer) show an "incl. flight from Skopje" chip.
   - Those flight offers now pass the drive filter; before this change, all 47 were hidden by default.
   - Summer self-catering shows a warning chip.
   - Placeholder dates show as "Dates on request".
   - The drawer's no-photo placeholder is fixed, and long source names no longer overflow the button.

## Checks
- Served with `python -m http.server 8812 -d docs` and tested at 1440×900 and 390×844.
- No console errors and no horizontal scroll.
- `impeccable detect`: 15 findings, all advisory.

## Known limits
- Picks rank by family fit, so an expensive hotel can be a pick (Sani Beach, €6,144).
- Clustering is a simple greedy pass with no plugin.
