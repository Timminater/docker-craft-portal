"""Real localized account security, dock preferences and update overview flows."""
import json
import os
import re
import time

import pytest

from portal.auth import totp_code
from portal.updates import REPOSITORIES
from portal.version import VERSION
from test_portal_browser import browser
from test_workspace_browser import workspace_site, sign_in, frame_for, PASSWORD

pytestmark = pytest.mark.skipif(os.getenv('CRAFT_BROWSER_TESTS') != '1', reason='set CRAFT_BROWSER_TESTS=1')
NEW_PASSWORD = 'a changed browser-test password!'


def new_page(browser, locale):
    context = browser.new_context(ignore_https_errors=True, locale=locale,
                                  viewport={'width': 1440, 'height': 1000})
    page = context.new_page()
    problems = []
    page.on('pageerror', lambda error: problems.append(str(error)))
    page.on('console', lambda message: problems.append(message.text) if message.type == 'error' else None)
    page.on('requestfailed', lambda request: problems.append(f'{request.url}: {request.failure}'))
    page.on('response', lambda response: problems.append(f'{response.status} {response.url}') if response.status >= 400 else None)
    return context, page, problems


def account_for(app, context, origin):
    # Browser host resolver rules do not apply to APIRequestContext. Use an
    # in-process authenticated read for revocation assertions, without issuing
    # intentional 401 requests from the page console or exposing cookie values.
    from fastapi.testclient import TestClient
    cookies = '; '.join(f"{cookie['name']}={cookie['value']}" for cookie in context.cookies(origin))
    return TestClient(app, base_url=origin).get('/api/account', headers={'Cookie': cookies})


def assert_localized_and_capture(page, area, locale, browser_name):
    assert not re.search(r'\b(?:account|storage|updates|dock)\.[A-Za-z]', page.locator('body').inner_text())
    page.screenshot(path=f'/tmp/craft-{area}-{locale}-{browser_name}.png', full_page=True)
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=f'/tmp/craft-{area}-mobile-{locale}-{browser_name}.png', full_page=True)
    page.set_viewport_size({'width': 1440, 'height': 1000})


def navigate(page, destination):
    page.locator(f'.nav [data-page="{destination}"]').click()


def sign_out(page):
    page.locator('#logout').click()
    page.locator('#auth-form').wait_for()


def login_with_factor(page, origin, password, factor):
    page.goto(origin)
    page.locator('#username').fill('admin')
    page.locator('#password').fill(password)
    page.locator('#login-otp').fill(factor)
    page.locator('#auth-form button').click()
    page.locator('#app [data-open="photocraft"]').wait_for()


@pytest.mark.parametrize('locale', ['en-US', 'nl-NL'])
def test_password_and_session_management_are_usable(browser, workspace_site, locale):
    from playwright.sync_api import expect
    app, origin, _ = workspace_site
    context, page, problems = new_page(browser, locale)
    second = browser.new_context(ignore_https_errors=True, locale=locale)
    sign_in(page, origin)
    other = second.new_page()
    sign_in(other, origin)
    navigate(page, 'account')
    expect(page.locator('#account-sessions li')).to_have_count(2)
    assert page.locator('html').get_attribute('lang') == locale[:2]
    assert page.locator('#current-password').get_attribute('autocomplete') == 'current-password'
    assert_localized_and_capture(page, 'account', locale, browser.browser_type.name)
    # Revoke a particular other device without losing the current browser.
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('[data-revoke-session]').click()
    expect(page.locator('#account-sessions li')).to_have_count(1)
    assert account_for(app, second, origin).status_code == 401
    # A fresh second session is invalidated by changing the password as well.
    sign_in(other, origin)
    navigate(page, 'apps')
    navigate(page, 'account')
    expect(page.locator('#account-sessions li')).to_have_count(2)
    page.locator('#current-password').fill(PASSWORD)
    page.locator('#new-password-account').fill(NEW_PASSWORD)
    page.locator('#repeat-password').fill(NEW_PASSWORD)
    with page.expect_response(lambda response: response.url.endswith('/api/account/password')) as changed:
        page.locator('#password-form button').click()
    assert changed.value.status == 200
    expect(page.locator('#account-sessions li')).to_have_count(1)
    assert page.locator('#current-password').input_value() == ''
    assert account_for(app, second, origin).status_code == 401
    assert account_for(app, context, origin).status_code == 200
    sign_out(page)
    login_with_factor(page, origin, NEW_PASSWORD, '')
    assert not problems, problems
    second.close(); context.close()


@pytest.mark.parametrize('locale', ['en-US', 'nl-NL'])
def test_manual_mfa_enrollment_recovery_and_authenticator_login(browser, workspace_site, locale):
    from playwright.sync_api import expect
    app, origin, _ = workspace_site
    context, page, problems = new_page(browser, locale)
    sign_in(page, origin)
    navigate(page, 'account')
    page.locator('#manage-mfa').click()
    page.locator('#mfa-password').fill(PASSWORD)
    page.locator('#mfa-start-form button').click()
    secret = page.locator('.mfa-secret')
    expect(secret).to_be_visible()
    manual_key = secret.inner_text()
    assert len(manual_key) == 32 and manual_key.isalnum()
    assert not page.locator('#mfa-password').count(), 'Password form disappears after enrollment starts'
    page.locator('#mfa-confirm-otp').fill(totp_code(manual_key, int(time.time() // 30)))
    page.locator('#mfa-confirm-form button').click()
    recovery = page.locator('textarea.recovery-codes')
    expect(recovery).to_be_visible()
    codes = recovery.input_value().splitlines()
    assert len(codes) == len(set(codes)) == 10
    assert recovery.get_attribute('readonly') is not None
    page.locator('#finish-mfa').click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    assert account_for(app, context, origin).json()['mfa_enabled']
    assert not page.locator('.mfa-secret,textarea.recovery-codes').count(), 'One-time enrollment secrets leave the DOM'
    sign_out(page)
    login_with_factor(page, origin, PASSWORD, codes[0])
    assert account_for(app, context, origin).json()['recovery_codes_remaining'] == 9
    sign_out(page)
    # Confirmation consumes its TOTP counter. The next permitted counter tests
    # authenticator login immediately without waiting thirty seconds.
    last = app.state.db.one("SELECT mfa_last_counter FROM users WHERE username='admin'")['mfa_last_counter']
    factor = totp_code(manual_key, max(int(time.time() // 30), last + 1))
    login_with_factor(page, origin, PASSWORD, factor)
    navigate(page, 'account')
    page.locator('#manage-mfa').click()
    page.locator('#mfa-password').fill(PASSWORD)
    page.locator('#mfa-disable-otp').fill(codes[1])
    page.locator('#mfa-start-form button').click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    account = account_for(app, context, origin).json()
    assert account['mfa_enabled'] is False and account['recovery_codes_remaining'] == 0
    assert not problems, problems
    context.close()


@pytest.mark.parametrize('locale', ['en-US', 'nl-NL'])
def test_dock_visibility_preserves_live_frames_and_updates_are_explicit(browser, workspace_site, locale, monkeypatch):
    from playwright.sync_api import expect
    app, origin, _ = workspace_site
    app.state.auth.create_user('another', PASSWORD, 'user')
    calls = []
    def release_metadata(url, **kwargs):
        calls.append(url)
        tag = 'v2099.10.15.0'
        return json.dumps({'tag_name': tag, 'draft': False, 'prerelease': False,
                           'html_url': f'https://github.com/{REPOSITORIES[0]}/releases/tag/{tag}'}).encode()
    monkeypatch.setattr(app.state.updater, 'request', release_metadata)
    context, page, problems = new_page(browser, locale)
    sign_in(page, origin)
    page.locator('#app [data-open="photocraft"]').click()
    photo = frame_for(page, 'photocraft')
    photo.locator('#document').fill('preserve while hiding dock icon')
    marker = photo.locator('body').evaluate('()=>window.sessionMarker')
    page.locator('[data-workspace="home"]').first.click()
    page.locator('#configure-dock').click()
    page.locator('[data-dock-slug="photocraft"]').uncheck()
    with page.expect_response(lambda response: response.url.endswith('/api/preferences') and response.request.method == 'PUT') as saved:
        page.locator('#save-dock').click()
    assert saved.value.status == 200
    expect(page.get_by_role('dialog')).to_have_count(0)
    # Running hidden apps remain switchable until explicitly closed.
    page.locator('.workspace-dock [data-open="photocraft"]').click()
    assert photo.locator('#document').input_value() == 'preserve while hiding dock icon'
    assert photo.locator('body').evaluate('()=>window.sessionMarker') == marker
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('[data-workspace="close"]').click()
    expect(page.locator('.workspace-dock [data-open="photocraft"]')).to_have_count(0)
    expect(page.locator('#app [data-open="photocraft"]')).to_be_visible()
    page.reload()
    page.locator('#configure-dock').wait_for()
    expect(page.locator('.workspace-dock [data-open="photocraft"]')).to_have_count(0)
    navigate(page, 'updates')
    expect(page.locator('#portal-updates-content')).to_contain_text(VERSION)
    assert not calls, 'Opening the overview must not trigger an external release check'
    with page.expect_response(lambda response: response.url.endswith('/api/admin/portal/check')) as checked:
        page.locator('#check-portal-update').click()
    assert checked.value.status == 200
    expect(page.locator('#portal-updates-content')).to_contain_text('v2099.10.15.0')
    assert calls == [f'https://api.github.com/repos/{REPOSITORIES[0]}/releases/latest']
    assert_localized_and_capture(page, 'updates', locale, browser.browser_type.name)
    expect(page.locator('a[href$="/releases/tag/v2099.10.15.0"]')).to_have_count(1)
    # Exact byte progress is shown from the updater, with no invented percentage.
    app.state.updater.set_progress('photocraft', 'download', 1024, 4096)
    navigate(page, 'apps'); navigate(page, 'updates')
    expect(page.locator('progress[value="1024"][max="4096"]')).to_have_count(1)
    app.state.updater.set_progress(None, None)
    sign_out(page)
    sign_in(page, origin, 'another')
    expect(page.locator('.workspace-dock [data-open="photocraft"]')).to_have_count(1)
    navigate(page, 'updates')
    expect(page.locator('#portal-updates-content')).to_contain_text(VERSION)
    expect(page.locator('#check-portal-update')).to_have_count(0)
    assert len(calls) == 1
    sign_out(page)
    sign_in(page, origin)
    expect(page.locator('.workspace-dock [data-open="photocraft"]')).to_have_count(0)
    # The default can be restored without changing the application order.
    page.locator('#configure-dock').click()
    page.locator('#show-all-dock').click()
    page.locator('#save-dock').click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    expect(page.locator('.workspace-dock [data-open="photocraft"]')).to_have_count(1)
    assert not problems, problems
    context.close()


def test_late_account_unauthorized_response_cannot_sign_out_new_session(browser, workspace_site):
    from playwright.sync_api import expect
    _, origin, _ = workspace_site
    context = browser.new_context(ignore_https_errors=True, locale='en-US')
    page = context.new_page()
    errors, console_errors, pending = [], [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: console_errors.append((message.text, message.location.get('url', ''))) if message.type == 'error' else None)
    sign_in(page, origin)
    page.route('**/api/account', lambda route: pending.append(route))
    navigate(page, 'account')
    assert len(pending) == 1
    sign_out(page)
    # Stay in the same document: navigating would cancel the old request. A
    # fresh csrf/session stamp must protect even the same public account id.
    page.locator('#username').fill('admin')
    page.locator('#password').fill(PASSWORD)
    page.locator('#auth-form button').click()
    page.locator('#arrange-apps').wait_for()
    with page.expect_response(lambda response: response.url.endswith('/api/account') and response.status == 401):
        pending[0].fulfill(status=401, content_type='application/json', body='{"detail":"Please log in"}')
    page.unroute('**/api/account')
    # Wait for the delayed response handler, then prove the newly authenticated
    # session still performs an account fetch successfully.
    navigate(page, 'account')
    expect(page.locator('#manage-mfa')).to_be_visible()
    expect(page.locator('#auth-form')).to_have_count(0)
    assert not errors, errors
    assert all('401' in message and url == origin + '/api/account' for message, url in console_errors), console_errors
    context.close()
