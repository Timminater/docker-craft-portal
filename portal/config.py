from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Config:
    data_dir: Path
    public_url: str
    apps_domain: str
    single_app_url: str = ""
    trusted_owner: str = "storytold"
    catalog_url: str = "https://getartcraft.com/apps"
    github_token: str = ""
    auto_start_updates: bool = True
    max_zip_bytes: int = 220 * 1024 * 1024
    max_extracted_bytes: int = 1_000 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Config":
        public_url = os.getenv("CRAFT_PUBLIC_URL", "http://localhost:8080").rstrip("/")
        parsed = urlparse(public_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path not in {"", "/"}:
            raise ValueError("CRAFT_PUBLIC_URL must be an origin URL (e.g. https://craft.example.com)")
        domain = os.getenv("CRAFT_APPS_DOMAIN", "").strip().lower().rstrip(".")
        if domain and (parsed.scheme != "https" or "." not in domain or domain == parsed.hostname):
            raise ValueError("CRAFT_APPS_DOMAIN requires a distinct hostname and an HTTPS public URL")
        if domain and domain.endswith(".localhost"):
            raise ValueError("CRAFT_APPS_DOMAIN must have valid TLS")
        if domain and os.getenv("CRAFT_SINGLE_APP_URL", "").strip():
            raise ValueError("Configure either CRAFT_APPS_DOMAIN or CRAFT_SINGLE_APP_URL, not both")
        single = os.getenv("CRAFT_SINGLE_APP_URL", "").strip().rstrip("/")
        if not domain and not single and parsed.hostname == "localhost" and parsed.scheme == "http":
            # Development convenience: distinct hostname/origin, same server and port.
            single = f"http://127.0.0.1:{parsed.port or 80}"
        if single:
            sp = urlparse(single)
            if sp.scheme not in {"https", "http"} or not sp.hostname or sp.netloc == parsed.netloc or sp.path not in {"", "/"}:
                raise ValueError("CRAFT_SINGLE_APP_URL must be a distinct origin")
            if sp.scheme != "https" and sp.hostname not in {"localhost", "127.0.0.1"}:
                raise ValueError("CRAFT_SINGLE_APP_URL requires HTTPS outside local development")
        return cls(
            data_dir=Path(os.getenv("CRAFT_DATA_DIR", "/data")).expanduser().resolve(),
            public_url=public_url,
            apps_domain=domain,
            single_app_url=single,
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
        return bool(self.apps_domain)

    @property
    def app_origin_configured(self) -> bool:
        return bool(self.apps_domain or self.single_app_url)
