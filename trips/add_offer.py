"""Add a price you saw on Fibula (or any agency page) to data/offers.toml, the easy way.

    python -m trips.add_offer --interactive                      # asks one question at a time
    python -m trips.add_offer --paste "Xenios Anastasia Resort & Spa ... HB ... 1.721 € ВКУПНО ОД 1.205 €" \
        --check-in 20.06.2027 --nights 7 --room "Standard Room Limited View"
    python -m trips.add_offer --hotel "Sani Beach" --check-in 2027-06-20 --nights 7 --board HB --price 5990
    python -m trips.add_offer --list                             # offers to re-check (last price > 7 days old)
    python -m trips.add_offer --again 3 --price 1180             # today's price for offer no. 3 of --list

Every entry is checked with trips.validate before it is saved, and the file is re-read afterwards
(if it no longer loads, the change is undone). A hotel that isn't in data/hotels.toml yet gets a
minimal stub there: season, area and approximate coordinates are copied from a known hotel in the
same area (or asked for); its family facts stay unknown, so the dashboard shows them as "ask".
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import tomllib
import unicodedata
from datetime import date, datetime
from pathlib import Path

from . import validate
from .db import offer_key
from .sources import manual

OFFERS = "data/offers.toml"
HOTELS = "data/hotels.toml"
CONFIG = "config.toml"
DATA = "docs/data.json"
DEFAULT_SOURCE = "Fibula (manual)"
DEFAULT_URL = "https://www.fibula.com.mk/"
STALE_DAYS = 7
ORDER = ("hotel", "source", "url", "seen", "check_in", "nights", "board", "room", "occupancy",
         "price_eur", "was_eur", "discount_label", "valid_until")
BOARDS = ("RO", "BB", "HB", "FB", "AI", "SC", "?")
BOARD_NAMES = {"RO": "room only", "BB": "breakfast", "HB": "half board (breakfast + dinner)",
               "FB": "full board", "AI": "all inclusive", "SC": "self-catering", "?": "not known"}


class AddError(Exception):
    """A problem the person can fix; the message says how."""


# ------------------------------------------------------------------ names ---

_CYR = dict(zip("абвгдѓежзѕијклљмнњопрстќуфхцчџш",
                ["a", "b", "v", "g", "d", "gj", "e", "zh", "z", "dz", "i", "j", "k", "l", "lj", "m", "n", "nj",
                 "o", "p", "r", "s", "t", "kj", "u", "f", "h", "c", "ch", "dzh", "sh"]))
_DROP = re.compile(r"\b(hotel|hotels|apart|aparthotel|apartment|apartments|apartmani|resort|spa|and|by|the|ex|"
                   r"holiday|holidays)\b|\d\s*\*")


def ascii_fold(s: str) -> str:
    s = "".join(_CYR.get(c, c) for c in s.lower())
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def norm(name: str) -> str:
    """Lower-case ASCII words without the generic ones ("hotel", "resort", "spa", "4*"...)."""
    s = re.sub(r"[^\w\s]", " ", ascii_fold(name))
    words = " ".join(s.split())
    short = " ".join(_DROP.sub(" ", words).split())
    return short or words


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", ascii_fold(name)).strip("-") or "hotel"


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def find_hotel(query: str, hotels: list[dict]) -> tuple[dict | None, list[dict]]:
    """(the hotel meant, or None) and the close candidates for a "did you mean" message."""
    q = (query or "").strip()
    if not q:
        return None, []
    for h in hotels:
        if q == h["id"] or q.lower() == h["name"].lower():
            return h, []
    nq = norm(q)
    scored = sorted(((max(_ratio(nq, norm(h["name"])), _ratio(nq, norm(h["id"].replace("-", " ")))), h)
                     for h in hotels), key=lambda x: -x[0])
    same = [h for h in hotels if norm(h["name"]) == nq]
    if len(same) == 1:
        return same[0], []
    # Only near-identical spellings count as a match. "Xenios Possidi Holidays" must NOT become
    # Xenios Possidi Paradise: anything less certain is offered as "did you mean".
    if scored and scored[0][0] >= 0.88 and (len(scored) == 1 or scored[1][0] < scored[0][0] - 0.05):
        return scored[0][1], []
    return None, [h for r, h in scored if r >= 0.6][:4]


def hotel_in_text(text: str, hotels: list[dict]) -> dict | None:
    """The known hotel whose (normalised, 2+ word) name appears in a pasted line; longest name wins."""
    t = f" {norm(text)} "
    hits = [h for h in hotels if len(norm(h["name"]).split()) >= 2 and f" {norm(h['name'])} " in t]
    if not hits:
        hits = [h for h in hotels if norm(h["name"]) and f" {norm(h['name'])} " in t and len(norm(h["name"])) >= 6]
    return max(hits, key=lambda h: len(norm(h["name"])), default=None)


# ------------------------------------------------------------------ paste ---

_NUM = r"\d{1,3}(?:[.  ]\d{3})+(?:,\d{1,2})?|\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_PRICE = re.compile(rf"(?:€|EUR|eur)\s*(?P<a>{_NUM})|(?P<b>{_NUM})\s*(?:€|EUR\b|eur\b|евра\b|евро\b)")
_TOTAL = re.compile(r"вкупно|total|ukupno", re.I)
_BOARD_WORDS = [
    (re.compile(r"\b(?:U?AI|ALL\s*INCLUSIVE|ULTRA\s*ALL)\b|ол\s*инклузив", re.I), "AI"),
    (re.compile(r"\bFB\b|full\s*board|полн\s*пансион", re.I), "FB"),
    (re.compile(r"\bHB\b|half\s*board|полупансион|полу\s*пансион", re.I), "HB"),
    (re.compile(r"\bBB\b|B&B|bed\s*(?:&|and)\s*breakfast|појадок|nocenje\s*sa\s*doruckom", re.I), "BB"),
    (re.compile(r"\bRO\b|room\s*only|ноќевање|само\s*сместување", re.I), "RO"),
    (re.compile(r"\bSC\b|self[\s-]*catering", re.I), "SC"),
]
_NIGHTS = re.compile(r"(\d{1,2})\s*(?:ноќ\w*|nights?|noći|noci|nocenja|noćenja)", re.I)
_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")
_DISCOUNT = re.compile(r"((?:early\s*booking|black\s*friday|first\s*minute|last\s*minute|рано\s*резервирање|"
                       r"попуст|ski)?[^\d%€\-−]{0,3}[-−]\s?\d{1,2}\s?%)", re.I)


def parse_amount(s: str) -> float:
    """"1.721" -> 1721, "1.205,50" -> 1205.5, "1,721" -> 1721, "980" -> 980, "99,5" -> 99.5."""
    s = s.replace(" ", "").replace(" ", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s:
        whole, _, frac = s.rpartition(".")
        if len(frac) == 3:                       # 1.721 = thousands separator
            s = s.replace(".", "")
    elif "," in s:
        whole, _, frac = s.rpartition(",")
        s = s.replace(",", "") if len(frac) == 3 else s.replace(",", ".")
    return float(s)


def parse_paste(text: str, hotels: list[dict] | None = None) -> dict:
    """Prefill fields from a copied result line, e.g.
    "Xenios Anastasia Resort & Spa ... HB ... 1.721 € ВКУПНО ОД 1.205 €" -> price 1205, was 1721, HB."""
    text = " ".join((text or "").split())
    out: dict = {}
    if not text:
        return out
    prices = [(m.start(), parse_amount(m.group("a") or m.group("b"))) for m in _PRICE.finditer(text)]
    prices = [(pos, p) for pos, p in prices if p > 0]
    if prices:
        tot = _TOTAL.search(text)
        after = [p for pos, p in prices if tot and pos > tot.start()]
        price = after[0] if after else min(p for _, p in prices)
        out["price_eur"] = _num(price)
        higher = [p for _, p in prices if p > price]
        if higher:
            out["was_eur"] = _num(max(higher))
    for rx, code in _BOARD_WORDS:
        if rx.search(text):
            out["board"] = code
            break
    m = _NIGHTS.search(text)
    if m:
        out["nights"] = int(m.group(1))
    dates = []
    for m in _DATE.finditer(text):
        try:
            dates.append(date(int(m[3]), int(m[2]), int(m[1])) if m[1] else date(int(m[4]), int(m[5]), int(m[6])))
        except ValueError:
            pass
    if dates:
        out["check_in"] = dates[0].isoformat()
        if len(dates) > 1 and "nights" not in out and 0 < (dates[1] - dates[0]).days <= 30:
            out["nights"] = (dates[1] - dates[0]).days
    pcts = [" ".join(d.split()).strip(" +,;") for d in _DISCOUNT.findall(text)]
    if pcts:
        out["discount_label"] = " + ".join(p.replace("−", "-") for p in pcts)
    h = hotel_in_text(text, hotels or [])
    if h:
        out["hotel"] = h["id"]
    else:
        cut = re.split(r"\.{3}|…|\s\d|\s(?:BB|HB|FB|AI|RO|SC)\b|\*|€|\|", text, maxsplit=1)[0].strip(" -–,")
        if cut and not cut[0].isdigit():
            out["hotel_name"] = cut
    return out


# ------------------------------------------------------------- read/write ---

def _num(x):
    x = float(x)
    return int(x) if x == int(x) else round(x, 2)


def toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(int(v)) if float(v) == int(v) else repr(float(v))
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)     # a JSON string is a valid TOML basic string


def render_offer(o: dict) -> str:
    lines = ["[[offer]]"] + [f"{k} = {toml_value(o[k])}" for k in ORDER if o.get(k) not in (None, "")]
    return "\n".join(lines) + "\n"


def parse_date(s) -> date:
    if isinstance(s, date):
        return s
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d.%m.%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise AddError(f"'{s}' is not a date: write it as 20.06.2027 or 2027-06-20")


def parse_board(s) -> str:
    b = str(s or "").strip().upper()
    if b in BOARDS:
        return b
    for rx, code in _BOARD_WORDS:
        if rx.search(b):
            return code
    raise AddError(f"board '{s}' isn't known: use BB (breakfast), HB (half board), FB, AI, RO, SC or ?")


def parse_occupancy(s) -> str:
    v = str(s or "2+2").strip().lower().replace(" ", "")
    if v in ("2+2", "family", "4", "2+2kids"):
        return "2+2"
    if v in ("2+0", "2", "adults", "2adults"):
        return "2+0"
    raise AddError(f"occupancy '{s}': use 2+2 (price for 2 adults + the twins) or 2+0 (2 adults only)")


def parse_price(s, what="price") -> float | int:
    try:
        p = parse_amount(str(s).replace("€", "").replace("EUR", "").strip())
    except ValueError:
        raise AddError(f"{what} '{s}' is not a number (write 1205 or 1.205)") from None
    return _num(p)


def load_cfg(path: str | Path) -> dict:
    p = Path(path)
    return tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def read_offers(path: str | Path) -> list[dict]:
    return manual.load(path)


def groups(offers: list[dict]) -> list[dict]:
    """Unique offers in file order: [{"no", "key", "latest", "sightings"}]. The number is stable
    as long as entries are only appended."""
    by: dict[str, dict] = {}
    for o in offers:
        k = offer_key(o)
        g = by.setdefault(k, {"no": len(by) + 1, "key": k, "sightings": []})
        g["sightings"].append(o)
    for g in by.values():
        g["latest"] = max(g["sightings"], key=lambda o: str(o["seen"]))
    return list(by.values())


def _append(path: Path, block: str, before: str | None = None) -> str:
    """Append (or insert before the first line matching the regex `before`) and return the
    original text, for undo."""
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    m = re.search(before, old, re.M) if before else None
    if m:
        new = old[:m.start()] + block + "\n" + old[m.start():]
    else:
        new = old.rstrip("\n") + ("\n\n" if old.strip() else "") + block
    path.write_text(new, encoding="utf-8", newline="\n")
    return old


# ------------------------------------------------------------ hotel stubs ---

def reference_hotel(hotels: list[dict], name: str = "", area: str = "", season: str | None = None) -> dict | None:
    """A known hotel to copy area / coordinates / season from: same area first, else the closest name."""
    pool = [h for h in hotels if not season or h.get("season") == season] or hotels
    if area:
        na = norm(area)
        best = max(pool, key=lambda h: (_area_score(na, h.get("area", "")), -len(h.get("area", ""))), default=None)
        if best and _area_score(na, best.get("area", "")) >= 0.6:
            return best
        return None
    if name:
        nn = norm(name)
        best = max(pool, key=lambda h: _ratio(nn, norm(h["name"])), default=None)
        if best and _ratio(nn, norm(best["name"])) >= 0.5:
            return best
    return None


def _area_score(na: str, area: str) -> float:
    parts = [norm(p) for p in area.split(",") if norm(p)]
    if any(na == p for p in parts):
        return 1.0
    if na and f" {na} " in f" {norm(area)} ":
        return 0.95
    return max([_ratio(na, p) for p in parts] + [_ratio(na, norm(area))])


_COUNTRIES = {"bulgaria": "BG", "greece": "GR", "halkidiki": "GR", "serbia": "RS", "turkey": "TR",
              "montenegro": "ME", "north macedonia": "MK", "macedonia": "MK", "albania": "AL", "thassos": "GR",
              "olympic riviera": "GR", "kassandra": "GR", "sithonia": "GR"}


def country_of(area: str) -> str | None:
    a = ascii_fold(area or "")
    return next((c for k, c in _COUNTRIES.items() if k in a), None)


def known_elsewhere(path: str | Path) -> list[dict]:
    """Hotels the automatic sources found (from the last docs/data.json), as extra references for
    area and coordinates. They are never written back; only a stub's area/coords come from them."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        items = json.loads(p.read_text(encoding="utf-8")).get("items", [])
    except (ValueError, AttributeError):
        return []
    out: dict[str, dict] = {}
    for i in items:
        if i.get("hotel_id") and i.get("lat") is not None and i.get("lng") is not None and i.get("season"):
            out.setdefault(i["hotel_id"], {"id": i["hotel_id"], "name": i.get("name") or i["hotel_id"],
                                           "area": i.get("area") or "", "season": i["season"], "lat": i["lat"],
                                           "lng": i["lng"], "stars": i.get("stars"),
                                           "country": country_of(i.get("area") or "")})
    return list(out.values())


def make_stub(name: str, hotels: list[dict], today: date, season: str | None = None, area: str | None = None,
              lat: float | None = None, lng: float | None = None, country: str | None = None,
              stars: int | None = None, extra: list[dict] | None = None) -> tuple[dict, str]:
    """A minimal [[hotel]] entry and a note saying where its area/coordinates came from.
    `hotels` are the curated ones (their ids are taken); `extra` are auto-found hotels used only
    as references."""
    pool = hotels + [e for e in (extra or []) if e["id"] not in {h["id"] for h in hotels}]
    nn = norm(name)
    same = max(pool, key=lambda h: _ratio(nn, norm(h["name"])), default=None)
    if same and _ratio(nn, norm(same["name"])) >= 0.88 and (not season or same["season"] == season):
        ref, is_same = same, True                   # this very hotel was found automatically before
    else:
        is_same = False
        ref = reference_hotel(pool, name=name if not area else "", area=area or "", season=season)
    note = ""
    if ref:
        season = season or ref.get("season")
        if area and _area_score(norm(area), ref.get("area", "")) >= 0.95:
            area = ref.get("area")                  # "Possidi" -> "Possidi, Kassandra, Halkidiki"
        area = area or ref.get("area")
        country = country or ref.get("country") or country_of(ref.get("area", ""))
        stars = stars or (ref.get("stars") if is_same else None)
        if lat is None or lng is None:
            lat, lng = ref.get("lat"), ref.get("lng")
            note = f"coordinates copied from {ref['name']} ({ref.get('area')}), approximate"
    country = country or country_of(area or "")
    missing = [k for k, v in (("season", season), ("area", area), ("lat", lat), ("lng", lng)) if v in (None, "")]
    if missing:
        raise AddError(f"'{name}' is a new hotel and I couldn't work out its {', '.join(missing)}. "
                       "Add --season summer|winter --area \"Town, Region\" (a town we already track is enough), "
                       "or --lat and --lng from Google Maps.")
    if season not in ("summer", "winter"):
        raise AddError(f"season '{season}': use summer or winter")
    ids = {h["id"] for h in pool}
    hid, n = slug(name), 2
    while hid in ids:
        hid, n = f"{slug(name)}-{n}", n + 1
    country = (country or "").upper() or None
    h = {"id": hid, "name": name.strip(), "stars": stars, "season": season, "area": area, "country": country,
         "lat": round(float(lat), 3), "lng": round(float(lng), 3), "direct_flight_skp": False,
         "border": country != "MK",
         "notes": f"Added by add_offer on {today.isoformat()}: family facts not known yet"
                  + (f"; {note}" if note else "") + ".",
         "family": {"verified": []}}
    return h, note


def render_hotel(h: dict) -> str:
    keys = ("id", "name", "stars", "season", "area", "country", "lat", "lng", "direct_flight_skp", "border", "notes")
    lines = ["[[hotel]]"] + [f"{k} = {toml_value(h[k])}" for k in keys if h.get(k) is not None]
    lines += ["[hotel.family]", f"verified = {toml_value(h['family'].get('verified', []))}"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- the work ---

def check(o: dict, today: date, cfg: dict) -> list[str]:
    missing = [k for k in manual.REQUIRED if o.get(k) in (None, "")]
    probs = [f"{k} is missing" for k in missing]
    return probs + validate.problems(o, today, validate.limits(cfg))


def save(o: dict, paths: dict, today: date, cfg: dict, stub: dict | None = None) -> str:
    """Validate, refuse a same-day duplicate, write, re-read (undo on failure). Returns a summary."""
    o = {k: v for k, v in o.items() if v not in (None, "")}     # as it will read back (offer key!)
    probs = check(o, today, cfg)
    if probs:
        raise AddError("Not saved — " + "; ".join(probs))
    offers_path, hotels_path = Path(paths["offers"]), Path(paths["hotels"])
    existing = read_offers(offers_path)
    k = offer_key(o)
    for e in existing:
        if offer_key(e) == k and str(e["seen"])[:10] == str(o["seen"])[:10]:
            raise AddError(f"This offer already has a price for {o['seen']} (€{e['price_eur']:,}). The engine keeps "
                           "only one price per offer per day; to correct it, edit that entry's price_eur in "
                           f"{offers_path}.")
    old_hotels = None
    if stub:
        old_hotels = _append(hotels_path, render_hotel(stub),
                             before=r"^# -+ WINTER" if stub["season"] == "summer" else None)
    old_offers = _append(offers_path, render_offer(o))
    try:
        manual.load_hotels(hotels_path)
        after = read_offers(offers_path)
        if not any(offer_key(e) == k and str(e["seen"]) == str(o["seen"]) for e in after):
            raise ValueError("the new entry didn't read back")
    except Exception as e:                          # never leave a file the run can't read
        offers_path.write_text(old_offers, encoding="utf-8", newline="\n")
        if old_hotels is not None:
            hotels_path.write_text(old_hotels, encoding="utf-8", newline="\n")
        raise AddError(f"Not saved — the file wouldn't load afterwards ({e}); nothing was changed.") from None
    no = next(g["no"] for g in groups(after) if g["key"] == k)
    return f"Saved as offer no. {no} in {offers_path}."


def describe(o: dict, hotels: dict[str, dict]) -> str:
    name = hotels.get(o["hotel"], {}).get("name", o["hotel"])
    who = "2 adults + twins" if o.get("occupancy", "2+2") == "2+2" else "2 adults only"
    was = f" (was €{o['was_eur']:,})" if o.get("was_eur") else ""
    room = f", {o['room']}" if o.get("room") else ""
    return (f"{name}: €{o['price_eur']:,}{was} for {who}, {o['nights']} nights {o['board']}{room}, "
            f"check-in {o['check_in']}, seen {o['seen']}")


def build_offer(a: argparse.Namespace, pre: dict, today: date) -> dict:
    o = {
        "hotel": a.hotel or pre.get("hotel"),
        "source": a.source,
        "url": a.url or DEFAULT_URL,
        "seen": (parse_date(a.seen) if a.seen else today).isoformat(),
        "check_in": parse_date(a.check_in).isoformat() if a.check_in else pre.get("check_in"),
        "nights": int(a.nights) if a.nights else pre.get("nights"),
        "board": parse_board(a.board) if a.board else pre.get("board"),
        "room": a.room,
        "occupancy": parse_occupancy(a.occupancy),
        "price_eur": parse_price(a.price) if a.price else pre.get("price_eur"),
        "was_eur": parse_price(a.was, "was") if a.was else pre.get("was_eur"),
        "discount_label": a.label or pre.get("discount_label"),
        "valid_until": parse_date(a.valid_until).isoformat() if a.valid_until else None,
    }
    if o["was_eur"] is not None and o["price_eur"] is not None and o["was_eur"] <= o["price_eur"]:
        o["was_eur"] = None                        # a "was" price that isn't higher means nothing
    return o


def add(a: argparse.Namespace, paths: dict, today: date, cfg: dict, out=print) -> int:
    hotels = manual.load_hotels(paths["hotels"])
    pre = parse_paste(a.paste, hotels) if a.paste else {}
    if pre:
        out("From the pasted line: " + ", ".join(f"{k}={v}" for k, v in pre.items()))
    o = build_offer(a, pre, today)
    query = o["hotel"] or pre.get("hotel_name")
    if not query:
        raise AddError("Which hotel? Add --hotel \"Hotel name\" (or paste a line that starts with the name).")
    h, close = find_hotel(query, hotels)
    stub = None
    if h:
        o["hotel"] = h["id"]
    else:
        if close and not a.new_hotel:
            raise AddError(f"No hotel called '{query}'. Did you mean: "
                           + "; ".join(f"{c['name']} (--hotel {c['id']})" for c in close)
                           + "? If it really is a different hotel, add --new-hotel.")
        stub, note = make_stub(query, hotels, today, a.season, a.area, a.lat, a.lng, a.country, a.stars,
                               extra=known_elsewhere(paths["data"]))
        o["hotel"] = stub["id"]
        out(f"New hotel '{stub['name']}' -> id {stub['id']} ({stub['season']}, {stub['area']})"
            + (f"; {note}" if note else ""))
    probs = check(o, today, cfg)
    if probs:
        raise AddError("Not saved — " + "; ".join(probs))
    names = {x["id"]: x for x in hotels} | ({stub["id"]: stub} if stub else {})
    if a.dry_run:
        out("Dry run, nothing saved. This would be added:\n" + (render_hotel(stub) + "\n" if stub else "")
            + render_offer(o))
        return 0
    msg = save(o, paths, today, cfg, stub)
    out(describe(o, names))
    out(msg + (f" New hotel stub added to {paths['hotels']}: confirm its facts with the hotel." if stub else ""))
    return 0


def resolve_ref(ref: str, gs: list[dict]) -> dict:
    ref = str(ref).strip()
    if ref.isdigit():
        for g in gs:
            if g["no"] == int(ref):
                return g
        raise AddError(f"There is no offer no. {ref}. See the numbers with --list --all.")
    for g in gs:
        if g["key"] == ref:
            return g
    hits = [g for g in gs if ref.lower() in g["key"].lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise AddError(f"No offer matches '{ref}'. See the numbers with --list --all.")
    raise AddError(f"'{ref}' matches {len(hits)} offers: " + ", ".join(str(g["no"]) for g in hits)
                   + ". Use the number from --list --all.")


def again(a: argparse.Namespace, paths: dict, today: date, cfg: dict, out=print) -> int:
    hotels = {h["id"]: h for h in manual.load_hotels(paths["hotels"])}
    g = resolve_ref(a.again, groups(read_offers(paths["offers"])))
    last = dict(g["latest"])
    pre = parse_paste(a.paste, list(hotels.values())) if a.paste else {}
    price = parse_price(a.price) if a.price else pre.get("price_eur")
    if price is None:
        raise AddError("Add today's price: --price 1180 (or --paste the result line).")
    o = {k: last.get(k) for k in ORDER}
    o["seen"] = (parse_date(a.seen) if a.seen else today).isoformat()
    o["price_eur"] = price
    ended = last.get("valid_until") and parse_date(last["valid_until"]) < today
    if a.clear_discount or ended:
        o["was_eur"] = o["discount_label"] = o["valid_until"] = None
        if ended and not a.clear_discount:
            out(f"The old promotion ended on {last['valid_until']}, so its 'was' price and label are not copied.")
    if a.was or pre.get("was_eur"):
        o["was_eur"] = parse_price(a.was, "was") if a.was else pre["was_eur"]
    if a.label or (pre.get("discount_label") and a.paste):
        o["discount_label"] = a.label or pre["discount_label"]
    if a.valid_until:
        o["valid_until"] = parse_date(a.valid_until).isoformat()
    if a.url:
        o["url"] = a.url
    if o.get("was_eur") is not None and o["was_eur"] <= o["price_eur"]:
        o["was_eur"] = None
    if a.dry_run:
        out("Dry run, nothing saved. This would be added:\n" + render_offer(o))
        return 0
    msg = save(o, paths, today, cfg)
    prev = last["price_eur"]
    change = "same price" if price == prev else f"{'down' if price < prev else 'up'} €{abs(price - prev):,} " \
                                                f"from €{prev:,} on {last['seen']}"
    out(describe(o, hotels) + f" ({change}).")
    out(msg)
    return 0


def stale(gs: list[dict], today: date, days: int = STALE_DAYS, show_all: bool = False) -> list[dict]:
    out = []
    for g in gs:
        o = g["latest"]
        age = (today - parse_date(o["seen"])).days
        if parse_date(o["check_in"]) < today:
            continue                                # the trip date has passed: nothing to re-check
        if show_all or age > days:
            out.append({**g, "age": age})
    return out


def list_offers(a: argparse.Namespace, paths: dict, today: date, out=print) -> int:
    hotels = {h["id"]: h for h in manual.load_hotels(paths["hotels"])}
    gs = groups(read_offers(paths["offers"]))
    rows = stale(gs, today, a.days, a.all)
    if not rows:
        live = len(stale(gs, today, show_all=True))
        out(f"Nothing to re-check: all {live} offers still ahead were checked in the last {a.days} days.")
        return 0
    out("All offers (number, last price):" if a.all else
        f"Re-check these on Fibula (last price is more than {a.days} days old):")
    for r in rows:
        o = r["latest"]
        name = hotels.get(o["hotel"], {}).get("name", o["hotel"])
        who = "2+2 family" if o.get("occupancy", "2+2") == "2+2" else "2 adults"
        room = f", {o['room']}" if o.get("room") else ""
        out(f"{r['no']:>3}. {name}: {parse_date(o['check_in']):%d.%m.%Y}, {o['nights']} nights {o['board']}, "
            f"{who}{room}")
        out(f"     last €{o['price_eur']:,} on {o['seen']} ({r['age']} day{'s' if r['age'] != 1 else ''} ago,{len(r['sightings'])} price"
            f"{'s' if len(r['sightings']) != 1 else ''} so far) · {o.get('url') or ''}")
    out("\nAfter checking, record today's price:  python -m trips.add_offer --again <number> --price <euros>")
    return 0


# ------------------------------------------------------------ interactive ---

def interactive(paths: dict, today: date, cfg: dict, ask=input, out=print) -> int:
    hotels = manual.load_hotels(paths["hotels"])

    def q(prompt, default=None, conv=lambda s: s, required=True):
        while True:
            shown = f" [{default}]" if default not in (None, "") else ""
            raw = ask(f"{prompt}{shown}: ").strip()
            if not raw:
                if default not in (None, ""):
                    return conv(default) if isinstance(default, str) else default
                if not required:
                    return None
                out("  (needed)")
                continue
            try:
                return conv(raw)
            except (AddError, ValueError) as e:
                out(f"  {e}")

    out("Add a Fibula price. Press Enter to accept the value in [brackets].")
    pre = parse_paste(ask("Paste the Fibula result line (or press Enter to skip): "), hotels)
    if pre:
        out("  Found: " + ", ".join(f"{k}={v}" for k, v in pre.items()))
    stub = None
    while True:
        default = pre.get("hotel") or pre.get("hotel_name")
        name = q("Hotel (name or id)", default)
        h, close = find_hotel(name, hotels)
        if h:
            out(f"  -> {h['name']} ({h['area']})")
            break
        if close:
            out("  Not found. Did you mean:")
            for i, c in enumerate(close, 1):
                out(f"   {i}. {c['name']} ({c['area']})")
            pick = q("Number, or N for a new hotel, or Enter to type again", "", required=False)
            if pick and pick.isdigit() and 1 <= int(pick) <= len(close):
                h = close[int(pick) - 1]
                break
            if not (pick and pick.lower().startswith("n")):
                continue
        out(f"  '{name}' is new; I'll add a short entry for it to {paths['hotels']}.")
        extra = known_elsewhere(paths.get("data", DATA))
        pool = hotels + extra
        ref = reference_hotel(pool, name=name)
        season = q("Season (summer/winter)", ref.get("season") if ref else None,
                   lambda s: s.lower() if s.lower() in ("summer", "winter") else _bad("type summer or winter"))
        area = q("Area (Town, Region; e.g. a town we already track)", ref.get("area") if ref else None)
        ref = reference_hotel(pool, area=area, season=season)
        lat = q("Latitude (from Google Maps)", ref.get("lat") if ref else None, float)
        lng = q("Longitude", ref.get("lng") if ref else None, float)
        stars = q("Stars (Enter to skip)", None, int, required=False)
        stub, _ = make_stub(name, hotels, today, season, area, lat, lng, ref.get("country") if ref else None, stars,
                            extra=extra)
        break
    o = {"hotel": h["id"] if h else stub["id"], "source": DEFAULT_SOURCE}
    o["check_in"] = q("Check-in date (20.06.2027)", pre.get("check_in"), lambda s: parse_date(s).isoformat())
    o["nights"] = q("Nights", pre.get("nights"), int)
    o["board"] = q("Board (BB, HB, FB, AI, RO, SC, ?)", pre.get("board"), parse_board)
    o["room"] = q("Room type (Enter to skip)", None, required=False)
    o["occupancy"] = q("Price is for 2+2 (2 adults + twins) or 2+0 (2 adults only)", "2+2", parse_occupancy)
    o["price_eur"] = q("Price in € (the total you pay)", pre.get("price_eur"), parse_price)
    o["was_eur"] = q("'Was' price in € (Enter to skip)", pre.get("was_eur"), lambda s: parse_price(s, "was"),
                     required=False)
    o["discount_label"] = q("Discount text (Enter to skip)", pre.get("discount_label"), required=False)
    o["valid_until"] = q("Offer valid until (Enter to skip)", None, lambda s: parse_date(s).isoformat(),
                         required=False)
    o["url"] = q("Link to the offer page", DEFAULT_URL)
    o["seen"] = today.isoformat()
    if o["was_eur"] is not None and o["was_eur"] <= o["price_eur"]:
        o["was_eur"] = None
    probs = check(o, today, cfg)
    if probs:
        out("Can't save: " + "; ".join(probs))
        return 2
    names = {x["id"]: x for x in hotels} | ({stub["id"]: stub} if stub else {})
    out("\n" + describe(o, names))
    if q("Save it? (y/n)", "y").lower().startswith("y"):
        out(save(o, paths, today, cfg, stub))
        return 0
    out("Not saved.")
    return 1


def _bad(msg):
    raise AddError(msg)


# -------------------------------------------------------------------- CLI ---

def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m trips.add_offer",
                                 description="Add a price seen on Fibula (or another agency) to data/offers.toml.")
    mode = ap.add_argument_group("what to do (default: add a new offer)")
    mode.add_argument("--interactive", "-i", action="store_true", help="ask one question at a time")
    mode.add_argument("--again", metavar="NO|KEY", help="record today's price for an offer already in the file "
                                                        "(its number from --list, or its key)")
    mode.add_argument("--list", action="store_true", help=f"offers to re-check (last price > {STALE_DAYS} days old)")
    mode.add_argument("--all", action="store_true", help="with --list: show every offer and its number")
    mode.add_argument("--days", type=int, default=STALE_DAYS, help="with --list: how old is too old (days)")
    f = ap.add_argument_group("the offer")
    f.add_argument("--paste", help="a copied result line: fills in price, 'was' price, board, hotel")
    f.add_argument("--hotel", help="hotel name or id (a close spelling is fine)")
    f.add_argument("--check-in", help="20.06.2027 or 2027-06-20")
    f.add_argument("--nights", type=int)
    f.add_argument("--board", help="BB, HB, FB, AI, RO, SC or ?")
    f.add_argument("--room", help="room type as the agency names it")
    f.add_argument("--occupancy", default="2+2", help="2+2 = 2 adults + twins (default), 2+0 = 2 adults only")
    f.add_argument("--price", help="the total price in €")
    f.add_argument("--was", help="the agency's 'before discount' price in €")
    f.add_argument("--label", help="discount text, e.g. 'Early Booking -30%% + Black Friday -5%%'")
    f.add_argument("--valid-until", help="the offer's deadline")
    f.add_argument("--url", help="link to the page where you saw it")
    f.add_argument("--source", default=DEFAULT_SOURCE)
    f.add_argument("--seen", help="when you saw it (default today)")
    f.add_argument("--clear-discount", action="store_true", help="with --again: don't copy the old was/label/deadline")
    n = ap.add_argument_group("a hotel that isn't tracked yet")
    n.add_argument("--new-hotel", action="store_true", help="it's a different hotel, even if the name is close")
    n.add_argument("--season", choices=("summer", "winter"))
    n.add_argument("--area", help="'Town, Region'; a town we already track fills in the coordinates")
    n.add_argument("--country", help="GR, BG, RS, AL, ME, MK, TR...")
    n.add_argument("--lat", type=float)
    n.add_argument("--lng", type=float)
    n.add_argument("--stars", type=int)
    o = ap.add_argument_group("files")
    o.add_argument("--dry-run", action="store_true", help="show what would be added, save nothing")
    o.add_argument("--offers-file", default=OFFERS)
    o.add_argument("--hotels-file", default=HOTELS)
    o.add_argument("--config", default=CONFIG)
    o.add_argument("--data-file", default=DATA, help="last dashboard data, used to look up areas/coordinates")
    return ap


def main(argv=None, today: date | None = None, ask=input, out=print) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")       # Cyrillic and € on a Windows console
        except (AttributeError, ValueError):
            pass
    a = parser().parse_args(argv)
    today = today or date.today()
    paths = {"offers": a.offers_file, "hotels": a.hotels_file, "data": a.data_file}
    cfg = load_cfg(a.config)
    try:
        if a.list:
            return list_offers(a, paths, today, out)
        if a.again:
            return again(a, paths, today, cfg, out)
        if a.interactive:
            return interactive(paths, today, cfg, ask, out)
        return add(a, paths, today, cfg, out)
    except AddError as e:
        out(f"✗ {e}")
        return 2
    except (KeyboardInterrupt, EOFError):
        out("\nStopped, nothing saved.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
