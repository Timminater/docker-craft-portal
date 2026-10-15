# Workspace and shared-host multi-user

The default Open action starts an app above the bottom dock inside the portal.
The dock lists enabled apps and indicates which are open. Selecting another open
app switches its existing iframe without reloading it. Library/admin navigation
keeps app frames mounted in a separate workspace container. Frames are created
only when opened, not for every dock icon. Up to four apps stay open; additional
apps require explicitly closing one. There is no automatic eviction of unsaved work.

Use Library to return to the portal, Close after saving, Restart to reload the
selected app, or Open separately for app/browser features that do not work in an
iframe. Close, restart, logout and page unload have save prompts when appropriate.
An expired/revoked portal session or changed account clears every app frame; it
cannot preserve unsaved app memory after authorization ends. Network interruption
alone does not automatically destroy frames. Hidden frames still consume memory
and may continue playback/background work; close unused apps on small devices.

## Two ordinary certificates; no wildcard required

Configure two different HTTPS hostnames pointing to the same container:

```sh
CRAFT_PUBLIC_URL=https://craft.example.com
CRAFT_SINGLE_APP_URL=https://craft-apps.example.com
CRAFT_SHARED_APP_MULTI_USER=true
CRAFT_APPS_DOMAIN=
```

The `CRAFT_SINGLE_APP_URL` name is retained for backward compatibility: it now
also supports explicitly enabled shared-host multi-user. Without the new flag,
one-account behavior is unchanged. Enabling the flag permits administrators to
create accounts. Existing accounts, app files and database settings remain in the
same persistent volume. Use normal TLS certificates for the two names (or one
certificate listing both); no wildcard DNS/certificate is required.

Every person must use their own OS account or browser profile. The portal keeps
passwords, roles, sessions, CSRF checks and server authorization per account.
However, accounts in one browser profile share the app origin's localStorage,
IndexedDB, OPFS and service-worker caches. A different portal account, URL path
or iframe is not a browser-storage boundary. Different apps also share this
origin. Logging out revokes server access and removes the portal's frames, not
previously saved browser data. Browser profiles remain the accepted local data
boundary; this mode is not appropriate if account-level browser isolation is
required. Browser documents are not in the server data-volume backup.

Changing from the previous wildcard origins to the shared app hostname does not
move browser documents. Export projects in each old app/origin before switching
and import them on the new origin where the upstream app supports it. Keep the
same data-volume mapping and retain old DNS/TLS until exports are complete.

## Reverse proxy and embedded compatibility

Use same-site hostnames (for example both under example.com). HTTPS and the
existing same-site HttpOnly cookie policy are retained. Unrelated domains and
browsers blocking embedded storage may not support the iframe flow; use Open
separately. Plain HTTP localhost/127.0.0.1 development origins are cross-site,
so standalone opening remains the reliable local fallback.

The proxy must preserve Host, CSP, COOP, COEP, CORP and Permissions-Policy headers.
Keep the portal's X-Frame-Options DENY. Do not add X-Frame-Options SAMEORIGIN/DENY
to app responses: the app's CSP frame-ancestors permits only the configured portal.
Do not alias app files directly from nginx or a CDN. The included
[nginx example](deployment/nginx.conf) routes both ordinary hostnames to the backend.

The portal has COOP same-origin and COEP require-corp. Embedded app documents use
COEP and appropriate resource policy with cross-origin-isolated delegation. The
workspace sandbox allows scripts, same-origin app storage, forms, downloads and
pointer lock; it does not allow navigation of the parent/top document. Clipboard
and fullscreen delegation are explicit. The browser's permissions and user-gesture
rules still apply. Apps requiring incompatible external assets, popup flows,
recording permissions or other browser capabilities can use the separate window.
Standalone noncritical apps retain their previous COEP behavior.

The bridge redeems a short-lived ticket and reports navigation/error to a trusted
portal origin. The parent validates exact sender origin, source iframe and slug.
No cookie, ticket or session value is passed in messages. A successful bridge does
not prove an upstream app rendered or that all app features work embedded.

## Preserve stronger wildcard isolation

To continue separate account/app origins, leave the shared flag false and keep
`CRAFT_APPS_DOMAIN` with wildcard DNS/TLS, clearing `CRAFT_SINGLE_APP_URL` as before.
The dock works with both modes. The backend continues matching exact public user
ID and slug for isolated app hosts. Configuration rejects enabling both modes.

## Verification

Deterministic browser tests use actual small WebAssembly modules and HTTPS on
separate same-site fixture hosts. They exercise retained frame state, dock
switching, library/admin navigation, save prompts, explicit separate opening,
server account authorization, cross-origin-isolated/SharedArrayBuffer access,
origin/source message validation, logout/session cleanup and console failures.
Shared-profile tests verify that localStorage/OPFS are deliberately shared within
one browser profile and isolated between separate browser contexts. Existing
wildcard account-origin and cookie rejection tests remain in the suite.

This is not evidence of every genuine ArtCraft app's iframe, WebGPU or service-
worker compatibility. Real official releases require separate acceptance checks;
the current cloud network blocks the live operator host and official catalog/API.
