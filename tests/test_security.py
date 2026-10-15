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
            assert webapp.post('/_redeem',headers={'X-Craft-Client':'app-bridge-v1'},json={'ticket':ticket,'slug':'photocraft'}).status_code==200
            assert webapp.get('/_app_info?slug=photocraft').json()['version']=='v0.9.0'
            assert webapp.get('/a/photocraft/v/v0.9.0/').status_code==200
            assert webapp.post('/_redeem',headers={'X-Craft-Client':'app-bridge-v1'},json={'ticket':ticket,'slug':'photocraft'}).status_code==403
