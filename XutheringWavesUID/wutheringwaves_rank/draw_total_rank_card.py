import time
import asyncio
from typing import Dict, Union, Optional
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.pool import to_thread
from gsuid_core.utils.image.convert import convert_img

from .rank_avatar import get_avatar
from .rank_badge import draw_bot_name_badge, draw_rank_badge
from .pagination import RANK_PAGE_SIZE
from ..utils.util import get_version, hide_uid
from ..utils.image import (
    RED,
    GREY,
    SPECIAL_GOLD,
    get_ICON,
    add_footer,
    get_square_avatar,
    get_custom_waves_bg,
)
from ..utils.api.wwapi import (
    GET_TOTAL_RANK_URL,
    TotalRankRequest,
    TotalRankResponse,
)
from ..utils.database.models import WavesBind
from ..wutheringwaves_config import WutheringWavesConfig
from ..utils.resource.constant import randomize_special_char_id
from ..utils.fonts.waves_fonts import (
    fit_text,
    waves_font_12,
    waves_font_14,
    waves_font_16,
    waves_font_18,
    waves_font_20,
    waves_font_28,
    waves_font_30,
    waves_font_34,
    waves_font_58,
)

TEXT_PATH = Path(__file__).parent / "texture2d"
char_mask = Image.open(TEXT_PATH / "char_mask.png")


async def get_rank(item: TotalRankRequest) -> Optional[TotalRankResponse]:
    WavesToken = WutheringWavesConfig.get_config("WavesToken").data

    if not WavesToken:
        return

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                GET_TOTAL_RANK_URL,
                json=item.model_dump(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {WavesToken}",
                },
                timeout=httpx.Timeout(10),
            )
            if res.status_code == 200:
                return TotalRankResponse.model_validate(res.json())
            else:
                logger.warning(f"[鸣潮·练度排行] 获取远端排行失败: {res.status_code} - {res.text}")
        except Exception as e:
            logger.exception(f"[鸣潮·练度排行] 获取远端排行失败: {e}")


async def draw_total_rank(bot: Bot, ev: Event, pages: int) -> Union[str, bytes]:
    page_num = RANK_PAGE_SIZE
    self_uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not self_uid:
        self_uid = ""
    item = TotalRankRequest(
        page=pages,
        page_num=page_num,
        waves_id=self_uid,
        version=get_version(dynamic=True, waves_id=self_uid, pages=pages),
    )

    rankInfoList = await get_rank(item)
    if not rankInfoList:
        return "获取练度总排行失败"

    if rankInfoList.message and not rankInfoList.data:
        return rankInfoList.message

    if not rankInfoList.data or not rankInfoList.data.score_details:
        return "暂无排行数据"

    # 设置图像尺寸
    width = 1300
    text_bar_height = 130
    item_spacing = 120
    header_height = 510
    footer_height = 50
    char_list_len = len(rankInfoList.data.score_details)

    # 计算所需的总高度
    total_height = header_height + text_bar_height + item_spacing * char_list_len + footer_height

    # 创建带背景的画布 - 使用bg9
    card_img = get_custom_waves_bg(width, total_height, "bg9")

    text_bar_img = Image.new("RGBA", (width, 130), color=(0, 0, 0, 0))
    text_bar_draw = ImageDraw.Draw(text_bar_img)
    # 绘制深灰色背景
    bar_bg_color = (36, 36, 41, 230)
    text_bar_draw.rounded_rectangle([20, 20, width - 40, 110], radius=8, fill=bar_bg_color)

    # 绘制顶部的金色高亮线
    accent_color = (203, 161, 95)
    text_bar_draw.rectangle([20, 20, width - 40, 26], fill=accent_color)

    # 左侧标题
    text_bar_draw.text((40, 60), "排行说明", GREY, waves_font_28, "lm")
    text_bar_draw.text(
        (185, 50),
        "1. 综合所有角色的声骸分数。具备声骸套装的角色，全量刷新面板后更新排行位置。",
        SPECIAL_GOLD,
        waves_font_20,
        "lm",
    )
    text_bar_draw.text((185, 85), "2. 显示前10个最强角色，刷新单角色影响此处显示但不计入总分。", SPECIAL_GOLD, waves_font_20, "lm")

    # 备注
    temp_notes = "排行标准：以所有角色评分（分数>=175）总和为排序的综合排名"
    text_bar_draw.text((1260, 100), temp_notes, SPECIAL_GOLD, waves_font_16, "rm")

    card_img.alpha_composite(text_bar_img, (0, header_height))

    # 导入必要的图片资源
    bar = Image.open(TEXT_PATH / "bar1.png")

    # 获取头像
    details = rankInfoList.data.score_details
    tasks = [get_avatar(detail.user_id, getattr(detail, "sender_avatar", "")) for detail in details]
    results = await asyncio.gather(*tasks)

    # 预取所有角色头像（按 detail 顺序 → top10 sorted）
    char_avatar_map: Dict[int, Image.Image] = {}
    char_ids_to_fetch = set()
    for detail in details:
        if detail.char_score_details:
            sorted_chars = sorted(detail.char_score_details, key=lambda x: x.phantom_score, reverse=True)[:10]
            for c in sorted_chars:
                char_ids_to_fetch.add(randomize_special_char_id(c.char_id))
    if char_ids_to_fetch:
        fetched = await asyncio.gather(*[get_square_avatar(cid) for cid in char_ids_to_fetch])
        char_avatar_map = dict(zip(char_ids_to_fetch, fetched))

    card_img = await _compose_total_rank(
        card_img, bar, details, results, char_avatar_map,
        self_uid, header_height, item_spacing, width,
    )
    return await convert_img(card_img)


@to_thread
def _compose_total_rank(card_img, bar, details, results, char_avatar_map,
                        self_uid, header_height, item_spacing, width):
    for rank_temp_index, temp in enumerate(zip(details, results)):
        detail, role_avatar = temp
        y_pos = header_height + 130 + rank_temp_index * item_spacing

        bar_bg = bar.copy()
        bar_bg.paste(role_avatar, (100, 0), role_avatar)
        bar_draw = ImageDraw.Draw(bar_bg)

        rank_id = detail.rank
        draw_rank_badge(bar_bg, rank_id)

        name_font, name_text = fit_text(
            bar_draw,
            str(detail.kuro_name),
            130,
            (waves_font_20, waves_font_18, waves_font_16, waves_font_14, waves_font_12),
        )
        bar_draw.text((210, 75), name_text, "white", name_font, "lm")

        char_count = len(detail.char_score_details) if detail.char_score_details else 0
        bar_draw.text((210, 45), "角色数:", (255, 255, 255), waves_font_18, "lm")
        bar_draw.text((280, 45), f"{char_count}", RED, waves_font_20, "lm")

        uid_color = "white"
        if detail.waves_id == self_uid:
            uid_color = RED
        bar_draw.text((350, 40), f"特征码: {hide_uid(detail.waves_id, user_pref='on' if detail.hide_uid else '')}", uid_color, waves_font_20, "lm")

        botName = getattr(detail, "alias_name", None)
        if botName:
            draw_bot_name_badge(bar_bg, getattr(detail, "background", ""), botName, (346, 61))

        bar_draw.text(
            (1180, 45),
            f"{detail.total_score:.1f}",
            (255, 255, 255),
            waves_font_34,
            "mm",
        )
        bar_draw.text((1180, 75), "总分", "white", waves_font_16, "mm")

        if detail.char_score_details:
            sorted_chars = sorted(detail.char_score_details, key=lambda x: x.phantom_score, reverse=True)[:10]

            char_size = 40
            char_spacing = 45
            char_start_x = 570
            char_start_y = 35

            char_mask_img = Image.open(TEXT_PATH / "char_mask.png")
            char_mask_resized = char_mask_img.resize((char_size, char_size))
            for i, char in enumerate(sorted_chars):
                char_x = char_start_x + i * char_spacing

                display_char_id = randomize_special_char_id(char.char_id)
                char_avatar = char_avatar_map.get(display_char_id)
                if char_avatar is None:
                    continue
                char_avatar = char_avatar.resize((char_size, char_size))

                char_avatar_masked = Image.new("RGBA", (char_size, char_size))
                char_avatar_masked.paste(char_avatar, (0, 0), char_mask_resized)

                bar_bg.paste(char_avatar_masked, (char_x, char_start_y), char_avatar_masked)

                score_text = f"{int(char.phantom_score)}"
                bar_draw.text(
                    (char_x + char_size // 2, char_start_y + char_size + 2),
                    score_text,
                    SPECIAL_GOLD,
                    waves_font_12,
                    "mm",
                )

            if sorted_chars:
                best_score = f"{int(sorted_chars[0].phantom_score)} "
                bar_draw.text((1080, 45), best_score, "lightgreen", waves_font_30, "mm")
                bar_draw.text((1080, 75), "最高分", "white", waves_font_16, "mm")

        card_img.paste(bar_bg, (0, y_pos), bar_bg)

    title_bg = Image.open(TEXT_PATH / "totalrank.jpg")
    title_bg = title_bg.crop((0, 0, width, 500))

    icon = get_ICON()
    icon = icon.resize((128, 128))
    title_bg.paste(icon, (60, 240), icon)

    title_text = "#练度总排行"
    title_bg_draw = ImageDraw.Draw(title_bg)
    title_bg_draw.text((220, 290), title_text, "white", waves_font_58, "lm")
    time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    title_bg_draw.text((225, 360), time_str, GREY, waves_font_20, "lm")

    char_mask = Image.open(TEXT_PATH / "char_mask.png").convert("RGBA")
    char_mask = char_mask.resize((width, char_mask.height * width // char_mask.width))
    char_mask = char_mask.crop((0, char_mask.height - 500, width, char_mask.height))
    char_mask_temp = Image.new("RGBA", char_mask.size, (0, 0, 0, 0))
    char_mask_temp.paste(title_bg, (0, 0), char_mask)

    card_img.paste(char_mask_temp, (0, 0), char_mask_temp)

    card_img = add_footer(card_img)
    return card_img
