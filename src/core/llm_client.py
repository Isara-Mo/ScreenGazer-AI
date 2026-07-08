"""
大模型客户端抽象层
LLM Client - supports OpenAI-compatible APIs, DashScope (Alibaba), and Ollama
"""

from __future__ import annotations

import base64
import io
import json
import os
import tempfile
from abc import ABC, abstractmethod
from typing import Optional

from PIL import Image


class LLMClient(ABC):
    """大模型客户端抽象基类"""

    @abstractmethod
    def chat(self, messages: list[dict]) -> str:
        """文本对话，返回文本响应"""
        ...

    @abstractmethod
    def chat_vision(self, text_prompt: str, image: Image.Image) -> str:
        """多模态对话（图文），返回文本响应"""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...


def _image_to_base64(image: Image.Image, fmt: str = "PNG") -> str:
    """将 PIL Image 转换为 Base64 字符串"""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format=fmt)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def _image_to_data_uri(image: Image.Image, fmt: str = "PNG") -> str:
    """将 PIL Image 转换为 Data URI"""
    b64 = _image_to_base64(image, fmt)
    mime = "image/png" if fmt.upper() == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{b64}"


def _save_image_to_temp(image: Image.Image) -> str:
    """将图像保存为临时文件，返回文件路径（调用方负责删除）"""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    image.convert("RGB").save(path, format="PNG")
    return path


# ─────────────────────────────────────────────────────────────
# OpenAI 兼容客户端（支持 OpenAI、Ollama、其他兼容 API）
# ─────────────────────────────────────────────────────────────
class OpenAIClient(LLMClient):
    """
    OpenAI 兼容 API 客户端
    适用于: OpenAI、Ollama (localhost:11434/v1)、其他兼容接口
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        vl_model: Optional[str] = None,
        timeout: int = 60,
    ) -> None:
        from openai import OpenAI
        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key or "ollama",
            timeout=timeout,
        )
        self._model = model
        self._vl_model = vl_model or model
        self._name = "OpenAI-Compatible"

    @property
    def provider_name(self) -> str:
        return self._name

    def chat(self, messages: list[dict]) -> str:
        kwargs = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.3,
        }
        if "aliyuncs.com" in str(self._client.base_url):
            kwargs["extra_body"] = {"enable_thinking": False}

        response = self._client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    def chat_vision(self, text_prompt: str, image: Image.Image) -> str:
        b64_img = _image_to_data_uri(image)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_prompt},
                    {"type": "image_url", "image_url": {"url": b64_img}},
                ],
            }
        ]
        
        kwargs = {
            "model": self._vl_model,
            "messages": messages,
            "temperature": 0.3,
        }
        if "aliyuncs.com" in str(self._client.base_url):
            kwargs["extra_body"] = {"enable_thinking": False}

        response = self._client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""


# ─────────────────────────────────────────────────────────────
# DashScope 客户端（阿里云通义千问）
# ─────────────────────────────────────────────────────────────

# 支持 VL 的 DashScope 模型前缀（用于错误提示）
_DASHSCOPE_VL_MODELS = [
    "qwen-vl", "qwen2-vl", "qwen2.5-vl",
    "qvq", "qwen-vl-plus", "qwen-vl-max",
]


class DashScopeClient(LLMClient):
    """
    阿里云 DashScope API 客户端
    支持 qwen 系列文本模型和 qwen-vl 系列多模态模型

    注意 VL 模型选择:
      - 文本模型 (不支持图像): qwen-turbo, qwen-plus, qwen-max, qwen3-*, qwen3.6-flash 等
      - VL 模型 (支持图像): qwen-vl-plus, qwen-vl-max, qwen2.5-vl-7b-instruct 等
    """

    def __init__(
        self,
        api_key: str,
        text_model: str = "qwen-turbo",
        vl_model: str = "qwen-vl-plus",
        base_url: Optional[str] = None,
        timeout: int = 60,
    ) -> None:
        import dashscope
        self._ds = dashscope
        self._ds.api_key = api_key
        if base_url and base_url.strip():
            self._ds.base_http_api_url = base_url.strip()
        self._text_model = text_model
        self._vl_model = vl_model
        self._timeout = timeout

    @property
    def provider_name(self) -> str:
        return "DashScope"

    def chat(self, messages: list[dict]) -> str:
        """文本对话，使用 Generation API"""
        response = self._ds.Generation.call(
            api_key=self._ds.api_key,
            model=self._text_model,
            messages=messages,
            result_format="message",
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"DashScope 请求失败 [{response.status_code}]: {response.message}"
            )
        content = response.output.choices[0].message.content
        # content 可能是字符串或列表
        if isinstance(content, list):
            parts = [c.get("text", "") for c in content if isinstance(c, dict)]
            return "".join(parts)
        return str(content)

    def chat_vision(self, text_prompt: str, image: Image.Image) -> str:
        """
        多模态对话，使用 MultiModalConversation API
        
        重要: 需要使用支持视觉的模型，例如:
          - qwen-vl-plus
          - qwen-vl-max  
          - qwen2.5-vl-7b-instruct
        
        qwen3.6-flash 等文本模型不支持图像输入，会返回 400 错误。
        """
        # 检查是否是已知的文本模型（给出友好提示）
        vl_model_lower = self._vl_model.lower()
        is_likely_text_only = not any(
            vl_model_lower.startswith(p) for p in _DASHSCOPE_VL_MODELS
        )
        if is_likely_text_only:
            raise RuntimeError(
                f"当前 VL 模型 '{self._vl_model}' 可能不支持图像输入。\n"
                f"请在设置 → 模型 → DashScope → VL模型 中更换为视觉模型，例如:\n"
                f"  • qwen-vl-plus\n"
                f"  • qwen-vl-max\n"
                f"  • qwen2.5-vl-7b-instruct"
            )

        # 优先使用临时文件（比 base64 更稳定）
        temp_path = _save_image_to_temp(image)
        try:
            return self._chat_vision_file(text_prompt, temp_path)
        except Exception as e:
            err_str = str(e)
            # 如果文件方式失败，尝试 base64 data URI
            if "400" in err_str or "unsupported" in err_str.lower():
                try:
                    return self._chat_vision_base64(text_prompt, image)
                except Exception as e2:
                    raise RuntimeError(
                        f"DashScope VL 调用失败 (文件+base64均失败):\n"
                        f"原始错误: {e}\n"
                        f"Base64错误: {e2}\n\n"
                        f"请确认 VL 模型名称正确（如 qwen-vl-plus）"
                    ) from e2
            raise

        finally:
            try:
                os.unlink(temp_path)
            except Exception:
                pass

    def _chat_vision_file(self, text_prompt: str, image_path: str) -> str:
        """使用本地文件路径发送图像"""
        file_uri = f"file:///{image_path.replace(os.sep, '/')}"
        messages = [
            {
                "role": "user",
                "content": [
                    {"image": file_uri},
                    {"text": text_prompt},
                ],
            }
        ]
        response = self._ds.MultiModalConversation.call(
            api_key=self._ds.api_key,
            model=self._vl_model,
            messages=messages,
        )
        return self._extract_vl_response(response)

    def _chat_vision_base64(self, text_prompt: str, image: Image.Image) -> str:
        """使用 base64 data URI 发送图像（备用方案）"""
        data_uri = _image_to_data_uri(image, "PNG")
        messages = [
            {
                "role": "user",
                "content": [
                    {"image": data_uri},
                    {"text": text_prompt},
                ],
            }
        ]
        response = self._ds.MultiModalConversation.call(
            api_key=self._ds.api_key,
            model=self._vl_model,
            messages=messages,
        )
        return self._extract_vl_response(response)

    def _extract_vl_response(self, response) -> str:
        """从 MultiModalConversation 响应中提取文本"""
        if response.status_code != 200:
            raise RuntimeError(
                f"DashScope VL 请求失败 [{response.status_code}]: {response.message}\n"
                f"提示: 请确认 VL 模型名称（如 qwen-vl-plus）"
            )
        content = response.output.choices[0].message.content
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    return item["text"]
            return str(content)
        return str(content)


# ─────────────────────────────────────────────────────────────
# Ollama 客户端（复用 OpenAI 兼容接口）
# ─────────────────────────────────────────────────────────────
class OllamaClient(OpenAIClient):
    """
    Ollama 本地模型客户端
    Ollama 提供 OpenAI 兼容的 /v1 端点
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        text_model: str = "llama3.2",
        vl_model: Optional[str] = None,
    ) -> None:
        api_base = base_url.rstrip("/") + "/v1"
        super().__init__(
            base_url=api_base,
            api_key="ollama",
            model=text_model,
            vl_model=vl_model or text_model,
        )
        self._name = "Ollama"


# ─────────────────────────────────────────────────────────────
# 工厂函数
# ─────────────────────────────────────────────────────────────
def create_client(provider: str, cfg: dict) -> LLMClient:
    """
    根据提供商名称和配置字典创建客户端
    :param provider: "openai" | "dashscope" | "ollama"
    :param cfg: 对应提供商的配置子字典
    """
    if provider == "openai":
        return OpenAIClient(
            base_url=cfg.get("base_url", "https://api.openai.com/v1"),
            api_key=cfg.get("api_key", ""),
            model=cfg.get("text_model", "gpt-4o-mini"),
            vl_model=cfg.get("vl_model", "gpt-4o"),
        )
    elif provider == "dashscope":
        return DashScopeClient(
            api_key=cfg.get("api_key", ""),
            text_model=cfg.get("text_model", "qwen-turbo"),
            vl_model=cfg.get("vl_model", "qwen-vl-plus"),
            base_url=cfg.get("base_url", ""),
        )
    elif provider == "ollama":
        return OllamaClient(
            base_url=cfg.get("base_url", "http://localhost:11434"),
            text_model=cfg.get("text_model", "llama3.2"),
            vl_model=cfg.get("vl_model"),
        )
    else:
        raise ValueError(f"未知提供商: {provider}")


def parse_json_response(response: str) -> dict:
    """
    从 LLM 响应中提取 JSON
    处理模型可能在 JSON 前后添加额外文字的情况（如 markdown 代码块）
    """
    text = response.strip()

    # 移除 markdown 代码块包装
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()

    # 找到 JSON 对象的起止位置
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        json_str = text[start:end]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # JSON 解析失败：返回原始文本作为 corrected
    return {"corrected": text, "translation": "", "raw": text}
