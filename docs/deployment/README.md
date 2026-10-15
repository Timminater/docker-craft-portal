# Deployment and release operations

Use HTTPS in production and keep port 8080 private. `compose.yaml` binds only
to loopback, uses a persistent named volume, runs as UID/GID 10001, drops Linux
capabilities and makes the image filesystem read-only. Only `/data` and the
bounded temporary filesystem are writable. The initial setup code appears in
private container logs; restrict access to Docker and its logs.

For a single-user deployment set these nonsecret variables before Compose:

```sh
export CRAFT_PUBLIC_URL=https://craft.example.com
export CRAFT_SINGLE_APP_URL=https://craft-apps.example.com
docker compose up --build -d
```

Both DNS records point to your reverse proxy. Install valid certificates and
adapt `nginx.conf`, included inside nginx's `http` context. Test `nginx -t` before
reloading. Never alias `/data` or app assets directly from nginx: the portal must
authorize every request. Preserve Host and application security headers. Do not
enable a shared proxy cache. The example limits login attempts by client IP;
keep the proxy directly internet-facing or configure nginx's trusted real-IP
sources explicitly when another load balancer precedes it.

For multiuser, unset `CRAFT_SINGLE_APP_URL`, set
`CRAFT_APPS_DOMAIN=apps.example.com`, create wildcard DNS and a certificate for
`*.apps.example.com`, and replace the app server name in nginx with that wildcard.
All app hosts reach the same backend. Each user/app receives its own origin.
Single-user mode isolates apps from the administrator but shares one app origin
between apps. App OPFS/IndexedDB remains on client devices and is not included in
server backups. Changing an app hostname changes its browser storage origin.

## Multiple accounts without wildcard TLS

Keep the two ordinary HTTPS origins above, leave `CRAFT_APPS_DOMAIN` empty and
set `CRAFT_SHARED_APP_MULTI_USER=true`. This explicitly accepts separate OS/browser
profiles as the local-document boundary. Accounts in one profile share app storage.
For embedded cookies, use same-site hostnames. See [workspace configuration](../workspace.md)
for the dock, fallback, proxy headers and origin-migration steps.

## Unraid bind mounts

Replace `craft-data:/data` with `/mnt/user/appdata/craft-portal:/data`. Create the
host folder first and grant it to the container identity:

```sh
mkdir -p /mnt/user/appdata/craft-portal
chown 10001:10001 /mnt/user/appdata/craft-portal
chmod 700 /mnt/user/appdata/craft-portal
```

Alternatively set `user: "99:100"` and own the directory with that UID/GID.
Do not run privileged or use chmod 777. The complete directory must be writable
for SQLite WAL, staging, release installation and retention. Keep the database on
local reliable storage with SQLite file locking, rather than a network share.

## Backups and recovery

Stop the portal and its updater before making a consistent snapshot of database
and installed release files. The helper uses SQLite's backup API (including
committed WAL pages), records SHA-256 checksums for every file, and rejects links
and special files. It is an **offline** operation: the helper does not stop a
running service or lock out another writer. An immutable checksum manifest detects
accidental corruption, not malicious replacement by someone who controls backups.

For a host bind mount, run from the repository with Python 3.12; no application
dependencies are required by this helper:

```sh
docker compose stop craft-portal
python -m portal.backup backup --data-dir /srv/craft-data --output /srv/backups/craft-snapshot
python -m portal.backup restore --snapshot /srv/backups/craft-snapshot --data-dir /srv/craft-restored
chown -R 10001:10001 /srv/craft-restored
```

The restore target must not exist. Restore checks the full manifest and SQLite
integrity before atomically installing the new directory. Existing live data is
never overwritten. Sessions and launch tickets are revoked during restore; users
must log in again. Point the Compose bind mount at the restored directory, start
the same image version with `CRAFT_AUTO_START_UPDATES=false`, verify health, log
in, and launch an installed app before re-enabling updates. For named volumes,
mount the stopped source volume and a separate backup destination in a one-off
container and invoke the same module; restore into a new volume/directory and
preserve UID 10001 ownership. Never mount the Docker socket in the portal.

Keep snapshots encrypted with permissions limited to the operator: they contain
password hashes, settings and audit records. The helper creates directories 0700
and files 0600; a host/root restore must be chowned to the runtime identity.
Regression tests exercise WAL snapshot/restore, retained assets, session
revocation, corruption, symlinks and non-overwrite behavior. Perform an operational
restore drill on your deployment before depending on backups. Browser-side
OPFS/IndexedDB projects are **not** in the server backup. Release rollback restores
app code, not browser projects or upstream document migrations.

## Images and CI

CI tests Python, JavaScript and Chromium/Firefox browser smoke flows, builds
linux/amd64 and linux/arm64 using QEMU and
Buildx, and boots a hardened native image. ARM64 is emulated build validation;
verify a deployment on real ARM64 hardware before claiming native runtime
coverage. Version tags beginning with `v` run the same complete CI gate before GHCR publishing with
version and commit tags, SBOM and provenance. After the package publish succeeds,
the workflow creates a GitHub Release containing its immutable image digest.
Tags with a prerelease suffix (such as `v0.1.0-rc.1`) are marked as prereleases
and are not marked latest. Release notes live under `docs/releases/<tag>.md`. No workflow was executed or image
published by adding this configuration. Review real-app/browser acceptance
results before intentionally pushing a release tag. Pin deployed images by digest
for reproducibility. Runtime app updates do not require rebuilding the image.

Optional `GITHUB_TOKEN` can increase API limits. Inject it with your deployment
secret manager; never store its value in Git or container build arguments. Docker
administrators can inspect runtime environment values, so limit daemon access.
