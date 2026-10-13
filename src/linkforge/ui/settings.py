"""GUI 偏好设置与服务商凭据，与运行时配置相分离。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Protocol

import keyring
from keyring.backend import KeyringBackend
from keyring.backends.chainer import ChainerBackend
from PySide6.QtCore import QSettings, QStandardPaths

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


def default_profile_dir() -> str:
    """将浏览器身份保存在可更换的便携应用目录之外。"""
    root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
    if not root:
        raise RuntimeError("Local application data directory is unavailable.")
    return str(Path(root) / "LinkForge" / "browser-profile")


@dataclass(slots=True, repr=False)
class UserSettings:
    """仅保存非机密 GUI 字段；空值保留首次运行的默认值。"""

    course_url: str = ""
    provider: str = ""
    model: str = ""
    profile_dir: str = ""


class CredentialStore(Protocol):
    """可替换的凭据接口，便于进行确定性测试。"""

    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...


class SystemCredentialStore:
    """仅使用原生 keyring 后端，拒绝文件型与空后端。"""

    @staticmethod
    def _backend() -> KeyringBackend:
        backend = keyring.get_keyring()
        # Chainer 可能包含第三方明文后端。显式选择原生后端，
        # 而不是让链一路回退到它们。
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
    """尽力而为的持久化；绝不暴露后端异常详情或机密。"""

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
        """恢复偏好设置；存储损坏或不可用时应使用默认值。"""
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
        """仅在 GUI 校验通过后写入四个非机密字段。"""
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

    def save_course_url(self, course_url: str) -> bool:
        """持久化课程进度断点，不重写其他字段或凭据。"""
        try:
            if self._settings is None:
                return False
            self._settings.setValue(_SETTINGS_PREFIX + "course_url", course_url)
            self._settings.sync()
            return self._settings.status() == QSettings.Status.NoError
        except Exception:
            logger.warning("Course progress could not be saved; this run can continue.")
            return False

    def load_api_key(self, provider: str) -> str | None:
        """只读取该服务商的凭据；缺失或已删除的密钥保持为空。"""
        if provider not in MODEL_PROVIDERS:
            return None
        try:
            return self._credentials.get_password(CREDENTIAL_SERVICE, f"api_key:{provider}")
        except Exception:
            logger.warning("API Key could not be loaded from system credential storage.")
            return None

    def save_api_key(self, provider: str, api_key: str) -> bool:
        """原生凭据存储无法保存时不提供明文回退。"""
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
