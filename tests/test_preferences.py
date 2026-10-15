"""Account-scoped ordering persists independently of browser-local documents."""
import pytest
from fastapi.testclient import TestClient

from portal.config import Config
from portal.server import create_app
from tests.test_security import headers, setup


def create(tmp_path):
    return create_app(Config(data_dir=tmp_path, public_url='https://craft.example.test',
                            apps_domain='apps.example.test', auto_start_updates=False), False)


def put(client, order, **kwargs):
    csrf = client.get('/api/bootstrap').json()['csrf']
    return client.put('/api/preferences', headers=headers(csrf), json={'app_order': order, **kwargs})


def apps(app):
    app.state.db.run("INSERT INTO apps(slug,name) VALUES('photocraft','PhotoCraft')")
    app.state.db.run("INSERT INTO apps(slug,name,disabled) VALUES('vectorcraft','VectorCraft',1)")


def test_preferences_isolated_by_account_and_empty_reset(tmp_path):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as admin:
        assert setup(admin, app).status_code == 200
        apps(app)
        app.state.auth.create_user('another', 'another strong password')
        other = TestClient(app, base_url=app.state.cfg.public_url)
        assert other.post('/api/login', headers=headers(), json={'username': 'another', 'password': 'another strong password'}).status_code == 200
        assert admin.get('/api/preferences').json() == {'app_order': [], 'hidden_dock_apps': []}
        assert other.get('/api/preferences').json() == {'app_order': [], 'hidden_dock_apps': []}
        order = ['vectorcraft', 'photocraft']
        assert put(admin, order).json() == {'app_order': order, 'hidden_dock_apps': []}
        assert other.get('/api/preferences').json() == {'app_order': [], 'hidden_dock_apps': []}
        assert put(other, ['photocraft']).status_code == 200
        assert admin.get('/api/preferences').json() == {'app_order': order, 'hidden_dock_apps': []}
        assert put(admin, []).json() == {'app_order': [], 'hidden_dock_apps': []}
        assert other.get('/api/preferences').json() == {'app_order': ['photocraft'], 'hidden_dock_apps': []}


def test_preferences_persist_after_restart_and_existing_db_upgrade(tmp_path):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as client:
        assert setup(client, app).status_code == 200
        apps(app)
        assert put(client, ['photocraft']).status_code == 200
    restarted = create(tmp_path)
    with TestClient(restarted, base_url=restarted.state.cfg.public_url) as client:
        assert client.post('/api/login', headers=headers(), json={'username': 'admin', 'password': 'strong password 123!'}).status_code == 200
        assert client.get('/api/preferences').json() == {'app_order': ['photocraft'], 'hidden_dock_apps': []}
        # Simulate an older database without this additive table.
        restarted.state.db.run('DROP TABLE user_preferences')
    upgraded = create(tmp_path)
    with TestClient(upgraded, base_url=upgraded.state.cfg.public_url) as client:
        assert client.post('/api/login', headers=headers(), json={'username': 'admin', 'password': 'strong password 123!'}).status_code == 200
        assert client.get('/api/preferences').json() == {'app_order': [], 'hidden_dock_apps': []}
        assert client.get('/api/apps').status_code == 200


def test_preferences_require_auth_csrf_and_portal_host(tmp_path):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as client:
        assert client.get('/api/preferences').status_code == 401
        assert client.put('/api/preferences', json={'app_order': [], 'hidden_dock_apps': []}).status_code == 401
        assert setup(client, app).status_code == 200
        assert client.put('/api/preferences', headers=headers(), json={'app_order': [], 'hidden_dock_apps': []}).status_code == 403
        csrf = client.get('/api/bootstrap').json()['csrf']
        assert client.put('/api/preferences', headers={**headers(csrf), 'Origin': 'https://evil.test'}, json={'app_order': [], 'hidden_dock_apps': []}).status_code == 403
        user = app.state.db.one("SELECT public_id FROM users WHERE username='admin'")
        web = TestClient(app, base_url=f"https://photocraft--{user['public_id']}.apps.example.test")
        assert web.get('/api/preferences').status_code == 404
        assert web.put('/api/preferences', headers=headers(csrf), json={'app_order': [], 'hidden_dock_apps': []}).status_code == 404


@pytest.mark.parametrize('order,extras,status', [
    (['photocraft', 'photocraft'], {}, 422),
    (['../photocraft'], {}, 422),
    (['unknowncraft'], {}, 400),
    (['photocraft'] * 101, {}, 422),
    (['photocraft'], {'user_id': 2}, 422),
    ([123], {}, 422),
    ('photocraft', {}, 422),
    (None, {}, 422),
])
def test_invalid_preferences_cannot_replace_saved_order(tmp_path, order, extras, status):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as client:
        assert setup(client, app).status_code == 200
        apps(app)
        assert put(client, ['photocraft']).status_code == 200
        assert put(client, order, **extras).status_code == status
        assert client.get('/api/preferences').json() == {'app_order': ['photocraft'], 'hidden_dock_apps': []}


def test_preferences_removed_when_user_deleted(tmp_path):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as client:
        assert setup(client, app).status_code == 200
        assert put(client, []).status_code == 200
        assert app.state.db.one('SELECT COUNT(*) AS n FROM user_preferences')['n'] == 1
        app.state.db.run("DELETE FROM users WHERE username='admin'")
        assert app.state.db.one('SELECT COUNT(*) AS n FROM user_preferences')['n'] == 0


def test_dock_visibility_partial_updates_preserve_order_and_account_isolation(tmp_path):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as client:
        assert setup(client, app).status_code == 200
        apps(app)
        assert put(client, ['photocraft', 'vectorcraft']).status_code == 200
        csrf = client.get('/api/bootstrap').json()['csrf']
        saved = client.put('/api/preferences', headers=headers(csrf), json={'hidden_dock_apps': ['photocraft']})
        assert saved.json() == {'app_order': ['photocraft', 'vectorcraft'], 'hidden_dock_apps': ['photocraft']}
        assert put(client, ['vectorcraft']).json()['hidden_dock_apps'] == ['photocraft']
        app.state.auth.create_user('another', 'another strong password')
        other = TestClient(app, base_url=app.state.cfg.public_url)
        assert other.post('/api/login', headers=headers(), json={'username': 'another', 'password': 'another strong password'}).status_code == 200
        assert other.get('/api/preferences').json() == {'app_order': [], 'hidden_dock_apps': []}
        for invalid in (None, ['unknowncraft'], ['photocraft', 'photocraft'], ['../secret'], [123]):
            response = client.put('/api/preferences', headers=headers(csrf), json={'hidden_dock_apps': invalid})
            assert response.status_code in (400, 422)
        assert client.get('/api/preferences').json()['hidden_dock_apps'] == ['photocraft']
    restarted = create(tmp_path)
    with TestClient(restarted, base_url=restarted.state.cfg.public_url) as client:
        assert client.post('/api/login', headers=headers(), json={'username': 'admin', 'password': 'strong password 123!'}).status_code == 200
        assert client.get('/api/preferences').json() == {'app_order': ['vectorcraft'], 'hidden_dock_apps': ['photocraft']}
