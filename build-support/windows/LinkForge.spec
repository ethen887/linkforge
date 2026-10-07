# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH).resolve().parents[1]
a = Analysis(
    [str(root / "src/linkforge/gui.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=copy_metadata("keyring"),
    hiddenimports=["keyring.backends.Windows", "keyring.backends.chainer"],
    hookspath=[],
    runtime_hooks=[str(root / "build-support/windows/runtime_hook.py")],
    excludes=["PyQt5", "PyQt6", "PySide2", "pytest"],
    noarchive=False,
)
# Reject a build contaminated by a developer machine's unrelated DLL directories.
allowed_binary_roots = [root / ".venv", Path(sys.base_prefix), Path(os.environ["SystemRoot"])]
for destination, source, kind in a.binaries:
    if not any(Path(source).resolve().is_relative_to(base.resolve()) for base in allowed_binary_roots):
        raise RuntimeError(f"Unexpected binary source outside the build environment: {source}")
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="LinkForge",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="LinkForge")
