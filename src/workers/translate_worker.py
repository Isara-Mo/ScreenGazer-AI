"""Background translation with one replaceable pending request."""
from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QThread, Signal, Slot
from src.core.translator import Translator


class TranslateWorker(QThread):
    result_ready = Signal(object)
    error_occurred = Signal(str)
    started_working = Signal()

    def __init__(self, translator: Translator, parent=None) -> None:
        super().__init__(parent)
        self._translator = translator
        self._pending = None
        self._job = None
        self._outcome = None
        self._generation = 0
        # isRunning() can turn false before Qt delivers finished. Do not
        # replace the active job until the GUI has consumed its outcome.
        self._busy = False
        self.finished.connect(self._finish)

    def translate(self, image: Image.Image, mode: str = "ocr", ocr_text: str | None = None) -> None:
        self._generation += 1
        self._pending = (self._generation, self._translator, image, mode, ocr_text)
        if not self._busy:
            self._start_pending()

    def _start_pending(self) -> None:
        if self._pending is None or self._busy:
            return
        self._job, self._pending = self._pending, None
        self._outcome = None
        self._busy = True
        self.started_working.emit()
        self.start()

    def run(self) -> None:
        _, translator, image, mode, ocr_text = self._job
        try:
            result = (translator.translate_vl(image, ocr_text=ocr_text) if mode == "vl"
                      else translator.translate_ocr(image, ocr_text=ocr_text))
            self._outcome = (result, "")
        except Exception as exc:
            self._outcome = (None, f"翻译异常: {exc}")

    @Slot()
    def _finish(self) -> None:
        generation = self._job[0]
        result, error = self._outcome
        self._busy = False
        if generation == self._generation:
            if error:
                self.error_occurred.emit(error)
            elif result.error and not result.corrected:
                self.error_occurred.emit(result.error)
            else:
                self.result_ready.emit(result)
        self._start_pending()

    def cancel_pending(self) -> None:
        """Drop queued work and ignore the active request's eventual result."""
        self._generation += 1
        self._pending = None

    def update_translator(self, translator: Translator) -> None:
        self.cancel_pending()
        self._translator = translator
