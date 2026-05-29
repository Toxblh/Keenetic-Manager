import json
import pytest

from src.config import load_routers, save_routers, CONFIG_FILE, CONFIG_DIR


@pytest.fixture
def config_file(tmp_path):
    import src.config as config_mod
    # Override the module-level config file
    config_mod.CONFIG_DIR = tmp_path
    config_mod.CONFIG_FILE = tmp_path / "routers.json"
    yield config_mod.CONFIG_FILE
    # Restore
    import importlib
    importlib.reload(config_mod)


def test_load_routers_empty_file(config_file):
    json.dump([], open(config_file, 'w'))
    import src.config as config_mod
    result = config_mod.load_routers()
    assert result == []


def test_load_routers_with_routers(config_file):
    routers = [
        {"name": "router1", "address": "192.168.1.1", "login": "admin"},
        {"name": "router2", "address": "192.168.1.2", "login": "user"},
    ]
    json.dump(routers, open(config_file, 'w'))
    import src.config as config_mod
    result = config_mod.load_routers()
    assert len(result) == 2
    assert result[0]["name"] == "router1"


def test_load_routers_nonexistent_file(config_file):
    config_file.unlink(missing_ok=True)
    import src.config as config_mod
    result = config_mod.load_routers()
    assert result == []


def test_save_and_load_routers(config_file):
    routers = [
        {"name": "test", "address": "10.0.0.1", "login": "admin", "password": "secret"},
    ]
    import src.config as config_mod
    config_mod.save_routers(routers)
    loaded = config_mod.load_routers()
    assert len(loaded) == 1
    assert loaded[0]["name"] == "test"
    assert loaded[0]["address"] == "10.0.0.1"


def test_save_empty_list(config_file):
    import src.config as config_mod
    config_mod.save_routers([])
    result = config_mod.load_routers()
    assert result == []
