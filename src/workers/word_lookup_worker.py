"""Nonblocking word lookup; rapid selections keep only the latest request."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal, Slot
from src.core.translator import Translator
from src.core.llm_client import LLMClient


class WordLookupWorker(QThread):
    result_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, translator: Translator, parent=None) -> None:
        super().__init__(parent)
        self._translator = translator
        self._pending = None
        self._job = None
        self._outcome = None
        self._generation = 0
        self._busy = False
        self.finished.connect(self._finish)

    def lookup(self, selected_text: str, context: str,
               lookup_client: LLMClient | None = None, prompt_template: str = "") -> None:
        self._generation += 1
        self._pending = (self._generation, self._translator, selected_text,
                         context, lookup_client, prompt_template)
        if not self._busy:
            self._start_pending()

    def _start_pending(self) -> None:
        if self._pending is None or self._busy:
            return
        self._job, self._pending = self._pending, None
        self._outcome = None
        self._busy = True
        self.start()

    def run(self) -> None:
        _, translator, selected, context, client, prompt = self._job
        if not selected.strip():
            self._outcome = (None, "未选择任何文本")
            return
        try:
            result = translator.lookup_word(selected_text=selected, context=context,
                                            lookup_client=client, prompt_template=prompt)
            self._outcome = (result, "")
        except Exception as exc:
            self._outcome = (None, f"查词失败: {exc}")

    @Slot()
    def _finish(self) -> None:
        generation = self._job[0]
        result, error = self._outcome
        self._busy = False
        if generation == self._generation:
            if error:
                self.error_occurred.emit(error)
            else:
                self.result_ready.emit(result)
        self._start_pending()

    def cancel_pending(self) -> None:
        self._generation += 1
        self._pending = None

    def update_translator(self, translator: Translator) -> None:
        self.cancel_pending()
        self._translator = translator
