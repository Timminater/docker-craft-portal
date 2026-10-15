# Release gates and known limitations

This document records the tested scope and remaining upstream/platform checks
for stable Craft Portal releases. See
[acceptance evidence](ACCEPTANCE.md) and [implementation review](SECURITY_REVIEW.md).

## Verified locally

- Authentication, session expiry/revocation, CSRF, request bounds, hostname and
  origin validation, HTTPS `__Host-` cookies and responsive password verification.
- ZIP directory compatibility, traversal/link/collision rejection, required
  SHA-256, bounded downloads, interrupted/bad downloads preserving the active
  release, serialized rollback, retention and six-hour scheduler behavior.
- Chromium setup/login/logout/admin, authenticated synthetic WASM compilation,
  rollback, reconnect/restart, installer filtering, modal keyboard behavior,
  polling error recovery, and two accounts in one browser profile with distinct
  HTTPS app origins and storage.
- Hardened native AMD64 container, persistent SQLite volume/restart, nginx
  configuration syntax, and checksum-verified offline backup/restore.

Synthetic fixtures prove portal behavior. Additionally, the checksum-verified official
PhotoCraft v0.9.0 release renders its full editor embedded and standalone under
local HTTPS. Its missing optional font manifest gives a non-blocking 404. This
does not validate all apps or the operator's DNS/TLS deployment.

## Required before production release

- [ ] Actual official catalog and publisher pages discover every current app.
- [ ] Every latest stable official ZIP has the supported name, bounded size and
  SHA-256 digest. Missing digests fail closed; do not bypass validation.
- [ ] All real apps load HTML/JS/WASM and relative assets on authenticated version
  paths, including service workers, OPFS, COOP/COEP and WebGPU where required.
- [ ] Chromium and Firefox real-app workflows pass. Both synthetic browser workflows
  passed in strict hosted CI; genuine upstream browser acceptance remains open.
- [x] AMD64/ARM64 image builds passed in hosted release CI.
- [ ] Native ARM64 runtime is tested on actual ARM64 hardware.
- [x] Hosted CI passed, including strict Chromium/Firefox integration, followed
  by v0.1.0-rc.1 prerelease and public GHCR publication. See ACCEPTANCE.md.
- [ ] Real DNS/TLS and reverse proxy preserve Host and security headers, keep
  backend port private, and apply client rate limits. Test deployment certificate
  rotation and restore operations with the actual volume and operator identity.
- [ ] External review of release supply chain and upstream JavaScript trust;
  complete deployment-specific threat assessment before public exposure.

The current managed environment blocks `getartcraft.com` and `api.github.com`
with proxy HTTP 403. Browser distribution downloads are also blocked. Required
domains have been saved in the environment configuration draft; saving a draft
does not change the running network policy. See ACCEPTANCE.md for commands and
precise remaining work.

## Operational limitations

- One application worker; login/setup limits and CSRF key are process-local.
  Use edge rate limiting. Restart changes CSRF keys; reload portal pages afterward.
- HTTPS sessions now use `__Host-` cookies. Existing MVP HTTPS sessions need a
  fresh login. HTTP localhost development keeps the original cookie names.
- Logout/disable revoke server access, not previously downloaded browser data.
  Upstream service workers can explicitly cache app responses despite HTTP
  no-store. OPFS/IndexedDB remain on devices; separate browser profiles are
  recommended for shared devices.
- Single-user and explicit shared-host multi-user deployments share one app
  origin among apps. Shared-host mode requires separate OS/browser profiles;
  portal accounts in one profile do not isolate documents. Wildcard origins
  remain available for account/app storage isolation. Neither mode syncs files.
- Embedded compatibility is app/browser dependent. Use Open separately if
  iframe storage, external resources or app permissions fail. Same-site HTTPS
  hostnames support the retained cookie policy. Up to four app frames remain
  mounted; no automatic eviction of unsaved app state is performed.
- Keep active + configured previous releases. A tab on a version removed by
  retention can fail on a later lazy asset load; tabs are not tracked.
- Rollback changes app code and pauses its automatic updates, not document formats
  or browser storage. Export projects before upgrades where needed.
- Backup helper requires every portal/updater writer stopped. Snapshot checksums
  detect corruption, not tampering by an attacker who controls the manifest.
  No online snapshot guarantee, encryption/key management, or power-loss guarantee
  is claimed. Browser projects are outside server backups.
- Shutdown waits for updater network operations to finish/cancel; socket timeouts
  can delay exit. Compose allows 120 seconds. Abrupt termination and full disk
  recovery still require operational monitoring and available disk capacity.

## Deliberately outside scope

Central document synchronization, OIDC/SSO, recovery emails/password resets,
custom/unsigned publishers, prerelease installs and cloud storage automation.

Self-service password changes, owned session revocation and optional TOTP with
single-use recovery codes are supported. Browser storage estimates/persistence
depend on browser support and are not a document backup. See
[personal settings](personal-settings.md).
