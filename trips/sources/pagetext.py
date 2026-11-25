"""Small helpers shared by the page-reading sources: HTML → plain text, loose date and money parsing."""
from __future__ import annotations

import re
from datetime import date
from html import unescape
from urllib.parse import urljoin

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|section|article)>", " \n ", html)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def image_url(src: str | None, base: str) -> str | None:
    """A card's photo URL as an absolute https link (hotlinked from the source, never downloaded).
    Protocol-relative ("//cdn…") and relative ("/img/…") URLs are made absolute; http → https."""
    src = unescape((src or "").strip())
    if not src or src.startswith("data:"):
        return None
    url = urljoin(base, "https:" + src if src.startswith("//") else src)
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url if url.startswith("https://") else None


def find_date(text: str, today: date) -> str | None:
    """First date in a snippet: 31.12.2026 · 31/12/2026 · Dec 23 · December 1st · 1 December 2026.
    A day+month without a year means its next occurrence from today."""
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\b", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass
    m = (re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?",
                   text, re.I)
         or re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?:\s+(20\d{2}))?",
                      text, re.I))
    if not m:
        return None
    a, b, y = m.groups()
    mon, day = (MONTHS[a.lower()[:3]], int(b)) if a[0].isalpha() else (MONTHS[b.lower()[:3]], int(a))
    try:
        d = date(int(y) if y else today.year, mon, day)
    except ValueError:
        return None
    if not y and d < today:
        d = d.replace(year=today.year + 1)
    return d.isoformat()


def money(s: str) -> float:
    """'2,768' → 2768 · '1.205' → 1205 · '75,00' → 75 · '75.00' → 75."""
    s = s.strip()
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        return float(re.sub(r"[.,]", "", s))
    return float(s.replace(",", "."))
