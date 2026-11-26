"""ArgusTours (argus.rs): Belgrade agency, robots.txt "User-agent: * / Disallow:" (everything allowed).

Why this one: its "sopstveni prevoz" (own transport) Greek summer pages print the whole season's
price list as one plain HTML table, and the prices are PER UNIT ("PO SOBI") for a 10-night stay.
A unit named A4 / S4 / S2+2 sleeps four, so its price is a real 2+2 family price for a family that
drives itself (we do: Skopje → Halkidiki is ~3 h). One request per destination gives every
object × unit × 10-night window of the season.

Page layout (checked 2026-11-26 on Kassandra, Sithonia, Olympic Riviera and Thassos):
- one tab pane per month: `id="<slug>_07-2027-pane"`; its `<thead>` lists the date windows
  ("01.07.<br>11.07.");
- in `<tbody>`, an object header row (`<h3><a href="/aranzmani/.../grigoriou-polihrono">
  Grigoriou - Polihrono</a></h3>`), then for each unit a name row ("A4 PR (NA)": unit code,
  then the service code in brackets) and a price row ("PO SOBI" + one cell per window);
- a price cell with a booking link is bookable; `capacity-no` (sold out) or a cell without a
  link ("booking not possible now", the page's own legend) is skipped.

Service codes (the page's legend): NA = najam (rental, self-catering), ND = BB, PP = HB,
PA = FB, AI / UAL = all inclusive, PCT = package.

We keep, per object and per window, the cheapest bookable unit that sleeps at least `min_beds`
(default 4) → occupancy "2+2". Prices "PO OSOBI" (per person; none seen yet, but the hotel pages
may use it when they open) are stored as 2 adults ("2+0"). Not in the price: tourist tax
(2–5 € per unit per day) and air-conditioning (5–10 € per day), both paid on the spot.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from html import unescape
from urllib.parse import urljoin, urlparse

from ..http import Blocked, PoliteSession, Unavailable

log = logging.getLogger(__name__)
BASE = "https://argus.rs"
SOURCE = "ArgusTours"
BOARDS = {"NA": "SC", "ND": "BB", "PP": "HB", "PA": "FB", "AI": "AI", "UAL": "AI", "PCT": "?"}
KINDS = (("mezonet", "maisonette"), ("mazonet", "maisonette"), ("dpl", "duplex"), ("a", "apartment"),
         ("s", "studio"), ("r", "room"), ("h", "room"))

_PANE = re.compile(r'<div class="tab-pane[^"]*"[^>]*id="[^"]*_(\d{2})-(\d{4})-pane"(.*?)(?=<div class="tab-pane|$)', re.S)
_WINDOW = re.compile(r'<th class="fw-medium text-center">\s*(\d{1,2})\.(\d{1,2})\.\s*<br\s*/?>\s*(\d{1,2})\.(\d{1,2})\.?\s*</th>')
_TR = re.compile(r"<tr>(.*?)</tr>", re.S)
_OBJ = re.compile(r'<h3[^>]*>\s*<a href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_UNIT = re.compile(r'<th class="fw-medium" colspan="\d+">([^<]+)</th>')
_TD = re.compile(r"<td([^>]*)>(.*?)</td>", re.S)
_SERVICE = re.compile(r"\(([A-Z]{2,3})\)\s*$")


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def beds(unit: str) -> int | None:
    """Sleeping places from a unit code: 'A4 PR' → 4, 'S2+2 VP' → 4, 'Mazoneta (2+1)' → 3."""
    m = re.search(r"(\d)\s*\+\s*(\d)", unit)
    if m:
        return int(m.group(1)) + int(m.group(2))
    m = re.search(r"\b[A-Za-z]{1,3}(\d)\b", unit)
    return int(m.group(1)) if m else None


def unit_kind(unit: str) -> str:
    u = unit.strip().lower()
    return next((label for key, label in KINDS if u.startswith(key)), "unit")


def _window(m: re.Match, year: int) -> tuple[str, int]:
    d1, m1, d2, m2 = (int(x) for x in m.groups())
    start = date(year, m1, d1)
    end = date(year + (1 if m2 < m1 else 0), m2, d2)
    return start.isoformat(), (end - start).days


def parse_page(html: str, base: str = BASE) -> list[dict]:
    """Every bookable price on one price-list page:
    {object_url, object_name, unit, beds, board, per, check_in, nights, price}."""
    rows = []
    for mm, yy, pane in _PANE.findall(html):
        windows = [_window(w, int(yy)) for w in _WINDOW.finditer(pane.split("</thead>")[0])]
        obj = unit = None
        for tr in _TR.findall(pane.split("</thead>", 1)[-1]):
            o = _OBJ.search(tr)
            if o:
                obj, unit = (urljoin(base, unescape(o.group(1))), _text(o.group(2))), None
                continue
            u = _UNIT.search(tr)
            if u:
                unit = unescape(u.group(1)).strip()
                continue
            cells = _TD.findall(tr)
            label = next((i for i, (_, body) in enumerate(cells) if _text(body).upper().startswith("PO ")), None)
            if obj is None or unit is None or label is None:
                continue
            per = "person" if "OSOB" in _text(cells[label][1]).upper() else "unit"
            service = _SERVICE.search(unit)
            code = _SERVICE.sub("", unit).strip()
            for (attrs, body), (check_in, nights) in zip(cells[label + 1:], windows):
                if "capacity-no" in attrs or "<a" not in body:
                    continue                          # sold out, or not bookable at the moment
                num = re.search(r"\d[\d.]*", _text(body))
                if not num:
                    continue
                rows.append({"object_url": obj[0], "object_name": obj[1], "unit": code, "beds": beds(code),
                             "board": BOARDS.get(service.group(1), "?") if service else "?",
                             "per": per, "check_in": check_in, "nights": nights,
                             "price": float(num.group(0).replace(".", ""))})
    return rows


def split_name(title: str) -> tuple[str, str, int | None]:
    """'Hotel Petridis 3* - Pefkohori' → ('Petridis', 'Pefkohori', 3)."""
    name, _, town = title.partition(" - ")
    stars = re.search(r"(\d)\s*\*", name)
    name = re.sub(r"\s*\d\s*\*", "", name)
    name = re.sub(r"^(Hotel|Apartmani|Vila|Villa|Aparthotel|Studios?)\s+", "", name.strip(), flags=re.I).strip()
    return name, town.strip(), int(stars.group(1)) if stars else None


def best_offers(rows: list[dict], page: dict, cfg: dict, today: date) -> tuple[list[dict], list[dict]]:
    """Cheapest family-size unit per object and window, as (hotels, offers)."""
    src = cfg["sources"].get("rs_agencies", {})
    min_beds = int(src.get("min_beds", 4))
    lo = max(str(src.get("check_in_from", "")), today.isoformat())
    hi = str(src.get("check_in_to", "9999-12-31"))
    adults = cfg["family"]["adults"]
    best: dict[tuple[str, str], tuple[float, dict, str]] = {}
    for r in rows:
        if not (lo <= r["check_in"] <= hi):
            continue
        if r["per"] == "unit" and (r["beds"] or 0) >= min_beds:
            total, occ = r["price"], "2+2"
        elif r["per"] == "person":
            total, occ = r["price"] * adults, "2+0"
        else:
            continue                                  # unit too small for the four of us
        key = (r["object_url"], r["check_in"])
        if key not in best or (occ, total) < (best[key][2], best[key][0]):
            best[key] = (total, r, occ)               # a 2+2 price beats a 2-adult one
    hotels: dict[str, dict] = {}
    offers = []
    for (url, _), (total, r, occ) in sorted(best.items()):
        slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        name, town, stars = split_name(r["object_name"])
        hid = f"ag-{slug}"
        hotels.setdefault(hid, {
            "id": hid,
            "name": name,
            "stars": stars,
            "season": page.get("season", "summer"),
            "area": page["area"],
            "country": page.get("country", "GR"),
            "lat": page["lat"],
            "lng": page["lng"],
            "direct_flight_skp": False,
            "border": page.get("border", True),
            "kind": "apartment" if r["board"] == "SC" else "hotel",
            "family": {"verified": []},
            "image": None,
            "notes": f"Auto-added from ArgusTours (own-transport price list){', in ' + town if town else ''}. "
                     "Tourist tax and air-conditioning are paid on the spot. Family facts unknown — use 'Ask the hotel'.",
        })
        what = f"{r['unit']} ({unit_kind(r['unit'])}"
        what += f", sleeps {r['beds']}, price per unit)" if occ == "2+2" else ", price per person × 2 adults)"
        offers.append({
            "hotel": hid,
            "source": SOURCE,
            "url": url,
            "seen": today.isoformat(),
            "check_in": r["check_in"],
            "nights": r["nights"],
            "board": r["board"],
            "room": f"{what}, own transport",
            "occupancy": occ,
            "price_eur": round(total, 2),
            "was_eur": None,
            "discount_label": None,
            "valid_until": None,
        })
    return list(hotels.values()), offers


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    src = cfg["sources"].get("rs_agencies", {})
    if not src.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    hotels: dict[str, dict] = {}
    offers = []
    for page in src.get("pages", []):
        try:
            rows = parse_page(s.get(page["url"]) or "", src.get("base", BASE))
            h, o = best_offers(rows, page, cfg, today)
            for x in h:
                hotels.setdefault(x["id"], x)
            offers += o
            log.info("ArgusTours %s: %d prices on the page, %d objects, %d offers", page["area"], len(rows),
                     len(h), len(o))
        except Blocked as e:
            log.warning("ArgusTours stopped (respecting the block): %s", e)
            break
        except (Unavailable, ValueError) as e:
            log.warning("ArgusTours %s skipped: %s", page["area"], e)
    return list(hotels.values()), offers
