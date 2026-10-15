from pathlib import Path
import hashlib
import io
import os
import stat
import zipfile

import pytest

from portal.updater import (InstallError, discover_slugs, parse_release, validate_archive,
                            unpack_archive, Updater, verify_official_app_page)


def zip_data(slug="photocraft",version="v0.9.0"):
    b=io.BytesIO()
    with zipfile.ZipFile(b,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{slug}-web-{version[1:]}/index.html",'<html><script src="app.js"></script></html>')
        z.writestr(f"{slug}-web-{version[1:]}/app.js",'console.log("test")')
        z.writestr(f"{slug}-web-{version[1:]}/app_bg.wasm",b'\0asm')
    return b.getvalue()


def test_discovery_and_publisher_verification():
    assert discover_slugs('<a href="/apps/photocraft">Photo</a><a href="/apps/wordcraft">Word</a><a href="https://attacker.tld/apps/evilcraft">Evil</a>',"https://getartcraft.com/apps")==["photocraft","wordcraft"]
    with pytest.raises(InstallError):
        discover_slugs("<a href='/apps/badcraft'>Bad</a>","https://getartcraft.com/apps")
    verify_official_app_page('<a href="https://github.com/storytold/photocraft">source</a>',"photocraft","https://getartcraft.com/apps","storytold")
    with pytest.raises(InstallError):
        verify_official_app_page('<a href="https://github.com/attacker/photocraft">source</a>',"photocraft","https://getartcraft.com/apps","storytold")


def test_release_digest_and_url():
    data=zip_data()
    asset={"name":"photocraft-web-0.9.0.zip","browser_download_url":"https://github.com/storytold/photocraft/releases/download/v0.9.0/photocraft-web-0.9.0.zip","digest":"sha256:"+hashlib.sha256(data).hexdigest(),"size":len(data)}
    release={"tag_name":"v0.9.0","draft":False,"prerelease":False,"assets":[asset]}
    assert parse_release("photocraft",release,"storytold")["version"]=="v0.9.0"
    asset["digest"]=""
    with pytest.raises(InstallError): parse_release("photocraft",release,"storytold")
    asset["digest"]="sha256:"+hashlib.sha256(data).hexdigest()
    asset["browser_download_url"]="https://attacker.invalid/fake.zip"
    with pytest.raises(InstallError): parse_release("photocraft",release,"storytold")


def test_zip_slip_and_symlinks_rejected(tmp_path):
    bad=tmp_path/"bad.zip"
    with zipfile.ZipFile(bad,"w") as z:
        z.writestr("../escape.txt","bad")
        z.writestr("index.html","hello")
        z.writestr("app.js","hi")
        z.writestr("a.wasm","1")
    with pytest.raises(InstallError):unpack_archive(bad,tmp_path/'extract','photocraft','v0.9.0',100000)
    assert not (tmp_path/'escape.txt').exists()
    with zipfile.ZipFile(bad,"w") as z:
        sym=zipfile.ZipInfo("script.js");sym.create_system=3;sym.external_attr=(stat.S_IFLNK|0o777)<<16
        z.writestr(sym,"/etc/passwd")
        z.writestr("index.html","hi");z.writestr("module.wasm","hi")
    with pytest.raises(InstallError):unpack_archive(bad,tmp_path/'extract2','photocraft','v0.9.0',100000)


def test_zip_explicit_directories_are_supported(tmp_path):
    archive=tmp_path/'release.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('release/','')
        z.writestr('release/assets/','')
        z.writestr('release/index.html','<html></html>')
        z.writestr('release/assets/app.js','console.log(1)')
        z.writestr('release/assets/app.wasm',b'\0asm')
    unpack_archive(archive,tmp_path/'app','photocraft','v0.9.0',100000)
    assert (tmp_path/'app/index.html').is_file()
    assert (tmp_path/'app/assets/app.wasm').read_bytes()==b'\0asm'


@pytest.mark.parametrize('entry',['../escape/','release/../escape/','release//assets/','/absolute/','release/./assets/','release\\assets/'])
def test_zip_unsafe_directories_remain_rejected(tmp_path,entry):
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr(entry,'')
        z.writestr('index.html','hello')
        z.writestr('app.js','hello')
        z.writestr('app.wasm',b'\0asm')
    with pytest.raises(InstallError):
        unpack_archive(archive,tmp_path/'app','photocraft','v0.9.0',100000)


@pytest.mark.parametrize('previous_count',[0,1])
def test_retention_counts_previous_versions_separately_after_rollback(factory,monkeypatch,previous_count):
    app=factory();u=app.state.updater;db=app.state.db
    db.run("INSERT INTO apps(slug,name,description) VALUES('photocraft','PhotoCraft','Photo')")
    monkeypatch.setattr(u,'download',lambda url,size,digest,dest:dest.write_bytes(zip_data()))
    for index,version in enumerate(('v0.9.0','v0.10.0','v0.11.0')):
        u.install('photocraft',{'version':version,'asset':{'browser_download_url':'unused','size':1,'digest':'unused'}})
        db.run('UPDATE versions SET installed_at=? WHERE slug=? AND version=?',(index,'photocraft',version))
    u.rollback('photocraft','v0.9.0')
    db.run("UPDATE settings SET value=? WHERE key='keep_previous_versions'",(str(previous_count),))
    u.prune('photocraft')
    retained={row['version'] for row in db.all("SELECT version FROM versions WHERE slug='photocraft'")}
    assert retained==({'v0.9.0','v0.11.0'} if previous_count else {'v0.9.0'})
    base=app.state.cfg.data_dir/'apps/photocraft/versions'
    assert {path.name for path in base.iterdir()}==retained


def test_install_rollback_retention(factory,monkeypatch):
    app=factory();u=app.state.updater;db=app.state.db
    def fake_download(url,size,digest,dest): dest.write_bytes(zip_data(version=current[0]))
    monkeypatch.setattr(u,'download',fake_download)
    current=['v0.9.0']
    for v in ('v0.9.0','v0.10.0','v0.11.0'):
        current[0]=v
        with db.tx() as con: con.execute("INSERT OR IGNORE INTO apps(slug,name,description) VALUES('photocraft','PhotoCraft','Photo')")
        u.install('photocraft',{'version':v,'asset':{'browser_download_url':'unused','size':1,'digest':'unused'}})
    assert db.one("SELECT active_version FROM apps WHERE slug='photocraft'")['active_version']=='v0.11.0'
    assert len(db.all("SELECT version FROM versions WHERE slug='photocraft'"))==3
    u.rollback('photocraft','v0.9.0')
    assert db.one("SELECT active_version FROM apps WHERE slug='photocraft'")['active_version']=='v0.9.0'
    current[0]='v0.12.0'
    u.install('photocraft',{'version':'v0.12.0','asset':{'browser_download_url':'unused','size':1,'digest':'unused'}})
    assert db.one("SELECT active_version FROM apps WHERE slug='photocraft'")['active_version']=='v0.12.0'
    assert len(db.all("SELECT version FROM versions WHERE slug='photocraft'"))==3


def test_install_failure_does_not_switch_active(factory,monkeypatch):
    app=factory();u=app.state.updater;db=app.state.db
    db.run("INSERT INTO apps(slug,name,description) VALUES('photocraft','PhotoCraft','Photo')")
    def good(url,size,digest,dest):dest.write_bytes(zip_data())
    monkeypatch.setattr(u,'download',good)
    u.install('photocraft',{'version':'v0.9.0','asset':{'browser_download_url':'unused','size':1,'digest':'unused'}})
    def corrupted(url,size,digest,dest): dest.write_bytes(b'bad zip')
    monkeypatch.setattr(u,'download',corrupted)
    with pytest.raises(zipfile.BadZipFile):u.install('photocraft',{'version':'v0.10.0','asset':{'browser_download_url':'unused','size':1,'digest':'unused'}})
    assert db.one("SELECT active_version FROM apps WHERE slug='photocraft'")['active_version']=='v0.9.0'
    assert (app.state.cfg.data_dir/'apps'/'photocraft'/'versions'/'v0.9.0'/'index.html').exists()


@pytest.mark.parametrize('entries',[
    [('assets','file'),('assets/app.js','js')],
    [('assets/app.js','js'),('assets','file')],
    [('assets/',''),('assets','file')],
    [('assets','file'),('assets/','')],
])
def test_zip_file_directory_collisions_rejected(tmp_path,entries):
    archive=tmp_path/'collision.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for name,data in entries: z.writestr(name,data)
        z.writestr('index.html','hi');z.writestr('app.js','hi');z.writestr('app.wasm',b'\0asm')
    with pytest.raises(InstallError,match='conflicting'):
        unpack_archive(archive,tmp_path/'out','photocraft','v0.9.0',100000)


def test_redirect_restricts_hosts_and_strips_authorization():
    from portal.updater import SafeRedirect
    from urllib.request import Request
    redirect=SafeRedirect()
    req=Request('https://api.github.com/repos/storytold/photocraft',headers={'Authorization':'Bearer test'})
    for url in ('http://github.com/file','https://evil.example/file','https://github.com:8443/file','https://user@github.com/file'):
        with pytest.raises(InstallError): redirect.redirect_request(req,None,302,'found',{},url)
    result=redirect.redirect_request(req,None,302,'found',{},'https://release-assets.githubusercontent.com/file')
    assert not result.has_header('Authorization')
    assert req.has_header('Authorization')


def test_interrupted_download_and_restart_preserve_installed_version(factory,monkeypatch):
    app=factory();u=app.state.updater;db=app.state.db
    db.run("INSERT INTO apps(slug,name,description) VALUES('photocraft','PhotoCraft','Photo')")
    monkeypatch.setattr(u,'download',lambda url,size,digest,dest:dest.write_bytes(zip_data()))
    release=lambda version:{'version':version,'asset':{'browser_download_url':'unused','size':1,'digest':'unused'}}
    u.install('photocraft',release('v0.9.0'))
    def interrupted(url,size,digest,dest):
        dest.write_bytes(b'partial')
        raise OSError('connection interrupted')
    monkeypatch.setattr(u,'download',interrupted)
    with pytest.raises(OSError):u.install('photocraft',release('v0.10.0'))
    assert list((app.state.cfg.data_dir/'staging').iterdir())==[]
    restarted=Updater(app.state.cfg,db)
    monkeypatch.setattr(restarted,'download',lambda *args:pytest.fail('installed version should work offline'))
    restarted.install('photocraft',release('v0.9.0'))
    assert db.one("SELECT active_version FROM apps WHERE slug='photocraft'")['active_version']=='v0.9.0'
    assert not (app.state.cfg.data_dir/'apps/photocraft/versions/v0.10.0').exists()


def test_trigger_is_single_flight_and_stop_waits(factory,monkeypatch):
    import threading
    u=factory().state.updater
    entered=threading.Event();release=threading.Event()
    def check(): entered.set();release.wait(3)
    monkeypatch.setattr(u,'check',check)
    assert u.trigger()
    assert entered.wait(2)
    assert not u.trigger()
    stopped=threading.Event()
    worker=threading.Thread(target=lambda:(u.stop(),stopped.set()))
    worker.start()
    assert not stopped.wait(.05)
    release.set();worker.join(2)
    assert stopped.is_set()
    assert not u.trigger()


def test_rollback_waits_for_install_serialization(factory):
    import threading
    u=factory().state.updater
    completed=threading.Event()
    def rollback():
        with pytest.raises(InstallError):u.rollback('photocraft','v0.9.0')
        completed.set()
    with u.lock:
        worker=threading.Thread(target=rollback);worker.start()
        assert not completed.wait(.05)
    worker.join(2)
    assert completed.is_set()


def test_live_verification_script_with_synthetic_official_release(monkeypatch,tmp_path):
    import importlib.util
    import json
    import sys
    script=Path(__file__).resolve().parents[1]/'scripts/verify_official_releases.py'
    spec=importlib.util.spec_from_file_location('verify_official_releases',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    data=zip_data()
    asset={'name':'photocraft-web-0.9.0.zip','browser_download_url':'https://github.com/storytold/photocraft/releases/download/v0.9.0/photocraft-web-0.9.0.zip','digest':'sha256:'+hashlib.sha256(data).hexdigest(),'size':len(data)}
    def request(self,url,**kwargs):
        if url.endswith('/releases/latest'):return json.dumps({'tag_name':'v0.9.0','assets':[asset]}).encode()
        if url.endswith('/photocraft'):return b'<a href="https://github.com/storytold/photocraft">source</a>'
        return b'<a href="/apps/photocraft">PhotoCraft</a>'
    monkeypatch.setattr(Updater,'request',request)
    monkeypatch.setattr(Updater,'download',lambda self,url,size,digest,dest:dest.write_bytes(data))
    report=tmp_path/'report.json'
    monkeypatch.setattr(sys,'argv',[str(script),'--run-live','--report',str(report)])
    assert module.main()==0
    result=json.loads(report.read_text())
    assert result['apps'][0]['ok'] is True
    assert result['apps'][0]['digest']==asset['digest']
    assert len(result['apps'][0]['headers'])==3
