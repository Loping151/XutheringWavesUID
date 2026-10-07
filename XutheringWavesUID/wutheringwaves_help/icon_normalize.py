"""帮助图标标准化脚本

用法: python icon_normalize.py [目录 ...] [--force] [--bust 名,...] [--pattern 名,...] [--frame 名=帧号,...]
不给目录时处理同目录下的 icon_path/ 和 change_icon_path/

- 输出统一为 150x150 RGBA PNG; GIF 选一帧转 PNG 后删除原 GIF
- GIF 默认取内容完整且与前后帧差异最小的一帧, 选得不对用 --frame 指定
- 半身像: 下边沿贴底, 等比缩放进 BUST_BOX, 水平居中
- 图案: 等比缩放进 PATTERN_BOX、不透明面积不超过 PATTERN_AREA, 居中
- 类型: --bust/--pattern 指定 > GIF 视为半身像 > PNG 内容贴底为半身像, 否则为图案
- 位置尺寸已达标的图不重写, --force 强制重做
"""

import sys
import argparse
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

import numpy as np
from PIL import Image, ImageSequence

SIZE = 150
BUST_BOX = (132, 132)
PATTERN_BOX = 118
PATTERN_AREA = 0.4 * SIZE * SIZE
ALPHA_T = 16
BOTTOM_TOL = 2
FULL_FRAME_RATIO = 0.97

BUST = "半身像"
PATTERN = "图案"


def _content_bbox(img: Image.Image) -> Optional[Tuple[int, int, int, int]]:
    alpha = np.asarray(img)[:, :, 3]
    ys, xs = np.nonzero(alpha > ALPHA_T)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def pick_gif_frame(path: Path, frame: Optional[int] = None) -> Tuple[Image.Image, int]:
    frames = [f.convert("RGBA") for f in ImageSequence.Iterator(Image.open(path))]
    if frame is not None:
        return frames[frame], frame

    arrs = [np.asarray(f, dtype=np.float32) for f in frames]
    premul = [a[..., :3] * (a[..., 3:] / 255.0) for a in arrs]
    areas = np.array([(a[..., 3] > ALPHA_T).sum() for a in arrs])

    def motion(i: int) -> float:
        nbs = [j for j in (i - 1, i + 1) if 0 <= j < len(frames)]
        if not nbs:
            return 0.0
        return float(np.mean([np.abs(premul[i] - premul[j]).mean() for j in nbs]))

    cands = [i for i in range(len(frames)) if areas[i] >= FULL_FRAME_RATIO * areas.max()]
    best = min(cands, key=lambda i: (round(motion(i), 1), -i))
    return frames[best], best


def classify(img: Image.Image) -> str:
    bbox = _content_bbox(img)
    if bbox is None:
        return PATTERN
    tol = BOTTOM_TOL * img.height / SIZE
    return BUST if bbox[3] >= img.height - tol else PATTERN


def _target_rect(img: Image.Image, bbox, kind: str) -> Tuple[int, int, int, int]:
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if kind == BUST:
        scale = min(BUST_BOX[0] / w, BUST_BOX[1] / h)
    else:
        alpha = np.asarray(img.crop(bbox))[:, :, 3]
        area = float(alpha.sum()) / 255.0
        scale = min(PATTERN_BOX / w, PATTERN_BOX / h, (PATTERN_AREA / max(area, 1.0)) ** 0.5)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    x = (SIZE - nw) // 2
    y = SIZE - nh if kind == BUST else (SIZE - nh) // 2
    return x, y, nw, nh


def normalize(img: Image.Image, kind: str, force: bool = False) -> Optional[Image.Image]:
    img = img.convert("RGBA")
    bbox = _content_bbox(img)
    if bbox is None:
        return None
    x, y, nw, nh = _target_rect(img, bbox, kind)
    if not force and img.size == (SIZE, SIZE):
        cur = (bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1])
        if all(abs(a - b) <= 1 for a, b in zip(cur, (x, y, nw, nh))):
            return None

    content = img.crop(bbox).convert("RGBa").resize((nw, nh), Image.Resampling.LANCZOS).convert("RGBA")
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    canvas.alpha_composite(content, (x, y))
    return canvas


def normalize_dir(icon_dir: Path, kinds: Dict[str, str], frames: Dict[str, int], force: bool = False):
    done = set()
    for f in sorted(icon_dir.glob("*.gif")):
        img, idx = pick_gif_frame(f, frames.get(f.stem))
        kind = kinds.get(f.stem, BUST)
        out = normalize(img, kind, force=True)
        if out is None:
            print(f"[跳过] {f.name} 无可见内容")
            continue
        out.save(f.with_suffix(".png"))
        f.unlink()
        print(f"[GIF] {f.name} 第{idx}帧 -> {f.stem}.png ({kind})")
        done.add(f.stem)

    for f in sorted(icon_dir.glob("*.png")):
        if f.stem in done:
            continue
        img = Image.open(f).convert("RGBA")
        kind = kinds.get(f.stem) or classify(img)
        out = normalize(img, kind, force=force)
        if out is not None:
            out.save(f)
            print(f"[标准化] {f.name} ({kind})")


def _parse_names(s: str) -> Set[str]:
    return {n.strip() for n in s.split(",") if n.strip()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="帮助图标标准化")
    parser.add_argument("dirs", nargs="*", type=Path)
    parser.add_argument("--force", action="store_true", help="已达标的图也重做")
    parser.add_argument("--bust", default="", help="指定为半身像的图标名, 逗号分隔")
    parser.add_argument("--pattern", default="", help="指定为图案的图标名, 逗号分隔")
    parser.add_argument("--frame", default="", help="指定 GIF 取第几帧, 如 名=3,名2=0")
    args = parser.parse_args()

    kinds = {n: BUST for n in _parse_names(args.bust)}
    kinds.update({n: PATTERN for n in _parse_names(args.pattern)})
    frames = {k: int(v) for k, v in (p.split("=") for p in _parse_names(args.frame))}

    here = Path(__file__).parent
    targets = args.dirs or [here / "icon_path", here / "change_icon_path"]
    for target in targets:
        if not target.is_dir():
            print(f"目录不存在: {target}")
            sys.exit(1)
        print(f"处理目录: {target}")
        normalize_dir(target, kinds, frames, force=args.force)
    print("完成")
