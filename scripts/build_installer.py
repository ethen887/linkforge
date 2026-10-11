"""Build a Windows installer from a freshly self-tested portable bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from packaging.version import Version

from scripts.build_windows import ROOT
from scripts.build_windows import main as build_windows


def find_compiler(explicit: Path | None = None) -> Path:
    """Locate Inno Setup 7/6, or use the caller's exact compiler path."""
    if explicit is not None:
        if not explicit.is_file():
            raise FileNotFoundError(f"Inno Setup compiler does not exist: {explicit}")
        return explicit.resolve()
    found = shutil.which("ISCC.exe")
    if found:
        return Path(found).resolve()
    for variable, suffix in (
        ("LOCALAPPDATA", Path("Programs")),
        ("ProgramFiles", Path()),
        ("ProgramFiles(x86)", Path()),
    ):
        root = os.environ.get(variable)
        if not root:
            continue
        for version in (7, 6):
            compiler = Path(root) / suffix / f"Inno Setup {version}" / "ISCC.exe"
            if compiler.is_file():
                return compiler.resolve()
    raise FileNotFoundError("Install Inno Setup, or provide --iscc <path to ISCC.exe>.")


def release_version(version: str) -> str:
    parsed = Version(version)
    result = parsed.base_version
    if parsed.pre:
        kind, number = parsed.pre
        result += f"-{'beta' if kind == 'b' else kind}.{number}"
    return result


def compile_installer(bundle: Path, compiler: Path) -> Path:
    """Compile the entire frozen directory, then write its checksum."""
    info = json.loads((bundle / "BUILD-INFO.json").read_text(encoding="utf-8"))
    version = release_version(info["version"])
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    installer = output / f"LinkForge-v{version}-windows-x64-setup.exe"
    # Avoid mistaking an old output for a successful new compile.
    installer.unlink(missing_ok=True)
    installer.with_suffix(".exe.sha256").unlink(missing_ok=True)
    subprocess.run(
        [
            str(compiler),
            f"/DBundleDir={bundle.resolve()}",
            f"/DReleaseVersion={version}",
            f"/DOutputPath={output}",
            str(ROOT / "build-support/windows/LinkForge.iss"),
        ],
        check=True,
        cwd=ROOT,
    )
    with installer.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    installer.with_suffix(".exe.sha256").write_text(f"{digest}  {installer.name}\n", encoding="ascii")
    return installer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iscc", type=Path, help="Explicit path to Inno Setup's ISCC.exe")
    arguments = parser.parse_args()
    compiler = find_compiler(arguments.iscc)
    bundle = build_windows()
    print(f"Installer: {compile_installer(bundle, compiler)}")


if __name__ == "__main__":
    main()
