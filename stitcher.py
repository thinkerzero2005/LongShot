"""重叠匹配：上一帧底部条带在当前帧中做灰度归一化互相关（NCC），求纵向偏移。

实现要点（与原先的 OpenCV `TM_CCOEFF_NORMED` 等价，但不再依赖 cv2）：

- 只沿纵向搜索。模板宽度约等于帧宽（仅去掉右侧滚动条），横向可偏移量只有滚动条
  的十几到几十像素，二维模板匹配在这里实际等价于一维纵向 NCC。
- 先用 4 倍降采样 + 一次 FFT 互相关做全局粗搜，再在原分辨率上对候选偏移精算，
  既保证精度又避免逐偏移的二维卷积开销。
"""
from __future__ import annotations

import numpy as np

MIN_TEMPLATE = 24  # 模板最小高度
MAX_TEMPLATE_RATIO = 0.85  # 加宽重试时模板最大占帧高比例
COARSE_FACTOR = 4  # 粗搜降采样倍数
REFINE_SPAN = 2  # 精搜范围：粗搜偏移前后各 REFINE_SPAN 个降采样块

# cv2.COLOR_RGB2GRAY 的权重，保持灰度值口径一致
_GRAY_WEIGHTS = np.array([0.299, 0.587, 0.114], dtype=np.float32)


def is_broken_frame(frame: np.ndarray) -> bool:
    """全黑画面通常意味着锁屏 / UAC / 独占全屏，GDI 抓不到内容。"""
    if frame is None or frame.size == 0:
        return True
    return int(frame.max()) <= 8


def _gray(frame: np.ndarray, exclude_right: int) -> np.ndarray:
    if frame.ndim == 3:
        gray = frame[:, :, :3].astype(np.float32) @ _GRAY_WEIGHTS
    else:
        gray = frame.astype(np.float32)
    if exclude_right > 0 and gray.shape[1] > exclude_right + 16:
        gray = gray[:, : gray.shape[1] - exclude_right]
    return gray


def _downscale(gray: np.ndarray, factor: int) -> np.ndarray | None:
    """按整数块求均值降采样，用于粗搜。"""
    h, w = gray.shape
    h2, w2 = h // factor, w // factor
    if h2 < 1 or w2 < 1:
        return None
    block = np.ascontiguousarray(gray[: h2 * factor, : w2 * factor])
    return block.reshape(h2, factor, w2, factor).mean(axis=(1, 3))


def _fft_cross_correlation(cur: np.ndarray, tpl: np.ndarray) -> np.ndarray:
    """沿纵向做互相关：corr[o] = Σ_r,c tpl[r,c] * cur[o+r,c]。"""
    n, m = cur.shape[0], tpl.shape[0]
    size = 1 << int(np.ceil(np.log2(n + m)))
    cur_f = np.fft.rfft(cur, n=size, axis=0)
    tpl_f = np.conj(np.fft.rfft(tpl, n=size, axis=0))
    corr = np.fft.irfft(cur_f * tpl_f, n=size, axis=0).sum(axis=1)
    return corr[: n - m + 1]


def _coarse_best_offset(cur: np.ndarray, tpl: np.ndarray) -> int | None:
    """降采样图上的最佳偏移（单位：降采样后的行）。"""
    n, m = cur.shape[0], tpl.shape[0]
    if m >= n or m < 2:
        return None

    t_centered = tpl - tpl.mean()
    t_norm = float(np.sqrt(np.square(t_centered, dtype=np.float64).sum()))
    if t_norm < 1e-3:
        return None

    corr = _fft_cross_correlation(cur, t_centered)

    count = float(tpl.size)
    row_sum = cur.sum(axis=1, dtype=np.float64)
    row_sq = np.square(cur, dtype=np.float64).sum(axis=1)
    csum = np.concatenate(([0.0], np.cumsum(row_sum)))
    csum_sq = np.concatenate(([0.0], np.cumsum(row_sq)))

    idx = np.arange(corr.shape[0])
    win_sum = csum[idx + m] - csum[idx]
    win_sq = csum_sq[idx + m] - csum_sq[idx]
    var = np.maximum(win_sq - win_sum * win_sum / count, 1e-3)

    scores = corr / (np.sqrt(var) * t_norm)
    return int(np.argmax(scores))


def _ncc_at(gray: np.ndarray, t_centered: np.ndarray, t_norm: float, offset: int) -> float:
    """原分辨率上 offset 处的 NCC 得分；-1 表示该窗口完全平坦、无法判定。"""
    m = t_centered.shape[0]
    win = gray[offset : offset + m]
    count = float(win.size)
    win_sum = float(win.sum(dtype=np.float64))
    win_sq = float(np.square(win, dtype=np.float64).sum())
    var = win_sq - win_sum * win_sum / count
    if var <= 1e-3:
        return -1.0
    dot = float(np.tensordot(win, t_centered, axes=2))
    return dot / (np.sqrt(var) * t_norm)


def _match_1d(gray: np.ndarray, tpl: np.ndarray, t_centered: np.ndarray, t_norm: float):
    """粗搜 + 精算，返回 (skip, score)；无有效结果时返回 (0, -1.0)。"""
    coarse_cur = _downscale(gray, COARSE_FACTOR)
    coarse_tpl = _downscale(tpl, COARSE_FACTOR)
    if coarse_cur is None or coarse_tpl is None:
        return 0, -1.0

    coarse = _coarse_best_offset(coarse_cur, coarse_tpl)
    if coarse is None:
        return 0, -1.0

    center = coarse * COARSE_FACTOR
    limit = gray.shape[0] - tpl.shape[0]
    lo = max(0, center - REFINE_SPAN * COARSE_FACTOR)
    hi = min(limit, center + REFINE_SPAN * COARSE_FACTOR)

    best_skip, best_score = center, -1.0
    for offset in range(lo, hi + 1):
        score = _ncc_at(gray, t_centered, t_norm, offset)
        if score > best_score:
            best_score, best_skip = score, offset
    # 命中位置的窗口顶部 + 模板高度 = 新增内容的起始行
    return best_skip + tpl.shape[0], best_score


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
        t_centered = template - template.mean()
        t_norm = float(np.sqrt(np.square(t_centered, dtype=np.float64).sum()))
        if t_norm < 1e-3:
            continue
        skip, score = _match_1d(g_cur, template, t_centered, t_norm)
        if score > best_score:
            best_score = float(score)
            best_skip = int(skip)
        if best_score >= threshold:
            break

    return best_skip, best_score
