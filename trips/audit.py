"""Data-quality audit of the published offers (docs/data.json) and the local store (data/trips.db).

    python -m trips.audit                      # ranked report on screen + docs/audit.json
    python -m trips.audit --today 2026-11-26   # audit as of another day

Read-only: it never changes the data. Each check returns findings with a count, a few examples,
the likely cause and the file that owns the fix. Rules that are clearly invalid data also live
in trips/validate.py (so they stop at the door); the audit adds the softer "looks wrong" checks
that need the whole data set (outliers, duplicates, mismatched nights, unreachable areas).
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import tomllib
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from statistics import median

from . import validate

SEVERITY = {"high": 3, "medium": 2, "low": 1}
MAX_EXAMPLES = 5

# Area words → ISO country. Country names first, so "Stara Planina, Serbia" is RS (the range
# also crosses Bulgaria).
AREA_COUNTRY = [
    ("north macedonia", "MK"), ("bulgaria", "BG"), ("serbia", "RS"), ("greece", "GR"), ("turkey", "TR"),
    ("montenegro", "ME"), ("albania", "AL"),
    ("ohrid", "MK"), ("bansko", "BG"), ("borovets", "BG"), ("pamporovo", "BG"), ("razlog", "BG"),
    ("kopaonik", "RS"), ("halkidiki", "GR"), ("kassandra", "GR"), ("sithonia", "GR"), ("thassos", "GR"),
    ("olympic riviera", "GR"), ("kavala", "GR"), ("stavros", "GR"), ("athos", "GR"),
    ("antalya", "TR"), ("kusadasi", "TR"), ("alanya", "TR"), ("kemer", "TR"),
    ("ulcinj", "ME"), ("dobre vode", "ME"), ("durr", "AL"), ("vlor", "AL"),
]
# Rough lat/lng boxes (lat_min, lat_max, lng_min, lng_max): only catches gross mix-ups.
COUNTRY_BOX = {
    "GR": (34.8, 41.8, 19.3, 29.7), "BG": (41.2, 44.3, 22.3, 28.7), "RS": (42.2, 46.2, 18.8, 23.1),
    "MK": (40.8, 42.4, 20.4, 23.1), "ME": (41.8, 43.6, 18.4, 20.4), "AL": (39.6, 42.7, 19.2, 21.1),
    "TR": (35.8, 42.2, 25.6, 44.9),
}
SUMMER_MONTHS = range(5, 11)          # May–Oct
WINTER_MONTHS = (11, 12, 1, 2, 3, 4)  # Nov–Apr
ACRONYMS = {"MPM", "HMG", "SPA", "AI", "STD", "APT", "LUX", "VIP", "II", "III", "IV"}
FAMILY_UNFIT = re.compile(r"adults?[ -]only|\b1[2-8]\+|nudist|naturist|nudisti", re.I)
EX_NAME = re.compile(r"\(\s*ex\b|\bex\.?\s+[A-ZŠČĆŽ]", re.I)
PLACEHOLDER_IMG = validate.PLACEHOLDER_IMAGE
SMALL_IMG = re.compile(r"_thumb_(\d+)x\d+|[?&](?:w|width)=(\d+)\b|profile=(?:sm|xs|thumb)|/(?:small|thumbs?)/", re.I)
# Which config section feeds which source name (for the configured nights per page).
SECTION_SOURCES = {
    "travelland": ["Travelland"], "olympic": ["Olympic"], "mk_agencies": ["AtlantiS (MK)"],
    "bgski": ["BulgariaSki"], "charters": ["Savana Travel"],
    "kopaonik": ["JAT Apartmani (own site)", "Supernova Travel"], "rentals": ["Clickstay"],
    "oliverstravels": ["Oliver's Travels"], "micazu": ["Micazu (owner)"],
}


# ------------------------------------------------------------------ helpers ---

def per_night(it: dict) -> float | None:
    try:
        return float(it["price_eur"]) / int(it["nights"])
    except (TypeError, ValueError, ZeroDivisionError, KeyError):
        return None


def expected_country(area: str | None) -> str | None:
    a = (area or "").lower()
    return next((c for word, c in AREA_COUNTRY if word in a), None)


def norm(name: str | None) -> str:
    from .run import norm_name          # same normaliser the merge uses
    return norm_name(name or "")


def _ex(it: dict, **extra) -> dict:
    """A short example row for the report."""
    out = {"source": it.get("source"), "hotel": it.get("name"), "area": it.get("area"),
           "check_in": it.get("check_in"), "nights": it.get("nights"), "price_eur": it.get("price_eur")}
    out.update(extra)
    return out


def finding(check: str, severity: str, title: str, cause: str, owner: str, rows: list[dict],
            examples: list[dict] | None = None, action: str = "") -> dict | None:
    if not rows:
        return None
    by_src = Counter(str(r.get("source")) for r in rows)
    return {"check": check, "severity": severity, "title": title, "count": len(rows),
            "by_source": dict(by_src.most_common()), "cause": cause, "owner": owner, "action": action,
            "examples": (examples if examples is not None else rows)[:MAX_EXAMPLES]}


def configured_nights(cfg: dict) -> dict[tuple[str, str], set[int]]:
    """(source name, area) → nights configured for that page."""
    out: dict[tuple[str, str], set[int]] = defaultdict(set)
    for section, names in SECTION_SOURCES.items():
        for page in (cfg.get("sources", {}).get(section) or {}).get("pages", []):
            for n in names:
                for area in {page.get("area"), page.get("region")} - {None}:
                    out[(n, area)].add(int(page.get("nights", 7)))
    return out


# ------------------------------------------------------------------- checks ---

def check_dates(items, hotels, cfg, today):
    lim = validate.limits(cfg)
    horizon = validate.add_months(today, int(lim["max_months_ahead"]))
    past, far, season, same_day = [], [], [], []
    for it in items:
        ci = validate._as_date(it.get("check_in"))
        if ci is None:
            continue
        if ci < today:
            past.append(_ex(it, last_seen=it.get("last_seen")))
        elif ci > horizon:
            far.append(_ex(it))
        s = it.get("season")
        if (s == "summer" and ci.month not in SUMMER_MONTHS) or (s == "winter" and ci.month not in WINTER_MONTHS):
            season.append(_ex(it, season=s))
        if str(it.get("check_in")) == str(it.get("first_seen"))[:10]:
            same_day.append(_ex(it, first_seen=it.get("first_seen")))
    return [
        finding("past_check_in", "high", "Check-in date already passed",
                "The offer stays in data/trips.db after its date and build() exports every stored offer; "
                "validate only stops past dates at insert time.",
                "trips/db.py offers() / trips/run.py build()", past,
                action="Skip offers with check_in < today when building (diff in proposals/quality.md)."),
        finding("check_in_is_scrape_date", "medium", "Check-in = the day it was scraped",
                "The parser had no usable date and fell back to today (max(date_from, today)). Nobody "
                "books a ski week for the same afternoon; the price is for the agency's own window.",
                "trips/sources/travelland.py:142", same_day,
                action="Use the page's configured check_in when the card's window already started."),
        finding("check_in_too_far", "high", "Check-in more than 18 months ahead",
                "Year guessed wrong when parsing a date.", "the source parser", far),
        finding("wrong_season", "high", "Check-in month doesn't match the season",
                "Summer offer dated in winter (or the reverse): year/season rollover in the parser.",
                "the source parser", season),
    ]


def check_nights(items, hotels, cfg, today):
    want = configured_nights(cfg)
    rows = []
    for it in items:
        conf = set()
        for (src, area), n in want.items():
            if src == it.get("source") and area and area in str(it.get("area")):
                conf |= n
        if conf and it.get("nights") not in conf:
            rows.append(_ex(it, configured=sorted(conf), room=str(it.get("room"))[:60]))
    return [finding("nights_mismatch", "medium", "Stay length differs from the page's configured nights",
                    "Savana's cheapest 'from' price is often a 6-night stay; Supernova's early-season "
                    "columns have a 3-night minimum stay. Prices for different stay lengths are compared "
                    "per night by the scorer but listed side by side on the dashboard.",
                    "trips/sources/charters.py:99, trips/sources/kopaonik.py:309", rows,
                    action="Prefer the configured stay length when the card lists it; otherwise keep, but label.")]


def check_prices(items, hotels, cfg, today):
    groups: dict[tuple, list] = defaultdict(list)
    for it in items:
        pn = per_night(it)
        if pn:
            groups[(it.get("season"), it.get("occupancy"), it.get("kind") or "hotel")].append(pn)
    med = {k: median(v) for k, v in groups.items() if len(v) >= 5}
    low, high = [], []
    for it in items:
        pn = per_night(it)
        m = med.get((it.get("season"), it.get("occupancy"), it.get("kind") or "hotel"))
        if not pn or not m:
            continue
        unit = re.search(r"\(([^()]*)\)\s*$", str(it.get("room")))
        ex = _ex(it, eur_per_night=round(pn), peer_median=round(m), unit=unit.group(1) if unit else None)
        if pn < m / 2.5:
            low.append(ex)
        elif pn > m * 3:
            high.append(ex)
    return [
        finding("price_low_outlier", "low", "Per-night price far below similar offers (< median / 2.5)",
                "Usually a per-person or per-day price read as a whole unit/stay (check the unit text), "
                "or a 2-3 night minimum stay priced as a week.",
                "the source parser (unit multiplier)", low),
        finding("price_high_outlier", "low", "Per-night price far above similar offers (> 3 × median)",
                "Large luxury villas (sleeps 8-12) priced for the whole house: real, but never a family deal; "
                "or a per-stay price multiplied by nights.",
                "trips/sources/oliverstravels.py, trips/sources/rentals.py", high,
                action="Cap villas by bedrooms/sleeps (e.g. ≤ 4 bedrooms) in the parser."),
    ]


def check_discounts(items, hotels, cfg, today):
    bad, huge, label_off = [], [], []
    for it in items:
        p, w = it.get("price_eur"), it.get("was_eur")
        if w is None or p is None:
            continue
        if w <= p:
            bad.append(_ex(it, was_eur=w))
            continue
        pct = (w - p) / w * 100
        if pct > validate.DEFAULTS["max_discount_pct"]:
            huge.append(_ex(it, was_eur=w, pct=round(pct)))
        m = re.findall(r"-\s*(\d{1,2})\s*%", str(it.get("discount_label") or ""))
        stated = sum(int(x) for x in m)
        if len(m) == 1 and abs(stated - pct) > 6:
            label_off.append(_ex(it, was_eur=w, computed_pct=round(pct), label=it.get("discount_label")))
    return [
        finding("was_not_above_price", "high", "'Was' price not above the price",
                "Old/new price swapped or read from different cards.", "the source parser", bad),
        finding("discount_too_big", "high", "Discount above 80%",
                "Old price per stay vs new price per night (or per person vs per unit).", "the source parser", huge),
        finding("discount_label_mismatch", "low", "Stated % differs from the was/price difference",
                "The badge % and the struck-through price disagree (rounded or a stacked discount).",
                "the source parser", label_off),
    ]


def check_names(items, hotels, cfg, today):
    ex_rows, caps, stars, unfit = [], [], [], []
    seen = set()
    for it in items:
        hid, name = it.get("hotel_id"), str(it.get("name") or "")
        if hid in seen:
            continue
        seen.add(hid)
        if EX_NAME.search(name):
            ex_rows.append(_ex(it))
        words = [w for w in re.findall(r"[A-ZŠČĆŽĐ]{4,}", name) if w not in ACRONYMS]
        if words:
            caps.append(_ex(it, caps=words))
        st = it.get("stars")
        if st is not None and not (isinstance(st, int) and 1 <= st <= 5):
            stars.append(_ex(it, stars=st))
        if FAMILY_UNFIT.search(name) and not it.get("excluded"):
            unfit.append(_ex(it, excluded=it.get("excluded")))
    # same hotel listed with different star counts by one source (Savana lists a hotel per star category)
    by_name: dict[tuple, set] = defaultdict(set)
    first: dict[tuple, dict] = {}
    for it in items:
        k = (it.get("source"), norm(it.get("name")), str(it.get("area")).split(",")[0])
        by_name[k].add(it.get("stars"))
        first.setdefault(k, it)
    multi = [_ex(first[k], stars=sorted(s, key=lambda x: x or 0)) for k, s in by_name.items() if len(s) > 1]
    return [
        finding("family_unfit_name", "high", "Adults-only / naturist property shown as a fit",
                "The name says adults only (or naturist) but no rule excludes it; family facts are unknown "
                "so the score only caps it.", "trips/score.py (or the source parser)", unfit,
                action="Set family.adults_only = True when the name matches and fail the hard rule."),
        finding("name_ex_suffix", "low", "'(ex. Old name)' left in the hotel name",
                "Agencies append the former name; it breaks cross-source matching and looks messy.",
                "trips/sources/travelland.py:112, trips/sources/olympic.py:89, trips/sources/bgski.py, "
                "trips/sources/kopaonik.py (page name)", ex_rows,
                action="Strip r'\\s*\\(\\s*ex\\.?[^)]*\\)' like charters._clean_name does; keep it in notes."),
        finding("name_allcaps", "low", "ALL-CAPS word in a hotel name", "Title-casing skipped for that source.",
                "the source parser", caps),
        finding("stars_invalid", "medium", "Stars outside 1-5", "Star count parsed from the wrong element.",
                "the source parser", stars),
        finding("stars_conflict", "medium", "Same hotel with different star counts in one source",
                "Savana lists the same hotel under 2 star categories (separate slugs → separate hotel ids); "
                "one of the star counts is wrong (Derici 4* and 1*).", "trips/sources/charters.py:135", multi,
                action="Drop the star number from the slug when building the id, keep the higher star count."),
    ]


def check_geo(items, hotels, cfg, today):
    wrong, box, far = [], [], []
    reach = cfg.get("reach", {})
    limit = reach.get("max_drive_minutes", 300) + reach.get("tolerance_minutes", 45)
    far_areas: dict[str, list] = defaultdict(list)
    seen = set()
    for it in items:
        hid = it.get("hotel_id")
        h = hotels.get(hid, {})
        exp = expected_country(it.get("area"))
        c = h.get("country")
        if hid not in seen:
            seen.add(hid)
            if exp and c and c != exp:
                wrong.append(_ex(it, country=c, expected=exp))
            lat, lng = it.get("lat"), it.get("lng")
            b = COUNTRY_BOX.get(exp or c or "")
            if b and lat is not None and lng is not None and not (b[0] <= lat <= b[1] and b[2] <= lng <= b[3]):
                box.append(_ex(it, lat=lat, lng=lng, country=exp or c))
        dm = (it.get("family") or {}).get("drive_minutes")
        if dm and dm > limit and not h.get("direct_flight_skp"):
            far_areas[str(it.get("area"))].append(it)
    for area, its in sorted(far_areas.items(), key=lambda kv: -len(kv[1])):
        dm = round(max((i.get("family") or {}).get("drive_minutes") or 0 for i in its))
        for i in its:
            far.append(_ex(i, drive_minutes=dm))
    far_examples = [{"area": a, "offers": len(v), "drive_minutes": round(max((i.get("family") or {}).get("drive_minutes") or 0 for i in v)),
                     "sources": dict(Counter(i.get("source") for i in v))} for a, v in
                    sorted(far_areas.items(), key=lambda kv: -len(kv[1]))]
    return [
        finding("country_mismatch", "high", "Hotel country doesn't match its area",
                "Page config copied with the wrong country, or a hotel merged into one from another page.",
                "config.toml page / trips/run.py merge_auto", wrong),
        finding("coords_outside_country", "medium", "Coordinates outside the area's country",
                "Wrong pin from the map script or lat/lng swapped.", "the source parser", box),
        finding("outside_drive_radius", "medium", f"Area beyond the drive limit ({limit} min incl. tolerance)",
                "These pages are scraped every run but every offer is excluded (drive too long, no direct "
                "flight): wasted polite requests and clutter in data.json.",
                "config.toml (integrator)", far, examples=far_examples,
                action="Disable those pages (or mark them direct_flight_skp when a charter exists)."),
    ]


def check_duplicates(items, hotels, cfg, today):
    exact: dict[tuple, list] = defaultdict(list)
    named: dict[tuple, list] = defaultdict(list)
    cross: dict[tuple, set] = defaultdict(set)
    for it in items:
        exact[(it.get("source"), it.get("hotel_id"), it.get("check_in"), it.get("nights"), it.get("board"),
               it.get("price_eur"))].append(it)
        n = norm(it.get("name"))
        named[(it.get("source"), n, it.get("check_in"), it.get("nights"), it.get("board"), it.get("price_eur"))].append(it)
        if n:
            cross[(it.get("season"), n, str(it.get("area")).split(",")[0])].add(it.get("hotel_id"))
    rows_exact = [_ex(v[0], copies=len(v), rooms=[str(x.get("room"))[:40] for x in v]) for v in exact.values() if len(v) > 1]
    rows_named = [_ex(v[0], copies=len(v), hotel_ids=sorted({x.get("hotel_id") for x in v}))
                  for v in named.values() if len({x.get("hotel_id") for x in v}) > 1]
    first = {}
    for it in items:
        first.setdefault((it.get("season"), norm(it.get("name")), str(it.get("area")).split(",")[0]), it)
    rows_cross = [_ex(first[k], hotel_ids=sorted(v)) for k, v in cross.items() if len(v) > 1
                  and not any(r["hotel"] == first[k].get("name") for r in rows_named)]
    return [
        finding("duplicate_offer", "medium", "Same hotel, dates, board and price twice from one source",
                "Two room labels for one price; both rows count as peers and inflate the hotel.",
                "the source parser", rows_exact),
        finding("duplicate_listing", "medium", "Same hotel listed under two ids by one source (same price)",
                "Savana publishes one card per star category; Olympic lists some hotels twice "
                "(two object ids). Both survive because the hotel id comes from the slug/object id.",
                "trips/sources/charters.py:135 (id from slug incl. star count)", rows_named,
                action="Key the hotel id on the name + town, not on the star-category slug."),
        finding("same_name_two_ids", "low", "One name, one area, several hotel ids",
                "merge_auto only folds into a known hotel when names match; ids from the same source are "
                "never merged (Olympic object ids, Savana slugs with/without 'otel-').",
                "trips/run.py merge_auto / the source parser", rows_cross),
    ]


def check_images(items, hotels, cfg, today):
    ph, small, shared = [], [], []
    by_url: dict[str, set] = defaultdict(set)
    seen = set()
    for it in items:
        img = it.get("image")
        if not img or it.get("hotel_id") in seen:
            continue
        seen.add(it.get("hotel_id"))
        by_url[img].add(norm(it.get("name")).split(" ")[0] if norm(it.get("name")) else it.get("hotel_id"))
        if PLACEHOLDER_IMG.search(img):
            ph.append(_ex(it, image=img))
            continue
        m = SMALL_IMG.search(img)
        if m:
            size = next((int(g) for g in m.groups() if g), None)
            if size is None or size < 400:
                small.append(_ex(it, image=img))
    for it in items:
        img = it.get("image")
        if img and len(by_url.get(img, ())) > 1 and not any(r.get("image") == img for r in shared):
            shared.append(_ex(it, image=img, names=sorted(by_url[img])))
    return [
        finding("placeholder_image", "medium", "Placeholder image used as the hotel photo",
                "The agency's 'no photo' default thumbnail was taken as the photo.",
                "trips/sources/mk_agencies.py (card image) → now nulled by validate.bad_image", ph),
        finding("small_image", "low", "Thumbnail-size photo (< 400 px)", "The card thumbnail was taken instead of the "
                "large photo (profile=sm, _thumb_ sizes).", "trips/sources/oliverstravels.py, olympic/travelland", small),
        finding("image_shared", "low", "One photo for differently named hotels",
                "Card photo reused across listings (Savana star-category duplicates).", "the source parser", shared),
    ]


def check_kopaonik(items, hotels, cfg, today):
    """Supernova prices are RSD per unit, converted at [sources.kopaonik] rsd_per_eur. A rate far from
    the real one (≈117 RSD/EUR, kept stable by the central bank) shifts every Serbian price; a unit
    price outside a sane band means a per-person or per-stay table was read as per unit per night."""
    rate = float((cfg.get("sources", {}).get("kopaonik") or {}).get("rsd_per_eur", 117.2))
    sn = [it for it in items if it.get("source") == "Supernova Travel"]
    bad_rate = [{"source": "Supernova Travel", "rsd_per_eur": rate, "offers": len(sn)}] if sn and not 110 <= rate <= 125 else []
    band = []
    for it in sn:
        pn = per_night(it) or 0
        if not 30 <= pn <= 600:
            band.append(_ex(it, eur_per_night=round(pn), rsd_per_night=round(pn * rate)))
    return [
        finding("rsd_rate_off", "high", "RSD/EUR rate in config looks wrong",
                "rsd_per_eur outside 110-125; every Supernova price is off by the same factor.",
                "config.toml [sources.kopaonik]", bad_rate),
        finding("rsd_out_of_band", "high", "Supernova unit price outside €30-600/night",
                "Per-person ('PO OSOBI') or per-stay table read as per night.", "trips/sources/kopaonik.py:189", band),
    ]


def check_db(items, hotels, con) -> list:
    if con is None:
        return []
    orphans = [{"source": r[1], "hotel": r[0], "check_in": r[2]} for r in con.execute(
        "SELECT o.hotel_id, o.source, o.check_in FROM offer o LEFT JOIN hotel h ON h.id = o.hotel_id WHERE h.id IS NULL")]
    no_snap = [{"source": r[1], "hotel": r[0]} for r in con.execute(
        "SELECT o.hotel_id, o.source FROM offer o LEFT JOIN snapshot s ON s.offer_key = o.key "
        "WHERE s.offer_key IS NULL")]
    no_country = [{"source": "hotel table", "hotel": hid, "area": h.get("area")} for hid, h in hotels.items()
                  if not h.get("country")]
    return [
        finding("orphan_offer", "medium", "Stored offer for a hotel that isn't in the hotel table",
                "Hotel id changed in the source (slug/object id) while old offers stayed.", "trips/db.py", orphans),
        finding("offer_without_price", "medium", "Stored offer with no price snapshot",
                "Interrupted insert.", "trips/db.py add_sighting", no_snap),
        finding("hotel_without_country", "low", "Hotel without a country", "Page config lacks `country`.",
                "config.toml", no_country),
    ]


def as_offer(it: dict) -> dict:
    """A data.json item back in the shape validate expects (a source sighting)."""
    return {"hotel": it.get("hotel_id"), "source": it.get("source"), "url": it.get("url"),
            "seen": it.get("last_seen"), "check_in": it.get("check_in"), "nights": it.get("nights"),
            "board": it.get("board"), "room": it.get("room"), "occupancy": it.get("occupancy"),
            "price_eur": it.get("price_eur"), "was_eur": it.get("was_eur")}


def check_revalidate(items, hotels, cfg, today):
    """Stored offers are validated once, on the way in: rows saved before a rule existed (or before it
    was tightened) stay in the DB and keep being published. Past check-ins have their own finding."""
    _, rejects = validate.split([as_offer(i) for i in items], today, cfg, hotels or None)
    by_key = {(i.get("hotel_id"), i.get("check_in"), i.get("room"), i.get("source")): i for i in items}
    rows = []
    for r in rejects:
        why = [w for w in r["reasons"] if "in the past" not in w]
        if why:
            o = r["offer"]
            it = by_key.get((o["hotel"], o["check_in"], o["room"], o["source"]), {})
            rows.append(_ex(it, reasons=why))
    return [finding("fails_validation", "high", "Stored offer fails today's validate rules",
                    "Saved before the rule existed or was tightened; the DB is never re-validated, so it is "
                    "published on every run until it is deleted.",
                    "trips/run.py build() (re-run validate.problems on stored offers)", rows,
                    action="Skip (and log) stored offers that fail validate.problems in build().")]


CHECKS = (check_revalidate, check_dates, check_nights, check_prices, check_discounts, check_names, check_geo, check_duplicates,
          check_images, check_kopaonik)


def audit(items: list[dict], hotels: dict[str, dict], cfg: dict, today: date, con=None) -> dict:
    found = [f for chk in CHECKS for f in chk(items, hotels, cfg, today) if f]
    found += [f for f in check_db(items, hotels, con) if f]
    found.sort(key=lambda f: (-SEVERITY[f["severity"]], -f["count"]))
    return {"today": today.isoformat(), "offers": len(items), "hotels": len({i.get("hotel_id") for i in items}),
            "problems": sum(f["count"] for f in found), "findings": found}


def render(rep: dict) -> str:
    lines = [f"Data audit {rep['today']}: {rep['offers']} offers, {rep['hotels']} hotels, "
             f"{len(rep['findings'])} kinds of problem ({rep['problems']} rows)", ""]
    for n, f in enumerate(rep["findings"], 1):
        src = ", ".join(f"{k} {v}" for k, v in f["by_source"].items())
        lines.append(f"{n:>2}. [{f['severity'].upper()}] {f['title']} — {f['count']}  ({src})")
        lines.append(f"    cause: {f['cause']}")
        lines.append(f"    fix in: {f['owner']}" + (f" — {f['action']}" if f.get("action") else ""))
        for e in f["examples"][:3]:
            lines.append("      · " + ", ".join(f"{k}={v}" for k, v in e.items() if v is not None))
        lines.append("")
    return "\n".join(lines)


def load(data_path: str | Path, db_path: str | Path | None):
    items = json.loads(Path(data_path).read_text(encoding="utf-8")).get("items", [])
    con, hotels = None, {}
    if db_path and Path(db_path).exists():
        con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
        hotels = {r[0]: json.loads(r[1]) for r in con.execute("SELECT id, data FROM hotel")}
    return items, hotels, con


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Audit docs/data.json and data/trips.db for data problems.")
    ap.add_argument("--data", default="docs/data.json")
    ap.add_argument("--db", default="data/trips.db")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--out", default="docs/audit.json")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD (default: today)")
    args = ap.parse_args(argv)
    cfg = tomllib.loads(Path(args.config).read_text(encoding="utf-8"))
    today = date.fromisoformat(args.today) if args.today else date.today()
    items, hotels, con = load(args.data, args.db)
    rep = audit(items, hotels, cfg, today, con)
    if con is not None:
        con.close()
    print(render(rep))
    if args.out:
        small = {**rep, "findings": [{**f, "examples": f["examples"][:2]} for f in rep["findings"]]}
        head = [f" {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in small.items() if k != "findings"]
        rows = ["  " + json.dumps(f, ensure_ascii=False) for f in small["findings"]]   # one finding per line
        text = "{\n" + ",\n".join(head) + ',\n "findings": [\n' + ",\n".join(rows) + "\n ]\n}\n"
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
