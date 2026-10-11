"""Install, self-test, reinstall and uninstall a candidate in an isolated directory.

Refuses to run while LinkForge is already registered as installed for this user.
Creates temporary installer registry entries and Start Menu shortcuts, removed by
the tested uninstaller. Diagnostic files and user-data logs are retained.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\LinkForge.Desktop_is1"


def installed_directory() -> Path | None:
    import winreg

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except FileNotFoundError:
        return None
    with key:
        return Path(winreg.QueryValueEx(key, "InstallLocation")[0]).resolve()


def main() -> None:
    if sys.platform != "win32" or len(sys.argv) != 2:
        raise SystemExit("Usage on Windows: python scripts/verify_installer.py <setup.exe>")
    if installed_directory() is not None:
        raise SystemExit("LinkForge is already installed; use a separate Windows test account or VM.")
    shortcut = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/LinkForge/LinkForge.lnk"
    if shortcut.exists():
        raise SystemExit("A LinkForge shortcut already exists; use a separate test account or VM.")
    installer = Path(sys.argv[1]).resolve()
    checksum = installer.with_suffix(".exe.sha256").read_text(encoding="ascii").split()[0]
    with installer.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != checksum:
            raise RuntimeError("Installer checksum does not match")
    build = Path(__file__).resolve().parents[1] / "build"
    build.mkdir(exist_ok=True)
    acceptance = Path(tempfile.mkdtemp(prefix="安装验收 空格-", dir=build)).resolve()
    target = acceptance / "LinkForge"
    log_dir = Path(os.environ["LOCALAPPDATA"]) / "LinkForge/logs"
    old_logs = set(log_dir.glob("*.log"))
    results: dict[str, object] = {}
    try:
        for attempt in range(2):
            subprocess.run(
                [
                    str(installer),
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    "/TASKS=",
                    f"/DIR={target}",
                    f"/LOG={acceptance / f'install-{attempt}.log'}",
                ],
                check=True,
                timeout=300,
            )
            if installed_directory() != target.resolve():
                raise RuntimeError("Installer registered an unexpected directory")
            if not (target / "installed.ini").is_file() or not shortcut.is_file():
                raise RuntimeError("Installation marker or Start Menu shortcut is missing")
            env = os.environ.copy()
            for variable in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
                env.pop(variable, None)
            windows = Path(env["SYSTEMROOT"])
            env["PATH"] = os.pathsep.join(str(p) for p in (windows / "System32", windows))
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(acceptance / "missing-browser-cache")
            env["PLAYWRIGHT_NODEJS_PATH"] = str(acceptance / "missing-node.exe")
            report = acceptance / f"package-check-{attempt}.json"
            subprocess.run(
                [str(target / "LinkForge.exe"), "--self-test", str(report)],
                cwd=acceptance,
                env=env,
                check=True,
                timeout=180,
            )
            diagnostic = json.loads(report.read_text(encoding="utf-8"))
            if diagnostic.get("status") != "passed" or diagnostic.get("frozen") is not True:
                raise RuntimeError("Installed application diagnostic did not pass")
            if (target / "logs").exists() or not (set(log_dir.glob("*.log")) - old_logs):
                raise RuntimeError("Installed application did not use the user-data log directory")
            results["install" if attempt == 0 else "reinstall"] = "passed"
    finally:
        # Uninstall only this freshly registered test installation, never a pre-existing one.
        if installed_directory() == target.resolve():
            if not target.resolve().is_relative_to(acceptance):
                raise RuntimeError("Test installation escaped the acceptance directory")
            subprocess.run(
                [str(target / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                check=True,
                timeout=180,
            )
    if installed_directory() is not None or (target / "LinkForge.exe").exists() or shortcut.exists():
        raise RuntimeError("Uninstaller did not remove the test installation")
    if not (set(log_dir.glob("*.log")) - old_logs):
        raise RuntimeError("Uninstaller removed user-data diagnostic logs")
    results["uninstall_preserves_logs"] = "passed"
    (acceptance / "acceptance.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(f"Reports and screenshots: {acceptance}")
    print("Clean-Windows, interactive wizard, desktop shortcut and real-course checks remain manual.")


if __name__ == "__main__":
    main()
