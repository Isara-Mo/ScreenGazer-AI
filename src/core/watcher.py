"""
变化检测模块
Change Watcher - polls screen region for content changes and text stability
"""

from __future__ import annotations

import time
from typing import Callable, Optional

import imagehash
from PIL import Image


class ChangeWatcher:
    """
    屏幕区域变化检测器 (优化版)
    
    工作流程:
    1. 每 poll_interval 秒截取目标区域并计算图像哈希
    2. 用图像哈希对比前后帧，检测画面是否有变化
    3. 检测到变化后，进入"稳定性检测"模式：连续 stability_count 次帧哈希稳定（无明显刷新）
    4. 帧稳定后，执行轻量 OCR，比对文本/哈希与上一版是否一致（文本去重）
    5. 确认文本为新内容且过了 cooldown 冷却期后，触发 on_stable 回调
    """

    def __init__(
        self,
        capture_fn: Callable[[], Optional[Image.Image]],
        quick_ocr_fn: Callable[[Image.Image], str],
        on_stable: Callable[[Image.Image], None],
        poll_interval: float = 0.3,
        stability_count: int = 2,
        hash_threshold: int = 5,
        cooldown_seconds: float = 0.5,
    ) -> None:
        """
        :param capture_fn: 截图函数，返回 PIL Image 或 None
        :param quick_ocr_fn: 轻量 OCR 函数，仅用于文本去重校验
        :param on_stable: 文本稳定且确认变动后的回调，传入最终截图
        :param poll_interval: 轮询间隔（秒）
        :param stability_count: 连续多少次图像帧不变才认为静止
        :param hash_threshold: 图像哈希差异阈值
        :param cooldown_seconds: 触发翻译后的防刷屏冷却时间（秒）
        """
        self._capture = capture_fn
        self._quick_ocr = quick_ocr_fn
        self._on_stable = on_stable
        self.poll_interval = poll_interval
        self.stability_count = max(1, stability_count)
        self.hash_threshold = hash_threshold
        self.cooldown_seconds = cooldown_seconds

        self._running = False
        self._last_hash: Optional[imagehash.ImageHash] = None
        self._stable_streak: int = 0
        self._in_stability_check: bool = False
        self._last_stable_image: Optional[Image.Image] = None

        # 去重与防刷屏状态
        self._last_trigger_time: float = 0.0
        self._last_triggered_hash: Optional[imagehash.ImageHash] = None
        self._last_triggered_text: str = ""

    def start(self) -> None:
        """标记为运行中"""
        self._running = True
        self._reset_state()

    def stop(self) -> None:
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def _reset_state(self) -> None:
        self._last_hash = None
        self._stable_streak = 0
        self._in_stability_check = False
        self._last_stable_image = None
        self._last_trigger_time = 0.0
        self._last_triggered_hash = None
        self._last_triggered_text = ""

    def force_trigger(self) -> None:
        """强制触发（快捷键手动触发，不受去重和冷却限制）"""
        img = self._capture()
        if img is not None:
            text = self._quick_ocr(img)
            self._last_triggered_text = text.strip()
            self._last_triggered_hash = imagehash.phash(img.convert("L"), hash_size=8)
            self._last_trigger_time = time.time()
            self._on_stable(img)

    def tick(self) -> str:
        """
        执行一次轮询 tick
        :return: 当前状态描述字符串（用于 UI 状态栏）
        """
        img = self._capture()
        if img is None:
            return "未配置捕获区域"

        # 计算当前帧哈希
        current_hash = imagehash.phash(img.convert("L"), hash_size=8)
        now = time.time()

        if self._last_hash is None:
            # 首次截图，初始化
            self._last_hash = current_hash
            self._last_stable_image = img
            return "已启动监视"

        hash_diff = abs(current_hash - self._last_hash)
        self._last_hash = current_hash

        if hash_diff > self.hash_threshold:
            # 检测到画面刷新/变动，重置稳定性计数
            self._in_stability_check = True
            self._stable_streak = 0
            self._last_stable_image = img
            return f"检测到画面变动 (diff={hash_diff})，等待文本稳定..."

        if self._in_stability_check:
            # 画面变化后处于静止状态，累加稳定计数
            self._stable_streak += 1
            self._last_stable_image = img

            if self._stable_streak >= self.stability_count:
                self._in_stability_check = False
                self._stable_streak = 0

                # 冷却时间检查
                if (now - self._last_trigger_time) < self.cooldown_seconds:
                    return f"画面已稳定，冷却中 ({self.cooldown_seconds - (now - self._last_trigger_time):.1f}s)"

                # 与上一次触发的图像哈希做比对
                if self._last_triggered_hash is not None:
                    trigger_diff = abs(current_hash - self._last_triggered_hash)
                    if trigger_diff <= self.hash_threshold:
                        return "画面静止（与上一次触发图像一致，跳过）"

                # 执行轻量 OCR 进行文本去重校验
                stable_img = self._last_stable_image or img
                text = self._quick_ocr(stable_img).strip()

                if not text:
                    return "画面稳定（未识别到文本）"

                if text == self._last_triggered_text:
                    return f"画面稳定（文本与上一次一致: '{text[:15]}...'，已忽略）"

                # 文本确认更新，触发翻译
                self._last_triggered_text = text
                self._last_triggered_hash = current_hash
                self._last_trigger_time = now
                self._on_stable(stable_img)
                return f"文本已更新（'{text[:15]}...'），已触发翻译"

            return f"稳定性检测中 ({self._stable_streak}/{self.stability_count})"

        return "监视中..."
