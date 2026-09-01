"""The pipeline vocabulary, taken from the FUIFOAA master workbook.

The workbook records a lead's journey as a row of *dated stage columns*: a date
in "4.1. 1st Meeting Happened" means the lead entered that stage on that day.
Across the 13 lead sheets there are 89 distinct stage labels, because each
campaign type words its stages differently -- a webinar raise says "4.1 Attended
Webinar/Met" where an intro raise says "4.1. 1st Meeting Happened", and the
hiring pipeline says "4. 1st Interview Happened".

They all describe the same shape, so every label is mapped onto one canonical
step. Ranking by label rather than by the numeric prefix matters: "3.2" means
*Interested* on an intro raise but *Invited to Webinar* on a webinar raise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Any numeric-prefixed header is treated as a stage column, not just the 0-6
# prefixes in use today: a stage added later must show up as unmapped rather
# than be silently ignored. "1st Meeting Date" does not match -- the prefix has
# to be digits and dots followed by whitespace.
STAGE_COLUMN_RE = re.compile(r"^\d[\.\d]*\s")


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    rank: int
    description: str


# The canonical funnel, in order. Ranks are the comparison key: a lead that
# reached rank 6 necessarily passed every step below it.
STEPS: list[Step] = [
    Step("targeting", "Targeting", 1, "Pathway identified, not yet contacted"),
    Step("outreach", "Outreach", 2, "Intro or invite requested"),
    Step("intro_made", "Intro Made", 3, "Introduction landed with the lead"),
    Step("interested", "Interested", 4, "Lead signalled interest"),
    Step("scheduled", "Meeting Scheduled", 5, "RSVPed or first meeting on the calendar"),
    Step("attended", "Meeting Happened", 6, "First meeting or event actually attended"),
    Step("progressing", "Progressing", 7, "Diligence, data room, second meeting, deciding"),
    Step("verbal", "Verbal Commitment", 8, "Verbal commitment or offer extended"),
    Step("docs", "Docs Out", 9, "SAFE/SPV/contract sent or signed"),
    Step("won", "Closed Won", 10, "Funded, hired, paid or otherwise closed"),
]

STEP_BY_KEY = {s.key: s for s in STEPS}
STEP_BY_RANK = {s.rank: s for s in STEPS}
STEP_KEYS = [s.key for s in STEPS]

# Steps that mean the conversation actually took place. This is what "a
# fundraising conversation you have had" means in this workbook.
MEETING_STEPS = {"attended"}

# Terminal outcomes. These do not sit on the funnel: a lead that passes after a
# first meeting got as far as a first meeting, no further and no less.
LOST = "lost"
HOLD = "hold"

_RANKS: dict[str, int] = {}
_TERMINAL: dict[str, str] = {}


def _rank(rank: int, *labels: str) -> None:
    for label in labels:
        _RANKS[label] = rank


def _terminal(kind: str, *labels: str) -> None:
    for label in labels:
        _TERMINAL[label] = kind


_rank(1,
      "1.0. Targeting", "1.1. Pathway Identified", "1.2. Selected by CS",
      "1.3. Offer to Client", "1.4. Approved by Client, Intro To Be Drafted",
      "1.4. Approved by Client to Invite", "1.5. Intro Drafted, Pending Client Action",
      "1.5. Invite Drafted, Pending Client Action", "1.6. Client Handling Outreach")

_rank(2,
      "2.1. Intro Requested, Pending Introducer Response",
      "2.2. Introducer Replied, Pending Introducer Action",
      "2.3. Intro Requested by Introducer, Pending Lead Response",
      "2.3. Invite Made by Introducer, Pending Lead Response")

_rank(3,
      "3.1. Introduction Made", "3.1. Intro Made", "3.1. Invited, Waiting on RSVP",
      "3.2. Invited to Webinar")

_rank(4,
      "3.2. Interested", "3.3. Interested", "3.2. RSVP Tentative",
      "3.2. Application Review")

# "Scheduling" is an intent, "Scheduled" is a booked meeting, so the two sit on
# different steps -- collapsing them overstates the scheduled count.
_rank(4, "3.3. Scheduling 1st Meeting")

_rank(5,
      "3.4. 1st Meeting Scheduled", "3.4. RSVPed/1st Meeting Scheduled",
      "3.3. RSVP Confirmed")

# The meeting itself. "Scheduling 2nd Meeting" implies the first one happened,
# so it sits here rather than higher -- it is not extra progress on its own.
_rank(6,
      "4.1. 1st Meeting Happened", "4.1 Attended Webinar/Met",
      "4. 1st Interview Happened", "4. Attended, 1-1 Intro Needed",
      "4.2. Scheduling 2nd Meeting", "4.3. 2nd Meeting Scheduled")

# How each canonical step is counted, shown in the UI so the numbers are
# auditable rather than magic.
STEP_RULES = {
    "targeting": "Pathway identified or selected, no outreach yet",
    "outreach": "An intro or invite was requested",
    "intro_made": "The introduction reached the lead",
    "interested": "Lead replied with interest, or a first meeting is being scheduled",
    "scheduled": "A first meeting is booked, or the lead RSVPed",
    "attended": "A first meeting or event actually happened",
    "progressing": "Second meeting, diligence, data room or deciding",
    "verbal": "Verbal commitment or offer extended",
    "docs": "SAFE, SPV or contract sent or signed",
    "won": "Funded, hired, paid or otherwise closed won",
}

_rank(7,
      "5.1. 2nd Meeting Happened", "5.1. 2nd Interview Happened",
      "5.1. Attended, Need Status Update", "5.1. Sent Data Room",
      "5.2. Due Diligence", "5.2. Attended, Client Contact, Need Update",
      "5.2. Mutual Vetting", "5.2. Scoping", "5.3. Waiting on Terms/Lead",
      "5.3. Drafting Offer", "5.3. Proposal", "5.3. Declined Invite, Wants 1-1 Intro",
      "5.4. Deciding (Uncertain)", "5.4. Offer Extended",
      "5.4. RSVP'd but No-Show, Wants 1-1 Intro",
      "5.5. Deciding (Signaled Interest)", "5.5. Negotiating")

_rank(8, "5.6. Verbal Commitment")

_rank(9,
      "5.7. SPV Link Sent", "5.7. SAFE Emailed", "5.7. Contract Emailed",
      "5.8. SAFE/SPV Emailed", "5.8. SAFE Signed", "5.8. Legal Review",
      "5.9. SAFE/SPV Signed", "5.9. Contract Signed")

_rank(10,
      "6. Closed Won - Funded", "6. Closed Won - Made Intro", "6. Closed Won - Hired",
      "6. Closed Won - Paid", "6. Closed Won - Pilot", "6. Closed Won - Other BD Goal",
      "6. Closed Won - New Pathway Created")

_terminal(LOST,
          "0. Closed Lost - Lead Not Interested", "0. Closed Lost - Lead is Conflicted",
          "0. Closed Lost - Not in Focus for Lead", "0. Closed Lost - Raising Next Fund",
          "0. Closed Lost - Unconvinced", "0. Closed Lost - Unclear Reason",
          "0. Closed Lost - Timeline", "0. Closed Lost - Compensation",
          "0. Closed Lost - Focused on Current Role", "0. Closed Lost - No Budget",
          "0. Closed Lost - Not Interested", "0. Closed Lost - Unresponsive",
          "0. Closed Partially Valuable", "0. Lead Opted Out", "0. CS Opted Out",
          "0. Client Opted Out", "0. Introducer Opted Out",
          "0. Intro Requested, No Reply from Introducer",
          "0. Intro Requested, No Reply from Lead", "0. Invited, No Reply from Lead",
          "0. RSVP Declined - Do Not Pursue", "0. RSVP Yes but No-Show",
          "0. Attended - Bad Fit For Client",
          "0. Attended - Jerk, No Access to Future Events")

_terminal(HOLD, "0. Hold")

# A handful of "0." outcomes still prove a meeting took place. Without this the
# funnel would under-count conversations that ended badly.
_IMPLIED_RANK = {
    "0. Attended - Bad Fit For Client": 6,
    "0. Attended - Jerk, No Access to Future Events": 6,
    "0. RSVP Yes but No-Show": 5,
    "0. RSVP Declined - Do Not Pursue": 4,
}


def is_stage_column(header: object) -> bool:
    return bool(STAGE_COLUMN_RE.match(str(header).strip()))


def rank_of(label: object) -> int:
    """Canonical rank for a stage label. 0 when it carries no progression."""
    key = str(label).strip()
    if key in _RANKS:
        return _RANKS[key]
    return _IMPLIED_RANK.get(key, 0)


def terminal_kind(label: object) -> str | None:
    """'lost', 'hold', or None for a stage that is still in play."""
    return _TERMINAL.get(str(label).strip())


def step_for_rank(rank: int) -> Step | None:
    """The furthest canonical step a rank has reached."""
    reached = [s for s in STEPS if s.rank <= rank]
    return reached[-1] if reached else None


def known_labels() -> set[str]:
    return set(_RANKS) | set(_TERMINAL)


def unknown_labels(headers) -> list[str]:
    """Stage columns we have no mapping for -- surfaced rather than silently dropped."""
    known = known_labels()
    return sorted({str(h).strip() for h in headers
                   if is_stage_column(h) and str(h).strip() not in known})


# --- Campaigns ---------------------------------------------------------------

# Grouping mirrors the workbook's own daily report.
CAMPAIGN_GROUPS: dict[str, list[str]] = {
    "FUIFOAA raises": ["Exp_Raise", "Inf_Raise", "Inv_Raise", "Ava_Raise"],
    "SPV raises": ["Bor_Raise", "Det_Raise", "Exc_Raise", "Mod_Raise", "Exp_Trip"],
    "Other raises": ["Dir_Raise", "Other_Misc"],
    "BD & hiring": ["Inv_BD", "Exp_Hire"],
}

# Sheets whose pipeline is actually about raising money. The dashboard defaults
# to these, since hiring and BD conversations are not fundraising conversations.
FUNDRAISING_SHEETS = [
    sheet for group, sheets in CAMPAIGN_GROUPS.items()
    if group != "BD & hiring" for sheet in sheets
]

CALENDAR_SHEETS = ["Exp_Calendar"]


def group_for_sheet(sheet: str) -> str:
    for group, sheets in CAMPAIGN_GROUPS.items():
        if sheet in sheets:
            return group
    return "Other raises"
