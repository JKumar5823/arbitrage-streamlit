"""The master-workbook adapter: one row per lead, dated stage columns."""

import io

import pandas as pd
import pytest

from fundraising import config, db, metrics, workbook

D = pd.Timestamp


def make_book(**sheets) -> io.BytesIO:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    buffer.seek(0)
    return buffer


LEADS = pd.DataFrame([
    # Reached a first meeting, then passed.
    {"Name": "Ana Diaz", "Relevant Firm": "Redwood", "Owner of Next Steps": "Jay",
     "Status": "0. Closed Lost - Unconvinced", "Grade": "A", "Score": 91.0,
     "Est Upper Limit": 500000, "Connector": "Sam",
     "1.1. Pathway Identified": D("2026-06-01"),
     "2.1. Intro Requested, Pending Introducer Response": D("2026-06-03"),
     "3.1. Introduction Made": D("2026-06-05"),
     "3.2. Interested": D("2026-06-06"),
     "3.4. 1st Meeting Scheduled": D("2026-06-08"),
     "4.1. 1st Meeting Happened": D("2026-06-10"),
     "0. Closed Lost - Unconvinced": D("2026-06-20"),
     "1st Meeting Date": D("2026-06-10"), "2nd Meeting Date": pd.NaT},
    # Never contacted.
    {"Name": "Bo Chen", "Relevant Firm": "Ironbridge", "Owner of Next Steps": "Priya",
     "Status": "1.1. Pathway Identified", "Grade": "B", "Score": 70.0,
     "Est Upper Limit": None, "Connector": "Sam",
     "1.1. Pathway Identified": D("2026-06-02"),
     "2.1. Intro Requested, Pending Introducer Response": pd.NaT,
     "3.1. Introduction Made": pd.NaT, "3.2. Interested": pd.NaT,
     "3.4. 1st Meeting Scheduled": pd.NaT, "4.1. 1st Meeting Happened": pd.NaT,
     "0. Closed Lost - Unconvinced": pd.NaT,
     "1st Meeting Date": pd.NaT, "2nd Meeting Date": pd.NaT},
    # Two meetings, still live.
    {"Name": "Cy Okafor", "Relevant Firm": "Redwood", "Owner of Next Steps": "Jay",
     "Status": "5.6. Verbal Commitment", "Grade": "A", "Score": 95.0,
     "Est Upper Limit": 1000000, "Connector": "Lee",
     "1.1. Pathway Identified": D("2026-06-01"),
     "2.1. Intro Requested, Pending Introducer Response": D("2026-06-02"),
     "3.1. Introduction Made": D("2026-06-04"),
     "3.2. Interested": D("2026-06-05"),
     "3.4. 1st Meeting Scheduled": D("2026-06-07"),
     "4.1. 1st Meeting Happened": D("2026-06-09"),
     "0. Closed Lost - Unconvinced": pd.NaT,
     "1st Meeting Date": D("2026-06-09"), "2nd Meeting Date": D("2026-06-25")},
    # A formatted row with no lead name -- the workbook is full of these.
    {"Name": None, "Relevant Firm": None, "Owner of Next Steps": None,
     "Status": "1.0. Targeting", "Grade": None, "Score": None,
     "Est Upper Limit": None, "Connector": None,
     "1.1. Pathway Identified": pd.NaT,
     "2.1. Intro Requested, Pending Introducer Response": pd.NaT,
     "3.1. Introduction Made": pd.NaT, "3.2. Interested": pd.NaT,
     "3.4. 1st Meeting Scheduled": pd.NaT, "4.1. 1st Meeting Happened": pd.NaT,
     "0. Closed Lost - Unconvinced": pd.NaT,
     "1st Meeting Date": pd.NaT, "2nd Meeting Date": pd.NaT},
])

CALENDAR = pd.DataFrame([
    {"Event Key": "evt-1", "Title": "Redwood intro call", "Start": D("2026-06-10 15:00"),
     "End": D("2026-06-10 16:00"), "Location": "", "Organizer": "jay@firm.com",
     "Guests": "ana@redwood.vc", "Description": "", "Sync Status": "Active",
     "Calendars": "jay@firm.com"},
    {"Event Key": "evt-2", "Title": "Deleted meeting", "Start": D("2026-06-11 15:00"),
     "End": D("2026-06-11 16:00"), "Location": "", "Organizer": "jay@firm.com",
     "Guests": "", "Description": "", "Sync Status": "Removed",
     "Calendars": "jay@firm.com"},
])


@pytest.fixture
def book():
    return make_book(Exp_Raise=LEADS, Exp_Calendar=CALENDAR)


def test_preview_finds_lead_sheets(book):
    summary = workbook.preview(book)
    assert summary["lead_sheets"] == ["Exp_Raise"]
    assert summary["calendar_sheets"] == ["Exp_Calendar"]
    assert summary["unmapped"] == {}


def test_import_counts(book, dbpath):
    report = workbook.import_workbook(book, path=dbpath)
    assert report.leads == 3            # the unnamed row is skipped
    assert report.skipped_rows == 1
    # Ana 1, Cy 2 -- Bo never met anyone.
    assert report.meetings == 3
    assert report.calendar_events == 1  # the "Removed" event is not synced


def test_nat_cells_never_become_dates(book, dbpath):
    """pandas NaT is a datetime whose isoformat() is the string 'NaT'; treating
    that as a date turned every empty cell into a meeting."""
    workbook.import_workbook(book, path=dbpath)
    frame = db.list_conversations(dbpath)
    assert frame["occurred_on"].notna().all()
    assert not frame["occurred_on"].astype(str).str.contains("NaT").any()


def test_meetings_and_stage_events_are_separated(book, dbpath):
    workbook.import_workbook(book, path=dbpath)
    frame = db.list_conversations(dbpath)
    meetings = frame[frame["kind"] == config.KIND_MEETING]
    stages = frame[frame["kind"] == config.KIND_STAGE]
    assert len(meetings) == 3
    assert len(stages) > len(meetings)
    # The headline count must never include stage transitions.
    assert len(metrics.meetings_only(frame)) == 3


def test_furthest_stage_reached_is_recorded(book, dbpath):
    workbook.import_workbook(book, path=dbpath)
    leads = db.list_leads(dbpath).set_index("name")
    assert leads.loc["Ana Diaz", "status_rank"] == 6      # met, then lost
    assert leads.loc["Bo Chen", "status_rank"] == 1
    assert leads.loc["Cy Okafor", "status_rank"] == 8     # verbal commitment
    assert leads.loc["Ana Diaz", "terminal"] == "lost"
    assert pd.isna(leads.loc["Cy Okafor", "terminal"])


def test_a_lost_lead_still_counts_at_the_depth_it_reached(book, dbpath):
    workbook.import_workbook(book, path=dbpath)
    funnel = metrics.lead_funnel(db.list_leads(dbpath)).set_index("label")["leads"]
    # Ana passed but had her meeting, so both she and Cy count as having met.
    assert funnel["Meeting Happened"] == 2
    assert funnel["Verbal Commitment"] == 1


def test_funnel_is_monotone(book, dbpath):
    workbook.import_workbook(book, path=dbpath)
    counts = metrics.lead_funnel(db.list_leads(dbpath))["leads"].tolist()
    assert counts == sorted(counts, reverse=True)


def test_reimport_is_idempotent(book, dbpath):
    first = workbook.import_workbook(book, path=dbpath)
    before = db.counts(dbpath)
    book.seek(0)
    second = workbook.import_workbook(book, path=dbpath)
    assert second.meetings == 0 and second.stage_events == 0
    assert db.counts(dbpath)["conversations"] == before["conversations"]
    assert db.counts(dbpath)["leads"] == first.leads


def test_firms_and_owners_are_created(book, dbpath):
    workbook.import_workbook(book, path=dbpath)
    assert set(db.list_investors(dbpath)["name"]) == {"Redwood", "Ironbridge"}
    assert set(db.list_people(dbpath)["name"]) == {"Jay", "Priya"}


def test_connector_hit_rate(book, dbpath):
    workbook.import_workbook(book, path=dbpath)
    connectors = metrics.top_connectors(db.list_leads(dbpath)).set_index("connector")
    assert connectors.loc["Sam", "leads"] == 2
    assert connectors.loc["Sam", "met"] == 1
    assert connectors.loc["Lee", "hit_rate"] == 1.0


def test_campaign_rollup(book, dbpath):
    workbook.import_workbook(book, path=dbpath)
    rollup = metrics.by_campaign(db.list_leads(dbpath)).set_index("sheet")
    assert rollup.loc["Exp_Raise", "leads"] == 3
    assert rollup.loc["Exp_Raise", "met"] == 2
    assert rollup.loc["Exp_Raise", "lost"] == 1


def test_selected_sheets_only(dbpath):
    two = make_book(Exp_Raise=LEADS, Inv_BD=LEADS)
    report = workbook.import_workbook(two, sheets=["Exp_Raise"], path=dbpath)
    assert report.sheets == ["Exp_Raise"]
    assert set(db.list_leads(dbpath)["sheet"]) == {"Exp_Raise"}


def test_unmapped_stage_columns_are_reported(dbpath):
    odd = LEADS.copy()
    odd["7. Brand New Stage"] = pd.NaT
    report = workbook.import_workbook(make_book(Exp_Raise=odd), path=dbpath)
    assert report.unmapped_labels["Exp_Raise"] == ["7. Brand New Stage"]
