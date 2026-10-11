"""
DNS Routes management for Keenetic-Manager.
Handles creation, deletion, and sync of domain-based routing rules (KeeneticOS 5+).

Object-group naming convention:
  Prefix: rt_
  Description format: [v2fly:]{slug}*{interface}*{date}*{batch}
  Example descriptions: v2fly:youtube*Wireguard1*240726*1, My list*Wireguard1*240726*1

The description encodes all metadata needed to manage the list:
  - v2fly: prefix marks a list downloaded from v2fly (absent for manual lists)
  - slug: v2fly domain list name, or the name of a manual list
  - interface: VPN interface to route through (e.g. Wireguard1)
  - date: last sync date in DDMMYY format
  - batch: batch number (1, 2, 3...) for lists split across multiple groups

All writes go through raw RCI JSON. The router answers HTTP 200 even when it
rejects a command, with the error buried in a "status" list somewhere in the
reply, so every reply is scanned and a rejected command raises RciError.
"""

import threading
from datetime import datetime
from typing import Any

DOMAIN_LIMIT = 300
GROUP_PREFIX = "rt_"
# Groups whose description follows the format above are managed by us. All other
# groups are displayed too, but their description is never rewritten automatically.

# Adding 300 addresses takes the router about 3 s, so writes get a longer
# timeout than reads and long include lists are split across requests.
WRITE_TIMEOUT = 30
INCLUDE_BATCH = 100
# Status code for an address the router refuses to store. The rest of the
# command is still applied, so this is reported as a warning, not a failure.
INVALID_ADDRESS_CODE = "101582220"

_router_locks: dict[str, Any] = {}
_router_locks_guard = threading.Lock()


def _lock_for(router):
    """One lock per router, shared by every manager created for it."""
    with _router_locks_guard:
        return _router_locks.setdefault(router.base_url, threading.RLock())


class RciError(RuntimeError):
    """The router was reached but rejected the request or answered unexpectedly."""


class DnsRouteGroup:
    """Represents a single DNS route group on the router."""
    def __init__(self, name: str, description: str = "", domains: list[str] = None,
                 interface: str = "", slug: str = "", date: str = "", batch: int = 1,
                 enabled: bool = True, source: str = "manual", route_index: str = "",
                 routes: list[dict] = None):
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
        self.routes = routes or []          # every dns-proxy route of this group

    @property
    def display_name(self) -> str:
        """Human-readable name for UI."""
        return self.slug or self.name

    @property
    def managed(self) -> bool:
        return DnsRouteGroup.is_managed(self.description)

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


def _encode(source: str, slug: str, interface: str, date: str, batch: int) -> str:
    return DnsRouteGroup(name="", slug=slug, interface=interface, date=date,
                         batch=batch, source=source).encode_description()


def _check_name(name: str) -> str:
    """Validate a list name before it is encoded into a '*'-delimited description."""
    name = (name or "").strip()
    if not name:
        raise ValueError(_("List name is empty."))
    if "*" in name or any(ord(c) < 32 for c in name):
        raise ValueError(_("List name must not contain '*' or control characters."))
    if name.startswith("v2fly:"):
        # The prefix is how a description marks a downloaded list
        raise ValueError(_("List name must not start with 'v2fly:'."))
    return name


def _scan_status(node, errors: list[str], warnings: list[str]):
    """Collect router status entries from an RCI reply of any shape."""
    if isinstance(node, dict):
        status = node.get("status")
        if isinstance(status, list):
            for item in status:
                if isinstance(item, dict) and item.get("status") == "error" and "message" in item:
                    target = warnings if str(item.get("code")) == INVALID_ADDRESS_CODE else errors
                    target.append(str(item["message"]))
        for value in node.values():
            _scan_status(value, errors, warnings)
    elif isinstance(node, list):
        for value in node:
            _scan_status(value, errors, warnings)


def _route_add(group: str, interface: str) -> dict:
    return {"dns-proxy": {"route": {"group": group, "interface": interface, "auto": True}}}


def _route_disable(index: str, enable: bool) -> dict:
    # A route can only be addressed reliably by its index here: given a group and
    # interface instead, the router acts on the last rule in its table.
    return {"dns-proxy": {"route": {"disable": {"index": index, "no": enable}}}}


def _route_del(group: str, interface: str) -> dict:
    return {"dns-proxy": {"route": {"group": group, "interface": interface, "no": True}}}


def _group_obj(group: str, data: dict) -> dict:
    return {"object-group": {"fqdn": {group: data}}}


class DnsRoutesManager:
    """Manages DNS-based routing on a Keenetic router via RCI API."""

    def __init__(self, router):
        """Initialize with a KeeneticRouter instance."""
        print(f"[dns] DnsRoutesManager init: base_url={router.base_url}")
        self.router = router
        self.autosave = True                # send 'system configuration save' after each operation
        self.warnings: list[str] = []       # addresses the router refused; read with pop_warnings()
        self._lock = _lock_for(router)
        # A failed login is not fatal here: the first request re-authenticates or raises.
        try:
            router.login()
        except Exception as e:
            print(f"[dns] Auth check error: {e}")

    def pop_warnings(self) -> list[str]:
        """Return and clear the warnings collected since the last call."""
        with self._lock:
            warnings, self.warnings = self.warnings, []
            return warnings

    # --- Transport ---

    def _request(self, endpoint: str, data=None, timeout: int = 5):
        """Send a request, re-authenticating once on 401. Raises unless the router answers 200."""
        resp = self.router.keen_request(endpoint, data, timeout=timeout)
        if resp is not None and resp.status_code == 401 and self.router.login():
            resp = self.router.keen_request(endpoint, data, timeout=timeout)
        if resp is None:
            raise ConnectionError(f"No response from router for {endpoint}")
        if resp.status_code != 200:
            raise RciError(f"RCI error {resp.status_code} for {endpoint}: {resp.text[:200]}")
        return resp

    def _json(self, resp, endpoint: str):
        try:
            return resp.json()
        except ValueError as e:
            raise RciError(f"Unreadable reply from router for {endpoint}: {e}")

    def _rci_get_json(self, endpoint: str):
        """GET request returning parsed JSON. Raises if the read failed."""
        return self._json(self._request(endpoint), endpoint)

    def _send(self, payload: list[dict]):
        """Send raw RCI objects to /rci/ in requests of 50.
        Raises RciError as soon as a request contains a rejected command, without
        sending the rest. Refused addresses are collected in self.warnings."""
        batch_size = 50
        for i in range(0, len(payload), batch_size):
            batch = payload[i:i + batch_size]
            results = self._json(self._request("rci/", batch, timeout=WRITE_TIMEOUT), "rci/")
            if not isinstance(results, (list, dict)):
                raise RciError(f"Unexpected reply from router: {str(results)[:200]}")
            errors: list[str] = []
            warnings: list[str] = []
            _scan_status(results, errors, warnings)
            self.warnings.extend(warnings)
            if errors:
                raise RciError("; ".join(errors[:3]))

    def _save(self):
        """Persist the running configuration."""
        if self.autosave:
            self._send([{"system": {"configuration": {"save": {}}}}])

    # --- Reading ---

    def fetch_all_route_data(self) -> dict[str, Any]:
        """Fetch all data needed for the Routes page in a single POST.
        Returns {'groups': dict, 'routes': list, 'interfaces': dict}.
        Raises if the router could not be read: a failed read is never reported as empty."""
        # "rc" is the running configuration. "sc" is the saved one: it lags behind
        # until the (asynchronous) save has finished, and so shows stale data when
        # read right after a change.
        commands = [
            {"show": {"rc": {"object-group": {"fqdn": {}}}}},
            {"show": {"rc": {"dns-proxy": {"route": {}}}}},  # config has disable field
            {"show": {"interface": {"details": "yes", "trait": "Ip"}}},
        ]
        try:
            data = self._json(self._request("rci/", commands), "rci/")
            return self._parse_show_batch(data)
        except RciError as e:
            print(f"[dns] fetch_all_route_data: batch failed ({e}), using individual requests")
            return self._fallback_fetch()

    def _parse_show_batch(self, data) -> dict[str, Any]:
        """Extract groups, routes and interfaces from the reply to fetch_all_route_data's batch."""
        if not isinstance(data, list) or len(data) != 3 or not all(isinstance(e, dict) for e in data):
            raise RciError("unexpected batch reply shape")
        errors: list[str] = []
        _scan_status(data[:2], errors, [])
        if errors:
            raise RciError("; ".join(errors[:3]))
        try:
            groups = data[0]["show"]["rc"].get("object-group", {}).get("fqdn", {})
            routes = data[1]["show"]["rc"].get("dns-proxy", {}).get("route", [])
            interfaces = data[2]["show"]["interface"]
        except (KeyError, AttributeError, TypeError):
            raise RciError("unexpected batch reply shape")
        return self._checked_state(groups, routes, interfaces)

    def _checked_state(self, groups, routes, interfaces) -> dict[str, Any]:
        """Validate the types of fetched data. An empty section is {} or []."""
        if isinstance(routes, dict) and not routes:
            routes = []
        if not isinstance(groups, dict) or not isinstance(routes, list) or not isinstance(interfaces, dict):
            raise RciError("unexpected data shape from router")
        return {"groups": groups, "routes": routes, "interfaces": interfaces}

    def _fallback_fetch(self) -> dict[str, Any]:
        """Individual GET requests, for firmware that does not answer the batch as expected."""
        return self._checked_state(
            self._rci_get_json("rci/object-group/fqdn"),
            self._rci_get_json("rci/dns-proxy/route"),
            self._rci_get_json("rci/show/interface"),
        )

    def _read_state(self) -> tuple[list[DnsRouteGroup], list[dict]]:
        """Read groups and routes fresh from the router. Raises on any failure."""
        state = self._checked_state(
            self._rci_get_json("rci/object-group/fqdn"),
            self._rci_get_json("rci/dns-proxy/route"),
            {},
        )
        return self.get_groups(state["groups"], state["routes"]), state["routes"]

    def get_vpn_interfaces(self, data: dict = None) -> list[dict]:
        """Get available VPN/WireGuard interfaces.
        Optionally accepts pre-fetched data to avoid extra requests."""
        if data is None:
            data = self._rci_get_json("rci/show/interface")

        if not isinstance(data, dict):
            return []

        interfaces = []
        for name, info in data.items():
            if not isinstance(info, dict):
                continue
            iface_type = info.get("type", "")
            if "Wireguard" in iface_type or "OpenVPN" in iface_type or "L2TP" in iface_type or \
               "PPTP" in iface_type or "SSTP" in iface_type or "IPsec" in iface_type:
                interfaces.append({
                    "id": info.get("interface-name", name),
                    "description": info.get("description", ""),
                    "connected": info.get("connected") == "yes",
                    "type": iface_type,
                })
        return interfaces

    def get_groups(self, groups_data: dict = None, routes_data: list = None) -> list[DnsRouteGroup]:
        """Get all DNS route groups from the router.
        Optionally accepts pre-fetched data to avoid extra requests.
        Raises if the router could not be read."""
        if groups_data is None or routes_data is None:
            state = self._checked_state(
                self._rci_get_json("rci/object-group/fqdn") if groups_data is None else groups_data,
                self._rci_get_json("rci/dns-proxy/route") if routes_data is None else routes_data,
                {},
            )
            groups_data, routes_data = state["groups"], state["routes"]

        # Build route map: group_name -> [{interface, enabled, index}, ...]
        route_map: dict[str, list[dict]] = {}
        for route in routes_data:
            if not isinstance(route, dict):
                continue
            route_map.setdefault(route.get("group", ""), []).append({
                "interface": route.get("interface", ""),
                "enabled": not route.get("disable", False),
                "index": route.get("index", ""),
            })

        groups = []
        for group_name, group_info in groups_data.items():
            if not isinstance(group_info, dict):
                continue

            desc = group_info.get("description", "")
            includes = group_info.get("include", [])
            domains = [entry.get("address", "") for entry in includes if entry.get("address")]
            routes = route_map.get(group_name, [])

            if DnsRouteGroup.is_managed(desc):
                meta = DnsRouteGroup.parse_description(desc)
                # Prefer the route that matches the stored interface
                route = next((r for r in routes if r["interface"] == meta["interface"]),
                             routes[0] if routes else {})
                group = DnsRouteGroup(
                    name=group_name,
                    description=desc,
                    domains=domains,
                    interface=meta["interface"] or route.get("interface", ""),
                    slug=meta["slug"],
                    date=meta["date"],
                    batch=meta["batch"],
                    enabled=route.get("enabled", True),
                    source=meta.get("source", "manual"),
                    route_index=route.get("index", ""),
                    routes=routes,
                )
            else:
                # Legacy or unmanaged group
                route = routes[0] if routes else {}
                group = DnsRouteGroup(
                    name=group_name,
                    description=desc,
                    domains=domains,
                    interface=route.get("interface", ""),
                    slug=desc or group_name,
                    enabled=route.get("enabled", True),
                    route_index=route.get("index", ""),
                    routes=routes,
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
        """Organize groups into UI rows, batches sorted.
        Only managed groups of the same source and slug are batches of one list.
        An unmanaged group is always a row of its own. When two rows would share
        a name, the later one gets a suffix so neither hides the other."""
        rows: dict[tuple, list[DnsRouteGroup]] = {}
        for g in groups:
            if g.managed:
                key = (g.source, g.slug or g.name)
            else:
                key = ("unmanaged", g.name)
            rows.setdefault(key, []).append(g)

        result = {}
        for (kind, ident), members in rows.items():
            members.sort(key=lambda g: g.batch)
            label = members[0].slug or members[0].name
            if label in result:
                label = f"{label} ({members[0].name})"
            result[label] = members
        return result

    # --- Validation / auto-repair ---

    def load_validated(self) -> tuple[dict[str, Any], dict[str, str]]:
        """Read the router, auto-repair it, and return (data, statuses).
        `data` is what fetch_all_route_data returns, read again after a repair.

        The read and the repair happen under the router lock. An operation such as
        an interface change passes through intermediate states (two routes for one
        group); repairing a snapshot taken in the middle of one would undo it."""
        with self._lock:
            data = self.fetch_all_route_data()
            groups = self.get_groups(data["groups"], data["routes"])
            statuses = self._validate(groups, data["routes"])
            if any(s not in ("ok", "no_interface") for s in statuses.values()):
                # A repair changed the router, or failed part-way: show what is there now
                data = self.fetch_all_route_data()
            return data, statuses

    def validate_and_repair(self) -> dict[str, str]:
        """Validate managed groups against actual routes, repair if needed."""
        return self.load_validated()[1]

    def _validate(self, groups: list[DnsRouteGroup], routes_data: list) -> dict[str, str]:
        """Validate managed groups against actual routes, repair if needed.
        Returns {group_name: status} where status is one of:
          'ok' - all good (also used for unmanaged groups)
          'repaired:→{iface}' - route was missing or wrong, created now
          'cleaned:{n}:→{iface}' - n duplicate routes removed
          'updated: {old} → {new}' - route points elsewhere, description updated to match
          'no_interface' - no route and no interface stored
          'error' - a repair was attempted and failed
        """
        route_map: dict[str, list[dict]] = {}
        for r in routes_data:
            gname = r.get("group", "")
            route_map.setdefault(gname, []).append({
                "interface": r.get("interface", ""),
                "index": r.get("index", ""),
                "disabled": r.get("disable", False),
            })

        statuses = {}
        changed = False

        for group in groups:
            if not group.managed:
                statuses[group.name] = "ok"
                continue

            routes = route_map.get(group.name, [])
            stored_iface = group.interface

            try:
                if not routes:
                    # No route at all - repair: create one
                    if stored_iface:
                        print(f"[dns] validate: {group.name} missing route, repairing -> {stored_iface}")
                        self._send([_route_add(group.name, stored_iface)])
                        changed = True
                        statuses[group.name] = f"repaired:→{stored_iface}"
                    else:
                        statuses[group.name] = "no_interface"

                elif len(routes) > 1:
                    # Multiple routes — delete only non-matching ones, keep the correct one
                    wrong_routes = [r for r in routes if r["interface"] != stored_iface]
                    matching = [r for r in routes if r["interface"] == stored_iface]
                    if wrong_routes and matching:
                        print(f"[dns] validate: {group.name} has {len(routes)} routes, "
                              f"removing {len(wrong_routes)} non-matching")
                        self._send([_route_del(group.name, r["interface"]) for r in wrong_routes])
                        changed = True
                        statuses[group.name] = f"cleaned:{len(wrong_routes)}:→{stored_iface}"
                    elif not matching and stored_iface:
                        # No matching route — create the correct one, then delete the rest
                        print(f"[dns] validate: {group.name} has {len(routes)} routes, none match {stored_iface}, repairing")
                        self._send([_route_add(group.name, stored_iface)])
                        self._send([_route_del(group.name, r["interface"]) for r in routes if r.get("interface")])
                        changed = True
                        statuses[group.name] = f"repaired:→{stored_iface}"
                    else:
                        statuses[group.name] = "ok"

                else:
                    # Exactly one route
                    current_route_iface = routes[0]["interface"]
                    if current_route_iface != stored_iface:
                        # Route was changed outside the app — update metadata to match reality
                        print(f"[dns] validate: {group.name} iface changed {stored_iface} -> {current_route_iface}, updating metadata")
                        new_desc = _encode(group.source, group.slug, current_route_iface, group.date, group.batch)
                        self._send([_group_obj(group.name, {"description": new_desc})])
                        changed = True
                        statuses[group.name] = f"updated: {stored_iface} → {current_route_iface}"
                    else:
                        statuses[group.name] = "ok"
            except Exception as e:
                print(f"[dns] validate: repair failed for {group.name}: {e}")
                statuses[group.name] = "error"

        if changed:
            try:
                self._save()
            except Exception as e:
                print(f"[dns] validate: config save failed: {e}")
        return statuses

    # --- Writing ---

    def _change_route(self, group_name: str, interface: str, routes_data: list) -> bool:
        """Leave the group with exactly one route, via `interface`. Returns True if anything was sent.
        The router keeps one route per (group, interface) pair: adding a route for
        another interface does not replace the old one, so the old ones are removed
        explicitly. A group whose routes were all disabled stays disabled.

        The router runs every command of a request even after one fails, so the new
        route is added in a request of its own: if it is refused (unknown interface),
        the old route is still there."""
        current = [r for r in routes_data if r.get("group") == group_name and r.get("interface")]
        disabled = bool(current) and all(r.get("disable", False) for r in current)
        stale = [_route_del(group_name, r["interface"]) for r in current if r["interface"] != interface]
        missing = not any(r["interface"] == interface for r in current)
        if missing:
            self._send([_route_add(group_name, interface)])
            if disabled:
                self._set_routes_enabled(group_name, False, interface=interface)
        if stale:
            self._send(stale)
        return missing or bool(stale)

    def _set_routes_enabled(self, group_name: str, enable: bool, interface: str = None):
        """Enable or disable the group's routes (only the one via `interface`, if given)."""
        routes = self._checked_state({}, self._rci_get_json("rci/dns-proxy/route"), {})["routes"]
        indexes = [r.get("index") for r in routes
                   if r.get("group") == group_name and (interface is None or r.get("interface") == interface)]
        if not indexes or not all(indexes):
            raise ValueError(_("No route found for {group}.").format(group=group_name))
        self._send([_route_disable(index, enable) for index in indexes])

    def _discard_group(self, group_name: str, interface: str):
        """Best-effort removal of a group this operation just created."""
        for command in (_route_del(group_name, interface), _group_obj(group_name, {"no": True})):
            try:
                self._send([command])
            except Exception as e:
                print(f"[dns] discard {group_name}: {e}")

    def _write_includes(self, group_name: str, entries: list[dict], last: dict = None):
        """Send include entries in requests of INCLUDE_BATCH.
        `last` (description and such) is merged into the final request."""
        chunks = [entries[i:i + INCLUDE_BATCH] for i in range(0, len(entries), INCLUDE_BATCH)] or [[]]
        for n, chunk in enumerate(chunks):
            data: dict[str, Any] = {"include": chunk} if chunk else {}
            if last and n == len(chunks) - 1:
                data.update(last)
            if data:
                self._send([_group_obj(group_name, data)])

    def create_group(self, slug: str, domains: list[str], interface: str,
                     date: str = None, batch: int = 1,
                     existing_names: set[str] = None,
                     source: str = "v2fly", save: bool = True, disabled: bool = False) -> str:
        """Create a new DNS route group and its route. Returns the group name.
        Pass existing_names to skip re-fetching; the chosen name is added to it.
        With `disabled` the route is created switched off.

        The route is added after the domains and the description last of all. If a
        step fails the group is removed again. If the router cannot be reached for
        that either, what stays behind has no managed description, so auto-repair
        ignores it, and it has a route only if every domain was already written:
        a partial list is never routed."""
        if not domains:
            raise ValueError(_("Domain list is empty."))
        if len(domains) > DOMAIN_LIMIT:
            raise ValueError(_("Too many domains ({n}), the limit is {limit}.").format(n=len(domains), limit=DOMAIN_LIMIT))
        if date is None:
            date = datetime.now().strftime("%d%m%y")

        with self._lock:
            if existing_names is None:
                existing_names = set(g.name for g in self.get_groups())
            idx = 0
            while f"{GROUP_PREFIX}{idx}" in existing_names:
                idx += 1
            group_name = f"{GROUP_PREFIX}{idx}"
            existing_names.add(group_name)  # Reserve for subsequent batches

            desc = _encode(source, slug, interface, date, batch)
            try:
                self._write_includes(group_name, [{"address": d} for d in domains])
                self._send([_route_add(group_name, interface)])
                if disabled:
                    self._set_routes_enabled(group_name, False, interface=interface)
                self._send([_group_obj(group_name, {"description": desc})])
            except Exception:
                self._discard_group(group_name, interface)
                raise
            if save:
                self._save()
            return group_name

    def update_group_domains(self, group_name: str, domains: list[str], description: str = None,
                             current: list[str] = None, save: bool = True):
        """Make the group contain exactly `domains`, optionally updating the description.
        Only the difference is sent, each removal paired with an addition, so domains
        that stay are never touched and a failure part-way leaves the group between
        the old and the new contents rather than emptied."""
        if len(domains) > DOMAIN_LIMIT:
            raise ValueError(_("Too many domains ({n}), the limit is {limit}.").format(n=len(domains), limit=DOMAIN_LIMIT))

        with self._lock:
            if current is None:
                groups, _routes = self._read_state()
                group = next((g for g in groups if g.name == group_name), None)
                if group is None:
                    raise ValueError(_("Group {group} not found.").format(group=group_name))
                current = group.domains

            new_set, old_set = set(domains), set(current)
            removals = [{"address": d, "no": True} for d in current if d not in new_set]
            additions = [{"address": d} for d in domains if d not in old_set]
            # Each addition follows a removal: a full group has no room otherwise,
            # and no request is a run of removals alone unless the list is shrinking
            entries = []
            for n in range(max(len(removals), len(additions))):
                entries += removals[n:n + 1] + additions[n:n + 1]
            self._write_includes(group_name, entries,
                                 last={"description": description} if description else None)
            if save and (entries or description):
                self._save()

    def update_group_interface(self, group_name: str, new_interface: str, save: bool = True):
        """Change the VPN interface for a group, keeping its enabled/disabled state.
        For a managed group the description is updated to match."""
        with self._lock:
            groups, routes = self._read_state()
            current = next((g for g in groups if g.name == group_name), None)
            if current is None:
                raise ValueError(_("Group {group} not found.").format(group=group_name))

            changed = self._change_route(group_name, new_interface, routes)
            if current.managed and current.interface != new_interface:
                self._send([_group_obj(group_name, {"description": _encode(
                    current.source, current.slug, new_interface, current.date, current.batch)})])
                changed = True
            if changed and save:
                self._save()

    def set_group_description(self, group_name: str, description: str, save: bool = True):
        """Replace the description of a group."""
        with self._lock:
            self._send([_group_obj(group_name, {"description": description})])
            if save:
                self._save()

    def delete_group(self, group_name: str, save: bool = True):
        """Delete a DNS route group and its routes."""
        with self._lock:
            groups, routes = self._read_state()
            payload = [_route_del(group_name, r["interface"]) for r in routes
                       if r.get("group") == group_name and r.get("interface")]
            if any(g.name == group_name for g in groups):
                payload.append(_group_obj(group_name, {"no": True}))
            if payload:
                self._send(payload)
                if save:
                    self._save()

    def toggle_route(self, group_name: str, enable: bool, save: bool = True):
        """Enable or disable every DNS route of a group."""
        with self._lock:
            self._set_routes_enabled(group_name, enable)
            if save:
                self._save()

    def edit_group(self, group_name: str, domains: list[str] = None,
                   interface: str = None, description: str = None):
        """Edit a single unmanaged group in place: domains, route and/or description."""
        if description:
            _check_name(description)
        with self._lock:
            if domains is not None:
                if not domains:
                    raise ValueError(_("Domain list is empty."))
                self.update_group_domains(group_name, domains, save=False)
            if interface:
                self.update_group_interface(group_name, interface, save=False)
            if description:
                # A plain name: it must not turn the group into a managed list
                self.set_group_description(group_name, _check_name(description), save=False)
            self._save()

    def apply_list(self, source: str, slug: str, domains: list[str], interface: str,
                   new_slug: str = None, create: bool = False) -> list[str]:
        """Make the router hold exactly `domains` for the list (source, slug), routed
        via `interface`, split into groups of DOMAIN_LIMIT. Creates the list if it
        does not exist; `new_slug` renames it. Only what changed is written.
        With `create` the list must not exist yet: adding a list never replaces one.
        Returns the group names of the list.

        The router is read first and nothing is written if that fails. Groups this
        call created are removed again if a later step fails, and the configuration
        is saved once, at the end."""
        domains = list(dict.fromkeys(d.strip() for d in domains if d and d.strip()))
        if not domains:
            raise ValueError(_("Domain list is empty."))
        if not interface:
            raise ValueError(_("No interface selected."))
        target_slug = _check_name(new_slug if new_slug is not None else slug)
        today = datetime.now().strftime("%d%m%y")
        chunks = [domains[i:i + DOMAIN_LIMIT] for i in range(0, len(domains), DOMAIN_LIMIT)]

        with self._lock:
            groups, routes = self._read_state()
            mine = sorted((g for g in groups if g.managed and g.source == source and g.slug == slug),
                          key=lambda g: g.batch)
            taken = any(g.slug == target_slug for g in groups if g not in mine)
            # Creating or renaming: the name must not belong to any other list.
            # Creating: nor to this one.
            if (create and mine) or ((not mine or target_slug != slug) and taken):
                raise ValueError(_("A list named '{name}' already exists.").format(name=target_slug))
            # A list switched off stays off when it grows into another group
            disabled = bool(mine) and all(not g.enabled for g in mine)

            names = set(g.name for g in groups)
            result = []
            created = []
            try:
                for i, chunk in enumerate(chunks):
                    batch_num = i + 1
                    if i < len(mine):
                        existing = mine[i]
                        desc = _encode(source, target_slug, interface, today, batch_num)
                        # Route first: if the interface is refused, the list keeps its old
                        # route and its old description
                        self._change_route(existing.name, interface, routes)
                        if set(chunk) != set(existing.domains):
                            print(f"[dns] apply {target_slug} batch {batch_num}: domains changed, updating")
                            self.update_group_domains(existing.name, chunk, description=desc,
                                                      current=existing.domains, save=False)
                        elif desc != existing.description:
                            self.set_group_description(existing.name, desc, save=False)
                        result.append(existing.name)
                    else:
                        print(f"[dns] apply {target_slug} batch {batch_num}: new batch, creating")
                        name = self.create_group(
                            slug=target_slug, domains=chunk, interface=interface,
                            date=today, batch=batch_num,
                            existing_names=names, source=source, save=False,
                            disabled=disabled,
                        )
                        created.append(name)
                        result.append(name)

                # Delete excess old groups (domains shrunk)
                for old in mine[len(chunks):]:
                    print(f"[dns] apply {target_slug} batch {old.batch}: excess, deleting {old.name}")
                    payload = [_route_del(old.name, r["interface"]) for r in routes
                               if r.get("group") == old.name and r.get("interface")]
                    payload.append(_group_obj(old.name, {"no": True}))
                    self._send(payload)
            except Exception:
                for name in created:
                    self._discard_group(name, interface)
                raise
            self._save()
            return result

    def delete_list(self, group_names: list[str]):
        """Delete every group of a list, saving once."""
        with self._lock:
            for name in group_names:
                self.delete_group(name, save=False)
            self._save()

    def toggle_list(self, group_names: list[str], enable: bool):
        """Enable or disable every group of a list, saving once."""
        with self._lock:
            for name in group_names:
                self.toggle_route(name, enable, save=False)
            self._save()

    def set_list_interface(self, group_names: list[str], interface: str):
        """Change the VPN interface of several groups, saving once."""
        with self._lock:
            for name in group_names:
                self.update_group_interface(name, interface, save=False)
            self._save()

    def sync_list(self, slug: str, interface: str, create: bool = False) -> list[str]:
        """Sync a v2fly domain list: download, compare, update only what changed.
        Raises without touching the router if the download fails or is empty.
        With `create` the list must not be on the router yet.
        Returns list of group names."""
        from .v2fly import fetch_domain_list

        # Download outside the lock: it does not touch the router
        domains, _total = fetch_domain_list(slug)
        return self.apply_list("v2fly", slug, domains, interface, create=create)
