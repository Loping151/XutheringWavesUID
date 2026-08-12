import os
import random
import base64
import hashlib
from io import BytesIO
from contextvars import ContextVar
from typing import Tuple, Union, Literal, Optional
from pathlib import Path

# 面板编辑器预览用: 强制本次渲染的立绘/背景图。
_force_pile_path: ContextVar[Optional[Path]] = ContextVar("_ww_force_pile_path", default=None)
_force_bg_path: ContextVar[Optional[Path]] = ContextVar("_ww_force_bg_path", default=None)

from PIL import (
    Image,
    ImageOps,
    ImageDraw,
    ImageFont,
    ImageFilter,
    ImageEnhance,
)

from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.utils.image.utils import sget
from gsuid_core.utils.image.image_tools import crop_center_img

from .resource.RESOURCE_PATH import (
    AVATAR_PATH,
    CACHE_PATH,
    WEAPON_PATH,
    ROLE_BG_PATH,
    SHARE_BG_PATH,
    TITLE_BG_PATH,
    ROLE_PILE_PATH,
    CUSTOM_CARD_PATH,
    CUSTOM_MR_BG_PATH,
    CUSTOM_MR_CARD_PATH,
)
from ..wutheringwaves_config.wutheringwaves_config import ShowConfig

ICON = Path(__file__).parent.parent.parent / "ICON.png"
TEXT_PATH = Path(__file__).parent / "texture2d"
GREY = (216, 216, 216)
BLACK_G = (40, 40, 40)
YELLOW = (255, 200, 1)
RED = (255, 0, 0)
BLUE = (1, 183, 255)
GOLD = (224, 202, 146)
SPECIAL_GOLD = (234, 183, 4)
AMBER = (204, 140, 0)
GREEN = (144, 238, 144)

# 冷凝-凝夜白霜
WAVES_FREEZING = (53, 152, 219)
# 热熔-熔山裂谷
WAVES_MOLTEN = (186, 55, 42)
# 导电-彻空冥雷
WAVES_VOID = (185, 106, 217)
# 气动-啸谷长风
WAVES_SIERRA = (22, 145, 121)
# 衍射-浮星祛暗
WAVES_CELESTIAL = (241, 196, 15)
# 湮灭-沉日劫明
WAVES_SINKING = (132, 63, 161)
# 治疗-隐世回光
WAVES_REJUVENATING = (45, 194, 107)
# 辅助-轻云出月
WAVES_MOONLIT = (149, 165, 166)
# 攻击-不绝余音
WAVES_LINGERING = (52, 73, 94)

WAVES_ECHO_MAP = {
    "凝夜白霜": WAVES_FREEZING,
    "熔山裂谷": WAVES_MOLTEN,
    "彻空冥雷": WAVES_VOID,
    "啸谷长风": WAVES_SIERRA,
    "浮星祛暗": WAVES_CELESTIAL,
    "沉日劫明": WAVES_SINKING,
    "隐世回光": WAVES_REJUVENATING,
    "轻云出月": WAVES_MOONLIT,
    "不绝余音": WAVES_LINGERING,
}

WAVES_SHUXING_MAP = {
    "冷凝": WAVES_FREEZING,
    "热熔": WAVES_MOLTEN,
    "导电": WAVES_VOID,
    "气动": WAVES_SIERRA,
    "衍射": WAVES_CELESTIAL,
    "湮灭": WAVES_SINKING,
}


def rgb_to_hex(rgb: Tuple) -> str:
    """将RGB/RGBA元组转换为十六进制或rgba颜色字符串"""
    if len(rgb) == 4:
        return "rgba({}, {}, {}, {})".format(rgb[0], rgb[1], rgb[2], rgb[3])
    return "#{:02x}{:02x}{:02x}".format(rgb[0], rgb[1], rgb[2])


def clean_alpha_matte(img: Image.Image, matte: Tuple[int, int, int, int]) -> Image.Image:
    """用指定底色清理透明图边缘的 RGB，避免缩放后出现白边/白点。"""
    img = img.convert("RGBA")
    alpha = img.getchannel("A")
    if alpha.getextrema() == (255, 255):
        return img
    clean = Image.new("RGBA", img.size, matte)
    clean.alpha_composite(img)
    clean.putalpha(alpha)
    return clean


def flatten_rgba(
    img: Image.Image,
    bg_color: Union[str, Tuple[int, ...]],
) -> Image.Image:
    """把 RGBA 图按指定底色压平成不透明图，避免转 JPEG 时透明层变白。"""
    base = Image.new("RGBA", img.size, bg_color)
    base.alpha_composite(img.convert("RGBA"))
    return base


def make_smooth_rounded_mask(size: Tuple[int, int], radius: int, scale: int = 4) -> Image.Image:
    scaled_size = (size[0] * scale, size[1] * scale)
    mask = Image.new("L", scaled_size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        (0, 0, scaled_size[0] - 1, scaled_size[1] - 1),
        radius=radius * scale,
        fill=255,
    )
    return mask.resize(size, Image.Resampling.LANCZOS)


def make_smooth_circle_mask(size: int, scale: int = 4) -> Image.Image:
    mask_size = size * scale
    mask = Image.new("L", (mask_size, mask_size), 0)
    draw = ImageDraw.Draw(mask)
    inset = scale
    draw.ellipse(
        (inset, inset, mask_size - inset - 1, mask_size - inset - 1),
        fill=255,
    )
    return mask.resize((size, size), Image.Resampling.LANCZOS)


def pil_to_b64(img: Image.Image, quality: int = 0) -> str:
    """将PIL图像转换为base64编码的data URL

    quality=0: PNG无损（默认）
    quality>0: WebP有损压缩（保留透明通道），推荐80
    """
    buffered = BytesIO()
    if quality > 0:
        img.save(buffered, format="WEBP", quality=quality)
        return "data:image/webp;base64," + base64.b64encode(buffered.getvalue()).decode('utf-8')
    img.save(buffered, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffered.getvalue()).decode('utf-8')


def img_to_b64(path: Union[str, Path], quality: int = 0, bake: bool = False,
               cover_size: Optional[Tuple[int, int]] = None) -> str:
    """文件路径 → base64 data URL，支持烘焙缓存。

    quality=0: 原格式直读（最快，不经过PIL）
    quality>0: WebP压缩
    bake=True + quality>0: 烘焙缓存，命中时跳过PIL，直接读文件
    cover_size: (w, h) 模拟 object-fit:cover 居中裁切到指定尺寸
    """
    from .resource.RESOURCE_PATH import BAKE_PATH

    path = Path(path) if not isinstance(path, Path) else path
    if not path.exists():
        return ""

    size_tag = f"_{cover_size[0]}x{cover_size[1]}" if cover_size else ""

    def _apply_cover(img: Image.Image) -> Image.Image:
        if cover_size is None:
            return img
        tw, th = cover_size
        scale = max(tw / img.width, th / img.height)
        new_w, new_h = int(img.width * scale), int(img.height * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - tw) // 2
        top = (new_h - th) // 2
        return img.crop((left, top, left + tw, top + th))

    # 烘焙命中：直接读 bake 文件，不打开 PIL
    if bake and quality > 0:
        import hashlib
        path_hash = hashlib.md5(str(path.resolve()).encode()).hexdigest()[:8]
        bake_path = BAKE_PATH / f"{path.stem}_{path_hash}_q{quality}{size_tag}.webp"
        if bake_path.exists() and bake_path.stat().st_mtime >= path.stat().st_mtime:
            with open(bake_path, "rb") as f:
                return "data:image/webp;base64," + base64.b64encode(f.read()).decode('utf-8')
        # 未命中：PIL 打开 → WebP → 写入烘焙
        img = _apply_cover(Image.open(path).convert("RGBA"))
        buffered = BytesIO()
        img.save(buffered, format="WEBP", quality=quality)
        data = buffered.getvalue()
        try:
            bake_path.write_bytes(data)
        except Exception:
            pass
        return "data:image/webp;base64," + base64.b64encode(data).decode('utf-8')

    # 不烘焙
    if quality > 0:
        img = _apply_cover(Image.open(path).convert("RGBA"))
        buffered = BytesIO()
        img.save(buffered, format="WEBP", quality=quality)
        return "data:image/webp;base64," + base64.b64encode(buffered.getvalue()).decode('utf-8')

    # quality=0: 原格式直读（不支持 cover_size）
    ext = path.suffix.lstrip(".").lower()
    if ext == "jpg":
        ext = "jpeg"
    with open(path, "rb") as f:
        return f"data:image/{ext};base64,{base64.b64encode(f.read()).decode('utf-8')}"


ELEMENT_COLOR_MAP = {
    "冷凝": rgb_to_hex(WAVES_FREEZING),
    "热熔": rgb_to_hex(WAVES_MOLTEN),
    "导电": rgb_to_hex(WAVES_VOID),
    "气动": rgb_to_hex(WAVES_SIERRA),
    "衍射": rgb_to_hex(WAVES_CELESTIAL),
    "湮灭": rgb_to_hex(WAVES_SINKING),
}

CHAIN_COLOR = {
    0: WAVES_MOONLIT,
    1: WAVES_LINGERING,
    2: WAVES_SIERRA,
    3: WAVES_FREEZING,
    4: WAVES_VOID,
    5: AMBER,
    6: WAVES_MOLTEN,
}

CHAIN_COLOR_LIST = [CHAIN_COLOR[i] for i in range(7)]

WEAPON_RESONLEVEL_COLOR = {
    0: WAVES_MOONLIT,
    1: WAVES_LINGERING,
    2: WAVES_SIERRA,
    3: WAVES_FREEZING,
    4: WAVES_VOID,
    5: AMBER,
    6: WAVES_MOLTEN,
}


# 排行卡 bot 背景: title_bg 下 T_TitleCardBg_<Name>.png
_TITLE_BG_PREFIX = "T_TitleCardBg_"
_RESERVED_BG = "weixin"  # 小程序专属, 普通用户禁用, 随机兜底也排除
# 标准背景图在 388x72 内的实际有效区域(量自常规图 L7/T9/R7/B8)。固定裁剪而非按各图
# 透明边裁: 部分图有溢出有效区的特效, 按透明边裁会得到不一致大小。比例化兼容非标尺寸。
_title_bg_index_cache: Optional[dict] = None
_title_bg_img_cache: dict = {}


def _title_bg_index() -> dict:
    """{小写名: 路径} 索引。空目录不缓存, 以便资源后到位时重扫。"""
    global _title_bg_index_cache
    if _title_bg_index_cache:
        return _title_bg_index_cache
    index = {}
    try:
        for f in os.listdir(TITLE_BG_PATH):
            if not f.startswith(_TITLE_BG_PREFIX) or not f.lower().endswith(".png"):
                continue
            index[f[len(_TITLE_BG_PREFIX):-4].lower()] = TITLE_BG_PATH / f
    except FileNotFoundError:
        pass
    if index:
        _title_bg_index_cache = index
    return index


def get_bot_bg(background: str) -> Optional[Image.Image]:
    """bot 背景: 按名取背景图(大小写无关); 未指定/未命中则随机(排除 weixin); 无图返回 None。"""
    index = _title_bg_index()
    if not index:
        return None
    path = index.get((background or "").strip().lower())
    if path is None:
        candidates = [p for n, p in index.items() if n != _RESERVED_BG]
        if not candidates:
            return None
        path = random.choice(candidates)
    key = str(path)
    img = _title_bg_img_cache.get(key)
    if img is None:
        try:
            img = Image.open(path).convert("RGBA")
        except Exception:
            return None
        # 不裁剪, 返回整图由调用方直接 resize, 兼容异形边缘的背景
        _title_bg_img_cache[key] = img
    return img


def _random_image_from_dir(directory: str) -> Optional[str]:
    """Return a random image filename from a directory, skipping hidden/non-image files."""
    valid_files = [
        f
        for f in os.listdir(directory)
        if not f.startswith(".") and f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
    ]
    return random.choice(valid_files) if valid_files else None


def _list_custom_char_dirs(base_path: str) -> list:
    """列出 base_path 下 4 位数字命名且非空的子目录名 (即合法 char_id 子目录)。
    避免抽到 .DS_Store / 临时目录 / 备份目录之类的脏命名。"""
    try:
        entries = os.listdir(base_path)
    except (FileNotFoundError, NotADirectoryError):
        return []
    result = []
    for name in entries:
        if len(name) != 4 or not name.isdigit():
            continue
        sub = f"{base_path}/{name}"
        try:
            if os.path.isdir(sub) and len(os.listdir(sub)) > 0:
                result.append(name)
        except OSError:
            continue
    return result


def get_ICON():
    return Image.open(ICON)


async def get_random_share_bg():
    path = random.choice(os.listdir(f"{SHARE_BG_PATH}"))
    return Image.open(f"{SHARE_BG_PATH}/{path}").convert("RGBA")


async def get_random_share_bg_path():
    path = random.choice(os.listdir(f"{SHARE_BG_PATH}"))
    return SHARE_BG_PATH / path


def _list_official_image_files(base_path: str) -> list:
    """列出 base_path 下合法图片文件名 (跳过隐藏/非图片)。"""
    try:
        entries = os.listdir(base_path)
    except (FileNotFoundError, NotADirectoryError):
        return []
    return [
        f for f in entries
        if not f.startswith(".") and f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
    ]


def _include_official_pile() -> bool:
    return bool(ShowConfig.get_config("MrRandomIncludeOfficialPile").data)


def _include_official_bg() -> bool:
    return bool(ShowConfig.get_config("MrRandomIncludeOfficialBg").data)


def _mr_pool(
    custom_base: str,
    official_base: str,
    char_id: Optional[str],
    official_name: str,
    force_not_use_custom: bool,
    include_official: bool,
    official_fallback: bool = True,
) -> list:
    """构建一侧(立绘或背景)的候选池, 每张图一个条目(逐张等权)。

    官方图并入条件: 开关开 / 强制只用官方 / (允许侧内 fallback 且 custom 池为空)。
    official_fallback=False 用于「随机」的计数口径: 官方只由开关决定,
    单侧 custom 为空不自动并官方(两侧全空的 fallback 由 mr_prefer_bg 统一处理)。
    指定角色时官方图为单文件; 无角色时数整库。
    """
    pool: list = []
    if not force_not_use_custom:
        if char_id:
            d = f"{custom_base}/{char_id}"
            pool += [f"{d}/{f}" for f in _list_official_image_files(d)]
        else:
            for cid in _list_custom_char_dirs(custom_base):
                d = f"{custom_base}/{cid}"
                pool += [f"{d}/{f}" for f in _list_official_image_files(d)]
    if include_official or force_not_use_custom or (official_fallback and not pool):
        if char_id:
            p = f"{official_base}/{official_name}"
            if os.path.exists(p):
                pool.append(p)
        else:
            pool += [f"{official_base}/{f}" for f in _list_official_image_files(official_base)]
    return pool


def _mr_pool_bg(char_id, force_not_use_custom, include_official, official_fallback=True) -> list:
    return _mr_pool(
        str(CUSTOM_MR_BG_PATH), str(ROLE_BG_PATH), char_id,
        f"{char_id}.webp", force_not_use_custom, include_official, official_fallback,
    )


def _mr_pool_pile(char_id, force_not_use_custom, include_official, official_fallback=True) -> list:
    return _mr_pool(
        str(CUSTOM_MR_CARD_PATH), str(ROLE_PILE_PATH), char_id,
        f"role_pile_{char_id}.png", force_not_use_custom, include_official, official_fallback,
    )


def mr_prefer_bg(char_id: Optional[str] = None, force_not_use_custom: bool = False) -> bool:
    """MrUseBG 三态 → 是否走背景分支; 随机=按两侧候选池实际图数加权(逐张等权)。

    随机口径: custom 立绘+custom 背景合并, 官方是否占位(各按实际张数)由两个开关分别控制;
    两侧候选全空时忽略开关, 按该作用域的官方背景/官方立绘 fallback,
    官方背景也没有则落到立绘分支(fetcher 内再逐级兜底)。
    分支选中后 fetcher 的单侧池与此口径一致, 整体等价于合并池逐张等权。
    """
    pref = ShowConfig.get_config("MrUseBG").data
    if pref == "背景":
        return True
    if pref != "随机":
        return False
    n_bg = len(_mr_pool_bg(char_id, force_not_use_custom, _include_official_bg(), official_fallback=False))
    n_pile = len(_mr_pool_pile(char_id, force_not_use_custom, _include_official_pile(), official_fallback=False))
    total = n_bg + n_pile
    if total > 0:
        return random.random() * total < n_bg
    n_bg = len(_mr_pool_bg(char_id, True, True))
    n_pile = len(_mr_pool_pile(char_id, True, True))
    total = n_bg + n_pile
    return total > 0 and random.random() * total < n_bg


async def get_random_waves_role_pile(
    char_id: Optional[str] = None,
    force_not_use_custom: bool = False,
) -> tuple[Image.Image, Optional[Path]]:
    forced = _force_pile_path.get()
    if forced is not None and forced.exists():
        return Image.open(forced).convert("RGBA"), forced
    pool = _mr_pool_pile(char_id, force_not_use_custom, _include_official_pile())
    if not pool and char_id:
        # 该角色 custom/官方立绘全缺: 从全库可用立绘里抽
        pool = _mr_pool_pile(None, force_not_use_custom, True)
    if pool:
        full = Path(random.choice(pool))
        return Image.open(full).convert("RGBA"), full
    full = ROLE_PILE_PATH / "role_pile_1503.png"
    return Image.open(full).convert("RGBA"), full


async def get_random_waves_bg(
    char_id: Optional[str] = None,
    force_not_use_custom: bool = False,
) -> tuple[Image.Image, bool, Optional[Path]]:
    forced = _force_bg_path.get()
    if forced is not None and forced.exists():
        return Image.open(forced).convert("RGBA"), True, forced
    pool = _mr_pool_bg(char_id, force_not_use_custom, _include_official_bg())
    if pool:
        full = Path(random.choice(pool))
        return Image.open(full).convert("RGBA"), True, full
    pile, pile_path = await get_random_waves_role_pile(char_id, force_not_use_custom)
    return pile, False, pile_path


async def get_role_pile(resource_id: Union[int, str], custom: bool = False) -> tuple[bool, Image.Image]:
    if custom:
        custom_dir = f"{CUSTOM_CARD_PATH}/{resource_id}"
        if os.path.isdir(custom_dir) and len(os.listdir(custom_dir)) > 0:
            path = _random_image_from_dir(custom_dir)
            if path:
                return True, Image.open(f"{custom_dir}/{path}").convert("RGBA")

    name = f"role_pile_{resource_id}.png"
    path = ROLE_PILE_PATH / name
    if os.path.exists(path):
        return False, Image.open(path).convert("RGBA")
    return False, Image.open(ROLE_PILE_PATH / "role_pile_1503.png").convert("RGBA")

async def get_role_pile_with_path(
    resource_id: Union[int, str],
    custom: bool = False,
) -> tuple[bool, Image.Image, Optional[Path]]:
    forced = _force_pile_path.get()
    if forced is not None and forced.exists():
        return True, Image.open(forced).convert("RGBA"), forced
    if custom:
        custom_dir = f"{CUSTOM_CARD_PATH}/{resource_id}"
        if os.path.isdir(custom_dir) and len(os.listdir(custom_dir)) > 0:
            name = _random_image_from_dir(custom_dir)
            if name:
                path = Path(custom_dir) / name
                return True, Image.open(path).convert("RGBA"), path

    name = f"role_pile_{resource_id}.png"
    path = ROLE_PILE_PATH / name
    if os.path.exists(path):
        return False, Image.open(path).convert("RGBA"), path
    return False, Image.open(ROLE_PILE_PATH / "role_pile_1503.png").convert("RGBA"), None

async def get_role_pile_default(
    resource_id: Union[int, str],
    custom: bool = False,
) -> tuple[Image.Image, Optional[Path]]:
    forced = _force_pile_path.get()
    if forced is not None and forced.exists():
        return Image.open(forced).convert("RGBA"), forced
    if custom:
        custom_dir = f"{CUSTOM_MR_CARD_PATH}/{resource_id}"
        if os.path.isdir(custom_dir) and len(os.listdir(custom_dir)) > 0:
            name = _random_image_from_dir(custom_dir)
            if name:
                full = Path(custom_dir) / name
                return Image.open(full).convert("RGBA"), full

    name = f"role_pile_{resource_id}.png"
    path = ROLE_PILE_PATH / name
    if not os.path.exists(path):
        path = ROLE_PILE_PATH / "role_pile_1503.png"
    return Image.open(path).convert("RGBA"), path


def get_square_avatar_path(resource_id: Union[int, str]) -> Path:
    path = AVATAR_PATH / f"role_head_{resource_id}.png"
    if not path.exists():
        path = AVATAR_PATH / "role_head_1503.png"
    return path


async def get_square_avatar(resource_id: Union[int, str]) -> Image.Image:
    return Image.open(get_square_avatar_path(resource_id)).convert("RGBA")


async def cropped_square_avatar(item_icon: Image.Image, size: int) -> Image.Image:
    # 目标尺寸
    target_width, target_height = size, size
    # 原始尺寸
    original_width, original_height = item_icon.size

    width_ratio = target_width / original_width
    height_ratio = target_height / original_height
    scale_ratio = max(width_ratio, height_ratio)
    new_width = int(original_width * scale_ratio)
    new_height = int(original_height * scale_ratio)
    resized_image = item_icon.resize((new_width, new_height), Image.Resampling.LANCZOS)
    x_center = new_width // 2
    y_center = new_height // 2
    crop_area = (
        x_center - target_width // 2,
        y_center - target_height // 2,
        x_center + target_width // 2,
        y_center + target_height // 2,
    )
    resized_image = resized_image.crop(crop_area).convert("RGBA")
    return resized_image


def get_square_weapon_path(resource_id: Union[int, str]) -> Path:
    path = WEAPON_PATH / f"weapon_{resource_id}.png"
    if path.exists():
        return path
    return WEAPON_PATH / "weapon_21020012.png"


async def get_square_weapon(resource_id: Union[int, str]) -> Image.Image:
    return Image.open(get_square_weapon_path(resource_id)).convert("RGBA")


async def get_attribute(name: str = "", is_simple: bool = False) -> Image.Image:
    if is_simple:
        name = f"attribute/attr_simple_{name}.png"
    else:
        name = f"attribute/attr_{name}.png"
    path = TEXT_PATH / name
    if not path.exists():
        return Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    return Image.open(path).convert("RGBA")


async def get_attribute_prop(name: str = "") -> Image.Image:
    if (TEXT_PATH / "attribute_prop" / f"attr_prop_{name}.png").exists():
        return Image.open(TEXT_PATH / "attribute_prop" / f"attr_prop_{name}.png").convert("RGBA")
    else:
        return Image.open(TEXT_PATH / "attribute_prop" / "attr_prop_攻击.png").convert("RGBA")

async def get_attribute_skill(name: str = "", locale: Optional[str] = None) -> Image.Image:
    if not name:
        return Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    cache_dir = CACHE_PATH / "attribute_skill"
    cache_path = cache_dir / f"{name}.png"
    if cache_path.exists():
        return Image.open(cache_path).convert("RGBA")
    from .fonts.waves_fonts import waves_font_20, waves_font_24
    from .localization import t

    img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    translated = t(name, locale) if locale else name
    for sep in ("·", " - "):
        if sep in translated:
            translated = translated.split(sep)[-1].strip()
            break
    short = translated[:10]
    font = waves_font_20 if len(short) > 6 else waves_font_24
    draw = ImageDraw.Draw(img)
    draw.text((50, 50), short, fill="white", font=font, anchor="mm")
    return img


def get_skill_branch_emblem(
    char_id: int, skill_branch_index: Optional[int], size: int = 30
) -> Optional[Image.Image]:
    """skillBranchIndex → 技能分支徽章(中心金色光源 + 灰底); 无则 None"""
    if skill_branch_index is None:
        return None
    from .ascension.char import get_char_model

    char_model = get_char_model(char_id)
    branches = getattr(char_model, "skillBranches", None) if char_model else None
    if not branches or skill_branch_index >= len(branches):
        return None
    cache_path = CACHE_PATH / "attribute_skill" / f"{branches[skill_branch_index].name}.png"
    if not cache_path.exists():
        return None
    icon = Image.open(cache_path).convert("RGBA").resize((size, size))
    rc = size // 2
    m = max(3, int(rc * 0.22))
    W = H = 2 * rc + 2 * m
    cx = cy = W // 2
    emblem = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow = Image.new("L", (W, H), 0)
    gr2 = max(2, int(rc * 0.45))
    ImageDraw.Draw(glow).ellipse([cx - gr2, cy - gr2, cx + gr2, cy + gr2], fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(max(2, int(rc * 0.4))))
    rlay = Image.new("RGBA", (W, H), (255, 221, 160, 0))
    rlay.putalpha(glow.point(lambda v: min(190, int(v * 1.7))))
    emblem.alpha_composite(rlay)
    gray = Image.new("L", (W, H), 0)
    gdr = int(rc * 0.72)
    ImageDraw.Draw(gray).ellipse([cx - gdr, cy - gdr, cx + gdr, cy + gdr], fill=255)
    glay = Image.new("RGBA", (W, H), (45, 49, 58, 0))
    glay.putalpha(gray.filter(ImageFilter.GaussianBlur(max(2, rc // 4))).point(lambda v: int(v * 0.55)))
    emblem.alpha_composite(glay)
    emblem.alpha_composite(icon, (cx - size // 2, cy - size // 2))
    return emblem


def paste_skill_branch_emblem(
    canvas: Image.Image,
    char_id: int,
    skill_branch_index: Optional[int],
    center: Tuple[int, int],
    size: int = 30,
) -> None:
    """有分支徽章则按 center 居中贴到 canvas, 无则跳过 (PIL 渲染用)"""
    emblem = get_skill_branch_emblem(char_id, skill_branch_index, size)
    if emblem:
        canvas.alpha_composite(emblem, (center[0] - emblem.width // 2, center[1] - emblem.height // 2))


def get_skill_branch_emblem_b64(
    char_id: int, skill_branch_index: Optional[int], size: int = 40
) -> str:
    """分支图标 base64(PNG data URL), 无则空串 (HTML 渲染用)"""
    emblem = get_skill_branch_emblem(char_id, skill_branch_index, size)
    return pil_to_b64(emblem) if emblem else ""


async def get_attribute_effect(name: str = "") -> Image.Image:
    if (TEXT_PATH / "attribute_effect" / f"attr_{name}.png").exists():
        return Image.open(TEXT_PATH / "attribute_effect" / f"attr_{name}.png").convert("RGBA")
    else:
        return Image.open(TEXT_PATH / "attribute_effect" / "attr.png").convert("RGBA")


def get_sonata_label(sonata_name: str) -> str:
    """组合套装名形如 '洛2+2|沉日劫明|幽夜隐匿之帷', 显示只取 '|' 前标签。"""
    return sonata_name.split("|", 1)[0]


async def get_sonata_effect_image(sonata_name: str, size: int = 50) -> Image.Image:
    """取合鸣图标; 组合套装名(含 '|')时把 '|' 后各套装图标对角错位叠成一张。"""
    parts = sonata_name.split("|")
    names = parts[1:] if len(parts) > 1 else parts[:1]
    icons = [await get_attribute_effect(n) for n in names]
    if len(icons) <= 1:
        return icons[0].resize((size, size))
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sub = int(size * 0.66)
    step = (size - sub) // (len(icons) - 1)
    for i, icon in enumerate(icons):
        canvas.alpha_composite(icon.resize((sub, sub)), (step * i, step * i))
    return canvas


async def get_weapon_type(name: str = "") -> Image.Image:  # 出新武器改这里
    path = TEXT_PATH / f"weapon_type/weapon_type_{name}.png"
    if not path.exists():
        return Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    return Image.open(path).convert("RGBA")


def get_waves_bg(w: int = 0, h: int = 0, bg: str = "bg", crop: bool = True) -> Image.Image:
    img = Image.open(TEXT_PATH / f"{bg}.jpg").convert("RGBA")
    return crop_center_img(img, w, h) if crop else img


def get_custom_waves_bg(  # 不是所有地方都适合替换为custom，函数分开
    w: int = 0,
    h: int = 0,
    bg: str = "bg",
    crop: bool = True,
):
    assert not crop or (w != 0 and h != 0), "裁剪图片时需要指定宽高"
    img: Optional[Image.Image] = None
    if ShowConfig.get_config("CardBg").data:
        bg_path = Path(ShowConfig.get_config("CardBgPath").data)
        if bg_path.is_file():
            img = Image.open(bg_path).convert("RGBA")
            if crop and img:
                img = crop_center_img(img, w, h)
    if not img:
        img = get_waves_bg(w, h, bg, crop=crop)

    img = _get_custom_gaussian_blur(img)
    return img


def get_crop_waves_bg(w: int, h: int, bg: str = "bg") -> Image.Image:
    img = Image.open(TEXT_PATH / f"{bg}.jpg").convert("RGBA")

    width, height = img.size

    crop_box = (0, height // 2, width, height)

    cropped_image = img.crop(crop_box)

    return crop_center_img(cropped_image, w, h)


# qlogo 对无效号/无头像返回 QQ 企鹅占位图(HTTP 200)，按 md5 识别并视为无头像
QQ_DEFAULT_AVATAR_MD5 = frozenset({
    "bad9cbb852b22fe58e62f3f23c7d63d2",  # q1.qlogo 个人号占位 (s>=140)
    "4700116072a9eba9330a81fbbe49b7d5",  # q1.qlogo 个人号占位 (s=100)
    "bb7257abd317126fc3fd3e29ea118958",  # q.qlogo 官机(qqgroup)占位
})


def is_qq_default_avatar(content: bytes) -> bool:
    return hashlib.md5(content).hexdigest() in QQ_DEFAULT_AVATAR_MD5


async def get_qq_avatar(
    qid: Optional[Union[int, str]] = None,
    avatar_url: Optional[str] = None,
    size: int = 640,
) -> Optional[Image.Image]:
    if qid and isinstance(qid, int) or (isinstance(qid, str) and qid.isdigit()):
        avatar_url = f"http://q1.qlogo.cn/g?b=qq&nk={qid}&s={size}"
    elif avatar_url is None:
        return None  # 并非 QQ 来源
    content = (await sget(avatar_url)).content
    if is_qq_default_avatar(content):
        return None
    return Image.open(BytesIO(content)).convert("RGBA")


async def get_event_avatar(
    ev: Event,
    avatar_path: Optional[Path] = None,
    size: int = 640,
    is_valid_at_param: bool = True,
) -> Image.Image:
    img = None

    if is_valid_at_param:
        from .at_help import is_valid_at

        is_valid_at_param = is_valid_at(ev)

    if ev.bot_id == "onebot" and ev.at and is_valid_at_param:
        try:
            img = await get_qq_avatar(ev.at, size=size)
        except Exception:
            img = None

    if img is None and ev.bot_id == "qqgroup" and ev.at and is_valid_at_param:
        try:
            url = f"https://q.qlogo.cn/qqapp/{ev.bot_self_id}/{ev.at}/100"
            img = await get_qq_avatar(avatar_url=url, size=size)
        except Exception:
            img = None

    if img is None and not is_valid_at_param and "avatar" in ev.sender and ev.sender["avatar"]:
        avatar_url: str = ev.sender["avatar"]
        if avatar_url.startswith(("http", "https")):
            try:
                content = (await sget(avatar_url)).content
                if not is_qq_default_avatar(content):
                    img = Image.open(BytesIO(content)).convert("RGBA")
            except Exception:
                img = None

    if img is None and ev.bot_id == "onebot" and not ev.sender:
        try:
            img = await get_qq_avatar(ev.user_id, size=size)
        except Exception:
            img = None

    if img is None and avatar_path:
        pic_path_list = list(avatar_path.iterdir())
        if pic_path_list:
            path = random.choice(pic_path_list)
            img = Image.open(path).convert("RGBA")

    if img is None:
        img = await get_square_avatar(1503)

    return img


def get_small_logo(logo_num=1):
    return Image.open(TEXT_PATH / f"logo_small_{logo_num}.png")


def get_footer(color: Literal["white", "black"] = "white"):
    return Image.open(TEXT_PATH / f"footer_{color}.png")


def add_footer(
    img: Image.Image,
    w: int = 0,
    offset_y: int = 0,
    is_invert: bool = False,
    color: Literal["white", "black"] = "white",
):
    footer = get_footer(color)
    if is_invert:
        r, g, b, a = footer.split()
        rgb_image = Image.merge("RGB", (r, g, b))
        rgb_image = ImageOps.invert(rgb_image.convert("RGB"))
        r2, g2, b2 = rgb_image.split()
        footer = Image.merge("RGBA", (r2, g2, b2, a))

    if w != 0:
        footer = footer.resize(
            (w, int(footer.size[1] * w / footer.size[0])),
        )

    x, y = (
        int((img.size[0] - footer.size[0]) / 2),
        img.size[1] - footer.size[1] - 20 + offset_y,
    )

    img.paste(footer, (x, y), footer)
    return img


async def change_color(
    chain,
    color: tuple = (255, 255, 255),
    w: Optional[int] = None,
    h: Optional[int] = None,
):
    # 获取图像数据
    pixels = chain.load()  # 加载像素数据
    if w is None:
        w = chain.size[0]
    if h is None:
        h = chain.size[1]

    if not isinstance(h, int) or not isinstance(w, int):
        return chain

    # 如果 color 是 RGBA，只取前三个
    if len(color) == 4:
        color = color[:3]

    # 遍历图像的每个像素
    for y in range(h):  # 图像高度
        for x in range(w):  # 图像宽度
            r, g, b, a = pixels[x, y]
            pixels[x, y] = color + (a,)

    return chain


def draw_text_with_shadow(
    image: ImageDraw.ImageDraw,
    text: str,
    _x: int,
    _y: int,
    font: ImageFont.FreeTypeFont,
    fill_color: str = "white",
    shadow_color: Union[float, tuple[int, ...], str] = "black",
    offset: Tuple[int, int] = (2, 2),
    anchor="rm",
):
    """描边"""
    from .fonts.waves_fonts import draw_text_with_fallback

    for i in range(-offset[0], offset[0] + 1):
        for j in range(-offset[1], offset[1] + 1):
            draw_text_with_fallback(image, (_x + i, _y + j), text, fill=shadow_color, font=font, anchor=anchor)

    draw_text_with_fallback(image, (_x, _y), text, fill=fill_color, font=font, anchor=anchor)
    draw_text_with_fallback(image, (_x, _y), text, fill=fill_color, font=font, anchor=anchor)


def compress_to_webp(image_path: Path, quality: int = 80, delete_original: bool = False) -> tuple[bool, Path]:
    try:
        from PIL import Image

        # 确保文件存在
        if not image_path.exists():
            logger.warning(f"[鸣潮·图像] 图片不存在: {image_path}")
            return False, image_path

        # 检查文件是否已经是webp格式
        if image_path.suffix.lower() == ".webp":
            logger.info(f"[鸣潮·图像] 图片已经是webp格式: {image_path}")
            return False, image_path

        # 创建webp文件路径
        webp_path = image_path.with_suffix(".webp")

        # 打开图片
        img = Image.open(image_path)

        # 记录原始大小
        orig_size = image_path.stat().st_size

        # 保存为webp格式
        img.save(webp_path, "WEBP", quality=quality, method=6)

        # 计算压缩率
        webp_size = webp_path.stat().st_size
        compression_ratio = (1 - webp_size / orig_size) * 100 if orig_size > 0 else 0
        logger.info(f"[鸣潮·图像] 图片 {image_path.name} 压缩为webp格式, 压缩率: {compression_ratio:.2f}%")

        # 删除原图片（如果需要）
        if delete_original:
            image_path.unlink()
            logger.info(f"[鸣潮·图像] 原图片已删除: {image_path}")

        return True, webp_path

    except Exception as e:
        logger.error(f"[鸣潮·图像] 压缩图片为webp格式失败: {e}")
        return False, image_path


async def draw_avatar_with_star(
    avatar: Image.Image,
    star_level: int = 5,
    need_text: bool = True,
    img_color: float | tuple[float, ...] | str | None = (0, 0, 0, 255),
    item_width: int = 144,
    item_height: int = 170,
) -> Image.Image:
    if need_text:
        img = Image.new("RGBA", (item_width, item_height), img_color)
    else:
        img = Image.new("RGBA", (item_width, item_width), img_color)

    # 144*144
    star_bg = Image.open(TEXT_PATH / f"star_{star_level}.png")
    avatar = avatar.resize((item_width, item_width))

    img.alpha_composite(avatar, (0, 0))
    img.alpha_composite(star_bg, (0, 0))
    return img


async def get_star_bg(star_level: int = 5) -> Image.Image:
    return Image.open(TEXT_PATH / f"star_{star_level}.png")


async def pic_download_from_url(
    path: Path,
    pic_url: str,
) -> Image.Image:
    path.mkdir(parents=True, exist_ok=True)

    name = pic_url.split("/")[-1]
    _path = path / name
    webp_path = _path.with_suffix(".webp")

    if webp_path.exists():
        return Image.open(webp_path).convert("RGBA")

    if not _path.exists():
        from gsuid_core.utils.download_resource.download_file import download

        await download(pic_url, path, name, tag="[鸣潮]")

    try:
        img = Image.open(_path).convert("RGBA")
    except Exception as e:
        logger.warning(f"[鸣潮·图像] 打开图片失败: {_path}, {e}")
        raise

    if _path != webp_path:
        try:
            img.save(webp_path, "WEBP", quality=85)
            _path.unlink(missing_ok=True)
            logger.debug(f"[鸣潮·图像] 已将图片转为webp: {webp_path.name}")
        except Exception as e:
            logger.warning(f"[鸣潮·图像] 转换webp失败: {e}")

    return img


async def get_custom_gaussian_blur(img: Image.Image) -> Image.Image:
    return _get_custom_gaussian_blur(img)


def _get_custom_gaussian_blur(img: Image.Image) -> Image.Image:
    from ..wutheringwaves_config.wutheringwaves_config import ShowConfig

    radius = ShowConfig.get_config("BlurRadius").data
    if radius > 0:
        # 应用高斯模糊
        img = img.filter(ImageFilter.GaussianBlur(radius=radius))
        # 调整亮度和对比度
        brightness = ShowConfig.get_config("BlurBrightness").data
        try:
            brightness = float(brightness)
        except Exception:
            brightness = 1
        contrast = ShowConfig.get_config("BlurContrast").data
        try:
            contrast = float(contrast)
        except Exception:
            contrast = 1

        img = ImageEnhance.Brightness(img).enhance(brightness)
        # 调整对比度
        img = ImageEnhance.Contrast(img).enhance(contrast)
    return img
