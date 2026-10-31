"""
Fast glass-style profile card (Gengar purple theme) for the /profile command.

Needs:  pip install pillow requests
Usage:  buf = render_profile(name, username, status, approved, sold, points, avatar_bytes)
        -> io.BytesIO (JPEG)   |   status: "verified" | "unverified" | "admin"
        approved / sold = [legendary, non-legendary, shiny, tms]

Why it is fast
--------------
Everything that never changes (background, blurred glass panels, shadows, star, labels) is rendered
ONCE in a background thread at startup and kept in memory. A /profile request only copies that image
and draws the name, avatar and numbers on it (a few milliseconds). Finished cards are also kept in a
small cache, so the same profile asked twice costs nothing.
"""
import io
import math
import os
import threading
import time
import unicodedata
import zlib
from collections import OrderedDict
from functools import lru_cache

import requests
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(BASE_DIR, "fonts")
BG_CACHE = os.path.join(BASE_DIR, "profile_bg.jpg")
BG_URL = "https://envs.sh/0ul.jpg"     # the picture the old /profile used as background
BG_TINT = 0.62                          # 0 = your picture only, 1 = pure purple gradient

W, H = 1280, 560
M = 56                                  # outer margin

# Gengar palette
C_DARK = (22, 9, 44)                    # deep indigo
C_MID = (84, 44, 148)                   # body purple
C_LIGHT = (142, 82, 206)                # light violet
VEIL = (236, 220, 255)                  # glass tint
SHADOW = (8, 2, 20)
WHITE = (255, 255, 255)
MUTED = (218, 200, 245)                 # labels
NUM_COLOR = (238, 205, 255)             # Auction Points number
NUM_GLOW = (178, 96, 255)
STAR_COLOR = (255, 112, 168)            # Gengar's eyes
STATUS_STYLE = {
    "verified": ("VERIFIED", (110, 236, 162)),
    "unverified": ("UNVERIFIED", (255, 112, 132)),
    "admin": ("ADMIN", (255, 208, 110)),
}

# Layout
AV = 190                                # avatar size
AX, AY = M, M
PC = (724, M, W - M, M + AV)            # Auction Points card
SP = (M, 282, W - M, 504)               # stats panel
LABEL_W = 230                           # row-label column inside the stats panel
HEAD_H = 66                             # header height inside the stats panel


# ---------------------------------------------------------------------------
# Fonts - loaded from ./fonts (shipped with the bot). Never downloaded while a request is waiting.
# ---------------------------------------------------------------------------
_FONT_FILES = {"light": "Poppins-Light.ttf", "medium": "Poppins-Medium.ttf", "bold": "Poppins-Bold.ttf"}
_SYSTEM_DIRS = ["/usr/share/fonts/truetype/google-fonts", "/usr/share/fonts/truetype/poppins",
                "/usr/share/fonts/poppins", os.path.expanduser("~/.fonts")]
_font_cache = {}
_fonts_checked = False


def _ensure_fonts():
    """If the fonts folder is missing, try ONCE (short timeouts) to fetch Poppins; else fall back to DejaVu."""
    global _fonts_checked
    if _fonts_checked:
        return
    _fonts_checked = True
    for fname in _FONT_FILES.values():
        if os.path.exists(os.path.join(FONT_DIR, fname)) or any(
                os.path.exists(os.path.join(d, fname)) for d in _SYSTEM_DIRS):
            continue
        try:
            os.makedirs(FONT_DIR, exist_ok=True)
            r = requests.get(f"https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/{fname}", timeout=6)
            if r.status_code == 200 and len(r.content) > 10000:
                with open(os.path.join(FONT_DIR, fname), "wb") as f:
                    f.write(r.content)
        except Exception as e:
            print("profile font download skipped:", e)
            return            # offline -> stop trying, fallback fonts are used


def font(size, weight="medium"):
    key = (size, weight)
    f = _font_cache.get(key)
    if f is not None:
        return f
    fname = _FONT_FILES[weight]
    paths = [os.path.join(FONT_DIR, fname)] + [os.path.join(d, fname) for d in _SYSTEM_DIRS]
    paths.append("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if weight == "bold"
                 else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    paths.append("arialbd.ttf" if weight == "bold" else "arial.ttf")
    for p in paths:
        try:
            f = ImageFont.truetype(p, size)
            break
        except Exception:
            f = None
    if f is None:
        try:
            f = ImageFont.load_default(size)
        except TypeError:
            f = ImageFont.load_default()
    _font_cache[key] = f
    return f


_measure = ImageDraw.Draw(Image.new("L", (1, 1)))


def text_w(s, f):
    return _measure.textlength(s, font=f)


# ---------------------------------------------------------------------------
# Small drawing helpers (all work in place on RGB images, local regions only)
# ---------------------------------------------------------------------------
S = 3   # supersampling for smooth rounded corners


@lru_cache(maxsize=24)
def rr_mask(w, h, r):
    m = Image.new("L", (w * S, h * S), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * S - 1, h * S - 1), radius=r * S, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def _shadow(img, box, radius, offset=12, blur=18, opacity=0.42):
    x0, y0, x1, y1 = box
    w, h, p = x1 - x0, y1 - y0, blur * 2
    m = Image.new("L", (w + 2 * p, h + 2 * p), 0)
    m.paste(rr_mask(w, h, radius), (p, p))
    m = m.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * opacity))
    img.paste(SHADOW, (x0 - p, y0 - p + offset), m)


def glass(img, box, radius=36, a_top=72, a_bot=36, blur=14, shadow=True):
    """Frosted glass: shadow + blurred backdrop + violet veil + thin light border."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if shadow:
        _shadow(img, box, radius)
    mask = rr_mask(w, h, radius)
    img.paste(img.crop(box).filter(ImageFilter.GaussianBlur(blur)), (x0, y0), mask)
    grad = Image.linear_gradient("L").resize((w, h), Image.BILINEAR)
    grad = grad.point(lambda v: a_top + (a_bot - a_top) * v // 255)
    img.paste(VEIL, (x0, y0), ImageChops.multiply(grad, mask))
    inner = Image.new("L", (w, h), 0)
    inner.paste(rr_mask(w - 4, h - 4, max(radius - 2, 1)), (2, 2))
    img.paste(WHITE, (x0, y0), ImageChops.subtract(mask, inner).point(lambda v: int(v * 0.6)))


def spaced(d, x, y, s, f, fill, spacing=2, anchor="l"):
    """Letter-spaced caps drawn straight on the image. y = vertical middle."""
    widths = [text_w(c, f) for c in s]
    total = sum(widths) + spacing * (len(s) - 1)
    if anchor == "m":
        x -= total / 2
    elif anchor == "r":
        x -= total
    for c, w in zip(s, widths):
        d.text((x, y), c, font=f, fill=fill, anchor="lm")
        x += w + spacing
    return total


def spaced_width(s, f, spacing=2):
    return sum(text_w(c, f) for c in s) + spacing * (len(s) - 1)


def star_points(cx, cy, r_out, r_in, n=5, rot=-90):
    pts = []
    for i in range(n * 2):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(rot + i * 180 / n)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def clean_name(s, fallback="User"):
    """Keep only characters the Latin font can draw (emoji / other scripts would show as boxes)."""
    out = []
    for ch in str(s or ""):
        if unicodedata.category(ch)[0] in "CZ" and ch != " ":
            continue
        if ord(ch) > 0x24F and not (0x2010 <= ord(ch) <= 0x2027):
            continue
        out.append(ch)
    s = " ".join("".join(out).split())
    return s or fallback


def fit_text(s, max_w, start, min_size, weight):
    size = start
    while size > min_size and text_w(s, font(size, weight)) > max_w:
        size -= 2
    f = font(size, weight)
    if text_w(s, f) > max_w:
        while len(s) > 1 and text_w(s + "…", f) > max_w:
            s = s[:-1]
        s = s.rstrip() + "…"
    return s, f


# ---------------------------------------------------------------------------
# Background (purple gradient, optionally mixed with the old /profile picture)
# ---------------------------------------------------------------------------
def _cover(img, w, h):
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    img = img.resize((max(w, round(iw * scale)), max(h, round(ih * scale))), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def _load_picture():
    """Background picture (RGB, W x H) or None. Downloaded once, then read from disk."""
    try:
        if not os.path.exists(BG_CACHE):
            r = requests.get(BG_URL, timeout=8)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/") \
                    and len(r.content) < 15_000_000:
                with open(BG_CACHE, "wb") as f:
                    f.write(r.content)
            else:
                return None
        img = Image.open(BG_CACHE)
        img.draft("RGB", (W * 2, H * 2))      # JPEG: decode at reduced size -> fast + low RAM
        img = _cover(img.convert("RGB"), W, H)
        return img
    except Exception as e:
        print("profile background unavailable:", e)
        return None


def _gradient():
    v = Image.linear_gradient("L").resize((W, H), Image.BILINEAR)
    hz = Image.linear_gradient("L").rotate(90).resize((W, H), Image.BILINEAR)
    t = Image.blend(hz, v, 0.38)                                     # diagonal 0..255
    a = Image.composite(Image.new("RGB", (W, H), C_MID), Image.new("RGB", (W, H), C_DARK),
                        t.point(lambda x: min(255, x * 2)))
    img = Image.composite(Image.new("RGB", (W, H), C_LIGHT), a, t.point(lambda x: max(0, (x - 128) * 2)))
    # soft glows, drawn small then scaled up (cheap)
    sw, sh = W // 4, H // 4
    for color, ellipse, strength in (((190, 120, 255), (sw * 0.55, -sh * 0.5, sw * 1.25, sh * 0.9), 0.55),
                                     ((255, 90, 170), (-sw * 0.3, sh * 0.5, sw * 0.4, sh * 1.5), 0.30)):
        g = Image.new("L", (sw, sh), 0)
        ImageDraw.Draw(g).ellipse(ellipse, fill=255)
        g = g.filter(ImageFilter.GaussianBlur(16)).resize((W, H), Image.BICUBIC)
        img.paste(color, (0, 0), g.point(lambda x, s=strength: int(x * s)))
    return img


def _background(pic):
    grad = _gradient()
    img = Image.blend(pic, grad, BG_TINT) if pic is not None else grad
    return Image.blend(img, Image.new("RGB", (W, H), C_DARK), 0.22)   # slight darkening for contrast


# ---------------------------------------------------------------------------
# Static layer: built once, kept in memory
# ---------------------------------------------------------------------------
_state = None
_state_lock = threading.Lock()
_retrying = False
CATS = ["LEGENDARY", "NON-LEGENDARY", "SHINY", "TMS"]
NAME_X = AX + AV + 34
NUM_X = PC[0] + 172
NUM_Y = (PC[1] + PC[3]) // 2 + 24
COL_W = (SP[2] - SP[0] - LABEL_W - 20) / 4
ROW_Y = [SP[1] + HEAD_H + 44, SP[1] + HEAD_H + 44 + 78]


def col_x(i):
    return SP[0] + LABEL_W + COL_W * i + COL_W / 2


def _build_state():
    _ensure_fonts()
    pic = _load_picture()
    img = _background(pic)

    # --- avatar ring + shadow
    rw = AV + 12
    ring = rr_mask(rw, rw, 52)
    sh = Image.new("L", (rw + 48, rw + 48), 0)
    sh.paste(ring, (24, 24))
    img.paste(SHADOW, (AX - 6 - 24, AY - 6 - 24 + 12),
              sh.filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.5)))
    img.paste(WHITE, (AX - 6, AY - 6), ring)

    # --- Auction Points card (the highlight)
    glass(img, PC, radius=40, a_top=82, a_bot=42, blur=18)
    cw, ch = PC[2] - PC[0], PC[3] - PC[1]
    wash = Image.new("L", (cw // 4, ch // 4), 0)
    ImageDraw.Draw(wash).ellipse((-30, -12, cw // 4 * 0.55, ch // 4 + 12), fill=255)
    wash = wash.filter(ImageFilter.GaussianBlur(10)).resize((cw, ch), Image.BICUBIC)
    img.paste(NUM_GLOW, (PC[0], PC[1]),
              ImageChops.multiply(wash, rr_mask(cw, ch, 40)).point(lambda v: int(v * 0.5)))
    sx, sy, box = PC[0] + 92, (PC[1] + PC[3]) // 2, 150
    big = Image.new("L", (box * 4, box * 4), 0)
    ImageDraw.Draw(big).polygon(star_points(box * 2, box * 2 + 8, 46 * 4, 19 * 4), fill=255)
    sm = big.resize((box, box), Image.LANCZOS)
    img.paste(STAR_COLOR, (sx - box // 2, sy - box // 2),
              sm.filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.85)))
    img.paste(STAR_COLOR, (sx - box // 2, sy - box // 2), sm)

    # --- stats panel
    glass(img, SP, radius=40)

    # --- static text
    d = ImageDraw.Draw(img)
    spaced(d, NUM_X + 4, PC[1] + 50, "AUCTION POINTS", font(22, "medium"), MUTED, spacing=5)
    d.line((SP[0] + 34, SP[1] + HEAD_H, SP[2] - 34, SP[1] + HEAD_H), fill=(176, 150, 214), width=2)
    head_size = 22
    while head_size > 15 and spaced_width("NON-LEGENDARY", font(head_size, "medium"), 1) > COL_W - 14:
        head_size -= 1
    hf = font(head_size, "medium")
    for i, c in enumerate(CATS):
        spaced(d, col_x(i), SP[1] + HEAD_H // 2 + 2, c, hf, MUTED, spacing=1, anchor="m")
    for label, y in zip(("APPROVED", "SOLD"), ROW_Y):
        spaced(d, SP[0] + 38, y, label, font(23, "medium"), MUTED, spacing=3)

    return {"base": img, "has_pic": pic is not None, "built": time.time(), "pills": {},
            "av_mask": rr_mask(AV, AV, 46)}


def _get_state():
    global _state
    st = _state
    if st is not None:
        if not st["has_pic"] and time.time() - st["built"] > 600:
            _retry_picture()
        return st
    with _state_lock:
        if _state is None:
            _state = _build_state()
        return _state


def _retry_picture():
    """The background picture failed earlier: retry in the background, never block a request."""
    global _retrying
    if _retrying:
        return
    _retrying = True

    def work():
        global _state, _retrying
        try:
            new = _build_state()
            if new["has_pic"]:
                _state = new
            else:
                _state["built"] = time.time()
        except Exception as e:
            print("profile background retry failed:", e)
        finally:
            _retrying = False

    threading.Thread(target=work, daemon=True).start()


def warmup():
    try:
        _get_state()
    except Exception as e:
        print("profile card warmup failed:", e)


threading.Thread(target=warmup, daemon=True).start()     # build the static layer in the background at startup


# ---------------------------------------------------------------------------
# Per-request pieces
# ---------------------------------------------------------------------------
def _pill(st, status):
    p = st["pills"].get(status)
    if p is not None:
        return p
    label, color = STATUS_STYLE.get(status, STATUS_STYLE["unverified"])
    f = font(20, "medium")
    pw, ph = int(spaced_width(label, f, 3)) + 78, 44
    px, py = NAME_X, AY + 4
    patch = st["base"].crop((px, py, px + pw, py + ph))
    glass(patch, (0, 0, pw, ph), radius=22, a_top=84, a_bot=52, blur=8, shadow=False)
    dm = Image.new("L", (72, 72), 0)
    ImageDraw.Draw(dm).ellipse((0, 0, 71, 71), fill=255)
    dm = dm.resize((18, 18), Image.LANCZOS)
    patch.paste(color, (22, ph // 2 - 9), dm)
    spaced(ImageDraw.Draw(patch), 54, ph // 2, label, f, WHITE, spacing=3)
    p = (patch, (px, py))
    st["pills"][status] = p
    return p


def _avatar(avatar_bytes, initial):
    if avatar_bytes:
        try:
            img = Image.open(io.BytesIO(avatar_bytes))
            img.draft("RGB", (AV * 2, AV * 2))
            return _cover(img.convert("RGB"), AV, AV)
        except Exception:
            pass
    g = Image.linear_gradient("L").resize((AV, AV), Image.BILINEAR)
    img = Image.composite(Image.new("RGB", (AV, AV), (60, 28, 110)), Image.new("RGB", (AV, AV), (150, 90, 215)), g)
    ImageDraw.Draw(img).text((AV / 2, AV / 2), (initial or "U")[0].upper(), font=font(96, "bold"),
                             fill=WHITE, anchor="mm")
    return img


def _compose(st, name, username, status, approved, sold, points, avatar_bytes):
    img = st["base"].copy()
    d = ImageDraw.Draw(img)

    pill, pos = _pill(st, status)
    img.paste(pill, pos)

    img.paste(_avatar(avatar_bytes, name), (AX, AY), st["av_mask"])

    max_w = PC[0] - 24 - NAME_X
    nm, nf = fit_text(name, max_w, 58, 32, "bold")
    d.text((NAME_X, AY + 66), nm, font=nf, fill=WHITE, anchor="la")
    if username:
        un, uf = fit_text("@" + username, max_w, 28, 18, "light")
        d.text((NAME_X, AY + 66 + nf.size + 20), un, font=uf, fill=MUTED, anchor="la")

    # Auction Points: big number with a soft glow
    txt = f"{int(points):,}"
    pf_txt, pf = fit_text(txt, PC[2] - 30 - NUM_X, 88, 44, "bold")
    tw = int(text_w(pf_txt, pf))
    pad, hh = 34, int(pf.size * 0.85)
    rx0, ry0, rw, rh = NUM_X - pad, NUM_Y - hh - pad, tw + 2 * pad, 2 * hh + 2 * pad
    gm = Image.new("L", (rw, rh), 0)
    ImageDraw.Draw(gm).text((pad, rh // 2), pf_txt, font=pf, fill=255, anchor="lm")
    img.paste(NUM_GLOW, (rx0, ry0), gm.filter(ImageFilter.GaussianBlur(13)).point(lambda v: int(v * 0.8)))
    d.text((NUM_X, NUM_Y), pf_txt, font=pf, fill=NUM_COLOR, anchor="lm")

    # Approved / Sold numbers (large)
    vf = font(56, "medium")
    for y, vals in zip(ROW_Y, (approved, sold)):
        for i, v in enumerate(vals):
            d.text((col_x(i), y), str(v), font=vf, fill=WHITE, anchor="mm")
    return img


_result_cache = OrderedDict()
_cache_lock = threading.Lock()
CACHE_SIZE = 32


def render_profile(name, username, status, approved, sold, points, avatar_bytes=None):
    name = clean_name(name, fallback=clean_name(username, "User") if username else "User")
    key = (name, username or "", status, tuple(approved), tuple(sold), int(points),
           zlib.crc32(avatar_bytes) if avatar_bytes else 0)
    with _cache_lock:
        data = _result_cache.get(key)
        if data is not None:
            _result_cache.move_to_end(key)
    if data is None:
        img = _compose(_get_state(), name, username, status, approved, sold, points, avatar_bytes)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92, subsampling=0)
        data = buf.getvalue()
        with _cache_lock:
            _result_cache[key] = data
            while len(_result_cache) > CACHE_SIZE:
                _result_cache.popitem(last=False)
    out = io.BytesIO(data)
    out.name = "profile.jpg"
    return out


if __name__ == "__main__":
    import sys
    t = time.time()
    buf = render_profile("Enryu", "enryu", "verified", [12, 48, 7, 3], [9, 30, 5, 2], 128)
    print("first render (includes one-time static layer):", round(time.time() - t, 2), "s")
    t = time.time()
    render_profile("Enryu", "enryu", "admin", [12, 48, 7, 3], [9, 30, 5, 2], 129)
    print("next render:", round((time.time() - t) * 1000), "ms")
    with open(sys.argv[1] if len(sys.argv) > 1 else "preview.jpg", "wb") as f:
        f.write(buf.getvalue())
