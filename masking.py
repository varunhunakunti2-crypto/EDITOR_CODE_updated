"""Mask placement: nine named zones, whole room, or a custom rectangle.

Custom coordinates are four percentages, ``x1,y1,x2,y2``, measured from the
top-left of the square working image. They are validated before use; anything
missing, reversed, out of bounds, too small or too large falls back to the
centre zone.
"""
import math

from PIL import Image, ImageDraw

IMG_SIZE = 512
ZONE_W = 150          # same zone size as the original fixed rectangle
ZONE_H = 130
MARGIN = 26           # gap kept between the zone and the image edge

# value -> (column, row) where 0 = start, 1 = middle, 2 = end.
# "custom" is a sentinel: without valid coords its preview/mask is the centre.
POSITIONS = {
    "top_left": (0, 0), "top_center": (1, 0), "top_right": (2, 0),
    "middle_left": (0, 1), "middle_center": (1, 1), "middle_right": (2, 1),
    "bottom_left": (0, 2), "bottom_center": (1, 2), "bottom_right": (2, 2),
    "custom": (1, 1),
}
LABELS = {
    "top_left": "Top left", "top_center": "Top centre", "top_right": "Top right",
    "middle_left": "Middle left", "middle_center": "Centre", "middle_right": "Middle right",
    "bottom_left": "Bottom left", "bottom_center": "Bottom centre", "bottom_right": "Bottom right",
    "custom": "Custom area",
    "whole_room": "Whole room",
}
DEFAULT_POSITION = "middle_center"

# Percent bounds for the custom rectangle and its area (as a fraction of the image).
COORD_MIN = 0.0
COORD_MAX = 100.0
MIN_AREA = 0.01        # 1% of the image, e.g. 10x10 percent
MAX_AREA = 0.85        # leave at least 15% of the room visible as context


def normalize_position(value):
    value = (value or "").strip().lower()
    return value if value in POSITIONS else DEFAULT_POSITION


def parse_coords(value):
    """Return fractional ``(x1, y1, x2, y2)`` or ``None`` if invalid.

    Accepts a comma-separated percentage string such as ``"25,25,75,75"`` or
    the fractional tuple returned by a previous call. It never raises.
    """
    if value is None:
        return None

    if isinstance(value, (tuple, list)) and len(value) == 4:
        try:
            raw = [float(part) for part in value]
        except (TypeError, ValueError):
            return None
        # Values from parse_coords are fractions; values typed in the form are
        # percentages. Both are accepted here.
        if all(COORD_MIN <= part <= 1.0 for part in raw):
            raw = [part * 100.0 for part in raw]
    else:
        parts = str(value).strip().split(',')
        if len(parts) != 4:
            return None
        try:
            raw = [float(part.strip()) for part in parts]
        except (TypeError, ValueError):
            return None

    if any(not math.isfinite(part) or part < COORD_MIN or part > COORD_MAX
           for part in raw):
        return None

    x1, y1, x2, y2 = raw
    if x2 <= x1 or y2 <= y1:
        return None
    area = ((x2 - x1) / 100.0) * ((y2 - y1) / 100.0)
    if area < MIN_AREA or area > MAX_AREA:
        return None
    return tuple(part / 100.0 for part in raw)


def _dimensions(size):
    if isinstance(size, (tuple, list)) and len(size) == 2:
        return max(1, int(size[0])), max(1, int(size[1]))
    side = max(1, int(size))
    return side, side


def _pixel_box(fractional, width, height):
    """Convert fractional edges to an inclusive PIL rectangle."""
    fx1, fy1, fx2, fy2 = fractional
    x1 = min(width - 1, max(0, int(round(fx1 * width))))
    y1 = min(height - 1, max(0, int(round(fy1 * height))))
    x2 = min(width - 1, max(x1, int(round(fx2 * width)) - 1))
    y2 = min(height - 1, max(y1, int(round(fy2 * height)) - 1))
    return x1, y1, x2, y2


def _axis(index, length, size):
    if index == 0:
        return MARGIN
    if index == 1:
        return (size - length) // 2
    return size - MARGIN - length


def mask_box(position, size=IMG_SIZE):
    """Return (x1, y1, x2, y2) of the white zone for a position."""
    col, row = POSITIONS[normalize_position(position)]
    x1 = _axis(col, ZONE_W, size)
    y1 = _axis(row, ZONE_H, size)
    return x1, y1, x1 + ZONE_W, y1 + ZONE_H


def build_mask(position, size=(IMG_SIZE, IMG_SIZE)):
    """Black image with a white rectangle at the chosen position (white = edit)."""
    width, height = _dimensions(size)
    mask = Image.new("RGB", (width, height), (0, 0, 0))
    x1, y1, x2, y2 = mask_box(position, width)
    ImageDraw.Draw(mask).rectangle(
        (x1, y1, min(width - 1, x2), min(height - 1, y2)), fill=(255, 255, 255))
    return mask


def build_custom_mask(coords, size=(IMG_SIZE, IMG_SIZE)):
    """Black mask with a white box at validated custom coords.

    Invalid coords silently produce the normal centre-zone mask, so a bad form
    value can never crash design generation.
    """
    width, height = _dimensions(size)
    mask = Image.new("RGB", (width, height), (0, 0, 0))
    parsed = parse_coords(coords)
    if parsed is None:
        return build_mask(DEFAULT_POSITION, (width, height))
    ImageDraw.Draw(mask).rectangle(_pixel_box(parsed, width, height),
                                   fill=(255, 255, 255))
    return mask


def build_full_mask(size=(IMG_SIZE, IMG_SIZE)):
    """White everywhere: let the model redesign the entire visible room."""
    width, height = _dimensions(size)
    return Image.new("RGB", (width, height), (255, 255, 255))


def zone_css(position):
    """Percent values the browser preview uses (kept in sync with mask_box)."""
    x1, y1, x2, y2 = mask_box(position)
    return {"left": 100 * x1 / IMG_SIZE, "top": 100 * y1 / IMG_SIZE,
            "width": 100 * ZONE_W / IMG_SIZE, "height": 100 * ZONE_H / IMG_SIZE}
