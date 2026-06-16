"""
Tests for the reels matcher. Run with:  python -m pytest test_matcher.py
(or simply: python test_matcher.py)
"""

from matcher import match


# (host, path, should_block)
CASES = [
    # --- blocked: reels surfaces ---
    ("i.instagram.com", "/api/v1/clips/home/", True),
    ("i.instagram.com", "/api/v1/feed/reels_tray/", True),
    ("www.instagram.com", "/reels/abc123/", True),
    ("m.facebook.com", "/reel/123456/", True),
    ("www.youtube.com", "/shorts/dQw4w9WgXcQ", True),
    ("youtubei.googleapis.com", "/youtubei/v1/reel/reel_watch_sequence", True),
    ("www.tiktok.com", "/foryou", True),               # whole-host block
    ("api.tiktok.com", "/anything", True),             # suffix host block
    ("www.snapchat.com", "/spotlight/xyz", True),

    # --- allowed: the rest of each app keeps working ---
    ("i.instagram.com", "/api/v1/direct_v2/inbox/", False),   # DMs
    ("www.instagram.com", "/api/v1/feed/timeline/", False),   # main feed
    ("m.facebook.com", "/api/graphql/", False),               # generic graphql
    ("www.youtube.com", "/watch?v=dQw4w9WgXcQ", False),       # normal video
    ("www.snapchat.com", "/add/friend", False),
    ("example.com", "/reels/", False),                        # unrelated host
]


def run():
    failures = 0
    for host, path, expected in CASES:
        reason = match(host, path)
        got = reason is not None
        status = "ok" if got == expected else "FAIL"
        if got != expected:
            failures += 1
        print(f"[{status}] {host}{path}  -> {reason}")
    print()
    if failures:
        print(f"{failures} failing case(s)")
        raise SystemExit(1)
    print(f"all {len(CASES)} cases passed")


# pytest-style assertions too, so `pytest` discovers them.
def test_all_cases():
    for host, path, expected in CASES:
        assert (match(host, path) is not None) == expected, (host, path)


if __name__ == "__main__":
    run()
