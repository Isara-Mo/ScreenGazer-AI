"""Reply detection uses generated UI shapes, without shipping game screenshots."""

import unittest

from PIL import Image, ImageDraw, ImageFont

from src.core.game_capture import detect_genshin_choices, prepare_genshin_dialogue
from tests.test_game_capture import exploration_hud


WHITE = (245, 245, 245)
GOLD = (255, 198, 25)
BACKGROUND = (25, 32, 60)


def reply_scene(scale=1, left=730, rows=None, with_dialogue=True):
    """A movable reply block, with optional NPC dialogue immediately below."""
    rows = rows or [("What news today, young", "man?"),
                    ("I'm fine without any", "papers to read.")]
    image = Image.new("RGB", (1200, 600), BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=26)
    boxes = []
    for index, lines in enumerate(rows):
        center_y = 255 + index * 90
        draw.rounded_rectangle((left - 12, center_y - 37, 1188, center_y + 38),
                               radius=35, fill=(34, 41, 55), outline=(110, 105, 80), width=2)
        # Filled speech bubble, with the actual icon's three aligned holes.
        draw.ellipse((left, center_y - 18, left + 39, center_y + 15), fill=WHITE)
        draw.polygon([(left + 24, center_y + 9), (left + 36, center_y + 21),
                      (left + 34, center_y + 4)], fill=WHITE)
        for offset in (9, 19, 29):
            draw.ellipse((left + offset - 2, center_y - 4,
                          left + offset + 2, center_y), fill=BACKGROUND)
        for line_index, text in enumerate(lines):
            y = center_y - len(lines) * 16 + line_index * 32
            position = (left + 52, y)
            draw.text(position, text, font=font, fill=WHITE, anchor="lt")
            boxes.append(draw.textbbox(position, text, font=font, anchor="lt"))
    draw.rounded_rectangle((left - 68, 241, left - 28, 279), radius=3, fill=WHITE)
    draw.text((left - 60, 245), "F", font=font, fill=BACKGROUND, anchor="lt")
    if with_dialogue:
        draw.text((600, 405), "Hannu", anchor="mt", font=font, fill=GOLD)
        draw.text((600, 440), "Newsy", anchor="mt", font=font, fill=GOLD)
        draw.text((600, 483), "Get your fresh newspapers here, sirs and ma'ams!",
                  anchor="mt", font=font, fill=WHITE)
    if scale != 1:
        image = image.resize((round(image.width * scale), round(image.height * scale)),
                             Image.Resampling.LANCZOS)
        boxes = [tuple(round(v * scale) for v in box) for box in boxes]
    return image, boxes


class GenshinChoiceTests(unittest.TestCase):
    def test_two_multiline_replies_preserve_pixels_and_exclude_icons(self):
        image, boxes = reply_scene()
        replies = detect_genshin_choices(image)
        self.assertEqual(len(replies), 2)
        self.assertLess(replies[0].bounds[3], replies[1].bounds[1])
        for index, reply in enumerate(replies):
            self.assertGreater(reply.bounds[0], 770)
            self.assertEqual(reply.image.tobytes(), image.crop(reply.bounds).tobytes())
            for box in boxes[index * 2:index * 2 + 2]:
                self.assertLessEqual(reply.bounds[0], box[0])
                self.assertLessEqual(reply.bounds[1], box[1])
                self.assertGreaterEqual(reply.bounds[2], box[2])
                self.assertGreaterEqual(reply.bounds[3], box[3])

    def test_replies_do_not_veto_dialogue_below_them(self):
        image, _ = reply_scene()
        result = prepare_genshin_dialogue(image)
        self.assertTrue(result.detected, result.reason)
        self.assertGreater(result.bounds[1], 460)
        self.assertLess(result.bounds[1], 483)
        self.assertEqual(result.image.tobytes(), image.crop(result.bounds).tobytes())

    def test_detection_supports_resolution_changes(self):
        for scale in (0.5, 1, 2, 3):
            with self.subTest(scale=scale):
                image, _ = reply_scene(scale=scale)
                self.assertEqual(len(detect_genshin_choices(image)), 2)

    def test_reply_icons_need_not_be_at_a_fixed_screen_position(self):
        image, _ = reply_scene(left=120, with_dialogue=False)
        self.assertEqual(len(detect_genshin_choices(image)), 2)

    def test_single_short_reply_and_narrow_selected_region(self):
        image, boxes = reply_scene(rows=[("No.",)], with_dialogue=False)
        selected = image.crop((700, 210, 950, 300))
        replies = detect_genshin_choices(selected)
        self.assertEqual(len(replies), 1)
        self.assertLessEqual(replies[0].bounds[1], boxes[0][1] - 210)
        self.assertGreaterEqual(replies[0].bounds[3], boxes[0][3] - 210)

    def test_hud_and_bright_plain_text_are_not_replies(self):
        self.assertEqual(detect_genshin_choices(exploration_hud()), ())
        image, _ = reply_scene()
        draw = ImageDraw.Draw(image)
        for center in (255, 345):
            draw.rectangle((729, center - 19, 771, center + 22), fill=BACKGROUND)
        self.assertEqual(detect_genshin_choices(image), ())

    def test_bubble_without_adjacent_text_does_not_confirm_a_reply(self):
        image, _ = reply_scene(with_dialogue=False)
        ImageDraw.Draw(image).rectangle((776, 200, 1199, 399), fill=BACKGROUND)
        self.assertEqual(detect_genshin_choices(image), ())

    def test_key_like_box_with_unaligned_holes_is_not_reply_icon(self):
        image, _ = reply_scene(with_dialogue=False)
        draw = ImageDraw.Draw(image)
        for center in (255, 345):
            draw.rectangle((729, center - 19, 771, center + 22), fill=BACKGROUND)
            draw.rounded_rectangle((731, center - 18, 769, center + 20), radius=4, fill=WHITE)
            for x, y in ((740, center - 10), (750, center), (760, center + 10)):
                draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=BACKGROUND)
        self.assertEqual(detect_genshin_choices(image), ())

    def test_tiny_and_transparent_input(self):
        self.assertEqual(detect_genshin_choices(Image.new("RGBA", (20, 20))), ())
        image, _ = reply_scene()
        replies = detect_genshin_choices(image.convert("RGBA"))
        self.assertEqual(len(replies), 2)
        self.assertTrue(all(reply.image.mode == "RGB" for reply in replies))


if __name__ == "__main__":
    unittest.main()
