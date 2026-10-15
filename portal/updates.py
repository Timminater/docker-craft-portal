"""Explicit, cached portal release discovery without installing container code."""
from __future__ import annotations

from datetime import date
import json
import re
import threading
import time
from urllib.error import HTTPError

from .updater import Updater
from .version import VERSION

REPOSITORIES = ("Timminater/craft-portal", "Timminater/docker-craft-portal")
CACHE_SECONDS = 15 * 60


def version_parts(value: str) -> tuple[int, int, int, int]:
    """Stable calendar versions only; reject prereleases and malformed dates."""
    if not isinstance(value, str) or not re.fullmatch(r"v[0-9]{4}\.[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,6}", value):
        raise ValueError("Invalid stable portal version")
    year, month, day, revision = map(int, value[1:].split("."))
    date(year, month, day)
    return year, month, day, revision


class PortalUpdates:
    def __init__(self, updater: Updater):
        self.updater = updater
        self.lock = threading.Lock()
        self.check_lock = threading.Lock()
        self.latest_version = None
        self.release_url = None
        self.checked_at = None
        self.check_error = None

    def status(self, *, admin=False):
        with self.lock:
            latest = self.latest_version
            state = {"version": VERSION, "latest_version": latest,
                     "release_url": self.release_url, "checked_at": self.checked_at,
                     "check_error": self.check_error,
                     "update_available": bool(latest and version_parts(latest) > version_parts(VERSION))}
        state["updater"] = self.updater.snapshot(admin=admin)
        return state

    def check(self, *, admin=True):
        # A click is the only trigger. Serialize checks without blocking status
        # snapshots during slow network access.
        with self.check_lock:
            now = time.time()
            with self.lock:
                cached = self.checked_at is not None and now - self.checked_at < CACHE_SECONDS
            if not cached:
                latest = release_url = None
                error = None
                try:
                    for index, repository in enumerate(REPOSITORIES):
                        try:
                            raw = self.updater.request(f"https://api.github.com/repos/{repository}/releases/latest", limit=512_000)
                            break
                        except HTTPError as exc:
                            # Only a missing renamed repository permits the
                            # exact old repository; outages do not change trust.
                            if index == 0 and exc.code == 404:
                                continue
                            raise
                    release = json.loads(raw)
                    tag = release.get("tag_name")
                    version_parts(tag)
                    if release.get("draft") or release.get("prerelease"):
                        raise ValueError("Not a stable release")
                    expected = f"https://github.com/{repository}/releases/tag/{tag}"
                    if release.get("html_url") != expected:
                        raise ValueError("Unexpected release URL")
                    latest, release_url = tag, expected
                except (ValueError, TypeError, AttributeError):
                    error = "invalid_release"
                except Exception:
                    # Never return network exceptions: URLs/headers can carry
                    # deployment details or credentials from a proxy.
                    error = "unavailable"
                with self.lock:
                    if error is None:
                        self.latest_version, self.release_url = latest, release_url
                    self.check_error = error
                    self.checked_at = now
        return self.status(admin=admin)
