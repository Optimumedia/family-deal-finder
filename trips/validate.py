"""Check every offer before it is stored, so one broken parser can't poison the price history.

    good, rejects = validate.split(sightings, today, cfg)            # offer-only rules
    good, rejects = validate.split(sightings, today, cfg, hotels)    # + season and duplicate-listing rules

Each reject is {"offer": <offer dict>, "reasons": ["...", ...]}. Limits can be tuned in an
optional [validate] table in config.toml; the defaults below are used otherwise.
`hotels` (id -> hotel dict) is optional: with it, a check-in outside the hotel's season and the
same price listed twice under two ids of one hotel (same source, same name) are rejected too.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from datetime import date

log = logging.getLogger(__name__)

KNOWN_BOARDS = frozenset({"RO", "BB", "HB", "FB", "AI", "SC", "?"})
OCCUPANCIES = frozenset({"2+2", "2+0"})
DEFAULTS = {
    # Whole-stay price divided by nights. Below ~€15 is a per-person or per-day price read
    # as a stay; above ~€2,500 is usually a misplaced decimal (or a palace, which we don't need).
    "min_eur_per_night": 15.0,
    "max_eur_per_night": 2500.0,
    "max_months_ahead": 18,
    "min_nights": 1,
    "max_nights": 21,
    # A "was" price must be above the price, and no real discount takes off more than this:
    # beyond it the old price is per stay and the new one per night (or per person vs per unit).
    "max_discount_pct": 80.0,
}
SEASON_MONTHS = {"summer": frozenset(range(5, 11)), "winter": frozenset({11, 12, 1, 2, 3, 4})}
# Agencies' "no photo" defaults (e.g. atlantisonline.mk/ExtraContent/Img/listdefaultthumb.png).
PLACEHOLDER_IMAGE = re.compile(r"placeholder|no[-_]?image|no[-_]?photo|default[-_]?(?:thumb|img|image)|"
                               r"listdefault|blank\.(?:png|gif|jpe?g)|spacer\.gif|1x1\.(?:png|gif)", re.I)


def limits(cfg: dict | None = None) -> dict:
    return {**DEFAULTS, **((cfg or {}).get("validate") or {})}


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):          # 31 Jan + 1 month -> 28/29 Feb
        try:
            return date(y, m, day)
        except ValueError:
            continue
    raise ValueError(d)


def _as_date(v) -> date | None:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _whole(v) -> int | None:
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if math.isfinite(f) and f == int(f) else None


def problems(o: dict, today: date, lim: dict | None = None, hotel: dict | None = None) -> list[str]:
    """Reasons this offer must not be stored (empty list = fine). With `hotel`, also its season."""
    lim = lim or DEFAULTS
    out = []
    nights = _whole(o.get("nights"))
    if nights is None:
        out.append(f"nights {o.get('nights')!r} is not a whole number")
    if nights is not None and not lim["min_nights"] <= nights <= lim["max_nights"]:
        out.append(f"nights {nights} outside {lim['min_nights']}–{lim['max_nights']}")

    try:
        price = float(o.get("price_eur"))
        if not math.isfinite(price):
            raise ValueError
    except (TypeError, ValueError):
        price = None
        out.append(f"price {o.get('price_eur')!r} is not a number")
    if price is not None:
        if price <= 0:
            out.append(f"price €{price:g} is not positive")
        elif nights and lim["min_nights"] <= nights <= lim["max_nights"]:
            per = price / nights
            if per < lim["min_eur_per_night"]:
                out.append(f"€{per:,.0f}/night below €{lim['min_eur_per_night']:,.0f} (per-person price read as a stay?)")
            elif per > lim["max_eur_per_night"]:
                out.append(f"€{per:,.0f}/night above €{lim['max_eur_per_night']:,.0f} (decimal misread?)")
    was = o.get("was_eur")
    if was is not None and price is not None and price > 0:
        try:
            was = float(was)
            if not math.isfinite(was):
                raise ValueError
        except (TypeError, ValueError):
            out.append(f"was {o.get('was_eur')!r} is not a number")
        else:
            if was <= price:
                out.append(f"was €{was:g} not above price €{price:g} (old/new swapped?)")
            elif (was - price) / was * 100 > lim["max_discount_pct"]:
                out.append(f"was €{was:g} is {(was - price) / was:.0%} off, above {lim['max_discount_pct']:g}% "
                           "(old price per stay, new per night?)")

    ci = _as_date(o.get("check_in"))
    if ci is None:
        out.append(f"check_in {o.get('check_in')!r} is not a date")
    else:
        horizon = add_months(today, int(lim["max_months_ahead"]))
        if ci < today:
            out.append(f"check_in {ci} is in the past")
        elif ci > horizon:
            out.append(f"check_in {ci} more than {lim['max_months_ahead']} months ahead")
        season = (hotel or {}).get("season")
        if season in SEASON_MONTHS and ci.month not in SEASON_MONTHS[season]:
            out.append(f"season {season} but check_in {ci} (month {ci.month}) is outside it")

    if o.get("board") not in KNOWN_BOARDS:
        out.append(f"board {o.get('board')!r} not one of {'/'.join(sorted(KNOWN_BOARDS))}")
    if o.get("occupancy", "2+2") not in OCCUPANCIES:
        out.append(f"occupancy {o.get('occupancy')!r} not 2+2 or 2+0")
    url = o.get("url")
    if not (isinstance(url, str) and url.startswith("https://") and len(url) > len("https://")):
        out.append(f"url {url!r} is not https")
    img = o.get("image")
    if img is not None and not (isinstance(img, str) and img.startswith("https://")):
        out.append(f"image {img!r} is not https")
    elif img is not None and PLACEHOLDER_IMAGE.search(img):
        out.append(f"image {img!r} is a placeholder")
    return out


def _dup_keys(o: dict, hotel: dict | None) -> list[tuple]:
    """Same source, dates, board and price: under one hotel id (two room labels for one price), or —
    with the hotel known — under two ids of the same-named hotel in one area (Savana lists a hotel
    once per star category)."""
    base = (o.get("source"), str(o.get("check_in")), o.get("nights"), o.get("board"), o.get("price_eur"))
    keys = [("id", o.get("hotel"), *base)]
    if hotel and hotel.get("name"):
        from .run import norm_name                     # lazy: run imports this module
        keys.append(("name", norm_name(hotel["name"]), str(hotel.get("area", "")).split(",")[0], *base))
    return keys


def split(offers: list[dict], today: date, cfg: dict | None = None,
          hotels: dict[str, dict] | None = None) -> tuple[list[dict], list[dict]]:
    lim = limits(cfg)
    hotels = hotels or {}
    good, rejects, seen = [], [], {}
    for o in offers:
        h = hotels.get(o.get("hotel"))
        why = problems(o, today, lim, h)
        if not why:
            keys = _dup_keys(o, h)
            first = next((seen[k] for k in keys if k in seen), None)
            if first is not None:
                why = [f"duplicate of {first.get('hotel')} / {first.get('room')!r} (same source, dates, board, price)"]
            else:
                seen.update({k: o for k in keys})
        if why:
            rejects.append({"offer": o, "reasons": why})
        else:
            good.append(o)
    return good, rejects


def bad_image(h: dict) -> bool:
    """A hotel photo we must not hotlink or show: not https, or an agency's "no photo" placeholder.
    The caller sets it to None."""
    img = h.get("image")
    if img is None:
        return False
    return not (isinstance(img, str) and img.startswith("https://")) or bool(PLACEHOLDER_IMAGE.search(img))


def by_source(rejects: list[dict]) -> dict[str, dict]:
    """{source: {"rejected": n, "reasons": {reason-kind: n}}} for the health report."""
    out: dict[str, dict] = {}
    for r in rejects:
        src = str(r["offer"].get("source") or "?")
        e = out.setdefault(src, {"rejected": 0, "reasons": Counter()})
        e["rejected"] += 1
        for why in r["reasons"]:
            e["reasons"][_kind(why)] += 1
    return {s: {"rejected": e["rejected"], "reasons": dict(e["reasons"])} for s, e in out.items()}


def _kind(reason: str) -> str:
    w = reason.split()
    if "/night" in reason:
        return "price per night"
    return w[0] if w else reason


def log_rejects(rejects: list[dict], limit: int = 20) -> None:
    if not rejects:
        return
    log.warning("%d offer(s) rejected by validation, not stored", len(rejects))
    for r in rejects[:limit]:
        o = r["offer"]
        log.warning("  rejected %s | %s | %s: %s", o.get("source"), o.get("hotel"), o.get("check_in"),
                    "; ".join(r["reasons"]))
    if len(rejects) > limit:
        log.warning("  … and %d more", len(rejects) - limit)
