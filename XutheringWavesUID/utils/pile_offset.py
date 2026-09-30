"""自定义体力立绘在排行 title 上的位置/缩放, 存于图片元数据的 rank 字段 (见 image_meta)。

格式: {"rank": {"x": int, "y": int, "scale": float}}; (0, 0, 1.0) 为默认位置, 不落盘。
scale 以立绘中心为锚(与前端 canvas 同算法)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

from .image_meta import read_image_meta, update_image_meta

OFFSET_LIMIT = 2000
SCALE_MIN, SCALE_MAX = 0.2, 3.0

RankOffset = Tuple[int, int, float]
DEFAULT_OFFSET: RankOffset = (0, 0, 1.0)


def clamp_offset(x: int, y: int, scale: float = 1.0) -> RankOffset:
    try:
        s = float(scale)
    except (TypeError, ValueError):
        s = 1.0
    if s != s:
        s = 1.0
    return (
        max(-OFFSET_LIMIT, min(OFFSET_LIMIT, int(x))),
        max(-OFFSET_LIMIT, min(OFFSET_LIMIT, int(y))),
        round(max(SCALE_MIN, min(SCALE_MAX, s)), 3),
    )


def offset_dict(o: Optional[RankOffset]) -> Optional[dict]:
    return {"x": o[0], "y": o[1], "scale": o[2]} if o else None


def read_rank_offset(image: Optional[Path]) -> RankOffset:
    """无 rank / 解析失败一律默认值。"""
    if image is None:
        return DEFAULT_OFFSET
    try:
        rank = read_image_meta(image).get("rank") or {}
        return clamp_offset(rank.get("x", 0), rank.get("y", 0), rank.get("scale", 1.0))
    except (OSError, ValueError, TypeError, AttributeError):
        return DEFAULT_OFFSET


def has_rank_offset(image: Path) -> bool:
    return bool(read_image_meta(image).get("rank"))


def write_rank_offset(image: Path, x: int, y: int, scale: float = 1.0) -> Optional[RankOffset]:
    """写入偏移; 默认值清除 rank。返回落盘后的偏移, None 表示已清除。"""
    o = clamp_offset(x, y, scale)
    if o == DEFAULT_OFFSET:
        update_image_meta(image, "rank", None)
        return None
    update_image_meta(image, "rank", offset_dict(o))
    return o


def place_rank_pile(
    pile: Image.Image, base: Tuple[int, int], offset: RankOffset,
) -> Tuple[Image.Image, Tuple[int, int]]:
    """base 为默认贴图左上角; 返回按 offset 平移 + 以中心缩放后的立绘与贴图坐标。"""
    dx, dy, s = offset
    w, h = pile.size
    nw, nh = w, h
    if abs(s - 1.0) > 1e-6:
        nw, nh = max(1, round(w * s)), max(1, round(h * s))
        pile = pile.resize((nw, nh), Image.LANCZOS)
    return pile, (base[0] + dx + (w - nw) // 2, base[1] + dy + (h - nh) // 2)
