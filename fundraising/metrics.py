"""Derived views over the conversation log.

Pure pandas: every function takes a conversations DataFrame and returns another
one. Keeping it free of Streamlit and SQL means the numbers on the dashboard are
directly testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence

import pandas as pd

from . import config, pipeline

# The funnel's depth axis. "Passed" is an exit, not a depth -- an investor who
# passed after a first meeting got no further than a first meeting -- so it is
# excluded here and reported separately.
FUNNEL_STAGES = [s for s in config.STAGES if s != "Passed"]
_STAGE_DEPTH = {stage: i for i, stage in enumerate(FUNNEL_STAGES)}


def stage_depth(stage: object) -> int:
    """How far into the funnel a stage label sits. Unknown/Passed -> 0."""
    if stage is None:
        return 0
    return _STAGE_DEPTH.get(str(stage).strip(), 0)


# --- Filtering ---------------------------------------------------------------

def apply_filters(df: pd.DataFrame, *, start: date | None = None, end: date | None = None,
                  people: Sequence[str] | None = None,
                  investors: Sequence[str] | None = None,
                  stages: Sequence[str] | None = None,
                  channels: Sequence[str] | None = None,
                  sources: Sequence[str] | None = None,
                  search: str | None = None) -> pd.DataFrame:
    """One filter set, applied identically to every chart on the page."""
    if df.empty:
        return df
    out = df.copy()
    occurred = pd.to_datetime(out["occurred_on"], errors="coerce")
    if start is not None:
        out = out[occurred >= pd.Timestamp(start)]
        occurred = occurred.loc[out.index]
    if end is not None:
        out = out[occurred <= pd.Timestamp(end)]
    if people:
        out = out[out["person"].isin(list(people))]
    if investors:
        out = out[out["investor"].isin(list(investors))]
    if stages:
        out = out[out["stage"].isin(list(stages))]
    if channels:
        out = out[out["channel"].isin(list(channels))]
    if sources:
        out = out[out["source"].isin(list(sources))]
    if search:
        needle = search.strip().lower()
        if needle:
            haystack = (
                out[["investor", "person", "counterpart", "notes", "next_step"]]
                .fillna("").astype(str).agg(" ".join, axis=1).str.lower()
            )
            out = out[haystack.str.contains(needle, regex=False)]
    return out


# --- Headline numbers --------------------------------------------------------

def split_by_today(df: pd.DataFrame, today: date | None = None
                   ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separate conversations already had from meetings still to come.

    A meeting on next Thursday is on the books, not in the count -- the whole
    question is how many conversations the team *has had*.
    """
    if df.empty:
        return df, df
    stamp = pd.Timestamp(today or date.today())
    occurred = pd.to_datetime(df["occurred_on"], errors="coerce")
    return df[occurred <= stamp], df[occurred > stamp]


@dataclass
class Kpis:
    total: int = 0
    investors: int = 0
    people: int = 0
    last_7: int = 0
    prior_7: int = 0
    last_30: int = 0
    weekly_average: float = 0.0
    in_flight: int = 0
    committed: int = 0
    passed: int = 0
    committed_amount: float = 0.0
    pipeline_amount: float = 0.0
    overdue_next_steps: int = 0
    upcoming: int = 0
    first_date: pd.Timestamp | None = None
    last_date: pd.Timestamp | None = None

    @property
    def week_delta(self) -> int:
        return self.last_7 - self.prior_7


def compute_kpis(df: pd.DataFrame, today: date | None = None) -> Kpis:
    if df.empty:
        return Kpis()
    today = today or date.today()
    now = pd.Timestamp(today)
    # Only conversations that have actually happened count; scheduled ones are
    # reported separately so they are visible without inflating the total.
    df, ahead = split_by_today(df, today)
    upcoming = int(len(ahead))
    if df.empty:
        return Kpis(upcoming=upcoming)
    occurred = pd.to_datetime(df["occurred_on"], errors="coerce")
    valid = df[occurred.notna()].copy()
    valid["_d"] = occurred[occurred.notna()]

    kpis = Kpis(
        upcoming=upcoming,
        total=int(len(df)),
        investors=int(df["investor"].dropna().nunique()),
        people=int(df["person"].dropna().nunique()),
        last_7=int(((valid["_d"] > now - pd.Timedelta(days=7)) & (valid["_d"] <= now)).sum()),
        prior_7=int(((valid["_d"] > now - pd.Timedelta(days=14))
                     & (valid["_d"] <= now - pd.Timedelta(days=7))).sum()),
        last_30=int(((valid["_d"] > now - pd.Timedelta(days=30)) & (valid["_d"] <= now)).sum()),
    )

    if not valid.empty:
        kpis.first_date = valid["_d"].min()
        kpis.last_date = valid["_d"].max()
        span_days = max((kpis.last_date - kpis.first_date).days, 1)
        kpis.weekly_average = round(len(valid) / (span_days / 7), 1)

    per_investor = furthest_stage(df)
    if not per_investor.empty:
        kpis.committed = int((per_investor["stage"] == "Committed").sum())
        kpis.passed = int((per_investor["stage"] == "Passed").sum())
        kpis.in_flight = int(len(per_investor) - kpis.committed - kpis.passed)

    amounts = pd.to_numeric(df["amount"], errors="coerce")
    kpis.committed_amount = float(amounts[df["stage"] == "Committed"].sum())
    kpis.pipeline_amount = float(amounts[~df["stage"].isin(config.TERMINAL_STAGES)].sum())

    due = pd.to_datetime(df["next_step_due"], errors="coerce")
    kpis.overdue_next_steps = int(
        (due.notna() & (due < now) & df["next_step"].notna()).sum())
    return kpis


# --- Time series -------------------------------------------------------------

def weekly_volume(df: pd.DataFrame, weeks: int | None = None) -> pd.DataFrame:
    """Conversations per calendar week (weeks starting Monday).

    Empty weeks are filled with zero so a gap in activity reads as a gap rather
    than a compressed axis.
    """
    columns = ["week", "label", "conversations"]
    if df.empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})
    occurred = pd.to_datetime(df["occurred_on"], errors="coerce").dropna()
    if occurred.empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})

    starts = occurred.dt.to_period("W-SUN").dt.start_time
    counts = starts.value_counts().sort_index()
    full_index = pd.date_range(counts.index.min(), counts.index.max(), freq="7D")
    counts = counts.reindex(full_index, fill_value=0)

    out = pd.DataFrame({"week": counts.index, "conversations": counts.to_numpy()})
    if weeks:
        out = out.tail(weeks)
    out["label"] = out["week"].dt.strftime("%b %d")
    return out[columns].reset_index(drop=True)


def cumulative(df: pd.DataFrame) -> pd.DataFrame:
    """Running total of conversations, one point per active day."""
    columns = ["date", "conversations", "total"]
    if df.empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})
    occurred = pd.to_datetime(df["occurred_on"], errors="coerce").dropna()
    if occurred.empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})
    daily = occurred.dt.normalize().value_counts().sort_index()
    out = pd.DataFrame({"date": daily.index, "conversations": daily.to_numpy()})
    out["total"] = out["conversations"].cumsum()
    return out.reset_index(drop=True)


# --- Pipeline shape ----------------------------------------------------------

def furthest_stage(df: pd.DataFrame) -> pd.DataFrame:
    """The deepest stage each investor has reached, plus their latest activity."""
    columns = ["investor", "stage", "depth", "conversations", "last_touch",
               "first_touch", "owner", "amount"]
    if df.empty or df["investor"].dropna().empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})

    work = df[df["investor"].notna()].copy()
    work["_depth"] = work["stage"].map(stage_depth)
    work["_passed"] = work["stage"].eq("Passed")
    work["_date"] = pd.to_datetime(work["occurred_on"], errors="coerce")
    work["_amount"] = pd.to_numeric(work["amount"], errors="coerce")

    rows = []
    for investor, group in work.groupby("investor", sort=True):
        depth = int(group["_depth"].max())
        # A pass is terminal regardless of how deep the conversation went, but
        # only if nothing later moved the relationship forward again.
        latest = group.sort_values("_date").iloc[-1]
        stage = "Passed" if latest["_passed"] else FUNNEL_STAGES[depth]
        if (group["stage"] == "Committed").any():
            stage = "Committed"
        rows.append({
            "investor": investor,
            "stage": stage,
            "depth": depth,
            "conversations": int(len(group)),
            "last_touch": group["_date"].max(),
            "first_touch": group["_date"].min(),
            "owner": latest.get("person"),
            "amount": float(group["_amount"].max()) if group["_amount"].notna().any() else None,
        })
    return pd.DataFrame(rows, columns=columns)


def funnel(df: pd.DataFrame) -> pd.DataFrame:
    """Investors that reached each stage, deepest-stage-wins and monotone."""
    per_investor = furthest_stage(df)
    columns = ["stage", "order", "investors", "conversion"]
    if per_investor.empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})

    # Committed investors necessarily cleared every earlier gate.
    depths = per_investor["depth"].copy()
    depths[per_investor["stage"] == "Committed"] = len(FUNNEL_STAGES) - 1

    rows = []
    top = int((depths >= 0).sum())
    for index, stage in enumerate(FUNNEL_STAGES):
        reached = int((depths >= index).sum())
        rows.append({
            "stage": stage,
            "order": index,
            "investors": reached,
            "conversion": round(reached / top, 3) if top else 0.0,
        })
    return pd.DataFrame(rows, columns=columns)


def by_person(df: pd.DataFrame) -> pd.DataFrame:
    """Per-team-member totals -- the leaderboard behind '# of conversations'."""
    columns = ["person", "conversations", "investors", "last_touch", "committed"]
    if df.empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})
    work = df.copy()
    work["person"] = work["person"].fillna("Unassigned")
    work["_date"] = pd.to_datetime(work["occurred_on"], errors="coerce")
    grouped = work.groupby("person", sort=False).agg(
        conversations=("id", "count"),
        investors=("investor", pd.Series.nunique),
        last_touch=("_date", "max"),
        committed=("stage", lambda s: int((s == "Committed").sum())),
    ).reset_index()
    return grouped.sort_values("conversations", ascending=False).reset_index(drop=True)


def person_week_matrix(df: pd.DataFrame, weeks: int = 12) -> pd.DataFrame:
    """Long-form person x week counts for the activity heatmap."""
    columns = ["person", "week", "label", "conversations"]
    if df.empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})
    work = df.copy()
    work["person"] = work["person"].fillna("Unassigned")
    work["_date"] = pd.to_datetime(work["occurred_on"], errors="coerce")
    work = work[work["_date"].notna()]
    if work.empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})

    work["week"] = work["_date"].dt.to_period("W-SUN").dt.start_time
    recent = sorted(work["week"].unique())[-weeks:]
    work = work[work["week"].isin(recent)]

    counts = work.groupby(["person", "week"], sort=False).size().reset_index(name="conversations")
    # Fill the grid so an inactive week reads as an empty cell, not a missing one.
    grid = pd.MultiIndex.from_product(
        [sorted(work["person"].unique()), recent], names=["person", "week"]
    ).to_frame(index=False)
    out = grid.merge(counts, on=["person", "week"], how="left").fillna({"conversations": 0})
    out["conversations"] = out["conversations"].astype(int)
    out["label"] = pd.to_datetime(out["week"]).dt.strftime("%b %d")
    return out[columns]


def investor_pipeline(df: pd.DataFrame, today: date | None = None) -> pd.DataFrame:
    """One row per investor: where they are and how cold they have gone."""
    per_investor = furthest_stage(df)
    if per_investor.empty:
        return per_investor.assign(days_since=pd.Series(dtype="float"),
                                   next_step=pd.Series(dtype="object"),
                                   next_step_due=pd.Series(dtype="object"))
    today = pd.Timestamp(today or date.today())
    out = per_investor.copy()
    out["days_since"] = (today - pd.to_datetime(out["last_touch"])).dt.days

    latest = df[df["investor"].notna()].copy()
    latest["_date"] = pd.to_datetime(latest["occurred_on"], errors="coerce")
    latest = latest.sort_values("_date").groupby("investor").tail(1)
    out = out.merge(
        latest[["investor", "next_step", "next_step_due"]], on="investor", how="left")
    return out.sort_values(["depth", "last_touch"], ascending=[False, False]).reset_index(drop=True)


def upcoming_next_steps(df: pd.DataFrame, today: date | None = None,
                        horizon_days: int = 14) -> pd.DataFrame:
    """Open next steps that are overdue or land inside the horizon."""
    columns = ["occurred_on", "investor", "person", "next_step", "next_step_due", "status"]
    if df.empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})
    today = pd.Timestamp(today or date.today())
    work = df[df["next_step"].notna()].copy()
    if work.empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})
    work["next_step_due"] = pd.to_datetime(work["next_step_due"], errors="coerce")
    horizon = today + pd.Timedelta(days=horizon_days)
    work = work[work["next_step_due"].isna() | (work["next_step_due"] <= horizon)]
    work["status"] = work["next_step_due"].apply(
        lambda d: "No date" if pd.isna(d) else ("Overdue" if d < today else "Due soon"))
    return (work[columns]
            .sort_values("next_step_due", na_position="last")
            .reset_index(drop=True))


# --- Workbook pipeline (lead-based) -----------------------------------------
#
# The FUIFOAA workbook tracks one row per lead with dated stage columns, so its
# funnel is computed over leads and their furthest stage reached -- not over the
# conversation log. These functions take the leads frame.


def filter_leads(leads: pd.DataFrame, *, groups: Sequence[str] | None = None,
                 sheets: Sequence[str] | None = None,
                 owners: Sequence[str] | None = None,
                 grades: Sequence[str] | None = None,
                 include_terminal: bool = True) -> pd.DataFrame:
    if leads.empty:
        return leads
    out = leads
    if groups:
        out = out[out["campaign_group"].isin(list(groups))]
    if sheets:
        out = out[out["sheet"].isin(list(sheets))]
    if owners:
        out = out[out["owner"].isin(list(owners))]
    if grades:
        out = out[out["grade"].isin(list(grades))]
    if not include_terminal:
        out = out[out["terminal"].isna()]
    return out


def lead_funnel(leads: pd.DataFrame) -> pd.DataFrame:
    """Leads reaching each canonical step, monotone by furthest stage reached.

    A lead that passed after a first meeting still counts as having reached the
    first meeting -- the funnel measures depth, not current state.
    """
    columns = ["step", "label", "rank", "leads", "share", "conversion", "rule"]
    if leads.empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})

    ranks = pd.to_numeric(leads["status_rank"], errors="coerce").fillna(0)
    top = int((ranks >= pipeline.STEP_BY_KEY["outreach"].rank).sum())

    rows, previous = [], None
    for step in pipeline.STEPS:
        if step.key == "targeting":
            continue          # every lead is at least targeted; not a funnel gate
        reached = int((ranks >= step.rank).sum())
        rows.append({
            "step": step.key,
            "label": step.label,
            "rank": step.rank,
            "leads": reached,
            "share": round(reached / top, 4) if top else 0.0,
            # Step-to-step conversion is what the team actually manages.
            "conversion": round(reached / previous, 4) if previous else 1.0,
            "rule": pipeline.STEP_RULES.get(step.key, ""),
        })
        previous = reached or None
    return pd.DataFrame(rows, columns=columns)


def lead_outcomes(leads: pd.DataFrame) -> dict[str, int]:
    if leads.empty:
        return {"live": 0, "lost": 0, "hold": 0, "won": 0}
    ranks = pd.to_numeric(leads["status_rank"], errors="coerce").fillna(0)
    terminal = leads["terminal"]
    won = int((ranks >= pipeline.STEP_BY_KEY["won"].rank).sum())
    lost = int((terminal == pipeline.LOST).sum())
    hold = int((terminal == pipeline.HOLD).sum())
    return {"live": int(len(leads) - lost - hold - won),
            "lost": lost, "hold": hold, "won": won}


def meetings_only(conversations: pd.DataFrame) -> pd.DataFrame:
    """Just the conversations that actually happened.

    Workbook imports also store stage transitions in this table; those drive the
    funnel and must never be counted as conversations.
    """
    if conversations.empty or "kind" not in conversations.columns:
        return conversations
    return conversations[conversations["kind"].fillna(config.KIND_MEETING)
                         == config.KIND_MEETING]


def by_campaign(leads: pd.DataFrame) -> pd.DataFrame:
    """Per-campaign roll-up: how deep each pipeline has got."""
    columns = ["campaign_group", "sheet", "leads", "met", "won", "lost", "live"]
    if leads.empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})
    ranks = pd.to_numeric(leads["status_rank"], errors="coerce").fillna(0)
    work = leads.assign(_rank=ranks)
    rows = []
    for (group, sheet), chunk in work.groupby(["campaign_group", "sheet"], sort=True):
        outcomes = lead_outcomes(chunk)
        rows.append({
            "campaign_group": group, "sheet": sheet, "leads": int(len(chunk)),
            "met": int((chunk["_rank"] >= pipeline.STEP_BY_KEY["attended"].rank).sum()),
            "won": outcomes["won"], "lost": outcomes["lost"], "live": outcomes["live"],
        })
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["campaign_group", "leads"], ascending=[True, False]).reset_index(drop=True)


def top_connectors(leads: pd.DataFrame, limit: int = 15) -> pd.DataFrame:
    """Who is actually opening doors -- intros that reached a meeting."""
    columns = ["connector", "leads", "met", "hit_rate"]
    if leads.empty or leads["connector"].dropna().empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})
    ranks = pd.to_numeric(leads["status_rank"], errors="coerce").fillna(0)
    work = leads.assign(_rank=ranks)
    work = work[work["connector"].notna()]
    rows = []
    for connector, chunk in work.groupby("connector", sort=False):
        met = int((chunk["_rank"] >= pipeline.STEP_BY_KEY["attended"].rank).sum())
        rows.append({"connector": connector, "leads": int(len(chunk)), "met": met,
                     "hit_rate": round(met / len(chunk), 3)})
    return (pd.DataFrame(rows, columns=columns)
            .sort_values(["met", "leads"], ascending=False)
            .head(limit).reset_index(drop=True))
