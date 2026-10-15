"""Storage inspection uses authenticated app origins and the live portal parent."""
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from portal.config import Config
from portal.server import create_app
from tests.test_security import headers, setup
from tests.test_shared_apps import build, install, redeem


@pytest.mark.parametrize('isolated', [False, True])
def test_storage_authentication_origin_binding_and_parent_revocation(tmp_path, isolated):
    app = (create_app(Config(data_dir=tmp_path, public_url='https://craft.example.test',
                            apps_domain='apps.example.test', auto_start_updates=False), False)
           if isolated else build(tmp_path))
    with TestClient(app, base_url=app.state.cfg.public_url) as portal:
        assert setup(portal, app).status_code == 200
        install(app)
        csrf = portal.get('/api/bootstrap').json()['csrf']
        assert portal.post('/api/apps/photocraft/storage', headers=headers()).status_code == 403
        assert portal.post('/api/apps/photocraft/storage', headers={**headers(csrf), 'Origin':'https://evil.test'}).status_code == 403
        response = portal.post('/api/apps/photocraft/storage', headers=headers(csrf))
        assert response.status_code == 200
        data = response.json()
        parts = parse_qs(urlparse(data['url']).fragment)
        assert data['slug'] == 'photocraft' and parts['storage'] == ['1']
        assert urlparse(data['url']).query == ''
        assert portal.get('/_storage?slug=photocraft').status_code == 404
        with TestClient(app, base_url=data['origin']) as assets:
            assert assets.get('/_storage?slug=photocraft').status_code == 401
            assert redeem(assets, parts['ticket'][0]).status_code == 200
            page = assets.get('/_storage?slug=photocraft', headers={'Sec-Fetch-Dest':'iframe'})
            assert page.status_code == 200
            assert '<meta name="craft-portal-origin" content="https://craft.example.test">' in page.text
            assert '<meta name="craft-app-slug" content="photocraft">' in page.text
            assert '/_storage.js' in page.text
            assert page.headers['cache-control'] == 'no-store'
            assert 'frame-ancestors https://craft.example.test' in page.headers['content-security-policy']
            assert page.headers['cross-origin-embedder-policy'] == 'require-corp'
            assert assets.get('/_storage?slug=vectorcraft').status_code in (401, 403, 404)
            if isolated:
                # Do not start/stop the same application's lifespan mid-test.
                wrong = TestClient(app, base_url='https://photocraft--000000000001.apps.example.test')
                for item in assets.cookies.jar:
                    wrong.cookies.set(item.name, item.value)
                assert wrong.get('/_storage?slug=photocraft').status_code in (401, 403)
                wrong.close()
            assert portal.post('/api/logout', headers=headers(csrf)).status_code == 200
            assert assets.get('/_storage?slug=photocraft').status_code == 401
    app.state.db.close()


@pytest.mark.parametrize('isolated', [False, True])
def test_storage_origins_group_shared_apps_and_keep_users_isolated(tmp_path, isolated):
    app = (create_app(Config(data_dir=tmp_path, public_url='https://craft.example.test',
                            apps_domain='apps.example.test', auto_start_updates=False), False)
           if isolated else build(tmp_path))
    with TestClient(app, base_url=app.state.cfg.public_url) as portal:
        assert portal.get('/api/storage/origins').status_code == 401
        assert setup(portal, app).status_code == 200
        install(app, 'photocraft')
        install(app, 'vectorcraft')
        install(app, 'wordcraft')
        app.state.db.run("UPDATE apps SET disabled=1 WHERE slug='wordcraft'")
        groups = portal.get('/api/storage/origins').json()['origins']
        assert len(groups) == (2 if isolated else 1)
        assert sorted(record['slug'] for group in groups for record in group['apps']) == ['photocraft', 'vectorcraft']
        if isolated:
            public_id = portal.get('/api/bootstrap').json()['user']['public_id']
            assert {group['origin'] for group in groups} == {
                f'https://{slug}--{public_id}.apps.example.test' for slug in ('photocraft', 'vectorcraft')}
        else:
            assert groups[0]['origin'] == 'https://apps.example.test'
    app.state.db.close()
