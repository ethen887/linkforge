"""Compiler discovery and release naming independent of local Inno Setup installs."""

import pytest

from scripts.build_installer import find_compiler, release_version


def test_compiler_discovery_supports_per_user_install_with_spaces(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.build_installer.shutil.which", lambda _name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "用户目录"))
    compiler = tmp_path / "用户目录" / "Programs" / "Inno Setup 7" / "ISCC.exe"
    compiler.parent.mkdir(parents=True)
    compiler.touch()
    assert find_compiler() == compiler.resolve()


def test_compiler_discovery_supports_registry_install(monkeypatch, tmp_path):
    compiler = tmp_path / "自定义目录" / "Inno Setup 7" / "ISCC.exe"
    compiler.parent.mkdir(parents=True)
    compiler.touch()
    monkeypatch.setattr("scripts.build_installer.shutil.which", lambda _name: None)
    monkeypatch.setattr("scripts.build_installer._registry_compilers", lambda: iter((compiler,)))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "missing-user"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "missing-program"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "missing-program-x86"))
    assert find_compiler() == compiler.resolve()


def test_explicit_missing_compiler_does_not_fall_back_to_another_installation(tmp_path):
    with pytest.raises(FileNotFoundError, match="does not exist"):
        find_compiler(tmp_path / "missing.exe")


def test_missing_compiler_explains_how_to_configure_it(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.build_installer.shutil.which", lambda _name: None)
    monkeypatch.setattr("scripts.build_installer._registry_compilers", lambda: iter(()))
    for variable in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.setenv(variable, str(tmp_path))
    with pytest.raises(FileNotFoundError, match="--iscc"):
        find_compiler()


@pytest.mark.parametrize(
    ("version", "expected"), [("0.1.0b1", "0.1.0-beta.1"), ("1.2.3", "1.2.3"), ("1.0rc2", "1.0-rc.2")]
)
def test_release_names_distinguish_stable_and_prerelease(version, expected):
    assert release_version(version) == expected
