"""Argon2id authentication, opaque sessions and short-lived one-time app tickets."""
from __future__ import annotations

import hashlib
import hmac
import base64
import re
import secrets
import struct
import time

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError, VerificationError

from .database import Database

PH = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16, type=Type.ID)
USERNAME = re.compile(r"^[a-zA-Z0-9_.-]{3,48}$")
PORTAL_COOKIE = "craft_portal_session"
APP_COOKIE = "craft_app_session"


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def device_name(user_agent: str) -> str:
    """Keep a useful coarse label, never the identifying raw user-agent or IP."""
    ua = user_agent[:1024].lower()
    browser = next((name for marker, name in (("edg/", "Edge"), ("firefox/", "Firefox"),
                    ("chrome/", "Chrome"), ("safari/", "Safari")) if marker in ua), "Browser")
    system = next((name for marker, name in (("android", "Android"), ("iphone", "iOS"),
                   ("ipad", "iPadOS"), ("windows", "Windows"), ("macintosh", "macOS"),
                   ("linux", "Linux")) if marker in ua), "unknown device")
    return f"{browser} · {system}"


def totp_code(secret: str, counter: int) -> str:
    key = base64.b32decode(secret, casefold=True)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 15
    return f"{(int.from_bytes(mac[offset:offset+4], 'big') & 0x7fffffff) % 1000000:06d}"


def matching_counter(secret: str, code: str, last: int = -1, now: float | None = None) -> int | None:
    if not re.fullmatch(r"\d{6}", code, re.ASCII):
        return None
    current = int((time.time() if now is None else now) // 30)
    for counter in (current, current - 1, current + 1):
        if counter > last and hmac.compare_digest(totp_code(secret, counter), code):
            return counter
    return None


def consume_factor(con, user, code: str) -> bool:
    """Called under the same write transaction as the protected operation."""
    if not user["mfa_secret"]:
        return True
    counter = matching_counter(user["mfa_secret"], code, user["mfa_last_counter"])
    if counter is not None:
        con.execute("UPDATE users SET mfa_last_counter=? WHERE id=?", (counter, user["id"]))
        return True
    normalized = code.replace("-", "").replace(" ", "").lower()
    if not re.fullmatch(r"[0-9a-f]{20}", normalized):
        return False
    return con.execute("DELETE FROM account_recovery_codes WHERE user_id=? AND code_hash=?",
                       (user["id"], digest(normalized))).rowcount == 1


class Auth:
    def __init__(self, db: Database):
        self.db = db
        self.setup_code = secrets.token_urlsafe(24)
        self.setup_hash = digest(self.setup_code)
        self.csrf_secret = secrets.token_bytes(32)
        self.dummy_hash = PH.hash("dummy-password-for-timing")

    def setup_required(self) -> bool:
        return not self.db.one("SELECT id FROM users LIMIT 1")

    def create_user(self, username: str, password: str, role: str = "user") -> int:
        if not USERNAME.fullmatch(username) or len(password) < 12 or len(password) > 1024:
            raise ValueError("Username 3-48 letters/numbers/._-; password 12-1024 characters")
        if role not in {"admin","user"}:
            raise ValueError("Invalid role")
        hashed = PH.hash(password)
        with self.db.tx() as con:
            cursor = con.execute("INSERT INTO users(username,password_hash,role,public_id,created_at) VALUES(?,?,?,?,?)", (username,hashed,role,secrets.token_hex(6),time.time()))
            return cursor.lastrowid

    def setup(self, code: str, username: str, password: str) -> int:
        if not hmac.compare_digest(digest(code), self.setup_hash):
            raise ValueError("Invalid setup code")
        if not USERNAME.fullmatch(username) or not 12 <= len(password) <= 1024:
            raise ValueError("Username 3-48 letters/numbers/._-; password 12-1024 characters")
        hashed = PH.hash(password)
        with self.db.tx() as con:
            if con.execute("SELECT id FROM users LIMIT 1").fetchone():
                raise ValueError("Already configured")
            row = con.execute("INSERT INTO users(username,password_hash,role,public_id,created_at) VALUES(?,?,?,?,?)",
                              (username,hashed,"admin",secrets.token_hex(6),time.time()))
            user_id = row.lastrowid
        self.setup_hash = digest(secrets.token_urlsafe(32))
        self.setup_code = ""
        return user_id

    def signin(self, username: str, password: str, otp: str = "", device_label: str = "") -> tuple[str, dict] | None:
        user = self.db.one("SELECT * FROM users WHERE username=? AND enabled=1", (username,))
        if not user:
            # Equalize work for unknown usernames.
            try:
                PH.verify(self.dummy_hash, password)
            except (VerifyMismatchError, VerificationError):
                pass
            return None
        try:
            if not PH.verify(user["password_hash"], password):
                return None
        except (VerifyMismatchError, VerificationError):
            return None
        refreshed_hash = PH.hash(password) if PH.check_needs_rehash(user["password_hash"]) else None
        with self.db.tx() as con:
            current = con.execute("SELECT * FROM users WHERE id=? AND enabled=1", (user["id"],)).fetchone()
            if (not current or current["password_hash"] != user["password_hash"]
                    or current["mfa_secret"] != user["mfa_secret"] or not consume_factor(con, current, otp)):
                return None
            if refreshed_hash:
                con.execute("UPDATE users SET password_hash=? WHERE id=?", (refreshed_hash,user["id"]))
            return self._insert_session(con, user["id"], "portal", device_label=device_label), user

    def new_session(self, user_id: int, kind: str, scope: str = "", parent_hash: str | None = None, device_label: str = ""):
        with self.db.tx() as con:
            return self._insert_session(con, user_id, kind, scope, parent_hash, device_label)

    def _insert_session(self, con, user_id: int, kind: str, scope: str = "", parent_hash: str | None = None, device_label: str = ""):
        token = secrets.token_urlsafe(36)
        now = time.time()
        ttl = 60*60*12 if kind == "portal" else 60*60*8
        con.execute("INSERT INTO sessions(token_hash,user_id,kind,scope,parent_hash,expires_at,created_at,display_id,device_label) VALUES(?,?,?,?,?,?,?,?,?)", (digest(token),user_id,kind,scope,parent_hash,now+ttl,now,secrets.token_urlsafe(18),device_name(device_label)))
        return token

    def get_session(self, token: str | None, kind: str, scope: str = "") -> dict | None:
        if not token:
            return None
        return self.db.one("""SELECT s.*,u.username,u.role,u.public_id,u.enabled
            FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.kind=? AND s.scope=? AND s.expires_at>? AND u.enabled=1
            AND (s.kind='portal' OR EXISTS (
                SELECT 1 FROM sessions parent WHERE parent.token_hash=s.parent_hash
                AND parent.kind='portal' AND parent.user_id=s.user_id AND parent.expires_at>?
            ))""", (digest(token),kind,scope,time.time(),time.time()))

    def csrf(self, session: dict) -> str:
        return hmac.new(self.csrf_secret, session["token_hash"].encode("ascii"), hashlib.sha256).hexdigest()

    def revoke(self, token_hash: str):
        with self.db.tx() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=? OR parent_hash=?", (token_hash, token_hash))
            con.execute("DELETE FROM launch_tickets WHERE parent_hash=?", (token_hash,))
            con.execute("DELETE FROM account_mfa_pending WHERE parent_hash=?", (token_hash,))

    def new_ticket(self, session: dict, slug: str, *, require_active: bool = False) -> str | None:
        token = secrets.token_urlsafe(32)
        with self.db.tx() as con:
            if require_active:
                active=con.execute("SELECT 1 FROM apps WHERE slug=? AND active_version IS NOT NULL AND disabled=0",(slug,)).fetchone()
                parent=con.execute("""SELECT 1 FROM sessions s JOIN users u ON u.id=s.user_id
                    WHERE s.token_hash=? AND s.user_id=? AND s.kind='portal' AND s.expires_at>? AND u.enabled=1""",
                    (session['token_hash'],session['user_id'],time.time())).fetchone()
                if not active or not parent:
                    return None
            con.execute("INSERT INTO launch_tickets(ticket_hash,user_id,slug,parent_hash,expires_at) VALUES(?,?,?,?,?)", (digest(token),session["user_id"],slug,session["token_hash"],time.time()+45))
        return token

    def redeem_ticket(self, ticket: str, slug: str) -> str | None:
        with self.db.tx() as con:
            row = con.execute("""SELECT t.*,u.enabled FROM launch_tickets t JOIN users u ON u.id=t.user_id
                JOIN sessions s ON s.token_hash=t.parent_hash
                WHERE t.ticket_hash=? AND t.slug=? AND t.expires_at>? AND s.expires_at>?
                AND s.kind='portal' AND s.user_id=t.user_id""", (digest(ticket),slug,time.time(),time.time())).fetchone()
            if row is None:
                return None
            con.execute("DELETE FROM launch_tickets WHERE ticket_hash=?", (digest(ticket),))
            if not row["enabled"]:
                return None
            return self._insert_session(con, row["user_id"], "app", slug, row["parent_hash"])
