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
