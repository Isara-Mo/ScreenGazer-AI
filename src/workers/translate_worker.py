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
    在后台线程中执行翻译任务 (非阻塞版)
    
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
        self._pending_image: Image.Image | None = None
        self._pending_mode: str = "ocr"

    def translate(self, image: Image.Image, mode: str = "ocr") -> None:
        """
        提交翻译任务（非阻塞：若线程忙碌，缓存最新截图待完成后自动处理）
        :param image: 截图
        :param mode: "ocr" 或 "vl"
        """
        if self.isRunning():
            # 正在翻译中，更新 pending 任务，不阻塞主线程 GUI
            self._pending_image = image
            self._pending_mode = mode
            return

        self._image = image
        self._mode = mode
        self._pending_image = None
        self.start()

    def run(self) -> None:
        while True:
            current_image = self._image
            current_mode = self._mode

            if current_image is None:
                self.error_occurred.emit("没有可翻译的图像")
                break

            self.started_working.emit()

            try:
                if current_mode == "vl":
                    result = self._translator.translate_vl(current_image)
                else:
                    result = self._translator.translate_ocr(current_image)

                if result.error and not result.corrected:
                    self.error_occurred.emit(result.error)
                else:
                    self.result_ready.emit(result)

            except Exception as e:
                self.error_occurred.emit(f"翻译异常: {e}")

            # 检查是否有在翻译期间积压的最新待处理截图
            if self._pending_image is not None:
                self._image = self._pending_image
                self._mode = self._pending_mode
                self._pending_image = None
            else:
                break

    def update_translator(self, translator: Translator) -> None:
        """更新翻译器（切换模型或模式后调用）"""
        self._translator = translator
