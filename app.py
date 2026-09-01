"""Fundraising Conversations dashboard.

Streamlit entry point. Three jobs, in the order they matter:

1. Count the fundraising conversations the team is having -- from calendars,
   from a spreadsheet, or typed in by hand.
2. Visualise them: volume, funnel, who is doing the work, what is going cold.
3. Take over from the Google Sheet, so this app becomes the system of record
   rather than another copy of it.
"""

from __future__ import annotations

import io
import json
import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from fundraising import (calendars, charts, config, db, metrics, pipeline,
                         seed, sheets, util, workbook)

st.set_page_config(page_title=config.APP_TITLE, page_icon=config.APP_ICON,
                   layout="wide", initial_sidebar_state="expanded")

STRETCH = "stretch"


# --- Small helpers -----------------------------------------------------------

def chart(spec, key: str | None = None, height: int | None = None) -> None:
    """Render an Altair chart with our palette (theme=None disables the override).

    Streamlit fits the whole spec -- plot, axis and legend -- into the container,
    so a chart with chrome needs its container sized to include that chrome or
    the plot itself gets squeezed.
    """
    st.altair_chart(spec, width=STRETCH, theme=None, key=key,
                    **({"height": height} if height else {}))


def table_view(frame: pd.DataFrame, label: str = "Table view") -> None:
    """The WCAG-clean twin of a chart: every plotted value, readable as text."""
    with st.expander(label):
        st.dataframe(frame, width=STRETCH, hide_index=True)


def service_account_info() -> dict | None:
    """Service-account key from st.secrets, or one uploaded this session."""
    if "gcp_service_account" in st.secrets:
        return dict(st.secrets["gcp_service_account"])
    return st.session_state.get("uploaded_service_account")


# Reads are deliberately uncached. st.cache_data is keyed on arguments, and
# these queries take none, so a cached frame would be shared across every
# session -- one person's edit would stay invisible to everyone else until the
# TTL expired. For a system of record that is the wrong trade, and against a
# local SQLite file of this size the query is not worth caching anyway.


def money(value: float | None) -> str:
    if not value or pd.isna(value):
        return "--"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:,.0f}"


# --- Boot --------------------------------------------------------------------

db.init_db()
settings = db.all_settings()

conversations_all = db.list_conversations()
people_frame = db.list_people()
investors_frame = db.list_investors()
leads_all = db.list_leads()
has_pipeline = not leads_all.empty

with st.sidebar:
    st.markdown(f"### {config.APP_ICON} {config.APP_TITLE}")
    row_counts = db.counts()
    held, booked = metrics.split_by_today(metrics.meetings_only(conversations_all))
    st.caption(
        f"{len(held):,} conversations · {row_counts['leads']:,} leads · "
        f"{row_counts['investors']:,} firms · {row_counts['people']} people"
    )
    if len(booked):
        st.caption(f"{len(booked):,} more meetings are booked but not yet held.")
    if sheets.is_system_of_record():
        adopted = str(settings.get(config.S_SOR_ADOPTED_AT))[:10]
        st.success(f"System of record since {adopted}", icon=":material/verified:")
    else:
        st.info("Reading from a sheet. Adopt it in **Import & Sources** "
                "to make this app the source of truth.", icon=":material/sync:")

    if row_counts["conversations"] == 0:
        st.divider()
        st.markdown("**Nothing here yet**")
        st.caption("Load a worked example to see the dashboard populated, then "
                   "clear it before importing your own data.")
        if st.button("Load demo data", width=STRETCH):
            seed.seed_demo()
            st.rerun()

st.title(f"{config.APP_ICON} Fundraising Conversations")

# --- One filter row, above everything it scopes ------------------------------

if conversations_all.empty:
    default_start, default_end = date.today() - timedelta(days=90), date.today()
else:
    dates = pd.to_datetime(
        metrics.meetings_only(conversations_all)["occurred_on"], errors="coerce").dropna()
    default_start = (dates.min().date() if not dates.empty
                     else date.today() - timedelta(days=90))
    # Ends today, not at the last record: meetings booked for next month have
    # not been had yet, so the default view is what actually happened.
    default_end = date.today()

f1, f2, f3, f4 = st.columns([2.1, 1.5, 1.5, 1.5])
with f1:
    date_range = st.date_input("Date range", value=(default_start, default_end),
                               format="YYYY-MM-DD")
with f2:
    people_filter = st.multiselect(
        "Team member", sorted(conversations_all["person"].dropna().unique().tolist()))
with f3:
    if has_pipeline:
        available_groups = [g for g in pipeline.CAMPAIGN_GROUPS
                            if g in set(leads_all["campaign_group"].dropna())]
        # Hiring and BD conversations are not fundraising conversations, so the
        # dashboard opens on the raises and lets you widen from there.
        group_filter = st.multiselect(
            "Campaign", available_groups,
            default=[g for g in available_groups if g != "BD & hiring"])
    else:
        group_filter = []
        stage_filter_fallback = st.multiselect("Stage", config.STAGES)
with f4:
    search_text = st.text_input("Search", placeholder="Firm, contact, note…")

stage_filter = [] if has_pipeline else locals().get("stage_filter_fallback", [])

start_date = date_range[0] if isinstance(date_range, (tuple, list)) and date_range else None
end_date = (date_range[1] if isinstance(date_range, (tuple, list)) and len(date_range) > 1
            else None)

# Workbook imports also store stage transitions in this table. They drive the
# funnel; only 'meeting' rows are conversations the team actually had.
meetings_all = metrics.meetings_only(conversations_all)
view = metrics.apply_filters(meetings_all, start=start_date, end=end_date,
                             people=people_filter, stages=stage_filter,
                             search=search_text)
if has_pipeline and group_filter and "campaign_group" in view.columns:
    view = view[view["campaign_group"].isin(group_filter)
                | view["campaign_group"].isna()]

leads_view = metrics.filter_leads(leads_all, groups=group_filter or None,
                                  owners=people_filter or None)

(tab_overview, tab_pipeline, tab_log, tab_calendar, tab_import, tab_directory,
 tab_data) = st.tabs(
    ["Overview", "Pipeline", "Conversations", "Calendars", "Import & Sources",
     "Directory", "Data & Settings"]
)


# --- Overview ----------------------------------------------------------------

with tab_overview:
    kpis = metrics.compute_kpis(view)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Conversations", f"{kpis.total:,}",
              delta=f"{kpis.week_delta:+d} vs prior week" if kpis.total else None,
              help="Meetings that actually happened, in the current filter. "
                   "Pipeline stage changes are not counted here.")
    if has_pipeline:
        outcomes = metrics.lead_outcomes(leads_view)
        met = int((pd.to_numeric(leads_view["status_rank"], errors="coerce").fillna(0)
                   >= pipeline.STEP_BY_KEY["attended"].rank).sum()) if not leads_view.empty else 0
        k2.metric("Leads met", f"{met:,}",
                  help="Distinct leads the team has actually sat down with.")
        k3.metric("Live pipeline", f"{outcomes['live']:,}",
                  delta=f"{outcomes['hold']} on hold" if outcomes["hold"] else None,
                  delta_color="off",
                  help="Leads that have neither closed nor been lost.")
        k4.metric("Closed won", f"{outcomes['won']:,}",
                  delta=money(kpis.committed_amount) if kpis.committed_amount else None,
                  delta_color="off")
    else:
        k2.metric("Investors engaged", f"{kpis.investors:,}",
                  help="Distinct investors with at least one conversation.")
        k3.metric("Live pipeline", f"{kpis.in_flight:,}",
                  help="Investors who have neither committed nor passed.")
        k4.metric("Committed", f"{kpis.committed:,}",
                  delta=money(kpis.committed_amount) if kpis.committed_amount else None,
                  delta_color="off")
    k5.metric("Conversations / week", f"{kpis.weekly_average:g}",
              delta=f"{kpis.last_7} in last 7 days" if kpis.total else None,
              delta_color="off")

    # Counted from the unfiltered log: the date filter already ends today, so
    # anything still to come would otherwise be invisible here.
    scoped = meetings_all
    if has_pipeline and group_filter and "campaign_group" in scoped.columns:
        scoped = scoped[scoped["campaign_group"].isin(group_filter)
                        | scoped["campaign_group"].isna()]
    booked_ahead = metrics.split_by_today(scoped)[1]
    if not booked_ahead.empty:
        st.caption(f"{len(booked_ahead)} further meetings are already booked but "
                   "have not happened yet, so they are not counted above.")

    target = settings.get(config.S_TARGET_CONVERSATIONS)
    if target and kpis.total:
        progress = min(kpis.total / float(target), 1.0)
        st.progress(progress, text=f"{kpis.total} of {target} conversations toward goal "
                                   f"({progress:.0%})")

    st.divider()

    left, right = st.columns(2)
    with left:
        st.subheader("Conversations per week")
        weekly = metrics.weekly_volume(view)
        chart(charts.weekly_volume_chart(weekly), key="weekly")
        table_view(weekly.rename(columns={"label": "Week of"})[["Week of", "conversations"]]
                   if not weekly.empty else weekly)
    with right:
        st.subheader("Cumulative progress")
        running = metrics.cumulative(view)
        chart(charts.cumulative_chart(running, target=target), key="cumulative")
        table_view(running)

    left, right = st.columns(2)
    with left:
        st.subheader("Pipeline funnel")
        if has_pipeline:
            st.caption("Leads reaching each step, by the furthest stage they got "
                       "to. A lead that passed after a first meeting still counts "
                       "as having had that meeting.")
            funnel_frame = metrics.lead_funnel(leads_view)
            chart(charts.lead_funnel_chart(funnel_frame), key="funnel",
                  height=max(260, 34 * len(funnel_frame) + 70))
            table_view(funnel_frame[["label", "leads", "conversion", "share", "rule"]]
                       if not funnel_frame.empty else funnel_frame)
        else:
            st.caption("Investors that reached each stage. A pass counts at the "
                       "depth reached before the pass, not below it.")
            funnel_frame = metrics.funnel(view)
            chart(charts.funnel_chart(funnel_frame), key="funnel")
            table_view(funnel_frame.drop(columns=["order"]) if not funnel_frame.empty
                       else funnel_frame)
    with right:
        st.subheader("Who is having the conversations")
        per_person = metrics.by_person(view)
        chart(charts.by_person_chart(per_person), key="person")
        table_view(per_person)

    st.subheader("Activity by week")
    matrix = metrics.person_week_matrix(view, weeks=14)
    chart(charts.activity_heatmap(matrix), key="heatmap",
          height=charts.heatmap_height(matrix))
    table_view(matrix[["person", "label", "conversations"]] if not matrix.empty else matrix)

    st.divider()
    left, right = st.columns([1.3, 1])
    with left:
        st.subheader("Next steps due")
        due = metrics.upcoming_next_steps(view)
        if due.empty:
            st.caption("Nothing scheduled. Add a next step to any conversation to see it here.")
        else:
            st.dataframe(
                due, width=STRETCH, hide_index=True,
                column_config={
                    "occurred_on": st.column_config.DateColumn("Conversation", format="YYYY-MM-DD"),
                    "investor": st.column_config.TextColumn("Investor"),
                    "person": st.column_config.TextColumn("Owner"),
                    "next_step": st.column_config.TextColumn("Next step", width="large"),
                    "next_step_due": st.column_config.DateColumn("Due", format="YYYY-MM-DD"),
                    "status": st.column_config.TextColumn("Status", width="small"),
                })
    with right:
        st.subheader("Going cold")
        pipeline = metrics.investor_pipeline(view)
        if pipeline.empty:
            st.caption("No investors recorded in this range.")
        else:
            cold = pipeline[~pipeline["stage"].isin(config.TERMINAL_STAGES)]
            cold = cold.sort_values("days_since", ascending=False).head(10)
            st.dataframe(
                cold[["investor", "stage", "days_since", "conversations"]],
                width=STRETCH, hide_index=True,
                column_config={
                    "investor": st.column_config.TextColumn("Investor"),
                    "stage": st.column_config.TextColumn("Stage"),
                    "days_since": st.column_config.NumberColumn("Days since contact"),
                    "conversations": st.column_config.NumberColumn("Convos"),
                })


# --- Pipeline ----------------------------------------------------------------

with tab_pipeline:
    if not has_pipeline:
        st.info("No lead pipeline imported yet. Load the master workbook under "
                "**Import & Sources** to see campaigns, connectors and the "
                "stage-by-stage funnel here.", icon=":material/upload_file:")
    else:
        st.subheader("Where every lead stands")
        st.caption(f"{len(leads_view):,} leads in the current filter. Each lead's "
                   "position is the furthest stage it reached, taken from the "
                   "dated stage columns in the workbook.")

        funnel_frame = metrics.lead_funnel(leads_view)
        left, right = st.columns([1.25, 1])
        with left:
            chart(charts.lead_funnel_chart(funnel_frame), key="pipeline_funnel",
                  height=max(300, 34 * len(funnel_frame) + 70))
        with right:
            st.markdown("**How each step is counted**")
            st.dataframe(
                funnel_frame[["label", "leads", "conversion", "rule"]],
                width=STRETCH, hide_index=True,
                column_config={
                    "label": st.column_config.TextColumn("Step"),
                    "leads": st.column_config.NumberColumn("Leads", format="%d"),
                    "conversion": st.column_config.ProgressColumn(
                        "From previous", format="%.0f%%", min_value=0, max_value=1),
                    "rule": st.column_config.TextColumn("Counted as", width="large"),
                })

        st.divider()
        st.subheader("Campaigns")
        st.dataframe(
            metrics.by_campaign(leads_view), width=STRETCH, hide_index=True,
            column_config={
                "campaign_group": st.column_config.TextColumn("Group"),
                "sheet": st.column_config.TextColumn("Campaign"),
                "leads": st.column_config.NumberColumn("Leads"),
                "met": st.column_config.NumberColumn("Met"),
                "won": st.column_config.NumberColumn("Won"),
                "lost": st.column_config.NumberColumn("Lost"),
                "live": st.column_config.NumberColumn("Live"),
            })

        st.divider()
        left, right = st.columns(2)
        with left:
            st.subheader("Who opens doors")
            st.caption("Connectors ranked by intros that reached a meeting.")
            connectors = metrics.top_connectors(leads_view)
            if connectors.empty:
                st.caption("No connectors recorded in this filter.")
            else:
                st.dataframe(
                    connectors, width=STRETCH, hide_index=True,
                    column_config={
                        "connector": st.column_config.TextColumn("Connector"),
                        "leads": st.column_config.NumberColumn("Intros"),
                        "met": st.column_config.NumberColumn("Reached a meeting"),
                        "hit_rate": st.column_config.NumberColumn(
                            "Hit rate", format="percent"),
                    })
        with right:
            st.subheader("Furthest along")
            top = leads_view.sort_values(
                ["status_rank", "score"], ascending=False).head(15)
            st.dataframe(
                top[["name", "firm", "status", "owner", "grade", "check_size"]],
                width=STRETCH, hide_index=True,
                column_config={
                    "name": st.column_config.TextColumn("Lead"),
                    "firm": st.column_config.TextColumn("Firm"),
                    "status": st.column_config.TextColumn("Status", width="medium"),
                    "owner": st.column_config.TextColumn("Owner"),
                    "grade": st.column_config.TextColumn("Grade", width="small"),
                    "check_size": st.column_config.NumberColumn(
                        "Est. check", format="dollar"),
                })

        st.divider()
        st.subheader("All leads")
        st.caption("Edit any cell and save. This is the system of record once you "
                   "adopt it, so corrections belong here rather than in the workbook.")
        lead_columns = ["id", "name", "firm", "status", "owner", "campaign_group",
                        "sheet", "grade", "score", "check_size", "committed",
                        "connector", "last_updated", "notes"]
        edited_leads = st.data_editor(
            leads_view.reindex(columns=lead_columns), key="leads_editor",
            width=STRETCH, hide_index=True, height=420,
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                "name": st.column_config.TextColumn("Lead", required=True),
                "firm": st.column_config.TextColumn("Firm"),
                "status": st.column_config.TextColumn("Status", width="medium"),
                "owner": st.column_config.TextColumn("Owner", disabled=True),
                "campaign_group": st.column_config.TextColumn("Group", disabled=True),
                "sheet": st.column_config.TextColumn("Campaign", disabled=True),
                "grade": st.column_config.TextColumn("Grade", width="small"),
                "score": st.column_config.NumberColumn("Score", format="%.1f"),
                "check_size": st.column_config.NumberColumn("Est. check", format="dollar"),
                "committed": st.column_config.NumberColumn("Committed", format="dollar"),
                "last_updated": st.column_config.DateColumn("Updated", format="YYYY-MM-DD"),
                "notes": st.column_config.TextColumn("Notes", width="large"),
            })
        if st.button("Save lead edits", type="primary"):
            changed = 0
            original = leads_view.set_index("id")
            for _, row in edited_leads.iterrows():
                if pd.isna(row.get("id")):
                    continue
                lead_id = int(row["id"])
                if lead_id not in original.index:
                    continue
                before = original.loc[lead_id]
                updates = {c: row[c] for c in
                           ("name", "firm", "status", "grade", "score", "check_size",
                            "committed", "connector", "notes")
                           if c in row.index and str(row[c]) != str(before.get(c))}
                if not updates:
                    continue
                # Editing the status re-derives how far the lead has got, so the
                # funnel stays consistent with what the grid says.
                if "status" in updates:
                    updates["status_rank"] = pipeline.rank_of(updates["status"])
                    updates["terminal"] = pipeline.terminal_kind(updates["status"])
                sets = ", ".join(f"{k} = ?" for k in updates)
                with db._WRITE_LOCK, db.session() as conn:
                    conn.execute(f"UPDATE leads SET {sets}, updated_at = ? WHERE id = ?",
                                 list(updates.values()) + [db._now(), lead_id])
                    db.log(conn, "leads", lead_id, "update",
                           {"fields": sorted(updates)}, "grid")
                changed += 1
            st.success(f"Saved {changed} lead(s).") if changed else st.info("Nothing to save.")
            st.rerun()


# --- Conversation log --------------------------------------------------------

EDITOR_COLUMNS = ["id", "occurred_on", "person", "investor", "counterpart", "channel",
                  "stage", "outcome", "amount", "next_step", "next_step_due", "notes",
                  "source"]


def editor_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in EDITOR_COLUMNS})
    out = frame.reindex(columns=EDITOR_COLUMNS).copy()
    out["occurred_on"] = pd.to_datetime(out["occurred_on"], errors="coerce").dt.date
    out["next_step_due"] = pd.to_datetime(out["next_step_due"], errors="coerce").dt.date
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce")
    return out


def persist_edits(before: pd.DataFrame, after: pd.DataFrame) -> tuple[int, int, int]:
    """Diff the grid against what was rendered and write only what changed."""
    updated = created = deleted = 0
    before_by_id = {int(r["id"]): r for _, r in before.iterrows() if pd.notna(r.get("id"))}
    seen: set[int] = set()

    for _, row in after.iterrows():
        payload = {
            "occurred_on": util.to_date_str(row.get("occurred_on")),
            "counterpart": row.get("counterpart"),
            "channel": row.get("channel"),
            "stage": row.get("stage"),
            "outcome": row.get("outcome"),
            "amount": row.get("amount"),
            "next_step": row.get("next_step"),
            "next_step_due": util.to_date_str(row.get("next_step_due")),
            "notes": row.get("notes"),
        }
        # Names typed into the grid become real people/investors.
        person = str(row.get("person") or "").strip()
        investor = str(row.get("investor") or "").strip()
        payload["person_id"] = db.upsert_person(person) if person else None
        payload["investor_id"] = db.upsert_investor(investor) if investor else None

        if pd.isna(row.get("id")):
            if not payload["occurred_on"]:
                continue
            payload["source"] = config.SOURCE_MANUAL
            db.add_conversation(payload, actor="grid")
            created += 1
            continue

        conv_id = int(row["id"])
        seen.add(conv_id)
        original = before_by_id.get(conv_id)
        if original is None:
            continue
        changed = {}
        for field, value in payload.items():
            old = original.get(field if field not in ("person_id", "investor_id")
                               else field.replace("_id", ""))
            if field in ("person_id", "investor_id"):
                old_name = str(old or "").strip()
                new_name = person if field == "person_id" else investor
                if old_name != new_name:
                    changed[field] = value
                continue
            old_norm = util.to_date_str(old) if field.endswith(("_on", "_due")) else old
            new_norm = value
            if pd.isna(old_norm) if not isinstance(old_norm, str) else False:
                old_norm = None
            if (old_norm or None) != (new_norm or None):
                changed[field] = value
        if changed:
            db.update_conversation(conv_id, changed, actor="grid")
            updated += 1

    for conv_id in before_by_id:
        if conv_id not in seen:
            db.delete_conversation(conv_id, actor="grid")
            deleted += 1
    return created, updated, deleted


with tab_log:
    st.subheader("Log a conversation")
    with st.form("add_conversation", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            new_date = st.date_input("Date", value=date.today())
            new_person = st.selectbox(
                "Team member",
                [""] + people_frame["name"].tolist() if not people_frame.empty else [""],
                accept_new_options=True)
        with c2:
            new_investor = st.selectbox(
                "Investor",
                [""] + investors_frame["name"].tolist() if not investors_frame.empty else [""],
                accept_new_options=True)
            new_contact = st.text_input("Contact", placeholder="partner@fund.com")
        with c3:
            new_stage = st.selectbox("Stage", config.STAGES, index=2)
            new_channel = st.selectbox("Channel", config.CHANNELS)
        c4, c5 = st.columns([1, 2])
        with c4:
            new_amount = st.number_input("Amount discussed", min_value=0.0, step=50_000.0,
                                         value=0.0, format="%.0f")
            new_due = st.date_input("Next step due", value=None)
        with c5:
            new_next = st.text_input("Next step")
            new_notes = st.text_area("Notes", height=80)

        if st.form_submit_button("Add conversation", type="primary"):
            db.add_conversation({
                "occurred_on": new_date.isoformat(),
                "person_id": db.upsert_person(new_person) if new_person else None,
                "investor_id": db.upsert_investor(new_investor) if new_investor else None,
                "counterpart": new_contact, "channel": new_channel, "stage": new_stage,
                "amount": new_amount or None, "next_step": new_next,
                "next_step_due": new_due.isoformat() if new_due else None,
                "notes": new_notes, "source": config.SOURCE_MANUAL,
            }, actor="form")
            st.success("Conversation added.")
            st.rerun()

    st.divider()
    st.subheader(f"All conversations ({len(view)} shown)")
    st.caption("Edit any cell, add rows at the bottom, or select rows and delete. "
               "Typing a new investor or team member creates them.")

    original = editor_frame(view)
    edited = st.data_editor(
        original, key="conversation_editor", width=STRETCH, hide_index=True,
        num_rows="dynamic",
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
            "occurred_on": st.column_config.DateColumn("Date", format="YYYY-MM-DD", required=True),
            "person": st.column_config.TextColumn("Team member"),
            "investor": st.column_config.TextColumn("Investor"),
            "counterpart": st.column_config.TextColumn("Contact"),
            "channel": st.column_config.SelectboxColumn("Channel", options=config.CHANNELS),
            "stage": st.column_config.SelectboxColumn("Stage", options=config.STAGES),
            "outcome": st.column_config.SelectboxColumn("Outcome", options=config.OUTCOMES),
            "amount": st.column_config.NumberColumn("Amount", format="dollar"),
            "next_step": st.column_config.TextColumn("Next step", width="medium"),
            "next_step_due": st.column_config.DateColumn("Due", format="YYYY-MM-DD"),
            "notes": st.column_config.TextColumn("Notes", width="large"),
            "source": st.column_config.TextColumn("Source", disabled=True, width="small"),
        },
    )

    save_col, export_col = st.columns([1, 3])
    with save_col:
        if st.button("Save changes", type="primary", width=STRETCH):
            created, updated, deleted = persist_edits(original, edited)
            if created or updated or deleted:
                st.success(f"Saved: {created} added, {updated} updated, {deleted} removed.")
            else:
                st.info("Nothing to save.")
            st.rerun()
    with export_col:
        st.download_button(
            "Download this view as CSV",
            data=view.to_csv(index=False).encode("utf-8"),
            file_name=f"fundraising-conversations-{date.today():%Y-%m-%d}.csv",
            mime="text/csv")


# --- Calendars ---------------------------------------------------------------

with tab_calendar:
    st.subheader("Read meetings from calendars")
    st.caption("Fetched meetings are scored, never auto-counted. You accept the ones "
               "that were really fundraising conversations, so the numbers stay yours.")

    with st.expander("Whose calendars", expanded=people_frame.empty):
        st.caption("Give each person a Google calendar ID (usually their email) for "
                   "API sync, or paste their private ICS address — in Google Calendar: "
                   "Settings → your calendar → *Secret address in iCal format*.")
        people_editor = st.data_editor(
            people_frame.reindex(columns=["id", "name", "email", "role", "calendar_id",
                                          "ics_url", "active"])
            if not people_frame.empty else
            pd.DataFrame({c: pd.Series(dtype="object") for c in
                          ["id", "name", "email", "role", "calendar_id", "ics_url", "active"]}),
            key="people_editor", width=STRETCH, hide_index=True, num_rows="dynamic",
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                "name": st.column_config.TextColumn("Name", required=True),
                "calendar_id": st.column_config.TextColumn("Google calendar ID"),
                "ics_url": st.column_config.TextColumn("Secret ICS address", width="medium"),
                "active": st.column_config.CheckboxColumn("Active"),
            })
        if st.button("Save people", key="save_people"):
            for _, row in people_editor.iterrows():
                if not str(row.get("name") or "").strip():
                    continue
                db.upsert_person(row["name"], email=row.get("email"), role=row.get("role"),
                                 calendar_id=row.get("calendar_id"), ics_url=row.get("ics_url"),
                                 active=bool(row.get("active", True)))
            st.success("Saved.")
            st.rerun()

    window_col, opts_col = st.columns([1.4, 1.6])
    with window_col:
        sync_range = st.date_input(
            "Sync window",
            value=(date.today() - timedelta(days=90), date.today() + timedelta(days=14)),
            key="sync_window", format="YYYY-MM-DD")
    with opts_col:
        only_fundraising = st.toggle(
            "Only keep meetings that look like fundraising", value=True,
            help="Scored using the keywords and investor domains in Data & Settings. "
                 "Turn this off to triage everything by hand.")

    sync_start = sync_range[0] if isinstance(sync_range, (tuple, list)) else date.today()
    sync_end = (sync_range[1] if isinstance(sync_range, (tuple, list)) and len(sync_range) > 1
                else date.today())
    classifier = calendars.Classifier.from_db()

    method = st.radio("Source", ["Secret ICS address", "Google Calendar API", "Upload CSV"],
                      horizontal=True, label_visibility="collapsed")

    if method == "Secret ICS address":
        saved = people_frame[people_frame["ics_url"].notna()] if not people_frame.empty \
            else pd.DataFrame()
        if not saved.empty:
            st.caption(f"{len(saved)} saved calendar(s): {', '.join(saved['name'])}")
            if st.button("Sync saved ICS calendars", type="primary"):
                totals = calendars.SyncResult()
                for _, person in saved.iterrows():
                    try:
                        text = calendars.fetch_ics_text(person["ics_url"])
                        events = calendars.parse_ics(
                            text, calendar_id=person["name"], person_id=int(person["id"]),
                            start=datetime.combine(sync_start, datetime.min.time()),
                            end=datetime.combine(sync_end, datetime.max.time()))
                        result = calendars.store_events(events, classifier, only_fundraising)
                        totals.fetched += result.fetched
                        totals.stored += result.stored
                    except Exception as exc:
                        totals.errors.append(f"{person['name']}: {exc}")
                st.success(f"Read {totals.fetched} meetings, queued {totals.stored} for review.")
                for message in totals.errors:
                    st.error(message)
                st.rerun()
        else:
            st.info("Add an ICS address under *Whose calendars* above to sync automatically.")

        with st.form("adhoc_ics"):
            adhoc_url = st.text_input("Or sync a single ICS address now",
                                      placeholder="https://calendar.google.com/calendar/ical/…/basic.ics")
            adhoc_person = st.selectbox("Attribute to",
                                        [""] + (people_frame["name"].tolist()
                                                if not people_frame.empty else []),
                                        accept_new_options=True)
            if st.form_submit_button("Fetch") and adhoc_url:
                try:
                    pid = db.upsert_person(adhoc_person, ics_url=adhoc_url) if adhoc_person else None
                    events = calendars.parse_ics(
                        calendars.fetch_ics_text(adhoc_url),
                        calendar_id=adhoc_person or "ics", person_id=pid,
                        start=datetime.combine(sync_start, datetime.min.time()),
                        end=datetime.combine(sync_end, datetime.max.time()))
                    result = calendars.store_events(events, classifier, only_fundraising)
                    st.success(f"Read {result.fetched} meetings, queued {result.stored}.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not read that calendar: {exc}")

    elif method == "Google Calendar API":
        creds = service_account_info()
        if creds is None:
            st.warning("No service-account key found.")
            st.markdown(
                "Add one to `.streamlit/secrets.toml` under `[gcp_service_account]`, or "
                "upload it below for this session only. Each calendar must be shared "
                "with the service account's `client_email` (or use domain-wide "
                "delegation and set an impersonation address).")
            upload = st.file_uploader("Service account JSON", type=["json"], key="sa_upload")
            if upload is not None:
                st.session_state["uploaded_service_account"] = json.load(upload)
                st.rerun()
        else:
            st.success(f"Using service account `{creds.get('client_email', 'unknown')}`.")
            impersonate = st.text_input(
                "Impersonate (domain-wide delegation only)",
                placeholder="founder@yourcompany.com") or None
            if st.button("List available calendars"):
                try:
                    st.session_state["gcal_list"] = calendars.list_google_calendars(
                        creds, impersonate)
                except Exception as exc:
                    st.error(f"Could not list calendars: {exc}")
            available = st.session_state.get("gcal_list", [])
            if available:
                st.dataframe(pd.DataFrame(available), width=STRETCH, hide_index=True)

            registered = people_frame[people_frame["calendar_id"].notna()] \
                if not people_frame.empty else pd.DataFrame()
            if registered.empty:
                st.info("Set a Google calendar ID for at least one person above.")
            elif st.button("Sync Google calendars", type="primary"):
                totals, errors = calendars.SyncResult(), []
                for _, person in registered.iterrows():
                    try:
                        events = calendars.fetch_google_events(
                            creds, person["calendar_id"],
                            datetime.combine(sync_start, datetime.min.time()),
                            datetime.combine(sync_end, datetime.max.time()),
                            impersonate=impersonate, person_id=int(person["id"]))
                        result = calendars.store_events(events, classifier, only_fundraising)
                        totals.fetched += result.fetched
                        totals.stored += result.stored
                    except Exception as exc:
                        errors.append(f"{person['name']}: {exc}")
                st.success(f"Read {totals.fetched} meetings, queued {totals.stored} for review.")
                for message in errors:
                    st.error(message)
                st.rerun()

    else:
        st.caption("Export events from any calendar as CSV. Columns are matched by "
                   "name: title/summary, start, end, description, location, attendees.")
        upload = st.file_uploader("Event CSV", type=["csv"], key="events_csv")
        attribute_to = st.selectbox("Attribute to",
                                    [""] + (people_frame["name"].tolist()
                                            if not people_frame.empty else []),
                                    accept_new_options=True, key="csv_person")
        if upload is not None and st.button("Import events", type="primary"):
            try:
                frame = pd.read_csv(upload)
                pid = db.upsert_person(attribute_to) if attribute_to else None
                events = calendars.parse_events_frame(
                    frame, calendar_id=attribute_to or "csv", person_id=pid)
                result = calendars.store_events(events, classifier, only_fundraising)
                st.success(f"Read {result.fetched} rows, queued {result.stored} for review.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not read that file: {exc}")

    st.divider()
    st.subheader("Review queue")
    pending = db.list_calendar_events(config.REVIEW_PENDING)
    if pending.empty:
        st.caption("Nothing waiting. Synced meetings that look like fundraising "
                   "conversations appear here for you to confirm.")
    else:
        display = pending.copy()
        display["reasons"] = display["reasons"].apply(
            lambda r: "; ".join(json.loads(r)) if r else "")
        display["accept"] = display["score"] >= classifier.threshold
        display = display[["accept", "starts_at", "title", "person", "suggested_investor",
                           "score", "reasons", "id"]]
        review = st.data_editor(
            display, key="review_editor", width=STRETCH, hide_index=True,
            column_config={
                "accept": st.column_config.CheckboxColumn("Count it", width="small"),
                "starts_at": st.column_config.DatetimeColumn("When", format="YYYY-MM-DD HH:mm"),
                "title": st.column_config.TextColumn("Meeting", width="large"),
                "person": st.column_config.TextColumn("Whose calendar"),
                "suggested_investor": st.column_config.TextColumn("Matched investor"),
                "score": st.column_config.NumberColumn("Score", format="%.1f", width="small"),
                "reasons": st.column_config.TextColumn("Why", width="large"),
                "id": st.column_config.NumberColumn("id", disabled=True, width="small"),
            },
            disabled=["starts_at", "title", "person", "suggested_investor", "score",
                      "reasons", "id"])

        accept_col, ignore_col = st.columns(2)
        chosen = review[review["accept"]]["id"].astype(int).tolist()
        rejected = review[~review["accept"]]["id"].astype(int).tolist()
        with accept_col:
            if st.button(f"Add {len(chosen)} as conversations", type="primary",
                         disabled=not chosen, width=STRETCH):
                created = calendars.accept_events(chosen)
                st.success(f"Added {len(created)} conversations.")
                st.rerun()
        with ignore_col:
            if st.button(f"Dismiss the other {len(rejected)}", disabled=not rejected,
                         width=STRETCH):
                db.set_review_status(rejected, config.REVIEW_IGNORED)
                st.success(f"Dismissed {len(rejected)} meetings.")
                st.rerun()

    dismissed = db.list_calendar_events(config.REVIEW_IGNORED)
    if not dismissed.empty:
        with st.expander(f"Dismissed meetings ({len(dismissed)})"):
            st.dataframe(dismissed[["starts_at", "title", "person", "score"]],
                         width=STRETCH, hide_index=True)
            if st.button("Send all back to the review queue"):
                db.set_review_status(dismissed["id"].astype(int).tolist(),
                                     config.REVIEW_PENDING)
                st.rerun()


# --- Import & sources --------------------------------------------------------

with tab_import:
    st.subheader("Feed a Google Sheet in")
    st.caption("Load the sheet, confirm how its columns map onto conversations, "
               "preview exactly what will change, then import. Re-importing the same "
               "sheet updates rows instead of duplicating them.")

    source_kind = st.radio(
        "Where is it",
        ["Master workbook (multi-sheet)", "Google Sheet link",
         "Google Sheet (service account)", "Upload CSV or Excel"],
        horizontal=True, label_visibility="collapsed")

    frame = st.session_state.get("import_frame")
    source_ref = st.session_state.get("import_ref", "")

    if source_kind == "Master workbook (multi-sheet)":
        st.caption("For a workbook that tracks one row per lead across many "
                   "campaign sheets, with a dated column per pipeline stage. "
                   "Stage dates become the funnel, meeting dates become "
                   "conversations, and a bundled calendar sheet is loaded too.")
        upload = st.file_uploader("Workbook", type=["xlsx", "xlsm"], key="wb_upload")
        if upload is not None:
            try:
                if st.session_state.get("wb_name") != upload.name:
                    st.session_state["wb_preview"] = workbook.preview(upload)
                    st.session_state["wb_name"] = upload.name
            except Exception as exc:
                st.error(f"Could not read that workbook: {exc}")

        summary = st.session_state.get("wb_preview")
        if summary:
            st.markdown(f"**Found {len(summary['lead_sheets'])} pipeline sheets**"
                        + (f" and {summary['calendar_rows']:,} calendar rows"
                           if summary["calendar_rows"] else ""))
            st.dataframe(summary["table"], width=STRETCH, hide_index=True,
                         column_config={
                             "sheet": st.column_config.TextColumn("Sheet"),
                             "group": st.column_config.TextColumn("Group"),
                             "leads": st.column_config.NumberColumn("Rows"),
                             "stage columns": st.column_config.NumberColumn("Stage cols"),
                             "unmapped": st.column_config.NumberColumn("Unmapped"),
                         })
            if summary["unmapped"]:
                # Never silently drop a stage we do not understand -- an unmapped
                # label would quietly sink those leads down the funnel.
                st.warning("Some stage columns have no mapping and will not count "
                           "toward the funnel:")
                for sheet_name, labels in summary["unmapped"].items():
                    st.caption(f"**{sheet_name}**: {', '.join(labels)}")

            chosen_sheets = st.multiselect(
                "Sheets to import", summary["lead_sheets"],
                default=summary["lead_sheets"])
            with_calendar = st.toggle(
                "Also import the bundled calendar sheet",
                value=bool(summary["calendar_rows"]),
                disabled=not summary["calendar_rows"])

            if st.button("Import workbook", type="primary", disabled=not chosen_sheets):
                with st.spinner("Reading the workbook…"):
                    report = workbook.import_workbook(
                        upload, sheets=chosen_sheets, include_calendar=with_calendar,
                        source_ref=upload.name)
                st.success(f"Imported {report.summary()}.")
                if report.skipped_rows:
                    st.caption(f"{report.skipped_rows:,} rows had no lead name and "
                               "were skipped.")
                for message in report.errors:
                    st.error(message)
                st.rerun()

    elif source_kind == "Google Sheet link":
        st.caption("Works when the sheet's link sharing is set to *Anyone with the "
                   "link can view*. Nothing is written back to the sheet.")
        url = st.text_input("Sheet URL",
                            value=settings.get(config.S_LAST_SHEET_URL) or "",
                            placeholder="https://docs.google.com/spreadsheets/d/…")
        if st.button("Load sheet", type="primary", disabled=not url):
            try:
                loaded = sheets.load_public_sheet(url)
                sheet_id, gid = sheets.parse_sheet_url(url)
                st.session_state["import_frame"] = loaded
                st.session_state["import_ref"] = f"gsheet:{sheet_id}:{gid or '0'}"
                st.session_state["import_kind"] = "google_sheet"
                db.set_setting(config.S_LAST_SHEET_URL, url)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    elif source_kind == "Google Sheet (service account)":
        creds = service_account_info()
        if creds is None:
            st.warning("No service-account key found. Add `[gcp_service_account]` to "
                       "`.streamlit/secrets.toml`, or upload it below, then share the "
                       "sheet with the key's `client_email` as a Viewer.")
            upload = st.file_uploader("Service account JSON", type=["json"],
                                      key="sa_upload_sheets")
            if upload is not None:
                st.session_state["uploaded_service_account"] = json.load(upload)
                st.rerun()
        else:
            st.success(f"Using service account `{creds.get('client_email', 'unknown')}`.")
            url = st.text_input("Sheet URL", value=settings.get(config.S_LAST_SHEET_URL) or "",
                                key="private_sheet_url")
            worksheet = st.text_input("Worksheet name", placeholder="(first sheet)")
            if st.button("Load sheet", type="primary", disabled=not url):
                try:
                    loaded = sheets.load_private_sheet(creds, url, worksheet or None)
                    sheet_id, _ = sheets.parse_sheet_url(url)
                    st.session_state["import_frame"] = loaded
                    st.session_state["import_ref"] = f"gsheet:{sheet_id}:{worksheet or 'sheet1'}"
                    st.session_state["import_kind"] = "google_sheet"
                    db.set_setting(config.S_LAST_SHEET_URL, url)
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    else:
        upload = st.file_uploader("Spreadsheet", type=["csv", "xlsx", "xlsm", "xls"],
                                  key="sheet_upload")
        if upload is not None and st.button("Load file", type="primary"):
            try:
                st.session_state["import_frame"] = sheets.load_upload(upload, upload.name)
                st.session_state["import_ref"] = f"file:{upload.name}"
                st.session_state["import_kind"] = "file"
                st.rerun()
            except Exception as exc:
                st.error(f"Could not read that file: {exc}")

    if (source_kind != "Master workbook (multi-sheet)"
            and frame is not None and not frame.empty):
        st.divider()
        st.markdown(f"**Loaded {len(frame)} rows** from `{source_ref}`")
        with st.expander("What the sheet looks like"):
            st.dataframe(frame.head(20), width=STRETCH)

        st.markdown("**Map the columns**")
        st.caption("Guessed from the headers. Only *Date* is required; leave anything "
                   "else unmapped if the sheet does not have it.")
        guess = st.session_state.get("import_mapping") or sheets.guess_mapping(frame.columns)
        options = ["(not in sheet)"] + [str(c) for c in frame.columns]
        mapping: dict[str, str | None] = {}
        map_columns = st.columns(3)
        for index, field_name in enumerate(sheets.FIELD_ALIASES):
            with map_columns[index % 3]:
                current = guess.get(field_name)
                default = options.index(str(current)) if current and str(current) in options else 0
                label = field_name.replace("_", " ").title()
                picked = st.selectbox(
                    label + (" *" if field_name in sheets.REQUIRED_FIELDS else ""),
                    options, index=default, key=f"map_{field_name}")
                mapping[field_name] = None if picked == options[0] else picked
        st.session_state["import_mapping"] = mapping

        plan = sheets.build_plan(frame, mapping, source_ref)
        if plan.unmapped_required:
            st.error(f"Map a column for: {', '.join(plan.unmapped_required)}")
        else:
            st.markdown("**Preview**")
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("New conversations", plan.inserts)
            p2.metric("Existing rows updated", plan.updates)
            p3.metric("Unchanged / duplicate", plan.skips)
            p4.metric("Rows with problems", plan.errors)

            preview = plan.preview_frame()
            problems = preview[preview["action"] == "error"]
            if not problems.empty:
                st.warning(f"{len(problems)} row(s) cannot be imported and will be "
                           "skipped. Fix them in the sheet and reload, or import the rest.")
                st.dataframe(
                    problems[["row", "problem", "person", "investor"]],
                    width=STRETCH, hide_index=True,
                    column_config={
                        "row": st.column_config.NumberColumn("Sheet row", width="small"),
                        "problem": st.column_config.TextColumn("Problem", width="medium"),
                        "person": st.column_config.TextColumn("Team member"),
                        "investor": st.column_config.TextColumn("Investor"),
                    })
            with st.expander("Row-by-row preview"):
                st.dataframe(preview, width=STRETCH, hide_index=True)

            overwrite = st.toggle(
                "Let the sheet overwrite edits made here", value=False,
                help="Off: a re-import only fills fields that are still empty, so "
                     "corrections made in this app survive. On: the sheet wins.")
            if st.button(f"Import {plan.inserts + plan.updates} rows", type="primary",
                         disabled=plan.inserts + plan.updates == 0):
                result = sheets.apply_plan(
                    plan, source_kind=st.session_state.get("import_kind", "google_sheet"),
                    overwrite_edits=overwrite)
                st.success(
                    f"Imported. {result.inserted} added, {result.updated} updated, "
                    f"{result.skipped} unchanged, {result.failed} skipped. "
                    f"Created {result.people_created} people and "
                    f"{result.investors_created} investors.")
                st.rerun()

        if st.button("Clear loaded sheet"):
            for key in ("import_frame", "import_ref", "import_mapping", "import_kind"):
                st.session_state.pop(key, None)
            st.rerun()

    st.divider()
    st.subheader("Become the system of record")
    if sheets.is_system_of_record():
        st.success(
            f"This app has been the system of record since "
            f"`{settings.get(config.S_SOR_ADOPTED_AT)}`, subsuming "
            f"`{settings.get(config.S_SOR_SOURCE)}`.", icon=":material/verified:")
        st.caption("Log conversations here from now on. Keep the old sheet as a "
                   "read-only archive so nobody edits two copies.")
        with st.expander("Hand back to the sheet"):
            st.caption("Only do this if you are reverting the migration.")
            if st.button("Release system-of-record status"):
                sheets.release_system_of_record()
                st.rerun()
    else:
        st.markdown(
            "Once the import above looks right, flip the switch. It stamps the "
            "cutover date, shows a banner across the app, and gives you the note to "
            "paste at the top of the old sheet.")
        candidate = source_ref or settings.get(config.S_LAST_SHEET_URL) or "the spreadsheet"
        st.code(f"ARCHIVED — this sheet is no longer maintained.\n"
                f"Fundraising conversations now live in the dashboard.",
                language="text")
        confirm = st.checkbox("The imported data above is complete and correct")
        if st.button("Adopt as system of record", type="primary", disabled=not confirm):
            stamp = sheets.adopt_as_system_of_record(str(candidate))
            st.success(f"Done — system of record as of {stamp}.")
            st.rerun()

    history = db.list_batches()
    if not history.empty:
        st.divider()
        st.subheader("Import history")
        st.dataframe(
            history[["ts", "source_kind", "source_ref", "rows_read", "rows_inserted",
                     "rows_updated", "rows_skipped"]],
            width=STRETCH, hide_index=True)


# --- Directory ---------------------------------------------------------------

with tab_directory:
    st.subheader("Investors")
    st.caption("A domain here is what lets calendar sync recognise a meeting as a "
               "conversation with that investor.")
    investor_columns = ["id", "name", "type", "domain", "partner", "location",
                        "target_amount", "notes"]
    investors_editor = st.data_editor(
        investors_frame.reindex(columns=investor_columns) if not investors_frame.empty
        else pd.DataFrame({c: pd.Series(dtype="object") for c in investor_columns}),
        key="investors_editor", width=STRETCH, hide_index=True, num_rows="dynamic",
        column_config={
            "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
            "name": st.column_config.TextColumn("Investor", required=True),
            "type": st.column_config.SelectboxColumn("Type", options=config.INVESTOR_TYPES),
            "domain": st.column_config.TextColumn("Email domain", help="e.g. acme.vc"),
            "target_amount": st.column_config.NumberColumn("Target check", format="dollar"),
            "notes": st.column_config.TextColumn("Notes", width="large"),
        })
    if st.button("Save investors", type="primary"):
        kept = set()
        for _, row in investors_editor.iterrows():
            if not str(row.get("name") or "").strip():
                continue
            kept.add(db.upsert_investor(
                row["name"], type=row.get("type"), domain=row.get("domain"),
                partner=row.get("partner"), location=row.get("location"),
                target_amount=row.get("target_amount"), notes=row.get("notes")))
        if not investors_frame.empty:
            for removed in set(investors_frame["id"].astype(int)) - kept:
                db.delete_investor(removed)
        st.success("Saved.")
        st.rerun()

    st.divider()
    st.subheader("Investor pipeline")
    pipeline = metrics.investor_pipeline(view)
    if pipeline.empty:
        st.caption("No conversations in the current filter.")
    else:
        st.dataframe(
            pipeline[["investor", "stage", "owner", "conversations", "first_touch",
                      "last_touch", "days_since", "next_step", "amount"]],
            width=STRETCH, hide_index=True,
            column_config={
                "first_touch": st.column_config.DateColumn("First", format="YYYY-MM-DD"),
                "last_touch": st.column_config.DateColumn("Last", format="YYYY-MM-DD"),
                "days_since": st.column_config.NumberColumn("Days cold"),
                "amount": st.column_config.NumberColumn("Amount", format="dollar"),
                "next_step": st.column_config.TextColumn("Next step", width="medium"),
            })


# --- Data & settings ---------------------------------------------------------

with tab_data:
    st.subheader("How meetings are classified")
    st.caption("Calendar sync scores each meeting against these. Every point is "
               "explained in the review queue, so a wrong call tells you what to change.")

    c1, c2 = st.columns(2)
    with c1:
        include_text = st.text_area(
            "Fundraising keywords", height=180,
            value="\n".join(settings.get(config.S_INCLUDE_KEYWORDS, [])))
        watchlist_text = st.text_area(
            "Investor domains to watch", height=100,
            value="\n".join(settings.get(config.S_WATCHLIST_DOMAINS, [])),
            help="Domains that are probably investors but are not in the directory yet.")
    with c2:
        exclude_text = st.text_area(
            "Never-fundraising keywords", height=180,
            value="\n".join(settings.get(config.S_EXCLUDE_KEYWORDS, [])))
        home_text = st.text_area(
            "Your own email domains", height=100,
            value="\n".join(settings.get(config.S_HOME_DOMAINS, [])),
            help="Colleagues on an invite are not an external-guest signal.")

    threshold = st.slider(
        "Score needed to flag a meeting", min_value=0.0, max_value=10.0, step=0.5,
        value=float(settings.get(config.S_SCORE_THRESHOLD, config.DEFAULT_SCORE_THRESHOLD)),
        help="Lower catches more and asks you to dismiss the extras. Higher is quieter.")

    goal_col, amount_col = st.columns(2)
    with goal_col:
        goal = st.number_input(
            "Conversation goal", min_value=0, step=10,
            value=int(settings.get(config.S_TARGET_CONVERSATIONS) or 0))
    with amount_col:
        raise_target = st.number_input(
            "Raise target", min_value=0, step=250_000,
            value=int(settings.get(config.S_RAISE_TARGET_AMOUNT) or 0))

    if st.button("Save settings", type="primary"):
        db.set_setting(config.S_INCLUDE_KEYWORDS, util.parse_list(include_text))
        db.set_setting(config.S_EXCLUDE_KEYWORDS, util.parse_list(exclude_text))
        db.set_setting(config.S_WATCHLIST_DOMAINS,
                       [util.clean_domain(d) for d in util.parse_list(watchlist_text)])
        db.set_setting(config.S_HOME_DOMAINS,
                       [util.clean_domain(d) for d in util.parse_list(home_text)])
        db.set_setting(config.S_SCORE_THRESHOLD, threshold)
        db.set_setting(config.S_TARGET_CONVERSATIONS, goal or None)
        db.set_setting(config.S_RAISE_TARGET_AMOUNT, raise_target or None)
        st.success("Saved.")
        st.rerun()

    st.divider()
    st.subheader("Take your data with you")
    st.caption("Being the system of record only works if the data is never trapped. "
               "Everything is a plain SQLite file plus CSV exports.")

    e1, e2, e3 = st.columns(3)
    with e1:
        st.download_button(
            "Conversations (CSV)",
            data=conversations_all.to_csv(index=False).encode("utf-8"),
            file_name=f"conversations-{date.today():%Y-%m-%d}.csv",
            mime="text/csv", width=STRETCH)
    with e2:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            (conversations_all if not conversations_all.empty
             else pd.DataFrame({"note": ["no data"]})).to_excel(
                writer, sheet_name="Conversations", index=False)
            if not investors_frame.empty:
                investors_frame.to_excel(writer, sheet_name="Investors", index=False)
            if not people_frame.empty:
                people_frame.to_excel(writer, sheet_name="People", index=False)
        st.download_button(
            "Workbook (XLSX)", data=buffer.getvalue(),
            file_name=f"fundraising-{date.today():%Y-%m-%d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width=STRETCH)
    with e3:
        database_file = config.db_path()
        if database_file.exists():
            st.download_button(
                "Full database (SQLite)", data=database_file.read_bytes(),
                file_name="fundraising.db", mime="application/vnd.sqlite3",
                width=STRETCH)

    st.divider()
    st.subheader("Change history")
    st.caption("Every write, including imports. This is what makes an imported "
               "number auditable back to its source row.")
    audit = db.list_audit(300)
    if audit.empty:
        st.caption("Nothing recorded yet.")
    else:
        st.dataframe(audit[["ts", "actor", "entity", "entity_id", "action", "detail"]],
                     width=STRETCH, hide_index=True)

    with st.expander("Danger zone"):
        st.caption("Deletes every conversation, investor, person and queued meeting. "
                   "Settings survive. Export first.")
        if st.text_input("Type DELETE to confirm", key="reset_confirm") == "DELETE":
            if st.button("Erase all data", type="primary"):
                seed.reset()
                st.success("Cleared.")
                st.rerun()
