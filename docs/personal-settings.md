# Personal portal settings

These features are available to every signed-in account. Interface text follows
the browser language: Dutch or English, with English as fallback.

## Account and sessions

Open **Account** from the navigation or your avatar. Changing your password
requires the current password and, when enabled, an authenticator or recovery
code. Passwords must contain 12–1024 characters. The current session and its
open apps remain authorized; other devices, their app sessions and launch
tickets are revoked. Previously downloaded documents remain in those browsers.

The session list shows a coarse browser/operating-system label, creation time,
expiry and the current session. Labels describe the submitted user-agent and
are informational, not proof of device identity. Old sessions have an unknown
browser label. Revoke an individual other session or all other sessions.

Optional two-step verification uses a standard authenticator (TOTP, SHA-1,
six digits, 30 seconds). Enter the displayed setup key manually in your
authenticator, then confirm its code. Enrollment expires after ten minutes
and belongs to the same portal session. The portal accepts a one-step clock
tolerance and rejects reuse of an accepted code. Wait for the next code if
you have just used one. Server and device clocks should be synchronized.

After confirmation, save the ten recovery codes in a safe place. They are
shown once, stored as hashes and each usable once instead of an authenticator
code. Enabling or disabling verification signs out other devices. There is no
email recovery or administrator bypass; retain your recovery codes. All
credential and code attempts share the existing rate limits.

The database contains the activated authenticator secret so the server can
verify codes. Protect `/data` and server backups as confidential. Offline restore
preserves activated factors and unused recovery hashes while invalidating all
sessions, launch tickets and unfinished enrollments.

## Browser storage

**Browser storage** measures approximate usage/quota and persistent-storage
status on the actual app origin, using an authenticated utility frame. It does
not open an editor or read, list, upload or remove document contents. Results
describe this browser profile and embedded browsing context, not other devices,
the portal origin or the server disk. Browser privacy settings can restrict
these APIs or partition data; unavailable results are reported without guessing.

With `CRAFT_SINGLE_APP_URL`, apps share an origin and are shown as one storage
group. With `CRAFT_APPS_DOMAIN`, every enabled installed app has its own
account-specific origin. In explicitly enabled shared-host multi-user mode,
portal accounts do not isolate documents: each person needs their own OS/browser
profile. Changing hostnames or browser profiles changes which data is visible.

**Request persistent storage** asks the browser to reduce automatic eviction.
The browser decides whether to grant the request, including restrictions on
embedded pages. Persistence is not synchronization or a backup and does not
prevent manual deletion. Quota/usage are estimates and do not represent exact
document sizes.

Export projects using each editor's own save/export function, keep a second
copy outside the browser, and test reopening it. Docker `/data` snapshots cover
portal accounts/settings and installed app code; they do not include OPFS,
IndexedDB or unsaved browser documents. The portal deliberately has no generic
clear-storage or document backup button.

## Personal dock

Choose **Customize dock** beside the library search to select visible apps.
This selection and the existing custom app order are stored with your account
and loaded on login/reload on each device. The app library remains complete.
An open app remains in the dock even if hidden in your selection; it disappears
after you close it. New apps are visible by default; **Show all** resets visibility.
Saving visibility does not overwrite app order, or vice versa.

## Versions and updates

**Updates** shows the running portal version, the last explicit portal release
check, and installed/latest app versions. Administrators can check the stable
portal release on GitHub. Checks are cached for fifteen minutes and only trust
the fixed `Timminater/craft-portal` repository, with the original
`Timminater/docker-craft-portal` repository as a 404-only migration fallback.
Network errors are displayed; the portal does not infer that it is up to date
when no successful check exists. Metadata is held in memory and clears on restart.

Portal code updates require updating/recreating the Docker container with
`ghcr.io/timminater/craft-portal:latest` (or a pinned version). No portal code is
installed into the running container. App releases continue to use the existing
automatic in-container updater, checksum validation, retention and rollback.

The page refreshes while open and shows catalog/release lookup, downloaded bytes
when known, extraction and activation. It does not invent a percentage for
unknown totals or extraction. Errors are summarized for ordinary users; detailed
administrative diagnostics remain under **Administration**.
