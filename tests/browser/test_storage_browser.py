"""Aggregate browser storage comes from a utility frame on the real app origin."""
import os

import pytest

from test_portal_browser import browser
from test_workspace_browser import workspace_site, PASSWORD, sign_in

pytestmark = pytest.mark.skipif(os.getenv('CRAFT_BROWSER_TESTS') != '1', reason='set CRAFT_BROWSER_TESTS=1')


def test_storage_utility_reports_only_metadata_and_validates_parent(browser, workspace_site):
    _, origin, apps = workspace_site
    context = browser.new_context(locale='en-US', ignore_https_errors=True)
    page = context.new_page()
    failures, requests = [], []
    page.on('pageerror', lambda error: failures.append(str(error)))
    page.on('console', lambda message: failures.append(message.text) if message.type == 'error' else None)
    page.on('request', lambda request: requests.append(request.url))
    page.goto(origin)
    page.evaluate("""async password=>{
      const login=await fetch('/api/login',{method:'POST',headers:{'X-Craft-Client':'portal-v1','Content-Type':'application/json'},
        body:JSON.stringify({username:'admin',password})});
      if(!login.ok)throw new Error('Fixture login failed');
      const session=await (await fetch('/api/bootstrap')).json();
      const response=await fetch('/api/apps/photocraft/storage',{method:'POST',
        headers:{'X-Craft-Client':'portal-v1','X-Craft-CSRF':session.csrf}});
      if(!response.ok)throw new Error('Storage launch failed');
      const result=await response.json();
      window.storageProbeMessages=[];window.storageProbeOrigin=result.origin;
      const frame=document.createElement('iframe');frame.id='storage-probe';frame.title='Storage test';
      frame.setAttribute('sandbox','allow-scripts allow-same-origin');
      addEventListener('message',event=>{
        if(event.origin===result.origin&&event.source===frame.contentWindow)storageProbeMessages.push(event.data);
      });
      frame.src=result.url;document.body.append(frame);
    }""", PASSWORD)
    page.wait_for_function("()=>storageProbeMessages.some(message=>message.type==='craft-storage-ready')")
    frame = page.locator('#storage-probe').content_frame
    assert frame.locator('body').evaluate('()=>location.origin') == apps
    assert frame.locator('body').evaluate('()=>location.hash') == ''
    assert not any('/a/photocraft/' in url for url in requests), 'Storage assessment must not launch the editor'
    frame.locator('body').evaluate("()=>localStorage.setItem('storage-private-document','private document content')")
    # A source with the expected origin still cannot impersonate the parent.
    frame.locator('body').evaluate("""portalOrigin=>{
      dispatchEvent(new MessageEvent('message',{origin:portalOrigin,source:window,
        data:{type:'craft-storage-request',slug:'photocraft',id:'forged_source',action:'estimate'}}));
      const forged=new MessageEvent('message',{origin:'https://evil.test',
        data:{type:'craft-storage-request',slug:'photocraft',id:'forged_origin',action:'estimate'}});
      Object.defineProperty(forged,'source',{value:parent});dispatchEvent(forged);
    }""", origin)
    page.evaluate("""()=>document.querySelector('#storage-probe').contentWindow.postMessage({
      type:'craft-storage-request',slug:'vectorcraft',id:'forged_slug',action:'estimate'},storageProbeOrigin)""")
    page.evaluate("""()=>document.querySelector('#storage-probe').contentWindow.postMessage({
      type:'craft-storage-request',slug:'photocraft',id:'estimate_test',action:'estimate'},storageProbeOrigin)""")
    page.wait_for_function("()=>storageProbeMessages.some(message=>message.id==='estimate_test')")
    result = page.evaluate("storageProbeMessages.find(message=>message.id==='estimate_test')")
    assert set(result) == {'type','slug','id','usage','quota','persisted','supported','error'}
    assert result['supported']['estimate'] is True
    assert isinstance(result['usage'], (int, float)) and result['usage'] >= 0
    assert isinstance(result['quota'], (int, float)) and result['quota'] > 0
    assert result['persisted'] in (True, False, None)
    assert not page.evaluate("storageProbeMessages.some(message=>message.id?.startsWith('forged_'))")
    # A browser denial is reported as a safe code, never its arbitrary message.
    frame.locator('body').evaluate("""()=>Object.defineProperty(navigator.storage,'persist',{
      value:async()=>{throw new DOMException('private document content','NotAllowedError')},configurable:true})""")
    page.evaluate("""()=>document.querySelector('#storage-probe').contentWindow.postMessage({
      type:'craft-storage-request',slug:'photocraft',id:'persist_test',action:'persist'},storageProbeOrigin)""")
    page.wait_for_function("()=>storageProbeMessages.some(message=>message.id==='persist_test')")
    result = page.evaluate("storageProbeMessages.find(message=>message.id==='persist_test')")
    assert result['error'] == 'NotAllowedError'
    assert 'private document content' not in str(page.evaluate('storageProbeMessages'))
    assert frame.locator('body').evaluate("()=>localStorage.getItem('storage-private-document')") == 'private document content'
    assert not failures, failures
    context.close()


@pytest.mark.parametrize('locale', ['en-US', 'nl-NL'])
def test_storage_page_groups_shared_apps_reuses_frame_and_cleans_up(browser, workspace_site, locale):
    from playwright.sync_api import expect
    app, origin, _ = workspace_site
    context = browser.new_context(locale=locale, ignore_https_errors=True)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
    sign_in(page, origin)
    page.locator('.nav [data-page="storage"]').click()
    groups = page.locator('[data-storage-origin]')
    expect(groups).to_have_count(1)
    expect(groups.locator('dl')).to_be_visible()
    assert 'Photocraft' in groups.inner_text() and 'Vectorcraft' in groups.inner_text()
    expect(page.locator('iframe')).to_have_count(1)
    probe = page.locator('iframe').content_frame
    probe.locator('body').evaluate("""()=>{
      window.storageFrameMarker='same storage frame';
      Object.defineProperty(navigator.storage,'persisted',{value:async()=>false,configurable:true});
      Object.defineProperty(navigator.storage,'persist',{value:async()=>{
        throw new DOMException('Browser denied persistence','NotAllowedError');
      },configurable:true});
    }""")
    measure = groups.locator('[data-storage-action="estimate"]')
    measure.click()
    expect(measure).to_be_enabled()
    expect(groups.locator('dl')).to_be_visible()
    expect(page.locator('iframe')).to_have_count(1)
    assert probe.locator('body').evaluate('()=>window.storageFrameMarker') == 'same storage frame'
    groups.locator('[data-storage-action="persist"]').click()
    expect(groups.locator('dl')).to_be_visible()
    expect(groups.get_by_text(page.evaluate("CraftI18n.t('storage.persistenceDenied')"), exact=True)).to_be_visible()
    expect(page.locator('iframe')).to_have_count(1)
    page.locator('.nav [data-page="apps"]').click()
    expect(page.locator('iframe')).to_have_count(0)
    page.locator('.nav [data-page="storage"]').click()
    expect(groups.locator('dl')).to_be_visible()
    expect(page.locator('iframe')).to_have_count(1)
    assert page.locator('iframe').content_frame.locator('body').evaluate('()=>window.storageFrameMarker') is None
    app.state.db.run("DELETE FROM sessions WHERE kind='portal'")
    page.evaluate('async()=>await checkWorkspaceSession()')
    expect(page.locator('#auth-form')).to_be_visible()
    expect(page.locator('iframe')).to_have_count(0)
    assert not errors, errors
    context.close()
