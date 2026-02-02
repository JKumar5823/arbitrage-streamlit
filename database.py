"""
Clinical Voice EHR - Database Layer
SQLite-based EHR database mimicking EPIC EHR functionality.
Manages patients, providers, encounters, clinical notes, prescriptions,
billing codes, and provider-patient messaging.
"""

import sqlite3
import os
import json
from datetime import datetime, timedelta, date
import random

DB_PATH = "clinical_ehr.db"


class Database:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.init_db()

    def get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self):
        conn = self.get_conn()
        c = conn.cursor()

        c.executescript("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mrn TEXT UNIQUE NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            date_of_birth DATE,
            gender TEXT,
            phone TEXT,
            email TEXT,
            address TEXT,
            insurance_provider TEXT,
            insurance_id TEXT,
            emergency_contact_name TEXT,
            emergency_contact_phone TEXT,
            blood_type TEXT,
            allergies TEXT,
            problem_list TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS providers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            npi TEXT UNIQUE NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            specialty TEXT,
            department TEXT,
            email TEXT,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS encounters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL REFERENCES patients(id),
            provider_id INTEGER NOT NULL REFERENCES providers(id),
            encounter_date TIMESTAMP NOT NULL,
            encounter_type TEXT DEFAULT 'Office Visit',
            chief_complaint TEXT,
            duration_minutes INTEGER,
            status TEXT DEFAULT 'In Progress',
            voice_recording_path TEXT,
            raw_transcription TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS clinical_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encounter_id INTEGER NOT NULL REFERENCES encounters(id),
            patient_id INTEGER NOT NULL REFERENCES patients(id),
            provider_id INTEGER NOT NULL REFERENCES providers(id),
            note_type TEXT DEFAULT 'SOAP',
            subjective TEXT,
            objective TEXT,
            assessment TEXT,
            plan TEXT,
            hpi TEXT,
            ros TEXT,
            physical_exam TEXT,
            vitals_json TEXT,
            follow_up TEXT,
            ai_summary TEXT,
            is_signed INTEGER DEFAULT 0,
            signed_by INTEGER REFERENCES providers(id),
            signed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS prescriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL REFERENCES patients(id),
            provider_id INTEGER NOT NULL REFERENCES providers(id),
            encounter_id INTEGER REFERENCES encounters(id),
            medication_name TEXT NOT NULL,
            dosage TEXT,
            frequency TEXT,
            route TEXT DEFAULT 'Oral',
            start_date DATE,
            end_date DATE,
            refills_total INTEGER DEFAULT 0,
            refills_remaining INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Active',
            pharmacy TEXT,
            notes TEXT,
            prescribed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_refill_date TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS billing_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encounter_id INTEGER NOT NULL REFERENCES encounters(id),
            code_type TEXT NOT NULL,
            code TEXT NOT NULL,
            description TEXT,
            amount REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL REFERENCES patients(id),
            provider_id INTEGER NOT NULL REFERENCES providers(id),
            sender_type TEXT NOT NULL,
            subject TEXT,
            body TEXT NOT NULL,
            is_draft INTEGER DEFAULT 0,
            is_ai_generated INTEGER DEFAULT 0,
            is_read INTEGER DEFAULT 0,
            is_signed INTEGER DEFAULT 0,
            parent_message_id INTEGER REFERENCES messages(id),
            signed_by INTEGER REFERENCES providers(id),
            signed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_type TEXT,
            user_id INTEGER,
            action TEXT,
            entity_type TEXT,
            entity_id INTEGER,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()
        conn.close()

    # ── Patient Operations ──────────────────────────────────────────

    def get_patients(self, search=None):
        conn = self.get_conn()
        if search:
            query = """
                SELECT * FROM patients
                WHERE first_name LIKE ? OR last_name LIKE ? OR mrn LIKE ?
                ORDER BY last_name, first_name
            """
            s = f"%{search}%"
            rows = conn.execute(query, (s, s, s)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM patients ORDER BY last_name, first_name"
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_patient(self, patient_id):
        conn = self.get_conn()
        row = conn.execute(
            "SELECT * FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_patient_by_mrn(self, mrn):
        conn = self.get_conn()
        row = conn.execute(
            "SELECT * FROM patients WHERE mrn = ?", (mrn,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def add_patient(self, **kwargs):
        conn = self.get_conn()
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * len(kwargs))
        conn.execute(
            f"INSERT INTO patients ({cols}) VALUES ({placeholders})",
            list(kwargs.values()),
        )
        conn.commit()
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return pid

    def update_patient(self, patient_id, **kwargs):
        conn = self.get_conn()
        sets = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        vals = list(kwargs.values()) + [patient_id]
        conn.execute(f"UPDATE patients SET {sets} WHERE id = ?", vals)
        conn.commit()
        conn.close()

    # ── Provider Operations ─────────────────────────────────────────

    def get_providers(self):
        conn = self.get_conn()
        rows = conn.execute(
            "SELECT * FROM providers ORDER BY last_name, first_name"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_provider(self, provider_id):
        conn = self.get_conn()
        row = conn.execute(
            "SELECT * FROM providers WHERE id = ?", (provider_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def add_provider(self, **kwargs):
        conn = self.get_conn()
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * len(kwargs))
        conn.execute(
            f"INSERT INTO providers ({cols}) VALUES ({placeholders})",
            list(kwargs.values()),
        )
        conn.commit()
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return pid

    # ── Encounter Operations ────────────────────────────────────────

    def get_encounters(self, patient_id=None, provider_id=None, status=None, limit=50):
        conn = self.get_conn()
        query = """
            SELECT e.*,
                   p.first_name || ' ' || p.last_name AS patient_name,
                   p.mrn,
                   pr.first_name || ' ' || pr.last_name AS provider_name,
                   pr.specialty AS provider_specialty
            FROM encounters e
            JOIN patients p ON e.patient_id = p.id
            JOIN providers pr ON e.provider_id = pr.id
            WHERE 1=1
        """
        params = []
        if patient_id:
            query += " AND e.patient_id = ?"
            params.append(patient_id)
        if provider_id:
            query += " AND e.provider_id = ?"
            params.append(provider_id)
        if status:
            query += " AND e.status = ?"
            params.append(status)
        query += " ORDER BY e.encounter_date DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_encounter(self, encounter_id):
        conn = self.get_conn()
        row = conn.execute("""
            SELECT e.*,
                   p.first_name || ' ' || p.last_name AS patient_name,
                   p.mrn, p.date_of_birth, p.gender, p.allergies,
                   pr.first_name || ' ' || pr.last_name AS provider_name,
                   pr.specialty AS provider_specialty
            FROM encounters e
            JOIN patients p ON e.patient_id = p.id
            JOIN providers pr ON e.provider_id = pr.id
            WHERE e.id = ?
        """, (encounter_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_encounter(self, **kwargs):
        conn = self.get_conn()
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * len(kwargs))
        conn.execute(
            f"INSERT INTO encounters ({cols}) VALUES ({placeholders})",
            list(kwargs.values()),
        )
        conn.commit()
        eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return eid

    def update_encounter(self, encounter_id, **kwargs):
        conn = self.get_conn()
        sets = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        vals = list(kwargs.values()) + [encounter_id]
        conn.execute(f"UPDATE encounters SET {sets} WHERE id = ?", vals)
        conn.commit()
        conn.close()

    def get_last_encounter(self, patient_id, before_encounter_id=None):
        conn = self.get_conn()
        query = """
            SELECT e.*, pr.first_name || ' ' || pr.last_name AS provider_name
            FROM encounters e
            JOIN providers pr ON e.provider_id = pr.id
            WHERE e.patient_id = ? AND e.status = 'Completed'
        """
        params = [patient_id]
        if before_encounter_id:
            query += " AND e.id < ?"
            params.append(before_encounter_id)
        query += " ORDER BY e.encounter_date DESC LIMIT 1"
        row = conn.execute(query, params).fetchone()
        conn.close()
        return dict(row) if row else None

    # ── Clinical Notes Operations ───────────────────────────────────

    def get_notes(self, encounter_id=None, patient_id=None, is_signed=None):
        conn = self.get_conn()
        query = """
            SELECT cn.*,
                   p.first_name || ' ' || p.last_name AS patient_name,
                   pr.first_name || ' ' || pr.last_name AS provider_name,
                   e.encounter_date, e.encounter_type, e.chief_complaint
            FROM clinical_notes cn
            JOIN patients p ON cn.patient_id = p.id
            JOIN providers pr ON cn.provider_id = pr.id
            JOIN encounters e ON cn.encounter_id = e.id
            WHERE 1=1
        """
        params = []
        if encounter_id:
            query += " AND cn.encounter_id = ?"
            params.append(encounter_id)
        if patient_id:
            query += " AND cn.patient_id = ?"
            params.append(patient_id)
        if is_signed is not None:
            query += " AND cn.is_signed = ?"
            params.append(1 if is_signed else 0)
        query += " ORDER BY cn.created_at DESC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_note(self, note_id):
        conn = self.get_conn()
        row = conn.execute("""
            SELECT cn.*,
                   p.first_name || ' ' || p.last_name AS patient_name,
                   pr.first_name || ' ' || pr.last_name AS provider_name,
                   e.encounter_date, e.encounter_type, e.chief_complaint
            FROM clinical_notes cn
            JOIN patients p ON cn.patient_id = p.id
            JOIN providers pr ON cn.provider_id = pr.id
            JOIN encounters e ON cn.encounter_id = e.id
            WHERE cn.id = ?
        """, (note_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_note(self, **kwargs):
        conn = self.get_conn()
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * len(kwargs))
        conn.execute(
            f"INSERT INTO clinical_notes ({cols}) VALUES ({placeholders})",
            list(kwargs.values()),
        )
        conn.commit()
        nid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return nid

    def update_note(self, note_id, **kwargs):
        conn = self.get_conn()
        sets = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        vals = list(kwargs.values()) + [note_id]
        conn.execute(f"UPDATE clinical_notes SET {sets} WHERE id = ?", vals)
        conn.commit()
        conn.close()

    def sign_note(self, note_id, provider_id):
        conn = self.get_conn()
        conn.execute("""
            UPDATE clinical_notes
            SET is_signed = 1, signed_by = ?, signed_at = ?
            WHERE id = ?
        """, (provider_id, datetime.now().isoformat(), note_id))
        note = conn.execute(
            "SELECT encounter_id FROM clinical_notes WHERE id = ?", (note_id,)
        ).fetchone()
        if note:
            conn.execute("""
                UPDATE encounters SET status = 'Completed' WHERE id = ?
            """, (note["encounter_id"],))
        conn.commit()
        conn.close()

    # ── Prescription Operations ─────────────────────────────────────

    def get_prescriptions(self, patient_id=None, status=None):
        conn = self.get_conn()
        query = """
            SELECT rx.*,
                   p.first_name || ' ' || p.last_name AS patient_name,
                   pr.first_name || ' ' || pr.last_name AS provider_name
            FROM prescriptions rx
            JOIN patients p ON rx.patient_id = p.id
            JOIN providers pr ON rx.provider_id = pr.id
            WHERE 1=1
        """
        params = []
        if patient_id:
            query += " AND rx.patient_id = ?"
            params.append(patient_id)
        if status:
            query += " AND rx.status = ?"
            params.append(status)
        query += " ORDER BY rx.prescribed_date DESC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_prescription(self, **kwargs):
        conn = self.get_conn()
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * len(kwargs))
        conn.execute(
            f"INSERT INTO prescriptions ({cols}) VALUES ({placeholders})",
            list(kwargs.values()),
        )
        conn.commit()
        rxid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return rxid

    def update_prescription(self, rx_id, **kwargs):
        conn = self.get_conn()
        sets = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        vals = list(kwargs.values()) + [rx_id]
        conn.execute(f"UPDATE prescriptions SET {sets} WHERE id = ?", vals)
        conn.commit()
        conn.close()

    def refill_prescription(self, rx_id):
        conn = self.get_conn()
        rx = conn.execute(
            "SELECT * FROM prescriptions WHERE id = ?", (rx_id,)
        ).fetchone()
        if rx and rx["refills_remaining"] > 0:
            conn.execute("""
                UPDATE prescriptions
                SET refills_remaining = refills_remaining - 1,
                    last_refill_date = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), rx_id))
            conn.commit()
            conn.close()
            return True
        conn.close()
        return False

    # ── Billing Code Operations ─────────────────────────────────────

    def get_billing_codes(self, encounter_id=None):
        conn = self.get_conn()
        if encounter_id:
            rows = conn.execute(
                "SELECT * FROM billing_codes WHERE encounter_id = ? ORDER BY code_type, code",
                (encounter_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM billing_codes ORDER BY created_at DESC"
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_billing_code(self, **kwargs):
        conn = self.get_conn()
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * len(kwargs))
        conn.execute(
            f"INSERT INTO billing_codes ({cols}) VALUES ({placeholders})",
            list(kwargs.values()),
        )
        conn.commit()
        bid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return bid

    def delete_billing_code(self, code_id):
        conn = self.get_conn()
        conn.execute("DELETE FROM billing_codes WHERE id = ?", (code_id,))
        conn.commit()
        conn.close()

    # ── Message Operations ──────────────────────────────────────────

    def get_messages(self, patient_id=None, provider_id=None, is_read=None, is_draft=None):
        conn = self.get_conn()
        query = """
            SELECT m.*,
                   p.first_name || ' ' || p.last_name AS patient_name,
                   p.mrn,
                   pr.first_name || ' ' || pr.last_name AS provider_name
            FROM messages m
            JOIN patients p ON m.patient_id = p.id
            JOIN providers pr ON m.provider_id = pr.id
            WHERE 1=1
        """
        params = []
        if patient_id:
            query += " AND m.patient_id = ?"
            params.append(patient_id)
        if provider_id:
            query += " AND m.provider_id = ?"
            params.append(provider_id)
        if is_read is not None:
            query += " AND m.is_read = ?"
            params.append(1 if is_read else 0)
        if is_draft is not None:
            query += " AND m.is_draft = ?"
            params.append(1 if is_draft else 0)
        query += " ORDER BY m.created_at DESC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_message(self, message_id):
        conn = self.get_conn()
        row = conn.execute("""
            SELECT m.*,
                   p.first_name || ' ' || p.last_name AS patient_name,
                   pr.first_name || ' ' || pr.last_name AS provider_name
            FROM messages m
            JOIN patients p ON m.patient_id = p.id
            JOIN providers pr ON m.provider_id = pr.id
            WHERE m.id = ?
        """, (message_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_thread(self, message_id):
        conn = self.get_conn()
        root = conn.execute(
            "SELECT * FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if not root:
            conn.close()
            return []
        root_id = root["parent_message_id"] or root["id"]
        rows = conn.execute("""
            SELECT m.*,
                   p.first_name || ' ' || p.last_name AS patient_name,
                   pr.first_name || ' ' || pr.last_name AS provider_name
            FROM messages m
            JOIN patients p ON m.patient_id = p.id
            JOIN providers pr ON m.provider_id = pr.id
            WHERE m.id = ? OR m.parent_message_id = ?
            ORDER BY m.created_at ASC
        """, (root_id, root_id)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def send_message(self, **kwargs):
        conn = self.get_conn()
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * len(kwargs))
        conn.execute(
            f"INSERT INTO messages ({cols}) VALUES ({placeholders})",
            list(kwargs.values()),
        )
        conn.commit()
        mid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return mid

    def mark_message_read(self, message_id):
        conn = self.get_conn()
        conn.execute("UPDATE messages SET is_read = 1 WHERE id = ?", (message_id,))
        conn.commit()
        conn.close()

    def sign_and_send_message(self, message_id, provider_id):
        conn = self.get_conn()
        conn.execute("""
            UPDATE messages
            SET is_draft = 0, is_signed = 1, signed_by = ?, signed_at = ?
            WHERE id = ?
        """, (provider_id, datetime.now().isoformat(), message_id))
        conn.commit()
        conn.close()

    # ── Dashboard / Analytics ───────────────────────────────────────

    def get_dashboard_stats(self, provider_id=None):
        conn = self.get_conn()
        stats = {}

        pq = "SELECT COUNT(*) FROM patients"
        stats["total_patients"] = conn.execute(pq).fetchone()[0]

        eq = "SELECT COUNT(*) FROM encounters WHERE status = 'In Progress'"
        if provider_id:
            eq += f" AND provider_id = {provider_id}"
        stats["open_encounters"] = conn.execute(eq).fetchone()[0]

        nq = "SELECT COUNT(*) FROM clinical_notes WHERE is_signed = 0"
        if provider_id:
            nq += f" AND provider_id = {provider_id}"
        stats["unsigned_notes"] = conn.execute(nq).fetchone()[0]

        mq = "SELECT COUNT(*) FROM messages WHERE is_read = 0 AND sender_type = 'patient'"
        if provider_id:
            mq += f" AND provider_id = {provider_id}"
        stats["unread_messages"] = conn.execute(mq).fetchone()[0]

        today = date.today().isoformat()
        tq = f"SELECT COUNT(*) FROM encounters WHERE DATE(encounter_date) = '{today}'"
        if provider_id:
            tq += f" AND provider_id = {provider_id}"
        stats["today_encounters"] = conn.execute(tq).fetchone()[0]

        rq = "SELECT COUNT(*) FROM prescriptions WHERE refills_remaining > 0 AND status = 'Active'"
        stats["pending_refills"] = conn.execute(rq).fetchone()[0]

        conn.close()
        return stats

    def get_recent_encounters(self, provider_id=None, limit=10):
        return self.get_encounters(provider_id=provider_id, limit=limit)

    # ── Audit Log ───────────────────────────────────────────────────

    def log_action(self, user_type, user_id, action, entity_type, entity_id, details=""):
        conn = self.get_conn()
        conn.execute("""
            INSERT INTO audit_log (user_type, user_id, action, entity_type, entity_id, details)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_type, user_id, action, entity_type, entity_id, details))
        conn.commit()
        conn.close()

    # ── Sample Data Seeding ─────────────────────────────────────────

    def seed_sample_data(self):
        conn = self.get_conn()
        existing = conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
        if existing > 0:
            conn.close()
            return False

        # Providers
        providers = [
            ("1234567890", "Sarah", "Chen", "Internal Medicine", "Primary Care",
             "s.chen@clinic.org", "555-0101"),
            ("1234567891", "James", "Wilson", "Cardiology", "Cardiology",
             "j.wilson@clinic.org", "555-0102"),
            ("1234567892", "Maria", "Garcia", "Family Medicine", "Primary Care",
             "m.garcia@clinic.org", "555-0103"),
            ("1234567893", "David", "Kim", "Endocrinology", "Specialty Care",
             "d.kim@clinic.org", "555-0104"),
        ]
        for pr in providers:
            conn.execute("""
                INSERT INTO providers (npi, first_name, last_name, specialty, department, email, phone)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, pr)

        # Patients
        patients_data = [
            ("MRN-100001", "John", "Martinez", "1958-03-15", "Male",
             "555-1001", "john.m@email.com", "123 Oak St, Springfield, IL 62701",
             "Blue Cross", "BC-445521", "Maria Martinez", "555-1002",
             "A+", "Penicillin, Sulfa drugs",
             "Hypertension, Type 2 Diabetes, Hyperlipidemia"),
            ("MRN-100002", "Emily", "Thompson", "1985-07-22", "Female",
             "555-1003", "emily.t@email.com", "456 Maple Ave, Springfield, IL 62702",
             "Aetna", "AE-889932", "Robert Thompson", "555-1004",
             "O+", "None known",
             "Asthma, Generalized Anxiety Disorder"),
            ("MRN-100003", "Robert", "Williams", "1972-11-08", "Male",
             "555-1005", "rob.w@email.com", "789 Elm Dr, Springfield, IL 62703",
             "United Health", "UH-667744", "Sandra Williams", "555-1006",
             "B+", "Latex",
             "GERD, Chronic Low Back Pain, Obesity"),
            ("MRN-100004", "Lisa", "Anderson", "1995-01-30", "Female",
             "555-1007", "lisa.a@email.com", "321 Pine Rd, Springfield, IL 62704",
             "Cigna", "CI-223311", "Mark Anderson", "555-1008",
             "AB+", "Ibuprofen",
             "Migraine, Iron Deficiency Anemia"),
            ("MRN-100005", "Michael", "Brown", "1965-09-12", "Male",
             "555-1009", "mike.b@email.com", "654 Cedar Ln, Springfield, IL 62705",
             "Medicare", "MC-998877", "Janet Brown", "555-1010",
             "O-", "Codeine, Shellfish",
             "CHF, Atrial Fibrillation, Type 2 Diabetes, CKD Stage 3"),
            ("MRN-100006", "Angela", "Davis", "1990-04-18", "Female",
             "555-1011", "angela.d@email.com", "987 Birch St, Springfield, IL 62706",
             "Blue Cross", "BC-556677", "James Davis", "555-1012",
             "A-", "Amoxicillin",
             "Hypothyroidism, Depression"),
        ]
        for pt in patients_data:
            conn.execute("""
                INSERT INTO patients
                (mrn, first_name, last_name, date_of_birth, gender, phone, email,
                 address, insurance_provider, insurance_id, emergency_contact_name,
                 emergency_contact_phone, blood_type, allergies, problem_list)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, pt)

        # Past Encounters
        now = datetime.now()
        past_encounters = [
            (1, 1, (now - timedelta(days=90)).isoformat(), "Office Visit",
             "Routine follow-up for diabetes and hypertension", 25, "Completed"),
            (1, 1, (now - timedelta(days=180)).isoformat(), "Office Visit",
             "Annual physical exam", 40, "Completed"),
            (2, 1, (now - timedelta(days=60)).isoformat(), "Office Visit",
             "Persistent cough and shortness of breath", 20, "Completed"),
            (2, 3, (now - timedelta(days=200)).isoformat(), "Telehealth",
             "Anxiety medication review", 15, "Completed"),
            (3, 1, (now - timedelta(days=45)).isoformat(), "Office Visit",
             "Back pain worsening", 30, "Completed"),
            (4, 3, (now - timedelta(days=30)).isoformat(), "Office Visit",
             "Severe headaches, frequency increasing", 25, "Completed"),
            (5, 2, (now - timedelta(days=14)).isoformat(), "Office Visit",
             "CHF follow-up, increased edema", 35, "Completed"),
            (5, 4, (now - timedelta(days=120)).isoformat(), "Office Visit",
             "Diabetes management review", 30, "Completed"),
            (6, 1, (now - timedelta(days=75)).isoformat(), "Telehealth",
             "Depression follow-up, medication adjustment", 20, "Completed"),
        ]
        for enc in past_encounters:
            conn.execute("""
                INSERT INTO encounters
                (patient_id, provider_id, encounter_date, encounter_type,
                 chief_complaint, duration_minutes, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, enc)

        # Clinical Notes for past encounters
        notes_data = [
            (1, 1, 1,
             "Patient reports blood sugars have been running 140-180 fasting. Compliant with medications. Occasional headaches in the morning. Diet has been fair, admits to increased carb intake over holidays.",
             "BP 148/92, HR 78, Temp 98.4F, Wt 198 lbs. Alert, oriented. Cardiac RRR, no murmurs. Lungs CTA bilaterally. Extremities no edema.",
             "1. Hypertension - suboptimally controlled\n2. Type 2 Diabetes - A1C likely elevated given fasting glucose readings\n3. Hyperlipidemia - stable on statin",
             "1. Increase lisinopril to 20mg daily\n2. Order A1C and BMP\n3. Reinforce dietary counseling\n4. Follow up in 3 months\n5. Continue atorvastatin 40mg",
             json.dumps({"bp": "148/92", "hr": "78", "temp": "98.4", "weight": "198", "spo2": "97"})),
            (2, 2, 1,
             "Patient reports intermittent dry cough for 3 weeks, worse at night. Some shortness of breath with exertion. Using albuterol inhaler 3-4 times per week. Anxiety has been manageable.",
             "BP 118/74, HR 72, Temp 98.2F, Wt 142 lbs, SpO2 97%. Mild expiratory wheezing bilateral lower lobes. No accessory muscle use.",
             "1. Asthma exacerbation - likely triggered by seasonal allergens\n2. Generalized anxiety disorder - stable",
             "1. Add fluticasone 110mcg inhaler, 2 puffs BID\n2. Continue albuterol PRN\n3. Consider allergy testing if symptoms persist\n4. Follow up in 4 weeks",
             json.dumps({"bp": "118/74", "hr": "72", "temp": "98.2", "weight": "142", "spo2": "97"})),
            (3, 3, 1,
             "Patient reports worsening low back pain, radiating to left leg. Pain rated 7/10. Worse with prolonged sitting. OTC ibuprofen provides minimal relief. No bowel or bladder changes.",
             "BP 132/84, HR 80, Temp 98.6F, Wt 245 lbs. Lumbar paraspinal tenderness. Positive straight leg raise on left at 45 degrees. Strength 5/5 bilateral lower extremities. DTRs intact.",
             "1. Lumbar radiculopathy - likely L4-L5 or L5-S1\n2. Chronic low back pain - worsening\n3. Obesity - contributing factor",
             "1. Order lumbar MRI\n2. Start gabapentin 300mg TID\n3. Physical therapy referral\n4. Weight management counseling\n5. Follow up after MRI results",
             json.dumps({"bp": "132/84", "hr": "80", "temp": "98.6", "weight": "245", "spo2": "98"})),
        ]
        for i, note in enumerate(notes_data):
            conn.execute("""
                INSERT INTO clinical_notes
                (encounter_id, patient_id, provider_id, subjective, objective,
                 assessment, plan, vitals_json, is_signed, signed_by, signed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """, (*note, note[2], (now - timedelta(days=90 - i * 30)).isoformat()))

        # Prescriptions
        rx_data = [
            (1, 1, None, "Lisinopril", "20mg", "Once daily", "Oral",
             "2024-06-01", None, 6, 4, "Active", "CVS Pharmacy", "For hypertension"),
            (1, 1, None, "Metformin", "1000mg", "Twice daily", "Oral",
             "2024-01-15", None, 6, 3, "Active", "CVS Pharmacy", "For type 2 diabetes"),
            (1, 1, None, "Atorvastatin", "40mg", "Once daily at bedtime", "Oral",
             "2024-01-15", None, 6, 5, "Active", "CVS Pharmacy", "For hyperlipidemia"),
            (2, 1, None, "Albuterol Inhaler", "90mcg", "2 puffs every 4-6 hours PRN", "Inhalation",
             "2024-03-01", None, 3, 2, "Active", "Walgreens", "For asthma rescue"),
            (2, 1, None, "Fluticasone Inhaler", "110mcg", "2 puffs twice daily", "Inhalation",
             "2024-09-15", None, 6, 5, "Active", "Walgreens", "For asthma maintenance"),
            (2, 3, None, "Sertraline", "50mg", "Once daily", "Oral",
             "2024-02-01", None, 6, 2, "Active", "Walgreens", "For anxiety"),
            (3, 1, None, "Omeprazole", "20mg", "Once daily before breakfast", "Oral",
             "2024-05-01", None, 6, 3, "Active", "Rite Aid", "For GERD"),
            (3, 1, None, "Gabapentin", "300mg", "Three times daily", "Oral",
             "2024-10-01", None, 3, 2, "Active", "Rite Aid", "For radiculopathy"),
            (4, 3, None, "Sumatriptan", "50mg", "As needed for migraine, max 2/day", "Oral",
             "2024-08-01", None, 6, 4, "Active", "CVS Pharmacy", "For migraine"),
            (4, 3, None, "Ferrous Sulfate", "325mg", "Once daily", "Oral",
             "2024-08-01", None, 6, 5, "Active", "CVS Pharmacy", "For iron deficiency"),
            (5, 2, None, "Furosemide", "40mg", "Twice daily", "Oral",
             "2024-04-01", None, 6, 2, "Active", "CVS Pharmacy", "For CHF/edema"),
            (5, 2, None, "Carvedilol", "25mg", "Twice daily", "Oral",
             "2024-04-01", None, 6, 3, "Active", "CVS Pharmacy", "For CHF/AF"),
            (5, 4, None, "Metformin", "500mg", "Twice daily", "Oral",
             "2024-01-01", None, 6, 1, "Active", "CVS Pharmacy", "For type 2 diabetes"),
            (5, 2, None, "Apixaban", "5mg", "Twice daily", "Oral",
             "2024-04-01", None, 6, 3, "Active", "CVS Pharmacy", "For atrial fibrillation"),
            (6, 1, None, "Levothyroxine", "75mcg", "Once daily on empty stomach", "Oral",
             "2024-03-01", None, 6, 4, "Active", "Walgreens", "For hypothyroidism"),
            (6, 1, None, "Escitalopram", "10mg", "Once daily", "Oral",
             "2024-07-01", None, 6, 5, "Active", "Walgreens", "For depression"),
        ]
        for rx in rx_data:
            conn.execute("""
                INSERT INTO prescriptions
                (patient_id, provider_id, encounter_id, medication_name, dosage,
                 frequency, route, start_date, end_date, refills_total,
                 refills_remaining, status, pharmacy, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rx)

        # Billing Codes for past encounters
        billing_data = [
            (1, "CPT", "99214", "Office visit, established patient, moderate complexity", 150.00),
            (1, "ICD-10", "I10", "Essential hypertension", 0),
            (1, "ICD-10", "E11.9", "Type 2 diabetes mellitus without complications", 0),
            (2, "CPT", "99213", "Office visit, established patient, low complexity", 110.00),
            (2, "ICD-10", "J45.20", "Mild intermittent asthma, uncomplicated", 0),
            (3, "CPT", "99214", "Office visit, established patient, moderate complexity", 150.00),
            (3, "ICD-10", "M54.5", "Low back pain", 0),
            (3, "ICD-10", "M54.31", "Sciatica, left side", 0),
        ]
        for bc in billing_data:
            conn.execute("""
                INSERT INTO billing_codes (encounter_id, code_type, code, description, amount)
                VALUES (?, ?, ?, ?, ?)
            """, bc)

        # Messages
        messages_data = [
            (1, 1, "patient", "Medication Question",
             "Dr. Chen, I've been experiencing some dizziness since my lisinopril dose was increased. Is this normal? Should I be concerned? The dizziness is worse when I stand up quickly.",
             0, 0, 0),
            (2, 1, "patient", "Inhaler Refill Request",
             "Hi Dr. Chen, I'm running low on my albuterol inhaler and would like to request a refill. I've been using it about 3-4 times per week as discussed. Thank you.",
             0, 0, 0),
            (5, 2, "patient", "Weight and Swelling Update",
             "Dr. Wilson, I wanted to let you know that my weight has gone up 4 pounds this week and my ankles are more swollen than usual. I've been taking all my medications as prescribed and limiting salt intake. Should I adjust my Lasix dose?",
             0, 0, 0),
            (6, 1, "patient", "Feeling Worse on Medication",
             "Dr. Chen, I've been on the escitalopram for about 3 weeks now and I'm not sure if it's working. I still feel very down most days and have trouble sleeping. Is there something else we can try?",
             0, 0, 0),
        ]
        for msg in messages_data:
            conn.execute("""
                INSERT INTO messages
                (patient_id, provider_id, sender_type, subject, body,
                 is_draft, is_ai_generated, is_read)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, msg)

        conn.commit()
        conn.close()
        return True
