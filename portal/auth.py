"""Argon2id authentication, opaque sessions and short-lived one-time app tickets."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
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

    def signin(self, username: str, password: str) -> tuple[str, dict] | None:
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
        if PH.check_needs_rehash(user["password_hash"]):
            self.db.run("UPDATE users SET password_hash=? WHERE id=?", (PH.hash(password),user["id"]))
        return self.new_session(user["id"], "portal"), user

    def new_session(self, user_id: int, kind: str, scope: str = "", parent_hash: str | None = None):
        token = secrets.token_urlsafe(36)
        now = time.time()
        ttl = 60*60*12 if kind == "portal" else 60*60*8
        self.db.run("INSERT INTO sessions(token_hash,user_id,kind,scope,parent_hash,expires_at,created_at) VALUES(?,?,?,?,?,?,?)", (digest(token),user_id,kind,scope,parent_hash,now+ttl,now))
        return token

    def get_session(self, token: str | None, kind: str, scope: str = "") -> dict | None:
        if not token:
            return None
        return self.db.one("""SELECT s.*,u.username,u.role,u.public_id,u.enabled
            FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.kind=? AND s.scope=? AND s.expires_at>? AND u.enabled=1""", (digest(token),kind,scope,time.time()))

    def csrf(self, session: dict) -> str:
        return hmac.new(self.csrf_secret, session["token_hash"].encode("ascii"), hashlib.sha256).hexdigest()

    def revoke(self, token_hash: str):
        with self.db.tx() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=? OR parent_hash=?", (token_hash, token_hash))
            con.execute("DELETE FROM launch_tickets WHERE parent_hash=?", (token_hash,))

    def new_ticket(self, session: dict, slug: str) -> str:
        token = secrets.token_urlsafe(32)
        self.db.run("INSERT INTO launch_tickets(ticket_hash,user_id,slug,parent_hash,expires_at) VALUES(?,?,?,?,?)", (digest(token),session["user_id"],slug,session["token_hash"],time.time()+45))
        return token

    def redeem_ticket(self, ticket: str, slug: str) -> str | None:
        with self.db.tx() as con:
            row = con.execute("""SELECT t.*,u.enabled FROM launch_tickets t JOIN users u ON u.id=t.user_id
                JOIN sessions s ON s.token_hash=t.parent_hash
                WHERE t.ticket_hash=? AND t.slug=? AND t.expires_at>? AND s.expires_at>?""", (digest(ticket),slug,time.time(),time.time())).fetchone()
            if row is None:
                return None
            con.execute("DELETE FROM launch_tickets WHERE ticket_hash=?", (digest(ticket),))
        if not row["enabled"]:
            return None
        return self.new_session(row["user_id"], "app", slug, row["parent_hash"])
