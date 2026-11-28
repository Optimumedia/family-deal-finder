"""Hotel-only ("Dojazd własny") prices near Barcelona, Malta and Larnaca airports, from Itaka (itaka.pl).

Why this source: the summer rule accepts a hotel without a package when a DIRECT flight from SKP
lands nearby (BCN, MLA, LCA in [flights]). Checked on 28.11.2026 and not usable: hotel chains
(Best Hotels = Paraty engine, H10, Ohtels: "from €" teasers only), Hello Holidays (403), wakacje.pl
(offer pages are 2 adults only; adding a party needs a query string, and robots.txt disallows
/oferty/*?*), Relaxo.bg (no Cyprus; Spain and Malta only as flight packages from Sofia), and no
Cypriot or Maltese hotel publishes a 2027 price list.

Itaka, Poland's biggest tour operator, sells "Dojazd własny" (own transport) stays: a hotel-only
"single tourist service", no flight and no transfer. These exist on the Costa Daurada (Salou,
Cambrils, La Pineda), on the Maresme / southern Costa Brava (Calella, Pineda, Santa Susanna,
Malgrat, Lloret), on Malta (Mellieħa, Qawra, St Julian's) and on Cyprus (one Ayia Napa hotel, the
rest are in Paphos). robots.txt (28.11.2026) disallows only /reservation*, /booking*, /api*,
/_next/static/, /zapytanie-ofertowe/*, /rabat-za-newsletter and /regulamin.

The page: a server-rendered search-results page, /wyniki-wyszukiwania/wakacje/?ownTransport=true&
destinations=<region>. Its __NEXT_DATA__ holds the query the server ran (rateParams: regions,
participant groups with the children's birth dates) and up to 15 rates (multiRoomRates.list):
hotel code, name, stars (hotelRating 40 = 4*), pin, facility ids ("sandy-beach", "by-the-beach",
"animations-for-kids"), the guest rating (1-6 scale), photos, the stay (beginDate/endDate), room and
meal, and the price per participant in grosze, with the catalogue price before discounts. Every card
also has a link to the exact rate (/wczasy/<country>/<region>/<slug>,<CODE>/?ownTransport=true&id[0]=
<rateId>&adults[0]=2). The rateId is a base64 protobuf; own-transport rates carry the code "OTS".

Occupancy is read from the page, never assumed: "2+2" only when the rate's participants are 2 adults
plus 2 children/infants, else "2+0". Prices are PLN, converted with `pln_eur` from the config.
LIMITS (see proposals/es_mt_cy.md): the plain URLs give Itaka's default search, 2 adults on the
cheapest/most popular short stays (mostly April, May and October). The URL keys for the children's
birth dates and the date range are not known yet ("childs", "childs[0]" are ignored; "dateFrom" gave
a 5xx). The parser is ready for them: paste a URL copied from a browser search into `pages`.
"""
from __future__ import annotations

import base64
import json
import logging
import math
import re
from datetime import date
from html import unescape

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import image_url

log = logging.getLogger(__name__)
BASE = "https://www.itaka.pl"
SOURCE = "Itaka (hotel only)"

MEALS = {"F": "BB", "H": "HB", "D": "HB", "V": "FB", "A": "AI", "U": "RO"}    # "2 posiłki Plus" = HB+
_ND = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_HREF = re.compile(r'href="(/(?:wczasy|narty)/[^"?]+,([A-Z0-9]+)/(?:\?[^"]*)?)"')


def _rates_query(data: dict) -> dict | None:
    for q in (data.get("props", {}).get("pageProps", {}).get("initialQueryState", {}).get("queries") or []):
        d = (q.get("state") or {}).get("data") or {}
        if isinstance(d, dict) and "multiRoomRates" in (d.get("main") or {}):
            return q
    return None


def own_transport(rate_id: str) -> bool | None:
    """True when the rate's protobuf id carries the own-transport code "OTS"; None if unreadable."""
    try:
        raw = base64.b64decode(rate_id + "=" * (-len(rate_id) % 4), validate=True)
    except (ValueError, TypeError):
        return None
    return b"\n\x03OTS" in raw


def links(html: str) -> dict[str, dict]:
    """Hotel code -> {"hotel": product URL, "rates": {rateId: rate URL}} from the result cards."""
    out: dict[str, dict] = {}
    for href, code in _HREF.findall(html):
        href = unescape(href)
        path = href.split("?", 1)[0]
        e = out.setdefault(code, {"hotel": BASE + path, "rates": {}})
        m = re.search(r"id%5B0%5D=([^&]+)", href)
        if m:
            rid = re.sub(r"%([0-9A-F]{2})", lambda x: chr(int(x.group(1), 16)), m.group(1))
            e["rates"][rid] = BASE + href
    return out


def parse_listing(html: str) -> dict:
    """{"party": {"adults", "children"}, "count", "rates": [...]} from one search-results page."""
    m = _ND.search(html or "")
    if not m:
        return {"party": None, "count": 0, "rates": []}
    q = _rates_query(json.loads(m.group(1)))
    if not q:
        return {"party": None, "count": 0, "rates": []}
    params = (q.get("queryKey") or [None, {}])[1].get("rateParams", {})
    groups = params.get("participantGroups") or [{}]
    party = {"adults": groups[0].get("adultsNumber"), "children": len(groups[0].get("childrenBirthDates") or [])}
    mr = q["state"]["data"]["main"]["multiRoomRates"]
    urls = links(html)
    rates = []
    for r in mr.get("list") or []:
        if r.get("rateType") != "holidays" or not r.get("segments") or not r.get("participantGroups"):
            continue                                       # cruises / round trips share the listing
        seg = r["segments"][0]
        c = seg.get("content") or {}
        geo = c.get("geolocation") or {}
        if not geo.get("lat") or not geo.get("lng"):
            continue
        pg, sp = r["participantGroups"][0], (seg.get("participantGroups") or [{}])[0]
        people = pg.get("participants") or []
        meal = (sp.get("meal") or {})
        rev = c.get("reviews") or {}
        photos = (c.get("photos") or {}).get("gallery") or []
        code = r["supplierObjectId"]
        rid = pg.get("rateId", "")
        rates.append({
            "code": code,
            "name": c.get("title", "").strip(),
            "stars": int(c["hotelRating"] // 10) if c.get("hotelRating") else None,
            "lat": float(geo["lat"]), "lng": float(geo["lng"]),
            "regions": [g["id"] for g in c.get("geographicalIdentifiers") or []],
            "facilities": [f["id"] for f in c.get("facilities") or []],
            "beach_m": (c.get("distances") or {}).get("beach"),
            "rating": rev.get("customersRating"), "reviews": rev.get("reviewsNumber") or 0,
            "image": image_url(photos[0], BASE) if photos else None,
            "check_in": seg["beginDate"], "check_out": seg["endDate"],
            "nights": (date.fromisoformat(seg["endDate"]) - date.fromisoformat(seg["beginDate"])).days,
            "meal": meal.get("id", ""), "meal_text": meal.get("title", ""),
            "board": MEALS.get(meal.get("id", ""), "?"),
            "room": ((sp.get("room") or {}).get("title") or "").strip(),
            "price_pln": pg["price"] / 100,
            "base_pln": sum(p.get("baseCatalogPrice") or p.get("price") or 0 for p in people) / 100,
            "adults": sum(1 for p in people if p.get("type") == "adult"),
            "children": sum(1 for p in people if p.get("type") in ("child", "infant")),
            "promotions": [p.get("title") for p in pg.get("promotions") or [] if p.get("title")],
            "own_transport": own_transport(rid),
            "transfer": bool(r.get("transferIncluded")),
            "hotel_url": (urls.get(code) or {}).get("hotel"),
            "url": (urls.get(code) or {}).get("rates", {}).get(rid) or (urls.get(code) or {}).get("hotel"),
        })
    return {"party": party, "count": mr.get("ratesCount") or len(rates), "rates": rates}


def km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lng2 - lng1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def keep(rate: dict, page: dict, months: list[int], today: date) -> bool:
    if rate["own_transport"] is False or rate["check_in"] < today.isoformat():
        return False
    if months and int(rate["check_in"][5:7]) not in months:
        return False
    return km(page["lat"], page["lng"], rate["lat"], rate["lng"]) <= float(page.get("max_km", 25))


def to_hotel(rate: dict, page: dict) -> dict:
    fam: dict = {"verified": []}
    f = set(rate["facilities"])
    if "sandy-beach" in f:
        fam["sand_beach"] = True
    if "by-the-beach" in f:
        fam["beachfront"] = True
    if "animations-for-kids" in f:
        fam["kids_animation"] = True
    if isinstance(rate.get("beach_m"), (int, float)):
        fam["beach_m"] = int(rate["beach_m"])
    if rate.get("rating"):
        fam["ratings"] = [{"source": "Itaka", "score": float(rate["rating"]), "scale": 6.0,
                           "count": int(rate["reviews"]) or None}]
    airport = page.get("airport")
    return {
        "id": f"itk-{rate['code'].lower()}",
        "name": rate["name"],
        "stars": rate["stars"],
        "season": page.get("season", "summer"),
        "area": page["area"],
        "country": page["country"],
        "lat": rate["lat"], "lng": rate["lng"],
        "direct_flight_skp": True,
        "border": False,
        "kind": "apartment" if re.search(r"(?i)apartament|apartments|bungalow|camping", rate["name"] + rate["room"]) else "hotel",
        "family": fam,
        "image": rate["image"],
        "notes": (f"Auto-added from Itaka (Poland), hotel only (\"Dojazd własny\", no transfer): book the direct "
                  f"flight SKP→{airport or 'the nearby airport'} yourself. Family facts are Itaka's facility tags "
                  f"(rating on Itaka's 1–6 scale) — confirm with the hotel."),
    }


def to_offer(hotel: dict, rate: dict, page_url: str, rate_eur: float, cfg: dict, today: date) -> dict:
    kids = int(cfg["family"].get("kids", 2))
    family = rate["adults"] == cfg["family"]["adults"] and rate["children"] == kids
    price = round(rate["price_pln"] * rate_eur, 2)
    was = round(rate["base_pln"] * rate_eur, 2) if rate["base_pln"] > rate["price_pln"] else None
    label = ", ".join(rate["promotions"]) or None
    if was:
        pct = round(100 * (1 - rate["price_pln"] / rate["base_pln"]))
        label = f"{label} -{pct}%" if label else f"Itaka -{pct}%"
    return {
        "hotel": hotel["id"],
        "source": SOURCE,
        "url": rate["url"] or page_url,
        "seen": today.isoformat(),
        "check_in": rate["check_in"],
        "nights": rate["nights"],
        "board": rate["board"],
        "room": (f"{rate['room']} ({rate['meal_text'].lower()}), hotel only — flight not included; "
                 f"PLN {rate['price_pln']:,.0f} at {rate_eur} €/PLN"),
        "occupancy": "2+2" if family else "2+0",
        "price_eur": price,
        "was_eur": was,
        "discount_label": label,
        "valid_until": None,
    }


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    src = cfg["sources"].get("es_mt_cy", {})
    if not src.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    rate_eur = float(src.get("pln_eur", 0.235))
    months = [int(m) for m in src.get("months", [6, 7, 8, 9])]
    hotels: dict[str, dict] = {}
    offers: list[dict] = []
    for page in src.get("pages", []):
        try:
            got = parse_listing(s.get(page["url"]) or "")
            kept = [r for r in got["rates"] if keep(r, page, page.get("months", months), today)]
            for r in kept:
                h = hotels.setdefault(f"itk-{r['code'].lower()}", to_hotel(r, page))
                offers.append(to_offer(h, r, page["url"], rate_eur, cfg, today))
            log.info("Itaka %s: %d rates on the page, %d kept (party %s)", page["area"], len(got["rates"]),
                     len(kept), got["party"])
        except Blocked as e:
            log.warning("Itaka stopped (respecting the block): %s", e)
            break
        except (Unavailable, ValueError, KeyError) as e:
            log.warning("Itaka %s skipped: %s", page["area"], e)
    return list(hotels.values()), offers
