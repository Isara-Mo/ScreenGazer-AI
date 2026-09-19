"""Conservative layout detection for Genshin's ordinary dialogue scenes.

The input should include the entire possible dialogue area, including the
speaker. Colour and glyph geometry locate the white dialogue below the gold
speaker/title; OCR still sees the original RGB pixels. Uncertain frames are
returned intact, including fades, menus, and dialogue without a gold speaker.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from PIL import Image
from scipy import ndimage


# Relative x, y, width, height in the selected game window. This is deliberately
# generous: text lines and optional NPC titles move within this area.
GENSHIN_DIALOGUE_REGION = (0.04, 0.62, 0.92, 0.36)


@dataclass(frozen=True)
class DialogueCrop:
    image: Image.Image
    bounds: tuple[int, int, int, int]
    detected: bool
    reason: str


@dataclass(frozen=True)
class _Glyph:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def height(self) -> int:
        return self.bottom - self.top


def _glyphs(mask: np.ndarray, min_height: float, max_height: float) -> list[_Glyph]:
    """Reject long rules, solid scenery, and isolated antialiasing pixels."""
    labels, _ = ndimage.label(mask, structure=np.ones((3, 3), dtype=bool))
    counts = np.bincount(labels.ravel())
    result = []
    for index, bounds in enumerate(ndimage.find_objects(labels), 1):
        if bounds is None:
            continue
        ys, xs = bounds
        height, width = ys.stop - ys.start, xs.stop - xs.start
        density = counts[index] / (height * width)
        if (min_height <= height <= max_height and width <= height * 4
                and counts[index] >= max(4, min_height * min_height * 0.1)
                and 0.1 <= density <= 0.9):
            result.append(_Glyph(xs.start, ys.start, xs.stop, ys.stop))
    return result


def _lines(glyphs: list[_Glyph]) -> list[list[_Glyph]]:
    """Group glyphs by their vertical alignment, allowing different cap heights."""
    lines: list[list[_Glyph]] = []
    for glyph in sorted(glyphs, key=lambda item: (item.top, item.left)):
        center = (glyph.top + glyph.bottom) / 2
        for line in reversed(lines):
            line_center = float(np.median([(item.top + item.bottom) / 2 for item in line]))
            line_height = float(np.median([item.height for item in line]))
            if abs(center - line_center) <= max(glyph.height, line_height) * 0.55:
                line.append(glyph)
                break
        else:
            lines.append([glyph])
    return sorted(lines, key=lambda line: min(item.top for item in line))


def prepare_genshin_dialogue(image: Image.Image) -> DialogueCrop:
    """Remove a verified gold speaker/title header without trimming body lines.

    ``bounds`` uses PIL's (left, top, right, bottom) coordinates in the input.
    Horizontal and bottom edges are retained even if glyph detection misses a
    word. This function performs no OCR and has no state or external effects.
    """
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    width, height = rgb.size

    def unchanged(reason: str) -> DialogueCrop:
        return DialogueCrop(rgb, (0, 0, width, height), False, reason)

    if width < 100 or height < 40:
        return unchanged("image_too_small")

    # Bound CPU and memory cost on 4K screens. Coordinates are converted back;
    # the output never contains resized or colour-filtered pixels.
    scale = min(1.0, 1400 / width, 800 / height)
    sample = rgb if scale == 1 else rgb.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.BILINEAR
    )
    pixels = np.asarray(sample).astype(np.int16)
    red, green, blue = pixels[..., 0], pixels[..., 1], pixels[..., 2]
    h, w = red.shape
    gold = ((red >= 175) & (green >= 105) & (blue < 145)
            & (red >= green * 1.06) & (green >= blue * 1.4) & (red - blue >= 70))
    minimum = max(3, w / 600)
    gold_glyphs = [glyph for glyph in _glyphs(gold, minimum, min(h * 0.3, w * 0.08))
                   if glyph.left >= w * 0.18 and glyph.right <= w * 0.82]
    header_lines = []
    for line in _lines(gold_glyphs):
        left, right = min(g.left for g in line), max(g.right for g in line)
        line_height = float(np.median([g.height for g in line]))
        # A single continue-diamond is not a name, and a row of gold scenery
        # must not qualify merely because one of its pixels touches the centre.
        if (len(line) >= 2 and w * 0.025 <= right - left <= w * 0.6
                and abs((left + right) / 2 - w / 2) <= w * 0.11
                and right - left >= line_height * 1.4):
            header_lines.append(line)
    if not header_lines:
        return unchanged("no_speaker_header")

    white = ((np.minimum(np.minimum(red, green), blue) >= 190)
             & (np.maximum(np.maximum(red, green), blue)
                - np.minimum(np.minimum(red, green), blue) <= 55))

    for header in header_lines:
        header_top = min(g.top for g in header)
        header_bottom = max(g.bottom for g in header)
        letter_height = float(np.median([g.height for g in header]))
        white_glyphs = _glyphs(white, max(3, letter_height * 0.4), letter_height * 2.2)
        body_lines = []
        for line in _lines(white_glyphs):
            left, right = min(g.left for g in line), max(g.right for g in line)
            top = min(g.top for g in line)
            if (len(line) >= 3 and right - left >= letter_height * 1.5
                    and left < w * 0.65 and right > w * 0.35):
                body_lines.append((top, line))
        # Gold emphasized words within an existing white sentence are not a
        # header. Also avoid choosing an incidental gold row below body text.
        if any(top < header_bottom for top, _ in body_lines):
            continue
        following = [(top, line) for top, line in body_lines
                     if header_bottom <= top <= header_bottom + letter_height * 3.5]
        if not following:
            continue
        body_top, _ = min(following, key=lambda item: item[0])
        # A very short first line ("Oh...", for example) may contain too few
        # glyphs to confirm a body row. Never trim it just because a longer
        # second line is easier to recognise; uncertainty keeps the input.
        if any(header_bottom <= g.top < body_top
               and g.left < w * 0.65 and g.right > w * 0.35 for g in white_glyphs):
            continue
        # Extra gold rows between name and body can be NPC titles. The first
        # white body row is the anchor, so titles need no fixed height rules.
        last_header_bottom = max(
            (max(g.bottom for g in line) for line in header_lines
             if min(g.top for g in line) >= header_top and max(g.bottom for g in line) < body_top),
            default=header_bottom,
        )
        padding = max(2, round(letter_height * 0.2))
        crop_top = max(last_header_bottom + 1, body_top - padding)
        if crop_top >= body_top or crop_top >= h - minimum:
            continue
        # Floor preserves the upper antialiasing pixels after downsampling.
        original_top = max(0, math.floor(crop_top * height / h))
        bounds = (0, original_top, width, height)
        return DialogueCrop(rgb.crop(bounds), bounds, True, "speaker_and_dialogue_detected")

    return unchanged("no_verified_dialogue_below_header")
