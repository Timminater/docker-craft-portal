"""Localized real-browser workflows, layout and per-page console regression checks."""
import json
import os
from pathlib import Path

import pytest

from test_portal_browser import browser, serve, site

pytestmark = pytest.mark.skipif(
    os.getenv('CRAFT_BROWSER_TESTS') != '1', reason='set CRAFT_BROWSER_TESTS=1 to run browsers'
)


@pytest.mark.parametrize('locale,language', [('en-US', 'en'), ('nl-NL', 'nl'), ('fr-FR', 'en')])
def test_localized_portal_pages_without_console_errors(browser, site, locale, language):
    app, origin, apps, port = site
    context = browser.new_context(locale=locale, viewport={'width': 1440, 'height': 1000})
    page = context.new_page()
    problems = []
    checked_pages = []
    current_page = ['setup']
    page.on('pageerror', lambda error: problems.append((current_page[0], 'pageerror', str(error))))
    page.on('console', lambda message: problems.append((current_page[0], 'console', message.text)) if message.type == 'error' else None)
    page.on('response', lambda response: problems.append((current_page[0], 'http', response.status, response.url)) if response.status >= 400 else None)
    page.on('requestfailed', lambda request: problems.append((current_page[0], 'requestfailed', request.url, request.failure)))

    def settled(name):
        current_page[0] = name
        page.wait_for_load_state('networkidle')
        assert page.locator('html').get_attribute('lang') == language
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), name
        assert not problems, json.dumps(problems)
        checked_pages.append(name)

    def navigate(name):
        current_page[0] = name
        page.locator(f'[data-page="{name}"]').click()
        settled(name)

    with serve(app, port):
        page.goto(origin)
        page.locator('#code').wait_for()
        settled('setup')
        assert page.locator('h1').inner_text() == ('Welkom bij Craft Portal' if language == 'nl' else 'Welcome to Craft Portal')
        page.locator('#code').fill(app.state.auth.setup_code)
        page.locator('#username').fill('admin')
        page.locator('#password').fill('browser-test strong password!')
        page.locator('#auth-form button').click()
        page.locator('[data-page="apps"]').wait_for()
        settled('apps')
        assert page.locator('h1').inner_text() == ('Mijn applicaties' if language == 'nl' else 'My applications')
        # Dates must follow the selected supported locale, rather than host defaults.
        assert page.evaluate('fmtTime(1700000000)') == page.evaluate("new Intl.DateTimeFormat(document.documentElement.lang,{dateStyle:'short',timeStyle:'short'}).format(new Date(1700000000000))")
        # Existing installed apps and apps waiting for installation both remain useful cards.
        app.state.db.run("INSERT INTO apps(slug,name,description,status) VALUES('vectorcraft','VectorCraft','','pending')")
        for slug, name in [('documentcraft', 'DocumentCraft'), ('videocraft', 'VideoCraft'),
                           ('audiocraft', 'AudioCraft'), ('designcraft', 'DesignCraft'),
                           ('slidecraft', 'SlideCraft'), ('sheetcraft', 'SheetCraft'),
                           ('codecraft', 'CodeCraft'), ('drawcraft', 'DrawCraft'),
                           ('animationcraft', 'AnimationCraft'), ('modelcraft', 'ModelCraft'),
                           ('publishcraft', 'PublishCraft')]:
            app.state.db.run('INSERT INTO apps(slug,name,description,status) VALUES(?,?,?,?)',
                             (slug, name, '', 'pending'))
        page.reload()
        page.locator('#app [data-open="vectorcraft"]').wait_for()
        assert page.locator('#app [data-open="photocraft"]').is_enabled()
        assert page.locator('#app [data-open="vectorcraft"]').is_disabled()
        for width, height, label in [(1440, 1000, 'desktop'), (390, 844, 'mobile')]:
            page.set_viewport_size({'width': width, 'height': height})
            settled('apps-' + label)
            assert page.locator('.app-card').first.bounding_box()['y'] < (300 if width > 700 else 350), 'Applications should be visible without a large introductory header'
            hero = page.locator('.hero')
            if hero.count():
                assert hero.bounding_box()['height'] < 210, 'App collection header must stay compact'
            screenshots = os.getenv('CRAFT_SCREENSHOT_DIR')
            if screenshots:
                Path(screenshots).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(screenshots) / f'apps-{locale}-{label}.png'), full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1000})
        current_page[0] = 'downloads'
        page.locator('[data-download="photocraft"]').click()
        page.get_by_role('dialog').wait_for()
        settled('downloads')
        assert page.locator('#installer-results a').count() == 3
        page.keyboard.press('Escape')
        navigate('admin')
        from playwright.sync_api import expect
        expect(page.locator('#settings-form')).to_be_visible()
        page.locator('[data-versions="photocraft"]').click()
        page.get_by_role('dialog').wait_for()
        settled('versions')
        page.keyboard.press('Escape')
        navigate('users')
        navigate('events')
        page.locator('#events-list table').wait_for()
        settled('events')
        current_page[0] = 'logout-login'
        page.locator('#logout').click()
        page.locator('#auth-form').wait_for()
        settled('login')
        assert not page.locator('#code').count()
        page.locator('#username').fill('admin')
        page.locator('#password').fill('browser-test strong password!')
        page.locator('#auth-form button').click()
        page.locator('[data-page="apps"]').wait_for()
        settled('authenticated-login')
        # Invalid bridge entry has a localized recovery message without making a failed request.
        current_page[0] = 'bridge'
        page.goto(apps + '/')
        page.locator('#message').wait_for()
        settled('bridge')
        assert page.locator('#message').inner_text() == ('Open deze applicatie via het Craft Portal.' if language == 'nl' else 'Open this application from Craft Portal.')
        assert not problems, json.dumps(problems)
    if os.getenv('CRAFT_SCREENSHOT_DIR'):
        report = Path(os.environ['CRAFT_SCREENSHOT_DIR']) / f'console-{locale}-{browser.browser_type.name}.json'
        report.write_text(json.dumps({'locale': locale, 'pages': checked_pages, 'errors': problems}, indent=2))
    context.close()


@pytest.mark.parametrize('locale,message', [
    ('en-US', 'Incorrect username or password'),
    ('nl-NL', 'Onjuiste gebruikersnaam of wachtwoord'),
])
def test_login_error_uses_browser_language(browser, site, locale, message):
    app, origin, apps, port = site
    app.state.auth.create_user('admin', 'browser-test strong password!', 'admin')
    context = browser.new_context(locale=locale)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    with serve(app, port):
        page.goto(origin)
        page.locator('#username').fill('admin')
        page.locator('#password').fill('incorrect-password')
        # This response is deliberately unauthorized; the clean-console workflow above
        # does not suppress errors from any request.
        with page.expect_response(lambda response: response.url == origin + '/api/login') as attempted:
            page.locator('#auth-form button').click()
        assert attempted.value.status == 401
        page.get_by_role('alert').filter(has_text=message).wait_for()
        assert page.locator('#auth-form').is_visible()
        assert not errors
    context.close()
