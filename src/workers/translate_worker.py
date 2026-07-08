"""
翻译任务 Worker (QThread)
Translate Worker - runs OCR + LLM or VL translation in background
"""

from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QThread, Signal

from src.core.translator import Translator, TranslationResult


class TranslateWorker(QThread):
    """
    在后台线程中执行翻译任务
    
    Signals:
        result_ready(TranslationResult): 翻译完成，携带结果
        error_occurred(str): 翻译失败
        started_working(): 开始工作（用于显示 loading 状态）
    """

    result_ready = Signal(object)       # TranslationResult
    error_occurred = Signal(str)
    started_working = Signal()

    def __init__(self, translator: Translator, parent=None) -> None:
        super().__init__(parent)
        self._translator = translator
        self._image: Image.Image | None = None
        self._mode: str = "ocr"   # "ocr" or "vl"

    def translate(self, image: Image.Image, mode: str = "ocr") -> None:
        """
        提交翻译任务（若线程已在运行则等待完成）
        :param image: 截图
        :param mode: "ocr" 或 "vl"
        """
        if self.isRunning():
            self.quit()
            self.wait(3000)
        self._image = image
        self._mode = mode
        self.start()

    def run(self) -> None:
        self.started_working.emit()

        if self._image is None:
            self.error_occurred.emit("没有可翻译的图像")
            return

        try:
            if self._mode == "vl":
                result = self._translator.translate_vl(self._image)
            else:
                result = self._translator.translate_ocr(self._image)

            if result.error and not result.corrected:
                self.error_occurred.emit(result.error)
            else:
                self.result_ready.emit(result)

        except Exception as e:
            self.error_occurred.emit(f"翻译异常: {e}")

    def update_translator(self, translator: Translator) -> None:
        """更新翻译器（切换模型或模式后调用）"""
        self._translator = translator
