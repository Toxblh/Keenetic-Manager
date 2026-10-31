# Global conftest - patch _ (gettext) for all tests
import builtins

import pytest

builtins._ = lambda s: s


@pytest.fixture(autouse=True)
def isolated_v2fly_snapshots(tmp_path, monkeypatch):
    """Keep the update-check state out of the real cache directory and between tests."""
    from src.api import v2fly
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(v2fly, "_snapshots", None)
    monkeypatch.setattr(v2fly, "_failed_at", {})
