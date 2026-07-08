"""
配置管理模块 - 负责所有配置的读取与持久化
Config Manager - Handles all configuration read/write operations
"""

import json
import os
from pathlib import Path
from typing import Any


# 默认配置
DEFAULT_CONFIG: dict[str, Any] = {
    "provider": "dashscope",          # 主模型提供商: openai | dashscope | ollama
    "word_lookup_provider": "same",   # 查词模型提供商: same | openai | dashscope | ollama

    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "text_model": "gpt-4o-mini",
        "vl_model": "gpt-4o",
    },

    "dashscope": {
        # 标准 DashScope 端点，或填写自定义 workspace URL
        "base_url": "https://dashscope.aliyuncs.com/api/v1",
        "api_key": "",
        "text_model": "qwen-turbo",
        "vl_model": "qwen3.6-flash",
    },

    "ollama": {
        "base_url": "http://localhost:11434",
        "text_model": "llama3.2",
        "vl_model": "llava",
    },

    # 识别模式: ocr(OCR+文本LLM) | vl(VL大模型直接识别)
    "recognition_mode": "ocr",

    "ocr": {
        "engine": "tesseract",                             # tesseract | paddleocr
        "tesseract_path": "E:/Tool/Tesseract/tesseract.exe",
        "tesseract_lang": "eng",
        "paddleocr_lang": "en",
    },

    "prompts": {
        "translate_text": (
            "You are a professional English-Chinese translator specializing in visual novels.\n"
            "The following text may contain OCR recognition errors. Please:\n"
            "1. Correct any OCR errors in the English text (fix typos, missing spaces, wrong characters)\n"
            "2. Translate the corrected English text to fluent, natural Chinese\n\n"
            "Respond ONLY with a valid JSON object, no extra text:\n"
            "{\"corrected\": \"corrected English text here\", \"translation\": \"中文翻译在这里\"}\n\n"
            "Text to process:\n{text}"
        ),
        "translate_vl": (
            "You are a professional English-Chinese translator specializing in visual novels.\n"
            "Look at the image and extract the dialog/subtitle English text.\n"
            "1. Provide the clean, corrected English text\n"
            "2. Translate it to fluent, natural Chinese\n\n"
            "Respond ONLY with a valid JSON object, no extra text:\n"
            "{\"corrected\": \"English text from image\", \"translation\": \"中文翻译在这里\"}"
        ),
        "word_lookup": (
            "You are an English language expert helping a Chinese learner understand a visual novel.\n\n"
            "Context (from visual novel):\n{context}\n\n"
            "The learner selected: \"{selected}\"\n\n"
            "Explain the meaning of this word or phrase IN THIS SPECIFIC CONTEXT. Be concise.\n"
            "Respond ONLY with a valid JSON object, no extra text:\n"
            "{\"word\": \"{selected}\", \"meaning\": \"含义（中文解释）\", \"part_of_speech\": \"词性\", \"note\": \"补充说明（可选）\"}"
        ),
    },

    "capture": {
        "mode": "window_region",    # window_region | absolute
        "window_title": "",
        "region": None,             # [x, y, w, h] 相对窗口坐标或绝对坐标
    },

    "hotkey": "ctrl+shift+t",

    "watcher": {
        "enabled": True,
        "poll_interval": 0.5,       # 轮询间隔（秒）
        "stability_count": 3,       # 字数稳定所需连续次数
        "hash_threshold": 8,        # 图像哈希差异阈值（0-64）
    },

    "ui": {
        "panel_geometry": None,     # [x, y, w, h]
        "always_on_top": True,
        "opacity": 0.95,
        "font_size_en": 13,
        "font_size_zh": 14,
    },
}


class ConfigManager:
    """
    单例配置管理器
    配置以 JSON 格式保存在项目根目录的 config.json 文件中
    """

    _instance: "ConfigManager | None" = None
    _config: dict[str, Any] = {}
    _config_path: Path

    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_config()
        return cls._instance

    def _init_config(self) -> None:
        """初始化配置，从文件加载或使用默认值"""
        root = Path(__file__).parent.parent.parent  # 项目根目录
        self._config_path = root / "config.json"
        self._config = self._deep_copy(DEFAULT_CONFIG)
        self._load()

    def _deep_copy(self, obj: Any) -> Any:
        """深拷贝字典/列表"""
        if isinstance(obj, dict):
            return {k: self._deep_copy(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._deep_copy(i) for i in obj]
        return obj

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """深度合并两个字典，override 覆盖 base"""
        result = self._deep_copy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = self._deep_copy(value)
        return result

    def _load(self) -> None:
        """从文件加载配置"""
        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._config = self._deep_merge(DEFAULT_CONFIG, saved)
            except (json.JSONDecodeError, OSError):
                self._config = self._deep_copy(DEFAULT_CONFIG)

    def save(self) -> None:
        """保存配置到文件"""
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"[ConfigManager] 保存配置失败: {e}")

    def get(self, *keys: str, default: Any = None) -> Any:
        """
        链式获取配置值
        例如: cfg.get("dashscope", "api_key")
        """
        node: Any = self._config
        for key in keys:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                return default
        return node

    def set(self, *keys_and_value: Any) -> None:
        """
        链式设置配置值（最后一个参数为值）
        例如: cfg.set("dashscope", "api_key", "sk-xxx")
        """
        *keys, value = keys_and_value
        node = self._config
        for key in keys[:-1]:
            if key not in node or not isinstance(node[key], dict):
                node[key] = {}
            node = node[key]
        node[keys[-1]] = value

    def get_all(self) -> dict[str, Any]:
        """返回完整配置的深拷贝"""
        return self._deep_copy(self._config)

    def reset_to_defaults(self) -> None:
        """重置为默认配置"""
        self._config = self._deep_copy(DEFAULT_CONFIG)


# 模块级单例快捷访问
config = ConfigManager()
