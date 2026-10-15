"""SQLite storage: no external database service, transactional upgrades."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

DEFAULT_SETTINGS = {
    "update_interval_hours": "6",
    "auto_install_versions": "true",
    "auto_discover_apps": "true",
    "keep_previous_versions": "2",
    "include_prereleases": "false",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('admin','user')),
 public_id TEXT NOT NULL UNIQUE,
 enabled INTEGER NOT NULL DEFAULT 1,
 created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 kind TEXT NOT NULL CHECK(kind IN ('portal','app')),
 scope TEXT NOT NULL DEFAULT '',
 parent_hash TEXT,
 expires_at REAL NOT NULL,
 created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS launch_tickets (
 ticket_hash TEXT PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 slug TEXT NOT NULL,
 parent_hash TEXT NOT NULL,
 expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS apps (
 slug TEXT PRIMARY KEY,
 name TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '',
 active_version TEXT,
 latest_version TEXT,
 status TEXT NOT NULL DEFAULT 'discovered',
 last_error TEXT NOT NULL DEFAULT '',
 disabled INTEGER NOT NULL DEFAULT 0,
 auto_update INTEGER NOT NULL DEFAULT 1,
 installed_at REAL,
 updated_at REAL
);
CREATE TABLE IF NOT EXISTS versions (
 slug TEXT NOT NULL REFERENCES apps(slug) ON DELETE CASCADE,
 version TEXT NOT NULL,
 rel_path TEXT NOT NULL,
 installed_at REAL NOT NULL,
 PRIMARY KEY (slug,version)
);
CREATE TABLE IF NOT EXISTS release_assets (
 slug TEXT NOT NULL REFERENCES apps(slug) ON DELETE CASCADE,
 name TEXT NOT NULL,
 url TEXT NOT NULL,
 PRIMARY KEY(slug,name)
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 at REAL NOT NULL,
 level TEXT NOT NULL,
 slug TEXT,
 action TEXT NOT NULL,
 detail TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.con = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA busy_timeout=5000")
        self.con.executescript(SCHEMA)
        with self.tx() as con:
            for key, value in DEFAULT_SETTINGS.items():
                con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key,value))

    @contextmanager
    def tx(self):
        with self.lock:
            self.con.execute("BEGIN IMMEDIATE")
            try:
                yield self.con
            except BaseException:
                self.con.execute("ROLLBACK")
                raise
            else:
                self.con.execute("COMMIT")

    def one(self, sql: str, args=()):
        with self.lock:
            item = self.con.execute(sql, args).fetchone()
            return dict(item) if item else None

    def all(self, sql: str, args=()):
        with self.lock:
            return [dict(row) for row in self.con.execute(sql,args)]

    def run(self, sql: str, args=()):
        with self.tx() as con:
            return con.execute(sql,args).rowcount

    def settings(self):
        return {row["key"]: row["value"] for row in self.all("SELECT key,value FROM settings")}

    def setting(self, key: str) -> str:
        value = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return value["value"] if value else DEFAULT_SETTINGS.get(key, "")

    def log(self, level: str, action: str, detail: str = "", slug: str | None = None):
        self.run("INSERT INTO events(at,level,slug,action,detail) VALUES(?,?,?,?,?)", (time.time(),level,slug,action,detail[:2000]))

    def cleanup_tokens(self):
        now = time.time()
        with self.tx() as con:
            con.execute("DELETE FROM sessions WHERE expires_at<?", (now,))
            con.execute("DELETE FROM launch_tickets WHERE expires_at<?", (now,))

    def close(self):
        with self.lock:
            self.con.close()
