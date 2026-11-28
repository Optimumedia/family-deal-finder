"""Italian family beach resorts near SKP's direct-flight airports (Bari, Naples, Alghero): hotel-only
2+2 prices read from the resorts' summer price sheets (PDF) published by Radio Radio Viaggi.

Why this source: hotel websites at Torre Canne, Monopoli, Mondello, Cefalù, Alghero and Stintino
publish no price list you can read (booking engines only), Bluserena sits behind an Incapsula bot
wall, and the Italian portals that do list prices are Booking-style engines. Radio Radio Viaggi
(viaggi.radioradio.it, a Rome agency; robots.txt disallows only /wp-admin/) publishes one PDF per
resort per summer (".../uploads/2026/01/2026-puglia-porto-giardino-IN4.pdf"). Page 1 is the
price table; it has a "solo soggiorno" (hotel only) column next to the ferry/flight packages:

    periodi | notti | [con nave] | solo sogg. | listino ufficiale | 3° letto 3/13 | 4° letto 3/13 …
    17/07 – 31/07 | 7 | 984 | 917 | 1.050 | gratis | gratis (*)        (per person, per 7 nights)
    24/05 – 21/06 | 1 min 3 | 118 | 130 | 90% | 50% | 25%               (per person, per night)

Each configured page says which cell is which (`columns`), whether a price is per night or per the
row's stay (`unit`), and the child reductions that are not table columns (`kid3`/`kid4`). Every
such reduction and every mandatory local fee (`extras`, e.g. "Tessera club € 7 a persona al
giorno") carries a `check` phrase that must appear in the sheet's text, so a new year's sheet with
other rules is skipped (and logged) instead of being priced with last year's rules.

What an offer is: 2 adults at the full rate + the twins as 3rd/4th bed (the sheets' 3/13 band:
"età non compiuta", so a 3-year-old is in it) + the mandatory fees, for 2+2 ("2+2"). The
"listino ufficiale" column gives `was_eur`. Twins outside the page's `kid_ages` band on the
check-in date: no offer (infant rules differ).

Which year: the newest sheet is found through the site's WordPress media search
(/wp-json/wp/v2/media?search=…, allowed by robots.txt; it lists only files of published offers).
Without a newer one the configured `pdf` (last summer's) is read; its dates are moved to the
coming summer and the room says "2026 price list" — a last-year price, not a quote.
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
from datetime import date, timedelta
from urllib.parse import quote, urlparse

from ..http import _CHALLENGE_MARKERS, Blocked, PoliteSession, Unavailable
from ..score import kids_age_on

log = logging.getLogger(__name__)
SOURCE = "Radio Radio Viaggi (price sheet)"
BASE = "https://viaggi.radioradio.it"

_PERIOD = re.compile(r"^(\d{1,2})/(\d{1,2})\s*[–—-]\s*(\d{1,2})/(\d{1,2})$")
_NIGHTS = re.compile(r"^(\d{1,2})(?:\s*min\.?\s*(\d{1,2}))?$", re.I)
_NUM = re.compile(r"^\d{1,3}(?:\.\d{3})*(?:,\d+)?$")
_PCT = re.compile(r"^(\d{1,3})\s*%$")
_FREE = re.compile(r"^gratis\b", re.I)
_YEAR = re.compile(r"\bEstate\s+(20\d{2})\b", re.I)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _num(s: str) -> float:
    """'1.050' → 1050 (Italian thousands dot), '75,50' → 75.5."""
    return float(s.replace(".", "").replace(",", "."))


def _cell(tok: str):
    """A table cell: a number, a reduction ('90%' → 0.9, 'gratis' → 1.0), or None if not a cell."""
    tok = tok.strip()
    if _NUM.match(tok):
        return _num(tok)
    m = _PCT.match(tok)
    if m:
        return ("red", int(m.group(1)) / 100)
    if _FREE.match(tok):
        return ("red", 1.0)
    return None


def parse_sheet(text: str) -> dict:
    """Price-table rows of one sheet: {"name", "year", "rows": [{d1, m1, d2, m2, nights, min_nights,
    per_night, cells}], "flat"}. A row is a period cell, a nights cell and the cells up to the next
    period (a sheet's 10/11-night package tables give rows with fewer cells)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    name = next((ln for ln in lines if "*" in ln and ln.upper() == ln and len(ln) > 5), lines[0] if lines else "")
    year = _YEAR.search(text or "")
    rows, i = [], 0
    while i < len(lines):
        p = _PERIOD.match(lines[i])
        n = _NIGHTS.match(lines[i + 1]) if p and i + 1 < len(lines) else None
        if not (p and n):
            i += 1
            continue
        cells, j = [], i + 2
        while j < len(lines) and not _PERIOD.match(lines[j]):
            c = _cell(lines[j])
            if c is None:
                break
            cells.append(c)
            j += 1
        d1, m1, d2, m2 = (int(x) for x in p.groups())
        per_night = n.group(2) is not None or n.group(1) == "1"
        rows.append({"d1": d1, "m1": m1, "d2": d2, "m2": m2,
                     "nights": int(n.group(1)), "min_nights": int(n.group(2) or n.group(1)),
                     "per_night": per_night, "cells": cells})
        i = j
    return {"name": re.sub(r"\s*\*+\s*$", "", name).strip(), "year": int(year.group(1)) if year else None,
            "rows": rows, "flat": _flat(text)}


def target_year(today: date) -> int:
    """The summer we plan for: this year's until the end of September, else next year's."""
    return today.year if today <= date(today.year, 9, 30) else today.year + 1


def _row_dates(r: dict, year: int) -> tuple[date, date] | None:
    try:
        return date(year, r["m1"], r["d1"]), date(year, r["m2"], r["d2"])
    except ValueError:
        return None


def _named(r: dict, columns: list[str]) -> dict | None:
    if len(r["cells"]) != len(columns):
        return None
    out = dict(zip(columns, r["cells"]))
    if not isinstance(out.get("price"), float):
        return None
    return out


def _reduction(v) -> float | None:
    if isinstance(v, tuple) and v[0] == "red":
        return v[1]
    return None


def missing_checks(page: dict, flat: str) -> list[str]:
    """Check phrases (child reductions, mandatory fees) that the sheet's text no longer contains."""
    norm = _flat(flat).lower()
    phrases = [k.get("check") for k in page.get("kid_rules", [])] + [x.get("check") for x in page.get("extras", [])]
    return [p for p in phrases if p and _flat(p).lower() not in norm]


def _in_window(d: date, x: dict) -> bool:
    if not (x.get("from") or x.get("to")):
        return True
    md = d.strftime("%m-%d")
    return x.get("from", "01-01") <= md <= x.get("to", "12-31")


def extras_eur(page: dict, check_in: date, nights: int, adults: int, kids: int, kids_age: float) -> float:
    """Mandatory local fees for the stay. per: person_night | person_week | room_night | room_week |
    kid_night (one child, e.g. a 3rd-bed forfait). `min_age` exempts younger kids."""
    total = 0.0
    for x in page.get("extras", []):
        payers = adults + (kids if kids_age >= float(x.get("min_age", 0)) else 0)
        per = x["per"]
        unit = {"person_night": payers, "person_week": payers / 7, "room_night": 1, "room_week": 1 / 7,
                "kid_night": 1 if kids else 0}[per]
        days = sum(1 for k in range(nights) if _in_window(check_in + timedelta(days=k), x))
        total += float(x["eur"]) * unit * days
    return round(total, 2)


def _kid_factors(page: dict, named: dict) -> list[float] | None:
    """What each twin pays as a share of an adult place: 3rd bed, 4th bed."""
    shares = []
    for bed in ("kid3", "kid4"):
        red = _reduction(named.get(bed))
        if red is None:
            red = _reduction(named.get("kid34"))
        if red is None:
            rule = next((k for k in page.get("kid_rules", []) if k.get("bed") in (bed, "kid34")), None)
            red = float(rule["reduction"]) if rule else None
        if red is None:
            return None
        shares.append(1.0 - red)
    return shares


def nightly_table(sheet: dict, page: dict, year: int) -> list[dict]:
    """Per-night sheets: [{start, end, price, was, shares, min_nights}] for the configured columns."""
    out = []
    for r in sheet["rows"]:
        named = _named(r, page["columns"])
        span = _row_dates(r, year)
        if not (named and span and r["per_night"]):
            continue
        shares = _kid_factors(page, named)
        if shares is None:
            continue
        out.append({"start": span[0], "end": span[1], "price": named["price"],
                    "was": named.get("was") if isinstance(named.get("was"), float) else None,
                    "shares": shares, "min_nights": r["min_nights"]})
    return out


def _night_rate(table: list[dict], d: date) -> dict | None:
    return next((t for t in table if t["start"] <= d < t["end"]), None)


def stays(sheet: dict, page: dict, year: int) -> list[dict]:
    """Candidate stays [{check_in, nights, pp, was_pp, shares}] — pp = what one adult pays for the
    stay. Per-stay sheets: one per row. Per-night sheets: from each period start, `nights` nights,
    each night at its own period's rate (a stay crossing two periods is priced across both)."""
    out = []
    if page.get("unit", "stay") == "stay":
        for r in sheet["rows"]:
            named = _named(r, page["columns"])
            span = _row_dates(r, year)
            if not (named and span) or r["per_night"]:
                continue
            shares = _kid_factors(page, named)
            if shares is None:
                continue
            out.append({"check_in": span[0], "nights": r["nights"], "pp": named["price"],
                        "was_pp": named.get("was") if isinstance(named.get("was"), float) else None,
                        "shares": [shares] * r["nights"]})
        return out
    table = nightly_table(sheet, page, year)
    nights = int(page.get("nights", 7))
    for t in table:
        pp, was, shares, ok = 0.0, 0.0, [], True
        for k in range(nights):
            rate = _night_rate(table, t["start"] + timedelta(days=k))
            if rate is None:
                ok = False
                break
            pp += rate["price"]
            was = was + rate["was"] if (was is not None and rate["was"]) else None
            shares.append(rate["shares"])
        if ok and nights >= t["min_nights"]:
            out.append({"check_in": t["start"], "nights": nights, "pp": pp, "was_pp": was, "shares": shares})
    return out


def _total(pp: float, nights: int, shares: list[list[float]], adults: int) -> float:
    """adults × full rate + each twin's share; shares vary per night when a stay crosses periods."""
    nightly = pp / nights
    return sum(nightly * (adults + sum(s)) for s in shares)


def hotel_offers(sheet: dict, page: dict, cfg: dict, today: date, pdf_url: str) -> tuple[dict | None, list[dict]]:
    adults, kids = cfg["family"]["adults"], cfg["family"]["kids"]
    missing = missing_checks(page, sheet["flat"])
    if missing:
        log.warning("Radio Radio %s: the sheet no longer says %s — rules changed, skipped", page["key"], missing)
        return None, []
    year = target_year(today)
    sheet_year = sheet.get("year") or year
    old = sheet_year < year
    months = set(page.get("months", [6, 7, 8, 9]))
    lo, hi = page.get("kid_ages", [3, 13])
    hotel = {
        "id": f"rr-{page['key']}",
        "name": page.get("name") or sheet["name"].title(),
        "stars": page.get("stars"),
        "season": "summer",
        "area": page["area"],
        "country": page.get("country", "IT"),
        "lat": page["lat"],
        "lng": page["lng"],
        "direct_flight_skp": bool(page.get("direct_flight_skp", True)),
        "border": False,
        "kind": "hotel",
        "family": {"verified": [], **page.get("family", {})},
        "image": page.get("image"),
        "notes": (f"Hotel-only price from the resort's Estate {sheet_year} price sheet (Radio Radio Viaggi). "
                  + (f"Last summer's prices, dates moved to {year}: the {year} sheet is not out yet. " if old else "")
                  + (page.get("notes") or "")).strip(),
    }
    offers = []
    for st in stays(sheet, page, year):
        ci = st["check_in"]
        if ci.month not in months or ci < today:
            continue
        age = kids_age_on(cfg, ci.isoformat())
        if not lo <= age < hi:
            continue
        fees = extras_eur(page, ci, st["nights"], adults, kids, age)
        price = _total(st["pp"], st["nights"], st["shares"], adults) + fees
        was = _total(st["was_pp"], st["nights"], st["shares"], adults) + fees if st["was_pp"] else None
        room = page.get("room", "standard room, twins in 3rd/4th bed")
        if old:
            room += f" — {sheet_year} price list"
        offers.append({
            "hotel": hotel["id"],
            "source": SOURCE,
            "url": pdf_url,
            "seen": today.isoformat(),
            "check_in": ci.isoformat(),
            "nights": st["nights"],
            "board": page.get("board", "?"),
            "room": room + (f" (incl. €{fees:,.0f} mandatory local fees)" if fees else ""),
            "occupancy": "2+2",
            "price_eur": round(price, 2),
            "was_eur": round(was, 2) if was and was > price else None,
            "discount_label": (f"agency price vs official list ({sheet_year})" if was and was > price else None),
            "valid_until": None,
        })
    return hotel, offers


# ------------------------------------------------------------------ network ---

def newest_pdf(media_json: str, file_key: str) -> tuple[int, str] | None:
    """From a /wp-json/wp/v2/media answer: the newest main sheet for this resort, as (year, url).
    Main sheets are "<year>-<file_key>-IN4[-n].pdf"; "-rep1", "date-speciali" variants are other offers."""
    try:
        items = json.loads(media_json or "[]")
    except ValueError:
        return None
    pat = re.compile(rf"/(20\d{{2}})-{re.escape(file_key)}-IN4(?:-\d+)?\.pdf$", re.I)
    best = None
    for it in items if isinstance(items, list) else []:
        url = str((it or {}).get("source_url") or "")
        m = pat.search(url)
        if m and url.startswith("https://") and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), url)
    return best


def _pdf_bytes(s: PoliteSession, url: str) -> bytes | None:
    """PoliteSession.get() returns text; a PDF needs bytes. Same rules: robots.txt, per-host delay,
    stop on 403 / a challenge page; 404 → None."""
    if not s._allowed(url):
        s.stats["blocked"] += 1
        raise Blocked(f"robots.txt disallows {url}")
    host = urlparse(url).netloc
    s._wait(host)
    s._last[host] = time.monotonic()
    s.requests_made += 1
    try:
        r = s.s.get(url, timeout=s.timeout, headers={"Accept": "application/pdf"})
    except Exception as e:                    # requests.RequestException
        s.stats["errors"] += 1
        raise Unavailable(str(e)) from e
    if r.status_code == 404:
        return None
    head = r.content[:4000].decode("latin-1", "ignore")
    if r.status_code == 403 or any(m in head for m in _CHALLENGE_MARKERS[:4]) or "Incapsula" in head:
        s.stats["blocked"] += 1
        raise Blocked(f"{r.status_code} bot challenge at {url}")
    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
        s.stats["errors"] += 1
        raise Unavailable(f"{r.status_code}, not a PDF: {url}")
    s.stats["pages"] += 1
    return r.content


def pdf_text(s, url: str) -> str | None:
    """Text of a sheet. A real PoliteSession downloads and reads the PDF (pypdf); a test double's
    get() is expected to answer the extracted text directly."""
    if not isinstance(s, PoliteSession):
        return s.get(url) or None
    data = _pdf_bytes(s, url)
    if not data:
        return None
    from pypdf import PdfReader               # optional dependency, only needed live
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages[:2])


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    src = cfg["sources"].get("it_hotels", {})
    if not src.get("enabled"):
        return [], []
    if session is None or isinstance(session, PoliteSession):
        try:
            import pypdf  # noqa: F401
        except ImportError:
            log.warning("Radio Radio: pypdf is not installed (pip install pypdf) — source skipped")
            return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    hotels, offers = [], []
    for page in src.get("pages", []):
        page = {**{k: v for k, v in src.items() if k not in ("pages", "enabled", "discover")}, **page}
        try:
            url = page["pdf"]
            if src.get("discover", True) and page.get("file_key"):
                q = quote(page.get("search") or page["file_key"].split("-", 1)[-1].replace("-", " "))
                found = newest_pdf(s.get(f"{BASE}/wp-json/wp/v2/media?search={q}&mime_type=application/pdf"
                                         f"&per_page=20&_fields=date,source_url"), page["file_key"])
                known = re.search(r"/(20\d{2})-", url)
                if found and (not known or found[0] > int(known.group(1))):
                    url = found[1]
            text = pdf_text(s, url)
            if not text:
                log.warning("Radio Radio %s: no sheet at %s", page["key"], url)
                continue
            hotel, offs = hotel_offers(parse_sheet(text), page, cfg, today, url)
            if hotel and offs:
                hotels.append(hotel)
                offers.extend(offs)
            log.info("Radio Radio %s: %d offers from %s", page["key"], len(offs), url.rsplit("/", 1)[-1])
        except Blocked as e:
            log.warning("Radio Radio stopped (respecting the block): %s", e)
            break
        except (Unavailable, ValueError, KeyError) as e:
            log.warning("Radio Radio %s skipped: %s", page.get("key"), e)
    return hotels, offers
