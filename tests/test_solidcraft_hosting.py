import hashlib
import io
import zipfile
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from portal.hosting import solidcraft_index
from tests.test_security import headers, setup
from tests.test_shared_apps import build
from tests.test_solidcraft import Opener, release
from portal.updater import parse_release

REGISTRATION = '''<script>
// Offline use and updates (sw.js; written into release builds).
if ("serviceWorker" in navigator) {
addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
}
</script>'''


def test_offline_adapter_preserves_bootstrap_and_rejects_unknown_registration():
    bootstrap = '<script type="module">import init from "./app.js"; init();</script>'
    output = solidcraft_index('<head></head>'+bootstrap+REGISTRATION)
    assert bootstrap in output and 'navigator.serviceWorker.register' not in output
    assert 'rel="icon"' in output
    with pytest.raises(ValueError, match='Unsupported SolidCraft'):
        solidcraft_index('<script>init();navigator.serviceWorker.register("other.js");</script>')


def test_unknown_offline_bootstrap_cannot_replace_active_release(factory):
    app=factory();updater=app.state.updater
    app.state.db.run("INSERT INTO apps(slug,name) VALUES('solidcraft','SolidCraft')")
    payload,data=release();updater.opener=Opener(data)
    updater.install('solidcraft',parse_release('solidcraft',payload,'bherbruck'))
    payload,_=release('v1.2.4')
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as archive:
        archive.writestr('index.html','<script>navigator.serviceWorker.register("other.js");</script>')
        archive.writestr('app.js','test');archive.writestr('app.wasm',b'\x00asm\x01\x00\x00\x00')
    data=buf.getvalue();payload['assets'][0].update(size=len(data),digest='sha256:'+hashlib.sha256(data).hexdigest())
    updater.opener=Opener(data)
    with pytest.raises(ValueError):updater.install('solidcraft',parse_release('solidcraft',payload,'bherbruck'))
    assert app.state.db.one("SELECT active_version FROM apps WHERE slug='solidcraft'")['active_version']=='v1.2.3'
    assert not (app.state.cfg.data_dir/'apps/solidcraft/versions/v1.2.4').exists()


def test_solidcraft_auth_workers_and_correct_publisher(tmp_path):
    app=build(tmp_path)
    base=app.state.cfg.data_dir/'apps/solidcraft/versions/v1.0.0';base.mkdir(parents=True)
    for filename in ['index.html','sw.js','worker.js']:(base/filename).write_text('test')
    app.state.db.run("INSERT INTO apps(slug,name,active_version,status) VALUES('solidcraft','SolidCraft','v1.0.0','ready')")
    app.state.db.run("INSERT INTO versions(slug,version,rel_path,installed_at) VALUES('solidcraft','v1.0.0','apps/solidcraft/versions/v1.0.0',1)")
    with TestClient(app,base_url=app.state.cfg.public_url) as portal,TestClient(app,base_url=app.state.cfg.single_app_url) as assets:
        assert setup(portal,app).status_code==200
        csrf=portal.get('/api/bootstrap').json()['csrf']
        assert portal.get('/api/apps/solidcraft/downloads').json()['github']=='https://github.com/bherbruck/solidcraft/releases'
        root='/a/solidcraft/v/v1.0.0/'
        assert assets.get(root).status_code==401
        launched=portal.post('/api/apps/solidcraft/launch?embedded=true',headers=headers(csrf)).json()
        ticket=parse_qs(urlparse(launched['url']).fragment)['ticket'][0]
        assert assets.post('/_redeem',headers={'X-Craft-Client':'app-bridge-v1'},json={'ticket':ticket,'slug':'solidcraft'}).status_code==200
        assert assets.get(root).status_code==200
        assert assets.get(root+'sw.js').status_code==404
        assert assets.get(root+'worker.js',headers={'Sec-Fetch-Dest':'serviceworker'}).status_code==404
        worker=assets.get(root+'worker.js',headers={'Sec-Fetch-Dest':'worker'})
        assert worker.status_code==200 and worker.headers['cross-origin-embedder-policy']=='require-corp'
        assert portal.get('/static/artcraft/solidcraft/icon.webp').headers['content-type']=='image/png'
        assert portal.get('/static/artcraft/solidcraft/hero.webp').headers['content-type']=='image/png'
        assert portal.post('/api/logout',headers=headers(csrf)).status_code==200
        assert assets.get(root+'worker.js').status_code==401
