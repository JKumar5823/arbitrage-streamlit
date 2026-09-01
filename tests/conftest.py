import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fundraising import db  # noqa: E402


@pytest.fixture
def dbpath(tmp_path):
    """A fresh, initialised database file for one test."""
    path = tmp_path / "test.db"
    db.init_db(path)
    return path
