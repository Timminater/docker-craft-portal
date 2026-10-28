"""Admin removal revokes app access, cleans portal files and prevents rediscovery."""
import json
from fastapi.testclient import TestClient
from tests.test_security import headers, setup


def test_remove_and_restore_custom_app_is_authorized_and_persistent(factory, monkeypatch):
    app=factory(multi_user=True)
    with TestClient(app,base_url=app.state.cfg.public_url) as admin:
        assert setup(admin,app).status_code==200
        csrf=admin.get('/api/bootstrap').json()['csrf']
        app.state.auth.create_user('otheruser','another strong password')
        other=TestClient(app,base_url=app.state.cfg.public_url)
        assert other.post('/api/login',headers=headers(),json={'username':'otheruser','password':'another strong password'}).status_code==200
        other_csrf=other.get('/api/bootstrap').json()['csrf']
        db=app.state.db
        db.run("INSERT INTO apps(slug,name,active_version) VALUES('dreamcraft','Dream Craft','v1.0.0')")
        db.run("INSERT INTO app_sources(slug,owner,repository) VALUES('dreamcraft','owner','dream-project')")
        db.run("INSERT INTO apps(slug,name) VALUES('photocraft','PhotoCraft')")
        uid=admin.get('/api/bootstrap').json()['user']['id']
        db.run("INSERT INTO user_preferences(user_id,app_order,hidden_dock_apps) VALUES(?,?,?)",(uid,json.dumps(['dreamcraft','photocraft']),json.dumps(['dreamcraft'])))
        base=app.state.cfg.data_dir/'apps/dreamcraft/versions/v1.0.0';base.mkdir(parents=True)
        (base/'index.html').write_text('app')
        db.run("INSERT INTO versions(slug,version,rel_path,installed_at) VALUES('dreamcraft','v1.0.0','apps/dreamcraft/versions/v1.0.0',1)")
        parent=db.one("SELECT token_hash,user_id FROM sessions WHERE user_id=? AND kind='portal'",(uid,))
        app.state.auth.new_session(uid,'app','dreamcraft',parent['token_hash'])
        unrelated=app.state.auth.new_session(uid,'app','photocraft',parent['token_hash'])
        pending_ticket=app.state.auth.new_ticket(parent,'dreamcraft',require_active=True)
        assert pending_ticket
        endpoint='/api/admin/apps/dreamcraft'
        assert other.delete(endpoint,headers=headers(other_csrf)).status_code==403
        assert admin.delete(endpoint,headers=headers()).status_code==403
        assert admin.delete(endpoint,headers={**headers(csrf),'Origin':'https://evil.test'}).status_code==403
        assert admin.delete('/api/admin/apps/..%2Fother',headers=headers(csrf)).status_code in (404,405)
        assert admin.delete(endpoint,headers=headers(csrf)).status_code==200
        assert not (app.state.cfg.data_dir/'apps/dreamcraft').exists()
        assert not db.one("SELECT * FROM apps WHERE slug='dreamcraft'")
        assert not db.one("SELECT * FROM sessions WHERE kind='app' AND scope='dreamcraft'")
        assert not db.one("SELECT * FROM launch_tickets WHERE slug='dreamcraft'")
        assert app.state.auth.get_session(unrelated,'app','photocraft')
        assert admin.get('/api/bootstrap').json()['user']['id']==uid
        assert app.state.auth.redeem_ticket(pending_ticket,'dreamcraft') is None
        assert app.state.auth.new_ticket(parent,'dreamcraft',require_active=True) is None
        assert admin.get('/api/preferences').json()=={'app_order':['photocraft'],'hidden_dock_apps':[]}
        removed=admin.get('/api/admin/status').json()['removed_apps']
        assert removed==[{'slug':'dreamcraft','name':'Dream Craft'}]
        assert admin.post('/api/admin/apps',headers=headers(csrf),json={'slug':'dreamcraft','name':'Dream Craft','owner':'owner','repository':'dream-project'}).status_code==409
        monkeypatch.setattr(app.state.updater,'trigger',lambda: True)
        assert admin.post(endpoint+'/restore',headers=headers(csrf)).json()=={'ok':True,'scheduled':True}
        assert db.one("SELECT owner,repository FROM app_sources WHERE slug='dreamcraft'")=={'owner':'owner','repository':'dream-project'}
        assert not db.one("SELECT slug FROM removed_apps WHERE slug='dreamcraft'")
        other.close()
    restarted=factory(multi_user=True)
    with TestClient(restarted,base_url=restarted.state.cfg.public_url) as admin:
        assert admin.post('/api/login',headers=headers(),json={'username':'admin','password':'strong password 123!'}).status_code==200
        assert restarted.state.db.one("SELECT slug FROM apps WHERE slug='dreamcraft'")
        assert restarted.state.db.one("SELECT repository FROM app_sources WHERE slug='dreamcraft'")['repository']=='dream-project'


def test_removed_official_apps_do_not_return_during_discovery(factory, monkeypatch):
    app=factory()
    with TestClient(app,base_url=app.state.cfg.public_url) as client:
        assert setup(client,app).status_code==200
        csrf=client.get('/api/bootstrap').json()['csrf']
        app.state.db.run("INSERT INTO apps(slug,name) VALUES('photocraft','PhotoCraft')")
        assert client.delete('/api/admin/apps/photocraft',headers=headers(csrf)).status_code==200
        called=[]
        def request(url,**kwargs):
            if url==app.state.cfg.catalog_url:
                return b'<a href="/apps/photocraft">Photo</a><a href="/apps/vectorcraft">Vector</a>'
            return b'<a href="https://github.com/storytold/vectorcraft">publisher</a>'
        monkeypatch.setattr(app.state.updater,'request',request)
        monkeypatch.setattr(app.state.updater,'sync_app',lambda slug: called.append(slug) or 'current')
        assert app.state.updater.check() is True
        assert 'photocraft' not in called
        assert 'vectorcraft' in called
        assert app.state.db.one("SELECT slug FROM removed_apps WHERE slug='photocraft'")
    restarted=factory()
    with TestClient(restarted,base_url=restarted.state.cfg.public_url) as client:
        assert client.post('/api/login',headers=headers(),json={'username':'admin','password':'strong password 123!'}).status_code==200
        assert restarted.state.db.one("SELECT slug FROM removed_apps WHERE slug='photocraft'")
        assert not restarted.state.db.one("SELECT slug FROM apps WHERE slug='photocraft'")


def test_removal_fails_closed_on_symlink_and_allows_retry(factory,tmp_path):
    app=factory()
    with TestClient(app,base_url=app.state.cfg.public_url) as client:
        assert setup(client,app).status_code==200
        csrf=client.get('/api/bootstrap').json()['csrf']
        app.state.db.run("INSERT INTO apps(slug,name) VALUES('dreamcraft','Dream Craft')")
        outside=tmp_path/'outside';outside.mkdir();(outside/'keep').write_text('preserved')
        target=app.state.cfg.data_dir/'apps/dreamcraft';target.symlink_to(outside,target_is_directory=True)
        assert client.delete('/api/admin/apps/dreamcraft',headers=headers(csrf)).status_code==500
        assert (outside/'keep').read_text()=='preserved'
        assert app.state.db.one("SELECT disabled FROM apps WHERE slug='dreamcraft'")['disabled']==1
        assert app.state.db.one("SELECT slug FROM removed_apps WHERE slug='dreamcraft'")
        target.unlink()
        assert client.delete('/api/admin/apps/dreamcraft',headers=headers(csrf)).status_code==200
        assert (outside/'keep').read_text()=='preserved'


def test_removal_cannot_race_ticket_redemption_into_a_new_app_session(factory,monkeypatch):
    import threading
    app=factory()
    with TestClient(app,base_url=app.state.cfg.public_url) as client:
        assert setup(client,app).status_code==200
        csrf=client.get('/api/bootstrap').json()['csrf']
        db=app.state.db
        db.run("INSERT INTO apps(slug,name,active_version) VALUES('dreamcraft','Dream Craft','v1.0.0')")
        parent=db.one("SELECT token_hash,user_id FROM sessions WHERE kind='portal'")
        ticket=app.state.auth.new_ticket(parent,'dreamcraft',require_active=True)
        entered=threading.Event();release=threading.Event();done=threading.Event();result=[]
        original=app.state.auth.new_session
        def delayed_session(user_id,kind,*args,**kwargs):
            if kind=='app':
                entered.set()
                assert release.wait(5)
            return original(user_id,kind,*args,**kwargs)
        monkeypatch.setattr(app.state.auth,'new_session',delayed_session)
        def redeem():
            try: result.append(app.state.auth.redeem_ticket(ticket,'dreamcraft'))
            finally: done.set()
        thread=threading.Thread(target=redeem);thread.start()
        try:
            # Old redemption created a session in a second transaction, allowing
            # deletion to interleave; atomic redemption finishes before removal.
            assert done.wait(2) or entered.is_set()
            assert client.delete('/api/admin/apps/dreamcraft',headers=headers(csrf)).status_code==200
        finally:
            release.set();thread.join(5)
        assert not thread.is_alive()
        assert done.is_set()
        assert not db.one("SELECT token_hash FROM sessions WHERE kind='app' AND scope='dreamcraft'")
        if result and result[0]: assert app.state.auth.get_session(result[0],'app','dreamcraft') is None
