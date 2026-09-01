import pandas as pd
import pytest

from fundraising import config, db, sheets

RAW = pd.DataFrame([
    {"Date": "2026-08-01", "Owner": "Jay", "Firm": "Acme Ventures",
     "Stage": "first call", "Type": "Zoom", "Check Size": "$250k",
     "Next Step": "send deck", "Notes": "strong fit"},
    {"Date": "2026-08-04", "Owner": "Jay", "Firm": "Beta Capital",
     "Stage": "closed lost", "Type": "email", "Check Size": "",
     "Next Step": "", "Notes": ""},
    {"Date": "", "Owner": "Sam", "Firm": "Gamma Fund",
     "Stage": "due diligence", "Type": "", "Check Size": "1.5m",
     "Next Step": "", "Notes": ""},
])


def test_guess_mapping_finds_the_obvious_columns():
    mapping = sheets.guess_mapping(RAW.columns)
    assert mapping["occurred_on"] == "Date"
    assert mapping["person"] == "Owner"
    assert mapping["investor"] == "Firm"
    assert mapping["stage"] == "Stage"
    assert mapping["amount"] == "Check Size"


def test_each_column_is_claimed_once():
    """'Date' and 'Follow-up Date' must not both map to occurred_on."""
    mapping = sheets.guess_mapping(["Date", "Follow-up Date", "Investor"])
    assert mapping["occurred_on"] == "Date"
    assert mapping["next_step_due"] == "Follow-up Date"


@pytest.mark.parametrize("raw,expected", [
    ("first call", "First Meeting"), ("closed lost", "Passed"),
    ("due diligence", "Diligence"), ("TERM SHEET", "Term Sheet"),
    ("wired", "Committed"), ("Partner Meeting", "Partner Meeting"),
    ("", None), (None, None), ("something odd", None),
])
def test_canonical_stage(raw, expected):
    assert sheets.canonical_stage(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Zoom", "Video Call"), ("email", "Email"), ("in person", "Meeting"),
    ("referral", "Intro"), ("", None),
])
def test_canonical_channel(raw, expected):
    assert sheets.canonical_channel(raw) == expected


def test_plan_flags_bad_rows_rather_than_dropping_them(dbpath):
    plan = sheets.build_plan(RAW, sheets.guess_mapping(RAW.columns), "sheet:t", path=dbpath)
    assert plan.inserts == 2
    assert plan.errors == 1

    problem = [r for r in plan.rows if r.action == "error"][0]
    assert "date" in problem.error
    # Row numbers are reported as the operator sees them in the sheet.
    assert plan.preview_frame().iloc[2]["row"] == 4


def test_plan_requires_a_date_column(dbpath):
    plan = sheets.build_plan(RAW, {"investor": "Firm"}, "sheet:t", path=dbpath)
    assert plan.unmapped_required == ["occurred_on"]
    assert plan.rows == []


def test_import_creates_people_and_investors(dbpath):
    plan = sheets.build_plan(RAW, sheets.guess_mapping(RAW.columns), "sheet:t", path=dbpath)
    result = sheets.apply_plan(plan, path=dbpath)

    assert result.inserted == 2
    assert result.failed == 1
    assert result.people_created == 1
    assert result.investors_created == 2

    frame = db.list_conversations(dbpath)
    acme = frame[frame["investor"] == "Acme Ventures"].iloc[0]
    assert acme["stage"] == "First Meeting"
    assert acme["channel"] == "Video Call"
    assert acme["amount"] == 250_000


def test_reimport_is_idempotent(dbpath):
    mapping = sheets.guess_mapping(RAW.columns)
    sheets.apply_plan(sheets.build_plan(RAW, mapping, "sheet:t", path=dbpath), path=dbpath)
    before = db.counts(dbpath)["conversations"]

    second = sheets.apply_plan(
        sheets.build_plan(RAW, mapping, "sheet:t", path=dbpath), path=dbpath)
    assert second.inserted == 0
    assert db.counts(dbpath)["conversations"] == before


def test_reimport_preserves_edits_by_default(dbpath):
    mapping = sheets.guess_mapping(RAW.columns)
    sheets.apply_plan(sheets.build_plan(RAW, mapping, "sheet:t", path=dbpath), path=dbpath)

    frame = db.list_conversations(dbpath)
    conv_id = int(frame[frame["investor"] == "Acme Ventures"].iloc[0]["id"])
    db.update_conversation(conv_id, {"stage": "Diligence"}, path=dbpath)

    sheets.apply_plan(sheets.build_plan(RAW, mapping, "sheet:t", path=dbpath), path=dbpath)
    after = db.list_conversations(dbpath)
    assert after[after["id"] == conv_id].iloc[0]["stage"] == "Diligence"


def test_reimport_can_be_told_to_overwrite(dbpath):
    mapping = sheets.guess_mapping(RAW.columns)
    sheets.apply_plan(sheets.build_plan(RAW, mapping, "sheet:t", path=dbpath), path=dbpath)

    frame = db.list_conversations(dbpath)
    conv_id = int(frame[frame["investor"] == "Acme Ventures"].iloc[0]["id"])
    db.update_conversation(conv_id, {"stage": "Diligence"}, path=dbpath)

    sheets.apply_plan(sheets.build_plan(RAW, mapping, "sheet:t", path=dbpath),
                      overwrite_edits=True, path=dbpath)
    after = db.list_conversations(dbpath)
    assert after[after["id"] == conv_id].iloc[0]["stage"] == "First Meeting"


def test_explicit_id_column_survives_row_reordering(dbpath):
    frame = RAW.head(2).copy()
    frame["Record ID"] = ["r1", "r2"]
    mapping = sheets.guess_mapping(frame.columns)
    assert mapping["row_key"] == "Record ID"
    sheets.apply_plan(sheets.build_plan(frame, mapping, "sheet:t", path=dbpath), path=dbpath)

    shuffled = frame.iloc[::-1].reset_index(drop=True)
    second = sheets.apply_plan(
        sheets.build_plan(shuffled, mapping, "sheet:t", path=dbpath), path=dbpath)
    assert second.inserted == 0
    assert db.counts(dbpath)["conversations"] == 2


def test_duplicate_rows_within_one_sheet_are_skipped(dbpath):
    frame = pd.concat([RAW.head(1), RAW.head(1)], ignore_index=True)
    frame["Record ID"] = ["same", "same"]
    plan = sheets.build_plan(frame, sheets.guess_mapping(frame.columns),
                             "sheet:t", path=dbpath)
    assert plan.inserts == 1
    assert plan.skips == 1


@pytest.mark.parametrize("url,expected_id", [
    ("https://docs.google.com/spreadsheets/d/1AbC-dEf_123/edit#gid=42", "1AbC-dEf_123"),
    ("https://docs.google.com/spreadsheets/d/1AbC-dEf_123/edit?usp=sharing", "1AbC-dEf_123"),
])
def test_parse_sheet_url(url, expected_id):
    sheet_id, _ = sheets.parse_sheet_url(url)
    assert sheet_id == expected_id


def test_parse_sheet_url_reads_gid():
    assert sheets.parse_sheet_url(
        "https://docs.google.com/spreadsheets/d/1AbC-dEf_123/edit#gid=42")[1] == "42"


def test_adopting_system_of_record(dbpath):
    assert sheets.is_system_of_record(dbpath) is False
    sheets.adopt_as_system_of_record("gsheet:abc", path=dbpath)
    assert sheets.is_system_of_record(dbpath) is True
    assert db.get_setting(config.S_SOR_SOURCE, path=dbpath) == "gsheet:abc"

    sheets.release_system_of_record(dbpath)
    assert sheets.is_system_of_record(dbpath) is False
