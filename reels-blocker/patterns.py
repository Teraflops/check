"""
Matching rules for short-form video ("reels") network traffic.

The goal is to block ONLY the short-form video surfaces (Instagram Reels,
Facebook Reels, YouTube Shorts, TikTok, Snapchat Spotlight) while leaving the
rest of each app working (DMs, the main feed, search, etc.).

Two kinds of rules are used:

  HOST_BLOCK   - request is dropped if the destination host matches. Used for
                 services/CDNs that exist *only* to serve short-form video.

  PATH_BLOCK   - request is dropped only when BOTH the host and a URL path
                 fragment match. Used for apps where reels share a domain with
                 features we want to keep alive, so we discriminate by endpoint.

Patterns are matched case-insensitively. Host patterns match if they appear as
a dot-delimited suffix of the request host (so "tiktok.com" also blocks
"www.tiktok.com" and "api.tiktok.com").
"""

# ---------------------------------------------------------------------------
# Whole-host blocks: these domains serve short-form video exclusively, so it is
# safe to drop every request to them.
# ---------------------------------------------------------------------------
HOST_BLOCK = [
    # TikTok is entirely a short-form video product.
    "tiktok.com",
    "tiktokv.com",
    "tiktokcdn.com",
    "tiktokcdn-us.com",
    "byteoversea.com",
    "ibytedtos.com",
    "muscdn.com",

    # Instagram Reels media/CDN edges that only appear in reels playback.
    # (Kept conservative — the path rules below do most of the Instagram work.)
]

# ---------------------------------------------------------------------------
# Host + path blocks: reels live on the same domains as features we keep.
# A request is blocked when the host matches one of `hosts` AND the request
# path/query contains one of `paths`.
# ---------------------------------------------------------------------------
PATH_BLOCK = [
    # --- Instagram ------------------------------------------------------
    {
        "name": "Instagram Reels",
        "hosts": [
            "instagram.com",
            "i.instagram.com",
            "b.i.instagram.com",
            "graph.instagram.com",
        ],
        "paths": [
            "/api/v1/clips/",            # reels ("clips") API surface
            "/api/v1/feed/reels_tray/",  # stories+reels tray
            "/api/v1/feed/reels_media/",
            "/api/v1/feed/clips_",
            "/reels/",
            "/reel/",
            "clips_media",
            "reels_media",
        ],
    },
    # --- Facebook -------------------------------------------------------
    {
        "name": "Facebook Reels",
        "hosts": [
            "facebook.com",
            "m.facebook.com",
            "graph.facebook.com",
            "web.facebook.com",
        ],
        "paths": [
            "/reel/",
            "/reels/",
            "/watch/reels/",
            "reels_video",
            "shortform",
        ],
    },
    # --- YouTube Shorts -------------------------------------------------
    {
        "name": "YouTube Shorts",
        "hosts": [
            "youtube.com",
            "m.youtube.com",
            "youtubei.googleapis.com",
        ],
        "paths": [
            "/shorts/",
            "/youtubei/v1/reel/",        # reel_watch_sequence / reel_item_watch
            "reelwatchendpoint",
        ],
    },
    # --- Snapchat Spotlight --------------------------------------------
    {
        "name": "Snapchat Spotlight",
        "hosts": [
            "snapchat.com",
        ],
        "paths": [
            "/spotlight/",
        ],
    },
]
