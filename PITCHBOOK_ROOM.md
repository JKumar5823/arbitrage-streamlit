# 🎯 PitchBook Capture Room

A locally-run control panel that drives your **real cursor**, captures
**screenshots of PitchBook**, extracts the data with **Claude vision** (with a
local Tesseract OCR fallback), and stores it in a **cloud SQL database**.

> ⚠️ **Run this on your own laptop.** Cursor control and screen capture talk to
> a physical display, so this cannot run on a headless server or in the cloud
> IDE — only on the machine whose screen you want to capture.
>
> ⚠️ **Use responsibly.** Automating capture of your PitchBook session is
> against PitchBook's Terms of Service, even for your own licensed account.
> Keep capture rates human-paced and stay within your license. You are
> responsible for how you use this.

---

## Quick start

```bash
# On your laptop, in a virtualenv:
pip install -r requirements.txt

# (macOS) grant Terminal/your IDE Accessibility + Screen Recording permissions
#   System Settings → Privacy & Security → Accessibility / Screen Recording
# (Linux) you also need an X server + the `scrot` package for screenshots,
#   plus `tesseract-ocr` if you want the OCR fallback:
#   sudo apt-get install scrot tesseract-ocr

cp .env.example .env   # then fill in ANTHROPIC_API_KEY and DATABASE_URL
streamlit run pitchbook_room.py
```

Then open the URL Streamlit prints (usually http://localhost:8501).

---

## How it works

The app has three tabs:

1. **📸 Capture & extract**
   - Set a **countdown** (default 4s) so you can alt-tab to your PitchBook
     window before the screenshot fires.
   - Capture the **full screen** or a **region** (left/top/width/height).
   - Hit **Extract** → Claude reads the screenshot and returns structured rows
     (company, deal type, deal size, valuation, investors, …). No API key →
     it falls back to raw Tesseract OCR text.
   - **Review & edit** the rows in a table, then **Save to database**.
   - You can also **upload** a screenshot instead of capturing (useful for
     testing away from your laptop).

2. **🖱️ Cursor control**
   - Read the current cursor position (use it to find region coordinates).
   - Move / click / scroll to navigate PitchBook hands-free.
   - **Fail-safe:** slam the mouse into a screen corner to abort any action.

3. **🗄️ Database**
   - Browse stored records, refresh, and export to CSV.

---

## Storage: cloud SQL

Set `DATABASE_URL` to any SQLAlchemy-supported database. Without it, the app
writes to a local `pitchbook.db` SQLite file so you can try it immediately.

### Setting up an AWS RDS Postgres database

1. In the AWS console → **RDS → Create database → PostgreSQL**.
2. Pick an instance size (e.g. `db.t4g.micro` for testing), set a master
   username/password, and a DB name like `pitchbook`.
3. Under **Connectivity**, enable **Public access** (for testing) and add an
   inbound rule to the security group allowing your IP on port `5432`.
4. After it's available, copy the **endpoint** and build the URL:

   ```
   postgresql+psycopg2://USER:PASSWORD@ENDPOINT:5432/pitchbook
   ```

5. Put it in `.env` as `DATABASE_URL`, or paste it into the sidebar.

The table `pitchbook_records` is created automatically on first run.

> Other zero-setup cloud options that work the same way: **Neon**, **Supabase**,
> **Railway** Postgres — just paste their connection string. See `.env.example`.

---

## Schema

`pitchbook_records` keeps the common fields as columns for easy querying, plus
the full extracted record (including any extra labelled fields) as JSON:

| column | notes |
|---|---|
| `id`, `captured_at`, `source_label` | metadata |
| `entity_type`, `name`, `company` | identity |
| `deal_type`, `deal_size`, `deal_date`, `valuation` | deal data |
| `industry`, `location`, `investors` | context |
| `extraction_method`, `screenshot_path` | provenance |
| `data` (JSON) | the complete extracted record |

---

## Files

| file | purpose |
|---|---|
| `pitchbook_room.py` | the Streamlit control panel ("the room") |
| `pitchbook/cursor.py` | cursor control + screen capture (pyautogui / mss) |
| `pitchbook/extract.py` | Claude-vision extraction + Tesseract OCR fallback |
| `pitchbook/storage.py` | SQLAlchemy storage (cloud Postgres / local SQLite) |
| `.env.example` | configuration template |
