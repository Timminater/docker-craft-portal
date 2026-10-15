"""Real browser smoke tests against a local server and a tiny genuine WASM module.

Run explicitly; ordinary pytest runs do not require installed browser packages.
The fixture uses synthetic versioned releases, not upstream ArtCraft applications.
"""
import os
import shutil
import socket
import threading
import time
from contextlib import contextmanager

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("CRAFT_BROWSER_TESTS") != "1", reason="set CRAFT_BROWSER_TESTS=1 to run browsers"
)


@contextmanager
def serve(app, port, **options):
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                         log_level="error", access_log=False, lifespan="off", timeout_graceful_shutdown=2, **options))
    worker = threading.Thread(target=server.run, daemon=True)
    worker.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not worker.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("browser test server failed to start")
        time.sleep(0.02)
    try:
        yield
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        assert not worker.is_alive()


@pytest.fixture
def site(tmp_path):
    from portal.config import Config
    from portal.server import create_app

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://localhost:{port}"
    apps = f"http://127.0.0.1:{port}"
    cfg = Config(data_dir=tmp_path, public_url=origin, single_app_url=apps,
                 apps_domain="", auto_start_updates=False)
    app = create_app(cfg, start_updater=False)
    db = app.state.db
    db.run("INSERT INTO apps(slug,name,description,active_version,status) "
           "VALUES('photocraft','PhotoCraft','Synthetic WASM fixture','v2.0.0','ready')")
    for number in (1, 2):
        relative = f"apps/photocraft/versions/v{number}.0.0"
        base = tmp_path / relative
        base.mkdir(parents=True)
        # Empty but valid WebAssembly module; instantiateStreaming checks MIME + actual compilation.
        (base / "fixture.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
        (base / "index.html").write_text(
            f'<h1>Fixture v{number}</h1><p id="result">Loading</p><script src="fixture.js"></script>'
        )
        (base / "fixture.js").write_text(
            "WebAssembly.instantiateStreaming(fetch('fixture.wasm')).then(()=>{"
            "document.querySelector('#result').textContent='WASM ready';"
            "localStorage.setItem('fixture-origin',location.origin);"
            "}).catch(e=>document.querySelector('#result').textContent=e.message);"
        )
        db.run("INSERT INTO versions(slug,version,rel_path,installed_at) VALUES(?,?,?,?)",
               ("photocraft", f"v{number}.0.0", relative, number))
    for name in ('photocraft-windows-x64.msi', 'photocraft-macos-universal.dmg', 'photocraft-linux-x86_64.AppImage'):
        db.run("INSERT INTO release_assets(slug,name,url) VALUES(?,?,?)",
               ('photocraft', name, 'https://github.com/storytold/photocraft/releases/download/v2.0.0/' + name))
    yield app, origin, apps, port
    db.close()


@pytest.fixture(params=["chromium", "firefox"])
def browser(request):
    if os.getenv("CRAFT_REQUIRE_BROWSERS") == "1":
        import playwright.sync_api as playwright
    else:
        playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as engine:
        name = request.param
        options = {"headless": True}
        if name == "chromium":
            options["args"] = ["--host-resolver-rules=MAP *.example.test 127.0.0.1", "--no-proxy-server"]
        else:
            options["firefox_user_prefs"] = {"network.dns.localDomains": "portal.example.test,photocraft--000000000001.apps.example.test,photocraft--000000000002.apps.example.test"}
        # An existing system Chromium avoids downloading a second browser in restricted environments.
        executable = os.getenv("CRAFT_CHROMIUM_EXECUTABLE") or shutil.which("chromium")
        if name == "chromium" and executable:
            options["executable_path"] = executable
        try:
            instance = getattr(engine, name).launch(**options)
        except playwright.Error as error:
            if "Executable doesn't exist" in str(error) and os.getenv("CRAFT_REQUIRE_BROWSERS") != "1":
                pytest.skip(f"{name} is not installed; run playwright install {name}")
            raise
        yield instance
        instance.close()


def login(page, origin):
    page.goto(origin)
    page.locator('#username').fill('admin')
    page.locator('#password').fill('browser-test strong password!')
    page.locator('#auth-form button').click()
    page.get_by_role('heading', name='Mijn applicaties', exact=True).wait_for()


def launch(page):
    with page.expect_popup() as opened:
        page.locator('[data-open="photocraft"]').click()
    app_page = opened.value
    app_page.get_by_text('WASM ready', exact=True).wait_for()
    return app_page


def test_browser_setup_wasm_csrf_rollback_restart_logout(browser, site):
    app, origin, apps, port = site
    context = browser.new_context()
    page = context.new_page()
    with serve(app, port):
        assert context.request.get(apps + '/a/photocraft/v/v2.0.0/fixture.wasm').status == 401
        page.goto(origin)
        page.locator('#code').fill(app.state.auth.setup_code)
        page.locator('#username').fill('admin')
        page.locator('#password').fill('browser-test strong password!')
        page.locator('#auth-form button').click()
        page.get_by_role('heading', name='Mijn applicaties', exact=True).wait_for()
        cookies = context.cookies(origin)
        assert cookies and all(cookie['httpOnly'] for cookie in cookies)
        assert page.evaluate('document.cookie') == ''
        assert context.request.post(origin + '/api/logout', headers={'X-Craft-Client': 'portal-v1'}).status == 403
        app_page = launch(page)
        assert app_page.url.startswith(apps + '/a/photocraft/v/v2.0.0/')
        assert '#' not in app_page.url
        assert app_page.evaluate('localStorage.getItem("fixture-origin")') == apps
        assert page.evaluate('localStorage.getItem("fixture-origin")') is None
        response = context.request.get(apps + '/a/photocraft/v/v2.0.0/fixture.wasm')
        assert response.status == 200
        assert response.headers['content-type'].startswith('application/wasm')
        page.locator('[data-download="photocraft"]').click()
        page.get_by_role('dialog', name='Native download').wait_for()
        assert page.locator('#installer-results a').count() == 3
        for platform, suffix in [('windows', '.msi'), ('macos', '.dmg'), ('linux', '.AppImage')]:
            page.locator('#installer-platform').select_option(platform)
            links = page.locator('#installer-results a')
            assert links.count() == 1
            assert links.first.get_attribute('href').endswith(suffix)
        page.locator('#installer-platform').select_option('all')
        assert page.locator('#installer-results a').count() == 3
        # The select is a normal keyboard focus stop inside the dialog trap.
        page.locator('#close-modal').focus()
        page.keyboard.press('Tab')
        page.keyboard.press('Tab')
        assert page.locator('#installer-platform').evaluate('(el)=>el===document.activeElement')
        page.keyboard.press('Escape')
        assert page.locator('[data-download="photocraft"]').evaluate('(el)=>el===document.activeElement')
        page.get_by_role('button', name='Beheer', exact=True).click()
        page.get_by_role('heading', name='Systeembeheer').wait_for()
        page.locator('#interval').select_option('12')
        page.locator('#interval').focus()
        await_refresh = 'async () => { await refreshAdmin(); }'
        page.evaluate(await_refresh)
        assert page.locator('#interval').input_value() == '12'
        assert page.locator('#interval').evaluate('(el)=>el===document.activeElement')
        page.route('**/api/admin/status', lambda route: route.fulfill(status=503, json={'detail':'Temporary fixture failure'}))
        page.evaluate(await_refresh)
        page.locator('#retry-admin').wait_for()
        assert page.locator('#interval').input_value() == '12'
        page.unroute('**/api/admin/status')
        page.locator('#retry-admin').click()
        page.locator('#retry-admin').wait_for(state='detached')
        assert page.locator('#interval').input_value() == '12'

        page.locator('[data-versions="photocraft"]').click()
        dialog = page.get_by_role('dialog')
        dialog.wait_for()
        page.keyboard.press('Shift+Tab')
        assert dialog.locator('[data-rollback]').evaluate('(el)=>el===document.activeElement')
        page.keyboard.press('Tab')
        assert page.locator('#close-modal').evaluate('(el)=>el===document.activeElement')
        page.keyboard.press('Escape')
        assert page.locator('[data-versions="photocraft"]').evaluate('(el)=>el===document.activeElement')
        page.locator('[data-versions="photocraft"]').click()
        page.once('dialog', lambda dialog: dialog.accept())
        page.locator('[data-rollback]').click()
        page.get_by_role('dialog').wait_for(state='detached')
        assert app.state.db.one("SELECT active_version,auto_update FROM apps WHERE slug='photocraft'") == {'active_version':'v1.0.0', 'auto_update':0}
        page.get_by_role('button', name='Applicaties', exact=True).click()
        rolled_back = launch(page)
        rolled_back.get_by_role('heading', name='Fixture v1').wait_for()
        context.set_offline(True)
        from playwright.sync_api import Error
        with pytest.raises(Error):
            rolled_back.reload()
        context.set_offline(False)
        rolled_back.reload()
        rolled_back.get_by_text('WASM ready', exact=True).wait_for()
    # Recreate application/auth/database objects against the same persisted data.
    from portal.server import create_app
    app.state.db.close()
    app = create_app(app.state.cfg, start_updater=False)
    with serve(app, port):
        page.reload()
        page.get_by_role('heading', name='Mijn applicaties', exact=True).wait_for()
        restored = launch(page)
        restored.get_by_role('heading', name='Fixture v1').wait_for()
        page.get_by_role('button', name='Uitloggen', exact=False).click()
        page.locator('#auth-form').wait_for()
        assert context.request.get(apps + '/a/photocraft/v/v1.0.0/fixture.wasm').status == 401
        login(page, origin)
    app.state.db.close()
    context.close()


def test_multiuser_browser_origin_isolation(browser, tmp_path):
    """Two accounts get separate actual browser origins and cannot reuse app cookies."""
    import subprocess
    from portal.config import Config
    from portal.server import create_app

    port = 443
    cert, key = tmp_path/'cert.pem', tmp_path/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                    '-subj','/CN=portal.example.test','-keyout',str(key),'-out',str(cert)],
                   check=True, capture_output=True)
    origin = 'https://portal.example.test'
    app = create_app(Config(data_dir=tmp_path/'data', public_url=origin,
                           apps_domain='apps.example.test', auto_start_updates=False), False)
    for number, username in enumerate(('admin', 'another'), 1):
        app.state.auth.create_user(username, 'browser-test strong password!', 'admin' if username=='admin' else 'user')
        # Stable synthetic public IDs let Firefox map these exact hosts to loopback.
        app.state.db.run('UPDATE users SET public_id=? WHERE username=?', (f'{number:012x}', username))
    db = app.state.db
    db.run("INSERT INTO apps(slug,name,active_version,status) VALUES('photocraft','PhotoCraft','v1.0.0','ready')")
    relative = 'apps/photocraft/versions/v1.0.0'
    base = app.state.cfg.data_dir / relative
    base.mkdir(parents=True)
    (base/'index.html').write_text('<h1>Isolated application</h1>')
    db.run('INSERT INTO versions(slug,version,rel_path,installed_at) VALUES(?,?,?,?)',
           ('photocraft','v1.0.0',relative,1))
    contexts = []
    try:
        with serve(app, port, ssl_certfile=str(cert), ssl_keyfile=str(key)):
            launched = []
            context = browser.new_context(ignore_https_errors=True)
            contexts.append(context)
            for username in ('admin','another'):
                # Switch only the portal identity, keeping app cookies and browser storage.
                context.clear_cookies(domain='portal.example.test')
                page = context.new_page()
                page.goto(origin)
                page.locator('#username').fill(username)
                page.locator('#password').fill('browser-test strong password!')
                page.locator('#auth-form button').click()
                page.get_by_role('heading',name='Mijn applicaties',exact=True).wait_for()
                with page.expect_popup() as opened:
                    page.locator('[data-open="photocraft"]').click()
                app_page = opened.value
                app_page.get_by_role('heading',name='Isolated application').wait_for()
                launched.append(app_page)
            first_origin = launched[0].evaluate('location.origin')
            second_origin = launched[1].evaluate('location.origin')
            assert first_origin != second_origin
            assert all(value != origin for value in (first_origin,second_origin))
            launched[0].evaluate('localStorage.setItem("private-document","first-user-only")')
            assert launched[1].evaluate('localStorage.getItem("private-document")') is None
            supports_opfs = launched[0].evaluate("typeof navigator.storage.getDirectory === 'function'")
            if browser.browser_type.name == 'chromium':
                assert supports_opfs, "Chromium must exercise OPFS isolation"
            if supports_opfs:
                launched[0].evaluate("""async () => {
                    const directory = await navigator.storage.getDirectory();
                    const file = await directory.getFileHandle('account-private-marker', {create:true});
                    const writer = await file.createWritable();
                    await writer.write('first-user-only'); await writer.close();
                }""")
                assert launched[1].evaluate("""async () => {
                    const directory = await navigator.storage.getDirectory();
                    try { await directory.getFileHandle('account-private-marker'); return 'visible'; }
                    catch(error) { return error.name; }
                }""") == 'NotFoundError'
                assert launched[0].evaluate("""async () => {
                    const directory = await navigator.storage.getDirectory();
                    const file = await directory.getFileHandle('account-private-marker');
                    return (await file.getFile()).text();
                }""") == 'first-user-only'

            unauthenticated = browser.new_context(ignore_https_errors=True)
            try:
                forbidden = unauthenticated.new_page()
                assert forbidden.goto(launched[0].url).status == 401
            finally:
                unauthenticated.close()
            # Even copying an authenticated app cookie to the other user's hostname fails closed.
            stolen = [cookie for cookie in contexts[0].cookies(first_origin) if cookie['httpOnly']]
            for cookie in stolen:
                cookie['domain'] = launched[1].url.split('/')[2].split(':')[0]
            isolated = browser.new_context(ignore_https_errors=True)
            try:
                isolated.add_cookies(stolen)
                forbidden = isolated.new_page()
                assert forbidden.goto(launched[1].url).status == 401
            finally:
                isolated.close()
    finally:
        for context in contexts:
            context.close()
        db.close()
