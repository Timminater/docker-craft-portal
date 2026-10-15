"""Bounded, authenticated presentation artwork from the official ArtCraft site."""
from __future__ import annotations

import os
from http.client import HTTPException
from pathlib import Path
import re
import tempfile
import threading
import time
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BYTES = 2 * 1024 * 1024
NEGATIVE_TTL = 3600
SLUG = re.compile(r'^[a-z][a-z0-9]{1,29}craft$')
KINDS = {'icon', 'hero'}
FALLBACK = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 160"><rect width="256" height="160" rx="16" fill="#173a40"/><path d="m128 28 15 35 37 17-37 17-15 35-15-35-37-17 37-17z" fill="#55dfbb"/></svg>'''


def trusted_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return (parsed.scheme == 'https' and parsed.hostname in {'getartcraft.com', 'www.getartcraft.com'}
                and parsed.port in {None, 443} and parsed.username is None and parsed.password is None
                and not any(c.isspace() for c in url) and '\\' not in url)
    except ValueError:
        return False


class ArtworkRedirect(HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 1

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not trusted_url(newurl):
            raise ValueError('Artwork redirect outside official HTTPS hosts')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def valid_webp(data: bytes) -> bool:
    return (20 <= len(data) <= MAX_BYTES and data[:4] == b'RIFF' and data[8:12] == b'WEBP'
            and int.from_bytes(data[4:8], 'little') + 8 == len(data)
            and data[12:16] in {b'VP8 ', b'VP8L', b'VP8X'})


class Artwork:
    def __init__(self, data_dir: Path, static_dir: Path, network: bool):
        self.cache = data_dir / 'artwork'
        self.static = static_dir / 'artcraft'
        self.network = network
        # Deliberately independent of the release opener: no GitHub authentication.
        self.opener = build_opener(ArtworkRedirect)
        self.failures: dict[tuple[str, str], float] = {}
        self.locks: dict[tuple[str, str], threading.Lock] = {}
        self.guard = threading.Lock()

    def get(self, slug: str, kind: str) -> tuple[bytes, str]:
        if not SLUG.fullmatch(slug) or kind not in KINDS:
            raise ValueError('Invalid artwork identifier')
        key = (slug, kind)
        with self.guard:
            lock = self.locks.setdefault(key, threading.Lock())
        with lock:
            path = self.cache / slug / f'{kind}.webp'
            try:
                with path.open('rb') as cached:
                    data = cached.read(MAX_BYTES + 1)
                if valid_webp(data):
                    return data, 'image/webp'
            except OSError:
                pass
            if slug == 'solidcraft':
                try:
                    with (self.static / slug / f'{kind}.png').open('rb') as bundled:
                        data = bundled.read(MAX_BYTES + 1)
                    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) <= MAX_BYTES:
                        return data, 'image/png'
                except OSError:
                    pass
                return FALLBACK, 'image/svg+xml'
            if self.network and self.failures.get(key, 0) <= time.monotonic():
                try:
                    data = self._fetch(slug, kind)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temp = None
                    try:
                        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.artwork-', delete=False) as output:
                            temp = Path(output.name)
                            output.write(data)
                        os.replace(temp, path)
                    finally:
                        if temp is not None:
                            temp.unlink(missing_ok=True)
                    self.failures.pop(key, None)
                    return data, 'image/webp'
                except (OSError, ValueError, HTTPException):
                    self.failures[key] = time.monotonic() + NEGATIVE_TTL
            if kind == 'icon':
                try:
                    with (self.static / slug / 'icon.png').open('rb') as bundled:
                        data = bundled.read(MAX_BYTES + 1)
                    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) <= MAX_BYTES:
                        return data, 'image/png'
                except OSError:
                    pass
            return FALLBACK, 'image/svg+xml'

    def _fetch(self, slug: str, kind: str) -> bytes:
        url = f'https://getartcraft.com/images/apps/{slug}/{kind}.webp'
        request = Request(url, headers={'User-Agent': 'Docker-Craft-Portal/1', 'Accept': 'image/webp'})
        with self.opener.open(request, timeout=5) as response:
            if not trusted_url(response.geturl()):
                raise ValueError('Invalid artwork response origin')
            length = response.headers.get('Content-Length')
            if length is not None and (not length.isdecimal() or int(length) > MAX_BYTES):
                raise ValueError('Artwork too large')
            data = response.read(MAX_BYTES + 1)
        if not valid_webp(data):
            raise ValueError('Invalid WebP artwork')
        return data
