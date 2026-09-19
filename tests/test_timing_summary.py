import unittest
from types import SimpleNamespace

from src.core.timing_summary import format_timing_summary


def monitor(**changes):
    values = dict(started_at=10.0, submitted_at=11.0,
                  capture_seconds=0.1, ocr_seconds=0.3,
                  ocr_samples=3, stable_seconds=0.7)
    values.update(changes)
    return SimpleNamespace(**values)


class TimingSummaryTests(unittest.TestCase):
    def test_monitor_partitions_confirmation_and_marks_overlap(self):
        result = format_timing_summary(
            {"ocr": 0.0, "model": 2.0, "total": 2.1, "queue": 0.2},
            monitor=monitor(), total_seconds=3.4,
        )
        self.assertIn("整体 3.40s（首次检测这句→文字显示）", result)
        self.assertIn("确认文字 1.00s", result)
        self.assertIn("截图/裁切 0.10s · OCR 累计 0.30s/3轮 · 等待/判断 0.60s", result)
        self.assertIn("文字保持一致 0.70s（与确认过程重叠，不另加）", result)
        self.assertIn("请求 OCR：复用监视识别", result)
        self.assertIn("其他处理/显示 0.20s", result)
        self.assertIn("请求合计 2.10s（不含监视/排队）", result)
        self.assertEqual(len(result.splitlines()), 6)

    def test_manual_request_ocr_and_unmeasured_total(self):
        result = format_timing_summary(
            {"ocr": 0.4, "model": 1.0, "total": 1.6},
            manual=True, display_seconds=0.1,
        )
        self.assertIn("整体：未记录（手动采集开始→文字显示）", result)
        self.assertIn("请求 OCR 0.40s", result)
        self.assertIn("其他处理/显示 0.30s", result)
        self.assertNotIn("确认文字", result)
        self.assertNotIn("文字保持一致", result)

    def test_manual_monitor_does_not_claim_text_stability(self):
        result = format_timing_summary({}, manual=True, monitor=monitor())
        self.assertIn("手动采集 1.00s", result)
        self.assertNotIn("文字保持一致", result)

    def test_vision_does_not_claim_zero_cost_or_reused_request_ocr(self):
        result = format_timing_summary(
            {"ocr": 0.0, "ocr_mode": "unused", "model": 1.0},
            monitor=monitor(),
        )
        self.assertIn("OCR 累计 0.30s", result)
        self.assertIn("请求 OCR：未使用", result)
        self.assertNotIn("复用监视识别", result)

    def test_held_time_is_separate_from_other_processing(self):
        result = format_timing_summary(
            {"model": 2.0, "refinement": 0.5, "queue": 0.2, "total": 2.6},
            monitor=monitor(), total_seconds=7.0, held_seconds=3.0,
        )
        self.assertIn("术语校正 0.50s", result)
        self.assertIn("其他处理/显示 0.30s", result)
        self.assertIn("等待对白恢复 3.00s", result)
        self.assertEqual(len(result.splitlines()), 6)

    def test_negative_and_invalid_durations_are_safe(self):
        result = format_timing_summary(
            {"ocr": -1, "model": float("nan"), "queue": None, "total": -4},
            monitor=monitor(submitted_at=9.0, capture_seconds=-1.0,
                            ocr_seconds=float("inf"), stable_seconds=-2.0),
            total_seconds=-5, display_seconds=-1, held_seconds=-1,
        )
        self.assertNotIn("-", result)
        self.assertNotIn("nan", result)
        self.assertNotIn("inf", result)
        self.assertIn("整体 0.00s", result)
        self.assertIn("等待/判断 0.00s", result)

    def test_missing_timings_are_not_invented_as_monitor_ocr(self):
        result = format_timing_summary({})
        self.assertIn("请求 OCR：未使用", result)
        self.assertNotIn("确认文字", result)
        self.assertNotIn("复用监视识别", result)


if __name__ == "__main__":
    unittest.main()
