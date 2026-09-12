"""自定义体力立绘在排行 title 上的位置/缩放 — 与图片同名(后缀换成 .json)的 sidecar。

格式: {"rank": {"x": int, "y": int, "scale": float}}; (0, 0, 1.0) 为默认位置, 不落文件。
scale 以立绘中心为锚(与前端 canvas 同算法)。sidecar 以 stem 匹配, 压缩 jpg→webp 后仍生效。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

OFFSET_SUFFIX = ".json"
OFFSET_LIMIT = 2000
SCALE_MIN, SCALE_MAX = 0.2, 3.0

RankOffset = Tuple[int, int, float]
DEFAULT_OFFSET: RankOffset = (0, 0, 1.0)


def offset_path(image: Path) -> Path:
    return image.with_suffix(OFFSET_SUFFIX)


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
    """无 sidecar / 解析失败一律默认值。"""
    if image is None:
        return DEFAULT_OFFSET
    try:
        rank = json.loads(offset_path(image).read_text("utf-8")).get("rank") or {}
        return clamp_offset(rank.get("x", 0), rank.get("y", 0), rank.get("scale", 1.0))
    except (OSError, ValueError, TypeError, AttributeError):
        return DEFAULT_OFFSET


def has_rank_offset(image: Path) -> bool:
    return offset_path(image).is_file()


def write_rank_offset(image: Path, x: int, y: int, scale: float = 1.0) -> Optional[RankOffset]:
    """写入偏移; 默认值直接删 sidecar。返回落盘后的偏移, None 表示已清除。"""
    o = clamp_offset(x, y, scale)
    p = offset_path(image)
    if o == DEFAULT_OFFSET:
        p.unlink(missing_ok=True)
        return None
    p.write_text(json.dumps({"rank": {"x": o[0], "y": o[1], "scale": o[2]}}), "utf-8")
    return o


def delete_rank_offset(image: Path) -> None:
    offset_path(image).unlink(missing_ok=True)


def move_rank_offset(src: Path, dst: Path) -> None:
    p = offset_path(src)
    if p.is_file():
        p.rename(offset_path(dst))


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
