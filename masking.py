"""Mask placement: nine named positions on the 512x512 working image."""
from PIL import Image, ImageDraw

IMG_SIZE = 512
ZONE_W = 150          # same zone size as the original fixed rectangle
ZONE_H = 130
MARGIN = 26           # gap kept between the zone and the image edge

# value -> (column, row) where 0 = start, 1 = middle, 2 = end
POSITIONS = {
    "top_left": (0, 0), "top_center": (1, 0), "top_right": (2, 0),
    "middle_left": (0, 1), "middle_center": (1, 1), "middle_right": (2, 1),
    "bottom_left": (0, 2), "bottom_center": (1, 2), "bottom_right": (2, 2),
}
LABELS = {
    "top_left": "Top left", "top_center": "Top centre", "top_right": "Top right",
    "middle_left": "Middle left", "middle_center": "Centre", "middle_right": "Middle right",
    "bottom_left": "Bottom left", "bottom_center": "Bottom centre", "bottom_right": "Bottom right",
    "whole_room": "Whole room",
}
DEFAULT_POSITION = "middle_center"


def normalize_position(value):
    value = (value or "").strip().lower()
    return value if value in POSITIONS else DEFAULT_POSITION


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
    mask = Image.new("RGB", size, (0, 0, 0))
    ImageDraw.Draw(mask).rectangle(mask_box(position, size[0]), fill=(255, 255, 255))
    return mask


def build_full_mask(size=(IMG_SIZE, IMG_SIZE)):
    """White everywhere: let the model redesign the entire visible room."""
    return Image.new("RGB", size, (255, 255, 255))


def zone_css(position):
    """Percent values the browser preview uses (kept in sync with mask_box)."""
    x1, y1, x2, y2 = mask_box(position)
    return {"left": 100 * x1 / IMG_SIZE, "top": 100 * y1 / IMG_SIZE,
            "width": 100 * ZONE_W / IMG_SIZE, "height": 100 * ZONE_H / IMG_SIZE}
