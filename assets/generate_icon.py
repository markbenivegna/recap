"""One-off script that renders the app icon. Requires Pillow: pip install pillow.
Run from the project root: python3 assets/generate_icon.py
"""
import math
import os

from PIL import Image, ImageDraw

SIZE = 1024
OUT_PATH = os.path.join(os.path.dirname(__file__), "icon.png")

BG_TOP = (217, 119, 87)  # matches --accent-hover from frontend/style.css
BG_BOTTOM = (181, 83, 60)  # matches --accent
GLYPH = (255, 250, 246)


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


def draw_mic_glyph(draw, cx, cy, scale):
    body_w = 190 * scale
    body_h = 320 * scale
    body_radius = body_w / 2

    # Mic capsule
    draw.rounded_rectangle(
        [cx - body_w / 2, cy - body_h / 2, cx + body_w / 2, cy + body_h / 2 - body_radius],
        radius=body_radius,
        fill=GLYPH,
    )

    # Cradle arc (open arc under the capsule)
    arc_r = 150 * scale
    arc_box = [cx - arc_r, cy - arc_r * 0.55, cx + arc_r, cy + arc_r * 1.35]
    stroke = 26 * scale
    draw.arc(arc_box, start=25, end=155, fill=GLYPH, width=int(stroke))

    # Stand
    stand_top = cy + arc_r * 1.05
    stand_bottom = stand_top + 90 * scale
    draw.line([cx, stand_top, cx, stand_bottom], fill=GLYPH, width=int(stroke))

    # Base
    base_w = 150 * scale
    draw.line(
        [cx - base_w / 2, stand_bottom, cx + base_w / 2, stand_bottom],
        fill=GLYPH,
        width=int(stroke),
    )


def draw_waveform(draw, cx, cy, scale):
    bars = [0.35, 0.65, 1.0, 0.5, 0.8, 0.4]
    bar_w = 22 * scale
    gap = 16 * scale
    max_h = 130 * scale
    total_w = len(bars) * bar_w + (len(bars) - 1) * gap
    x = cx - total_w / 2
    for h_ratio in bars:
        h = max_h * h_ratio
        draw.rounded_rectangle(
            [x, cy - h / 2, x + bar_w, cy + h / 2],
            radius=bar_w / 2,
            fill=GLYPH,
        )
        x += bar_w + gap


def main():
    bg = gradient_background(SIZE, BG_TOP, BG_BOTTOM)
    mask = squircle_mask(SIZE)

    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    canvas.paste(bg, (0, 0), mask)

    draw = ImageDraw.Draw(canvas)
    scale = SIZE / 1024
    draw_mic_glyph(draw, SIZE / 2, SIZE * 0.40, scale)
    draw_waveform(draw, SIZE / 2, SIZE * 0.775, scale)

    canvas.save(OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
