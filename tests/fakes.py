"""Shared test doubles: a fake PoliteSession that serves saved fixture files by URL pattern.

    s = FakeSession([(r"travelland\\.rs/services/list/.*paginate=1\\b", "travelland_list_bansko.json")])
    s.get("https://www.travelland.rs/services/list/?...&paginate=1")   # -> the fixture's text

No network: a URL that matches no route answers "" (what PoliteSession returns for a 404) and is
recorded in `misses`. A route's target is a fixture file name (read from tests/fixtures), a literal
string (anything with a "<" or "{" in it), a callable(url) -> str, or an exception instance to raise
(e.g. trips.http.Blocked("...")). The first matching route wins.

Same public surface as trips.http.PoliteSession as far as the sources, enrich and health use it:
get(url), stats{pages, not_modified, blocked, errors}, requests_made, min_delay(host).
"""
from __future__ import annotations

import re
import socket
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from trips.http import Blocked

FIXTURES = Path(__file__).parent / "fixtures"
EMPTY_LIST = '{"html": "", "total": 0}'      # an Olympic/Travelland /services/list/ page past the end


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="ignore")


class FakeSession:
    def __init__(self, routes=(), default: str = ""):
        self.routes = [(re.compile(p), target) for p, target in routes]
        self.default = default
        self.urls: list[str] = []
        self.misses: list[str] = []
        self.requests_made = 0
        self.stats = {"pages": 0, "not_modified": 0, "blocked": 0, "errors": 0}
        self._files: dict[str, str] = {}

    # PoliteSession(delay, jitter, timeout, host_delays=..., cache_path=...) signature, ignored
    @classmethod
    def factory(cls, routes, default: str = "", log: list | None = None):
        """A drop-in for the PoliteSession class: every call returns a new FakeSession on the same
        routes. Pass `log` to collect every session made (to inspect urls/misses afterwards)."""
        def make(*_a, **_kw):
            s = cls(routes, default)
            if log is not None:
                log.append(s)
            return s
        return make

    def min_delay(self, host: str) -> float:
        return 0.0

    def _resolve(self, target, url: str) -> str:
        if isinstance(target, BaseException):
            raise target
        if callable(target):
            return target(url)
        if "<" in target or "{" in target or not target.strip():
            return target
        if target not in self._files:
            self._files[target] = fixture(target)
        return self._files[target]

    def get(self, url: str) -> str:
        self.urls.append(url)
        self.requests_made += 1
        for pattern, target in self.routes:
            if pattern.search(url):
                try:
                    body = self._resolve(target, url)
                except Blocked:
                    self.stats["blocked"] += 1
                    raise
                self.stats["pages"] += 1
                return body
        self.misses.append(url)
        return self.default


class NetworkUsed(AssertionError):
    pass


@contextmanager
def no_network():
    """Any socket connect inside the block fails the test (so an unpatched fetch can't go live)."""
    def refuse(*a, **kw):
        raise NetworkUsed(f"test tried to open a network connection: {a[1:] if len(a) > 1 else a}")
    with mock.patch.object(socket.socket, "connect", refuse), \
            mock.patch.object(socket, "create_connection", refuse):
        yield
