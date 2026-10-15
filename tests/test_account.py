"""Account ownership, credential rotation and factor replay guarantees."""
import time
import sqlite3
import secrets
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from fastapi.testclient import TestClient

from portal.auth import digest, totp_code
from tests.test_preferences import create
from tests.test_security import headers, setup

PASSWORD = 'strong password 123!'


def change(client, method, path, payload=None):
    csrf = client.get('/api/bootstrap').json()['csrf']
    return client.request(method, '/api/account' + path, headers=headers(csrf), json=payload)


def login(app, username='admin', password=PASSWORD, otp=''):
    client = TestClient(app, base_url=app.state.cfg.public_url)
    response = client.post('/api/login', headers={**headers(), 'User-Agent': 'Mozilla/5.0 Firefox/130.0 Linux'},
                           json={'username': username, 'password': password, 'otp': otp})
    return client, response


def enable(client):
    enrolled = change(client, 'POST', '/mfa/enroll', {'current_password': PASSWORD})
    assert enrolled.status_code == 200
    secret = enrolled.json()['secret']
    response = change(client, 'POST', '/mfa/confirm', {'otp': totp_code(secret, int(time.time() // 30))})
    assert response.status_code == 200
    return secret, response.json()['recovery_codes']


def test_session_list_never_exposes_credentials_and_revoke_is_owned(tmp_path):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as admin:
        assert setup(admin, app).status_code == 200
        other_session, response = login(app)
        assert response.status_code == 200
        user = app.state.auth.create_user('another', 'another strong password')
        stranger, response = login(app, 'another', 'another strong password')
        assert response.status_code == 200
        rows = admin.get('/api/account').json()['sessions']
        assert len(rows) == 2
        assert all(set(row) == {'id', 'device', 'created_at', 'expires_at', 'current'} for row in rows)
        assert len({row['id'] for row in rows}) == 2
        assert not any(row['id'] == stored['token_hash'] for row in rows for stored in app.state.db.all('SELECT token_hash FROM sessions'))
        target = next(row for row in rows if not row['current'])
        assert target['device'] == 'Firefox · Linux'
        assert change(stranger, 'DELETE', '/sessions/' + target['id']).status_code == 404
        assert other_session.get('/api/account').status_code == 200
        assert change(admin, 'DELETE', '/sessions/' + target['id']).status_code == 200
        assert other_session.get('/api/account').status_code == 401
        assert stranger.get('/api/account').status_code == 200


def test_password_change_revokes_other_sessions_children_tickets_and_preserves_current(tmp_path):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as client:
        setup(client, app)
        other, _ = login(app)
        auth = app.state.auth
        token = other.cookies.get('__Host-craft_portal_session')
        s = auth.get_session(token, 'portal')
        ticket = auth.new_ticket(s, 'photocraft')
        child = auth.redeem_ticket(auth.new_ticket(s, 'photocraft'), 'photocraft')
        assert change(client, 'POST', '/password', {'current_password': 'incorrect', 'new_password': 'new strong password 123'}).status_code == 400
        assert change(client, 'POST', '/password', {'current_password': PASSWORD, 'new_password': 'short'}).status_code == 422
        assert change(client, 'POST', '/password', {'current_password': PASSWORD, 'new_password': 'new strong password 123'}).status_code == 200
        assert client.get('/api/account').status_code == 200
        assert other.get('/api/account').status_code == 401
        assert auth.get_session(child, 'app', 'photocraft') is None
        assert auth.redeem_ticket(ticket, 'photocraft') is None
        assert not app.state.db.one('SELECT token_hash FROM sessions WHERE parent_hash=?', (digest(token),))
        assert auth.signin('admin', PASSWORD) is None
        assert auth.signin('admin', 'new strong password 123')


def test_account_requires_auth_csrf_and_portal_host(tmp_path):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as client:
        assert client.get('/api/account').status_code == 401
        setup(client, app)
        for method, path, payload in [('POST', '/password', {'current_password': PASSWORD, 'new_password': PASSWORD}),
                                      ('POST', '/mfa/enroll', {'current_password': PASSWORD}),
                                      ('POST', '/mfa/confirm', {'otp': '000000'}),
                                      ('DELETE', '/mfa', {'current_password': PASSWORD, 'otp': '000000'}),
                                      ('DELETE', '/sessions/others', None)]:
            assert client.request(method, '/api/account' + path, json=payload, headers=headers()).status_code == 403
        assert client.get('/api/account', headers={'Host': 'photocraft--000000000000.apps.example.test'}).status_code == 404
        assert change(client, 'POST', '/password', {'current_password': PASSWORD, 'new_password': PASSWORD, 'user_id': 2}).status_code == 422


def test_mfa_enrollment_requires_same_session_and_expiry(tmp_path):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as client:
        setup(client, app)
        second, _ = login(app)
        r = change(client, 'POST', '/mfa/enroll', {'current_password': PASSWORD})
        secret = r.json()['secret']
        assert 'issuer=Craft+Portal' in r.json()['otpauth_uri']
        assert app.state.auth.signin('admin', PASSWORD)  # Not enabled before confirmation.
        code = totp_code(secret, int(time.time() // 30))
        assert change(second, 'POST', '/mfa/confirm', {'otp': code}).status_code == 400
        app.state.db.run('UPDATE account_mfa_pending SET expires_at=0')
        assert change(client, 'POST', '/mfa/confirm', {'otp': code}).status_code == 400
        assert client.get('/api/account').json()['mfa_enabled'] is False


def test_mfa_login_recovery_atomic_replay_and_disable(tmp_path):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as client:
        setup(client, app)
        second, _ = login(app)
        secret, codes = enable(client)
        assert second.get('/api/account').status_code == 401
        public = client.get('/api/account').json()
        assert public['mfa_enabled'] is True and public['recovery_codes_remaining'] == 10
        assert secret not in str(public) and codes[0] not in str(app.state.db.all('SELECT * FROM account_recovery_codes'))
        auth = app.state.auth
        assert auth.signin('admin', PASSWORD) is None
        # The enrollment factor cannot immediately be reused to log in.
        assert auth.signin('admin', PASSWORD, totp_code(secret, int(time.time() // 30))) is None
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = list(pool.map(lambda _: auth.signin('admin', PASSWORD, codes[0]), range(2)))
        assert sum(result is not None for result in attempts) == 1
        assert client.get('/api/account').json()['recovery_codes_remaining'] == 9
        assert change(client, 'POST', '/password', {'current_password': PASSWORD, 'new_password': 'a new secure password'}).status_code == 400
        assert change(client, 'DELETE', '/mfa', {'current_password': PASSWORD, 'otp': codes[0]}).status_code == 400
        assert change(client, 'DELETE', '/mfa', {'current_password': PASSWORD, 'otp': codes[1]}).status_code == 200
        assert auth.signin('admin', PASSWORD)
        assert client.get('/api/account').json()['recovery_codes_remaining'] == 0
        assert not app.state.db.one('SELECT secret FROM account_mfa_pending')


def test_factor_counter_single_use_and_wrong_password_cannot_consume_recovery(tmp_path):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as client:
        setup(client, app)
        secret, codes = enable(client)
        auth, db = app.state.auth, app.state.db
        assert auth.signin('admin', 'incorrect password', codes[0]) is None
        assert auth.signin('admin', PASSWORD, codes[0])
        db.run('UPDATE users SET mfa_last_counter=-1')
        code = totp_code(secret, int(time.time() // 30))
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = list(pool.map(lambda _: auth.signin('admin', PASSWORD, code), range(2)))
        assert sum(result is not None for result in attempts) == 1
        assert auth.signin('admin', PASSWORD, code) is None


def test_password_verification_attempts_rate_limited(tmp_path):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as client:
        setup(client, app)
        for _ in range(8):
            assert change(client, 'POST', '/mfa/enroll', {'current_password': 'wrong'}).status_code == 400
        assert change(client, 'POST', '/mfa/enroll', {'current_password': PASSWORD}).status_code == 429


def test_credential_update_rechecks_live_session_and_competing_password(tmp_path, monkeypatch):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as client:
        setup(client, app)
        from portal.auth import PH
        original = PH.hash
        def concurrent_hash(password):
            value = original(password)
            if password == 'a newer secure password':
                app.state.db.run('UPDATE users SET password_hash=?', (original('concurrent secure password'),))
            return value
        monkeypatch.setattr('portal.account.PH', SimpleNamespace(hash=concurrent_hash, verify=PH.verify))
        response = change(client, 'POST', '/password', {'current_password': PASSWORD, 'new_password': 'a newer secure password'})
        assert response.status_code == 409
        assert app.state.auth.signin('admin', 'concurrent secure password')
        assert not app.state.auth.signin('admin', 'a newer secure password')


def test_signin_cannot_issue_old_password_session_after_competing_change(tmp_path, monkeypatch):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as client:
        setup(client, app)
        from portal.auth import PH
        replacement = PH.hash('concurrently changed password')
        def verify_and_change(hashed, password):
            result = PH.verify(hashed, password)
            app.state.db.run('UPDATE users SET password_hash=?', (replacement,))
            return result
        before = app.state.db.one('SELECT COUNT(*) AS n FROM sessions')['n']
        monkeypatch.setattr('portal.auth.PH', SimpleNamespace(verify=verify_and_change,
                            check_needs_rehash=PH.check_needs_rehash, hash=PH.hash))
        assert app.state.auth.signin('admin', PASSWORD) is None
        assert app.state.db.one('SELECT COUNT(*) AS n FROM sessions')['n'] == before


def test_password_change_fails_if_current_session_revoked_during_hash(tmp_path, monkeypatch):
    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as client:
        setup(client, app)
        from portal.auth import PH
        def hash_and_revoke(password):
            result = PH.hash(password)
            app.state.db.run('DELETE FROM sessions')
            return result
        monkeypatch.setattr('portal.account.PH', SimpleNamespace(hash=hash_and_revoke, verify=PH.verify))
        assert change(client, 'POST', '/password', {'current_password': PASSWORD, 'new_password': 'a new secure password'}).status_code == 401
        assert app.state.auth.signin('admin', PASSWORD)


def test_pre_feature_database_upgrade_preserves_login_sessions_order_and_mfa(tmp_path):
    """Upgrade an actual old database, rather than a current schema with data removed."""
    from portal.auth import PH
    from portal.database import Database

    path = tmp_path / 'database' / 'portal.sqlite'
    path.parent.mkdir()
    portal_token, app_token = secrets.token_urlsafe(36), secrets.token_urlsafe(36)
    password_hash = PH.hash(PASSWORD)
    public_id = 'a1b2c3d4e5f6'
    now = time.time()
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','user')),
            public_id TEXT NOT NULL UNIQUE,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL
        );
        CREATE TABLE sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('portal','app')),
            scope TEXT NOT NULL DEFAULT '',
            parent_hash TEXT,
            expires_at REAL NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE user_preferences (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            app_order TEXT NOT NULL DEFAULT '[]'
        );
    """)
    old.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?)', (1, 'admin', password_hash, 'admin', public_id, 1, now))
    old.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?)', (digest(portal_token), 1, 'portal', '', None, now + 3600, now))
    old.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?)', (digest(app_token), 1, 'app', 'photocraft', digest(portal_token), now + 3600, now))
    old.execute('INSERT INTO user_preferences VALUES(?,?)', (1, '["vectorcraft","photocraft"]'))
    old.commit()
    old.close()

    upgraded = Database(path)
    migrated = upgraded.all('SELECT token_hash,display_id,device_label FROM sessions')
    ids = {row['token_hash']: row['display_id'] for row in migrated}
    assert len(set(ids.values())) == 2 and all(ids.values())
    assert all(row['device_label'] == 'Unknown browser' for row in migrated)
    assert upgraded.one('SELECT password_hash FROM users')['password_hash'] == password_hash
    assert upgraded.one('SELECT mfa_secret,mfa_last_counter FROM users') == {'mfa_secret': None, 'mfa_last_counter': -1}
    upgraded.close()

    app = create(tmp_path)
    with TestClient(app, base_url=app.state.cfg.public_url) as client:
        client.cookies.set('__Host-craft_portal_session', portal_token, domain='craft.example.test', path='/')
        assert client.get('/api/bootstrap').json()['user']['public_id'] == public_id
        preferences = client.get('/api/preferences').json()
        assert preferences['app_order'] == ['vectorcraft', 'photocraft']
        assert preferences['hidden_dock_apps'] == []
        account = client.get('/api/account').json()
        assert account['sessions'][0]['id'] == ids[digest(portal_token)]
        assert portal_token not in str(account) and digest(portal_token) not in str(account)
        assert password_hash not in str(account)
        assert app.state.auth.get_session(app_token, 'app', 'photocraft')
        another, response = login(app)
        assert response.status_code == 200
        assert another.get('/api/preferences').json()['app_order'] == preferences['app_order']
        secret, codes = enable(client)
        assert another.get('/api/account').status_code == 401
        assert client.get('/api/account').json()['mfa_enabled'] is True

    # The additive upgrade is idempotent and persisted MFA continues working.
    restarted = create(tmp_path)
    with TestClient(restarted, base_url=restarted.state.cfg.public_url) as client:
        client.cookies.set('__Host-craft_portal_session', portal_token, domain='craft.example.test', path='/')
        account = client.get('/api/account').json()
        assert account['mfa_enabled'] is True
        assert account['sessions'][0]['id'] == ids[digest(portal_token)]
        assert secret not in str(account) and codes[0] not in str(account)
        assert client.get('/api/preferences').json()['app_order'] == ['vectorcraft', 'photocraft']
        rows = restarted.state.db.all('SELECT token_hash,display_id FROM sessions')
        assert {row['token_hash']: row['display_id'] for row in rows} == ids
        assert restarted.state.auth.signin('admin', PASSWORD) is None
        assert restarted.state.auth.signin('admin', PASSWORD, codes[0])
        assert restarted.state.auth.signin('admin', PASSWORD, codes[0]) is None
