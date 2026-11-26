"""Pochivka.bg: Bulgaria's big accommodation directory. Owners and aparthotels post their own
price table per unit type, so it adds many Bansko / Razlog / Dobrinishte / Borovets / Pamporovo
apartments that BulgariaSki, Micazu and the agencies don't carry.

robots.txt (pochivka.bg) allows everything except /ajax/, /cgi-bin/, /user3/, /execute/,
/redirects/, /tester*, /backend. We read only the resort's apartment list pages
(/apartamenti-bansko-t6, /apartamenti-bansko-t6/2 …) and the listing pages (/<name>-o<id>).

A list page has 10 cards: link, thumbnail, "from" price and, for single-type listings, the number
of places ("4" + person icon). Cards that say fewer places than our family are skipped without
opening them. A listing page carries, in plain HTML:
- `<table class="prices">` under "*цената е обща за помещението на вечер" (the price is for the
  whole unit per night): one row per unit type (тип, места, брой от типа) and a rate for
  силен летен / слаб летен / силен зимен / слаб зимен / друг сезон (high/low summer, high/low
  winter, other). "не се дава" = not let in that season.
- the description, from which we only take facts: "две спални", "спалнята" … → separate bedroom;
  "кошара" / "бебешко легло" → cot mentioned.
- the listing's own map point (place:location:latitude/longitude) and photo gallery.

Season dates are not published, so a winter stay is priced at the HIGH-winter rate (the low-winter
rate only when no high-winter rate is given) × nights: never lower than what we'd pay.
Prices are EUR (Bulgaria uses the euro since 2026); an old "лв" price is converted at 1.95583.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from html import unescape

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import html_to_text, image_url

log = logging.getLogger(__name__)
BASE = "https://pochivka.bg"
SOURCE = "Pochivka.bg (owner)"
BGN_PER_EUR = 1.95583
SEASONS = ("high_summer", "low_summer", "high_winter", "low_winter", "other")

_CARD = re.compile(r'<div class="result-item">(.*?)(?=<div class="result-item">|<div class="pagination|\Z)', re.S)
_CARD_LINK = re.compile(r'<a href="(https://pochivka\.bg/[a-z0-9-]+-o(\d+))"')
_CARD_PLACES = re.compile(r'<span><span>(\d+)</span><i class="pd-icon-user"')
_PRICES = re.compile(r'<div class="content-block" id="prices".*?<span class="info">(.*?)</span>.*?'
                     r'<table class="prices">(.*?)</table>', re.S)
_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_H1 = re.compile(r'<h1 itemprop="name">(.*?)</h1>', re.S)
_SUB = re.compile(r'<div class="sub-title">(.*?)</div>', re.S)
_LAT = re.compile(r'place:location:latitude"\s+content="([\d.]+)"')
_LNG = re.compile(r'place:location:longitude"\s+content="([\d.]+)"')
_PHOTO = re.compile(r'<div class="pswp-gallery[^"]*".*?<a href="(https://static\.pochivka\.bg/[^"]+?\.jpe?g)[^"]*"', re.S)
_DESC = re.compile(r'<span itemprop="description">(.*?)</span>\s*(?:</div>|<div)', re.S)
_AMEN = re.compile(r"Удобства в .*?(?=телефон е-поща адрес|$)", re.S)

# "двойна спалня" (a double bed) etc. are beds, not rooms: removed before looking for a bedroom.
_BED_NOT_ROOM = re.compile(r"(?:двойна|френска|голяма|единична|разтегателна|разтегаема|спалня-диван)\s+спалня|спалня[- ]диван",
                           re.I)
_BEDROOMS = re.compile(r"\b(една|1|две|2|три|3)\s+(?:отделни\s+|самостоятелни\s+)?спални?\b", re.I)
_BEDROOM = re.compile(r"\bспалнята\b|\b(?:отделна|самостоятелна|обзаведена|уютна|просторна)\s+спалня\b"
                      r"|\bспалня\s+(?:с|със)\s|\bспално помещение\b|\bспалня\s+и\s+(?:всекидневна|хол|дневна)", re.I)
_COT = re.compile(r"кошар|бебешк\w*\s+легл|детск\w*\s+легл|бебешко креватче", re.I)
_NUMWORD = {"една": 1, "две": 2, "три": 3}
# Bulgarian flats are counted in rooms: "двустаен" = living room + 1 bedroom, "тристаен" = + 2.
_ROOMS = re.compile(r"\b(дву|три|четири)стаен\b", re.I)
_ROOMS_BED = {"дву": 1, "три": 2, "четири": 3}
_ROOM_ONLY = re.compile(r"\b(стая|стаи|легло)\b", re.I)


def _rate(cell: str) -> float | None:
    """'46<span…>.</span><sup>02</sup>€' → 46.02 · '130 лв' → 66.47 · 'не се дава' → None."""
    t = " ".join(unescape(re.sub(r"<[^>]+>", "", cell)).split())
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(€|лв)", t)
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return round(v / BGN_PER_EUR, 2) if m.group(2) == "лв" else v


def parse_list(html: str) -> list[dict]:
    """Cards on one resort list page: {url, oid, places (None = several unit types), thumb}."""
    out = []
    for body in _CARD.findall(html):
        link = _CARD_LINK.search(body)
        if not link:
            continue
        places = _CARD_PLACES.search(body)
        out.append({"url": link.group(1), "oid": link.group(2),
                    "places": int(places.group(1)) if places else None})
    return list({c["oid"]: c for c in out}.values())


def parse_listing(html: str) -> dict | None:
    h1, prices = _H1.search(html), _PRICES.search(html)
    if not h1 or not prices:
        return None
    note = " ".join(html_to_text(prices.group(1)).split())
    rows = []
    for tr in _TR.findall(prices.group(2).split("<tbody>", 1)[-1]):
        cells = _TD.findall(tr)
        if len(cells) < 3 + len(SEASONS):
            continue
        places = re.sub(r"\D", "", html_to_text(cells[1]))
        rows.append({"type": " ".join(html_to_text(cells[0]).split()),
                     "places": int(places) if places else 0,
                     "rates": dict(zip(SEASONS, (_rate(c) for c in cells[3:3 + len(SEASONS)])))})
    desc_m = _DESC.search(html)
    desc = " ".join(html_to_text(desc_m.group(1)).split()) if desc_m else ""
    clean = _BED_NOT_ROOM.sub(" ", desc)
    counts = [int(_NUMWORD.get(n.lower(), n)) for n in _BEDROOMS.findall(clean)]
    counts += [_ROOMS_BED[r.lower()] for r in _ROOMS.findall(clean)]
    amen = _AMEN.search(" ".join(html_to_text(html).split()))
    amen = amen.group(0) if amen else ""
    photo, lat, lng = _PHOTO.search(html), _LAT.search(html), _LNG.search(html)
    return {
        "name": " ".join(unescape(re.sub(r"<[^>]+>", "", h1.group(1))).split()),
        "town": " ".join(html_to_text(_SUB.search(html).group(1)).split()) if _SUB.search(html) else "",
        "per_unit_night": "обща за помещението" in note,
        "rows": rows,
        "bedrooms": max(counts) if counts else (1 if _BEDROOM.search(clean) else None),
        "cot": bool(_COT.search(desc)),
        "kids_corner": "детски кът" in amen,
        "kitchen": bool(re.search(r"кухн", amen)),
        "ski_room": "ски гардероб" in amen,
        "lat": float(lat.group(1)) if lat else None,
        "lng": float(lng.group(1)) if lng else None,
        "image": image_url(photo.group(1), BASE) if photo else None,
    }


def winter_rate(rates: dict) -> tuple[float | None, str]:
    if rates.get("high_winter"):
        return rates["high_winter"], "high-winter rate"
    if rates.get("low_winter"):
        return rates["low_winter"], "low-winter rate (no high-winter rate given)"
    return None, ""


def to_hotel_and_offer(lst: dict, oid: str, url: str, page: dict, cfg: dict, today: date):
    need = cfg["family"]["adults"] + cfg["family"]["kids"]
    if not lst or not lst["per_unit_night"]:
        return None                    # a per-person table would need a different sum: not guessed
    nights = int(page.get("nights", 5))
    check_in = max(str(page.get("check_in", today.isoformat())), today.isoformat())
    best = None
    for r in lst["rows"]:
        if r["places"] < need or _ROOM_ONLY.search(r["type"]):
            continue
        rate, basis = winter_rate(r["rates"])
        # an apartment (may have a bedroom) beats a cheaper studio (never has one)
        key = (bool(re.search(r"студио", r["type"], re.I)), rate or 0)
        if rate and (best is None or key < best[0]):
            best = (key, r, rate, basis)
    if not best:
        return None
    _, row, rate, basis = best
    studio = bool(re.search(r"студио", row["type"], re.I))
    fam = {"verified": []}
    if lst["bedrooms"] and not studio:
        fam["separate_bedroom"] = True          # only when the owner's text names a bedroom
    if lst["kids_corner"]:
        fam["kids_corner"] = True
    bits = [f"Owner/aparthotel listing on Pochivka.bg: {row['type']} for {row['places']}, "
            f"price per whole unit per night ({basis}; season dates not published)."]
    if lst["bedrooms"]:
        bits.append(f"Text mentions {lst['bedrooms']} bedroom(s).")
    bits.append("Cot mentioned (how many not stated)." if lst["cot"] else "Cots not mentioned: ask.")
    if lst["ski_room"]:
        bits.append("Ski room.")
    hotel = {
        "id": f"pv-{oid}",
        "name": lst["name"],
        "stars": None,
        "season": page.get("season", "winter"),
        "area": page["area"],
        "country": page.get("country", "BG"),
        "lat": lst["lat"] or page["lat"],
        "lng": lst["lng"] or page["lng"],
        "direct_flight_skp": False,
        "border": page.get("border", True),
        "kind": "apartment",
        "family": fam,
        "image": lst["image"],
        "notes": " ".join(bits),
    }
    offer = {
        "hotel": hotel["id"], "source": SOURCE, "url": url, "seen": today.isoformat(),
        "check_in": check_in, "nights": nights, "board": "SC",
        "room": f"whole {row['type']} (sleeps {row['places']})",
        "occupancy": "2+2",               # whole-unit price for a unit that sleeps ≥ 4
        "price_eur": round(rate * nights, 2), "was_eur": None, "discount_label": None, "valid_until": None,
    }
    return hotel, offer


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    pv = cfg["sources"].get("bg_more", {})
    if not pv.get("enabled"):
        return [], []
    s = session or PoliteSession(max(cfg["sources"]["delay_seconds"], 5), cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    need = cfg["family"]["adults"] + cfg["family"]["kids"]
    hotels, offers, seen = [], [], set()
    for page in pv.get("pages", []):
        try:
            cards = []
            for n in range(1, int(page.get("list_pages", pv.get("list_pages", 2))) + 1):
                html = s.get(page["url"].rstrip("/") + (f"/{n}" if n > 1 else ""))
                got = parse_list(html)
                if not got:
                    break
                cards += got
            cards = [c for c in cards if c["oid"] not in seen and (c["places"] is None or c["places"] >= need)]
            cards = cards[: int(page.get("max_listings", pv.get("max_listings", 12)))]
            kept = 0
            for c in cards:
                seen.add(c["oid"])
                try:
                    pair = to_hotel_and_offer(parse_listing(s.get(c["url"])), c["oid"], c["url"], page, cfg, today)
                except Unavailable as e:
                    log.warning("Pochivka.bg %s skipped: %s", c["url"], e)
                    continue
                if pair:
                    hotels.append(pair[0])
                    offers.append(pair[1])
                    kept += 1
            log.info("Pochivka.bg %s: %d listings opened, %d with a winter price for 4", page["area"], len(cards), kept)
        except Blocked as e:
            log.warning("Pochivka.bg stopped (respecting the block): %s", e)
            break
        except Unavailable as e:
            log.warning("Pochivka.bg %s skipped: %s", page["area"], e)
    return hotels, offers
