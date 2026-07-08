"""
单词查询 Worker (QThread)
Word Lookup Worker - queries LLM for word/phrase meaning in context
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from src.core.translator import Translator
from src.core.llm_client import LLMClient


class WordLookupWorker(QThread):
    """
    在后台线程中执行单词/词组查询
    
    Signals:
        result_ready(dict): 查询完成，携带含义数据
        error_occurred(str): 查询失败
    """

    result_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, translator: Translator, parent=None) -> None:
        super().__init__(parent)
        self._translator = translator
        self._selected_text: str = ""
        self._context: str = ""
        self._lookup_client: LLMClient | None = None
        self._prompt_template: str = ""

    def lookup(
        self,
        selected_text: str,
        context: str,
        lookup_client: LLMClient | None = None,
        prompt_template: str = "",
    ) -> None:
        """
        提交查词任务
        :param selected_text: 用户选中的单词或词组
        :param context: 矫正后的完整英文文本（上下文）
        :param lookup_client: 查词专用客户端（None 则用翻译客户端）
        :param prompt_template: 查词 prompt 模板
        """
        if self.isRunning():
            self.quit()
            self.wait(2000)
        self._selected_text = selected_text
        self._context = context
        self._lookup_client = lookup_client
        self._prompt_template = prompt_template
        self.start()

    def run(self) -> None:
        if not self._selected_text.strip():
            self.error_occurred.emit("未选择任何文本")
            return
        try:
            result = self._translator.lookup_word(
                selected_text=self._selected_text,
                context=self._context,
                lookup_client=self._lookup_client,
                prompt_template=self._prompt_template,
            )
            self.result_ready.emit(result)
        except Exception as e:
            self.error_occurred.emit(f"查词失败: {e}")

    def update_translator(self, translator: Translator) -> None:
        self._translator = translator
