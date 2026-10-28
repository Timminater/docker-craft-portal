"""Administrator removes an open app and can restore its configuration."""
import os
import pytest
from test_portal_browser import browser
from test_workspace_browser import workspace_site, sign_in, frame_for, PASSWORD

pytestmark=pytest.mark.skipif(os.getenv('CRAFT_BROWSER_TESTS') != '1',reason='browser tests disabled')

@pytest.mark.parametrize('locale',['en-US','nl-NL'])
def test_remove_open_app_and_restore_without_deleting_browser_data(browser,workspace_site,locale,monkeypatch):
    from playwright.sync_api import expect
    app,origin,apps=workspace_site
    app.state.auth.create_user('otheruser',PASSWORD,'user')
    monkeypatch.setattr(app.state.updater,'trigger',lambda: False)
    context=browser.new_context(ignore_https_errors=True,locale=locale)
    other_context=browser.new_context(ignore_https_errors=True,locale=locale)
    other=other_context.new_page()
    sign_in(other,origin,'otheruser')
    other.locator('#configure-dock').click()
    other.locator('[data-dock-slug="photocraft"]').uncheck()
    other.locator('#save-dock').click()
    expect(other.get_by_role('dialog')).to_have_count(0)
    other.locator('#app [data-open="photocraft"]').click()
    frame_for(other,'photocraft')
    other.locator('.workspace-toolbar [data-workspace="home"]').click()
    other.locator('.nav [data-page="account"]').click()
    other.locator('.workspace-dock [data-open="photocraft"]').click()
    page=context.new_page();errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    sign_in(page,origin)
    page.locator('#app [data-open="photocraft"]').click()
    photo=frame_for(page,'photocraft')
    photo.locator('body').evaluate("()=>localStorage.setItem('saved-document','keep me')")
    page.locator('.workspace-toolbar [data-workspace="home"]').click()
    page.locator('.nav [data-page="admin"]').click()
    page.once('dialog',lambda dialog: dialog.accept())
    with page.expect_response(lambda r:r.url.endswith('/api/admin/apps/photocraft') and r.request.method=='DELETE') as response:
        page.locator('[data-remove-app="photocraft"]').click()
    assert response.value.status==200
    expect(page.locator('iframe[title="Photocraft"]')).to_have_count(0)
    expect(page.locator('.workspace-dock [data-open="photocraft"]')).to_have_count(0)
    expect(page.locator('[data-restore-app="photocraft"]')).to_be_visible()
    # Other accounts can have a different underlying page while the app is
    # open; periodic reconciliation must close it and refresh dock preferences.
    expect(other.locator('iframe[title="Photocraft"]')).to_have_count(0,timeout=25000)
    other.locator('.nav [data-page="apps"]').click()
    other.locator('#configure-dock').click()
    other.locator('#save-dock').click()
    expect(other.get_by_role('dialog')).to_have_count(0)
    # Browser storage belongs to the app origin and is not in the server volume.
    proof=context.new_page();proof.goto(apps)
    assert proof.evaluate("localStorage.getItem('saved-document')")=='keep me'
    proof.close()
    with page.expect_response(lambda r:r.url.endswith('/api/admin/apps/photocraft/restore') and r.request.method=='POST') as response:
        page.locator('[data-restore-app="photocraft"]').click()
    assert response.value.status==200
    expect(page.locator('[data-restore-app="photocraft"]')).to_have_count(0)
    page.locator('.nav [data-page="apps"]').click()
    expect(page.locator('#app [data-open="photocraft"]')).to_be_disabled()
    assert not errors
    other_context.close()
    context.close()
