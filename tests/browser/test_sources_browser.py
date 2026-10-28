"""Administrator edits a trusted repository from the browser."""
import os
import pytest
from test_portal_browser import browser, site, serve
from test_workspace_browser import workspace_site, sign_in

pytestmark = pytest.mark.skipif(os.getenv('CRAFT_BROWSER_TESTS') != '1', reason='browser tests disabled')

@pytest.mark.parametrize('locale', ['en-US','nl-NL'])
def test_admin_can_review_and_change_source(browser, site, locale):
    from playwright.sync_api import expect
    app, origin, _, port = site
    app.state.auth.create_user('admin','browser-test strong password!','admin')
    context=browser.new_context(locale=locale, viewport={'width':390,'height':844})
    page=context.new_page()
    errors=[]
    page.on('pageerror',lambda error: errors.append(str(error)))
    with serve(app,port):
        page.goto(origin)
        page.locator('#username').fill('admin')
        page.locator('#password').fill('browser-test strong password!')
        page.locator('#auth-form button').click()
        page.locator('[data-page="admin"]').first.click()
        form=page.locator('[data-source-slug="photocraft"]')
        expect(form).to_be_visible()
        assert form.locator('[name=owner]').input_value()=='storytold'
        form.locator('[name=owner]').fill('example')
        form.locator('[name=repository]').fill('new-repo')
        page.once('dialog',lambda dialog: dialog.accept())
        with page.expect_response(lambda r: r.url.endswith('/api/admin/sources/photocraft') and r.request.method=='PUT') as response:
            form.locator('button').click()
        assert response.value.status==200
        assert app.state.db.one("SELECT owner,repository FROM app_sources WHERE slug='photocraft'")=={'owner':'example','repository':'new-repo'}
        page.reload()
        page.locator('[data-page="admin"]').first.click()
        expect(form.locator('[name=owner]')).to_have_value('example')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
    context.close()

@pytest.mark.parametrize('locale', ['en-US','nl-NL'])
def test_admin_adds_custom_app_in_the_browser(browser, workspace_site, locale, monkeypatch):
    from playwright.sync_api import expect
    app, origin, _=workspace_site
    monkeypatch.setattr(app.state.updater,'trigger',lambda: False)
    context=browser.new_context(locale=locale,ignore_https_errors=True,viewport={'width':390,'height':844})
    page=context.new_page()
    errors=[]
    page.on('pageerror',lambda error: errors.append(str(error)))
    page.goto(origin)
    page.locator('#username').fill('admin')
    page.locator('#password').fill('browser-test strong password!')
    page.locator('#auth-form button').click()
    page.locator('[data-page="admin"]').first.click()
    form=page.locator('#add-custom-app')
    form.locator('[name=name]').fill('Dream Craft')
    form.locator('[name=slug]').fill('dreamcraft')
    form.locator('[name=owner]').fill('example-org')
    form.locator('[name=repository]').fill('dream-project')
    page.once('dialog',lambda dialog: dialog.accept())
    with page.expect_response(lambda r:r.url.endswith('/api/admin/apps') and r.request.method=='POST') as response:
        form.locator('button').click()
    assert response.value.status==200
    expect(page.locator('[data-source-slug="dreamcraft"]')).to_be_visible()
    assert app.state.db.one("SELECT owner,repository FROM app_sources WHERE slug='dreamcraft'")=={'owner':'example-org','repository':'dream-project'}
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    # Install an authenticated synthetic release, then let the normal
    # library polling discover it and open the actual embedded frame.
    import hashlib, json
    from tests.test_updater import zip_data
    from tests.test_solidcraft import Opener
    bundle=zip_data('dreamcraft','v1.2.3')
    metadata={'tag_name':'v1.2.3','assets':[{'name':'dreamcraft-web-1.2.3.zip','browser_download_url':'https://github.com/example-org/dream-project/releases/download/v1.2.3/dreamcraft-web-1.2.3.zip','size':len(bundle),'digest':'sha256:'+hashlib.sha256(bundle).hexdigest()}]}
    monkeypatch.setattr(app.state.updater,'request',lambda *args,**kwargs: json.dumps(metadata).encode())
    app.state.updater.opener=Opener(bundle)
    assert app.state.updater.sync_app('dreamcraft')=='updated'
    page.locator('[data-page="apps"]').first.click()
    card=page.locator('.app-card').filter(has_text='Dream Craft')
    expect(card.locator('[data-open="dreamcraft"]')).to_be_enabled(timeout=20000)
    card.locator('[data-open="dreamcraft"]').click()
    expect(page.locator('iframe[title="Dream Craft"]')).to_have_count(1)
    expect(page.locator('iframe[title="Dream Craft"]').content_frame.locator('script[src="app.js"]')).to_have_count(1)
    assert not errors
    context.close()
