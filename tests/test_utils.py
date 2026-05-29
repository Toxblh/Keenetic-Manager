import pytest
import netifaces
from unittest.mock import patch

from src.helpers.utils import clear_container


def test_clear_container_removes_all_children():
    """clear_container удаляет все дочерние элементы."""
    removed = []

    child2 = type('Child', (), {
        'name': 'c2',
        'get_next_sibling': lambda self: None,
    })()
    child1 = type('Child', (), {
        'name': 'c1',
        'get_next_sibling': lambda self: child2,
    })()

    container = type('Container', (), {
        'get_first_child': lambda self: child1,
        'remove': lambda self, child: removed.append(child),
    })()

    clear_container(container)

    assert len(removed) == 2
    assert removed[0].name == 'c1'
    assert removed[1].name == 'c2'


def test_clear_container_empty_container():
    """clear_container корректно работает с пустым контейнером."""
    class MockContainer:
        def get_first_child(self):
            return None
        def remove(self, *a):
            pass

    c = MockContainer()
    clear_container(c)  # should not raise


def test_get_local_mac_addresses():
    """get_local_mac_addresses возвращает MAC-адреса всех интерфейсов."""
    from src.helpers.utils import get_local_mac_addresses

    mock_interfaces = ["lo0", "en0", "en1"]
    mock_addrs = {
        "lo0": {netifaces.AF_LINK: [{"addr": "00:00:00:00:00:00"}]},
        "en0": {netifaces.AF_LINK: [{"addr": "AA:BB:CC:DD:EE:FF"}]},
        "en1": {netifaces.AF_LINK: [{"addr": "11:22:33:44:55:66"}]},
    }

    with patch('netifaces.interfaces', return_value=mock_interfaces):
        with patch('netifaces.ifaddresses', side_effect=lambda x: mock_addrs[x]):
            macs = get_local_mac_addresses()

    assert len(macs) == 3
    assert "00:00:00:00:00:00" in macs
    assert "aa:bb:cc:dd:ee:ff" in macs
    assert "11:22:33:44:55:66" in macs


def test_get_local_mac_addresses_filter_none_addrs():
    """get_local_mac_addresses фильтрует интерфейсы без MAC."""
    from src.helpers.utils import get_local_mac_addresses

    mock_interfaces = ["eth0", "tun0"]
    mock_addrs = {
        "eth0": {netifaces.AF_LINK: [{"addr": "AB:CD:EF:01:23:45"}]},
        "tun0": {netifaces.AF_LINK: [{"addr": None}]},
    }

    with patch('netifaces.interfaces', return_value=mock_interfaces):
        with patch('netifaces.ifaddresses', side_effect=lambda x: mock_addrs[x]):
            macs = get_local_mac_addresses()

    assert macs == ["ab:cd:ef:01:23:45"]
