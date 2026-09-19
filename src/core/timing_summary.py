"""Compact, non-overlapping timing explanations for completed translations."""

from __future__ import annotations

import math


def _seconds(value) -> float:
    """Keep incomplete or invalid telemetry from breaking result display."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return max(0.0, number) if math.isfinite(number) else 0.0


def format_timing_summary(
    timings: dict,
    *,
    monitor=None,
    total_seconds: float | None = None,
    display_seconds: float = 0.0,
    held_seconds: float = 0.0,
    manual: bool = False,
) -> str:
    """Describe measured stages without counting text stability twice.

    ``monitor`` is a WatchTiming-compatible object. Its interval already
    includes captures, OCR, and waiting; ``stable_seconds`` overlaps those
    stages. ``total_seconds`` is measured by the caller from its first capture
    (or manual capture preparation) until the result is displayed, not inferred
    from stages. A manual request during monitoring excludes the wait for an
    already-running OCR cycle to finish before manual capture can begin.
    Optional ``ocr_mode`` distinguishes ``reused``, ``unused`` and ``request``;
    zero OCR with a monitor defaults to reused, otherwise to unused.
    """
    timings = timings or {}
    request_total = _seconds(timings.get("total"))
    ocr = _seconds(timings.get("ocr"))
    model = _seconds(timings.get("model"))
    refinement = _seconds(timings.get("refinement"))
    queue = _seconds(timings.get("queue"))
    reuse_wait = _seconds(timings.get("reuse_wait"))
    held = _seconds(held_seconds)
    display = _seconds(display_seconds)
    monitor_total = 0.0
    lines = []

    origin = "手动采集开始" if manual else "首次检测这句"
    if total_seconds is None:
        lines.append(f"整体：未记录（{origin}→文字显示）")
    else:
        lines.append(f"整体 {_seconds(total_seconds):.2f}s（{origin}→文字显示）")

    if monitor is not None:
        monitor_total = _seconds(monitor.submitted_at - monitor.started_at)
        capture = _seconds(monitor.capture_seconds)
        monitor_ocr = _seconds(monitor.ocr_seconds)
        waiting = max(0.0, monitor_total - capture - monitor_ocr)
        samples = int(_seconds(monitor.ocr_samples))
        label = "手动采集" if manual else "确认文字"
        lines.append(
            f"{label} {monitor_total:.2f}s：截图/裁切 {capture:.2f}s · "
            f"OCR 累计 {monitor_ocr:.2f}s/{samples}轮 · 等待/判断 {waiting:.2f}s"
        )
        if not manual:
            lines.append(
                f"文字保持一致 {_seconds(monitor.stable_seconds):.2f}s"
                "（与确认过程重叠，不另加）"
            )

    ocr_mode = timings.get("ocr_mode")
    if ocr_mode == "reused" or (not ocr_mode and not ocr and monitor is not None):
        ocr_label = "请求 OCR：复用监视识别"
    elif ocr_mode == "unused" or (not ocr_mode and not ocr):
        ocr_label = "请求 OCR：未使用"
    else:
        ocr_label = f"请求 OCR {ocr:.2f}s"
    if timings.get("cache_hit"):
        lines.append("命中同句缓存 · 本次模型请求 0 次 · 模型 0.00s")
    elif timings.get("joined_request"):
        lines.append(f"复用进行中的请求：等待 {reuse_wait:.2f}s（未新增请求）")
    else:
        lines.append(f"排队 {queue:.2f}s · {ocr_label} · 模型 {model:.2f}s")

    if total_seconds is not None:
        # The residual includes request preparation, parsing, GUI delivery and
        # rendering, plus manual capture when no monitor telemetry is present.
        other = max(0.0, _seconds(total_seconds) - monitor_total - queue
                    - ocr - model - refinement - held - reuse_wait)
    else:
        other = max(0.0, request_total - ocr - model - refinement - reuse_wait) + display
    final_stages = []
    if refinement:
        final_stages.append(f"术语校正 {refinement:.2f}s")
    final_stages.append(f"其他处理/显示 {other:.2f}s")
    if held:
        final_stages.append(f"等待对白恢复 {held:.2f}s")
    lines.append(" · ".join(final_stages))
    if timings.get("joined_request"):
        lines.append(
            f"原请求模型 {_seconds(timings.get('original_model')):.2f}s · "
            f"术语校正 {_seconds(timings.get('original_refinement')):.2f}s"
            "（跨越本轮检测，不另加）"
        )
    else:
        lines.append(f"请求合计 {request_total:.2f}s（不含监视/排队）")
    return "\n".join(lines)
