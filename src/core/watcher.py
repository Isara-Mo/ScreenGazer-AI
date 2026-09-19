"""Poll local OCR for stable text, independently of animated backgrounds."""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, Optional

import imagehash
from PIL import Image

from src.core.dialogue_content import pack_scene_text, unpack_scene_text


WATCH_PRESETS = {
    "auto": {"label": "自动适应（推荐）", "poll_interval": 0.3,
             "stability_count": 2, "hash_threshold": 5},
    "fast": {"label": "快速字幕", "poll_interval": 0.2,
             "stability_count": 2, "hash_threshold": 5},
    "stable": {"label": "慢速打字", "poll_interval": 0.5,
               "stability_count": 3, "hash_threshold": 5},
    "custom": {"label": "手动微调"},
}


@dataclass(frozen=True)
class WatchTiming:
    """Measured work for the pending dialogue, before a translation request.

    ``stable_seconds`` describes overlapping screenshot observations; it is
    not an additional phase to add to capture and OCR work.
    """

    started_at: float
    submitted_at: float
    capture_seconds: float
    ocr_seconds: float
    ocr_samples: int
    stable_seconds: float


@dataclass(frozen=True)
class WatchObservation:
    """An observed dialogue state, independent of localized progress messages."""

    kind: str
    text: str = ""
    manual: bool = False
    timing: WatchTiming | None = field(default=None, compare=False)


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
    scene = unpack_scene_text(text)
    if scene is not None:
        return pack_scene_text(normalize_ocr_text(scene.dialogue),
                               [normalize_ocr_text(choice) for choice in scene.choices])
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
        manual_capture_fn: Callable[[], Optional[Image.Image]] | None = None,
        empty_capture_status: str = "未配置捕获区域",
        progress_callback: Callable[[str], None] | None = None,
        observation_callback: Callable[[WatchObservation], None] | None = None,
    ) -> None:
        self._capture = capture_fn
        self._manual_capture = manual_capture_fn
        self._empty_capture_status = empty_capture_status
        self._quick_ocr = quick_ocr_fn
        self._progress_callback = progress_callback
        self._observation_callback = observation_callback
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
        self._cycle_started = self._clock()
        self._cycle_capture_duration = 0.0
        self._cycle_ocr_duration = 0.0
        self._sampled_at = self._clock()
        self._last_observation: WatchObservation | None = None
        self._reset_timing()

    def _reset_timing(self) -> None:
        self._episode_started: float | None = None
        self._episode_capture_seconds = 0.0
        self._episode_ocr_seconds = 0.0
        self._episode_ocr_samples = 0
        self._episode_candidate = ""
        self._episode_candidate_since = 0.0

    def _record_timing(self, text: str) -> None:
        """Count this completed OCR sample exactly once in the pending line."""
        if self._episode_started is None:
            self._episode_started = self._cycle_started
        self._episode_capture_seconds += self._cycle_capture_duration
        self._episode_ocr_seconds += self._cycle_ocr_duration
        self._episode_ocr_samples += 1
        if text != self._episode_candidate:
            self._episode_candidate = text
            self._episode_candidate_since = self._sampled_at

    def _submission_timing(self, *, manual: bool) -> WatchTiming:
        submitted = self._clock()
        started = self._episode_started
        if started is None:
            started = self._cycle_started
        elapsed = max(0.0, submitted - started)
        # Work is sequential. Bound floating-point roundoff so a caller can
        # safely derive remaining waiting/processing time by subtraction.
        capture = min(elapsed, self._episode_capture_seconds)
        ocr = min(max(0.0, elapsed - capture), self._episode_ocr_seconds)
        stable = 0.0 if manual else max(0.0, self._sampled_at - self._episode_candidate_since)
        return WatchTiming(started, submitted, capture, ocr,
                           self._episode_ocr_samples, min(elapsed, stable))

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
        """Wait until the next capture, accounting for work already completed.

        OCR is synchronous within the worker. Adding a whole sampling interval
        after it (and another OCR-duration multiplier in auto mode) makes slow
        OCR unnecessarily slower. Keep a short CPU rest when work overruns the
        requested cadence; idle OCR has its own deadline below.
        """
        now = self._clock()
        elapsed = max(0.0, now - self._cycle_started)
        rest = max(0.02, min(0.15, self._cycle_ocr_duration * 0.2))
        wait = max(rest, self.poll_interval - elapsed)
        pending = self._candidate_text and self._candidate_text != self._last_triggered_text
        if pending and self.preset != "custom" and self._stable_streak >= self.stability_count:
            deadline = self._candidate_since + self._settle_seconds
            if self._sampled_at < deadline:
                # Once sample count is sufficient, confirm at the settling
                # deadline instead of OCRing just before it and sleeping again.
                return max(rest, deadline - now)
        if not pending and self._ocr_due_at > now:
            wait = min(wait, max(rest, self._ocr_due_at - now))
        return wait

    @property
    def _idle_ocr_interval(self) -> float:
        """Idle OCR backs off; inexpensive screen checks remain responsive."""
        idle_seconds = self._clock() - self._unchanged_since
        factor = min(3.0, 1.0 + max(0.0, idle_seconds - 3.0) / 5.0)
        if self.preset != "auto":
            factor = 2.0
        return min(1.5, self.poll_interval * factor)

    @property
    def stats(self) -> dict:
        return {
            "preset": self.preset,
            "effective_interval": self.next_poll_interval,
            "ocr_duration": self._ocr_duration,
            "ocr_samples": self._ocr_samples,
            "stable_samples": self._stable_streak,
            "hash_difference": self._last_hash_diff,
            "ocr_recheck_interval": self._idle_ocr_interval,
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
        self._reset_timing()

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
        self._reset_timing()

    def _capture_frame(self, *, manual: bool = False) -> Optional[Image.Image]:
        try:
            capture = self._manual_capture if manual and self._manual_capture is not None else self._capture
            started = self._clock()
            image = capture()
            self._cycle_capture_duration = max(0.0, self._clock() - started)
        except Exception:
            self._invalidate_candidate()
            raise
        if image is None:
            self._invalidate_candidate()
        return image

    def _recognize(self, image: Image.Image) -> str:
        if self._progress_callback is not None:
            message = "本地 OCR 识别中"
            if not self._ocr_samples:
                message += "（首次加载可能较慢）"
            self._progress_callback(message)
        started = self._clock()
        try:
            text = (self._quick_ocr(image) or "").strip()
        except Exception:
            self._invalidate_candidate()
            raise
        duration = max(0.0, self._clock() - started)
        self._cycle_ocr_duration = duration
        self._ocr_duration = duration if not self._ocr_samples else self._ocr_duration * 0.7 + duration * 0.3
        self._ocr_samples += 1
        return text

    def _observe(self, kind: str, text: str = "", *, manual: bool = False,
                 timing: WatchTiming | None = None) -> None:
        observation = WatchObservation(kind, text, manual, timing)
        if kind != "submitted" and observation == self._last_observation:
            return
        self._last_observation = observation
        if self._observation_callback is not None:
            self._observation_callback(observation)

    def _emit(self, image: Image.Image, raw_text: str, normalized: str, *, manual: bool = False) -> None:
        # Deliver request identity before its corresponding translation signal.
        self._observe("submitted", normalized, manual=manual,
                      timing=self._submission_timing(manual=manual))
        self._on_stable(image, raw_text)
        self._last_triggered_text = normalized
        self._last_trigger_time = self._clock()
        self._reset_timing()

    def force_trigger(self) -> str:
        """Manual request, called by the worker (never directly from the GUI)."""
        self._cycle_started = self._clock()
        self._cycle_capture_duration = 0.0
        self._cycle_ocr_duration = 0.0
        self._reset_timing()
        image = self._capture_frame(manual=True)
        if image is None:
            self._observe("unavailable", manual=True)
            return self._status("未配置捕获区域")
        self._sampled_at = self._clock()
        raw_text = self._recognize(image)
        normalized = normalize_ocr_text(raw_text)
        if not normalized:
            self._invalidate_candidate()
            self._observe("empty", manual=True)
            return self._status("未识别到文本")
        self._candidate_text = normalized
        self._candidate_since = self._clock()
        self._unchanged_since = self._clock()
        self._stable_streak = 0
        self._record_timing(normalized)
        self._emit(image, raw_text, normalized, manual=True)
        return self._status("已手动触发翻译")

    def tick(self) -> str:
        self._cycle_started = self._clock()
        self._cycle_capture_duration = 0.0
        self._cycle_ocr_duration = 0.0
        image = self._capture_frame()
        if image is None:
            self._observe("unavailable")
            return self._status(self._empty_capture_status)
        self._sampled_at = self._clock()

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

        ocr_started = self._clock()
        raw_text = self._recognize(image)
        text = normalize_ocr_text(raw_text)
        now = self._clock()
        # Even identical hashes are rechecked. Pending lines never use this skip.
        # This is a start-to-start deadline, not another delay after OCR.
        self._ocr_due_at = ocr_started + self._idle_ocr_interval
        if not text:
            if self._candidate_text:
                self._unchanged_since = now
            self._candidate_text = ""
            self._stable_streak = 0
            self._reset_timing()
            self._observe("empty")
            return self._status("监视中，未识别到文本")

        if text != self._candidate_text:
            self._candidate_text = text
            self._candidate_since = self._sampled_at
            self._unchanged_since = now
            self._stable_streak = 1
        else:
            self._stable_streak += 1

        if text == self._last_triggered_text:
            self._reset_timing()
            self._observe("current", text)
            return self._status("文字未变化，已省略 API 调用")

        self._record_timing(text)
        self._observe("candidate", text)
        # Compare screenshot times: variable OCR/cold-start latency must not
        # create or erase time for which we actually observed stable text.
        settled_for = self._sampled_at - self._candidate_since
        if self._stable_streak < self.stability_count or settled_for + 1e-9 < self._settle_seconds:
            return self._status(
                f"等待文字稳定（{self._stable_streak}/{self.stability_count} 次，"
                f"{settled_for:.1f}/{self._settle_seconds:.1f}s）"
            )

        cooldown_left = self.cooldown_seconds - (now - self._last_trigger_time)
        if cooldown_left > 0:
            # Keep the candidate; every subsequent tick can release it.
            return self._status(f"文字已稳定，等待冷却 {cooldown_left:.1f}s")

        self._emit(image, raw_text, text)
        scene = unpack_scene_text(raw_text)
        preview = f"含 {len(scene.choices)} 条回复选项" if scene else raw_text[:24]
        return self._status(f"文字已更新（{preview}），已触发翻译")
