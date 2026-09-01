"""Small text/date helpers shared by the ingestion modules."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from typing import Any, Iterable

import pandas as pd

from . import config

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def emails_in(text: str | None) -> list[str]:
    """Every email address appearing in a blob of text, lowercased and unique."""
    if not text:
        return []
    seen, out = set(), []
    for match in _EMAIL_RE.findall(str(text)):
        addr = match.lower().rstrip(".")
        if addr not in seen:
            seen.add(addr)
            out.append(addr)
    return out


def domain_of(email: str | None) -> str:
    if not email or "@" not in str(email):
        return ""
    return str(email).rsplit("@", 1)[-1].strip().lower().strip(">").strip()


def is_generic_domain(domain: str) -> bool:
    return domain.lower() in config.GENERIC_EMAIL_DOMAINS


def clean_domain(value: str | None) -> str:
    """Normalise anything domain-ish (a URL, an @handle, an email) to a domain."""
    if not value:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = text.split("/")[0]
    if "@" in text:
        text = text.rsplit("@", 1)[-1]
    text = text.lstrip("@").strip()
    if text.startswith("www."):
        text = text[4:]
    return text


def to_iso(value: Any) -> str | None:
    """Best-effort conversion of a date-like value to an ISO string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    parsed = pd.to_datetime(value, errors="coerce")
    if parsed is None or pd.isna(parsed):
        return None
    return parsed.isoformat()


def to_date_str(value: Any) -> str | None:
    """Convert a date-like value to a bare ``YYYY-MM-DD`` string."""
    iso = to_iso(value)
    return iso[:10] if iso else None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_aware(value: datetime | date | None) -> datetime | None:
    """Promote a date or naive datetime to a UTC-aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


def stable_key(*parts: Any) -> str:
    """A short deterministic hash, used to make re-imports idempotent."""
    joined = "|".join("" if p is None else str(p).strip().lower() for p in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def parse_list(value: Any) -> list[str]:
    """Split a comma/newline separated blob into a clean list of strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in re.split(r"[,\n;]+", str(value)) if part.strip()]


def coerce_amount(value: Any) -> float | None:
    """Parse money written by humans: ``$250,000``, ``1.5m``, ``250k``."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None if pd.isna(value) else float(value)
    text = str(value).strip().lower().replace(",", "").replace("$", "").replace("usd", "").strip()
    if not text:
        return None
    multiplier = 1.0
    if text.endswith(("k", "m", "b")):
        multiplier = {"k": 1e3, "m": 1e6, "b": 1e9}[text[-1]]
        text = text[:-1].strip()
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def first_present(mapping: dict, keys: Iterable[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None
