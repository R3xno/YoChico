"""
Telegram Mini App server for HeXa Auction.

- GET /            -> the Mini App (webapp/index.html)
- GET /api/items   -> current auction items as JSON (read only, no user ids)

Runs inside the bot's event loop. Set these environment variables:
    WEBAPP_URL   public HTTPS url of this server (Telegram requires https),
                 e.g. https://auction.example.com
    WEBAPP_PORT  port to listen on (default 8080)
    WEBAPP_HOST  host to bind (default 0.0.0.0)

Put a reverse proxy / tunnel (nginx, Caddy, cloudflared, ngrok) with HTTPS in
front of it and point WEBAPP_URL at that address.
"""
import os
import re
from aiohttp import web

from bot import auction_pokes, bot_username

WEBAPP_URL = os.environ.get("WEBAPP_URL", "").rstrip("/")
WEBAPP_HOST = os.environ.get("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = int(os.environ.get("WEBAPP_PORT", "8080"))
AUCTION_CHANNEL = "HexaAuction"  # keep in sync with pokemon_adder.py

INDEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp", "index.html")
TYPE_NAMES = {0: "legendary", 1: "non-legendary", 2: "shiny", 3: "tm"}


def _next_min_bid(current):
    if current <= 50000:
        return current + 500
    if current <= 100000:
        return current + 1000
    return current + 2000


def _sprite_slug(name):
    """'Mega Charizard X' -> 'charizard-mega-x' style is not guessable, so
    keep it simple: lowercase, strip accents/symbols, spaces -> hyphens.
    The front end falls back to a Poké Ball if the sprite is missing."""
    s = str(name).lower().strip()
    s = s.replace("é", "e").replace("♀", "-f").replace("♂", "-m")
    s = re.sub(r"[.'’:]", "", s)
    s = re.sub(r"\s+", "-", s)
    return re.sub(r"[^a-z0-9\-]", "", s)


def _serialize(p):
    bids = p.get("bids") or []
    base = p.get("base", 0) or 0
    current = bids[-1] if bids else base
    mid = p.get("msg_id")
    if mid is None:
        try:
            mid = int(str(p.get("link", "")).rstrip("/").split("/")[-1])
        except (ValueError, TypeError):
            mid = None
    tipe = p.get("tipe", 1)
    return {
        "token": p.get("token"),
        "name": p.get("pokemon_name", "Unknown"),
        "slug": _sprite_slug(p.get("pokemon_name", "")),
        "nature": p.get("nature", ""),
        "level": p.get("level"),
        "type": TYPE_NAMES.get(tipe, "non-legendary"),
        "boosted": p.get("boosted"),
        "info": p.get("info"),          # TM description
        "base": base,
        "current": current,
        "bids": len(bids),
        "next_min": _next_min_bid(current),
        "post": f"https://t.me/{AUCTION_CHANNEL}/{mid}" if mid else None,
        "bid_url": f"https://t.me/{str(bot_username).lstrip('@')}?start={p.get('token')}",
    }


async def index(request):
    return web.FileResponse(INDEX_PATH, headers={"Cache-Control": "no-cache"})


async def api_items(request):
    items = []
    for p in auction_pokes.find({}):
        try:
            if p.get("token"):
                items.append(_serialize(p))
        except Exception as e:
            print("webapp serialize error:", e)
    return web.json_response(
        {"items": items},
        headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
    )


_runner = None


async def start_webapp():
    """Start the web server inside the bot's running loop."""
    global _runner
    if _runner is not None:
        return
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/items", api_items)
    _runner = web.AppRunner(app)
    await _runner.setup()
    site = web.TCPSite(_runner, WEBAPP_HOST, WEBAPP_PORT)
    await site.start()
    print(f"Web app listening on {WEBAPP_HOST}:{WEBAPP_PORT} (public url: {WEBAPP_URL or 'NOT SET'})")
