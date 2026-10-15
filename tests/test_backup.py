from pathlib import Path
import sqlite3

import pytest

from portal.backup import backup, restore
from portal.database import Database


def seed(path):
    db = Database(path / 'database' / 'portal.sqlite')
    db.run("INSERT INTO users(username,password_hash,role,public_id,created_at) VALUES('owner','hash','admin','aabbccddeeff',1)")
    db.run("INSERT INTO sessions(token_hash,user_id,kind,expires_at,created_at) VALUES('session',1,'portal',9999999999,1)")
    app = path / 'apps' / 'photocraft' / 'versions' / 'v1.0.0'
    app.mkdir(parents=True)
    (app / 'index.html').write_text('retained app')
    return db


def test_snapshot_restore_wal_database_assets_and_revoked_sessions(tmp_path):
    data, snapshot, target = (tmp_path / p for p in ('live', 'snapshot', 'restored'))
    db = seed(data)
    # Exercise SQLite backup with committed WAL pages, not a naked copy of the main file.
    backup(data, snapshot)
    db.close()
    restore(snapshot, target)
    with sqlite3.connect(target / 'database/portal.sqlite') as con:
        assert con.execute('SELECT username FROM users').fetchone() == ('owner',)
        assert con.execute('SELECT count(*) FROM sessions').fetchone() == (0,)
    assert (target / 'apps/photocraft/versions/v1.0.0/index.html').read_text() == 'retained app'
    assert target.stat().st_mode & 0o777 == 0o700


def test_corruption_does_not_create_restore_target(tmp_path):
    data, snapshot, target = (tmp_path / p for p in ('live', 'snapshot', 'restored'))
    seed(data).close()
    backup(data, snapshot)
    (snapshot / 'apps/photocraft/versions/v1.0.0/index.html').write_text('corrupted')
    with pytest.raises(ValueError, match='checksum'):
        restore(snapshot, target)
    assert not target.exists()


def test_backup_rejects_symlinks_and_existing_destinations(tmp_path):
    data, snapshot = (tmp_path / p for p in ('live', 'snapshot'))
    seed(data).close()
    (data / 'apps' / 'outside').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='links'):
        backup(data, snapshot)
    assert not snapshot.exists()
    (data / 'apps' / 'outside').unlink()
    backup(data, snapshot)
    with pytest.raises(ValueError, match='exists'):
        backup(data, snapshot)
    with pytest.raises(ValueError, match='absent'):
        restore(snapshot, data)


def test_offline_restore_can_login_and_launch_retained_app(tmp_path):
    from fastapi.testclient import TestClient
    from portal.config import Config
    from portal.server import create_app
    from urllib.parse import parse_qs, urlparse

    live, snapshot, recovered = (tmp_path / p for p in ('live', 'snapshot', 'recovered'))
    def application(path):
        return create_app(Config(data_dir=path, public_url='https://portal.example.test', apps_domain='',
                                 single_app_url='https://apps.example.test', auto_start_updates=False), False)
    app = application(live)
    client_headers = {'X-Craft-Client': 'portal-v1'}
    with TestClient(app, base_url='https://portal.example.test') as client:
        assert client.post('/api/setup', headers=client_headers,
                           json={'code': app.state.auth.setup_code, 'username': 'owner', 'password': 'recovery-password-123'}).status_code == 200
        db = app.state.db
        db.run("INSERT INTO apps(slug,name,active_version,status) VALUES('photocraft','PhotoCraft','v1.0.0','ready')")
        db.run("INSERT INTO versions(slug,version,rel_path,installed_at) VALUES('photocraft','v1.0.0','apps/photocraft/versions/v1.0.0',1)")
        base = live / 'apps/photocraft/versions/v1.0.0'
        base.mkdir(parents=True)
        (base / 'index.html').write_text('<html>restored application</html>')
    # All app writers are now stopped, as required by the snapshot contract.
    backup(live, snapshot)
    restore(snapshot, recovered)
    restored = application(recovered)
    with TestClient(restored, base_url='https://portal.example.test') as client:
        assert client.get('/api/bootstrap').json()['setup_required'] is False
        assert client.post('/api/login', headers=client_headers,
                           json={'username': 'owner', 'password': 'recovery-password-123'}).status_code == 200
        csrf = client.get('/api/bootstrap').json()['csrf']
        launch = client.post('/api/apps/photocraft/launch', headers={**client_headers, 'X-Craft-CSRF': csrf})
        assert launch.status_code == 200
        ticket = parse_qs(urlparse(launch.json()['url']).fragment)['ticket'][0]
        # Do not nest another lifespan for the same application/database.
        assets = TestClient(restored, base_url='https://apps.example.test')
        try:
            assert assets.post('/_redeem', headers={'X-Craft-Client': 'app-bridge-v1'},
                               json={'slug': 'photocraft', 'ticket': ticket}).status_code == 200
            response = assets.get('/a/photocraft/v/v1.0.0/')
            assert response.status_code == 200
            assert 'restored application' in response.text
        finally:
            assets.close()
