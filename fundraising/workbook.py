"""Import the FUIFOAA master workbook.

The workbook is not a flat conversation log -- it is a set of campaign sheets
where **one row is one lead** and roughly forty dated columns record when that
lead entered each stage. This module turns that shape into the app's model:

* one ``leads`` row per workbook row, carrying grade, firm, connector and the
  furthest stage reached;
* one ``conversations`` row of ``kind='stage'`` per dated stage cell, which is
  the transition history the funnel is built from;
* one ``conversations`` row of ``kind='meeting'`` per meeting that actually
  happened, which is what the headline conversation count reports.

Meetings are read from the explicit "1st..4th Meeting Date" columns, falling
back to the stage-entry date when a meeting stage was reached but no date was
recorded. Stage rows are never counted as meetings, so nothing is double
counted.

``Exp_Calendar`` is a Google Calendar sync that already lives in the workbook,
so it is loaded straight into ``calendar_events``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

import pandas as pd

from . import config, db, pipeline, util

# Lead attributes, mapped from the header names the workbook uses. Sheets vary
# in which of these they carry, so every one is optional.
LEAD_COLUMNS = {
    "name": ["Name"],
    "firm": ["Relevant Firm"],
    "campaign": ["Campaign"],
    "wave": ["Wave"],
    "title": ["Relevant Title"],
    "location": ["Location"],
    "emails": ["Emails"],
    "linkedin": ["LinkedIn"],
    "grade": ["Grade"],
    "score": ["Score"],
    "investor_types": ["Investor Types"],
    "check_size": ["Est. \nCheck Size", "Est. Check Size", "Est Check Size"],
    "check_upper": ["Est Upper Limit"],
    "committed": ["Committed Investment"],
    "connector": ["Connector"],
    "status": ["Status"],
    "owner": ["Owner of Next Steps"],
    "notes": ["Notes"],
    "last_updated": ["Date Last Updated"],
}

# Explicit meeting-date columns, in order. These are the authoritative record of
# meetings that took place.
MEETING_DATE_COLUMNS = [
    ("1st Meeting Date", "1st meeting"),
    ("2nd Meeting Date", "2nd meeting"),
    ("3rd Meeting Date", "3rd meeting"),
    ("4th Meeting Date", "4th meeting"),
]

# Stage labels that mean a meeting happened, used only when the matching
# meeting-date cell is blank.
MEETING_STAGE_FALLBACK = {
    "1st meeting": ["4.1. 1st Meeting Happened", "4.1 Attended Webinar/Met",
                    "4. 1st Interview Happened", "4. Attended, 1-1 Intro Needed"],
    "2nd meeting": ["5.1. 2nd Meeting Happened", "5.1. 2nd Interview Happened"],
}

# Placeholders the workbook uses for "nothing here".
BLANKS = {"", "-", "--", "n/a", "na", "none", "tbd", "?", "nan", "nat"}


@dataclass
class WorkbookReport:
    """What an import did, in enough detail to audit it."""

    batch_id: int | None = None
    sheets: list[str] = field(default_factory=list)
    leads: int = 0
    stage_events: int = 0
    meetings: int = 0
    calendar_events: int = 0
    people: int = 0
    investors: int = 0
    unmapped_labels: dict[str, list[str]] = field(default_factory=dict)
    skipped_rows: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.leads:,} leads · {self.meetings:,} meetings · "
                f"{self.stage_events:,} stage events · "
                f"{self.calendar_events:,} calendar events")


# --- Reading -----------------------------------------------------------------

def _clean(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return None if text.lower() in BLANKS else text


def _pick(row: Mapping[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in row:
            value = _clean(row[name])
            if value is not None:
                return value
    return None


def detect_sheets(book: Mapping[str, pd.DataFrame] | pd.ExcelFile) -> list[str]:
    """Sheets that look like lead pipelines: they carry dated stage columns."""
    names = book.sheet_names if isinstance(book, pd.ExcelFile) else list(book)
    found = []
    for name in names:
        frame = (book.parse(name, nrows=0) if isinstance(book, pd.ExcelFile)
                 else book[name])
        if any(pipeline.is_stage_column(c) for c in frame.columns):
            found.append(name)
    return found


def open_workbook(source: Any) -> pd.ExcelFile:
    return pd.ExcelFile(source)


def preview(source: Any) -> dict[str, Any]:
    """Describe a workbook without importing it, for the confirmation screen."""
    book = open_workbook(source)
    lead_sheets = detect_sheets(book)
    rows: list[dict[str, Any]] = []
    unmapped: dict[str, list[str]] = {}
    for name in lead_sheets:
        frame = book.parse(name)
        missing = pipeline.unknown_labels(frame.columns)
        if missing:
            unmapped[name] = missing
        rows.append({
            "sheet": name,
            "group": pipeline.group_for_sheet(name),
            "leads": int(len(frame)),
            "stage columns": sum(1 for c in frame.columns if pipeline.is_stage_column(c)),
            "unmapped": len(missing),
        })
    calendars = [s for s in book.sheet_names if s in pipeline.CALENDAR_SHEETS]
    calendar_rows = sum(len(book.parse(s)) for s in calendars)
    return {
        "lead_sheets": lead_sheets,
        "calendar_sheets": calendars,
        "calendar_rows": calendar_rows,
        "table": pd.DataFrame(rows),
        "unmapped": unmapped,
    }


# --- Importing ---------------------------------------------------------------

def import_workbook(source: Any, sheets: Iterable[str] | None = None,
                    include_calendar: bool = True, source_ref: str = "workbook",
                    path=None) -> WorkbookReport:
    """Load the workbook into the database. Safe to re-run: keys are stable."""
    book = open_workbook(source)
    lead_sheets = list(sheets) if sheets is not None else detect_sheets(book)
    report = WorkbookReport(sheets=lead_sheets)
    report.batch_id = db.create_batch("fuifoaa_workbook", source_ref,
                                      {"sheets": lead_sheets}, path=path)

    people_cache: dict[str, int] = {}
    investor_cache: dict[str, int] = {}

    for name in lead_sheets:
        try:
            frame = book.parse(name)
        except Exception as exc:                       # pragma: no cover
            report.errors.append(f"{name}: {exc}")
            continue
        missing = pipeline.unknown_labels(frame.columns)
        if missing:
            report.unmapped_labels[name] = missing
        _import_sheet(frame, name, report, people_cache, investor_cache, path)

    if include_calendar:
        for name in book.sheet_names:
            if name in pipeline.CALENDAR_SHEETS:
                report.calendar_events += _import_calendar(book.parse(name), name, path)

    report.people = len(people_cache)
    report.investors = len(investor_cache)
    db.finalise_batch(report.batch_id, rows_read=report.leads,
                      rows_inserted=report.meetings + report.stage_events,
                      rows_updated=0, rows_skipped=report.skipped_rows, path=path)
    return report


def _import_sheet(frame: pd.DataFrame, sheet: str, report: WorkbookReport,
                  people_cache: dict[str, int], investor_cache: dict[str, int],
                  path=None) -> None:
    stage_columns = [c for c in frame.columns if pipeline.is_stage_column(c)]
    group = pipeline.group_for_sheet(sheet)
    records = frame.to_dict("records")

    with db._WRITE_LOCK, db.session(path) as conn:
        for position, row in enumerate(records):
            name = _pick(row, LEAD_COLUMNS["name"])
            if not name:
                report.skipped_rows += 1
                continue

            firm = _pick(row, LEAD_COLUMNS["firm"])
            owner = _pick(row, LEAD_COLUMNS["owner"])
            owner_id = _person_id(conn, owner, people_cache) if owner else None
            investor_id = _investor_id(conn, firm, investor_cache) if firm else None

            status = _pick(row, LEAD_COLUMNS["status"])
            # Furthest point reached: the deepest dated stage, or the current
            # status if that is further along than anything dated.
            reached = max(
                [pipeline.rank_of(c) for c in stage_columns
                 if _clean(row.get(c)) is not None] or [0]
            )
            reached = max(reached, pipeline.rank_of(status) if status else 0)

            source_key = f"{sheet}#{position}#{util.stable_key(name, firm)}"
            lead_id = db.upsert_lead(conn, {
                "name": name,
                "firm": firm,
                "investor_id": investor_id,
                "owner_id": owner_id,
                "campaign": _pick(row, LEAD_COLUMNS["campaign"]) or sheet,
                "campaign_group": group,
                "sheet": sheet,
                "wave": _pick(row, LEAD_COLUMNS["wave"]),
                "title": _pick(row, LEAD_COLUMNS["title"]),
                "location": _pick(row, LEAD_COLUMNS["location"]),
                "emails": _pick(row, LEAD_COLUMNS["emails"]),
                "linkedin": _pick(row, LEAD_COLUMNS["linkedin"]),
                "grade": _pick(row, LEAD_COLUMNS["grade"]),
                "score": util.coerce_amount(_pick(row, LEAD_COLUMNS["score"])),
                "investor_types": _pick(row, LEAD_COLUMNS["investor_types"]),
                "check_size": util.coerce_amount(_pick(row, LEAD_COLUMNS["check_size"])),
                "check_upper": util.coerce_amount(_pick(row, LEAD_COLUMNS["check_upper"])),
                "committed": util.coerce_amount(_pick(row, LEAD_COLUMNS["committed"])),
                "connector": _pick(row, LEAD_COLUMNS["connector"]),
                "status": status,
                "status_rank": reached,
                "terminal": pipeline.terminal_kind(status) if status else None,
                "last_updated": util.to_date_str(_pick(row, LEAD_COLUMNS["last_updated"])),
                "notes": _pick(row, LEAD_COLUMNS["notes"]),
                "source_key": source_key,
            })
            report.leads += 1

            common = {
                "person_id": owner_id, "investor_id": investor_id,
                "counterpart": name, "lead_id": lead_id,
                "source": config.SOURCE_WORKBOOK, "batch_id": report.batch_id,
            }
            report.stage_events += _emit_stage_events(
                conn, row, stage_columns, source_key, common)
            report.meetings += _emit_meetings(
                conn, row, stage_columns, source_key, common)


def _emit_stage_events(conn, row: Mapping[str, Any], stage_columns: list[str],
                       source_key: str, common: Mapping[str, Any]) -> int:
    """One row per dated stage cell -- the lead's transition history."""
    written = 0
    for column in stage_columns:
        occurred = util.to_date_str(row.get(column))
        if not occurred:
            continue
        label = str(column).strip()
        rank = pipeline.rank_of(label)
        step = pipeline.step_for_rank(rank)
        key = f"{source_key}#stage#{label}"
        if _exists(conn, key):
            continue
        db._insert_conversation(conn, {
            **common,
            "occurred_on": occurred,
            "stage": step.label if step else (pipeline.terminal_kind(label) or "Other"),
            "outcome": pipeline.terminal_kind(label),
            "notes": label,
            "kind": config.KIND_STAGE,
            "stage_rank": rank,
            "source_key": key,
        }, actor="workbook-import")
        written += 1
    return written


def _emit_meetings(conn, row: Mapping[str, Any], stage_columns: list[str],
                   source_key: str, common: Mapping[str, Any]) -> int:
    """One row per meeting that actually took place.

    Prefers the explicit meeting-date column; falls back to the date the lead
    entered the matching "happened" stage, so a meeting recorded only as a stage
    transition is still counted exactly once.
    """
    written = 0
    for column, slot in MEETING_DATE_COLUMNS:
        occurred = util.to_date_str(row.get(column)) if column in row else None
        if not occurred:
            for fallback in MEETING_STAGE_FALLBACK.get(slot, []):
                if fallback in stage_columns:
                    occurred = util.to_date_str(row.get(fallback))
                    if occurred:
                        break
        if not occurred:
            continue
        key = f"{source_key}#meeting#{slot}"
        if _exists(conn, key):
            continue
        db._insert_conversation(conn, {
            **common,
            "occurred_on": occurred,
            "channel": "Meeting",
            "stage": "Meeting Happened",
            "stage_rank": pipeline.STEP_BY_KEY["attended"].rank,
            "notes": slot,
            "kind": config.KIND_MEETING,
            "source_key": key,
        }, actor="workbook-import")
        written += 1
    return written


def _exists(conn, source_key: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM conversations WHERE source = ? AND source_key = ?",
        (config.SOURCE_WORKBOOK, source_key),
    ).fetchone() is not None


def _person_id(conn, name: str, cache: dict[str, int]) -> int | None:
    key = name.strip().lower()
    if key in cache:
        return cache[key]
    row = conn.execute(
        "SELECT id FROM people WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if row:
        cache[key] = int(row["id"])
        return cache[key]
    now = db._now()
    cur = conn.execute(
        "INSERT INTO people(name, active, created_at, updated_at) VALUES(?,1,?,?)",
        (name, now, now))
    cache[key] = int(cur.lastrowid)
    return cache[key]


def _investor_id(conn, name: str, cache: dict[str, int]) -> int | None:
    key = name.strip().lower()
    if key in cache:
        return cache[key]
    row = conn.execute(
        "SELECT id FROM investors WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if row:
        cache[key] = int(row["id"])
        return cache[key]
    now = db._now()
    cur = conn.execute(
        "INSERT INTO investors(name, created_at, updated_at) VALUES(?,?,?)",
        (name, now, now))
    cache[key] = int(cur.lastrowid)
    return cache[key]


# --- Calendar ----------------------------------------------------------------

def _import_calendar(frame: pd.DataFrame, sheet: str, path=None) -> int:
    """Load the workbook's existing Google Calendar sync into calendar_events."""
    from . import calendars

    events = []
    for row in frame.to_dict("records"):
        uid = _clean(row.get("Event Key"))
        title = _clean(row.get("Title"))
        if not uid or str(row.get("Sync Status", "")).strip().lower() == "removed":
            continue
        events.append(calendars.CalendarEvent(
            uid=f"wb:{sheet}:{uid}",
            title=title or "",
            description=_clean(row.get("Description")) or "",
            location=_clean(row.get("Location")) or "",
            starts_at=util.to_iso(row.get("Start")),
            ends_at=util.to_iso(row.get("End")),
            attendees=util.emails_in(_clean(row.get("Guests"))),
            organizer=(util.emails_in(_clean(row.get("Organizer"))) or [""])[0],
            calendar_id=_clean(row.get("Calendars")) or sheet,
        ))
    classifier = calendars.Classifier.from_db(path)
    # Everything is stored: these events came from the team's own calendars, and
    # the review queue is where a human decides what counted.
    result = calendars.store_events(events, classifier, only_fundraising=False, path=path)
    return result.stored
