"""
Glass-style profile card for the /profile command.

Needs:  pip install pillow requests
Usage:  png = render_profile(name, username, status, approved, sold, points, avatar_bytes)
        -> io.BytesIO (PNG)   |   status: "verified" | "unverified" | "admin"
        approved / sold = [legendary, non-legendary, shiny, tms]
"""
import io
import os
import time
import unicodedata

import requests
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BG_URL = "https://envs.sh/0ul.jpg"        # same picture the old /profile used as background
BG_CACHE = "profile_bg.jpg"
FONT_DIR = "fonts"

W, H = 1500, 640
MARGIN = 70
ACCENT = (110, 232, 255)                   # cyan highlight (Auction Points)
STATUS_STYLE = {
    "verified": ("VERIFIED", (96, 228, 150)),
    "unverified": ("UNVERIFIED", (255, 125, 125)),
    "admin": ("ADMIN", (255, 206, 96)),
}

# ---------------------------------------------------------------------------
# Fonts (Poppins). Uses a local copy / system copy, tries to download once,
# and finally falls back to DejaVu / Pillow's default so it never crashes.
# ---------------------------------------------------------------------------
_WEIGHTS = {"light": "Light", "regular": "Regular", "medium": "Medium", "bold": "Bold"}
_font_cache = {}
_font_download_tried = False
_SYSTEM_DIRS = ["/usr/share/fonts/truetype/google-fonts", "/usr/share/fonts/truetype/poppins",
                "/usr/share/fonts/poppins", os.path.expanduser("~/.fonts")]


def _download_fonts():
    global _font_download_tried
    if _font_download_tried:
        return
    _font_download_tried = True
    os.makedirs(FONT_DIR, exist_ok=True)
    for w in _WEIGHTS.values():
        path = os.path.join(FONT_DIR, f"Poppins-{w}.ttf")
        if os.path.exists(path):
            continue
        try:
            r = requests.get(f"https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-{w}.ttf",
                             timeout=20)
            if r.status_code == 200 and len(r.content) > 10000:
                with open(path, "wb") as f:
                    f.write(r.content)
        except Exception as e:
            print("font download failed:", e)
            return


def font(size, weight="regular"):
    key = (size, weight)
    if key in _font_cache:
        return _font_cache[key]
    fname = f"Poppins-{_WEIGHTS[weight]}.ttf"
    paths = [os.path.join(FONT_DIR, fname)] + [os.path.join(d, fname) for d in _SYSTEM_DIRS]
    if not any(os.path.exists(p) for p in paths):
        _download_fonts()
    paths.append("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if weight == "bold"
                 else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    paths += ["arialbd.ttf" if weight == "bold" else "arial.ttf"]
    f = None
    for p in paths:
        try:
            f = ImageFont.truetype(p, size)
            break
        except Exception:
            continue
    if f is None:
        try:
            f = ImageFont.load_default(size)
        except TypeError:
            f = ImageFont.load_default()
    _font_cache[key] = f
    return f


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------
_bg_cache = None
_bg_last_try = 0


def _gradient_bg():
    """Fallback teal gradient (used only if the background picture can't be loaded)."""
    base = Image.new("RGB", (W, H))
    px = base.load()
    c0, c1 = (0, 176, 206), (0, 88, 124)
    for x in range(W):
        for y in range(H):
            t = min(1.0, max(0.0, (x / W) * 0.75 + (y / H) * 0.25))
            px[x, y] = tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse((900, -250, 1700, 450), fill=(255, 255, 255, 38))
    d.ellipse((-250, 300, 450, 900), fill=(255, 255, 255, 26))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    return Image.alpha_composite(base.convert("RGBA"), glow)


def _cover(img, w, h):
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    img = img.resize((int(iw * scale) + 1, int(ih * scale) + 1), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def get_background():
    global _bg_cache, _bg_last_try
    if _bg_cache is not None:
        return _bg_cache.copy()
    img = None
    try:
        if os.path.exists(BG_CACHE):
            img = Image.open(BG_CACHE)
            img.load()
        elif time.time() - _bg_last_try > 300:
            _bg_last_try = time.time()
            r = requests.get(BG_URL, timeout=15)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                with open(BG_CACHE, "wb") as f:
                    f.write(r.content)
                img = Image.open(io.BytesIO(r.content))
                img.load()
    except Exception as e:
        print("profile background load failed:", e)
        img = None
    if img is None:
        return _gradient_bg()          # not cached -> retried later
    bg = _cover(img.convert("RGB"), W, H).convert("RGBA")
    # soft dark veil so the white text stays readable on any picture
    bg = Image.alpha_composite(bg, Image.new("RGBA", (W, H), (0, 20, 40, 85)))
    _bg_cache = bg
    return bg.copy()


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
S = 4  # supersampling for smooth rounded corners


def _rr_mask(w, h, radius):
    m = Image.new("L", (w * S, h * S), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * S - 1, h * S - 1), radius=radius * S, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def glass(img, box, radius=34, alpha_top=62, alpha_bottom=26, blur=16, tint=None):
    """Frosted-glass panel: blurred backdrop + white veil + thin light border + soft shadow."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    mask = _rr_mask(w, h, radius)

    # shadow
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh.paste((0, 25, 45, 70), (x0, y0 + 12), mask)
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(20)))

    # frosted backdrop
    backdrop = img.crop(box).filter(ImageFilter.GaussianBlur(blur))
    img.paste(backdrop, (x0, y0), mask)

    # white veil (vertical gradient)
    grad = Image.linear_gradient("L").resize((w, h))           # black -> white, top -> bottom
    grad = grad.point(lambda v: int(alpha_top + (alpha_bottom - alpha_top) * v / 255))
    veil_alpha = ImageChops.multiply(grad, mask)
    veil = Image.new("RGBA", (w, h), tint or (255, 255, 255, 0))
    veil.putalpha(veil_alpha)
    img.alpha_composite(veil, (x0, y0))

    # border
    inner = Image.new("L", (w, h), 0)
    inner.paste(_rr_mask(w - 4, h - 4, max(radius - 2, 1)), (2, 2))
    border = ImageChops.subtract(mask, inner).point(lambda v: int(v * 0.55))
    b = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    b.putalpha(border)
    img.alpha_composite(b, (x0, y0))


def text(img, xy, s, fnt, fill=(255, 255, 255, 255), anchor="la"):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, s, font=fnt, fill=fill, anchor=anchor)
    img.alpha_composite(layer)


def glow_text(img, xy, s, fnt, color, anchor="la", radius=22, strength=150):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, s, font=fnt, fill=color + (strength,), anchor=anchor)
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius)))
    text(img, xy, s, fnt, color + (255,), anchor)


def spaced_text(img, xy, s, fnt, fill, spacing=3, anchor="l"):
    """Letter-spaced caps. anchor: 'l' left, 'm' centre, 'r' right (x = reference, y = middle)."""
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    widths = [d.textlength(c, font=fnt) for c in s]
    total = sum(widths) + spacing * (len(s) - 1)
    x, y = xy
    if anchor == "m":
        x -= total / 2
    elif anchor == "r":
        x -= total
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for c, wd in zip(s, widths):
        ld.text((x, y), c, font=fnt, fill=fill, anchor="lm")
        x += wd + spacing
    img.alpha_composite(layer)
    return total


def star(cx, cy, r_out, r_in, points=5, rot=-90):
    import math
    pts = []
    for i in range(points * 2):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(rot + i * 180 / points)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def clean_name(s, fallback="User"):
    """Keep only characters the Latin font can draw (emoji / other scripts would show as boxes)."""
    out = []
    for ch in str(s or ""):
        cat = unicodedata.category(ch)
        if cat[0] in "CZ" and ch != " ":
            continue
        if ord(ch) > 0x24F and not (0x2010 <= ord(ch) <= 0x2027):
            continue
        out.append(ch)
    s = " ".join("".join(out).split())
    return s or fallback


def fit_text(s, max_w, start, min_size, weight):
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    size = start
    while size > min_size and d.textlength(s, font=font(size, weight)) > max_w:
        size -= 2
    f = font(size, weight)
    if d.textlength(s, font=f) > max_w:
        while len(s) > 1 and d.textlength(s + "…", font=f) > max_w:
            s = s[:-1]
        s = s.rstrip() + "…"
    return s, f


# ---------------------------------------------------------------------------
# Avatar
# ---------------------------------------------------------------------------
def _avatar(avatar_bytes, size, initial):
    img = None
    if avatar_bytes:
        try:
            img = Image.open(io.BytesIO(avatar_bytes)).convert("RGB")
            img = _cover(img, size, size)
        except Exception:
            img = None
    if img is None:
        img = Image.new("RGB", (size, size))
        g = Image.linear_gradient("L").resize((size, size))
        top, bottom = Image.new("RGB", (size, size), (70, 200, 230)), Image.new("RGB", (size, size), (20, 110, 150))
        img = Image.composite(bottom, top, g)
        d = ImageDraw.Draw(img)
        d.text((size / 2, size / 2), (initial or "U")[0].upper(), font=font(int(size * 0.5), "bold"),
               fill=(255, 255, 255), anchor="mm")
    return img.convert("RGBA")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def render_profile(name, username, status, approved, sold, points, avatar_bytes=None):
    img = get_background()
    label, scolor = STATUS_STYLE.get(status, STATUS_STYLE["unverified"])
    name = clean_name(name, fallback=clean_name(username, "User") if username else "User")

    # ---- left: avatar -------------------------------------------------------
    av = 230
    ax, ay = MARGIN, MARGIN
    ring = Image.new("RGBA", (av + 12, av + 12), (0, 0, 0, 0))
    ring_mask = _rr_mask(av + 12, av + 12, 52)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh.paste((0, 20, 40, 80), (ax - 6, ay - 6 + 12), ring_mask)
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(16)))
    ring.paste((255, 255, 255, 255), (0, 0), ring_mask)
    img.alpha_composite(ring, (ax - 6, ay - 6))
    img.paste(_avatar(avatar_bytes, av, name), (ax, ay), _rr_mask(av, av, 46))

    # ---- middle: status, name, username ------------------------------------
    tx = ax + av + 50
    max_text_w = 790 - tx - 20
    pill_font = font(21, "medium")
    pw = int(ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(label, font=pill_font)) + 3 * (len(label) - 1) + 70
    px0, py0 = tx, ay + 6
    glass(img, (px0, py0, px0 + pw, py0 + 48), radius=24, alpha_top=70, alpha_bottom=40, blur=8)
    d = ImageDraw.Draw(img)
    dot = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(dot).ellipse((px0 + 20, py0 + 15, px0 + 38, py0 + 33), fill=scolor + (255,))
    img.alpha_composite(dot.filter(ImageFilter.GaussianBlur(5)))
    ImageDraw.Draw(img).ellipse((px0 + 20, py0 + 15, px0 + 38, py0 + 33), fill=scolor + (255,))
    spaced_text(img, (px0 + 52, py0 + 25), label, pill_font, (255, 255, 255, 235), spacing=3)

    nm, nf = fit_text(name, max_text_w, 70, 38, "bold")
    text(img, (tx, ay + 78), nm, nf, (255, 255, 255, 255))
    if username:
        un, uf = fit_text("@" + username, max_text_w, 34, 22, "light")
        text(img, (tx, ay + 78 + nf.size + 22), un, uf, (255, 255, 255, 190))

    # ---- right: approved / sold glass panel ---------------------------------
    gx0, gy0, gx1, gy1 = 810, MARGIN, W - MARGIN, MARGIN + 230
    glass(img, (gx0, gy0, gx1, gy1), radius=38)
    cats = ["LEGENDARY", "NON-LEG", "SHINY", "TMS"]
    label_w = 140
    col_w = (gx1 - gx0 - label_w - 20) / 4
    head_y = gy0 + 42
    for i, c in enumerate(cats):
        cx = gx0 + label_w + col_w * i + col_w / 2
        spaced_text(img, (cx, head_y), c, font(14, "medium"), (255, 255, 255, 165), spacing=1, anchor="m")
    div = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(div).line((gx0 + 30, gy0 + 72, gx1 - 30, gy0 + 72), fill=(255, 255, 255, 70), width=2)
    img.alpha_composite(div)
    for r, (row_label, vals) in enumerate((("APPROVED", approved), ("SOLD", sold))):
        cy = gy0 + 112 + r * 66
        spaced_text(img, (gx0 + 34, cy), row_label, font(16, "medium"), (255, 255, 255, 190), spacing=2)
        for i, v in enumerate(vals):
            cx = gx0 + label_w + col_w * i + col_w / 2
            text(img, (cx, cy), str(v), font(40, "medium"), (255, 255, 255, 255), anchor="mm")

    # ---- bottom: Auction Points (the highlight) ----------------------------
    bx0, by0, bx1, by1 = MARGIN, 340, W - MARGIN, H - MARGIN
    glass(img, (bx0, by0, bx1, by1), radius=44, alpha_top=70, alpha_bottom=34, blur=20)
    # soft accent wash inside the card
    wash = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(wash).ellipse((bx0 - 140, by0 - 80, bx0 + 560, by1 + 80), fill=ACCENT + (46,))
    wash = wash.filter(ImageFilter.GaussianBlur(70))
    clip = Image.new("L", (W, H), 0)
    clip.paste(_rr_mask(bx1 - bx0, by1 - by0, 44), (bx0, by0))
    wash.putalpha(ImageChops.multiply(wash.getchannel("A"), clip))
    img.alpha_composite(wash)

    cy = (by0 + by1) // 2
    # star icon
    sx = bx0 + 130
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).polygon(star(sx, cy + 4, 62, 26), fill=ACCENT + (170,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(20)))
    big = Image.new("RGBA", (W * 2, H * 2), (0, 0, 0, 0))
    ImageDraw.Draw(big).polygon(star(sx * 2, (cy + 4) * 2, 124, 52), fill=ACCENT + (255,))
    img.alpha_composite(big.resize((W, H), Image.LANCZOS))

    spaced_text(img, (bx0 + 250, cy - 70), "AUCTION POINTS", font(24, "medium"), (255, 255, 255, 210), spacing=6)
    pts = f"{int(points):,}"
    glow_text(img, (bx0 + 246, cy + 16), pts, font(112, "bold"), ACCENT, anchor="lm")

    # faint brand mark, bottom right of the card
    spaced_text(img, (bx1 - 40, by1 - 38), "HEXA AUCTION", font(18, "medium"), (255, 255, 255, 110), spacing=5, anchor="r")

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=False)
    out.name = "profile.png"
    out.seek(0)
    return out


if __name__ == "__main__":
    import sys
    buf = render_profile("Enryu", "enryu", "verified", [12, 48, 7, 3], [9, 30, 5, 2], 128)
    with open(sys.argv[1] if len(sys.argv) > 1 else "preview.png", "wb") as f:
        f.write(buf.read())
