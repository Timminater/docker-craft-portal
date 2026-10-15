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
| Isolated account/app to another account/app | Exact slug and user-public-ID hostname plus matching app-session scope | Wildcard-mode Chromium HTTPS and server tests remain enforced |
| Explicit shared apphost mode | Multiple accounts share one app origin, with per-slug server authorization and live parent-session checks | Owner accepted separate OS/browser profiles; accounts within one browser profile deliberately share OPFS/IndexedDB/localStorage |
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
* Single-user mode and explicit shared-host multi-user share one app origin among apps; choose wildcard multi-user
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
* Existing-user email recovery, OIDC, email reset and centralized document sync are
  outside this release's scope. Never expose an unreviewed first-run installation.
* CI is configured for both CPU architectures and browser engines. Configuring
  jobs does not prove a hosted run or release publication succeeded. Pin deployed
  image digests and complete the acceptance gates before tagging a release.

## Embedded workspace update

The owner explicitly authorized `CRAFT_SHARED_APP_MULTI_USER=true` under the
separate-OS/browser-profile assumption. This changes the browser-data boundary,
not server account authorization. The opt-in cannot be combined with wildcard
mode and requires a distinct app host. It must never be presented as per-account
OPFS isolation within one profile.

The portal enables COOP/COEP and allows framing only configured app origins.
App documents allow ancestors only at the configured portal. The sandbox allows
app execution/storage but excludes top navigation; bridge messages carry status
only and are matched by exact origin, source frame and slug. App workers inherit
the isolation policy needed for SharedArrayBuffer. A browser test creates a real
worker and verifies that shared memory works, rather than relying on headers alone.
Portal JavaScript cannot inspect app iframe contents across origins; iframe
loading success does not establish compatibility with arbitrary upstream apps.

Frames remain mounted across app/navigation changes, with a four-frame limit and
explicit save confirmations. They are destroyed on logout/session revocation,
identity change or app disablement. Periodic session checks preserve focus and
unsaved forms when identity stays the same. Server revocation cannot erase browser
documents, service-worker caches or state in an independently opened app tab.
Same-site HTTPS app hosts are recommended for the retained cookie policy; other
setups use the separate-window fallback instead of weakening cookie settings.

## Official artwork cache review

Presentation image routes require an authenticated portal session and known app;
app hosts cannot use them. The fetcher has a separate opener with no release/API
credentials, exact HTTPS official-host redirect/final-origin checks, bounded
redirects, a five-second socket timeout and a 2 MiB read bound. WebP envelope
checks reject HTML/error responses. Cache writes are atomic and failed fetches
are negatively cached. Bundled icons have pinned upstream provenance and MIT
attribution. Artwork networking is optional; unavailable artwork returns a local
200 fallback without loosening the portal's self-only image CSP. A separate
read-only review found no concrete blockers. TLS/SNI deployment failures occur
before these HTTP routes and cannot be remediated by their authentication policy.

## Explicit SolidCraft publisher

The user authorized bherbruck/solidcraft specifically. An exact source registry
keeps this separate from the official catalog; neither arbitrary GitHub owners
nor other repositories of this owner gain trust. Metadata and original archive
digests remain verified, with the same staged activation and safe ZIP rules.
The SolidCraft HTML adaptation recognizes one standalone offline registration
script; unknown registration code aborts staging. Authenticated service-worker
routes are blocked, while normal worker requests retain their existing controls.
Native release links resolve to the actual configured publisher. Artwork comes
from pinned, licensed upstream source files and stays portal-authenticated.
Independent read-only review found no concrete blockers. Shared-origin browser
storage retains the previously documented profile boundary for all hosted apps.

## Account settings and storage diagnostics (2026-10-15)

An independent focused read-only review examined the new account and diagnostic
paths. Password changes verify the current hash and live session again inside
the write transaction; sign-in also rechecks the password/factor after Argon2
verification. Accepted TOTP counters and recovery hashes are consumed in that
same transaction. Enrollment is password-verified, expires after ten minutes,
and is bound to the initiating portal session. Recovery codes have 80 random
bits each, are stored as hashes and share credential-attempt limits.

Session display IDs are unrelated to bearer tokens/digests. Session queries and
revocation are restricted to the signed-in user, including child app sessions
and launch tickets. Credential/MFA mutations revoke other devices while retaining
the current authorized workspace. MFA secrets are confidential database contents;
no external QR service, email delivery or telemetry is used.

Browser storage diagnostics use the existing app-ticket and parent-session
authorization boundary. The utility reports aggregate estimates and persistence
status only to the configured portal parent. The portal validates the exact
origin, frame, slug and random request ID; leaving the page or changing session
removes diagnostic frames. Shared-host measurements are grouped by origin.
Portal release checks accept stable calendar tags and exact links from the two
fixed migration repositories; they do not execute downloads or replace code.

Review found and resolved stale MFA form state and a delayed old-session response
that could visually sign out a new login. Tests cover credential/factor races,
old-schema upgrades, session ownership/revocation and storage message forgery.
This focused implementation review does not claim an external penetration test
or validation of the operator's live DNS/TLS deployment.
