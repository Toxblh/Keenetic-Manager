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


@pytest.fixture(autouse=True)
def isolated_geodat(tmp_path, monkeypatch):
    """Keep downloaded geo files and their state out of the real cache directory."""
    from src.api import geodat
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(geodat, "_state", None)
    monkeypatch.setattr(geodat, "_failed_at", {})
    monkeypatch.setattr(geodat, "_index_cache", {})
    monkeypatch.setattr(geodat, "_count_cache", {})

    def no_network(url, timeout):
        raise AssertionError(f"unexpected download of {url}")
    monkeypatch.setattr(geodat, "_get", no_network)
