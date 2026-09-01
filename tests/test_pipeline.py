"""The stage taxonomy taken from the master workbook."""

import pytest

from fundraising import pipeline


def test_every_step_rank_is_unique_and_ordered():
    ranks = [s.rank for s in pipeline.STEPS]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)


def test_all_89_workbook_labels_are_mapped():
    """An unmapped label would silently sink its leads down the funnel."""
    assert len(pipeline.known_labels()) == 89


def test_every_step_has_a_stated_rule():
    for step in pipeline.STEPS:
        assert pipeline.STEP_RULES.get(step.key)


@pytest.mark.parametrize("label,rank", [
    ("1.1. Pathway Identified", 1),
    ("2.1. Intro Requested, Pending Introducer Response", 2),
    ("3.1. Introduction Made", 3),
    ("4.1. 1st Meeting Happened", 6),
    ("5.6. Verbal Commitment", 8),
    ("6. Closed Won - Funded", 10),
])
def test_canonical_ranks(label, rank):
    assert pipeline.rank_of(label) == rank


def test_same_prefix_can_mean_different_steps_across_campaigns():
    """'3.2' is Interested on an intro raise but Invited on a webinar raise, so
    ranking must key on the label, never the numeric prefix."""
    assert pipeline.rank_of("3.2. Interested") == 4
    assert pipeline.rank_of("3.2. Invited to Webinar") == 3


def test_scheduling_ranks_below_scheduled():
    """'Scheduling' is an intent; only 'Scheduled' is a booked meeting."""
    assert pipeline.rank_of("3.3. Scheduling 1st Meeting") < \
           pipeline.rank_of("3.4. 1st Meeting Scheduled")


def test_campaign_variants_land_on_the_same_step():
    for label in ("4.1. 1st Meeting Happened", "4.1 Attended Webinar/Met",
                  "4. 1st Interview Happened"):
        assert pipeline.step_for_rank(pipeline.rank_of(label)).key == "attended"


def test_terminal_outcomes():
    assert pipeline.terminal_kind("0. Closed Lost - Unconvinced") == pipeline.LOST
    assert pipeline.terminal_kind("0. Hold") == pipeline.HOLD
    assert pipeline.terminal_kind("4.1. 1st Meeting Happened") is None


def test_a_bad_outcome_after_a_meeting_still_counts_as_a_meeting():
    """Otherwise the funnel would lose conversations that ended badly."""
    assert pipeline.rank_of("0. Attended - Bad Fit For Client") == 6
    assert pipeline.terminal_kind("0. Attended - Bad Fit For Client") == pipeline.LOST


def test_is_stage_column():
    assert pipeline.is_stage_column("4.1. 1st Meeting Happened")
    assert pipeline.is_stage_column("6. Closed Won - Funded")
    assert not pipeline.is_stage_column("Relevant Firm")
    assert not pipeline.is_stage_column("1st Meeting Date")


def test_unknown_labels_are_reported():
    missing = pipeline.unknown_labels(["4.1. 1st Meeting Happened", "9.9. Invented Stage",
                                       "Relevant Firm"])
    assert missing == ["9.9. Invented Stage"]


def test_fundraising_sheets_exclude_bd_and_hiring():
    assert "Inv_BD" not in pipeline.FUNDRAISING_SHEETS
    assert "Exp_Hire" not in pipeline.FUNDRAISING_SHEETS
    assert "Exp_Raise" in pipeline.FUNDRAISING_SHEETS


def test_group_for_sheet():
    assert pipeline.group_for_sheet("Exp_Raise") == "FUIFOAA raises"
    assert pipeline.group_for_sheet("Inv_BD") == "BD & hiring"
    assert pipeline.group_for_sheet("Unheard_Of") == "Other raises"
