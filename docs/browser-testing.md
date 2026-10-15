# Browser acceptance tests

Install the separate optional browser dependencies and browser engines:

```sh
python -m pip install -r requirements-browser.txt
python -m playwright install --with-deps chromium firefox
CRAFT_BROWSER_TESTS=1 CRAFT_REQUIRE_BROWSERS=1 python -m pytest tests/browser -q
```

Ordinary `python -m pytest -q` explicitly skips browser tests. With
`CRAFT_REQUIRE_BROWSERS=1`, missing browser executables fail instead of silently
skipping. `CRAFT_CHROMIUM_EXECUTABLE` selects a system Chromium; an installed
`chromium` binary is otherwise detected automatically. Set
`PLAYWRIGHT_BROWSERS_PATH` consistently during browser install and execution if
using a shared browser cache.

The deterministic suite uses temporary SQLite databases and synthetic versioned
releases. The single-user test compiles an actual minimal WebAssembly module via
`WebAssembly.instantiateStreaming`, exercising relative assets and the WASM MIME
type through the authenticated app origin. It covers UI setup, login, logout,
admin navigation, HttpOnly cookies, missing-CSRF rejection, separate portal/app
browser storage, modal keyboard navigation and focus restoration, installer platform filtering,
admin refresh/retry preserving unsaved settings, version rollback,
failed reload while offline, reconnection, and stopping/restarting the HTTP
listener and recreating application/auth/database objects with persisted releases, database and browser sessions. It does not claim that an
app works offline: authentication intentionally requires server access. Application
recreation is not an OS process crash/restart test.

The multi-user test creates two accounts and launches both through the
UI in one shared browser context/profile on distinct HTTPS account/app origins,
clearing only the portal cookie between logins while keeping both app sessions live. It checks localStorage separation and
OPFS marker-file isolation when the browser supports the OPFS API,
unauthenticated access to the other account origin, and rejection even when an
app cookie is deliberately copied to the wrong user's hostname. Chromium's test
DNS mapping directs `*.example.test` to loopback; Firefox maps the fixture's explicit hostnames through its `network.dns.localDomains` preference. A temporary self-signed TLS
certificate is accepted only in the test browser contexts. The test binds port
443 because production multi-user hostnames do not include arbitrary ports;
Linux CI runners may need:

```sh
sudo sysctl -w net.ipv4.ip_unprivileged_port_start=0
```

Do not run the TLS test alongside another listener on local port 443. Both Chromium and Firefox are configured for both workflows. No test records setup codes, tickets, cookies or CSRF
values in artifacts or enables server access logs.

These fixtures validate the portal integration, not compatibility with real
ArtCraft releases. Real release discovery, verified official release downloads,
service workers, OPFS, WebGPU and each upstream application's workflows require
separate end-to-end validation with network access. Tests never substitute a
synthetic release for that evidence.
