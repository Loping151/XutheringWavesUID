from typing import Union
from pathlib import Path

from PIL import Image, ImageDraw

from gsuid_core.logger import logger
from gsuid_core.utils.download_resource.download_file import download

from ..name_convert import easy_id_to_name
from .RESOURCE_PATH import (
    PHANTOM_PATH,
    MATERIAL_PATH,
    MATERIAL_ICON_PATH,
    ROLE_DETAIL_SKILL_PATH,
    ROLE_DETAIL_CHAINS_PATH,
)
from ..fonts.waves_fonts import (
    fit_text,
    waves_font_28,
    waves_font_32,
    waves_font_40,
    waves_font_50,
    waves_font_60,
)


def _open_img(_path: Path) -> Image.Image:
    try:
        return Image.open(_path).convert("RGBA")
    except Exception as e:
        if _path.exists():
            logger.warning(f"[鸣潮·资源下载] 图片损坏，已删除: {_path}, {e}")
            _path.unlink(missing_ok=True)
        raise


async def get_skill_img(char_id: Union[str, int], skill_name: str, pic_url: str) -> Image.Image:
    _dir = ROLE_DETAIL_SKILL_PATH / str(char_id)
    _dir.mkdir(parents=True, exist_ok=True)

    skill_name = skill_name.strip()
    name = f"skill_{skill_name}.png"
    _path = _dir / name
    if not _path.exists():
        if pic_url:
            await download(pic_url, _dir, name, tag="[鸣潮]")
        else:
            # logger.warning(f"[鸣潮·资源下载] 角色 {char_id} 的技能图片不存在，使用默认图片")
            _path = ROLE_DETAIL_SKILL_PATH / "1503" / "skill_星星花绽放.png"

    return _open_img(_path)


async def get_chain_img(char_id: Union[str, int], order_id: int, pic_url: str) -> Image.Image:
    _dir = ROLE_DETAIL_CHAINS_PATH / str(char_id)
    _dir.mkdir(parents=True, exist_ok=True)

    name = f"chain_{order_id}.png"
    _path = _dir / name
    if not _path.exists():
        if pic_url:
            await download(pic_url, _dir, name, tag="[鸣潮]")
        else:
            # logger.warning(f"[鸣潮·资源下载] 角色 {char_id} 的共鸣链图片不存在，使用默认图片")
            _path = ROLE_DETAIL_CHAINS_PATH / "1503" / f"chain_{order_id}.png"

    return _open_img(_path)


async def get_phantom_img(phantom_id: int, pic_url: str) -> Image.Image:
    name = f"phantom_{phantom_id}.png"
    _path = PHANTOM_PATH / name
    if not _path.exists():
        if pic_url:
            await download(pic_url, PHANTOM_PATH, name, tag="[鸣潮]")
        else:
            _path = PHANTOM_PATH / "phantom_390070051.png"

    return _open_img(_path)


def _draw_material_name(material_id: str) -> Image.Image:
    img = Image.new("RGBA", (256, 256))
    draw = ImageDraw.Draw(img)
    font, text = fit_text(
        draw,
        easy_id_to_name(material_id, material_id),
        232,
        (waves_font_60, waves_font_50, waves_font_40, waves_font_32, waves_font_28),
    )
    draw.text(
        (128, 128),
        text,
        fill=(255, 255, 255, 255),
        font=font,
        anchor="mm",
        stroke_width=3,
        stroke_fill=(0, 0, 0, 255),
    )
    return img


async def get_material_img(material_id: Union[str, int], pic_url: str = "") -> Image.Image:
    name = f"material_{material_id}.png"
    _path = MATERIAL_ICON_PATH / name
    if not _path.exists() and pic_url:
        await download(pic_url, MATERIAL_ICON_PATH, name, tag="[鸣潮]")
    for _path in (_path, MATERIAL_PATH / name):
        if not _path.exists():
            continue
        try:
            return _open_img(_path)
        except Exception:
            continue
    logger.warning(f"[鸣潮·资源下载] 素材图 {name} 不存在，使用文字代替")
    return _draw_material_name(str(material_id))
