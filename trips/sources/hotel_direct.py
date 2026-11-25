"""Hotels' own websites: watch each hotel's offers page for campaigns.

Hotel sites rarely show a bookable price without their booking engine (and the
big Greek engine, WebHotelier, blocks robots — we leave it alone). But their
offers pages state the campaign in plain text: "Black Friday | Save 40%",
"Early Booking … save up to 10% … before December 1st". We pick those out as
campaigns (discount %, deadline, short text) attached to the hotel, so the
dashboard can show "the hotel's own site offers −40%" next to the agency
price, and the digest can say when a new campaign appears.

Configure in config.toml under [[sources.hotel_direct.pages]] with the hotel id
from data/hotels.toml (or an auto id) and the offers-page URL.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import find_date, html_to_text

log = logging.getLogger(__name__)
SOURCE = "Hotel website"
KEYWORDS = re.compile(r"early|black friday|cyber|offer|save|off\b|discount|deal|last minute|promo|popust|"
                      r"rani buking|kids? (stay|free)|children free|free night", re.I)
_PCT = re.compile(r"(\d{1,2})\s?%")
_NOISE = re.compile(r"cookie|newsletter|subscribe|privacy|vat\b|tax", re.I)


def campaigns(html: str, today: date, max_items: int = 6) -> list[dict]:
    text = html_to_text(html)
    out, seen = [], set()
    for m in _PCT.finditer(text):
        pct = int(m.group(1))
        if not 3 <= pct <= 70:
            continue
        start = max(0, m.start() - 160)
        chunk = text[start:m.end() + 140]
        if not KEYWORDS.search(chunk) or _NOISE.search(chunk):
            continue
        # Trim to sentence-ish bounds around the % sign.
        left = re.split(r"(?<=[.!?])\s+|\n", text[start:m.start()])[-1]
        right = re.split(r"(?<=[.!?])\s+|\n", text[m.start():m.end() + 140])[0]
        title = " ".join((left + right).split())[:180]
        key = title.lower()[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "pct": pct, "valid_until": find_date(chunk, today)})
        if len(out) >= max_items:
            break
    return out


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> list[dict]:
    hd = cfg["sources"].get("hotel_direct", {})
    if not hd.get("enabled"):
        return []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    found = []
    for page in hd.get("pages", []):
        try:
            for c in campaigns(s.get(page["url"]), today):
                found.append({**c, "hotel": page["hotel"], "source": SOURCE, "url": page["url"],
                              "seen": today.isoformat()})
        except Blocked as e:
            log.warning("hotel site %s blocked us, skipping (not getting around it): %s", page["url"], e)
        except Unavailable as e:
            log.warning("hotel site %s unavailable: %s", page["url"], e)
    log.info("Hotel websites: %d campaigns on %d pages", len(found), len(hd.get("pages", [])))
    return found
