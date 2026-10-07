"""Portable paths and startup failures, without native credentials or browser launches."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from linkforge import gui
from linkforge.ui.settings import UserSettings, default_profile_dir
from linkforge.ui.window import MainWindow


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


def test_default_profile_is_stable_and_does_not_create_data(tmp_path, monkeypatch):
    monkeypatch.setattr(QStandardPaths, "writableLocation", lambda _kind: str(tmp_path))
    expected = tmp_path / "LinkForge" / "browser-profile"
    assert default_profile_dir() == str(expected)
    assert not expected.exists()


def test_missing_local_data_location_is_explicit(monkeypatch):
    monkeypatch.setattr(QStandardPaths, "writableLocation", lambda _kind: "")
    with pytest.raises(RuntimeError):
        default_profile_dir()


def test_default_profile_only_replaces_empty_saved_value(application, isolated_settings_store, monkeypatch):
    monkeypatch.setattr("linkforge.ui.window.default_profile_dir", lambda: "default-profile")
    window = MainWindow()
    assert window.profile_dir_edit.text() == "default-profile"
    window.close()
    isolated_settings_store.save(UserSettings(profile_dir="custom-profile"))
    window = MainWindow()
    assert window.profile_dir_edit.text() == "custom-profile"
    window.close()


def test_log_button_opens_supplied_active_directory(application, tmp_path, monkeypatch):
    opened = []
    directory = tmp_path / "中文 logs"
    monkeypatch.setattr(
        "linkforge.ui.window.QDesktopServices.openUrl", lambda url: opened.append(url) or True
    )
    window = MainWindow(log_dir=directory)
    window.open_logs_button.click()
    assert len(opened) == 1
    assert Path(opened[0].toLocalFile()) == directory
    window.close()


@pytest.mark.parametrize("raises", [False, True])
def test_log_folder_open_failure_explains_manual_location(application, tmp_path, monkeypatch, raises):
    def open_url(_url):
        if raises:
            raise OSError("test")
        return False

    warning = Mock()
    monkeypatch.setattr("linkforge.ui.window.QDesktopServices.openUrl", open_url)
    monkeypatch.setattr(QMessageBox, "warning", warning)
    window = MainWindow(log_dir=tmp_path)
    window.open_logs_button.click()
    assert str(tmp_path) in warning.call_args.args[2]
    window.close()


def test_gui_reports_unwritable_logs_before_creating_window(monkeypatch):
    app = Mock()
    error = Mock()
    window = Mock()
    monkeypatch.setattr(gui, "QApplication", lambda _args: app)
    monkeypatch.setattr(gui, "setup_logging", Mock(side_effect=PermissionError("private-path")))
    monkeypatch.setattr(gui, "MainWindow", window)
    monkeypatch.setattr(QMessageBox, "critical", error)
    assert gui.main() == 1
    assert "logs" in error.call_args.args[2]
    assert "private-path" not in error.call_args.args[2]
    window.assert_not_called()
    app.exec.assert_not_called()


def test_gui_passes_actual_log_location_to_window(monkeypatch, tmp_path):
    app = Mock()
    app.exec.return_value = 0
    window = Mock()
    monkeypatch.setattr(gui, "QApplication", lambda _args: app)
    monkeypatch.setattr(gui, "setup_logging", lambda: tmp_path / "test.log")
    monkeypatch.setattr(gui, "MainWindow", window)
    monkeypatch.setattr(gui.sys, "argv", ["LinkForge.exe"])
    assert gui.main() == 0
    window.assert_called_once_with(log_dir=tmp_path)
