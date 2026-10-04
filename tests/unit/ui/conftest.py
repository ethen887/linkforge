"""Isolate all GUI tests from real preferences and system credentials."""

import logging
import os
from collections.abc import Iterator
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication

from linkforge.ui.settings import UserSettingsStore
from linkforge.ui.window import MainWindow
from tests.fakes import FakeCredentialStore


@pytest.fixture(autouse=True)
def isolated_settings_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[UserSettingsStore]:
    settings = QSettings(str(tmp_path / "gui-test.ini"), QSettings.Format.IniFormat)
    store = UserSettingsStore(settings=settings, credentials=FakeCredentialStore())
    monkeypatch.setattr("linkforge.ui.window.UserSettingsStore", lambda: store)
    # Earlier logging tests disable propagation; security assertions must still
    # capture persistence warnings when running the complete suite.
    monkeypatch.setattr(logging.getLogger("linkforge"), "propagate", True)

    # Fail loudly if any test accidentally reaches native backend discovery.
    backend_calls = []

    def unexpected_backend():
        backend_calls.append("unexpected")
        raise AssertionError("GUI tests must not access the real system credential backend")

    monkeypatch.setattr("linkforge.ui.settings.keyring.get_keyring", unexpected_backend)
    yield store
    # Match Qt's normal deferred destruction, rather than leaving closed
    # windows and signal cycles for Python's interpreter shutdown.
    application = QApplication.instance()
    if isinstance(application, QApplication):
        for window in application.topLevelWidgets():
            if isinstance(window, MainWindow):
                assert window._thread is None
                window.close()
                window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        application.processEvents()
    assert backend_calls == []
