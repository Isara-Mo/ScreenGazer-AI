"""Offline dialogue geometry regressions, using generated UI-like text only."""

import unittest

from PIL import Image, ImageDraw, ImageFont

from src.core.game_capture import GENSHIN_DIALOGUE_REGION, prepare_genshin_dialogue


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


class GenshinDialogueTests(unittest.TestCase):
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
