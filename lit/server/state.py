"""What the server knows beyond the papers: its users and their libraries.

The papers stay files in the collection, in the format every `litdb` command
reads. This is the rest, in one SQLite file inside the collection directory, so
one backup of that directory holds everything. Its name starts with a dot, as
`.references.jsonl` does, so no pass over the papers mistakes it for one, and the
reader refuses to serve it.

A token is stored only as its SHA-256. Whoever reads the database learns who the
users are, and cannot sign in as one of them.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from pathlib import Path

DB_NAME = ".server.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    name       TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS libraries (
    name  TEXT PRIMARY KEY,
    owner TEXT NOT NULL REFERENCES users(name)
);
"""


def db_path(root: Path) -> Path:
    return root / DB_NAME


def connect(root: Path) -> sqlite3.Connection:
    """A connection with the schema in place. Cheap enough to open per request."""
    db = sqlite3.connect(db_path(root))
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def add_user(db: sqlite3.Connection, name: str) -> str:
    """Create a user and their personal library, and return their token.

    The token is shown once. Only its hash is kept, so a lost token is replaced
    by deleting the user and adding them again, not by looking it up.
    """
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        raise ValueError("a user name is letters, digits, - and _: %r" % name)
    token = secrets.token_urlsafe(24)
    with db:
        db.execute("INSERT INTO users (name, token_hash) VALUES (?, ?)", (name, hash_token(token)))
        db.execute("INSERT INTO libraries (name, owner) VALUES (?, ?)", (name, name))
    return token


def user_for(db: sqlite3.Connection, token: str | None) -> str | None:
    """The name of the user a token belongs to, or None."""
    if not token:
        return None
    row = db.execute("SELECT name FROM users WHERE token_hash = ?", (hash_token(token),)).fetchone()
    return row["name"] if row else None
