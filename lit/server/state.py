"""What the server knows beyond the papers: users, libraries, ingest jobs and reports.

The papers stay files in the collection, in the format every `litdb` command
reads. This is the rest, in one SQLite file inside the collection directory, so
one backup of that directory holds everything. Its name starts with a dot, as
`.references.jsonl` does, so no pass over the papers mistakes it for one, and the
reader refuses to serve it.

A token is stored only as its SHA-256. Whoever reads the database learns who the
users are, and cannot sign in as one of them.

A library is a named list of slugs. It copies nothing: the papers stay in the
shared collection, and a library turns into the `--scope` of a command.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from lit import identity, reference_store

DB_NAME = ".server.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    name       TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    admin      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS libraries (
    name  TEXT PRIMARY KEY,
    owner TEXT NOT NULL REFERENCES users(name)
);
CREATE TABLE IF NOT EXISTS library_papers (
    library  TEXT NOT NULL REFERENCES libraries(name),
    slug     TEXT NOT NULL,
    added_by TEXT NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (library, slug)
);
CREATE TABLE IF NOT EXISTS jobs (
    id       INTEGER PRIMARY KEY,
    source   TEXT NOT NULL,          -- arxiv:<id>; a PDF backend would add its own prefix
    library  TEXT NOT NULL REFERENCES libraries(name),
    user     TEXT NOT NULL,
    status   TEXT NOT NULL,          -- queued, running, done, failed
    force    INTEGER NOT NULL DEFAULT 0,
    slug     TEXT,
    report   TEXT,                   -- the JSON add-paper printed, or the error
    created  TEXT NOT NULL,
    finished TEXT
);
CREATE TABLE IF NOT EXISTS reports (
    owner   TEXT NOT NULL REFERENCES users(name),
    name    TEXT NOT NULL,
    text    TEXT NOT NULL DEFAULT '',  -- the report source, with its lit: markers
    log     TEXT NOT NULL DEFAULT '',  -- the research log, appended to during the research
    public  INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    PRIMARY KEY (owner, name)
);
"""

NAME = re.compile(r"^[A-Za-z0-9_-]+$")

# How long one ingest may run before the worker gives up on it. A long review
# with a hundred figures takes minutes; an hour means something hangs.
INGEST_TIMEOUT_S = 3600

# Held by whatever writes the shared collection: the ingest worker, and an
# admin removing a paper. Both rewrite the collection index and the reference
# store, and two writers at once would lose one of the two changes.
WRITE_LOCK = threading.Lock()


def db_path(root: Path) -> Path:
    return root / DB_NAME


def connect(root: Path) -> sqlite3.Connection:
    """A connection with the schema in place. Cheap enough to open per request."""
    db = sqlite3.connect(db_path(root), timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


# What a project sets LITERATURE_LIBRARY to when it works on its local
# collection; so no library, user or report may be called that.
LOCAL = "local"


def check_name(name: str) -> str:
    if not NAME.match(name or ""):
        raise ValueError("a name is letters, digits, - and _: %r" % name)
    if name == LOCAL:
        raise ValueError("%r is reserved: LITERATURE_LIBRARY=local means a local collection" % name)
    return name


def add_user(db: sqlite3.Connection, name: str, admin: bool = False) -> str:
    """Create a user and their personal library, and return their token.

    The token is shown once. Only its hash is kept, so a lost token is replaced
    by deleting the user and adding them again, not by looking it up.
    """
    check_name(name)
    token = secrets.token_urlsafe(24)
    with db:
        db.execute("INSERT INTO users (name, token_hash, admin) VALUES (?, ?, ?)",
                   (name, hash_token(token), int(admin)))
        db.execute("INSERT INTO libraries (name, owner) VALUES (?, ?)", (name, name))
    return token


def user_for(db: sqlite3.Connection, token: str | None) -> str | None:
    """The name of the user a token belongs to, or None."""
    if not token:
        return None
    row = db.execute("SELECT name FROM users WHERE token_hash = ?", (hash_token(token),)).fetchone()
    return row["name"] if row else None


def is_admin(db: sqlite3.Connection, user: str) -> bool:
    row = db.execute("SELECT admin FROM users WHERE name = ?", (user,)).fetchone()
    return bool(row and row["admin"])


# --------------------------------------------------------------------------
# libraries
# --------------------------------------------------------------------------


def libraries(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every library, with its owner and how many papers it lists."""
    return db.execute(
        "SELECT l.name, l.owner, COUNT(p.slug) AS papers FROM libraries l "
        "LEFT JOIN library_papers p ON p.library = l.name GROUP BY l.name ORDER BY l.name"
    ).fetchall()


def create_library(db: sqlite3.Connection, name: str, owner: str) -> None:
    check_name(name)
    with db:
        db.execute("INSERT INTO libraries (name, owner) VALUES (?, ?)", (name, owner))


def delete_library(db: sqlite3.Connection, name: str, user: str) -> None:
    """Delete a library its owner no longer needs. The papers stay in the collection.

    A personal library cannot go: it is where a user's papers land when no other
    library is named, on the web and over MCP.
    """
    row = db.execute("SELECT owner FROM libraries WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise LookupError("There is no library named %s." % name)
    if row["owner"] != user:
        raise PermissionError("Only %s, who owns %s, can delete it." % (row["owner"], name))
    if name == user:
        raise PermissionError("Your personal library cannot be deleted.")
    with db:
        db.execute("DELETE FROM library_papers WHERE library = ?", (name,))
        db.execute("DELETE FROM libraries WHERE name = ?", (name,))


def library_exists(db: sqlite3.Connection, name: str) -> bool:
    return db.execute("SELECT 1 FROM libraries WHERE name = ?", (name,)).fetchone() is not None


def library_slugs(db: sqlite3.Connection, name: str) -> list[str]:
    rows = db.execute("SELECT slug FROM library_papers WHERE library = ? ORDER BY slug", (name,))
    return [row["slug"] for row in rows]


def add_to_library(db: sqlite3.Connection, library: str, slug: str, user: str) -> None:
    """List a paper in a library. Listing it twice is not an error."""
    with db:
        db.execute("INSERT OR IGNORE INTO library_papers VALUES (?, ?, ?, ?)",
                   (library, slug, user, now()))


def remove_from_library(db: sqlite3.Connection, library: str, slug: str) -> None:
    """Take a paper out of a library. The collection keeps it."""
    with db:
        db.execute("DELETE FROM library_papers WHERE library = ? AND slug = ?", (library, slug))


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------

PARTS = ("text", "log")  # the report and its research log, as columns


def report(db: sqlite3.Connection, owner: str, name: str) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM reports WHERE owner = ? AND name = ?",
                      (owner, name)).fetchone()


def visible_reports(db: sqlite3.Connection, user: str) -> list[sqlite3.Row]:
    """The user's own reports and everyone's public ones, newest first."""
    return db.execute(
        "SELECT owner, name, public, updated, log != '' AS has_log FROM reports "
        "WHERE owner = ? OR public ORDER BY updated DESC", (user,)).fetchall()


def write_report(db: sqlite3.Connection, owner: str, name: str, part: str, text: str) -> None:
    """Create a report, or replace one part of it: `text` or `log`."""
    check_name(name)
    if part not in PARTS:
        raise ValueError("a report has the parts %s, not %r" % (", ".join(PARTS), part))
    with db:
        db.execute("INSERT OR IGNORE INTO reports (owner, name, created, updated) "
                   "VALUES (?, ?, ?, ?)", (owner, name, now(), now()))
        db.execute("UPDATE reports SET %s = ?, updated = ? WHERE owner = ? AND name = ?" % part,
                   (text, now(), owner, name))


def append_log(db: sqlite3.Connection, owner: str, name: str, entry: str) -> str:
    """Add an entry to the end of a report's research log, and return the log."""
    found = report(db, owner, name)
    log = found["log"] if found else ""
    log = (log.rstrip("\n") + "\n\n" if log.strip() else "") + entry.strip("\n") + "\n"
    write_report(db, owner, name, "log", log)
    return log


def edit_report(db: sqlite3.Connection, owner: str, name: str, part: str, old: str,
                new: str) -> str:
    """Replace the one place in a part of a report that reads `old`, and return the part."""
    found = report(db, owner, name)
    if found is None:
        raise LookupError("You have no report named %s." % name)
    if part not in PARTS:
        raise ValueError("a report has the parts %s, not %r" % (", ".join(PARTS), part))
    count = found[part].count(old) if old else 0
    if count == 0:
        raise LookupError("The %s of %s does not contain that text." % (part, name))
    if count > 1:
        raise ValueError("The %s of %s contains that text %d times; give more of it."
                         % (part, name, count))
    text = found[part].replace(old, new, 1)
    write_report(db, owner, name, part, text)
    return text


def owned_report(db: sqlite3.Connection, owner: str, name: str, user: str) -> None:
    found = report(db, owner, name)
    if found is None:
        raise LookupError("There is no report %s/%s." % (owner, name))
    if owner != user:
        raise PermissionError("Only %s, who owns %s, can change it." % (owner, name))


def set_public(db: sqlite3.Connection, owner: str, name: str, user: str, public: bool) -> None:
    owned_report(db, owner, name, user)
    with db:
        db.execute("UPDATE reports SET public = ? WHERE owner = ? AND name = ?",
                   (int(public), owner, name))


def delete_report(db: sqlite3.Connection, owner: str, name: str, user: str) -> None:
    owned_report(db, owner, name, user)
    with db:
        db.execute("DELETE FROM reports WHERE owner = ? AND name = ?", (owner, name))


# --------------------------------------------------------------------------
# ingest jobs
# --------------------------------------------------------------------------


def arxiv_source(argument: str) -> str:
    """`arxiv:<id>` for what a user typed, without the version.

    The version is not the paper: the collection holds one version of each, the
    one the first ingest found.
    """
    argument = argument.strip()
    if not identity.looks_like_arxiv_id(argument):
        raise ValueError("not an arXiv identifier: %r" % argument)
    return "arxiv:" + reference_store.normalize_arxiv(argument)


def held_slug(root: Path, source: str) -> str | None:
    """The slug of the paper that holds this source already, or None."""
    return reference_store.held_index(root).get(source)


def add_paper(db: sqlite3.Connection, root: Path, argument: str, library: str,
              user: str) -> tuple[str, str]:
    """Put a paper in a library, ingesting it first if the collection lacks it.

    Returns ("listed", slug) when the collection held it, and ("queued", job id)
    when an ingest has to run first.
    """
    source = arxiv_source(argument)
    if not library_exists(db, library):
        raise ValueError("no library named %r" % library)
    slug = held_slug(root, source)
    if slug:
        add_to_library(db, library, slug, user)
        return "listed", slug
    with db:
        cursor = db.execute(
            "INSERT INTO jobs (source, library, user, status, created) VALUES (?, ?, ?, 'queued', ?)",
            (source, library, user, now()),
        )
    return "queued", str(cursor.lastrowid)


def jobs(db: sqlite3.Connection, status: str | None = None, limit: int = 200) -> list[dict]:
    query = "SELECT * FROM jobs" + (" WHERE status = ?" if status else "") + " ORDER BY id DESC LIMIT ?"
    rows = db.execute(query, ((status, limit) if status else (limit,))).fetchall()
    return [dict(row, report=json.loads(row["report"]) if row["report"] else None) for row in rows]


def job(db: sqlite3.Connection, job_id: int) -> dict | None:
    row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return dict(row, report=json.loads(row["report"]) if row["report"] else None)


def retry(db: sqlite3.Connection, job_id: int, force: bool = False) -> None:
    """Queue a failed job again. `force` replaces a paper directory that is there."""
    with db:
        db.execute(
            "UPDATE jobs SET status = 'queued', force = ?, report = NULL, finished = NULL "
            "WHERE id = ? AND status = 'failed'",
            (int(force), job_id),
        )


def requeue_interrupted(db: sqlite3.Connection) -> None:
    """A job that was running when the server stopped runs again from the start."""
    with db:
        db.execute("UPDATE jobs SET status = 'queued' WHERE status = 'running'")


def ingest_command(root: Path, source: str, force: bool) -> list[str]:
    kind, _, identifier = source.partition(":")
    if kind != "arxiv":
        raise ValueError("no ingest backend for %r" % source)
    command = [sys.executable, "-m", "lit", "add-paper", "--auto", identifier,
               "--literature-root", str(root)]
    return command + (["--force"] if force else [])


def last_json_line(text: str) -> dict | None:
    for line in reversed(text.strip().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def run_job(db: sqlite3.Connection, root: Path, row: sqlite3.Row) -> None:
    """Run one ingest to its end, and record what happened.

    The ingest is `litdb add-paper` in a process of its own: its exit status
    and its one-line report are the contract every caller of it already reads,
    and a crash or a hang in the conversion stays out of the server.
    """
    source, force = row["source"], bool(row["force"])
    slug = None if force else held_slug(root, source)
    if slug:
        status, report = "done", {"status": "present", "slug": slug}
    else:
        try:
            done = subprocess.run(ingest_command(root, source, force), capture_output=True,
                                  text=True, timeout=INGEST_TIMEOUT_S)
            report = last_json_line(done.stdout) or {
                "error": (done.stderr or done.stdout).strip()[-2000:] or "no output"}
            ok = done.returncode == 0
        except subprocess.TimeoutExpired:
            report, ok = {"error": "the ingest ran longer than %d s" % INGEST_TIMEOUT_S}, False
        except ValueError as error:
            report, ok = {"error": str(error)}, False
        slug = report.get("slug") if ok else None
        status = "done" if ok and slug else "failed"
    if slug and library_exists(db, row["library"]):  # deleted while the job waited
        add_to_library(db, row["library"], slug, row["user"])
    with db:
        db.execute("UPDATE jobs SET status = ?, slug = ?, report = ?, finished = ? WHERE id = ?",
                   (status, slug, json.dumps(report, ensure_ascii=False), now(), row["id"]))


def remove_paper(db: sqlite3.Connection, root: Path, slug: str, force: bool) -> tuple[int, dict]:
    """Take a paper out of the collection with `litdb remove`, and out of every library.

    Returns the exit status and the report: 0 removed, 1 no such paper, 2 other
    papers cite it and `force` was not given. The caller holds `WRITE_LOCK`.
    """
    command = [sys.executable, "-m", "lit", "remove", slug, "--literature-root", str(root)]
    done = subprocess.run(command + (["--force"] if force else []),
                          capture_output=True, text=True, timeout=300)
    try:
        report = json.loads(done.stdout)
    except json.JSONDecodeError:
        report = {"error": (done.stderr or done.stdout).strip()[-2000:] or "no output"}
    if done.returncode == 0:
        with db:
            db.execute("DELETE FROM library_papers WHERE slug = ?", (slug,))
    return done.returncode, report


class Worker(threading.Thread):
    """The one thread that ingests, one job at a time, oldest first.

    One at a time is what the APIs allow anyway: the rate gate sends one request
    per host at a time. `wake` is set when a job is queued, so a new job starts
    at once rather than at the next poll.
    """

    def __init__(self, root: Path) -> None:
        super().__init__(daemon=True, name="ingest")
        self.root = root
        self.wake = threading.Event()

    def run(self) -> None:
        db = connect(self.root)
        requeue_interrupted(db)
        while True:
            row = db.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
            if row is None:
                self.wake.wait(timeout=30)
                self.wake.clear()
                continue
            with WRITE_LOCK:
                with db:
                    db.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (row["id"],))
                run_job(db, self.root, row)
