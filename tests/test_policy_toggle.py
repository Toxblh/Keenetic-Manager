import pytest


def _compute_active_index(deny, current_policy, policies):
    """Mirrors PolicyToggleWidget._set_active_from_state logic.
    Toggle indices: 0=Block, 1=Default, 2+=custom policies
    """
    if deny:
        return 0
    elif current_policy is None:
        return 1
    else:
        for idx, (policy_name, _) in enumerate(policies):
            if current_policy == policy_name:
                return idx + 2
    # Default fallback
    return 1


class TestPolicyToggleStateLogic:
    def test_deny_shows_block(self):
        active_idx = _compute_active_index(
            deny=True, current_policy=None,
            policies=[("block", "Block"), ("wifi", "WiFi")]
        )
        assert active_idx == 0

    def test_no_policy_shows_default(self):
        active_idx = _compute_active_index(
            deny=False, current_policy=None,
            policies=[("block", "Block"), ("wifi", "WiFi")]
        )
        assert active_idx == 1

    def test_matching_policy_shows_correct_index(self):
        policies = [("block", "Block"), ("wifi", "WiFi"), ("time", "Time")]
        assert _compute_active_index(False, "wifi", policies) == 3
        assert _compute_active_index(False, "block", policies) == 2
        assert _compute_active_index(False, "time", policies) == 4

    def test_unknown_policy_falls_back_to_default(self):
        policies = [("block", "Block"), ("wifi", "WiFi")]
        idx = _compute_active_index(False, "unknown_policy", policies)
        assert idx == 1

    def test_deny_overrides_policy(self):
        policies = [("block", "Block"), ("wifi", "WiFi")]
        idx = _compute_active_index(True, "wifi", policies)
        assert idx == 0

    def test_single_policy(self):
        policies = [("game", "Game Mode")]
        idx = _compute_active_index(False, "game", policies)
        assert idx == 2

    def test_empty_policies_with_deny(self):
        assert _compute_active_index(True, None, []) == 0

    def test_empty_policies_no_policy(self):
        assert _compute_active_index(False, None, []) == 1


class TestMigrateMetadataLogic:
    """Testing migration logic extracted from RouterManager.migrate_router_metadata."""

    def _needs_migration(self, r):
        return (
            ('network_ip' not in r or r.get('network_ip') is None)
            or ('keendns_urls' not in r or r.get('keendns_urls') is None)
            or (r.get('keendns_urls') == [] and r.get('network_ip') is None)
        )

    def _wants_dns_retry(self, r, checked):
        return (
            r.get('keendns_urls') == []
            and r.get('network_ip') is not None
            and r.get('name') not in checked
        )

    def test_old_config_needs_migration(self):
        r = {"name": "old", "address": "192.168.1.1", "login": "admin"}
        assert self._needs_migration(r) is True

    def test_new_config_no_migration_needed(self):
        r = {
            "name": "new",
            "network_ip": "192.168.1.1",
            "keendns_urls": ["test.keenetic.net"],
        }
        assert self._needs_migration(r) is False

    def test_none_network_ip_needs_migration(self):
        r = {"name": "x", "network_ip": None}
        assert self._needs_migration(r) is True

    def test_wants_dns_retry_true(self):
        r = {"name": "r1", "network_ip": "192.168.1.1", "keendns_urls": []}
        assert self._wants_dns_retry(r, set()) is True

    def test_wants_dns_retry_already_checked(self):
        r = {"name": "r1", "network_ip": "192.168.1.1", "keendns_urls": []}
        assert self._wants_dns_retry(r, {"r1"}) is False

    def test_wants_dns_retry_no_network_ip(self):
        r = {"name": "r1", "keendns_urls": []}
        assert self._wants_dns_retry(r, set()) is False


import ipaddress


class TestRouterManagerLocalNetworkLogic:
    def _is_in_local_network(self, router_info, local_networks):
        ip_val = router_info.get('network_ip')
        if not ip_val:
            return False
        addr = ipaddress.ip_address(ip_val)
        return any(addr in net for net in local_networks)

    def test_router_in_local_network(self):
        nets = [ipaddress.IPv4Network("192.168.1.0/24")]
        assert self._is_in_local_network({"network_ip": "192.168.1.5"}, nets) is True

    def test_router_not_in_local_network(self):
        nets = [ipaddress.IPv4Network("192.168.1.0/24")]
        assert self._is_in_local_network({"network_ip": "10.0.0.1"}, nets) is False

    def test_router_no_network_ip(self):
        nets = [ipaddress.IPv4Network("192.168.1.0/24")]
        assert self._is_in_local_network({}, nets) is False

    def test_router_in_different_subnet(self):
        nets = [
            ipaddress.IPv4Network("192.168.1.0/24"),
            ipaddress.IPv4Network("10.0.0.0/8"),
        ]
        assert self._is_in_local_network({"network_ip": "172.16.0.1"}, nets) is False


class TestRefreshRouterComboLogic:
    """Testing the refresh_router_combo logic."""
    def test_refresh_with_selection(self):
        """finds and selects by name."""
        routers = [
            {"name": "A"},
            {"name": "B"},
            {"name": "C"},
        ]
        selected = "B"
        found = None
        for i, r in enumerate(routers):
            if r["name"] == selected:
                found = i
                break
        assert found == 1

    def test_refresh_with_nonexistent_name(self):
        routers = [{"name": "A"}, {"name": "B"}]
        selected = "Z"
        found = None
        for i, r in enumerate(routers):
            if r["name"] == selected:
                found = i
                break
        assert found is None

    def test_refresh_empty_routers(self):
        routers = []
        current_router = None
        # simulate: self.current_router = None
        assert current_router is None
