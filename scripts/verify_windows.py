"""Verify the shipped ZIP in a fresh Unicode path with developer PATH entries removed."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main() -> None:
    if sys.platform != "win32" or len(sys.argv) != 2:
        raise SystemExit("Usage on Windows: python scripts/verify_windows.py <candidate.zip>")
    archive = Path(sys.argv[1]).resolve()
    expected_hash = archive.with_suffix(".zip.sha256").read_text(encoding="ascii").split()[0]
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected_hash:
            raise RuntimeError("Candidate checksum does not match")
    root = Path(__file__).resolve().parents[1]
    destination = Path(tempfile.mkdtemp(prefix="验收 空格-", dir=root / "build"))
    with zipfile.ZipFile(archive) as package:
        for entry in package.infolist():
            relative = Path(entry.filename)
            if not (destination / relative).resolve().is_relative_to(destination):
                raise RuntimeError("Archive member escapes destination")
            if relative.parts[0] != "LinkForge":
                raise RuntimeError("Unexpected archive root")
            if any(part.lower() in {"logs", "browser-profile", ".venv", ".env"} for part in relative.parts):
                raise RuntimeError("Unexpected user/build data in candidate")
        package.extractall(destination)
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        env.pop(name, None)
    windows = Path(env["SYSTEMROOT"])
    env["PATH"] = os.pathsep.join(str(p) for p in (windows / "System32", windows))
    env["QT_QPA_PLATFORM"] = "windows"
    # Deliberately wrong inherited paths must be overridden by the runtime hook.
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(destination / "missing-browser-cache")
    env["PLAYWRIGHT_NODEJS_PATH"] = str(destination / "missing-node.exe")
    report = destination / "package-check.json"
    process = subprocess.run(
        [str(destination / "LinkForge/LinkForge.exe"), "--self-test", str(report)],
        cwd=destination,
        env=env,
        timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW,
        capture_output=True,
    )
    if process.returncode != 0 or not report.is_file():
        raise RuntimeError(f"Packaged diagnostic failed ({process.returncode}); inspect {destination}")
    result = json.loads(report.read_text(encoding="utf-8"))
    if result.get("status") != "passed" or result.get("frozen") is not True:
        raise RuntimeError(f"Packaged diagnostic did not pass: {report}")
    print(json.dumps(result, indent=2))
    print(f"Report and screenshot: {report}")
    print("This isolates development PATH and browser cache; it is not a clean Windows VM test.")


if __name__ == "__main__":
    main()
