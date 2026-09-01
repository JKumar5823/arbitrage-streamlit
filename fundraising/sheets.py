"""Read a Google Sheet (or any tabular file) and adopt it into the database.

The point of this module is *subsumption*: pull the spreadsheet in once, keep
pulling it while both systems run in parallel, then flip a switch and let the
app own the data. Three properties make that safe:

* **Idempotent.** Every imported row gets a deterministic ``source_key``, so
  re-importing the same sheet updates rows instead of duplicating them.
* **Previewable.** Every import is a dry run first, reporting exactly what would
  be inserted, updated, skipped, and which rows fail validation.
* **Non-destructive.** Edits made in the app are never clobbered by a later
  re-import unless the operator explicitly asks for that.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import pandas as pd

from . import config, db, util

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# The conversation fields an imported sheet can populate, and the header names
# we will auto-detect for each. Detection is a convenience -- the operator always
# confirms the mapping before anything is written.
FIELD_ALIASES: dict[str, list[str]] = {
    "occurred_on": ["date", "meeting date", "conversation date", "occurred", "when",
                    "day", "call date", "last contact", "date of conversation"],
    "person": ["owner", "person", "team member", "who", "rep", "founder",
               "assigned to", "our lead", "lead"],
    "investor": ["investor", "firm", "fund", "organization", "organisation",
                 "company", "account", "investor name", "vc"],
    "counterpart": ["contact", "counterpart", "partner", "investor contact",
                    "person met", "their contact", "name", "email"],
    "channel": ["channel", "type", "meeting type", "medium", "format"],
    "stage": ["stage", "status", "pipeline stage", "step", "phase"],
    "outcome": ["outcome", "result", "disposition", "next status"],
    "amount": ["amount", "check size", "cheque size", "commitment", "raised",
               "soft circle", "allocation", "$", "value"],
    "next_step": ["next step", "next steps", "action", "todo", "follow up",
                  "follow-up", "next action"],
    "next_step_due": ["due", "next step due", "due date", "follow up date",
                      "follow-up date", "deadline"],
    "notes": ["notes", "comments", "detail", "details", "summary", "log"],
    "investor_type": ["investor type", "type of investor", "category", "fund type"],
    "row_key": ["id", "row id", "key", "uuid", "record id"],
}

REQUIRED_FIELDS = ["occurred_on"]

# Values in a "stage" column rarely match our vocabulary exactly; these get the
# common spreadsheet spellings onto the canonical stage list.
STAGE_SYNONYMS = {
    "lead": "Sourced", "sourced": "Sourced", "target": "Sourced",
    "prospect": "Sourced", "researching": "Sourced", "not started": "Sourced",
    "intro": "Intro", "intro requested": "Intro", "warm intro": "Intro",
    "introduced": "Intro", "outreach": "Intro", "contacted": "Intro",
    "first meeting": "First Meeting", "first call": "First Meeting",
    "initial call": "First Meeting", "intro call": "First Meeting",
    "meeting": "First Meeting", "pitched": "First Meeting", "pitch": "First Meeting",
    "follow up": "Follow-up", "follow-up": "Follow-up", "followup": "Follow-up",
    "second meeting": "Follow-up", "second call": "Follow-up",
    "partner meeting": "Partner Meeting", "partner": "Partner Meeting",
    "full partnership": "Partner Meeting", "ic": "Partner Meeting",
    "diligence": "Diligence", "due diligence": "Diligence", "dd": "Diligence",
    "deep dive": "Diligence", "data room": "Diligence",
    "term sheet": "Term Sheet", "termsheet": "Term Sheet", "ts": "Term Sheet",
    "offer": "Term Sheet",
    "committed": "Committed", "closed": "Committed", "closed won": "Committed",
    "won": "Committed", "signed": "Committed", "wired": "Committed",
    "invested": "Committed", "yes": "Committed",
    "passed": "Passed", "pass": "Passed", "closed lost": "Passed",
    "lost": "Passed", "declined": "Passed", "no": "Passed", "rejected": "Passed",
    "dead": "Passed",
}

CHANNEL_SYNONYMS = {
    "call": "Phone Call", "phone": "Phone Call", "phone call": "Phone Call",
    "zoom": "Video Call", "video": "Video Call", "video call": "Video Call",
    "gmeet": "Video Call", "google meet": "Video Call", "meet": "Video Call",
    "teams": "Video Call", "vc": "Video Call",
    "in person": "Meeting", "in-person": "Meeting", "irl": "Meeting",
    "meeting": "Meeting", "coffee": "Meeting", "dinner": "Meeting",
    "email": "Email", "e-mail": "Email", "note": "Email",
    "event": "Event", "conference": "Event", "demo day": "Event",
    "intro": "Intro", "introduction": "Intro", "referral": "Intro",
}


# --- Loading -----------------------------------------------------------------

SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
GID_RE = re.compile(r"[#&?]gid=([0-9]+)")


def parse_sheet_url(url: str) -> tuple[str | None, str | None]:
    """Extract ``(spreadsheet_id, gid)`` from a Google Sheets URL or bare ID."""
    if not url:
        return None, None
    url = url.strip()
    match = SHEET_ID_RE.search(url)
    sheet_id = match.group(1) if match else (url if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", url) else None)
    gid_match = GID_RE.search(url)
    return sheet_id, (gid_match.group(1) if gid_match else None)


def csv_export_url(sheet_id: str, gid: str | None = None) -> str:
    base = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    return f"{base}&gid={gid}" if gid else base


def load_public_sheet(url: str, timeout: int = 30) -> pd.DataFrame:
    """Read a link-shared sheet through its CSV export endpoint (no auth)."""
    import requests

    sheet_id, gid = parse_sheet_url(url)
    if not sheet_id:
        raise ValueError("Could not find a spreadsheet ID in that URL.")
    resp = requests.get(csv_export_url(sheet_id, gid), timeout=timeout)
    if resp.status_code in (401, 403) or "text/html" in resp.headers.get("content-type", ""):
        raise PermissionError(
            "That sheet is not readable without signing in. Either set link "
            "sharing to 'Anyone with the link can view', or connect a service "
            "account and share the sheet with its email address."
        )
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text))


def list_worksheets(service_account_info: Mapping[str, Any], url: str) -> list[str]:
    import gspread
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_info(
        dict(service_account_info), scopes=GOOGLE_SCOPES)
    client = gspread.authorize(creds)
    sheet_id, _ = parse_sheet_url(url)
    book = client.open_by_key(sheet_id)
    return [ws.title for ws in book.worksheets()]


def load_private_sheet(service_account_info: Mapping[str, Any], url: str,
                       worksheet: str | None = None) -> pd.DataFrame:
    """Read a sheet shared with the service account, via the Sheets API."""
    import gspread
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_info(
        dict(service_account_info), scopes=GOOGLE_SCOPES)
    client = gspread.authorize(creds)
    sheet_id, _ = parse_sheet_url(url)
    if not sheet_id:
        raise ValueError("Could not find a spreadsheet ID in that URL.")
    book = client.open_by_key(sheet_id)
    ws = book.worksheet(worksheet) if worksheet else book.sheet1
    records = ws.get_all_records(head=1)
    return pd.DataFrame(records)


def load_upload(file_obj, filename: str) -> pd.DataFrame:
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(file_obj)
    return pd.read_csv(file_obj)


# --- Mapping -----------------------------------------------------------------

def _normalise_header(header: Any) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(header).strip().lower()).strip()


def guess_mapping(columns: Sequence[Any]) -> dict[str, str | None]:
    """Guess which spreadsheet column feeds each conversation field.

    Exact header matches win; otherwise the first column whose name contains an
    alias is used. Each column is claimed at most once so a sheet with both
    "Date" and "Follow-up Date" does not map both to ``occurred_on``.
    """
    normalised = {col: _normalise_header(col) for col in columns}
    taken: set[Any] = set()
    mapping: dict[str, str | None] = {field: None for field in FIELD_ALIASES}

    def claim(field_name: str, predicate) -> None:
        if mapping[field_name] is not None:
            return
        for alias in FIELD_ALIASES[field_name]:
            for col, norm in normalised.items():
                if col not in taken and predicate(alias, norm):
                    mapping[field_name] = col
                    taken.add(col)
                    return

    # Every exact header match is resolved before any loose one, so a sheet with
    # both "Follow-up" and "Follow-up Date" assigns each to the right field
    # regardless of which field is declared first.
    for field_name in FIELD_ALIASES:
        claim(field_name, lambda alias, norm: norm == alias)
    for field_name in FIELD_ALIASES:
        claim(field_name, lambda alias, norm: alias in norm)
    return mapping


def _match_on_word_boundary(key: str, synonyms: dict[str, str]) -> str | None:
    """Find a synonym appearing as whole words in ``key``.

    Boundaries matter: plain substring matching let short synonyms such as "dd"
    (diligence) fire inside unrelated words like "odd". Longer synonyms are
    preferred so "partner meeting" wins over "partner".
    """
    for synonym in sorted(synonyms, key=len, reverse=True):
        if re.search(rf"\b{re.escape(synonym)}\b", key):
            return synonyms[synonym]
    return None


def canonical_stage(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    for stage in config.STAGES:
        if text.lower() == stage.lower():
            return stage
    key = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()
    key = re.sub(r"\s+", " ", key)
    if key in STAGE_SYNONYMS:
        return STAGE_SYNONYMS[key]
    return _match_on_word_boundary(key, STAGE_SYNONYMS)


def canonical_channel(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    for channel in config.CHANNELS:
        if text.lower() == channel.lower():
            return channel
    key = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()
    if key in CHANNEL_SYNONYMS:
        return CHANNEL_SYNONYMS[key]
    return _match_on_word_boundary(key, CHANNEL_SYNONYMS)


# --- Preparation & preview ---------------------------------------------------

@dataclass
class PreparedRow:
    index: int
    data: dict[str, Any]
    person: str | None = None
    investor: str | None = None
    investor_type: str | None = None
    error: str | None = None
    action: str = "insert"          # insert | update | skip | error


@dataclass
class ImportPlan:
    source_ref: str
    mapping: dict[str, str | None]
    rows: list[PreparedRow] = field(default_factory=list)
    unmapped_required: list[str] = field(default_factory=list)

    @property
    def inserts(self) -> int:
        return sum(1 for r in self.rows if r.action == "insert")

    @property
    def updates(self) -> int:
        return sum(1 for r in self.rows if r.action == "update")

    @property
    def skips(self) -> int:
        return sum(1 for r in self.rows if r.action == "skip")

    @property
    def errors(self) -> int:
        return sum(1 for r in self.rows if r.action == "error")

    def preview_frame(self) -> pd.DataFrame:
        if not self.rows:
            return pd.DataFrame(columns=["row", "action", "problem", "date", "person",
                                         "investor", "stage", "channel", "amount"])
        return pd.DataFrame([{
            "row": r.index + 2,          # +2 == spreadsheet row (1-based + header)
            "action": r.action,
            "problem": r.error or "",
            "date": r.data.get("occurred_on"),
            "person": r.person or "",
            "investor": r.investor or "",
            "stage": r.data.get("stage") or "",
            "channel": r.data.get("channel") or "",
            "amount": r.data.get("amount"),
        } for r in self.rows])


def build_plan(frame: pd.DataFrame, mapping: Mapping[str, str | None],
               source_ref: str, path=None) -> ImportPlan:
    """Validate and normalise every row, and decide insert vs update vs skip."""
    mapping = {k: v for k, v in mapping.items()}
    missing = [f for f in REQUIRED_FIELDS if not mapping.get(f)]
    plan = ImportPlan(source_ref=source_ref, mapping=dict(mapping),
                      unmapped_required=missing)
    if missing:
        return plan

    existing_keys = _existing_source_keys(path)

    def cell(row, field_name: str):
        column = mapping.get(field_name)
        if not column or column not in row.index:
            return None
        value = row[column]
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        return value

    seen_keys: set[str] = set()
    for position, (_, row) in enumerate(frame.iterrows()):
        occurred_on = util.to_date_str(cell(row, "occurred_on"))
        person = (str(cell(row, "person")).strip() if cell(row, "person") else None) or None
        investor = (str(cell(row, "investor")).strip() if cell(row, "investor") else None) or None

        explicit_key = cell(row, "row_key")
        if explicit_key not in (None, ""):
            source_key = f"{source_ref}#{str(explicit_key).strip()}"
        else:
            # No stable ID in the sheet, so derive one from the row's identity.
            # Deliberately excludes free-text notes: editing a note in the sheet
            # should update the existing conversation, not create a second one.
            source_key = f"{source_ref}#{util.stable_key(occurred_on, person, investor, position)}"

        data = {
            "occurred_on": occurred_on,
            "counterpart": _text(cell(row, "counterpart")),
            "channel": canonical_channel(cell(row, "channel")),
            "stage": canonical_stage(cell(row, "stage")),
            "outcome": _text(cell(row, "outcome")),
            "amount": util.coerce_amount(cell(row, "amount")),
            "next_step": _text(cell(row, "next_step")),
            "next_step_due": util.to_date_str(cell(row, "next_step_due")),
            "notes": _text(cell(row, "notes")),
            "source": config.SOURCE_SHEET,
            "source_key": source_key,
        }

        prepared = PreparedRow(index=position, data=data, person=person,
                               investor=investor,
                               investor_type=_text(cell(row, "investor_type")))

        if not occurred_on:
            raw = cell(row, "occurred_on")
            prepared.action = "error"
            prepared.error = ("no date" if raw in (None, "")
                              else f"unreadable date {raw!r}")
        elif source_key in seen_keys:
            prepared.action = "skip"
            prepared.error = "duplicate of an earlier row in this sheet"
        elif source_key in existing_keys:
            prepared.action = "update"
        seen_keys.add(source_key)
        plan.rows.append(prepared)
    return plan


def _text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _existing_source_keys(path=None) -> set[str]:
    frame = db.query_df(
        "SELECT source_key FROM conversations WHERE source = ? AND source_key IS NOT NULL",
        [config.SOURCE_SHEET], path=path)
    return set(frame["source_key"].tolist()) if not frame.empty else set()


# --- Applying ----------------------------------------------------------------

@dataclass
class ImportResult:
    batch_id: int
    rows_read: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    people_created: int = 0
    investors_created: int = 0


def apply_plan(plan: ImportPlan, source_kind: str = "google_sheet",
               overwrite_edits: bool = False, path=None) -> ImportResult:
    """Write the plan to the database inside one transaction.

    ``overwrite_edits`` decides what an update does to a row someone has since
    corrected by hand in the app. Left off (the default), a re-import only fills
    fields that are still empty, so the sheet can never undo a human edit.
    """
    batch_id = db.create_batch(source_kind, plan.source_ref, plan.mapping, path=path)
    result = ImportResult(batch_id=batch_id, rows_read=len(plan.rows))

    person_ids: dict[str, int] = {}
    investor_ids: dict[str, int] = {}

    for row in plan.rows:
        if row.action == "error":
            result.failed += 1
            continue
        if row.action == "skip":
            result.skipped += 1
            continue

        person_id = None
        if row.person:
            key = row.person.lower()
            if key not in person_ids:
                before = db.query_df("SELECT id FROM people WHERE name = ? COLLATE NOCASE",
                                     [row.person], path=path)
                person_ids[key] = db.upsert_person(row.person, path=path)
                if before.empty:
                    result.people_created += 1
            person_id = person_ids[key]

        investor_id = None
        if row.investor:
            key = row.investor.lower()
            if key not in investor_ids:
                before = db.query_df("SELECT id FROM investors WHERE name = ? COLLATE NOCASE",
                                     [row.investor], path=path)
                investor_ids[key] = db.upsert_investor(
                    row.investor, type=row.investor_type, path=path)
                if before.empty:
                    result.investors_created += 1
            investor_id = investor_ids[key]

        payload = dict(row.data)
        payload["person_id"] = person_id
        payload["investor_id"] = investor_id
        payload["batch_id"] = batch_id

        with db._WRITE_LOCK, db.session(path) as conn:
            existing = conn.execute(
                "SELECT * FROM conversations WHERE source = ? AND source_key = ?",
                (config.SOURCE_SHEET, payload["source_key"]),
            ).fetchone()
            if existing is None:
                db._insert_conversation(conn, payload, actor="sheet-import")
                result.inserted += 1
                continue

            updates = {}
            for field_name, value in payload.items():
                if field_name in ("source", "source_key"):
                    continue
                value = db._norm(value)
                if value is None:
                    continue
                if overwrite_edits or existing[field_name] in (None, ""):
                    if existing[field_name] != value:
                        updates[field_name] = value
            if updates:
                assignments = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE conversations SET {assignments}, updated_at = ? WHERE id = ?",
                    list(updates.values()) + [db._now(), existing["id"]])
                db.log(conn, "conversations", existing["id"], "update",
                       {"fields": sorted(updates)}, "sheet-import")
                result.updated += 1
            else:
                result.skipped += 1

    db.finalise_batch(batch_id, rows_read=result.rows_read, rows_inserted=result.inserted,
                      rows_updated=result.updated,
                      rows_skipped=result.skipped + result.failed, path=path)
    return result


# --- Becoming the system of record ------------------------------------------

def adopt_as_system_of_record(source_ref: str, path=None) -> str:
    """Record the cutover moment. After this the sheet is a historical artefact."""
    stamp = util.utcnow().isoformat(timespec="seconds")
    db.set_setting(config.S_SOR_ADOPTED_AT, stamp, path=path)
    db.set_setting(config.S_SOR_SOURCE, source_ref, path=path)
    with db._WRITE_LOCK, db.session(path) as conn:
        db.log(conn, "settings", None, "adopt_system_of_record",
               {"source": source_ref, "at": stamp})
    return stamp


def release_system_of_record(path=None) -> None:
    db.set_setting(config.S_SOR_ADOPTED_AT, None, path=path)
    db.set_setting(config.S_SOR_SOURCE, None, path=path)


def is_system_of_record(path=None) -> bool:
    return bool(db.get_setting(config.S_SOR_ADOPTED_AT, path=path))
