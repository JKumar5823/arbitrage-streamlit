"""
ClinicalVoice EHR - Clinical Voice-Enabled Electronic Health Record System
A Streamlit application that records clinical interactions, generates structured
notes via AI, manages patient records, prescriptions, billing, and provider-patient
communication with AI-assisted draft responses.
"""

import streamlit as st
import pandas as pd
import json
from datetime import datetime, timedelta, date
import io
import time

from database import Database
from ai_engine import AIEngine, ENCOUNTER_TEMPLATES, ICD10_CODES, CPT_CODES

# ── Page Config ─────────────────────────────────────────────────────

st.set_page_config(
    page_title="ClinicalVoice EHR",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ──────────────────────────────────────────────────────

st.markdown("""
<style>
    /* Main EHR styling */
    .main-header {
        background: linear-gradient(135deg, #1a365d 0%, #2d5f8a 100%);
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 8px;
        margin-bottom: 1.5rem;
    }
    .main-header h1 {
        margin: 0;
        font-size: 1.6rem;
        font-weight: 600;
    }
    .main-header p {
        margin: 0.3rem 0 0 0;
        opacity: 0.85;
        font-size: 0.9rem;
    }
    .patient-banner {
        background: #edf2f7;
        border-left: 4px solid #2d5f8a;
        padding: 0.8rem 1.2rem;
        border-radius: 0 6px 6px 0;
        margin-bottom: 1rem;
    }
    .status-badge {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .badge-active { background: #c6f6d5; color: #22543d; }
    .badge-pending { background: #fefcbf; color: #744210; }
    .badge-completed { background: #bee3f8; color: #2a4365; }
    .badge-signed { background: #c6f6d5; color: #22543d; }
    .badge-unsigned { background: #fed7d7; color: #822727; }
    .metric-card {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    .metric-card h3 {
        font-size: 2rem;
        margin: 0;
        color: #2d5f8a;
    }
    .metric-card p {
        margin: 0.3rem 0 0 0;
        color: #718096;
        font-size: 0.85rem;
    }
    .soap-section {
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 0.8rem;
    }
    .soap-section h4 {
        color: #2d5f8a;
        margin-top: 0;
        border-bottom: 2px solid #2d5f8a;
        padding-bottom: 0.3rem;
    }
    .message-bubble {
        padding: 0.8rem 1rem;
        border-radius: 12px;
        margin-bottom: 0.5rem;
        max-width: 85%;
    }
    .msg-patient {
        background: #ebf8ff;
        border: 1px solid #bee3f8;
        margin-right: auto;
    }
    .msg-provider {
        background: #f0fff4;
        border: 1px solid #c6f6d5;
        margin-left: auto;
    }
    .recording-indicator {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 0.5rem 1rem;
        border-radius: 20px;
        font-weight: 600;
    }
    .recording-active {
        background: #fed7d7;
        color: #c53030;
        animation: pulse 1.5s infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.6; }
    }
    .voice-transcript {
        background: #fffaf0;
        border: 1px solid #fbd38d;
        border-radius: 8px;
        padding: 1rem;
        font-family: 'Georgia', serif;
        line-height: 1.7;
        max-height: 400px;
        overflow-y: auto;
    }
    div[data-testid="stSidebar"] {
        background: #1a365d;
    }
    div[data-testid="stSidebar"] .stMarkdown p,
    div[data-testid="stSidebar"] .stMarkdown h1,
    div[data-testid="stSidebar"] .stMarkdown h2,
    div[data-testid="stSidebar"] .stMarkdown h3 {
        color: white;
    }
    .rx-card {
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem;
        margin-bottom: 0.5rem;
        background: white;
    }
</style>
""", unsafe_allow_html=True)

# ── Initialize Database & AI ────────────────────────────────────────


@st.cache_resource
def init_database():
    db = Database()
    db.seed_sample_data()
    return db


@st.cache_resource
def init_ai():
    return AIEngine()


db = init_database()
ai = init_ai()

# ── Session State ───────────────────────────────────────────────────

if "current_page" not in st.session_state:
    st.session_state.current_page = "Dashboard"
if "current_provider_id" not in st.session_state:
    st.session_state.current_provider_id = 1
if "selected_patient_id" not in st.session_state:
    st.session_state.selected_patient_id = None
if "encounter_in_progress" not in st.session_state:
    st.session_state.encounter_in_progress = None
if "recording_active" not in st.session_state:
    st.session_state.recording_active = False
if "transcription_text" not in st.session_state:
    st.session_state.transcription_text = ""
if "generated_notes" not in st.session_state:
    st.session_state.generated_notes = None
if "current_encounter_id" not in st.session_state:
    st.session_state.current_encounter_id = None
if "view_note_id" not in st.session_state:
    st.session_state.view_note_id = None
if "view_message_id" not in st.session_state:
    st.session_state.view_message_id = None

# ── Sidebar ─────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ClinicalVoice EHR")
    st.markdown("---")

    providers = db.get_providers()
    provider_options = {f"Dr. {p['first_name']} {p['last_name']} ({p['specialty']})": p["id"] for p in providers}
    selected_provider = st.selectbox("Logged in as:", list(provider_options.keys()))
    st.session_state.current_provider_id = provider_options[selected_provider]
    current_provider = db.get_provider(st.session_state.current_provider_id)

    st.markdown("---")

    nav_items = [
        ("Dashboard", "📊"),
        ("Patients", "👥"),
        ("Voice Encounter", "🎤"),
        ("Clinical Notes", "📋"),
        ("Prescriptions", "💊"),
        ("Messages", "✉️"),
        ("Billing", "💰"),
    ]
    for label, icon in nav_items:
        if st.button(f"{icon}  {label}", key=f"nav_{label}", use_container_width=True):
            st.session_state.current_page = label

    st.markdown("---")

    stats = db.get_dashboard_stats(st.session_state.current_provider_id)
    if stats["unsigned_notes"] > 0:
        st.warning(f"Unsigned notes: {stats['unsigned_notes']}")
    if stats["unread_messages"] > 0:
        st.info(f"Unread messages: {stats['unread_messages']}")

# ── Helper Functions ────────────────────────────────────────────────


def calculate_age(dob_str):
    if not dob_str:
        return "N/A"
    try:
        dob = datetime.strptime(str(dob_str), "%Y-%m-%d")
        today = datetime.now()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    except (ValueError, TypeError):
        return "N/A"


def format_datetime(dt_str):
    if not dt_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(str(dt_str))
        return dt.strftime("%b %d, %Y %I:%M %p")
    except (ValueError, TypeError):
        return str(dt_str)[:16]


def format_date(dt_str):
    if not dt_str:
        return "N/A"
    try:
        dt = datetime.strptime(str(dt_str)[:10], "%Y-%m-%d")
        return dt.strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return str(dt_str)[:10]


def render_patient_banner(patient):
    age = calculate_age(patient.get("date_of_birth"))
    st.markdown(f"""
    <div class="patient-banner">
        <strong>{patient['first_name']} {patient['last_name']}</strong>
        &nbsp;|&nbsp; MRN: {patient['mrn']}
        &nbsp;|&nbsp; DOB: {format_date(patient.get('date_of_birth'))} (Age: {age})
        &nbsp;|&nbsp; {patient.get('gender', 'N/A')}
        &nbsp;|&nbsp; Allergies: <span style="color:#c53030; font-weight:600">{patient.get('allergies', 'None known')}</span>
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# PAGE: Dashboard
# ══════════════════════════════════════════════════════════════════

def page_dashboard():
    st.markdown("""
    <div class="main-header">
        <h1>Provider Dashboard</h1>
        <p>Clinical overview and pending actions</p>
    </div>
    """, unsafe_allow_html=True)

    provider = db.get_provider(st.session_state.current_provider_id)
    st.markdown(f"**Welcome, Dr. {provider['first_name']} {provider['last_name']}** | "
                f"{provider['specialty']} | {datetime.now().strftime('%A, %B %d, %Y')}")

    stats = db.get_dashboard_stats(st.session_state.current_provider_id)

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("Total Patients", stats["total_patients"])
    with col2:
        st.metric("Today's Visits", stats["today_encounters"])
    with col3:
        st.metric("Open Encounters", stats["open_encounters"])
    with col4:
        st.metric("Unsigned Notes", stats["unsigned_notes"])
    with col5:
        st.metric("Unread Messages", stats["unread_messages"])
    with col6:
        st.metric("Pending Refills", stats["pending_refills"])

    st.markdown("---")

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.subheader("Recent Encounters")
        encounters = db.get_recent_encounters(
            provider_id=st.session_state.current_provider_id, limit=8
        )
        if encounters:
            for enc in encounters:
                status_class = "badge-completed" if enc["status"] == "Completed" else "badge-pending"
                st.markdown(f"""
                <div style="border:1px solid #e2e8f0; border-radius:6px; padding:0.7rem; margin-bottom:0.5rem; background:white;">
                    <strong>{enc['patient_name']}</strong> ({enc['mrn']})
                    <span class="status-badge {status_class}">{enc['status']}</span><br>
                    <small>{format_datetime(enc['encounter_date'])} | {enc['encounter_type']} | {enc.get('chief_complaint', 'N/A')}</small>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No recent encounters.")

    with col_right:
        st.subheader("Action Items")

        unsigned = db.get_notes(is_signed=False)
        unsigned_mine = [n for n in unsigned if n["provider_id"] == st.session_state.current_provider_id]
        if unsigned_mine:
            st.markdown("**Notes Awaiting Signature:**")
            for note in unsigned_mine[:5]:
                st.markdown(f"- {note['patient_name']} - {format_date(note['encounter_date'])} "
                            f"({note.get('chief_complaint', 'N/A')})")

        unread = db.get_messages(
            provider_id=st.session_state.current_provider_id, is_read=False
        )
        patient_msgs = [m for m in unread if m["sender_type"] == "patient"]
        if patient_msgs:
            st.markdown("**Unread Patient Messages:**")
            for msg in patient_msgs[:5]:
                st.markdown(f"- **{msg['patient_name']}**: {msg['subject']}")

        if not unsigned_mine and not patient_msgs:
            st.success("All caught up! No pending actions.")

        st.markdown("---")
        st.subheader("Quick Actions")
        if st.button("Start New Encounter", key="dash_new_enc", use_container_width=True):
            st.session_state.current_page = "Voice Encounter"
            st.rerun()
        if st.button("View Messages", key="dash_msgs", use_container_width=True):
            st.session_state.current_page = "Messages"
            st.rerun()


# ══════════════════════════════════════════════════════════════════
# PAGE: Patients
# ══════════════════════════════════════════════════════════════════

def page_patients():
    st.markdown("""
    <div class="main-header">
        <h1>Patient Records</h1>
        <p>Search, view, and manage patient charts</p>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["Patient List", "Add New Patient"])

    with tab1:
        search = st.text_input("Search patients (name or MRN):", placeholder="Type to search...")
        patients = db.get_patients(search=search if search else None)

        if patients:
            for patient in patients:
                age = calculate_age(patient.get("date_of_birth"))
                with st.expander(
                    f"{patient['last_name']}, {patient['first_name']} | "
                    f"MRN: {patient['mrn']} | Age: {age} | {patient.get('gender', 'N/A')}"
                ):
                    render_patient_banner(patient)

                    ptab1, ptab2, ptab3, ptab4, ptab5 = st.tabs([
                        "Demographics", "Encounters", "Medications",
                        "Notes Summary", "Problem List"
                    ])

                    with ptab1:
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown(f"**Phone:** {patient.get('phone', 'N/A')}")
                            st.markdown(f"**Email:** {patient.get('email', 'N/A')}")
                            st.markdown(f"**Address:** {patient.get('address', 'N/A')}")
                            st.markdown(f"**Blood Type:** {patient.get('blood_type', 'N/A')}")
                        with c2:
                            st.markdown(f"**Insurance:** {patient.get('insurance_provider', 'N/A')}")
                            st.markdown(f"**Policy #:** {patient.get('insurance_id', 'N/A')}")
                            st.markdown(f"**Emergency Contact:** {patient.get('emergency_contact_name', 'N/A')}")
                            st.markdown(f"**Emergency Phone:** {patient.get('emergency_contact_phone', 'N/A')}")

                    with ptab2:
                        enc_list = db.get_encounters(patient_id=patient["id"])
                        if enc_list:
                            for enc in enc_list:
                                status_icon = "✅" if enc["status"] == "Completed" else "🔄"
                                st.markdown(
                                    f"{status_icon} **{format_datetime(enc['encounter_date'])}** - "
                                    f"{enc['encounter_type']} with {enc['provider_name']} | "
                                    f"{enc.get('chief_complaint', 'N/A')} | "
                                    f"Duration: {enc.get('duration_minutes', 'N/A')} min"
                                )
                        else:
                            st.info("No encounters on record.")

                    with ptab3:
                        rxs = db.get_prescriptions(patient_id=patient["id"])
                        active_rx = [r for r in rxs if r["status"] == "Active"]
                        if active_rx:
                            for rx in active_rx:
                                refill_text = f"{rx['refills_remaining']}/{rx['refills_total']}"
                                st.markdown(
                                    f"**{rx['medication_name']}** {rx['dosage']} - "
                                    f"{rx['frequency']} ({rx['route']}) | "
                                    f"Refills: {refill_text} | "
                                    f"Prescribed by: {rx['provider_name']}"
                                )
                        else:
                            st.info("No active medications.")

                    with ptab4:
                        notes = db.get_notes(patient_id=patient["id"])
                        if notes:
                            summary = ai.summarize_notes(notes, patient)
                            st.markdown(summary)
                        else:
                            st.info("No clinical notes available.")

                    with ptab5:
                        problem_list = patient.get("problem_list", "")
                        if problem_list:
                            for prob in problem_list.split(","):
                                st.markdown(f"- {prob.strip()}")
                        else:
                            st.info("No active problems listed.")

                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("Start Encounter", key=f"enc_{patient['id']}"):
                            st.session_state.selected_patient_id = patient["id"]
                            st.session_state.current_page = "Voice Encounter"
                            st.rerun()
                    with c2:
                        if st.button("Send Message", key=f"msg_{patient['id']}"):
                            st.session_state.selected_patient_id = patient["id"]
                            st.session_state.current_page = "Messages"
                            st.rerun()
        else:
            st.info("No patients found.")

    with tab2:
        st.subheader("Register New Patient")
        with st.form("new_patient_form"):
            c1, c2, c3 = st.columns(3)
            with c1:
                first_name = st.text_input("First Name*")
                last_name = st.text_input("Last Name*")
                dob = st.date_input("Date of Birth", min_value=date(1920, 1, 1), max_value=date.today())
                gender = st.selectbox("Gender", ["Male", "Female", "Non-binary", "Other", "Prefer not to say"])
            with c2:
                phone = st.text_input("Phone")
                email = st.text_input("Email")
                address = st.text_area("Address", height=100)
                blood_type = st.selectbox("Blood Type", ["Unknown", "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"])
            with c3:
                insurance = st.text_input("Insurance Provider")
                insurance_id = st.text_input("Insurance Policy #")
                emergency_name = st.text_input("Emergency Contact Name")
                emergency_phone = st.text_input("Emergency Contact Phone")

            allergies = st.text_input("Allergies (comma-separated)", "None known")
            problems = st.text_input("Problem List (comma-separated)")

            submitted = st.form_submit_button("Register Patient", use_container_width=True)
            if submitted:
                if not first_name or not last_name:
                    st.error("First name and last name are required.")
                else:
                    mrn = f"MRN-{100000 + len(db.get_patients()) + 1}"
                    pid = db.add_patient(
                        mrn=mrn,
                        first_name=first_name,
                        last_name=last_name,
                        date_of_birth=dob.isoformat(),
                        gender=gender,
                        phone=phone,
                        email=email,
                        address=address,
                        insurance_provider=insurance,
                        insurance_id=insurance_id,
                        emergency_contact_name=emergency_name,
                        emergency_contact_phone=emergency_phone,
                        blood_type=blood_type if blood_type != "Unknown" else "",
                        allergies=allergies,
                        problem_list=problems,
                    )
                    db.log_action("provider", st.session_state.current_provider_id,
                                  "create", "patient", pid, f"Registered new patient: {first_name} {last_name}")
                    st.success(f"Patient registered successfully! MRN: {mrn}")


# ══════════════════════════════════════════════════════════════════
# PAGE: Voice Encounter
# ══════════════════════════════════════════════════════════════════

def page_voice_encounter():
    st.markdown("""
    <div class="main-header">
        <h1>Voice Encounter</h1>
        <p>Record clinical interactions and generate structured notes</p>
    </div>
    """, unsafe_allow_html=True)

    if st.session_state.current_encounter_id:
        render_active_encounter()
        return

    st.subheader("Start New Encounter")

    patients = db.get_patients()
    patient_options = {
        f"{p['last_name']}, {p['first_name']} (MRN: {p['mrn']})": p["id"]
        for p in patients
    }

    preselected_idx = 0
    if st.session_state.selected_patient_id:
        for i, (label, pid) in enumerate(patient_options.items()):
            if pid == st.session_state.selected_patient_id:
                preselected_idx = i
                break

    selected = st.selectbox("Select Patient", list(patient_options.keys()), index=preselected_idx)
    patient_id = patient_options[selected]
    patient = db.get_patient(patient_id)

    if patient:
        render_patient_banner(patient)

    last_enc = db.get_last_encounter(patient_id)
    if last_enc:
        st.info(f"Last visit: {format_datetime(last_enc['encounter_date'])} "
                f"with {last_enc['provider_name']}")

    col1, col2 = st.columns(2)
    with col1:
        encounter_type = st.selectbox(
            "Encounter Type",
            ["Office Visit", "Telehealth", "Follow-up", "Urgent Visit", "Annual Wellness"]
        )
    with col2:
        chief_complaint = st.text_input(
            "Chief Complaint",
            placeholder="e.g., Follow-up for diabetes and hypertension"
        )

    st.markdown("---")
    st.subheader("Recording Mode")

    rec_tab1, rec_tab2 = st.tabs(["Demo Recording", "Upload Audio"])

    with rec_tab1:
        st.markdown("""
        **Demo Mode:** Simulates a clinical voice recording session. In production, this
        would use your device's microphone with real-time speech-to-text transcription
        (powered by Whisper, Azure Speech, or similar services).
        """)

        demo_scenarios = {
            "Select scenario...": None,
            "Diabetes & Hypertension Follow-up": "hypertension_diabetes",
            "Respiratory / Asthma Visit": "respiratory",
            "Back Pain with Radiculopathy": "back_pain",
            "Depression / Mental Health Follow-up": "mental_health",
            "General Follow-up / Wellness": "general_followup",
        }
        scenario = st.selectbox("Choose clinical scenario:", list(demo_scenarios.keys()))

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            start_rec = st.button("🎙️ Start Recording", use_container_width=True,
                                  disabled=demo_scenarios[scenario] is None)
        with col_b:
            stop_rec = st.button("⏹️ Stop Recording", use_container_width=True)
        with col_c:
            clear_rec = st.button("🗑️ Clear", use_container_width=True)

        if start_rec and demo_scenarios[scenario]:
            st.session_state.recording_active = True
            template_key = demo_scenarios[scenario]
            st.session_state.transcription_text = ai.transcribe_audio(
                encounter_type=template_key
            )
            if not chief_complaint:
                chief_complaint = ENCOUNTER_TEMPLATES[template_key]["chief_complaints"][0]

        if stop_rec:
            st.session_state.recording_active = False

        if clear_rec:
            st.session_state.recording_active = False
            st.session_state.transcription_text = ""
            st.session_state.generated_notes = None

        if st.session_state.recording_active:
            st.markdown("""
            <div class="recording-indicator recording-active">
                ● REC - Recording in progress...
            </div>
            """, unsafe_allow_html=True)

    with rec_tab2:
        st.markdown("Upload an audio file from a clinical encounter. "
                     "Supported formats: WAV, MP3, M4A, OGG.")
        uploaded = st.file_uploader(
            "Upload Audio File",
            type=["wav", "mp3", "m4a", "ogg"],
            key="audio_upload"
        )
        if uploaded:
            st.audio(uploaded)
            if st.button("Transcribe Audio"):
                with st.spinner("Transcribing audio..."):
                    time.sleep(1)
                    enc_key = ai.get_encounter_type_key(chief_complaint)
                    st.session_state.transcription_text = ai.transcribe_audio(
                        encounter_type=enc_key
                    )
                    st.success("Transcription complete!")

    if st.session_state.transcription_text:
        st.markdown("---")
        st.subheader("Transcription")
        st.markdown(f'<div class="voice-transcript">{st.session_state.transcription_text}</div>',
                    unsafe_allow_html=True)

        st.markdown("---")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🤖 Generate Structured Notes", use_container_width=True, type="primary"):
                with st.spinner("AI is generating structured clinical notes..."):
                    time.sleep(1)
                    notes = ai.generate_soap_notes(
                        st.session_state.transcription_text,
                        chief_complaint=chief_complaint,
                        patient_info=patient
                    )
                    notes["follow_up"] = ai.get_follow_up_text(chief_complaint)
                    st.session_state.generated_notes = notes

        with col2:
            if st.button("📋 Create Encounter & Save", use_container_width=True,
                         disabled=st.session_state.generated_notes is None):
                enc_id = db.create_encounter(
                    patient_id=patient_id,
                    provider_id=st.session_state.current_provider_id,
                    encounter_date=datetime.now().isoformat(),
                    encounter_type=encounter_type,
                    chief_complaint=chief_complaint,
                    duration_minutes=25,
                    status="In Progress",
                    raw_transcription=st.session_state.transcription_text,
                )

                notes = st.session_state.generated_notes
                note_id = db.create_note(
                    encounter_id=enc_id,
                    patient_id=patient_id,
                    provider_id=st.session_state.current_provider_id,
                    subjective=notes["subjective"],
                    objective=notes["objective"],
                    assessment=notes["assessment"],
                    plan=notes["plan"],
                    hpi=notes.get("hpi", ""),
                    ros=notes.get("ros", ""),
                    physical_exam=notes.get("physical_exam", ""),
                    vitals_json=notes.get("vitals_json", "{}"),
                    follow_up=notes.get("follow_up", ""),
                )

                billing = ai.suggest_billing_codes(
                    chief_complaint, notes, encounter_type
                )
                for code, desc in billing["icd10"]:
                    db.add_billing_code(
                        encounter_id=enc_id,
                        code_type="ICD-10",
                        code=code,
                        description=desc,
                    )
                for code, desc, amount in billing["cpt"]:
                    db.add_billing_code(
                        encounter_id=enc_id,
                        code_type="CPT",
                        code=code,
                        description=desc,
                        amount=amount,
                    )

                db.log_action("provider", st.session_state.current_provider_id,
                              "create", "encounter", enc_id,
                              f"Created encounter for patient {patient_id}")

                st.session_state.current_encounter_id = enc_id
                st.session_state.recording_active = False
                st.success("Encounter created! Notes and billing codes saved.")
                st.rerun()

    if st.session_state.generated_notes:
        st.markdown("---")
        st.subheader("Generated SOAP Notes (Preview)")
        notes = st.session_state.generated_notes
        render_soap_notes_display(notes)


def render_active_encounter():
    enc = db.get_encounter(st.session_state.current_encounter_id)
    if not enc:
        st.error("Encounter not found.")
        st.session_state.current_encounter_id = None
        return

    patient = db.get_patient(enc["patient_id"])
    render_patient_banner(patient)

    st.markdown(f"**Encounter #{enc['id']}** | {enc['encounter_type']} | "
                f"{format_datetime(enc['encounter_date'])} | Status: **{enc['status']}**")

    last_enc = db.get_last_encounter(enc["patient_id"], before_encounter_id=enc["id"])
    if last_enc:
        st.info(f"Previous visit: {format_datetime(last_enc['encounter_date'])} "
                f"with {last_enc['provider_name']}")

    enc_tabs = st.tabs(["SOAP Notes", "Transcription", "Billing Codes",
                         "Previous Notes", "Prescriptions"])

    with enc_tabs[0]:
        notes = db.get_notes(encounter_id=enc["id"])
        if notes:
            note = notes[0]
            if note["is_signed"]:
                st.success(f"Note signed by {note['provider_name']} on {format_datetime(note['signed_at'])}")

            with st.form("edit_soap"):
                subjective = st.text_area("Subjective", note["subjective"], height=120)
                objective = st.text_area("Objective", note["objective"], height=120)
                assessment = st.text_area("Assessment", note["assessment"], height=120)
                plan = st.text_area("Plan", note["plan"], height=120)
                follow_up = st.text_input("Follow-up", note.get("follow_up", ""))

                if note.get("vitals_json"):
                    st.markdown("**Vitals:**")
                    try:
                        vitals = json.loads(note["vitals_json"])
                        v_cols = st.columns(6)
                        labels = ["BP", "HR", "Temp", "Weight", "SpO2", "RR"]
                        keys = ["bp", "hr", "temp", "weight", "spo2", "rr"]
                        for i, (label, key) in enumerate(zip(labels, keys)):
                            with v_cols[i]:
                                st.text_input(label, vitals.get(key, ""), key=f"vital_{key}")
                    except (json.JSONDecodeError, TypeError):
                        pass

                col1, col2, col3 = st.columns(3)
                with col1:
                    save = st.form_submit_button("💾 Save Changes", use_container_width=True)
                with col2:
                    sign = st.form_submit_button("✅ Sign & Complete", use_container_width=True)
                with col3:
                    summarize = st.form_submit_button("🤖 AI Summary", use_container_width=True)

                if save:
                    db.update_note(note["id"],
                                   subjective=subjective, objective=objective,
                                   assessment=assessment, plan=plan, follow_up=follow_up)
                    st.success("Notes saved.")
                    st.rerun()

                if sign:
                    db.update_note(note["id"],
                                   subjective=subjective, objective=objective,
                                   assessment=assessment, plan=plan, follow_up=follow_up)
                    db.sign_note(note["id"], st.session_state.current_provider_id)
                    db.log_action("provider", st.session_state.current_provider_id,
                                  "sign", "clinical_note", note["id"],
                                  f"Signed note for encounter {enc['id']}")
                    st.success("Note signed and encounter completed!")
                    st.rerun()

                if summarize:
                    all_notes = db.get_notes(patient_id=enc["patient_id"])
                    summary = ai.summarize_notes(all_notes, patient)
                    db.update_note(note["id"], ai_summary=summary)
                    st.markdown("**AI-Generated Summary:**")
                    st.markdown(summary)

    with enc_tabs[1]:
        if enc.get("raw_transcription"):
            st.markdown(f'<div class="voice-transcript">{enc["raw_transcription"]}</div>',
                        unsafe_allow_html=True)
        else:
            st.info("No transcription available for this encounter.")

    with enc_tabs[2]:
        codes = db.get_billing_codes(encounter_id=enc["id"])
        if codes:
            icd_codes = [c for c in codes if c["code_type"] == "ICD-10"]
            cpt_codes = [c for c in codes if c["code_type"] == "CPT"]

            if icd_codes:
                st.markdown("**ICD-10 Diagnosis Codes:**")
                for c in icd_codes:
                    st.markdown(f"- `{c['code']}` - {c['description']}")
            if cpt_codes:
                st.markdown("**CPT Procedure Codes:**")
                for c in cpt_codes:
                    amount = f" (${c['amount']:.2f})" if c.get("amount") else ""
                    st.markdown(f"- `{c['code']}` - {c['description']}{amount}")

        with st.form("add_billing_code"):
            st.markdown("**Add Billing Code:**")
            bc1, bc2, bc3 = st.columns(3)
            with bc1:
                code_type = st.selectbox("Code Type", ["ICD-10", "CPT"])
            with bc2:
                code_val = st.text_input("Code", placeholder="e.g., I10 or 99214")
            with bc3:
                code_desc = st.text_input("Description", placeholder="Code description")
            if st.form_submit_button("Add Code"):
                if code_val:
                    db.add_billing_code(
                        encounter_id=enc["id"],
                        code_type=code_type,
                        code=code_val,
                        description=code_desc,
                    )
                    st.success(f"Added {code_type} code: {code_val}")
                    st.rerun()

    with enc_tabs[3]:
        prev_notes = db.get_notes(patient_id=enc["patient_id"])
        prev_notes = [n for n in prev_notes if n["encounter_id"] != enc["id"]]
        if prev_notes:
            for pn in prev_notes:
                signed_text = "Signed" if pn["is_signed"] else "Unsigned"
                with st.expander(
                    f"{format_date(pn['encounter_date'])} - {pn.get('chief_complaint', 'N/A')} "
                    f"({pn['provider_name']}) [{signed_text}]"
                ):
                    render_soap_notes_display(pn)
        else:
            st.info("No previous notes for this patient.")

    with enc_tabs[4]:
        rxs = db.get_prescriptions(patient_id=enc["patient_id"])
        active_rx = [r for r in rxs if r["status"] == "Active"]
        if active_rx:
            st.markdown("**Active Medications:**")
            for rx in active_rx:
                col_a, col_b = st.columns([4, 1])
                with col_a:
                    st.markdown(
                        f"**{rx['medication_name']}** {rx['dosage']} - {rx['frequency']} "
                        f"({rx['route']})\n\n"
                        f"Refills: {rx['refills_remaining']}/{rx['refills_total']} | "
                        f"Start: {format_date(rx['start_date'])} | "
                        f"Rx by: {rx['provider_name']}"
                    )
                with col_b:
                    if rx["refills_remaining"] > 0:
                        if st.button("Refill", key=f"refill_{rx['id']}"):
                            db.refill_prescription(rx["id"])
                            st.success(f"Refilled {rx['medication_name']}")
                            st.rerun()
                st.markdown("---")
        else:
            st.info("No active medications.")

    st.markdown("---")
    if st.button("← Back to New Encounter", use_container_width=True):
        st.session_state.current_encounter_id = None
        st.session_state.transcription_text = ""
        st.session_state.generated_notes = None
        st.rerun()


def render_soap_notes_display(notes):
    sections = [
        ("Subjective", "subjective"),
        ("Objective", "objective"),
        ("Assessment", "assessment"),
        ("Plan", "plan"),
    ]
    for title, key in sections:
        content = notes.get(key, "")
        if content:
            st.markdown(f"""
            <div class="soap-section">
                <h4>{title}</h4>
                <p style="white-space: pre-wrap;">{content}</p>
            </div>
            """, unsafe_allow_html=True)

    if notes.get("follow_up"):
        st.markdown(f"**Follow-up:** {notes['follow_up']}")


# ══════════════════════════════════════════════════════════════════
# PAGE: Clinical Notes
# ══════════════════════════════════════════════════════════════════

def page_clinical_notes():
    st.markdown("""
    <div class="main-header">
        <h1>Clinical Notes</h1>
        <p>View, edit, and sign clinical documentation</p>
    </div>
    """, unsafe_allow_html=True)

    tab_unsigned, tab_signed, tab_all = st.tabs(["Unsigned Notes", "Signed Notes", "All Notes"])

    with tab_unsigned:
        notes = db.get_notes(is_signed=False)
        my_notes = [n for n in notes if n["provider_id"] == st.session_state.current_provider_id]
        if my_notes:
            st.markdown(f"**{len(my_notes)} unsigned note(s) requiring attention**")
            for note in my_notes:
                with st.expander(
                    f"⚠️ {note['patient_name']} - {format_date(note['encounter_date'])} | "
                    f"{note.get('chief_complaint', 'N/A')}"
                ):
                    render_soap_notes_display(note)

                    if note.get("ai_summary"):
                        st.markdown("**AI Summary:**")
                        st.markdown(note["ai_summary"])

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if st.button("Open in Encounter", key=f"open_note_{note['id']}"):
                            st.session_state.current_encounter_id = note["encounter_id"]
                            st.session_state.current_page = "Voice Encounter"
                            st.rerun()
                    with col2:
                        if st.button("Generate Summary", key=f"sum_note_{note['id']}"):
                            patient = db.get_patient(note["patient_id"])
                            all_notes = db.get_notes(patient_id=note["patient_id"])
                            summary = ai.summarize_notes(all_notes, patient)
                            db.update_note(note["id"], ai_summary=summary)
                            st.rerun()
                    with col3:
                        if st.button("Quick Sign", key=f"sign_note_{note['id']}"):
                            db.sign_note(note["id"], st.session_state.current_provider_id)
                            db.log_action("provider", st.session_state.current_provider_id,
                                          "sign", "clinical_note", note["id"], "Quick signed")
                            st.success("Note signed!")
                            st.rerun()
        else:
            st.success("No unsigned notes. All documentation is complete.")

    with tab_signed:
        notes = db.get_notes(is_signed=True)
        my_notes = [n for n in notes if n["provider_id"] == st.session_state.current_provider_id]
        if my_notes:
            for note in my_notes:
                with st.expander(
                    f"✅ {note['patient_name']} - {format_date(note['encounter_date'])} | "
                    f"{note.get('chief_complaint', 'N/A')} | "
                    f"Signed: {format_datetime(note.get('signed_at'))}"
                ):
                    render_soap_notes_display(note)
                    if note.get("ai_summary"):
                        st.markdown("**AI Summary:**")
                        st.markdown(note["ai_summary"])
        else:
            st.info("No signed notes found.")

    with tab_all:
        patients = db.get_patients()
        patient_filter = st.selectbox(
            "Filter by patient:",
            ["All Patients"] + [f"{p['last_name']}, {p['first_name']} ({p['mrn']})" for p in patients]
        )

        patient_id_filter = None
        if patient_filter != "All Patients":
            for p in patients:
                if f"{p['last_name']}, {p['first_name']} ({p['mrn']})" == patient_filter:
                    patient_id_filter = p["id"]
                    break

        all_notes = db.get_notes(patient_id=patient_id_filter)
        if all_notes:
            df_data = []
            for n in all_notes:
                df_data.append({
                    "Date": format_date(n["encounter_date"]),
                    "Patient": n["patient_name"],
                    "Provider": n["provider_name"],
                    "Type": n.get("encounter_type", ""),
                    "Chief Complaint": n.get("chief_complaint", ""),
                    "Status": "Signed" if n["is_signed"] else "Unsigned",
                })
            st.dataframe(pd.DataFrame(df_data), use_container_width=True, hide_index=True)
        else:
            st.info("No notes found.")


# ══════════════════════════════════════════════════════════════════
# PAGE: Prescriptions
# ══════════════════════════════════════════════════════════════════

def page_prescriptions():
    st.markdown("""
    <div class="main-header">
        <h1>Prescriptions</h1>
        <p>Manage medications and refills</p>
    </div>
    """, unsafe_allow_html=True)

    tab_active, tab_add, tab_all = st.tabs(["Active Medications", "New Prescription", "All Prescriptions"])

    with tab_active:
        patients = db.get_patients()
        patient_filter = st.selectbox(
            "Filter by patient:",
            ["All Patients"] + [f"{p['last_name']}, {p['first_name']} ({p['mrn']})" for p in patients],
            key="rx_patient_filter"
        )

        patient_id_filter = None
        if patient_filter != "All Patients":
            for p in patients:
                if f"{p['last_name']}, {p['first_name']} ({p['mrn']})" == patient_filter:
                    patient_id_filter = p["id"]
                    break

        rxs = db.get_prescriptions(patient_id=patient_id_filter, status="Active")
        if rxs:
            for rx in rxs:
                with st.container():
                    col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
                    with col1:
                        st.markdown(f"**{rx['medication_name']}** {rx['dosage']}")
                        st.caption(f"{rx['frequency']} | {rx['route']}")
                    with col2:
                        st.markdown(f"**Patient:** {rx['patient_name']}")
                        st.caption(f"Prescribed by: {rx['provider_name']}")
                    with col3:
                        refill_pct = (rx["refills_remaining"] / rx["refills_total"] * 100) if rx["refills_total"] > 0 else 0
                        st.markdown(f"**Refills:** {rx['refills_remaining']}/{rx['refills_total']}")
                        st.progress(refill_pct / 100)
                        if rx.get("last_refill_date"):
                            st.caption(f"Last refill: {format_date(rx['last_refill_date'])}")
                    with col4:
                        if rx["refills_remaining"] > 0:
                            if st.button("Refill", key=f"rx_refill_{rx['id']}"):
                                db.refill_prescription(rx["id"])
                                db.log_action("provider", st.session_state.current_provider_id,
                                              "refill", "prescription", rx["id"],
                                              f"Refilled {rx['medication_name']}")
                                st.success(f"Refilled {rx['medication_name']}")
                                st.rerun()
                        else:
                            st.caption("No refills")
                        if st.button("D/C", key=f"rx_dc_{rx['id']}", help="Discontinue"):
                            db.update_prescription(rx["id"], status="Discontinued")
                            st.rerun()
                    st.markdown("---")
        else:
            st.info("No active prescriptions found.")

    with tab_add:
        st.subheader("Prescribe New Medication")
        with st.form("new_rx_form"):
            patients = db.get_patients()
            pt_options = {f"{p['last_name']}, {p['first_name']} ({p['mrn']})": p["id"] for p in patients}
            pt_select = st.selectbox("Patient*", list(pt_options.keys()))

            c1, c2 = st.columns(2)
            with c1:
                med_name = st.text_input("Medication Name*", placeholder="e.g., Lisinopril")
                dosage = st.text_input("Dosage*", placeholder="e.g., 10mg")
                frequency = st.text_input("Frequency*", placeholder="e.g., Once daily")
            with c2:
                route = st.selectbox("Route", ["Oral", "Topical", "Inhalation", "Injectable",
                                                "Rectal", "Sublingual", "Transdermal", "Ophthalmic"])
                refills = st.number_input("Number of Refills", 0, 12, 3)
                pharmacy = st.text_input("Pharmacy", placeholder="e.g., CVS Pharmacy")

            notes = st.text_area("Notes", placeholder="Additional instructions or notes")

            if st.form_submit_button("Prescribe Medication", use_container_width=True):
                if not med_name or not dosage or not frequency:
                    st.error("Medication name, dosage, and frequency are required.")
                else:
                    rx_id = db.add_prescription(
                        patient_id=pt_options[pt_select],
                        provider_id=st.session_state.current_provider_id,
                        medication_name=med_name,
                        dosage=dosage,
                        frequency=frequency,
                        route=route,
                        start_date=date.today().isoformat(),
                        refills_total=refills,
                        refills_remaining=refills,
                        pharmacy=pharmacy,
                        notes=notes,
                    )
                    db.log_action("provider", st.session_state.current_provider_id,
                                  "prescribe", "prescription", rx_id,
                                  f"Prescribed {med_name} {dosage}")
                    st.success(f"Prescription created for {med_name} {dosage}.")

    with tab_all:
        all_rx = db.get_prescriptions()
        if all_rx:
            df_data = []
            for rx in all_rx:
                df_data.append({
                    "Patient": rx["patient_name"],
                    "Medication": rx["medication_name"],
                    "Dosage": rx["dosage"],
                    "Frequency": rx["frequency"],
                    "Route": rx["route"],
                    "Refills Left": f"{rx['refills_remaining']}/{rx['refills_total']}",
                    "Status": rx["status"],
                    "Prescriber": rx["provider_name"],
                    "Start Date": format_date(rx["start_date"]),
                })
            st.dataframe(pd.DataFrame(df_data), use_container_width=True, hide_index=True)
        else:
            st.info("No prescriptions found.")


# ══════════════════════════════════════════════════════════════════
# PAGE: Messages (In-Basket)
# ══════════════════════════════════════════════════════════════════

def page_messages():
    st.markdown("""
    <div class="main-header">
        <h1>In-Basket Messages</h1>
        <p>Provider-patient communication with AI-assisted responses</p>
    </div>
    """, unsafe_allow_html=True)

    tab_inbox, tab_compose, tab_drafts = st.tabs(["Inbox", "Compose Message", "AI Drafts"])

    with tab_inbox:
        messages = db.get_messages(provider_id=st.session_state.current_provider_id)
        patient_msgs = [m for m in messages if m["sender_type"] == "patient" and not m["is_draft"]]

        unread = [m for m in patient_msgs if not m["is_read"]]
        read = [m for m in patient_msgs if m["is_read"]]

        if unread:
            st.markdown(f"**Unread Messages ({len(unread)})**")
            for msg in unread:
                with st.expander(f"🔴 {msg['patient_name']} - {msg['subject']} "
                                 f"({format_datetime(msg['created_at'])})"):
                    db.mark_message_read(msg["id"])

                    st.markdown(f"""
                    <div class="message-bubble msg-patient">
                        <strong>{msg['patient_name']}</strong>
                        <small> | {format_datetime(msg['created_at'])}</small><br><br>
                        {msg['body']}
                    </div>
                    """, unsafe_allow_html=True)

                    thread = db.get_thread(msg["id"])
                    replies = [t for t in thread if t["id"] != msg["id"] and not t["is_draft"]]
                    for reply in replies:
                        bubble_class = "msg-provider" if reply["sender_type"] == "provider" else "msg-patient"
                        sender = reply["provider_name"] if reply["sender_type"] == "provider" else reply["patient_name"]
                        st.markdown(f"""
                        <div class="message-bubble {bubble_class}">
                            <strong>{sender}</strong>
                            <small> | {format_datetime(reply['created_at'])}</small><br><br>
                            {reply['body']}
                        </div>
                        """, unsafe_allow_html=True)

                    st.markdown("---")

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("🤖 Generate AI Draft", key=f"ai_draft_{msg['id']}"):
                            patient = db.get_patient(msg["patient_id"])
                            rxs = db.get_prescriptions(patient_id=msg["patient_id"], status="Active")
                            notes = db.get_notes(patient_id=msg["patient_id"])
                            draft = ai.draft_message_response(
                                msg["body"], patient_info=patient,
                                recent_notes=notes, prescriptions=rxs,
                            )
                            draft_id = db.send_message(
                                patient_id=msg["patient_id"],
                                provider_id=st.session_state.current_provider_id,
                                sender_type="provider",
                                subject=f"Re: {msg['subject']}",
                                body=draft,
                                is_draft=1,
                                is_ai_generated=1,
                                parent_message_id=msg["id"],
                            )
                            st.success("AI draft generated! Check the AI Drafts tab to review and send.")
                            st.rerun()

                    with col2:
                        with st.form(f"reply_form_{msg['id']}"):
                            reply_text = st.text_area("Reply:", key=f"reply_text_{msg['id']}", height=100)
                            if st.form_submit_button("Send Reply"):
                                if reply_text:
                                    db.send_message(
                                        patient_id=msg["patient_id"],
                                        provider_id=st.session_state.current_provider_id,
                                        sender_type="provider",
                                        subject=f"Re: {msg['subject']}",
                                        body=reply_text,
                                        is_signed=1,
                                        signed_by=st.session_state.current_provider_id,
                                        signed_at=datetime.now().isoformat(),
                                        parent_message_id=msg["id"],
                                    )
                                    st.success("Reply sent!")
                                    st.rerun()

        if read:
            st.markdown(f"**Read Messages ({len(read)})**")
            for msg in read:
                with st.expander(f"✅ {msg['patient_name']} - {msg['subject']} "
                                 f"({format_datetime(msg['created_at'])})"):
                    st.markdown(f"""
                    <div class="message-bubble msg-patient">
                        <strong>{msg['patient_name']}</strong>
                        <small> | {format_datetime(msg['created_at'])}</small><br><br>
                        {msg['body']}
                    </div>
                    """, unsafe_allow_html=True)

                    thread = db.get_thread(msg["id"])
                    replies = [t for t in thread if t["id"] != msg["id"] and not t["is_draft"]]
                    for reply in replies:
                        bubble_class = "msg-provider" if reply["sender_type"] == "provider" else "msg-patient"
                        sender = reply["provider_name"] if reply["sender_type"] == "provider" else reply["patient_name"]
                        st.markdown(f"""
                        <div class="message-bubble {bubble_class}">
                            <strong>{sender}</strong>
                            <small> | {format_datetime(reply['created_at'])}</small><br><br>
                            {reply['body']}
                        </div>
                        """, unsafe_allow_html=True)

        if not patient_msgs:
            st.info("No messages in inbox.")

    with tab_compose:
        st.subheader("Send Message to Patient")
        with st.form("compose_message"):
            patients = db.get_patients()
            pt_options = {f"{p['last_name']}, {p['first_name']} ({p['mrn']})": p["id"] for p in patients}

            preselected_idx = 0
            if st.session_state.selected_patient_id:
                for i, (_, pid) in enumerate(pt_options.items()):
                    if pid == st.session_state.selected_patient_id:
                        preselected_idx = i
                        break

            pt_select = st.selectbox("To (Patient):", list(pt_options.keys()), index=preselected_idx)
            subject = st.text_input("Subject:")
            body = st.text_area("Message:", height=200)
            send_btn = st.form_submit_button("Send Message", use_container_width=True)

            if send_btn:
                if not subject or not body:
                    st.error("Subject and message body are required.")
                else:
                    db.send_message(
                        patient_id=pt_options[pt_select],
                        provider_id=st.session_state.current_provider_id,
                        sender_type="provider",
                        subject=subject,
                        body=body,
                        is_signed=1,
                        signed_by=st.session_state.current_provider_id,
                        signed_at=datetime.now().isoformat(),
                    )
                    db.log_action("provider", st.session_state.current_provider_id,
                                  "send_message", "message", 0,
                                  f"Sent message to patient {pt_options[pt_select]}")
                    st.success("Message sent!")

    with tab_drafts:
        st.subheader("AI-Generated Draft Responses")
        st.markdown("Review, edit, and sign AI-drafted responses before sending to patients.")

        drafts = db.get_messages(
            provider_id=st.session_state.current_provider_id, is_draft=True
        )
        ai_drafts = [d for d in drafts if d["is_ai_generated"]]

        if ai_drafts:
            for draft in ai_drafts:
                with st.expander(
                    f"📝 Draft for {draft['patient_name']} - {draft['subject']} "
                    f"({format_datetime(draft['created_at'])})"
                ):
                    if draft.get("parent_message_id"):
                        parent = db.get_message(draft["parent_message_id"])
                        if parent:
                            st.markdown("**Original message from patient:**")
                            st.markdown(f"""
                            <div class="message-bubble msg-patient">
                                {parent['body']}
                            </div>
                            """, unsafe_allow_html=True)
                            st.markdown("---")

                    st.markdown("**AI-Generated Draft Response:**")
                    with st.form(f"draft_form_{draft['id']}"):
                        edited_body = st.text_area(
                            "Edit response before sending:",
                            draft["body"],
                            height=250,
                            key=f"draft_body_{draft['id']}"
                        )

                        col1, col2, col3 = st.columns(3)
                        with col1:
                            sign_send = st.form_submit_button(
                                "✅ Sign & Send", use_container_width=True
                            )
                        with col2:
                            save_draft = st.form_submit_button(
                                "💾 Save Edits", use_container_width=True
                            )
                        with col3:
                            discard = st.form_submit_button(
                                "🗑️ Discard", use_container_width=True
                            )

                        if sign_send:
                            conn = db.get_conn()
                            conn.execute(
                                "UPDATE messages SET body = ? WHERE id = ?",
                                (edited_body, draft["id"])
                            )
                            conn.commit()
                            conn.close()
                            db.sign_and_send_message(
                                draft["id"], st.session_state.current_provider_id
                            )
                            db.log_action("provider", st.session_state.current_provider_id,
                                          "sign_send", "message", draft["id"],
                                          "Signed and sent AI draft")
                            st.success("Response signed and sent to patient!")
                            st.rerun()

                        if save_draft:
                            conn = db.get_conn()
                            conn.execute(
                                "UPDATE messages SET body = ? WHERE id = ?",
                                (edited_body, draft["id"])
                            )
                            conn.commit()
                            conn.close()
                            st.success("Draft saved.")
                            st.rerun()

                        if discard:
                            conn = db.get_conn()
                            conn.execute("DELETE FROM messages WHERE id = ?", (draft["id"],))
                            conn.commit()
                            conn.close()
                            st.info("Draft discarded.")
                            st.rerun()
        else:
            st.info("No AI drafts pending review. "
                     "Generate drafts from the Inbox tab by clicking 'Generate AI Draft' on patient messages.")


# ══════════════════════════════════════════════════════════════════
# PAGE: Billing
# ══════════════════════════════════════════════════════════════════

def page_billing():
    st.markdown("""
    <div class="main-header">
        <h1>Billing & Coding</h1>
        <p>Clinical billing codes and encounter charges</p>
    </div>
    """, unsafe_allow_html=True)

    tab_encounters, tab_lookup, tab_report = st.tabs([
        "Encounter Billing", "Code Lookup", "Billing Report"
    ])

    with tab_encounters:
        encounters = db.get_encounters(provider_id=st.session_state.current_provider_id)
        if encounters:
            for enc in encounters:
                codes = db.get_billing_codes(encounter_id=enc["id"])
                total = sum(c.get("amount", 0) for c in codes)
                icd_count = len([c for c in codes if c["code_type"] == "ICD-10"])
                cpt_count = len([c for c in codes if c["code_type"] == "CPT"])

                with st.expander(
                    f"{enc['patient_name']} | {format_date(enc['encounter_date'])} | "
                    f"{enc['encounter_type']} | Codes: {icd_count} ICD + {cpt_count} CPT | "
                    f"Total: ${total:.2f}"
                ):
                    st.markdown(f"**Chief Complaint:** {enc.get('chief_complaint', 'N/A')}")
                    st.markdown(f"**Status:** {enc['status']} | "
                                f"**Duration:** {enc.get('duration_minutes', 'N/A')} min | "
                                f"**Visit Time:** {format_datetime(enc['encounter_date'])}")

                    if codes:
                        df_codes = pd.DataFrame([{
                            "Type": c["code_type"],
                            "Code": c["code"],
                            "Description": c["description"],
                            "Amount": f"${c.get('amount', 0):.2f}" if c.get("amount") else "-",
                        } for c in codes])
                        st.dataframe(df_codes, use_container_width=True, hide_index=True)
                    else:
                        st.info("No billing codes assigned.")

                    if st.button("Add Missing Codes", key=f"add_codes_{enc['id']}"):
                        notes = db.get_notes(encounter_id=enc["id"])
                        if notes:
                            billing = ai.suggest_billing_codes(
                                enc.get("chief_complaint", ""),
                                {"assessment": notes[0].get("assessment", "")},
                                enc["encounter_type"],
                            )
                            added = 0
                            existing = {c["code"] for c in codes}
                            for code, desc in billing["icd10"]:
                                if code not in existing:
                                    db.add_billing_code(
                                        encounter_id=enc["id"],
                                        code_type="ICD-10", code=code, description=desc,
                                    )
                                    added += 1
                            for code, desc, amount in billing["cpt"]:
                                if code not in existing:
                                    db.add_billing_code(
                                        encounter_id=enc["id"],
                                        code_type="CPT", code=code, description=desc, amount=amount,
                                    )
                                    added += 1
                            if added:
                                st.success(f"Added {added} billing code(s).")
                                st.rerun()
                            else:
                                st.info("All suggested codes already present.")
        else:
            st.info("No encounters found.")

    with tab_lookup:
        st.subheader("ICD-10 Code Lookup")
        icd_search = st.text_input("Search ICD-10 codes by keyword:", placeholder="e.g., diabetes, back pain, anxiety")
        if icd_search:
            results = []
            for keyword, codes in ICD10_CODES.items():
                if icd_search.lower() in keyword:
                    for code, desc in codes:
                        results.append({"Code": code, "Description": desc, "Category": keyword.title()})
            if results:
                st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
            else:
                st.info("No matching codes found.")

        st.markdown("---")

        st.subheader("CPT Code Reference")
        cpt_data = []
        for key, (code, desc, amount) in CPT_CODES.items():
            cpt_data.append({
                "Code": code,
                "Description": desc,
                "Fee": f"${amount:.2f}",
                "Category": key.replace("_", " ").title(),
            })
        st.dataframe(pd.DataFrame(cpt_data), use_container_width=True, hide_index=True)

    with tab_report:
        st.subheader("Billing Summary Report")
        encounters = db.get_encounters(provider_id=st.session_state.current_provider_id)

        if encounters:
            total_charges = 0
            encounter_data = []
            for enc in encounters:
                codes = db.get_billing_codes(encounter_id=enc["id"])
                enc_total = sum(c.get("amount", 0) for c in codes)
                total_charges += enc_total
                cpt_list = [c["code"] for c in codes if c["code_type"] == "CPT"]
                icd_list = [c["code"] for c in codes if c["code_type"] == "ICD-10"]
                encounter_data.append({
                    "Date": format_date(enc["encounter_date"]),
                    "Patient": enc["patient_name"],
                    "Type": enc["encounter_type"],
                    "CPT Codes": ", ".join(cpt_list) if cpt_list else "None",
                    "ICD-10 Codes": ", ".join(icd_list) if icd_list else "None",
                    "Charges": f"${enc_total:.2f}",
                    "Status": enc["status"],
                })

            st.metric("Total Charges", f"${total_charges:.2f}")
            st.metric("Total Encounters", len(encounters))

            df = pd.DataFrame(encounter_data)
            st.dataframe(df, use_container_width=True, hide_index=True)

            csv = df.to_csv(index=False)
            st.download_button(
                "Download Billing Report (CSV)",
                csv,
                "billing_report.csv",
                "text/csv",
                use_container_width=True,
            )
        else:
            st.info("No billing data available.")


# ══════════════════════════════════════════════════════════════════
# Main Router
# ══════════════════════════════════════════════════════════════════

PAGE_MAP = {
    "Dashboard": page_dashboard,
    "Patients": page_patients,
    "Voice Encounter": page_voice_encounter,
    "Clinical Notes": page_clinical_notes,
    "Prescriptions": page_prescriptions,
    "Messages": page_messages,
    "Billing": page_billing,
}

page_fn = PAGE_MAP.get(st.session_state.current_page, page_dashboard)
page_fn()
