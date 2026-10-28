from fastapi.testclient import TestClient
from tests.test_security import headers, setup
from portal.updater import parse_release, InstallError
import pytest


def test_sources_admin_csrf_validation_isolation_and_reset(factory):
    app = factory(multi_user=True)
    with TestClient(app, base_url=app.state.cfg.public_url) as admin:
        assert setup(admin, app).status_code == 200
        app.state.db.run("INSERT INTO apps(slug,name,active_version,latest_version) VALUES('solidcraft','SolidCraft','v0.12.0','v0.13.1')")
        app.state.auth.create_user('another', 'another strong password')
        other = TestClient(app, base_url=app.state.cfg.public_url)
        assert other.post('/api/login', headers=headers(), json={'username':'another','password':'another strong password'}).status_code == 200
        csrf = admin.get('/api/bootstrap').json()['csrf']
        other_csrf = other.get('/api/bootstrap').json()['csrf']
        endpoint='/api/admin/sources/solidcraft'
        assert other.get('/api/admin/sources').status_code == 403
        assert other.put(endpoint,headers=headers(other_csrf),json={'owner':'example','repository':'solidcraft'}).status_code == 403
        assert admin.put(endpoint,headers=headers(),json={'owner':'example','repository':'solidcraft'}).status_code == 403
        assert admin.put(endpoint,headers={**headers(csrf),'Origin':'https://evil.test'},json={'owner':'example','repository':'solidcraft'}).status_code == 403
        for owner, repo in [('evil/path','solidcraft'), ('example','../repo'), ('https://evil.test','repo')]:
            assert admin.put(endpoint,headers=headers(csrf),json={'owner':owner,'repository':repo}).status_code == 400
        assert admin.put(endpoint,headers=headers(csrf),json={'owner':'example','repository':'new-repo'}).status_code == 200
        source=admin.get('/api/admin/sources').json()['sources'][0]
        assert (source['owner'],source['repository'],source['custom']) == ('example','new-repo',True)
        assert app.state.db.one("SELECT active_version,latest_version FROM apps WHERE slug='solidcraft'") == {'active_version':'v0.12.0','latest_version':None}
        assert admin.get('/api/apps/solidcraft/downloads').json()['github']=='https://github.com/example/new-repo/releases'
        with pytest.raises(InstallError, match='Untrusted asset URL'):
            app.state.updater.download('https://github.com/tangency-labs/solidcraft/releases/download/v0.13.1/solidcraft-web-0.13.1.zip',1,'sha256:'+'a'*64,app.state.cfg.data_dir/'unused.zip')
        assert admin.put(endpoint,headers=headers(csrf),json={'owner':'tangency-labs','repository':'solidcraft'}).status_code == 200
        assert not admin.get('/api/admin/sources').json()['sources'][0]['custom']
        other.close()


def test_custom_repository_is_exact_and_does_not_change_artifact_checks():
    payload={'tag_name':'v0.13.1','assets':[{'name':'solidcraft-web-0.13.1.zip','browser_download_url':'https://github.com/example/new-repo/releases/download/v0.13.1/solidcraft-web-0.13.1.zip','size':42,'digest':'sha256:'+'a'*64}]}
    assert parse_release('solidcraft',payload,'example','new-repo')['version']=='v0.13.1'
    payload['assets'][0]['browser_download_url']='https://github.com/example/other/releases/download/v0.13.1/solidcraft-web-0.13.1.zip'
    with pytest.raises(InstallError): parse_release('solidcraft',payload,'example','new-repo')
