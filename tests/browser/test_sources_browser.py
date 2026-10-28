"""Administrator edits a trusted repository from the browser."""
import os
import pytest
from test_portal_browser import browser, site, serve

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
