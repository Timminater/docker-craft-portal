from __future__ import annotations

import os
import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Config:
    data_dir: Path
    public_url: str
    apps_domain: str
    single_app_url: str = ""
    shared_app_multi_user: bool = False
    trusted_owner: str = "storytold"
    catalog_url: str = "https://getartcraft.com/apps"
    github_token: str = ""
    auto_start_updates: bool = True
    max_zip_bytes: int = 220 * 1024 * 1024
    max_extracted_bytes: int = 1_000 * 1024 * 1024

    def __post_init__(self):
        def origin(value: str, name: str):
            parsed = urlparse(value)
            try:
                port = parsed.port
            except ValueError as exc:
                raise ValueError(f"{name} has an invalid port") from exc
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment
                    or "?" in value or "#" in value or "\\" in value
                    or any(c.isspace() for c in value) or parsed.netloc.endswith(":")):
                raise ValueError(f"{name} must be an origin URL without credentials, query or fragment")
            host = parsed.hostname.lower()
            try:
                ipaddress.ip_address(host)
            except ValueError:
                if not valid_hostname(host):
                    raise ValueError(f"{name} has an invalid hostname")
            if port == 0:
                raise ValueError(f"{name} has an invalid port")
            return parsed

        def valid_hostname(host: str) -> bool:
            return len(host) <= 253 and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
                                           for part in host.split("."))

        public = origin(self.public_url, "CRAFT_PUBLIC_URL")
        domain = self.apps_domain.strip().lower().rstrip(".")
        single = self.single_app_url
        if domain:
            if (not valid_hostname(domain) or "." not in domain or domain.endswith(".localhost")
                    or domain == public.hostname or public.scheme != "https"):
                raise ValueError("CRAFT_APPS_DOMAIN requires a valid distinct DNS hostname and HTTPS public URL")
            if single:
                raise ValueError("Configure either CRAFT_APPS_DOMAIN or CRAFT_SINGLE_APP_URL, not both")
        if single:
            app = origin(single, "CRAFT_SINGLE_APP_URL")
            # Cookies are scoped to hostname, regardless of port or scheme.
            if app.hostname == public.hostname:
                raise ValueError("CRAFT_SINGLE_APP_URL requires a distinct hostname")
            if app.scheme != public.scheme:
                raise ValueError("Portal and app origins must use the same scheme")
            if app.scheme != "https" and (app.hostname not in {"localhost", "127.0.0.1", "::1"}
                                           or public.hostname not in {"localhost", "127.0.0.1", "::1"}):
                raise ValueError("CRAFT_SINGLE_APP_URL requires HTTPS outside local development")
        if self.shared_app_multi_user and (not single or domain):
            raise ValueError("CRAFT_SHARED_APP_MULTI_USER requires CRAFT_SINGLE_APP_URL without CRAFT_APPS_DOMAIN")
        object.__setattr__(self, "public_url", self.public_url.rstrip("/"))
        object.__setattr__(self, "single_app_url", single.rstrip("/"))
        object.__setattr__(self, "apps_domain", domain)

    @classmethod
    def from_env(cls) -> "Config":
        public_url = os.getenv("CRAFT_PUBLIC_URL", "http://localhost:8080").rstrip("/")
        parsed = urlparse(public_url)
        domain = os.getenv("CRAFT_APPS_DOMAIN", "").strip().lower().rstrip(".")
        single = os.getenv("CRAFT_SINGLE_APP_URL", "").strip().rstrip("/")
        if not domain and not single and parsed.hostname == "localhost" and parsed.scheme == "http":
            # Development convenience: distinct hostname/origin, same server and port.
            single = f"http://127.0.0.1:{parsed.port or 80}"
        return cls(
            data_dir=Path(os.getenv("CRAFT_DATA_DIR", "/data")).expanduser().resolve(),
            public_url=public_url,
            apps_domain=domain,
            single_app_url=single,
            shared_app_multi_user=os.getenv("CRAFT_SHARED_APP_MULTI_USER", "false").lower() in {"1", "true", "on"},
            github_token=os.getenv("GITHUB_TOKEN", ""),
            auto_start_updates=os.getenv("CRAFT_AUTO_START_UPDATES", "true").lower() not in {"0", "false", "off"},
        )

    @property
    def portal_host(self) -> str:
        return urlparse(self.public_url).netloc.lower()

    @property
    def secure_cookie(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def multi_user(self) -> bool:
        return bool(self.apps_domain) or self.shared_app_multi_user

    @property
    def isolated_app_origins(self) -> bool:
        return bool(self.apps_domain)

    @property
    def app_origin_mode(self) -> str:
        if self.isolated_app_origins:
            return "isolated"
        if self.single_app_url:
            return "shared" if self.shared_app_multi_user else "single"
        return "none"

    @property
    def app_origin_configured(self) -> bool:
        return bool(self.apps_domain or self.single_app_url)
