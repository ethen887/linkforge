"""GUI preferences and provider credentials, separate from runtime configuration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from typing import Protocol

import keyring
from keyring.backend import KeyringBackend
from keyring.backends.chainer import ChainerBackend
from PySide6.QtCore import QSettings

from linkforge.config import MODEL_PROVIDERS

logger = logging.getLogger(__name__)

CREDENTIAL_SERVICE = "LinkForge.GUI"
_SETTINGS_PREFIX = "gui/"
_NATIVE_BACKEND_MODULES = {
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.kwallet",
}


@dataclass(slots=True, repr=False)
class UserSettings:
    """Only non-secret GUI fields; empty values preserve first-run defaults."""

    course_url: str = ""
    provider: str = ""
    model: str = ""
    profile_dir: str = ""


class CredentialStore(Protocol):
    """Replaceable credential interface for deterministic tests."""

    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...


class SystemCredentialStore:
    """Use native keyring backends only, rejecting file and null backends."""

    @staticmethod
    def _backend() -> KeyringBackend:
        backend = keyring.get_keyring()
        # A Chainer may contain third-party plaintext backends. Select a native
        # backend explicitly rather than allowing the chain to fall through.
        candidates = backend.backends if isinstance(backend, ChainerBackend) else [backend]
        for candidate in candidates:
            if type(candidate).__module__ in _NATIVE_BACKEND_MODULES and candidate.priority > 0:
                return candidate
        raise RuntimeError("System credential storage is unavailable.")

    def get_password(self, service: str, username: str) -> str | None:
        return self._backend().get_password(service, username)

    def set_password(self, service: str, username: str, password: str) -> None:
        self._backend().set_password(service, username, password)


class UserSettingsStore:
    """Best-effort persistence; never expose backend exception details or secrets."""

    def __init__(
        self,
        *,
        settings: QSettings | None = None,
        credentials: CredentialStore | None = None,
    ) -> None:
        self._credentials = credentials if credentials is not None else SystemCredentialStore()
        self._settings: QSettings | None = None
        try:
            self._settings = settings if settings is not None else QSettings("LinkForge", "LinkForge")
            self._settings.setFallbacksEnabled(False)
        except Exception:
            self._settings = None
            logger.warning("GUI settings storage is unavailable.")

    def load(self) -> UserSettings:
        """Restore preferences, or use defaults when storage is corrupt/unavailable."""
        try:
            if self._settings is None:
                return UserSettings()
            self._settings.sync()
            if self._settings.status() != QSettings.Status.NoError:
                raise RuntimeError("Settings read failed.")
            values: dict[str, str] = {}
            for field in fields(UserSettings):
                value = self._settings.value(_SETTINGS_PREFIX + field.name, "")
                if not isinstance(value, str):
                    raise ValueError("Settings values must be strings.")
                values[field.name] = value
            return UserSettings(**values)
        except Exception:
            logger.warning("GUI settings could not be loaded; using defaults.")
            return UserSettings()

    def save(self, settings: UserSettings) -> bool:
        """Write the four non-secret fields only after GUI validation succeeds."""
        try:
            if self._settings is None:
                return False
            for field in fields(UserSettings):
                self._settings.setValue(_SETTINGS_PREFIX + field.name, getattr(settings, field.name))
            self._settings.sync()
            if self._settings.status() != QSettings.Status.NoError:
                raise RuntimeError("Settings write failed.")
            return True
        except Exception:
            logger.warning("GUI settings could not be saved; this run can continue.")
            return False

    def load_api_key(self, provider: str) -> str | None:
        """Read only this provider's credential; missing/deleted keys stay empty."""
        if provider not in MODEL_PROVIDERS:
            return None
        try:
            return self._credentials.get_password(CREDENTIAL_SERVICE, f"api_key:{provider}")
        except Exception:
            logger.warning("API Key could not be loaded from system credential storage.")
            return None

    def save_api_key(self, provider: str, api_key: str) -> bool:
        """No plaintext fallback when native credential storage cannot save."""
        if provider not in MODEL_PROVIDERS or not api_key:
            return False
        try:
            self._credentials.set_password(CREDENTIAL_SERVICE, f"api_key:{provider}", api_key)
            return True
        except Exception:
            logger.warning(
                "API Key could not be saved to system credential storage; this run can continue."
            )
            return False
