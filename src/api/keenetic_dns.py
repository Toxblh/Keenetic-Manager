"""
DNS Routes management for Keenetic-Manager.
Handles creation, deletion, and sync of domain-based routing rules (KeeneticOS 5+).

Object-group naming convention:
  Prefix: rt_
  Description format: {slug}*{interface}*{date}*{batch}
  Example description: youtube*Wireguard1*240726*1

The description encodes all metadata needed to manage the list:
  - slug: v2fly domain list name
  - interface: VPN interface to route through (e.g. Wireguard1)
  - date: last sync date in DDMMYY format
  - batch: batch number (1, 2, 3...) for lists split across multiple groups
"""

import re
import json
from datetime import datetime
from typing import Optional, Any

DOMAIN_LIMIT = 300
GROUP_PREFIX = "rt_"
# Groups with this prefix are managed by us. We also display ALL other groups
# but with limited edit capabilities.


class DnsRouteGroup:
    """Represents a single DNS route group on the router."""
    def __init__(self, name: str, description: str = "", domains: list[str] = None,
                 interface: str = "", slug: str = "", date: str = "", batch: int = 1,
                 enabled: bool = True, source: str = "manual", route_index: str = ""):
        self.name = name                    # object-group fqdn name (e.g. rt_0)
        self.description = description      # raw description from router
        self.domains = domains or []        # list of domain strings
        self.interface = interface          # VPN interface (e.g. Wireguard1)
        self.slug = slug                    # v2fly slug or manual name
        self.date = date                    # DDMMYY sync date
        self.batch = batch                  # batch number within split group
        self.enabled = enabled              # route is active
        self.source = source                # "v2fly" or "manual"
        self.route_index = route_index      # RCI route index (for toggle)

    @property
    def display_name(self) -> str:
        """Human-readable name for UI."""
        return self.slug or self.name

    @property
    def is_outdated(self) -> bool:
        """Check if the sync date is older than yesterday."""
        if not self.date or len(self.date) != 6:
            return True
        # Consider outdated if date is not today
        today = datetime.now().strftime("%d%m%y")
        return self.date != today

    def encode_description(self) -> str:
        """Encode metadata into description string.
        v2fly lists: v2fly:{slug}*{iface}*{date}*{batch}
        manual lists: {name}*{iface}*{date}*{batch}"""
        prefix = "v2fly:" if self.source == "v2fly" else ""
        return f"{prefix}{self.slug}*{self.interface}*{self.date}*{self.batch}"

    @staticmethod
    def parse_description(desc: str) -> dict:
        """Parse encoded metadata from description string."""
        result = {"slug": "", "interface": "", "date": "", "batch": 1, "source": "manual"}
        d = desc
        if d.startswith("v2fly:"):
            result["source"] = "v2fly"
            d = d[6:]
        parts = d.split("*")
        if len(parts) >= 1:
            result["slug"] = parts[0].strip()
        if len(parts) >= 2:
            result["interface"] = parts[1].strip()
        if len(parts) >= 3:
            result["date"] = parts[2].strip()
        if len(parts) >= 4:
            try:
                result["batch"] = int(parts[3].strip())
            except ValueError:
                result["batch"] = 1
        return result

    @staticmethod
    def is_managed(description: str) -> bool:
        """Check if a description follows our encoding format (with or without v2fly: prefix)."""
        if not description:
            return False
        d = description[6:] if description.startswith("v2fly:") else description
        return "*" in d and len(d.split("*")) >= 3

    @staticmethod
    def is_v2fly(description: str) -> bool:
        """Check if a managed group is from v2fly (has v2fly: prefix)."""
        return description.startswith("v2fly:")


class DnsRoutesManager:
    """Manages DNS-based routing on a Keenetic router via RCI API."""

    def __init__(self, router):
        """Initialize with a KeeneticRouter instance."""
        print(f"[dns] DnsRoutesManager init: base_url={router.base_url}")
        self.router = router
        self._groups_cache = None
        # Ensure authenticated
        try:
            ok = router.login()
            print(f"[dns] login result: {ok}")
        except Exception as e:
            print(f"[dns] Auth check error: {e}")

    def _rci_post(self, endpoint: str, data=None, log_first: bool = True):
        """Send POST request to RCI API."""
        if log_first:
            req = json.dumps(data)[:120] if data else "<no data>"
            print(f"[dns] POST {endpoint} {req}...")
        resp = self.router.keen_request(endpoint, data)
        if resp is None:
            raise ConnectionError(f"No response from router for {endpoint}")
        if resp.status_code != 200:
            raise RuntimeError(f"RCI error {resp.status_code} for {endpoint}: {resp.text[:200]}")
        if log_first:
            print(f"[dns] POST {endpoint} -> {resp.status_code}")
        return resp

    def _rci_batch_show(self, commands: list[dict]) -> list:
        """Send multiple 'show' commands in one POST to /rci/.
        Each command is a dict like {"show": {"sc": {"object-group": {"fqdn": {}}}}}.
        Returns raw parsed response (might be list or dict depending on API version)."""
        resp = self._rci_post("rci/", commands, log_first=False)
        data = resp.json()
        if isinstance(data, list):
            print(f"[dns] batch_show: {len(commands)} commands -> list[{len(data)}]")
        elif isinstance(data, dict):
            print(f"[dns] batch_show: {len(commands)} commands -> dict[{len(data)} keys]")
        return data

    def fetch_all_route_data(self) -> dict[str, Any]:
        """Fetch all data needed for the Routes page in a single POST.
        Returns {'groups': dict, 'routes': list, 'interfaces': dict}."""
        print("[dns] fetch_all_route_data START (single POST)")
        try:
            data = self._rci_batch_show([
                {"show": {"sc": {"object-group": {"fqdn": {}}}}},
                {"show": {"sc": {"dns-proxy": {"route": {}}}}},  # config has disable field
                {"show": {"interface": {"details": "yes", "trait": "Ip"}}},
            ])
        except Exception as e:
            print(f"[dns] fetch_all_route_data FAILED: {e}, falling back to individual requests")
            return self._fallback_fetch()

        groups_data = {}
        routes_data = []
        interfaces_data = {}

        # Response may be a list (one element per command) or merged dict
        if isinstance(data, list):
            for i, entry in enumerate(data):
                if i == 0:
                    # show sc object-group fqdn
                    sc = entry.get("show", {}).get("sc", {}).get("object-group", {}).get("fqdn", {})
                    groups_data = sc if isinstance(sc, dict) else {}
                elif i == 1:
                    # show sc dns-proxy route (config, has disable field)
                    routes_data = entry.get("show", {}).get("sc", {}).get("dns-proxy", {}).get("route", [])
                elif i == 2:
                    # show interface details=yes trait=Ip
                    interfaces_data = entry.get("show", {}).get("interface", {})
                    if not isinstance(interfaces_data, dict):
                        interfaces_data = {}
        elif isinstance(data, dict):
            # Merged response - try common patterns
            # Check for nested structure
            if "sc" in data:
                sc = data["sc"]
                groups_data = sc.get("object-group", {}).get("fqdn", {})
            if "object-group" in data:
                groups_data = data.get("object-group", {}).get("fqdn", {})
            if "dns-proxy" in data:
                routes_data = data.get("dns-proxy", {}).get("route", [])
            if "interface" in data and isinstance(data.get("interface"), dict):
                # Check if it's the detailed view
                ifaces = data["interface"]
                if any(isinstance(v, dict) and "connected" in v for v in ifaces.values()):
                    interfaces_data = ifaces
            # Last resort: try extracting from top-level keys
            if not groups_data:
                # Try to find fqdn groups at any level
                for key in data:
                    if isinstance(data[key], dict) and "include" in str(data[key].keys()):
                        groups_data = data
                        break

        result = {
            "groups": groups_data,
            "routes": routes_data if isinstance(routes_data, list) else [],
            "interfaces": interfaces_data if isinstance(interfaces_data, dict) else {},
        }
        print(f"[dns] fetch_all_route_data OK: groups={len(result['groups'])} keys, "
              f"routes={len(result['routes'])} items, ifaces={len(result['interfaces'])} keys")
        return result

    def _fallback_fetch(self) -> dict[str, Any]:
        """Fall back to individual GET requests when batch fails."""
        print("[dns] _fallback_fetch: using individual GETs")
        try:
            groups = self._rci_get_json("rci/object-group/fqdn")
        except:
            groups = {}
        try:
            routes = self._rci_get_json("rci/dns-proxy/route")
        except:
            routes = []
        try:
            interfaces = self._rci_get_json("rci/show/interface")
        except:
            interfaces = {}
        return {
            "groups": groups if isinstance(groups, dict) else {},
            "routes": routes if isinstance(routes, list) else [],
            "interfaces": interfaces if isinstance(interfaces, dict) else {},
        }

    def _rci_get(self, endpoint: str):
        """Send GET request to RCI API. Returns response on success, logs and returns None on failure."""
        print(f"[dns_routes] GET {endpoint}...")
        resp = self.router.keen_request(endpoint)
        if resp is None:
            print(f"[dns_routes] No response for {endpoint}")
            return None
        print(f"[dns_routes] GET {endpoint} -> {resp.status_code}")
        if resp.status_code != 200:
            print(f"[dns_routes] RCI {resp.status_code} for {endpoint}: {resp.text[:100]}")
            return None
        return resp

    def _rci_get_json(self, endpoint: str):
        """GET request returning parsed JSON, or empty dict/list on failure."""
        print(f"[dns] _rci_get_json START: {endpoint}")
        resp = self._rci_get(endpoint)
        if resp is None:
            print(f"[dns] _rci_get_json FAIL: {endpoint} - no response")
            return {}
        try:
            data = resp.json()
            t = type(data).__name__
            if isinstance(data, list):
                print(f"[dns] _rci_get_json OK: {endpoint} -> {t}[{len(data)}]")
            elif isinstance(data, dict):
                print(f"[dns] _rci_get_json OK: {endpoint} -> {t}[{len(data)} keys]")
            else:
                print(f"[dns] _rci_get_json OK: {endpoint} -> {t}")
            return data
        except Exception as e:
            print(f"[dns] _rci_get_json JSON parse error for {endpoint}: {e}")
            # Log raw response
            print(f"[dns] Raw (first 500): {resp.text[:500]}")
            return {}

    def _parse_batch(self, commands: list[str]):
        """Execute multiple CLI commands in one HTTP request via /rci/ batch endpoint.
        Each command is sent as {"parse": "command string"}.
        Automatically appends 'system configuration save' at the end."""
        payload = [{"parse": cmd} for cmd in commands]
        payload.append({"parse": "system configuration save"})
        self._send_batch(payload)

    def _rci_raw_batch(self, payload: list[dict]):
        """Send raw RCI JSON objects (not wrapped in parse). 
        Automatically appends system configuration save."""
        payload_with_save = list(payload)
        payload_with_save.append({"system": {"configuration": {"save": {}}}})
        self._send_batch(payload_with_save)

    def _send_batch(self, payload: list[dict]):
        """Send payload in batches of 50 to /rci/."""
        batch_size = 50
        for i in range(0, len(payload), batch_size):
            batch = payload[i:i + batch_size]
            resp = self._rci_post("rci/", batch)
            # Check for errors in response
            try:
                results = resp.json()
                for entry in results:
                    for status in entry.get("parse", {}).get("status", []):
                        if status.get("status") == "error":
                            print(f"[dns_routes] RCI error: {status.get('message', 'unknown')} "
                                  f"(code={status.get('code')}, ident={status.get('ident')})")
            except (ValueError, KeyError):
                pass

    def get_vpn_interfaces(self, data: dict = None) -> list[dict]:
        """Get available VPN/WireGuard interfaces.
        Optionally accepts pre-fetched data to avoid extra requests."""
        if data is None:
            try:
                data = self._rci_get_json("rci/show/interface")
            except Exception as e:
                print(f"[dns] Failed to get interfaces: {e}")
                return []

        if not isinstance(data, dict):
            return []

        print(f"[dns] show/interface: {len(data)} entries")
        interfaces = []
        for name, info in data.items():
            if not isinstance(info, dict):
                continue
            iface_type = info.get("type", "")
            if "Wireguard" in iface_type or "OpenVPN" in iface_type or "L2TP" in iface_type or \
               "PPTP" in iface_type or "SSTP" in iface_type or "IPsec" in iface_type:
                id_val = info.get("interface-name", name)
                desc = info.get("description", "")
                connected = info.get("connected") == "yes"
                print(f"[dns] VPN iface: id={id_val}, desc='{desc}', connected={connected}, type={iface_type}")
                interfaces.append({
                    "id": id_val,
                    "description": desc,
                    "connected": connected,
                    "type": iface_type,
                })
        return interfaces

    def get_groups(self, groups_data: dict = None, routes_data: list = None) -> list[DnsRouteGroup]:
        """Get all DNS route groups from the router.
        Optionally accepts pre-fetched data to avoid extra requests."""
        print("[dns] get_groups START")
        try:
            if groups_data is None:
                print("[dns] get_groups: fetching object-group/fqdn...")
                groups_data = self._rci_get_json("rci/object-group/fqdn")
            print(f"[dns] get_groups: groups_data type={type(groups_data).__name__}")
            
            if routes_data is None:
                print("[dns] get_groups: fetching dns-proxy/route...")
                routes_data = self._rci_get_json("rci/dns-proxy/route")
            print(f"[dns] get_groups: routes_data type={type(routes_data).__name__}")
        except Exception as e:
            print(f"[dns] get_groups EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            return []

        # Ensure routes_data is a list
        if not isinstance(routes_data, list):
            print(f"[dns] get_groups: routes_data not a list, converting from {type(routes_data).__name__}")
            routes_data = []
        if not isinstance(groups_data, dict):
            print(f"[dns] get_groups: groups_data not a dict, converting from {type(groups_data).__name__}")
            groups_data = {}

        print(f"[dns] get_groups: {len(groups_data)} group(s), {len(routes_data)} route(s)")

        # Build route map: group_name -> {interface, enabled, index}
        route_map = {}
        for route in routes_data:
            group_name = route.get("group", "")
            route_map[group_name] = {
                "interface": route.get("interface", ""),
                "enabled": not route.get("disable", False),
                "index": route.get("index", ""),
            }

        # Build groups
        groups = []
        for group_name, group_info in groups_data.items():
            if not isinstance(group_info, dict):
                continue

            desc = group_info.get("description", "")
            includes = group_info.get("include", [])
            domains = [entry.get("address", "") for entry in includes if entry.get("address")]

            route_info = route_map.get(group_name, {})
            interface = route_info.get("interface", "")
            enabled = route_info.get("enabled", True)
            route_index = route_info.get("index", "")

            if DnsRouteGroup.is_managed(desc):
                meta = DnsRouteGroup.parse_description(desc)
                group = DnsRouteGroup(
                    name=group_name,
                    description=desc,
                    domains=domains,
                    interface=meta["interface"] or interface,
                    slug=meta["slug"],
                    date=meta["date"],
                    batch=meta["batch"],
                    enabled=enabled,
                    source=meta.get("source", "manual"),
                    route_index=route_index,
                )
            else:
                # Legacy or unmanaged group
                group = DnsRouteGroup(
                    name=group_name,
                    description=desc,
                    domains=domains,
                    interface=interface,
                    slug=desc or group_name,
                    enabled=enabled,
                    route_index=route_index,
                )
            groups.append(group)

        return groups

    def get_grouped_by_slug(self) -> dict[str, list[DnsRouteGroup]]:
        """Get groups organized by slug for UI display.
        Returns {slug: [DnsRouteGroup, ...]} with batches sorted."""
        groups = self.get_groups()
        return self._group_by_slug(groups)

    def get_grouped_by_slug_cached(self, groups_data: dict = None, routes_data: list = None) -> dict[str, list[DnsRouteGroup]]:
        """Same as get_grouped_by_slug but uses pre-fetched data."""
        groups = self.get_groups(groups_data=groups_data, routes_data=routes_data)
        return self._group_by_slug(groups)

    def _group_by_slug(self, groups: list[DnsRouteGroup]) -> dict[str, list[DnsRouteGroup]]:
        """Organize groups by slug, batches sorted."""
        result = {}
        for g in groups:
            slug = g.slug or g.name
            if slug not in result:
                result[slug] = []
            result[slug].append(g)
        for slug in result:
            result[slug].sort(key=lambda g: g.batch)
        return result

    def validate_and_repair(self) -> dict[str, str]:
        """Validate managed groups against actual routes, repair if needed."""
        groups = self.get_groups()
        routes_data = self._rci_get_json("rci/dns-proxy/route")
        if not isinstance(routes_data, list):
            routes_data = []
        return self._validate(groups, routes_data)

    def validate_and_repair_cached(self, groups_data: dict, routes_data: list) -> dict[str, str]:
        """Validate using pre-fetched data (no extra requests)."""
        groups = self.get_groups(groups_data=groups_data, routes_data=routes_data)
        if not isinstance(routes_data, list):
            routes_data = []
        return self._validate(groups, routes_data)

    def _validate(self, groups: list[DnsRouteGroup], routes_data: list) -> dict[str, str]:
        """Validate managed groups against actual routes, repair if needed.
        Returns {group_name: status_message} where status_message is:
          'ok' - all good
          'repaired: route_name via iface' - route was missing, created now
          'updated: old_iface → new_iface' - interface changed, metadata updated
          'no_interface' - no interface stored
        """
        if not isinstance(routes_data, list):
            routes_data = []

        route_map: dict[str, list[dict]] = {}
        for r in routes_data:
            gname = r.get("group", "")
            if gname not in route_map:
                route_map[gname] = []
            route_map[gname].append({
                "interface": r.get("interface", ""),
                "index": r.get("index", ""),
                "disabled": r.get("disable", False),
            })

        statuses = {}

        for group in groups:
            if not DnsRouteGroup.is_managed(group.description):
                statuses[group.name] = "ok"
                continue

            routes = route_map.get(group.name, [])
            stored_iface = group.interface

            if not routes:
                # No route at all - repair: create one
                if stored_iface:
                    print(f"[dns] validate: {group.name} missing route, repairing -> {stored_iface}")
                    try:
                        self._set_route(group.name, stored_iface)
                        statuses[group.name] = f"repaired: → {stored_iface}"
                    except Exception as e:
                        print(f"[dns] validate: repair failed for {group.name}: {e}")
                        statuses[group.name] = "error"
                else:
                    statuses[group.name] = "no_interface"

            elif len(routes) > 1:
                # Multiple routes — delete only non-matching ones, keep the correct one
                wrong_routes = [r for r in routes if r["interface"] != stored_iface]
                matching = [r for r in routes if r["interface"] == stored_iface]
                if wrong_routes and matching:
                    # Delete non-matching routes using group+interface (web UI format)
                    print(f"[dns] validate: {group.name} has {len(routes)} routes, "
                          f"removing {len(wrong_routes)} non-matching")
                    try:
                        payload = [{"dns-proxy": {"route": {
                            "group": group.name, "interface": r["interface"], "no": True
                        }}} for r in wrong_routes]
                        self._rci_raw_batch(payload)
                        statuses[group.name] = f"repaired: → {stored_iface} (cleaned {len(wrong_routes)} dups)"
                    except Exception as e:
                        print(f"[dns] validate: failed to clean dups for {group.name}: {e}")
                        statuses[group.name] = "error"
                elif not matching and stored_iface:
                    # No matching route — delete all, create correct
                    print(f"[dns] validate: {group.name} has {len(routes)} routes, none match {stored_iface}, repairing")
                    try:
                        payload = [{"dns-proxy": {"route": {
                            "group": group.name, "interface": r["interface"], "no": True
                        }}} for r in routes if r.get("interface")]
                        payload.append({"dns-proxy": {"route": {
                            "group": group.name, "interface": stored_iface, "auto": True
                        }}})
                        self._rci_raw_batch(payload)
                        statuses[group.name] = f"repaired: → {stored_iface}"
                    except Exception as e:
                        print(f"[dns] validate: repair failed for {group.name}: {e}")
                        statuses[group.name] = "error"
                else:
                    statuses[group.name] = "ok"

            else:
                # Exactly one route
                current_route = routes[0]
                current_route_iface = current_route["interface"]

                if current_route_iface != stored_iface:
                    # Interface mismatch — update metadata to match reality OR fix the route
                    print(f"[dns] validate: {group.name} iface changed {stored_iface} -> {current_route_iface}, updating metadata")
                    prefix = "v2fly:" if DnsRouteGroup.is_v2fly(group.description) else ""
                    new_desc = f"{prefix}{group.slug}*{current_route_iface}*{group.date}*{group.batch}"
                    try:
                        self._parse_batch([
                            f"object-group fqdn {group.name} description \"{new_desc}\""
                        ])
                        statuses[group.name] = f"updated: {stored_iface} → {current_route_iface}"
                    except Exception as e:
                        print(f"[dns] validate: metadata update failed for {group.name}: {e}")
                        statuses[group.name] = "error"
                else:
                    statuses[group.name] = "ok"

        print(f"[dns] validate: {statuses}")
        return statuses

    def _set_route(self, group_name: str, interface: str, old_routes: list[dict] = None):
        """Ensure exactly one dns-proxy route exists for a group.
        Deletes existing routes by group+interface, then creates the correct one."""
        print(f"[dns] _set_route: {group_name} -> {interface}")
        payload = []
        if old_routes:
            for r in old_routes:
                payload.append({"dns-proxy": {"route": {
                    "group": group_name, "interface": r.get("interface", ""), "no": True
                }}})
        payload.append({"dns-proxy": {"route": {
            "group": group_name, "interface": interface, "auto": True
        }}})
        self._rci_raw_batch(payload)

    def _remove_route(self, group_name: str):
        """Remove all dns-proxy routes for a group via raw JSON."""
        self._rci_raw_batch([
            {"dns-proxy": {"route": {"group": group_name, "no": True}}}
        ])

    def create_group(self, slug: str, domains: list[str], interface: str,
                     date: str = None, batch: int = 1, batch_total: int = 1) -> str:
        """Create a new DNS route group.
        Returns the generated group name."""
        if date is None:
            date = datetime.now().strftime("%d%m%y")

        # Find next available index
        existing = self.get_groups()
        used_indices = set()
        for g in existing:
            if g.name.startswith(GROUP_PREFIX):
                try:
                    used_indices.add(int(g.name[len(GROUP_PREFIX):]))
                except ValueError:
                    pass
        idx = 0
        while idx in used_indices:
            idx += 1
        group_name = f"{GROUP_PREFIX}{idx}"

        # Encode metadata in description
        desc = f"v2fly:{slug}*{interface}*{date}*{batch}"

        # Build commands
        commands = [
            f"object-group fqdn {group_name}",
            f"object-group fqdn {group_name} description \"{desc}\"",
        ]
        for domain in domains[:DOMAIN_LIMIT]:
            commands.append(f"object-group fqdn {group_name} include {domain}")

        # Add route (set, not add - avoids duplicates)
        commands.append(f"no dns-proxy route object-group {group_name}")
        commands.append(f"dns-proxy route object-group {group_name} {interface} auto")

        self._parse_batch(commands)
        return group_name

    def update_group_domains(self, group_name: str, domains: list[str], description: str = None):
        """Replace all domains in an existing group using raw JSON (fast).
        Optionally update description at the same time."""
        if len(domains) > DOMAIN_LIMIT:
            raise ValueError(f"Too many domains ({len(domains)}), max {DOMAIN_LIMIT}")

        payload = [
            # Clear existing domains
            {"object-group": {"fqdn": {group_name: {"include": {"no": True}}}}},
        ]
        # Build new group data
        group_data: dict[str, Any] = {
            "include": [{"address": d} for d in domains],
        }
        if description:
            group_data["description"] = description
        payload.append({"object-group": {"fqdn": {group_name: group_data}}})
        self._rci_raw_batch(payload)

    def update_group_interface(self, group_name: str, new_interface: str):
        """Change the VPN interface for a group. Updates both the route and description."""
        # Get current group info
        groups = self.get_groups()
        current = None
        for g in groups:
            if g.name == group_name:
                current = g
                break
        if not current:
            raise ValueError(f"Group {group_name} not found")

        # Update description with new interface, then set (not add) route
        prefix = "v2fly:" if current.source == "v2fly" else ""
        new_desc = f"{prefix}{current.slug}*{new_interface}*{current.date}*{current.batch}"

        commands = [
            f"object-group fqdn {group_name} description \"{new_desc}\"",
            f"no dns-proxy route object-group {group_name}",
            f"dns-proxy route object-group {group_name} {new_interface} auto",
        ]
        self._parse_batch(commands)

    def delete_group(self, group_name: str):
        """Delete a DNS route group and its route (no extra requests)."""
        commands = [
            f"no dns-proxy route object-group {group_name}",
            f"no object-group fqdn {group_name}",
        ]
        self._parse_batch(commands)

    def create_group(self, slug: str, domains: list[str], interface: str,
                     date: str = None, batch: int = 1, batch_total: int = 1,
                     existing_names: set[str] = None) -> str:
        """Create a new DNS route group. Optionally pass existing_names to skip re-fetching."""
        if date is None:
            date = datetime.now().strftime("%d%m%y")

        # Find next available index
        if existing_names is None:
            existing = self.get_groups()
            existing_names = set(g.name for g in existing)
        idx = 0
        while f"{GROUP_PREFIX}{idx}" in existing_names:
            idx += 1
        group_name = f"{GROUP_PREFIX}{idx}"
        existing_names.add(group_name)  # Reserve for subsequent batches

        # Encode metadata in description
        desc = f"v2fly:{slug}*{interface}*{date}*{batch}"

        # Build commands
        commands = [
            f"object-group fqdn {group_name}",
            f"object-group fqdn {group_name} description \"{desc}\"",
        ]
        for domain in domains[:DOMAIN_LIMIT]:
            commands.append(f"object-group fqdn {group_name} include {domain}")

        # Add route (set, not add - avoids duplicates)
        commands.append(f"no dns-proxy route object-group {group_name}")
        commands.append(f"dns-proxy route object-group {group_name} {interface} auto")

        self._parse_batch(commands)
        return group_name

    def toggle_route(self, group_name: str, enable: bool):
        """Enable or disable a DNS route via RCI disable API."""
        # Find the route index
        routes_data = self._rci_get_json("rci/dns-proxy/route")
        if not isinstance(routes_data, list):
            routes_data = []

        route_index = None
        for r in routes_data:
            if r.get("group") == group_name:
                route_index = r.get("index", "")
                break

        if not route_index:
            raise ValueError(f"No route index found for {group_name}")

        # Use raw RCI JSON (not CLI parse) for disable/enable
        self._rci_raw_batch([
            {"dns-proxy": {"route": {"disable": {"index": route_index, "no": enable}}}}
        ])

    def sync_list(self, slug: str, interface: str,
                  existing_groups_for_slug: list = None,
                  all_existing_names: set[str] = None) -> list[str]:
        """Sync a v2fly domain list: download, compare, update only what changed.
        Pass existing_groups_for_slug and all_existing_names to avoid re-fetching.
        Returns list of group names."""
        from .v2fly import fetch_domain_list

        domains, _ = fetch_domain_list(slug)
        today = datetime.now().strftime("%d%m%y")

        # Split into chunks of DOMAIN_LIMIT
        chunks = [domains[i:i + DOMAIN_LIMIT] for i in range(0, len(domains), DOMAIN_LIMIT)]

        # Get existing groups, sorted by batch
        if existing_groups_for_slug is None:
            existing_groups_for_slug = self.get_grouped_by_slug().get(slug, [])
        existing_sorted = sorted(existing_groups_for_slug, key=lambda g: g.batch)

        if all_existing_names is None:
            all_existing_names = set()
            grouped = self.get_grouped_by_slug()
            for gs in grouped.values():
                for g in gs:
                    all_existing_names.add(g.name)

        updated = []

        # Update existing groups, create new ones if needed
        for i, chunk in enumerate(chunks):
            batch_num = i + 1
            if i < len(existing_sorted):
                existing = existing_sorted[i]
                new_set = set(chunk)
                old_set = set(existing.domains)
                if new_set == old_set:
                    # Unchanged — just update date in description
                    print(f"[dns] sync {slug} batch {batch_num}: unchanged, updating date")
                    new_desc = f"v2fly:{slug}*{interface}*{today}*{batch_num}"
                    self._parse_batch([
                        f"object-group fqdn {existing.name} description \"{new_desc}\""
                    ])
                    updated.append(existing.name)
                else:
                    # Changed — update domains + description in one raw JSON call
                    added = new_set - old_set
                    removed = old_set - new_set
                    new_desc = f"v2fly:{slug}*{interface}*{today}*{batch_num}"
                    print(f"[dns] sync {slug} batch {batch_num}: changed (+{len(added)} -{len(removed)}), updating")
                    self.update_group_domains(existing.name, chunk, description=new_desc)
                    updated.append(existing.name)
            else:
                # New batch needed (domains grew)
                print(f"[dns] sync {slug} batch {batch_num}: new batch, creating")
                name = self.create_group(
                    slug=slug, domains=chunk, interface=interface,
                    date=today, batch=batch_num, batch_total=len(chunks),
                    existing_names=all_existing_names,
                )
                updated.append(name)

        # Delete excess old groups (domains shrunk)
        for i in range(len(chunks), len(existing_sorted)):
            old = existing_sorted[i]
            print(f"[dns] sync {slug} batch {old.batch}: excess, deleting {old.name}")
            try:
                self.delete_group(old.name)
            except Exception as e:
                print(f"[dns_routes] Failed to delete excess {old.name}: {e}")

        return updated
