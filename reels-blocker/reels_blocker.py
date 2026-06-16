"""
reels_blocker — a mitmproxy addon that blocks short-form video ("reels")
at the network level.

It inspects each HTTP(S) request flowing through the proxy and drops the ones
that target a reels surface (Instagram Reels, Facebook Reels, YouTube Shorts,
TikTok, Snapchat Spotlight) using the rules in patterns.py. Everything else
passes through untouched, so the rest of each app keeps working.

Why a proxy and not just DNS?
  Reels share domains with features people want to keep (DMs, the main feed).
  DNS/hosts blocking can only nuke an entire domain, so it cannot separate
  "reels" from "the rest of Instagram". A filtering proxy can match the
  specific API endpoints and is the only clean way to block reels alone.
  Whole-app products (TikTok) are still handled by host rules / DNS.

Usage:
  mitmdump -s reels_blocker.py

Then point your device/router at the proxy (default :8080) and trust the
mitmproxy CA on the client so HTTPS can be inspected. See README.md.
"""

import logging
import time

from mitmproxy import http

from matcher import match

logger = logging.getLogger("reels_blocker")


class ReelsBlocker:
    def __init__(self) -> None:
        # Lightweight in-memory counters so you can see it working.
        self.blocked = 0
        self.allowed = 0
        self._started = time.time()

    # -- mitmproxy hook ----------------------------------------------------
    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        # path + query, lowercased once for all the substring checks below.
        target = (flow.request.path or "").lower()

        reason = match(host, target)
        if reason is None:
            self.allowed += 1
            return

        self.blocked += 1
        logger.info("BLOCKED %s  %s%s", reason, host, flow.request.path)

        # Respond directly so the request never leaves the proxy. A 204 keeps
        # apps happy (no error spinner) while returning no reels content.
        flow.response = http.Response.make(
            204,
            b"",
            {"X-Blocked-By": "reels-blocker", "X-Block-Reason": reason},
        )

    # -- lifecycle ---------------------------------------------------------
    def done(self) -> None:
        elapsed = time.time() - self._started
        logger.info(
            "reels-blocker stopping: blocked=%d allowed=%d over %.0fs",
            self.blocked,
            self.allowed,
            elapsed,
        )


addons = [ReelsBlocker()]
