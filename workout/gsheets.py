"""
Live Google Sheets reader for Lift Lab.

Reads the workout tabs straight from your Google Sheet using a **service account**
so the sheet can stay fully private (you share it read-only with the service
account's email).  The same row format the .xlsx loader produces is returned, so
all downstream parsing is identical.

Setup (one time):
  1. In Google Cloud, create a project, enable the **Google Sheets API**, and
     create a **service account**.  Download its JSON key.
  2. Share your Life Dashboard sheet (read-only is enough) with the service
     account's email, e.g.  lift-lab@my-project.iam.gserviceaccount.com
  3. Put the key + sheet id in Streamlit secrets (see .streamlit/secrets.toml.example).

Nothing here is imported unless live sync is actually used, so gspread is an
optional dependency.
"""

from __future__ import annotations

from .loader import Dataset, build_dataset, ROUTINE_SHEET, DAILY_SHEET, PRS_SHEET

# the workbook tabs we need to read
WORKOUT_SHEETS = [ROUTINE_SHEET, DAILY_SHEET, PRS_SHEET]


def _client(creds: dict):
    """Create an authorised gspread client from a service-account info dict."""
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    credentials = Credentials.from_service_account_info(dict(creds), scopes=scopes)
    return gspread.authorize(credentials)


def fetch_sheets(sheet_id: str, creds: dict) -> dict[str, list[list]]:
    """Return {sheet_name: rows} for the workout tabs, read live from Google Sheets."""
    gc = _client(creds)
    sh = gc.open_by_key(sheet_id)
    available = {ws.title: ws for ws in sh.worksheets()}
    out: dict[str, list[list]] = {}
    for name in WORKOUT_SHEETS:
        ws = available.get(name)
        if ws is None:
            out[name] = []
            continue
        # FORMATTED_VALUE (default) gives the displayed text — dates as the user
        # sees them, formula results already computed.  Our parsers coerce strings.
        out[name] = ws.get_all_values()
    return out


def load_dataset_live(sheet_id: str, creds: dict) -> Dataset:
    return build_dataset(fetch_sheets(sheet_id, creds))


def connection_check(sheet_id: str, creds: dict) -> tuple[bool, str]:
    """Lightweight credential/permission check used by the UI. Returns (ok, message)."""
    try:
        gc = _client(creds)
        sh = gc.open_by_key(sheet_id)
        titles = [ws.title for ws in sh.worksheets()]
        missing = [s for s in WORKOUT_SHEETS if s not in titles]
        if missing:
            return False, f"Connected, but these tabs are missing: {', '.join(missing)}"
        return True, f"Connected to '{sh.title}'."
    except Exception as exc:  # noqa: BLE001 - surface any auth/permission error to the user
        return False, _friendly_error(exc)


def _friendly_error(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "permission" in low or "403" in low or "forbidden" in low:
        return ("Permission denied — share the sheet (read-only) with the service "
                "account's client_email, then retry.")
    if "not found" in low or "404" in low:
        return "Sheet not found — check the sheet id in your secrets."
    if "invalid_grant" in low or "jwt" in low or "credentials" in low:
        return "Invalid credentials — re-check the service-account JSON in your secrets."
    if "module named 'gspread'" in low or "no module named" in low:
        return ("gspread isn't installed. Add `gspread` and `google-auth` "
                "(already in requirements.txt) and reinstall.")
    return f"Could not connect: {msg}"
