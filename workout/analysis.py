"""
Analytics layer: PRs, bodyweight correlation, plateau detection, volume by muscle,
and coaching recommendations built on top of the tidy DataFrames from ``loader``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Exercise progression & PRs
# ---------------------------------------------------------------------------

def exercise_list(routine: pd.DataFrame, min_sets: int = 3) -> list[str]:
    """Exercises with at least ``min_sets`` logged sets, most-frequent first."""
    if routine.empty:
        return []
    vc = routine["exercise"].value_counts()
    return vc[vc >= min_sets].index.tolist()


def exercise_history(routine: pd.DataFrame, exercise: str) -> pd.DataFrame:
    df = routine[routine["exercise"] == exercise].copy()
    return df.sort_values("date")


def session_best(routine: pd.DataFrame, exercise: str) -> pd.DataFrame:
    """One row per session: the best estimated-1RM and heaviest top set that day."""
    df = exercise_history(routine, exercise)
    if df.empty:
        return df
    g = df.groupby(df["date"].dt.date)
    out = g.agg(
        e1rm=("e1rm", "max"),
        top_weight=("weight", "max"),
        total_volume=("volume", "sum"),
        sets=("weight", "size"),
    ).reset_index()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values("date")
    # running best e1rm = the PR curve
    out["best_e1rm"] = out["e1rm"].cummax()
    return out


def pr_events(routine: pd.DataFrame, exercise: str) -> pd.DataFrame:
    """Sessions where a new estimated-1RM personal record was set."""
    sb = session_best(routine, exercise)
    if sb.empty:
        return sb
    sb = sb.dropna(subset=["e1rm"])
    if sb.empty:
        return sb
    prs = sb[sb["e1rm"] >= sb["best_e1rm"] - 1e-6]
    prs = prs[sb["e1rm"] == sb["e1rm"].cummax()]
    # keep only rows that strictly improved on the previous best
    improved = prs["e1rm"].cummax().diff().fillna(prs["e1rm"]).gt(0)
    return prs[improved].reset_index(drop=True)


def all_prs(routine: pd.DataFrame, min_sets: int = 5) -> pd.DataFrame:
    """Best estimated-1RM ever achieved per exercise, with the date it happened."""
    rows = []
    for ex in exercise_list(routine, min_sets):
        sb = session_best(routine, ex).dropna(subset=["e1rm"])
        if sb.empty:
            continue
        best = sb.loc[sb["e1rm"].idxmax()]
        rows.append({
            "exercise": ex,
            "best_e1rm": best["e1rm"],
            "top_weight": sb["top_weight"].max(),
            "date": best["date"],
            "sessions": len(sb),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("best_e1rm", ascending=False).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Bodyweight correlation
# ---------------------------------------------------------------------------

def attach_bodyweight(events: pd.DataFrame, daily: pd.DataFrame,
                      tol_days: int = 5) -> pd.DataFrame:
    """For each dated event, attach the nearest logged bodyweight (within tol_days)."""
    if events.empty or daily.empty or "weight" not in daily:
        events = events.copy()
        events["bodyweight"] = np.nan
        return events
    bw = daily.dropna(subset=["weight"])[["date", "weight"]].rename(
        columns={"weight": "bodyweight"}).sort_values("date")
    ev = events.sort_values("date")
    merged = pd.merge_asof(ev, bw, on="date", direction="nearest",
                           tolerance=pd.Timedelta(days=tol_days))
    return merged


# ---------------------------------------------------------------------------
# Plateau detection
# ---------------------------------------------------------------------------

def detect_plateau(routine: pd.DataFrame, exercise: str,
                   window_days: int = 56, min_gain_pct: float = 1.0) -> dict:
    """
    Flag a plateau if the best estimated-1RM has not improved by ``min_gain_pct``
    within the trailing ``window_days``.  Returns a dict describing the status.
    """
    sb = session_best(routine, exercise).dropna(subset=["e1rm"])
    if len(sb) < 3:
        return {"status": "insufficient", "exercise": exercise}

    last_date = sb["date"].max()
    window_start = last_date - pd.Timedelta(days=window_days)
    recent = sb[sb["date"] >= window_start]
    older = sb[sb["date"] < window_start]

    all_time_best = sb["e1rm"].max()
    best_before_window = older["e1rm"].max() if not older.empty else np.nan
    recent_best = recent["e1rm"].max()

    days_since_pr = (last_date - sb.loc[sb["e1rm"].idxmax(), "date"]).days

    # gain over the window relative to the best the athlete had entering it
    if not np.isnan(best_before_window) and best_before_window > 0:
        gain_pct = (recent_best - best_before_window) / best_before_window * 100
    else:
        gain_pct = np.nan

    plateaued = (
        days_since_pr >= window_days
        or (not np.isnan(gain_pct) and gain_pct < min_gain_pct)
    )
    status = "plateau" if plateaued else "progressing"
    if days_since_pr >= window_days * 1.6:
        status = "regression_risk"

    return {
        "status": status,
        "exercise": exercise,
        "all_time_best": round(float(all_time_best), 1),
        "recent_best": round(float(recent_best), 1) if not np.isnan(recent_best) else None,
        "gain_pct": None if np.isnan(gain_pct) else round(float(gain_pct), 1),
        "days_since_pr": int(days_since_pr),
        "sessions_in_window": int(len(recent)),
        "last_trained": last_date,
    }


def plateau_overview(routine: pd.DataFrame, min_sets: int = 8,
                     window_days: int = 56) -> pd.DataFrame:
    rows = []
    for ex in exercise_list(routine, min_sets):
        d = detect_plateau(routine, ex, window_days=window_days)
        if d.get("status") == "insufficient":
            continue
        # only show exercises trained reasonably recently
        rows.append(d)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    order = {"regression_risk": 0, "plateau": 1, "progressing": 2}
    df["__o"] = df["status"].map(order).fillna(3)
    df = df.sort_values(["__o", "days_since_pr"], ascending=[True, False]).drop(columns="__o")
    return df.reset_index(drop=True)


def plateau_advice(info: dict) -> list[str]:
    """Concrete, exercise-specific suggestions for breaking a plateau."""
    ex = info.get("exercise", "this lift")
    tips = []
    if info["status"] == "progressing":
        tips.append(f"✅ {ex} is still progressing (+{info.get('gain_pct')}% over the window). "
                    "Keep adding small load/reps each week.")
        return tips
    tips.append(f"⛔ No new {ex} PR in {info['days_since_pr']} days "
                f"(best ≈ {info['all_time_best']} lb e1RM).")
    tips += [
        "Run a short **deload** (1 week at ~60% volume) then restart at ~90% and build back — "
        "stagnation is often accumulated fatigue masking real strength.",
        "**Change the stimulus**: swap rep range (if you've been heavy, do 3×8–12; if light, do "
        "5×3–5), or rotate to a close variation for 4–6 weeks (tempo, pause, or a cousin lift).",
        "**Add a weekly volume set** to the main movement, or a second lighter session — "
        "the biggest driver of accessory-lift progress is total hard sets per week.",
        "Check **recovery inputs**: PRs are hard to set in a calorie deficit. If you're cutting, "
        "aim to maintain rather than PR, or take a maintenance break.",
    ]
    if info["status"] == "regression_risk":
        tips.insert(1, "⚠️ It's been a long time since you trained this hard — make sure it's still "
                       "in your program at a meaningful frequency (1–2×/week).")
    return tips


# ---------------------------------------------------------------------------
# Volume by muscle group
# ---------------------------------------------------------------------------

def weekly_volume_by_muscle(routine: pd.DataFrame) -> pd.DataFrame:
    if routine.empty:
        return pd.DataFrame()
    df = routine.copy()
    df["week"] = df["date"].dt.to_period("W").dt.start_time
    g = df.groupby(["week", "body_part"]).agg(
        hard_sets=("weight", "size"),
        volume=("volume", "sum"),
    ).reset_index()
    return g


def weekly_sets_by_muscle(routine: pd.DataFrame, weeks: int = 8) -> pd.DataFrame:
    """Average hard sets per week per muscle over the trailing ``weeks`` weeks."""
    wv = weekly_volume_by_muscle(routine)
    if wv.empty:
        return wv
    last = wv["week"].max()
    recent = wv[wv["week"] > last - pd.Timedelta(weeks=weeks)]
    out = recent.groupby("body_part").agg(
        avg_weekly_sets=("hard_sets", lambda s: round(s.sum() / weeks, 1)),
    ).reset_index().sort_values("avg_weekly_sets", ascending=False)
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Nutrition / activity coaching
# ---------------------------------------------------------------------------

def bodyweight_trend(daily: pd.DataFrame, window: int = 7) -> pd.DataFrame:
    if daily.empty or "weight" not in daily:
        return pd.DataFrame()
    df = daily.dropna(subset=["weight"])[["date", "weight"]].copy()
    df["smoothed"] = df["weight"].rolling(window, min_periods=1).mean()
    return df


def nutrition_summary(daily: pd.DataFrame, days: int = 28) -> dict:
    """Recent calorie balance, rate of weight change, and a coaching read."""
    if daily.empty:
        return {}
    df = daily.sort_values("date")
    cutoff = df["date"].max() - pd.Timedelta(days=days)
    recent = df[df["date"] >= cutoff]
    out: dict = {"window_days": days, "n_days": len(recent)}

    wt = recent.dropna(subset=["weight"])
    if len(wt) >= 2:
        span_weeks = max((wt["date"].max() - wt["date"].min()).days / 7.0, 1e-6)
        delta = wt["weight"].iloc[-1] - wt["weight"].iloc[0]
        out["weight_now"] = round(float(wt["weight"].iloc[-1]), 1)
        out["weight_change"] = round(float(delta), 1)
        out["rate_lb_per_week"] = round(float(delta / span_weeks), 2)
    if "calories" in recent:
        out["avg_calories"] = _safe_mean(recent["calories"])
    if "maint_cals" in recent:
        out["avg_maint"] = _safe_mean(recent["maint_cals"])
    if "deficit" in recent:
        out["avg_deficit"] = _safe_mean(recent["deficit"])
    if "steps" in recent:
        out["avg_steps"] = _safe_mean(recent["steps"])
    if "lifted" in recent:
        out["lift_days"] = int((recent["lifted"].str.upper().isin(["Y", "L", "U"])).sum())
    return out


def _safe_mean(s: pd.Series):
    s = pd.to_numeric(s, errors="coerce").dropna()
    return None if s.empty else round(float(s.mean()), 0)


def diminishing_returns(daily: pd.DataFrame, segment_weeks: int = 3) -> pd.DataFrame:
    """
    Break the timeline into segments and compute, for each, the weekly weight-change
    per 100 kcal of average deficit — i.e. how much 'bang' the deficit is buying.
    A shrinking magnitude = diminishing returns (adaptive thermogenesis / stall).
    """
    if daily.empty:
        return pd.DataFrame()
    df = daily.dropna(subset=["weight"]).sort_values("date").copy()
    if len(df) < segment_weeks * 7:
        return pd.DataFrame()
    df["seg"] = ((df["date"] - df["date"].min()).dt.days // (segment_weeks * 7))
    rows = []
    for seg, g in df.groupby("seg"):
        if len(g) < 4:
            continue
        weeks = max((g["date"].max() - g["date"].min()).days / 7.0, 1e-6)
        rate = (g["weight"].iloc[-1] - g["weight"].iloc[0]) / weeks
        avg_def = pd.to_numeric(g.get("deficit"), errors="coerce").mean()
        rows.append({
            "period_start": g["date"].min(),
            "period_end": g["date"].max(),
            "rate_lb_per_week": round(float(rate), 2),
            "avg_deficit": None if pd.isna(avg_def) else round(float(avg_def), 0),
            "avg_weight": round(float(g["weight"].mean()), 1),
        })
    return pd.DataFrame(rows)


def coaching_recommendations(daily: pd.DataFrame, routine: pd.DataFrame,
                             goal: str = "Lose fat") -> list[str]:
    """
    Turn the recent nutrition + training picture into concrete next actions,
    including a diminishing-returns read on when to shift focus.
    """
    tips: list[str] = []
    s = nutrition_summary(daily, days=28)
    if not s:
        return ["Not enough recent daily data to advise on. Log weight + calories to enable coaching."]

    rate = s.get("rate_lb_per_week")
    deficit = s.get("avg_deficit")
    steps = s.get("avg_steps")
    lift_days = s.get("lift_days")
    wt = s.get("weight_now")

    header = f"Last 4 weeks: ~{s.get('avg_calories','?')} kcal/day"
    if deficit is not None:
        header += f" ({'deficit' if deficit < 0 else 'surplus'} {abs(deficit):.0f} kcal)"
    if rate is not None:
        header += f", bodyweight {rate:+.2f} lb/week (now {wt} lb)."
    tips.append(header)

    if goal == "Lose fat":
        if rate is None:
            pass
        elif rate > 0.1:
            tips.append("🍽️ Goal is fat loss but bodyweight is **trending up** — you're at/above "
                        f"maintenance (~{s.get('avg_maint','?')} kcal). To lose ~0.5–1%/week, eat "
                        "roughly 400–600 kcal below maintenance and keep protein ≥0.9 g/lb.")
        elif -0.1 <= rate <= 0.1:
            tips.append("➖ Weight is basically flat — you're eating around maintenance. If the goal "
                        "is fat loss, drop ~300–500 kcal/day (or add steps) to create a real deficit.")
        elif rate > -0.25 and (deficit or 0) < -150:
            tips.append("⚠️ You're eating in a deficit but the scale has stalled — classic "
                        "**diminishing returns**. Options: (1) take a 1–2 week diet break at "
                        "maintenance to restore metabolic/hormonal output, then resume; "
                        "(2) add ~2k steps/day rather than cutting calories further; "
                        "(3) recheck logging accuracy. Don't just slash calories.")
        elif rate < -1.5:
            tips.append("🚩 Losing faster than ~1% BW/week — muscle-loss risk is high. Add "
                        "~150–250 kcal back and keep protein ≥0.9 g/lb to preserve your lifts.")
        elif rate is not None and -1.2 <= rate <= -0.4:
            tips.append("✅ Loss rate is in the ideal 0.5–1%/week band — hold this course and "
                        "keep protein high and training intensity up to retain strength.")
        if steps is not None and steps < 8000:
            tips.append(f"Steps average ~{steps:.0f}/day — nudging toward 9–10k is the cheapest "
                        "way to widen the deficit without touching food.")

    elif goal == "Build muscle":
        if rate is None or rate < 0.05:
            tips.append("To gain muscle you generally need a small surplus. Add ~150–250 kcal "
                        "until the scale trends up ~0.25–0.5 lb/week (lean-bulk range).")
        elif rate > 0.75:
            tips.append("⚠️ Gaining >0.75 lb/week is mostly fat past the novice stage — trim "
                        "the surplus so the trend is ~0.25–0.5 lb/week.")
        else:
            tips.append("✅ Surplus and gain rate look right for lean muscle gain.")
        tips.append("Muscle is built by progressive overload + volume: make sure priority "
                    "muscles are getting 10–20 hard sets/week (see the Volume page).")

    elif goal == "Improve a lift":
        tips.append("Strength PRs come easiest at maintenance or a slight surplus. If you're in "
                    "a deficit and a key lift has stalled, consider shifting to maintenance for a "
                    "training block so recovery can support new PRs (see Plateaus page).")

    if lift_days is not None:
        tips.append(f"You lifted ~{lift_days} day(s) in the last 4 weeks — "
                    + ("solid consistency." if lift_days >= 12 else
                       "bumping frequency would accelerate progress toward any goal."))

    # diminishing-returns trend
    dr = diminishing_returns(daily)
    if len(dr) >= 2:
        recent_rates = dr["rate_lb_per_week"].tail(3).tolist()
        if all(abs(r) < 0.25 for r in recent_rates[-2:]):
            tips.append("📉 The last several weeks show near-flat weight change — a sign it's time "
                        "to **shift focus** (e.g. from cutting to a maintenance/strength block, or "
                        "vice-versa) rather than grinding the same approach.")
    return tips
