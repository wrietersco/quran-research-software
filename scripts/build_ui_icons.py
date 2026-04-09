"""
Generate 24x24 PNG icons (Material-style strokes) for Tkinter PhotoImage.
Run once after changing shapes:  python scripts/build_ui_icons.py
Requires Pillow.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "ui" / "icons_data"

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Install Pillow: pip install Pillow", file=sys.stderr)
    sys.exit(1)

# Stroke color matches MaterialSymbols on-surface default
STROKE = (0, 107, 94, 255)  # primary teal
STROKE_MUTED = (68, 71, 78, 255)
WIDTH = 24
SCALE = 2  # supersample


def _new() -> Image.Image:
    return Image.new("RGBA", (WIDTH * SCALE, WIDTH * SCALE), (0, 0, 0, 0))


def _save(name: str, im: Image.Image) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    small = im.resize((WIDTH, WIDTH), Image.Resampling.LANCZOS)
    small.save(OUT / f"{name}.png", "PNG")


def _circle_arc(draw: ImageDraw.ImageDraw, bbox, start, end, fill, w: float) -> None:
    draw.arc(bbox, start=start, end=end, fill=fill, width=int(w * SCALE))


def icon_refresh() -> Image.Image:
    im = _new()
    d = ImageDraw.Draw(im)
    cx, cy, r = 12 * SCALE, 12 * SCALE, 7 * SCALE
    # arc arrow (270° sweep from ~45 to 315)
    bbox = (cx - r, cy - r, cx + r, cy + r)
    _circle_arc(d, bbox, 200, 520, STROKE, 2.0)
    # arrow head
    ax, ay = cx + int(r * 0.65), cy - int(r * 0.55)
    d.line(
        [(ax, ay), (ax + 3 * SCALE, ay - 2 * SCALE), (ax + 2 * SCALE, ay + 3 * SCALE)],
        fill=STROKE,
        width=int(2 * SCALE),
    )
    return im


def icon_storage() -> Image.Image:
    im = _new()
    d = ImageDraw.Draw(im)
    # cylinder top ellipse
    d.ellipse((6 * SCALE, 5 * SCALE, 18 * SCALE, 11 * SCALE), outline=STROKE, width=int(2 * SCALE))
    d.line([(6 * SCALE, 8 * SCALE), (6 * SCALE, 17 * SCALE)], fill=STROKE, width=int(2 * SCALE))
    d.line([(18 * SCALE, 8 * SCALE), (18 * SCALE, 17 * SCALE)], fill=STROKE, width=int(2 * SCALE))
    d.arc((6 * SCALE, 14 * SCALE, 18 * SCALE, 20 * SCALE), start=0, end=180, fill=STROKE, width=int(2 * SCALE))
    return im


def icon_chat() -> Image.Image:
    im = _new()
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(
        (4 * SCALE, 5 * SCALE, 19 * SCALE, 16 * SCALE),
        radius=3 * SCALE,
        outline=STROKE,
        width=int(2 * SCALE),
    )
    d.polygon(
        [(8 * SCALE, 16 * SCALE), (11 * SCALE, 16 * SCALE), (9 * SCALE, 19 * SCALE)],
        fill=STROKE,
    )
    return im


def icon_smart_toy() -> Image.Image:
    im = _new()
    d = ImageDraw.Draw(im)
    d.rounded_rectangle(
        (5 * SCALE, 7 * SCALE, 19 * SCALE, 17 * SCALE),
        radius=2 * SCALE,
        outline=STROKE,
        width=int(2 * SCALE),
    )
    d.ellipse((8 * SCALE, 10 * SCALE, 10 * SCALE, 12 * SCALE), fill=STROKE)
    d.ellipse((14 * SCALE, 10 * SCALE, 16 * SCALE, 12 * SCALE), fill=STROKE)
    d.arc((9 * SCALE, 12 * SCALE, 15 * SCALE, 16 * SCALE), start=20, end=160, fill=STROKE, width=int(2 * SCALE))
    return im


def icon_folder() -> Image.Image:
    im = _new()
    d = ImageDraw.Draw(im)
    d.polygon(
        [(5 * SCALE, 8 * SCALE), (9 * SCALE, 6 * SCALE), (13 * SCALE, 6 * SCALE), (15 * SCALE, 8 * SCALE), (19 * SCALE, 8 * SCALE), (19 * SCALE, 17 * SCALE), (5 * SCALE, 17 * SCALE)],
        outline=STROKE,
        width=int(2 * SCALE),
    )
    return im


def icon_table() -> Image.Image:
    im = _new()
    d = ImageDraw.Draw(im)
    d.rectangle((5 * SCALE, 5 * SCALE, 19 * SCALE, 19 * SCALE), outline=STROKE, width=int(2 * SCALE))
    d.line([(5 * SCALE, 10 * SCALE), (19 * SCALE, 10 * SCALE)], fill=STROKE, width=int(1.5 * SCALE))
    d.line([(12 * SCALE, 5 * SCALE), (12 * SCALE, 19 * SCALE)], fill=STROKE, width=int(1.5 * SCALE))
    return im


def icon_account_tree() -> Image.Image:
    im = _new()
    d = ImageDraw.Draw(im)
    d.line([(12 * SCALE, 4 * SCALE), (12 * SCALE, 9 * SCALE)], fill=STROKE, width=int(2 * SCALE))
    d.line([(6 * SCALE, 9 * SCALE), (18 * SCALE, 9 * SCALE)], fill=STROKE, width=int(2 * SCALE))
    d.line([(6 * SCALE, 9 * SCALE), (6 * SCALE, 14 * SCALE)], fill=STROKE, width=int(2 * SCALE))
    d.line([(12 * SCALE, 9 * SCALE), (12 * SCALE, 14 * SCALE)], fill=STROKE, width=int(2 * SCALE))
    d.line([(18 * SCALE, 9 * SCALE), (18 * SCALE, 14 * SCALE)], fill=STROKE, width=int(2 * SCALE))
    d.ellipse((4 * SCALE, 14 * SCALE, 8 * SCALE, 18 * SCALE), outline=STROKE, width=int(2 * SCALE))
    d.ellipse((10 * SCALE, 14 * SCALE, 14 * SCALE, 18 * SCALE), outline=STROKE, width=int(2 * SCALE))
    d.ellipse((16 * SCALE, 14 * SCALE, 20 * SCALE, 18 * SCALE), outline=STROKE, width=int(2 * SCALE))
    return im


def icon_send() -> Image.Image:
    im = _new()
    d = ImageDraw.Draw(im)
    d.polygon(
        [(5 * SCALE, 12 * SCALE), (19 * SCALE, 5 * SCALE), (14 * SCALE, 19 * SCALE), (12 * SCALE, 12 * SCALE)],
        outline=STROKE,
        fill=(0, 107, 94, 60),
        width=int(2 * SCALE),
    )
    return im


def icon_add() -> Image.Image:
    im = _new()
    d = ImageDraw.Draw(im)
    d.line([(12 * SCALE, 6 * SCALE), (12 * SCALE, 18 * SCALE)], fill=STROKE, width=int(2 * SCALE))
    d.line([(6 * SCALE, 12 * SCALE), (18 * SCALE, 12 * SCALE)], fill=STROKE, width=int(2 * SCALE))
    return im


def icon_edit() -> Image.Image:
    im = _new()
    d = ImageDraw.Draw(im)
    d.polygon(
        [(14 * SCALE, 5 * SCALE), (18 * SCALE, 9 * SCALE), (9 * SCALE, 18 * SCALE), (5 * SCALE, 19 * SCALE), (6 * SCALE, 15 * SCALE)],
        outline=STROKE,
        width=int(2 * SCALE),
    )
    d.line([(5 * SCALE, 19 * SCALE), (4 * SCALE, 20 * SCALE)], fill=STROKE, width=int(2 * SCALE))
    return im


def icon_delete() -> Image.Image:
    im = _new()
    d = ImageDraw.Draw(im)
    d.rectangle((7 * SCALE, 7 * SCALE, 17 * SCALE, 18 * SCALE), outline=STROKE, width=int(2 * SCALE))
    d.line([(9 * SCALE, 7 * SCALE), (10 * SCALE, 5 * SCALE), (14 * SCALE, 5 * SCALE), (15 * SCALE, 7 * SCALE)], fill=STROKE, width=int(2 * SCALE))
    d.line([(10 * SCALE, 10 * SCALE), (10 * SCALE, 16 * SCALE)], fill=STROKE_MUTED, width=int(1.5 * SCALE))
    d.line([(12 * SCALE, 10 * SCALE), (12 * SCALE, 16 * SCALE)], fill=STROKE_MUTED, width=int(1.5 * SCALE))
    d.line([(14 * SCALE, 10 * SCALE), (14 * SCALE, 16 * SCALE)], fill=STROKE_MUTED, width=int(1.5 * SCALE))
    return im


def icon_menu_book() -> Image.Image:
    im = _new()
    d = ImageDraw.Draw(im)
    d.line([(8 * SCALE, 4 * SCALE), (8 * SCALE, 20 * SCALE)], fill=STROKE, width=int(2 * SCALE))
    d.arc((8 * SCALE, 4 * SCALE, 18 * SCALE, 20 * SCALE), start=270, end=90, fill=STROKE, width=int(2 * SCALE))
    d.line([(13 * SCALE, 7 * SCALE), (16 * SCALE, 7 * SCALE)], fill=STROKE_MUTED, width=int(1.2 * SCALE))
    d.line([(13 * SCALE, 10 * SCALE), (16 * SCALE, 10 * SCALE)], fill=STROKE_MUTED, width=int(1.2 * SCALE))
    return im


def icon_cloud() -> Image.Image:
    im = _new()
    d = ImageDraw.Draw(im)
    d.arc((5 * SCALE, 10 * SCALE, 13 * SCALE, 16 * SCALE), 120, 360, fill=STROKE, width=int(2 * SCALE))
    d.arc((10 * SCALE, 8 * SCALE, 18 * SCALE, 14 * SCALE), 180, 400, fill=STROKE, width=int(2 * SCALE))
    d.arc((14 * SCALE, 10 * SCALE, 21 * SCALE, 17 * SCALE), 220, 470, fill=STROKE, width=int(2 * SCALE))
    return im


def icon_tune() -> Image.Image:
    im = _new()
    d = ImageDraw.Draw(im)
    for x, y in [(7, 6), (12, 10), (17, 7)]:
        d.line([(x * SCALE, y * SCALE), (x * SCALE, (y + 8) * SCALE)], fill=STROKE, width=int(2 * SCALE))
        d.line([((x - 2) * SCALE, (y + 3) * SCALE), ((x + 2) * SCALE, (y + 3) * SCALE)], fill=STROKE, width=int(2 * SCALE))
    return im


def icon_bar_chart() -> Image.Image:
    im = _new()
    d = ImageDraw.Draw(im)
    d.rectangle((5 * SCALE, 14 * SCALE, 8 * SCALE, 19 * SCALE), fill=STROKE, outline=STROKE)
    d.rectangle((10 * SCALE, 10 * SCALE, 13 * SCALE, 19 * SCALE), fill=STROKE, outline=STROKE)
    d.rectangle((15 * SCALE, 6 * SCALE, 18 * SCALE, 19 * SCALE), fill=STROKE, outline=STROKE)
    return im


def main() -> None:
    icons = {
        "refresh": icon_refresh,
        "storage": icon_storage,
        "chat": icon_chat,
        "smart_toy": icon_smart_toy,
        "folder": icon_folder,
        "table": icon_table,
        "account_tree": icon_account_tree,
        "send": icon_send,
        "add": icon_add,
        "edit": icon_edit,
        "delete": icon_delete,
        "menu_book": icon_menu_book,
        "cloud": icon_cloud,
        "tune": icon_tune,
        "bar_chart": icon_bar_chart,
    }
    for name, fn in icons.items():
        _save(name, fn())
    print(f"Wrote {len(icons)} PNGs to {OUT}")


if __name__ == "__main__":
    main()
