"""
Clinical Voice EHR - AI Engine
Handles voice transcription simulation, clinical note generation,
note summarization, draft message responses, and billing code suggestions.

In production, these methods would call external AI APIs (OpenAI Whisper,
Claude, GPT-4, etc.). This implementation provides realistic simulated
outputs for demonstration purposes.
"""

import json
import random
from datetime import datetime


# ── Common ICD-10 Codes ────────────────────────────────────────────

ICD10_CODES = {
    "hypertension": [("I10", "Essential (primary) hypertension")],
    "diabetes": [
        ("E11.9", "Type 2 diabetes mellitus without complications"),
        ("E11.65", "Type 2 diabetes mellitus with hyperglycemia"),
    ],
    "back pain": [
        ("M54.5", "Low back pain"),
        ("M54.31", "Sciatica, left side"),
        ("M54.32", "Sciatica, right side"),
        ("M54.41", "Lumbago with sciatica, right side"),
    ],
    "headache": [
        ("R51.9", "Headache, unspecified"),
        ("G43.909", "Migraine, unspecified, not intractable"),
    ],
    "anxiety": [
        ("F41.1", "Generalized anxiety disorder"),
        ("F41.9", "Anxiety disorder, unspecified"),
    ],
    "depression": [
        ("F32.1", "Major depressive disorder, single episode, moderate"),
        ("F33.1", "Major depressive disorder, recurrent, moderate"),
    ],
    "asthma": [
        ("J45.20", "Mild intermittent asthma, uncomplicated"),
        ("J45.30", "Mild persistent asthma, uncomplicated"),
        ("J45.40", "Moderate persistent asthma, uncomplicated"),
    ],
    "cough": [
        ("R05.9", "Cough, unspecified"),
        ("J06.9", "Acute upper respiratory infection, unspecified"),
    ],
    "chest pain": [
        ("R07.9", "Chest pain, unspecified"),
        ("I20.9", "Angina pectoris, unspecified"),
    ],
    "fatigue": [
        ("R53.83", "Other fatigue"),
        ("R53.1", "Weakness"),
    ],
    "obesity": [
        ("E66.01", "Morbid obesity due to excess calories"),
        ("E66.9", "Obesity, unspecified"),
    ],
    "heart failure": [
        ("I50.9", "Heart failure, unspecified"),
        ("I50.22", "Chronic systolic heart failure"),
    ],
    "atrial fibrillation": [
        ("I48.91", "Unspecified atrial fibrillation"),
        ("I48.0", "Paroxysmal atrial fibrillation"),
    ],
    "hypothyroidism": [
        ("E03.9", "Hypothyroidism, unspecified"),
    ],
    "gerd": [
        ("K21.0", "GERD with esophagitis"),
        ("K21.9", "GERD without esophagitis"),
    ],
    "hyperlipidemia": [
        ("E78.5", "Hyperlipidemia, unspecified"),
        ("E78.00", "Pure hypercholesterolemia, unspecified"),
    ],
    "uti": [
        ("N39.0", "Urinary tract infection, site not specified"),
    ],
    "insomnia": [
        ("G47.00", "Insomnia, unspecified"),
    ],
    "knee pain": [
        ("M25.561", "Pain in right knee"),
        ("M25.562", "Pain in left knee"),
        ("M17.11", "Primary osteoarthritis, right knee"),
    ],
    "diabetes follow-up": [
        ("E11.9", "Type 2 diabetes mellitus without complications"),
        ("E11.65", "Type 2 diabetes mellitus with hyperglycemia"),
        ("Z79.84", "Long term use of oral hypoglycemic drugs"),
    ],
    "shortness of breath": [
        ("R06.00", "Dyspnea, unspecified"),
        ("R06.02", "Shortness of breath"),
    ],
    "skin rash": [
        ("R21", "Rash and other nonspecific skin eruption"),
        ("L30.9", "Dermatitis, unspecified"),
    ],
}

# ── Common CPT Codes ───────────────────────────────────────────────

CPT_CODES = {
    "new_low": ("99203", "New patient, office visit, low complexity", 120.00),
    "new_mod": ("99204", "New patient, office visit, moderate complexity", 180.00),
    "new_high": ("99205", "New patient, office visit, high complexity", 250.00),
    "est_low": ("99213", "Established patient, office visit, low complexity", 110.00),
    "est_mod": ("99214", "Established patient, office visit, moderate complexity", 150.00),
    "est_high": ("99215", "Established patient, office visit, high complexity", 210.00),
    "preventive_18_39": ("99395", "Preventive visit, established, 18-39", 200.00),
    "preventive_40_64": ("99396", "Preventive visit, established, 40-64", 220.00),
    "telehealth": ("99441", "Telehealth E/M service, 5-10 minutes", 60.00),
    "telehealth_ext": ("99442", "Telehealth E/M service, 11-20 minutes", 110.00),
    "care_mgmt": ("99490", "Chronic care management, 20 min/month", 65.00),
}

# ── Simulated Encounter Transcriptions ────────────────────────────

ENCOUNTER_TEMPLATES = {
    "hypertension_diabetes": {
        "chief_complaints": [
            "Follow-up for diabetes and hypertension",
            "Routine check for blood pressure and blood sugar management",
            "Diabetes and blood pressure follow-up",
        ],
        "transcription": """Dr: Good morning. How have you been since our last visit?

Patient: I've been doing okay, but my blood sugars have been running a bit high in the mornings. Usually around 150 to 170 fasting.

Dr: And how about your blood pressure? Have you been checking it at home?

Patient: Yes, it's been around 140 over 88 most days. Sometimes a bit higher in the evenings.

Dr: Are you still taking all your medications as prescribed? The metformin and lisinopril?

Patient: Yes, I take them every day. The metformin twice a day with meals and the lisinopril in the morning.

Dr: Good. Any side effects? Dizziness, nausea, anything like that?

Patient: A little lightheaded when I get up too fast sometimes. Nothing too bad though.

Dr: That could be the blood pressure medication. Let's check your vitals. Your blood pressure today is 145 over 90, heart rate 76. Let me listen to your heart and lungs... Heart sounds regular, no murmurs. Lungs are clear. Let me check your feet... No ulcers, pulses are good bilaterally.

Patient: My feet have been tingling a bit at night sometimes.

Dr: That's something we need to watch. It could be early diabetic neuropathy. I'd like to order an A1C to see where your average blood sugar has been, and also check your kidney function. Based on your home readings, I think we should adjust your metformin. I want to increase it to 1000mg twice daily. And let's add a low-dose amlodipine for your blood pressure since the lisinopril alone isn't quite getting us to goal.

Patient: Okay, that sounds fine. Should I keep checking my blood sugar at home?

Dr: Absolutely. Keep checking fasting and before dinner. I also want you to try to get at least 30 minutes of walking most days. Let's follow up in 6 weeks to recheck everything.""",
        "soap": {
            "subjective": "Patient reports fasting blood glucose readings of 150-170 mg/dL. Home blood pressure readings averaging 140/88. Taking metformin 500mg BID and lisinopril 10mg daily as prescribed. Reports occasional lightheadedness on standing. New complaint of intermittent tingling in bilateral feet at night. Denies nausea, chest pain, or visual changes.",
            "objective": "VS: BP 145/90, HR 76, Temp 98.4°F, Wt 205 lbs, SpO2 98%\nGeneral: Alert, oriented, NAD\nCardiac: RRR, no murmurs/gallops/rubs\nPulmonary: CTAB, no wheezing or crackles\nExtremities: No edema, pedal pulses 2+ bilaterally, no foot ulcers\nNeuro: Decreased monofilament sensation bilateral feet, DTRs intact",
            "assessment": "1. Type 2 Diabetes Mellitus - suboptimally controlled, fasting glucose elevated\n2. Essential Hypertension - not at goal (<140/90)\n3. Peripheral neuropathy - new onset, likely diabetic\n4. Hyperlipidemia - stable on current regimen",
            "plan": "1. Increase metformin to 1000mg BID with meals\n2. Add amlodipine 5mg daily for blood pressure\n3. Order: HbA1c, BMP, lipid panel, urine microalbumin\n4. Continue home blood glucose monitoring (fasting and pre-dinner)\n5. Lifestyle: 30 min walking most days, dietary counseling\n6. Monofilament exam for neuropathy monitoring\n7. Follow up in 6 weeks to reassess\n8. Continue atorvastatin 40mg daily, lisinopril 10mg daily",
        },
    },
    "respiratory": {
        "chief_complaints": [
            "Persistent cough and shortness of breath",
            "Worsening cough, wheezing at night",
            "Cough with difficulty breathing during exercise",
        ],
        "transcription": """Dr: I see from the notes that you're here about a cough. Tell me what's been going on.

Patient: I've had this cough for about two weeks now. It's mostly dry, but sometimes I bring up a little clear mucus. It's really bad at night and wakes me up.

Dr: Are you having any shortness of breath or wheezing?

Patient: Yeah, especially when I exercise or climb stairs. I feel like I can't take a deep breath sometimes.

Dr: Any fever, chills, or body aches?

Patient: No fever. I've been feeling okay otherwise.

Dr: Do you have a history of asthma or allergies?

Patient: I have asthma, diagnosed a few years ago. I use my rescue inhaler but I've been using it a lot more lately, probably 4 or 5 times a week.

Dr: That's more than it should be. Are you on a controller medication?

Patient: I was on a steroid inhaler but I ran out a couple months ago and never got it refilled.

Dr: Okay, that's likely why things have gotten worse. Let me take a listen. I can hear some mild wheezing in both lower lobes, but your upper airways sound clear. Oxygen saturation looks good at 97 percent. No signs of infection.

Patient: So it's just my asthma acting up?

Dr: It appears so. Your asthma isn't well controlled right now, which is why you're coughing and feeling short of breath. We need to get you back on a controller inhaler. I'm going to prescribe fluticasone, two puffs twice a day. Keep your albuterol for rescue use. If you're using the rescue inhaler more than twice a week, that means we need to step up your treatment.

Patient: Okay. Should I worry about any of this being serious?

Dr: Given your exam and history, this is consistent with an asthma flare. But if you develop a fever, cough up colored mucus, or feel significantly worse, come back right away or go to the ER. Let's follow up in 4 weeks to see how you're doing on the controller.""",
        "soap": {
            "subjective": "Patient presents with persistent dry cough x 2 weeks, worse at night, occasionally productive of clear mucus. Associated shortness of breath with exertion and stair climbing. Using albuterol rescue inhaler 4-5x/week. Ran out of fluticasone controller inhaler 2 months ago and did not refill. No fever, chills, or body aches. History of asthma.",
            "objective": "VS: BP 120/76, HR 74, Temp 98.2°F, RR 16, SpO2 97%\nGeneral: Alert, oriented, no acute distress, speaking in full sentences\nENT: Oropharynx clear, no erythema\nPulmonary: Mild expiratory wheezing bilateral lower lobes, no crackles, no accessory muscle use, good air movement\nCardiac: RRR, no murmurs\nSkin: No cyanosis",
            "assessment": "1. Asthma exacerbation, mild persistent - likely due to discontinuation of controller medication\n2. Increased rescue inhaler use indicating poor asthma control",
            "plan": "1. Restart fluticasone propionate 110mcg inhaler - 2 puffs BID\n2. Continue albuterol 90mcg inhaler PRN for rescue\n3. Asthma action plan reviewed with patient\n4. Discussed importance of controller medication adherence\n5. Return precautions: fever, colored sputum, worsening dyspnea\n6. Follow up in 4 weeks to reassess asthma control\n7. Consider allergy testing if not improving with controller",
        },
    },
    "back_pain": {
        "chief_complaints": [
            "Low back pain worsening with leg radiation",
            "Back pain getting worse, shooting down leg",
            "Chronic back pain flare-up",
        ],
        "transcription": """Dr: Tell me about your back pain. When did it start getting worse?

Patient: It's been bad for about three weeks now. I've had back issues on and off for years, but this time it's different. I've got this shooting pain going down my left leg all the way to my calf.

Dr: On a scale of 1 to 10, how bad is the pain?

Patient: It's about a 7 most of the time. When I sit too long, like at my desk, it gets up to an 8 or 9.

Dr: Does anything make it better?

Patient: Walking actually helps a little. Lying down with a pillow under my knees. I've been taking ibuprofen but it barely takes the edge off.

Dr: Any numbness, tingling, or weakness in your legs? Any trouble with bladder or bowel control?

Patient: Some tingling in my left foot. No bladder problems though.

Dr: Okay, let me examine you. I can feel some tightness in the muscles along your lower spine. Now let me do a straight leg raise... that reproduces the pain at about 45 degrees on the left. Right side is fine. Your strength looks good in both legs, reflexes are normal.

Patient: What do you think is going on?

Dr: Your symptoms are consistent with a lumbar disc herniation pressing on a nerve root, likely at L4-L5 or L5-S1. The leg pain and tingling are from nerve irritation. I want to order an MRI to confirm this. In the meantime, I'm going to start you on gabapentin for the nerve pain, and I want you to see a physical therapist. We should also talk about your weight since that puts extra stress on your spine.

Patient: Do I need surgery?

Dr: Let's see what the MRI shows first. Most disc herniations improve with conservative treatment. Physical therapy and medication work for the majority of patients. We'll review the MRI results and decide on next steps from there.""",
        "soap": {
            "subjective": "Patient reports worsening low back pain x 3 weeks with new left-sided radicular symptoms extending to the calf. Pain 7/10 baseline, up to 8-9/10 with prolonged sitting. Intermittent tingling in left foot. Pain partially relieved with walking and lying supine with knee support. OTC ibuprofen provides minimal relief. Denies bowel or bladder dysfunction. Denies saddle anesthesia. History of chronic intermittent low back pain.",
            "objective": "VS: BP 134/86, HR 82, Temp 98.6°F, Wt 242 lbs, BMI 34.8\nMusculoskeletal: Lumbar paraspinal tenderness and muscle spasm. Decreased lumbar flexion.\nNeurological: Positive straight leg raise left at 45° (reproduces radicular pain). Negative SLR right. Motor strength 5/5 bilateral LE. DTRs 2+ symmetric. Decreased light touch sensation lateral left foot.\nGait: Antalgic, favoring left side",
            "assessment": "1. Lumbar radiculopathy, left-sided - suspect L4-L5 or L5-S1 disc herniation\n2. Chronic low back pain, acute exacerbation\n3. Obesity (BMI 34.8) - contributing mechanical factor",
            "plan": "1. Order lumbar spine MRI without contrast\n2. Start gabapentin 300mg PO TID, titrate as tolerated\n3. Discontinue ibuprofen (minimal benefit, GI risk)\n4. Refer to physical therapy - core strengthening, McKenzie protocol\n5. Weight management counseling, goal 10% weight reduction\n6. Activity modification: avoid prolonged sitting, ergonomic assessment\n7. Follow up in 2 weeks or sooner when MRI results available\n8. Return precautions: weakness, bowel/bladder changes, worsening numbness",
        },
    },
    "mental_health": {
        "chief_complaints": [
            "Depression follow-up, medication not helping",
            "Feeling down, trouble sleeping",
            "Anxiety and depression management",
        ],
        "transcription": """Dr: How have you been feeling since we started the escitalopram three weeks ago?

Patient: Honestly, not great. I still feel pretty down most of the time. I don't have much energy and I've been having trouble sleeping. I wake up at 3 or 4 in the morning and can't fall back asleep.

Dr: I'm sorry to hear that. It's important to know that antidepressants typically take 4 to 6 weeks to reach their full effect, so we're still in that window. Have you noticed any change at all, even small?

Patient: Maybe a little. I'm not crying as much as I was before. But I still don't feel like doing anything. I've been skipping my exercise and not really wanting to see friends.

Dr: How about your appetite?

Patient: It's decreased. I've probably lost a few pounds.

Dr: I need to ask some important safety questions. Have you had any thoughts of hurting yourself or ending your life?

Patient: No, nothing like that. I'm just tired and sad.

Dr: Thank you for being honest with me. Any side effects from the medication? Nausea, headaches?

Patient: A little nausea the first few days but that went away. I've been a bit more jittery but it's mild.

Dr: That initial activation can happen and usually settles. Here's what I'd recommend: let's give the escitalopram a full 6-week trial at this dose before making changes. I'd also like to refer you to a therapist for cognitive behavioral therapy, which works very well alongside medication. For sleep, let's try improving your sleep hygiene first, and if that doesn't help, we can consider a short-term sleep aid. Keep trying to do some light activity even when you don't feel like it.

Patient: Okay, I'll try. When should I come back?

Dr: Let's meet again in 3 weeks. But if things get significantly worse or you have any safety concerns, call us right away or go to the emergency room.""",
        "soap": {
            "subjective": "Patient returns 3 weeks after starting escitalopram 10mg daily for major depression. Reports persistent low mood, anhedonia, decreased energy, and early morning awakening (3-4 AM). Decreased appetite with mild unintentional weight loss. Some reduction in crying episodes. Social withdrawal from friends and discontinued exercise routine. Mild initial nausea resolved, mild jitteriness persisting. Denies suicidal ideation, self-harm thoughts, or homicidal ideation. Denies psychotic symptoms.",
            "objective": "VS: BP 116/72, HR 68, Temp 98.4°F, Wt 148 lbs (down 3 lbs from last visit)\nGeneral: Appears tired, psychomotor slowing noted, appropriate grooming\nMental Status: Alert, oriented x4. Affect flat, mood 'sad and tired.' Speech normal rate and rhythm. Thought process linear, goal-directed. No SI/HI. Insight fair, judgment intact.\nPHQ-9 Score: 16 (moderately severe depression)",
            "assessment": "1. Major Depressive Disorder, single episode, moderate - partial response to escitalopram at 3 weeks\n2. Insomnia, early morning awakening - associated with depression\n3. Decreased appetite with weight loss - monitor",
            "plan": "1. Continue escitalopram 10mg daily - allow full 6-week trial before dose adjustment\n2. Referral to psychology for cognitive behavioral therapy (CBT)\n3. Sleep hygiene counseling provided: consistent wake time, limit screens before bed, no caffeine after noon\n4. Encouraged gradual return to exercise - start with 15-min daily walks\n5. Safety plan reviewed, crisis hotline number (988) provided\n6. Follow up in 3 weeks, repeat PHQ-9\n7. If worsening mood or any SI, instruct to call office or go to ER immediately\n8. Consider dose increase to 20mg if no further improvement at 6-week mark",
        },
    },
    "general_followup": {
        "chief_complaints": [
            "General follow-up visit",
            "Annual wellness check",
            "Routine check-up and medication review",
        ],
        "transcription": """Dr: Good to see you for your follow-up. How have things been going overall?

Patient: Pretty good actually. I've been feeling better since our last appointment. The medication seems to be working well.

Dr: That's great to hear. Any new symptoms or concerns since we last met?

Patient: Nothing major. I get occasional headaches but they go away with Tylenol. Otherwise I've been feeling fine.

Dr: How about your diet and exercise?

Patient: I've been trying to eat better. More vegetables, less processed food. I walk about 20 minutes most days.

Dr: That's excellent. Let me do a quick exam. Blood pressure looks good at 128 over 80. Heart and lungs sound great. Everything looks stable.

Patient: Do I need any lab work?

Dr: Let's do a routine check since it's been about 6 months. Basic metabolic panel and CBC. I'll have the nurse draw that before you leave. Your medications are working well so let's keep everything the same. See you in 6 months for your next routine follow-up, or sooner if anything comes up.

Patient: Sounds good. Thank you, doctor.""",
        "soap": {
            "subjective": "Patient presents for routine follow-up. Reports feeling well overall. Current medications are well-tolerated and effective. Occasional mild headaches responsive to acetaminophen. Improved dietary habits and regular walking exercise 20 min/day. No new complaints.",
            "objective": "VS: BP 128/80, HR 72, Temp 98.5°F, Wt 180 lbs, SpO2 99%\nGeneral: Well-appearing, NAD\nCardiac: RRR, no murmurs\nPulmonary: CTAB\nAbdomen: Soft, non-tender\nExtremities: No edema",
            "assessment": "1. Routine health maintenance - stable\n2. Current medical conditions - well controlled on current regimen",
            "plan": "1. Continue all current medications unchanged\n2. Order: BMP, CBC\n3. Continue lifestyle modifications - diet and exercise\n4. Follow up in 6 months or PRN\n5. Age-appropriate screening up to date",
        },
    },
}

# ── AI Engine Class ────────────────────────────────────────────────


class AIEngine:
    """Simulates AI-powered clinical processing for demonstration.
    Replace methods with actual API calls for production use."""

    def transcribe_audio(self, audio_bytes=None, encounter_type=None):
        """Simulate audio transcription.
        In production: call Whisper API or similar speech-to-text service."""
        if encounter_type and encounter_type in ENCOUNTER_TEMPLATES:
            template = ENCOUNTER_TEMPLATES[encounter_type]
        else:
            template = random.choice(list(ENCOUNTER_TEMPLATES.values()))
        return template["transcription"]

    def generate_soap_notes(self, transcription, chief_complaint="", patient_info=None):
        """Generate structured SOAP notes from transcription.
        In production: call LLM API with clinical prompt."""
        best_match = None
        best_score = 0
        complaint_lower = (chief_complaint or "").lower() + " " + (transcription or "").lower()

        keyword_map = {
            "hypertension_diabetes": ["diabetes", "blood sugar", "blood pressure", "hypertension", "glucose", "a1c", "metformin"],
            "respiratory": ["cough", "wheez", "breath", "asthma", "inhaler", "lung"],
            "back_pain": ["back pain", "sciatica", "radiculopathy", "spine", "leg pain", "disc"],
            "mental_health": ["depress", "anxiety", "escitalopram", "sertraline", "mood", "sleep", "sad", "mental"],
            "general_followup": ["follow-up", "routine", "wellness", "check-up", "annual"],
        }

        for template_key, keywords in keyword_map.items():
            score = sum(1 for kw in keywords if kw in complaint_lower)
            if score > best_score:
                best_score = score
                best_match = template_key

        if not best_match:
            best_match = "general_followup"

        template = ENCOUNTER_TEMPLATES[best_match]
        soap = template["soap"]

        vitals = {
            "bp": f"{random.randint(115, 150)}/{random.randint(70, 95)}",
            "hr": str(random.randint(62, 92)),
            "temp": f"{random.uniform(97.8, 99.0):.1f}",
            "weight": str(random.randint(130, 260)),
            "spo2": str(random.randint(95, 100)),
            "rr": str(random.randint(14, 20)),
        }

        return {
            "subjective": soap["subjective"],
            "objective": soap["objective"],
            "assessment": soap["assessment"],
            "plan": soap["plan"],
            "vitals_json": json.dumps(vitals),
            "hpi": soap["subjective"][:200] + "...",
            "ros": "Constitutional: No fever, chills, or weight gain. "
                   "HEENT: No visual changes, sore throat, or nasal congestion. "
                   "Cardiovascular: No chest pain or palpitations. "
                   "Respiratory: As noted in HPI. "
                   "GI: No nausea, vomiting, or diarrhea. "
                   "Musculoskeletal: As noted in HPI.",
            "physical_exam": soap["objective"],
        }

    def suggest_billing_codes(self, chief_complaint, soap_notes, encounter_type="Office Visit",
                              is_new_patient=False, duration_minutes=None):
        """Suggest appropriate ICD-10 and CPT codes based on encounter.
        In production: call specialized medical coding AI."""
        suggestions = {"icd10": [], "cpt": []}

        complaint_lower = (chief_complaint or "").lower()
        assessment_lower = (soap_notes.get("assessment", "") or "").lower()
        combined = complaint_lower + " " + assessment_lower

        for keyword, codes in ICD10_CODES.items():
            if keyword in combined:
                for code, desc in codes[:2]:
                    if (code, desc) not in suggestions["icd10"]:
                        suggestions["icd10"].append((code, desc))

        if not suggestions["icd10"]:
            suggestions["icd10"].append(("Z00.00", "Encounter for general adult medical examination"))

        if encounter_type == "Telehealth":
            if duration_minutes and duration_minutes > 10:
                cpt = CPT_CODES["telehealth_ext"]
            else:
                cpt = CPT_CODES["telehealth"]
        elif is_new_patient:
            if len(suggestions["icd10"]) > 2:
                cpt = CPT_CODES["new_high"]
            elif len(suggestions["icd10"]) > 1:
                cpt = CPT_CODES["new_mod"]
            else:
                cpt = CPT_CODES["new_low"]
        else:
            if len(suggestions["icd10"]) > 2 or (duration_minutes and duration_minutes > 30):
                cpt = CPT_CODES["est_high"]
            elif len(suggestions["icd10"]) > 1 or (duration_minutes and duration_minutes > 20):
                cpt = CPT_CODES["est_mod"]
            else:
                cpt = CPT_CODES["est_low"]

        suggestions["cpt"].append(cpt)
        return suggestions

    def summarize_notes(self, notes_list, patient_info=None):
        """Generate a clinical summary from multiple encounter notes.
        In production: call LLM API with summarization prompt."""
        if not notes_list:
            return "No clinical notes available for summarization."

        patient_name = patient_info.get("first_name", "Patient") + " " + patient_info.get("last_name", "") if patient_info else "Patient"
        age = ""
        if patient_info and patient_info.get("date_of_birth"):
            try:
                dob = datetime.strptime(str(patient_info["date_of_birth"]), "%Y-%m-%d")
                age_years = (datetime.now() - dob).days // 365
                age = f"{age_years}-year-old "
            except (ValueError, TypeError):
                pass

        gender = patient_info.get("gender", "").lower() + " " if patient_info else ""
        allergies = patient_info.get("allergies", "None known") if patient_info else "None known"
        problems = patient_info.get("problem_list", "") if patient_info else ""

        summary_parts = [f"**Clinical Summary for {patient_name}**\n"]
        summary_parts.append(f"**Demographics:** {age}{gender}patient")
        summary_parts.append(f"**Known Allergies:** {allergies}")
        if problems:
            summary_parts.append(f"**Active Problem List:** {problems}")

        summary_parts.append(f"\n**Encounter History** ({len(notes_list)} notes reviewed):\n")

        for note in notes_list[:5]:
            enc_date = note.get("encounter_date", "Unknown date")
            enc_type = note.get("encounter_type", "Visit")
            provider = note.get("provider_name", "Unknown")
            complaint = note.get("chief_complaint", "")

            summary_parts.append(f"- **{enc_date[:10]}** ({enc_type}) with {provider}")
            if complaint:
                summary_parts.append(f"  Chief Complaint: {complaint}")
            if note.get("assessment"):
                first_assessment = note["assessment"].split("\n")[0]
                summary_parts.append(f"  Assessment: {first_assessment}")
            if note.get("plan"):
                first_plan = note["plan"].split("\n")[0]
                summary_parts.append(f"  Plan: {first_plan}")
            summary_parts.append("")

        latest = notes_list[0] if notes_list else {}
        if latest.get("plan"):
            summary_parts.append("**Current Treatment Plan:**")
            for line in latest["plan"].split("\n"):
                line = line.strip()
                if line:
                    summary_parts.append(f"  {line}")

        summary_parts.append("\n**Key Clinical Considerations:**")
        summary_parts.append("- Monitor medication adherence and efficacy")
        summary_parts.append("- Review lab results when available")
        summary_parts.append("- Assess response to current treatment at next visit")
        if "diabetes" in (problems or "").lower():
            summary_parts.append("- Track HbA1c and fasting glucose trends")
        if "hypertension" in (problems or "").lower():
            summary_parts.append("- Monitor home blood pressure readings")

        return "\n".join(summary_parts)

    def draft_message_response(self, incoming_message, patient_info=None,
                                recent_notes=None, prescriptions=None):
        """Draft a provider response to a patient message.
        In production: call LLM API with patient context and message."""
        msg_lower = incoming_message.lower()
        patient_name = ""
        if patient_info:
            patient_name = patient_info.get("first_name", "")

        if any(kw in msg_lower for kw in ["dizz", "lightheaded", "faint"]):
            return (
                f"Dear {patient_name},\n\n"
                "Thank you for reaching out about the dizziness you've been experiencing. "
                "Lightheadedness can occur when adjusting to a new blood pressure medication dose, "
                "particularly when standing up quickly (orthostatic hypotension).\n\n"
                "Here are some recommendations:\n"
                "- Rise slowly from sitting or lying positions\n"
                "- Stay well hydrated (aim for 6-8 glasses of water daily)\n"
                "- Avoid standing for long periods\n"
                "- Monitor your blood pressure at home if possible\n\n"
                "If the dizziness is severe, persistent, or accompanied by chest pain, "
                "vision changes, or fainting, please seek immediate medical attention or call 911.\n\n"
                "If symptoms persist beyond one week, I'd like to see you in the office "
                "to reassess your medication dosing. Please call to schedule an appointment.\n\n"
                "Best regards"
            )

        elif any(kw in msg_lower for kw in ["refill", "running low", "need more", "prescription"]):
            med_name = "your medication"
            if prescriptions:
                for rx in prescriptions:
                    rx_name = rx.get("medication_name", "").lower()
                    if rx_name and rx_name in msg_lower:
                        med_name = rx["medication_name"]
                        break
                else:
                    if prescriptions:
                        med_name = prescriptions[0].get("medication_name", "your medication")

            return (
                f"Dear {patient_name},\n\n"
                f"I've received your request for a refill of {med_name}. "
                "I have reviewed your chart and will process the refill to your pharmacy on file.\n\n"
                "Please allow 24-48 hours for processing. If you don't receive notification "
                "from your pharmacy within that time, please contact them directly or call our office.\n\n"
                "As a reminder, please continue taking the medication as directed. "
                "If you have any questions about your dosage or are experiencing any side effects, "
                "don't hesitate to let us know.\n\n"
                "Best regards"
            )

        elif any(kw in msg_lower for kw in ["swell", "edema", "weight", "gained", "pounds", "fluid"]):
            return (
                f"Dear {patient_name},\n\n"
                "Thank you for the update on your weight and swelling. A 4-pound weight gain "
                "over a week with increased ankle swelling is concerning and may indicate fluid retention.\n\n"
                "Please take the following steps:\n"
                "- Continue all medications as prescribed - do NOT adjust doses on your own\n"
                "- Restrict sodium intake to less than 2,000mg daily\n"
                "- Elevate your legs when resting\n"
                "- Weigh yourself daily at the same time and record it\n"
                "- Monitor for any shortness of breath, especially when lying flat\n\n"
                "I would like to see you in the office within the next 2-3 days for an assessment. "
                "Please call to schedule an urgent appointment.\n\n"
                "If you develop significant shortness of breath, chest pain, or "
                "sudden worsening of symptoms, go to the emergency room immediately.\n\n"
                "Best regards"
            )

        elif any(kw in msg_lower for kw in ["not working", "not helping", "worse", "feeling down",
                                              "depressed", "sleep", "tired"]):
            return (
                f"Dear {patient_name},\n\n"
                "I appreciate you sharing how you've been feeling. I understand this has been "
                "a difficult time, and it's important that we work together to find the right approach.\n\n"
                "Many antidepressant medications require 4-6 weeks to reach full therapeutic effect. "
                "At 3 weeks, it's still early, and the fact that you've noticed some improvement "
                "(even small) is actually a positive sign.\n\n"
                "In the meantime, I encourage you to:\n"
                "- Continue taking your medication at the same time each day\n"
                "- Try to maintain a regular sleep schedule\n"
                "- Engage in light physical activity, even a short walk\n"
                "- Reach out to supportive friends or family when you can\n\n"
                "I'd like to see you at our next scheduled appointment to reassess. "
                "If you feel significantly worse at any point, or have any thoughts of self-harm, "
                "please call our office immediately, go to the nearest ER, or call the "
                "Suicide and Crisis Lifeline at 988.\n\n"
                "You're taking the right steps by communicating with us.\n\n"
                "Best regards"
            )

        else:
            return (
                f"Dear {patient_name},\n\n"
                "Thank you for your message. I've reviewed your chart and your concerns.\n\n"
                "Based on your recent visit and current treatment plan, I recommend "
                "continuing your current medications and monitoring your symptoms. "
                "If you notice any changes or new symptoms, please don't hesitate to reach out.\n\n"
                "If your symptoms worsen or you have urgent concerns, please call our office "
                "to schedule a sooner appointment. For emergencies, please call 911 or "
                "go to your nearest emergency department.\n\n"
                "We'll address your concerns in more detail at your next scheduled visit.\n\n"
                "Best regards"
            )

    def get_encounter_type_key(self, chief_complaint):
        """Map a chief complaint to an encounter template key."""
        if not chief_complaint:
            return "general_followup"

        complaint_lower = chief_complaint.lower()
        mappings = {
            "hypertension_diabetes": ["diabetes", "blood sugar", "hypertension", "blood pressure", "a1c"],
            "respiratory": ["cough", "breath", "wheez", "asthma", "respiratory"],
            "back_pain": ["back", "spine", "radiculopathy", "sciatica"],
            "mental_health": ["depress", "anxiety", "mood", "mental", "sleep disturbance"],
        }
        for key, keywords in mappings.items():
            if any(kw in complaint_lower for kw in keywords):
                return key
        return "general_followup"

    def get_follow_up_text(self, chief_complaint):
        """Generate appropriate follow-up recommendation text."""
        key = self.get_encounter_type_key(chief_complaint)
        follow_ups = {
            "hypertension_diabetes": "Follow up in 6 weeks. Repeat A1C, BMP, lipid panel. "
                                      "Earlier if symptoms worsen or blood pressure not improving.",
            "respiratory": "Follow up in 4 weeks. Sooner if fever develops, worsening dyspnea, "
                          "or increased rescue inhaler use beyond baseline.",
            "back_pain": "Follow up in 2 weeks or when MRI results available. "
                        "Return sooner for weakness, bowel/bladder changes, or worsening numbness.",
            "mental_health": "Follow up in 3 weeks for medication reassessment. "
                            "Repeat PHQ-9. Immediate contact if safety concerns arise.",
            "general_followup": "Follow up in 6 months for routine visit. "
                               "Sooner if any new symptoms or concerns arise.",
        }
        return follow_ups.get(key, follow_ups["general_followup"])
