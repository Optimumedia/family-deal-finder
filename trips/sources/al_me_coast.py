"""Albanian coast via Vlero.com: an Albanian booking portal where hotels and apartment owners list
their own rooms and the guest pays the property (cash/bank). It is not a Booking.com reseller.
robots.txt (checked 2026-11-26) only blocks `/*&language=*`, `/*leadrent*`, `/*ontop.php*` and
`/*count_view.php*`; the GET listing pages we read are allowed.

Vlero has one keyword page per beach area (".../dhoma-plazhi-ne-golem/l-al-c-26.html",
".../banesa-me-qera-ne-shengjin/l-al-c-26.html" …). Each shows up to 40 room cards, mostly from
that area plus a few "featured" rooms from elsewhere, so every page lists the zones it keeps
(`zones = ["Golem", "Shkembi Kavajes"]`) and other cards are dropped. A card gives, in plain HTML:
the property type and stars ("✰✰✰ Hotel ne Durres - Dhome + sallon Standard"), the zone, a nightly
price ("44 Euro/1 Nate"), beds, capacity ("2 te rritur + 2 femije" = 2 adults + 2 children), the
distance to the beach ("140 m nga plazhi"), size in m² and what's included ("Mengjesi" = breakfast,
"Kuzhine Private" = own kitchen). Property names are not shown — the portal keeps them for the
booking — so a hotel is named by type, zone and Vlero's property number.

Prices are the room's listed nightly price, not a quote for given dates: Vlero's calendar only
opens a few months ahead (to May 2027 on 2026-11-26), and the card shows the top of the room's
price range. We therefore store `price × nights` for the page's default check-in, like the "from"
prices of the agency sources, and say "dates on request" in the room text. Only rooms that sleep
the whole family are kept, and those are honest 2+2 prices (the price is per room, not per person).
Prices in Lek are skipped unless `all_per_eur` is set.

The search form (zone, adults, children, dates) is a POST we don't submit; the keyword pages are
enough and cost one request per area per run.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from html import unescape

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import image_url, money

log = logging.getLogger(__name__)
BASE = "https://www.vlero.com"
SOURCE = "Vlero (Albania)"

_CARD_SPLIT = 'itemtype="https://schema.org/Offer" class="item-list'
_HREF = re.compile(r'href="(https://www\.vlero\.com/hotelet-shqiptare/l-al-c-\d+-h-(\d+)-r-(\d+)\.html)"')
_TITLE = re.compile(r'<h4 class="add-title"><a [^>]*>(.*?)</a></h4>', re.S)
_TYPE = re.compile(r"(Hotel|Apartament|Vila|Shtepi|Bujtine|Resort|Hostel|Dhome)\s+ne\s+([^-]+?)\s*-\s*(.+)", re.S)
_LOC = re.compile(r'<b>([^<]+)</b>\s*-\s*<span class="item-location">([^<]+)</span>')
# The visible word ("Euro" / "Leke") is the real currency: the schema.org meta says EUR even on Lek prices.
_PRICE = re.compile(r'<b itemprop="price">([\d.,]+)</b>\s*<meta itemprop="priceCurrency" content="[A-Z]{3}">\s*(\w+)/'
                    r'<small[^>]*>([^<]+)</small>')
_CURRENCY = {"euro": "EUR", "eur": "EUR", "leke": "ALL", "lek": "ALL", "all": "ALL"}
_BEDS = re.compile(r'krevate</small><br>\s*<b>([^<]+)</b>')
_CAP = re.compile(r'Kapaciteti</small><br>\s*<b>(\d+) te rritur</b>\s*(?:\+\s*<b>(\d+) femije</b>)?')
_BEACH = re.compile(r'<b>(\d+) m</b>\s*nga plazhi')
_SIZE = re.compile(r"(\d+)\s*m2")
_INCL = re.compile(r"<b>E perfshire falas</b>:(.*?)</small>", re.S)
_ITEM = re.compile(r"<i[^>]*>(?:&#\d+;|[^\w<])*\s*([^<]+?)\s*</i>")
_IMG = re.compile(r'<img [^>]*src="([^"]+)"')
_KIND = {"hotel": "hotel", "resort": "hotel", "hostel": "hotel", "dhome": "hotel", "bujtine": "hotel",
         "apartament": "apartment", "vila": "villa", "shtepi": "villa"}
_TYPE_EN = {"hotel": "Hotel", "resort": "Resort", "hostel": "Hostel", "dhome": "Room", "bujtine": "Guesthouse",
            "apartament": "Apartment", "vila": "Villa", "shtepi": "House"}


def _clean(s: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", s)).split())


def parse_list(html: str) -> list[dict]:
    """Every room card on one Vlero listing page (no filtering)."""
    cards = []
    for block in (html or "").split(_CARD_SPLIT)[1:]:
        href, title, price = _HREF.search(block), _TITLE.search(block), _PRICE.search(block)
        if not href or not title or not price:
            continue
        stars = title.group(1).count("&#10032;") + title.group(1).count("✰")
        t = _TYPE.search(_clean(title.group(1)))
        loc, beds, cap = _LOC.search(block), _BEDS.search(block), _CAP.search(block)
        beach, incl, img = _BEACH.search(block), _INCL.search(block), _IMG.search(block)
        desc = re.search(r'<small style="color:#ABABAA">([^<]*Zona[^<]*?)<b>', block)
        size = _SIZE.search(desc.group(1)) if desc else None
        included = [unescape(x).strip(" ,") for x in _ITEM.findall(incl.group(1))] if incl else []
        cards.append({
            "property_id": href.group(2),
            "room_id": href.group(3),
            "url": href.group(1),
            "type": (t.group(1) if t else "Hotel").lower(),
            "city": _clean(loc.group(1)) if loc else (t.group(2).strip() if t else ""),
            "zone": _clean(loc.group(2)) if loc else "",
            "room": t.group(3).strip() if t else "",
            "stars": stars or None,
            "price": money(price.group(1)),
            "currency": _CURRENCY.get(price.group(2).lower(), price.group(2).upper()),
            "unit": price.group(3).strip(),
            "beds": _clean(beds.group(1)) if beds else "",
            "adults": int(cap.group(1)) if cap else 0,
            "kids": int(cap.group(2) or 0) if cap else 0,
            "beach_m": int(beach.group(1)) if beach else None,
            "size_m2": int(size.group(1)) if size and int(size.group(1)) > 0 else None,
            "included": included,
            "image": image_url(img.group(1), BASE) if img else None,
        })
    return cards


def board_code(included: list[str]) -> str:
    low = " ".join(included).lower()
    if "darke" in low or "darkë" in low:            # dinner named → half board
        return "HB"
    if "mengjes" in low:
        return "BB"
    if "kuzhin" in low:
        return "SC"
    return "RO"


def _nightly_eur(card: dict, src_cfg: dict) -> float | None:
    unit = card["unit"].lower()
    if "nat" in unit or "net" in unit:              # "1 Nate" / "1 Nete" = per night
        per = 1
    elif "jav" in unit:                             # "1 Jave" = per week
        per = 7
    else:
        return None
    price = card["price"]
    if card["currency"] == "ALL":
        rate = src_cfg.get("all_per_eur")
        if not rate:
            return None
        price = price / float(rate)
    elif card["currency"] != "EUR":
        return None
    return price / per


def fits_family(card: dict, cfg: dict) -> bool:
    fam = cfg["family"]
    return card["adults"] >= fam["adults"] and card["adults"] + card["kids"] >= fam["adults"] + fam["kids"]


def separate_bedroom(room: str) -> bool:
    """'2 dhoma + sallon', '3 dhoma', 'Dhome + sallon' (room + living room) have a separate bedroom;
    a single 'Dhome Standard' doesn't."""
    r = room.lower()
    m = re.match(r"(\d+)\s*dhoma", r)
    return bool((m and int(m.group(1)) >= 2) or "sallon" in r)


def to_hotel_and_offer(card: dict, page: dict, cfg: dict, today: date, src_cfg: dict | None = None):
    nightly = _nightly_eur(card, src_cfg or {})
    if nightly is None or nightly <= 0 or not fits_family(card, cfg):
        return None
    nights = int(page.get("nights", 7))
    check_in = max(str(page.get("check_in", today.isoformat())), today.isoformat())
    kind = _KIND.get(card["type"], "hotel")
    label = _TYPE_EN.get(card["type"], "Hotel")
    fam = {"verified": [], "family_room": True, "separate_bedroom": separate_bedroom(card["room"])}
    if card["beach_m"] is not None:
        fam["beach_m"] = card["beach_m"]
    if any("kuzhin" in x.lower() for x in card["included"]):
        fam["kitchen"] = True
    if "pishin" in " ".join(card["included"]).lower():
        fam["pool"] = True
    hotel = {
        "id": f"vl-{card['property_id']}",
        "name": f"{label} in {card['zone'] or card['city']} (Vlero #{card['property_id']})",
        "stars": card["stars"],
        "season": page.get("season", "summer"),
        "area": page["area"],
        "country": page.get("country", "AL"),
        "lat": page["lat"],
        "lng": page["lng"],
        "direct_flight_skp": False,
        "border": page.get("border", True),
        "kind": kind,
        "family": fam,
        "image": card.get("image"),
        "notes": "Auto-added from Vlero.com (Albanian portal, pay the property). Name not shown until booking; "
                 f"{card['beach_m']} m to the beach. Ask about cots and summer dates." if card["beach_m"] is not None
                 else "Auto-added from Vlero.com (Albanian portal, pay the property). Name not shown until booking; "
                      "ask about cots and summer dates.",
    }
    bits = [card["room"] or "room"]
    if card["size_m2"]:
        bits.append(f"{card['size_m2']} m²")
    if card["beds"]:
        bits.append(f"beds {card['beds']}")
    bits.append(f"sleeps {card['adults']}+{card['kids']}")
    offer = {
        "hotel": hotel["id"],
        "source": SOURCE,
        "url": card["url"],
        "seen": today.isoformat(),
        "check_in": check_in,
        "nights": nights,
        "board": board_code(card["included"]),
        "room": f"{', '.join(bits)} — listed nightly price, dates on request",
        "occupancy": "2+2",
        "price_eur": round(nightly * nights, 2),
        "was_eur": None,
        "discount_label": None,
        "valid_until": None,
    }
    return hotel, offer


def pick(cards: list[dict], page: dict) -> list[dict]:
    """Cards in the page's zones (the keyword pages mix in a few featured rooms from elsewhere)."""
    zones = {z.lower() for z in page.get("zones", [])}
    return [c for c in cards if not zones or c["zone"].lower() in zones]


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    src = cfg["sources"].get("al_me_coast", {})
    if not src.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    hotels: dict[str, dict] = {}
    offers, seen_rooms = [], set()
    for page in src.get("pages", []):
        try:
            cards = pick(parse_list(s.get(page["url"])), page)
            kept = 0
            for c in cards:
                if c["room_id"] in seen_rooms:
                    continue
                pair = to_hotel_and_offer(c, page, cfg, today, src)
                if not pair:
                    continue
                seen_rooms.add(c["room_id"])
                hotels.setdefault(pair[0]["id"], pair[0])
                offers.append(pair[1])
                kept += 1
            log.info("Vlero %s: %d rooms in the area, %d sleep the family with a euro price", page["area"],
                     len(cards), kept)
        except Blocked as e:
            log.warning("Vlero stopped (respecting the block): %s", e)
            break
        except (Unavailable, ValueError) as e:
            log.warning("Vlero %s skipped: %s", page["area"], e)
    return list(hotels.values()), offers
