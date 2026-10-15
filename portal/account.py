"""Self-service account security. Portal session credentials never leave the server."""
from __future__ import annotations

import base64
import secrets
import time
from urllib.parse import quote, urlencode

from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth import PH, consume_factor, digest, matching_counter


class CurrentPassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=1024)


class FactorPassword(CurrentPassword):
    otp: str = Field(default="", max_length=80)


class ChangePassword(FactorPassword):
    new_password: str = Field(min_length=12, max_length=1024)


class FactorCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    otp: str = Field(min_length=1, max_length=80)


def _live_user(con, session, expected_hash=None):
    row = con.execute("""SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id
        WHERE u.id=? AND u.enabled=1 AND s.token_hash=? AND s.kind='portal' AND s.expires_at>?""",
        (session["user_id"], session["token_hash"], time.time())).fetchone()
    if not row:
        raise HTTPException(401, "Please log in")
    if expected_hash is not None and row["password_hash"] != expected_hash:
        raise HTTPException(409, "Account changed; retry")
    return row


def _revoke_other_sessions(con, session):
    # Remove both portal sessions and every child app session/ticket belonging to them.
    con.execute("DELETE FROM launch_tickets WHERE user_id=? AND parent_hash<>?", (session["user_id"], session["token_hash"]))
    con.execute("DELETE FROM account_mfa_pending WHERE user_id=? AND parent_hash<>?", (session["user_id"], session["token_hash"]))
    con.execute("""DELETE FROM sessions WHERE user_id=? AND token_hash<>?
        AND (kind='portal' OR parent_hash IS NULL OR parent_hash<>?)""",
        (session["user_id"], session["token_hash"], session["token_hash"]))


def register_account_routes(app, cfg, db, auth, session, changing, check_login_limit):
    def verified_password(request, s, password):
        check_login_limit(request, s["username"])
        row = db.one("SELECT * FROM users WHERE id=? AND enabled=1", (s["user_id"],))
        try:
            valid = row and PH.verify(row["password_hash"], password)
        except (VerifyMismatchError, VerificationError):
            valid = False
        if not valid:
            raise HTTPException(400, "Incorrect password or verification code")
        return row["password_hash"]

    @app.get("/api/account")
    def account(s: dict = Depends(session)):
        with db.tx() as con:
            user = _live_user(con, s)
            sessions = con.execute("""SELECT display_id,device_label,created_at,expires_at,token_hash
                FROM sessions WHERE user_id=? AND kind='portal' AND expires_at>? ORDER BY created_at DESC""",
                (s["user_id"], time.time())).fetchall()
            remaining = con.execute("SELECT COUNT(*) FROM account_recovery_codes WHERE user_id=?", (s["user_id"],)).fetchone()[0]
            return {"username": user["username"], "mfa_enabled": bool(user["mfa_secret"]),
                    "recovery_codes_remaining": remaining,
                    "sessions": [{"id": row["display_id"], "device": row["device_label"],
                                  "created_at": row["created_at"], "expires_at": row["expires_at"],
                                  "current": row["token_hash"] == s["token_hash"]} for row in sessions]}

    @app.post("/api/account/password")
    def password(request: Request, payload: ChangePassword, s: dict = Depends(session)):
        changing(request, s)
        expected = verified_password(request, s, payload.current_password)
        new_hash = PH.hash(payload.new_password)
        with db.tx() as con:
            user = _live_user(con, s, expected)
            if not consume_factor(con, user, payload.otp):
                raise HTTPException(400, "Incorrect password or verification code")
            con.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, s["user_id"]))
            con.execute("DELETE FROM account_mfa_pending WHERE user_id=?", (s["user_id"],))
            _revoke_other_sessions(con, s)
        db.log("info", "account_password_changed", s["username"])
        return {"ok": True}

    @app.delete("/api/account/sessions/others")
    def revoke_others(request: Request, s: dict = Depends(session)):
        changing(request, s)
        with db.tx() as con:
            _live_user(con, s)
            _revoke_other_sessions(con, s)
        return {"ok": True}

    @app.delete("/api/account/sessions/{display_id}")
    def revoke_session(display_id: str, request: Request, s: dict = Depends(session)):
        changing(request, s)
        with db.tx() as con:
            _live_user(con, s)
            target = con.execute("SELECT token_hash FROM sessions WHERE display_id=? AND user_id=? AND kind='portal'",
                                 (display_id, s["user_id"])).fetchone()
            if not target:
                raise HTTPException(404, "Session not found")
            token_hash = target["token_hash"]
            con.execute("DELETE FROM sessions WHERE token_hash=? OR parent_hash=?", (token_hash, token_hash))
            con.execute("DELETE FROM launch_tickets WHERE parent_hash=?", (token_hash,))
            con.execute("DELETE FROM account_mfa_pending WHERE parent_hash=?", (token_hash,))
        return {"ok": True, "current": token_hash == s["token_hash"]}

    @app.post("/api/account/mfa/enroll")
    def enroll(request: Request, payload: CurrentPassword, s: dict = Depends(session)):
        changing(request, s)
        expected = verified_password(request, s, payload.current_password)
        secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii")
        with db.tx() as con:
            user = _live_user(con, s, expected)
            if user["mfa_secret"]:
                raise HTTPException(409, "Two-step verification is already enabled")
            con.execute("""INSERT INTO account_mfa_pending(user_id,secret,parent_hash,expires_at) VALUES(?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET secret=excluded.secret,parent_hash=excluded.parent_hash,expires_at=excluded.expires_at""",
                (s["user_id"], secret, s["token_hash"], time.time() + 600))
        label = quote("Craft Portal:" + s["username"], safe="")
        uri = "otpauth://totp/" + label + "?" + urlencode({"secret": secret, "issuer": "Craft Portal", "algorithm": "SHA1", "digits": 6, "period": 30})
        return {"secret": secret, "otpauth_uri": uri}

    @app.post("/api/account/mfa/confirm")
    def confirm(request: Request, payload: FactorCode, s: dict = Depends(session)):
        changing(request, s)
        check_login_limit(request, s["username"])
        with db.tx() as con:
            user = _live_user(con, s)
            pending = con.execute("SELECT * FROM account_mfa_pending WHERE user_id=? AND parent_hash=? AND expires_at>?",
                                  (s["user_id"], s["token_hash"], time.time())).fetchone()
            counter = matching_counter(pending["secret"], payload.otp) if pending else None
            if user["mfa_secret"] or counter is None:
                raise HTTPException(400, "Incorrect or expired verification code")
            con.execute("UPDATE users SET mfa_secret=?,mfa_last_counter=? WHERE id=?", (pending["secret"], counter, s["user_id"]))
            con.execute("DELETE FROM account_mfa_pending WHERE user_id=?", (s["user_id"],))
            con.execute("DELETE FROM account_recovery_codes WHERE user_id=?", (s["user_id"],))
            codes = [secrets.token_hex(10) for _ in range(10)]
            con.executemany("INSERT INTO account_recovery_codes(user_id,code_hash) VALUES(?,?)", [(s["user_id"], digest(code)) for code in codes])
            _revoke_other_sessions(con, s)
        db.log("info", "account_mfa_enabled", s["username"])
        return {"recovery_codes": ["-".join(code[i:i+4] for i in range(0, 20, 4)) for code in codes]}

    @app.delete("/api/account/mfa")
    def disable(request: Request, payload: FactorPassword, s: dict = Depends(session)):
        changing(request, s)
        expected = verified_password(request, s, payload.current_password)
        with db.tx() as con:
            user = _live_user(con, s, expected)
            if not user["mfa_secret"] or not consume_factor(con, user, payload.otp):
                raise HTTPException(400, "Incorrect password or verification code")
            con.execute("UPDATE users SET mfa_secret=NULL,mfa_last_counter=-1 WHERE id=?", (s["user_id"],))
            con.execute("DELETE FROM account_recovery_codes WHERE user_id=?", (s["user_id"],))
            con.execute("DELETE FROM account_mfa_pending WHERE user_id=?", (s["user_id"],))
            _revoke_other_sessions(con, s)
        db.log("info", "account_mfa_disabled", s["username"])
        return {"ok": True}
