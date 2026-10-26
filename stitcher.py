"""重叠匹配：用上一帧底部条带在当前帧中做灰度模板匹配，求纵向偏移。"""
from __future__ import annotations

import cv2
import numpy as np

MIN_TEMPLATE = 24  # 模板最小高度
MAX_TEMPLATE_RATIO = 0.85  # 加宽重试时模板最大占帧高比例


def is_broken_frame(frame: np.ndarray) -> bool:
    """全黑画面通常意味着锁屏 / UAC / 独占全屏，GDI 抓不到内容。"""
    if frame is None or frame.size == 0:
        return True
    return int(frame.max()) <= 8


def _gray(frame: np.ndarray, exclude_right: int) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    if exclude_right > 0 and gray.shape[1] > exclude_right + 16:
        gray = gray[:, : gray.shape[1] - exclude_right]
    return gray


def match_offset(
    prev: np.ndarray,
    cur: np.ndarray,
    search_height: int,
    threshold: float,
    exclude_right: int,
) -> tuple[int, float]:
    """返回 (skip, score)。

    skip  = 当前帧顶部需要丢弃的行数（也就是新增内容的起始行）；
    score = 相似度，-1 表示无法计算（尺寸不符 / 画面过于平坦）。
    """
    if prev is None or cur is None or prev.shape[:2] != cur.shape[:2]:
        return 0, -1.0
    h = int(cur.shape[0])
    if h < MIN_TEMPLATE * 2:
        return 0, -1.0

    g_prev = _gray(prev, exclude_right)
    g_cur = _gray(cur, exclude_right)

    base = max(MIN_TEMPLATE, int(search_height))
    base = min(base, int(h * 0.5))

    best_skip, best_score = 0, -1.0
    tried: list[int] = []
    # 先按配置高度匹配；失败则自动加宽模板再试，减少「滚太快」造成的误判
    for scale in (1, 2, 3):
        size = min(int(h * MAX_TEMPLATE_RATIO), base * scale)
        if size < MIN_TEMPLATE or size >= h - 4 or size in tried:
            continue
        tried.append(size)
        template = g_prev[h - size :, :]
        if float(template.std()) < 2.0:
            # 完全平坦的区域没有可匹配特征
            continue
        result = cv2.matchTemplate(g_cur, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best_score:
            best_score = float(max_val)
            best_skip = int(max_loc[1]) + size
        if best_score >= threshold:
            break

    return best_skip, best_score
