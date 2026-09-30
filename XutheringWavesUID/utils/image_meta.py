"""图片同名 JSON 元数据 (按 stem 匹配, 压缩 jpg→webp 后仍生效)。

crop: 面板图框选, 原图不动, 出图/查重/缩略图时在内存里应用。
rank: 体力立绘在排行 title 上的偏移, 见 pile_offset。
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image

# 框选画布尺寸上限
MAX_CROP_DIM = 16384
MAX_CROP_PIXELS = 160_000_000


def meta_path(image: Path) -> Path:
    return image.with_suffix(".json")


def read_image_meta(image: Path) -> dict:
    try:
        data = json.loads(meta_path(image).read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def update_image_meta(image: Path, key: str, value) -> None:
    """只改一个字段, 其余字段保留; 改完为空则删文件。"""
    data = read_image_meta(image)
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    target = meta_path(image)
    if not data:
        target.unlink(missing_ok=True)
        return
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


def delete_image_meta(image: Path) -> None:
    meta_path(image).unlink(missing_ok=True)


def move_image_meta(src: Path, dst: Path) -> None:
    p = meta_path(src)
    if p.is_file():
        p.rename(meta_path(dst))


def normalize_crop(value: dict) -> dict:
    """源图绝对像素坐标, 允许越界。"""
    try:
        crop = {key: int(round(float(value[key]))) for key in ("x", "y", "w", "h")}
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("x/y/w/h required and numeric") from exc
    w, h = crop["w"], crop["h"]
    if w <= 0 or h <= 0:
        raise ValueError("invalid crop size")
    if max(w, h) > MAX_CROP_DIM or w * h > MAX_CROP_PIXELS:
        raise ValueError("crop size too large")
    return crop


def read_crop(image: Path) -> Optional[dict]:
    try:
        return normalize_crop(read_image_meta(image).get("crop"))
    except ValueError:
        return None


def crop_image(image: Image.Image, crop: Optional[dict]) -> Image.Image:
    """在内存里应用框选, 越界部分填白。"""
    if crop is None:
        return image
    x, y, w, h = (crop[key] for key in ("x", "y", "w", "h"))
    mode = "RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB"
    fill = (255, 255, 255, 255) if mode == "RGBA" else (255, 255, 255)
    canvas = Image.new(mode, (w, h), fill)
    left, top = max(0, x), max(0, y)
    right, bottom = min(image.width, x + w), min(image.height, y + h)
    if right > left and bottom > top:
        region = image.crop((left, top, right, bottom)).convert(mode)
        canvas.paste(region, (left - x, top - y))
    return canvas


def open_meta_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        image.load()
        return crop_image(image, read_crop(path)).convert("RGBA")


def file_fingerprint(image: Path) -> str:
    """原图 + 同名 JSON 的 mtime_ns/size, 任一变化即不同; 可直接放进 URL。"""
    parts = []
    for p in (image, meta_path(image)):
        try:
            info = p.stat()
            parts.append(f"{info.st_mtime_ns}-{info.st_size}")
        except OSError:
            parts.append("-")
    return "_".join(parts)


class CacheFingerprint:
    """派生缓存的指纹 = 生成逻辑(函数源码+常量) + 源文件, 改算法或改图都自动失效。"""

    def __init__(self, *deps):
        h = hashlib.md5()
        for dep in deps:
            if callable(dep):
                try:
                    dep = inspect.getsource(dep)
                except (OSError, TypeError):
                    dep = getattr(dep, "__qualname__", repr(dep))
            h.update(repr(dep).encode())
        self.code = h.hexdigest()[:12]

    def __call__(self, image: Path) -> str:
        return f"{self.code}_{file_fingerprint(image)}"
