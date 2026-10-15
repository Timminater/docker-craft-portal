from fastapi.testclient import TestClient


def headers(csrf=""):
    h={"X-Craft-Client":"portal-v1"}
    if csrf: h["X-Craft-CSRF"]=csrf
    return h


def setup(client,app):
    return client.post("/api/setup",headers=headers(),json={"username":"admin","password":"strong password 123!","code":app.state.auth.setup_code})


def test_first_run_login_logout_and_guard(factory):
    app=factory()
    with TestClient(app,base_url="http://localhost:8080") as c:
        assert c.get("/api/bootstrap").json()["setup_required"] is True
        assert c.get("/api/admin/status").status_code == 401
        assert c.post("/api/setup",headers=headers(),json={"username":"admin","password":"strong password 123!","code":"invalid"}).status_code == 400
        assert setup(c,app).status_code == 200
        data=c.get("/api/bootstrap").json()
        assert data["user"]["role"]=="admin"
        csrf=data["csrf"]
        assert c.get("/api/admin/status").status_code==200
        assert c.put("/api/admin/settings",headers=headers(),json={"update_interval_hours":6,"auto_install_versions":True,"auto_discover_apps":True,"keep_previous_versions":2}).status_code==403
        assert c.put("/api/admin/settings",headers=headers(csrf),json={"update_interval_hours":6,"auto_install_versions":True,"auto_discover_apps":True,"keep_previous_versions":2}).status_code==200
        assert c.post("/api/logout",headers=headers(csrf)).status_code==200
        assert c.get("/api/admin/status").status_code==401
        assert c.post("/api/login",headers=headers(),json={"username":"admin","password":"strong password 123!"}).status_code==200
        assert c.get("/api/admin/status").status_code==200
        assert c.post("/api/admin/users",headers=headers(c.get('/api/bootstrap').json()['csrf']),json={"username":"another","password":"a very good password","role":"user"}).status_code==400


def test_security_host_and_setup_idempotence(factory):
    app=factory()
    with TestClient(app,base_url="http://localhost:8080") as c:
        assert setup(c,app).status_code==200
        assert setup(c,app).status_code==400
        assert c.get("/",headers={"Host":"attacker.invalid"}).status_code==421
        assert c.get("/api/bootstrap",headers={"Host":"attacker.invalid"}).status_code==421
        assert c.get("/api/admin/status").status_code==200
        assert c.post("/api/logout",headers={**headers(c.get('/api/bootstrap').json()['csrf']),"Origin":"https://evil.example"}).status_code==403


def test_multiuser_subdomain_isolation(factory):
    app=factory(multi_user=True)
    with TestClient(app,base_url="https://craft.example.test") as c:
        assert setup(c,app).status_code==200
        csrf=c.get('/api/bootstrap').json()['csrf']
        assert c.post("/api/admin/users",headers=headers(csrf),json={"username":"someone","password":"a very good password","role":"user"}).status_code==200
        admin=app.state.db.one("SELECT public_id FROM users WHERE username='admin'")
        other=app.state.db.one("SELECT public_id FROM users WHERE username='someone'")
        assert admin['public_id']!=other['public_id']
        with TestClient(app,base_url=f"https://photocraft--{admin['public_id']}.apps.example.test") as ac:
            assert ac.get("/v/v0.9.0/").status_code==401 or ac.get("/v/v0.9.0/").status_code==404
            assert ac.get("/").status_code==200


def test_single_user_apps_on_separate_origin(factory,tmp_path):
    from pathlib import Path
    from portal.config import Config
    from portal.server import create_app
    # Simulate two public hostnames that point to the same container.
    app = create_app(Config(data_dir=tmp_path,
                public_url='https://craft.example.test',apps_domain='',single_app_url='https://apps.example.test',auto_start_updates=False),False)
    with TestClient(app,base_url='https://craft.example.test') as portal:
        assert setup(portal,app).status_code == 200
        db=app.state.db
        db.run("INSERT INTO apps(slug,name,description,active_version,status) VALUES('photocraft','PhotoCraft','Editor','v0.9.0','ready')")
        db.run("INSERT INTO versions(slug,version,rel_path,installed_at) VALUES('photocraft','v0.9.0','apps/photocraft/versions/v0.9.0',1)")
        base=app.state.cfg.data_dir/'apps/photocraft/versions/v0.9.0'
        base.mkdir(parents=True)
        (base/'index.html').write_text('<html>WebAssembly app</html>')
        csrf=portal.get('/api/bootstrap').json()['csrf']
        assert portal.get('/a/photocraft/v/v0.9.0/').status_code == 404
        r=portal.post('/api/apps/photocraft/launch',headers=headers(csrf))
        assert r.status_code==200
        launch=r.json()['url']
        assert launch.startswith('https://apps.example.test/#ticket=')
        ticket=launch.split('ticket=')[1].split('&')[0]
        with TestClient(app,base_url='https://apps.example.test') as webapp:
            assert webapp.get('/a/photocraft/v/v0.9.0/').status_code==401
            redeemed = webapp.post('/_redeem',headers={'X-Craft-Client':'app-bridge-v1'},json={'ticket':ticket,'slug':'photocraft'})
            assert redeemed.status_code == 200
            assert redeemed.headers['set-cookie'].startswith('__Host-craft_app_session_photocraft=')
            assert 'Secure' in redeemed.headers['set-cookie']
            assert 'Path=/' in redeemed.headers['set-cookie']
            assert 'domain=' not in redeemed.headers['set-cookie'].lower()
            assert webapp.get('/_app_info?slug=photocraft').json()['version']=='v0.9.0'
            asset = webapp.get('/a/photocraft/v/v0.9.0/')
            assert asset.status_code == 200
            assert asset.headers['cache-control'] == 'no-store'
            assert webapp.post('/_redeem',headers={'X-Craft-Client':'app-bridge-v1'},json={'ticket':ticket,'slug':'photocraft'}).status_code==403
            db.run("UPDATE sessions SET expires_at=0 WHERE kind='portal'")
            assert webapp.get('/_app_info?slug=photocraft').status_code == 401
            assert webapp.get('/a/photocraft/v/v0.9.0/').status_code == 401


def test_app_sessions_require_live_matching_portal_parent(factory):
    from portal.auth import digest
    app = factory()
    auth, db = app.state.auth, app.state.db
    try:
        user = auth.create_user('alice', 'a strong password 123')
        other = auth.create_user('bobby', 'another strong password')
        parent = auth.new_session(user, 'portal')
        token = auth.new_session(user, 'app', 'photocraft', digest(parent))
        assert auth.get_session(token, 'app', 'photocraft')
        db.run('UPDATE sessions SET expires_at=0 WHERE token_hash=?', (digest(parent),))
        assert auth.get_session(token, 'app', 'photocraft') is None
        db.run('UPDATE sessions SET expires_at=9999999999 WHERE token_hash=?', (digest(parent),))
        assert auth.get_session(token, 'app', 'photocraft')
        db.run('UPDATE sessions SET user_id=? WHERE token_hash=?', (other, digest(parent)))
        assert auth.get_session(token, 'app', 'photocraft') is None
        db.run('DELETE FROM sessions WHERE token_hash=?', (digest(parent),))
        assert auth.get_session(token, 'app', 'photocraft') is None
    finally:
        db.close()


def test_logout_revokes_app_sessions_and_pending_tickets(factory):
    from portal.auth import digest
    app = factory()
    auth, db = app.state.auth, app.state.db
    try:
        user = auth.create_user('alice', 'a strong password 123')
        parent = auth.new_session(user, 'portal')
        session = auth.get_session(parent, 'portal')
        ticket = auth.new_ticket(session, 'photocraft')
        token = auth.redeem_ticket(ticket, 'photocraft')
        pending = auth.new_ticket(session, 'photocraft')
        assert auth.get_session(token, 'app', 'photocraft')
        auth.revoke(digest(parent))
        assert auth.get_session(token, 'app', 'photocraft') is None
        assert auth.redeem_ticket(pending, 'photocraft') is None
    finally:
        db.close()


def test_sensitive_responses_are_not_cached_and_login_fields_are_bounded(factory):
    app = factory()
    with TestClient(app, base_url='http://localhost:8080') as c:
        for path in ('/api/bootstrap', '/api/admin/status', '/a/photocraft/v/v1/', '/v/v1/'):
            assert c.get(path).headers['cache-control'] == 'no-store'
        assert setup(c, app).headers['cache-control'] == 'no-store'
        for payload in ({'username': 'x' * 49, 'password': 'normal'},
                        {'username': 'admin', 'password': 'x' * 1025}):
            response = c.post('/api/login', headers=headers(), json=payload)
            assert response.status_code == 422
            assert response.headers['cache-control'] == 'no-store'


def test_setup_attempts_are_rate_limited(factory):
    app = factory()
    with TestClient(app, base_url='http://localhost:8080') as c:
        payload = {'username': 'admin', 'password': 'strong password 123!', 'code': 'wrong'}
        for _ in range(8):
            assert c.post('/api/setup', headers=headers(), json=payload).status_code == 400
        assert c.post('/api/setup', headers=headers(), json=payload).status_code == 429


def test_streamed_body_limit_does_not_depend_on_content_length():
    import asyncio
    from portal.server import RequestBodyLimit

    async def run():
        called, sent = [], []
        async def downstream(scope, receive, send):
            called.append(True)
        chunks = iter([
            {'type': 'http.request', 'body': b'x' * 40000, 'more_body': True},
            {'type': 'http.request', 'body': b'x' * 40000, 'more_body': False},
        ])
        async def receive():
            return next(chunks)
        async def send(message):
            sent.append(message)
        await RequestBodyLimit(downstream)({'type': 'http', 'method': 'POST'}, receive, send)
        assert not called
        assert sent[0]['status'] == 413
    asyncio.run(run())


def test_blocking_login_does_not_block_health_requests(factory, monkeypatch):
    import asyncio
    import threading
    import httpx

    app = factory()
    app.state.auth.create_user('admin', 'strong password 123!', 'admin')
    entered, release = threading.Event(), threading.Event()

    def slow_signin(username, password):
        entered.set()
        assert release.wait(3), 'test did not release password verification'
        return None

    monkeypatch.setattr(app.state.auth, 'signin', slow_signin)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost:8080') as client:
            pending = asyncio.create_task(client.post('/api/login', headers=headers(),
                json={'username': 'admin', 'password': 'strong password 123!'}))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                response = await asyncio.wait_for(client.get('/healthz'), timeout=1)
                assert response.status_code == 200
                assert not pending.done()
            finally:
                release.set()
                assert (await pending).status_code == 401

    try:
        asyncio.run(run())
    finally:
        app.state.db.close()


def test_https_auth_uses_host_prefixed_cookies_only(factory):
    from portal.auth import PORTAL_COOKIE
    app = factory(multi_user=True)
    with TestClient(app, base_url='https://craft.example.test') as c:
        response = setup(c, app)
        cookie = response.headers['set-cookie']
        assert cookie.startswith(f'__Host-{PORTAL_COOKIE}=')
        assert 'Secure' in cookie and 'HttpOnly' in cookie and 'Path=/' in cookie
        assert 'domain=' not in cookie.lower()
        token = c.cookies.get(f'__Host-{PORTAL_COOKIE}')
        csrf = c.get('/api/bootstrap').json()['csrf']
        # A valid token injected under the old, Domain-capable name is ignored.
        c.cookies.clear()
        c.cookies.set(PORTAL_COOKIE, token, domain='craft.example.test')
        assert c.get('/api/bootstrap').json()['user'] is None
        c.cookies.set(f'__Host-{PORTAL_COOKIE}', token, domain='craft.example.test')
        response = c.post('/api/logout', headers=headers(csrf))
        assert response.status_code == 200
        assert response.headers['set-cookie'].startswith(f'__Host-{PORTAL_COOKIE}=')
        assert 'Secure' in response.headers['set-cookie']
        assert 'domain=' not in response.headers['set-cookie'].lower()
