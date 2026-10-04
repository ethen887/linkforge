"""Tests for QSettings and injected credentials without real secret storage."""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from keyring.backends.chainer import ChainerBackend
from PySide6.QtCore import QSettings

from linkforge.config import MODEL_PROVIDERS
from linkforge.ui.settings import CREDENTIAL_SERVICE, SystemCredentialStore, UserSettings, UserSettingsStore
from tests.fakes import FakeCredentialStore


def test_no_history_loads_empty_defaults(isolated_settings_store: UserSettingsStore) -> None:
    assert isolated_settings_store.load() == UserSettings()


def test_preferences_round_trip_across_store_instances(tmp_path: Path) -> None:
    path = str(tmp_path / "settings.ini")
    settings = UserSettings("https://example.test/course", "deepseek", "custom-model", "test-profile")
    store = UserSettingsStore(
        settings=QSettings(path, QSettings.Format.IniFormat), credentials=FakeCredentialStore()
    )
    assert store.save(settings)
    reloaded = UserSettingsStore(
        settings=QSettings(path, QSettings.Format.IniFormat), credentials=FakeCredentialStore()
    )
    assert reloaded.load() == settings


def test_api_keys_are_isolated_and_never_written_to_qsettings(tmp_path: Path) -> None:
    path = tmp_path / "settings.ini"
    qsettings = QSettings(str(path), QSettings.Format.IniFormat)
    credentials = FakeCredentialStore()
    store = UserSettingsStore(settings=qsettings, credentials=credentials)
    store.save(UserSettings(provider="deepseek"))
    for provider in MODEL_PROVIDERS:
        assert store.save_api_key(provider, f"test-{provider}-key")
    for provider in MODEL_PROVIDERS:
        assert store.load_api_key(provider) == f"test-{provider}-key"
        assert (CREDENTIAL_SERVICE, f"api_key:{provider}") in credentials.set_calls
    assert set(qsettings.allKeys()) == {"gui/course_url", "gui/provider", "gui/model", "gui/profile_dir"}
    text = path.read_text(encoding="utf-8")
    assert "api_key" not in text
    for provider in MODEL_PROVIDERS:
        assert f"test-{provider}-key" not in text
    assert "test-" not in repr(store)


def test_missing_or_externally_deleted_credential_returns_none(tmp_path: Path) -> None:
    credentials = FakeCredentialStore()
    store = UserSettingsStore(
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
        credentials=credentials,
    )
    assert store.load_api_key("openai") is None
    store.save_api_key("openai", "test-openai-key")
    credentials._passwords.clear()
    assert store.load_api_key("openai") is None


def test_unsupported_provider_never_reaches_credential_store(tmp_path: Path) -> None:
    credentials = FakeCredentialStore()
    store = UserSettingsStore(
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
        credentials=credentials,
    )
    assert store.load_api_key("unknown") is None
    assert not store.save_api_key("unknown", "test-unknown-key")
    assert not store.save_api_key("qwen", "")
    assert credentials.get_calls == credentials.set_calls == []


def test_credential_exceptions_do_not_expose_details_or_fall_back(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    credentials = FakeCredentialStore()
    credentials.read_error = RuntimeError("test-read-key")
    credentials.write_error = RuntimeError("test-write-key")
    qsettings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    store = UserSettingsStore(settings=qsettings, credentials=credentials)
    with caplog.at_level(logging.WARNING):
        assert store.load_api_key("qwen") is None
        assert not store.save_api_key("qwen", "test-write-key")
    assert qsettings.allKeys() == []
    assert "test-read-key" not in caplog.text
    assert "test-write-key" not in caplog.text
    assert len(caplog.records) == 2
    assert all(record.exc_info is None and not record.args for record in caplog.records)


def test_malformed_preferences_fall_back_without_logging_values(tmp_path: Path, caplog) -> None:
    qsettings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    qsettings.setValue("gui/course_url", "https://example.test/?ticket=test-ticket")
    qsettings.setValue("gui/model", 12)
    store = UserSettingsStore(settings=qsettings, credentials=FakeCredentialStore())
    assert store.load() == UserSettings()
    assert "test-ticket" not in caplog.text
    assert "test-ticket" not in repr(UserSettings(course_url="test-ticket"))


def test_qsettings_status_errors_are_nonfatal(tmp_path: Path, monkeypatch, caplog) -> None:
    qsettings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    store = UserSettingsStore(settings=qsettings, credentials=FakeCredentialStore())
    monkeypatch.setattr(qsettings, "status", lambda: QSettings.Status.AccessError)
    assert store.load() == UserSettings()
    assert not store.save(UserSettings())
    assert "Traceback" not in caplog.text


def test_qsettings_constructor_failure_is_nonfatal(monkeypatch, caplog) -> None:
    def fail(*args):
        raise RuntimeError("test-sensitive-details")

    monkeypatch.setattr("linkforge.ui.settings.QSettings", fail)
    store = UserSettingsStore(credentials=FakeCredentialStore())
    assert store.load() == UserSettings()
    assert not store.save(UserSettings())
    assert "test-sensitive-details" not in caplog.text


@pytest.mark.parametrize("operation", ["value", "setValue", "sync"])
def test_qsettings_operation_exceptions_are_nonfatal(
    tmp_path: Path, monkeypatch, caplog, operation
) -> None:
    qsettings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    store = UserSettingsStore(settings=qsettings, credentials=FakeCredentialStore())

    def fail(*args):
        raise RuntimeError("test-sensitive-details")

    monkeypatch.setattr(qsettings, operation, fail)
    if operation != "setValue":
        assert store.load() == UserSettings()
    if operation != "value":
        assert not store.save(UserSettings())
    assert "test-sensitive-details" not in caplog.text


def test_backend_discovery_failure_is_sanitized(tmp_path: Path, monkeypatch, caplog) -> None:
    def fail():
        raise RuntimeError("test-backend-secret")

    monkeypatch.setattr("linkforge.ui.settings.keyring.get_keyring", fail)
    store = UserSettingsStore(
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    assert store.load_api_key("openai") is None
    assert not store.save_api_key("openai", "test-openai-key")
    assert "test-backend-secret" not in caplog.text
    assert "test-openai-key" not in caplog.text


@pytest.mark.parametrize("module", ["keyrings.alt.file", "keyring.backends.null", "keyring.backends.fail"])
def test_non_native_backends_are_rejected_without_secret_calls(monkeypatch, module) -> None:
    class UnsafeBackend:
        priority = 10

        def get_password(self, *args):
            raise AssertionError("Unsafe backend must never be called")

        def set_password(self, *args):
            raise AssertionError("Unsafe backend must never be called")

    UnsafeBackend.__module__ = module
    monkeypatch.setattr("linkforge.ui.settings.keyring.get_keyring", lambda: UnsafeBackend())
    native = SystemCredentialStore()
    with pytest.raises(RuntimeError, match="unavailable"):
        native.get_password(CREDENTIAL_SERVICE, "api_key:qwen")
    with pytest.raises(RuntimeError, match="unavailable"):
        native.set_password(CREDENTIAL_SERVICE, "api_key:qwen", "test-qwen-key")


def test_native_backend_delegation_and_chainer_never_falls_through(monkeypatch) -> None:
    class NativeBackend(FakeCredentialStore):
        priority = 1

    NativeBackend.__module__ = "keyring.backends.Windows"
    backend = NativeBackend()
    native = SystemCredentialStore()
    monkeypatch.setattr("linkforge.ui.settings.keyring.get_keyring", lambda: backend)
    native.set_password(CREDENTIAL_SERVICE, "api_key:qwen", "test-qwen-key")
    assert native.get_password(CREDENTIAL_SERVICE, "api_key:qwen") == "test-qwen-key"
    # Bypass Chainer discovery: it must not call a plaintext backend first.
    chain = object.__new__(ChainerBackend)
    monkeypatch.setattr(ChainerBackend, "backends", [SimpleNamespace(priority=99), backend])
    monkeypatch.setattr("linkforge.ui.settings.keyring.get_keyring", lambda: chain)
    assert native.get_password(CREDENTIAL_SERVICE, "api_key:qwen") == "test-qwen-key"
