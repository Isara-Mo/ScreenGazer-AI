"""
配置管理模块 - 负责所有配置的读取与持久化
Config Manager - Handles all configuration read/write operations
"""

import json
import os
from pathlib import Path
from typing import Any


# 默认模型配置列表
DEFAULT_MODELS: list[dict[str, Any]] = [
    {
        "id": "dashscope_default",
        "name": "DashScope (阿里云通义)",
        "api_type": "dashscope",
        "base_url": "https://dashscope.aliyuncs.com/api/v1",
        "api_key": "",
        "text_model": "qwen-turbo",
        "vl_model": "qwen3.6-flash",
        "thinking_mode": "default",
    },
    {
        "id": "openai_default",
        "name": "OpenAI 兼容 API",
        "api_type": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "text_model": "gpt-4o-mini",
        "vl_model": "gpt-4o",
        "thinking_mode": "default",
    },
    {
        "id": "ollama_default",
        "name": "Ollama 本地模型",
        "api_type": "ollama",
        "base_url": "http://localhost:11434",
        "api_key": "",
        "text_model": "llama3.2",
        "vl_model": "llava",
        "thinking_mode": "default",
    },
]

# 默认配置
DEFAULT_CONFIG: dict[str, Any] = {
    "active_model_id": "dashscope_default",         # 主模型 ID
    "active_word_lookup_model_id": "same",          # 查词模型 ID ("same" 表示与主模型相同)
    "models": DEFAULT_MODELS,                        # 模型配置 Profile 列表

    # 识别模式: ocr(OCR+文本LLM) | vl(VL大模型直接识别)
    "recognition_mode": "ocr",

    "ocr": {
        "engine": "paddleocr",                             # tesseract | paddleocr
        "tesseract_path": "E:/Tool/Tesseract/tesseract.exe",
        "tesseract_lang": "eng",
        "paddleocr_lang": "en",
    },

    "prompts": {
        "translate_text": (
            "Please translate the English text to Chinese\n\n"
            "Respond ONLY with a valid JSON object, no extra text:\n"
            "{\"corrected\": \"corrected English text here\", \"translation\": \"中文翻译在这里\"}\n\n"
            "Text to process:\n{text}"
        ),
        "translate_vl": (
            "You are a professional English-Chinese translator.\n"
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
        "poll_interval": 0.3,       # 轮询间隔（秒）
        "stability_count": 2,       # 字数稳定所需连续次数
        "hash_threshold": 8,        # 图像哈希差异阈值（0-64）
    },

    "ui": {
        "panel_geometry": None,     # [x, y, w, h] (合并面板位置)
        "panel_geometry_en": None,  # [x, y, w, h] (英文面板位置)
        "panel_geometry_zh": None,  # [x, y, w, h] (中文面板位置)
        "split_mode": True,         # 是否开启拆分独立模式
        "show_en_panel": True,      # 是否显示英文面板
        "show_zh_panel": True,      # 是否显示中文面板
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
        """从文件加载配置，并在必要时迁移旧版本格式"""
        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)

                # 兼容性迁移：检查是否为旧格式
                if "models" not in saved:
                    saved = self._migrate_legacy_config(saved)

                self._config = self._deep_merge(DEFAULT_CONFIG, saved)
            except (json.JSONDecodeError, OSError):
                self._config = self._deep_copy(DEFAULT_CONFIG)

    def _migrate_legacy_config(self, saved: dict[str, Any]) -> dict[str, Any]:
        """将旧版本的 provider/openai/dashscope/ollama 结构平滑迁移到 models profiles 模式"""
        migrated = self._deep_copy(saved)
        models = self._deep_copy(DEFAULT_MODELS)

        # 尝试使用已保存的 key/model 信息更新默认 profile
        for m in models:
            m_id = m["id"]
            legacy_key = m_id.split("_")[0]  # dashscope, openai, ollama
            if legacy_key in saved and isinstance(saved[legacy_key], dict):
                old_cfg = saved[legacy_key]
                if "base_url" in old_cfg and old_cfg["base_url"]:
                    m["base_url"] = old_cfg["base_url"]
                if "api_key" in old_cfg and old_cfg["api_key"]:
                    m["api_key"] = old_cfg["api_key"]
                if "text_model" in old_cfg and old_cfg["text_model"]:
                    m["text_model"] = old_cfg["text_model"]
                if "vl_model" in old_cfg and old_cfg["vl_model"]:
                    m["vl_model"] = old_cfg["vl_model"]

        provider = saved.get("provider", "dashscope")
        lookup_provider = saved.get("word_lookup_provider", "same")

        provider_map = {
            "dashscope": "dashscope_default",
            "openai": "openai_default",
            "ollama": "ollama_default",
        }

        migrated["models"] = models
        migrated["active_model_id"] = provider_map.get(provider, "dashscope_default")
        if lookup_provider == "same":
            migrated["active_word_lookup_model_id"] = "same"
        else:
            migrated["active_word_lookup_model_id"] = provider_map.get(lookup_provider, "dashscope_default")

        return migrated

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
        例如: cfg.get("watcher", "poll_interval")
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
        例如: cfg.set("active_model_id", "my_custom_id")
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

    def get_model_profiles(self) -> list[dict[str, Any]]:
        """获取所有模型配置 profile"""
        profiles = self._deep_copy(self._config.get("models", DEFAULT_MODELS))
        for p in profiles:
            if "thinking_mode" not in p:
                old_val = p.pop("enable_thinking", None)
                if old_val is True:
                    p["thinking_mode"] = "on"
                elif old_val is False:
                    p["thinking_mode"] = "off"
                else:
                    p["thinking_mode"] = "default"
        return profiles

    def get_model_profile(self, profile_id: str) -> dict[str, Any] | None:
        """根据 ID 获取特定模型配置 profile"""
        for m in self.get_model_profiles():
            if m.get("id") == profile_id:
                return m
        return None

    def get_active_model_profile(self) -> dict[str, Any] | None:
        """获取当前激活的主模型配置 profile"""
        active_id = self.get("active_model_id") or "dashscope_default"
        profile = self.get_model_profile(active_id)
        if profile is None:
            # 回退机制
            profiles = self.get_model_profiles()
            if profiles:
                return profiles[0]
        return profile

    def get_active_lookup_model_profile(self) -> dict[str, Any] | None:
        """获取当前激活的查词模型配置 profile"""
        lookup_id = self.get("active_word_lookup_model_id") or "same"
        if lookup_id == "same":
            return self.get_active_model_profile()
        profile = self.get_model_profile(lookup_id)
        if profile is None:
            return self.get_active_model_profile()
        return profile

    def save_models(self, models: list[dict[str, Any]], active_id: str, lookup_active_id: str) -> None:
        """保存模型 profiles 及选中的激活模型 ID"""
        self.set("models", self._deep_copy(models))
        self.set("active_model_id", active_id)
        self.set("active_word_lookup_model_id", lookup_active_id)
        self.save()

    def reset_to_defaults(self) -> None:
        """重置为默认配置"""
        self._config = self._deep_copy(DEFAULT_CONFIG)


# 模块级单例快捷访问
config = ConfigManager()
