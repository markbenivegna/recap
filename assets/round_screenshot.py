#!/usr/bin/env python3
"""Applies the same rounded-corner + hairline-border treatment the earlier
README screenshots had (reverse-engineered by sampling the actual pixels of
assets/screenshot-summary.png from an earlier commit): a 12px corner radius
and a 1px border stored as raw rgba(0, 0, 0, 40), genuinely semi-transparent
black (renders correctly on both light and dark GitHub themes), not an
opaque gray pre-blended against a white background.

Usage: venv/bin/python3 assets/round_screenshot.py <file1.png> [file2.png ...]
Overwrites each file in place.
"""
import sys

from PIL import Image, ImageDraw

RADIUS = 12
BORDER_RGBA = (0, 0, 0, 40)


def round_screenshot(path):
    img = Image.open(path).convert("RGBA")
    w, h = img.size

    # Content mask: inset 1px from the true edge on every side. This leaves
    # the outer 1px ring (where the border stroke goes, drawn centered on
    # the true edge below) transparent in the content layer itself, rather
    # than already-opaque, before the border is composited on top of it.
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([1, 1, w - 2, h - 2], radius=max(0, RADIUS - 1), fill=255)
    img.putalpha(mask)

    # Border: draw the stroke onto its own blank transparent layer, then
    # composite it over the now-rounded image. Compositing a
    # semi-transparent color over a *transparent* layer preserves the real
    # rgba(0,0,0,40) at the stroke's own solidly-covered pixels. Compositing
    # over already-*opaque* content (the mistake in an earlier version of
    # this script) washes a semi-transparent border out toward opaque gray
    # instead.
    border = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle([0, 0, w - 1, h - 1], radius=RADIUS, outline=BORDER_RGBA, width=1)

    result = Image.alpha_composite(img, border)
    result.save(path)


if __name__ == "__main__":
    for path in sys.argv[1:]:
        round_screenshot(path)
        print(f"rounded {path}")
