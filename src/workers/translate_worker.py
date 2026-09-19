"""Background translation with one replaceable pending request."""
from __future__ import annotations

import time
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from PIL import Image
from PySide6.QtCore import QThread, Qt, Signal, Slot
from src.core.translator import Translator
from src.core.watcher import normalize_ocr_text
from src.core.dialogue_content import unpack_scene_text


@dataclass(frozen=True)
class _Request:
    generation: int
    epoch: int
    translator: Translator
    image: Image.Image
    mode: str
    ocr_text: str | None
    submitted: float
    key: tuple | None


class TranslateWorker(QThread):
    CACHE_LIMIT = 128
    result_ready = Signal(object)
    error_occurred = Signal(str)
    started_working = Signal()
    progress_changed = Signal(str)
    queued = Signal()
    _stage_reported = Signal(int, str)

    def __init__(self, translator: Translator, parent=None) -> None:
        super().__init__(parent)
        self._translator = translator
        self._pending = None
        self._job = None
        self._outcome = None
        self._generation = 0
        self._epoch = 0
        self._cache = OrderedDict()
        self._delivery_generation = 0
        self._joined_at = None
        # isRunning() can turn false before Qt delivers finished. Do not
        # replace the active job until the GUI has consumed its outcome.
        self._busy = False
        self.finished.connect(self._finish)
        self._stage_reported.connect(self._relay_progress, Qt.ConnectionType.QueuedConnection)

    def translate(self, image: Image.Image, mode: str = "ocr", ocr_text: str | None = None,
                  *, automatic: bool = False) -> None:
        # Manual translation is an explicit retry, including after a poor but
        # syntactically valid answer. Never resurrect that answer from cache.
        if not automatic:
            self._epoch += 1
            self._cache.clear()
        self._generation += 1
        text = normalize_ocr_text(ocr_text or "") if automatic else ""
        key = (mode, text) if text else None
        request = _Request(self._generation, self._epoch, self._translator,
                           image, mode, ocr_text, time.perf_counter(), key)
        self._pending = None
        if key is not None and key in self._cache:
            self._cache.move_to_end(key)
            result = deepcopy(self._cache[key])
            result.timings = dict(ocr=0.0, model=0.0, refinement=0.0,
                                  queue=0.0, total=0.0, cache_hit=1.0)
            self.result_ready.emit(result)
            return
        if (key is not None and self._busy and self._job.key == key
                and self._job.epoch == self._epoch):
            # A -> queued B -> A: the first A is still useful. Associate its
            # eventual result with the latest observation, not its old generation.
            self._delivery_generation = self._generation
            self._joined_at = request.submitted
            self.progress_changed.emit("复用正在进行的同句请求")
            return
        self._pending = request
        if not self._busy:
            self._start_pending()
        else:
            self.queued.emit()

    def _start_pending(self) -> None:
        if self._pending is None or self._busy:
            return
        self._job, self._pending = self._pending, None
        self._outcome = None
        self._delivery_generation = self._job.generation
        self._joined_at = None
        self._busy = True
        self.started_working.emit()
        self.start()

    def run(self) -> None:
        job = self._job
        queue_seconds = time.perf_counter() - job.submitted
        try:
            def progress(message):
                self._stage_reported.emit(job.generation, message)

            result = (job.translator.translate_vl(job.image, ocr_text=job.ocr_text, progress_callback=progress)
                      if job.mode == "vl" else job.translator.translate_ocr(
                          job.image, ocr_text=job.ocr_text, progress_callback=progress))
            result.timings["queue"] = queue_seconds
            self._outcome = (result, "")
        except Exception as exc:
            self._outcome = (None, f"翻译异常: {exc}")

    @Slot(int, str)
    def _relay_progress(self, generation: int, message: str) -> None:
        # Filtering happens after delivery on the GUI thread: a queued progress
        # event from an old request must not replace the new request's status.
        if (self._busy and self._delivery_generation == self._generation
                and generation == self._job.generation):
            self.progress_changed.emit(message)

    @Slot()
    def _finish(self) -> None:
        job = self._job
        result, error = self._outcome
        self._busy = False
        if (job.key is not None and job.epoch == self._epoch
                and not error and self._complete_result(job, result)):
            # A superseded but successful request is still reusable later.
            # Never let a request from before cancellation/config changes refill it.
            self._cache[job.key] = deepcopy(result)
            self._cache.move_to_end(job.key)
            while len(self._cache) > self.CACHE_LIMIT:
                self._cache.popitem(last=False)
        if self._delivery_generation == self._generation:
            if result is not None and self._joined_at is not None:
                result = deepcopy(result)
                elapsed = max(0.0, time.perf_counter() - self._joined_at)
                result.timings = dict(
                    ocr=0.0, model=0.0, refinement=0.0, queue=0.0,
                    total=elapsed, reuse_wait=elapsed, joined_request=1.0,
                    original_model=result.timings.get("model", 0.0),
                    original_refinement=result.timings.get("refinement", 0.0),
                )
            if error:
                self.error_occurred.emit(error)
            elif result.error and not result.corrected and not result.choices:
                self.error_occurred.emit(result.error)
            else:
                self.result_ready.emit(result)
        self._start_pending()

    @staticmethod
    def _complete_result(job, result) -> bool:
        """Do not preserve errors, malformed answers or partially translated choices."""
        def has_text(value):
            return isinstance(value, str) and bool(value.strip())

        if result is None or result.error or result.warning:
            return False
        scene = unpack_scene_text(job.key[1])
        if scene is None or scene.dialogue:
            if not (has_text(result.corrected) and has_text(result.translation)):
                return False
        if scene is not None:
            if len(result.choices) != len(scene.choices):
                return False
            return all(getattr(c, "index", None) == i
                       and has_text(getattr(c, "corrected", None))
                       and has_text(getattr(c, "translation", None))
                       for i, c in enumerate(result.choices, 1))
        return not result.choices

    def cancel_pending(self) -> None:
        """Drop queued work and ignore the active request's eventual result."""
        self._generation += 1
        self._epoch += 1
        self._cache.clear()
        self._pending = None

    def update_translator(self, translator: Translator) -> None:
        self.cancel_pending()
        self._translator = translator
