"""Offline dialogue geometry regressions, using generated UI-like text only."""

import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from src.core.game_capture import GENSHIN_DIALOGUE_REGION, prepare_genshin_dialogue
from src.core import game_capture


GOLD = (255, 198, 25)
WHITE = (245, 245, 245)


def dialogue(size=(1200, 330), title=False, lines=1, font_size=28, body_top=None):
    image = Image.new("RGB", size, (25, 32, 60))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=font_size)
    name_top = font_size // 2
    draw.text((size[0] / 2, name_top), "Azhdaha", font=font, fill=GOLD, anchor="mt")
    header_bottom = draw.textbbox((size[0] / 2, name_top), "Azhdaha", font=font, anchor="mt")[3]
    if title:
        title_y = header_bottom + font_size // 2
        text = "Lord of Vishaps"
        draw.text((size[0] / 2, title_y), text, font=font, fill=GOLD, anchor="mt")
        header_bottom = draw.textbbox((size[0] / 2, title_y), text, font=font, anchor="mt")[3]
    body_top = header_bottom + font_size // 2 if body_top is None else body_top
    body_boxes = []
    for index in range(lines):
        text = "We shall meet again in Liyue." if index == 0 else "The contract still binds us all."
        y = body_top + index * round(font_size * 1.45)
        draw.text((size[0] / 2, y), text, font=font, fill=WHITE, anchor="mt")
        body_boxes.append(draw.textbbox((size[0] / 2, y), text, font=font, anchor="mt"))
    return image, header_bottom, body_boxes


def exploration_hud():
    """Health, level and chat/key prompts after ordinary dialogue closes."""
    image = Image.new("RGB", (1200, 330), (25, 32, 60))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=28)
    draw.rectangle((430, 130, 790, 144), fill=(150, 215, 15))
    for position, text in [((320, 122), "Lv. 90"), ((535, 122), "19091 / 20706"),
                           ((30, 200), "Enter"), ((1000, 200), "E   Q")]:
        draw.text(position, text, fill=WHITE, font=font)
    image.info["text"] = "Lv. 90 19091 / 20706 Enter E Q"
    return image


class GenshinDialogueTests(unittest.TestCase):
    def test_health_level_and_key_prompts_do_not_confirm_dialogue(self):
        image = exploration_hud()
        result = prepare_genshin_dialogue(image)
        self.assertFalse(result.detected)
        self.assertEqual(result.image.tobytes(), image.tobytes())

    def assert_preserves_body(self, original, result, header_bottom, body_boxes):
        self.assertTrue(result.detected, result.reason)
        self.assertEqual(result.bounds[0], 0)
        self.assertEqual(result.bounds[2:], original.size)
        self.assertGreaterEqual(result.bounds[1], header_bottom)
        self.assertLess(result.bounds[1], body_boxes[0][1])
        # Verify actual pixels across every line, rather than only dimensions.
        for left, top, right, bottom in body_boxes:
            before = original.crop((left, top, right, bottom))
            after = result.image.crop((left, top - result.bounds[1], right, bottom - result.bounds[1]))
            self.assertEqual(before.tobytes(), after.tobytes())

    def test_short_dialogue_without_title(self):
        image, header_bottom, boxes = dialogue()
        self.assert_preserves_body(image, prepare_genshin_dialogue(image), header_bottom, boxes)

    def test_optional_npc_title_moves_crop_below_both_header_rows(self):
        ordinary, _, _ = dialogue()
        image, header_bottom, boxes = dialogue(title=True)
        result = prepare_genshin_dialogue(image)
        self.assert_preserves_body(image, result, header_bottom, boxes)
        self.assertGreater(result.bounds[1], prepare_genshin_dialogue(ordinary).bounds[1])

    def test_multiple_body_lines_and_long_final_line_survive(self):
        image, header_bottom, boxes = dialogue(title=True, lines=4)
        self.assert_preserves_body(image, prepare_genshin_dialogue(image), header_bottom, boxes)

    def test_body_has_ocr_context_above_first_line_when_gap_allows(self):
        image, header_bottom, boxes = dialogue(body_top=100)
        result = prepare_genshin_dialogue(image)
        self.assert_preserves_body(image, result, header_bottom, boxes)
        # This margin matters even when every source text pixel survives:
        # Paddle's text boxes can otherwise fragment and drop short words.
        self.assertGreaterEqual(boxes[0][1] - result.bounds[1], 10)

    def test_short_unconfirmed_first_line_is_never_trimmed_for_second_line(self):
        image, header_bottom, _ = dialogue(lines=0)
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=28)
        first_top = header_bottom + 16
        draw.text((image.width / 2, first_top), "Oh...", anchor="mt", fill=WHITE, font=font)
        draw.text((image.width / 2, first_top + 40), "The contract still binds us all.",
                  anchor="mt", fill=WHITE, font=font)
        result = prepare_genshin_dialogue(image)
        self.assertLess(result.bounds[1], first_top)

    def test_small_raised_punctuation_is_not_mistaken_for_an_earlier_line(self):
        image, header_bottom, _ = dialogue(lines=0)
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=36)
        body_text = "Sure. A little light reading will be fine."
        draw.text((600, 80), body_text, anchor="mt", font=font, fill=WHITE)
        body_box = draw.textbbox((600, 80), body_text, anchor="mt", font=font)
        # Like a serif apostrophe, this component begins a pixel above the
        # capitals, overlaps their vertical span, and is too small to qualify
        # as a full letter in the row. It cannot represent a separate sentence.
        draw.line((430, 79, 431, 81, 431, 87, 433, 87), fill=WHITE, width=2)
        result = prepare_genshin_dialogue(image)
        self.assert_preserves_body(image, result, header_bottom, [body_box])
        self.assertLess(result.bounds[1], 79)

    def test_continue_diamond_below_body_is_not_the_header(self):
        image, header_bottom, boxes = dialogue(title=True, lines=3)
        draw = ImageDraw.Draw(image)
        x, y = image.width // 2, image.height - 25
        draw.polygon([(x, y - 12), (x + 12, y), (x, y + 12), (x - 12, y)], outline=GOLD, width=3)
        self.assert_preserves_body(image, prepare_genshin_dialogue(image), header_bottom, boxes)

    def test_gold_continue_diamond_alone_cannot_hide_earlier_dialogue(self):
        image = Image.new("RGB", (1000, 220), (25, 32, 60))
        draw = ImageDraw.Draw(image)
        draw.text((500, 30), "A dialogue without a gold name", anchor="mt", fill=WHITE,
                  font=ImageFont.load_default(size=28))
        draw.polygon([(500, 160), (515, 175), (500, 190), (485, 175)], outline=GOLD, width=3)
        result = prepare_genshin_dialogue(image)
        self.assertFalse(result.detected)
        self.assertEqual(result.image.tobytes(), image.tobytes())

    def test_gold_scenery_and_horizontal_separator_are_not_a_speaker(self):
        image = Image.new("RGB", (1000, 220), (25, 32, 60))
        draw = ImageDraw.Draw(image)
        draw.rectangle((350, 10, 650, 65), fill=GOLD)
        draw.line((0, 85, 999, 85), fill=GOLD, width=2)
        draw.text((500, 105), "A dialogue without a gold name", anchor="mt", fill=WHITE,
                  font=ImageFont.load_default(size=28))
        self.assertFalse(prepare_genshin_dialogue(image).detected)

    def test_gold_keyword_in_body_must_not_drop_previous_white_lines(self):
        image = Image.new("RGB", (1000, 280), (25, 32, 60))
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=28)
        for y, text, color in [(15, "A first body line", WHITE), (95, "Liyue Harbor", GOLD),
                               (135, "And another body line", WHITE)]:
            draw.text((500, y), text, anchor="mt", fill=color, font=font)
        self.assertFalse(prepare_genshin_dialogue(image).detected)

    def test_wide_background_gold_block_does_not_move_valid_crop(self):
        image, header_bottom, boxes = dialogue(title=True)
        ImageDraw.Draw(image).rectangle((5, 2, 180, 175), fill=GOLD)
        self.assert_preserves_body(image, prepare_genshin_dialogue(image), header_bottom, boxes)

    def test_scattered_white_clothing_highlights_above_name_are_not_body(self):
        image = Image.new("RGB", (1200, 330), (90, 80, 60))
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=28)
        for box in [(500, 20, 510, 40), (540, 20, 547, 40), (600, 20, 610, 40)]:
            draw.rectangle(box, outline=WHITE, width=2)
        draw.text((600, 160), "Nefer", anchor="mt", font=font, fill=GOLD)
        draw.text((600, 205), "Hmm... This book looks good. I'll take it.",
                  anchor="mt", font=font, fill=WHITE)
        header_bottom = draw.textbbox((600, 160), "Nefer", anchor="mt", font=font)[3]
        body_box = draw.textbbox((600, 205), "Hmm... This book looks good. I'll take it.",
                                 anchor="mt", font=font)
        self.assert_preserves_body(image, prepare_genshin_dialogue(image), header_bottom, [body_box])

    def test_tall_bright_scenery_beside_small_specks_is_not_a_body_row(self):
        image = Image.new("RGB", (1200, 330), (90, 80, 60))
        draw = ImageDraw.Draw(image)
        for box in [(540, 25, 547, 57), (529, 48, 533, 57), (512, 49, 522, 58)]:
            draw.rectangle(box, outline=WHITE, width=1)
        font = ImageFont.load_default(size=28)
        draw.text((600, 160), "Nefer", anchor="mt", font=font, fill=GOLD)
        draw.text((600, 205), "Wrap it up with the two from before.",
                  anchor="mt", font=font, fill=WHITE)
        result = prepare_genshin_dialogue(image)
        self.assertTrue(result.detected, result.reason)
        self.assertLess(result.bounds[1], 205)
        self.assertGreater(result.bounds[1], 180)

    def test_distant_white_scene_text_does_not_veto_real_dialogue(self):
        # A scene sign is text-like even after geometric filtering, unlike
        # isolated clothing highlights. It belongs to a different text block.
        for scale in (0.5, 1, 2):
            with self.subTest(scale=scale):
                size = (round(1200 * scale), round(330 * scale))
                image = Image.new("RGB", size, (25, 32, 60))
                draw = ImageDraw.Draw(image)
                font = ImageFont.load_default(size=round(28 * scale))
                center = size[0] // 2
                draw.text((center, round(14 * scale)), "A DISTANT SIGN IN THE SCENE",
                          anchor="mt", font=font, fill=WHITE)
                name_xy = (center, round(160 * scale))
                body_xy = (center, round(205 * scale))
                body_text = "Sure. A little light reading won't hurt her."
                draw.text(name_xy, "Nefer", anchor="mt", font=font, fill=GOLD)
                draw.text(body_xy, body_text, anchor="mt", font=font, fill=WHITE)
                header_bottom = draw.textbbox(name_xy, "Nefer", anchor="mt", font=font)[3]
                body_box = draw.textbbox(body_xy, body_text, anchor="mt", font=font)
                self.assert_preserves_body(image, prepare_genshin_dialogue(image),
                                           header_bottom, [body_box])

    def test_nearby_previous_white_row_still_rejects_false_gold_header(self):
        image = Image.new("RGB", (1200, 330), (25, 32, 60))
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=28)
        for y, text, color in [(105, "The previous part of the sentence", WHITE),
                               (160, "Liyue Harbor", GOLD),
                               (205, "is still our destination.", WHITE)]:
            draw.text((600, y), text, anchor="mt", font=font, fill=color)
        self.assertFalse(prepare_genshin_dialogue(image).detected)

    def test_nearby_gold_scenery_does_not_merge_with_name(self):
        image, header_bottom, boxes = dialogue()
        draw = ImageDraw.Draw(image)
        # Both highlights fit the allowed centre band, but are distant from the
        # speaker. A single frame-wide row would reject the real name as wide.
        for box in [(230, 15, 246, 33), (952, 15, 968, 33)]:
            draw.rectangle(box, outline=GOLD, width=2)
        self.assert_preserves_body(image, prepare_genshin_dialogue(image), header_bottom, boxes)

    def test_gold_scenery_does_not_create_header_from_disconnected_fragments(self):
        image = exploration_hud()
        draw = ImageDraw.Draw(image)
        for box in [(370, 72, 379, 92), (500, 72, 509, 92), (750, 72, 759, 92)]:
            draw.rectangle(box, outline=GOLD, width=2)
        self.assertFalse(prepare_genshin_dialogue(image).detected)

    def test_connected_components_are_extracted_once_per_colour(self):
        image, _, _ = dialogue(title=True)
        with patch.object(game_capture, "_glyphs", wraps=game_capture._glyphs) as extract:
            self.assertTrue(prepare_genshin_dialogue(image).detected)
        # Additional title/name candidates must not rescan all white pixels.
        self.assertEqual(extract.call_count, 2)

    def test_conservative_fallback_for_no_gold_or_missing_body(self):
        image, _, _ = dialogue()
        result = prepare_genshin_dialogue(image.convert("L"))
        self.assertFalse(result.detected)
        self.assertEqual(result.image.mode, "RGB")
        self.assertEqual(result.bounds, (0, 0, 1200, 330))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 55, 1199, 329), fill=(25, 32, 60))
        self.assertFalse(prepare_genshin_dialogue(image).detected)

    def test_resolution_and_aspect_ratios(self):
        for size, font_size in [((400, 150), 12), ((960, 345), 25),
                                ((1920, 370), 36), ((2560, 410), 42)]:
            with self.subTest(size=size):
                image, header_bottom, boxes = dialogue(size=size, font_size=font_size, title=True, lines=2)
                self.assert_preserves_body(image, prepare_genshin_dialogue(image), header_bottom, boxes)

    def test_tiny_and_transparent_input_is_safe_rgb(self):
        image = Image.new("RGBA", (60, 30), (255, 198, 25, 255))
        result = prepare_genshin_dialogue(image)
        self.assertFalse(result.detected)
        self.assertEqual(result.image.mode, "RGB")
        self.assertEqual(result.bounds, (0, 0, 60, 30))

    def test_preset_bounds_stay_inside_game_window(self):
        x, y, width, height = GENSHIN_DIALOGUE_REGION
        self.assertLessEqual(x + width, 1)
        self.assertLessEqual(y + height, 1)
        self.assertGreater(width, 0.9)
        self.assertGreater(height, 0.3)


if __name__ == "__main__":
    unittest.main()
