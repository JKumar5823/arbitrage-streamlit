"""Persistence layer for extracted PitchBook records.

Talks to any SQL database SQLAlchemy supports. Set ``DATABASE_URL`` to a
cloud Postgres instance (AWS RDS, Neon, Supabase, ...) for cloud storage; if
unset, it falls back to a local SQLite file so the room works out of the box.

Cloud examples:
    postgresql+psycopg2://user:pass@my-db.abcdef.us-east-1.rds.amazonaws.com:5432/pitchbook
    postgresql+psycopg2://user:pass@ep-xxx.neon.tech/pitchbook?sslmode=require
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    desc,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Session

DEFAULT_SQLITE_PATH = os.environ.get("PITCHBOOK_DB_PATH", "pitchbook.db")


def resolve_db_url() -> str:
    """Cloud DATABASE_URL if set, else a local SQLite file."""
    url = os.environ.get("DATABASE_URL")
    if url:
        # Normalise the common 'postgres://' form to a SQLAlchemy driver URL.
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        return url
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"


class Base(DeclarativeBase):
    pass


class PitchbookRecord(Base):
    __tablename__ = "pitchbook_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    captured_at = Column(DateTime(timezone=True), nullable=False)
    source_label = Column(String(255), nullable=True)  # e.g. "Sequoia deals page"
    entity_type = Column(String(64), nullable=True)
    name = Column(String(512), nullable=True)
    company = Column(String(512), nullable=True)
    deal_type = Column(String(255), nullable=True)
    deal_size = Column(String(128), nullable=True)
    deal_date = Column(String(128), nullable=True)
    valuation = Column(String(128), nullable=True)
    industry = Column(String(255), nullable=True)
    location = Column(String(255), nullable=True)
    investors = Column(Text, nullable=True)
    extraction_method = Column(String(128), nullable=True)
    screenshot_path = Column(String(1024), nullable=True)
    data = Column(JSON, nullable=True)  # full record dict, incl. extra fields


# Normalised top-level columns we pull out of each record for easy querying.
_TOP_LEVEL = (
    "entity_type",
    "name",
    "company",
    "deal_type",
    "deal_size",
    "deal_date",
    "valuation",
    "industry",
    "location",
    "investors",
)


class Database:
    def __init__(self, url: Optional[str] = None):
        self.url = url or resolve_db_url()
        connect_args = {}
        if self.url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
        self.engine = create_engine(self.url, connect_args=connect_args, future=True)
        Base.metadata.create_all(self.engine)

    @property
    def backend(self) -> str:
        return self.engine.dialect.name  # 'sqlite', 'postgresql', ...

    def is_cloud(self) -> bool:
        return self.backend != "sqlite"

    def save_records(
        self,
        records: list[dict[str, Any]],
        source_label: str = "",
        extraction_method: str = "",
        screenshot_path: str = "",
        captured_at: Optional[datetime] = None,
    ) -> int:
        """Persist a batch of extracted records. Returns the count saved."""
        captured_at = captured_at or datetime.now(timezone.utc)
        rows = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            vals = {k: rec.get(k) for k in _TOP_LEVEL}
            # investors may arrive as a list
            if isinstance(vals.get("investors"), (list, tuple)):
                vals["investors"] = ", ".join(str(i) for i in vals["investors"])
            rows.append(
                PitchbookRecord(
                    captured_at=captured_at,
                    source_label=source_label or None,
                    extraction_method=extraction_method or None,
                    screenshot_path=screenshot_path or None,
                    data=rec,
                    **vals,
                )
            )
        if not rows:
            return 0
        with Session(self.engine) as session:
            session.add_all(rows)
            session.commit()
        return len(rows)

    def fetch_df(self, limit: int = 500) -> pd.DataFrame:
        with Session(self.engine) as session:
            stmt = select(PitchbookRecord).order_by(desc(PitchbookRecord.id)).limit(limit)
            records = session.scalars(stmt).all()
            data = []
            for r in records:
                data.append(
                    {
                        "id": r.id,
                        "captured_at": r.captured_at,
                        "source_label": r.source_label,
                        "entity_type": r.entity_type,
                        "name": r.name,
                        "company": r.company,
                        "deal_type": r.deal_type,
                        "deal_size": r.deal_size,
                        "deal_date": r.deal_date,
                        "valuation": r.valuation,
                        "industry": r.industry,
                        "location": r.location,
                        "investors": r.investors,
                        "method": r.extraction_method,
                        "data": json.dumps(r.data) if r.data else None,
                    }
                )
        return pd.DataFrame(data)

    def count(self) -> int:
        with Session(self.engine) as session:
            return session.query(PitchbookRecord).count()
