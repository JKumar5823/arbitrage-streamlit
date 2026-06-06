# 🏋️ Lift Lab

A personal **workout-intelligence dashboard** built from your *Life Dashboard*
Google Sheet. It turns 2+ years of training, bodyweight and calorie logs into
PRs, plateau alerts, physique-photo correlation, and concrete coaching.

```bash
pip install -r requirements.txt
streamlit run app.py
```

## What it does

| Page | What you get |
|------|--------------|
| **📊 Overview** | Headline stats, bodyweight trend, weekly hard-sets per muscle, training frequency, and a quick coaching read. |
| **🏋️ Exercises** | Searchable history of **every** exercise you've logged (450+). Per-exercise progression of estimated 1RM / top-set weight / session volume, plus recent set-by-set logs with your notes. |
| **🏆 PRs** | Best **estimated 1RM** per exercise (Epley, computed from every logged set) **and** your hand-logged rep-max table — each PR **timestamped and tied to the bodyweight you were at when you hit it** (pulled from the Daily Wgt tab). Shows strength-to-bodyweight ratio. |
| **📸 Physique** | Upload progress photos, tag the muscle/area each shows. Each photo is auto-correlated to your bodyweight and the **driver lifts** for that muscle, so a weak body part can be matched against weak priority lifts. |
| **🥗 Nutrition & Activity** | Ingests calories / maintenance / steps / activity from Daily Wgt. Weight-vs-deficit charts, a **diminishing-returns** breakdown (weekly rate per 3-week block), and goal-aware coaching (*Lose fat / Build muscle / Improve a lift*) telling you what to change and **when to shift focus**. |
| **🧱 Plateaus & Coaching** | Flags every lift whose estimated 1RM hasn't improved in ~8 weeks (configurable), classifies *progressing / plateaued / regression-risk*, and gives specific break-through tactics per lift. |

## How the data is read

The source sheet (`Routine` tab) is a hand-maintained, very wide layout that has
evolved over two years: 4–5 training-day blocks side by side, repeated weekly,
with drifting column names, `#REF!` errors and the occasional date typed into a
numeric cell. `workout/loader.py` parses it **adaptively** — it detects each
header row, splits it into day blocks, fuzzy-matches the sub-columns, and
forward-fills exercise names/dates within each superset group — producing one
tidy "long" row per logged set.

- `workout/loader.py` — parse the `.xlsx` export → tidy DataFrames (routine / daily / PRs).
- `workout/analysis.py` — PRs, bodyweight correlation, plateau detection, weekly volume, nutrition coaching, diminishing-returns.
- `workout/physique.py` — local photo store + lift correlation.
- `app.py` — the Streamlit UI.

## Keeping it in sync with your sheet

The repo bundles a snapshot containing **only** the three workout-relevant tabs
(`Routine`, `Daily Wgt`, `PRs`) — your financial / personal tabs are deliberately
**not** included. The app resolves its data source in this priority order:
**manual upload → live Google Sheets sync → bundled snapshot.**

### 🔗 Live sync (recommended) — edit the sheet, the app updates

Reads the latest workout tabs straight from your Google Sheet via a **service
account**, so the sheet stays fully private. One-time setup:

1. **Google Cloud Console** → create/select a project → enable the **Google Sheets API**.
2. Create a **Service Account** → *Keys* → *Add key* → **JSON**; download it.
3. Open your Life Dashboard sheet → **Share** → add the service account's
   `client_email` (e.g. `lift-lab@my-project.iam.gserviceaccount.com`) as **Viewer**.
4. Copy `.streamlit/secrets.toml.example` → `.streamlit/secrets.toml` and paste in
   the JSON fields + your `sheet_id`. (`secrets.toml` is git-ignored.)

Then the sidebar shows **🔗 Google Sheets live sync** — leave it on and the app
pulls fresh data (cached ~5 min; **🔄 Refresh now** pulls immediately, **🧪 Test
connection** verifies access). Now whenever you edit the sheet, just refresh.

### ⬆️ Manual upload (no setup)

In Google Sheets: **File → Download → Microsoft Excel (.xlsx)**, then in the app
sidebar **📂 Data source → Upload updated .xlsx**.

(Physique photos you upload stay local in `data/physique/` and are git-ignored.)

## Notes & caveats

- **Estimated 1RM** uses the Epley formula and is only computed for sets of ≤12
  reps, where it's reasonably accurate; high-rep / timed accessory work is tracked
  by weight & volume instead.
- Bodyweight correlation matches the nearest daily weigh-in within a few days; PRs
  set before the Daily Wgt log began (Oct 2024) show no bodyweight.
- Coaching heuristics are general strength-training guidance, not medical advice.
