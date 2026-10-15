"""Shared origins are explicit; authorization still follows the portal session."""
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from portal.config import Config
from portal.server import create_app
from tests.test_security import headers, setup


def build(tmp_path, **kwargs):
    return create_app(Config(data_dir=tmp_path, public_url='https://craft.example.test',
                             apps_domain='', single_app_url='https://apps.example.test',
                             shared_app_multi_user=True, auto_start_updates=False, **kwargs), False)


def install(app, slug='photocraft'):
    app.state.db.run('INSERT INTO apps(slug,name,active_version,status) VALUES(?,?,?,?)',
                     (slug, slug, 'v1.0.0', 'ready'))
    app.state.db.run('INSERT INTO versions(slug,version,rel_path,installed_at) VALUES(?,?,?,?)',
                     (slug, 'v1.0.0', f'apps/{slug}/versions/v1.0.0', 1))
    base = app.state.cfg.data_dir / 'apps' / slug / 'versions/v1.0.0'
    base.mkdir(parents=True)
    (base / 'index.html').write_text('<html>app</html>')


def launch(portal):
    csrf = portal.get('/api/bootstrap').json()['csrf']
    response = portal.post('/api/apps/photocraft/launch?embedded=true', headers=headers(csrf))
    assert response.status_code == 200
    data = response.json()
    assert data['origin'] == 'https://apps.example.test'
    assert data['slug'] == 'photocraft' and data['embedded'] is True
    parts = parse_qs(urlparse(data['url']).fragment)
    assert parts['embedded'] == ['1']
    return parts['ticket'][0]


def redeem(assets, ticket, slug='photocraft'):
    return assets.post('/_redeem', headers={'X-Craft-Client': 'app-bridge-v1'},
                       json={'ticket': ticket, 'slug': slug})


def test_shared_configuration_requires_explicit_separate_origin(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='requires CRAFT_SINGLE_APP_URL'):
        Config(data_dir=tmp_path, public_url='https://craft.example.test', apps_domain='', shared_app_multi_user=True)
    with pytest.raises(ValueError, match='distinct hostname'):
        Config(data_dir=tmp_path, public_url='https://craft.example.test', apps_domain='',
               single_app_url='https://craft.example.test', shared_app_multi_user=True)
    monkeypatch.setenv('CRAFT_PUBLIC_URL', 'https://craft.example.test')
    monkeypatch.setenv('CRAFT_SINGLE_APP_URL', 'https://apps.example.test')
    monkeypatch.setenv('CRAFT_SHARED_APP_MULTI_USER', 'true')
    monkeypatch.delenv('CRAFT_APPS_DOMAIN', raising=False)
    assert Config.from_env().app_origin_mode == 'shared'


@pytest.mark.parametrize('revocation', ['logout', 'expire', 'disable'])
def test_shared_multiuser_session_lifecycle(tmp_path, revocation):
    app = build(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as portal, TestClient(app, base_url=app.state.cfg.single_app_url) as assets:
        assert setup(portal, app).status_code == 200
        install(app)
        bootstrap = portal.get('/api/bootstrap').json()
        assert bootstrap['multi_user'] is True and bootstrap['app_origin_mode'] == 'shared'
        assert portal.post('/api/admin/users', headers=headers(bootstrap['csrf']),
                           json={'username': 'another', 'password': 'another strong password', 'role': 'user'}).status_code == 200
        assert assets.get('/a/photocraft/v/v1.0.0/').status_code == 401
        ticket = launch(portal)
        assert redeem(assets, ticket, 'vectorcraft').status_code == 403
        assert redeem(assets, ticket).status_code == 200
        assert redeem(assets, ticket).status_code == 403
        assert assets.get('/_app_info?slug=photocraft').json()['path'] == '/a/photocraft/v/v1.0.0/'
        assert assets.get('/a/photocraft/v/v1.0.0/').status_code == 200
        if revocation == 'logout':
            assert portal.post('/api/logout', headers=headers(bootstrap['csrf'])).status_code == 200
        elif revocation == 'expire':
            app.state.db.run("UPDATE sessions SET expires_at=0 WHERE kind='portal'")
        else:
            app.state.db.run("UPDATE users SET enabled=0 WHERE username='admin'")
        assert assets.get('/a/photocraft/v/v1.0.0/').status_code == 401
        assert assets.get('/_app_info?slug=photocraft').status_code == 401


def test_embedding_headers_and_portal_boundary(tmp_path):
    app = build(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as portal, TestClient(app, base_url=app.state.cfg.single_app_url) as assets:
        page = portal.get('/')
        assert 'frame-src https://apps.example.test' in page.headers['content-security-policy']
        assert "frame-ancestors 'none'" in page.headers['content-security-policy']
        assert page.headers['cross-origin-opener-policy'] == 'same-origin'
        assert page.headers['cross-origin-embedder-policy'] == 'require-corp'
        assert 'cross-origin-embedder-policy' not in assets.get('/').headers
        bridge = assets.get('/', headers={'Sec-Fetch-Dest': 'iframe'})
        assert '<meta name="craft-portal-origin" content="https://craft.example.test">' in bridge.text
        assert bridge.headers['content-security-policy'] == 'frame-ancestors https://craft.example.test'
        assert bridge.headers['cross-origin-embedder-policy'] == 'require-corp'
        for destination in ("worker", "sharedworker", "serviceworker"):
            response = assets.get("/_bridge.js", headers={"Sec-Fetch-Dest": destination})
            assert response.headers["cross-origin-embedder-policy"] == "require-corp"
        assert assets.get('/api/bootstrap').status_code == 404
        assert portal.get('/a/photocraft/v/v1.0.0/').status_code == 404


def test_isolated_mode_keeps_exact_user_host_binding(tmp_path):
    app = create_app(Config(data_dir=tmp_path, public_url='https://craft.example.test',
                            apps_domain='apps.example.test', auto_start_updates=False), False)
    with TestClient(app, base_url=app.state.cfg.public_url) as portal:
        assert setup(portal, app).status_code == 200
        install(app)
        other_id = app.state.auth.create_user('another', 'another strong password')
        other = app.state.db.one('SELECT public_id FROM users WHERE id=?', (other_id,))
        csrf = portal.get('/api/bootstrap').json()['csrf']
        data = portal.post('/api/apps/photocraft/launch?embedded=true', headers=headers(csrf)).json()
        ticket = parse_qs(urlparse(data['url']).fragment)['ticket'][0]
        assert portal.get('/api/bootstrap').json()['app_origin_mode'] == 'isolated'
        assert 'frame-src https://*.apps.example.test' in portal.get('/').headers['content-security-policy']
        wrong = TestClient(app, base_url=f"https://photocraft--{other['public_id']}.apps.example.test")
        assert redeem(wrong, ticket).status_code == 403
        correct = TestClient(app, base_url=data['origin'])
        assert redeem(correct, ticket).status_code == 200
        assert correct.get('/v/v1.0.0/').status_code == 200
        assert correct.get('/a/photocraft/v/v1.0.0/').status_code == 404
