"""Tests for DnsRoutesManager.

FakeRouter reproduces what a KeeneticOS 5.1 router was observed to do over RCI:
it answers HTTP 200 with the error inside a "status" list, it runs every command
of a request even after one of them failed, it keeps one route per
(group, interface) pair, and it refuses addresses it cannot parse while applying
the rest of the command.
"""
import copy
import threading
import time
from datetime import datetime

import pytest

from src.api import keenetic_dns, v2fly
from src.api.keenetic_dns import DnsRoutesManager, DnsRouteGroup, RciError, _scan_status

TODAY = datetime.now().strftime("%d%m%y")


def _status(kind, code, message):
    return {"status": [{"status": kind, "code": code, "ident": "Test", "message": message}]}


def _error(code, message):
    return _status("error", code, message)


def _ok(message="done."):
    return _status("message", "1", message)


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class FakeRouter:
    base_url = "http://fake-router"

    def __init__(self, interfaces=("Wireguard0", "Wireguard1")):
        FakeRouter.base_url = f"http://fake-router-{id(self)}"
        self.base_url = FakeRouter.base_url
        self.groups = {}          # name -> {"description": str, "include": [{"address": str}]}
        self.routes = []          # {"group", "interface", "auto", "index", "comment", ["disable"]}
        self.interfaces = list(interfaces)
        self.saves = 0
        self.saved = ({}, [])     # what "show sc" returns: the configuration as of the last save
        self.posts = []           # every write request payload, in order
        self.logins = 0
        self.fail_gets = False
        self.fail_post_number = None   # 1-based index among write requests
        self.unauthorized_once = False
        self.batch_show_as_dict = False
        self.read_delay = 0            # seconds every read takes, to make threads overlap
        self.on_write = None           # called with the 1-based number of each write request

    # -- KeeneticRouter interface --

    def login(self):
        self.logins += 1
        return True

    def keen_request(self, endpoint, data=None, timeout=5):
        if self.unauthorized_once:
            self.unauthorized_once = False
            return FakeResponse(401, "<html>401</html>")
        if not data:
            if self.fail_gets:
                return None
            time.sleep(self.read_delay)
            return self._get(endpoint)
        if isinstance(data, list) and data and "show" in data[0]:
            if self.fail_gets:
                return None
            time.sleep(self.read_delay)
            return self._show(data)
        self.posts.append(data)
        if self.fail_post_number == len(self.posts):
            return None
        if self.on_write:
            self.on_write(len(self.posts))
        return FakeResponse(200, [self._run(cmd) for cmd in data])

    # -- helpers for tests --

    def add_group(self, name, description, domains, interface=None, disabled=False):
        self.groups[name] = {"description": description, "include": [{"address": d} for d in domains]}
        if interface:
            self._add_route(name, interface)
            if disabled:
                self._route(name, interface)["disable"] = True

    def route_view(self):
        return sorted((r["group"], r["interface"], bool(r.get("disable"))) for r in self.routes)

    def domains(self, name):
        return [e["address"] for e in self.groups[name]["include"]]

    # -- read side --

    def _interfaces(self):
        return {i: {"interface-name": i, "type": "Wireguard", "description": i, "connected": "yes"}
                for i in self.interfaces}

    def _get(self, endpoint):
        if endpoint == "rci/object-group/fqdn":
            return FakeResponse(200, self.groups)
        if endpoint == "rci/dns-proxy/route":
            return FakeResponse(200, self.routes)
        if endpoint == "rci/show/interface":
            return FakeResponse(200, self._interfaces())
        return FakeResponse(404, "")

    def _show(self, data):
        if self.batch_show_as_dict:
            return FakeResponse(200, {"show": {"rc": {}}})
        # "rc" is the running configuration, "sc" the one saved last
        which = next(iter(data[0]["show"]))
        groups, routes = (self.groups, self.routes) if which == "rc" else self.saved
        fqdn = {"object-group": {"fqdn": groups}} if groups else {}
        route = {"dns-proxy": {"route": routes}} if routes else {}
        return FakeResponse(200, [{"show": {which: fqdn}}, {"show": {which: route}},
                                  {"show": {"interface": self._interfaces()}}])

    # -- write side --

    def _route(self, group, interface):
        return next((r for r in self.routes if r["group"] == group and r["interface"] == interface), None)

    def _add_route(self, group, interface):
        self.routes.append({"group": group, "interface": interface, "auto": True,
                            "index": f"idx-{group}-{interface}", "comment": ""})

    def _run(self, cmd):
        if "system" in cmd:
            self.saves += 1
            self.saved = (copy.deepcopy(self.groups), copy.deepcopy(self.routes))
            return {"system": {"configuration": {"save": _ok("saving configuration...")}}}
        if "object-group" in cmd:
            (name, data), = cmd["object-group"]["fqdn"].items()
            return {"object-group": {"fqdn": {name: self._run_group(name, data)}}}
        if "dns-proxy" in cmd:
            return {"dns-proxy": {"route": self._run_route(cmd["dns-proxy"]["route"])}}
        return _error("7405600", "no such command")

    def _run_group(self, name, data):
        if data.get("no") is True:
            if name not in self.groups:
                return _error("7471107", "no input")
            del self.groups[name]
            self.routes = [r for r in self.routes if r["group"] != name]
            return _ok("group removed.")
        reply = {}
        if name not in self.groups:
            self.groups[name] = {"description": "", "include": []}
            reply.update(_ok("group created."))
        group = self.groups[name]
        if "include" in data:
            include = data["include"]
            if isinstance(include, dict) and include.get("no"):
                group["include"] = []
                reply["include"] = _ok("cleared included.")
            else:
                replies = []
                for entry in include:
                    address = entry["address"]
                    if entry.get("no"):
                        group["include"] = [e for e in group["include"] if e["address"] != address]
                        replies.append(_ok("removed"))
                    elif " " in address or "!" in address:
                        replies.append(_error("101582220", f'"{name}": invalid FQDN or IP address "{address}".'))
                    elif len(group["include"]) >= 300:
                        replies.append(_error("101583600", f'"{name}": too many elements: "{address}".'))
                    elif all(e["address"] != address for e in group["include"]):
                        group["include"].append({"address": address})
                        replies.append(_ok("added"))
                reply["include"] = replies
        if "description" in data:
            group["description"] = data["description"]
            reply["description"] = _ok("set group description.")
        return reply

    def _run_route(self, route):
        if "disable" in route:
            target = route["disable"]
            found = next((r for r in self.routes if r["index"] == target.get("index")), None)
            if not found:
                return {"disable": _error("4457348", "unable to find the DNS route rule with index")}
            if target.get("no"):
                found.pop("disable", None)
            else:
                found["disable"] = True
            return {"disable": _ok("disabled the DNS route rule")}
        group, interface = route.get("group"), route.get("interface")
        if route.get("no"):
            found = self._route(group, interface)
            if not found:
                return _error("4457148", "unable to find the DNS route rule.")
            self.routes.remove(found)
            return _ok("deleted the DNS route rule")
        if group not in self.groups:
            return _error("7471107", "no input")
        if interface not in self.interfaces:
            return _error("4456948", f"no such interface: {interface}.")
        if self._route(group, interface):
            return _ok("updated the DNS route")
        self._add_route(group, interface)
        return _ok("added the DNS route")


@pytest.fixture
def router():
    return FakeRouter()


@pytest.fixture
def manager(router):
    return DnsRoutesManager(router)


def names(n, prefix="d"):
    return [f"{prefix}{i}.example.com" for i in range(n)]


# --- error detection ---------------------------------------------------------

class TestScanStatus:
    """Replies below are copied from a real router."""

    def scan(self, reply):
        errors, warnings = [], []
        _scan_status(reply, errors, warnings)
        return errors, warnings

    def test_parse_error(self):
        reply = [{"parse": {"prompt": "(config)", "status": [
            {"status": "error", "code": "7405602", "ident": "Command::Base", "message": "argument parse error."}]}}]
        assert self.scan(reply) == (["argument parse error."], [])

    def test_raw_route_error(self):
        reply = [{"dns-proxy": {"route": {"status": [
            {"status": "error", "code": "4456948", "ident": "Dns::Route::Manager", "message": "no such interface: Nope9."}]}}}]
        assert self.scan(reply) == (["no such interface: Nope9."], [])

    def test_error_nested_in_include_list_is_a_warning(self):
        reply = [{"object-group": {"fqdn": {"g": {
            "description": {"status": [{"status": "message", "code": "101582400", "message": "set group description."}]},
            "include": [
                {"status": [{"status": "message", "code": "101582200", "message": "added"}]},
                {"status": [{"status": "error", "code": "101582220", "ident": "Network::ObjectGroup",
                             "message": '"g": invalid FQDN or IP address "bad domain!!".'}]}]}}}}]
        errors, warnings = self.scan(reply)
        assert errors == [] and len(warnings) == 1

    def test_too_many_elements_is_an_error(self):
        reply = [{"object-group": {"fqdn": {"g": {"include": [{"status": [
            {"status": "error", "code": "101583600", "message": '"g": too many elements: "x".'}]}]}}}}]
        assert len(self.scan(reply)[0]) == 1

    def test_success_messages_are_ignored(self):
        reply = [{"dns-proxy": {"route": {"status": [
            {"status": "message", "code": "4456748", "message": "added the DNS route to g."}]}}}]
        assert self.scan(reply) == ([], [])


class TestErrorsRaise:
    def test_rejected_command_raises(self, manager, router):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*{TODAY}*1", ["a.com"], "Wireguard0")
        with pytest.raises(RciError, match="no such interface"):
            manager.update_group_interface("rt_0", "Nope9")

    def test_rejected_interface_keeps_old_route_and_description(self, manager, router):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*{TODAY}*1", ["a.com"], "Wireguard0")
        with pytest.raises(RciError):
            manager.update_group_interface("rt_0", "Nope9")
        assert router.route_view() == [("rt_0", "Wireguard0", False)]
        assert router.groups["rt_0"]["description"] == f"v2fly:a*Wireguard0*{TODAY}*1"
        assert router.saves == 0

    def test_nothing_is_saved_after_a_rejected_command(self, manager, router):
        with pytest.raises(RciError):
            manager.apply_list("manual", "mine", names(5), "Nope9")
        assert router.saves == 0
        assert router.groups == {} and router.routes == []

    def test_refused_address_is_a_warning_not_a_failure(self, manager, router):
        manager.apply_list("manual", "mine", ["ok.com", "bad domain!!", "ok2.com"], "Wireguard0")
        assert router.domains("rt_0") == ["ok.com", "ok2.com"]
        warnings = manager.pop_warnings()
        assert len(warnings) == 1 and "bad domain!!" in warnings[0]
        assert manager.pop_warnings() == []

    def test_non_json_reply_raises(self, manager, router):
        router.keen_request = lambda endpoint, data=None, timeout=5: FakeResponse(200, "<html>")
        with pytest.raises(RciError):
            manager.get_groups()

    def test_non_200_raises(self, manager, router):
        router.keen_request = lambda endpoint, data=None, timeout=5: FakeResponse(500, "boom")
        with pytest.raises(RciError):
            manager.get_groups()


# --- failed reads ------------------------------------------------------------

class TestFailedRead:
    def test_get_groups_raises_instead_of_returning_empty(self, manager, router):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*{TODAY}*1", ["a.com"], "Wireguard0")
        router.fail_gets = True
        with pytest.raises(ConnectionError):
            manager.get_groups()

    def test_fetch_all_raises(self, manager, router):
        router.fail_gets = True
        with pytest.raises(ConnectionError):
            manager.fetch_all_route_data()

    def test_create_does_not_overwrite_rt_0_when_the_read_fails(self, manager, router):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*{TODAY}*1", ["a.com"], "Wireguard0")
        router.fail_gets = True
        with pytest.raises(ConnectionError):
            manager.create_group("b", ["b.com"], "Wireguard1")
        with pytest.raises(ConnectionError):
            manager.apply_list("manual", "b", ["b.com"], "Wireguard1")
        assert router.posts == []
        assert router.domains("rt_0") == ["a.com"]

    def test_expired_session_logs_in_again(self, manager, router):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*{TODAY}*1", ["a.com"], "Wireguard0")
        logins = router.logins
        router.unauthorized_once = True
        assert len(manager.get_groups()) == 1
        assert router.logins == logins + 1

    def test_empty_router_reads_as_empty(self, manager, router):
        data = manager.fetch_all_route_data()
        assert data["groups"] == {} and data["routes"] == []
        assert manager.get_groups() == []

    def test_page_read_shows_changes_that_are_not_saved_yet(self, manager, router):
        """The save is asynchronous on the router; a reload right after a change
        must not show the previous state."""
        manager.autosave = False
        manager.apply_list("manual", "mine", ["a.com"], "Wireguard0")
        data = manager.fetch_all_route_data()
        assert list(data["groups"]) == ["rt_0"] and len(data["routes"]) == 1

    def test_unexpected_batch_shape_falls_back_to_gets(self, manager, router):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*{TODAY}*1", ["a.com"], "Wireguard0")
        router.batch_show_as_dict = True
        data = manager.fetch_all_route_data()
        assert list(data["groups"]) == ["rt_0"] and len(data["routes"]) == 1


# --- creating and updating lists ---------------------------------------------

class TestApplyList:
    def test_create_splits_into_batches(self, manager, router):
        result = manager.apply_list("manual", "big", names(450), "Wireguard0")
        assert result == ["rt_0", "rt_1"]
        assert len(router.domains("rt_0")) == 300 and len(router.domains("rt_1")) == 150
        assert router.groups["rt_0"]["description"] == f"big*Wireguard0*{TODAY}*1"
        assert router.groups["rt_1"]["description"] == f"big*Wireguard0*{TODAY}*2"
        assert router.route_view() == [("rt_0", "Wireguard0", False), ("rt_1", "Wireguard0", False)]
        assert router.saves == 1

    def test_reapplying_an_unchanged_list_writes_nothing(self, manager, router):
        manager.apply_list("manual", "big", names(450), "Wireguard0")
        posts, saves = len(router.posts), router.saves
        manager.apply_list("manual", "big", names(450), "Wireguard0")
        assert len(router.posts) == posts + 1 and router.saves == saves + 1  # only the save

    def test_edit_of_multi_batch_list_keeps_every_domain(self, manager, router):
        manager.apply_list("manual", "big", names(400), "Wireguard0")
        edited = [d for d in names(400) if d != "d5.example.com"] + ["new.example.com"]
        manager.apply_list("manual", "big", edited, "Wireguard0")
        assert set(router.domains("rt_0")) | set(router.domains("rt_1")) == set(edited)
        assert not set(router.domains("rt_0")) & set(router.domains("rt_1"))

    def test_shrinking_removes_excess_batches_and_their_routes(self, manager, router):
        manager.apply_list("manual", "big", names(450), "Wireguard0")
        manager.apply_list("manual", "big", names(100), "Wireguard0")
        assert list(router.groups) == ["rt_0"]
        assert router.route_view() == [("rt_0", "Wireguard0", False)]

    def test_empty_list_is_refused_before_touching_the_router(self, manager, router):
        manager.apply_list("manual", "big", names(450), "Wireguard0")
        posts = len(router.posts)
        with pytest.raises(ValueError):
            manager.apply_list("manual", "big", [], "Wireguard0")
        assert len(router.posts) == posts and len(router.groups) == 2

    def test_rename(self, manager, router):
        manager.apply_list("manual", "old", names(350), "Wireguard0")
        manager.apply_list("manual", "old", names(350), "Wireguard0", new_slug="new")
        assert [g["description"] for g in router.groups.values()] == [
            f"new*Wireguard0*{TODAY}*1", f"new*Wireguard0*{TODAY}*2"]

    @pytest.mark.parametrize("bad", ["", "  ", "a*b", "a\nb"])
    def test_bad_names_are_refused(self, manager, router, bad):
        with pytest.raises(ValueError):
            manager.apply_list("manual", bad, ["a.com"], "Wireguard0")
        assert router.posts == []

    def test_interface_change_moves_the_route(self, manager, router):
        manager.apply_list("manual", "big", names(350), "Wireguard0")
        manager.apply_list("manual", "big", names(350), "Wireguard1")
        assert router.route_view() == [("rt_0", "Wireguard1", False), ("rt_1", "Wireguard1", False)]
        assert all("*Wireguard1*" in g["description"] for g in router.groups.values())

    def test_failure_midway_removes_what_this_call_created(self, manager, router):
        router.add_group("rt_0", f"keep*Wireguard0*{TODAY}*1", ["keep.com"], "Wireguard0")
        router.fail_post_number = len(router.posts) + 6   # while writing the second new group
        with pytest.raises(ConnectionError):
            manager.apply_list("manual", "big", names(450), "Wireguard0")
        assert list(router.groups) == ["rt_0"]
        assert router.route_view() == [("rt_0", "Wireguard0", False)]
        assert router.saves == 0

    @pytest.mark.parametrize("dies_at", [1, 2, 3, 4, 5])
    def test_group_left_by_a_dead_connection(self, manager, router, dies_at):
        """The connection dies for good at one of the five writes that create a
        250-domain group (three include requests, the route, the description), so
        the clean-up cannot reach the router either. Whatever is left must not be
        managed (auto-repair would give it a route) and must not route a partial list."""
        real = router.keen_request
        state = {"writes": 0}

        def dying(endpoint, data=None, timeout=5):
            if data and "show" not in data[0]:
                state["writes"] += 1
                if state["writes"] >= dies_at:
                    return None
            return real(endpoint, data, timeout)

        router.keen_request = dying
        with pytest.raises(ConnectionError):
            manager.apply_list("manual", "big", names(250), "Wireguard0")
        router.keen_request = real

        leftover = manager.get_groups()
        assert not any(g.managed for g in leftover)
        for g in leftover:
            if g.routes:
                assert len(g.domains) == 250
        assert router.saves == 0
        # auto-repair leaves it alone
        routes_before = router.route_view()
        assert set(manager.validate_and_repair().values()) <= {"ok"}
        assert router.route_view() == routes_before

    def test_add_refuses_an_existing_list_of_the_same_source(self, manager, router):
        manager.apply_list("manual", "work", ["a.com", "b.com", "c.com"], "Wireguard0")
        posts = len(router.posts)
        with pytest.raises(ValueError, match="already exists"):
            manager.apply_list("manual", "work", ["new.com"], "Wireguard1", create=True)
        assert len(router.posts) == posts
        assert router.domains("rt_0") == ["a.com", "b.com", "c.com"]
        assert router.route_view() == [("rt_0", "Wireguard0", False)]

    def test_add_creates_when_the_name_is_free(self, manager, router):
        assert manager.apply_list("manual", "work", ["a.com"], "Wireguard0", create=True) == ["rt_0"]

    def test_disabled_list_stays_disabled_when_it_grows_a_batch(self, manager, router):
        manager.apply_list("manual", "big", names(300), "Wireguard0")
        manager.toggle_list(["rt_0"], False)
        manager.apply_list("manual", "big", names(350), "Wireguard0")
        assert router.route_view() == [("rt_0", "Wireguard0", True), ("rt_1", "Wireguard0", True)]

    def test_enabled_list_grows_an_enabled_batch(self, manager, router):
        manager.apply_list("manual", "big", names(300), "Wireguard0")
        manager.apply_list("manual", "big", names(350), "Wireguard0")
        assert router.route_view() == [("rt_0", "Wireguard0", False), ("rt_1", "Wireguard0", False)]

    def test_replacing_many_domains_never_empties_the_group(self, manager, router):
        manager.apply_list("manual", "mine", names(150, "old"), "Wireguard0")
        router.fail_post_number = len(router.posts) + 2      # second include request of the edit
        with pytest.raises(ConnectionError):
            manager.apply_list("manual", "mine", names(150, "new"), "Wireguard0")
        left = router.domains("rt_0")
        assert len(left) == 150
        assert any(d.startswith("old") for d in left) and any(d.startswith("new") for d in left)


class TestCollisions:
    def test_manual_list_cannot_take_the_name_of_a_v2fly_list(self, manager, router):
        router.add_group("rt_0", f"v2fly:youtube*Wireguard0*{TODAY}*1", ["yt.com"], "Wireguard0")
        with pytest.raises(ValueError, match="already exists"):
            manager.apply_list("manual", "youtube", ["mine.com"], "Wireguard0")
        assert router.posts == []

    def test_rename_onto_existing_name_is_refused(self, manager, router):
        router.add_group("rt_0", f"v2fly:youtube*Wireguard0*{TODAY}*1", ["yt.com"], "Wireguard0")
        router.add_group("rt_1", f"mine*Wireguard0*{TODAY}*1", ["mine.com"], "Wireguard0")
        with pytest.raises(ValueError, match="already exists"):
            manager.apply_list("manual", "mine", ["mine.com"], "Wireguard0", new_slug="youtube")
        assert router.posts == []

    def test_sync_leaves_a_manual_list_with_the_same_name_alone(self, manager, router, monkeypatch):
        """State that older versions could produce: the sync used to delete rt_1."""
        router.add_group("rt_0", f"v2fly:youtube*Wireguard0*010101*1", ["old.com"], "Wireguard0")
        router.add_group("rt_1", f"youtube*Wireguard0*010101*1", ["hand-typed.com"], "Wireguard0")
        monkeypatch.setattr(v2fly, "fetch_domain_list", lambda slug: (["new.com"], 1))
        manager.sync_list("youtube", "Wireguard0")
        assert router.domains("rt_0") == ["new.com"]
        assert router.domains("rt_1") == ["hand-typed.com"]
        assert router.groups["rt_1"]["description"] == "youtube*Wireguard0*010101*1"

    @pytest.mark.parametrize("name", ["v2fly:youtube", "v2fly:"])
    def test_manual_name_cannot_carry_the_v2fly_marker(self, manager, router, name):
        with pytest.raises(ValueError):
            manager.apply_list("manual", name, ["mine.com"], "Wireguard0")
        router.add_group("rt_0", f"mine*Wireguard0*{TODAY}*1", ["mine.com"], "Wireguard0")
        with pytest.raises(ValueError):
            manager.apply_list("manual", "mine", ["mine.com"], "Wireguard0", new_slug=name)
        assert router.posts == []

    def test_rows_do_not_merge_across_sources(self, manager, router):
        router.add_group("rt_0", f"v2fly:youtube*Wireguard0*{TODAY}*1", ["a.com"], "Wireguard0")
        router.add_group("rt_1", f"youtube*Wireguard0*{TODAY}*1", ["b.com"], "Wireguard0")
        router.add_group("domain-list0", "Telegram", ["t.me"], "Wireguard0")
        router.add_group("domain-list1", "Telegram", ["telegram.org"], "Wireguard0")
        rows = manager.get_grouped_by_slug()
        assert len(rows) == 4
        assert all(len(groups) == 1 for groups in rows.values())

    def test_batches_of_one_list_share_a_row(self, manager, router):
        manager.apply_list("manual", "big", names(450), "Wireguard0")
        rows = manager.get_grouped_by_slug()
        assert list(rows) == ["big"] and [g.batch for g in rows["big"]] == [1, 2]

    def test_concurrent_creates_get_distinct_groups(self, router):
        # Slow reads: without the shared lock every thread would read the router
        # while it is still empty and pick rt_0
        router.read_delay = 0.02
        errors = []

        def create(i):
            try:
                DnsRoutesManager(router).apply_list("manual", f"list{i}", names(3, f"l{i}-"), "Wireguard0")
            except Exception as e:  # pragma: no cover - reported below
                errors.append(e)

        threads = [threading.Thread(target=create, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(router.groups) == 8
        assert all(len(g["include"]) == 3 for g in router.groups.values())
        assert len({g["description"] for g in router.groups.values()}) == 8


# --- sync --------------------------------------------------------------------

class TestSync:
    def test_failed_download_leaves_router_untouched(self, manager, router, monkeypatch):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*010101*1", ["a.com"], "Wireguard0")

        def boom(slug):
            raise ValueError("Failed to fetch 'inc'")

        monkeypatch.setattr(v2fly, "fetch_domain_list", boom)
        with pytest.raises(ValueError):
            manager.sync_list("a", "Wireguard0")
        assert router.posts == [] and router.domains("rt_0") == ["a.com"]

    def test_sync_with_another_interface_moves_the_route(self, manager, router, monkeypatch):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*010101*1", ["a.com"], "Wireguard0")
        monkeypatch.setattr(v2fly, "fetch_domain_list", lambda slug: (["a.com"], 1))
        manager.sync_list("a", "Wireguard1")
        assert router.route_view() == [("rt_0", "Wireguard1", False)]
        assert router.groups["rt_0"]["description"] == f"v2fly:a*Wireguard1*{TODAY}*1"
        # and auto-repair has nothing to revert
        assert manager.validate_and_repair() == {"rt_0": "ok"}

    def test_adding_an_already_added_v2fly_list_is_refused(self, manager, router, monkeypatch):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*010101*1", ["a.com"], "Wireguard0")
        monkeypatch.setattr(v2fly, "fetch_domain_list", lambda slug: (["new.com"], 1))
        with pytest.raises(ValueError, match="already exists"):
            manager.sync_list("a", "Wireguard1", create=True)
        assert router.posts == [] and router.route_view() == [("rt_0", "Wireguard0", False)]

    def test_one_save_per_sync(self, manager, router, monkeypatch):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*010101*1", names(300), "Wireguard0")
        router.add_group("rt_1", f"v2fly:a*Wireguard0*010101*2", names(50, "e"), "Wireguard0")
        monkeypatch.setattr(v2fly, "fetch_domain_list", lambda slug: (names(299) + names(60, "e"), 359))
        manager.sync_list("a", "Wireguard0")
        assert router.saves == 1
        assert set(router.domains("rt_0")) | set(router.domains("rt_1")) == set(names(299) + names(60, "e"))


class TestV2flyParsing:
    def fetch_from(self, files, monkeypatch):
        def fake(slug):
            if slug not in files:
                raise ValueError(f"Failed to fetch '{slug}'")
            return files[slug], slug
        monkeypatch.setattr(v2fly, "_fetch_raw", fake)

    def test_failed_include_fails_the_whole_list(self, monkeypatch):
        self.fetch_from({"top": "a.com\ninclude:missing\n"}, monkeypatch)
        with pytest.raises(ValueError, match="missing"):
            v2fly.fetch_domain_list("top")

    def test_include_only_list(self, monkeypatch):
        self.fetch_from({"top": "include:one\ninclude:two\n", "one": "a.com", "two": "full:b.com"}, monkeypatch)
        assert v2fly.fetch_domain_list("top")[0] == ["a.com", "b.com"]

    def test_list_without_domains_raises(self, monkeypatch):
        self.fetch_from({"top": "# comment\nkeyword:foo\nregexp:^x$\n"}, monkeypatch)
        with pytest.raises(ValueError, match="no domains"):
            v2fly.fetch_domain_list("top")

    def test_include_with_attribute_filter(self, monkeypatch):
        self.fetch_from({"top": "include:other @cn\ninclude:third @-ads\n",
                         "other": "a.com @cn\nb.com\nc.com @cn @ads",
                         "third": "d.com @ads\ne.com"}, monkeypatch)
        assert v2fly.fetch_domain_list("top")[0] == ["a.com", "c.com", "e.com"]

    def test_attributes_are_not_stored_as_domains(self, monkeypatch):
        self.fetch_from({"top": "domain:a.com @ads\nfull:B.com # note\n"}, monkeypatch)
        assert v2fly.fetch_domain_list("top")[0] == ["a.com", "b.com"]

    def test_include_cycle_terminates(self, monkeypatch):
        self.fetch_from({"top": "a.com\ninclude:other", "other": "b.com\ninclude:top"}, monkeypatch)
        assert set(v2fly.fetch_domain_list("top")[0]) == {"a.com", "b.com"}


# --- routes ------------------------------------------------------------------

class TestRoutes:
    def test_interface_change_leaves_exactly_one_route(self, manager, router):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*{TODAY}*1", ["a.com"], "Wireguard0")
        manager.update_group_interface("rt_0", "Wireguard1")
        assert router.route_view() == [("rt_0", "Wireguard1", False)]
        assert router.groups["rt_0"]["description"] == f"v2fly:a*Wireguard1*{TODAY}*1"

    def test_interface_change_keeps_a_disabled_list_disabled(self, manager, router):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*{TODAY}*1", ["a.com"], "Wireguard0", disabled=True)
        router.add_group("rt_1", f"v2fly:b*Wireguard0*{TODAY}*1", ["b.com"], "Wireguard0")
        manager.update_group_interface("rt_0", "Wireguard1")
        assert router.route_view() == [("rt_0", "Wireguard1", True), ("rt_1", "Wireguard0", False)]

    def test_interface_change_does_not_rewrite_unmanaged_description(self, manager, router):
        router.add_group("domain-list0", "Telegram", ["t.me"], "Wireguard0")
        manager.update_group_interface("domain-list0", "Wireguard1")
        assert router.groups["domain-list0"]["description"] == "Telegram"
        assert router.route_view() == [("domain-list0", "Wireguard1", False)]

    def test_toggle_targets_the_named_group(self, manager, router):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*{TODAY}*1", ["a.com"], "Wireguard0")
        router.add_group("rt_1", f"v2fly:b*Wireguard0*{TODAY}*1", ["b.com"], "Wireguard0")
        manager.toggle_route("rt_0", False)
        assert router.route_view() == [("rt_0", "Wireguard0", True), ("rt_1", "Wireguard0", False)]
        manager.toggle_route("rt_0", True)
        assert router.route_view() == [("rt_0", "Wireguard0", False), ("rt_1", "Wireguard0", False)]

    def test_toggle_without_a_route_raises(self, manager, router):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*{TODAY}*1", ["a.com"])
        with pytest.raises(ValueError):
            manager.toggle_route("rt_0", False)

    def test_delete_removes_group_and_routes(self, manager, router):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*{TODAY}*1", ["a.com"], "Wireguard0")
        router.add_group("rt_1", f"v2fly:b*Wireguard0*{TODAY}*1", ["b.com"], "Wireguard0")
        manager.delete_list(["rt_0"])
        assert list(router.groups) == ["rt_1"] and router.route_view() == [("rt_1", "Wireguard0", False)]
        assert router.saves == 1

    def test_deleting_a_missing_group_is_harmless(self, manager, router):
        manager.delete_group("rt_9")
        assert router.posts == []


class TestEditGroup:
    def test_domains_are_changed_by_difference(self, manager, router):
        router.add_group("domain-list0", "Telegram", ["a.com", "b.com"], "Wireguard0")
        manager.edit_group("domain-list0", domains=["b.com", "c.com"])
        assert router.domains("domain-list0") == ["b.com", "c.com"]
        assert router.groups["domain-list0"]["description"] == "Telegram"

    def test_full_group_can_swap_a_domain(self, manager, router):
        router.add_group("domain-list0", "Full", names(300), "Wireguard0")
        manager.edit_group("domain-list0", domains=names(299) + ["new.example.com"])
        assert len(router.domains("domain-list0")) == 300 and "new.example.com" in router.domains("domain-list0")

    def test_over_the_limit_is_refused_without_writing(self, manager, router):
        router.add_group("domain-list0", "Telegram", ["a.com"], "Wireguard0")
        with pytest.raises(ValueError):
            manager.edit_group("domain-list0", domains=names(301))
        assert router.posts == [] and router.domains("domain-list0") == ["a.com"]

    @pytest.mark.parametrize("name", ["My*list*2", "v2fly:telegram*x*y", "**x**", "v2fly:telegram"])
    def test_rename_cannot_turn_an_external_group_into_a_managed_list(self, manager, router, name):
        router.add_group("domain-list0", "Telegram", ["t.me"], "Wireguard0")
        with pytest.raises(ValueError):
            manager.edit_group("domain-list0", domains=["t.me", "telegram.org"], description=name)
        assert router.posts == []
        assert router.groups["domain-list0"]["description"] == "Telegram"

    def test_plain_rename_of_an_external_group(self, manager, router):
        router.add_group("domain-list0", "Telegram", ["t.me"], "Wireguard0")
        manager.edit_group("domain-list0", description="Телеграм & Co")
        assert router.groups["domain-list0"]["description"] == "Телеграм & Co"
        assert not manager.get_groups()[0].managed

    def test_clearing_all_domains_is_refused(self, manager, router):
        router.add_group("domain-list0", "Telegram", ["a.com"], "Wireguard0")
        with pytest.raises(ValueError):
            manager.edit_group("domain-list0", domains=[])
        assert router.domains("domain-list0") == ["a.com"]


class TestValidate:
    def test_missing_route_is_repaired(self, manager, router):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*{TODAY}*1", ["a.com"])
        statuses = manager.validate_and_repair()
        assert statuses == {"rt_0": "repaired:→Wireguard0"}
        assert router.route_view() == [("rt_0", "Wireguard0", False)]

    def test_duplicate_routes_are_cleaned(self, manager, router):
        router.add_group("rt_0", f"v2fly:a*Wireguard1*{TODAY}*1", ["a.com"], "Wireguard0")
        router._add_route("rt_0", "Wireguard1")
        statuses = manager.validate_and_repair()
        assert statuses == {"rt_0": "cleaned:1:→Wireguard1"}
        assert router.route_view() == [("rt_0", "Wireguard1", False)]

    def test_route_changed_outside_updates_description(self, manager, router):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*{TODAY}*1", ["a.com"], "Wireguard1")
        statuses = manager.validate_and_repair()
        assert statuses == {"rt_0": "updated: Wireguard0 → Wireguard1"}
        assert router.groups["rt_0"]["description"] == f"v2fly:a*Wireguard1*{TODAY}*1"

    def test_repair_waits_for_a_running_operation(self, manager, router):
        """An interface change passes through a state with two routes. A page load
        arriving then must not repair that snapshot: it would delete the new route."""
        router.add_group("rt_0", f"v2fly:a*Wireguard0*{TODAY}*1", ["a.com"], "Wireguard0")
        seen = {}

        def during_operation(write_number):
            if "loader" in seen:
                return
            # First write of the operation: the new route was just added
            seen["routes_mid"] = len(router.routes)
            loader = threading.Thread(target=lambda: seen.setdefault(
                "statuses", DnsRoutesManager(router).validate_and_repair()))
            seen["loader"] = loader
            loader.start()
            loader.join(0.2)
            seen["blocked"] = loader.is_alive()

        router.on_write = during_operation
        manager.update_group_interface("rt_0", "Wireguard1")
        router.on_write = None
        seen["loader"].join(5)

        assert seen["blocked"], "the load ran in the middle of the operation"
        assert seen["statuses"] == {"rt_0": "ok"}
        assert router.route_view() == [("rt_0", "Wireguard1", False)]

    def test_healthy_state_writes_nothing(self, manager, router):
        router.add_group("rt_0", f"v2fly:a*Wireguard0*{TODAY}*1", ["a.com"], "Wireguard0")
        router.add_group("domain-list0", "Telegram", ["t.me"])
        statuses = manager.validate_and_repair()
        assert set(statuses.values()) == {"ok"} and router.posts == []


class TestDescription:
    def test_round_trip(self):
        g = DnsRouteGroup("rt_0", slug="youtube", interface="Wireguard1", date="240726", batch=2, source="v2fly")
        assert g.encode_description() == "v2fly:youtube*Wireguard1*240726*2"
        assert DnsRouteGroup.parse_description(g.encode_description()) == {
            "slug": "youtube", "interface": "Wireguard1", "date": "240726", "batch": 2, "source": "v2fly"}

    def test_plain_description_is_not_managed(self):
        assert not DnsRouteGroup.is_managed("📺  YouTube")
        assert DnsRouteGroup.is_managed("mine*Wireguard1*240726*1")
