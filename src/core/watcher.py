"""Poll local OCR for stable text, independently of animated backgrounds."""

from __future__ import annotations

import re
import time
import unicodedata
from typing import Callable, Optional

import imagehash
from PIL import Image


WATCH_PRESETS = {
    "auto": {"label": "自动适应（推荐）", "poll_interval": 0.3,
             "stability_count": 2, "hash_threshold": 5},
    "fast": {"label": "快速字幕", "poll_interval": 0.2,
             "stability_count": 2, "hash_threshold": 5},
    "stable": {"label": "慢速打字", "poll_interval": 0.5,
               "stability_count": 3, "hash_threshold": 5},
    "custom": {"label": "手动微调"},
}


def resolve_watch_settings(
    preset: str = "auto", poll_interval: float = 0.3,
    stability_count: int = 2, hash_threshold: int = 5,
) -> dict:
    """Resolve named presets; only custom uses the supplied manual values."""
    preset = preset if preset in WATCH_PRESETS else "auto"
    values = WATCH_PRESETS[preset]
    return {
        "preset": preset,
        "poll_interval": max(0.1, min(5.0, float(values.get("poll_interval", poll_interval)))),
        "stability_count": max(1, min(20, int(values.get("stability_count", stability_count)))),
        "hash_threshold": max(0, min(64, int(values.get("hash_threshold", hash_threshold)))),
    }


def normalize_ocr_text(text: str) -> str:
    """Normalize layout, while retaining words, case, numbers and punctuation.

    Do not use fuzzy similarity: a single digit or a short negation can change
    the meaning of a game instruction. Limit compatibility folding to width
    forms so that, for example, x² and x2 remain different.
    """
    text = unicodedata.normalize("NFC", text or "")
    text = re.sub(r"[\uff00-\uffef]+", lambda m: unicodedata.normalize("NFKC", m[0]), text)
    text = text.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"}))
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r" +([,.;:!?，。；：！？])", r"\1", text)


class ChangeWatcher:
    """Confirm consecutive OCR results, then emit the image and its OCR text.

    Image similarity only skips redundant idle samples briefly. Every scene,
    including an entirely static scene, is OCR sampled periodically. All work
    and state mutations belong to the worker thread.
    """

    def __init__(
        self,
        capture_fn: Callable[[], Optional[Image.Image]],
        quick_ocr_fn: Callable[[Image.Image], str],
        on_stable: Callable[[Image.Image, str], None],
        poll_interval: float = 0.3,
        stability_count: int = 2,
        hash_threshold: int = 5,
        cooldown_seconds: float = 0.5,
        preset: str = "auto",
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._capture = capture_fn
        self._quick_ocr = quick_ocr_fn
        self._on_stable = on_stable
        self._clock = clock
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        for key, value in resolve_watch_settings(
            preset, poll_interval, stability_count, hash_threshold
        ).items():
            setattr(self, key, value)
        self._running = False
        self._reset_state()

    def _reset_state(self) -> None:
        self._last_hash = None
        self._last_hash_diff = 0
        self._candidate_text = ""
        self._stable_streak = 0
        self._candidate_since = self._clock()
        self._unchanged_since = self._clock()
        self._last_trigger_time = float("-inf")
        self._last_triggered_text = ""
        self._ocr_due_at = float("-inf")
        self._ocr_duration = 0.0
        self._ocr_samples = 0

    def start(self) -> None:
        self._reset_state()
        self._running = True

    def stop(self) -> None:
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def next_poll_interval(self) -> float:
        """Interruptible delay *after* a tick, in addition to OCR runtime."""
        if self.preset != "auto":
            return self.poll_interval
        idle_seconds = self._clock() - self._unchanged_since
        pending = self._candidate_text and self._candidate_text != self._last_triggered_text
        idle_factor = 1.0 if pending else min(3.0, 1.0 + max(0.0, idle_seconds - 3.0) / 5.0)
        # Throttle expensive OCR, but cap the extra wait: model cold startup can take seconds.
        return max(self.poll_interval * idle_factor, min(1.5, self._ocr_duration * 1.5))

    @property
    def stats(self) -> dict:
        return {
            "preset": self.preset,
            "effective_interval": self.next_poll_interval,
            "ocr_duration": self._ocr_duration,
            "ocr_samples": self._ocr_samples,
            "stable_samples": self._stable_streak,
            "hash_difference": self._last_hash_diff,
        }

    @property
    def _settle_seconds(self) -> float:
        if self.preset == "fast":
            return 0.35
        if self.preset == "stable":
            return 1.0
        if self.preset == "auto":
            return 0.65
        return max(0.35, self.poll_interval * (self.stability_count - 1))

    def update_settings(self, **settings) -> None:
        resolved = resolve_watch_settings(
            settings.get("preset", self.preset),
            settings.get("poll_interval", self.poll_interval),
            settings.get("stability_count", self.stability_count),
            settings.get("hash_threshold", self.hash_threshold),
        )
        for key, value in resolved.items():
            setattr(self, key, value)
        # Preserve translation deduplication, but re-confirm an unfinished line.
        self._stable_streak = 0
        self._candidate_since = self._clock()
        self._ocr_due_at = float("-inf")

    def _status(self, message: str) -> str:
        mode = WATCH_PRESETS[self.preset]["label"]
        return (f"{message} · {mode} · 采样等待 {self.next_poll_interval:.2f}s"
                f" / OCR {self._ocr_duration:.2f}s")

    def _invalidate_candidate(self) -> None:
        """A missing or failed observation breaks consecutive text samples."""
        if self._candidate_text:
            self._unchanged_since = self._clock()
        self._candidate_text = ""
        self._stable_streak = 0
        self._candidate_since = self._clock()
        self._ocr_due_at = float("-inf")
        self._last_hash = None

    def _capture_frame(self) -> Optional[Image.Image]:
        try:
            image = self._capture()
        except Exception:
            self._invalidate_candidate()
            raise
        if image is None:
            self._invalidate_candidate()
        return image

    def _recognize(self, image: Image.Image) -> str:
        started = self._clock()
        try:
            text = (self._quick_ocr(image) or "").strip()
        except Exception:
            self._invalidate_candidate()
            raise
        duration = max(0.0, self._clock() - started)
        self._ocr_duration = duration if not self._ocr_samples else self._ocr_duration * 0.7 + duration * 0.3
        self._ocr_samples += 1
        return text

    def _emit(self, image: Image.Image, raw_text: str, normalized: str) -> None:
        self._on_stable(image, raw_text)
        self._last_triggered_text = normalized
        self._last_trigger_time = self._clock()

    def force_trigger(self) -> str:
        """Manual request, called by the worker (never directly from the GUI)."""
        image = self._capture_frame()
        if image is None:
            return self._status("未配置捕获区域")
        raw_text = self._recognize(image)
        normalized = normalize_ocr_text(raw_text)
        if not normalized:
            self._invalidate_candidate()
            return self._status("未识别到文本")
        self._candidate_text = normalized
        self._candidate_since = self._clock()
        self._unchanged_since = self._clock()
        self._stable_streak = 0
        self._emit(image, raw_text, normalized)
        return self._status("已手动触发翻译")

    def tick(self) -> str:
        image = self._capture_frame()
        if image is None:
            return self._status("未配置捕获区域")

        try:
            current_hash = imagehash.phash(image.convert("L"), hash_size=8)
            previous_hash = self._last_hash
            self._last_hash_diff = abs(current_hash - previous_hash) if previous_hash is not None else 0
        except Exception:
            self._invalidate_candidate()
            raise
        self._last_hash = current_hash
        now = self._clock()
        pending = self._candidate_text and self._candidate_text != self._last_triggered_text
        if (previous_hash is not None and self._last_hash_diff <= self.hash_threshold
                and not pending and now < self._ocr_due_at):
            return self._status("画面相似，等待周期文字复查")

        raw_text = self._recognize(image)
        text = normalize_ocr_text(raw_text)
        now = self._clock()
        # Even identical hashes are rechecked. Pending lines never use this skip.
        self._ocr_due_at = now + min(1.5, max(self.poll_interval, self.next_poll_interval) * 2)
        if not text:
            if self._candidate_text:
                self._unchanged_since = now
            self._candidate_text = ""
            self._stable_streak = 0
            return self._status("监视中，未识别到文本")

        if text != self._candidate_text:
            self._candidate_text = text
            self._candidate_since = now
            self._unchanged_since = now
            self._stable_streak = 1
        else:
            self._stable_streak += 1

        if text == self._last_triggered_text:
            return self._status("文字未变化，已省略 API 调用")

        settled_for = now - self._candidate_since
        if self._stable_streak < self.stability_count or settled_for < self._settle_seconds:
            return self._status(
                f"等待文字稳定（{self._stable_streak}/{self.stability_count} 次，"
                f"{settled_for:.1f}/{self._settle_seconds:.1f}s）"
            )

        cooldown_left = self.cooldown_seconds - (now - self._last_trigger_time)
        if cooldown_left > 0:
            # Keep the candidate; every subsequent tick can release it.
            return self._status(f"文字已稳定，等待冷却 {cooldown_left:.1f}s")

        self._emit(image, raw_text, text)
        return self._status(f"文字已更新（{raw_text[:24]}），已触发翻译")
