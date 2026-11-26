"""Hotels' own websites: watch each hotel's offers page for campaigns.

Hotel sites rarely show a bookable price without their booking engine (and the
big Greek engine, WebHotelier, blocks robots — we leave it alone). But their
offers pages state the campaign in plain text: "Black Friday | Save 40%",
"Early Booking … save up to 10% … before December 1st". We pick those out as
campaigns (discount %, deadline, short text) attached to the hotel, so the
dashboard can show "the hotel's own site offers −40%" next to the agency
price, and the digest can say when a new campaign appears.

Wording is matched in English, Serbian, Bulgarian and Greek. Snippets that are
not a public discount are dropped: deposits / advance payments, taxes, spa or
restaurant extras, and loyalty perks (returning guests, members, "guests who
visit us often"). Loyalty perks can be kept, tagged `kind: "loyalty"`, with
`include_loyalty = true` (a page with `kind = "loyalty"`, or a members-club URL,
counts as all-loyalty) so the dashboard can de-emphasise them. Near-identical
campaigns on one page (same %, and the same deadline or nearly the same words)
are kept once, with the fuller text.

Configure in config.toml under [[sources.hotel_direct.pages]] with the hotel id
from data/hotels.toml (or an auto id) and the offers-page URL. A URL shared by
several hotels (a group's offers page) is fetched once per run.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import find_date, html_to_text

log = logging.getLogger(__name__)
SOURCE = "Hotel website"
KEYWORDS = re.compile(
    r"early|black friday|cyber|offer|save|off\b|discount|deal|last minute|first minute|promo|\bEB\b|"
    r"kids? (stay|free)|children free|free night|"
    r"popust|rani buking|ranij[ae] rezerv|akcij|ponud|"                         # Serbian (Latin)
    r"попуст|акциј|рано резерв|понуд|"                                          # Serbian (Cyrillic)
    r"отстъпк|намален|промоц|оферт|ранн[иоа] записван|ранни резерв|"            # Bulgarian
    r"έκπτωσ|εκπτωσ|προσφορ|έγκαιρ|εγκαιρ|πρώιμ|πρωιμ",                         # Greek
    re.I)
_PCT = re.compile(r"(\d{1,2})\s?%")
# Page furniture: never a campaign, wherever it sits around the %.
_PAGE_NOISE = re.compile(r"cookie|newsletter|subscribe|privacy|бисквитк|бюлетин", re.I)
# Payment terms, taxes and extras: checked on the clause holding the %, so "−10% … 30% payment in
# advance" keeps the 10% and drops the 30%.
_NOISE = re.compile(
    r"vat\b|\btax|deposit|prepayment|(payment|paid|pay) in advance|advance payment|down ?payment|"
    r"avans|kapar|akontacij|uplat|pdv\b|"
    r"депозит|аванс|предплат|капаро|ддс|данък|"
    r"προκαταβολ|φπα|φόρο|"
    r"spa treatment|treatments?\b|massage|masa[žz]|tretman|масаж|μασάζ|restaurant|drinks|\bbar\b|f&b|"
    r"ресторант|напитк|restoran|pić", re.I)
_LOYALTY = re.compile(
    r"returning guest|repeat(ed|ing)? guest|regular guest|previous guest|past guest|loyal|member|"
    r"visit us (often|again)|continued trust|stayed with us|"
    r"stalni gost|redovni gost|lojaln|član|"
    r"стални гост|редовни гост|постоянн[иа] (клиент|гост)|лоялн|член|"
    r"πιστ(οί|ούς|ών) πελάτ|μέλ(η|ος|ών)\b|επαναλαμβαν", re.I)
_CLAUSE = re.compile(r"[,;|•]|\s(?:plus|and|и|i|και)\s", re.I)
_WORD = re.compile(r"\w+", re.U)


def _clause(text: str, at: int) -> str:
    """The clause of `text` holding position `at` (cut at , ; | • and plus/and)."""
    start, end = 0, len(text)
    for m in _CLAUSE.finditer(text):
        if m.end() <= at:
            start = m.end()
        elif m.start() >= at:
            end = m.start()
            break
    return text[start:end]


def _words(title: str) -> set[str]:
    return {w for w in _WORD.findall(title.lower()) if len(w) > 2 and not w.isdigit()}


def _same_campaign(a: dict, b: dict) -> bool:
    """Near-identical: same % and the same deadline, or (almost) the same words."""
    if a["pct"] != b["pct"]:
        return False
    if a["valid_until"] and a["valid_until"] == b["valid_until"]:
        return True
    wa, wb = _words(a["title"]), _words(b["title"])
    if not wa or not wb:
        return True                                   # e.g. "EB -10%" next to its long version
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.7


def _dedupe(found: list[dict]) -> list[dict]:
    out: list[dict] = []
    for c in found:
        i = next((i for i, o in enumerate(out) if o["kind"] == c["kind"] and _same_campaign(o, c)), None)
        if i is None:
            out.append(c)
        elif len(c["title"]) > len(out[i]["title"]):
            out[i] = {**c, "valid_until": c["valid_until"] or out[i]["valid_until"]}   # keep the fuller text
    return out


def campaigns(html: str, today: date, max_items: int = 6, include_loyalty: bool = False,
              page_kind: str | None = None) -> list[dict]:
    text = html_to_text(html)
    found = []
    for m in _PCT.finditer(text):
        pct = int(m.group(1))
        if not 3 <= pct <= 70:
            continue
        start = max(0, m.start() - 160)
        chunk = text[start:m.end() + 140]
        if not KEYWORDS.search(chunk) or _PAGE_NOISE.search(chunk):
            continue
        # Trim to sentence-ish bounds around the % sign.
        left = re.split(r"(?<=[.!?])\s+|\n", text[start:m.start()])[-1]
        right = re.split(r"(?<=[.!?])\s+|\n", text[m.start():m.end() + 140])[0]
        sentence = left + right
        clause = _clause(sentence, len(left))
        if _NOISE.search(clause):
            continue
        # Loyalty: a loyalty word in the % clause, or anywhere in the sentence and the heading line
        # just above it ("Direct Booking & Loyalty Benefits" / "Unlock up to 15% off") when that
        # holds only this one %.
        lines = [x for x in text[start:m.start()].split("\n") if x.strip()]
        near = " ".join(lines[-2:]) + right
        loyal = page_kind == "loyalty" or bool(_LOYALTY.search(clause)) or (
            len(_PCT.findall(near)) == 1 and bool(_LOYALTY.search(near)))
        if loyal and not include_loyalty:
            continue
        found.append({"title": " ".join(sentence.split())[:180], "pct": pct,
                      "valid_until": find_date(chunk, today), "kind": "loyalty" if loyal else "campaign"})
    return _dedupe(found)[:max_items]


def page_kind(page: dict) -> str | None:
    """A page's own `kind`, or "loyalty" for a members-club / loyalty URL."""
    return page.get("kind") or ("loyalty" if re.search(r"member|loyal", page["url"], re.I) else None)


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> list[dict]:
    hd = cfg["sources"].get("hotel_direct", {})
    if not hd.get("enabled"):
        return []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    include_loyalty = bool(hd.get("include_loyalty", False))
    pages: dict[str, str | None] = {}      # url -> html (None = failed): a shared page costs one request
    found = []
    for page in hd.get("pages", []):
        url = page["url"]
        if url not in pages:
            pages[url] = None
            try:
                pages[url] = s.get(url)
            except Blocked as e:
                log.warning("hotel site %s blocked us, skipping (not getting around it): %s", url, e)
            except Unavailable as e:
                log.warning("hotel site %s unavailable: %s", url, e)
        if not pages[url]:
            continue
        for c in campaigns(pages[url], today, include_loyalty=include_loyalty, page_kind=page_kind(page)):
            found.append({**c, "hotel": page["hotel"], "source": SOURCE, "url": url, "seen": today.isoformat()})
    log.info("Hotel websites: %d campaigns on %d pages (%d fetched)", len(found), len(hd.get("pages", [])),
             len(pages))
    return found
