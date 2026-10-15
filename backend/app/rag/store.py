"""Private SQLite metadata/session/identity store. No original PDFs are retained."""

import hashlib
import hmac
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import HTTPException

from app.rag.models import Principal


def normalized(value: str) -> str:
    return " ".join(value.casefold().split())


class Store:
    def __init__(self, root: Path, encryption_key: str, lookup_key: str, ttl: int):
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = root / "private.sqlite3"
        self.cipher = Fernet(encryption_key.encode())
        if len(lookup_key) < 32:
            raise ValueError("IDENTITY_LOOKUP_KEY must have at least 32 characters")
        self.lookup_key = lookup_key.encode()
        self.ttl = ttl
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, owner TEXT NOT NULL,
                    readers TEXT NOT NULL, title TEXT NOT NULL,
                    classification TEXT NOT NULL, confidentiality TEXT NOT NULL,
                    status TEXT NOT NULL, pages INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS identities (
                    token TEXT PRIMARY KEY, tenant TEXT NOT NULL,
                    strong_hash TEXT NOT NULL, payload BLOB NOT NULL,
                    readers TEXT NOT NULL, UNIQUE(tenant, strong_hash));
                CREATE TABLE IF NOT EXISTS aliases (
                    tenant TEXT NOT NULL, alias_hash TEXT NOT NULL, token TEXT NOT NULL,
                    PRIMARY KEY(tenant, alias_hash, token));
                CREATE TABLE IF NOT EXISTS mentions (
                    token TEXT NOT NULL, document_id TEXT NOT NULL,
                    PRIMARY KEY(token, document_id));
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, user_id TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, expires REAL NOT NULL);
            """)
            # Additive migration preserves existing documents, identities and sessions.
            db.execute("BEGIN IMMEDIATE")
            if "language" not in {
                row["name"] for row in db.execute("PRAGMA table_info(documents)")
            }:
                db.execute(
                    "ALTER TABLE documents ADD COLUMN "
                    "language TEXT NOT NULL DEFAULT 'und'"
                )
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.row_factory = sqlite3.Row
            with db:
                yield db
        finally:
            db.close()

    def lookup_alias(self, p: Principal, alias: str) -> list[dict]:
        """Use the private HMAC index and intersect with authorized identities."""
        with self.db() as db:
            tokens = {
                r["token"]
                for r in db.execute(
                    "SELECT token FROM aliases WHERE tenant=? AND alias_hash=?",
                    (p.tenant_id, self.digest(p.tenant_id, alias)),
                )
            }
        return [i for i in self.allowed_identities(p) if i["token"] in tokens]

    def digest(self, tenant: str, value: str) -> str:
        return hmac.new(
            self.lookup_key,
            (tenant + "\0" + normalized(value)).encode(),
            hashlib.sha256,
        ).hexdigest()

    def visible_docs(self, p: Principal) -> list[dict]:
        with self.db() as db:
            rows = db.execute(
                "SELECT * FROM documents WHERE tenant=? AND status='ready'",
                (p.tenant_id,),
            ).fetchall()
        return [
            {**dict(r), "readers": json.loads(r["readers"])}
            for r in rows
            if p.user_id in json.loads(r["readers"])
        ]

    def document(self, p: Principal, document_id: str) -> dict:
        for doc in self.visible_docs(p):
            if doc["id"] == document_id:
                return doc
        raise HTTPException(404, "Document not found")

    def create_document(
        self, p, doc_id, readers, classification, confidentiality, pages, language="und"
    ):
        with self.db() as db:
            db.execute(
                "INSERT INTO documents (id,tenant,owner,readers,title,classification,"
                "confidentiality,status,pages,language) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    doc_id,
                    p.tenant_id,
                    p.user_id,
                    json.dumps(readers),
                    f"Document {doc_id[:8]}",
                    classification,
                    confidentiality,
                    "processing",
                    pages,
                    language,
                ),
            )

    def status(self, doc_id: str, status: str):
        with self.db() as db:
            db.execute("UPDATE documents SET status=? WHERE id=?", (status, doc_id))

    def put_identity(
        self,
        p: Principal,
        strong: str,
        name: str,
        aliases: list[str],
        readers: list[str],
        document_id: str | None = None,
        curated: bool = False,
    ) -> str:
        """Strong identity key only; names alone are scoped to a single document."""
        key = self.digest(p.tenant_id, strong)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM identities WHERE tenant=? AND strong_hash=?",
                (p.tenant_id, key),
            ).fetchone()
            if existing:
                if curated and p.user_id not in json.loads(existing["readers"]):
                    raise HTTPException(403, "Identity registration is not authorized")
                token = existing["token"]
                # Uploaders cannot modify existing identity payloads or grants.
            else:
                token = "PII_" + uuid4().hex.upper()
                values = list(dict.fromkeys([name, *aliases]))
                payload = self.cipher.encrypt(
                    json.dumps(
                        {"name": name, "aliases": values, "curated": curated}
                    ).encode()
                )
                db.execute(
                    "INSERT INTO identities VALUES(?,?,?,?,?)",
                    (token, p.tenant_id, key, payload, json.dumps(readers)),
                )
                for alias in values:
                    db.execute(
                        "INSERT OR IGNORE INTO aliases VALUES(?,?,?)",
                        (p.tenant_id, self.digest(p.tenant_id, alias), token),
                    )
            if document_id:
                db.execute(
                    "INSERT OR IGNORE INTO mentions VALUES(?,?)", (token, document_id)
                )
        return token

    def allowed_identities(self, p: Principal) -> list[dict]:
        docs = {d["id"] for d in self.visible_docs(p)}
        with self.db() as db:
            rows = db.execute(
                "SELECT * FROM identities WHERE tenant=?", (p.tenant_id,)
            ).fetchall()
            mentions = db.execute(
                "SELECT m.token,m.document_id FROM mentions m JOIN identities i "
                "ON i.token=m.token WHERE i.tenant=?",
                (p.tenant_id,),
            ).fetchall()
        visible_tokens = {m["token"] for m in mentions if m["document_id"] in docs}
        result = []
        for row in rows:
            if (
                p.user_id in json.loads(row["readers"])
                or row["token"] in visible_tokens
            ):
                result.append(
                    {
                        "token": row["token"],
                        **json.loads(self.cipher.decrypt(row["payload"])),
                    }
                )
        return result

    def restore(self, text: str, p: Principal, allowed_tokens: set[str]) -> str:
        if "pii:read" not in p.scopes:
            raise HTTPException(403, "PII restoration requires pii:read")
        mapping = {
            i["token"]: i["name"]
            for i in self.allowed_identities(p)
            if i["token"] in allowed_tokens
        }
        return re.sub(r"PII_[A-F0-9]{32}", lambda m: mapping.get(m[0], m[0]), text)

    def new_session(self, p: Principal) -> dict:
        sid = uuid4().hex
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?,0,?)",
                (sid, p.tenant_id, p.user_id, time.time() + self.ttl),
            )
        return {"session_id": sid, "attempts": 0, "attempts_remaining": 3}

    def session(self, p: Principal, sid: str, reject: bool = False) -> dict:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM sessions WHERE id=? AND tenant=? "
                "AND user_id=? AND expires>?",
                (sid, p.tenant_id, p.user_id, time.time()),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Session not found or expired")
            attempts = row["attempts"]
            if attempts >= 3:
                raise HTTPException(
                    423, "Session locked after three out-of-scope questions"
                )
            if reject:
                attempts += 1
                db.execute("UPDATE sessions SET attempts=? WHERE id=?", (attempts, sid))
        return {
            "session_id": sid,
            "attempts": attempts,
            "attempts_remaining": max(0, 3 - attempts),
            "locked": attempts >= 3,
        }
