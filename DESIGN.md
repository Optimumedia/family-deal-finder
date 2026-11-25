---
name: Family Deal Finder
description: The familiar travel-results page, built around one family's non-negotiables and honest prices.
colors:
  sea-teal: "#0B6E70"
  deep-teal: "#084C4E"
  teal-mist: "#E2F1F0"
  teal-edge: "#9FCFCC"
  claim-coral: "#A8331C"
  claim-coral-wash: "#FDE9E4"
  coral-flare: "#E4573D"
  sand: "#FFE3A3"
  ink: "#12262B"
  ink-soft: "#3E5257"
  muted: "#566A6F"
  page: "#F5F8F8"
  surface: "#FFFFFF"
  sunk: "#EEF3F3"
  hairline: "#DCE5E5"
  hairline-strong: "#C7D4D4"
  good: "#176B3A"
  good-wash: "#E3F3E8"
  warn: "#8A5300"
  warn-wash: "#FFF1D6"
  bad: "#B42318"
  bad-wash: "#FDE8E6"
typography:
  price:
    fontFamily: "Onest, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "27px"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.02em"
    fontFeature: "\"tnum\" 1"
  headline:
    fontFamily: "Onest, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "22px"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.015em"
  title:
    fontFamily: "Onest, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "19px"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Onest, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
    fontFeature: "\"tnum\" 1"
  body-small:
    fontFamily: "Onest, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Onest, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "12.5px"
    fontWeight: 600
    lineHeight: 1.35
rounded:
  s: "8px"
  m: "12px"
  l: "16px"
  pill: "999px"
spacing:
  hair: "4px"
  tight: "6px"
  sm: "8px"
  md: "12px"
  row: "14px"
  panel: "18px"
  page: "24px"
components:
  button-primary:
    backgroundColor: "{colors.sea-teal}"
    textColor: "{colors.surface}"
    rounded: "{rounded.s}"
    padding: "9px 14px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.deep-teal}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.s}"
    padding: "9px 14px"
    height: "40px"
  button-secondary-hover:
    backgroundColor: "{colors.sunk}"
  segment-selected:
    backgroundColor: "{colors.sea-teal}"
    textColor: "{colors.surface}"
    rounded: "{rounded.pill}"
    padding: "7px 13px"
  chip:
    backgroundColor: "{colors.sunk}"
    textColor: "{colors.ink-soft}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "3px 9px"
  chip-good:
    backgroundColor: "{colors.good-wash}"
    textColor: "{colors.good}"
  chip-warn:
    backgroundColor: "{colors.warn-wash}"
    textColor: "{colors.warn}"
  badge-claim:
    backgroundColor: "{colors.claim-coral-wash}"
    textColor: "{colors.claim-coral}"
    rounded: "6px"
    padding: "3px 8px"
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.m}"
  hotel-row:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.l}"
    padding: "12px"
  header:
    backgroundColor: "{colors.sea-teal}"
    textColor: "{colors.surface}"
---

# Design System: Family Deal Finder

## Overview

**Creative North Star: "The Honest Results Page"**

This is the travel-results page everyone already knows from Booking, Airbnb and Kayak, kept deliberately familiar and executed with more care. A solid sea-teal header carries the brand and season tabs; a white summary bar restates the search; a filter rail sits left and hotel rows stack in the main column. Nothing about the layout asks to be learned. The craft goes into the price block, where every number comes with its qualifier and a price-insight strip instead of an unexplained "was" badge.

The ground is white and cool off-white, light only. Teal is the colour of action and selection; coral is reserved for what an agency claims and what is about to run out; sand marks the middle of the price-insight bar. Density is moderate: laptop-first rows that show photo, fit checklist and price at once, collapsing to a single column on a phone.

Honesty states are visual citizens, not footnotes: hollow rings for unverified answers, dashed rings for unknowns, dashed "ask" chips, and amber qualifiers for 2-adult prices all use the same system tokens as everything else.

**Key Characteristics:**
- Category-standard results layout: teal header, summary bar, 288px filter rail, hotel rows.
- White surfaces on a cool off-white page, separated by hairlines and two soft shadows.
- One typeface (Onest) for everything, tabular figures on by default.
- Pills for anything you toggle; 8/12/16px corners for things you press, frame or read.
- One authored inline SVG icon set at 1.75 stroke.

## Colors

A cool, low-chroma neutral field with one action colour (sea teal), one claim colour (coral) and a semantic trio for fit and verdicts.

### Primary
- **Sea Teal** (sea-teal): the header band, primary buttons, selected sort and view segments, checkbox and range accents, text selection, focus outline, and near-drive map pins.
- **Deep Teal** (deep-teal): links, hotel names, text buttons ("Show on map", "Reset"), and primary-button hover.
- **Teal Mist** (teal-mist) with **Teal Edge** (teal-edge): the explanatory note banner, the no-photo placeholder gradient, map-button hover, and "differs" cells in the compare table.

### Secondary
- **Claim Coral** (claim-coral) on **Claim Coral Wash** (claim-coral-wash): the "Agency says −30%" discount badge, campaign names, and "ends in N days" deadlines. This is the AA-safe text value of the coral.
- **Coral Flare** (coral-flare): the filled heart on a shortlisted hotel, and nothing else.

### Tertiary
- **Sand** (sand): the middle stop of the price-insight bar (good-wash → sand → bad-wash) and the whole bar when a price is not yet checked.

### Neutral
- **Ink** (ink): body text, the price, the insight-bar marker, and the dark shortlist tray.
- **Ink Soft** (ink-soft): secondary text such as area lines, checklist items and chip text.
- **Muted** (muted): captions, counts, struck "was" prices, "stated" verdicts.
- **Page** (page): the page ground and the email textarea.
- **Surface** (surface): every panel, row, bar, dialog and segmented control.
- **Sunk** (sunk): neutral chips, secondary-button hover, photo wells, the dialog close button.
- **Hairline** (hairline) and **Hairline Strong** (hairline-strong): borders and dividers; the strong value is for button borders, row hover and dashed empty states.

### Semantic
- **Good / Good Wash**: real discounts, verified fit marks, half-board-or-better chips.
- **Warn / Warn Wash**: drive-time-over-rule chips, 2-adult-only price qualifiers, stale data.
- **Bad / Bad Wash**: failed must-haves, "fake discount" verdicts, the expensive end of the insight bar.

### Named Rules
**The Claim Colour Rule.** Coral is only for what an agency claims (discounts, campaigns) and what runs out (deadlines), plus the shortlisted heart. It never marks a button, a link, or a selection.

**The Teal Means You Can Act Rule.** Sea teal fills only things you can press or have selected: the header, primary buttons, selected segments, form accents, focus. Body text is never teal; links and names are deep teal.

## Typography

**Display Font:** Onest (with system-ui, -apple-system, Segoe UI, Roboto, sans-serif)
**Body Font:** Onest (same stack)

**Character:** One friendly, slightly rounded grotesk, used at 400–800 for the whole interface; weight, not a second face, does the hierarchy. Tabular figures are set on the body so prices, counts and dates align everywhere.

### Hierarchy
- **Price** (800, 27px, line-height 1, −0.02em): the family price in each row's price block. The heaviest thing on any row.
- **Brand** (800, 20px, −0.01em): the header wordmark only.
- **Headline** (700, 22px, 1.25, −0.015em; 19px under 720px): the results heading ("Summer 2027: 70 hotels for us"). Dialog headings use 18px.
- **Title** (700, 19px, 1.25, −0.01em): hotel names in deep teal.
- **Body** (400, 15px, 1.5): base text; the note banner and filter options run at 14px.
- **Body Small** (400, 13–13.5px): area lines, fit checklist, legend, campaign lines.
- **Label** (600, 12.5px): chips, discount badge, qualifiers, verdicts. Summary-bar field captions use 12px 400 muted above a 14.5px 600 value.

### Named Rules
**The Weight Does It Rule.** Hierarchy comes from weight and size within Onest; there is no second typeface and no uppercase label style.

**The Figures Line Up Rule.** Tabular figures stay on globally (`font-feature-settings: "tnum" 1` on body); never switch prices to proportional figures.

## Layout

Centred container at 1440px max with 24px side padding (16px under 720px). Below the teal header, the summary bar sits in its own 16px-padded strip. The main area is a two-column grid: a 288px sticky rail (top 16px, scrolls within the viewport) and a fluid results column, 24px apart.

Hotel rows are a three-column grid: photo (220px; 200px under 1180px) at 4:3, a flexible middle column, and a price block (250px; 210px under 1180px) divided from the middle by a hairline and right-aligned. Rows stack with 14px gaps; panels and rows pad 12–18px.

Responsive steps: under 1000px the rail becomes static, the map card hides and filters collapse behind a "Filters" button. Under 720px rows become one column with a 16:10 photo, the price block moves below a top hairline and left-aligns, its actions sit side by side, the summary bar shows only When and Prices checked, the "who" line in the header hides, and sort tabs scroll horizontally. Touch pointers raise options and segments to 44px.

Spacing rhythm is small-step: 4, 6, 8, 12, 14, 18, 24px, with 120px of bottom padding so the shortlist tray never covers the last row.

## Elevation & Depth

A light hybrid: surfaces are white on an off-white page, bounded by hairlines, and carry one of two soft, ink-tinted, blurred shadows. Shadows are low and diffuse; there are no hard offsets.

### Shadow Vocabulary
- **Rest** (`box-shadow: 0 1px 2px rgba(18,38,43,.06), 0 2px 8px rgba(18,38,43,.05)`): summary bar, rail panels, hotel rows, map frame.
- **Lifted** (`box-shadow: 0 2px 4px rgba(18,38,43,.08), 0 10px 28px rgba(18,38,43,.12)`): hotel-row hover, the shortlist tray, dialogs.
- **Floating control** (`box-shadow: 0 1px 4px rgba(0,0,0,.18)`): the heart button over a photo.

### Named Rules
**The Lift on Hover Rule.** Rows rest at the Rest shadow and move to Lifted on hover (with a stronger hairline), over 0.2s ease. Nothing else changes elevation on interaction.

## Shapes

Three corner sizes keyed to role: 8px for controls (buttons, textarea, compare thumbnails), 12px for photos, panels, the summary bar and the note banner, 16px for hotel rows, the map frame, empty states and dialogs. Anything toggled or counted is a full pill: season-tab tops, sort and view segments, chips, count bubbles, the kind tag and the shortlist tray. Circles are for the heart, the dialog close button and fit marks. The discount badge alone uses 6px. Dashed borders mean "unknown / to ask": the ask chip, unknown fit marks and the empty state.

## Components

### Buttons
Plain, solid and quietly rounded.
- **Shape:** gently rounded (8px), 40px minimum height (36px inside the price block).
- **Primary:** sea-teal fill, white 600 14px text, 9px 14px padding; hover to deep teal. Used for "See offer", "Copy email", "Compare".
- **Secondary:** white with a strong hairline border, ink text; hover to sunk.
- **Text button:** deep-teal 600 13–13.5px, underlined at 3px offset, no fill ("Reset").
- **Focus:** global 3px sea-teal outline at 2px offset.

### Segmented controls
- **Style:** a white pill track with a hairline border and 4px inner padding; segments are 600 13.5px ink-soft text.
- **State:** selected segment fills sea teal with white text; unselected hover fills sunk. Used for sort order and List/Map.

### Chips
- **Style:** pill, 12.5px 600, 3px 9px, optional 14px icon. Neutral on sunk; good, warn and bad variants use their wash with the matching text colour.
- **Ask chip:** transparent with a dashed strong hairline, for facts still to confirm with the hotel.

### Cards / Containers
- **Hotel row:** white, 16px corners, 12px padding, hairline border, Rest shadow lifting to Lifted on hover. Excluded rows drop to 72% opacity.
- **Panel:** white, 12px corners, hairline, Rest shadow; used for the map card and filters, with filter groups split by hairlines and 14px 18px padding.
- **Note banner:** teal mist with a teal-edge border, 12px corners, info icon in deep teal.

### Inputs / Fields
- **Checkboxes and range:** native controls with sea-teal accent colour, 18px boxes, option rows with right-aligned muted counts.
- **Textarea:** page-coloured fill, strong hairline border, 8px corners, 14px/1.5 text.

### Navigation
- **Header:** full-width sea-teal band; white 800 wordmark beside a white rounded-square home mark; season tabs below in pale teal-white (#D9F0EE) text with pill-topped hover fills and a 3px white underline on the selected tab; translucent white count bubbles.
- **Summary bar:** a white 12px-cornered strip of icon + caption + value cells divided by hairlines, the last cell pushed right.

### Price block (signature)
Right column of every row: coral claim badge, struck muted "was", the 27px 800 family price, an ink-soft qualifier (warn and 600 when it is a 2-adult price), muted per-night line, then the price-insight strip: an 8px pill bar graded good-wash → sand → bad-wash with a white, ink-ringed 14px marker (a centre tick and solid sand when not yet checked), a muted caption, a verdict line in good, muted or bad, and the actions.

### Fit checklist
A two-column list (one column on phones) of 14px circular marks: solid good with a check for confirmed, hollow good ring for agency-stated but unverified, dashed muted ring for unknown, solid bad with a cross for failed.

### Shortlist tray
Dark ink pill fixed bottom-centre, white text, Lifted shadow, pill buttons inside; rises in over 0.35s on first appearance.

## Do's and Don'ts

### Do:
- **Do** keep every price beside its qualifier (who it covers, board, nights, source); a 2-adult price shows its qualifier in warn 600.
- **Do** use sea teal for press-and-select only, and deep teal for links and hotel names.
- **Do** draw icons from the inline SVG sprite: 24px viewBox, 1.75 stroke, round caps and joins, currentColor, 18px by default.
- **Do** mark unknowns with dashed outlines and unverified answers with hollow rings, using the same semantic tokens as confirmed states.
- **Do** keep elevation to the Rest and Lifted shadows, lifting rows on hover.
- **Do** honour reduced motion: transitions switch off under `prefers-reduced-motion`.

### Don't:
- **Don't** use coral for buttons, links or selection; it belongs to claims, deadlines and the shortlisted heart.
- **Don't** add a dark theme; the product is light only by the owner's choice.
- **Don't** introduce a second typeface or proportional figures for prices.
- **Don't** use hard, unblurred offset shadows; depth here is soft and ink-tinted.
- **Don't** show a "was" price or discount without the insight strip and verdict that say whether it is real.
