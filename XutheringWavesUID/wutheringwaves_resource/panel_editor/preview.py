"""面板/MR 预览渲染。

- 面板: 复用 draw_char_detail_img(is_limit_query=True, fallback_to_generic=True)。
- MR: 用固定样本 DailyData/AccountBaseInfo 直接调用 stamina 渲染函数。
- _force_pile_path 注入选中图。
"""

from __future__ import annotations

import time
from io import BytesIO
from pathlib import Path
from typing import Literal, Optional, Tuple

from PIL import Image

from gsuid_core.logger import logger
from gsuid_core.models import Event

from ...utils.image import _force_pile_path
from ...utils.name_convert import easy_id_to_name
from ...utils.pile_offset import RankOffset, clamp_offset, place_rank_pile, read_rank_offset


def _pil_to_jpeg_bytes(im: Image.Image, quality: int = 90) -> bytes:
    buf = BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


PREVIEW_USER_ID = "0"
PREVIEW_BOT_ID = "panel_edit"


def make_synthetic_event() -> Event:
    """构造预览用的 Event, 让深层调用拿默认头像/语言。"""
    ev = Event(
        bot_id=PREVIEW_BOT_ID,
        user_id=PREVIEW_USER_ID,
        user_type="direct",
        sender={},
    )
    ev.raw_text = ""
    ev.text = ""
    return ev


def _build_sample_daily_dict(role_id: str = "100000001", role_name: str = "漂泊者"):
    """生成稳定的 sample DailyData 字典 (字段对齐 model/daily.py)。"""
    now = int(time.time())
    return {
        "gameId": 3,
        "userId": 0,
        "serverId": "76402e5b20be2c39f095a152090afddc",
        "roleId": role_id,
        "roleName": role_name,
        "signInTxt": "已签到",
        "hasSignIn": True,
        "energyData": {
            "name": "结晶波片",
            "img": "",
            "refreshTimeStamp": now + 3600 * 8,
            "cur": 180,
            "total": 240,
        },
        "livenessData": {
            "name": "活跃度",
            "img": "",
            "cur": 80,
            "total": 100,
        },
        "battlePassData": [
            {"name": "电台", "cur": 12, "total": 70},
        ],
        "storeEnergyData": {
            "name": "结晶单质",
            "cur": 200,
            "total": 480,
            "refreshTimeStamp": now + 3600 * 8,
        },
        "weeklyData": {
            "name": "周本",
            "cur": 0,
            "total": 3,
            "refreshTimeStamp": now + 3600 * 24,
        },
        "weeklyRougeData": {
            "name": "千道门扉的异想",
            "cur": 0,
            "total": 1500,
            "refreshTimeStamp": now + 3600 * 24,
        },
    }


def _build_sample_account_dict(role_id: str = "100000001", role_name: str = "漂泊者"):
    return {
        "name": role_name,
        "id": int(role_id) if role_id.isdigit() else 100000001,
        "creatTime": int(time.time()) - 86400 * 365,
        "activeDays": 365,
        "level": 90,
        "worldLevel": 10,
        "roleNum": 30,
        "bigCount": 100,
        "smallCount": 200,
        "achievementCount": 500,
        "achievementStar": 1500,
        "weeklyInstCount": 0,
        "weeklyInstCountLimit": 3,
        "storeEnergy": 200,
        "storeEnergyLimit": 480,
        "rougeScore": 1500,
        "rougeScoreLimit": 1500,
    }


async def render_panel_preview(char_id: str, image_path: Path) -> Optional[bytes]:
    """渲染角色面板预览, 返回 jpg/png 字节流。"""
    from ...wutheringwaves_charinfo.draw_char_card import draw_char_detail_img

    char_name = easy_id_to_name(char_id, "")
    if not char_name:
        return None

    ev = make_synthetic_event()
    token = _force_pile_path.set(image_path)
    try:
        result = await draw_char_detail_img(
            ev, "1", char_name, PREVIEW_USER_ID,
            is_limit_query=True, fallback_to_generic=True,
        )
    finally:
        _force_pile_path.reset(token)

    if isinstance(result, (bytes, bytearray)):
        return bytes(result)
    if isinstance(result, Image.Image):
        return _pil_to_jpeg_bytes(result)
    if isinstance(result, str):
        logger.info(f"[鸣潮·面板编辑] 面板预览失败: {result}")
        return None
    return None


# 排行 title 画布与立绘默认贴图位, 与 draw_rank_card 一致; 前端 app.js RANK_CANVAS / RANK_PASTE 同值。
RANK_CANVAS = (1050, 540)
RANK_PILE_PASTE = (450, -120)


def _rank_char_name(char_id: str) -> str:
    from ...utils.resource.constant import SPECIAL_CHAR_NAME
    return SPECIAL_CHAR_NAME.get(char_id) or easy_id_to_name(char_id, "漂泊者")


def _rank_bg() -> Image.Image:
    from ...utils.image import get_custom_waves_bg
    return get_custom_waves_bg(*RANK_CANVAS, "bg3")


def _rank_base() -> Image.Image:
    from ...wutheringwaves_rank.draw_rank_card import TITLE_I, logo_img
    title = TITLE_I.copy()
    title.alpha_composite(logo_img.copy(), dest=(50, 65))
    return title


def _rank_mask() -> Image.Image:
    from ...wutheringwaves_rank.draw_rank_card import char_mask
    return char_mask


def _draw_rank_text(title: Image.Image, char_name: str) -> None:
    from PIL import ImageDraw
    from ...utils.image import GREY, SPECIAL_GOLD
    from ...utils.fonts.waves_fonts import (
        waves_font_16,
        waves_font_20,
        waves_font_30,
        waves_font_44,
    )

    d = ImageDraw.Draw(title)
    d.text((200, 335), "12345", "white", waves_font_44, "mm")
    d.text((200, 375), "平均声骸分数", SPECIAL_GOLD, waves_font_20, "mm")
    d.text((390, 335), "678,910", "white", waves_font_44, "mm")
    d.text((390, 375), "平均伤害", SPECIAL_GOLD, waves_font_20, "mm")
    d.text((140, 265), f"{char_name}伤害群排行", "black", waves_font_30, "lm")
    d.text((20, 420), "入榜条件", SPECIAL_GOLD, waves_font_16, "lm")
    d.text((90, 420), "（预览, 实际数据按群内查询）", GREY, waves_font_16, "lm")


def _png_bytes(im: Image.Image) -> bytes:
    buf = BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


async def render_rank_preview(
    char_id: str, image_path: Path, offset: Optional[RankOffset] = None,
) -> Optional[bytes]:
    """渲染角色排行 title 区域的立绘合成预览 (1050x500)。offset 缺省读图片同名 sidecar。"""
    from ...utils.image import get_role_pile_default

    token = _force_pile_path.set(image_path)
    try:
        pile, _ = await get_role_pile_default(char_id, custom=True)
    finally:
        _force_pile_path.reset(token)

    off = clamp_offset(*offset) if offset is not None else read_rank_offset(image_path)
    card_img = _rank_bg()
    title = _rank_base()
    pile, pos = place_rank_pile(pile, RANK_PILE_PASTE, off)
    title.paste(pile, pos, pile)
    _draw_rank_text(title, _rank_char_name(char_id))

    mask = _rank_mask()
    img_temp = Image.new("RGBA", mask.size)
    img_temp.paste(title, (0, 0), mask.copy())
    card_img.alpha_composite(img_temp, (0, 0))
    return _pil_to_jpeg_bytes(card_img)


def rank_layer_bytes(kind: str, char_id: str = "", pile_path: Optional[Path] = None) -> Tuple[bytes, str]:
    """前端 canvas 拼排行预览的分层素材 → (bytes, media_type)。
    bg: 背景 jpg; base: title+logo png; mask: 仅 alpha 的 png (char_mask 的 A 通道, 供 destination-in);
    text: 透明底文字 png; pile: 原尺寸带 alpha 的 webp。
    """
    if kind == "bg":
        return _pil_to_jpeg_bytes(_rank_bg(), quality=85), "image/jpeg"
    if kind == "base":
        return _png_bytes(_rank_base()), "image/png"
    if kind == "mask":
        src = _rank_mask()
        mask = Image.new("RGBA", src.size, (0, 0, 0, 0))
        mask.putalpha(src.getchannel("A") if "A" in src.getbands() else src.convert("L"))
        return _png_bytes(mask), "image/png"
    if kind == "text":
        text = Image.new("RGBA", _rank_mask().size, (0, 0, 0, 0))
        _draw_rank_text(text, _rank_char_name(char_id))
        return _png_bytes(text), "image/png"
    if kind == "pile" and pile_path is not None:
        with Image.open(pile_path) as im:
            pile = im.convert("RGBA")
        buf = BytesIO()
        pile.save(buf, "WEBP", quality=85, method=4)
        return buf.getvalue(), "image/webp"
    raise ValueError(f"unknown layer {kind!r}")


async def render_mr_preview(
    char_id: str,
    image_path: Path,
    *,
    use_html: bool = True,
    role_kind: Literal["bg", "stamina"] = "bg",
) -> Optional[bytes]:
    """渲染 mr 预览。

    role_kind=bg → 选中的是背景图, has_bg=True 让 stamina 渲染走"全图背景"分支;
    role_kind=stamina → 选中的是立绘, 走默认 letterbox 分支。
    use_html: True 走 HTML, 失败回退 PIL。
    """
    from ...utils.image import get_event_avatar
    from ...wutheringwaves_stamina.draw_waves_stamina import (
        _render_stamina_card,
        _render_stamina_card_pil,
        draw_pic_with_ring,
        TEXT_PATH as STAMINA_TEXT_PATH,
        YES,
        NO,
    )
    from ...utils.api.model import AccountBaseInfo, DailyData

    char_name = easy_id_to_name(char_id, "漂泊者")
    role_id = char_id if char_id.isdigit() else "100000001"

    daily_info = DailyData.model_validate(_build_sample_daily_dict(role_id, char_name))
    account_info = AccountBaseInfo.model_validate(_build_sample_account_dict(role_id, char_name))

    try:
        pile = Image.open(image_path).convert("RGBA")
    except Exception as e:
        logger.warning(f"[鸣潮·面板编辑] 读取 MR 图失败 {image_path}: {e}")
        return None

    ev = make_synthetic_event()
    has_bg = role_kind == "bg"
    sing_in_text = "签到已完成！"
    active_text = "活跃度未满！"

    # 预览的目标本身就是自定义图, 计算 hash 让用户看到将来命中时的标记
    from ...wutheringwaves_charinfo.card_hash_index import compute_hash
    pile_hash = compute_hash(image_path.name)

    if use_html:
        try:
            img = await _render_stamina_card(
                ev=ev, pile=pile, has_bg=has_bg,
                daily_info=daily_info, account_info=account_info,
                sign_in_status=daily_info.hasSignIn, sign_in_text=sing_in_text,
                active_status=False, active_text=active_text,
                avatar=await get_event_avatar(ev), locale="", from_sdk=False,
                pile_hash=pile_hash,
            )
        except Exception as e:
            logger.exception(f"[鸣潮·面板编辑] HTML MR 预览失败: {e}")
            img = None
        if isinstance(img, Image.Image):
            return _pil_to_jpeg_bytes(img)
        if isinstance(img, (bytes, bytearray)):
            return bytes(img)
        logger.info("[鸣潮·面板编辑] HTML 预览失败, 回退 PIL")

    result_img = await _render_stamina_card_pil(
        img=Image.open(STAMINA_TEXT_PATH / "bg.jpg").convert("RGBA"),
        info=Image.open(STAMINA_TEXT_PATH / "main_bar.png").convert("RGBA"),
        base_info_bg=Image.open(STAMINA_TEXT_PATH / "base_info_bg.png"),
        avatar_ring=Image.open(STAMINA_TEXT_PATH / "avatar_ring.png"),
        avatar=await draw_pic_with_ring(ev),
        pile=pile, has_bg=has_bg,
        daily_info=daily_info, account_info=account_info,
        sign_in_icon=YES, sing_in_text=sing_in_text,
        active_icon=NO, active_text=active_text,
        locale="",
        pile_hash=pile_hash,
    )
    return _pil_to_jpeg_bytes(result_img)
