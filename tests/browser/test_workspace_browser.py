"""Real cross-origin embedded workspace acceptance, with synthetic WASM apps."""
import os
import socket
import subprocess

import pytest

from test_portal_browser import browser, serve

pytestmark = pytest.mark.skipif(os.getenv('CRAFT_BROWSER_TESTS') != '1', reason='set CRAFT_BROWSER_TESTS=1')
PASSWORD = 'browser-test strong password!'


@pytest.fixture
def workspace_site(tmp_path):
    from portal.config import Config
    from portal.server import create_app
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    cert, key = tmp_path/'cert.pem', tmp_path/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                    '-subj','/CN=portal.example.test','-keyout',str(key),'-out',str(cert)],
                   check=True, capture_output=True)
    origin, apps = f'https://portal.example.test:{port}', f'https://apps.example.test:{port}'
    app = create_app(Config(data_dir=tmp_path/'data', public_url=origin, apps_domain='',
                           single_app_url=apps, shared_app_multi_user=True, auto_start_updates=False), False)
    app.state.auth.create_user('admin', PASSWORD, 'admin')
    for slug in ('photocraft', 'vectorcraft'):
        relative = f'apps/{slug}/versions/v1.0.0'
        base = app.state.cfg.data_dir/relative
        base.mkdir(parents=True)
        (base/'worker.js').write_text("onmessage = () => postMessage({isolated:crossOriginIsolated,bytes:new SharedArrayBuffer(16).byteLength});")
        (base/'fixture.wasm').write_bytes(b'\x00asm\x01\x00\x00\x00')
        (base/'index.html').write_text(f'<h1>{slug}</h1><input id="document" aria-label="Document"><p id="result">Loading</p><script src="fixture.js"></script>')
        (base/'fixture.js').write_text("window.sessionMarker=crypto.randomUUID();WebAssembly.instantiateStreaming(fetch('fixture.wasm')).then(()=>document.querySelector('#result').textContent='WASM ready');")
        app.state.db.run('INSERT INTO apps(slug,name,active_version,status) VALUES(?,?,?,?)', (slug,slug.title(),'v1.0.0','ready'))
        app.state.db.run('INSERT INTO versions(slug,version,rel_path,installed_at) VALUES(?,?,?,?)', (slug,'v1.0.0',relative,1))
    with serve(app, port, ssl_certfile=str(cert), ssl_keyfile=str(key)):
        yield app, origin, apps
    app.state.db.close()


def sign_in(page, origin, username='admin'):
    page.goto(origin)
    page.locator('#username').fill(username)
    page.locator('#password').fill(PASSWORD)
    page.locator('#auth-form button').click()
    page.locator('#app [data-open="photocraft"]').wait_for()


def frame_for(page, slug):
    # Match versioned URL, never the transient ticket-bearing bridge URL.
    from playwright.sync_api import expect
    locator = page.locator(f'iframe[title="{slug.title()}"]')
    expect(locator).to_have_count(1)
    frame = locator.content_frame
    frame.get_by_text('WASM ready', exact=True).wait_for()
    return frame


@pytest.mark.parametrize('locale', ['en-US', 'nl-NL'])
def test_workspace_preserves_app_state_navigation_and_accessibility(browser, workspace_site, locale):
    app, origin, apps = workspace_site
    context = browser.new_context(locale=locale, ignore_https_errors=True)
    page = context.new_page()
    problems, requested = [], []
    page.on('pageerror', lambda error: problems.append(str(error)))
    page.on('console', lambda message: problems.append(message.text) if message.type == 'error' else None)
    page.on('requestfailed', lambda request: problems.append(request.url + ': ' + str(request.failure)))
    page.on('response', lambda response: problems.append(f'{response.status} {response.url}') if response.status >= 400 else None)
    page.on('request', lambda request: requested.append(request.url))
    sign_in(page, origin)
    assert not page.locator('iframe').count(), 'Dock icons must not eagerly load applications'
    page.locator('#app [data-open="photocraft"]').click()
    photo = frame_for(page, 'photocraft')
    assert len(context.pages) == 1
    assert page.evaluate('crossOriginIsolated')
    assert photo.locator('body').evaluate('()=>crossOriginIsolated && typeof SharedArrayBuffer === \"function\"')
    assert photo.locator('body').evaluate("""()=>new Promise((resolve,reject)=>{
        const worker=new Worker('worker.js');worker.onmessage=event=>{worker.terminate();resolve(event.data)};
        worker.onerror=event=>reject(new Error(event.message || 'Worker failed'));worker.postMessage('check');
    })""") == {'isolated': True, 'bytes': 16}
    photo.locator('#document').fill('unsaved photo')
    marker = photo.locator('body').evaluate('()=>window.sessionMarker')
    photo.locator('#document').focus()
    page.evaluate('reconcileWorkspace()')
    assert page.evaluate('document.activeElement.tagName') == 'IFRAME'
    assert photo.locator('#document').evaluate('(el)=>el===document.activeElement')
    assert not any('/a/vectorcraft/' in url for url in requested)
    page.locator('.workspace-dock [data-open="vectorcraft"]').click()
    frame_for(page, 'vectorcraft')
    page.locator('.workspace-dock [data-open="photocraft"]').click()
    assert photo.locator('#document').input_value() == 'unsaved photo'
    assert photo.locator('body').evaluate('()=>window.sessionMarker') == marker
    page.locator('.workspace-toolbar [data-workspace="home"]').click()
    page.locator('[data-page="admin"]').click()
    page.locator('#settings-form').wait_for()
    assert page.locator('iframe').count() == 2
    page.locator('.workspace-dock [data-open="photocraft"]').click()
    assert photo.locator('#document').input_value() == 'unsaved photo'
    # App origin cannot inspect its parent document or use parent portal APIs.
    assert photo.locator('body').evaluate("()=>{try{return parent.document.body.innerHTML}catch(e){return e.name}}") == 'SecurityError'
    # Forged messages from the portal itself are not trusted as a frame response.
    before_status = page.locator('.workspace-status').inner_text()
    page.evaluate("""origin => {
        const frame = document.querySelector('iframe[title=\"Photocraft\"]');
        window.dispatchEvent(new MessageEvent('message', {origin, source:window, data:{type:'craft-bridge-error',slug:'photocraft'}}));
        window.dispatchEvent(new MessageEvent('message', {origin:'https://untrusted.example', source:frame.contentWindow, data:{type:'craft-bridge-error',slug:'photocraft'}}));
    }""", apps)
    assert page.locator('.workspace-status').inner_text() == before_status
    assert photo.locator('#document').input_value() == 'unsaved photo'
    for width, height in [(1440, 1000), (390, 844)]:
        page.set_viewport_size({'width':width, 'height':height})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('.workspace-dock [data-open="photocraft"]').is_visible()
    # Polling keeps the portal network active; wait for the app's actual ready state.
    assert photo.locator('body').evaluate('()=>document.readyState') == 'complete'
    assert page.locator('iframe[title="Vectorcraft"]').content_frame.locator('body').evaluate('()=>document.readyState') == 'complete'
    assert not problems, problems
    # Explicit separate-tab fallback remains available.
    with page.expect_popup() as popup:
        page.locator('[data-workspace="separate"]').click()
    popup.value.get_by_text('WASM ready', exact=True).wait_for()
    popup.value.close()
    page.locator('.workspace-toolbar [data-workspace="home"]').click()
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#logout').click()
    page.locator('#auth-form').wait_for()
    assert not page.locator('iframe').count()
    context.close()


def test_shared_origin_accounts_and_separate_browser_profiles(browser, workspace_site):
    app, origin, apps = workspace_site
    context = browser.new_context(ignore_https_errors=True, locale='en-US')
    page = context.new_page()
    sign_in(page, origin)
    page.locator('[data-page="users"]').click()
    page.locator('#new-username').fill('another')
    page.locator('#new-password').fill(PASSWORD)
    page.locator('#new-user button').click()
    page.get_by_role('cell', name='another', exact=True).wait_for()
    page.locator('.workspace-dock [data-open="photocraft"]').click()
    photo = frame_for(page, 'photocraft')
    photo.locator('body').evaluate("()=>localStorage.setItem('shared-profile-document','first-account')")
    photo.locator('body').evaluate("""async () => {
        const root = await navigator.storage.getDirectory();
        const file = await root.getFileHandle('shared-profile-document', {create:true});
        const writer = await file.createWritable(); await writer.write('first-account'); await writer.close();
    }""")
    page.locator('.workspace-toolbar [data-workspace="home"]').click()
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#logout').click()
    page.locator('#auth-form').wait_for()
    sign_in(page, origin, 'another')
    page.locator('#app [data-open="photocraft"]').click()
    second = frame_for(page, 'photocraft')
    assert context.request.get(apps.replace('apps.example.test', '127.0.0.1') + '/api/bootstrap', headers={'Host':apps.split('//')[1]}).status == 404
    assert second.locator('body').evaluate("()=>localStorage.getItem('shared-profile-document')") == 'first-account'
    assert second.locator('body').evaluate("""async () => {
        const root = await navigator.storage.getDirectory();
        return (await (await root.getFileHandle('shared-profile-document')).getFile()).text();
    }""") == 'first-account'
    isolated = browser.new_context(ignore_https_errors=True, locale='en-US')
    other = isolated.new_page()
    sign_in(other, origin, 'another')
    other.locator('#app [data-open="photocraft"]').click()
    separate = frame_for(other, 'photocraft')
    assert separate.locator('body').evaluate("()=>localStorage.getItem('shared-profile-document')") is None
    assert separate.locator('body').evaluate("""async () => {
        const root = await navigator.storage.getDirectory();
        try { await root.getFileHandle('shared-profile-document'); return 'visible'; }
        catch(error) { return error.name; }
    }""") == 'NotFoundError'
    # A cancelled close preserves the exact frame and its unsaved DOM; accepted close removes it.
    second.locator('#document').fill('unsaved')
    page.once('dialog', lambda dialog: dialog.dismiss())
    page.locator('[data-workspace="close"]').click()
    assert second.locator('#document').input_value() == 'unsaved'
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('[data-workspace="close"]').click()
    assert not page.locator('iframe').count()
    # Bootstrap liveness also runs when the underlying page is users/events.
    # This account is not admin, so use its permitted apps page and exercise the same checker.
    page.locator('.workspace-dock [data-open="photocraft"]').click()
    frame_for(page, 'photocraft')
    app.state.db.run("DELETE FROM sessions WHERE kind='portal'")
    page.evaluate('async()=>await checkWorkspaceSession()')
    page.locator('#auth-form').wait_for()
    assert not page.locator('iframe').count()
    sign_in(page, origin, 'another')
    page.locator('#app [data-open="photocraft"]').click()
    frame_for(page, 'photocraft')
    app.state.db.run("DELETE FROM sessions WHERE kind='portal'")
    page.evaluate("async()=>{try{await api('/api/apps')}catch{}}")
    page.locator('#auth-form').wait_for()
    assert not page.locator('iframe').count()
    isolated.close()
    context.close()
