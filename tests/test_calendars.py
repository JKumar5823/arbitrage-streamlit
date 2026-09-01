from datetime import datetime, timezone

from fundraising import calendars, config, db

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:evt-1
SUMMARY:Pitch meeting with Acme Ventures
DESCRIPTION:Series A discussion
DTSTART:20260805T150000Z
DTEND:20260805T160000Z
ATTENDEE;CN=Partner:mailto:partner@acme.vc
ORGANIZER:mailto:jay@startup.com
END:VEVENT
BEGIN:VEVENT
UID:evt-2
SUMMARY:Daily standup
DTSTART:20260806T090000Z
DTEND:20260806T091500Z
ATTENDEE:mailto:dev@startup.com
END:VEVENT
BEGIN:VEVENT
UID:evt-3
SUMMARY:Weekly investor update
DTSTART:20260801T090000Z
DTEND:20260801T093000Z
RRULE:FREQ=WEEKLY;COUNT=3
END:VEVENT
END:VCALENDAR"""

WINDOW = (datetime(2026, 7, 1, tzinfo=timezone.utc),
          datetime(2026, 10, 1, tzinfo=timezone.utc))


def make_classifier():
    return calendars.Classifier(
        include_keywords=["pitch", "series a", "investor"],
        exclude_keywords=["standup"],
        home_domains=["startup.com"],
        investor_domains={"acme.vc": 7},
        threshold=3.0,
    )


def test_investor_domain_outweighs_keywords():
    event = calendars.CalendarEvent(uid="u", title="Coffee",
                                    attendees=["partner@acme.vc"])
    score, reasons, suggested = make_classifier().score(event)
    assert suggested == 7
    assert score >= 3.0
    assert any("known investor" in r for r in reasons)


def test_internal_meeting_is_rejected():
    event = calendars.CalendarEvent(uid="u", title="Daily standup",
                                    attendees=["dev@startup.com"])
    score, reasons, _ = make_classifier().score(event)
    assert score < 0
    assert any("looks internal" in r for r in reasons)


def test_colleagues_are_not_external_guests():
    """A home-domain attendee must not register as an external-guest signal."""
    event = calendars.CalendarEvent(uid="u", title="Chat",
                                    attendees=["colleague@startup.com"])
    score, reasons, _ = make_classifier().score(event)
    assert score == 0.0
    assert reasons == ["no fundraising signal found"]


def test_generic_domains_are_not_external_guests():
    event = calendars.CalendarEvent(uid="u", title="Chat", attendees=["bob@gmail.com"])
    assert make_classifier().score(event)[0] == 0.0


def test_parse_ics_expands_recurrence():
    events = calendars.parse_ics(ICS, calendar_id="jay",
                                 start=WINDOW[0], end=WINDOW[1])
    recurring = [e for e in events if "evt-3" in e.uid]
    assert len(recurring) == 3
    # Each occurrence needs its own uid or the review queue would collapse them.
    assert len({e.uid for e in recurring}) == 3


def test_parse_ics_reads_attendees():
    events = calendars.parse_ics(ICS, start=WINDOW[0], end=WINDOW[1])
    pitch = next(e for e in events if "evt-1" in e.uid)
    assert pitch.attendees == ["partner@acme.vc"]
    assert pitch.organizer == "jay@startup.com"


def test_store_events_keeps_only_fundraising(dbpath):
    db.upsert_investor("Acme Ventures", domain="acme.vc", path=dbpath)
    db.set_setting(config.S_HOME_DOMAINS, ["startup.com"], path=dbpath)
    classifier = calendars.Classifier.from_db(dbpath)

    events = calendars.parse_ics(ICS, start=WINDOW[0], end=WINDOW[1])
    result = calendars.store_events(events, classifier, only_fundraising=True, path=dbpath)

    assert result.fetched == 5          # 1 pitch + 1 standup + 3 recurrences
    titles = db.list_calendar_events(path=dbpath)["title"].tolist()
    assert "Pitch meeting with Acme Ventures" in titles
    assert "Daily standup" not in titles


def test_resync_does_not_reset_triage(dbpath):
    classifier = make_classifier()
    events = calendars.parse_ics(ICS, start=WINDOW[0], end=WINDOW[1])
    calendars.store_events(events, classifier, only_fundraising=False, path=dbpath)

    pending = db.list_calendar_events(config.REVIEW_PENDING, dbpath)
    db.set_review_status([int(pending.iloc[0]["id"])], config.REVIEW_IGNORED, path=dbpath)

    calendars.store_events(events, classifier, only_fundraising=False, path=dbpath)
    assert db.list_calendar_events(config.REVIEW_IGNORED, dbpath).shape[0] == 1


def test_accepting_events_is_idempotent(dbpath):
    db.upsert_investor("Acme Ventures", domain="acme.vc", path=dbpath)
    classifier = calendars.Classifier.from_db(dbpath)
    calendars.store_events(calendars.parse_ics(ICS, start=WINDOW[0], end=WINDOW[1]),
                           classifier, only_fundraising=True, path=dbpath)

    queued = db.list_calendar_events(config.REVIEW_PENDING, dbpath)
    ids = queued["id"].astype(int).tolist()

    created = calendars.accept_events(ids, path=dbpath)
    assert len(created) == len(ids)
    # Accepting the same events again must not double-count them.
    assert calendars.accept_events(ids, path=dbpath) == []
    assert db.counts(dbpath)["conversations"] == len(ids)


def test_accepted_event_links_matched_investor(dbpath):
    investor_id = db.upsert_investor("Acme Ventures", domain="acme.vc", path=dbpath)
    db.set_setting(config.S_HOME_DOMAINS, ["startup.com"], path=dbpath)
    classifier = calendars.Classifier.from_db(dbpath)
    calendars.store_events(calendars.parse_ics(ICS, start=WINDOW[0], end=WINDOW[1]),
                           classifier, only_fundraising=True, path=dbpath)

    queued = db.list_calendar_events(config.REVIEW_PENDING, dbpath)
    pitch = queued[queued["title"].str.contains("Pitch")]
    calendars.accept_events([int(pitch.iloc[0]["id"])], path=dbpath)

    conversation = db.list_conversations(dbpath).iloc[0]
    assert conversation["investor_id"] == investor_id
    assert conversation["counterpart"] == "partner@acme.vc"
    assert conversation["source"] == config.SOURCE_CALENDAR


def test_parse_events_frame_guesses_columns():
    import pandas as pd

    frame = pd.DataFrame([{
        "Summary": "Investor pitch", "Start Time": "2026-08-05 15:00",
        "Guests": "partner@acme.vc, jay@startup.com", "Description": "deck review",
    }])
    events = calendars.parse_events_frame(frame)
    assert len(events) == 1
    assert events[0].title == "Investor pitch"
    assert "partner@acme.vc" in events[0].attendees
