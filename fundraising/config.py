"""Shared configuration: vocabularies, defaults and file locations.

Everything here is data rather than behaviour, so the rest of the package can be
imported without side effects (important for tests and for Streamlit reruns).
"""

from __future__ import annotations

import os
from pathlib import Path

APP_TITLE = "Fundraising Conversations"
APP_ICON = "\N{CHART WITH UPWARDS TREND}"

# --- Storage -----------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "fundraising.db"


def db_path() -> Path:
    """Location of the SQLite file that is the system of record.

    Override with FUNDRAISING_DB so a deployment can point at a mounted volume
    instead of the ephemeral working directory.
    """
    return Path(os.environ.get("FUNDRAISING_DB", DEFAULT_DB_PATH))


# --- Pipeline vocabulary -----------------------------------------------------

# Ordered from top of funnel to resolved. Order matters: it drives the funnel
# chart, "furthest stage reached" and the ordinal colour ramp.
STAGES = [
    "Sourced",
    "Intro",
    "First Meeting",
    "Follow-up",
    "Partner Meeting",
    "Diligence",
    "Term Sheet",
    "Committed",
    "Passed",
]

# Stages that mean the conversation is finished, one way or the other.
TERMINAL_STAGES = {"Committed", "Passed"}

# Stages counted as "in the funnel" for progression maths.
PROGRESSION_STAGES = [s for s in STAGES if s not in TERMINAL_STAGES]

CHANNELS = ["Meeting", "Video Call", "Phone Call", "Email", "Event", "Intro", "Other"]

OUTCOMES = ["Advancing", "Holding", "Awaiting Reply", "Passed", "Committed", "Unknown"]

INVESTOR_TYPES = [
    "VC",
    "Angel",
    "Family Office",
    "Strategic",
    "Accelerator",
    "Crossover",
    "Other",
]

# --- Calendar classification defaults ---------------------------------------

# Substrings that suggest a calendar event is a fundraising conversation.
DEFAULT_INCLUDE_KEYWORDS = [
    "fundrais", "fund rais", "raise", "round", "seed", "pre-seed", "series a",
    "series b", "series c", "investor", "investment", "vc ", "venture",
    "capital", "pitch", "term sheet", "termsheet", "diligence", "dd call",
    "cap table", "partner meeting", "ic meeting", "angel", "lp ", "limited partner",
    "data room", "deck review", "intro to", "warm intro",
]

# Substrings that strongly suggest an event is internal or unrelated. These
# subtract from the score so a "Series A retro" style false positive is unlikely.
DEFAULT_EXCLUDE_KEYWORDS = [
    "standup", "stand-up", "all hands", "allhands", "retro", "sprint",
    "1:1", "1-1", "one on one", "interview", "onboarding", "lunch", "coffee chat",
    "birthday", "ooo", "out of office", "holiday", "pto", "focus time",
    "no meetings", "blocked", "dentist", "doctor", "gym", "commute",
    "team sync", "weekly sync", "design review", "code review", "demo day prep",
]

# Scoring weights. Exposed in Settings so the model can be tuned without code.
DEFAULT_SCORE_WEIGHTS = {
    "keyword_title": 3.0,
    "keyword_description": 1.5,
    "known_investor_domain": 4.0,
    "watchlist_domain": 2.0,
    "external_guest": 0.5,
    "exclude_keyword": -4.0,
}

DEFAULT_SCORE_THRESHOLD = 3.0

# Email domains that are never treated as an "external investor" signal.
GENERIC_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com",
    "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "live.com",
    "msn.com", "mail.com", "fastmail.com", "hey.com", "zoho.com",
}

# --- Settings keys -----------------------------------------------------------

S_INCLUDE_KEYWORDS = "classifier.include_keywords"
S_EXCLUDE_KEYWORDS = "classifier.exclude_keywords"
S_WATCHLIST_DOMAINS = "classifier.watchlist_domains"
S_SCORE_WEIGHTS = "classifier.score_weights"
S_SCORE_THRESHOLD = "classifier.score_threshold"
S_HOME_DOMAINS = "org.home_domains"
S_SOR_ADOPTED_AT = "sor.adopted_at"
S_SOR_SOURCE = "sor.adopted_source"
S_TARGET_CONVERSATIONS = "goal.target_conversations"
S_TARGET_DATE = "goal.target_date"
S_RAISE_TARGET_AMOUNT = "goal.raise_target_amount"
S_LAST_SHEET_URL = "import.last_sheet_url"

SETTINGS_DEFAULTS = {
    S_INCLUDE_KEYWORDS: DEFAULT_INCLUDE_KEYWORDS,
    S_EXCLUDE_KEYWORDS: DEFAULT_EXCLUDE_KEYWORDS,
    S_WATCHLIST_DOMAINS: [],
    S_SCORE_WEIGHTS: DEFAULT_SCORE_WEIGHTS,
    S_SCORE_THRESHOLD: DEFAULT_SCORE_THRESHOLD,
    S_HOME_DOMAINS: [],
    S_SOR_ADOPTED_AT: None,
    S_SOR_SOURCE: None,
    S_TARGET_CONVERSATIONS: 150,
    S_TARGET_DATE: None,
    S_RAISE_TARGET_AMOUNT: None,
    S_LAST_SHEET_URL: None,
}

REVIEW_PENDING = "pending"
REVIEW_ACCEPTED = "accepted"
REVIEW_IGNORED = "ignored"

SOURCE_MANUAL = "manual"
SOURCE_CALENDAR = "calendar"
SOURCE_SHEET = "sheet"
