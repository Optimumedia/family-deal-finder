"""Per-source run stats → docs/health.json, so the dashboard can say "Olympic failed today".

    health = RunHealth()
    with health.track("Olympic", session) as st:
        hotels, offers = olympic.fetch(cfg, today, session=session)
        st.offers_parsed = len(offers)
    health.add_rejects(validate.by_source(rejects))
    report = health.write()           # docs/health.json + data/health-history.json

`track` times the block, reads the PoliteSession's counters (pages, blocked, errors), keeps the
source's warnings, and catches any exception so one broken source never stops the whole run.

A source that returns 0 offers while its last-7-runs average was at least `min_avg` is flagged
"zero": the site most likely changed its layout or started refusing us.
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .http import Blocked

log = logging.getLogger(__name__)

OK, PARTIAL, BLOCKED, ERROR, ZERO, IDLE = "ok", "partial", "blocked", "error", "zero", "idle"
FAILED = (BLOCKED, ERROR, ZERO)
KEEP_RUNS = 60


@dataclass
class SourceStats:
    name: str
    status: str = OK
    pages_fetched: int = 0
    not_modified: int = 0
    offers_parsed: int = 0
    offers_rejected: int = 0
    blocked: int = 0
    errors: int = 0
    duration_s: float = 0.0
    avg_offers_7: float | None = None
    messages: list[str] = field(default_factory=list)
    crashed: bool = False


class _Collect(logging.Handler):
    def __init__(self, st: SourceStats, keep: int = 5):
        super().__init__(logging.WARNING)
        self.st, self.keep = st, keep

    def emit(self, record):
        if len(self.st.messages) < self.keep:
            self.st.messages.append(record.getMessage()[:300])


def rolling_average(history: list[dict], name: str, window: int = 7) -> float | None:
    """Average offers of `name` over its last `window` recorded runs (None if never seen)."""
    counts = [r["sources"][name] for r in history if name in r.get("sources", {})][-window:]
    return sum(counts) / len(counts) if counts else None


def classify(st: SourceStats, avg: float | None, min_avg: float = 3.0, used_session: bool = True) -> str:
    if st.crashed:
        return ERROR
    if st.blocked and st.offers_parsed == 0:
        return BLOCKED
    if st.offers_parsed == 0 and avg is not None and avg >= min_avg:
        return ZERO
    if st.offers_parsed == 0 and st.errors and not st.pages_fetched:
        return ERROR
    if st.blocked or st.errors or (st.offers_parsed and st.offers_rejected * 2 >= st.offers_parsed):
        return PARTIAL
    if used_session and st.pages_fetched == 0 and st.offers_parsed == 0:
        return IDLE                         # disabled in config, or nothing configured
    return OK


def describe(st: SourceStats) -> str | None:
    """One line for the dashboard, or None when nothing is wrong."""
    avg = f"{st.avg_offers_7:.0f}" if st.avg_offers_7 is not None else "?"
    first = f" ({st.messages[0]})" if st.messages else ""
    match st.status:
        case "error":
            return f"{st.name} failed today{first}"
        case "blocked":
            return f"{st.name} refused us today (bot wall or robots.txt), 0 offers{first}"
        case "zero":
            return f"{st.name} returned 0 offers today (usually ~{avg}); the page layout may have changed"
        case "partial":
            bits = []
            if st.blocked:
                bits.append("blocked part-way")
            if st.errors:
                bits.append(f"{st.errors} page(s) failed")
            if st.offers_rejected:
                bits.append(f"{st.offers_rejected} of {st.offers_parsed} offers rejected by validation")
            return f"{st.name}: " + ", ".join(bits)
    return None


class RunHealth:
    def __init__(self, history_path: str | Path = "data/health-history.json", window: int = 7,
                 min_avg: float = 3.0):
        self.history_path, self.window, self.min_avg = Path(history_path), window, min_avg
        self.started = time.monotonic()
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.sources: dict[str, SourceStats] = {}
        self._session_used: dict[str, bool] = {}

    @contextmanager
    def track(self, name: str, session=None):
        st = self.sources.setdefault(name, SourceStats(name))
        self._session_used[name] = session is not None
        before = dict(getattr(session, "stats", {}) or {})
        handler = _Collect(st)
        root = logging.getLogger("trips")
        root.addHandler(handler)
        t0 = time.monotonic()
        try:
            yield st
        except Blocked as e:                         # a bot wall the source didn't catch itself
            st.blocked += 1
            st.messages.insert(0, str(e)[:300])
            log.warning("%s stopped (respecting the block): %s", name, e)
        except Exception as e:                       # one broken source must not stop the run
            st.crashed = True
            st.errors += 1
            st.messages.insert(0, f"{type(e).__name__}: {e}"[:300])
            log.exception("%s crashed; carrying on with the other sources", name)
        finally:
            root.removeHandler(handler)
            st.duration_s = round(st.duration_s + time.monotonic() - t0, 1)
            after = getattr(session, "stats", None) or {}
            delta = {k: after.get(k, 0) - before.get(k, 0) for k in ("pages", "not_modified", "blocked", "errors")}
            st.pages_fetched += delta["pages"]
            st.not_modified += delta["not_modified"]
            st.blocked += delta["blocked"]
            st.errors += delta["errors"]

    def add_rejects(self, by_source: dict[str, dict]) -> None:
        """validate.by_source(rejects) → offers_rejected per source."""
        for name, r in by_source.items():
            self.sources.setdefault(name, SourceStats(name)).offers_rejected += r["rejected"]
        self._rejects = by_source

    def _load_history(self) -> list[dict]:
        try:
            return json.loads(self.history_path.read_text(encoding="utf-8")).get("runs", [])
        except (OSError, ValueError, AttributeError):
            return []

    def report(self, history: list[dict] | None = None) -> dict:
        history = self._load_history() if history is None else history
        for st in self.sources.values():
            st.avg_offers_7 = rolling_average(history, st.name, self.window)
            if st.avg_offers_7 is not None:
                st.avg_offers_7 = round(st.avg_offers_7, 1)
            st.status = classify(st, st.avg_offers_7, self.min_avg, self._session_used.get(st.name, False))
        problems = [p for p in (describe(s) for s in self.sources.values()) if p]
        failed = [s.name for s in self.sources.values() if s.status in FAILED]
        return {
            "generated": datetime.now().isoformat(timespec="minutes"),
            "started": self.started_at,
            "duration_s": round(time.monotonic() - self.started, 1),
            "status": "fail" if failed else "warn" if problems else "ok",
            "failed_sources": failed,
            "problems": problems,
            "sources": [{k: v for k, v in asdict(s).items() if k != "crashed"} for s in self.sources.values()],
            "rejected_by_source": getattr(self, "_rejects", {}),
        }

    def write(self, path: str | Path = "docs/health.json") -> dict:
        history = self._load_history()
        rep = self.report(history)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        # Only runs where the source didn't crash count toward its normal level.
        history.append({"at": self.started_at,
                        "sources": {s.name: s.offers_parsed for s in self.sources.values() if not s.crashed}})
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text(json.dumps({"runs": history[-KEEP_RUNS:]}, indent=1), encoding="utf-8")
        for p in rep["problems"]:
            log.warning("health: %s", p)
        return rep
