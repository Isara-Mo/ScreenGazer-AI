"""
OCR 引擎抽象层
OCR Engine abstraction - supports Tesseract and PaddleOCR (3.x)
"""

from __future__ import annotations

import subprocess
import io
from abc import ABC, abstractmethod
from typing import Optional

from PIL import Image


class OCREngine(ABC):
    """OCR 引擎抽象基类"""

    @abstractmethod
    def recognize(self, image: Image.Image) -> str:
        """
        对图像进行文字识别
        :param image: PIL Image
        :return: 识别出的文字
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """检查引擎是否可用"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """引擎名称"""
        ...


class TesseractEngine(OCREngine):
    """
    Tesseract OCR 引擎
    通过调用 tesseract 可执行文件实现，兼容 snipaste 的配置方式
    """

    def __init__(self, exe_path: str = "tesseract", lang: str = "eng") -> None:
        self.exe_path = exe_path
        self.lang = lang
        self._available: Optional[bool] = None

    @property
    def name(self) -> str:
        return "Tesseract"

    def is_available(self) -> bool:
        if self._available is None:
            try:
                result = subprocess.run(
                    [self.exe_path, "--version"],
                    capture_output=True,
                    timeout=5,
                )
                self._available = result.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                self._available = False
        return self._available

    def _img_to_bytes(self, image: Image.Image) -> bytes:
        """将 PIL Image 转换为 PNG bytes（灰度化提升识别率）"""
        buf = io.BytesIO()
        image.convert("L").save(buf, format="PNG")
        buf.seek(0)
        return buf.read()

    def recognize(self, image: Image.Image) -> str:
        """
        通过 stdin/stdout 管道调用 tesseract 识别图像
        等价于: tesseract stdin stdout -l eng
        """
        if not self.is_available():
            raise RuntimeError(f"Tesseract 不可用，请检查路径: {self.exe_path}")

        cmd = [self.exe_path, "stdin", "stdout", "-l", self.lang, "--psm", "6"]
        try:
            result = subprocess.run(
                cmd,
                input=self._img_to_bytes(image),
                capture_output=True,
                timeout=30,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace")
                raise RuntimeError(f"Tesseract 返回错误: {stderr}")
            return result.stdout.decode("utf-8", errors="replace").strip()
        except subprocess.TimeoutExpired:
            raise RuntimeError("Tesseract 识别超时（30s）")

    def quick_recognize(self, image: Image.Image) -> str:
        """
        快速识别（用于变化检测的轻量轮询），失败时静默返回空串
        """
        if not self.is_available():
            return ""
        cmd = [self.exe_path, "stdin", "stdout", "-l", self.lang, "--psm", "6"]
        try:
            result = subprocess.run(
                cmd,
                input=self._img_to_bytes(image),
                capture_output=True,
                timeout=10,
            )
            return result.stdout.decode("utf-8", errors="replace").strip()
        except Exception:
            return ""


class PaddleOCREngine(OCREngine):
    """
    PaddleOCR 引擎（可选）
    兼容 PaddleOCR 2.x 和 3.x API
    安装: uv pip install paddlepaddle paddleocr
    """

    def __init__(self, lang: str = "en") -> None:
        self.lang = lang
        self._ocr = None
        self._available: Optional[bool] = None
        self._api_version: Optional[int] = None  # 2 或 3

    @property
    def name(self) -> str:
        return "PaddleOCR"

    def is_available(self) -> bool:
        if self._available is None:
            try:
                import paddleocr  # noqa: F401
                import paddle      # noqa: F401
                self._available = True
            except ImportError:
                self._available = False
        return self._available

    def _get_ocr(self):
        """懒加载 PaddleOCR 实例，自动检测 API 版本"""
        if self._ocr is not None:
            return self._ocr

        from paddleocr import PaddleOCR
        import logging
        import warnings

        # 强制静默 ppocr 及相关库的 logging 和 warning 输出
        logging.getLogger("ppocr").setLevel(logging.ERROR)
        logging.getLogger("ppocr").propagate = False
        warnings.filterwarnings("ignore")

        # 尝试 3.x API（参数更少，简洁）
        try:
            self._ocr = PaddleOCR(use_angle_cls=False, lang=self.lang, show_log=False)
            # 检查是否支持 predict()（3.x 特有）
            if hasattr(self._ocr, 'predict'):
                self._api_version = 3
            else:
                self._api_version = 2
        except TypeError:
            # 2.x 的旧 API
            try:
                self._ocr = PaddleOCR(
                    use_angle_cls=False,
                    lang=self.lang,
                    show_log=False,
                    use_gpu=False,
                )
            except Exception:
                self._ocr = PaddleOCR(
                    lang=self.lang,
                    show_log=False,
                )
            self._api_version = 2

        return self._ocr

    def recognize(self, image: Image.Image) -> str:
        if not self.is_available():
            raise RuntimeError(
                "PaddleOCR 不可用，请安装:\n"
                "  uv pip install paddlepaddle paddleocr"
            )

        import numpy as np
        import logging
        import warnings
        logging.getLogger("ppocr").setLevel(logging.ERROR)
        warnings.filterwarnings("ignore")

        img_array = np.array(image.convert("RGB"))
        ocr = self._get_ocr()

        lines: list[str] = []

        if self._api_version == 3:
            # PaddleOCR 3.x: 使用 predict() 方法
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    results = ocr.predict(img_array)
                for item in (results or []):
                    if isinstance(item, dict):
                        # 新格式: {'rec_texts': [...], 'rec_scores': [...], ...}
                        texts = item.get('rec_texts') or item.get('texts', [])
                        lines.extend(t for t in texts if t)
                    elif isinstance(item, list):
                        # 备用格式: [(box, (text, conf)), ...]
                        for entry in item:
                            if entry and len(entry) >= 2:
                                text_info = entry[1]
                                if isinstance(text_info, (list, tuple)):
                                    lines.append(str(text_info[0]))
            except Exception:
                # 降级到 ocr() 方法
                self._api_version = 2
                return self.recognize(image)
        else:
            # PaddleOCR 2.x: 使用 ocr() 方法
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                result = ocr.ocr(img_array, cls=False)
            if result and result[0]:
                for line in result[0]:
                    if line and len(line) >= 2:
                        text = line[1][0] if isinstance(line[1], (list, tuple)) else line[1]
                        lines.append(str(text))

        return "\n".join(lines)


def create_engine(engine_type: str, **kwargs) -> OCREngine:
    """
    工厂函数：根据配置创建 OCR 引擎
    :param engine_type: "tesseract" 或 "paddleocr"
    """
    if engine_type.lower() == "tesseract":
        return TesseractEngine(
            exe_path=kwargs.get("tesseract_path", "tesseract"),
            lang=kwargs.get("tesseract_lang", "eng"),
        )
    elif engine_type.lower() in ("paddleocr", "paddle"):
        return PaddleOCREngine(
            lang=kwargs.get("paddleocr_lang", "en"),
        )
    else:
        raise ValueError(f"未知的 OCR 引擎类型: {engine_type}")
