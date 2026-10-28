# Craft Portal

Self-hosted, login-protected web portal for all *official* ArtCraft WebAssembly apps. **One Docker container**, no Linux desktop streaming, no per-app containers, no runtime Rust compilation. The release updater automatically discovers compatible new apps in the official [ArtCraft catalog](https://getartcraft.com/apps), downloads verified official release ZIPs, installs versions transactionally and retains the previous two releases.

> **Stable release: v2026.10.28.2.** Includes personal account security, browser storage information, dock selection and a version/update overview. Authentication, updates, backups, Chromium/Firefox browser workflows and multiarchitecture builds are release-gated. Real PhotoCraft and SolidCraft releases have also been exercised. App-specific compatibility and native ARM64 runtime verification are tracked in [acceptance evidence](docs/ACCEPTANCE.md) and [known limitations](docs/KNOWN_LIMITATIONS.md).

## Features already implemented

- Responsive dark dashboard, favorites, app launch, native installer links from official GitHub Releases.
- First-start admin provisioning via one-time code printed in private Docker logs; Argon2id password hashes, SQLite accounts and opaque revocable HttpOnly sessions.
- User/admin roles, CSRF and Origin checks for state-changing APIs, basic in-memory login rate limiting, exact Host validation.
- Personal account settings: password changes, owned device/session revocation and optional authenticator-based two-step verification with single-use recovery codes.
- Browser storage estimates and persistent-storage requests on the actual app origin, with honest local-document backup guidance.
- Account-specific app order and dock visibility; open hidden apps stay switchable until closed.
- Portal version/release overview and live app updater phases/download progress. See [personal settings](docs/personal-settings.md).
- Official catalog discovery every **6 hours**, automatic new-app addition and auto-updating stable WASM releases.
- Checks trusted GitHub issuer/release ZIP name, download URL, digest and size; rejects suspicious ZIP paths, links and decompression bombs. Extracts into staging, activates atomically, keeps active + **2 previous versions**.
- Admin UI for checks, version rollback, app auto-update pause, settings, accounts (multi-user only), logs and disk usage.
- Administrators can review and explicitly change the exact GitHub repository for an installed app. Only choose repositories whose code you trust to run in users' browsers.
- Optional host-isolated multi-user mode using a unique `app--user` subdomain/origin per app and account, with one-time launch tickets in URL fragments.
- Separate app version URLs and persisting files and SQLite under `/data`. For security, the app-serving origin is always different from the administrator portal origin.

## Quickstart (local development)

```bash
python -m pip install -r requirements-dev.txt
export CRAFT_DATA_DIR="$(pwd)/data"
export CRAFT_PUBLIC_URL=http://localhost:8080
uvicorn portal.main:app --host 127.0.0.1 --port 8080
```

Open <http://localhost:8080>. Find the first-start administrator code in the console, set username and strong password, and sign in. In local-only development, apps open on the separate origin <http://127.0.0.1:8080> automatically (same container, different browser origin). Startup schedules the initial official release check in a background thread and checks again every 6 hours. The UI is available while downloads happen. For offline development set `CRAFT_AUTO_START_UPDATES=false`.

### Unraid

Install the provided [Unraid user template](docs/unraid.md), with a persistent
appdata mapping and configurable portal/app HTTPS origins. This is a manual user
template, not a Community Applications listing.

### Docker Compose

```bash
docker compose up --build -d
docker compose logs -f craft-portal    # first-start admin code
```

`compose.yaml` provides the local HTTP example. **For access from another device, set `CRAFT_PUBLIC_URL` to the exact URL you use**, such as `https://craft.example.nl`, and configure a reverse proxy that preserves the `Host` header. In production you MUST also configure a **different hostname** for app code with either `CRAFT_SINGLE_APP_URL=https://craft-apps.example.nl` or the optional multi-user wildcard `CRAFT_APPS_DOMAIN=apps.example.nl`. Both hostnames point to the same container:8080; app JavaScript never shares the portal's origin. Without a separate app origin, the portal and updater work but "Open" buttons are intentionally disabled. On Unraid map `/data` to `/mnt/user/appdata/craft-portal`, using a host directory writable by UID 10001 or override the Compose `user` with the desired Unraid UID/GID (typically `99:100`).

The live app data is in `data/` and **must not be committed to Git**. Existing data are retained on container rebuild/recreation.

### Configuration

| Variable | Default | Function |
|---|---|---|
| `CRAFT_DATA_DIR` | `/data` | Writable persistent directory |
| `CRAFT_PUBLIC_URL` | `http://localhost:8080` | Exact HTTPS portal origin in production |
| `CRAFT_APPS_DOMAIN` | unset | Enables safe multiple accounts with per-user/app hostnames |
| `CRAFT_SINGLE_APP_URL` | local `http://127.0.0.1:8080` when portal uses localhost | Separate app origin; shared multi-user is an explicit opt-in, otherwise one account |
| `CRAFT_SHARED_APP_MULTI_USER` | `false` | Allow multiple accounts on that app origin when each person uses a separate OS/browser profile; requires `CRAFT_SINGLE_APP_URL` and no `CRAFT_APPS_DOMAIN` |
| `GITHUB_TOKEN` | unset | Optional API-rate-limit token; do not commit secrets |
| `CRAFT_AUTO_START_UPDATES` | `true` | `false` for offline tests |

Portal settings (stored in SQLite; editable in Admin UI):

| Setting | Default |
|---|---|
| Interval | 6 hours |
| Auto-install latest stable versions | On |
| Auto-discover new official apps | On |
| Previously installed versions | 2 |
| Include prereleases | Off (locked off in the current release) |

Manual update button initiates a new discovery cycle. On failure, the currently installed version remains usable.

## App workspace and multi-user without wildcard TLS

Apps open inside the portal above a bottom dock. Switching keeps each open app
mounted; returning to the library or admin pages does not reload it. Up to four
apps can remain open at once. Close/restart explicitly after saving, or use
**Open separately** for app features that do not work embedded.

For several accounts without wildcard certificates, set one separate app HTTPS
origin plus `CRAFT_SHARED_APP_MULTI_USER=true` and leave `CRAFT_APPS_DOMAIN` empty.
Every person must use a separate OS/browser profile: portal accounts authorize
server access, while local documents/caches are shared by accounts within one
browser profile. This is the explicitly accepted alternative to per-user origins.
Use same-site hostnames for reliable embedded cookies. See the complete
[workspace and shared-host guide](docs/workspace.md) below.

## Reverse proxy, HTTPS and WebGPU

Production requires HTTPS to support WebGPU and browser clipboard features. Set `CRAFT_PUBLIC_URL` to the **exact public URL**, including the port if nondefault; the proxy MUST forward the original `Host` header. Ideally route all traffic only through the proxy and restrict direct access to port `8080`.

- Portal: `craft.example.nl` → same container port 8080.
- Single-user app host: `craft-apps.example.nl` → same container port 8080; set `CRAFT_SINGLE_APP_URL=https://craft-apps.example.nl` (a second ordinary DNS record and TLS certificate, no wildcard needed).
- Multi-user app hostnames: `*.apps.example.nl` → **same container port 8080**, with wildcard DNS and TLS. Set `CRAFT_APPS_DOMAIN=apps.example.nl` and `CRAFT_PUBLIC_URL=https://craft.example.nl`.
- WebAssembly code **never shares the portal admin's origin**: otherwise upstream app JavaScript could read the portal's same-origin API endpoints. The single-user host separates portal credentials while apps still share one app origin. For strict per-app privacy choose multi-user wildcard origins.
- User app data in OPFS/IndexedDB are keyed to browser origin. The unique user-and-app hostname is necessary to avoid leaking browser documents when users share the same computer/browser profile. This does *not* sync documents between devices or encrypt browser storage at rest.
- Existing browser data stay on the device if the user signs out; on a shared device, use separate browser profiles or clear site data as needed.
- WebAssembly apps are not automatically granted server folders or centralized document storage. Users must save/export projects according to each upstream app's capabilities.

On multi-user installations, launching an app creates a 45-second one-time ticket passed in the URL **fragment**, which never reaches the reverse proxy; the app-host bridge redeems it via a same-origin POST. Keep TLS, no third-party script injection and no excessive logging of API bodies.

## Runtime flow

1. First run creates SQLite and an administrator setup code. It never starts an anonymous session.
2. The updater reads the official catalog, verifies each app's `github.com/storytold/<slug>` link and asks GitHub for its stable release.
3. Only exact `slug-web-X.Y.Z.zip` release assets with `sha256:` metadata, trusted URLs and bounded sizes are accepted.
4. Downloads stay in `/data/staging`. After archive validation, files are extracted into a versioned directory, activated in one DB transaction and previous releases are pruned.
5. Browser app files are served **only after authorization**, with version-specific URLs. An application update does not rebuild the Docker image.
6. The admin can restore any retained version; this pauses further automatic updates for that particular app until re-enabled, preventing immediate reinstallation of a broken release. Rollback does not restore browser-side file format changes.

## Testing

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
node --check portal/static/app.js
node --check portal/static/bridge.js
docker build -t craft-portal:test .
```

Tests use synthetic ZIPs and a local in-memory HTTP client; they do **not** prove every real ArtCraft web build loads. For production approval also execute the checklist in `docs/KNOWN_LIMITATIONS.md` and browser smoke tests against actual official web release ZIPs.

## Language and library

The portal follows the first supported browser language: Dutch or English, with
English as fallback. Setup and every portal page use the same translations.
See [language behavior](docs/i18n.md) and [visual/console review](docs/UI_REVIEW.md).

## Development and acceptance

`bash .codex/setup.sh` creates an isolated `.venv` and runs non-browser checks.
`bash .codex/start.sh` starts the local development portal with updates paused.
Set `CRAFT_VENV_DIR` to reuse an external environment. For a nondefault port set
both `CRAFT_PORT` and the matching `CRAFT_PUBLIC_URL`.

Use Python 3.12. Keep a virtual environment outside source control. Install
`requirements-dev.txt` for API/updater/backup tests. For browser acceptance,
install `requirements-browser.txt` and follow [browser testing](docs/browser-testing.md).
CI runs unit tests, JavaScript checks, Chromium/Firefox and multi-architecture
container builds. Version tags trigger the same checks before GHCR publishing;
adding workflow configuration does not itself publish an image.

An explicit live check downloads every discovered official release into isolated
temporary storage, verifies publisher and SHA-256, and checks authenticated HTTP
assets (potentially several GB):

```sh
python scripts/verify_official_releases.py --run-live --report /tmp/craft-releases.json
```

That HTTP check does not prove browser rendering, WebGPU or service-worker
compatibility. Never relax digest or TLS validation to pass an upstream failure.
Production deployment, separate origin/TLS, Unraid permissions, tagged images and
checksum-verified backup/restore are documented in [deployment operations](docs/deployment/README.md).

## Licensing

Portal starter code is offered under the MIT license. This repository does **not** redistribute ArtCraft release binaries; users running the container fetch ArtCraft upstream assets under their respective licenses. Retain license notices packaged within each upstream web release.

The compact workspace dock uses official Craft app icons and card heroes, cached
locally from getartcraft.com with offline fallbacks. See [workspace setup and TLS
troubleshooting](docs/workspace.md) for app-host connection errors and artwork behavior.

SolidCraft is also supported through the explicitly selected
[`bherbruck/solidcraft`](https://github.com/bherbruck/solidcraft) release repository.
It installs as a self-hosted WASM app with the same launch, update, rollback and
personal-order controls. See [SolidCraft integration](docs/solidcraft.md).
