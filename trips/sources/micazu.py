"""Micazu (micazu.com): holiday homes rented directly from the owner. robots.txt only blocks
booking/account/handler paths — region and listing pages are allowed.

A region page links to listings (/vacation-rentals/<country>/<region>/<town>/<name>-<id>/).
A listing page gives, in plain HTML: "1-5 persons", "1 bedroom", the rate table
("From Tue 30-Dec-2025 to Thu 31-Dec-2026 … Week € 525.00 … Night € 75.00"),
cleaning costs, and facilities text (we look for cot / high chair / kitchen).
We only use a rate period that covers the check-in date — an owner who hasn't
entered next season's rates yet is skipped, not guessed.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from urllib.parse import urljoin

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import html_to_text, money

log = logging.getLogger(__name__)
BASE = "https://www.micazu.com"
SOURCE = "Micazu (owner)"
_LISTING = re.compile(r'href="(/vacation-rentals/[a-z-]+/[a-z-]+/[a-z-]+/[a-z0-9-]+-(\d+)/)"')
_PERIOD = re.compile(r"From \w{3} (\d{1,2}-\w{3}-\d{4}) to \w{3} (\d{1,2}-\w{3}-\d{4})(.*?)(?=From \w{3} \d|Additional costs|$)")


def listing_links(html: str) -> list[tuple[str, str]]:
    return list(dict.fromkeys((urljoin(BASE, p), i) for p, i in _LISTING.findall(html)))


def _d(s: str) -> str:
    return datetime.strptime(s, "%d-%b-%Y").date().isoformat()


def parse_listing(html: str) -> dict:
    t = " ".join(html_to_text(html).split())
    title = re.search(r"Share (?:Apartment|House|Villa|Chalet|Holiday home|Bungalow) (.+?) (?:Bulgaria|Greece|Albania|Montenegro|Serbia)", t)
    persons = re.search(r"\b\d+\s*-\s*(\d+) persons", t)
    bedrooms = re.search(r"\b(\d+) bedrooms?\b", t)
    kind = re.search(r"Share (Apartment|House|Villa|Chalet|Holiday home|Bungalow)", t)
    periods = []
    for a, b, body in _PERIOD.findall(t):
        night = re.search(r"Night € ([\d.,]+)", body)
        week = re.search(r"Week € ([\d.,]+)", body)
        periods.append({"from": _d(a), "to": _d(b), "night": money(night.group(1)) if night else None,
                        "week": money(week.group(1)) if week else None})
    clean = re.search(r"Final cleaning € ([\d.,]+)", t)
    return {
        "name": title.group(1).strip() if title else None,
        "kind": (kind.group(1).lower() if kind else "apartment"),
        "max_persons": int(persons.group(1)) if persons else None,
        "bedrooms": int(bedrooms.group(1)) if bedrooms else None,
        "periods": periods,
        "cleaning": money(clean.group(1)) if clean else 0.0,
        "cot": bool(re.search(r"\b(cot|crib|baby bed)\b", t, re.I)),
        "high_chair": bool(re.search(r"high chair", t, re.I)),
        "kitchen": bool(re.search(r"kitchen", t, re.I)),
    }


def to_hotel_and_offer(lst: dict, oid: str, url: str, page: dict, cfg: dict, today: date):
    need = cfg["family"]["adults"] + cfg["family"]["kids"]
    if not lst["name"] or (lst["max_persons"] or 0) < need:
        return None
    check_in = max(str(page.get("check_in", today.isoformat())), today.isoformat())
    nights = int(page.get("nights", 5))
    period = next((p for p in lst["periods"] if p["from"] <= check_in <= p["to"]), None)
    if not period or not (period["night"] or period["week"]):
        return None                                   # no rates entered for those dates yet
    stay = period["week"] * nights / 7 if nights >= 7 and period["week"] else (period["night"] or period["week"] / 7) * nights
    hotel = {
        "id": f"mz-{oid}",
        "kind": "apartment" if lst["kind"] == "apartment" else "villa",
        "name": lst["name"],
        "stars": None,
        "season": page["season"],
        "area": page["area"],
        "country": page.get("country", ""),
        "lat": page["lat"],
        "lng": page["lng"],
        "direct_flight_skp": False,
        "border": True,
        "family": {"separate_bedroom": (lst["bedrooms"] or 0) >= 1, "family_room": True,
                   **({"cots_max": 1} if lst["cot"] else {}), "verified": []},
        "notes": f"Rented from the owner: up to {lst['max_persons']} persons, {lst['bedrooms']} bedroom(s), self-catering."
                 + (" Cot mentioned (likely 1 — ask for a second)." if lst["cot"] else "")
                 + (" High chair available." if lst["high_chair"] else ""),
    }
    offer = {
        "hotel": hotel["id"], "source": SOURCE, "url": url, "seen": today.isoformat(), "check_in": check_in,
        "nights": nights, "board": "SC", "room": f"whole {lst['kind']} ({lst['bedrooms']} bedroom)",
        "occupancy": "2+2", "price_eur": round(stay + lst["cleaning"], 2), "was_eur": None,
        "discount_label": None, "valid_until": None,
    }
    return hotel, offer


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    mz = cfg["sources"].get("micazu", {})
    if not mz.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    hotels, offers = [], []
    for page in mz.get("pages", []):
        try:
            links = listing_links(s.get(page["url"]))[: int(mz.get("max_listings", 15))]
            kept = 0
            for url, oid in links:
                pair = to_hotel_and_offer(parse_listing(s.get(url)), oid, url, page, cfg, today)
                if pair:
                    hotels.append(pair[0])
                    offers.append(pair[1])
                    kept += 1
            log.info("Micazu %s: %d listings, %d with rates for the dates and room for 4", page["area"], len(links), kept)
        except Blocked as e:
            log.warning("Micazu stopped (respecting the block): %s", e)
            break
        except Unavailable as e:
            log.warning("Micazu %s skipped: %s", page["area"], e)
    return hotels, offers
