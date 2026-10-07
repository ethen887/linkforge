"""Ensure duplicate editable metadata cannot break release assembly."""

from importlib.metadata import PackagePath
from types import SimpleNamespace

from scripts.build_windows import build_environment, collect_notices


def test_duplicate_distributions_preserve_notices_without_copying_user_data(tmp_path, monkeypatch):
    metadata = tmp_path / "example-1.0.dist-info"
    metadata.mkdir()
    (metadata / "LICENSE").write_text("license text", encoding="utf-8")
    (metadata / "METADATA").write_text("Name: example", encoding="utf-8")
    secret = tmp_path / "user-data.txt"
    secret.write_text("must not be packaged", encoding="utf-8")
    distribution = SimpleNamespace(
        metadata={"Name": "example"},
        version="1.0",
        files=[
            PackagePath("example-1.0.dist-info/LICENSE"),
            PackagePath("example-1.0.dist-info/METADATA"),
            PackagePath("user-data.txt"),
        ],
        locate_file=lambda entry: tmp_path / entry,
    )
    monkeypatch.setattr(
        "scripts.build_windows.importlib.metadata.distributions", lambda: [distribution, distribution]
    )
    destination = tmp_path / "notices"
    collect_notices(destination)
    assert (destination / "example-1.0/LICENSE").read_text(encoding="utf-8") == "license text"
    assert not list(destination.rglob("user-data.txt"))


def test_build_environment_does_not_inherit_developer_dll_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path / "Windows"))
    monkeypatch.setenv("PATH", "unrelated-dlls")
    monkeypatch.setenv("PYTHONPATH", "unrelated-modules")
    monkeypatch.setenv("QT_PLUGIN_PATH", "unrelated-qt")
    monkeypatch.setenv("PLAYWRIGHT_NODEJS_PATH", "unrelated-node")
    env = build_environment()
    assert "unrelated" not in env["PATH"]
    assert "PYTHONPATH" not in env
    assert "QT_PLUGIN_PATH" not in env
    assert "PLAYWRIGHT_NODEJS_PATH" not in env
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == "0"
