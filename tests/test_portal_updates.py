"""Portal metadata trust, cache behavior and nonblocking updater observations."""
import hashlib
import json
import threading
from urllib.error import HTTPError

import pytest

from portal.updates import CACHE_SECONDS, PortalUpdates, REPOSITORIES, version_parts
from portal.version import VERSION


def test_portal_status_and_explicit_check_require_the_correct_authority(factory, monkeypatch):
    from fastapi.testclient import TestClient
    from tests.test_security import headers, setup

    app = factory(multi_user=True)
    calls = []
    monkeypatch.setattr(app.state.updater, 'request', lambda url, **kw: (calls.append(url), release())[1])
    with TestClient(app, base_url=app.state.cfg.public_url) as admin:
        assert admin.get('/api/portal/status').status_code == 401
        assert admin.post('/api/admin/portal/check', headers=headers()).status_code == 401
        assert setup(admin, app).status_code == 200
        assert admin.get('/api/portal/status').json()['latest_version'] is None
        assert calls == []
        assert admin.post('/api/admin/portal/check', headers=headers()).status_code == 403
        csrf = admin.get('/api/bootstrap').json()['csrf']
        assert admin.post('/api/admin/portal/check', headers={**headers(csrf), 'Origin': 'https://evil.test'}).status_code == 403
        app.state.auth.create_user('another', 'another strong password')
        other = TestClient(app, base_url=app.state.cfg.public_url)
        assert other.post('/api/login', headers=headers(), json={'username': 'another', 'password': 'another strong password'}).status_code == 200
        other_csrf = other.get('/api/bootstrap').json()['csrf']
        assert other.post('/api/admin/portal/check', headers=headers(other_csrf)).status_code == 403
        assert calls == []
        result = admin.post('/api/admin/portal/check', headers=headers(csrf))
        assert result.status_code == 200 and result.json()['latest_version'] == 'v2026.10.16.0'
        assert other.get('/api/portal/status').json()['latest_version'] == 'v2026.10.16.0'
        assert len(calls) == 1
        other.close()


def release(tag='v2026.10.16.0', repository=REPOSITORIES[0]):
    return json.dumps({'tag_name': tag, 'draft': False, 'prerelease': False,
                       'html_url': f'https://github.com/{repository}/releases/tag/{tag}'}).encode()


def test_metadata_check_is_explicit_cached_and_calendar_ordered(factory, monkeypatch):
    updater = factory().state.updater
    overview = PortalUpdates(updater)
    requests = []
    monkeypatch.setattr(updater, 'request', lambda url, **kwargs: (requests.append(url), release())[1])
    assert overview.status()['latest_version'] is None
    assert requests == []
    first = overview.check()
    assert first['version'] == VERSION
    assert first['latest_version'] == 'v2026.10.16.0'
    assert first['update_available']
    assert first['check_error'] is None
    assert overview.check() == first
    assert requests == [f'https://api.github.com/repos/{REPOSITORIES[0]}/releases/latest']
    overview.checked_at -= CACHE_SECONDS + 1
    monkeypatch.setattr(updater, 'request', lambda *args, **kwargs: release(VERSION))
    assert not overview.check()['update_available']
    assert version_parts('v2026.10.15.10') > version_parts('v2026.10.15.9')


@pytest.mark.parametrize('tag', ['v2026.2.30.0', 'v2026.10.15.1-rc1', 'v1.2.3', 'v2026.10.15.-1', '', None])
def test_invalid_stable_versions_rejected(tag):
    with pytest.raises(ValueError):
        version_parts(tag)


def test_fallback_only_for_missing_exact_canonical_repository(factory, monkeypatch):
    updater = factory().state.updater
    calls = []
    def request(url, **kwargs):
        calls.append(url)
        if REPOSITORIES[0] in url:
            raise HTTPError(url, 404, 'missing', None, None)
        return release(repository=REPOSITORIES[1])
    monkeypatch.setattr(updater, 'request', request)
    view = PortalUpdates(updater).check()
    assert view['check_error'] is None
    assert view['release_url'].startswith(f'https://github.com/{REPOSITORIES[1]}/')
    assert calls == [f'https://api.github.com/repos/{repo}/releases/latest' for repo in REPOSITORIES]
    calls.clear()
    def unavailable(url, **kwargs):
        calls.append(url)
        raise HTTPError(url, 403, 'private proxy detail', None, None)
    monkeypatch.setattr(updater, 'request', unavailable)
    view = PortalUpdates(updater).check()
    assert view['check_error'] == 'unavailable'
    assert len(calls) == 1
    assert 'private proxy detail' not in json.dumps(view)


@pytest.mark.parametrize('change', [
    {'html_url': 'https://evil.example/release'}, {'tag_name': 'v2026.10.16.0-rc1'},
    {'prerelease': True}, {'draft': True},
])
def test_untrusted_or_prerelease_metadata_preserves_last_known_release(factory, monkeypatch, change):
    updater = factory().state.updater
    overview = PortalUpdates(updater)
    monkeypatch.setattr(updater, 'request', lambda *args, **kwargs: release())
    known = overview.check()
    invalid = json.loads(release()); invalid.update(change)
    monkeypatch.setattr(updater, 'request', lambda *args, **kwargs: json.dumps(invalid).encode())
    overview.checked_at -= CACHE_SECONDS + 1
    failed = overview.check()
    assert failed['check_error'] == 'invalid_release'
    assert failed['latest_version'] == known['latest_version']
    assert failed['release_url'] == known['release_url']


def test_status_during_network_check_does_not_block(factory, monkeypatch):
    overview = PortalUpdates(factory().state.updater)
    entered, proceed = threading.Event(), threading.Event()
    def request(*args, **kwargs):
        entered.set()
        assert proceed.wait(3)
        return release()
    monkeypatch.setattr(overview.updater, 'request', request)
    check = threading.Thread(target=overview.check)
    check.start()
    try:
        assert entered.wait(2)
        assert overview.status()['checked_at'] is None
    finally:
        proceed.set(); check.join(3)
    assert overview.status()['latest_version'] == 'v2026.10.16.0'


def test_snapshot_filters_disabled_apps_and_never_returns_raw_errors(factory):
    app = factory(); updater = app.state.updater; db = app.state.db
    db.run("INSERT INTO apps(slug,name,active_version,latest_version,last_error) VALUES('photocraft','PhotoCraft','v0.9.0','v0.10.0','SECRET')")
    db.run("INSERT INTO apps(slug,name,disabled,last_error) VALUES('wordcraft','WordCraft',1,'SECRET')")
    updater.set_progress('wordcraft', 'download', 1024, 2048)
    ordinary = updater.snapshot()
    assert [row['slug'] for row in ordinary['apps']] == ['photocraft']
    assert ordinary['progress'] is None
    assert ordinary['apps'][0]['update_available']
    assert ordinary['apps'][0]['has_error']
    assert 'SECRET' not in json.dumps(ordinary)
    admin = updater.snapshot(admin=True)
    assert len(admin['apps']) == 2
    assert admin['progress']['downloaded_bytes'] == 1024
    assert 'SECRET' not in json.dumps(admin)
    # A long install holds this lock; an overview must never wait for it.
    with updater.lock:
        completed = threading.Event()
        worker = threading.Thread(target=lambda: (updater.snapshot(), completed.set()))
        worker.start()
        assert completed.wait(2)
    worker.join(2)


def test_download_reports_real_bytes_and_total(factory, monkeypatch, tmp_path):
    updater = factory().state.updater
    updater.set_progress('photocraft', 'metadata')
    app = updater.db
    app.run("INSERT INTO apps(slug,name) VALUES('photocraft','PhotoCraft')")
    data = b'abcde'
    observations = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            observations.append(updater.snapshot()['progress'])
            return {1: b'abc', 2: b'de'}.get(len(observations), b'')
    monkeypatch.setattr(updater.opener, 'open', lambda *args, **kwargs: Response())
    dest = tmp_path / 'download.zip'
    updater.download('https://github.com/storytold/photocraft/releases/download/v0.9.0/photocraft-web-0.9.0.zip', 5,
                     'sha256:' + hashlib.sha256(data).hexdigest(), dest)
    assert dest.read_bytes() == data
    assert [row['downloaded_bytes'] for row in observations] == [0, 3, 5]
    assert all(row['total_bytes'] == 5 and row['phase'] == 'download' for row in observations)


def test_failed_install_clears_progress_without_exposing_exception(factory, monkeypatch):
    updater = factory().state.updater
    monkeypatch.setattr(updater, 'download', lambda url, size, digest, dest: dest.write_bytes(b'invalid zip'))
    with pytest.raises(Exception):
        updater.install('photocraft', {'version': 'v0.9.0', 'asset': {'browser_download_url': 'unused', 'size': 1, 'digest': 'unused'}})
    assert updater.snapshot()['progress'] is None
