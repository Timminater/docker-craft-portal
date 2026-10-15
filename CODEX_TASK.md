# Codex Cloud task: productionize Docker Craft Portal

Model requested by project owner: **GPT-6.1 Sol, Low reasoning effort**. Select it in the Codex Cloud model picker if available. Preserve code quality through small, testable sub-tasks and focused reviews, rather than increasing model cost indiscriminately.

The current repository is a functional initial implementation. **Do not replace it with an architecture document or starter template.** Finish a deployable, reviewed application.

## Priorities (execute in order)

1. Read `AGENTS.md`, `README.md`, `docs/KNOWN_LIMITATIONS.md`; run tests. Inspect and fix any security bugs before feature work.
2. In a network-enabled ephemeral environment, run a full first-start discovery against `https://getartcraft.com/apps`, download the genuine official WebAssembly ZIPs for all currently available apps and verify they launch via authenticated versioned paths. Correct URL, MIME, headers, service-worker scope and relative assets per app. If the release API digest field is missing, fail closed and report it; never turn off integrity checks casually.
3. Add Playwright smoke tests with a browser, including UI login, app selection and actual WASM load, offline/restart recovery, rollback, cookie/CSRF handling and two account origins. Test both Chromium and Firefox if reasonable.
4. Package and verify Docker (multi-architecture AMD64 and ARM64), runtime nonroot permissions, Unraid bind mounts, GHCR GitHub Actions CI and tagged releases. Use build cache and minimal Python runtime.
5. Improve UX and accessibility (keyboard navigation, focus traps for dialogs, download filtering by platform, setup onboarding, update progress and error recovery), while keeping a lightweight portal.
6. Conduct threat review: release supply chain, HTTP redirects, untrusted ZIP contents and service workers, CSP, per-origin OPFS, host validation, reverse proxy, rate limiting, token expiration, file permission and backups.
7. Add configuration/reference documentation and evidence in PR: commands executed, actual results, remaining risks.

## Acceptance criteria

- Fresh Docker container provides login/setup and automatically installs official WASM apps without rebuilding the image.
- Every 6 hours the updater checks the official catalog; new apps and new stable releases appear automatically.
- An interrupted download or bad digest does not break the currently served app. Retention is active + two previous releases, with safe rollback.
- Unauthenticated requests cannot fetch protected app files. **All deployments**, including single-user, must isolate app origin from admin portal origin. Default isolated multi-user mode additionally gives distinct origin per account and app. The owner later authorized explicit shared-host multi-user for separate OS/browser profiles; that opt-in must not claim account-level browser storage isolation.
- Admin can manage settings, users (when multiuser is configured), pause updates and inspect history.
- Native installers are links to official GitHub release assets, not proxied/scraped executables.
- Responsive UX and accessible controls, documentation and reproducible tests.

## Subagent split (if Codex Cloud makes subagents available)

- **Security:** auth, CSRF, session scope, hostname trust, ZIP supply chain. Do not modify UI files.
- **Update engine:** publisher discovery, metadata, downloads, checksum, unpack, filesystem retention. Do not change auth endpoints.
- **Frontend/UX:** navigation, mobile, dialogs, installer selection, accessibility. Do not change DB schema.
- **Integration/testing:** Docker, CI, Playwright smoke tests, reverse proxy guidance. Avoid production logic except test-driven fixes.

Integrate by a main agent reviewing all outputs, running all tests and reporting unfinished items. Do not overclaim production readiness until real official apps are tested.
