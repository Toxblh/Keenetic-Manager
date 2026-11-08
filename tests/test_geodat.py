"""Tests for the geosite.dat / geoip.dat reader and its download logic."""
import hashlib

import pytest

from src.api import geodat


# --- building .dat files -----------------------------------------------------

def _varint(n):
    out = b""
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out += bytes([byte | 0x80])
        else:
            return out + bytes([byte])


def _bytes_field(field, data):
    return _varint(field << 3 | 2) + _varint(len(data)) + data


def _int_field(field, value):
    return _varint(field << 3) + _varint(value)


def geosite(categories):
    """categories: {name: [(type, value), ...]}"""
    out = b""
    for name, domains in categories.items():
        body = _bytes_field(1, name.encode())
        for kind, value in domains:
            domain = (_int_field(1, kind) if kind else b"") + _bytes_field(2, value.encode())
            # an attribute, which must be skipped over
            domain += _bytes_field(3, _bytes_field(1, b"ads") + _int_field(2, 1))
            body += _bytes_field(2, domain)
        out += _bytes_field(1, body)
    return out


def geoip(categories):
    """categories: {name: [(ip bytes, prefix), ...]}"""
    out = b""
    for name, cidrs in categories.items():
        body = _bytes_field(1, name.encode())
        for ip, prefix in cidrs:
            body += _bytes_field(2, _bytes_field(1, ip) + _int_field(2, prefix))
        out += _bytes_field(1, body)
    return out


SITE = geosite({
    "telegram": [(2, "telegram.org"), (3, "t.me"), (1, "^tg.*$"), (0, "keyword")],
    "YOUTUBE": [(2, "YouTube.com")],
})
IP = geoip({
    "TELEGRAM": [(bytes([91, 108, 4, 0]), 22), (bytes([149, 154, 167, 99]), 32),
                 (bytes(16), 32)],
    "NETFLIX": [(bytes([23, 246, 0, 0]), 18)],
})


# --- parsing -----------------------------------------------------------------

class TestParse:
    def test_domain_and_full_rules_only(self):
        assert geodat.parse_category("geosite", SITE, "TELEGRAM") == ["telegram.org", "t.me"]

    def test_domains_are_lowercased(self):
        assert geodat.parse_category("geosite", SITE, "youtube") == ["youtube.com"]

    def test_subnets_ipv4_only_and_bare_host(self):
        assert geodat.parse_category("geoip", IP, "telegram") == ["91.108.4.0/22", "149.154.167.99"]

    def test_unknown_category(self):
        assert geodat.parse_category("geoip", IP, "nope") == []

    def test_truncated_file_raises(self):
        with pytest.raises(ValueError):
            geodat.parse_category("geosite", SITE[:-3], "YOUTUBE")


# --- downloads ---------------------------------------------------------------

def _sums(data, name="x.dat"):
    return f"{hashlib.sha256(data).hexdigest()}  {name}\n".encode()


class FakeNet:
    """Serves {url: bytes or Exception} and records what was asked for."""
    def __init__(self, files):
        self.files = files
        self.asked = []

    def __call__(self, url, timeout):
        self.asked.append(url)
        item = self.files.get(url)
        if item is None or isinstance(item, Exception):
            raise item or OSError(f"404 {url}")
        return item


def _serve(monkeypatch, source, site=SITE, ip=IP, mirror=0, extra=None):
    info = geodat.SOURCES[source]
    files = {}
    for kind, data in (("geosite", site), ("geoip", ip)):
        url = info["mirrors"][kind][mirror]
        files[url] = data
        files[url + info["hash_suffix"]] = _sums(data)
    files.update(extra or {})
    net = FakeNet(files)
    monkeypatch.setattr(geodat, "_get", net)
    return net


class TestDownload:
    def test_fetch_category_merges_domains_and_subnets(self, monkeypatch):
        _serve(monkeypatch, "hydraponique")
        entries, total = geodat.fetch_category("hydraponique:TELEGRAM")
        assert entries == ["telegram.org", "t.me", "91.108.4.0/22", "149.154.167.99"]
        assert total == 4

    def test_category_in_one_file_only(self, monkeypatch):
        _serve(monkeypatch, "hydraponique")
        assert geodat.fetch_category("hydraponique:NETFLIX")[0] == ["23.246.0.0/18"]

    def test_missing_category_is_an_error(self, monkeypatch):
        _serve(monkeypatch, "hydraponique")
        with pytest.raises(ValueError, match="not in"):
            geodat.fetch_category("hydraponique:NOPE")

    def test_category_with_only_regex_rules_is_an_error(self, monkeypatch):
        _serve(monkeypatch, "hydraponique", site=geosite({"RX": [(1, "^a$")]}))
        with pytest.raises(ValueError, match="no entries"):
            geodat.fetch_category("hydraponique:RX")

    def test_unchanged_hash_downloads_only_the_hash(self, monkeypatch):
        net = _serve(monkeypatch, "hydraponique")
        geodat.ensure_file("hydraponique", "geosite", now=1000)
        net.asked.clear()
        geodat.ensure_file("hydraponique", "geosite", max_age=0, now=2000)
        assert all(u.endswith(".sha256") for u in net.asked) and len(net.asked) == 1

    def test_recent_check_asks_nothing(self, monkeypatch):
        net = _serve(monkeypatch, "hydraponique")
        geodat.ensure_file("hydraponique", "geosite", now=1000)
        net.asked.clear()
        geodat.ensure_file("hydraponique", "geosite", now=1000 + geodat.FILE_CHECK_INTERVAL - 1)
        assert net.asked == []

    def test_changed_hash_replaces_the_file(self, monkeypatch):
        _serve(monkeypatch, "hydraponique")
        geodat.ensure_file("hydraponique", "geosite", now=1000)
        _serve(monkeypatch, "hydraponique", site=geosite({"TELEGRAM": [(2, "new.org")]}))
        path = geodat.ensure_file("hydraponique", "geosite", max_age=0, now=2000)
        assert geodat.parse_category("geosite", open(path, "rb").read(), "TELEGRAM") == ["new.org"]

    def test_file_not_matching_its_hash_falls_to_the_next_mirror(self, monkeypatch):
        info = geodat.SOURCES["hydraponique"]
        first = info["mirrors"]["geosite"][0]
        _serve(monkeypatch, "hydraponique", mirror=1, extra={
            first: SITE[:-5], first + info["hash_suffix"]: _sums(SITE)})
        path = geodat.ensure_file("hydraponique", "geosite", now=1000)
        assert open(path, "rb").read() == SITE

    def test_unreachable_mirrors_keep_the_old_copy(self, monkeypatch):
        _serve(monkeypatch, "hydraponique")
        geodat.ensure_file("hydraponique", "geosite", now=1000)
        net = FakeNet({})
        monkeypatch.setattr(geodat, "_get", net)
        path = geodat.ensure_file("hydraponique", "geosite", max_age=0, now=2000)
        assert open(path, "rb").read() == SITE
        # and the mirrors are not asked again right away
        net.asked.clear()
        geodat.ensure_file("hydraponique", "geosite", max_age=0, now=2001)
        assert net.asked == []

    def test_no_copy_and_no_mirror_is_an_error(self, monkeypatch):
        monkeypatch.setattr(geodat, "_get", FakeNet({}))
        with pytest.raises(ValueError, match="Failed to download"):
            geodat.ensure_file("hydraponique", "geosite")

    def test_categories_with_counts(self, monkeypatch):
        _serve(monkeypatch, "runetfreedom")
        assert geodat.get_categories("runetfreedom") == [
            {"name": "NETFLIX", "domains": 0, "ips": 1},
            {"name": "TELEGRAM", "domains": 2, "ips": 2},
            {"name": "YOUTUBE", "domains": 1, "ips": 0},
        ]

    def test_categories_from_one_file_when_the_other_fails(self, monkeypatch):
        net = _serve(monkeypatch, "runetfreedom")
        for url in list(net.files):
            if "geoip" in url:
                del net.files[url]
        assert [c["name"] for c in geodat.get_categories("runetfreedom")] == ["TELEGRAM", "YOUTUBE"]

    @pytest.mark.parametrize("slug", ["TELEGRAM", "nosuch:TELEGRAM", "hydraponique:"])
    def test_bad_slug(self, slug):
        with pytest.raises(ValueError):
            geodat.split_slug(slug)
