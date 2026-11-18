"""SQLite transactions; connections are scoped to each operation."""

import secrets
import sqlite3
import string
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS owner (
                    id INTEGER PRIMARY KEY CHECK(id=1), password_hash TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS links (
                    id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    title TEXT NOT NULL, destination TEXT NOT NULL, tag TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL,
                    expires_at REAL, clicks INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS visits (
                    id INTEGER PRIMARY KEY, link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
                    created_at REAL NOT NULL, browser TEXT NOT NULL, source TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS visits_date ON visits(created_at);
                CREATE INDEX IF NOT EXISTS visits_link ON visits(link_id, created_at);
                CREATE TABLE IF NOT EXISTS attempts (subject TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS attempts_subject ON attempts(subject,created_at);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def owner(self):
        with self.connection() as db:
            row = db.execute("SELECT * FROM owner WHERE id=1").fetchone()
            return dict(row) if row else None

    def create_owner(self, encoded):
        with self.connection() as db:
            db.execute("INSERT INTO owner(id,password_hash) VALUES (1,?)", (encoded,))

    def change_password(self, encoded):
        with self.connection() as db:
            db.execute(
                "UPDATE owner SET password_hash=?,revision=revision+1 WHERE id=1", (encoded,)
            )

    def throttled(self, subject: str) -> bool:
        with self.connection() as db:
            db.execute("DELETE FROM attempts WHERE created_at<?", (time.time() - 600,))
            return (
                db.execute("SELECT count(*) FROM attempts WHERE subject=?", (subject,)).fetchone()[
                    0
                ]
                >= 5
            )

    def attempt(self, subject):
        with self.connection() as db:
            db.execute("INSERT INTO attempts VALUES (?,?)", (subject, time.time()))

    def list_links(self):
        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM links ORDER BY created_at DESC,id DESC")
            ]

    def get_link(self, slug):
        with self.connection() as db:
            row = db.execute("SELECT * FROM links WHERE slug=?", (slug,)).fetchone()
            return dict(row) if row else None

    def create_link(self, values):
        with self.connection() as db:
            for _ in range(8):
                slug = (
                    values.get("slug")
                    or secrets.choice(string.ascii_lowercase + string.digits)
                    + secrets.token_urlsafe(6).lower()
                )
                try:
                    db.execute(
                        """INSERT INTO links(slug,title,destination,tag,created_at,expires_at,active)
                        VALUES (?,?,?,?,?,?,?)""",
                        (
                            slug,
                            values["title"],
                            values["destination"],
                            values["tag"],
                            time.time(),
                            values.get("expires_at"),
                            values.get("active", True),
                        ),
                    )
                    return slug
                except sqlite3.IntegrityError:
                    if values.get("slug"):
                        raise
            raise RuntimeError("Не удалось подобрать свободный адрес. Попробуйте ещё раз.")

    def update_link(self, slug, values):
        with self.connection() as db:
            cursor = db.execute(
                """UPDATE links SET title=?,destination=?,tag=?,expires_at=?,active=?
                WHERE slug=?""",
                (
                    values["title"],
                    values["destination"],
                    values["tag"],
                    values.get("expires_at"),
                    values["active"],
                    slug,
                ),
            )
            return cursor.rowcount

    def delete_link(self, slug):
        with self.connection() as db:
            return db.execute("DELETE FROM links WHERE slug=?", (slug,)).rowcount

    def follow(self, slug, browser, source, *, count=True):
        # Read availability and record the click in the same transaction.
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM links WHERE slug=?", (slug,)).fetchone()
            if not row:
                return None, 404
            if not row["active"] or (
                row["expires_at"] is not None and row["expires_at"] <= time.time()
            ):
                return None, 410
            if count:
                db.execute("UPDATE links SET clicks=clicks+1 WHERE id=?", (row["id"],))
                db.execute(
                    "INSERT INTO visits(link_id,created_at,browser,source) VALUES (?,?,?,?)",
                    (row["id"], time.time(), browser, source),
                )
                db.execute("DELETE FROM visits WHERE created_at<?", (time.time() - 90 * 86400,))
            return row["destination"], 302

    def analytics(self):
        now = datetime.now(UTC)
        days = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(13, -1, -1)]
        with self.connection() as db:
            db.execute("DELETE FROM visits WHERE created_at<?", (time.time() - 90 * 86400,))
            counts = dict(
                db.execute(
                    """SELECT strftime('%Y-%m-%d',created_at,'unixepoch'),count(*)
                FROM visits WHERE created_at>=? GROUP BY 1""",
                    (time.time() - 14 * 86400,),
                )
            )
            sources = [
                dict(row)
                for row in db.execute(
                    """SELECT source AS name,count(*) AS count
                FROM visits WHERE created_at>=? GROUP BY source ORDER BY count DESC LIMIT 5""",
                    (time.time() - 30 * 86400,),
                )
            ]
            browsers = [
                dict(row)
                for row in db.execute(
                    """SELECT browser AS name,count(*) AS count
                FROM visits WHERE created_at>=? GROUP BY browser ORDER BY count DESC LIMIT 5""",
                    (time.time() - 30 * 86400,),
                )
            ]
            total = db.execute("SELECT COALESCE(sum(clicks),0) FROM links").fetchone()[0]
        return {
            "days": [{"date": day, "count": counts.get(day, 0)} for day in days],
            "sources": sources,
            "browsers": browsers,
            "total_clicks": total,
        }
