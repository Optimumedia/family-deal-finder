"""Kajak.mk: a Macedonian accommodation portal (hosts list their own apartments, villas and small
hotels; requests go to the host, it is not a Booking/Airbnb reseller). Covers the places near
Skopje: Mavrovo, Popova Šapka, Kruševo, Pelister (Bitola region) in winter; Ohrid, Struga and
Dojran in summer.

robots.txt allows everything except account, reservation, /search, /api/, /ajax/ and a few other
endpoints. We read only the region lists (/smestuvanja/<id>-<region>?Page=N) and the listing
pages (/smestuvanje/<slug>).

A region list gives cards: place label ("Mavrovo"), title, "Цена од 4,900.00 ден" (from-price per
night in MKD) and sometimes a "МОМЕТАЛНО НЕ РАБОТАТ" (closed for now) badge. Every list also
carries promoted cards from other regions, so cards are kept only when their place label matches
the page's `location` (and the optional `title_match` regex, used for Pelister inside the Bitola
region).

A listing page adds the facts we need, in Macedonian or English:
* "СЕ ИЗНАЈМУВА ЦЕЛО СМЕСТУВАЊЕ" / "ENTIRE ACCOMMODATION IS RENTED" — the whole unit is rented;
* "Макс. Капацитет : 4" — max guests;
* the "Вклучено во цена" / "Included in price" list, which says what the price is:
  "Цена за 4 лица: 2.200 ден" (price for 4 people), "по лице" (per person), "за двајца"
  / "Цена за 2 лица" (for two), "Наем на цел објект: 2.000 – 4.000" (whole place, a range);
* the description: bedrooms ("две спални соби", "Една спална соба", "separate bedroom"),
  studios, a minimum stay ("минимум 2 ноќевања", "minimum of three nights"), breakfast.

The site picks its edition from Accept-Language: "mk,en" gets the English edition, which lists
only the translated subset. fetch() therefore asks for "mk" on its own session. English pages
still parse ("Price from … mkd", "4 guests: ~€36" lines are read as a price for 4).

Price rules (nothing guessed):
1. A "price for N people" line with N ≥ family size → that price, occupancy "2+2".
2. Else, a whole-unit rental for 4+ guests with no per-person / for-two wording → the
   from-price, "2+2" (it is the price of the unit).
3. Per person → from-price × adults, "2+0". For two / anything else → from-price, "2+0".
Units for fewer guests than the family, and whole villas for more than `max_capacity` guests
(party houses), are skipped. All prices are "from" prices with dates on request; the stay length
is the page's `nights` (or the listing's minimum stay if longer).
"""
from __future__ import annotations

import logging
import re
from datetime import date
from html import unescape

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import html_to_text, image_url, money

log = logging.getLogger(__name__)
SOURCE = "Kajak.mk"
BASE = "https://kajak.mk"
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "seven": 7,
         "една": 1, "еден": 1, "две": 2, "два": 2, "три": 3, "четири": 4, "пет": 5}

_CARD_SPLIT = '<div class="card shadow-sm'
_CARD_LINK = re.compile(r'<a href="(https://kajak\.mk/smestuvanje/[^"]+)" class="font-weight-bold">\s*(.*?)\s*</a>', re.S)
_CARD_LOC = re.compile(r'fa-map-marker-alt mr-1"></span>\s*([^<]+?)\s*</a>')
_CARD_PRICE = re.compile(r'text-primary mb-0 mt-n1">\s*([\d.,]+)\s*(?:ден|mkd)', re.I)
_CARD_IMG = re.compile(r'<img class="card-img-top[^"]*" src="([^"]+)"')
_PAGES = re.compile(r'(\d+)\s+(?:од|of)\s+(\d+)')


def mkd(s: str) -> float:
    """'3,075.00' → 3075 · '2.200.00' → 2200 · '6.159' → 6159 · '1.800' → 1800."""
    s = re.sub(r"[.,]00$", "", s.strip())
    return money(s)


def _slug(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def parse_list(html: str) -> tuple[list[dict], int]:
    """Cards on one region list page, and how many list pages the region has."""
    cards = []
    for block in html.split(_CARD_SPLIT)[1:]:
        link, price = _CARD_LINK.search(block), _CARD_PRICE.search(block)
        if not link or not price:
            continue
        loc, img = _CARD_LOC.search(block), _CARD_IMG.search(block)
        cards.append({
            "url": link.group(1),
            "title": " ".join(unescape(link.group(2)).split()),
            "location": unescape(loc.group(1)).strip() if loc else "",
            "price_mkd": mkd(price.group(1)),
            "closed": "НЕ РАБОТАТ" in block or "badge-danger" in block,
            "image": image_url(img.group(1), BASE) if img else None,
        })
    pages = _PAGES.search(html)
    return cards, int(pages.group(2)) if pages else 1


def _section(html: str, start: str, ends: tuple[str, ...]) -> str:
    i = html.find(start)
    if i < 0:
        return ""
    j = min([k for k in (html.find(e, i + len(start)) for e in ends) if k > 0] or [len(html)])
    return html[i + len(start):j]


def _li(html: str) -> list[str]:
    return [" ".join(unescape(re.sub(r"<[^>]+>", " ", x)).split()) for x in re.findall(r"(?s)<li>(.*?)</li>", html)]


def _count(word: str) -> int | None:
    return int(word) if word.isdigit() else WORDS.get(word.lower())


def parse_listing(html: str) -> dict:
    head = html[:html.find('<h2 class="text-primary">')] if '<h2 class="text-primary">' in html else ""
    title = re.search(r'<h2 class="text-primary">\s*(.*?)\s*</h2>', html, re.S)
    price = re.search(r'(?:Цена од|Price from):</small>\s*<h3[^>]*>\s*([\d.,]+)\s*(?:ден|mkd)', html, re.I)
    cap = re.search(r'(?:Капацитет|Capacity)\s*</span>\s*<span[^>]*>\s*:\s*(\d+)', html)
    og = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    inc = _li(_section(html, "Вклучено во цена:", ("Не е вклучено",))
              or _section(html, "Included in price:", ("Not included",)))
    exc = _li(_section(html, "Не е вклучено во цена:", ("</ul>",))
              or _section(html, "Not included in price:", ("</ul>",)))
    body = html[cap.end():] if cap else html
    desc = html_to_text(_section(body, "", ("ЛОКАЦИЈА", "LOCATION", "Остави Рецензија", "Leave a comment")) or body)
    price_text = " · ".join(inc)
    t = f"{price_text} {desc}"

    per_n = {}
    for n, amount in re.findall(r"(?:Цена за|Price for)\s*(\d+)\s*(?:лица|лице|persons?|people|guests?)\s*:?\s*([\d.,]+)",
                                price_text, re.I):
        per_n[int(n)] = mkd(amount)
    per_n_eur = {int(n): float(eur) for n, eur in
                 re.findall(r"\b(\d+)\s*(?:guests?|persons?|people|лица)\s*:\s*~?\s*€\s*(\d+(?:\.\d+)?)", price_text, re.I)}
    rng = re.search(r"([\d.,]{3,})\s*[–-]\s*([\d.,]{3,})\s*(?:денари|ден)", price_text)
    min_n = re.search(r"минимум\s*(?:од\s*)?(\d+|\w+)\s*(?:ноќ|ноќевањ)|minimum (?:of )?(\d+|\w+)\s*nights?", t, re.I)
    title_s = " ".join(unescape(title.group(1)).split()) if title else ""
    tl = title_s.lower()
    studio = bool(re.search(r"студи|studio", tl))
    bedroom = bool(re.search(r"спалн\w*\s+соб|bedroom|двособ|тривособ", t, re.I))
    kind = "hotel" if re.search(r"хотел|hotel", tl) else "villa" if re.search(r"вила|villa|викендиц|куќ", tl) else "apartment"
    if re.search(r"полупансион|half board", t, re.I):
        board = "HB"
    elif re.search(r"појадок\s*:?\s*вклучен|breakfast (?:is )?included", t, re.I):
        board = "BB"
    elif any(re.search(r"^(?:храна|food)$", x, re.I) for x in exc):
        board = "SC"
    else:
        board = "?"
    return {
        "title": title_s,
        "price_mkd": mkd(price.group(1)) if price else None,
        "entire": "ЦЕЛО СМЕСТУВАЊЕ" in head or "ENTIRE ACCOMMODATION" in head,
        "closed": "НЕ РАБОТАТ" in head or "badge-danger" in head,
        "capacity": int(cap.group(1)) if cap else None,
        "price_text": price_text,
        "per_n": per_n,
        "per_n_eur": per_n_eur,
        "per_person": bool(re.search(r"по лице|по особа|по човек|per person", price_text, re.I)),
        "for_two": bool(re.search(r"за двајца|за 2 лица|for two|for 2 (?:persons|people)", price_text, re.I)),
        "range_mkd": (mkd(rng.group(1)), mkd(rng.group(2))) if rng else None,
        "min_nights": _count(next(g for g in min_n.groups() if g)) if min_n else None,
        "separate_bedroom": False if studio and not re.search(r"апартман|apartment", tl) else True if bedroom else None,
        "kind": kind,
        "board": board,
        "image": image_url(og.group(1), BASE) if og else None,
    }


def to_hotel_and_offer(card: dict, info: dict, page: dict, cfg: dict, today: date):
    """None when the listing can't host the family or has no readable price."""
    adults, need = cfg["family"]["adults"], cfg["family"]["adults"] + cfg["family"]["kids"]
    kc = cfg["sources"].get("mk_local", {})
    rate = float(kc.get("mkd_per_eur", 61.5))
    max_cap = int(page.get("max_capacity", kc.get("max_capacity", 8)))
    cap = info.get("capacity")
    if info.get("closed") or not cap or cap < need:
        return None
    if info["entire"] and info["kind"] != "hotel" and cap > max_cap:
        return None
    base = info.get("price_mkd") or card.get("price_mkd")
    per_n = {**{n: eur * rate for n, eur in info.get("per_n_eur", {}).items()}, **info["per_n"]}
    fam_n = sorted(n for n in per_n if n >= need)
    if fam_n:
        night, occ, basis = per_n[fam_n[0]], "2+2", f"price for {fam_n[0]} people"
    elif not base:
        return None
    elif info["per_person"]:
        night, occ, basis = base * adults, "2+0", "per person × 2 adults; kids' price on request"
    elif info["entire"] and not info["for_two"] and not per_n:
        night, occ, basis = base, "2+2", f"whole unit, up to {cap} guests"
    else:
        night, occ, basis = base, "2+0", "from-price for 2; ask the price for 2 adults + 2 small kids"
    nights = max(int(page.get("nights", 5 if page["season"] == "winter" else 7)), info.get("min_nights") or 0)
    check_in = max(str(page.get("check_in", today.isoformat())), today.isoformat())
    hid = f"kj-{_slug(card['url'])[:60]}"
    notes = [f"Kajak.mk listing ({basis}): from {night:,.0f} MKD/night, converted at {rate} MKD/EUR; "
             "dates and final price on request from the host."]
    if info.get("range_mkd"):
        lo, hi = info["range_mkd"]
        notes.append(f"Listed range {lo:,.0f}–{hi:,.0f} MKD/night (higher in season and holidays).")
    if info.get("min_nights"):
        notes.append(f"Minimum stay {info['min_nights']} nights.")
    if info["separate_bedroom"] is None and info["kind"] != "hotel":
        notes.append("Ask whether the bedroom is separate.")
    hotel = {
        "id": hid, "name": info.get("title") or card["title"], "stars": None,
        "season": page["season"], "area": page["area"], "country": page.get("country", "MK"),
        "lat": page["lat"], "lng": page["lng"], "direct_flight_skp": False,
        "border": bool(page.get("border", False)), "kind": info["kind"],
        "family": {"separate_bedroom": info["separate_bedroom"], "verified": []},
        "image": info.get("image") or card.get("image"), "notes": " ".join(notes),
    }
    offer = {
        "hotel": hid, "source": SOURCE, "url": card["url"], "seen": today.isoformat(),
        "check_in": check_in, "nights": nights, "board": info["board"],
        "room": f"{'whole unit' if info['entire'] else 'room/unit'}, up to {cap} guests (from-price, dates on request)",
        "occupancy": occ, "price_eur": round(night * nights / rate, 2), "was_eur": None,
        "discount_label": None, "valid_until": None,
    }
    return hotel, offer


def _wanted(card: dict, page: dict) -> bool:
    if card["closed"] or card["location"].lower() != str(page.get("location", "")).lower():
        return False
    pat = page.get("title_match")
    return not pat or bool(re.search(pat, card["title"], re.I))


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    kc = cfg["sources"].get("mk_local", {})
    if not kc.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    # The site answers "mk,en" with its English edition, which lists only the translated subset
    # (Dojran: 18 of ~40). Ask for Macedonian on this source's own session (run.py gives each source one).
    if hasattr(s, "s"):
        s.s.headers["Accept-Language"] = kc.get("accept_language", "mk")
    hotels, offers = {}, []
    for page in kc.get("pages", []):
        try:
            picked, seen = [], set()
            max_pages = int(page.get("max_list_pages", kc.get("max_list_pages", 2)))
            max_listings = int(page.get("max_listings", kc.get("max_listings", 15)))
            n, total = 1, 1
            while n <= min(total, max_pages) and len(picked) < max_listings:
                cards, total = parse_list(s.get(page["url"] if n == 1 else f"{page['url']}?Page={n}"))
                for c in cards:
                    if c["url"] not in seen and _wanted(c, page):
                        seen.add(c["url"])
                        picked.append(c)
                n += 1
            got = 0
            for c in picked[:max_listings]:
                try:
                    res = to_hotel_and_offer(c, parse_listing(s.get(c["url"])), page, cfg, today)
                except (Unavailable, ValueError) as e:
                    log.warning("Kajak %s skipped: %s", c["url"], e)
                    continue
                if res:
                    hotels[res[0]["id"]] = res[0]
                    offers.append(res[1])
                    got += 1
            log.info("Kajak %s: %d listings read, %d offers", page["area"], len(picked[:max_listings]), got)
        except Blocked as e:
            log.warning("Kajak stopped (respecting the block): %s", e)
            break
        except (Unavailable, ValueError) as e:
            log.warning("Kajak %s skipped: %s", page["area"], e)
    return list(hotels.values()), offers
