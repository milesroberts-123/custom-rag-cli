"""Smoke test for the Streamlit review page."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from review_app import db

APP = Path(__file__).resolve().parents[1] / "app.py"


def _app(review_root, monkeypatch):
    monkeypatch.setenv("REVIEW_APP_ROOT", str(review_root))
    monkeypatch.setenv(
        "REVIEW_APP_DB", str(review_root / "results" / "review" / "review.db")
    )
    app = AppTest.from_file(str(APP), default_timeout=30)
    return app


def test_app_loads(review_root, monkeypatch):
    app = _app(review_root, monkeypatch)
    app.run()
    assert not app.exception
    assert app.title[0].value == "SRA annotation review"
    assert any(button.label == "Mark reviewed without changes" for button in app.button)


def test_app_marks_reviewed(review_root, monkeypatch):
    app = _app(review_root, monkeypatch)
    app.run()
    app.text_input(key="reviewer").set_value("miles").run()
    button = next(
        button
        for button in app.button
        if button.label == "Mark reviewed without changes"
    )
    button.click().run()
    assert not app.exception

    connection = db.connect(review_root / "results" / "review" / "review.db")
    try:
        status = db.review_status(connection)
    finally:
        connection.close()
    assert status["SRR000001"]["event_type"] == "reviewed"
    assert status["SRR000001"]["reviewer"] == "miles"


def test_app_saves_edit(review_root, monkeypatch):
    app = _app(review_root, monkeypatch)
    app.run()
    app.text_input(key="reviewer").set_value("miles").run()
    tissue = next(
        widget for widget in app.selectbox if widget.key == "tissue-SRR000001"
    )
    tissue.set_value("root")
    button = next(button for button in app.button if button.label == "Save")
    button.click().run()
    assert not app.exception

    connection = db.connect(review_root / "results" / "review" / "review.db")
    try:
        edits = db.latest_edits(connection)
    finally:
        connection.close()
    assert edits[("SRR000001", "tissue")] == "root"
