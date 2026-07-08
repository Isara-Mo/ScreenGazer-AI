"""
翻译协调器
Translator - coordinates OCR + LLM or VL LLM for translation
"""

from __future__ import annotations

import time
from PIL import Image

from src.core.llm_client import LLMClient, parse_json_response
from src.core.ocr_engine import OCREngine


def _safe_format(template: str, **kwargs) -> str:
    """
    安全的模板替换，只替换已知的 {key} 占位符，
    不会因模板中存在 JSON {} 大括号而崩溃（避免 str.format() 的 KeyError）
    """
    result = template
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", str(value))
    return result


class TranslationResult:
    """翻译结果"""
    def __init__(
        self,
        corrected: str = "",
        translation: str = "",
        original_ocr: str = "",
        error: str = "",
    ) -> None:
        self.corrected = corrected          # 矫正后的英文
        self.translation = translation      # 中文翻译
        self.original_ocr = original_ocr   # OCR 原始识别文本（模式1）
        self.error = error                  # 错误信息（若有）

    @property
    def success(self) -> bool:
        return not self.error and bool(self.corrected or self.translation)

    def __repr__(self) -> str:
        return (
            f"TranslationResult(corrected={self.corrected!r}, "
            f"translation={self.translation!r}, error={self.error!r})"
        )


class Translator:
    """
    翻译协调器
    支持两种模式:
    - 模式1 (ocr): 截图 → OCR → 文本 LLM 矫正+翻译
    - 模式2 (vl):  截图 → VL 大模型直接识别+翻译
    """

    def __init__(
        self,
        llm_client: LLMClient,
        ocr_engine: OCREngine | None = None,
        translate_text_prompt: str = "",
        translate_vl_prompt: str = "",
    ) -> None:
        self._llm = llm_client
        self._ocr = ocr_engine
        self._text_prompt_tpl = translate_text_prompt
        self._vl_prompt = translate_vl_prompt

    def translate_ocr(self, image: Image.Image) -> TranslationResult:
        """
        模式1: OCR + 文本 LLM
        1. 使用 OCR 引擎识别图像文字
        2. 将识别结果发送给文本 LLM 进行矫正和翻译
        """
        if self._ocr is None:
            return TranslationResult(error="未配置 OCR 引擎")

        print("\n" + "=" * 20 + " 翻译耗时统计 (OCR模式) " + "=" * 20)
        t_start = time.perf_counter()

        # Step 1: OCR 识别
        try:
            ocr_text = self._ocr.recognize(image)
        except Exception as e:
            return TranslationResult(error=f"OCR 识别失败: {e}")

        t_ocr = time.perf_counter()
        print(f"[耗时] OCR 识别: {t_ocr - t_start:.2f} 秒")

        if not ocr_text.strip():
            return TranslationResult(error="OCR 未识别到文字")

        # Step 2: LLM 矫正 + 翻译
        prompt = _safe_format(self._text_prompt_tpl, text=ocr_text)
        messages = [{"role": "user", "content": prompt}]

        try:
            response = self._llm.chat(messages)
            t_llm = time.perf_counter()
            print(f"[耗时] LLM 响应: {t_llm - t_ocr:.2f} 秒")
            print(f"[耗时] 总计用时: {t_llm - t_start:.2f} 秒")
            print("=" * 64)
            
            data = parse_json_response(response)
            return TranslationResult(
                corrected=data.get("corrected", ocr_text),
                translation=data.get("translation", ""),
                original_ocr=ocr_text,
            )
        except Exception as e:
            return TranslationResult(
                corrected=ocr_text,
                original_ocr=ocr_text,
                error=f"LLM 翻译失败: {e}",
            )

    def translate_vl(self, image: Image.Image) -> TranslationResult:
        """
        模式2: VL 大模型直接识别 + 翻译
        将截图直接发送给 VL 模型进行识别和翻译
        """
        print("\n" + "=" * 20 + " 翻译耗时统计 (VL模式) " + "=" * 20)
        t_start = time.perf_counter()
        try:
            response = self._llm.chat_vision(self._vl_prompt, image)
            t_llm = time.perf_counter()
            print(f"[耗时] VL模型响应: {t_llm - t_start:.2f} 秒")
            print(f"[耗时] 总计用时: {t_llm - t_start:.2f} 秒")
            print("=" * 62)
            
            data = parse_json_response(response)
            return TranslationResult(
                corrected=data.get("corrected", ""),
                translation=data.get("translation", ""),
            )
        except Exception as e:
            return TranslationResult(error=f"VL 模型识别失败: {e}")

    def lookup_word(
        self,
        selected_text: str,
        context: str,
        lookup_client: LLMClient | None = None,
        prompt_template: str = "",
    ) -> dict:
        """
        查询单词/词组在语境中的含义
        :param selected_text: 用户选中的单词或词组
        :param context: 矫正后的完整英文（作为语境）
        :param lookup_client: 查词专用客户端（若 None 则复用翻译客户端）
        :param prompt_template: 查词 Prompt 模板
        :return: dict with keys: word, meaning, part_of_speech, note
        """
        client = lookup_client or self._llm
        prompt = _safe_format(
            prompt_template,
            context=context,
            selected=selected_text,
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            response = client.chat(messages)
            data = parse_json_response(response)
            return {
                "word": data.get("word", selected_text),
                "meaning": data.get("meaning", ""),
                "part_of_speech": data.get("part_of_speech", ""),
                "note": data.get("note", ""),
            }
        except Exception as e:
            return {
                "word": selected_text,
                "meaning": f"查询失败: {e}",
                "part_of_speech": "",
                "note": "",
            }
