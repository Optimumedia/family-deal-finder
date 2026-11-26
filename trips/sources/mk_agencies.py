"""Macedonian agencies: AtlantiS (atlantis.mk / atlantisonline.mk), a Skopje agency on the Tournate
booking platform. robots.txt on both hosts has no Disallow lines at all (only Content-Signal
comments), so every path is allowed.

What we read: the agency's own saved-search result pages in its menu ("Бугарија → Банско,
Боровец, Пампорово, Разлог"), e.g. /hotels/bansko?PartialGuid=…. They are server-rendered HTML:
one card per hotel with the cheapest room (data-price, data-room, data-pansion = board,
data-night, data-adultcount, data-childcount) and, under "Други видови на соби", every other
room type with its board and total price for the stay. Early-booking cards also show the old
price and the % ("#EB Discount#").

What the page states: the price is the TOTAL for the stay, for 2 adults and 0 children
("2Возрасни · 4 Ноќевања"), so offers are "2+0". The stay dates are chosen by the agency
inside the saved search and are NOT shown, so check_in is the page's configured date.

Winter rule: the family needs a separate bedroom, so when a hotel lists a room type with a
bedroom ("Apt 1 Bedroom …", "2 Bedroom …") we use the cheapest such room (and record
separate_bedroom = true, as the room type states it); otherwise the cheapest room, fact unknown.
Greece (summer) on this site is "хотели на барање" (on request) with no prices.

The PartialGuid links can change when the agency refreshes a search; if a configured page has
no cards we look the area up once in the homepage menu and retry with the current link.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from html import unescape
from urllib.parse import urljoin, urlparse

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import image_url, money

log = logging.getLogger(__name__)
SOURCE = "AtlantiS (MK)"
HOME = "https://www.atlantis.mk/"

_CARD_SPLIT = '<div class="wideResultBox forMap'
_ATTR = re.compile(r'data-([a-z]+)=(?:"([^"]*)"|([^\s">]+))')        # data-price=550 is unquoted
_IMG = re.compile(r'<img src="([^"]+)"')
_OLD = re.compile(r'class="wpOldPrice">\s*([\d.,]+)\s*EUR')
_PCT = re.compile(r'class="wpDiscount">.*?(\d{1,2})%', re.S)
_ROOM = re.compile(r'<div class="wrbRoomType">.*?<span class="title">(?:<span class="starColor">.*?</span>)?\s*(?P<room>[^<]+?)\s*</span>'
                   r'.*?<span class="label">\s*(?P<board>[^<]*?)\s*</span>'
                   r'(?P<prices>.*?)<span class="mainPrice">\s*(?P<price>[\d.,]+)\s*EUR', re.S)
_ROOM_OLD = re.compile(r'class="oldPrice"[^>]*>\s*([\d.,]+)\s*EUR')
_BEDROOM = re.compile(r"\b(\d|one|two|three)[\s-]*bedroom|\bbedroom\b", re.I)
_APT = re.compile(r"\b(apt|apartment|appart|apartament|studio|stu)\b", re.I)
_MENU = re.compile(r'href="(https://[^"]+/hotels/(?P<slug>[a-z0-9-]+)\?PartialGuid=[^"]+)"')


def board_code(text: str) -> str:
    t = " ".join((text or "").lower().split())
    if not t:
        return "?"
    if "all inclusive" in t or t in ("ai", "uai", "ultra all inclusive"):
        return "AI"
    if "full board" in t or t == "fb":
        return "FB"
    if "half board" in t or t == "hb":
        return "HB"
    if "breakfast" in t or t == "bb":
        return "BB"
    if "room only" in t or t == "ro":
        return "RO"
    if "self catering" in t or t == "sc":
        return "SC"
    return "?"                              # e.g. "THERME PRIVILEGE": a hotel package name


def _clean(s: str) -> str:
    return " ".join(unescape(s or "").split())


def _title_case(name: str) -> str:
    return " ".join(w if any(c.islower() for c in w) else w.capitalize() for w in name.split())


def has_bedroom(room: str) -> bool:
    return bool(_BEDROOM.search(room or ""))


def parse_results(html: str, base: str) -> list[dict]:
    """One saved-search result page → hotel cards with all their room rows."""
    cards = []
    for block in html.split(_CARD_SPLIT)[1:]:
        head = block[:block.find(">")]
        a = {k: unescape(q or u) for k, q, u in _ATTR.findall(head)}
        if not a.get("hotelcode") or not a.get("price"):
            continue
        rooms = []
        for m in _ROOM.finditer(block):
            old = _ROOM_OLD.search(m.group("prices"))
            rooms.append({"room": _clean(m.group("room")), "board_text": _clean(m.group("board")),
                          "board": board_code(m.group("board")), "price": money(m.group("price")),
                          "old": money(old.group(1)) if old else None})
        head_room = {"room": _clean(a.get("room")), "board_text": _clean(a.get("pansion")),
                     "board": board_code(a.get("pansion")), "price": money(a["price"]),
                     "old": money(_OLD.search(block).group(1)) if _OLD.search(block) else None}
        if not rooms:
            rooms = [head_room]
        pct = _PCT.search(block)
        img = _IMG.search(block)
        stars = a.get("stars", "").strip()
        cards.append({
            "code": a["hotelcode"],
            "name": _clean(a.get("name")),
            "stars": int(stars) if stars.isdigit() else None,
            "town": _clean(a.get("town") or a.get("city")),
            "slug": a.get("url", ""),
            "hotel_url": urljoin(base, f"/hotel/{a['url']}") if a.get("url") else None,
            "adults": int(a.get("adultcount") or 2),
            "children": int(a.get("childcount") or 0),
            "nights": int(a.get("night") or 0) or None,
            "head": head_room,
            "rooms": rooms,
            "pct": int(pct.group(1)) if pct else None,
            "early_booking": "#EB Discount#" in block,
            "image": image_url(img.group(1), base) if img else None,
        })
    return cards


def menu_links(home_html: str) -> dict[str, str]:
    """Homepage menu → {"bansko": "https://www.atlantis.mk/hotels/bansko?PartialGuid=…", …}."""
    return {m.group("slug"): unescape(m.group(1)) for m in _MENU.finditer(home_html)}


def pick_room(card: dict, season: str) -> dict:
    rooms = card["rooms"]
    if season == "winter":
        sep = [r for r in rooms if has_bedroom(r["room"])]
        if sep:
            return min(sep, key=lambda r: r["price"])
    else:
        dinner = [r for r in rooms if r["board"] in ("HB", "FB", "AI")]
        if dinner:
            return min(dinner, key=lambda r: r["price"])
    return min(rooms, key=lambda r: r["price"])


def to_hotel_and_offer(card: dict, page: dict, today: date) -> tuple[dict, dict]:
    room = pick_room(card, page["season"])
    bedroom = has_bedroom(room["room"])
    nights = card["nights"] or int(page.get("nights", 4))
    family_room = card["adults"] + card["children"] >= 4
    family: dict = {"verified": []}
    if bedroom:
        family["separate_bedroom"] = True
    old = room.get("old")
    pct = round((old - room["price"]) / old * 100) if old and old > room["price"] else None
    label = " ".join(x for x in ("Early booking" if card["early_booking"] and pct else "",
                                 f"-{pct}%" if pct else "") if x) or None
    hotel = {
        "id": f"atl-{card['code'].lower()}",
        "name": _title_case(card["name"]),
        "stars": card["stars"],
        "season": page["season"],
        "area": page["area"],
        "country": page.get("country", ""),
        "lat": page["lat"],
        "lng": page["lng"],
        "direct_flight_skp": bool(page.get("direct_flight_skp", False)),
        "border": page.get("border", True),
        "kind": "apartment" if bedroom or _APT.search(room["room"]) else "hotel",
        "family": family,
        "image": card.get("image"),
        "notes": f"Auto-added from AtlantiS (Skopje agency). Hotel page: {card['hotel_url'] or '—'}. "
                 f"Price is for {card['adults']} adults, {card['children']} children; stay dates are set by the "
                 f"agency's saved search and not shown. Family facts unknown — use 'Ask the hotel'.",
    }
    offer = {
        "hotel": hotel["id"],
        "source": SOURCE,
        "url": page["url"],
        "seen": today.isoformat(),
        "check_in": max(str(page.get("check_in", today.isoformat())), today.isoformat()),
        "nights": nights,
        "board": room["board"],
        "room": f"{room['room']} ({room['board_text'] or 'board ?'}), agency's dates",
        "occupancy": "2+2" if family_room else "2+0",
        "price_eur": round(room["price"], 2),
        "was_eur": round(old, 2) if pct else None,
        "discount_label": label,
        "valid_until": None,
    }
    return hotel, offer


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    mk = cfg["sources"].get("mk_agencies", {})
    if not mk.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    hotels, offers = [], []
    menu: dict[str, str] | None = None
    seen: set[str] = set()
    for page in mk.get("pages", []):
        try:
            url = page["url"]
            cards = parse_results(s.get(url), url)
            if not cards:                     # saved search refreshed → find the current link once
                if menu is None:
                    menu = menu_links(s.get(mk.get("home", HOME)))
                slug = urlparse(url).path.rstrip("/").split("/")[-1]
                if menu.get(slug) and menu[slug] != url:
                    url = menu[slug]
                    cards = parse_results(s.get(url), url)
            for c in cards:
                if c["code"] in seen:         # e.g. a hotel listed under both Bansko and Razlog
                    continue
                seen.add(c["code"])
                h, o = to_hotel_and_offer(c, {**page, "url": url}, today)
                hotels.append(h)
                offers.append(o)
            log.info("AtlantiS %s: %d hotels with a price", page["area"], len(cards))
        except Blocked as e:
            log.warning("AtlantiS stopped (respecting the block): %s", e)
            break
        except (Unavailable, ValueError) as e:
            log.warning("AtlantiS %s skipped: %s", page["area"], e)
    return hotels, offers
