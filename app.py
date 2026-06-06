"""
Lift Lab — a personal workout-intelligence dashboard.

Reads the "Life Dashboard" Google-Sheet export and turns 2+ years of training,
bodyweight and calorie logs into:

  • a searchable history of every exercise + its progression
  • estimated-1RM PRs per exercise, timestamped and tied to the bodyweight you
    were at when you hit them
  • physique-photo timeline correlated to the lifts that drive each muscle
  • nutrition / activity analysis with concrete "what to change" coaching, including
    a diminishing-returns read on when to shift focus
  • plateau detection with specific break-through tactics

Run with:  streamlit run app.py
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pandas as pd
import streamlit as st

from workout import loader, analysis as A, physique

DATA_PATH = Path("data/workout_data.xlsx")

st.set_page_config(page_title="Lift Lab", page_icon="🏋️", layout="wide")


# ---------------------------------------------------------------------------
# Data loading (cached) + source selection
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Parsing workout history…")
def _load_from_bytes(data: bytes):
    ds = loader.load_dataset(data)
    return ds.routine, ds.daily, ds.prs


@st.cache_data(show_spinner="Parsing workout history…")
def _load_from_path(path: str, mtime: float):
    ds = loader.load_dataset(path)
    return ds.routine, ds.daily, ds.prs


@st.cache_data(ttl=300, show_spinner="Syncing from Google Sheets…")
def _load_live(sheet_id: str, _creds: dict, nonce: int):
    """Live read from Google Sheets. ``nonce`` lets the UI force a refresh; ``_creds``
    is underscore-prefixed so Streamlit doesn't try to hash the credentials dict."""
    from workout import gsheets
    ds = gsheets.load_dataset_live(sheet_id, _creds)
    return ds.routine, ds.daily, ds.prs


def gsheets_configured() -> bool:
    try:
        return bool(st.secrets.get("sheet_id")) and "gcp_service_account" in st.secrets
    except Exception:
        return False


def get_dataset():
    """Resolve the active data source. Priority: manual upload > live sync > snapshot."""
    src = st.session_state.get("uploaded_bytes")
    if src is not None:
        st.session_state["active_source"] = "upload"
        return _load_from_bytes(src)
    if st.session_state.get("use_live") and gsheets_configured():
        try:
            creds = dict(st.secrets["gcp_service_account"])
            data = _load_live(st.secrets["sheet_id"], creds,
                              st.session_state.get("live_nonce", 0))
            st.session_state["active_source"] = "live"
            return data
        except Exception as exc:  # fall back to snapshot but tell the user
            st.session_state["live_error"] = str(exc)
            st.session_state["active_source"] = "bundled"
    if DATA_PATH.exists():
        st.session_state.setdefault("active_source", "bundled")
        return _load_from_path(str(DATA_PATH), DATA_PATH.stat().st_mtime)
    return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.title("🏋️ Lift Lab")
st.sidebar.caption("Your training, decoded.")

# Auto-enable live sync the first time we see configured secrets.
if gsheets_configured():
    st.session_state.setdefault("use_live", True)

with st.sidebar.expander("📂 Data source", expanded=False):
    if gsheets_configured():
        st.markdown("**🔗 Google Sheets live sync**")
        st.session_state["use_live"] = st.toggle(
            "Sync live from my sheet", value=st.session_state.get("use_live", True),
            help="Reads the latest Routine / Daily Wgt / PRs straight from your sheet.")
        cols = st.columns(2)
        if cols[0].button("🔄 Refresh now", width="stretch"):
            st.session_state["live_nonce"] = st.session_state.get("live_nonce", 0) + 1
            st.cache_data.clear()
            st.rerun()
        if cols[1].button("🧪 Test connection", width="stretch"):
            from workout import gsheets
            ok, msg = gsheets.connection_check(
                st.secrets["sheet_id"], dict(st.secrets["gcp_service_account"]))
            (st.success if ok else st.error)(msg)
        st.caption("Live data is cached ~5 min; **Refresh now** pulls immediately.")
        st.divider()
    else:
        st.info("💡 Want it to **auto-update** when you edit the sheet? Set up a Google "
                "service account and add it to `.streamlit/secrets.toml` "
                "(see `secrets.toml.example` / the README). Until then, upload manually below.")

    st.markdown("**⬆️ Manual upload** (overrides live)")
    st.caption("Export the sheet as `.xlsx` (File → Download → Microsoft Excel) and drop it here.")
    up = st.file_uploader("Upload updated .xlsx", type=["xlsx"])
    if up is not None:
        st.session_state["uploaded_bytes"] = up.getvalue()
        st.success("Using your uploaded file.")
    if st.session_state.get("uploaded_bytes") and st.button("Use live / snapshot instead"):
        st.session_state.pop("uploaded_bytes", None)
        st.rerun()

routine, daily, prs = get_dataset()

# Surface the active source + any live-sync error.
_src = st.session_state.get("active_source", "bundled")
_src_label = {"live": "🟢 Live from Google Sheets", "upload": "📄 Uploaded file",
              "bundled": "📦 Bundled snapshot"}.get(_src, _src)
st.sidebar.caption(f"Source: {_src_label}")
if st.session_state.get("live_error") and _src != "live":
    st.sidebar.warning("Live sync failed, showing snapshot. "
                       f"{st.session_state['live_error'][:160]}")
    st.session_state.pop("live_error", None)

if routine.empty:
    st.error("No workout data found. Upload your Life Dashboard .xlsx in the sidebar.")
    st.stop()

PAGE = st.sidebar.radio(
    "Go to",
    ["📊 Overview", "🏋️ Exercises", "🏆 PRs", "📸 Physique", "🥗 Nutrition & Activity",
     "🧱 Plateaus & Coaching"],
)

last_session = routine["date"].max().date()
st.sidebar.metric("Logged sessions", routine["date"].nunique())
st.sidebar.metric("Exercises tracked", routine["exercise"].nunique())
st.sidebar.caption(f"History: {routine['date'].min().date()} → {last_session}")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def page_overview():
    st.title("📊 Overview")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total sets logged", f"{len(routine):,}")
    c2.metric("Sessions", f"{routine['date'].nunique():,}")
    c3.metric("Exercises", f"{routine['exercise'].nunique():,}")
    if not daily.empty and daily["weight"].notna().any():
        bw = daily.dropna(subset=["weight"])
        c4.metric("Bodyweight", f"{bw['weight'].iloc[-1]:.1f} lb",
                  f"{bw['weight'].iloc[-1] - bw['weight'].iloc[0]:+.1f} since {bw['date'].iloc[0].date()}")

    st.subheader("Bodyweight trend")
    bwt = A.bodyweight_trend(daily)
    if not bwt.empty:
        chart = bwt.set_index("date")[["weight", "smoothed"]]
        st.line_chart(chart, height=260)
    else:
        st.info("No bodyweight data yet.")

    left, right = st.columns(2)
    with left:
        st.subheader("Weekly hard sets by muscle (8 wk avg)")
        wm = A.weekly_sets_by_muscle(routine)
        if not wm.empty:
            st.bar_chart(wm.set_index("body_part"), height=300)
            st.caption("Rough volume guide: 10–20 hard sets/week per muscle drives growth. "
                       "Low bars on a priority muscle = add sets.")
    with right:
        st.subheader("Training frequency (sessions/month)")
        freq = (routine.groupby(routine["date"].dt.to_period("M").dt.start_time)["date"]
                .nunique().rename("sessions").rename_axis("month").reset_index())
        st.bar_chart(freq, x="month", y="sessions", height=300)

    st.subheader("⚡ Quick coaching read")
    for tip in A.coaching_recommendations(daily, routine,
                                          st.session_state.get("goal", "Lose fat")):
        st.write("• " + tip)


def page_exercises():
    st.title("🏋️ Exercises")
    exes = A.exercise_list(routine, min_sets=2)
    search = st.text_input("🔎 Search exercise")
    if search:
        exes = [e for e in exes if search.lower() in e.lower()]
    if not exes:
        st.info("No matching exercises.")
        return
    ex = st.selectbox(f"Choose an exercise ({len(exes)} available)", exes)

    hist = A.exercise_history(routine, ex)
    sb = A.session_best(routine, ex)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sets logged", len(hist))
    c2.metric("Sessions", hist["date"].nunique())
    c3.metric("Heaviest set", f"{hist['weight'].max():.0f} lb")
    if sb["e1rm"].notna().any():
        c4.metric("Best est. 1RM", f"{sb['e1rm'].max():.0f} lb")

    st.subheader("Progression")
    metric = st.radio("Plot", ["Estimated 1RM", "Top set weight", "Session volume"],
                      horizontal=True)
    col = {"Estimated 1RM": "best_e1rm", "Top set weight": "top_weight",
           "Session volume": "total_volume"}[metric]
    plot = sb.dropna(subset=[col]).set_index("date")[[col]]
    if not plot.empty:
        st.line_chart(plot, height=300)
    else:
        st.info("Not enough numeric data to chart this metric for this exercise.")

    st.subheader("Recent sessions")
    show = hist[["date", "weight", "sets_done", "reps_done", "e1rm", "body_part",
                 "comments"]].sort_values("date", ascending=False).head(40)
    st.dataframe(show, width="stretch", hide_index=True)


def page_prs():
    st.title("🏆 Personal Records")
    st.caption("Estimated 1RM (Epley, capped at 12 reps) computed from every logged set, "
               "plus your hand-logged rep-max PRs — each tied to the bodyweight you were "
               "at when it happened.")

    tab1, tab2 = st.tabs(["Computed from history", "Logged rep-max PRs"])

    with tab1:
        table = A.attach_bodyweight(A.all_prs(routine, min_sets=5), daily)
        table = table.rename(columns={
            "exercise": "Exercise", "best_e1rm": "Best e1RM (lb)",
            "top_weight": "Heaviest set (lb)", "date": "Date hit",
            "bodyweight": "Bodyweight (lb)", "sessions": "Sessions"})
        table["Date hit"] = pd.to_datetime(table["Date hit"]).dt.date
        st.dataframe(table, width="stretch", hide_index=True, height=480)

        st.subheader("PR timeline for one lift")
        exes = A.exercise_list(routine, min_sets=5)
        ex = st.selectbox("Exercise", exes,
                          index=exes.index("Bench Press") if "Bench Press" in exes else 0)
        ev = A.attach_bodyweight(A.pr_events(routine, ex), daily)
        if ev.empty:
            st.info("No PR progression found.")
        else:
            st.line_chart(A.session_best(routine, ex).dropna(subset=["best_e1rm"])
                          .set_index("date")[["best_e1rm"]], height=260)
            disp = ev[["date", "e1rm", "top_weight", "bodyweight"]].copy()
            disp["date"] = disp["date"].dt.date
            disp = disp.rename(columns={"date": "PR date", "e1rm": "New e1RM (lb)",
                                        "top_weight": "Top set (lb)",
                                        "bodyweight": "Bodyweight (lb)"})
            st.write("**Each new PR and your bodyweight at the time:**")
            st.dataframe(disp, width="stretch", hide_index=True)
            rel = ev.dropna(subset=["bodyweight"])
            if not rel.empty:
                rel = rel.assign(rel_strength=(rel["e1rm"] / rel["bodyweight"]).round(2))
                st.caption(f"Strength-to-bodyweight on latest PR: "
                           f"**{rel['rel_strength'].iloc[-1]}×** bodyweight.")

    with tab2:
        if prs.empty:
            st.info("No logged rep-max PRs in the sheet.")
        else:
            piv = prs.pivot_table(index="exercise", columns="reps", values="weight",
                                  aggfunc="max")
            piv.columns = [f"{int(c)}RM" for c in piv.columns]
            st.dataframe(piv, width="stretch", height=480)
            st.subheader("Best estimated 1RM from logged rep-maxes")
            best = (prs.dropna(subset=["e1rm"]).sort_values("e1rm", ascending=False)
                    .groupby("exercise").first().reset_index()
                    [["exercise", "e1rm", "weight", "reps"]]
                    .rename(columns={"e1rm": "Est 1RM", "weight": "from weight",
                                     "reps": "x reps"}))
            st.dataframe(best, width="stretch", hide_index=True)


def page_physique():
    st.title("📸 Physique")
    st.caption("Upload progress photos and tag the muscle/area each shows. Lift Lab ties "
               "each photo to your bodyweight and the priority lifts that drive that muscle, "
               "so you can see whether a weak area is matched by weak driver-lifts.")

    with st.expander("➕ Add a photo", expanded=False):
        with st.form("add_photo", clear_on_submit=True):
            f = st.file_uploader("Photo", type=["png", "jpg", "jpeg", "webp"])
            cc1, cc2 = st.columns(2)
            d = cc1.date_input("Date taken", value=_dt.date.today())
            area = cc2.selectbox("Area shown", list(physique.AREA_TO_LIFTS.keys()))
            notes = st.text_input("Notes (optional)")
            if st.form_submit_button("Save photo") and f is not None:
                physique.add_photo(f.getvalue(), f.name, d, area, notes)
                st.success("Saved.")
                st.rerun()

    pdf = physique.photos_df()
    if pdf.empty:
        st.info("No photos yet. Add your progress pictures above to build the timeline.")
        return

    areas = ["All"] + sorted(pdf["area"].unique())
    pick = st.selectbox("Filter by area", areas)
    view = pdf if pick == "All" else pdf[pdf["area"] == pick]

    st.subheader(f"Timeline ({len(view)} photos)")
    for _, row in view.iterrows():
        ctx = physique.context_for_photo(row.to_dict(), daily, routine, A)
        cols = st.columns([1, 2])
        with cols[0]:
            if Path(row["path"]).exists():
                st.image(row["path"], width="stretch")
        with cols[1]:
            st.markdown(f"**{row['date'].date()} — {row['area']}**")
            if ctx["bodyweight"]:
                st.write(f"Bodyweight: **{ctx['bodyweight']} lb**")
            if ctx["lifts"]:
                st.write("Driver lifts (best e1RM by then):")
                st.table(pd.DataFrame(ctx["lifts"]).rename(
                    columns={"lift": "Lift", "e1rm": "Est 1RM (lb)"}))
            else:
                st.caption("No driver-lift history yet for this area.")
            if row["notes"]:
                st.caption(f"📝 {row['notes']}")
            if st.button("Delete", key=f"del_{row['file']}"):
                physique.delete_photo(row["file"])
                st.rerun()
        st.divider()

    st.subheader("How to read this")
    st.write("If a body part looks like a weak point in your photos, check its driver lifts: "
             "if those e1RMs are flat or low relative to your other lifts, prioritising them "
             "(more frequency/volume) is the highest-leverage fix. Use the **Plateaus** page to "
             "see which of them have stalled.")


def page_nutrition():
    st.title("🥗 Nutrition & Activity")
    if daily.empty:
        st.info("No daily weight/calorie data found.")
        return

    goal = st.radio("Current goal", ["Lose fat", "Build muscle", "Improve a lift"],
                    horizontal=True, key="goal")

    s = A.nutrition_summary(daily, days=28)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Bodyweight", f"{s.get('weight_now','?')} lb",
              f"{s.get('rate_lb_per_week','?')} lb/wk")
    c2.metric("Avg calories", f"{s.get('avg_calories','?')}")
    c3.metric("Avg deficit", f"{s.get('avg_deficit','?')} kcal")
    c4.metric("Avg steps", f"{s.get('avg_steps','?')}")

    st.subheader("Weight vs. calorie balance")
    df = daily.copy()
    if "weight" in df and "deficit" in df:
        cc = st.columns(2)
        with cc[0]:
            st.caption("Smoothed bodyweight")
            bwt = A.bodyweight_trend(daily)
            if not bwt.empty:
                st.line_chart(bwt.set_index("date")[["smoothed"]], height=240)
        with cc[1]:
            st.caption("Calorie balance vs maintenance (7-day avg)")
            d2 = df.dropna(subset=["deficit"]).set_index("date")[["deficit"]]
            if not d2.empty:
                st.line_chart(d2.rolling(7, min_periods=1).mean(), height=240)

    st.subheader("Diminishing returns")
    st.caption("Each block ≈ 3 weeks. When the weekly rate flattens despite a deficit (or stalls "
               "despite a surplus when bulking), you've hit diminishing returns — time to shift "
               "focus rather than push the same lever harder.")
    dr = A.diminishing_returns(daily)
    if not dr.empty:
        disp = dr.copy()
        disp["period_start"] = disp["period_start"].dt.date
        disp["period_end"] = disp["period_end"].dt.date
        st.dataframe(disp.tail(12).rename(columns={
            "period_start": "From", "period_end": "To",
            "rate_lb_per_week": "Rate (lb/wk)", "avg_deficit": "Avg deficit",
            "avg_weight": "Avg weight"}), width="stretch", hide_index=True)
        st.line_chart(dr.set_index("period_end")[["rate_lb_per_week"]], height=220)

    st.subheader("🎯 What to do")
    for tip in A.coaching_recommendations(daily, routine, goal):
        st.write("• " + tip)


def page_plateaus():
    st.title("🧱 Plateaus & Coaching")
    st.caption("A lift is flagged as plateaued if its best estimated-1RM hasn't improved in "
               "~8 weeks. 'Regression risk' = a long time since you trained it hard.")

    window = st.slider("Plateau window (weeks)", 4, 16, 8)
    overview = A.plateau_overview(routine, min_sets=8, window_days=window * 7)
    if overview.empty:
        st.info("Not enough data to assess plateaus.")
        return

    counts = overview["status"].value_counts()
    c1, c2, c3 = st.columns(3)
    c1.metric("Progressing", int(counts.get("progressing", 0)))
    c2.metric("Plateaued", int(counts.get("plateau", 0)))
    c3.metric("Regression risk", int(counts.get("regression_risk", 0)))

    show = overview.copy()
    show["last_trained"] = pd.to_datetime(show["last_trained"]).dt.date
    emoji = {"progressing": "✅", "plateau": "⛔", "regression_risk": "⚠️"}
    show["status"] = show["status"].map(lambda s: f"{emoji.get(s,'')} {s}")
    st.dataframe(show.rename(columns={
        "exercise": "Exercise", "status": "Status", "all_time_best": "All-time e1RM",
        "recent_best": "Recent best", "gain_pct": "Gain % (window)",
        "days_since_pr": "Days since PR", "sessions_in_window": "Sessions",
        "last_trained": "Last trained"}),
        width="stretch", hide_index=True, height=420)

    st.subheader("Break-through plan")
    stalled = overview[overview["status"] != "progressing"]["exercise"].tolist()
    options = stalled or overview["exercise"].tolist()
    ex = st.selectbox("Pick a lift for specific advice", options)
    info = A.detect_plateau(routine, ex, window_days=window * 7)
    sb = A.session_best(routine, ex).dropna(subset=["best_e1rm"])
    if not sb.empty:
        st.line_chart(sb.set_index("date")[["e1rm", "best_e1rm"]], height=240)
    for tip in A.plateau_advice(info):
        st.write("• " + tip)


PAGES = {
    "📊 Overview": page_overview,
    "🏋️ Exercises": page_exercises,
    "🏆 PRs": page_prs,
    "📸 Physique": page_physique,
    "🥗 Nutrition & Activity": page_nutrition,
    "🧱 Plateaus & Coaching": page_plateaus,
}
PAGES[PAGE]()
