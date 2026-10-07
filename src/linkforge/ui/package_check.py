"""Explicit, offline packaged-app diagnostic using only disposable test data."""

from __future__ import annotations

import json
import logging
import sys
import tempfile
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from linkforge.ui.settings import SystemCredentialStore, UserSettings, UserSettingsStore
from linkforge.ui.window import MainWindow


class _EmptyCredentials:
    def get_password(self, service: str, username: str) -> None:
        return None

    def set_password(self, service: str, username: str, password: str) -> None:
        raise RuntimeError("UI diagnostic must not save credentials")


def run_package_check(application: QApplication, report_path: Path, log_file: Path) -> int:
    """Write a report and screenshot; never open courses or read user settings/keys."""
    results: dict[str, object] = {"frozen": bool(getattr(sys, "frozen", False))}
    report_path = report_path.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    window: MainWindow | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="linkforge-check-", dir=report_path.parent) as temporary:
            root = Path(temporary)
            store = UserSettingsStore(
                settings=QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat),
                credentials=_EmptyCredentials(),
            )
            expected = UserSettings(model="package-check", profile_dir=str(root / "profile"))
            if not store.save(expected):
                raise RuntimeError("QSettings write failed")
            reloaded = UserSettingsStore(
                settings=QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat),
                credentials=_EmptyCredentials(),
            )
            if reloaded.load() != expected:
                raise RuntimeError("QSettings reload failed")
            results["settings"] = "passed"
            window = MainWindow(settings_store=reloaded, log_dir=log_file.parent)
            # Render a hidden widget with the native Windows font engine. The offscreen
            # Qt backend on Windows can render every glyph as a box despite a valid build.
            window.ensurePolished()
            central_widget = window.centralWidget()
            if central_widget is None:
                raise RuntimeError("Main window has no central widget")
            layout = central_widget.layout()
            if layout is not None:
                layout.activate()
            application.processEvents()
            if not window.grab().save(str(report_path.with_suffix(".png"))):
                raise RuntimeError("Qt screenshot failed")
            window.close()
            results["qt"] = "passed"

            backend = SystemCredentialStore._backend()
            service = "LinkForge.PackageCheck"
            username = uuid.uuid4().hex
            try:
                backend.set_password(service, username, "disposable-package-check")
                if backend.get_password(service, username) != "disposable-package-check":
                    raise RuntimeError("Credential readback failed")
                results["credentials"] = "passed"
                results["credential_backend"] = type(backend).__module__
            finally:
                # This unique entry belongs only to this check, never to the user.
                if backend.get_password(service, username) is not None:
                    backend.delete_password(service, username)

            with sync_playwright() as playwright:
                executable = Path(playwright.chromium.executable_path).resolve()
                if getattr(sys, "frozen", False):
                    if not executable.is_relative_to(Path(sys.executable).resolve().parent):
                        raise RuntimeError("Chromium resolved outside the bundle")
                # channel=chromium uses the full browser, including in headless mode.
                for attempt in range(2):
                    context = playwright.chromium.launch_persistent_context(
                        str(root / "profile"), headless=True, channel="chromium"
                    )
                    try:
                        page = context.new_page()
                        page.set_content("<title>LinkForge package check</title><p>offline</p>")
                        if page.title() != "LinkForge package check":
                            raise RuntimeError("Browser DOM check failed")
                        if attempt == 0:
                            context.add_cookies(
                                [
                                    {
                                        "name": "package-check",
                                        "value": "ok",
                                        "url": "https://example.test",
                                        "expires": 4102444800,
                                    }
                                ]
                            )
                        elif not any(c["name"] == "package-check" for c in context.cookies()):
                            raise RuntimeError("Browser profile persistence failed")
                    finally:
                        context.close()
                results["chromium_and_profile"] = "passed"
            if not log_file.is_file():
                raise RuntimeError("Log file is missing")
            results["logs"] = "passed"
        results["status"] = "passed"
    except Exception as exc:
        results["status"] = "failed"
        results["error_type"] = type(exc).__name__
        logging.getLogger(__name__).exception("Package diagnostic failed")
    finally:
        if window is not None:
            window.close()
        report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if results["status"] == "passed" else 1
