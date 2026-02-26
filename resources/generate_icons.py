#!/usr/bin/env python3
"""Generate menu bar icon and app icon for Sony XM6 Controller.

Requires: pip install Pillow
"""

import os
import subprocess
import sys
import tempfile

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow is required: pip install Pillow")
    sys.exit(1)

RESOURCES_DIR = os.path.dirname(os.path.abspath(__file__))


def draw_headphone(draw, size, color="black", line_width=None):
    """Draw a headphone silhouette on the given ImageDraw context."""
    w, h = size
    lw = line_width or max(2, w // 11)

    # Headband arc — top half of an ellipse spanning the full width
    band_l = w * 0.14
    band_r = w - band_l
    band_top = h * 0.07
    band_bot = h * 0.68
    draw.arc(
        [band_l, band_top, band_r, band_bot],
        start=180, end=360,
        fill=color, width=lw,
    )

    # Ear cup dimensions
    cup_w = w * 0.20
    cup_h = h * 0.34
    cup_top = h * 0.53
    cup_radius = max(1, cup_w * 0.3)

    # Left ear cup
    lx = band_l + lw / 2 - cup_w / 2
    draw.rounded_rectangle(
        [lx, cup_top, lx + cup_w, cup_top + cup_h],
        radius=cup_radius, fill=color,
    )

    # Right ear cup
    rx = band_r - lw / 2 - cup_w / 2
    draw.rounded_rectangle(
        [rx, cup_top, rx + cup_w, cup_top + cup_h],
        radius=cup_radius, fill=color,
    )


def generate_menu_icon():
    """Create 22x22 (+ @2x) template icon for the macOS menu bar.

    Template images are black on transparent — macOS adapts them to the
    current menu bar appearance (light/dark mode) automatically.
    """
    # Draw at 2x for crisp Retina rendering
    size_2x = (44, 44)
    img = Image.new("RGBA", size_2x, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_headphone(draw, size_2x, color="black", line_width=4)

    path_2x = os.path.join(RESOURCES_DIR, "icon@2x.png")
    img.save(path_2x)
    print(f"  {path_2x}")

    # 1x version (downscaled)
    img_1x = img.resize((22, 22), Image.LANCZOS)
    path_1x = os.path.join(RESOURCES_DIR, "icon.png")
    img_1x.save(path_1x)
    print(f"  {path_1x}")


def render_app_icon(px):
    """Render a single app icon frame at the given pixel size."""
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Dark circular background (matches the web UI theme)
    m = px * 0.06
    draw.ellipse([m, m, px - m, px - m], fill="#1a1a1f")

    # Headphone in accent orange, centered
    pad = px * 0.22
    hp_sz = int(px - 2 * pad)
    hp = Image.new("RGBA", (hp_sz, hp_sz), (0, 0, 0, 0))
    draw_headphone(ImageDraw.Draw(hp), (hp_sz, hp_sz), color="#e87a2e")
    img.paste(hp, (int(pad), int(pad)), hp)

    return img


def generate_app_icon():
    """Create AppIcon.icns via macOS iconutil."""
    # iconset requires specific filenames at specific pixel sizes
    entries = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        iconset = os.path.join(tmpdir, "AppIcon.iconset")
        os.makedirs(iconset)

        for fname, px in entries.items():
            render_app_icon(px).save(os.path.join(iconset, fname))

        output = os.path.join(RESOURCES_DIR, "AppIcon.icns")
        subprocess.run(
            ["iconutil", "-c", "icns", iconset, "-o", output],
            check=True,
        )
        print(f"  {output}")


if __name__ == "__main__":
    print("Generating menu bar icon...")
    generate_menu_icon()
    print("Generating app icon (icns)...")
    generate_app_icon()
    print("Done!")
