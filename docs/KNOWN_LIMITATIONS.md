# Known limitations / production gate

This is an initial runnable implementation, not a fully field-tested release. Real downstream ArtCraft web builds and networked Docker deployment have **not** been verified from this environment.

## Must verify or fix before public exposure

- [ ] Actual GitHub `releases/latest` JSON for all 13 apps returns SHA-256 digest and an expected `*-web-<version>.zip` asset. Test against upstream, not only synthetic ZIPs.
- [ ] Official catalog `/apps` exposes all app links and publisher repo confirmation on every app detail page.
- [ ] Actual app ZIP layout, favicon/fonts, service workers, optional COOP/COEP and WebGPU loads in Chromium/Firefox (especially FilmCraft, EffectCraft, LightCraft).
- [ ] Browser automation covers an authenticated app launch end-to-end on real files and failed/in-progress downloads.
- [ ] Full multiuser wildcard DNS and TLS demonstration; cross-account asset and OPFS isolation with the same browser profile, including logout/revocation.
- [ ] Verify both the public portal hostname and a separate public app hostname/wildcard (they MUST NOT be the same browser origin); reverse proxy configuration with trusted preserved Host, restricted direct 8080, HTTPS, timeouts and appropriate `/api/login` rate limiting.
- [ ] GitHub Actions cross-arch images published via tags (current workflow runs tests and builds a container but intentionally does not publish unverified images).
- [ ] External security review for untrusted upstream JavaScript running on separately scoped origins; supply-chain integrity is not a proof upstream is harmless.
- [ ] Production backup and restore for SQLite (including WAL files safely) and app storage, plus disaster-recovery drill.
- [ ] Login rate limiting is currently process-local, not distributed or persistent across restarts; add edge rate limits before exposing publicly.

## Deliberately not yet implemented

- Central document storage and sync across webapps and devices (upstream WASM apps commonly use browser localStorage/OPFS/IndexedDB or export to downloads).
- OIDC/SSO, recovery emails, TOTP, self-service password resets, invitations.
- Uploading local packages, custom publishers, unsigned web ZIP support, prerelease installation.
- Actively probing browser tabs to defer file cleanup beyond the retention policy; an open page on an older version may fail to load lazily fetched assets after enough updates.
- Disabling user accounts keeps local browser OPFS data on that user's device. Use separate browser profiles if devices are shared.
- Per-app encrypted backing storage and protection against browser extensions/compromised clients.

## Security notes

The app validates GitHub digest metadata and the official publisher identity, but it still executes third-party JS/WASM in end-user browsers. The updater can change app code every six hours. This is explicitly opted into by the owner; install only trusted official apps and maintain the admin audit log.

Set up an HTTPS reverse proxy, keep admin login and Docker logs private, and restrict public network exposure until the above checks pass. The current single-user mode intentionally refuses additional accounts. Its app code is served from a separate origin from the admin portal; individual apps on the single-user app hostname still share browser storage with other app code on that hostname. To isolate each app use CRAFT_APPS_DOMAIN with per-user/app hostnames.
