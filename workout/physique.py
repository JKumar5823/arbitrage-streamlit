"""
Physique photo store.

Photos are NOT in the spreadsheet, so the app lets you upload progress pictures,
tag each with a date + which muscle/area it shows + notes.  Each photo is then
auto-correlated with (a) your bodyweight on that date and (b) the priority-lift
estimated-1RMs around that date, so you can scrub a timeline and see how a body
part's development tracks the lifts that drive it.
"""

from __future__ import annotations

import json
import os
import datetime as _dt
from pathlib import Path

import pandas as pd

PHOTO_DIR = Path("data/physique")
INDEX = PHOTO_DIR / "index.json"

# which lifts most drive each physique area (used for correlation)
AREA_TO_LIFTS = {
    "Chest": ["Bench Press", "Low Incline DB Press", "DB Bench Press", "Dips",
              "Barbell Incline Press"],
    "Back": ["Weighted Neutral Grip Pull-ups", "Pull-Ups", "Lat Pulldowns",
             "Chest Supported Barbell Row", "Pendlay Row", "Cable Rows"],
    "Shoulders": ["Seated Overhead Press", "Standing Overhead Press", "Overhead Press",
                  "DB Shoulder Press", "Standing DB Lateral Raise"],
    "Arms": ["Close Grip Bench Press", "Standing Ez Bar Curl", "DB Preacher Curl",
             "Skull Crushers", "Ez Bar French Ext"],
    "Quads": ["High Bar Squat", "Front Squat", "Leg Press", "Hack Squat", "Leg Ext"],
    "Hamstrings": ["Romanian Deadlifts", "Straight Leg Deadlifts", "Lying Leg Curl",
                   "Seated Hamstring Curl", "Good Morning"],
    "Glutes": ["Romanian Deadlifts", "Hip Thrust", "DB Reverse Lunge", "DB Split Squat"],
    "Full body / Front": [],
    "Full body / Back": [],
    "Other": [],
}


def _ensure():
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    if not INDEX.exists():
        INDEX.write_text("[]")


def load_index() -> list[dict]:
    _ensure()
    try:
        return json.loads(INDEX.read_text())
    except json.JSONDecodeError:
        return []


def _save_index(items: list[dict]):
    INDEX.write_text(json.dumps(items, indent=2, default=str))


def add_photo(file_bytes: bytes, filename: str, date: _dt.date, area: str,
              notes: str = "") -> dict:
    _ensure()
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    stamp = _dt.datetime.now().strftime("%Y%m%d%H%M%S%f")
    stored = f"{date.isoformat()}_{area.replace(' ', '-').replace('/', '-')}_{stamp}{ext}"
    (PHOTO_DIR / stored).write_bytes(file_bytes)
    items = load_index()
    rec = {"file": stored, "date": date.isoformat(), "area": area, "notes": notes}
    items.append(rec)
    _save_index(items)
    return rec


def delete_photo(stored: str):
    items = [i for i in load_index() if i["file"] != stored]
    p = PHOTO_DIR / stored
    if p.exists():
        p.unlink()
    _save_index(items)


def photos_df() -> pd.DataFrame:
    items = load_index()
    if not items:
        return pd.DataFrame(columns=["file", "date", "area", "notes", "path"])
    df = pd.DataFrame(items)
    df["date"] = pd.to_datetime(df["date"])
    df["path"] = df["file"].map(lambda f: str(PHOTO_DIR / f))
    return df.sort_values("date").reset_index(drop=True)


def context_for_photo(photo: dict, daily: pd.DataFrame, routine: pd.DataFrame,
                      analysis_mod) -> dict:
    """Return bodyweight + priority-lift e1RMs near a photo's date."""
    date = pd.to_datetime(photo["date"])
    out: dict = {"bodyweight": None, "lifts": []}

    if not daily.empty and "weight" in daily:
        bw = daily.dropna(subset=["weight"])
        if not bw.empty:
            near = bw.iloc[(bw["date"] - date).abs().argsort()[:1]]
            if not near.empty and abs((near["date"].iloc[0] - date).days) <= 14:
                out["bodyweight"] = round(float(near["weight"].iloc[0]), 1)

    for lift in AREA_TO_LIFTS.get(photo["area"], []):
        sb = analysis_mod.session_best(routine, lift).dropna(subset=["e1rm"])
        if sb.empty:
            continue
        upto = sb[sb["date"] <= date + pd.Timedelta(days=7)]
        if upto.empty:
            continue
        out["lifts"].append({"lift": lift,
                             "e1rm": round(float(upto["best_e1rm"].iloc[-1]), 1)})
    return out
