# Codex development instructions — docker-craft-portal

## Model / cost policy
The user's requested model is **GPT-6.1 Sol**, with **Low** reasoning effort (also described as light). Select that combination in Codex Cloud if supported; never claim the model has been selected if the Cloud UI did not confirm it. Keep tasks narrow so Low effort produces high-quality changes. For security-critical or architecturally risky work, ask for an explicit review rather than silently downgrading quality.

## Objective
Build a production-worthy, self-hosted, single-Docker ArtCraft WASM portal with first-run setup, secure authentication, versioned static hosting, a trusted GitHub release updater, automatic discovery, rollback and native download links. Important defaults: check every 6 hours, auto-install new versions, discover new official apps, retain the active release + two previous versions.

## Current implementation
Python FastAPI + SQLite + Argon2id + zero-build vanilla JS/CSS in `portal/`, `tests/` with fake release archives, multi-user origins optional via `CRAFT_APPS_DOMAIN`. This is a functional initial implementation, **not a verified production release**.

## Required tests before a PR
1. `python -m pip install -r requirements-dev.txt && python -m pytest -q`
2. `node --check portal/static/app.js && node --check portal/static/bridge.js`
3. `docker build -t craft-portal:test . && docker run ...` (if Docker available).
4. Under browser automation, test setup / login / logout / admin / app launch / assets.
5. Enable network on an isolated dev environment and test one real official release ZIP end to end. Do not use production credentials.

## Delegation/subagents
If subagents are available, use **non-overlapping** tasks: security+auth review, updater+filesystem review, portal UX/accessibility review, integration testing+Docker packaging. Main agent owns API contracts, merges, tests and final review. Low/light for implementation; escalate complexity only where necessary and when the user approves.

## Security invariants
- Do not expose raw WASM assets before session authorization. No public alias path.
- In default isolated multi-user mode, bind each app session to exact user public ID and app slug host.
- The owner explicitly authorized an alternative shared-host mode with `CRAFT_SHARED_APP_MULTI_USER=true`: every person uses their own OS/browser profile. In this mode, portal accounts do NOT isolate OPFS/IndexedDB; describe that boundary accurately. Keep this an explicit opt-in and preserve wildcard mode.
- The portal and app origin must always use distinct hostnames. Embedded apps must not read portal APIs/cookies, navigate the top frame, or receive tickets through postMessage/logs. Keep bridge message checks bound to exact origin, source frame and slug.
- Trust the official getartcraft catalog and `github.com/storytold/<slug>` for ArtCraft release assets. The user explicitly authorized one additional fixed source: `github.com/bherbruck/solidcraft`. Keep that exact repository allowlisted; do not broaden third-party publisher trust. SolidCraft offline service-worker registration is removed before activation to preserve server authorization.
- Fail closed on mismatched SHA-256, arbitrary redirects, symlinks, traversal and ZIP bombs.
- Never unpack over active files. Keep explicit rollback and preserve last known-good release.
- Never expose setup code, session cookies, CSRF keys, GitHub tokens or secrets to portal JavaScript.
- Auth credentials and `/_redeem` tickets are forbidden in logs and URLs. Tickets go in URL *fragments* and one-time POST bodies.
- Do not store persistent secrets in Git. Do not add external telemetry or analytics.

## Work order
1. Inspect `docs/KNOWN_LIMITATIONS.md`, reproduce high-priority gaps; fix security first.
2. End-to-end real web ZIP verification and browser compatibility for all official ArtCraft apps (some require COOP/COEP, WebGPU and Service Worker scopes).
3. Browser tests with Playwright including multi-user isolation, updater activation and rollback.
4. Production deployment/reverse proxy examples, backups, least privileges, audit and threat model.
5. Only then consider OIDC, sync storage or cloud automation.

Keep PRs focused and document any limitations honestly. Run CI on every change. The entire project and its functionality are self-hosted; the only required network traffic is release/update discovery and native installer redirects.
