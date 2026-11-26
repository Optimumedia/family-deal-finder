"""Private apartments / studios / small family hotels in northern Greece from Grčka Info
(grckainfo.com), a Serbian-language portal aimed at Balkan families.

Every property page publishes its price list in plain HTML, per unit and per occupancy
variant:

    <h3 class="acc-name">Studio (27m2) - prizemlje</h3> <p class="acc-guest">Odrasli: 2, Deca: 2</p>
    <details class="detail-rate-table"> … <td>01.05.2027. – 30.06.2027.</td> <td>70.00 €</td> …

and states the basis under "Napomene" ("Cene su izražene u € po smeštajnoj jedinici/dnevno" =
per unit, per night). Prices are the owners' own; the site is not fed by Booking.com.

How a page is read
* `pages` are the site's own region / town lists (/sr/smestaji/<place>/<id>/), optionally with
  its beach-distance filter `?udaljenost[0]=1` ("Do 200 m"). Cards give the link, the town and
  the capacity ("Do 5 osoba"); only cards for 4+ guests are opened. `towns` keeps only cards in
  the named towns (e.g. Sarti, Nikiti on the Sithonia list).
* On a property page each unit type (h3 name) can have several occupancy variants. The 2+2
  price is the variant with the smallest capacity that still takes 2 adults + 2 kids
  (e.g. "Odrasli: 2, Deca: 2" or "Odrasli: 4"), so we never pay for a 5th bed.
* Total = the sum of the nightly rates for each night of the configured stay (a stay may cross
  two price periods). A night with no published rate drops the offer — nothing is guessed.
* Facts only: name, coordinates and photo from the page's JSON-LD; amenity chips
  (kitchen, cot on request, beachfront, half board, separate bedroom, playground); beach
  distance and sand/pebble from the property's own description, else sand/pebble from the
  site's town paragraph (flagged as such). Text is never copied.

robots.txt (Nov 2026) disallows only /api/, /login/, /sr/search/, /hotels/search/ and a few
code folders for every agent; the lists and property pages used here are allowed.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from html import unescape
from urllib.parse import urljoin, urlsplit

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import html_to_text, image_url, money

log = logging.getLogger(__name__)
SOURCE = "Grčka Info"
BASE = "https://grckainfo.com"

_UNIT = re.compile(r'<div class="container[^"]*shadow-acc[^"]*" id="detail-unit-(\d+)">')
_PERIOD = re.compile(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})\.?\s*[–-]\s*(\d{1,2})\.(\d{1,2})\.(20\d{2})")
_EUR = re.compile(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?|\d+)\s*€")
_BEACH_NUM = re.compile(
    r"(\d{1,4})\s*(m|km|metara|metra|metar)\b\.?\s+(?:je\s+)?(?:udaljen\w*\s+)?od\s+(?:\w+\s+){0,3}?(?:pla[zž]\w*|mora\b|obale\b)"
    r"|pla[zž]\w*[^.\d]{0,40}?udaljenosti\s+od\s+(?:samo\s+|oko\s+)?(\d{1,4})\s*(m|km|metara)\b"
    r"|(?:do|od)\s+(?:pla[zž]\w*|mora)\s+(?:je\s+)?(?:samo\s+|oko\s+)?(\d{1,4})\s*(m|km|metara)\b", re.I)
_BEACHFRONT = re.compile(r"\bna\s+(?:samoj\s+)?pla[zž]i\b(?!\s+\w+\s+na\s+udaljenosti)|prv\w+\s+red\w*\s+(?:do|uz)\s+(?:mora|pla[zž]\w*)"
                         r"|(?:direktno|neposredno|odmah)\s+na\s+(?:\w+\s+){0,2}?pla[zž]\w*", re.I)
_SAND = re.compile(r"\b(?:pe[sš][cč]an\w*|pesk\w*|pesak|sitan\s+pesak)", re.I)
_PEBBLE = re.compile(r"\b(?:[sš]ljun\w*|oblut\w*|kamenit\w*)", re.I)
_BEACHY = re.compile(r"pla[zž]|obal|\bmor[ea]\b", re.I)
_SEP_YES = re.compile(r"\b\d\s*sob[ae]\b|spava[cć]\w*\s+sob\w*|dvosoban|trosoban|dvoetažn\w*|maisonette", re.I)
_SEP_NO = re.compile(r"\bstudi[oj]\w*\b|garsonjer\w*|\bsoba\b(?!\s*\d)", re.I)


def _clean(s: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", s)).split())


def _slug(s: str) -> str:
    s = s.lower().translate(str.maketrans("čćšžđ", "ccszd"))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


# ------------------------------------------------------------- list ---

def parse_list(html: str) -> dict:
    """{'cards': [{'url','id','name','town','region','capacity','discount'}], 'last_page': int}."""
    cards = []
    for a in re.findall(r'(?s)<article class="stay-card">(.*?)</article>', html):
        link = re.search(r'<h3><a href="([^"]+)">(.*?)</a>', a, re.S)
        if not link:
            continue
        url = urljoin(BASE, unescape(link.group(1)))
        pid = re.search(r"/(\d+)/?$", urlsplit(url).path)
        loc = re.search(r'(?s)class="stay-location">.*?<span>(.*?)</span>', a)
        loc = _clean(loc.group(1)) if loc else ""
        parts = [p.strip() for p in loc.split("·")[0].split(",")]
        cap = re.search(r"</i>\s*Do\s+(\d+)\s+osob", a)
        cards.append({
            "url": url, "id": pid.group(1) if pid else _slug(url), "name": _clean(link.group(2)),
            "town": parts[0] if parts else "", "region": parts[1] if len(parts) > 1 else "",
            "capacity": int(cap.group(1)) if cap else None, "discount": "stay-discount" in a,
        })
    pages = [int(n) for n in re.findall(r'href="/sr/smestaji/[^"/]+/\d+/(\d+)/', html)]
    return {"cards": cards, "last_page": max(pages, default=1)}


def page_url(url: str, n: int) -> str:
    """List page n: /sr/smestaji/sitonija/210/?f → /sr/smestaji/sitonija/210/3/?f."""
    if n <= 1:
        return url
    p = urlsplit(url)
    path = re.sub(r"(/sr/smestaji/[^/]+/\d+)(?:/\d+)?/?$", rf"\1/{n}/", p.path)
    return f"{p.scheme}://{p.netloc}{path}" + (f"?{p.query}" if p.query else "")


# ---------------------------------------------------------- property ---

def _ldjson(html: str) -> dict:
    for blob in re.findall(r'(?s)<script type="application/ld\+json">(.*?)</script>', html):
        try:
            d = json.loads(blob)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") in ("Hotel", "LodgingBusiness", "Accommodation", "VacationRental"):
            return d
    return {}


def _section(html: str, start: str, end_markers=("<section",)) -> str:
    i = html.find(start)
    if i < 0:
        return ""
    j = min((k for k in (html.find(m, i + len(start)) for m in end_markers) if k > 0), default=len(html))
    return html[i:j]


def _rates(block: str) -> list[dict]:
    out = []
    table = re.search(r'(?s)<details class="detail-rate-table">.*?<tbody>(.*?)</tbody>', block)
    for row in re.findall(r"(?s)<tr>(.*?)</tr>", table.group(1) if table else ""):
        cells = [_clean(c) for c in re.findall(r"(?s)<td[^>]*>(.*?)</td>", row)]
        if len(cells) < 2:
            continue
        m = _PERIOD.search(cells[0])
        amounts = [money(x) for x in _EUR.findall(cells[1])]
        if not m or not amounts:
            continue                                   # "na upit" or an unreadable period
        d1, m1, y1, d2, m2, y2 = map(int, m.groups())
        try:
            start, end = date(y1, m1, d1), date(y2, m2, d2)
        except ValueError:
            continue
        if end < start:
            continue
        out.append({"from": start.isoformat(), "to": end.isoformat(), "night": amounts[-1],
                    "was": amounts[0] if len(amounts) > 1 and amounts[0] > amounts[-1] else None})
    return out


def _beach_facts(text: str) -> dict:
    sents = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    out = {}
    for s in sents:
        m = _BEACH_NUM.search(s)
        if m:
            g = [x for x in m.groups() if x]
            v, unit = int(g[0]), g[1].lower()
            out["beach_m"] = v * 1000 if unit == "km" else v
            out["beach_ev"] = m.group(0)[:60]
            break
    if out.get("beach_m", 0) <= 50 and any(_BEACHFRONT.search(s) for s in sents):
        out["beachfront"] = True
    sand = next((m for s in sents if _BEACHY.search(s) and (m := _SAND.search(s))), None)
    pebble = next((m for s in sents if _BEACHY.search(s) and (m := _PEBBLE.search(s))), None)
    if sand and pebble:
        out["beach_type"] = "mixed"
    elif sand:
        out["beach_type"], out["sand_beach"] = "sand", True
    elif pebble:
        out["beach_type"], out["sand_beach"] = "pebble", False
    return out


def parse_property(html: str) -> dict:
    """Everything the page states that we use. `units`: [{'name','adults','kids','rates':[…]}]."""
    ld = _ldjson(html)
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    units = []
    starts = [(m.start(), m.group(1)) for m in _UNIT.finditer(html)]
    for k, (pos, uid) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else html.find("</section>", pos)
        block = html[pos:end if end > 0 else len(html)]
        name = re.search(r'(?s)<h3 class="acc-name">(.*?)</h3>', block)
        guests = re.search(r"Odrasli:\s*(\d+)\s*,\s*Deca:\s*(\d+)", block)
        if not name or not guests:
            continue
        units.append({"id": uid, "name": _clean(name.group(1)), "adults": int(guests.group(1)),
                      "kids": int(guests.group(2)), "rates": _rates(block)})
    amen = {_clean(s) for s in re.findall(r"(?s)<div class=\"detail-amenity-grid\">(.*?)</div>", html)
            for s in re.findall(r"(?s)<span>(.*?)</span>", s)}
    amen |= {_clean(s) for s in re.findall(r'(?s)<div class="detail-amenity-highlights">.*?</div></div>', html)
             for s in re.findall(r"<span>(.*?)</span>", s)}
    notes = html_to_text(_section(html, 'id="detail-policy"'))
    basis = ("unit" if re.search(r"po\s+smeštajnoj\s+jedinici|po\s+jedinici|po\s+apartmanu|po\s+studiju", notes, re.I)
             else "person" if re.search(r"po\s+osobi", notes, re.I) else None)
    tax = re.search(r"[Tt]uristička taksa\s*\(([^)]{3,40})\)", notes)
    offers = html_to_text(_section(html, 'class="detail-section detail-offers"'))
    desc = html_to_text(_section(html, 'id="opis"'))
    desc = desc.split("Kontakt i informacije")[0]
    town = html_to_text(_section(html, 'id="detail-location"'))
    geo = ld.get("geo") or {}
    img = ld.get("image")
    if isinstance(img, list):
        img = img[0] if img else None
    if not img:
        og = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        img = og.group(1) if og else None
    return {
        "name": _clean(h1.group(1)) if h1 else unescape(ld.get("name") or ""),
        "lat": geo.get("latitude"), "lng": geo.get("longitude"),
        "image": image_url(img, BASE) if img else None,
        "amenities": amen, "basis": basis, "tax": tax.group(1).strip() if tax else None,
        "special_offer": bool(offers.strip()) and "Specijalne ponude" in offers,
        "min_nights": int(m.group(1)) if (m := re.search(r"[Mm]inimal\w*\s+boravak[^.\d]{0,30}(\d{1,2})", notes + " " + desc)) else None,
        "beach": _beach_facts(desc), "town_beach": _beach_facts(town.split("Niste sigurni")[0]),
        "units": units,
    }


_OCC_NOTE = re.compile(r"\s*\([^)]*(?:odrasl|dec[ea]|dete|osob)[^)]*\)", re.I)


def unit_type(name: str) -> str:
    """'Apartman 40m² - 2 sobe (za 4 odraslih ili 2 odraslih + 2 dece)' → 'Apartman 40m² - 2 sobe'."""
    return " ".join(_OCC_NOTE.sub("", name).split())


def unit_board(name: str) -> str | None:
    """Board stated in a unit's name ('Standard soba 28m² - BB', 'Soba - 4 osobe HB'), else None."""
    for code, rx in (("AI", r"\bAI\b|all[\s-]inclusive"), ("FB", r"\bFB\b|pun\s+pansion"),
                     ("HB", r"\bHB\b|polupansion"), ("BB", r"\bBB\b|doru[cč]a?k")):
        if re.search(rx, name, re.I):
            return code
    return None


def pick_family_variants(units: list[dict], adults: int, kids: int, max_guests: int = 6) -> list[dict]:
    """Per unit type (h3 name), the variant with the smallest capacity that still takes the
    family; ties → the cheapest. Variants that only take adults count adult beds for the kids.
    Units for more than `max_guests` (e.g. "apartment for 2 families, 9 adults") are left out."""
    groups: dict[str, list[dict]] = {}
    for u in units:
        groups.setdefault(unit_type(u["name"]), []).append(u)
    out = []
    for vs in groups.values():
        ok = [v for v in vs if v["adults"] >= adults and adults + kids <= v["adults"] + v["kids"] <= max_guests
              and v["rates"]]
        if not ok:
            continue
        ok.sort(key=lambda v: (v["adults"] + v["kids"], min(r["night"] for r in v["rates"])))
        out.append(ok[0])
    return out


def stay_price(rates: list[dict], check_in: date, nights: int) -> tuple[float, float | None] | None:
    """Sum of the nightly rates (and of the 'was' rates, when every night has one). None if a
    night has no published rate."""
    total, was, all_was = 0.0, 0.0, True
    for i in range(nights):
        d = (check_in + timedelta(days=i)).isoformat()
        r = next((r for r in rates if r["from"] <= d <= r["to"]), None)
        if r is None:
            return None
        total += r["night"]
        if r["was"]:
            was += r["was"]
        else:
            all_was = False
    return round(total, 2), (round(was, 2) if all_was and was > total else None)


def _sep(name: str) -> bool | None:
    yes, no = bool(_SEP_YES.search(name)), bool(_SEP_NO.search(name))
    return True if yes and not no else False if no and not yes else None


def property_offers(card: dict, prop: dict, page: dict, cfg: dict, today: date):
    """(hotel, offers) for one property; (None, []) when nothing fits 2+2 or the basis is per person."""
    if prop["basis"] == "person":
        return None, []
    fam_cfg = cfg["family"]
    max_guests = int(cfg["sources"].get("gr_apartments", {}).get("max_unit_guests", 6))
    chosen = pick_family_variants(prop["units"], fam_cfg["adults"], fam_cfg["kids"], max_guests)
    if not chosen:
        return None, []
    nights = int(page.get("nights", 7))
    check_ins = page.get("check_ins") or [page.get("check_in")]
    check_ins = [date.fromisoformat(c) for c in check_ins if c]
    hid = f"gi-{card['id']}"
    am = prop["amenities"]
    family: dict = {"verified": [], "family_room": True}
    if "Bebi krevetac (na zahtev)" in am:
        family["cots_mentioned"] = True
    if "Smeštaj na plaži" in am:
        family["beachfront"] = True
    if "Polupansion" in am:
        family["half_board"] = True
    if "Dečije igralište" in am:
        family["playground"] = True
    seps = {_sep(u["name"]) for u in chosen}
    if "Odvojena spavaća soba" in am or seps == {True}:
        family["separate_bedroom"] = True
    elif seps == {False}:
        family["separate_bedroom"] = False
    notes = [f"Grčka Info price list (owner's rates, per unit per night{'' if prop['basis'] else ' — basis not stated, read as per unit'})."]
    b, tb = prop["beach"], prop["town_beach"]
    if b.get("beach_m") is not None:
        family["beach_m"] = b["beach_m"]
        notes.append(f"Beach {b['beach_m']} m (page: \"{b['beach_ev']}\").")
    if b.get("beachfront"):
        family["beachfront"] = True
    if b.get("beach_type"):
        family["beach_type"] = b["beach_type"]
        if "sand_beach" in b:
            family["sand_beach"] = b["sand_beach"]
    elif tb.get("beach_type"):
        family["beach_type"] = tb["beach_type"]
        if "sand_beach" in tb:
            family["sand_beach"] = tb["sand_beach"]
        notes.append(f"Beach type from the site's description of {card.get('town') or 'the town'}'s beach, not this house.")
    if page.get("beach_filter_m") and family.get("beach_m") is None and not family.get("beachfront"):
        family["beach_max_m"] = int(page["beach_filter_m"])
        notes.append(f"Listed under the site's 'beach up to {int(page['beach_filter_m'])} m' filter.")
    if prop["tax"]:
        notes.append(f"Tourist tax extra ({prop['tax']}).")
    if prop["special_offer"] or card.get("discount"):
        notes.append("The page lists special offers (last minute / early booking) — check them.")
    if prop["min_nights"]:
        notes.append(f"Minimum stay {prop['min_nights']} nights.")
    kitchen = bool(am & {"Kuhinja", "Čajna kuhinja"})
    name = prop["name"] or card["name"]
    town = card.get("town") or ""
    # "Paralija" (Serbian spelling) is already in "Paralia, Olympic Riviera": don't repeat the town.
    area = page["area"] if not town or _slug(town)[:5] in _slug(page["area"]) else f"{town}, {page['area']}"
    hotel = {
        "id": hid, "name": name, "stars": None, "season": page.get("season", "summer"), "area": area,
        "country": page.get("country", "GR"),
        "lat": prop["lat"] if prop["lat"] is not None else page["lat"],
        "lng": prop["lng"] if prop["lng"] is not None else page["lng"],
        "direct_flight_skp": bool(page.get("direct_flight_skp", False)), "border": bool(page.get("border", True)),
        "kind": "hotel" if re.search(r"\bhotel\b", name, re.I) else "apartment",
        "family": family, "image": prop["image"], "notes": " ".join(notes),
    }
    offers = []
    for u in chosen:
        board = unit_board(u["name"]) or ("SC" if kitchen or hotel["kind"] == "apartment" else "?")
        cap = u["adults"] + u["kids"]
        guests = f"{u['adults']} adults" + (f" + {u['kids']} kids" if u["kids"] else "")
        for ci in check_ins:
            if ci < today:
                continue
            if prop["min_nights"] and nights < prop["min_nights"]:
                continue
            got = stay_price(u["rates"], ci, nights)
            if not got:
                continue
            price, was = got
            offers.append({
                "hotel": hid, "source": SOURCE, "url": card["url"], "seen": today.isoformat(),
                "check_in": ci.isoformat(), "nights": nights, "board": board,
                "room": f"{unit_type(u['name'])} (whole unit, priced for {guests}; sleeps {cap})", "occupancy": "2+2",
                "price_eur": price, "was_eur": was, "discount_label": "Grčka Info: reduced rate" if was else None,
                "valid_until": None,
            })
    return (hotel if offers else None), offers


# --------------------------------------------------------------- fetch ---

def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    gc = cfg["sources"].get("gr_apartments", {})
    if not gc.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    need = cfg["family"]["adults"] + cfg["family"]["kids"]
    hotels, offers, seen = {}, [], set()
    for page in gc.get("pages", []):
        towns = [t.lower() for t in page.get("towns", [])]
        max_pages = int(page.get("max_list_pages", gc.get("max_list_pages", 2)))
        max_props = int(page.get("max_properties", gc.get("max_properties", 15)))
        opened = 0
        try:
            n, last = 1, 1
            while n <= min(max_pages, last) and opened < max_props:
                lst = parse_list(s.get(page_url(page["url"], n)))
                last = lst["last_page"]
                for card in lst["cards"]:
                    if opened >= max_props or card["id"] in seen:
                        continue
                    if card["capacity"] is None or card["capacity"] < need:
                        continue
                    if towns and card["town"].lower() not in towns:
                        continue
                    seen.add(card["id"])
                    opened += 1
                    try:
                        h, os_ = property_offers(card, parse_property(s.get(card["url"])), page, cfg, today)
                    except (Unavailable, ValueError, AttributeError) as e:
                        log.warning("Grčka Info %s skipped: %s", card["url"], e)
                        continue
                    if h:
                        hotels[h["id"]] = h
                        offers.extend(os_)
                n += 1
            log.info("Grčka Info %s: %d properties opened", page["url"], opened)
        except Blocked as e:
            log.warning("Grčka Info stopped (respecting the block): %s", e)
            break
        except Unavailable as e:
            log.warning("Grčka Info list %s skipped: %s", page["url"], e)
    return list(hotels.values()), offers
