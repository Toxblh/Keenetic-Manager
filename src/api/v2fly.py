"""
v2fly domain list integration for Keenetic-Manager.
Fetches available domain lists from v2fly/domain-list-community and downloads domain content.
Uses jsDelivr CDN API for listing (no rate limit) with bundled fallback.
"""

import json
import os
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional

V2FLY_DATA_URL = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/"
V2FLY_CDN_URL = "https://cdn.jsdelivr.net/gh/v2fly/domain-list-community@master/data/"
JSDELIVR_API = "https://data.jsdelivr.com/v1/packages/gh/v2fly/domain-list-community@master"
DOMAIN_LIMIT = 300

# Path to bundled list (shipped with app, installed alongside .py files)
_BUNDLED_LIST_PATH = os.path.join(os.path.dirname(__file__), "v2fly_list.json")

# Cache
_list_names_cache: Optional[list[str]] = None
_list_names_cache_time: float = 0
CACHE_TTL = 24 * 60 * 60  # 24 hours


def _load_bundled_list() -> list[str]:
    """Load pre-bundled v2fly domain list from the JSON file."""
    try:
        with open(_BUNDLED_LIST_PATH) as fp:
            return json.load(fp)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def get_available_lists() -> list[str]:
    """Fetch list of all available domain lists from v2fly/domain-list-community.
    Uses jsDelivr CDN API (no rate limit), falls back to bundled list.
    Returns sorted list of domain file names."""
    global _list_names_cache, _list_names_cache_time

    if _list_names_cache is not None and (time.time() - _list_names_cache_time) < CACHE_TTL:
        return _list_names_cache

    # Try jsDelivr API first (no auth, no rate limit)
    try:
        req = urllib.request.Request(
            JSDELIVR_API,
            headers={"User-Agent": "Keenetic-Manager/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        names = []
        for entry in data.get("files", []):
            if entry.get("name") == "data" and entry.get("type") == "directory":
                for f in entry.get("files", []):
                    if f.get("type") == "file":
                        name = f["name"]
                        if "/" not in name:
                            names.append(name)
        names.sort()

        if names:
            _list_names_cache = names
            _list_names_cache_time = time.time()
            return names
    except Exception as e:
        print(f"[v2fly] jsDelivr API failed: {e}")

    # Fallback to bundled list
    bundled = _load_bundled_list()
    if bundled:
        print(f"[v2fly] Using bundled list ({len(bundled)} names)")
        _list_names_cache = bundled
        _list_names_cache_time = time.time()
        return bundled

    return []


def search_lists(query: str, limit: int = 20) -> list[str]:
    """Search available v2fly lists by substring. Returns up to `limit` matches."""
    query = query.lower().strip()
    if not query:
        return get_available_lists()[:limit]

    results = []
    for name in get_available_lists():
        if query in name.lower():
            results.append(name)
            if len(results) >= limit:
                break
    return results


def fetch_domain_list(slug: str) -> tuple[list[str], int]:
    """Download and parse a v2fly domain list, following its includes.
    Returns (domains, total_lines). Tries CDN first, then GitHub raw.
    Raises ValueError if the list or any list it includes cannot be downloaded,
    or if it yields no domains: the result is either complete or an error."""
    text, _ = _fetch_raw(slug)
    domains, total, _ = _parse_domain_text(text, slug)
    if not domains:
        raise ValueError(f"v2fly list '{slug}' contains no domains")
    return domains, total


def _parse_domain_text(text: str, source: str, depth: int = 0, _seen_includes: set = None,
                       _attrs: tuple = ((), ())) -> tuple[list[str], int, int]:
    """Parse v2fly domain list text recursively.
    `_attrs` is (required, excluded) attribute names from an `include:list @a @-b`
    directive: only rules carrying every required attribute and none of the
    excluded ones are kept.
    Returns (domains, total_lines, includes_count)."""
    if _seen_includes is None:
        _seen_includes = set()

    if depth > 10:
        raise ValueError(f"Include depth limit reached in '{source}'")

    required, excluded = _attrs
    domains = []
    includes_count = 0
    total_lines = 0

    for raw_line in text.replace("\ufeff", "").split("\n"):
        # Strip comments
        line = raw_line.split("#")[0].strip()
        if not line:
            continue
        total_lines += 1

        # Handle include directives: "include:list", "include:list @attr @-attr", "include list"
        if line.startswith("include:") or line.startswith("include "):
            tokens = line[len("include:"):].split()
            if not tokens:
                continue
            include_target = tokens[0]
            sub_required = tuple(required) + tuple(t[1:] for t in tokens[1:] if t.startswith("@") and not t.startswith("@-"))
            sub_excluded = tuple(excluded) + tuple(t[2:] for t in tokens[1:] if t.startswith("@-"))
            seen_key = (include_target, sub_required, sub_excluded)
            if seen_key not in _seen_includes:
                _seen_includes.add(seen_key)
                includes_count += 1
                # A failed include raises: a partial list must not look complete
                sub_text, _ = _fetch_raw(include_target)
                sub_domains, sub_total, sub_includes = _parse_domain_text(
                    sub_text, include_target, depth + 1, _seen_includes, (sub_required, sub_excluded)
                )
                domains.extend(sub_domains)
                total_lines += sub_total
                includes_count += sub_includes
            continue

        # Skip keyword and regexp rules
        if line.startswith("keyword:") or line.startswith("regexp:"):
            continue

        # Strip domain:/full: prefix
        if ":" in line:
            prefix = line.split(":", 1)[0]
            if prefix in ("domain", "full"):
                line = line.split(":", 1)[1]

        # First token is the domain, the rest are @attributes
        tokens = line.split()
        if not tokens or tokens[0].startswith("@"):
            continue
        attrs = {t[1:] for t in tokens[1:] if t.startswith("@")}
        if any(a not in attrs for a in required) or any(a in attrs for a in excluded):
            continue
        domains.append(tokens[0].lower())

    # Deduplicate
    return list(dict.fromkeys(domains)), total_lines, includes_count


# Mirror that answered last, tried first: when one is unreachable, waiting for
# its timeout on every file of a list with dozens of includes takes minutes.
_preferred_mirror = 0


def _fetch_raw(slug: str) -> tuple[str, str]:
    """Fetch raw text of a v2fly list. Tries CDN and GitHub raw, last working one first."""
    global _preferred_mirror
    bases = [V2FLY_CDN_URL, V2FLY_DATA_URL]
    order = [_preferred_mirror] + [i for i in range(len(bases)) if i != _preferred_mirror]
    last_err = None
    for i in order:
        url = bases[i] + urllib.parse.quote(slug)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Keenetic-Manager/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("utf-8")
                print(f"[v2fly] Fetched {slug} from {url.split('/')[2]}")
                _preferred_mirror = i
                return text, slug
        except Exception as e:
            last_err = e
            continue
    raise ValueError(f"Failed to fetch '{slug}': {last_err}")


def check_list_updated(slug: str, stored_date: str) -> bool:
    """Check if a v2fly list has been updated since the stored date.
    stored_date format: DDMMYY (e.g. '240726').
    Returns True if an update is needed (list is newer than stored date)."""
    import datetime

    if not stored_date or len(stored_date) != 6:
        return True  # No date stored, needs update

    try:
        stored = datetime.datetime.strptime(stored_date, "%d%m%y")
    except ValueError:
        return True

    # Check GitHub API for last commit date of the file
    api_url = f"https://api.github.com/repos/v2fly/domain-list-community/commits?path=data/{slug}&per_page=1"
    try:
        req = urllib.request.Request(api_url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Keenetic-Manager/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json
            commits = json.loads(resp.read().decode())
            if commits and len(commits) > 0:
                commit_date_str = commits[0]["commit"]["committer"]["date"]
                commit_date = datetime.datetime.strptime(
                    commit_date_str[:10], "%Y-%m-%d"
                )
                return commit_date.date() > stored.date()
    except Exception as e:
        print(f"[v2fly] Failed to check updates for {slug}: {e}")
        return False  # Can't determine, assume no update needed

    return False
