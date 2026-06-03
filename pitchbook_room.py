"""PitchBook Capture Room — a local control panel.

Run this ON YOUR OWN LAPTOP (not a server):

    pip install -r requirements.txt
    streamlit run pitchbook_room.py

It drives your real cursor, captures PitchBook screenshots, extracts the data
with Claude vision (Tesseract OCR fallback), and stores it in your cloud SQL
database (set DATABASE_URL) or a local SQLite file.

Use only within your own licensed PitchBook access and at human-paced rates.
"""

from __future__ import annotations

import os
import time
from datetime import datetime

import pandas as pd
import streamlit as st
from PIL import Image

from pitchbook import cursor as cur
from pitchbook import extract as ex
from pitchbook import storage

st.set_page_config(page_title="PitchBook Capture Room", layout="wide")

SHOT_DIR = os.environ.get("PITCHBOOK_SHOT_DIR", "captures")
os.makedirs(SHOT_DIR, exist_ok=True)


# --- shared resources -------------------------------------------------------

@st.cache_resource
def get_db(url: str | None):
    return storage.Database(url or None)


def _session_defaults():
    st.session_state.setdefault("last_image_path", None)
    st.session_state.setdefault("last_records", [])
    st.session_state.setdefault("last_method", "")
    st.session_state.setdefault("last_source_label", "")


_session_defaults()


# --- sidebar: connection + status ------------------------------------------

st.sidebar.title("⚙️ Room settings")

api_key = st.sidebar.text_input(
    "Anthropic API key",
    value=os.environ.get("ANTHROPIC_API_KEY", ""),
    type="password",
    help="Used for Claude-vision extraction. Leave blank to use OCR only.",
)
model = st.sidebar.text_input("Vision model", value=ex.DEFAULT_MODEL)

db_url = st.sidebar.text_input(
    "DATABASE_URL (cloud SQL)",
    value=os.environ.get("DATABASE_URL", ""),
    type="password",
    help="Cloud Postgres URL (AWS RDS / Neon / Supabase). Blank = local SQLite.",
)

db = get_db(db_url)
if db.is_cloud():
    st.sidebar.success(f"☁️ Connected to cloud DB ({db.backend})")
else:
    st.sidebar.info(f"💾 Local SQLite ({storage.DEFAULT_SQLITE_PATH})")
st.sidebar.caption(f"Stored records: {db.count()}")

try:
    w, h = cur.screen_size()
    st.sidebar.caption(f"🖥️ Screen detected: {w}×{h}px")
    display_ok = True
except cur.NoDisplayError:
    st.sidebar.error("No display detected — cursor/capture run only on your laptop.")
    display_ok = False


st.title("🎯 PitchBook Capture Room")
st.caption(
    "Control your cursor → capture a PitchBook screen → extract structured "
    "data with Claude → store it in your database."
)

tab_capture, tab_cursor, tab_db = st.tabs(
    ["📸 Capture & extract", "🖱️ Cursor control", "🗄️ Database"]
)


# --- tab: cursor control ----------------------------------------------------

with tab_cursor:
    st.subheader("Drive the cursor")
    st.write(
        "Move the mouse to a target on PitchBook, then read its coordinates "
        "here to build a capture region. Slam the mouse into a screen corner "
        "to abort any running action (pyautogui fail-safe)."
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📍 Read current cursor position", disabled=not display_ok):
            x, y = cur.get_position()
            st.info(f"Cursor at **({x}, {y})**")
    with c2:
        if st.button("🔄 Refresh screen size", disabled=not display_ok):
            st.info(f"Screen: {cur.screen_size()}")

    st.divider()
    st.markdown("**Move / click**")
    mc1, mc2, mc3, mc4 = st.columns(4)
    with mc1:
        mx = st.number_input("X", min_value=0, value=100, step=10)
    with mc2:
        my = st.number_input("Y", min_value=0, value=100, step=10)
    with mc3:
        btn = st.selectbox("Button", ["left", "right", "middle"])
    with mc4:
        clicks = st.number_input("Clicks", min_value=1, max_value=3, value=1)

    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        if st.button("➡️ Move to", disabled=not display_ok):
            st.success(f"Moved to {cur.move_to(int(mx), int(my))}")
    with bc2:
        if st.button("🖱️ Click", disabled=not display_ok):
            st.success(f"Clicked at {cur.click(int(mx), int(my), button=btn, clicks=int(clicks))}")
    with bc3:
        scroll_amt = st.number_input("Scroll (±)", value=-300, step=100)
        if st.button("↕️ Scroll", disabled=not display_ok):
            cur.scroll(int(scroll_amt))
            st.success("Scrolled.")


# --- tab: capture & extract -------------------------------------------------

with tab_capture:
    st.subheader("1 · Capture a screenshot")

    delay = st.slider(
        "Countdown before capture (seconds)",
        0, 10, 4,
        help="Use the delay to alt-tab to your PitchBook window before capture.",
    )

    use_region = st.checkbox("Capture a region only (else full screen)")
    region = None
    if use_region:
        rc1, rc2, rc3, rc4 = st.columns(4)
        with rc1:
            rl = st.number_input("Left", min_value=0, value=0, step=10)
        with rc2:
            rt = st.number_input("Top", min_value=0, value=0, step=10)
        with rc3:
            rw = st.number_input("Width", min_value=1, value=1200, step=10)
        with rc4:
            rh = st.number_input("Height", min_value=1, value=800, step=10)
        region = cur.Region(int(rl), int(rt), int(rw), int(rh))

    source_label = st.text_input(
        "Source label (saved with the rows)",
        value=st.session_state["last_source_label"],
        placeholder="e.g. Sequoia Capital — recent deals",
    )

    if st.button("📸 Capture now", type="primary", disabled=not display_ok):
        if delay:
            ph = st.empty()
            cur.countdown(delay, on_tick=lambda r: ph.warning(f"Capturing in {r}…"))
            ph.empty()
        path = os.path.join(SHOT_DIR, f"shot_{datetime.now():%Y%m%d_%H%M%S}.png")
        cur.capture_to_file(path, region)
        st.session_state["last_image_path"] = path
        st.session_state["last_source_label"] = source_label
        st.session_state["last_records"] = []
        st.success(f"Saved {path}")

    # Also allow uploading a screenshot (handy when testing off your laptop).
    uploaded = st.file_uploader("…or upload a screenshot", type=["png", "jpg", "jpeg"])
    if uploaded is not None:
        path = os.path.join(SHOT_DIR, f"upload_{datetime.now():%Y%m%d_%H%M%S}.png")
        Image.open(uploaded).convert("RGB").save(path)
        st.session_state["last_image_path"] = path
        st.session_state["last_records"] = []

    img_path = st.session_state["last_image_path"]
    if img_path and os.path.exists(img_path):
        st.image(img_path, caption=img_path, use_container_width=True)

        st.subheader("2 · Extract structured data")
        instructions = st.text_area(
            "Extra extraction instructions (optional)",
            placeholder="e.g. Only extract deals after 2023; treat the first column as company name.",
        )
        prefer = "claude" if api_key else "ocr"
        if not api_key:
            st.warning("No API key — using local OCR (raw text only).")

        if st.button("🤖 Extract", type="primary"):
            with st.spinner("Reading the screenshot…"):
                result = ex.extract(
                    Image.open(img_path),
                    instructions=instructions,
                    api_key=api_key or None,
                    model=model,
                    prefer=prefer,
                )
            st.session_state["last_records"] = result.records
            st.session_state["last_method"] = result.method
            if result.error:
                st.warning(result.error)
            if result.records:
                st.success(f"Extracted {len(result.records)} record(s) via {result.method}.")
            else:
                st.error("No records extracted.")

    # Review + save
    records = st.session_state["last_records"]
    if records:
        st.subheader("3 · Review & save")
        df = pd.json_normalize(records)
        edited = st.data_editor(df, num_rows="dynamic", use_container_width=True)
        if st.button("💾 Save to database", type="primary"):
            to_save = edited.where(pd.notnull(edited), None).to_dict(orient="records")
            n = db.save_records(
                to_save,
                source_label=st.session_state["last_source_label"],
                extraction_method=st.session_state["last_method"],
                screenshot_path=st.session_state["last_image_path"] or "",
            )
            st.success(f"Saved {n} record(s) to {db.backend}.")
            st.cache_resource.clear()


# --- tab: database ----------------------------------------------------------

with tab_db:
    st.subheader("Stored records")
    st.caption(f"Backend: {db.backend} · total rows: {db.count()}")
    limit = st.slider("Rows to show", 10, 1000, 200, step=10)
    if st.button("🔄 Refresh"):
        st.cache_resource.clear()
    df = db.fetch_df(limit=limit)
    if df.empty:
        st.info("No records yet. Capture and save some from the first tab.")
    else:
        st.dataframe(df, use_container_width=True)
        st.download_button(
            "📥 Download CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="pitchbook_records.csv",
            mime="text/csv",
        )
