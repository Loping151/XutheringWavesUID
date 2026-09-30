import os
import ssl
import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from PIL import Image
from gsuid_core.logger import logger
from gsuid_core.pool import to_thread

from . import card_hash_index
from .card_hash_index import compute_hash as get_hash_id  # 对外别名, 旧 import 不破


def _import_cv2():
    try:
        import cv2  # type: ignore
        return cv2
    except Exception:
        logger.warning("[鸣潮·卡片工具] 未安装opencv-python，安装后可使用面板图重复判断、提取面板图等功能。")
        logger.info("[鸣潮·卡片工具] 安装方法 Linux/Mac: 在当前目录下执行 source .venv/bin/activate && uv pip install opencv-python")
        logger.info("[鸣潮·卡片工具] 安装方法 Windows: 在当前目录下执行 .venv\\Scripts\\activate; uv pip install opencv-python")
        return None
    
def _import_np():
    try:
        import numpy as np  # type: ignore
        return np
    except Exception:
        return None


cv2 = _import_cv2()
np = _import_np()

import httpx

from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment
from gsuid_core.utils.image.convert import convert_img

from ..utils.image_meta import CacheFingerprint, crop_image, read_crop
from ..utils.name_convert import alias_to_char_name, char_name_to_char_id, easy_id_to_name
from ..utils.resource.constant import SPECIAL_CHAR, SPECIAL_CHAR_ID
from ..utils.resource.RESOURCE_PATH import (
    CUSTOM_CARD_PATH,
    CUSTOM_DIRS as CUSTOM_PATH_MAP,
    CUSTOM_ORB_PATH,
    IMAGE_EXTS,
    MAIN_PATH,
)
from ..wutheringwaves_config import WutheringWavesConfig

ORB_RATIO = 0.75
ORB_MIN_MATCHES = 40
ORB_THRESHOLD = 0.7
ORB_BLOCK_THRESHOLD = 0.9
ORB_FEATURES = 2000

CROP_PORTRAIT = (85, 265, 525, 1070)
CROP_LANDSCAPE = (520, 0, 1100, 620)

CUSTOM_PATH_NAME_MAP = {
    "card": "面板",
    "bg": "背景",
    "stamina": "体力",
}

_ROVER_ID_FULL_NAME = {v: k for k, v in SPECIAL_CHAR_ID.items()}


def _listing_char_name(char_id) -> str:
    cid = str(char_id)
    return _ROVER_ID_FULL_NAME.get(cid) or easy_id_to_name(cid, cid)


def get_char_id_and_name(char: str) -> tuple[Optional[str], str, str]:
    char_id = None
    msg = "[鸣潮] 角色名无法找到, 可能暂未适配, 请先检查输入是否正确！"
    sex = ""
    if "男" in char:
        char = char.replace("男", "")
        sex = "男"
    elif "女" in char:
        char = char.replace("女", "")
        sex = "女"

    char = alias_to_char_name(char)
    if not char:
        return char_id, char, msg

    char_id = char_name_to_char_id(char)
    if not char_id:
        return char_id, char, msg

    if char_id in SPECIAL_CHAR:
        if not sex:
            msg1 = f"[鸣潮] 主角【{char}】需要指定性别！"
            return char_id, char, msg1
        char_id = SPECIAL_CHAR_ID[f"{char}·{sex}"]

    return char_id, char, ""


def _iter_images(path: Path) -> Iterable[Path]:
    for p in path.iterdir():
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            yield p


def _relative_to_main(path: Path) -> str:
    try:
        return str(path.relative_to(MAIN_PATH))
    except ValueError:
        return str(path)


async def get_image(ev: Event) -> List[str]:
    res = []
    for content in ev.content:
        if content.type == "img" and content.data and isinstance(content.data, str) and content.data.startswith("http"):
            res.append(content.data)
        elif (
            content.type == "image"
            and content.data
            and isinstance(content.data, str)
            and content.data.startswith("http")
        ):
            res.append(content.data)

    if not res and ev.image:
        res.append(ev.image)
    return res


async def _fetch_image_bytes(url: str) -> Optional[bytes]:
    try:
        if httpx.__version__ >= "0.28.0":
            ssl_context = ssl.create_default_context()
            ssl_context.set_ciphers("DEFAULT")
            async with httpx.AsyncClient(verify=ssl_context) as client:
                res = await client.get(url)
        else:
            async with httpx.AsyncClient() as client:
                res = await client.get(url)
        if res.status_code != 200:
            return None
        return res.content
    except Exception:
        return None


def _compute_orb_features_from_image(image: Image.Image):
    if cv2 is None:
        return None
    rgb = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    orb = cv2.ORB_create(nfeatures=ORB_FEATURES)
    keypoints, descriptors = orb.detectAndCompute(gray, None)
    if descriptors is None or not keypoints:
        return None
    pts = np.float32([kp.pt for kp in keypoints])
    return pts, descriptors


@to_thread
def _match_one_image_orb(
    image_bytes: bytes,
    search_types: List[str],
    target_type: str,
    char_id: Optional[str],
) -> Tuple[float, Optional[Path], Optional[str]]:
    """单张候选图片的 ORB 处理 + 库内匹配, 全部同步, 用线程池执行避免阻塞 loop"""
    try:
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return 0.0, None, None

    if image.width > image.height:
        crop_boxes = [CROP_LANDSCAPE]
    else:
        crop_boxes = [CROP_PORTRAIT]
        if image.height > 4000:
            left0, top0, right0, bottom0 = CROP_PORTRAIT
            crop_boxes.append((left0, top0 + 875, right0, bottom0 + 875))

    best_sim = 0.0
    best_path: Optional[Path] = None
    best_char_id: Optional[str] = None

    for crop_box in crop_boxes:
        left, top, right, bottom = crop_box

        if left >= image.width or top >= image.height:
            crop = image
        else:
            left = max(0, left)
            top = max(0, top)
            right = min(right, image.width)
            bottom = min(bottom, image.height)
            if right <= left or bottom <= top:
                crop = image
            else:
                crop = image.crop((left, top, right, bottom))
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.Resampling.LANCZOS)
        feat_new = _compute_orb_features_from_image(crop)
        if feat_new is None:
            continue

        for current_type in search_types:
            if char_id:
                char_dirs = [CUSTOM_PATH_MAP.get(current_type, CUSTOM_CARD_PATH) / f"{char_id}"]
            else:
                char_dirs = []
                base = CUSTOM_PATH_MAP.get(current_type, CUSTOM_CARD_PATH)
                if base.exists():
                    for d in base.iterdir():
                        if d.is_dir():
                            char_dirs.append(d)

            for dir_path in char_dirs:
                if not dir_path.exists():
                    continue
                for img_path in _iter_images(dir_path):
                    feat_old = get_orb_features(img_path)
                    if feat_old is None:
                        continue
                    sim = _orb_similarity(feat_new, feat_old)
                    if sim is None:
                        continue
                    if sim > best_sim:
                        best_sim = sim
                        best_path = img_path
                        best_char_id = dir_path.name

            if best_sim >= ORB_THRESHOLD:
                break

        if best_sim >= ORB_THRESHOLD:
            break

    return best_sim, best_path, best_char_id


async def match_hash_id_from_event(
    ev: Event,
    target_type: str,
    char_id: Optional[str] = None,
) -> Optional[Tuple[str, Path, float, str]]:
    if cv2 is None:
        logger.warning("[鸣潮·卡片工具] 未安装opencv-python，无法使用相似度识别。")
        return None

    urls = await get_image(ev)
    if not urls:
        return None

    best_sim = 0.0
    best_path: Optional[Path] = None
    best_char_id: Optional[str] = None

    search_types = [target_type]
    other_types = [t for t in ["card", "bg", "stamina"] if t != target_type]
    search_types.extend(other_types)

    for url in urls:
        image_bytes = await _fetch_image_bytes(url)
        if not image_bytes:
            continue
        sim, path, c_id = await _match_one_image_orb(image_bytes, search_types, target_type, char_id)
        if sim > best_sim:
            best_sim = sim
            best_path = path
            best_char_id = c_id

    if best_path is None or best_char_id is None:
        return None
    if best_sim < ORB_THRESHOLD:
        return None
    return get_hash_id(best_path.name), best_path, best_sim, best_char_id


def _shorten_rel_path(path: Path) -> str:
    rel = _relative_to_main(path)
    p = Path(rel)
    stem = p.stem
    if len(stem) > 10:
        short_stem = f"{stem[:4]}...{stem[-4:]}"
        return str(p.with_name(f"{short_stem}{p.suffix}"))
    return rel


# role_pile 在主面板上的偏移 (25, 170) 与 CROP_PORTRAIT (85, 265, 525, 1070)
# 决定可见区在 role_pile 局部坐标 = (60, 95, 500, 900)。
_PANEL_VISIBLE_BOX_LOCAL = (60, 95, 500, 900)


def resize_and_center_image(
    image: Image.Image,
    output_size: Tuple[int, int] = (560, 1000),
    background_color=(255, 255, 255, 0),
    is_custom: bool = False,
) -> Image.Image:
    """缩放使图片尽量填满目标尺寸并居中, 给 face_card 渲染与 ORB 预处理共用。

    is_custom=False 直接返回原图。
    is_custom=True 且图片含 alpha 时走带 mask 粘贴, 否则无 mask 粘贴 (兼容 RGB 输入)。
    """
    if not is_custom:
        return image

    image = image.copy()
    img_width, img_height = image.size
    target_width, target_height = output_size

    if img_width > img_height:
        scale_factor = target_width / img_width
        new_width = target_width
        new_height = int(img_height * scale_factor)
    else:
        scale_factor = target_height / img_height
        new_width = int(img_width * scale_factor)
        new_height = target_height

    image = image.resize((new_width, new_height))
    result_image = Image.new("RGBA", output_size, background_color)
    paste_x = (target_width - new_width) // 2
    paste_y = (target_height - new_height) // 2
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        result_image.paste(image, (paste_x, paste_y), image)
    else:
        result_image.paste(image, (paste_x, paste_y))
    return result_image


def _prepare_card_image_for_orb(image: Image.Image) -> Image.Image:
    """对 card (面板) 类型: 只取面板真实可见区做 ORB, 与上传分支的 CROP_PORTRAIT 对齐。

    上传分支: 从屏幕坐标 CROP_PORTRAIT (440x805) 裁出来再 ×2;
    存图分支: resize_and_center → 局部 (60,95,500,900) (440x805) 再 ×2;
    两者最终落到同一区域同一分辨率, ORB 描述子可比。
    """
    canvas = resize_and_center_image(image, is_custom=True)
    visible = canvas.crop(_PANEL_VISIBLE_BOX_LOCAL)
    visible = visible.resize(
        (visible.width * 2, visible.height * 2), Image.Resampling.LANCZOS
    )
    return visible.convert("RGB")


def _get_orb_cache_path(image_path: Path) -> Optional[Path]:
    t = card_hash_index.detect_type(image_path)
    if t is None:
        return None
    rel = image_path.relative_to(card_hash_index.TYPE_BASES[t])
    cache_path = CUSTOM_ORB_PATH / t / rel
    return cache_path.with_suffix(cache_path.suffix + ".npz")


def get_orb_dir_for_char(target_type: str, char_id: str) -> Path:
    return CUSTOM_ORB_PATH / target_type / str(char_id)


def _load_orb_cache(image_path: Path):
    cache_path = _get_orb_cache_path(image_path)
    if not cache_path or not cache_path.exists():
        return None
    try:
        data = np.load(cache_path)
        if str(data["fingerprint"][0]) != _orb_fingerprint(image_path):
            return None
        pts = data["pts"]
        des = data["des"]
        if pts.size == 0 or des.size == 0:
            return None
        return pts, des
    except Exception:
        return None


def _save_orb_cache(image_path: Path, pts, des) -> None:
    cache_path = _get_orb_cache_path(image_path)
    if not cache_path:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        cache_path,
        pts=pts,
        des=des,
        fingerprint=np.array([_orb_fingerprint(image_path)]),
    )


def delete_orb_cache(image_path: Path) -> None:
    cache_path = _get_orb_cache_path(image_path)
    if cache_path and cache_path.exists():
        try:
            cache_path.unlink()
        except Exception:
            logger.warning(f"[鸣潮·卡片工具] 删除ORB缓存失败: {cache_path}")


def _compute_orb_features(image_path: Path, t: Optional[str] = None):
    if cv2 is None:
        return None
    if t is None:
        t = card_hash_index.detect_type(image_path)
    if t == "card":
        try:
            with Image.open(image_path) as im:
                im.load()
                prepared = _prepare_card_image_for_orb(crop_image(im, read_crop(image_path)))
        except Exception:
            return None
        rgb = np.array(prepared)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    else:
        gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return None
    orb = cv2.ORB_create(nfeatures=ORB_FEATURES)
    keypoints, descriptors = orb.detectAndCompute(gray, None)
    if descriptors is None or not keypoints:
        return None
    pts = np.float32([kp.pt for kp in keypoints])
    return pts, descriptors


_orb_fingerprint = CacheFingerprint(
    _compute_orb_features,
    _prepare_card_image_for_orb,
    resize_and_center_image,
    crop_image,
    _PANEL_VISIBLE_BOX_LOCAL,
    ORB_FEATURES,
    getattr(cv2, "__version__", None),
)


def get_orb_features(image_path: Path, t: Optional[str] = None):
    # t 显式指定且与路径真实类型不一致时(如 tmp/pending 图按 card 预处理), 跳过按路径缓存。
    use_cache = t is None or t == card_hash_index.detect_type(image_path)
    if use_cache:
        cached = _load_orb_cache(image_path)
        if cached is not None:
            return cached
    computed = _compute_orb_features(image_path, t)
    if computed is None:
        return None
    pts, des = computed
    if use_cache:
        _save_orb_cache(image_path, pts, des)
    return pts, des


def update_orb_cache(image_path: Path) -> bool:
    computed = _compute_orb_features(image_path)
    if computed is None:
        return False
    pts, des = computed
    _save_orb_cache(image_path, pts, des)
    return True


def _orb_similarity(
    feat1,
    feat2,
    ratio: float = ORB_RATIO,
    min_matches: int = ORB_MIN_MATCHES,
) -> Optional[float]:
    if cv2 is None:
        return None
    pts1, des1 = feat1
    pts2, des2 = feat2
    if des1 is None or des2 is None:
        return None
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    knn = matcher.knnMatch(des1, des2, k=2)
    good = []
    for row in knn:
        if len(row) < 2:
            continue
        m, n = row
        if m.distance < ratio * n.distance:
            good.append(m)
    if len(good) < min_matches:
        return None
    pts1_m = np.float32([pts1[m.queryIdx] for m in good])
    pts2_m = np.float32([pts2[m.trainIdx] for m in good])
    h, mask = cv2.findHomography(pts1_m, pts2_m, cv2.RANSAC, 5.0)
    if h is None or mask is None:
        return None
    inliers = int(mask.ravel().sum())
    return inliers / max(len(good), 1)


class UnionFind:
    def __init__(self, items: Iterable[Path]) -> None:
        self.parent: Dict[Path, Path] = {i: i for i in items}
        self.rank: Dict[Path, int] = {i: 0 for i in items}

    def find(self, x: Path) -> Path:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: Path, b: Path) -> None:
        ra = self.find(a)
        rb = self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            self.parent[ra] = rb
        elif self.rank[ra] > self.rank[rb]:
            self.parent[rb] = ra
        else:
            self.parent[rb] = ra
            self.rank[ra] += 1

    def groups(self) -> List[List[Path]]:
        grouped: Dict[Path, List[Path]] = {}
        for item in self.parent:
            root = self.find(item)
            grouped.setdefault(root, []).append(item)
        return list(grouped.values())


def find_duplicate_pairs_in_dir(
    dir_path: Path,
    threshold: float = ORB_THRESHOLD,
) -> List[Tuple[Path, Path, float]]:
    images = list(_iter_images(dir_path))
    if len(images) < 2:
        return []
    features = []
    for img_path in images:
        feat = get_orb_features(img_path)
        if feat is not None:
            features.append((img_path, feat))
    pairs: List[Tuple[Path, Path, float]] = []
    for i in range(len(features)):
        p1, f1 = features[i]
        for j in range(i + 1, len(features)):
            p2, f2 = features[j]
            sim = _orb_similarity(f1, f2)
            if sim is not None and sim >= threshold:
                pairs.append((p1, p2, sim))
    return pairs


def find_duplicate_groups_in_dir(
    dir_path: Path,
    threshold: float = ORB_THRESHOLD,
) -> List[Tuple[List[Path], Dict[Tuple[Path, Path], float]]]:
    images = list(_iter_images(dir_path))
    if len(images) < 2:
        return []
    features = []
    for img_path in images:
        feat = get_orb_features(img_path)
        if feat is not None:
            features.append((img_path, feat))

    uf = UnionFind([p for p, _ in features])
    sim_map: Dict[Tuple[Path, Path], float] = {}
    for i in range(len(features)):
        p1, f1 = features[i]
        for j in range(i + 1, len(features)):
            p2, f2 = features[j]
            sim = _orb_similarity(f1, f2)
            if sim is not None and sim >= threshold:
                uf.union(p1, p2)
                sim_map[(p1, p2)] = sim

    groups = [g for g in uf.groups() if len(g) >= 2]
    return [(g, sim_map) for g in groups]


def find_duplicates_for_new_images(
    dir_path: Path,
    new_images: List[Path],
    threshold: float = ORB_THRESHOLD,
    as_type: Optional[str] = None,
) -> Dict[Path, List[Tuple[Path, float]]]:
    existing = [p for p in _iter_images(dir_path) if p not in new_images]
    existing_feats = {}
    for p in existing:
        feat = get_orb_features(p, as_type)
        if feat is not None:
            existing_feats[p] = feat

    result: Dict[Path, List[Tuple[Path, float]]] = {}
    for new_path in new_images:
        feat_new = get_orb_features(new_path, as_type)
        if feat_new is None:
            continue
        dup_list: List[Tuple[Path, float]] = []
        for old_path, feat_old in existing_feats.items():
            sim = _orb_similarity(feat_new, feat_old)
            if sim is not None and sim >= threshold:
                dup_list.append((old_path, sim))
        if dup_list:
            result[new_path] = dup_list
    return result


def duplicates_for_single(
    target_dir: Path,
    image_path: Path,
    threshold: float = ORB_THRESHOLD,
    as_type: Optional[str] = None,
) -> List[Tuple[Path, float]]:
    """单张图与 target_dir 内已有图的相似项, 按相似度降序。
    as_type 指定时按该类型统一做 ORB 预处理(如 card 裁到面板可见区), 使 tmp/pending 图与已入库图同尺度。cv2 缺失时返回空。"""
    dup = find_duplicates_for_new_images(target_dir, [image_path], threshold, as_type).get(image_path, [])
    return sorted(dup, key=lambda x: -x[1])


async def send_repeated_custom_cards(
    bot: Bot,
    ev: Event,
    threshold: float = ORB_THRESHOLD,
) -> None:
    at_sender = True if ev.group_id else False
    if cv2 is None:
        logger.warning("[鸣潮·卡片工具] opencv-python 未安装，无法使用重复图片查找功能。")
        msg = "[鸣潮] 未安装opencv-python，无法使用重复图片查找功能！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)
    groups: List[Tuple[List[Path], Dict[Tuple[Path, Path], float]]] = []
    char_dirs: List[Path] = []
    for base in CUSTOM_PATH_MAP.values():
        for char_dir in base.iterdir():
            if not char_dir.is_dir():
                continue
            char_dirs.append(char_dir)

    use_cores = max((os.cpu_count() or 1) - 2, 1)
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=use_cores) as executor:
        tasks = [
            loop.run_in_executor(executor, find_duplicate_groups_in_dir, d, threshold)
            for d in char_dirs
        ]
        for result in await asyncio.gather(*tasks):
            groups.extend(result)

    if not groups:
        msg = "[鸣潮] 未找到重复图片！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    groups.sort(key=lambda g: len(g[0]), reverse=True)
    card_num = WutheringWavesConfig.get_config("CharCardNum").data
    card_num = max(5, min(card_num, 30))

    batch: List[object] = []
    batch_img_count = 0

    for group, sim_map in groups:
        group_sorted = sorted(group, key=lambda p: p.name)
        lines = []
        for p in group_sorted:
            rel = _shorten_rel_path(p)
            hash_id = get_hash_id(p.name)
            lines.append(f"{rel} ({hash_id})")
        pair_lines = []
        for i in range(len(group_sorted)):
            for j in range(i + 1, len(group_sorted)):
                p1 = group_sorted[i]
                p2 = group_sorted[j]
                sim = sim_map.get((p1, p2)) or sim_map.get((p2, p1))
                if sim is not None:
                    id1 = get_hash_id(p1.name)
                    id2 = get_hash_id(p2.name)
                    pair_lines.append(f"{id1} <-> {id2} sim={sim:.2f}")
        if pair_lines:
            lines.append("相似度:")
            lines.extend(pair_lines)
        text = "\n".join(lines)
        if at_sender:
            text = " " + text

        imgs = [await convert_img(p) for p in group_sorted]
        if len(imgs) > card_num:
            if batch:
                await bot.send(batch)
                batch = []
                batch_img_count = 0
            msg = f"[鸣潮] 重复组图片数量({len(imgs)})超过单条上限({card_num})，将分条发送。"
            await bot.send((" " if at_sender else "") + msg, at_sender)
            for i in range(0, len(imgs), card_num):
                part_imgs = imgs[i : i + card_num]
                await bot.send([text] + part_imgs)
            continue

        if batch_img_count + len(imgs) > card_num and batch:
            await bot.send(batch)
            batch = []
            batch_img_count = 0

        batch.extend([text] + imgs)
        batch_img_count += len(imgs)

    if batch:
        await bot.send(batch)


@to_thread
def _crop_card_file(path: Path) -> Optional[Image.Image]:
    crop = read_crop(path)
    if crop is None:
        return None
    try:
        with Image.open(path) as im:
            im.load()
            return crop_image(im, crop)
    except Exception:
        return None


async def _one_card_img(t: str, path: Path) -> str:
    cropped = await _crop_card_file(path)
    return await convert_img(cropped if cropped is not None else path, is_base64=True)


async def _send_found_matches(bot: Bot, matches) -> None:
    """命中非空: 单张直接发; 多张走转发消息 (来源「xx角色的xx图」+ 图)。"""
    if len(matches) == 1:
        _t, _cid, path = matches[0]
        return await bot.send(await convert_img(path))
    imgs = []
    for t, other_char_id, path in matches:
        type_name = CUSTOM_PATH_NAME_MAP.get(t, t)
        imgs.append(f"{_listing_char_name(other_char_id)}的{type_name}图")
        imgs.append(await convert_img(path))
    await bot.send(MessageSegment.node(imgs))


async def send_custom_card_single(
    bot: Bot,
    ev: Event,
    char: str,
    hash_id: str,
    target_type: str = "card",
) -> None:
    at_sender = True if ev.group_id else False
    char_id, char, msg = get_char_id_and_name(char)
    if msg:
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    type_label = CUSTOM_PATH_NAME_MAP.get(target_type, target_type)
    target = card_hash_index.lookup_in(target_type, char_id, hash_id)
    if target is not None:
        return await bot.send(await convert_img(target))

    matches = card_hash_index.find(hash_id)
    if matches:
        return await _send_found_matches(bot, matches)

    if not card_hash_index.list_dir(target_type, char_id):
        msg = f"[鸣潮] 角色【{char}】暂未上传过{type_label}图！"
    else:
        msg = f"[鸣潮] 角色【{char}】未找到id为【{hash_id}】的{type_label}图！"
    return await bot.send((" " if at_sender else "") + msg, at_sender)


async def send_custom_card_single_by_id(
    bot: Bot,
    ev: Event,
    hash_id: str,
) -> None:
    at_sender = True if ev.group_id else False
    matches = card_hash_index.find(hash_id)
    if not matches:
        msg = f"[鸣潮] 未找到id为【{hash_id}】的图片！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)
    await _send_found_matches(bot, matches)
