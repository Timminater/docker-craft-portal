# Install on Unraid

The repository supplies a Docker **version 2 user template** at
[`unraid/docker-craft-portal.xml`](../unraid/docker-craft-portal.xml). This is a
manual installation option, not a Community Applications listing or submission.
It uses `ghcr.io/timminater/docker-craft-portal:latest` for normal Unraid updates.
The current image is the verified `v0.1.0-rc.6` candidate; use a version tag if you prefer a pinned installation. The image is publicly published for AMD64 and ARM64; its release workflow passed
unit, Chromium/Firefox and multiarch container checks. See the
[release](https://github.com/Timminater/docker-craft-portal/releases/tag/v0.1.0-rc.6)
and [package](https://github.com/Timminater/docker-craft-portal/pkgs/container/docker-craft-portal). Review
[acceptance evidence](ACCEPTANCE.md) and [known limitations](KNOWN_LIMITATIONS.md)
before public deployment. Installing a template does not verify production readiness.

## Install the user template

Download the raw XML from:

<https://raw.githubusercontent.com/Timminater/docker-craft-portal/main/unraid/docker-craft-portal.xml>

On the Unraid terminal, save it as a user template (review downloaded content
before applying):

```sh
mkdir -p /boot/config/plugins/dockerMan/templates-user
curl --fail --location --proto '=https' --tlsv1.2 \
  https://raw.githubusercontent.com/Timminater/docker-craft-portal/main/unraid/docker-craft-portal.xml \
  -o /boot/config/plugins/dockerMan/templates-user/my-docker-craft-portal.xml
```

Then open **Docker → Add Container** and select the installed
`docker-craft-portal` user template. Alternatively, if your Unraid version has
**Docker → Template Repositories**, add
`https://github.com/Timminater/docker-craft-portal`, save/reload templates and
select its template. If repository discovery does not find the XML, use the
explicit `templates-user` installation above.

## Prepare private persistent storage

Before clicking Apply, prepare the host directory on the Unraid terminal:

```sh
mkdir -p /mnt/user/appdata/craft-portal
chown 10001:10001 /mnt/user/appdata/craft-portal
chmod 700 /mnt/user/appdata/craft-portal
```

The image runs as UID/GID `10001:10001`. Keep the complete appdata directory
writable by that identity; SQLite, staging, releases and backups need it. For an
existing installation, stop the container and back up first; inspect ownership
before deliberately changing existing files. Do not run privileged or chmod 777.
Use storage supporting SQLite locking, not an SMB/NFS mount.

If you deliberately prefer Unraid's `99:100` identity, append `--user=99:100` to
**Extra Parameters** in Advanced View and prepare the directory with
`chown 99:100` and `chmod 700` instead. The image does not modify existing bind
mount ownership at startup. Never map the Docker socket into this container.

## Set DNS, HTTPS and exact origins

Replace **both** example hostnames before first use:

- `CRAFT_PUBLIC_URL=https://craft.your-domain.example`: portal/admin origin.
- `CRAFT_SINGLE_APP_URL=https://craft-apps.your-domain.example`: separate app
  hostname. It must not be the portal hostname, including when ports differ.

Set the template's **WebUI** field in Advanced View to the exact
`CRAFT_PUBLIC_URL` value. Its example `https://craft.example.com` is a placeholder,
not an automatic link to your Unraid IP. Opening `http://UNRAID-IP:8080` directly
will fail Host validation once a production portal URL is configured.

Create DNS and valid TLS certificates for both names and route both to the
mapped backend port (default `8080`). Preserve the original Host header and app
security headers. See the [nginx HTTPS example](deployment/nginx.conf). Permit
backend access only from your trusted reverse proxy using your firewall or
Docker network rules. The template's bridge port mapping can bind all host
interfaces: it must not be forwarded directly from your router or exposed to
untrusted LAN clients. Check port 8080 is free or change the host mapping and
proxy upstream together. Keep the container port at 8080.

For multiple accounts **without wildcard TLS**, keep the two ordinary HTTPS
origins and set `CRAFT_SHARED_APP_MULTI_USER=true`, leaving `CRAFT_APPS_DOMAIN`
empty. Every person must use their own OS/browser profile; portal accounts do not
separate local app documents inside one profile. Use hostnames under the same
parent site for embedded cookies. See [the workspace guide](workspace.md).

For stronger per-account/app origin isolation, keep that flag false, clear
`CRAFT_SINGLE_APP_URL` entirely, then set
`CRAFT_APPS_DOMAIN=apps.your-domain.example` without a scheme or port. Set up
wildcard DNS and TLS for `*.apps.your-domain.example`, routing all app hosts to
the same backend. The two app-origin configuration modes are mutually exclusive.
Per-user/app origins isolate browser storage; the single-user app host shares
one origin across apps. Browser OPFS/IndexedDB is not part of server backups.

## Start and maintain

Click Apply, open the configured HTTPS WebUI and find the one-time setup code in
private container logs. Create the administrator and allow the updater to install
verified official apps. The default scheduled check is every six hours. Keep
`CRAFT_AUTO_START_UPDATES=true` for normal use. No production credential is
required; the optional GitHub token only increases API limits. The masked field
is not a secret vault: Docker administrators and readers of saved Unraid
configuration can access it. Restrict access and never publish populated templates.

The template uses a read-only root filesystem, bounded `/tmp`, dropped Linux
capabilities, no-new-privileges, bounded logs and a 120-second shutdown timeout.
Keep these options. App versions and the database persist in appdata when the
container is recreated. Before changing images, create a consistent backup and
follow the [backup and recovery guide](deployment/README.md). Pinning the image
tag makes portal upgrades deliberate; app release updates happen independently
without rebuilding the portal container.
