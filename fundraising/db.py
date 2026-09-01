"""SQLite persistence layer.

This module is the system of record. Everything the dashboard displays is read
from here, and every write goes through a function that also appends to
``audit_log`` so an imported spreadsheet row can always be traced back to the
batch it came from.

The connection is deliberately created per-call rather than cached on a module
global: Streamlit reruns scripts on every interaction and can serve them from
different threads, and SQLite connections are not thread-safe by default.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import pandas as pd

from . import config

_WRITE_LOCK = threading.Lock()

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT,
    role        TEXT,
    calendar_id TEXT,
    ics_url     TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_people_name ON people(name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS investors (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT,
    domain      TEXT,
    partner     TEXT,
    location    TEXT,
    target_amount REAL,
    notes       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_investors_name ON investors(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS ix_investors_domain ON investors(domain);

CREATE TABLE IF NOT EXISTS conversations (
    id            INTEGER PRIMARY KEY,
    occurred_on   TEXT NOT NULL,
    person_id     INTEGER REFERENCES people(id) ON DELETE SET NULL,
    investor_id   INTEGER REFERENCES investors(id) ON DELETE SET NULL,
    counterpart   TEXT,
    channel       TEXT,
    stage         TEXT,
    outcome       TEXT,
    amount        REAL,
    next_step     TEXT,
    next_step_due TEXT,
    notes         TEXT,
    source        TEXT NOT NULL DEFAULT 'manual',
    source_key    TEXT,
    batch_id      INTEGER REFERENCES import_batches(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
-- Idempotency for re-imports: a calendar event or spreadsheet row can only ever
-- produce one conversation. Manual rows leave source_key NULL, and SQLite
-- permits unlimited NULLs in a unique index, so hand entry is never blocked.
CREATE UNIQUE INDEX IF NOT EXISTS ix_conversations_source
    ON conversations(source, source_key) WHERE source_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_conversations_date ON conversations(occurred_on);
CREATE INDEX IF NOT EXISTS ix_conversations_person ON conversations(person_id);
CREATE INDEX IF NOT EXISTS ix_conversations_investor ON conversations(investor_id);

CREATE TABLE IF NOT EXISTS calendar_events (
    id            INTEGER PRIMARY KEY,
    uid           TEXT NOT NULL,
    calendar_id   TEXT,
    person_id     INTEGER REFERENCES people(id) ON DELETE SET NULL,
    title         TEXT,
    description   TEXT,
    location      TEXT,
    starts_at     TEXT,
    ends_at       TEXT,
    attendees     TEXT,
    organizer     TEXT,
    score         REAL,
    reasons       TEXT,
    suggested_investor_id INTEGER REFERENCES investors(id) ON DELETE SET NULL,
    review_status TEXT NOT NULL DEFAULT 'pending',
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    fetched_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_calendar_uid ON calendar_events(uid);
CREATE INDEX IF NOT EXISTS ix_calendar_review ON calendar_events(review_status);

CREATE TABLE IF NOT EXISTS import_batches (
    id            INTEGER PRIMARY KEY,
    ts            TEXT NOT NULL,
    source_kind   TEXT NOT NULL,
    source_ref    TEXT,
    rows_read     INTEGER DEFAULT 0,
    rows_inserted INTEGER DEFAULT 0,
    rows_updated  INTEGER DEFAULT 0,
    rows_skipped  INTEGER DEFAULT 0,
    mapping       TEXT,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id        INTEGER PRIMARY KEY,
    ts        TEXT NOT NULL,
    actor     TEXT,
    entity    TEXT NOT NULL,
    entity_id INTEGER,
    action    TEXT NOT NULL,
    detail    TEXT
);
CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_log(ts);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

CONVERSATION_FIELDS = [
    "occurred_on", "person_id", "investor_id", "counterpart", "channel",
    "stage", "outcome", "amount", "next_step", "next_step_due", "notes",
    "source", "source_key", "batch_id",
]


# --- Connection handling -----------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    target = Path(path) if path is not None else config.db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def session(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, roll back on error."""
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: str | Path | None = None) -> None:
    """Create the schema and seed default settings. Safe to call repeatedly."""
    with _WRITE_LOCK, session(path) as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        for key, value in config.SETTINGS_DEFAULTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                (key, json.dumps(value)),
            )


# --- Generic helpers ---------------------------------------------------------

def _norm(value: Any) -> Any:
    """Coerce values into something SQLite accepts, mapping blanks to NULL."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value)
    # pandas / numpy scalars (NaN, NaT, np.int64, ...)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


def log(conn: sqlite3.Connection, entity: str, entity_id: int | None,
        action: str, detail: Any = None, actor: str = "app") -> None:
    conn.execute(
        "INSERT INTO audit_log(ts, actor, entity, entity_id, action, detail) "
        "VALUES(?,?,?,?,?,?)",
        (_now(), actor, entity, entity_id, action,
         json.dumps(detail, default=str) if detail is not None else None),
    )


def query_df(sql: str, params: Sequence[Any] = (), path: str | Path | None = None) -> pd.DataFrame:
    conn = connect(path)
    try:
        return pd.read_sql_query(sql, conn, params=list(params))
    finally:
        conn.close()


# --- Settings ----------------------------------------------------------------

def get_setting(key: str, default: Any = None, path: str | Path | None = None) -> Any:
    conn = connect(path)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    if row is None or row["value"] is None:
        return config.SETTINGS_DEFAULTS.get(key, default)
    try:
        return json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return row["value"]


def set_setting(key: str, value: Any, path: str | Path | None = None) -> None:
    with _WRITE_LOCK, session(path) as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
        log(conn, "settings", None, "set", {"key": key})


def all_settings(path: str | Path | None = None) -> dict[str, Any]:
    out = dict(config.SETTINGS_DEFAULTS)
    conn = connect(path)
    try:
        for row in conn.execute("SELECT key, value FROM settings"):
            try:
                out[row["key"]] = json.loads(row["value"])
            except (TypeError, json.JSONDecodeError):
                out[row["key"]] = row["value"]
    finally:
        conn.close()
    return out


# --- People ------------------------------------------------------------------

def upsert_person(name: str, *, email: str | None = None, role: str | None = None,
                  calendar_id: str | None = None, ics_url: str | None = None,
                  active: bool = True, path: str | Path | None = None) -> int:
    """Insert a person, or update the non-empty fields of an existing one.

    Matching is case-insensitive on name so "Jay Kumar" and "jay kumar" arriving
    from two different spreadsheets do not create duplicate rows.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("person name is required")
    with _WRITE_LOCK, session(path) as conn:
        row = conn.execute(
            "SELECT id FROM people WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        now = _now()
        if row:
            pid = row["id"]
            updates, params = [], []
            for field, value in (("email", email), ("role", role),
                                 ("calendar_id", calendar_id), ("ics_url", ics_url)):
                value = _norm(value)
                if value is not None:
                    updates.append(f"{field} = ?")
                    params.append(value)
            updates.append("active = ?")
            params.append(1 if active else 0)
            updates.append("updated_at = ?")
            params.append(now)
            params.append(pid)
            conn.execute(f"UPDATE people SET {', '.join(updates)} WHERE id = ?", params)
            log(conn, "people", pid, "update", {"name": name})
            return pid
        cur = conn.execute(
            "INSERT INTO people(name, email, role, calendar_id, ics_url, active, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (name, _norm(email), _norm(role), _norm(calendar_id), _norm(ics_url),
             1 if active else 0, now, now),
        )
        log(conn, "people", cur.lastrowid, "create", {"name": name})
        return int(cur.lastrowid)


def delete_person(person_id: int, path: str | Path | None = None) -> None:
    with _WRITE_LOCK, session(path) as conn:
        conn.execute("DELETE FROM people WHERE id = ?", (person_id,))
        log(conn, "people", person_id, "delete")


def list_people(path: str | Path | None = None) -> pd.DataFrame:
    return query_df("SELECT * FROM people ORDER BY active DESC, name", path=path)


# --- Investors ---------------------------------------------------------------

def upsert_investor(name: str, *, type: str | None = None, domain: str | None = None,
                    partner: str | None = None, location: str | None = None,
                    target_amount: float | None = None, notes: str | None = None,
                    path: str | Path | None = None) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("investor name is required")
    domain = (domain or "").strip().lower().lstrip("@") or None
    with _WRITE_LOCK, session(path) as conn:
        row = conn.execute(
            "SELECT id FROM investors WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        now = _now()
        if row:
            iid = row["id"]
            updates, params = [], []
            for field, value in (("type", type), ("domain", domain), ("partner", partner),
                                 ("location", location), ("target_amount", target_amount),
                                 ("notes", notes)):
                value = _norm(value)
                if value is not None:
                    updates.append(f"{field} = ?")
                    params.append(value)
            updates.append("updated_at = ?")
            params.extend([now, iid])
            conn.execute(f"UPDATE investors SET {', '.join(updates)} WHERE id = ?", params)
            log(conn, "investors", iid, "update", {"name": name})
            return iid
        cur = conn.execute(
            "INSERT INTO investors(name, type, domain, partner, location, target_amount, notes, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (name, _norm(type), domain, _norm(partner), _norm(location),
             _norm(target_amount), _norm(notes), now, now),
        )
        log(conn, "investors", cur.lastrowid, "create", {"name": name})
        return int(cur.lastrowid)


def delete_investor(investor_id: int, path: str | Path | None = None) -> None:
    with _WRITE_LOCK, session(path) as conn:
        conn.execute("DELETE FROM investors WHERE id = ?", (investor_id,))
        log(conn, "investors", investor_id, "delete")


def list_investors(path: str | Path | None = None) -> pd.DataFrame:
    return query_df("SELECT * FROM investors ORDER BY name", path=path)


def find_investor_by_domain(domain: str, path: str | Path | None = None) -> int | None:
    domain = (domain or "").strip().lower().lstrip("@")
    if not domain:
        return None
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT id FROM investors WHERE domain = ? COLLATE NOCASE", (domain,)
        ).fetchone()
    finally:
        conn.close()
    return int(row["id"]) if row else None


# --- Conversations -----------------------------------------------------------

def add_conversation(data: Mapping[str, Any], path: str | Path | None = None,
                     actor: str = "app") -> int:
    with _WRITE_LOCK, session(path) as conn:
        return _insert_conversation(conn, data, actor=actor)


def _insert_conversation(conn: sqlite3.Connection, data: Mapping[str, Any],
                         actor: str = "app") -> int:
    payload = {k: _norm(data.get(k)) for k in CONVERSATION_FIELDS}
    if not payload.get("occurred_on"):
        raise ValueError("occurred_on is required")
    payload["source"] = payload.get("source") or config.SOURCE_MANUAL
    now = _now()
    cols = ", ".join(CONVERSATION_FIELDS + ["created_at", "updated_at"])
    marks = ", ".join(["?"] * (len(CONVERSATION_FIELDS) + 2))
    cur = conn.execute(
        f"INSERT INTO conversations({cols}) VALUES({marks})",
        [payload[k] for k in CONVERSATION_FIELDS] + [now, now],
    )
    log(conn, "conversations", cur.lastrowid, "create",
        {"source": payload["source"], "occurred_on": payload["occurred_on"]}, actor)
    return int(cur.lastrowid)


def update_conversation(conv_id: int, data: Mapping[str, Any],
                        path: str | Path | None = None, actor: str = "app") -> None:
    fields = {k: _norm(v) for k, v in data.items() if k in CONVERSATION_FIELDS}
    if not fields:
        return
    with _WRITE_LOCK, session(path) as conn:
        before = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
        if before is None:
            raise KeyError(f"conversation {conv_id} not found")
        assignments = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE conversations SET {assignments}, updated_at = ? WHERE id = ?",
            list(fields.values()) + [_now(), conv_id],
        )
        changed = {k: {"from": before[k], "to": v}
                   for k, v in fields.items() if before[k] != v}
        if changed:
            log(conn, "conversations", conv_id, "update", changed, actor)


def delete_conversation(conv_id: int, path: str | Path | None = None,
                        actor: str = "app") -> None:
    with _WRITE_LOCK, session(path) as conn:
        conn.execute(
            "UPDATE calendar_events SET conversation_id = NULL, review_status = ? "
            "WHERE conversation_id = ?",
            (config.REVIEW_PENDING, conv_id),
        )
        conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        log(conn, "conversations", conv_id, "delete", None, actor)


def conversation_id_for_source(source: str, source_key: str,
                               path: str | Path | None = None) -> int | None:
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT id FROM conversations WHERE source = ? AND source_key = ?",
            (source, source_key),
        ).fetchone()
    finally:
        conn.close()
    return int(row["id"]) if row else None


CONVERSATIONS_SQL = """
SELECT c.*,
       p.name AS person,
       i.name AS investor,
       i.type AS investor_type,
       i.domain AS investor_domain
FROM conversations c
LEFT JOIN people p ON p.id = c.person_id
LEFT JOIN investors i ON i.id = c.investor_id
ORDER BY c.occurred_on DESC, c.id DESC
"""


def list_conversations(path: str | Path | None = None) -> pd.DataFrame:
    df = query_df(CONVERSATIONS_SQL, path=path)
    if df.empty:
        # Give callers a stable set of columns so downstream code never has to
        # special-case the empty database.
        cols = ["id", *CONVERSATION_FIELDS, "created_at", "updated_at",
                "person", "investor", "investor_type", "investor_domain"]
        return pd.DataFrame({c: pd.Series(dtype="object") for c in cols})
    df["occurred_on"] = pd.to_datetime(df["occurred_on"], errors="coerce", format="mixed")
    df["next_step_due"] = pd.to_datetime(df["next_step_due"], errors="coerce", format="mixed")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    return df


# --- Calendar events ---------------------------------------------------------

CAL_FIELDS = [
    "uid", "calendar_id", "person_id", "title", "description", "location",
    "starts_at", "ends_at", "attendees", "organizer", "score", "reasons",
    "suggested_investor_id",
]


def upsert_calendar_event(event: Mapping[str, Any], path: str | Path | None = None) -> int:
    """Store a fetched calendar event, refreshing its classification.

    A re-sync must never resurrect an event the user already triaged, so
    ``review_status`` and ``conversation_id`` are left untouched on update.
    """
    with _WRITE_LOCK, session(path) as conn:
        return _upsert_calendar_event(conn, event)


def _row_exists(conn: sqlite3.Connection, table: str, row_id: Any) -> bool:
    if row_id is None:
        return False
    found = conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return found is not None


def _upsert_calendar_event(conn: sqlite3.Connection, event: Mapping[str, Any]) -> int:
    payload = {k: _norm(event.get(k)) for k in CAL_FIELDS}
    if not payload.get("uid"):
        raise ValueError("calendar event uid is required")
    # A person or investor may have been deleted since the classifier read them.
    # Drop the dangling reference rather than aborting the whole sync over it.
    for field, table in (("person_id", "people"), ("suggested_investor_id", "investors")):
        if payload[field] is not None and not _row_exists(conn, table, payload[field]):
            payload[field] = None
    now = _now()
    row = conn.execute(
        "SELECT id FROM calendar_events WHERE uid = ?", (payload["uid"],)
    ).fetchone()
    if row:
        assignments = ", ".join(f"{k} = ?" for k in CAL_FIELDS if k != "uid")
        conn.execute(
            f"UPDATE calendar_events SET {assignments}, fetched_at = ? WHERE id = ?",
            [payload[k] for k in CAL_FIELDS if k != "uid"] + [now, row["id"]],
        )
        return int(row["id"])
    cols = ", ".join(CAL_FIELDS + ["review_status", "fetched_at"])
    marks = ", ".join(["?"] * (len(CAL_FIELDS) + 2))
    cur = conn.execute(
        f"INSERT INTO calendar_events({cols}) VALUES({marks})",
        [payload[k] for k in CAL_FIELDS] + [config.REVIEW_PENDING, now],
    )
    return int(cur.lastrowid)


CAL_EVENTS_SQL = """
SELECT e.*, p.name AS person, i.name AS suggested_investor
FROM calendar_events e
LEFT JOIN people p ON p.id = e.person_id
LEFT JOIN investors i ON i.id = e.suggested_investor_id
{where}
ORDER BY e.starts_at DESC
"""


def list_calendar_events(review_status: str | None = None,
                         path: str | Path | None = None) -> pd.DataFrame:
    where, params = "", []
    if review_status:
        where, params = "WHERE e.review_status = ?", [review_status]
    df = query_df(CAL_EVENTS_SQL.format(where=where), params, path=path)
    if not df.empty:
        df["starts_at"] = pd.to_datetime(df["starts_at"], errors="coerce", format="mixed", utc=True)
        df["ends_at"] = pd.to_datetime(df["ends_at"], errors="coerce", format="mixed", utc=True)
    return df


def set_review_status(event_ids: Iterable[int], status: str,
                      path: str | Path | None = None) -> int:
    ids = [int(i) for i in event_ids]
    if not ids:
        return 0
    with _WRITE_LOCK, session(path) as conn:
        marks = ",".join("?" * len(ids))
        cur = conn.execute(
            f"UPDATE calendar_events SET review_status = ? WHERE id IN ({marks})",
            [status, *ids],
        )
        log(conn, "calendar_events", None, f"review:{status}", {"ids": ids})
        return cur.rowcount


def link_event_to_conversation(event_id: int, conv_id: int,
                               path: str | Path | None = None) -> None:
    with _WRITE_LOCK, session(path) as conn:
        conn.execute(
            "UPDATE calendar_events SET conversation_id = ?, review_status = ? WHERE id = ?",
            (conv_id, config.REVIEW_ACCEPTED, event_id),
        )


# --- Import batches ----------------------------------------------------------

def create_batch(source_kind: str, source_ref: str | None, mapping: Any = None,
                 notes: str | None = None, path: str | Path | None = None) -> int:
    with _WRITE_LOCK, session(path) as conn:
        cur = conn.execute(
            "INSERT INTO import_batches(ts, source_kind, source_ref, mapping, notes) "
            "VALUES(?,?,?,?,?)",
            (_now(), source_kind, _norm(source_ref),
             json.dumps(mapping) if mapping is not None else None, _norm(notes)),
        )
        log(conn, "import_batches", cur.lastrowid, "create",
            {"kind": source_kind, "ref": source_ref})
        return int(cur.lastrowid)


def finalise_batch(batch_id: int, *, rows_read: int, rows_inserted: int,
                   rows_updated: int, rows_skipped: int,
                   path: str | Path | None = None) -> None:
    with _WRITE_LOCK, session(path) as conn:
        conn.execute(
            "UPDATE import_batches SET rows_read = ?, rows_inserted = ?, "
            "rows_updated = ?, rows_skipped = ? WHERE id = ?",
            (rows_read, rows_inserted, rows_updated, rows_skipped, batch_id),
        )


def list_batches(path: str | Path | None = None) -> pd.DataFrame:
    return query_df("SELECT * FROM import_batches ORDER BY ts DESC", path=path)


def list_audit(limit: int = 250, path: str | Path | None = None) -> pd.DataFrame:
    return query_df(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", [limit], path=path
    )


def counts(path: str | Path | None = None) -> dict[str, int]:
    conn = connect(path)
    try:
        return {
            table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in ("people", "investors", "conversations",
                          "calendar_events", "import_batches")
        }
    finally:
        conn.close()
