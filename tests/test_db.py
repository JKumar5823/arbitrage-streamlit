import pytest

from fundraising import config, db


def test_upsert_person_is_case_insensitive(dbpath):
    first = db.upsert_person("Jay Kumar", email="jay@example.com", path=dbpath)
    second = db.upsert_person("jay kumar", role="CEO", path=dbpath)
    assert first == second

    people = db.list_people(dbpath)
    assert len(people) == 1
    # The second call must fill the new field without wiping the first one.
    assert people.iloc[0]["email"] == "jay@example.com"
    assert people.iloc[0]["role"] == "CEO"


def test_upsert_investor_normalises_domain(dbpath):
    investor_id = db.upsert_investor("Acme Ventures", domain="@ACME.VC", path=dbpath)
    assert db.list_investors(dbpath).iloc[0]["domain"] == "acme.vc"
    assert db.find_investor_by_domain("acme.vc", path=dbpath) == investor_id
    assert db.find_investor_by_domain("nope.com", path=dbpath) is None


def test_source_key_uniqueness_blocks_duplicate_imports(dbpath):
    row = {"occurred_on": "2026-08-01", "source": config.SOURCE_SHEET, "source_key": "k1"}
    db.add_conversation(row, path=dbpath)
    with pytest.raises(Exception):
        db.add_conversation(row, path=dbpath)


def test_manual_rows_may_repeat(dbpath):
    """source_key is NULL for hand entry, so identical manual rows are allowed."""
    row = {"occurred_on": "2026-08-01", "source": config.SOURCE_MANUAL}
    db.add_conversation(row, path=dbpath)
    db.add_conversation(row, path=dbpath)
    assert db.counts(dbpath)["conversations"] == 2


def test_updates_are_audited(dbpath):
    conv_id = db.add_conversation({"occurred_on": "2026-08-01", "stage": "Intro"},
                                  path=dbpath)
    db.update_conversation(conv_id, {"stage": "Diligence"}, path=dbpath)
    audit = db.list_audit(path=dbpath)
    actions = audit["action"].tolist()
    assert "update" in actions
    detail = audit[audit["action"] == "update"].iloc[0]["detail"]
    assert "Diligence" in detail and "Intro" in detail


def test_empty_conversations_has_stable_columns(dbpath):
    frame = db.list_conversations(dbpath)
    assert frame.empty
    for column in ("occurred_on", "person", "investor", "stage", "amount"):
        assert column in frame.columns


def test_settings_round_trip(dbpath):
    db.set_setting(config.S_SCORE_THRESHOLD, 4.5, path=dbpath)
    assert db.get_setting(config.S_SCORE_THRESHOLD, path=dbpath) == 4.5
    db.set_setting(config.S_INCLUDE_KEYWORDS, ["seed", "series a"], path=dbpath)
    assert db.get_setting(config.S_INCLUDE_KEYWORDS, path=dbpath) == ["seed", "series a"]


def test_deleting_conversation_returns_event_to_queue(dbpath):
    conv_id = db.add_conversation({"occurred_on": "2026-08-01"}, path=dbpath)
    event_id = db.upsert_calendar_event({"uid": "u1", "title": "Pitch"}, path=dbpath)
    db.link_event_to_conversation(event_id, conv_id, path=dbpath)
    assert db.list_calendar_events(config.REVIEW_ACCEPTED, dbpath).shape[0] == 1

    db.delete_conversation(conv_id, path=dbpath)
    assert db.list_calendar_events(config.REVIEW_PENDING, dbpath).shape[0] == 1
