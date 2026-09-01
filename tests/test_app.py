"""End-to-end checks that the Streamlit script runs and its writes land."""

import os
from datetime import date

import pytest

from fundraising import config, db, seed

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str((__import__("pathlib").Path(__file__).resolve().parent.parent / "app.py"))


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Point the app at a throwaway database instead of the real one."""
    monkeypatch.setenv("FUNDRAISING_DB", str(tmp_path / "app.db"))
    return AppTest.from_file(APP, default_timeout=120)


def test_runs_with_no_data(app):
    app.run()
    assert not app.exception
    assert len(app.tabs) == 6
    assert app.metric[0].value == "0"


def test_runs_with_data(app, tmp_path, monkeypatch):
    seed.seed_demo(tmp_path / "app.db", today=date.today())
    app.run()
    assert not app.exception
    assert int(app.metric[0].value.replace(",", "")) == 53
    assert app.metric[1].label == "Investors engaged"


def test_demo_button_populates_an_empty_database(app):
    app.run()
    button = [b for b in app.button if b.label == "Load demo data"]
    assert button, "an empty database should offer the demo"
    button[0].click().run()
    assert not app.exception
    assert db.counts(os.environ["FUNDRAISING_DB"])["conversations"] > 0


def test_logging_a_conversation_through_the_form(app, tmp_path):
    # Seed the directory first: the form's pickers offer known names, and the
    # test harness can only select an option that is already on the list.
    db.init_db(tmp_path / "app.db")
    db.upsert_person("Jay Kumar", path=tmp_path / "app.db")
    db.upsert_investor("Acme Ventures", path=tmp_path / "app.db")
    app.run()

    app.selectbox[0].set_value("Jay Kumar")      # team member
    app.selectbox[1].set_value("Acme Ventures")  # investor
    app.button[0].click().run()

    assert not app.exception
    frame = db.list_conversations(os.environ["FUNDRAISING_DB"])
    assert len(frame) == 1
    assert frame.iloc[0]["person"] == "Jay Kumar"
    assert frame.iloc[0]["investor"] == "Acme Ventures"
    assert frame.iloc[0]["source"] == config.SOURCE_MANUAL


def test_settings_persist(app):
    app.run()
    app.slider[0].set_value(6.5).run()
    [b for b in app.button if b.label == "Save settings"][0].click().run()

    assert not app.exception
    assert db.get_setting(config.S_SCORE_THRESHOLD,
                          path=os.environ["FUNDRAISING_DB"]) == 6.5


def test_adopting_system_of_record_from_the_ui(app):
    app.run()
    adopt = [b for b in app.button if b.label == "Adopt as system of record"][0]
    assert adopt.disabled, "adoption must be gated behind the confirmation box"

    app.checkbox[0].set_value(True).run()
    [b for b in app.button if b.label == "Adopt as system of record"][0].click().run()

    assert not app.exception
    assert db.get_setting(config.S_SOR_ADOPTED_AT, path=os.environ["FUNDRAISING_DB"])


def test_filters_narrow_the_headline_number(app, tmp_path):
    seed.seed_demo(tmp_path / "app.db", today=date.today())
    app.run()
    everything = int(app.metric[0].value.replace(",", ""))

    app.multiselect[0].set_value(["Jay Kumar"]).run()
    filtered = int(app.metric[0].value.replace(",", ""))

    assert not app.exception
    assert 0 < filtered < everything
