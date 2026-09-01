"""Read meetings out of people's calendars and decide which ones are fundraising.

Three ways in, so the dashboard works whether or not anyone has Google Cloud
admin rights:

* **Google Calendar API** with a service account (optionally impersonating a
  user via domain-wide delegation). Best fidelity: real attendee lists, and
  recurring meetings are expanded server-side.
* **Secret ICS URL** -- the "Secret address in iCal format" every Google
  Calendar user can copy from their own calendar settings. No admin needed.
* **CSV upload** -- an exported event list, for calendars we cannot reach.

Nothing here writes conversations. Fetched events land in a review queue and a
human accepts them, which keeps the counts honest and matches the ask that the
numbers stay manually confirmable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from . import config, db, util

GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


# --- Normalised event --------------------------------------------------------

@dataclass
class CalendarEvent:
    """One meeting, in the shape the rest of the app expects."""

    uid: str
    title: str = ""
    description: str = ""
    location: str = ""
    starts_at: str | None = None
    ends_at: str | None = None
    attendees: list[str] = field(default_factory=list)
    organizer: str = ""
    calendar_id: str = ""
    person_id: int | None = None

    def as_row(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "calendar_id": self.calendar_id,
            "person_id": self.person_id,
            "title": self.title,
            "description": self.description,
            "location": self.location,
            "starts_at": self.starts_at,
            "ends_at": self.ends_at,
            "attendees": json.dumps(self.attendees),
            "organizer": self.organizer,
        }


# --- Classification ----------------------------------------------------------

@dataclass
class Classifier:
    """Scores an event on how likely it is to be a fundraising conversation.

    Transparent on purpose: every point added or removed is recorded as a
    human-readable reason, shown next to the event in the review queue, so a
    misfire tells you which keyword to edit rather than leaving you guessing.
    """

    include_keywords: Sequence[str]
    exclude_keywords: Sequence[str]
    watchlist_domains: Sequence[str] = ()
    home_domains: Sequence[str] = ()
    investor_domains: Mapping[str, int] = field(default_factory=dict)
    weights: Mapping[str, float] = field(default_factory=lambda: dict(config.DEFAULT_SCORE_WEIGHTS))
    threshold: float = config.DEFAULT_SCORE_THRESHOLD

    @classmethod
    def from_db(cls, path=None) -> "Classifier":
        settings = db.all_settings(path)
        investors = db.list_investors(path)
        domains: dict[str, int] = {}
        if not investors.empty:
            for _, row in investors.iterrows():
                domain = util.clean_domain(row.get("domain"))
                if domain:
                    domains[domain] = int(row["id"])
        return cls(
            include_keywords=settings.get(config.S_INCLUDE_KEYWORDS, config.DEFAULT_INCLUDE_KEYWORDS),
            exclude_keywords=settings.get(config.S_EXCLUDE_KEYWORDS, config.DEFAULT_EXCLUDE_KEYWORDS),
            watchlist_domains=[util.clean_domain(d) for d in settings.get(config.S_WATCHLIST_DOMAINS, [])],
            home_domains=[util.clean_domain(d) for d in settings.get(config.S_HOME_DOMAINS, [])],
            investor_domains=domains,
            weights={**config.DEFAULT_SCORE_WEIGHTS, **(settings.get(config.S_SCORE_WEIGHTS) or {})},
            threshold=float(settings.get(config.S_SCORE_THRESHOLD, config.DEFAULT_SCORE_THRESHOLD)),
        )

    def _weight(self, key: str) -> float:
        return float(self.weights.get(key, config.DEFAULT_SCORE_WEIGHTS.get(key, 0.0)))

    def score(self, event: CalendarEvent) -> tuple[float, list[str], int | None]:
        """Return ``(score, reasons, suggested_investor_id)``."""
        title = (event.title or "").lower()
        body = " ".join(filter(None, [(event.description or "").lower(),
                                      (event.location or "").lower()]))
        total = 0.0
        reasons: list[str] = []

        title_hits = sorted({kw for kw in self.include_keywords if kw and kw.lower() in title})
        if title_hits:
            total += self._weight("keyword_title")
            reasons.append(f"title matches {', '.join(repr(k) for k in title_hits[:3])}")

        body_hits = sorted({kw for kw in self.include_keywords
                            if kw and kw.lower() in body and kw not in title_hits})
        if body_hits:
            total += self._weight("keyword_description")
            reasons.append(f"details mention {', '.join(repr(k) for k in body_hits[:3])}")

        blocked = sorted({kw for kw in self.exclude_keywords
                          if kw and (kw.lower() in title or kw.lower() in body)})
        if blocked:
            total += self._weight("exclude_keyword")
            reasons.append(f"looks internal: {', '.join(repr(k) for k in blocked[:3])}")

        # Attendee analysis. Guests are the strongest signal available: a known
        # investor domain on the invite is worth more than any keyword.
        home = {d for d in self.home_domains if d}
        suggested: int | None = None
        matched_investor_domains: list[str] = []
        watchlist_hits: list[str] = []
        external = 0
        for address in self._guest_addresses(event):
            domain = util.domain_of(address)
            if not domain or domain in home:
                continue
            if domain in self.investor_domains:
                matched_investor_domains.append(domain)
                suggested = suggested or self.investor_domains[domain]
            elif domain in set(self.watchlist_domains):
                watchlist_hits.append(domain)
            elif not util.is_generic_domain(domain):
                external += 1

        if matched_investor_domains:
            total += self._weight("known_investor_domain")
            reasons.append(f"guest from known investor {sorted(set(matched_investor_domains))[0]}")
        if watchlist_hits:
            total += self._weight("watchlist_domain")
            reasons.append(f"guest from watchlist domain {sorted(set(watchlist_hits))[0]}")
        if external and not matched_investor_domains:
            total += self._weight("external_guest")
            reasons.append(f"{external} external guest(s)")

        if not reasons:
            reasons.append("no fundraising signal found")
        return round(total, 2), reasons, suggested

    def _guest_addresses(self, event: CalendarEvent) -> list[str]:
        addresses = list(event.attendees or [])
        if event.organizer:
            addresses.append(event.organizer)
        # Invites pasted into the body (common with forwarded intros) still count.
        addresses.extend(util.emails_in(event.description))
        return [a.lower() for a in addresses if a]

    def is_fundraising(self, event: CalendarEvent) -> bool:
        return self.score(event)[0] >= self.threshold


# --- Source: Google Calendar API --------------------------------------------

def google_credentials(service_account_info: Mapping[str, Any],
                       impersonate: str | None = None):
    """Build read-only Calendar credentials from a service-account key."""
    from google.oauth2 import service_account  # imported lazily: optional dependency

    creds = service_account.Credentials.from_service_account_info(
        dict(service_account_info), scopes=GOOGLE_SCOPES
    )
    if impersonate:
        creds = creds.with_subject(impersonate)
    return creds


def list_google_calendars(service_account_info: Mapping[str, Any],
                          impersonate: str | None = None) -> list[dict[str, str]]:
    from googleapiclient.discovery import build

    service = build("calendar", "v3",
                    credentials=google_credentials(service_account_info, impersonate),
                    cache_discovery=False)
    out, token = [], None
    while True:
        resp = service.calendarList().list(pageToken=token, maxResults=250).execute()
        for item in resp.get("items", []):
            out.append({"id": item.get("id", ""),
                        "summary": item.get("summary", item.get("id", "")),
                        "access": item.get("accessRole", "")})
        token = resp.get("nextPageToken")
        if not token:
            return out


def fetch_google_events(service_account_info: Mapping[str, Any], calendar_id: str,
                        start: datetime, end: datetime,
                        impersonate: str | None = None,
                        person_id: int | None = None) -> list[CalendarEvent]:
    """Pull events in a window. ``singleEvents`` expands recurrences for us."""
    from googleapiclient.discovery import build

    service = build("calendar", "v3",
                    credentials=google_credentials(service_account_info, impersonate),
                    cache_discovery=False)
    events: list[CalendarEvent] = []
    token = None
    while True:
        resp = service.events().list(
            calendarId=calendar_id,
            timeMin=util.as_aware(start).isoformat(),
            timeMax=util.as_aware(end).isoformat(),
            singleEvents=True,
            orderBy="startTime",
            showDeleted=False,
            maxResults=2500,
            pageToken=token,
        ).execute()
        for item in resp.get("items", []):
            if item.get("status") == "cancelled":
                continue
            events.append(_from_google_item(item, calendar_id, person_id))
        token = resp.get("nextPageToken")
        if not token:
            return events


def _from_google_item(item: Mapping[str, Any], calendar_id: str,
                      person_id: int | None) -> CalendarEvent:
    def stamp(node: Mapping[str, Any] | None) -> str | None:
        if not node:
            return None
        return util.to_iso(node.get("dateTime") or node.get("date"))

    attendees = [a.get("email", "").lower()
                 for a in item.get("attendees", []) or []
                 if a.get("email") and not a.get("resource")]
    return CalendarEvent(
        uid=f"gcal:{calendar_id}:{item.get('id', '')}",
        title=item.get("summary", "") or "",
        description=item.get("description", "") or "",
        location=item.get("location", "") or "",
        starts_at=stamp(item.get("start")),
        ends_at=stamp(item.get("end")),
        attendees=attendees,
        organizer=(item.get("organizer") or {}).get("email", "") or "",
        calendar_id=calendar_id,
        person_id=person_id,
    )


# --- Source: ICS -------------------------------------------------------------

def fetch_ics_text(url: str, timeout: int = 30) -> str:
    """Download an ICS feed. Accepts the ``webcal://`` scheme Google hands out."""
    import requests

    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def parse_ics(text: str | bytes, calendar_id: str = "ics",
              person_id: int | None = None,
              start: datetime | None = None,
              end: datetime | None = None,
              max_occurrences: int = 200) -> list[CalendarEvent]:
    """Parse an ICS document, expanding simple recurrences into the window."""
    from icalendar import Calendar

    cal = Calendar.from_ical(text)
    window_start = util.as_aware(start) or (util.utcnow() - timedelta(days=365))
    window_end = util.as_aware(end) or (util.utcnow() + timedelta(days=120))

    events: list[CalendarEvent] = []
    for component in cal.walk("VEVENT"):
        if str(component.get("STATUS", "")).upper() == "CANCELLED":
            continue
        base_uid = str(component.get("UID", "") or util.stable_key(
            component.get("SUMMARY"), component.get("DTSTART")))
        dtstart = _ical_dt(component.get("DTSTART"))
        dtend = _ical_dt(component.get("DTEND"))
        if dtstart is None:
            continue
        duration = (dtend - dtstart) if dtend else timedelta(hours=1)

        attendees = []
        raw_attendees = component.get("ATTENDEE")
        for entry in (raw_attendees if isinstance(raw_attendees, list) else [raw_attendees]):
            if entry is None:
                continue
            address = str(entry).replace("MAILTO:", "").replace("mailto:", "").strip()
            if "@" in address:
                attendees.append(address.lower())
        organizer = str(component.get("ORGANIZER", "") or "")
        organizer = organizer.replace("MAILTO:", "").replace("mailto:", "").strip().lower()

        for occurrence in _occurrences(component, dtstart, window_start, window_end,
                                       max_occurrences):
            events.append(CalendarEvent(
                uid=f"ics:{calendar_id}:{base_uid}:{occurrence.date().isoformat()}",
                title=str(component.get("SUMMARY", "") or ""),
                description=str(component.get("DESCRIPTION", "") or ""),
                location=str(component.get("LOCATION", "") or ""),
                starts_at=occurrence.isoformat(),
                ends_at=(occurrence + duration).isoformat(),
                attendees=attendees,
                organizer=organizer,
                calendar_id=calendar_id,
                person_id=person_id,
            ))
    return events


def _ical_dt(value) -> datetime | None:
    if value is None:
        return None
    return util.as_aware(getattr(value, "dt", value))


def _occurrences(component, dtstart: datetime, window_start: datetime,
                 window_end: datetime, cap: int) -> list[datetime]:
    """Expand an RRULE into the window, or return the single occurrence."""
    rrule_prop = component.get("RRULE")
    if not rrule_prop:
        return [dtstart] if window_start <= dtstart <= window_end else []
    try:
        from dateutil.rrule import rrulestr

        rule_text = rrule_prop.to_ical().decode() if hasattr(rrule_prop, "to_ical") else str(rrule_prop)
        rule = rrulestr(rule_text, dtstart=dtstart)
        found = list(rule.between(window_start, window_end, inc=True))[:cap]
        return [util.as_aware(d) for d in found]
    except Exception:
        # A malformed or exotic rule should degrade to the base event, never
        # abort the whole sync.
        return [dtstart] if window_start <= dtstart <= window_end else []


# --- Source: CSV -------------------------------------------------------------

CSV_ALIASES = {
    "title": ["title", "summary", "subject", "event", "event name", "meeting"],
    "starts_at": ["start", "starts_at", "start time", "start date", "date", "when"],
    "ends_at": ["end", "ends_at", "end time", "end date"],
    "description": ["description", "notes", "details", "agenda"],
    "location": ["location", "where", "place"],
    "attendees": ["attendees", "guests", "participants", "invitees", "emails"],
    "organizer": ["organizer", "organiser", "creator", "host"],
}


def parse_events_frame(frame: pd.DataFrame, calendar_id: str = "csv",
                       person_id: int | None = None) -> list[CalendarEvent]:
    """Turn an exported event table into events, guessing the column names."""
    lookup = {str(c).strip().lower(): c for c in frame.columns}
    resolved = {
        field_name: next((lookup[a] for a in aliases if a in lookup), None)
        for field_name, aliases in CSV_ALIASES.items()
    }
    events = []
    for idx, row in frame.iterrows():
        def cell(name: str) -> str:
            column = resolved.get(name)
            if column is None:
                return ""
            value = row[column]
            return "" if pd.isna(value) else str(value)

        title = cell("title")
        starts_at = util.to_iso(cell("starts_at")) if cell("starts_at") else None
        if not title and not starts_at:
            continue
        attendees = util.emails_in(cell("attendees"))
        events.append(CalendarEvent(
            uid=f"csv:{calendar_id}:{util.stable_key(title, starts_at, idx)}",
            title=title,
            description=cell("description"),
            location=cell("location"),
            starts_at=starts_at,
            ends_at=util.to_iso(cell("ends_at")) if cell("ends_at") else None,
            attendees=attendees,
            organizer=(util.emails_in(cell("organizer")) or [""])[0],
            calendar_id=calendar_id,
            person_id=person_id,
        ))
    return events


# --- Persisting a sync -------------------------------------------------------

@dataclass
class SyncResult:
    fetched: int = 0
    stored: int = 0
    flagged: int = 0
    errors: list[str] = field(default_factory=list)


def store_events(events: Iterable[CalendarEvent], classifier: Classifier,
                 only_fundraising: bool = True, path=None) -> SyncResult:
    """Classify events and persist the interesting ones into the review queue."""
    result = SyncResult()
    with db._WRITE_LOCK, db.session(path) as conn:
        for event in events:
            result.fetched += 1
            score, reasons, suggested = classifier.score(event)
            if only_fundraising and score < classifier.threshold:
                continue
            row = event.as_row()
            row.update({"score": score, "reasons": json.dumps(reasons),
                        "suggested_investor_id": suggested})
            db._upsert_calendar_event(conn, row)
            result.stored += 1
            if score >= classifier.threshold:
                result.flagged += 1
        db.log(conn, "calendar_events", None, "sync",
               {"fetched": result.fetched, "stored": result.stored})
    return result


def accept_events(event_ids: Sequence[int], defaults: Mapping[str, Any] | None = None,
                  path=None) -> list[int]:
    """Promote reviewed calendar events into conversations.

    Idempotent: an event already linked to a conversation is skipped rather than
    counted twice, so a double-click never inflates the numbers.
    """
    defaults = dict(defaults or {})
    created: list[int] = []
    with db._WRITE_LOCK, db.session(path) as conn:
        for event_id in event_ids:
            row = conn.execute(
                "SELECT * FROM calendar_events WHERE id = ?", (int(event_id),)
            ).fetchone()
            if row is None or row["conversation_id"] is not None:
                continue
            source_key = row["uid"]
            existing = conn.execute(
                "SELECT id FROM conversations WHERE source = ? AND source_key = ?",
                (config.SOURCE_CALENDAR, source_key),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE calendar_events SET conversation_id = ?, review_status = ? WHERE id = ?",
                    (existing["id"], config.REVIEW_ACCEPTED, row["id"]),
                )
                continue
            attendees = json.loads(row["attendees"] or "[]")
            counterpart = next(
                (a for a in attendees
                 if util.domain_of(a) and not util.is_generic_domain(util.domain_of(a))),
                attendees[0] if attendees else None,
            )
            conv_id = db._insert_conversation(conn, {
                "occurred_on": (row["starts_at"] or "")[:10] or None,
                "person_id": row["person_id"],
                "investor_id": row["suggested_investor_id"],
                "counterpart": counterpart,
                "channel": defaults.get("channel", "Meeting"),
                "stage": defaults.get("stage", "First Meeting"),
                "outcome": defaults.get("outcome", "Unknown"),
                "notes": row["title"],
                "source": config.SOURCE_CALENDAR,
                "source_key": source_key,
            }, actor="calendar-sync")
            conn.execute(
                "UPDATE calendar_events SET conversation_id = ?, review_status = ? WHERE id = ?",
                (conv_id, config.REVIEW_ACCEPTED, row["id"]),
            )
            created.append(conv_id)
    return created
