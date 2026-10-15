# Implementation security review

Reviewed during the 2026-10-15 implementation pass by separate authentication,
updater and read-only integration reviewers. This is a source/regression review,
not external certification or proof that upstream app code is benign.

## Boundaries and controls

| Boundary | Enforced control | Evidence / remaining condition |
| --- | --- | --- |
| Browser to portal | Exact configured Host, origin + first-party header, per-session CSRF, 64 KiB actual streamed body limit | Security and origin regression tests; proxy must preserve Host and limit slow requests |
| Password to account | Argon2id; bounded credential fields; generic login failures; setup code invalidated atomically | Setup/login tests; first-start code exists only in private logs |
| Portal session to app | Different hostname; single-use 45-second launch ticket in fragment; HttpOnly scoped cookie | Browser authenticated WASM load; app session requires live same-user portal parent |
| Account/app to another account/app | Exact slug and user-public-ID hostname plus matching app-session scope | Two-account Chromium HTTPS test; server-side security tests |
| Release metadata to network | Exact HTTPS hosts and port 443; API token only for GitHub API; redirects remove authorization outside API | Redirect tests; proxy/TLS remain enabled; optional GitHub binding must be deployment-managed |
| Download to installed code | Expected publisher/name/URL, bounded size, required SHA-256, ZIP traversal/link/collision/ratio checks | Fake-download tests prove failed digest/interruption preserve active release; genuine upstream check blocked by egress policy |
| Staging to activation/rollback | Separate temporary extraction, atomic directory activation, SQLite pointer transaction; serialized update/rollback/prune | Retention and concurrency tests; manual rollback pauses automatic updates |
| App code to portal authority | Separate hostname, portal CSP, no permissive CORS, no direct volume aliases | API/app-origin tests; reverse proxy must retain headers and use TLS |
| Versioned service worker | Default version-directory scope; no Service-Worker-Allowed broadening | Source review only for genuine apps; upstream cache behavior still needs live browser tests |
| Container to host | UID 10001, read-only root, bounded tmpfs, capabilities dropped, no-new-privileges, no Docker socket | Native hardened-container health/persistence test; bind directory must have correct ownership |
| Backup to restored instance | Offline SQLite backup API; SHA-256 exact manifest; reject links; new target only; atomic rename; revoke sessions/tickets | WAL/corruption/symlink/non-overwrite regressions; operator must stop every writer and protect/encrypt snapshots |

## Residual deployment and supply-chain risks

* A trusted upstream release executes arbitrary third-party JavaScript/WASM on
  its app origin. Digest verification authenticates bytes, not behavior.
* HTTP no-store prevents ordinary HTTP caching of protected responses. It does
  not erase OPFS, IndexedDB, or an upstream service worker's explicit Cache API
  copies. Logout revokes **server** access; a hostile or offline app may still
  display previously obtained local data. Use separate browser profiles on
  shared devices and test each real app's offline behavior.
* Single-user mode shares one app origin among apps; choose wildcard multi-user
  mode for per-account/per-app browser storage separation. Do not change origins
  without planning browser document export/migration.
* Login/setup limits are process-local. Use one application worker and edge
  rate limiting. Do not trust arbitrary forwarded client headers. Account-wide
  limits can temporarily deny a targeted account; operators need a recovery path.
* Updater requests have socket timeouts, but a slow upstream can delay graceful
  shutdown. Killing during download leaves active versions intact; disk fsync
  of all installed files and full host power-loss resilience are not established.
* The volume is the trusted persistence boundary: an operator who can modify it
  can replace application code, users or database pointers. Backups contain
  password hashes; a checksum manifest is not a signature against that operator.
* Existing-user recovery, MFA/OIDC, email reset and centralized document sync are
  outside this release's scope. Never expose an unreviewed first-run installation.
* CI is configured for both CPU architectures and browser engines. Configuring
  jobs does not prove a hosted run or release publication succeeded. Pin deployed
  image digests and complete the acceptance gates before tagging a release.
