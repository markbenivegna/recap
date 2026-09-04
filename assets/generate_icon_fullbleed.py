"""Generates a full-bleed master image for the Icon Composer (.icon) bundle,
as opposed to generate_icon.py's output which is pre-rounded/pre-padded for
the legacy .icns pipeline. Icon Composer expects edge-to-edge square artwork
with no rounded corners and no built-in margin — the OS applies its own
squircle mask, shadow, and safe-area inset on top. Feeding it an
already-inset image (like assets/icon.png) causes a doubled inset ("huge
white border").

Run from the project root: python3 assets/generate_icon_fullbleed.py
Writes assets/AppIcon.icon/Assets/icon.png directly (overwriting it).
"""
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageOps

SIZE = 1024
OUT_PATH = os.path.join(os.path.dirname(__file__), "AppIcon.icon", "Assets", "icon.png")
SOURCE_SVG = os.path.join(os.path.dirname(__file__), "mic-icon-source.svg")

BG_TOP = (255, 230, 102)
BG_BOTTOM = (254, 216, 0)
GLYPH = (43, 36, 0)

# Same visual glyph-to-canvas ratio as the legacy icon (328px glyph in a
# 1024px canvas, after that pipeline's own 80% content inset) — since the
# OS now applies its own inset instead of us doing it, this should land at
# roughly the same final visual size.
GLYPH_RATIO = 0.32


def gradient_background(size, top, bottom):
    base = Image.new("RGB", (1, size), 0)
    for y in range(size):
        t = y / (size - 1)
        r = round(top[0] + (bottom[0] - top[0]) * t)
        g = round(top[1] + (bottom[1] - top[1]) * t)
        b = round(top[2] + (bottom[2] - top[2]) * t)
        base.putpixel((0, y), (r, g, b))
    return base.resize((size, size))


def load_mic_glyph(render_size=1600):
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["qlmanage", "-t", "-s", str(render_size), "-o", tmp, SOURCE_SVG],
            check=True,
            capture_output=True,
        )
        thumb_path = os.path.join(tmp, os.path.basename(SOURCE_SVG) + ".png")
        raster = Image.open(thumb_path).convert("L")
        alpha = ImageOps.invert(raster)
        glyph = Image.new("RGBA", raster.size, GLYPH + (0,))
        glyph.putalpha(alpha)
        bbox = alpha.getbbox()
        if bbox:
            glyph = glyph.crop(bbox)
        return glyph


def main():
    bg = gradient_background(SIZE, BG_TOP, BG_BOTTOM)
    canvas = bg.convert("RGBA")

    glyph = load_mic_glyph()
    glyph_w = round(SIZE * GLYPH_RATIO)
    glyph_h = round(glyph_w * glyph.height / glyph.width)
    glyph = glyph.resize((glyph_w, glyph_h), Image.LANCZOS)
    glyph_x = (SIZE - glyph_w) // 2
    glyph_y = round((SIZE - glyph_h) / 2)
    canvas.alpha_composite(glyph, (glyph_x, glyph_y))

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    canvas.save(OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
