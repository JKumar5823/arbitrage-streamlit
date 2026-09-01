# Fundraising Conversations

A Streamlit dashboard that counts the fundraising conversations a team is
having — pulled from their calendars, imported from the spreadsheet they are
using today, or typed in by hand — and then takes over from that spreadsheet as
the system of record.

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app creates `data/fundraising.db` on first run. With an empty database the
sidebar offers a **Load demo data** button so you can see the dashboard
populated before importing anything real.

## What it does

**Counts conversations.** The headline number is fundraising conversations
logged, with per-week volume, cumulative progress against a goal, a pipeline
funnel, a per-person leaderboard, and a person × week activity heatmap. One
filter row at the top of the page scopes every chart and table at once, and
every chart has a table view beside it so no value is reachable only by
hovering.

**Reads meetings from calendars.** Three ways in, so it works whether or not
anyone has Google Cloud admin rights:

| Source | What you need |
| --- | --- |
| **Secret ICS address** | Google Calendar → Settings → *your* calendar → *Secret address in iCal format*. No admin, no API setup. |
| **Google Calendar API** | A service account key. Each calendar is shared with its `client_email`, or you use domain-wide delegation and set an impersonation address. |
| **CSV upload** | Any exported event list. Columns are matched by name. |

Meetings are **scored, never auto-counted**. Each one lands in a review queue
with its score and the reasons behind it ("guest from known investor acme.vc",
"title matches 'pitch'", "looks internal: 'standup'"), and you confirm the ones
that were really fundraising conversations. That is what keeps the numbers
defensible — and it means a wrong call tells you exactly which keyword or
investor domain to fix in **Data & Settings**.

**Absorbs your Google Sheet.** Load it by link, through a service account, or by
uploading a file. The app guesses which of your columns feeds which field, you
confirm the mapping, and you get a full dry run — how many rows are new, how
many update existing ones, and which rows cannot be imported and why, named by
their spreadsheet row number — before anything is written.

Then **Adopt as system of record** stamps the cutover date, shows a banner
across the app, and gives you the note to paste at the top of the old sheet.

## Why re-importing is safe

Every imported row gets a deterministic `source_key`, so importing the same
sheet twice updates rows instead of duplicating them. If the sheet has an ID
column, that is used; otherwise the key is derived from the row's date, owner,
investor and position — deliberately *not* from free text, so editing a note in
the sheet updates the existing conversation rather than creating a second one.

By default a re-import only fills fields that are still empty, so corrections
made in the app survive. A toggle on the import screen lets the sheet win
instead, when that is what you want.

## Your data is not trapped

The store is a plain SQLite file. **Data & Settings** exports conversations as
CSV, a multi-sheet workbook as XLSX, or the whole database file. Every write —
including each imported row and its batch — is recorded in an audit log, so any
number on the dashboard can be traced back to where it came from.

Point `FUNDRAISING_DB` at a mounted volume to keep the database off ephemeral
disk:

```bash
FUNDRAISING_DB=/var/data/fundraising.db streamlit run app.py
```

## Google credentials (optional)

The app runs fully without them. To enable the two API-backed sources, copy
`.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in a
service account key, or upload the JSON in the UI for one session. Grant it
read-only scopes and share the specific calendars and sheets with its
`client_email`. `.gitignore` already excludes `secrets.toml`.

## Layout

| Path | What it is |
| --- | --- |
| `app.py` | Streamlit UI: the six tabs and their wiring |
| `fundraising/db.py` | SQLite schema, CRUD and the audit log |
| `fundraising/calendars.py` | Calendar ingestion and the meeting classifier |
| `fundraising/sheets.py` | Sheet loading, column mapping, import, subsumption |
| `fundraising/metrics.py` | Derived views — KPIs, funnel, volume, heatmap |
| `fundraising/charts.py` | Altair charts and the colour palette |
| `fundraising/seed.py` | Demo data |
| `tests/` | `pytest` suite (89 tests) |
| `legacy_arbitrage_app.py` | The repo's previous arbitrage scraper, kept as-is |

```bash
python -m pytest tests/ -q
```

## Notes on the charts

Single-series charts use one hue and no legend; the heatmap is the only
continuous encoding and uses a one-hue light-to-dark ramp. No chart uses two
y-scales. The funnel uses one hue rather than a stage ramp — its order is
already carried by bar position and direct labels, and this ramp only holds four
visually distinct steps against eight stages.

The `.streamlit/config.toml` theme is pinned to light because the palette is
validated against that surface; a dark palette is defined in `charts.py` and
selected automatically when the viewer's Streamlit theme is dark.
