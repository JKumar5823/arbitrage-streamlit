"""Realistic demo data, so the dashboard is legible before any real import."""

from __future__ import annotations

import random
from datetime import date, timedelta

from . import config, db

PEOPLE = [
    ("Jay Kumar", "jay@example.com", "CEO"),
    ("Priya Raman", "priya@example.com", "COO"),
    ("Marcus Webb", "marcus@example.com", "Head of BD"),
]

INVESTORS = [
    ("Northgate Capital", "VC", "northgate.vc"),
    ("Bluefern Ventures", "VC", "bluefern.com"),
    ("Harbour Line Partners", "VC", "harbourline.vc"),
    ("Ada Angels", "Angel", "adaangels.io"),
    ("Kestrel Family Office", "Family Office", "kestrelfo.com"),
    ("Summit Strategic", "Strategic", "summitstrategic.com"),
    ("Rivermark Fund", "VC", "rivermark.fund"),
    ("Tessera Seed", "VC", "tessera.vc"),
    ("Cobalt Crossover", "Crossover", "cobaltx.com"),
    ("Lantern Accelerator", "Accelerator", "lantern.co"),
    ("Vale Partners", "VC", "valepartners.vc"),
    ("Orchard Angels", "Angel", "orchardangels.com"),
]

# Each investor's journey: how far they got, and whether they ended up passing.
JOURNEYS = [
    ("Northgate Capital", ["Sourced", "Intro", "First Meeting", "Follow-up",
                           "Partner Meeting", "Diligence", "Term Sheet", "Committed"]),
    ("Bluefern Ventures", ["Sourced", "Intro", "First Meeting", "Follow-up",
                           "Partner Meeting", "Diligence"]),
    ("Harbour Line Partners", ["Sourced", "Intro", "First Meeting", "Passed"]),
    ("Ada Angels", ["Intro", "First Meeting", "Committed"]),
    ("Kestrel Family Office", ["Sourced", "Intro", "First Meeting", "Follow-up"]),
    ("Summit Strategic", ["Sourced", "Intro", "First Meeting", "Follow-up",
                          "Partner Meeting"]),
    ("Rivermark Fund", ["Sourced", "Intro", "Passed"]),
    ("Tessera Seed", ["Sourced", "Intro", "First Meeting", "Follow-up",
                      "Partner Meeting", "Diligence", "Term Sheet"]),
    ("Cobalt Crossover", ["Sourced", "Intro"]),
    ("Lantern Accelerator", ["Sourced", "Intro", "First Meeting", "Committed"]),
    ("Vale Partners", ["Sourced", "Intro", "First Meeting", "Passed"]),
    ("Orchard Angels", ["Intro", "First Meeting", "Follow-up"]),
]

NEXT_STEPS = [
    "Send updated deck", "Share data room access", "Schedule partner meeting",
    "Send customer references", "Follow up on diligence questions",
    "Circulate revised model", "Intro to design partner", "Confirm allocation",
]

CHANNEL_BY_STAGE = {
    "Sourced": "Email", "Intro": "Intro", "First Meeting": "Video Call",
    "Follow-up": "Video Call", "Partner Meeting": "Meeting",
    "Diligence": "Video Call", "Term Sheet": "Phone Call",
    "Committed": "Phone Call", "Passed": "Email",
}


def seed_demo(path=None, today: date | None = None, seed: int = 7) -> dict[str, int]:
    """Populate an empty database with a plausible ~14-week raise.

    Returns the row counts written. Existing conversations are left untouched --
    call ``reset`` first if you want a clean slate.
    """
    rng = random.Random(seed)
    today = today or date.today()
    db.init_db(path)

    person_ids = {name: db.upsert_person(name, email=email, role=role, path=path)
                  for name, email, role in PEOPLE}
    investor_ids = {name: db.upsert_investor(name, type=kind, domain=domain, path=path)
                    for name, kind, domain in INVESTORS}

    db.set_setting(config.S_HOME_DOMAINS, ["example.com"], path=path)
    db.set_setting(config.S_TARGET_CONVERSATIONS, 120, path=path)
    db.set_setting(config.S_RAISE_TARGET_AMOUNT, 6_000_000, path=path)

    written = 0
    for investor_name, journey in JOURNEYS:
        owner = rng.choice([p[0] for p in PEOPLE])
        # Walk the journey backwards from a recent date so the pipeline looks live.
        cursor = today - timedelta(days=rng.randint(2, 30))
        dates = []
        for _ in journey:
            dates.append(cursor)
            cursor -= timedelta(days=rng.randint(5, 16))
        dates.reverse()

        for position, (stage, when) in enumerate(zip(journey, dates)):
            is_last = position == len(journey) - 1
            amount = None
            if stage in ("Term Sheet", "Committed"):
                amount = rng.choice([250_000, 500_000, 750_000, 1_000_000, 2_000_000])
            db.add_conversation({
                "occurred_on": when.isoformat(),
                "person_id": person_ids[owner],
                "investor_id": investor_ids[investor_name],
                "counterpart": f"partner@{dict((i[0], i[2]) for i in INVESTORS)[investor_name]}",
                "channel": CHANNEL_BY_STAGE.get(stage, "Meeting"),
                "stage": stage,
                "outcome": ("Committed" if stage == "Committed"
                            else "Passed" if stage == "Passed"
                            else "Advancing"),
                "amount": amount,
                "next_step": (rng.choice(NEXT_STEPS)
                              if is_last and stage not in config.TERMINAL_STAGES else None),
                "next_step_due": ((when + timedelta(days=rng.randint(-4, 12))).isoformat()
                                  if is_last and stage not in config.TERMINAL_STAGES else None),
                "notes": f"{stage} with {investor_name}",
                "source": config.SOURCE_MANUAL,
            }, path=path)
            written += 1

    return {"people": len(person_ids), "investors": len(investor_ids),
            "conversations": written}


def reset(path=None) -> None:
    """Drop all operational rows. Settings and schema survive."""
    with db._WRITE_LOCK, db.session(path) as conn:
        for table in ("calendar_events", "conversations", "import_batches",
                      "investors", "people", "audit_log"):
            conn.execute(f"DELETE FROM {table}")
        db.log(conn, "database", None, "reset")
