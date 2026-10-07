"""Build a fresh Windows x64 candidate from locked dependencies (no user data)."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]


def build_environment() -> dict[str, str]:
    """Do not resolve Qt/system DLLs from Conda or unrelated developer tools."""
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        env.pop(name, None)
    windows = Path(env["SYSTEMROOT"])
    env["PATH"] = os.pathsep.join(
        str(path)
        for path in (Path(sys.executable).parent, Path(sys.base_prefix), windows / "System32", windows)
    )
    env["PLAYWRIGHT_BROWSERS_PATH"] = "0"
    env.pop("PLAYWRIGHT_NODEJS_PATH", None)
    return env


def collect_notices(destination: Path) -> None:
    """Preserve installed distributions' license texts and metadata attribution."""
    destination.mkdir()
    inventory = []
    # Editable installs may expose the same distribution through multiple sys.path entries.
    distributions = {(d.metadata["Name"].lower(), d.version): d for d in importlib.metadata.distributions()}
    for distribution in sorted(distributions.values(), key=lambda d: d.metadata["Name"]):
        name = distribution.metadata["Name"]
        directory = destination / f"{name}-{distribution.version}"
        directory.mkdir()
        files = []
        for entry in distribution.files or []:
            # Only distribution metadata: never copy arbitrary project or user files.
            if not any(part.endswith(".dist-info") for part in entry.parts):
                continue
            if entry.name != "METADATA" and not any(
                word in str(entry).lower() for word in ("license", "licence", "copying", "notice")
            ):
                continue
            source = Path(distribution.locate_file(entry))
            if source.is_file():
                relative = Path(*entry.parts[1:])
                target = directory / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                files.append(str(relative))
        inventory.append({"name": name, "version": distribution.version, "notice_files": files})
    (destination / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (destination / "README.txt").write_text(
        "This directory preserves notices from the locked build environment, including build tools.\n"
        "Not every listed distribution is included in the executable.\n"
        "Additional Node.js, Playwright and Chromium notices remain beside their bundled files.\n"
        "Qt/PySide6 libraries are dynamically loaded from _internal/PySide6; preserve their licenses.\n"
        "Upstream source: https://code.qt.io/ and https://code.qt.io/pyside/pyside-setup.git/\n"
        "Python source and license: https://www.python.org/downloads/source/\n"
        "Chromium source: https://chromium.googlesource.com/chromium/src/\n",
        encoding="utf-8",
    )


def main() -> None:
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Build with Windows x64 and 64-bit Python.")
    if sys.maxsize <= 2**32:
        raise SystemExit("64-bit Python is required.")
    version = Version(importlib.metadata.version("linkforge"))
    release = version.base_version
    if version.pre:
        kind, number = version.pre
        release += f"-{'beta' if kind == 'b' else kind}.{number}"
    filename = f"LinkForge-v{release}-windows-x64"
    env = build_environment()
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True, env=env)
    build_root = ROOT / "build"
    build_root.mkdir(exist_ok=True)
    # A fresh staging directory prevents previous logs, profiles or extra files entering a ZIP.
    stage = Path(tempfile.mkdtemp(prefix="windows-", dir=build_root))
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(stage / "dist"),
            "--workpath",
            str(stage / "work"),
            str(ROOT / "build-support/windows/LinkForge.spec"),
        ],
        check=True,
        cwd=ROOT,
        env=env,
    )
    bundle = stage / "dist/LinkForge"
    browser_root = bundle / "_internal/playwright/driver/package/.local-browsers"
    if not list(browser_root.glob("chromium-*/chrome-win64/chrome.exe")):
        raise RuntimeError("Bundled Chromium executable is missing")
    shutil.copy2(ROOT / "LICENSE", bundle / "LICENSE.txt")
    shutil.copy2(ROOT / "build-support/windows/使用说明.txt", bundle / "使用说明.txt")
    collect_notices(bundle / "THIRD_PARTY_NOTICES")
    shutil.copytree(ROOT / "build-support/windows/licenses", bundle / "THIRD_PARTY_NOTICES/supplemental")
    # CPython's Windows installation normally provides LICENSE.txt; PyInstaller also collects it.
    for candidate in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE"):
        if candidate.is_file():
            shutil.copy2(candidate, bundle / "THIRD_PARTY_NOTICES/Python-LICENSE.txt")
            break
    (bundle / "BUILD-INFO.json").write_text(
        json.dumps(
            {
                "version": str(version),
                "python": platform.python_version(),
                "platform": "windows-x64",
                "pyinstaller": importlib.metadata.version("pyinstaller"),
                "playwright": importlib.metadata.version("playwright"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    archive = Path(shutil.make_archive(str(output / filename), "zip", stage / "dist", "LinkForge"))
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"Candidate directory: {bundle}")
    print(f"Candidate ZIP: {archive}")
    print("Run the packaged --self-test and clean-Windows acceptance before publishing.")


if __name__ == "__main__":
    main()
