import asyncio
import re
from io import BytesIO
from base64 import b64encode
from pathlib import Path

from PIL import Image
from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event

from ..utils.name_convert import alias_to_char_name_optional
from ..utils.resource.RESOURCE_PATH import GUIDE_PATH
from ..wutheringwaves_config.wutheringwaves_config import WutheringWavesConfig

guide_map = {
    "社区攻略": "KuroBBS",
    "金铃子攻略组": "JinLingZi",
    "丸子": "VanZi",
    "Moealkyne": "Moealkyne",
    "小沐XMu": "XMu",
    "小羊早睡不遭罪": "XiaoYang",
    "吃我无痕": "WuHen",
    "巡游天国FM": "XFM",
    "猫眼石攻略组": "Chrysoberyl",
}

guide_author_map = {v: k for k, v in guide_map.items()}


async def get_guide(bot: Bot, ev: Event, char_name: str):
    is_dps = char_name.lower() == "dps"
    if not is_dps:
        char_name = alias_to_char_name_optional(char_name)
        if not char_name:
            msg = "[鸣潮] 未找到指定角色, 请检查输入是否正确！"
            return await bot.send(msg)

    logger.info(f"[鸣潮·百科攻略] 开始获取{char_name}图鉴")

    config = WutheringWavesConfig.get_config("WavesGuide").data

    # 获取群组排除的攻略提供方
    excluded_providers = []
    if ev.group_id:
        from ..wutheringwaves_config.guide_config import get_excluded_providers

        excluded_providers = get_excluded_providers(ev.group_id)

    imgs_result = []
    pattern = re.compile(rf"^{re.escape(char_name)}(?:-\d+)?\.[^.]+$", re.IGNORECASE)
    if "all" in config:
        paths = sorted(
            GUIDE_PATH.iterdir(),
            key=lambda p: (p.name != "KuroBBS", p.name),
        )
        for guide_path in paths:
            # 检查是否被排除
            author_name = guide_author_map.get(guide_path.name, guide_path.name)
            if author_name in excluded_providers or any(excluded in author_name for excluded in excluded_providers):
                continue

            imgs = await get_guide_pic(
                guide_path,
                pattern,
                author_name,
            )
            if len(imgs) == 0:
                continue
            imgs_result.extend(imgs)
    else:
        for guide_name in config:
            if guide_name in excluded_providers:
                continue

            if guide_name in guide_map:
                guide_path = GUIDE_PATH / guide_map[guide_name]
            else:
                guide_path = GUIDE_PATH / guide_name

            author_name = guide_author_map.get(guide_path.name, guide_path.name)
            if author_name in excluded_providers or any(excluded in author_name for excluded in excluded_providers):
                continue

            imgs = await get_guide_pic(
                guide_path,
                pattern,
                author_name,
            )
            if len(imgs) == 0:
                continue
            imgs_result.extend(imgs)

    if len(imgs_result) == 0:
        msg = f"[鸣潮]【{char_name}】暂无攻略！"
        return await bot.send(msg)

    await send_guide(config, imgs_result, bot)


def _guide_sort_key(p: Path):
    # 多图攻略: 基图(角色名.jpg)在前, 角色名-1/-2/...按序号升序跟在后面
    m = re.fullmatch(r"(.+?)-(\d+)", p.stem)
    if m:
        return (m.group(1), 1, int(m.group(2)))
    return (p.stem, 0, 0)


async def get_guide_pic(guide_path: Path, pattern: re.Pattern, guide_author: str):
    imgs = []
    if not guide_path.is_dir():
        logger.warning(f"[鸣潮·百科攻略] 攻略路径错误 {guide_path}")
        return imgs

    if not guide_path.exists():
        logger.warning(f"[鸣潮·百科攻略] 攻略路径不存在 {guide_path}")
        return imgs

    files = sorted(
        (f for f in guide_path.iterdir() if pattern.search(f.name)),
        key=_guide_sort_key,
    )
    for file in files:
        imgs.extend(await process_images_new(file))

    if len(imgs) > 0:
        imgs.insert(0, f"攻略作者：{guide_author}")

    return imgs


JPG_MAX_DIMENSION = 65535


def resize_for_jpg(img: Image.Image) -> Image.Image:
    """
    如果图片尺寸超过JPG限制(65535像素)，按比例缩放
    """
    width, height = img.size
    if width <= JPG_MAX_DIMENSION and height <= JPG_MAX_DIMENSION:
        return img

    scale = min(JPG_MAX_DIMENSION / width, JPG_MAX_DIMENSION / height)
    new_width = int(width * scale)
    new_height = int(height * scale)
    logger.info(f"[鸣潮·百科攻略] 攻略图尺寸{width}x{height}超过JPG限制，缩放至{new_width}x{new_height}")
    return img.resize((new_width, new_height), Image.Resampling.LANCZOS)


def compress_image_to_jpg(img: Image.Image, max_size_mb: int) -> bytes:
    """
    将图片转为JPG格式，若超过max_size_mb则逐步降低质量压缩
    """
    max_size_bytes = max_size_mb * 1024 * 1024

    # 检查并缩放超大图片
    img = resize_for_jpg(img)

    # 先尝试95%质量
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=95)
    result = buffer.getvalue()

    if len(result) <= max_size_bytes:
        return result

    # 超过大小限制，逐步降低质量
    for quality in range(90, 10, -5):
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        result = buffer.getvalue()
        if len(result) <= max_size_bytes:
            logger.info(f"[鸣潮·百科攻略] 攻略图压缩至quality={quality}, 大小={len(result)/1024/1024:.2f}MB")
            return result

    # 如果降到quality=10仍然超过，返回最后的结果
    logger.warning(f"[鸣潮·百科攻略] 攻略图压缩至最低质量仍超过{max_size_mb}MB, 当前大小={len(result)/1024/1024:.2f}MB")
    return result


def _open_and_compress(path: Path, max_size_mb: int) -> bytes:
    img = Image.open(path)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    return compress_image_to_jpg(img, max_size_mb)


async def process_images_new(_dir: Path):
    imgs = []
    try:
        max_size_mb = WutheringWavesConfig.get_config("WavesGuideMaxSize").data
        img_bytes = await asyncio.to_thread(_open_and_compress, _dir, max_size_mb)
        img_base64 = f"base64://{b64encode(img_bytes).decode()}"
        imgs.append(img_base64)
    except Exception as e:
        logger.warning(f"[鸣潮·百科攻略] 攻略图片读取失败 {_dir}: {e}")
    return imgs


async def send_guide(config, imgs: list, bot: Bot):
    # 处理发送逻辑
    if "all" in config:
        await bot.send(imgs)
    elif len(imgs) == 2:
        await bot.send(imgs[1])
    else:
        await bot.send(imgs)
