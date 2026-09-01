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

**Absorbs the master workbook.** The FUIFOAA workbook is not a flat log: one row
is one *lead*, and roughly forty dated columns record when that lead entered each
stage. Point the importer at the file and it reads all 13 campaign sheets, the
lead directory behind them, and the Google Calendar sync bundled in
`Exp_Calendar`. See [The master workbook](#the-master-workbook) below.

**Absorbs a plain Google Sheet too.** Load it by link, through a service account,
or by uploading a file. The app guesses which of your columns feeds which field,
you confirm the mapping, and you get a full dry run — how many rows are new, how
many update existing ones, and which rows cannot be imported and why, named by
their spreadsheet row number — before anything is written.

Then **Adopt as system of record** stamps the cutover date, shows a banner
across the app, and gives you the note to paste at the top of the old sheet.

## The master workbook

### What it reads

| Workbook shape | Becomes |
| --- | --- |
| One row per lead, across 13 campaign sheets | A `leads` row with grade, firm, connector, owner and furthest stage reached |
| A dated stage column (`4.1. 1st Meeting Happened`) | A `stage` event — these build the funnel |
| `1st…4th Meeting Date` | A `meeting` event — these are the conversations that get counted |
| `Exp_Calendar` | Calendar events, ready for the review queue |

Stage events and meetings are stored separately and counted separately, so a
pipeline transition is never mistaken for a conversation.

### One vocabulary out of eighty-nine labels

Each campaign type words its stages differently — a webinar raise says
`4.1 Attended Webinar/Met` where an intro raise says `4.1. 1st Meeting Happened`
and the hiring pipeline says `4. 1st Interview Happened`. All 89 labels are
mapped onto ten canonical steps in `fundraising/pipeline.py`.

Mapping is by **label, never by the numeric prefix**: `3.2` means *Interested* on
an intro raise but *Invited to Webinar* on a webinar raise. Two consequences
worth knowing:

* `3.3. Scheduling 1st Meeting` counts as *Interested*, not *Meeting Scheduled* —
  scheduling is an intent, only `3.4` is a booked meeting.
* `0. Attended - Bad Fit For Client` still counts as a meeting that happened.
  A conversation that ended badly was still a conversation.

A stage label the mapping does not recognise is **reported, never silently
dropped** — the import screen lists it, because an unmapped stage would quietly
sink its leads down the funnel.

### How the funnel is counted

Each lead sits at the furthest stage it reached, taken from its dated stage
columns and its current status. The funnel is therefore monotone: a lead that
passed after a first meeting still counts as having had that meeting. Each step
states its own rule in the UI.

### How it compares to the workbook's own daily report

Reproducing the report's figures was the acceptance test. The BD group matches
exactly, and Closed Won matches exactly across every group; intro/interested/
verbal land within a few percent. Two steps differ more:

| Step | This app | Daily report |
| --- | --- | --- |
| Outreach (FUIFOAA) | 512 | 659 |
| Meeting Scheduled (FUIFOAA) | 179 | 165 |
| Meeting Happened (FUIFOAA) | 152 | 132 |

The report's exact edge rules are not visible in the workbook, so rather than
bit-match an opaque snapshot the app applies the documented rule above. If you
want a step counted differently, change its rank in `fundraising/pipeline.py` —
that is the single place the funnel is defined.

### Conversations you have had, not ones you have booked

The workbook holds meetings dated in the future. Those are excluded from the
conversation count and reported separately, because a meeting on next Thursday
is on the books, not in the total.

### What is not migrated

The workbook's own machinery — `Daily Report`, `_Change Log`, `_Ambiguity Log`,
`_Hold Log`, `_Portal-Log`, `_KPI Calc`, `Validations`, `Connectors` and the
blacklists — is workbook plumbing rather than pipeline data, and is left where it
is. The app imports the campaign sheets and the calendar.

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
| `fundraising/pipeline.py` | The 89-label stage taxonomy and the canonical funnel |
| `fundraising/workbook.py` | The master-workbook adapter |
| `fundraising/calendars.py` | Calendar ingestion and the meeting classifier |
| `fundraising/sheets.py` | Sheet loading, column mapping, import, subsumption |
| `fundraising/metrics.py` | Derived views — KPIs, funnel, volume, heatmap |
| `fundraising/charts.py` | Altair charts and the colour palette |
| `fundraising/seed.py` | Demo data |
| `tests/` | `pytest` suite (123 tests) |
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
