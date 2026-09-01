from datetime import date

import pandas as pd
import pytest

from fundraising import db, metrics

TODAY = date(2026, 8, 25)

JOURNEYS = [
    # (date, person, investor, stage)
    ("2026-07-10", "Jay", "Acme", "Sourced"),
    ("2026-08-01", "Jay", "Acme", "First Meeting"),
    ("2026-08-05", "Jay", "Acme", "Diligence"),
    ("2026-08-06", "Sam", "Beta", "Intro"),
    ("2026-08-20", "Sam", "Beta", "Passed"),
    ("2026-08-22", "Jay", "Gamma", "Committed"),
    ("2026-08-24", "Sam", "Delta", "Sourced"),
]


@pytest.fixture
def frame(dbpath):
    for occurred, person, investor, stage in JOURNEYS:
        db.add_conversation({
            "occurred_on": occurred,
            "person_id": db.upsert_person(person, path=dbpath),
            "investor_id": db.upsert_investor(investor, path=dbpath),
            "stage": stage, "channel": "Meeting",
        }, path=dbpath)
    return db.list_conversations(dbpath)


def test_kpis(frame):
    kpis = metrics.compute_kpis(frame, today=TODAY)
    assert kpis.total == 7
    assert kpis.investors == 4
    assert kpis.people == 2
    assert kpis.committed == 1
    assert kpis.passed == 1
    assert kpis.in_flight == 2


def test_funnel_is_monotone(frame):
    funnel = metrics.funnel(frame)
    counts = funnel["investors"].tolist()
    assert counts == sorted(counts, reverse=True)


def test_pass_counts_at_the_depth_it_reached(frame):
    """Beta passed after an intro, so it counts at Intro but not First Meeting."""
    funnel = metrics.funnel(frame).set_index("stage")["investors"]
    assert funnel["Sourced"] == 4
    assert funnel["Intro"] == 3      # Acme, Beta, Gamma -- not Delta
    assert funnel["First Meeting"] == 2   # Acme, Gamma -- Beta dropped out
    assert funnel["Committed"] == 1


def test_committed_investor_counts_at_every_earlier_stage(frame):
    """Gamma only has one 'Committed' row but must fill the whole funnel."""
    funnel = metrics.funnel(frame).set_index("stage")["investors"]
    for stage in metrics.FUNNEL_STAGES:
        assert funnel[stage] >= 1


def test_furthest_stage_prefers_the_deepest_not_the_latest(frame):
    stages = metrics.furthest_stage(frame).set_index("investor")["stage"]
    assert stages["Acme"] == "Diligence"
    assert stages["Beta"] == "Passed"
    assert stages["Gamma"] == "Committed"


def test_by_person(frame):
    per_person = metrics.by_person(frame).set_index("person")
    assert per_person.loc["Jay", "conversations"] == 4
    assert per_person.loc["Sam", "conversations"] == 3
    assert per_person.loc["Jay", "investors"] == 2


def test_weekly_volume_fills_empty_weeks(frame):
    weekly = metrics.weekly_volume(frame)
    # Mid-July has no activity but must still appear, as a zero.
    assert (weekly["conversations"] == 0).any()
    assert weekly["week"].is_monotonic_increasing
    assert weekly["conversations"].sum() == len(frame)


def test_cumulative_only_increases(frame):
    running = metrics.cumulative(frame)
    assert running["total"].is_monotonic_increasing
    assert running["total"].iloc[-1] == len(frame)


def test_person_week_matrix_is_a_full_grid(frame):
    matrix = metrics.person_week_matrix(frame, weeks=8)
    assert len(matrix) == matrix["person"].nunique() * matrix["week"].nunique()


def test_investor_pipeline_days_since(frame):
    pipeline = metrics.investor_pipeline(frame, today=TODAY).set_index("investor")
    assert pipeline.loc["Delta", "days_since"] == 1
    assert pipeline.loc["Acme", "days_since"] == 20


def test_filters_compose(frame):
    filtered = metrics.apply_filters(frame, people=["Jay"], stages=["Diligence"])
    assert len(filtered) == 1
    assert filtered.iloc[0]["investor"] == "Acme"

    windowed = metrics.apply_filters(frame, start=date(2026, 8, 1), end=date(2026, 8, 10))
    assert len(windowed) == 3


def test_search_looks_across_text_columns(dbpath):
    db.add_conversation({"occurred_on": "2026-08-01", "notes": "great chemistry",
                         "investor_id": db.upsert_investor("Acme", path=dbpath)},
                        path=dbpath)
    frame = db.list_conversations(dbpath)
    assert len(metrics.apply_filters(frame, search="chemistry")) == 1
    assert len(metrics.apply_filters(frame, search="acme")) == 1
    assert len(metrics.apply_filters(frame, search="nothing")) == 0


@pytest.mark.parametrize("fn", [
    metrics.compute_kpis, metrics.weekly_volume, metrics.cumulative,
    metrics.funnel, metrics.by_person, metrics.person_week_matrix,
    metrics.furthest_stage, metrics.upcoming_next_steps, metrics.investor_pipeline,
])
def test_every_metric_survives_an_empty_database(fn, dbpath):
    """The dashboard renders before any data exists, so nothing may raise."""
    fn(db.list_conversations(dbpath))


def test_overdue_next_steps(dbpath):
    db.add_conversation({"occurred_on": "2026-08-01", "next_step": "send deck",
                         "next_step_due": "2026-08-10"}, path=dbpath)
    db.add_conversation({"occurred_on": "2026-08-01", "next_step": "later",
                         "next_step_due": "2026-09-30"}, path=dbpath)
    frame = db.list_conversations(dbpath)
    assert metrics.compute_kpis(frame, today=TODAY).overdue_next_steps == 1

    due = metrics.upcoming_next_steps(frame, today=TODAY)
    assert due.iloc[0]["status"] == "Overdue"


# --- Scheduled-but-not-yet-held meetings -------------------------------------

def test_future_meetings_are_not_counted_as_had(dbpath):
    """A meeting booked for next week is on the books, not in the count."""
    db.add_conversation({"occurred_on": "2026-08-20"}, path=dbpath)
    db.add_conversation({"occurred_on": "2026-08-24"}, path=dbpath)
    db.add_conversation({"occurred_on": "2026-09-30"}, path=dbpath)   # future
    frame = db.list_conversations(dbpath)

    kpis = metrics.compute_kpis(frame, today=TODAY)
    assert kpis.total == 2
    assert kpis.upcoming == 1


def test_split_by_today(dbpath):
    db.add_conversation({"occurred_on": "2026-08-01"}, path=dbpath)
    db.add_conversation({"occurred_on": "2026-12-01"}, path=dbpath)
    had, ahead = metrics.split_by_today(db.list_conversations(dbpath), today=TODAY)
    assert len(had) == 1 and len(ahead) == 1


def test_kpis_with_only_future_meetings(dbpath):
    db.add_conversation({"occurred_on": "2026-12-01"}, path=dbpath)
    kpis = metrics.compute_kpis(db.list_conversations(dbpath), today=TODAY)
    assert kpis.total == 0
    assert kpis.upcoming == 1
