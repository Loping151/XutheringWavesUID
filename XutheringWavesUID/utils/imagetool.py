from pathlib import Path

from PIL import Image, ImageDraw

from gsuid_core.models import Event
from gsuid_core.utils.image.image_tools import crop_center_img

from .image import GOLD, get_event_avatar, get_square_avatar, paste_masked_avatar
from .fonts.waves_fonts import waves_font_25, waves_font_30

TEXT_PATH = Path(__file__).parent / "texture2d"


def draw_base_info_bg(name: str, uid_text: str, text_path: Path) -> Image.Image:
    """各 pil 通用顶部信息底图: 在 base_info_bg 上画名字 + 特征码, 返回图(由调用方自行 paste)。

    name: 已截断好的昵称; uid_text: 形如 "特征码:  1****8"(i18n/脱敏由调用方决定)。
    text_path: 调用模块的 texture2d 目录(各模块各有一份 base_info_bg.png)。

    不接本函数的特例(各自不同, 故意保留内联):
    - char_card: 名字走 draw_text_with_fallback(emoji) + i18n
    - stamina:   GREY 名字 / roleName / 特征码 i18n
    - matrix:    _load_texture 防御式加载 + alpha_composite
    """
    bg = Image.open(text_path / "base_info_bg.png")
    draw = ImageDraw.Draw(bg)
    draw.text((275, 120), name, "white", waves_font_30, "lm")
    draw.text((226, 173), uid_text, GOLD, waves_font_25, "lm")
    return bg


async def draw_pic_with_ring(ev: Event):
    pic = await get_event_avatar(ev)

    mask_pic = Image.open(TEXT_PATH / "avatar_mask.png")
    avatar = Image.new("RGBA", (180, 180))
    paste_masked_avatar(avatar, pic, mask_pic, 160, (20, 20))

    avatar_ring = Image.open(TEXT_PATH / "avatar_ring.png")
    avatar_ring = avatar_ring.resize((180, 180))
    return avatar, avatar_ring


async def draw_pic(roleId):
    pic = await get_square_avatar(roleId)
    mask_pic = Image.open(TEXT_PATH / "avatar_mask.png")
    img = Image.new("RGBA", (180, 180))
    mask = mask_pic.resize((140, 140))
    resize_pic = crop_center_img(pic, 140, 140)
    img.paste(resize_pic, (22, 18), mask)

    return img


def get_weapon_icon_bg(star: int, texture_path: Path) -> Image.Image:
    """按星级从调用模块的 texture2d 目录读取武器底图"""
    if star < 3:
        star = 3
    return Image.open(texture_path / f"weapon_icon_bg_{star}.png")
