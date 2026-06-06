"""
Data loader / parser for the "Life Dashboard" Google Sheet export.

The workout history lives in a single very wide, hand-maintained sheet ("Routine")
whose layout has evolved over two years:

  * It is laid out as 4-5 *day blocks* side by side (e.g. Shoulders | Lower | Pull |
    Legs | Arms).  Each block has its own Date / day-letter / exercise columns.
  * The whole 4-5-block structure repeats *vertically*, once per training week, each
    repetition preceded by its own header row (the row where column 0 == "Date").
  * Column meanings drifted over time ("Target Weight" -> "Tgt Wgt", a "Total Vol",
    "Body Part" and "Time" column were added, day names changed, etc.).
  * The live sheet contains formula errors (``#REF!``) and cells where a *date* got
    typed into a numeric reps/weight cell.

Rather than hard-code column positions we parse *adaptively*: for every header row we
read the labels, split the row into day blocks (each block starts at a "Date" label),
and map each block's sub-columns by fuzzy-matching the header text.  Data rows are then
read until the next header row, forward-filling the exercise name and date within a
block (the sheet only writes the exercise name on the first set of a superset group).

The output is a tidy "long" DataFrame with one row per logged *set group*.
"""

from __future__ import annotations

import io
import re
import datetime as _dt
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
import openpyxl


# ---------------------------------------------------------------------------
# Low level workbook access
# ---------------------------------------------------------------------------

def load_workbook(path_or_buffer) -> openpyxl.Workbook:
    """Load an .xlsx workbook from a path or a file-like/bytes buffer."""
    if isinstance(path_or_buffer, (bytes, bytearray)):
        path_or_buffer = io.BytesIO(path_or_buffer)
    return openpyxl.load_workbook(path_or_buffer, data_only=True)


def _sheet_rows(wb: openpyxl.Workbook, name: str) -> list[list]:
    if name not in wb.sheetnames:
        return []
    ws = wb[name]
    return [list(r) for r in ws.iter_rows(values_only=True)]


# ---------------------------------------------------------------------------
# Value coercion helpers
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _clean_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and np.isnan(v):
        return ""
    return str(v).strip()


def _to_date(v) -> Optional[_dt.date]:
    """Coerce a cell into a date, or None."""
    if v is None or v == "":
        return None
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date):
        return v
    s = str(v).strip()
    # "2024-01-12 00:00:00"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y", "%m/%d"):
        try:
            d = _dt.datetime.strptime(s, fmt)
            return d.date()
        except ValueError:
            continue
    return None


def _to_num(v) -> Optional[float]:
    """Coerce a cell to a float, ignoring junk (#REF!, dates-in-numeric-cells, AMRAP)."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not (isinstance(v, float) and np.isnan(v)):
        return float(v)
    s = str(v).strip()
    if not s or s.startswith("#") or "Not do" in s:
        return None
    # A datetime accidentally typed into a numeric cell -> not a real number.
    if _to_date(s) is not None and re.search(r"[-/:]", s):
        return None
    m = _NUM_RE.search(s.replace(",", ""))
    return float(m.group()) if m else None


def _to_reps(v) -> Optional[float]:
    """Reps may be 'AMRAP', '6-8', '7+', a date (junk), etc.  Return a representative number."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.upper() == "AMRAP" or s.startswith("#"):
        return None
    if _to_date(s) is not None and re.search(r"[-/:]", s):
        return None
    nums = _NUM_RE.findall(s.replace(",", ""))
    if not nums:
        return None
    # ranges like 6-8 -> take the upper bound actually achieved feel; use mean
    vals = [float(n) for n in nums]
    return float(np.mean(vals))


# ---------------------------------------------------------------------------
# Routine parsing
# ---------------------------------------------------------------------------

# canonical sub-field -> set of header keywords (lowercased, substring match)
_FIELD_KEYS = {
    "order": ("",),          # the day-letter column ("S","M", "1a" values) - positional
    "exercise": ("",),
    "tgt_wgt": ("tgt wgt", "target weight"),
    "tgt_sets": ("tgt sets", "target sets"),
    "tgt_reps": ("tgt reps", "target reps"),
    "act_wgt": ("act wgt", "actual weight"),
    "sets_done": ("sets done", "sets completed"),
    "reps_done": ("reps done", "reps completed"),
    "comments": ("comment",),
    "total_vol": ("total vol",),
    "body_part": ("body part", "body"),
    "time": ("time",),
}

# day-letter -> weekday name for nicer display (best-effort, layout has drifted)
_DAY_LETTER = {"S": "Sat", "M": "Mon", "T": "Tue", "W": "Wed", "F": "Fri"}


@dataclass
class _Block:
    start: int                 # first column of the block (the "Date" col)
    cols: dict                 # canonical field -> column index
    day_letter: str            # S/M/T/W/F
    focus: str                 # "Shoulders"/"Lower"/"Pull"/... (the 3rd-col header text)
    date_col: int              # column holding the block's date


def _split_blocks(header: list[str]) -> list[_Block]:
    """Given a header row, return the list of day-blocks it defines."""
    n = len(header)
    # indices where a new block starts (label == 'Date')
    starts = [j for j in range(n) if _clean_str(header[j]).lower() == "date"]
    blocks: list[_Block] = []
    for bi, s in enumerate(starts):
        end = starts[bi + 1] if bi + 1 < len(starts) else n
        # the day-letter is the cell right after Date; focus is the next one
        day_letter = _clean_str(header[s + 1]) if s + 1 < end else ""
        focus = _clean_str(header[s + 2]) if s + 2 < end else ""
        cols: dict[str, int] = {}
        for j in range(s, end):
            label = _clean_str(header[j]).lower()
            if not label:
                continue
            for field, keys in _FIELD_KEYS.items():
                if field in ("order", "exercise"):
                    continue
                if any(k and k in label for k in keys):
                    cols.setdefault(field, j)
        # positional columns: order = s+1, exercise = s+2
        cols["order"] = s + 1
        cols["exercise"] = s + 2
        # date for the block: prefer a 'Time' column if present else the Date col
        date_col = cols.get("time", s)
        blocks.append(_Block(start=s, cols=cols, day_letter=day_letter,
                             focus=focus, date_col=date_col))
    return blocks


def _is_header(row: list) -> bool:
    return len(row) > 0 and _clean_str(row[0]).lower() == "date"


def parse_routine(wb: openpyxl.Workbook) -> pd.DataFrame:
    rows = _sheet_rows(wb, "Routine")
    if not rows:
        return pd.DataFrame()

    records: list[dict] = []
    cur_blocks: list[_Block] = []
    # per-block running state (date + exercise carried down)
    state: dict[int, dict] = {}

    for row in rows:
        if _is_header(row):
            cur_blocks = _split_blocks([_clean_str(c) for c in row])
            state = {b.start: {"date": None, "exercise": "", "focus": b.focus,
                               "day": b.day_letter} for b in cur_blocks}
            continue
        if not cur_blocks:
            continue
        for b in cur_blocks:
            st = state[b.start]

            def cell(field):
                j = b.cols.get(field)
                if j is None or j >= len(row):
                    return None
                return row[j]

            # update carried date
            d = _to_date(cell("time")) or _to_date(row[b.start] if b.start < len(row) else None)
            if d is not None:
                st["date"] = d
            # update carried exercise name (only meaningful text rows)
            ex = _clean_str(cell("exercise"))
            order = _clean_str(cell("order"))
            if ex and ex.lower() not in ("date", b.focus.lower()):
                st["exercise"] = ex

            act_wgt = _to_num(cell("act_wgt"))
            tgt_wgt = _to_num(cell("tgt_wgt"))
            reps = _to_reps(cell("reps_done"))
            sets_done = _to_num(cell("sets_done"))
            body = _clean_str(cell("body_part")) or st["focus"]
            comments = _clean_str(cell("comments"))

            # Only record rows that carry a real logged load and an exercise name.
            wgt = act_wgt if act_wgt is not None else tgt_wgt
            if not st["exercise"] or wgt is None:
                continue
            if st["date"] is None:
                continue

            records.append({
                "date": st["date"],
                "day": st["day"],
                "focus": st["focus"],
                "order": order,
                "exercise": st["exercise"],
                "body_part": body,
                "tgt_wgt": tgt_wgt,
                "act_wgt": act_wgt,
                "weight": wgt,
                "sets_done": sets_done,
                "reps_done": reps,
                "comments": comments,
            })

    df = pd.DataFrame.from_records(records)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["exercise"] = df["exercise"].map(_canonical_exercise)
    df["body_part"] = df["body_part"].str.strip().str.title()
    # estimated 1RM (Epley) per logged set
    df["e1rm"] = df.apply(
        lambda r: _epley(r["weight"], r["reps_done"]), axis=1)
    df["volume"] = df.apply(
        lambda r: (r["weight"] or 0) * (r["sets_done"] or 1) * (r["reps_done"] or 0),
        axis=1)
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _epley(weight: Optional[float], reps: Optional[float]) -> Optional[float]:
    # The Epley estimate is only trustworthy up to ~12 reps; above that the formula
    # over-predicts wildly and many high "rep" entries are really seconds/time work.
    if weight is None or reps is None or reps <= 0:
        return None
    if reps > 12:
        return None
    return round(weight * (1 + reps / 30.0), 1)


_CANON_FIXES = {
    "ohp": "Overhead Press",
    "overhead press": "Overhead Press",
    "bench press": "Bench Press",
    "barbell bench press": "Bench Press",
}


def _canonical_exercise(name: str) -> str:
    s = str(name).strip()
    s = re.sub(r"\s+", " ", s)
    key = s.lower()
    return _CANON_FIXES.get(key, s)


# ---------------------------------------------------------------------------
# Daily weight / calorie / activity parsing
# ---------------------------------------------------------------------------

_DAILY_MAP = {
    "Date": "date",
    "Wgt": "weight",
    "Cals Maint.": "maint_cals",
    "Cal Cons.": "calories",
    "# of Steps": "steps",
    "Lift": "lifted",
    "Cardio ": "cardio",
    "Avg Cal Deficit": "avg_deficit",
    "3-DMA Wgt": "weight_3dma",
    "Avg Wgt Loss": "avg_wgt_loss",
}


def parse_daily_wgt(wb: openpyxl.Workbook) -> pd.DataFrame:
    rows = _sheet_rows(wb, "Daily Wgt")
    if not rows:
        return pd.DataFrame()
    header = [_clean_str(c) for c in rows[0]]
    idx = {h: i for i, h in enumerate(header)}
    recs = []
    for row in rows[1:]:
        d = _to_date(row[idx["Date"]]) if "Date" in idx and idx["Date"] < len(row) else None
        if d is None:
            continue
        rec = {"date": d}
        for src, dst in _DAILY_MAP.items():
            if src == "Date":
                continue
            j = idx.get(src)
            val = row[j] if (j is not None and j < len(row)) else None
            if dst in ("lifted", "cardio"):
                rec[dst] = _clean_str(val)
            else:
                rec[dst] = _to_num(val)
        recs.append(rec)
    df = pd.DataFrame.from_records(recs)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    # Drop future placeholder rows (no real weight and no real calories logged).
    df = df[df["weight"].notna() | df["calories"].notna()].copy()
    df = df.sort_values("date").reset_index(drop=True)
    # deficit = consumed - maintenance (negative == deficit)
    df["deficit"] = df["calories"] - df["maint_cals"]
    return df


# ---------------------------------------------------------------------------
# PRs tab (rep-max matrix)
# ---------------------------------------------------------------------------

def parse_prs(wb: openpyxl.Workbook) -> pd.DataFrame:
    """Return long DataFrame [exercise, reps, weight] from the logged rep-max matrix."""
    rows = _sheet_rows(wb, "PRs")
    if not rows:
        return pd.DataFrame()
    header = [_clean_str(c) for c in rows[0]]
    # map column -> rep number from headers like '1RM','12 RM'
    rep_cols: dict[int, int] = {}
    other_col = None
    for j, h in enumerate(header):
        m = re.match(r"(\d+)\s*RM", h)
        if m:
            rep_cols[j] = int(m.group(1))
        elif h.lower() == "other":
            other_col = j
    recs = []
    for row in rows[1:]:
        name = _clean_str(row[0]) if row else ""
        if not name:
            continue
        # stop once we hit the program-notes section (no rep data, prose blocks)
        low = name.lower()
        if low.startswith(("70s", "base phase", "main", "week ", "peak", "accessory",
                           "wave")):
            break
        for j, reps in rep_cols.items():
            if j >= len(row):
                continue
            w = _to_num(row[j])
            if w is not None:
                recs.append({"exercise": name, "reps": reps, "weight": w,
                             "source": "logged"})
        # 'Other' column like '230x22'
        if other_col is not None and other_col < len(row):
            o = _clean_str(row[other_col])
            m = re.match(r"(\d+(?:\.\d+)?)\s*[xX]\s*(\d+)", o)
            if m:
                recs.append({"exercise": name, "reps": int(m.group(2)),
                             "weight": float(m.group(1)), "source": "logged"})
    df = pd.DataFrame.from_records(recs)
    if not df.empty:
        df["e1rm"] = df.apply(lambda r: _epley(r["weight"], r["reps"]), axis=1)
    return df


# ---------------------------------------------------------------------------
# Convenience: parse everything
# ---------------------------------------------------------------------------

@dataclass
class Dataset:
    routine: pd.DataFrame
    daily: pd.DataFrame
    prs: pd.DataFrame


def load_dataset(path_or_buffer) -> Dataset:
    wb = load_workbook(path_or_buffer)
    return Dataset(
        routine=parse_routine(wb),
        daily=parse_daily_wgt(wb),
        prs=parse_prs(wb),
    )
