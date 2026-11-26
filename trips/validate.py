"""Check every offer before it is stored, so one broken parser can't poison the price history.

    good, rejects = validate.split(sightings, today, cfg)
    log_rejects(rejects)

Each reject is {"offer": <offer dict>, "reasons": ["...", ...]}. Limits can be tuned in an
optional [validate] table in config.toml; the defaults below are used otherwise.
"""
from __future__ import annotations

import logging
import math
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
}


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


def problems(o: dict, today: date, lim: dict | None = None) -> list[str]:
    """Reasons this offer must not be stored (empty list = fine)."""
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

    ci = _as_date(o.get("check_in"))
    if ci is None:
        out.append(f"check_in {o.get('check_in')!r} is not a date")
    else:
        horizon = add_months(today, int(lim["max_months_ahead"]))
        if ci < today:
            out.append(f"check_in {ci} is in the past")
        elif ci > horizon:
            out.append(f"check_in {ci} more than {lim['max_months_ahead']} months ahead")

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
    return out


def split(offers: list[dict], today: date, cfg: dict | None = None) -> tuple[list[dict], list[dict]]:
    lim = limits(cfg)
    good, rejects = [], []
    for o in offers:
        why = problems(o, today, lim)
        if why:
            rejects.append({"offer": o, "reasons": why})
        else:
            good.append(o)
    return good, rejects


def bad_image(h: dict) -> bool:
    """A hotel photo we must not hotlink (anything not https). The caller sets it to None."""
    img = h.get("image")
    return img is not None and not (isinstance(img, str) and img.startswith("https://"))


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
