"""Keep dialogue and player replies separate from capture through translation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Sequence

from PIL import Image, ImageDraw, ImageFont


SCENE_PREFIX = "__SCREENGAZER_SCENE_V1__:"
_SCENE_IMAGE_KEY = "screengazer_scene_v1"


@dataclass(frozen=True)
class SceneText:
    dialogue: str
    choices: tuple[str, ...]

    @property
    def all_text(self) -> str:
        return "\n".join((self.dialogue, *self.choices)).strip()


@dataclass(frozen=True)
class ReplyChoice:
    index: int
    original_ocr: str = ""
    corrected: str = ""
    translation: str = ""


@dataclass(frozen=True)
class SceneImage:
    dialogue: Image.Image | None
    choices: tuple[Image.Image, ...]


def _one_line(text: str) -> str:
    return " ".join(text.split())


def pack_scene_text(dialogue: str, choices: Sequence[str]) -> str:
    """Stable internal encoding; an empty option still occupies its own index."""
    data = {"dialogue": _one_line(dialogue), "choices": [_one_line(c) for c in choices]}
    return SCENE_PREFIX + json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def unpack_scene_text(text: str) -> SceneText | None:
    if not isinstance(text, str) or not text.startswith(SCENE_PREFIX):
        return None
    try:
        data = json.loads(text[len(SCENE_PREFIX):])
        if not isinstance(data, dict) or not isinstance(data.get("dialogue"), str):
            return None
        choices = data.get("choices")
        if not isinstance(choices, list) or not all(isinstance(c, str) for c in choices):
            return None
        return SceneText(data["dialogue"], tuple(choices))
    except (ValueError, TypeError):
        return None


def scene_image_parts(image: Image.Image) -> SceneImage | None:
    parts = image.info.get(_SCENE_IMAGE_KEY)
    return parts if isinstance(parts, SceneImage) else None


def prepare_scene_image(dialogue: Image.Image | None, choices: Sequence[Image.Image]) -> Image.Image:
    """Create a labeled VL/hash image while keeping original crops for local OCR.

    Labels are never passed to OCR. The metadata lives in memory only and is
    deliberately not persisted by PNG encoding or sent as model text.
    """
    if not choices:
        if dialogue is None:
            raise ValueError("A scene needs dialogue or at least one reply option")
        return dialogue
    parts = SceneImage(dialogue, tuple(choices))
    blocks = ([('DIALOGUE', dialogue)] if dialogue is not None else [])
    blocks += [(f'REPLY {i}', crop) for i, crop in enumerate(choices, 1)]
    margin, label_height, gap = 12, 26, 14
    width = max(crop.width for _, crop in blocks) + 2 * margin
    height = sum(crop.height + label_height + gap for _, crop in blocks) + margin
    combined = Image.new('RGB', (width, height), (20, 24, 32))
    draw = ImageDraw.Draw(combined)
    label_font = ImageFont.load_default(size=20)
    top = margin
    for label, crop in blocks:
        draw.text((margin, top), label, fill=(210, 225, 240), font=label_font)
        top += label_height
        combined.paste(crop.convert('RGB'), (margin, top))
        top += crop.height + gap
    combined.info[_SCENE_IMAGE_KEY] = parts
    return combined


def recognize_scene(image: Image.Image, recognize_fn: Callable[[Image.Image], str]) -> str:
    parts = scene_image_parts(image)
    if parts is None:
        return recognize_fn(image)
    dialogue = recognize_fn(parts.dialogue) if parts.dialogue is not None else ""
    choices = [recognize_fn(crop) for crop in parts.choices]
    if not any(text.strip() for text in (dialogue, *choices)):
        return ""
    return pack_scene_text(dialogue, choices)
