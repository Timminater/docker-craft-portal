"""FastAPI HTTP portal with authenticated, versioned WASM routes."""
from __future__ import annotations

from contextlib import asynccontextmanager
from collections import defaultdict, deque
import threading
from datetime import datetime, timezone
import html
import json
import logging
import mimetypes
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.base import BaseHTTPMiddleware

from .artwork import Artwork, KINDS
from .sources import app_owner, repository, valid_repository
from .auth import APP_COOKIE, PORTAL_COOKIE, Auth, digest
from .account import register_account_routes
from .config import Config
from .database import Database
from .updater import Updater, SLUG, TAG
from .updates import PortalUpdates

LOG = logging.getLogger(__name__)
mimetypes.add_type("application/wasm",".wasm")
mimetypes.add_type("text/javascript",".mjs")
mimetypes.add_type("application/manifest+json",".webmanifest")
STATIC = Path(__file__).parent / "static"


class RequestBodyLimit:
    """Bound actual request bytes even when Content-Length is absent or false."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await self.app(scope, receive, send)
        messages, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > 65536:
                response = JSONResponse(status_code=413, content={"detail": "Request body too large"},
                                        headers={"Cache-Control": "no-store"})
                return await response(scope, receive, send)
            messages.append(message)
            if not message.get("more_body", False):
                break
        pending = iter(messages)
        async def replay():
            return next(pending, None) or await receive()
        return await self.app(scope, replay, send)


class Credentials(BaseModel):
    username: str = Field(min_length=3,max_length=48)
    password: str = Field(min_length=12,max_length=1024)


class FirstSetup(Credentials):
    code: str


class SettingsInput(BaseModel):
    update_interval_hours: int = Field(ge=1,le=168)
    auto_install_versions: bool
    auto_discover_apps: bool
    keep_previous_versions: int = Field(ge=0,le=10)


class UserInput(Credentials):
    role: str = "user"


class ToggleInput(BaseModel):
    disabled: bool | None = None
    auto_update: bool | None = None


class RollbackInput(BaseModel):
    version: str


class TicketInput(BaseModel):
    ticket: str
    slug: str


class PreferencesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_order: list[str] | None = Field(default=None, max_length=100)
    hidden_dock_apps: list[str] | None = Field(default=None, max_length=100)

    @field_validator("app_order", "hidden_dock_apps")
    @classmethod
    def valid_app_order(cls, value: list[str] | None) -> list[str]:
        if value is None:
            raise ValueError("Application identifiers must be a list")
        if any(not SLUG.fullmatch(slug) for slug in value):
            raise ValueError("Invalid application identifier")
        if len(set(value)) != len(value):
            raise ValueError("Duplicate application identifiers")
        return value


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=48)
    password: str = Field(min_length=1, max_length=1024)
    otp: str = Field(default="", max_length=80)


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner: str = Field(min_length=1, max_length=39)
    repository: str = Field(min_length=1, max_length=100)


def same_origin(request: Request, cfg: Config):
    origin = request.headers.get("origin")
    expected = cfg.public_url
    if origin is not None and origin.rstrip("/") != expected:
        raise HTTPException(403,"Invalid request origin")
    if request.headers.get("X-Craft-Client") != "portal-v1":
        raise HTTPException(403,"Missing first-party request header")


def format_user(s: dict) -> dict:
    return {"id":s["user_id"],"username":s["username"],"role":s["role"],"public_id":s["public_id"]}


def create_app(config: Config | None = None, start_updater: bool | None = None) -> FastAPI:
    cfg = config or Config.from_env()
    cfg.data_dir.mkdir(parents=True,exist_ok=True)
    db = Database(cfg.data_dir/"database"/"portal.sqlite")
    auth = Auth(db)
    updater = Updater(cfg,db)
    portal_updates = PortalUpdates(updater)
    artwork = Artwork(cfg.data_dir, STATIC, network=cfg.auto_start_updates)
    if start_updater is None: start_updater=cfg.auto_start_updates

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if auth.setup_required():
            # This code is intentionally emitted only to private container logs.
            LOG.warning("FIRST-START ADMIN SETUP CODE: %s",auth.setup_code)
        db.cleanup_tokens()
        if start_updater:
            updater.start()
        yield
        updater.stop()
        db.close()

    app=FastAPI(title="Craft Portal",docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.add_middleware(RequestBodyLimit)
    # Bound authentication attempts per remote peer and username without trusting spoofable X-Forwarded-For.
    login_attempts = defaultdict(deque)
    login_lock = threading.Lock()

    def check_login_limit(request: Request, username: str):
        keys = ("ip:" + (request.client.host if request.client else "unknown"), "user:" + username.lower())
        now = time.monotonic()
        with login_lock:
            for key in keys:
                q = login_attempts[key]
                while q and now-q[0] > 60: q.popleft()
                if len(q) >= (20 if key.startswith("ip:") else 8):
                    raise HTTPException(429, "Too many login attempts; retry later")
            for key in keys: login_attempts[key].append(now)
            # Prune the bounded in-memory map periodically to avoid growth from random usernames.
            if len(login_attempts)>2000:
                for key in list(login_attempts):
                    q = login_attempts[key]
                    if not q or now-q[-1]>60: del login_attempts[key]

    app.state.cfg,app.state.db,app.state.auth,app.state.updater = cfg,db,auth,updater
    app.state.artwork = artwork
    single_host = urlparse(cfg.single_app_url).netloc.lower() if cfg.single_app_url else ""
    app_host = re.compile(rf"^(?P<slug>[a-z][a-z0-9]{{1,29}}craft)--(?P<publicid>[0-9a-f]{{12}})\.{re.escape(cfg.apps_domain)}$",re.I) if cfg.isolated_app_origins else None

    def host_type(request: Request):
        host = request.headers.get("host","").lower().rstrip(".")
        if host == cfg.portal_host:
            return ("portal",None,None)
        if single_host and host == single_host and not cfg.isolated_app_origins:
            return ("single_app",None,None)
        if app_host:
            m=app_host.fullmatch(host)
            if m:
                return ("app",m.group("slug"),m.group("publicid"))
        return ("invalid",None,None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        kind,_,_ = host_type(request)
        if kind == "invalid" and request.url.path != "/healthz":
            return JSONResponse(status_code=421,content={"detail":"Unrecognized hostname"})
        if request.method in {"POST","PUT","PATCH","DELETE"}:
            try:
                if int(request.headers.get("content-length","0"))>65536:
                    return JSONResponse(status_code=413,content={"detail":"Request body too large"})
            except ValueError:
                return JSONResponse(status_code=400,content={"detail":"Invalid Content-Length"})
        response=await call_next(request)
        # Never let browser/proxy caches bypass a later authorization check.
        if request.url.path.startswith(("/api/", "/a/", "/v/")) or request.url.path in {"/_redeem", "/_app_info", "/_storage", "/_storage.js"}:
            response.headers["Cache-Control"]="no-store"
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["Permissions-Policy"]="camera=(), geolocation=()"
        if kind=="portal":
            frame_source = f"https://*.{cfg.apps_domain}" if cfg.isolated_app_origins else (cfg.single_app_url or "'none'")
            response.headers["Content-Security-Policy"]=f"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; frame-src {frame_source}"
            response.headers["X-Frame-Options"]="DENY"
            response.headers["Cross-Origin-Opener-Policy"]="same-origin"
            response.headers["Cross-Origin-Embedder-Policy"]="require-corp"
        elif kind in {"app", "single_app"}:
            response.headers["Content-Security-Policy"] = f"frame-ancestors {cfg.public_url}"
            # Embedded documents and their workers inherit the isolated workspace
            # contract. Preserve standalone documents for non-isolated apps.
            if request.headers.get("sec-fetch-dest") in {"iframe", "worker", "sharedworker", "serviceworker"}:
                response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
            response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
        return response

    def portal_only(request: Request):
        if host_type(request)[0] != "portal":
            raise HTTPException(404)

    def cookie_name(name: str) -> str:
        # Browsers reject __Host- cookies with Domain or without Secure/path=/.
        # An upstream app on a sibling origin therefore cannot shadow portal auth.
        return f"__Host-{name}" if cfg.secure_cookie else name

    def read_cookie(request: Request, name: str):
        return request.cookies.get(cookie_name(name))

    def session(request: Request):
        portal_only(request)
        s=auth.get_session(read_cookie(request, PORTAL_COOKIE),"portal")
        if not s: raise HTTPException(401,"Please log in")
        return s

    def admin_session(request: Request):
        s=session(request)
        if s["role"]!="admin": raise HTTPException(403,"Administrator required")
        return s

    def changing(request: Request, s: dict):
        same_origin(request,cfg)
        actual=request.headers.get("x-craft-csrf","")
        if not secrets.compare_digest(actual,auth.csrf(s)):
            raise HTTPException(403,"CSRF validation failed")

    def cookie(response: Response, name: str, token: str, ttl: int):
        response.set_cookie(cookie_name(name),token,max_age=ttl,path="/",httponly=True,secure=cfg.secure_cookie,samesite="lax")

    register_account_routes(app, cfg, db, auth, session, changing, check_login_limit)
    app.state.portal_updates = portal_updates

    @app.get("/api/portal/status")
    def portal_status(s: dict = Depends(session)):
        return portal_updates.status(admin=s["role"] == "admin")

    @app.post("/api/admin/portal/check")
    def portal_update_check(request: Request, s: dict = Depends(admin_session)):
        changing(request, s)
        return portal_updates.check(admin=True)

    @app.get("/healthz")
    async def health():
        return {"status":"ok"}

    @app.get("/")
    async def index(request: Request):
        kind,slug,_ = host_type(request)
        if kind in {"app", "single_app"}:
            bridge = (STATIC/"bridge.html").read_text().replace("</head>", f'<meta name="craft-portal-origin" content="{html.escape(cfg.public_url, quote=True)}"></head>')
            return HTMLResponse(bridge,headers={"Cache-Control":"no-store"})
        if kind!="portal": raise HTTPException(404)
        return FileResponse(STATIC/"index.html",headers={"Cache-Control":"no-store"})

    @app.get("/_asset/{filename}")
    async def portal_asset(filename: str,request:Request):
        portal_only(request)
        if filename not in {"app.css","app.js"}:
            raise HTTPException(404)
        return FileResponse(STATIC/filename,headers={"Cache-Control":"no-cache"})

    @app.get("/static/artcraft/{slug}/{kind}.webp")
    def app_artwork(slug: str, kind: str, request: Request, s: dict = Depends(session)):
        if not SLUG.fullmatch(slug) or kind not in KINDS:
            raise HTTPException(404)
        record = db.one("SELECT disabled FROM apps WHERE slug=?", (slug,))
        if not record or (record["disabled"] and s["role"] != "admin"):
            raise HTTPException(404)
        data, media_type = artwork.get(slug, kind)
        return Response(data, media_type=media_type, headers={"Cache-Control": "private, no-store"})

    @app.get("/_i18n.js")
    async def i18n_js(request:Request):
        if host_type(request)[0] not in {"portal", "app", "single_app"}: raise HTTPException(404)
        return FileResponse(STATIC/"i18n.js", headers={"Cache-Control":"no-cache"})

    @app.get("/_bridge.css")
    async def bridge_css(request:Request):
        if host_type(request)[0] not in {"app", "single_app"}: raise HTTPException(404)
        return FileResponse(STATIC/"app.css", headers={"Cache-Control":"no-cache"})

    @app.get("/_bridge.js")
    async def bridge_js(request:Request):
        if host_type(request)[0] not in {"app", "single_app"}: raise HTTPException(404)
        return FileResponse(STATIC/"bridge.js",headers={"Cache-Control":"no-store"})

    @app.post("/_redeem")
    async def redeem(request:Request,payload:TicketInput):
        kind,host_slug,public_id=host_type(request)
        if kind not in {"app", "single_app"}: raise HTTPException(404)
        slug = host_slug if kind == "app" else payload.slug
        if not slug or not SLUG.fullmatch(slug) or (kind=="app" and payload.slug!=slug):
            raise HTTPException(403)
        # Same-origin JS must send this header: cross-site forms cannot use it.
        if request.headers.get("x-craft-client")!="app-bridge-v1":
            raise HTTPException(403)
        target=db.one("SELECT * FROM users WHERE public_id=? AND enabled=1",(public_id,)) if kind=="app" else None
        row=db.one("SELECT user_id FROM launch_tickets WHERE ticket_hash=?",(digest(payload.ticket),))
        if not row or (kind=="app" and (not target or row["user_id"]!=target["id"])):
            raise HTTPException(403,"Ticket invalid or expired")
        token=auth.redeem_ticket(payload.ticket,slug)
        if not token: raise HTTPException(403,"Ticket invalid or expired")
        response=JSONResponse({"ok":True})
        cookie(response, APP_COOKIE if kind=="app" else f"{APP_COOKIE}_{slug}", token, 8*3600)
        response.headers["Cache-Control"]="no-store"
        return response

    def app_info_sync(request: Request, slug: str):
        kind, host_slug, public_id = host_type(request)
        if kind not in {"app", "single_app"} or not SLUG.fullmatch(slug): raise HTTPException(404)
        if kind == "app" and host_slug != slug: raise HTTPException(403)
        app_cookie_name = APP_COOKIE if kind=="app" else f"{APP_COOKIE}_{slug}"
        sess = auth.get_session(read_cookie(request, app_cookie_name), "app", slug)
        if not sess or (kind == "app" and sess["public_id"] != public_id): raise HTTPException(401)
        row = db.one("SELECT active_version,disabled FROM apps WHERE slug=?", (slug,))
        if not row or not row["active_version"] or row["disabled"]: raise HTTPException(404)
        path = f"/v/{row['active_version']}/" if kind == "app" else f"/a/{slug}/v/{row['active_version']}/"
        return JSONResponse({"version": row["active_version"], "path": path}, headers={"Cache-Control":"no-store"})

    @app.get("/_app_info")
    async def app_info(request: Request, slug: str):
        return app_info_sync(request, slug)

    @app.get("/api/bootstrap")
    async def bootstrap(request: Request):
        portal_only(request)
        s=auth.get_session(read_cookie(request, PORTAL_COOKIE),"portal")
        return {"setup_required":auth.setup_required(),"user":format_user(s) if s else None,"csrf":auth.csrf(s) if s else None,"multi_user":cfg.multi_user,"app_origin_configured":cfg.app_origin_configured,"app_origin_mode":cfg.app_origin_mode,"app_origin":cfg.single_app_url or None}

    @app.get("/_storage")
    def storage_document(request: Request, slug: str):
        # Reuse the asset authorization boundary, including parent session,
        # account hostname and enabled application checks.
        app_info_sync(request, slug)
        page = (STATIC / "storage.html").read_text()
        meta = (f'<meta name="craft-portal-origin" content="{html.escape(cfg.public_url, quote=True)}">'
                f'<meta name="craft-app-slug" content="{html.escape(slug, quote=True)}">')
        return HTMLResponse(page.replace("</head>", meta + "</head>"), headers={"Cache-Control": "no-store"})

    @app.get("/_storage.js")
    def storage_script(request: Request):
        if host_type(request)[0] not in {"app", "single_app"}:
            raise HTTPException(404)
        return FileResponse(STATIC / "storage.js", headers={"Cache-Control": "no-store"})

    @app.get("/api/storage/origins")
    def storage_origins(s: dict = Depends(session)):
        grouped = {}
        if cfg.app_origin_configured:
            for record in db.all("SELECT slug,name FROM apps WHERE active_version IS NOT NULL AND disabled=0 ORDER BY name"):
                slug = record["slug"]
                origin = f"https://{slug}--{s['public_id']}.{cfg.apps_domain}" if cfg.isolated_app_origins else cfg.single_app_url
                group = grouped.setdefault(origin, {"origin": origin, "slug": slug, "apps": []})
                group["apps"].append(record)
        return {"mode": cfg.app_origin_mode, "origins": list(grouped.values())}

    @app.get("/api/preferences")
    def preferences(s: dict = Depends(session)):
        row = db.one("SELECT app_order,hidden_dock_apps FROM user_preferences WHERE user_id=?", (s["user_id"],))
        return {field: json.loads(row[field]) if row else [] for field in ("app_order", "hidden_dock_apps")}

    @app.put("/api/preferences")
    def save_preferences(request: Request, payload: PreferencesInput, s: dict = Depends(session)):
        changing(request, s)
        fields = payload.model_dump(exclude_unset=True)
        with db.tx() as con:
            for value in fields.values():
                if not value:
                    continue
                placeholders = ",".join("?" for _ in value)
                known = con.execute(f"SELECT slug FROM apps WHERE slug IN ({placeholders})", value).fetchall()
                if len(known) != len(value):
                    raise HTTPException(400, "Unknown application identifier")
            con.execute("INSERT OR IGNORE INTO user_preferences(user_id) VALUES(?)", (s["user_id"],))
            for field, value in fields.items():
                con.execute(f"UPDATE user_preferences SET {field}=? WHERE user_id=?", (json.dumps(value), s["user_id"]))
        return preferences(s)

    @app.post("/api/setup")
    def setup(request:Request,payload:FirstSetup):
        portal_only(request); same_origin(request,cfg)
        check_login_limit(request, "__first_setup__")
        try: user_id=auth.setup(payload.code,payload.username,payload.password)
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc
        token=auth.new_session(user_id,"portal",device_label=request.headers.get("user-agent", ""))
        response=JSONResponse({"ok":True})
        cookie(response,PORTAL_COOKIE,token,12*3600)
        db.log("info","admin_created",payload.username)
        return response

    # Login is protected by a first-party custom header to mitigate login CSRF.
    @app.post("/api/login")
    def login(request:Request,payload:LoginInput):
        portal_only(request); same_origin(request,cfg)
        if auth.setup_required(): raise HTTPException(409,"Complete administrator setup first")
        check_login_limit(request, payload.username)
        result=auth.signin(payload.username,payload.password,payload.otp,request.headers.get("user-agent", ""))
        if not result:
            # Deliberately generic error. A reverse proxy should also rate-limit /api/login.
            raise HTTPException(401,"Incorrect username, password or verification code")
        token,_user=result
        response=JSONResponse({"ok":True})
        cookie(response,PORTAL_COOKIE,token,12*3600)
        db.log("info","login",payload.username)
        return response

    @app.post("/api/logout")
    async def logout(request:Request,s:dict=Depends(session)):
        changing(request,s)
        auth.revoke(s["token_hash"])
        response=JSONResponse({"ok":True})
        response.delete_cookie(cookie_name(PORTAL_COOKIE),path="/",secure=cfg.secure_cookie,httponly=True,samesite="lax")
        return response

    @app.get("/api/apps")
    async def apps(request:Request,s:dict=Depends(session)):
        rows=db.all("SELECT slug,name,description,active_version,latest_version,status,last_error,disabled,auto_update FROM apps ORDER BY name")
        if s["role"]!="admin":
            rows=[r for r in rows if not r["disabled"]]
            for r in rows: r.pop("last_error",None)
        return {"apps":rows,"updated_at":updater.last_check}

    @app.get("/api/apps/{slug}/downloads")
    async def downloads(slug:str,request:Request,s:dict=Depends(session)):
        app_record=db.one("SELECT * FROM apps WHERE slug=?",(slug,))
        if not app_record or (app_record["disabled"] and s["role"]!="admin"):
            raise HTTPException(404)
        owner, repo = repository(db,slug,cfg.trusted_owner)
        return {"assets":db.all("SELECT name,url FROM release_assets WHERE slug=? ORDER BY name",(slug,)),"github":f"https://github.com/{owner}/{repo}/releases"}

    @app.post("/api/apps/{slug}/launch")
    async def launch(slug:str,request:Request,embedded:bool=False,s:dict=Depends(session)):
        changing(request,s)
        app_record=db.one("SELECT active_version,disabled FROM apps WHERE slug=?",(slug,))
        if not app_record or not app_record["active_version"] or app_record["disabled"]:
            raise HTTPException(404,"Application is not ready")
        if not cfg.app_origin_configured:
            raise HTTPException(409,"Configure a separate CRAFT_SINGLE_APP_URL or CRAFT_APPS_DOMAIN before launching apps")
        if cfg.isolated_app_origins:
            ticket=auth.new_ticket(s,slug)
            url=f"https://{slug}--{s['public_id']}.{cfg.apps_domain}/#ticket={ticket}&slug={slug}"
        else:
            ticket=auth.new_ticket(s,slug)
            url=f"{cfg.single_app_url}/#ticket={ticket}&slug={slug}"
        if embedded:
            url += "&embedded=1"
        return {"url":url,"origin":url.split("/#",1)[0],"slug":slug,"embedded":embedded}

    @app.post("/api/apps/{slug}/storage")
    async def storage_launch(slug: str, request: Request, s: dict = Depends(session)):
        result = await launch(slug, request, False, s)
        result["url"] += "&storage=1"
        return {field: result[field] for field in ("url", "origin", "slug")}

    @app.get("/api/admin/status")
    def status(request:Request,s:dict=Depends(admin_session)):
        settings=db.settings()
        rows=db.all("SELECT slug,active_version,status,last_error,latest_version,disabled,auto_update FROM apps ORDER BY slug")
        count=db.one("SELECT COUNT(*) as count FROM users")["count"]
        used=sum(f.stat().st_size for f in (cfg.data_dir/"apps").rglob("*") if f.is_file())
        return {"apps":rows,"count":len(rows),"users":count,"bytes":used,"running":updater.running,
                "last_check":updater.last_check,"next_check":updater.next_check,"last_result":updater.last_result,
                "settings":settings,"multi_user":cfg.multi_user,"sources": sources(s)['sources']}

    @app.get('/api/admin/sources')
    def sources(s: dict = Depends(admin_session)):
        rows = db.all('SELECT slug,name FROM apps ORDER BY name')
        return {'sources': [dict(row, owner=repository(db,row['slug'],cfg.trusted_owner)[0],
                                 repository=repository(db,row['slug'],cfg.trusted_owner)[1],
                                 custom=bool(db.one('SELECT slug FROM app_sources WHERE slug=?',(row['slug'],)))) for row in rows]}

    @app.put('/api/admin/sources/{slug}')
    def save_source(slug: str, request: Request, payload: SourceInput, s: dict = Depends(admin_session)):
        changing(request,s)
        if not SLUG.fullmatch(slug) or not valid_repository(payload.owner,payload.repository):
            raise HTTPException(400,'Invalid GitHub repository')
        with updater.lock:
            if not db.one('SELECT slug FROM apps WHERE slug=?',(slug,)):
                raise HTTPException(404)
            if repository(db,slug,cfg.trusted_owner) == (payload.owner,payload.repository):
                return {'ok': True}
            with db.tx() as con:
                if (payload.owner,payload.repository) == (app_owner(slug,cfg.trusted_owner),slug):
                    con.execute('DELETE FROM app_sources WHERE slug=?',(slug,))
                else:
                    con.execute('INSERT INTO app_sources(slug,owner,repository) VALUES(?,?,?) ON CONFLICT(slug) DO UPDATE SET owner=excluded.owner,repository=excluded.repository',(slug,payload.owner,payload.repository))
                con.execute('DELETE FROM release_assets WHERE slug=?',(slug,))
                con.execute("UPDATE apps SET latest_version=NULL,last_error='' WHERE slug=?",(slug,))
        db.log('warning','app_source_changed',f'{s["username"]}: {payload.owner}/{payload.repository}',slug)
        return {'ok': True}

    @app.put("/api/admin/settings")
    async def settings(request:Request,payload:SettingsInput,s:dict=Depends(admin_session)):
        changing(request,s)
        val={"update_interval_hours":str(payload.update_interval_hours),
             "auto_install_versions":str(payload.auto_install_versions).lower(),
             "auto_discover_apps":str(payload.auto_discover_apps).lower(),
             "keep_previous_versions":str(payload.keep_previous_versions)}
        with db.tx() as con:
            for k,v in val.items(): con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(k,v))
        db.log("info","settings_updated",json.dumps(val))
        # Recompute next scheduled check if interval changed.
        updater.next_check=time.time()+payload.update_interval_hours*3600
        return {"ok":True}

    @app.post("/api/admin/check")
    async def check_now(request:Request,s:dict=Depends(admin_session)):
        changing(request,s)
        if not updater.trigger(): raise HTTPException(409,"Update already in progress")
        return {"ok":True,"message":"Update check scheduled"}

    @app.get("/api/admin/events")
    async def events(request:Request,s:dict=Depends(admin_session)):
        return {"events":db.all("SELECT at,level,slug,action,detail FROM events ORDER BY id DESC LIMIT 120")}

    @app.get("/api/admin/apps/{slug}/versions")
    async def versions(slug:str,request:Request,s:dict=Depends(admin_session)):
        if not db.one("SELECT slug FROM apps WHERE slug=?",(slug,)): raise HTTPException(404)
        return {"versions":db.all("SELECT version,installed_at FROM versions WHERE slug=? ORDER BY installed_at DESC",(slug,))}

    @app.post("/api/admin/apps/{slug}/rollback")
    def rollback(slug:str,request:Request,payload:RollbackInput,s:dict=Depends(admin_session)):
        changing(request,s)
        try: updater.rollback(slug,payload.version)
        except Exception as exc: raise HTTPException(400,str(exc)) from exc
        return {"ok":True}

    @app.put("/api/admin/apps/{slug}")
    async def toggle(slug:str,request:Request,payload:ToggleInput,s:dict=Depends(admin_session)):
        changing(request,s)
        if not db.one("SELECT slug FROM apps WHERE slug=?",(slug,)): raise HTTPException(404)
        with db.tx() as con:
            if payload.disabled is not None: con.execute("UPDATE apps SET disabled=? WHERE slug=?",(int(payload.disabled),slug))
            if payload.auto_update is not None: con.execute("UPDATE apps SET auto_update=? WHERE slug=?",(int(payload.auto_update),slug))
        db.log("info","app_settings",f"disabled={payload.disabled} auto_update={payload.auto_update}",slug)
        return {"ok":True}

    @app.get("/api/admin/users")
    async def users(request:Request,s:dict=Depends(admin_session)):
        return {"users":db.all("SELECT id,username,role,public_id,enabled,created_at FROM users ORDER BY username")}

    @app.post("/api/admin/users")
    def create_user(request:Request,payload:UserInput,s:dict=Depends(admin_session)):
        changing(request,s)
        if not cfg.multi_user:
            raise HTTPException(400,"Additional users require isolated origins or explicit CRAFT_SHARED_APP_MULTI_USER opt-in")
        try: user_id=auth.create_user(payload.username,payload.password,payload.role)
        except Exception as exc:
            if "UNIQUE constraint" in str(exc): raise HTTPException(409,"Username already in use") from exc
            if isinstance(exc,ValueError): raise HTTPException(400,str(exc)) from exc
            raise
        db.log("info","user_created",payload.username)
        return {"id":user_id}

    @app.put("/api/admin/users/{user_id}/disable")
    async def disable_user(user_id:int,request:Request,s:dict=Depends(admin_session)):
        changing(request,s)
        if user_id == s["user_id"]: raise HTTPException(400,"Cannot disable your own account")
        target=db.one("SELECT role FROM users WHERE id=?",(user_id,))
        if not target: raise HTTPException(404)
        with db.tx() as con:
            con.execute("UPDATE users SET enabled=0 WHERE id=?",(user_id,))
            con.execute("DELETE FROM sessions WHERE user_id=?",(user_id,))
            con.execute("DELETE FROM launch_tickets WHERE user_id=?",(user_id,))
        db.log("warning","user_disabled",str(user_id))
        return {"ok":True}

    def serve_app_asset(request:Request,slug:str,version:str,asset:str,mode:str):
        if not SLUG.fullmatch(slug) or not TAG.fullmatch(version): raise HTTPException(404)
        kind,host_slug,public_id = host_type(request)
        if mode == "single":
            if cfg.isolated_app_origins or kind!="single_app": raise HTTPException(404)
            s=auth.get_session(read_cookie(request, f"{APP_COOKIE}_{slug}"),"app",slug)
            if not s: raise HTTPException(401,"Open this app from Craft Portal")
        else:
            if not cfg.isolated_app_origins or kind!="app" or host_slug!=slug: raise HTTPException(404)
            s=auth.get_session(read_cookie(request, APP_COOKIE),"app",slug)
            if not s or s["public_id"]!=public_id: raise HTTPException(401,"Open this app from Craft Portal")
        row=db.one("SELECT active_version,disabled FROM apps WHERE slug=?",(slug,))
        known=db.one("SELECT rel_path FROM versions WHERE slug=? AND version=?",(slug,version))
        if not row or row["disabled"] or not known: raise HTTPException(404)
        # Filesystem absolute path canonicalization defends even against symlinks in the volume.
        base=(cfg.data_dir/"apps"/slug/"versions"/version).resolve()
        file=(base/(asset or "index.html")).resolve()
        if not file.is_relative_to(base) or not file.is_file(): raise HTTPException(404)
        if slug == "solidcraft" and (asset == "sw.js" or request.headers.get("sec-fetch-dest") == "serviceworker"):
            raise HTTPException(404)
        headers={"Cache-Control":"no-store"}
        # Web GPU + selected media workflows require a secure origin (configured via reverse proxy).
        if slug in {"filmcraft","effectcraft","lightcraft","solidcraft"}:
            headers.update({"Cross-Origin-Opener-Policy":"same-origin", "Cross-Origin-Embedder-Policy":"require-corp", "Cross-Origin-Resource-Policy":"cross-origin"})
        return FileResponse(file,headers=headers)

    @app.get("/a/{slug}/v/{version}/")
    @app.get("/a/{slug}/v/{version}/{asset:path}")
    async def single_app(slug:str,version:str,request:Request,asset:str=""):
        return serve_app_asset(request,slug,version,asset,"single")

    @app.get("/v/{version}/")
    @app.get("/v/{version}/{asset:path}")
    async def multi_app(version:str,request:Request,asset:str=""):
        kind,slug,_=host_type(request)
        if kind!="app": raise HTTPException(404)
        return serve_app_asset(request,slug,version,asset,"multi")

    return app



