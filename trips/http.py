"""Polite HTTP client: rate limited per host, robots.txt aware, gives up on bot walls.

If a site answers with a CAPTCHA / bot challenge we stop and report it —
we never try to get around it.

Optional conditional-GET cache (`cache_path=`): pages that came with an ETag or
Last-Modified header are stored, and the next run asks with If-None-Match /
If-Modified-Since. A "304 Not Modified" answer costs the server almost nothing
and we reuse the stored page. Servers that send neither header are fetched in
full as before.
"""
from __future__ import annotations

import logging
import random
import sqlite3
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

USER_AGENT = "family-deal-finder/0.1 (personal, low-volume trip planner; honest bot, obeys robots.txt)"
_CHALLENGE_MARKERS = ("Just a moment...", "cf-chl-", "challenge-error-text", "Attention Required!", "captcha")


class Blocked(Exception):
    """The site served a bot challenge or refused us; stop scraping it this run."""


class Unavailable(requests.RequestException):
    """One page kept timing out or erroring — skip it and carry on (not a block)."""


class _Cache:
    """url -> (etag, last_modified, body) in a small SQLite file (on this PC only, never published)."""

    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(path))
        self.con.execute("CREATE TABLE IF NOT EXISTS page (url TEXT PRIMARY KEY, etag TEXT, last_modified TEXT, "
                         "body TEXT NOT NULL, stored REAL NOT NULL)")

    def get(self, url: str):
        return self.con.execute("SELECT etag, last_modified, body FROM page WHERE url=?", (url,)).fetchone()

    def put(self, url: str, etag: str | None, last_modified: str | None, body: str) -> None:
        self.con.execute("INSERT OR REPLACE INTO page(url, etag, last_modified, body, stored) VALUES(?,?,?,?,?)",
                         (url, etag, last_modified, body, time.time()))
        self.con.commit()


class PoliteSession:
    """Waits `delay` + up to `jitter` seconds between two requests to the same host. Each host has
    its own clock, so a slow site never slows another. `host_delays` raises the minimum for named
    hosts, e.g. {"www.olympic.rs": 10}. `stats` counts what happened, for the run's health report."""

    def __init__(self, delay: float = 2.5, jitter: float = 1.5, timeout: float = 25,
                 host_delays: dict[str, float] | None = None, cache_path: str | Path | None = None):
        self.delay, self.jitter, self.timeout = delay, jitter, timeout
        self.host_delays = dict(host_delays or {})
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "mk,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml",
        })
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._cache = _Cache(cache_path) if cache_path else None
        self.requests_made = 0
        self.stats = {"pages": 0, "not_modified": 0, "blocked": 0, "errors": 0}

    def _allowed(self, url: str) -> bool:
        host = urlparse(url).netloc
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            self._wait(host)
            self._last[host] = time.monotonic()
            try:
                r = self.s.get(f"https://{host}/robots.txt", timeout=self.timeout)
                rp.parse(r.text.splitlines() if r.ok else [])
            except requests.RequestException:
                rp.parse([])
            self._robots[host] = rp
        return self._robots[host].can_fetch(USER_AGENT, url)

    def min_delay(self, host: str) -> float:
        return max(self.delay, self.host_delays.get(host, 0.0))

    def _wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is None:
            return
        pause = self.min_delay(host) + random.uniform(0, self.jitter) - (time.monotonic() - last)
        if pause > 0:
            time.sleep(pause)

    def _conditional(self, url: str) -> tuple[dict, tuple | None]:
        hit = self._cache.get(url) if self._cache else None
        headers = {}
        if hit:
            if hit[0]:
                headers["If-None-Match"] = hit[0]
            if hit[1]:
                headers["If-Modified-Since"] = hit[1]
        return headers, hit

    def get(self, url: str) -> str:
        if not self._allowed(url):
            self.stats["blocked"] += 1
            raise Blocked(f"robots.txt disallows {url}")
        host = urlparse(url).netloc
        for attempt in range(3):
            self._wait(host)
            self._last[host] = time.monotonic()
            self.requests_made += 1
            headers, hit = self._conditional(url)
            try:
                r = self.s.get(url, timeout=self.timeout, headers=headers or None)
            except requests.RequestException as e:
                log.warning("request failed (%s): %s", attempt + 1, e)
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 304 and hit:
                self.stats["pages"] += 1
                self.stats["not_modified"] += 1
                return hit[2]
            head = r.text[:4000]
            challenge = any(m in head for m in _CHALLENGE_MARKERS[:4])
            if r.status_code == 403 or challenge:
                self.stats["blocked"] += 1
                raise Blocked(f"{r.status_code} bot challenge at {url}")
            # A plain 503 is the site being overloaded, not a wall: retry like any 5xx.
            if r.status_code == 404:          # e.g. past the last search page
                return ""
            if r.status_code == 429:
                time.sleep(30 * (attempt + 1))
                continue
            if r.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            try:
                r.raise_for_status()
            except requests.RequestException:
                self.stats["errors"] += 1
                raise
            r.encoding = r.encoding or "utf-8"
            self.stats["pages"] += 1
            etag, modified = r.headers.get("ETag"), r.headers.get("Last-Modified")
            if self._cache and (etag or modified):
                self._cache.put(url, etag, modified, r.text)
            return r.text
        self.stats["errors"] += 1
        raise Unavailable(f"gave up after retries: {url}")
