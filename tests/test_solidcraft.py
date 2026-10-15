"""The SolidCraft exception trusts one explicitly authorized repository only."""
import hashlib
import io
import json

import pytest

from portal.sources import EXTRA_APPS, app_owner
from portal.updater import InstallError, parse_release
from tests.test_updater import zip_data


def release(version='v1.2.3', *, owner='bherbruck'):
    data = zip_data('solidcraft', version)
    filename = f'solidcraft-web-{version[1:]}.zip'
    asset = {'name': filename, 'browser_download_url': f'https://github.com/{owner}/solidcraft/releases/download/{version}/{filename}',
             'size': len(data), 'digest': 'sha256:' + hashlib.sha256(data).hexdigest()}
    return {'tag_name': version, 'assets': [asset]}, data


class Response(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()


class Opener:
    def __init__(self, data):
        self.data = data
        self.requests = []
    def open(self, request, timeout):
        self.requests.append(request)
        assert request.get_header('Authorization') is None
        return Response(self.data)


def test_registry_only_exposes_authorized_repository():
    assert set(EXTRA_APPS) == {'solidcraft'}
    assert app_owner('solidcraft', 'storytold') == 'bherbruck'
    assert app_owner('photocraft', 'storytold') == 'storytold'
    assert app_owner('evilcraft', 'storytold') == 'storytold'
    bad, _ = release(owner='attacker')
    with pytest.raises(InstallError, match='unusual release download URL'):
        parse_release('solidcraft', bad, app_owner('solidcraft'))


@pytest.mark.parametrize('url', [
    'https://github.com/bherbruck/evilcraft/releases/download/v1.2.3/evilcraft-web-1.2.3.zip',
    'https://github.com/bherbruck/solidcraft-other/releases/download/v1.2.3/solidcraft-web-1.2.3.zip',
    'https://github.com/attacker/solidcraft/releases/download/v1.2.3/solidcraft-web-1.2.3.zip',
    'https://github.com/bherbruck/solidcraft/archive/main.zip',
    'https://github.com/bherbruck/solidcraft/releases/download/v1.2.3/other.zip',
    'https://github.com/bherbruck/solidcraft/releases/download/v1.2.3/solidcraft-web-1.2.3.zip?extra=1',
])
def test_download_rejects_other_extra_publisher_paths(factory, tmp_path, url):
    updater = factory().state.updater
    opener = Opener(b'no request')
    updater.opener = opener
    with pytest.raises(InstallError, match='Untrusted asset URL'):
        updater.download(url, 1, 'sha256:' + '0' * 64, tmp_path / 'bad.zip')
    assert not opener.requests


def test_solidcraft_install_checksum_and_rollback(factory, monkeypatch):
    app = factory()
    updater = app.state.updater
    current = ['v1.2.3']
    urls = []
    def metadata(url, **kwargs):
        urls.append(url)
        assert url == 'https://api.github.com/repos/bherbruck/solidcraft/releases/latest'
        payload, data = release(current[0])
        updater.opener = Opener(data)
        return json.dumps(payload).encode()
    monkeypatch.setattr(updater, 'request', metadata)
    assert updater.sync_app('solidcraft') == 'updated'
    current[0] = 'v1.2.4'
    assert updater.sync_app('solidcraft') == 'updated'
    updater.rollback('solidcraft', 'v1.2.3')
    row = app.state.db.one("SELECT * FROM apps WHERE slug='solidcraft'")
    assert row['active_version'] == 'v1.2.3' and row['auto_update'] == 0
    payload, data = release('v1.2.5')
    updater.opener = Opener(data + b'corrupt')
    with pytest.raises(InstallError, match='larger than expected'):
        updater.install('solidcraft', parse_release('solidcraft', payload, 'bherbruck'))
    assert app.state.db.one("SELECT active_version FROM apps WHERE slug='solidcraft'")['active_version'] == 'v1.2.3'
    assert not (app.state.cfg.data_dir / 'apps/solidcraft/versions/v1.2.5').exists()
    # A same-size payload cannot bypass digest validation either.
    updater.opener = Opener(b'x' * len(data))
    with pytest.raises(InstallError, match='checksum mismatch'):
        updater.install('solidcraft', parse_release('solidcraft', payload, 'bherbruck'))


def test_extra_repository_updates_even_when_catalog_fails(factory, monkeypatch):
    app = factory()
    updater = app.state.updater
    payload, data = release()
    requested = []
    def metadata(url, **kwargs):
        requested.append(url)
        if url == app.state.cfg.catalog_url:
            raise InstallError('catalog unavailable')
        assert url == 'https://api.github.com/repos/bherbruck/solidcraft/releases/latest'
        return json.dumps(payload).encode()
    monkeypatch.setattr(updater, 'request', metadata)
    updater.opener = Opener(data)
    assert updater.check() is False  # Catalog failure remains visible.
    assert app.state.db.one("SELECT active_version FROM apps WHERE slug='solidcraft'")['active_version'] == 'v1.2.3'
    assert 'Catalog check failed' in updater.last_result
    assert not any('/storytold/' in url for url in requested)


def test_extra_discovery_and_existing_update_flags(factory, monkeypatch):
    app = factory()
    updater = app.state.updater
    app.state.db.run("UPDATE settings SET value='false' WHERE key='auto_discover_apps'")
    requested = []
    def metadata(url, **kwargs):
        requested.append(url)
        if url == app.state.cfg.catalog_url:
            return b'<a href="/apps/photocraft">PhotoCraft</a>'
        payload, _ = release()
        assert '/bherbruck/solidcraft/' in url
        return json.dumps(payload).encode()
    monkeypatch.setattr(updater, 'request', metadata)
    assert updater.check() is True
    assert requested == [app.state.cfg.catalog_url]
    app.state.db.run("INSERT INTO apps(slug,name,auto_update) VALUES('solidcraft','SolidCraft',0)")
    assert updater.check() is True
    row = app.state.db.one("SELECT * FROM apps WHERE slug='solidcraft'")
    assert row['latest_version'] == 'v1.2.3' and row['active_version'] is None
    app.state.db.run("UPDATE apps SET auto_update=1,disabled=1 WHERE slug='solidcraft'")
    assert updater.check() is True
    assert app.state.db.one("SELECT active_version FROM apps WHERE slug='solidcraft'")['active_version'] is None


def test_extra_trust_does_not_bypass_original_catalog_publisher(factory, monkeypatch):
    updater = factory().state.updater
    synced = []
    def metadata(url, **kwargs):
        if url == updater.cfg.catalog_url:
            return b'<a href="/apps/photocraft">PhotoCraft</a>'
        return b'<a href="https://github.com/bherbruck/photocraft">untrusted publisher</a>'
    monkeypatch.setattr(updater, 'request', metadata)
    monkeypatch.setattr(updater, 'sync_app', lambda slug: synced.append(slug) or 'current')
    assert updater.check() is True
    assert synced == ['solidcraft']
    assert '1 errors' in updater.last_result
