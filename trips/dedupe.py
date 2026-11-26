"""Find the same hotel listed under different ids / spellings by different sources.

Two hotels are the same only when ALL of these hold (conservative on purpose: a missed merge
shows a hotel twice, a false merge hides a real offer under the wrong hotel):

- same season, and both villas or both not villas
- the same unit (Kopaonik price lists split one building into "Name — 2+1 Apt" units)
- no conflicting place word in the names ("Lion Bansko" vs "Lion Borovets")
- compatible area: an area word in common, or within 15 km; and when both have hotel-level
  coordinates, within 3 km
- stars no more than 1 apart (unless hotel-level coordinates put them within 300 m)
- the names match after normalisation (accents, Cyrillic, "St/Saint/Sveti", hotel/apart/spa,
  MPM/HMG brands, stars, "(ex. ...)", "by ..." tails, place words):
    exact    same core words
    subset   one core is the other plus only "soft" words (boutique, residence, mountain, ...)
    fuzzy    same number of words, each pair equal or a near spelling (Radinas ~ Radina's)
  A name that is only generic words ("Grand Hotel", "Palace", "Garden") never merges on
  its name alone, and two hotels from the same source merge only on an exact core.

`merge_auto_v2` is a drop-in for `run.merge_auto`. `find_clusters` + `apply_clusters` are for
the one-time clean-up of the existing database.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from difflib import SequenceMatcher

# --- normalisation ----------------------------------------------------------------------------

_CYR = dict(zip("абвгдежзийклмнопрстуфхцчшщъьюяѓќџљњѕјєіїыэё",
                ["a", "b", "v", "g", "d", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                 "u", "f", "h", "ts", "ch", "sh", "sht", "a", "", "yu", "ya", "gj", "kj", "dz", "lj", "nj", "dz",
                 "j", "e", "i", "i", "y", "e", "e"]))
_SPECIAL = {"đ": "dj", "ð": "d", "ı": "i", "ł": "l", "ß": "ss", "ø": "o", "æ": "ae", "œ": "oe", "þ": "th"}

# carry no identity at all: dropped
WEAK = {"hotel", "hotels", "otel", "hotelli", "apart", "aparthotel", "aparthotels", "apartment", "apartments",
        "apartmani", "apartman", "apartamenti", "apts", "apt", "resort", "resorts", "spa", "wellness", "and",
        "the", "of", "a", "et", "i", "y", "complex", "kompleks", "stars", "star", "holiday", "holidays",
        "rooms", "studios", "hostel"}
# chain / agency brand words that some sources add and others don't: dropped
BRANDS = {"mpm", "hmg", "karisma"}
SAINT = {"st", "saint", "sveti", "sveta", "sv", "sankt", "san", "santa", "agios", "agia", "ag"}
# words that alone do not identify a hotel
GENERIC = {"grand", "palace", "royal", "royale", "park", "city", "central", "centre", "center", "plaza", "sun",
           "sunny", "sea", "beach", "bay", "view", "garden", "gardens", "golden", "gold", "blue", "white",
           "green", "club", "family", "villa", "villas", "vila", "house", "studio", "lux", "luxury", "deluxe",
           "mountain", "ski", "lodge", "inn", "panorama", "princess", "paradise", "seaside", "village",
           "chalet", "chalets", "residence", "boutique", "suites", "suite", "mare", "nova", "new", "life", "dream",
           "exclusive", "luxurious", "comfort", "premium", "superior", "boutique", "st", "summer", "winter",
           "holidays", "home", "homes", "plus", "lake", "riviera", "hills", "forest", "pine", "pines", "rose",
           "star", "stars", "aqua", "blu", "kids", "relax", "sport", "palas", "mediterranean"}
# allowed as the only extra words when one name is contained in the other
SOFT = {"boutique", "residence", "mountain", "suites", "suite", "deluxe", "luxury", "lux", "club", "lodge",
        "superior", "premium"}
# resort / place words (also every word of the hotel's own area string)
PLACES = {"bansko", "borovets", "pamporovo", "razlog", "dobrinishte", "chepelare", "kopaonik", "jahorina",
          "brezovica", "mavrovo", "popova", "sapka", "ohrid", "struga", "kassandra", "sithonia", "halkidiki",
          "chalkidiki", "pefkohori", "psakoudia", "hanioti", "kallithea", "nikiti", "vourvourou", "possidi",
          "sani", "afitos", "polychrono", "kriopigi", "siviri", "fourka", "skioni", "marmaras", "metamorfosi",
          "sarti", "toroni", "ouranoupoli", "leptokaria", "leptokarya", "platamonas", "paralia", "katerini",
          "olympic", "olimpic", "neoi", "poroi", "skotina", "plaka", "litochoro", "nei", "pori", "thessaloniki",
          "ulcinj", "budva", "becici", "petrovac", "bar", "herceg", "novi", "kusadasi", "alanya", "kemer", "side",
          "antalya", "belek", "bodrum", "marmaris", "didim", "stara", "planina", "zlatibor", "tara", "dojran",
          "thassos", "lefkada", "corfu", "parga", "sivota", "nea", "neos", "kalandra", "moudania", "propontida"}
# area-string words that say nothing about the resort
REGION_NOISE = {"bulgaria", "greece", "serbia", "montenegro", "turkey", "north", "macedonia", "albania",
                "region", "coast", "aegean", "area", "villa", "rental", "riviera", "halkidiki", "chalkidiki",
                "nea", "neos", "olympic", "the", "and"}

_UNIT = re.compile(r"\s+[—–]\s+")                 # "Apartmani Konaci — 2+1 Apt": the unit after the dash
_PAREN = re.compile(r"\(([^)]*)\)")
_STARS = re.compile(r"\d\s*(\*+|stars?\b|zvezdic\w*|sterne\b)|\*+")


def fold(text: str) -> str:
    """Lowercase ASCII: Cyrillic transliterated, accents stripped."""
    s = (text or "").lower()
    s = "".join(_CYR.get(c, _SPECIAL.get(c, c)) for c in s)
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _words(text: str) -> list[str]:
    s = re.sub(r"['’`´]", "", fold(text))             # Radina's -> radinas
    s = re.sub(r"(?<=\w)\+(?!\w)", " plus ", s)          # "Poseidon Palace+" is its own product
    s = _STARS.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    out = []
    for w in s.split():
        out.append("st" if w in SAINT else w)
    return out


def area_words(area: str | None) -> set[str]:
    return {w for w in _words(area or "") if len(w) > 2 and w not in REGION_NOISE}


def _core(words: list[str], places: set[str]) -> tuple[str, ...]:
    if "by" in words[1:]:                            # "Mursalitsa Hotel by HMG", "Eona Beach by Greek Pride"
        words = words[:words.index("by", 1)]
    words = [w for w in words if w not in WEAK and w not in BRANDS and w != "ex"]
    kept = [w for w in words if w not in places]
    if any(w not in GENERIC and not w.isdigit() for w in kept):
        words = kept                                 # drop place words only if something specific is left
    return tuple(dict.fromkeys(words))               # ordered, unique


def name_key(name: str, area: str | None = None) -> dict:
    """Everything the matcher needs from a name: core words (main + "(ex. old name)" alias),
    the unit after an em dash, the place words in the name, and the digit words."""
    name = name or ""
    unit = None
    parts = _UNIT.split(name, maxsplit=1)
    if len(parts) == 2:
        name, unit = parts[0], " ".join(_words(parts[1])) or None
    aliases = []
    for m in _PAREN.finditer(name):
        inner = _words(m.group(1))
        if inner and inner[0] == "ex":
            aliases.append(inner[1:])
    base = _words(_PAREN.sub(" ", name))
    if "ex" in base:                                 # "Alanya Beach Club ex Holiday Larissa"
        i = base.index("ex")
        if base[i + 1:]:
            aliases.append(base[i + 1:])
        base = base[:i]
    places = PLACES | area_words(area)
    cores = [c for c in (_core(base, places), *(_core(a, places) for a in aliases)) if c]
    return {"cores": cores, "unit": unit, "places": {w for w in base if w in PLACES},
            "digits": {w for w in base if any(ch.isdigit() for ch in w)}}


def _specific(core: tuple[str, ...]) -> list[str]:
    return [w for w in core if w not in GENERIC and w not in PLACES and not w.isdigit()]


def _near(a: str, b: str) -> bool:
    if a == b:
        return True
    return (len(a) >= 5 and len(b) >= 5 and a[0] == b[0]
            and SequenceMatcher(None, a, b).ratio() >= 0.88)


def compare_names(ca: tuple[str, ...], cb: tuple[str, ...], same_source: bool) -> str | None:
    """'exact' / 'subset' / 'fuzzy' / None for two core word tuples."""
    sa, sb = set(ca), set(cb)
    spec = _specific(ca)
    if sa == sb:
        # a generic-only name ("Grand", "Palace") needs at least two words to stand on its own
        return "exact" if spec or len(sa) >= 2 else None
    if same_source:
        return None
    small, big = (sa, sb) if len(sa) < len(sb) else (sb, sa)
    if small < big:
        extra = big - small
        if extra <= SOFT and any(len(w) >= 4 for w in _specific(tuple(small))):
            return "subset"
        return None
    if len(ca) == len(cb) and spec and len(ca) <= 6:
        left = list(cb)
        for w in ca:
            hit = next((x for x in left if _near(w, x)), None)
            if hit is None:
                return None
            left.remove(hit)
        return "fuzzy"
    return None


def token_similarity(ca, cb) -> float:
    """Token-set similarity in [0, 1] (shown in review lists; not used to decide)."""
    sa, sb = set(ca), set(cb)
    if not sa or not sb:
        return 0.0
    inter = " ".join(sorted(sa & sb))
    a, b = " ".join(sorted(sa)), " ".join(sorted(sb))
    return max(SequenceMatcher(None, a, b).ratio(),
               SequenceMatcher(None, inter, a).ratio() if inter else 0,
               SequenceMatcher(None, inter, b).ratio() if inter else 0)


# --- geography --------------------------------------------------------------------------------

def km(a: dict, b: dict) -> float | None:
    try:
        la1, lo1, la2, lo2 = (math.radians(float(x)) for x in (a["lat"], a["lng"], b["lat"], b["lng"]))
    except (KeyError, TypeError, ValueError):
        return None
    d = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(min(1.0, d)))


def _coord(h: dict):
    try:
        return round(float(h["lat"]), 4), round(float(h["lng"]), 4)
    except (KeyError, TypeError, ValueError):
        return None


def _decimals(x) -> int:
    s = repr(float(x))
    return len(s.split(".")[1].rstrip("0")) if "." in s else 0


def coord_counts(hotels) -> dict:
    """How many distinct hotel ids sit on each coordinate."""
    seen: dict = {}
    for h in hotels:
        c = _coord(h)
        if c:
            seen.setdefault(c, set()).add(h.get("id"))
    return {c: len(ids) for c, ids in seen.items()}


def hotel_level(h: dict, counts: dict) -> bool:
    """Coordinates of the building itself, not a resort centroid shared by a source's cards."""
    c = _coord(h)
    if not c or counts.get(c, 0) >= 3:
        return False
    return max(_decimals(h["lat"]), _decimals(h["lng"])) >= 3


# --- the matcher ------------------------------------------------------------------------------

AUTO_PREFIXES = {"ol", "tl", "atl", "bs", "sv", "cs", "ot", "mz", "kop"}   # ids made by trips/sources


def source_of(hotel_id: str) -> str:
    m = re.match(r"([a-z]+)-", hotel_id or "")
    return m.group(1) if m and m.group(1) in AUTO_PREFIXES else "curated"


def _is_villa(h: dict) -> bool:
    return h.get("kind") == "villa"


def match(a: dict, b: dict, counts: dict | None = None, keys: dict | None = None) -> tuple[bool, str]:
    """(same hotel?, reason). Reasons starting with 'blocked' mean "never these two"."""
    counts = counts if counts is not None else coord_counts([a, b])
    ka = keys[a["id"]] if keys and a["id"] in keys else name_key(a.get("name", ""), a.get("area"))
    kb = keys[b["id"]] if keys and b["id"] in keys else name_key(b.get("name", ""), b.get("area"))
    if a.get("season") != b.get("season"):
        return False, "blocked: season"
    if _is_villa(a) != _is_villa(b):
        return False, "blocked: villa vs hotel"
    if ka["unit"] != kb["unit"]:
        return False, "blocked: different unit"
    if ka["digits"] != kb["digits"]:
        return False, "blocked: different numbers"
    if ka["places"] and kb["places"] and not ka["places"] & kb["places"]:
        return False, "blocked: different place in name"
    d = km(a, b)
    both_exact = hotel_level(a, counts) and hotel_level(b, counts)
    if both_exact and d is not None and d > 3:
        return False, f"blocked: {d:.1f} km apart"
    confirmed = both_exact and d is not None and d <= 0.3
    if a.get("area") and b.get("area"):
        if not (area_words(a["area"]) & area_words(b["area"])) and not (d is not None and d <= 15):
            return False, "blocked: different area"
    sa, sb = a.get("stars"), b.get("stars")
    if sa and sb and abs(int(sa) - int(sb)) >= 2 and not confirmed:
        return False, "blocked: stars differ"
    same_source = source_of(a["id"]) == source_of(b["id"]) and source_of(a["id"]) != "curated"
    best = None
    for ca in ka["cores"]:
        for cb in kb["cores"]:
            how = compare_names(ca, cb, same_source)
            if how is None and confirmed and set(ca) == set(cb):
                how = "exact+coords"                 # generic name, but the same building
            if how and (best is None or ["exact+coords", "exact", "subset", "fuzzy"].index(how)
                        < ["exact+coords", "exact", "subset", "fuzzy"].index(best)):
                best = how
    if best:
        return True, best + (" (same source)" if same_source else "") + (f", {d:.2f} km" if confirmed else "")
    return False, "names differ"


# --- run-time merge (drop-in for run.merge_auto) ----------------------------------------------

def merge_auto_v2(known: list[dict], auto_hotels: list[dict], auto_offers: list[dict],
                  images: dict[str, str] | None = None, log: list | None = None) -> list[dict]:
    """Same contract as run.merge_auto: auto hotels matching a known one (or one earlier in this
    batch) are folded into it, offers are remapped in place, and the auto hotels to add are
    returned. `images` collects a folded-in photo for a known hotel without one. `log`, when
    given, receives (auto_id, kept_id, reason) for every fold.
    `known` may also hold the auto hotels already in the database (recommended, see
    proposals/dedupe.md): a fresh card with an id that is already known is returned again so
    its row is refreshed, and a duplicate under a new id folds into the id the history is under."""
    has_photo = {h["id"] for h in known if h.get("image")}
    pool = list(known)
    counts = coord_counts(pool + list(auto_hotels))
    keys = {h["id"]: name_key(h.get("name", ""), h.get("area")) for h in pool + list(auto_hotels)}
    by_season: dict[str, list[dict]] = {}
    for h in pool:
        by_season.setdefault(h.get("season"), []).append(h)
    remap, add = {}, {}
    for h in auto_hotels:
        if h["id"] in remap or h["id"] in add:
            continue
        hit = next((k for k in by_season.get(h.get("season"), []) if k["id"] == h["id"]), None)
        reason = "same id"
        if hit is None:
            for k in by_season.get(h.get("season"), []):
                ok, why = match(h, k, counts, keys)
                if ok:
                    hit, reason = k, why
                    break
        if hit is not None and hit["id"] != h["id"]:
            target = remap.get(hit["id"], hit["id"])
            remap[h["id"]] = target
            if log is not None:
                log.append((h["id"], target, reason))
            if images is not None and h.get("image") and target not in has_photo and target not in add:
                images.setdefault(target, h["image"])
            if target in add and not add[target].get("image") and h.get("image"):
                add[target]["image"] = h["image"]
        elif hit is None:
            add[h["id"]] = h
            by_season.setdefault(h.get("season"), []).append(h)
        elif source_of(h["id"]) != "curated":
            add[h["id"]] = h                         # an auto hotel already in the DB: refresh its row
    for o in auto_offers:
        o["hotel"] = remap.get(o["hotel"], o["hotel"])
    return list(add.values())


# --- one-time clean-up of the database --------------------------------------------------------

def _priority(h: dict, curated: set[str], offers: dict[str, int], counts: dict):
    return (h["id"] not in curated, -offers.get(h["id"], 0), not hotel_level(h, counts),
            not h.get("image"), -(h.get("stars") or 0), len(h["id"]), h["id"])


def find_clusters(hotels: list[dict], curated_ids=(), offer_counts: dict[str, int] | None = None) -> list[dict]:
    """Groups of hotel rows that are the same hotel. Each: {"keep": id, "drop": [ids],
    "reasons": {id: reason}, "names": {id: name}}. A hotel joins a group only if it matches a
    member and is blocked by none of them (no chaining Kleopatra Beach -> ... -> Ada Beach)."""
    curated, offer_counts = set(curated_ids), offer_counts or {}
    counts = coord_counts(hotels)
    keys = {h["id"]: name_key(h.get("name", ""), h.get("area")) for h in hotels}
    groups: list[list[tuple[dict, str]]] = []
    for h in sorted(hotels, key=lambda x: _priority(x, curated, offer_counts, counts)):
        placed = False
        for g in groups:
            if g[0][0].get("season") != h.get("season"):
                continue
            results = [match(h, m, counts, keys) for m, _ in g]
            if any(r[1].startswith("blocked") for r in results):
                continue
            # a group whose kept row is curated only takes rows that match the curated row itself
            ok = [r for r in results if r[0]]
            if ok and (g[0][0]["id"] not in curated or results[0][0]):
                g.append((h, ok[0][1]))
                placed = True
                break
        if not placed:
            groups.append([(h, "")])
    out = []
    for g in groups:
        if len(g) > 1:
            out.append({"keep": g[0][0]["id"], "drop": [m["id"] for m, _ in g[1:]],
                        "reasons": {m["id"]: r for m, r in g[1:]},
                        "names": {m["id"]: m.get("name") for m, _ in g}})
    return out


def near_misses(hotels: list[dict], min_similarity: float = 0.6) -> list[tuple]:
    """Pairs NOT merged that share a specific word, same season and area: for a human to look at."""
    counts = coord_counts(hotels)
    keys = {h["id"]: name_key(h.get("name", ""), h.get("area")) for h in hotels}
    out = []
    hs = sorted(hotels, key=lambda h: h["id"])
    for i, a in enumerate(hs):
        for b in hs[i + 1:]:
            if a.get("season") != b.get("season"):
                continue
            ca, cb = keys[a["id"]]["cores"][:1], keys[b["id"]]["cores"][:1]
            if not ca or not cb or not set(_specific(ca[0])) & set(_specific(cb[0])):
                continue
            ok, why = match(a, b, counts, keys)
            if ok or why in ("blocked: different area", "blocked: different place in name",
                             "blocked: different unit", "blocked: different numbers") \
                    or why.endswith("km apart"):
                continue
            sim = token_similarity(ca[0], cb[0])
            if sim >= min_similarity:
                out.append((round(sim, 2), a["id"], a.get("name"), b["id"], b.get("name"), why))
    return sorted(out, reverse=True)


def _merged_record(keep: dict, drops: list[dict], curated: set[str], counts: dict) -> dict:
    """The kept auto hotel, with gaps (photo, stars, building coordinates, unknown family facts)
    filled from the rows folded into it. Curated rows are never changed (hotels.toml wins)."""
    h = json.loads(json.dumps(keep))
    if h["id"] in curated:
        return h
    fam = h.setdefault("family", {})
    for d in drops:
        if not h.get("image") and d.get("image"):
            h["image"] = d["image"]
        if h.get("stars") is None and d.get("stars") is not None:
            h["stars"] = d["stars"]
        if not hotel_level(h, counts) and hotel_level(d, counts):
            h["lat"], h["lng"] = d["lat"], d["lng"]
        for k, v in (d.get("family") or {}).items():
            if k != "verified" and k not in fam and v is not None:
                fam[k] = v
    return h


def apply_clusters(con, clusters: list[dict], curated_ids=()) -> dict:
    """Fold every dropped hotel into the kept one: offers (+ their price snapshots) are re-keyed,
    campaigns, photos and sent-alert keys follow, drive cache and the hotel row of the dropped id
    are removed. Runs in the caller's transaction; commit afterwards. Returns counts."""
    from . import db
    curated = set(curated_ids)
    hotels = db.hotels(con)
    counts = coord_counts(hotels.values())
    stats = {"hotels_removed": 0, "offers_moved": 0, "offers_folded": 0, "snapshots_moved": 0}
    for c in clusters:
        keep = c["keep"]
        for drop in c["drop"]:
            for r in con.execute("SELECT * FROM offer WHERE hotel_id=?", (drop,)).fetchall():
                old = r["key"]
                new = keep + old[len(drop):] if old.startswith(drop + "|") else old
                if con.execute("SELECT 1 FROM offer WHERE key=?", (new,)).fetchone():
                    con.execute("UPDATE offer SET first_seen=min(first_seen,?), last_seen=max(last_seen,?) "
                                "WHERE key=?", (r["first_seen"], r["last_seen"], new))
                    # same offer seen under both ids at the same moment: keep the cheaper price point
                    stats["snapshots_moved"] += con.execute(
                        "INSERT INTO snapshot(offer_key, seen, price_eur, was_eur, discount_label, valid_until, "
                        "checks) SELECT ?, seen, price_eur, was_eur, discount_label, valid_until, checks "
                        "FROM snapshot WHERE offer_key=? AND true "
                        "ON CONFLICT(offer_key, seen) DO UPDATE SET price_eur=excluded.price_eur, "
                        "was_eur=excluded.was_eur, discount_label=excluded.discount_label, "
                        "valid_until=excluded.valid_until WHERE excluded.price_eur < snapshot.price_eur",
                        (new, old)).rowcount
                    con.execute("DELETE FROM snapshot WHERE offer_key=?", (old,))
                    con.execute("DELETE FROM offer WHERE key=?", (old,))
                    stats["offers_folded"] += 1
                else:
                    con.execute("UPDATE offer SET key=?, hotel_id=? WHERE key=?", (new, keep, old))
                    stats["snapshots_moved"] += con.execute(
                        "UPDATE snapshot SET offer_key=? WHERE offer_key=?", (new, old)).rowcount
                    stats["offers_moved"] += 1
            for r in con.execute("SELECT key FROM campaign WHERE hotel_id=?", (drop,)).fetchall():
                new = keep + r["key"][len(drop):]
                con.execute("UPDATE OR IGNORE campaign SET key=?, hotel_id=? WHERE key=?", (new, keep, r["key"]))
                con.execute("DELETE FROM campaign WHERE key=?", (r["key"],))      # left only on a clash
            img = con.execute("SELECT url, seen FROM hotel_image WHERE hotel_id=?", (drop,)).fetchone()
            if img:
                con.execute("INSERT OR IGNORE INTO hotel_image(hotel_id, url, seen) VALUES(?,?,?)",
                            (keep, img["url"], img["seen"]))
                con.execute("DELETE FROM hotel_image WHERE hotel_id=?", (drop,))
            for r in con.execute("SELECT key, sent_at FROM alert_sent WHERE key LIKE ?",
                                 (f"%|{drop}|%",)).fetchall():
                con.execute("INSERT OR IGNORE INTO alert_sent(key, sent_at) VALUES(?,?)",
                            (r["key"].replace(f"|{drop}|", f"|{keep}|"), r["sent_at"]))
            con.execute("DELETE FROM drive_cache WHERE hotel_id=?", (drop,))
            con.execute("DELETE FROM hotel WHERE id=?", (drop,))
            stats["hotels_removed"] += 1
        if keep in hotels:
            rec = _merged_record(hotels[keep], [hotels[d] for d in c["drop"] if d in hotels], curated, counts)
            if rec != hotels[keep]:
                db.upsert_hotel(con, rec)
                if (rec.get("lat"), rec.get("lng")) != (hotels[keep].get("lat"), hotels[keep].get("lng")):
                    con.execute("DELETE FROM drive_cache WHERE hotel_id=?", (keep,))
    return stats


def aliases(clusters: list[dict]) -> dict[str, str]:
    """old id -> kept id (for shortlists saved in browsers, see proposals/dedupe.md)."""
    return {d: c["keep"] for c in clusters for d in c["drop"]}


def main(argv=None) -> int:
    """python -m trips.dedupe [--db data/trips.db] [--apply]  (dry run by default)"""
    import argparse
    import shutil
    from datetime import datetime
    from pathlib import Path

    from . import db
    from .sources import manual
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/trips.db")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    con = db.connect(args.db)
    curated = {h["id"] for h in manual.load_hotels()}
    hotels = list(db.hotels(con).values())
    n_offers = {r[0]: r[1] for r in con.execute("SELECT hotel_id, count(*) FROM offer GROUP BY hotel_id")}
    clusters = find_clusters(hotels, curated, n_offers)
    names = {h["id"]: h["name"] for h in hotels}
    for c in clusters:
        print(f"KEEP {c['keep']:<28} {names[c['keep']]}")
        for d in c["drop"]:
            print(f"  <- {d:<26} {names[d]:<40} [{c['reasons'][d]}] offers={n_offers.get(d, 0)}")
    print(f"\n{len(clusters)} clusters, {sum(len(c['drop']) for c in clusters)} duplicate rows, "
          f"{len(hotels)} -> {len(hotels) - sum(len(c['drop']) for c in clusters)} hotels")
    print("\nNot merged, worth a look:")
    for row in near_misses(hotels):
        print("  ", *row, sep=" | ")
    if args.apply:
        backup = Path(args.db).with_suffix(f".db.bak-dedupe-{datetime.now():%Y%m%d%H%M}")
        con.commit()
        shutil.copy2(args.db, backup)
        print("backup:", backup)
        print(apply_clusters(con, clusters, curated))
        con.commit()
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
