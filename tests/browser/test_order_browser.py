"""Account-scoped application arrangement through the real browser interface."""
import os

import pytest

from test_portal_browser import browser
from test_workspace_browser import workspace_site, sign_in, frame_for

pytestmark = pytest.mark.skipif(os.getenv('CRAFT_BROWSER_TESTS') != '1', reason='set CRAFT_BROWSER_TESTS=1')


def card_order(page):
    return page.locator('#app .app-card [data-open]').evaluate_all('(buttons)=>buttons.map(button=>button.dataset.open)')


def dock_order(page):
    return page.locator('.workspace-dock [data-open]').evaluate_all('(buttons)=>buttons.map(button=>button.dataset.open)')


def order_rows(page):
    return page.locator('[data-order-slug]').evaluate_all('(rows)=>rows.map(row=>row.dataset.orderSlug)')


def arrange(page):
    page.locator('#arrange-apps').click()
    page.get_by_role('dialog').wait_for()


def save(page):
    with page.expect_response(lambda response: response.url.endswith('/api/preferences') and response.request.method == 'PUT') as saved:
        page.locator('#save-order').click()
    assert saved.value.status == 200
    page.get_by_role('dialog').wait_for(state='detached')
    return saved.value.json()['app_order']


def logout(page):
    page.locator('#logout').click()
    page.locator('#auth-form').wait_for()


@pytest.mark.parametrize('locale', ['en-US', 'nl-NL'])
def test_saved_order_is_account_scoped_and_preserves_running_apps(browser, workspace_site, locale):
    app, origin, apps = workspace_site
    app.state.auth.create_user('another', 'browser-test strong password!', 'user')
    context = browser.new_context(ignore_https_errors=True, locale=locale, viewport={'width':1440, 'height':1000})
    page = context.new_page()
    problems = []
    page.on('pageerror', lambda error: problems.append(str(error)))
    page.on('console', lambda message: problems.append(message.text) if message.type == 'error' else None)
    page.on('requestfailed', lambda request: problems.append(f'{request.url}: {request.failure}'))
    page.on('response', lambda response: problems.append(f'{response.status} {response.url}') if response.status >= 400 else None)
    sign_in(page, origin)
    assert page.locator('html').get_attribute('lang') == locale[:2]
    assert card_order(page) == ['photocraft', 'vectorcraft']
    assert dock_order(page) == card_order(page)
    arrange(page)
    assert order_rows(page) == ['photocraft', 'vectorcraft']
    assert page.locator('[data-order-slug="vectorcraft"]').get_attribute('draggable') == 'true'
    # Keyboard-operable move controls also work on a narrow viewport.
    page.set_viewport_size({'width':390, 'height':844})
    page.locator('[data-order-up="vectorcraft"]').focus()
    page.keyboard.press('Enter')
    assert order_rows(page) == ['vectorcraft', 'photocraft']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert save(page) == ['vectorcraft', 'photocraft']
    assert card_order(page) == ['vectorcraft', 'photocraft']
    assert dock_order(page) == card_order(page)
    page.reload()
    page.locator('#arrange-apps').wait_for()
    assert card_order(page) == ['vectorcraft', 'photocraft']
    # Marking a favourite must not override an explicitly saved order.
    page.locator('[data-fav="photocraft"]').click()
    assert card_order(page) == ['vectorcraft', 'photocraft']
    # Search preserves the relative custom order when all cards match.
    page.locator('#search').fill('craft')
    assert card_order(page) == ['vectorcraft', 'photocraft']
    page.locator('#search').fill('')
    arrange(page)
    page.locator('[data-order-up="photocraft"]').click()
    assert order_rows(page) == ['photocraft', 'vectorcraft']
    page.locator('#close-modal').click()
    assert card_order(page) == ['vectorcraft', 'photocraft']
    # A second account in the same browser gets its own server preference.
    logout(page)
    sign_in(page, origin, 'another')
    assert card_order(page) == ['photocraft', 'vectorcraft']
    assert dock_order(page) == card_order(page)
    logout(page)
    sign_in(page, origin)
    assert card_order(page) == ['vectorcraft', 'photocraft']
    page.set_viewport_size({'width':1440, 'height':1000})
    page.locator('#app [data-open="photocraft"]').click()
    photo = frame_for(page, 'photocraft')
    photo.locator('#document').fill('unsaved while arranging')
    marker = photo.locator('body').evaluate('()=>window.sessionMarker')
    page.locator('.workspace-toolbar [data-workspace="home"]').click()
    arrange(page)
    page.locator('#reset-order').click()
    assert save(page) == []
    assert card_order(page) == ['photocraft', 'vectorcraft']
    assert dock_order(page) == card_order(page)
    page.locator('.workspace-dock [data-open="photocraft"]').click()
    assert photo.locator('#document').input_value() == 'unsaved while arranging'
    assert photo.locator('body').evaluate('()=>window.sessionMarker') == marker
    page.locator('.workspace-toolbar [data-workspace="home"]').click()
    # Default order resumes the existing favourites-first behavior.
    page.locator('[data-fav="vectorcraft"]').click()
    page.locator('[data-fav="photocraft"]').click()
    assert card_order(page) == ['vectorcraft', 'photocraft']
    assert dock_order(page) == card_order(page)
    assert not problems, problems
    context.close()
