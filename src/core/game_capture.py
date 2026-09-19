"""Conservative layout detection for Genshin's ordinary dialogue scenes.

The input should include the entire possible dialogue area, including the
speaker. Colour and glyph geometry locate the white dialogue below the gold
speaker/title; OCR still sees the original RGB pixels. Uncertain frames are
returned intact, including fades, menus, and dialogue without a gold speaker.
Automatic monitoring must check ``detected`` before forwarding the image;
the intact fallback is intended for previews and explicit manual translation.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from PIL import Image
from scipy import ndimage


# Relative x, y, width, height in the selected game window. This is deliberately
# generous: text lines and optional NPC titles move within this area.
GENSHIN_DIALOGUE_REGION = (0.04, 0.38, 0.95, 0.60)


@dataclass(frozen=True)
class DialogueCrop:
    image: Image.Image
    bounds: tuple[int, int, int, int]
    detected: bool
    reason: str


@dataclass(frozen=True)
class ChoiceCrop:
    """One reply, in screen order, with untouched RGB text pixels."""

    image: Image.Image
    bounds: tuple[int, int, int, int]


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


def _text_runs(glyphs: list[_Glyph]) -> list[list[_Glyph]]:
    """Keep neighbouring glyphs with the proportions of an actual text row.

    Bright clothing and gold scenery also produce small connected components.
    Sharing a vertical coordinate is insufficient: widely separated highlights
    and a tall scenery edge beside tiny specks must not become a sentence.
    Components of Chinese characters may overlap horizontally, so occupancy is
    measured with merged intervals rather than by counting character widths.
    """
    runs = []
    for line in _lines(glyphs):
        median_height = float(np.median([g.height for g in line]))
        letters = sorted((g for g in line
                          if median_height * 0.45 <= g.height <= median_height * 1.85),
                         key=lambda g: g.left)
        groups: list[list[_Glyph]] = []
        right = -math.inf
        for glyph in letters:
            if not groups or glyph.left - right > median_height * 2.3:
                groups.append([])
            groups[-1].append(glyph)
            right = max(g.right for g in groups[-1])
        for group in groups:
            if len(group) < 2:
                continue
            left, right = group[0].left, max(g.right for g in group)
            occupied, previous_right = 0, left
            for glyph in group:
                occupied += max(0, glyph.right - max(previous_right, glyph.left))
                previous_right = max(previous_right, glyph.right)
            if occupied / max(1, right - left) >= 0.35:
                runs.append(group)
    return sorted(runs, key=lambda line: min(g.top for g in line))


def _choice_icons(white: np.ndarray) -> list[_Glyph]:
    """Locate the white reply bubbles by their three aligned dark dots.

    A text row or an F/Enter key is insufficient evidence of a reply. The
    enclosed, evenly spaced dots distinguish these icons from letters, HUD
    labels and the bright scenery behind the translucent buttons.
    """
    labels, _ = ndimage.label(white, structure=np.ones((3, 3), dtype=bool))
    icons = []
    for index, bounds in enumerate(ndimage.find_objects(labels), 1):
        if bounds is None:
            continue
        ys, xs = bounds
        height, width = ys.stop - ys.start, xs.stop - xs.start
        if not (12 <= height <= min(140, white.shape[0] * 0.9)
                and 0.9 <= width / height <= 1.5):
            continue
        component = labels[ys, xs] == index
        if not 0.45 <= component.mean() <= 0.88:
            continue
        holes = ndimage.binary_fill_holes(component) & ~component
        hole_labels, count = ndimage.label(holes)
        areas = np.bincount(hole_labels.ravel())
        dot_ids = [i for i in range(1, count + 1)
                   if max(2, height * width * 0.008) <= areas[i] <= height * width * 0.09]
        if len(dot_ids) != 3 or max(areas[dot_ids]) > min(areas[dot_ids]) * 2.5:
            continue
        centers = sorted(ndimage.center_of_mass(holes, hole_labels, dot_ids), key=lambda p: p[1])
        y_centers = [p[0] for p in centers]
        x_centers = [p[1] for p in centers]
        gaps = np.diff(x_centers)
        if (max(y_centers) - min(y_centers) > height * 0.12
                or not height * 0.25 <= np.mean(y_centers) <= height * 0.7
                or not all(width * 0.16 <= gap <= width * 0.35 for gap in gaps)
                or max(gaps) > min(gaps) * 1.5):
            continue
        icons.append(_Glyph(xs.start, ys.start, xs.stop, ys.stop))
    return sorted(icons, key=lambda icon: icon.top)


def _choice_regions(white: np.ndarray, glyphs: list[_Glyph]) -> list[_Glyph]:
    """Find multi-line text next to verified reply icons in sampled pixels."""
    icons = _choice_icons(white)
    regions = []
    for icon in icons:
        center = (icon.top + icon.bottom) / 2
        neighbours = [other for other in icons if other is not icon
                      and abs(other.left - icon.left) <= icon.height]
        radius = min((abs((other.top + other.bottom) / 2 - center) / 2
                      for other in neighbours), default=icon.height * 2)
        radius = min(icon.height * 4, radius)
        top, bottom = center - radius, center + radius
        letters = [g for g in glyphs
                   if icon.right < g.left and top <= (g.top + g.bottom) / 2 <= bottom
                   and icon.height * 0.3 <= g.height <= icon.height * 1.3]
        lines = [line for line in _text_runs(letters)
                 if min(g.left for g in line) <= icon.right + icon.height * 1.5
                 and max(g.right for g in line) - min(g.left for g in line) >= icon.height * 0.6]
        if not lines:
            continue
        first_top = min(g.top for line in lines for g in line)
        last_bottom = max(g.bottom for line in lines for g in line)
        # Text must actually be beside the icon, rather than only a scene sign
        # elsewhere in the same broad search band.
        if first_top > icon.bottom or last_bottom < icon.top:
            continue
        padding = max(4, round(icon.height * 0.25))
        regions.append(_Glyph(
            icon.right + max(2, round(icon.height * 0.1)),
            max(0, math.floor(first_top - padding)),
            min(white.shape[1], max(g.right for line in lines for g in line) + padding * 2),
            min(white.shape[0], math.ceil(last_bottom + padding)),
        ))
    return regions


def detect_genshin_choices(image: Image.Image) -> tuple[ChoiceCrop, ...]:
    """Return reply text crops in top-to-bottom order, excluding bubble/F icons.

    Input may be a whole game frame or a selected region that includes the
    reply icons. Position and resolution are inferred from their geometry;
    menus without the distinctive three-dot bubble remain unconfirmed.
    """
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    width, height = rgb.size
    if width < 100 or height < 40:
        return ()
    scale = min(1.0, 1400 / width, 800 / height)
    sample = rgb if scale == 1 else rgb.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.BILINEAR
    )
    pixels = np.asarray(sample).astype(np.int16)
    low, high = pixels.min(axis=2), pixels.max(axis=2)
    white = (low >= 190) & (high - low <= 55)
    glyphs = _glyphs(white, 3, min(sample.height * 0.66, sample.width * 0.176))
    choices = []
    for region in _choice_regions(white, glyphs):
        bounds = (math.floor(region.left * width / sample.width),
                  math.floor(region.top * height / sample.height),
                  math.ceil(region.right * width / sample.width),
                  math.ceil(region.bottom * height / sample.height))
        choices.append(ChoiceCrop(rgb.crop(bounds), bounds))
    return tuple(choices)


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
    for line in _text_runs(gold_glyphs):
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
    # Extract connected components once. Busy golden scenery can produce many
    # header candidates, but must not multiply full-frame scans on each tick.
    all_white_glyphs = _glyphs(white, 3, min(h * 0.66, w * 0.176))
    choices = _choice_regions(white, all_white_glyphs)
    # Reply buttons are a separate text block. On wider/taller selections their
    # white rows can otherwise look like earlier dialogue above a gold keyword,
    # incorrectly vetoing the actual speaker/title below them.
    all_white_glyphs = [g for g in all_white_glyphs if not any(
        choice.left <= g.left and g.right <= choice.right
        and choice.top <= g.top and g.bottom <= choice.bottom for choice in choices
    )]

    for header in header_lines:
        header_top = min(g.top for g in header)
        header_bottom = max(g.bottom for g in header)
        letter_height = float(np.median([g.height for g in header]))
        white_glyphs = [g for g in all_white_glyphs
                        if max(3, letter_height * 0.4) <= g.height <= letter_height * 2.2]
        body_lines = []
        for line in _text_runs(white_glyphs):
            left, right = min(g.left for g in line), max(g.right for g in line)
            top = min(g.top for g in line)
            if (len(line) >= 3 and right - left >= letter_height * 1.5
                    and left < w * 0.65 and right > w * 0.35):
                body_lines.append((top, line))
        # Gold emphasized words within the same dialogue block are not a
        # header. Only nearby rows belong to that block: a distant sign or
        # bright clothing above the speaker must not veto real dialogue.
        # Use the full header height here (lowercase glyphs alone underestimate
        # line spacing), rather than treating the entire frame as earlier text.
        if any(top < header_bottom
               and max(g.bottom for g in line) >= header_top - (header_bottom - header_top) * 3.5
               for top, line in body_lines):
            continue
        following = [(top, line) for top, line in body_lines
                     if header_bottom <= top <= header_bottom + letter_height * 3.5]
        if not following:
            continue
        body_top, _ = min(following, key=lambda item: item[0])
        # A very short first line ("Oh...", for example) may contain too few
        # glyphs to confirm a body row. Never trim it just because a longer
        # second line is easier to recognise. A small apostrophe can start
        # above the capital letters of its own row and be omitted by the run
        # filter; vertical overlap still makes it part of that same row.
        if any(header_bottom <= g.top and g.bottom <= body_top
               and g.left < w * 0.65 and g.right > w * 0.35 for g in white_glyphs):
            continue
        # Extra gold rows between name and body can be NPC titles. The first
        # white body row is the anchor, so titles need no fixed height rules.
        last_header_bottom = max(
            (max(g.bottom for g in line) for line in header_lines
             if min(g.top for g in line) >= header_top and max(g.bottom for g in line) < body_top),
            default=header_bottom,
        )
        # OCR text detectors need some background above the first baseline.
        # Keeping only antialiasing pixels can still split an English sentence
        # into boxes and lose short words (for example "I'll" in PaddleOCR).
        # Use the available gap while never restoring the speaker/title.
        padding = max(4, round(letter_height))
        # The component filter can omit tiny descenders / antialiasing pixels
        # from the header. Leave a safety gap before the OCR image starts.
        header_clearance = max(3, math.ceil(letter_height * 0.1))
        crop_top = max(last_header_bottom + header_clearance, body_top - padding)
        if crop_top >= body_top or crop_top >= h - minimum:
            continue
        # Floor preserves the upper antialiasing pixels after downsampling.
        original_top = max(0, math.floor(crop_top * height / h))
        bounds = (0, original_top, width, height)
        return DialogueCrop(rgb.crop(bounds), bounds, True, "speaker_and_dialogue_detected")

    return unchanged("no_verified_dialogue_below_header")
