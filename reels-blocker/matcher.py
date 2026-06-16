"""
Pure matching logic for the reels blocker — no mitmproxy dependency, so it can
be unit tested on its own (see test_matcher.py).
"""

from patterns import HOST_BLOCK, PATH_BLOCK


def host_matches(host: str, pattern: str) -> bool:
    """True if `pattern` equals `host` or is a dot-delimited suffix of it."""
    host = host.lower()
    pattern = pattern.lower()
    return host == pattern or host.endswith("." + pattern)


def match(host: str, path: str):
    """
    Decide whether a request should be blocked.

    Returns a human-readable reason string if the request targets a reels
    surface, or None if it should be allowed through.
    """
    host = (host or "").lower()
    target = (path or "").lower()

    for pattern in HOST_BLOCK:
        if host_matches(host, pattern):
            return f"host:{pattern}"

    for rule in PATH_BLOCK:
        if not any(host_matches(host, h) for h in rule["hosts"]):
            continue
        for frag in rule["paths"]:
            if frag.lower() in target:
                return f"{rule['name']}:{frag}"

    return None
