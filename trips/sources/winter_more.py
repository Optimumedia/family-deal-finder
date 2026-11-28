"""Halo Oglasi (halooglasi.com) owner ads for Serbian ski resorts: Kopaonik, Stara Planina.

Halo Oglasi is Serbia's big classifieds site. Its "Odmor › Planine" section holds owners' own
holiday-rental ads. There is no booking engine. The guest phones or e-mails the owner. Two kinds of page:

* the resort list (`/odmor/planine/<place>[?page=N]`, 20 ads a page). The server-rendered ad
  JSON carries each card's HTML: the price badge ("40 €/noć", or "Dogovor" = price on request),
  the place (`data-field-name='mesto_s'`), title and the first lines of the text;
* the ad itself (`/odmor/planine/<slug>/<id>`). `QuidditaEnvironment.CurrentClassified` is a JSON
  object with the owner's structured fields: `cena_noc_d` (EUR per night), `kapacitet_smestaja_s`
  (guests), `tip_smestaja_s` (Apartman / Studio / Kuća …), `last_minute_b`, `po_dogovoru_b`, the
  map point, the photo list and the free text.

Rules (nothing guessed):
* "Dogovor" cards (no price) are not opened. Ads for fewer than adults + kids, rooms, or more than
  `max_capacity` guests give no offer. A nightly price above `max_night_eur` (e.g. a time-share sale) is ignored.
* The price is the whole unit's per night, so a unit for 4+ guests is stored as "2+2". When the text
  says the price is per person ("po osobi"), it is ×2 adults and stored as "2+0".
* `separate_bedroom` is True only when the owner names a bedroom ("spavaća soba", "odvojena soba",
  "jednoiposoban", "dvosoban"); False for studios / garsonjere with no bedroom wording; otherwise unknown.
* `cots_mentioned` when the text or bedroom equipment names a cot ("krevetac", "krevetić", "bebi krevet").
  How many cots stays "ask".
* The price is the owner's advertised nightly price with no season stated. It is multiplied by the
  page's `nights` and dated at the page's `check_in`. The notes say to confirm the price for the dates.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from html import unescape

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import html_to_text, image_url

log = logging.getLogger(__name__)
SOURCE = "Halo Oglasi (owner)"
BASE = "https://www.halooglasi.com"
IMG_BASE = "https://img.halooglasi.com"

_BEDROOM = re.compile(r"spava[ćc][aeiu]\w* sob|odvojen\w* (?:spava\w+ )?sob|zasebn\w* (?:spava\w+ )?sob|"
                      r"jednoiposob|dvosob|trosob|dve sobe|dvije sobe|\b[12] spava|bedroom", re.I)
_STUDIO = re.compile(r"\bstudi[oj]\w*|garsonjer", re.I)
_COT = re.compile(r"krevet[ai]c|kreveti[ćc]|bebi krev|be[bj]bi krev|de[čc]ij\w* krevet\w*|kolevk|baby cot|\bcot\b", re.I)
_PER_PERSON = re.compile(r"po osobi|po krevetu|po le[žz]aju", re.I)
_PRICE_WORD = re.compile(r"cen[aeiu]|€|\beur|evra|\bdin\b|\d\s*e\b", re.I)
_PLAYROOM = re.compile(r"igraonic|de[čc]ij\w* (?:kutak|igrali[šs]t)|kids corner", re.I)
_POOL = re.compile(r"\bbazen", re.I)
_ROOM_TYPES = {"soba", "sobe", "krevet", "hostel"}
_KIND = (("kuć", "villa"), ("kuc", "villa"), ("vil", "villa"), ("vikend", "villa"), ("brvnar", "villa"),
         ("hotel", "hotel"))


def _kind(tip: str) -> str:
    t = tip.lower()
    return next((k for p, k in _KIND if t.startswith(p)), "apartment")


def _per_person(text: str) -> bool:
    """'Cena 20 € po osobi' — but not the tourist tax ('boravišna taksa … po osobi dnevno')."""
    for m in _PER_PERSON.finditer(text):
        before = text[max(0, m.start() - 60):m.start()]
        before = re.split(r"[.!?\n]", before)[-1]
        if _PRICE_WORD.search(before) and not re.search(r"taks|osiguranj|doplat|dodatn", before, re.I):
            return True
    return False


def _cards_json(html: str) -> list[dict]:
    """The list page's ad objects (only the keys we read)."""
    out = []
    for chunk in html.split('{"RelativeUrl":"')[1:]:
        rel = chunk[:chunk.find('"')]
        aid = re.search(r'"Id":"(\d+)"', chunk)
        title = re.search(r'"Title":"((?:[^"\\]|\\.)*)"', chunk)
        lst = re.search(r'"ListHTML":"((?:[^"\\]|\\.)*)"', chunk)
        if not (rel.startswith("/odmor/") and aid and title and lst):
            continue
        out.append({"rel": rel, "id": aid.group(1), "title": json.loads(f'"{title.group(1)}"'),
                    "list_html": unescape(unescape(json.loads(f'"{lst.group(1)}"')))})
    return out


def parse_list(html: str) -> tuple[list[dict], int]:
    """([{'id','url','title','place','price_night','text'}], total pages)."""
    total = re.search(r'"TotalPages":(\d+)', html)
    cards = []
    for c in _cards_json(html):
        h = c["list_html"]
        badge = re.search(r'class="central-feature"><span data-value="([^"]*)"', h)
        price = None
        if badge and re.fullmatch(r"[\d.,]+", badge.group(1)):
            price = float(badge.group(1).replace(".", "").replace(",", "."))
        place = re.search(r"data-field-name='mesto_s' data-field-value='([^']*)'", h)
        desc = re.search(r'(?s)<p class="text-description-list[^"]*">(.*?)</p>', h)
        cards.append({
            "id": c["id"], "url": BASE + c["rel"].split("?")[0], "title": " ".join(c["title"].split()),
            "place": unescape(place.group(1)).strip().lower() if place else "",
            "price_night": price, "text": html_to_text(desc.group(1)) if desc else "",
        })
    return cards, int(total.group(1)) if total else 1


def _int(s) -> int | None:
    m = re.search(r"\d+", str(s or ""))
    return int(m.group()) if m else None


def parse_listing(html: str) -> dict:
    """The ad's structured fields from QuidditaEnvironment.CurrentClassified."""
    i = html.find("QuidditaEnvironment.CurrentClassified")
    if i < 0:
        raise ValueError("no ad data on page")
    d, _ = json.JSONDecoder().raw_decode(html[html.find("{", i):])
    f = d.get("OtherFields") or {}
    text = html_to_text(d.get("TextHtml") or "")
    beds = " ".join(f.get("opremljenost_spavaca_soba_ss") or [])
    general = f.get("smestaj_opste_ss") or []
    title = " ".join((d.get("Title") or "").split())
    tip = (f.get("tip_smestaja_s") or "").strip()
    blob = f"{title} {text}"
    bedroom = bool(_BEDROOM.search(blob))
    studio = tip.lower() == "studio" or bool(_STUDIO.search(blob))
    geo = re.fullmatch(r"\s*(-?\d+\.\d+),\s*(-?\d+\.\d+)\s*", d.get("GeoLocationRPT") or "")
    imgs = d.get("ImageURLs") or []
    return {
        "id": str(d.get("Id") or ""),
        "title": title,
        "type": tip,
        "place": (f.get("mesto_s") or "").strip(),
        "price_night": float(f["cena_noc_d"]) if f.get("cena_noc_d") else None,
        "on_request": bool(f.get("po_dogovoru_b")),
        "last_minute": bool(f.get("last_minute_b")),
        "capacity": _int(f.get("kapacitet_smestaja_s")),
        "beds": _int(f.get("broj_svih_lezajeva_s")),
        "per_person": _per_person(text),
        "separate_bedroom": True if bedroom else False if studio else None,
        "cots_mentioned": bool(_COT.search(f"{text} {beds}")),
        "playroom": bool(_PLAYROOM.search(text)),
        "pool": bool(_POOL.search(text)) or any("bazen" in g.lower() for g in general),
        "to_centre_m": f.get("udaljenost_centar_i"),
        "lat": float(geo.group(1)) if geo else None,
        "lng": float(geo.group(2)) if geo else None,
        "image": image_url(IMG_BASE + imgs[0], IMG_BASE) if imgs else None,
    }


def to_hotel_and_offer(card: dict, info: dict, page: dict, cfg: dict, today: date):
    """None when the ad can't host the family or has no usable price."""
    adults, need = cfg["family"]["adults"], cfg["family"]["adults"] + cfg["family"]["kids"]
    sc = cfg["sources"].get("winter_more", {})
    max_cap = int(page.get("max_capacity", sc.get("max_capacity", 8)))
    max_night = float(page.get("max_night_eur", sc.get("max_night_eur", 400)))
    cap = info.get("capacity")
    night = info.get("price_night") or card.get("price_night")
    if not cap or cap < need or cap > max_cap or not night or night > max_night:
        return None
    if info["type"].lower() in _ROOM_TYPES:
        return None
    if info["per_person"]:
        total_night, occ, basis = night * adults, "2+0", "per person × 2 adults; ask the price with the twins"
    else:
        total_night, occ, basis = night, "2+2", f"whole unit, up to {cap} guests"
    nights = int(page.get("nights", 5))
    check_in = max(str(page.get("check_in", today.isoformat())), today.isoformat())
    hid = f"ho-{info['id'] or card['id']}"
    notes = [f"Halo Oglasi owner ad ({basis}): {night:,.0f} EUR/night as advertised, season not stated; "
             "confirm the price for your dates with the owner. Tourist tax extra."]
    if info["separate_bedroom"] is None:
        notes.append("Ask whether the bedroom is separate.")
    notes.append("Cot mentioned in the ad (how many not stated)." if info["cots_mentioned"]
                 else "Cots not mentioned: ask.")
    if info.get("to_centre_m"):
        notes.append(f"{info['to_centre_m']} m to the centre (owner).")
    if info["pool"]:
        notes.append("Pool / spa in the building or complex (owner; kids' pool not stated).")
    family = {"separate_bedroom": info["separate_bedroom"], "verified": []}
    if info["cots_mentioned"]:
        family["cots_mentioned"] = True
    if info["playroom"]:
        family["playroom"] = True
    hotel = {
        "id": hid, "name": info.get("title") or card["title"], "stars": None,
        "season": page["season"], "area": page["area"], "country": page.get("country", "RS"),
        "lat": info.get("lat") or page["lat"], "lng": info.get("lng") or page["lng"],
        "direct_flight_skp": False, "border": bool(page.get("border", True)),
        "kind": _kind(info["type"]),
        "family": family, "image": info.get("image"), "notes": " ".join(notes),
    }
    offer = {
        "hotel": hid, "source": SOURCE, "url": card["url"], "seen": today.isoformat(),
        "check_in": check_in, "nights": nights, "board": "SC",
        "room": f"{info['type'] or 'Apartman'}, whole unit, up to {cap} guests (owner's price, dates on request)",
        "occupancy": occ, "price_eur": round(total_night * nights, 2), "was_eur": None,
        "discount_label": "Last minute (owner's ad)" if info["last_minute"] else None, "valid_until": None,
    }
    return hotel, offer


def _wanted(card: dict, page: dict) -> bool:
    place = str(page.get("place", "")).lower()
    return card["price_night"] is not None and (not place or card["place"] == place)


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    sc = cfg["sources"].get("winter_more", {})
    if not sc.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    hotels, offers = {}, []
    for page in sc.get("pages", []):
        try:
            picked, seen = [], set()
            max_pages = int(page.get("list_pages", sc.get("list_pages", 2)))
            max_listings = int(page.get("max_listings", sc.get("max_listings", 12)))
            n, total = 1, 1
            while n <= min(total, max_pages) and len(picked) < max_listings:
                cards, total = parse_list(s.get(page["url"] if n == 1 else f"{page['url']}?page={n}"))
                for c in cards:
                    if c["id"] not in seen and _wanted(c, page):
                        seen.add(c["id"])
                        picked.append(c)
                n += 1
            got = 0
            for c in picked[:max_listings]:
                try:
                    res = to_hotel_and_offer(c, parse_listing(s.get(c["url"])), page, cfg, today)
                except (Unavailable, ValueError, KeyError) as e:
                    log.warning("Halo Oglasi %s skipped: %s", c["url"], e)
                    continue
                if res:
                    hotels[res[0]["id"]] = res[0]
                    offers.append(res[1])
                    got += 1
            log.info("Halo Oglasi %s: %d ads read, %d offers", page["area"], len(picked[:max_listings]), got)
        except Blocked as e:
            log.warning("Halo Oglasi stopped (respecting the block): %s", e)
            break
        except (Unavailable, ValueError) as e:
            log.warning("Halo Oglasi %s skipped: %s", page["area"], e)
    return list(hotels.values()), offers
