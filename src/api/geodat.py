"""
geosite.dat / geoip.dat integration for Keenetic-Manager.

These are the rule files of v2ray/xray: a geosite.dat holds domain lists and a
geoip.dat holds subnet lists, both split into named categories (YOUTUBE,
RU-BLOCKED...). A category becomes one list on the router, holding the domains
of the geosite category and the subnets of the geoip category of the same name.

Both files are protobuf messages, read here without a protobuf library:
  GeoSiteList { repeated GeoSite entry = 1; }
  GeoSite     { string country_code = 1; repeated Domain domain = 2; }
  Domain      { Type type = 1; string value = 2; ... }   Plain=0 Regex=1 Domain=2 Full=3
  GeoIPList   { repeated GeoIP entry = 1; }
  GeoIP       { string country_code = 1; repeated CIDR cidr = 2; ... }
  CIDR        { bytes ip = 1; uint32 prefix = 2; }

The files carry no version, so a change is noticed by the sha256 published next
to each of them: that small file is fetched, and the large one only when the hash
differs from the copy kept on disk.
"""

import hashlib
import json
import os
import threading
import time
import urllib.request
from typing import Optional

KINDS = ("geosite", "geoip")

# Mirrors in order of preference. GitHub comes first: jsDelivr serves a branch
# with a delay of hours to days, so its hash may name an older file. Each file is
# checked against the hash from the same mirror.
SOURCES = {
    "runetfreedom": {
        "url": "https://github.com/runetfreedom/russia-v2ray-rules-dat",
        "mirrors": {
            "geosite": [
                "https://github.com/runetfreedom/russia-v2ray-rules-dat/releases/latest/download/geosite.dat",
                "https://raw.githubusercontent.com/runetfreedom/russia-v2ray-rules-dat/release/geosite.dat",
                # No jsDelivr: it refuses a file this large (86 MB)
            ],
            "geoip": [
                "https://github.com/runetfreedom/russia-v2ray-rules-dat/releases/latest/download/geoip.dat",
                "https://raw.githubusercontent.com/runetfreedom/russia-v2ray-rules-dat/release/geoip.dat",
                "https://cdn.jsdelivr.net/gh/runetfreedom/russia-v2ray-rules-dat@release/geoip.dat",
            ],
        },
        "hash_suffix": ".sha256sum",
    },
    "hydraponique": {
        "url": "https://github.com/hydraponique/roscomvpn-geosite",
        "mirrors": {
            "geosite": [
                "https://github.com/hydraponique/roscomvpn-geosite/releases/latest/download/geosite.dat",
                "https://raw.githubusercontent.com/hydraponique/roscomvpn-geosite/master/release/geosite.dat",
                "https://cdn.jsdelivr.net/gh/hydraponique/roscomvpn-geosite@master/release/geosite.dat",
            ],
            "geoip": [
                "https://github.com/hydraponique/roscomvpn-geoip/releases/latest/download/geoip.dat",
                "https://raw.githubusercontent.com/hydraponique/roscomvpn-geoip/master/release/geoip.dat",
                "https://cdn.jsdelivr.net/gh/hydraponique/roscomvpn-geoip@master/release/geoip.dat",
            ],
        },
        "hash_suffix": ".sha256",
    },
}

# A category with more entries than this is not offered: 300 entries go into one
# group, and writing a group takes the router about 3 s.
ENTRY_LIMIT = 3000
# Subnets only of IPv4. Whether the router takes IPv6 subnets in a domain group
# is not known, and most categories hold more of them than of IPv4.
INCLUDE_IPV6 = False
# How long a file is used before its hash is asked for again
FILE_CHECK_INTERVAL = 10 * 60

_USER_AGENT = "Keenetic-Manager/1.0"
SEPARATOR = ":"  # slug = "{source}:{CATEGORY}"

_state: Optional[dict] = None              # {"source/kind": {"sha256", "checked"}}
_state_lock = threading.Lock()
_file_locks: dict[str, threading.Lock] = {}
_index_cache: dict[tuple, dict] = {}       # (path, sha256) -> {name: (start, end)}
_count_cache: dict[tuple, dict] = {}       # (path, sha256) -> {name: usable entries}
_failed_at: dict[str, float] = {}          # "source/kind" -> time every mirror last failed
RETRY_INTERVAL = 5 * 60                    # how long a copy on disk is used after that


# --- Slugs ---

def make_slug(source: str, category: str) -> str:
    return f"{source}{SEPARATOR}{category}"


def split_slug(slug: str) -> tuple[str, str]:
    source, sep, category = slug.partition(SEPARATOR)
    if not sep or source not in SOURCES or not category:
        raise ValueError(f"Not a geo list: '{slug}'")
    return source, category


# --- Protobuf ---

def _varint(b: bytes, i: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if i >= len(b):
            raise ValueError("truncated varint")
        c = b[i]
        i += 1
        result |= (c & 0x7F) << shift
        if c < 0x80:
            return result, i
        shift += 7


def _fields(b: bytes, start: int = 0, end: int = None):
    """Yield (field number, value) of a message: an int for a varint, a (start,
    end) span for a length-delimited field. Other wire types are skipped."""
    i = start
    end = len(b) if end is None else end
    while i < end:
        key, i = _varint(b, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _varint(b, i)
            yield field, value
        elif wire == 2:
            n, i = _varint(b, i)
            if i + n > end:
                raise ValueError("truncated field")
            yield field, (i, i + n)
            i += n
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            raise ValueError(f"unsupported wire type {wire}")
    if i != end:
        raise ValueError("truncated message")


def _index(b: bytes) -> dict[str, tuple[int, int]]:
    """{category name: span of its entry} of a GeoSiteList or GeoIPList."""
    result = {}
    for field, span in _fields(b):
        if field != 1 or not isinstance(span, tuple):
            continue
        for sub, value in _fields(b, *span):
            if sub == 1 and isinstance(value, tuple):
                result[b[value[0]:value[1]].decode("utf-8", "replace").upper()] = span
                break
    return result


def _site_entries(b: bytes, span: tuple[int, int], count_only: bool = False):
    """Domains of a GeoSite. Domain and Full rules only: the router matches a
    domain with its subdomains, which is what a Domain rule means, and has no
    counterpart for Plain (keyword) and Regex rules."""
    out = 0 if count_only else []
    for field, value in _fields(b, *span):
        if field != 2 or not isinstance(value, tuple):
            continue
        kind, text = 0, None
        for sub, v in _fields(b, *value):
            if sub == 1 and isinstance(v, int):
                kind = v
            elif sub == 2 and isinstance(v, tuple) and not count_only:
                text = b[v[0]:v[1]].decode("utf-8", "replace")
        if kind not in (2, 3):
            continue
        if count_only:
            out += 1
        elif text:
            out.append(text.strip().lower())
    return out


def _format_cidr(ip: bytes, prefix: int) -> Optional[str]:
    if len(ip) == 4:
        prefix = 32 if prefix is None else prefix
        addr = ".".join(str(x) for x in ip)
        return addr if prefix == 32 else f"{addr}/{prefix}"
    if len(ip) == 16 and INCLUDE_IPV6:
        import ipaddress
        prefix = 128 if prefix is None else prefix
        addr = str(ipaddress.IPv6Address(ip))
        return addr if prefix == 128 else f"{addr}/{prefix}"
    return None


def _ip_entries(b: bytes, span: tuple[int, int], count_only: bool = False):
    """Subnets of a GeoIP, as a.b.c.d/prefix (a bare address for a /32)."""
    out = 0 if count_only else []
    for field, value in _fields(b, *span):
        if field != 2 or not isinstance(value, tuple):
            continue
        ip, prefix = b"", None
        for sub, v in _fields(b, *value):
            if sub == 1 and isinstance(v, tuple):
                ip = b[v[0]:v[1]]
            elif sub == 2 and isinstance(v, int):
                prefix = v
        if count_only:
            if len(ip) == 4 or (len(ip) == 16 and INCLUDE_IPV6):
                out += 1
            continue
        text = _format_cidr(ip, prefix)
        if text:
            out.append(text)
    return out


def parse_category(kind: str, data: bytes, category: str) -> list[str]:
    """Entries of one category of a file's contents, [] if it has no such category."""
    span = _index(data).get(category.upper())
    if span is None:
        return []
    return _site_entries(data, span) if kind == "geosite" else _ip_entries(data, span)


# --- Files on disk ---

def _cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "keenetic-manager", "geodat")


def _file_path(source: str, kind: str) -> str:
    return os.path.join(_cache_dir(), f"{source}-{kind}.dat")


def _state_path() -> str:
    return os.path.join(_cache_dir(), "state.json")


def _load_state() -> dict:
    """Call with _state_lock held."""
    global _state
    if _state is None:
        try:
            with open(_state_path()) as fp:
                data = json.load(fp)
        except (OSError, ValueError):
            data = {}
        _state = {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
    return _state


def _save_state():
    """Call with _state_lock held. A failure costs one extra hash check."""
    try:
        os.makedirs(_cache_dir(), exist_ok=True)
        tmp = _state_path() + ".tmp"
        with open(tmp, "w") as fp:
            json.dump(_load_state(), fp)
        os.replace(tmp, _state_path())
    except OSError as e:
        print(f"[geodat] Failed to save state: {e}")


def _get(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_hash(text: bytes) -> str:
    """The hash from a sha256sum line: "<hex>  <name>"."""
    token = text.decode("ascii", "replace").strip().split()[0].lower() if text.strip() else ""
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError("not a sha256 file")
    return token


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_file(source: str, kind: str, max_age: float = FILE_CHECK_INTERVAL, now: float = None) -> str:
    """Path of an up-to-date copy of a source's file, downloading it if its hash
    changed. A copy checked within `max_age` seconds is used as it is. If no mirror
    answers, an older copy is used rather than none. Raises ValueError if there is
    no copy at all. Blocks: run it off the main thread."""
    if source not in SOURCES:
        raise ValueError(f"Unknown source '{source}'")
    key = f"{source}/{kind}"
    path = _file_path(source, kind)
    with _state_lock:
        lock = _file_locks.setdefault(key, threading.Lock())

    with lock:
        now = time.time() if now is None else now
        with _state_lock:
            entry = dict(_load_state().get(key, {}))
        have = os.path.exists(path) and entry.get("sha256")
        if have and 0 <= now - entry.get("checked", 0) < max_age:
            return path
        if have and 0 <= now - _failed_at.get(key, -RETRY_INTERVAL) < RETRY_INTERVAL:
            return path  # the mirrors just failed: do not wait for them again

        info = SOURCES[source]
        errors = []
        for url in info["mirrors"][kind]:
            try:
                expected = _parse_hash(_get(url + info["hash_suffix"], timeout=15))
            except Exception as e:
                errors.append(f"{url.split('/')[2]}: {e}")
                continue
            if have and expected == entry["sha256"]:
                _record(key, expected, now)
                return path
            try:
                data = _get(url, timeout=120)
            except Exception as e:
                errors.append(f"{url.split('/')[2]}: {e}")
                continue
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected:
                errors.append(f"{url.split('/')[2]}: hash mismatch")
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as fp:
                fp.write(data)
            os.replace(tmp, path)
            print(f"[geodat] Downloaded {key} from {url.split('/')[2]} ({len(data)} bytes)")
            _record(key, expected, now)
            return path

        _failed_at[key] = now
        if have:
            print(f"[geodat] Update check failed for {key}, using the copy on disk: {'; '.join(errors)}")
            return path
        raise ValueError(f"Failed to download {kind} of {source}: {'; '.join(errors)}")


def _record(key: str, sha: str, now: float):
    with _state_lock:
        _load_state()[key] = {"sha256": sha, "checked": now}
        _save_state()


def _read(source: str, kind: str, max_age: float) -> tuple[bytes, dict, tuple]:
    """Contents, category index and cache key of a file, the index cached per hash."""
    path = ensure_file(source, kind, max_age)
    with open(path, "rb") as fp:
        data = fp.read()
    key = (path, hashlib.sha256(data).hexdigest())
    index = _index_cache.get(key)
    if index is None:
        index = _index(data)
        # One version of each file is kept
        for cache in (_index_cache, _count_cache):
            for k in [k for k in cache if k[0] == path]:
                del cache[k]
        _index_cache[key] = index
    return data, index, key


# --- Public API ---

def get_categories(source: str, max_age: float = FILE_CHECK_INTERVAL) -> list[dict]:
    """Categories of a source, sorted by name, each as {"name", "domains", "ips"}:
    the number of entries the router would get from geosite and geoip. A file that
    cannot be had is reported as an error only if both are missing.
    Blocks for seconds on a large file: run it off the main thread."""
    counts: dict[str, dict] = {}
    errors = []
    for kind in KINDS:
        try:
            data, index, key = _read(source, kind, max_age)
        except Exception as e:
            errors.append(str(e))
            continue
        count = _site_entries if kind == "geosite" else _ip_entries
        field = "domains" if kind == "geosite" else "ips"
        sizes = _count_cache.get(key)
        if sizes is None:
            sizes = {name: count(data, span, count_only=True) for name, span in index.items()}
            _count_cache[key] = sizes
        for name, n in sizes.items():
            entry = counts.setdefault(name, {"name": name, "domains": 0, "ips": 0})
            entry[field] = n
    if len(errors) == len(KINDS):
        raise ValueError("; ".join(errors))
    return sorted((c for c in counts.values() if c["domains"] or c["ips"]), key=lambda c: c["name"])


def fetch_category(slug: str, max_age: float = FILE_CHECK_INTERVAL) -> tuple[list[str], int]:
    """Entries of a category, its domains first and then its subnets.
    Returns (entries, total). Raises ValueError if a file cannot be had, or the
    category is in neither file: the result is complete or an error."""
    source, category = split_slug(slug)
    entries = []
    found = False
    for kind in KINDS:
        data, index, _key = _read(source, kind, max_age)
        span = index.get(category.upper())
        if span is None:
            continue
        found = True
        entries += _site_entries(data, span) if kind == "geosite" else _ip_entries(data, span)
    if not found:
        raise ValueError(f"'{category}' is not in {source}")
    entries = list(dict.fromkeys(e for e in entries if e))
    if not entries:
        raise ValueError(f"'{slug}' contains no entries the router can use")
    return entries, len(entries)
