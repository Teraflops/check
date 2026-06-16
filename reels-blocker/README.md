# reels-blocker

Block short-form video ("reels") at the network level — Instagram Reels,
Facebook Reels, YouTube Shorts, TikTok, and Snapchat Spotlight — while leaving
the rest of each app (DMs, the main feed, search, normal videos) working.

It runs as a filtering HTTP/HTTPS proxy you point your phone, laptop, or whole
router at. For services that *only* serve short-form video (TikTok), there's
also a DNS sinkhole config so you don't even need the proxy.

## Why a proxy, not just a hosts/DNS blocklist?

Reels share domains with features you want to keep. `instagram.com` serves both
your DMs and Reels; `youtube.com` serves both normal videos and Shorts. DNS or
`/etc/hosts` blocking can only kill an *entire* domain, so it can't separate
"reels" from "the rest of the app". A proxy can see the specific request path
(e.g. `/api/v1/clips/`, `/shorts/`, `/reel/`) and block just those.

So this project uses two layers:

| Layer | File | Blocks |
|-------|------|--------|
| Filtering proxy (mitmproxy) | `reels_blocker.py` + `patterns.py` | Reels endpoints on apps you keep using (Instagram/Facebook/YouTube/Snapchat) |
| DNS sinkhole (dnsmasq) | `dnsmasq/reels-block.conf` | Whole short-form-only services (TikTok) |

## Setup — filtering proxy

1. Install dependencies (Python 3.9+):

   ```bash
   pip install -r requirements.txt
   ```

2. Start the proxy:

   ```bash
   ./run.sh            # listens on 0.0.0.0:8080
   PORT=9090 ./run.sh  # custom port
   ```

3. Point the client at the proxy:
   - **Phone:** Wi-Fi settings → configure HTTP proxy → this machine's IP, port 8080.
   - **Whole network:** set the proxy on your router, or run this host as the
     gateway.

4. Trust the TLS certificate so HTTPS can be inspected (reels are all HTTPS):
   with the proxy active, open <http://mitm.it> on the client and follow the
   instructions to install + trust the mitmproxy CA. Without this, HTTPS
   traffic can't be filtered.

The proxy logs each block, e.g.:

```
BLOCKED Instagram Reels:/api/v1/clips/  i.instagram.com/api/v1/clips/home/
```

Blocked requests get an empty `204 No Content` response, so apps show no reels
instead of an error spinner.

## Setup — DNS sinkhole (optional, for TikTok etc.)

```bash
sudo cp dnsmasq/reels-block.conf /etc/dnsmasq.d/
sudo systemctl restart dnsmasq
```

Then set your LAN's DNS server to this host. (Works the same on a Pi-hole:
drop the `address=` lines into a custom dnsmasq config.)

## Tuning the rules

All matching lives in `patterns.py`:

- `HOST_BLOCK` — hosts dropped entirely (short-form-only services/CDNs).
- `PATH_BLOCK` — host + URL-path fragments; a request is blocked only when both
  match, so you can keep an app while killing its reels surface.

Edit those lists to add a service or loosen a rule. Verify your changes with:

```bash
python3 test_matcher.py        # or: python -m pytest test_matcher.py
```

`test_matcher.py` asserts both that reels endpoints are blocked **and** that
normal traffic (DMs, main feed, normal YouTube videos) still passes.

## Notes / limitations

- Native apps that use certificate pinning may reject the mitmproxy CA. Mobile
  browsers and most first-party apps work; a pinned app may need the DNS layer
  or a patched client instead.
- Endpoint paths can change as the apps evolve; update `patterns.py` when a
  reels surface starts leaking through.
- This is meant for blocking content on devices/networks you control.
