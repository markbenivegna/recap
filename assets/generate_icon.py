"""One-off script that renders the app icon. Requires Pillow: pip install pillow.
Run from the project root: python3 assets/generate_icon.py

The mic glyph (assets/mic-icon-source.svg, from the Noun Project) is rasterized
via macOS's QuickLook thumbnail generator (`qlmanage -t`), then recolored from
black-on-white to dark-on-transparent and composited onto the gradient
background here.
"""
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageOps

SIZE = 1024
OUT_PATH = os.path.join(os.path.dirname(__file__), "icon.png")
SOURCE_SVG = os.path.join(os.path.dirname(__file__), "mic-icon-source.svg")

BG_TOP = (255, 230, 102)  # lighter tint of the bottom stop, matches --accent-light
BG_BOTTOM = (254, 216, 0)  # #FED800, matches --accent
GLYPH = (43, 36, 0)  # matches --accent-text — dark glyph reads better on this bright yellow


def squircle_mask(size, corner_ratio=0.225):
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    radius = int(size * corner_ratio)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


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

        # Recolor black-glyph-on-white to GLYPH-color-on-transparent.
        alpha = ImageOps.invert(raster)
        glyph = Image.new("RGBA", raster.size, GLYPH + (0,))
        glyph.putalpha(alpha)

        # Trim the whitespace margin QuickLook adds around the glyph.
        bbox = alpha.getbbox()
        if bbox:
            glyph = glyph.crop(bbox)
        return glyph


def main():
    # macOS app icons sit on a 1024x1024 canvas but the visible glyph should
    # only fill ~80% of it (matching Apple's icon grid) with transparent
    # margin around it — otherwise the tile reads as oversized next to
    # other app icons in the Dock/Finder.
    content_size = round(SIZE * 0.80)

    bg = gradient_background(content_size, BG_TOP, BG_BOTTOM)
    mask = squircle_mask(content_size)

    content = Image.new("RGBA", (content_size, content_size), (0, 0, 0, 0))
    content.paste(bg, (0, 0), mask)

    glyph = load_mic_glyph()
    glyph_w = round(content_size * 0.40)
    glyph_h = round(glyph_w * glyph.height / glyph.width)
    glyph = glyph.resize((glyph_w, glyph_h), Image.LANCZOS)
    glyph_x = (content_size - glyph_w) // 2
    glyph_y = round((content_size - glyph_h) / 2)
    content.alpha_composite(glyph, (glyph_x, glyph_y))

    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    offset = (SIZE - content_size) // 2
    canvas.paste(content, (offset, offset), content)

    canvas.save(OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
