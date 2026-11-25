"""Manual source: offers typed in from agency pages looked at by hand (data/offers.toml).

Why manual first: Fibula (the main Skopje operator) loads its prices from a
private API host, and its robots.txt disallows /api/ and /search? for robots.
So we don't scrape its prices — we record what we see in the browser, and the
engine still builds price history, checks the discount and scores the family fit.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

REQUIRED = ("hotel", "source", "seen", "check_in", "nights", "board", "price_eur")


def load(path: str | Path = "data/offers.toml") -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    out = []
    for i, o in enumerate(data.get("offer", []), 1):
        missing = [k for k in REQUIRED if k not in o]
        if missing:
            raise ValueError(f"offers.toml entry #{i} is missing {', '.join(missing)}")
        o = dict(o)
        for k in ("seen", "check_in", "valid_until"):
            if k in o:
                o[k] = str(o[k])
        o.setdefault("occupancy", "2+2")
        out.append(o)
    return out


def load_hotels(path: str | Path = "data/hotels.toml") -> list[dict]:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    hotels = data.get("hotel", [])
    ids = [h["id"] for h in hotels]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"hotels.toml has duplicate ids: {', '.join(sorted(dupes))}")
    return hotels
