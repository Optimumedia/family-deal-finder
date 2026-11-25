# Surface brief: dashboard (docs/index.html)

Mode: Operate. Laptop-first decision tool for two parents; phone must work.
Job: narrow ~75 offers per season to a shortlist, compare, open the source offer to book.
Content: docs/data.json (offers with photo, price, was-price, occupancy 2+2|2+0, board, nights, drive minutes, family checklist, deal verdict, valid-until, hotel-site campaigns, email draft).
Constraints: static HTML/vanilla JS, Leaflet 1.9.4 from cdnjs for the map, photos hotlinked with placeholder fallback; honesty states (2 adults only, board unknown, not yet checked) stay visible.
Unresolved: none.

## Direction contract

THESIS: The travel-results page everyone already knows (Booking/Airbnb/Kayak), executed better: one row per hotel with its best comparable offer, the real family price and its honesty qualifier leading, and a Kayak-style price-insight strip replacing unexplained "was" badges. Refuses the category's habits of mixing 2-adult "from" prices with family prices, fake urgency, and duplicate hotel rows.

OWN-WORLD: White ground, cool off-white page #F5F8F8; sea teal #0B6E70 header, buttons, selection; deep teal #084C4E text accents; coral #E4573D for discounts and deadlines only; sand #FFE3A3 price-insight highlight; ink #12262B, muted #566A6F, hairline #DCE5E5. Onest for everything, tabular figures for prices. Rounded 12px photo corners, 8px controls, soft offset shadows. One authored SVG icon set, 1.75 stroke.

STORY: Parents see which hotels truly fit the twins and what the family really pays, spot which discounts are only the agency's claim, shortlist 2–4, compare side by side, and open the source offer or send the hotel their questions.

FIRST VIEWPORT: Teal header (brand, Summer/Winter tabs, family chip "2 adults + twins · from Skopje", updated time). Below, a white summary bar (dates · nights · guests · 5h drive rule). Left 280px rail: mini map card, then filters with counts. Main column: result count + sort tabs + List/Map switch, then hotel rows (4:3 photo left 260px, name/stars/area/chips/fit checklist centre, price block right with coral badge, struck was, big price, qualifier, insight strip, See offer). Shortlist tray pinned bottom when non-empty.

FORM: Category standard (canon), chosen by the user over the roll; seed key c216c5bc.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
