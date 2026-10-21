"""SQLite storage with simple versioned migrations."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

MIGRATIONS = [
    # v1
    """
    CREATE TABLE papers (
        id               TEXT PRIMARY KEY,      -- arXiv id without version, e.g. 2410.01234
        version          TEXT,
        title            TEXT NOT NULL,
        authors          TEXT NOT NULL,         -- JSON list
        abstract         TEXT,
        published_at     TEXT,                  -- UTC ISO, from arXiv
        updated_at       TEXT,
        retrieved_at     TEXT NOT NULL,         -- UTC ISO, when we fetched it (never used as publish time)
        url              TEXT NOT NULL,
        pdf_url          TEXT,
        primary_category TEXT,
        categories       TEXT,                  -- JSON list
        journal_ref      TEXT,
        comment          TEXT,
        source           TEXT NOT NULL DEFAULT 'arXiv',
        source_type      TEXT NOT NULL DEFAULT 'academic_paper',
        content_access   TEXT NOT NULL DEFAULT 'abstract_only',
        found_by         TEXT,                  -- JSON list of search names
        area             TEXT,
        score            REAL,
        breakdown        TEXT,                  -- JSON: component scores
        why              TEXT,
        matched          TEXT                   -- JSON: {area: [keywords]}
    );
    CREATE INDEX idx_papers_published ON papers(published_at);
    CREATE INDEX idx_papers_score ON papers(score);

    CREATE TABLE briefings (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        trigger      TEXT NOT NULL,            -- scheduled | manual | catch-up | startup
        status       TEXT NOT NULL,            -- running | ok | partial | failed
        started_at   TEXT NOT NULL,
        finished_at  TEXT,
        fetched      INTEGER DEFAULT 0,
        new_papers   INTEGER DEFAULT 0,
        item_ids     TEXT,                     -- JSON list, ranked
        errors       TEXT                      -- JSON list of {source, error}
    );

    CREATE TABLE feedback (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        paper_id   TEXT NOT NULL,
        kind       TEXT NOT NULL,              -- relevant | not_relevant | opened | dismissed
        created_at TEXT NOT NULL
    );

    CREATE TABLE bookmarks (
        paper_id   TEXT PRIMARY KEY,
        created_at TEXT NOT NULL
    );
    """,
    # v2: news, discussions and market data alongside papers
    """
    ALTER TABLE papers ADD COLUMN meta TEXT;          -- JSON: domain, points, comments, coverage...
    CREATE INDEX idx_papers_source_type ON papers(source_type);
    CREATE TABLE snapshots (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        kind       TEXT NOT NULL,                     -- markets | macro
        taken_at   TEXT NOT NULL,
        data       TEXT NOT NULL                      -- JSON
    );
    """,
    # v3: dashboard sections (market | research | news | tech)
    """
    ALTER TABLE papers ADD COLUMN section TEXT;
    CREATE INDEX idx_papers_section ON papers(section);
    UPDATE papers SET section = 'research' WHERE source_type = 'academic_paper' OR source_type IS NULL;
    """,
]

JSON_FIELDS = {"authors", "categories", "found_by", "breakdown", "matched", "item_ids", "errors", "meta", "data"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    # -- infrastructure -------------------------------------------------
    def migrate(self) -> None:
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
                self._conn.executescript(sql)
                self._conn.execute(f"PRAGMA user_version = {i}")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        d = dict(row)
        for k in JSON_FIELDS & d.keys():
            if d[k] is not None:
                d[k] = json.loads(d[k])
        return d

    def _query(self, sql: str, args: Iterable = ()) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._row(r) for r in self._conn.execute(sql, tuple(args)).fetchall()]

    # -- papers ---------------------------------------------------------
    def has_paper(self, paper_id: str) -> bool:
        with self._lock:
            return self._conn.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone() is not None

    def upsert_paper(self, p: Dict[str, Any]) -> bool:
        """Insert or refresh a paper. Returns True if it was new."""
        is_new = not self.has_paper(p["id"])
        cols = [
            "id", "version", "title", "authors", "abstract", "published_at", "updated_at",
            "retrieved_at", "url", "pdf_url", "primary_category", "categories", "journal_ref",
            "comment", "source", "source_type", "content_access", "found_by", "meta",
        ]
        p = {**p, "meta": p.get("meta") or {}}
        vals = [json.dumps(p.get(c)) if c in JSON_FIELDS else p.get(c) for c in cols]
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in ("id", "retrieved_at"))
        with self._lock:
            self._conn.execute(
                f"INSERT INTO papers ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                vals,
            )
            self._conn.commit()
        return is_new

    def set_score(self, paper_id: str, area: str, score: float, breakdown: dict, why: str, matched: dict,
                  section: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE papers SET area=?, score=?, breakdown=?, why=?, matched=?, section=COALESCE(?, section) WHERE id=?",
                (area, score, json.dumps(breakdown), why, json.dumps(matched), section, paper_id),
            )
            self._conn.commit()

    def get_paper(self, paper_id: str) -> Optional[Dict[str, Any]]:
        rows = self._query(
            "SELECT p.*, (b.paper_id IS NOT NULL) AS bookmarked FROM papers p "
            "LEFT JOIN bookmarks b ON b.paper_id = p.id WHERE p.id=?", (paper_id,))
        return rows[0] if rows else None

    def get_papers(self, ids: List[str]) -> List[Dict[str, Any]]:
        by_id = {p["id"]: p for p in (self.get_paper(i) for i in ids) if p}
        return [by_id[i] for i in ids if i in by_id]

    def list_papers(self, area: str | None = None, q: str | None = None, sort: str = "score",
                    limit: int = 50, bookmarked: bool = False, since: str | None = None,
                    kind: str | None = None, section: str | None = None) -> List[Dict[str, Any]]:
        where, args = ["p.score IS NOT NULL"], []
        if section:
            where.append("p.section = ?"); args.append(section)
        if kind == "papers":
            where.append("p.source_type = 'academic_paper'")
        elif kind == "news":
            where.append("p.source_type != 'academic_paper'")
        if area:
            where.append("p.area = ?"); args.append(area)
        if q:
            where.append("(p.title LIKE ? OR p.abstract LIKE ? OR p.authors LIKE ?)")
            args += [f"%{q}%"] * 3
        if bookmarked:
            where.append("b.paper_id IS NOT NULL")
        if since:
            where.append("p.published_at >= ?"); args.append(since)
        order = "p.published_at DESC" if sort == "date" else "p.score DESC, p.published_at DESC"
        args.append(limit)
        return self._query(
            "SELECT p.*, (b.paper_id IS NOT NULL) AS bookmarked FROM papers p "
            "LEFT JOIN bookmarks b ON b.paper_id = p.id "
            f"WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?", args)

    def recent_items(self, since: str, source_types: tuple) -> List[Dict[str, Any]]:
        marks = ",".join("?" * len(source_types))
        return self._query(f"SELECT id, title, meta FROM papers WHERE retrieved_at >= ? AND source_type IN ({marks})",
                           (since, *source_types))

    def update_meta(self, paper_id: str, meta: dict) -> None:
        with self._lock:
            self._conn.execute("UPDATE papers SET meta=? WHERE id=?", (json.dumps(meta), paper_id))
            self._conn.commit()

    # -- market / macro snapshots -----------------------------------------
    def save_snapshot(self, kind: str, taken_at: str, data: dict) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO snapshots (kind, taken_at, data) VALUES (?,?,?)",
                               (kind, taken_at, json.dumps(data)))
            self._conn.commit()

    def latest_snapshot(self, kind: str) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM snapshots WHERE kind=? ORDER BY id DESC LIMIT 1", (kind,))
        return rows[0] if rows else None

    def recent_titles(self, exclude_id: str, since: str) -> List[str]:
        with self._lock:
            return [r[0] for r in self._conn.execute(
                "SELECT title FROM papers WHERE id != ? AND retrieved_at >= ? AND score IS NOT NULL",
                (exclude_id, since)).fetchall()]

    def count_papers(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]

    def section_counts(self) -> Dict[str, int]:
        with self._lock:
            return {r[0]: r[1] for r in self._conn.execute(
                "SELECT section, COUNT(*) FROM papers WHERE section IS NOT NULL AND score IS NOT NULL GROUP BY section")}

    def area_counts(self) -> Dict[str, int]:
        with self._lock:
            return {r[0]: r[1] for r in self._conn.execute(
                "SELECT area, COUNT(*) FROM papers WHERE area IS NOT NULL GROUP BY area")}

    # -- briefings ------------------------------------------------------
    def start_briefing(self, trigger: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO briefings (trigger, status, started_at) VALUES (?, 'running', ?)",
                (trigger, utcnow()))
            self._conn.commit()
            return cur.lastrowid

    def finish_briefing(self, bid: int, status: str, fetched: int, new: int, item_ids: List[str], errors: list) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE briefings SET status=?, finished_at=?, fetched=?, new_papers=?, item_ids=?, errors=? WHERE id=?",
                (status, utcnow(), fetched, new, json.dumps(item_ids), json.dumps(errors), bid))
            self._conn.commit()

    def latest_briefing(self, successful_only: bool = True) -> Optional[Dict[str, Any]]:
        cond = "WHERE status IN ('ok','partial')" if successful_only else ""
        rows = self._query(f"SELECT * FROM briefings {cond} ORDER BY id DESC LIMIT 1")
        return rows[0] if rows else None

    def recent_briefings(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self._query("SELECT * FROM briefings ORDER BY id DESC LIMIT ?", (limit,))

    def fail_stale_running(self) -> None:
        """A crash mid-briefing leaves a 'running' row; mark it failed on startup."""
        with self._lock:
            self._conn.execute(
                "UPDATE briefings SET status='failed', finished_at=?, errors=? WHERE status='running'",
                (utcnow(), json.dumps([{"source": "butler", "error": "interrupted (process stopped)"}])))
            self._conn.commit()

    # -- feedback & bookmarks -------------------------------------------
    def add_feedback(self, paper_id: str, kind: str) -> None:
        with self._lock:
            self._conn.execute("INSERT INTO feedback (paper_id, kind, created_at) VALUES (?,?,?)",
                               (paper_id, kind, utcnow()))
            self._conn.commit()

    def latest_feedback(self, paper_id: str) -> Optional[str]:
        with self._lock:
            r = self._conn.execute(
                "SELECT kind FROM feedback WHERE paper_id=? AND kind IN ('relevant','not_relevant') "
                "ORDER BY id DESC LIMIT 1", (paper_id,)).fetchone()
            return r[0] if r else None

    def set_bookmark(self, paper_id: str, on: bool) -> None:
        with self._lock:
            if on:
                self._conn.execute("INSERT OR IGNORE INTO bookmarks VALUES (?, ?)", (paper_id, utcnow()))
            else:
                self._conn.execute("DELETE FROM bookmarks WHERE paper_id=?", (paper_id,))
            self._conn.commit()

    def reset_personal_data(self) -> None:
        with self._lock:
            self._conn.executescript("DELETE FROM feedback; DELETE FROM bookmarks;")
            self._conn.commit()
