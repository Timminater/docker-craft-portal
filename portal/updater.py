"""Transactional, allowlisted, in-container official WASM release updater."""
from __future__ import annotations

import hashlib
from functools import wraps
import html.parser
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
import zipfile

from .config import Config
from .database import Database
from .hosting import solidcraft_index
from .sources import EXTRA_APPS, app_owner, repository
from .version import VERSION

LOG = logging.getLogger(__name__)
SLUG = re.compile(r"^[a-z][a-z0-9]{1,29}craft$")
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
DESCRIPTIONS = {
    "photocraft": ("PhotoCraft", "Fotobewerking"),
    "vectorcraft": ("VectorCraft", "Vectorillustraties"),
    "filmcraft": ("FilmCraft", "Videobewerking"),
    "lightcraft": ("LightCraft", "RAW-foto's en fotobibliotheek"),
    "pdfcraft": ("PdfCraft", "PDF-bewerking"),
    "effectcraft": ("EffectCraft", "Visuele effecten en animatie"),
    "designcraft": ("DesignCraft", "Paginaopmaak en publicatie"),
    "figcraft": ("FigCraft", "Interfaceontwerp"),
    "wordcraft": ("WordCraft", "Tekstverwerking"),
    "soundcraft": ("SoundCraft", "Audio en muziek"),
    "deckcraft": ("DeckCraft", "Presentaties"),
    "cadcraft": ("CADCraft", "Technische tekeningen"),
    "gridcraft": ("GridCraft", "Spreadsheets"),
}


class InstallError(Exception):
    pass


def serialized(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return run


def installation_progress(method):
    @wraps(method)
    def run(self, slug, *args, **kwargs):
        self.set_progress(slug, "metadata")
        try:
            return method(self, slug, *args, **kwargs)
        finally:
            self.set_progress(None, None)
    return run


class SafeRedirect(HTTPRedirectHandler):
    # Exact allowlist; never follow an arbitrary repo-provided URL or SSRF target.
    allowed_hosts = {
        "github.com", "api.github.com", "getartcraft.com", "www.getartcraft.com", "release-assets.githubusercontent.com",
        "objects.githubusercontent.com", "github-releases.githubusercontent.com",
    }

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        p = urlparse(newurl)
        if p.scheme != "https" or p.hostname not in self.allowed_hosts or p.port not in (None,443) or p.username or p.password:
            raise InstallError("Download redirected outside trusted GitHub hosts")
        redirect = super().redirect_request(req,fp,code,msg,headers,newurl)
        # A GitHub API token must never reach a release CDN or website.
        if redirect is not None and p.hostname != "api.github.com":
            redirect.remove_header("Authorization")
        return redirect


class CatalogLinks(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.extend(value for key,value in attrs if key == "href" and value)


def discover_slugs(page: str, catalog_url: str) -> list[str]:
    p = CatalogLinks(); p.feed(page)
    origin = urlparse(catalog_url)
    found = set()
    for href in p.links:
        u = urlparse(urljoin(catalog_url, href))
        if u.netloc != origin.netloc or u.scheme != "https":
            continue
        m = re.fullmatch(r"/apps/([a-z][a-z0-9]*craft)/?",u.path)
        if m and SLUG.fullmatch(m[1]):
            found.add(m[1])
    if not found or "photocraft" not in found:
        raise InstallError("Official catalog missing expected apps; preserving installations")
    return sorted(found)


def verify_official_app_page(page: str, slug: str, catalog_url: str, owner: str):
    p = CatalogLinks(); p.feed(page)
    for href in p.links:
        parsed = urlparse(urljoin(catalog_url,href))
        if parsed.hostname == "github.com" and parsed.path.rstrip("/").lower() == f"/{owner}/{slug}" and parsed.scheme == "https":
            return
    raise InstallError(f"{slug}: no official publisher link found in catalog page")


def parse_release(slug: str, release: dict, owner: str, repo: str | None = None) -> dict:
    repo = repo or slug
    tag = release.get("tag_name", "")
    if not TAG.fullmatch(tag) or release.get("draft") or release.get("prerelease"):
        raise InstallError(f"{slug}: latest release is not a supported stable version")
    filename = f"{slug}-web-{tag[1:]}.zip"
    candidates = [a for a in release.get("assets",[]) if a.get("name") == filename]
    if len(candidates) != 1:
        raise InstallError(f"{slug}: no WebAssembly release ZIP named {filename}")
    asset = candidates[0]
    expected_url = f"https://github.com/{owner}/{repo}/releases/download/{tag}/{filename}"
    if asset.get("browser_download_url") != expected_url:
        raise InstallError(f"{slug}: unusual release download URL")
    sha = asset.get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}",sha):
        raise InstallError(f"{slug}: no trustworthy SHA-256 digest")
    if not isinstance(asset.get("size"),int) or not 0 < asset["size"] <= 220*1024*1024:
        raise InstallError(f"{slug}: invalid ZIP size")
    native = []
    for a in release.get("assets",[]):
        name = a.get("name", "")
        url = a.get("browser_download_url", "")
        if (isinstance(name,str) and isinstance(url,str)
                and (name.endswith((".msi",".dmg",".AppImage",".deb",".rpm",".flatpak","-portable.zip")))
                and url.startswith(f"https://github.com/{owner}/{repo}/releases/download/{tag}/")
                and not name.endswith(".AppImage.zsync")):
            native.append({"name":name,"url":url})
    return {"version":tag,"asset":asset,"native":native}


def validate_archive(z: zipfile.ZipFile, app: str, version: str, limit: int) -> tuple[list[zipfile.ZipInfo],str]:
    items = z.infolist()
    if not items or len(items) > 4000:
        raise InstallError("ZIP contains no files or too many entries")
    names = set(); directories = set(); total=0; files=[]
    for info in items:
        name = info.filename
        # ZIP directories have one trailing slash; validate the remaining path
        # without relaxing checks for empty components or traversal.
        entry_path = name[:-1] if info.is_dir() else name
        path = PurePosixPath(entry_path)
        if ("\\" in name or name.startswith("/") or ":" in name or any(x in {"", ".", ".."} for x in entry_path.split("/"))
                or any(part in {"..", "."} for part in path.parts)):
            raise InstallError(f"Unsafe ZIP entry: {name[:80]}")
        mode = info.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if file_type not in (0, stat.S_IFDIR, stat.S_IFREG):
            raise InstallError("ZIP contains a link or special file")
        if info.flag_bits & 0x1:
            raise InstallError("Encrypted ZIP entries are not supported")
        parents={str(parent) for parent in path.parents if str(parent) != "."}
        if entry_path in names or parents & names or (not info.is_dir() and entry_path in directories):
            raise InstallError("ZIP contains conflicting file and directory entries")
        directories.update(parents)
        if info.is_dir():
            directories.add(entry_path)
            continue
        if file_type == stat.S_IFDIR:
            raise InstallError("ZIP directory entry missing trailing slash")
        if name in names:
            raise InstallError("Duplicate ZIP filename")
        names.add(name)
        total += info.file_size
        if info.file_size > 256*1024*1024 or total > limit or (info.compress_size == 0 and info.file_size > 0):
            raise InstallError("ZIP decompression size exceeds limits")
        if info.compress_size and info.file_size > info.compress_size*300:
            raise InstallError("Suspicious ZIP compression ratio")
        files.append(info)
    roots = {PurePosixPath(f.filename).parts[0] for f in files}
    prefix = next(iter(roots)) + "/" if len(roots) == 1 and all(len(PurePosixPath(f.filename).parts)>1 for f in files) else ""
    flat = {f.filename[len(prefix):] for f in files if f.filename.startswith(prefix)}
    if "index.html" not in flat or not any(p.endswith(".wasm") or ".part-" in p for p in flat) or not any(p.endswith(".js") for p in flat):
        raise InstallError("ZIP missing index.html, JavaScript or WebAssembly")
    return files,prefix


def unpack_archive(archive: Path, dest: Path, slug: str, version: str, max_bytes: int):
    dest.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        items,prefix = validate_archive(z,slug,version,max_bytes)
        for info in items:
            rel = info.filename[len(prefix):]
            if not rel:
                continue
            target = dest / rel
            target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src,out,1024*1024)
            target.chmod(0o644)


class Updater:
    def __init__(self, cfg: Config, db: Database):
        self.cfg,self.db = cfg,db
        self.lock = threading.RLock()
        self.schedule_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.progress = None
        self.manual_thread = None
        self.scheduled = False
        self.running = False
        self.last_check = None
        self.next_check = None
        self.last_result = "never"
        self.last_check_failed = False
        self.stop_event = threading.Event()
        self.thread = None
        (cfg.data_dir/"apps").mkdir(parents=True,exist_ok=True)
        (cfg.data_dir/"staging").mkdir(parents=True,exist_ok=True)
        self.opener = build_opener(SafeRedirect)

    def set_progress(self, slug, phase, downloaded_bytes=None, total_bytes=None):
        with self.state_lock:
            self.progress = None if phase is None else {
                "slug": slug, "phase": phase,
                "downloaded_bytes": downloaded_bytes, "total_bytes": total_bytes,
            }

    def snapshot(self, *, admin=False):
        # Do not acquire the install lock: downloads can take minutes, while the
        # overview must remain available to report their actual progress.
        with self.state_lock:
            state = {"running": self.running or self.progress is not None,
                     "last_check": self.last_check, "next_check": self.next_check,
                     "last_result": ("never" if self.last_check is None else
                                     "error" if self.last_check_failed else "complete"),
                     "progress": dict(self.progress) if self.progress else None}
        with self.schedule_lock:
            state["scheduled"] = self.scheduled
        rows = self.db.all("SELECT slug,name,active_version,latest_version,auto_update,status,last_error,disabled FROM apps ORDER BY name COLLATE NOCASE")
        visible = {row["slug"] for row in rows if admin or not row["disabled"]}
        if state["progress"] and state["progress"]["slug"] is not None and state["progress"]["slug"] not in visible:
            state["progress"] = None
        state["apps"] = []
        for row in rows:
            if row["slug"] not in visible:
                continue
            error = bool(row.pop("last_error"))
            disabled = bool(row.pop("disabled"))
            row["auto_update"] = bool(row["auto_update"])
            row["has_error"] = error
            row["update_available"] = bool(row["latest_version"] and row["active_version"] != row["latest_version"])
            if admin:
                row["disabled"] = disabled
            state["apps"].append(row)
        return state

    def request(self,url: str,*,limit=3_000_000) -> bytes:
        p = urlparse(url)
        allowed = {"api.github.com", "getartcraft.com", "www.getartcraft.com"}
        if p.scheme != "https" or p.hostname not in allowed or p.port not in (None,443) or p.username or p.password:
            raise InstallError("Disallowed metadata URL")
        headers = {"User-Agent":f"craft-portal/{VERSION.removeprefix('v')} (+https://github.com/Timminater/craft-portal)","Accept":"application/vnd.github+json" if p.hostname=="api.github.com" else "text/html"}
        if p.hostname=="api.github.com" and self.cfg.github_token:
            headers["Authorization"] = "Bearer " + self.cfg.github_token
        with self.opener.open(Request(url,headers=headers),timeout=25) as response:
            if response.status != 200:
                raise InstallError(f"HTTP {response.status}")
            data = response.read(limit+1)
            if len(data)>limit:
                raise InstallError("Metadata response size exceeded")
            return data

    def download(self,url: str, expected_size: int, expected_digest: str, destination: Path):
        p = urlparse(url)
        match = re.fullmatch(r"/([^/]+)/([^/]+)/releases/download/(v[0-9]+\.[0-9]+\.[0-9]+)/([a-z][a-z0-9]{1,29}craft)-web-([0-9]+\.[0-9]+\.[0-9]+)\.zip", p.path)
        additional = bool(match and match[3] == 'v' + match[5] and
                          (match[1], match[2]) == repository(self.db, match[4], self.cfg.trusted_owner))
        if (p.scheme!="https" or p.hostname!="github.com" or p.port not in (None,443)
                or p.username or p.password or p.query or p.fragment
                or not additional):
            raise InstallError("Untrusted asset URL")
        headers = {"User-Agent":f"craft-portal/{VERSION.removeprefix('v')}"}
        total=0; h=hashlib.sha256()
        with self.state_lock:
            slug = self.progress["slug"] if self.progress else None
        self.set_progress(slug, "download", 0, expected_size)
        with self.opener.open(Request(url,headers=headers),timeout=90) as response, destination.open("xb") as f:
            while True:
                if self.stop_event.is_set():
                    raise InstallError("Updater is shutting down")
                data=response.read(1024*1024)
                if not data: break
                total+=len(data)
                if total>self.cfg.max_zip_bytes or total>expected_size:
                    raise InstallError("ZIP larger than expected")
                h.update(data);f.write(data)
                self.set_progress(slug, "download", total, expected_size)
            f.flush();os.fsync(f.fileno())
        if total!=expected_size or not hmac_compare(h.hexdigest(), expected_digest.lower().removeprefix("sha256:")):
            raise InstallError("Release ZIP size or checksum mismatch")

    def sync_app(self,slug: str):
        if self.db.one('SELECT slug FROM removed_apps WHERE slug=?', (slug,)):
            raise InstallError('Application has been removed')
        owner,repo=repository(self.db,slug,self.cfg.trusted_owner)
        api=f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        release=json.loads(self.request(api))
        parsed=parse_release(slug,release,owner,repo)
        version=parsed["version"]
        known=self.db.one("SELECT * FROM apps WHERE slug=?",(slug,))
        extra = EXTRA_APPS.get(slug)
        name,description = ((extra["name"], extra["description"]) if extra else
                            DESCRIPTIONS.get(slug,(slug.removesuffix("craft").capitalize()+"Craft","Creative application")))
        with self.db.tx() as con:
            con.execute("INSERT OR IGNORE INTO apps(slug,name,description,updated_at) VALUES(?,?,?,?)",(slug,name,description,time.time()))
            con.execute("UPDATE apps SET latest_version=?,updated_at=? WHERE slug=?",(version,time.time(),slug))
            con.execute("DELETE FROM release_assets WHERE slug=?",(slug,))
            con.executemany("INSERT INTO release_assets(slug,name,url) VALUES(?,?,?)",[(slug,a["name"],a["url"]) for a in parsed["native"]])
        app=self.db.one("SELECT * FROM apps WHERE slug=?",(slug,))
        if app["disabled"] or not app["auto_update"]:
            return "skipped"
        if app["active_version"] == version and (self.cfg.data_dir/"apps"/slug/"versions"/version/"index.html").is_file():
            return "current"
        if app["active_version"] and self.db.setting("auto_install_versions")!="true":
            return "available"
        self.install(slug, parsed)
        return "updated"

    @serialized
    @installation_progress
    def install(self,slug: str, release: dict):
        if self.stop_event.is_set(): raise InstallError("Updater is shutting down")
        if not SLUG.fullmatch(slug): raise InstallError("Invalid app slug")
        version=release["version"]
        if not TAG.fullmatch(version): raise InstallError("Invalid version")
        base=self.cfg.data_dir/"apps"/slug/"versions"
        base.mkdir(parents=True,exist_ok=True)
        dest=base/version
        # If previously installed, only switch the active pointer.
        if dest.exists():
            if not (dest/"index.html").is_file():
                raise InstallError("Existing installation is corrupt; manual recovery required")
        else:
            with tempfile.TemporaryDirectory(prefix="craft-",dir=self.cfg.data_dir/"staging") as tmp:
                tmp=Path(tmp)
                zip_path=tmp/"bundle.zip"
                asset=release["asset"]
                self.download(asset["browser_download_url"],asset["size"],asset["digest"],zip_path)
                self.set_progress(slug, "extract")
                unpack_archive(zip_path,tmp/"unpacked",slug,version,self.cfg.max_extracted_bytes)
                if slug == 'solidcraft':
                    index = tmp / 'unpacked' / 'index.html'
                    index.write_text(solidcraft_index(index.read_text(encoding='utf-8')), encoding='utf-8')
                if self.stop_event.is_set():
                    raise InstallError("Updater is shutting down")
                self.set_progress(slug, "activate")
                os.replace(tmp/"unpacked",dest)
        self.set_progress(slug, "activate")
        with self.db.tx() as con:
            con.execute("INSERT OR IGNORE INTO versions(slug,version,rel_path,installed_at) VALUES(?,?,?,?)", (slug,version,f"apps/{slug}/versions/{version}",time.time()))
            con.execute("UPDATE apps SET active_version=?, status='ready', last_error='', installed_at=COALESCE(installed_at,?),updated_at=? WHERE slug=?",(version,time.time(),time.time(),slug))
        self.prune(slug)
        self.db.log("success","installed",version,slug)

    @serialized
    def prune(self,slug: str):
        keep=max(0,min(10,int(self.db.setting("keep_previous_versions"))))
        app=self.db.one("SELECT active_version FROM apps WHERE slug=?",(slug,))
        versions=self.db.all("SELECT version,rel_path FROM versions WHERE slug=? ORDER BY installed_at DESC",(slug,))
        previous=[v for v in versions if v["version"] != app["active_version"]]
        retained={v["version"] for v in previous[:keep]}
        retained.add(app["active_version"])
        for v in versions:
            if v["version"] in retained: continue
            target=(self.cfg.data_dir/v["rel_path"]).resolve()
            allowed=(self.cfg.data_dir/"apps"/slug/"versions").resolve()
            if target.parent!=allowed:
                raise InstallError("Refusing to delete file outside app version directory")
            shutil.rmtree(target,ignore_errors=False)
            self.db.run("DELETE FROM versions WHERE slug=? AND version=?",(slug,v["version"]))

    @serialized
    def rollback(self,slug: str,version: str):
        if not SLUG.fullmatch(slug) or not TAG.fullmatch(version):
            raise InstallError("Invalid app/version")
        row=self.db.one("SELECT rel_path FROM versions WHERE slug=? AND version=?",(slug,version))
        if not row or not (self.cfg.data_dir/row["rel_path"]/"index.html").is_file():
            raise InstallError("Target version is not installed")
        # A manual rollback pins the chosen build until an administrator resumes updates.
        self.db.run("UPDATE apps SET active_version=?,auto_update=0,status='ready',last_error='',updated_at=? WHERE slug=?",(version,time.time(),slug))
        self.db.log("warning","rollback",version+" (automatic updates paused)",slug)

    def check(self):
        if self.stop_event.is_set(): return False
        if not self.lock.acquire(blocking=False):
            return False
        with self.state_lock:
            self.running=True
            self.last_check=time.time()
        try:
            self.set_progress(None, "catalog")
            self.db.log("info","check_started","Checking official app catalog")
            catalog_error = None
            try:
                page=self.request(self.cfg.catalog_url).decode("utf-8")
                catalog_slugs=discover_slugs(page,self.cfg.catalog_url)
            except Exception as exc:
                # Additional exact repositories remain independent of catalog outages.
                catalog_error = str(exc)
                catalog_slugs = []
                LOG.exception("Catalog check failed")
                self.db.log("error","catalog_failed",catalog_error)
            existing={app["slug"] for app in self.db.all("SELECT slug FROM apps")}
            slugs=sorted(set(catalog_slugs) | set(EXTRA_APPS) | {x['slug'] for x in self.db.all('SELECT slug FROM app_sources')})
            removed={x['slug'] for x in self.db.all('SELECT slug FROM removed_apps')}
            slugs=[slug for slug in slugs if slug not in removed]
            if self.db.setting("auto_discover_apps")!="true":
                slugs=[x for x in slugs if x in existing]
            errors=[]; updates=0
            for slug in slugs:
                if self.stop_event.is_set(): break
                self.set_progress(slug, "metadata")
                try:
                    if slug not in EXTRA_APPS and not self.db.one('SELECT slug FROM app_sources WHERE slug=?', (slug,)):
                        # Original publishers still require the official catalog link.
                        app_page=self.request(f"{self.cfg.catalog_url}/{slug}").decode("utf-8")
                        verify_official_app_page(app_page,slug,self.cfg.catalog_url,self.cfg.trusted_owner)
                    status=self.sync_app(slug)
                    updates+=int(status=="updated")
                except Exception as exc:
                    LOG.exception("Update failed: %s",slug)
                    errors.append(slug)
                    self.db.log("error","update_failed",str(exc),slug)
                    if self.db.one("SELECT slug FROM apps WHERE slug=?",(slug,)):
                        self.db.run("UPDATE apps SET last_error=?,status=CASE WHEN active_version IS NULL THEN 'error' ELSE 'ready' END WHERE slug=?",(str(exc)[:500],slug))
            with self.state_lock:
                self.last_check_failed = bool(errors) or catalog_error is not None
                self.last_result=f"{updates} updates; {len(errors)} errors"
                if catalog_error is not None:
                    self.last_result = "Catalog check failed: " + catalog_error + "; " + self.last_result
            self.db.log("info","check_completed",self.last_result)
            return catalog_error is None
        finally:
            next_check=time.time()+max(1,min(168,int(self.db.setting("update_interval_hours"))))*3600
            with self.state_lock:
                self.running=False
                self.progress=None
                self.next_check=next_check
            self.lock.release()

    def start(self):
        if self.thread: return
        def loop():
            # First run starts immediately, but never blocks HTTP server readiness.
            next_run=time.time()
            while not self.stop_event.is_set():
                now=time.time()
                if now>=next_run:
                    self.check()
                    next_run=self.next_check or now+21600
                if self.next_check is not None:
                    next_run = self.next_check
                self.stop_event.wait(min(15,max(0.5,next_run-time.time())))
        self.thread=threading.Thread(target=loop,name="craft-update-manager",daemon=True)
        self.thread.start()

    def trigger(self):
        with self.schedule_lock:
            if self.running or self.scheduled or self.stop_event.is_set(): return False
            self.scheduled = True
            def run():
                try:
                    self.check()
                finally:
                    with self.schedule_lock:
                        self.scheduled = False
            self.manual_thread = threading.Thread(target=run,name="craft-manual-update",daemon=True)
            self.manual_thread.start()
            return True

    def stop(self):
        self.stop_event.set()
        # Wait before the server closes SQLite; in-flight requests use timeouts.
        for worker in (self.thread, self.manual_thread):
            if worker and worker is not threading.current_thread(): worker.join()


def hmac_compare(a: str,b: str) -> bool:
    import hmac
    return hmac.compare_digest(a,b)
