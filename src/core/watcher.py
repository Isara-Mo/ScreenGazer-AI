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
    屏幕区域变化检测器
    
    工作流程:
    1. 每 poll_interval 秒截取目标区域
    2. 用图像哈希对比前后帧，检测是否有变化
    3. 检测到变化后，切换为"稳定性检测"模式
    4. 稳定性检测: 用 OCR 轻量识别，比较连续 stability_count 次字数是否稳定
    5. 字数稳定后，触发 on_stable 回调
    """

    def __init__(
        self,
        capture_fn: Callable[[], Optional[Image.Image]],
        quick_ocr_fn: Callable[[Image.Image], str],
        on_stable: Callable[[Image.Image], None],
        poll_interval: float = 0.5,
        stability_count: int = 3,
        hash_threshold: int = 8,
    ) -> None:
        """
        :param capture_fn: 截图函数，返回 PIL Image 或 None（区域未配置）
        :param quick_ocr_fn: 轻量 OCR 函数，仅用于字数统计
        :param on_stable: 文本稳定后的回调，传入最终截图
        :param poll_interval: 轮询间隔（秒）
        :param stability_count: 需要连续多少次字数相同才认为稳定
        :param hash_threshold: 图像哈希差异阈值（0-64，越小越敏感）
        """
        self._capture = capture_fn
        self._quick_ocr = quick_ocr_fn
        self._on_stable = on_stable
        self.poll_interval = poll_interval
        self.stability_count = stability_count
        self.hash_threshold = hash_threshold

        self._running = False
        self._last_hash: Optional[imagehash.ImageHash] = None
        self._last_word_count: int = -1
        self._stable_streak: int = 0
        self._in_stability_check: bool = False
        self._last_stable_image: Optional[Image.Image] = None

    def start(self) -> None:
        """标记为运行中（由 WatchWorker 的 run() 循环调用 tick()）"""
        self._running = True
        self._reset_state()

    def stop(self) -> None:
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def _reset_state(self) -> None:
        self._last_hash = None
        self._last_word_count = -1
        self._stable_streak = 0
        self._in_stability_check = False
        self._last_stable_image = None

    def force_trigger(self) -> None:
        """强制触发（快捷键手动触发）"""
        img = self._capture()
        if img is not None:
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

        if self._last_hash is None:
            # 首次截图，初始化
            self._last_hash = current_hash
            self._last_stable_image = img
            return "已启动监视"

        hash_diff = abs(current_hash - self._last_hash)

        if hash_diff > self.hash_threshold:
            # 检测到变化，进入稳定性检测模式
            self._in_stability_check = True
            self._stable_streak = 0
            self._last_word_count = -1
            self._last_hash = current_hash
            return f"检测到变化 (diff={hash_diff})，等待文本稳定..."

        if self._in_stability_check:
            # 稳定性检测：用 OCR 轻量识别，统计字数
            try:
                text = self._quick_ocr(img)
                word_count = len(text.split())
            except Exception:
                word_count = 0

            if word_count == self._last_word_count and word_count > 0:
                self._stable_streak += 1
            else:
                self._stable_streak = 1
                self._last_word_count = word_count
                self._last_stable_image = img

            if self._stable_streak >= self.stability_count:
                # 文本稳定，触发翻译
                self._in_stability_check = False
                self._stable_streak = 0
                stable_img = self._last_stable_image or img
                self._on_stable(stable_img)
                return f"文本稳定（{word_count} 词），已触发翻译"

            return (
                f"稳定性检测中 ({self._stable_streak}/{self.stability_count})，"
                f"当前字数: {word_count}"
            )

        self._last_hash = current_hash
        return "监视中..."
