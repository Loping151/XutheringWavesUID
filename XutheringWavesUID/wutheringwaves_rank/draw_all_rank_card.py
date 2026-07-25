import time
import asyncio
from typing import Union, Optional
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img

from .rank_avatar import get_avatar
from .rank_badge import draw_bot_name_badge, draw_rank_badge
from .pagination import (
    RANK_PAGE_SIZE,
    group_rank_empty_page_message,
    paginate_group_rank,
)
from ..utils.util import get_version, hide_uid, build_uid_masker
from ..utils.image import (
    RED,
    GREY,
    CHAIN_COLOR,
    SPECIAL_GOLD,
    WEAPON_RESONLEVEL_COLOR,
    add_footer,
    get_attribute,
    crop_center_img,
    get_square_weapon,
    get_sonata_label,
    get_custom_waves_bg,
    get_role_pile_default,
    get_sonata_effect_image,
)
from ..utils.api.wwapi import (
    GET_RANK_URL,
    GET_CARDS_RANK_URL,
    RankItem,
    RankDetail,
    RankInfoResponse,
    CardsRankRequest,
    CardsRankResponse,
)
from ..utils.waves_api import waves_api
from ..utils.name_convert import alias_to_char_name, char_name_to_char_id
from ..utils.ascension.char import get_char_model
from ..utils.database.models import WavesBind
from ..wutheringwaves_config import WutheringWavesConfig
from ..utils.damage.modal import get_modal_name, get_modal_options, get_role_modal, get_default_modal
from .draw_rank_card import find_role_detail
from ..utils.ascension.weapon import get_weapon_model
from ..utils.fonts.waves_fonts import (
    fit_text,
    waves_font_12,
    waves_font_14,
    waves_font_16,
    waves_font_18,
    waves_font_20,
    waves_font_24,
    waves_font_28,
    waves_font_30,
    waves_font_34,
    waves_font_40,
    waves_font_44,
)
from ..utils.resource.constant import ATTRIBUTE_ID_MAP, SPECIAL_CHAR_NAME
from ..utils.imagetool import get_weapon_icon_bg
from ..utils.score import get_panel_score_grade

TEXT_PATH = Path(__file__).parent / "texture2d"
TITLE_I = Image.open(TEXT_PATH / "title.png")
TITLE_II = Image.open(TEXT_PATH / "title2.png")
weapon_icon_bg_3 = Image.open(TEXT_PATH / "weapon_icon_bg_3.png")
weapon_icon_bg_4 = Image.open(TEXT_PATH / "weapon_icon_bg_4.png")
weapon_icon_bg_5 = Image.open(TEXT_PATH / "weapon_icon_bg_5.png")
promote_icon = Image.open(TEXT_PATH / "promote_icon.png")
char_mask = Image.open(TEXT_PATH / "char_mask.png")
char_mask2 = Image.open(TEXT_PATH / "char_mask.png")
char_mask2 = char_mask2.resize((1300, char_mask2.size[1]))
logo_img = Image.open(TEXT_PATH / "logo_small_2.png")


async def get_rank(item: RankItem) -> Optional[RankInfoResponse]:
    WavesToken = WutheringWavesConfig.get_config("WavesToken").data

    if not WavesToken:
        return

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                GET_RANK_URL,
                json=item.model_dump(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {WavesToken}",
                },
                timeout=httpx.Timeout(10),
            )
            if res.status_code == 200:
                return RankInfoResponse.model_validate(res.json())
            else:
                logger.warning(f"[鸣潮·练度排行] 获取远端排行失败: {res.status_code} - {res.text}")
        except Exception as e:
            logger.exception(f"[鸣潮·练度排行] 获取远端排行失败: {e}")


async def get_cards_rank(item: CardsRankRequest) -> Optional[CardsRankResponse]:
    WavesToken = WutheringWavesConfig.get_config("WavesToken").data
    if not WavesToken:
        return
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                GET_CARDS_RANK_URL,
                json=item.model_dump(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {WavesToken}",
                },
                timeout=httpx.Timeout(20),
            )
            if res.status_code == 200:
                return CardsRankResponse.model_validate(res.json())
            else:
                logger.warning(f"[鸣潮·练度排行] 获取群卡片排行失败: {res.status_code} - {res.text}")
        except Exception as e:
            logger.exception(f"[鸣潮·练度排行] 获取群卡片排行失败: {e}")


# TODO: PIL 卸到线程池 (loop 内 await get_attribute / get_attribute_effect / get_square_weapon 多处, 需要批量预取重构)
async def draw_all_rank_card(bot: Bot, ev: Event, char: str, rank_type: str, pages: int, modal: str = "", group_uids: Optional[list] = None) -> Union[str, bytes]:
    is_self_ck = False
    self_uid = ""
    try:
        self_uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
        is_self_ck, ck = await waves_api.get_ck_result(self_uid, ev.user_id, ev.bot_id)
    except Exception:
        pass
    char_id = char_name_to_char_id(char)
    if not char_id:
        return "未找到指定角色, 请检查输入是否正确！"
    char_name = alias_to_char_name(char)

    char_model = get_char_model(char_id)
    if not char_model:
        return f"[鸣潮] 角色名【{char_name}】暂未适配！\n"

    attribute_name = ATTRIBUTE_ID_MAP[char_model.attributeId]

    start_time = time.time()
    logger.info(f"[鸣潮·练度排行] get_rank_info_for_user start: {start_time}")

    rank_type_num = 3 if rank_type == "综合评分" else (2 if rank_type == "伤害" else 1)
    page_num = RANK_PAGE_SIZE
    if not modal:
        options = get_modal_options(int(char_id))
        if options:
            role = await find_role_detail(self_uid, char_id) if self_uid else None
            modal = get_role_modal(role) if role else get_default_modal(int(char_id))
    is_group = group_uids is not None
    if is_group:
        resp = await get_cards_rank(
            CardsRankRequest(
                char_id=int(char_id),
                rank_type=rank_type_num,
                modal=modal,
                waves_ids=[str(u) for u in group_uids if u],
            )
        )
        if not resp:
            return "获取群排行失败"
        if not resp.data or not resp.data.details:
            return "暂无排行数据"
        details = [d for d in resp.data.details if d.overall_score > 0]
        if not details:
            return "[鸣潮] 群内暂无该角色综合评分数据\n需【登录】并【刷新单角色面板】上传后才会上榜"
        details.sort(key=lambda d: d.overall_score, reverse=True)
        for i, d in enumerate(details):
            d.rank = i + 1
        self_entry = next((d for d in details if self_uid and d.waves_id == self_uid), None)
        self_rank = self_entry.rank if self_entry else None
        details, _, page_count, page_item_count = paginate_group_rank(
            details,
            pages,
            self_rank,
            self_entry,
        )
        if page_item_count == 0:
            return group_rank_empty_page_message(pages, page_count)
    else:
        item = RankItem(
            char_id=int(char_id),
            page=pages,
            page_num=page_num,
            rank_type=rank_type_num,
            waves_id=self_uid,
            version=get_version(dynamic=True, waves_id=self_uid, char_id=char_id, rank_type=rank_type, pages=pages),
            modal=modal,
        )
        rankInfoList = await get_rank(item)
        if not rankInfoList:
            return "获取排行失败"
        if rankInfoList.message and not rankInfoList.data:
            return rankInfoList.message
        if not rankInfoList.data or not rankInfoList.data.details:
            return "暂无排行数据"
        details = rankInfoList.data.details

    totalNum = len([rank for rank in details if rank.rank > 0])
    title_h = 500
    bar_star_h = 110
    modal_options = get_modal_options(int(char_id))
    text_bar_h = 170 if modal_options else 130
    h = title_h + totalNum * bar_star_h + text_bar_h + 80
    card_img = get_custom_waves_bg(1300, h, "bg3")

    text_bar_img = Image.new("RGBA", (1300, text_bar_h), color=(0, 0, 0, 0))
    text_bar_draw = ImageDraw.Draw(text_bar_img)
    # 绘制深灰色背景
    bar_bg_color = (36, 36, 41, 230)
    text_bar_draw.rounded_rectangle([20, 20, 1280, text_bar_h - 15], radius=8, fill=bar_bg_color)

    # 绘制顶部的金色高亮线
    accent_color = (203, 161, 95)
    text_bar_draw.rectangle([20, 20, 1280, 26], fill=accent_color)

    # 左侧标题
    text_bar_draw.text((40, 60), "上榜条件", GREY, waves_font_28, "lm")
    text_bar_draw.text((185, 50), "1. 声骸套装为常规套装", SPECIAL_GOLD, waves_font_20, "lm")
    cond2 = "2. 登录用户&刷新单角色面板" if rank_type == "综合评分" else "2. 登录用户&刷新面板"
    text_bar_draw.text((185, 85), cond2, SPECIAL_GOLD, waves_font_20, "lm")
    if modal_options:
        from ..wutheringwaves_config import PREFIX
        names = "/".join(o["name"] for o in modal_options)
        text_bar_draw.text((185, 120), f"支持模态: {PREFIX}{char}总排行 {names}", SPECIAL_GOLD, waves_font_20, "lm")
        current_modal_name = get_modal_name(int(char_id), modal)
        if current_modal_name:
            text_bar_draw.text((1260, 120), f"当前模态: {current_modal_name}", SPECIAL_GOLD, waves_font_20, "rm")

    # 备注
    if rank_type == "伤害":
        temp_notes = "排行标准：以期望伤害（计算暴击率的伤害，不代表实际伤害) 为排序的排名"
    elif rank_type == "综合评分":
        temp_notes = "综合评分为个性化标准，按各自配置估算得出，仅供参考，非公平对比。"
    else:
        temp_notes = "排行标准：以声骸分数（声骸评分高，不代表实际伤害高) 为排序的排名"
    text_bar_draw.text((1260, text_bar_h - 30), temp_notes, SPECIAL_GOLD, waves_font_16, "rm")

    card_img.alpha_composite(text_bar_img, (0, title_h))

    bar = Image.open(TEXT_PATH / "bar1.png")
    total_score = 0
    total_damage = 0

    tasks = [
        get_avatar(rank.user_id, getattr(rank, "sender_avatar", ""), char_id=rank.char_id)
        for rank in details
    ]
    results = await asyncio.gather(*tasks)

    _mask_uid = None
    if is_group:
        _mask_uid = await build_uid_masker([(d.waves_id, d.user_id) for d in details], ev.bot_id)

    avg_num = 0
    damage_name = ""
    valid_pairs = [(rank, avatar) for rank, avatar in zip(details, results) if rank.rank > 0]
    for index, temp in enumerate(valid_pairs):
        rank: RankDetail = temp[0]
        damage_name = rank.expected_name
        role_avatar: Image.Image = temp[1]
        bar_bg = bar.copy()
        bar_star_draw = ImageDraw.Draw(bar_bg)
        bar_bg.paste(role_avatar, (100, 0), role_avatar)

        role_attribute = await get_attribute(attribute_name, is_simple=True)
        role_attribute = role_attribute.resize((40, 40)).convert("RGBA")
        bar_bg.alpha_composite(role_attribute, (300, 20))

        # 命座
        info_block = Image.new("RGBA", (46, 20), color=(255, 255, 255, 0))
        info_block_draw = ImageDraw.Draw(info_block)
        fill = CHAIN_COLOR[rank.chain] + (int(0.9 * 255),)
        info_block_draw.rounded_rectangle([0, 0, 46, 20], radius=6, fill=fill)
        info_block_draw.text((5, 10), f"{get_chain_name(rank.chain)}", "white", waves_font_18, "lm")
        bar_bg.alpha_composite(info_block, (190, 30))

        # 等级
        info_block = Image.new("RGBA", (60, 20), color=(255, 255, 255, 0))
        info_block_draw = ImageDraw.Draw(info_block)
        info_block_draw.rounded_rectangle([0, 0, 60, 20], radius=6, fill=(54, 54, 54, int(0.9 * 255)))
        info_block_draw.text((5, 10), f"Lv.{rank.level}", "white", waves_font_18, "lm")
        bar_bg.alpha_composite(info_block, (240, 30))

        # 评分 / 综合评分
        _score_val = rank.overall_score if rank_type == "综合评分" else rank.phantom_score
        _score_label = "综合评分" if rank_type == "综合评分" else "声骸分数"
        if _score_val > 0.0:
            _score_grade = get_panel_score_grade(_score_val) if rank_type == "综合评分" else rank.phantom_score_bg
            score_bg = Image.open(TEXT_PATH / f"score_{_score_grade}.png")
            bar_bg.alpha_composite(score_bg, (545, 2))
            bar_star_draw.text(
                (707, 45),
                f"{int(_score_val * 100) / 100:.2f}",
                "white",
                waves_font_34,
                "mm",
            )
            bar_star_draw.text((707, 75), _score_label, SPECIAL_GOLD, waves_font_16, "mm")

        # 合鸣效果
        if rank.sonata_name:
            effect_image = await get_sonata_effect_image(rank.sonata_name, 50)
            bar_bg.alpha_composite(effect_image, (790, 15))
            sonata_name = get_sonata_label(rank.sonata_name)
        else:
            sonata_name = "合鸣效果"

        sonata_font = waves_font_16
        if len(sonata_name) > 4:
            sonata_font = waves_font_14
        bar_star_draw.text((815, 75), f"{sonata_name}", "white", sonata_font, "mm")

        # 武器
        weapon_bg_temp = Image.new("RGBA", (600, 300))

        weapon_model = get_weapon_model(rank.weapon_id)
        if not weapon_model:
            logger.warning(f"[鸣潮·练度排行] 武器无法找到, 可能暂未适配, 请先检查输入是否正确")
            continue

        weapon_icon = await get_square_weapon(rank.weapon_id)
        weapon_icon = crop_center_img(weapon_icon, 110, 110)
        weapon_icon_bg = get_weapon_icon_bg(weapon_model.starLevel, TEXT_PATH)
        weapon_icon_bg.paste(weapon_icon, (10, 20), weapon_icon)

        weapon_bg_temp_draw = ImageDraw.Draw(weapon_bg_temp)
        weapon_bg_temp_draw.text(
            (200, 30),
            f"{weapon_model.name}",
            SPECIAL_GOLD,
            waves_font_40,
            "lm",
        )
        weapon_bg_temp_draw.text((203, 75), f"Lv.{rank.weapon_level}/90", "white", waves_font_30, "lm")

        _x = 220
        _y = 120
        wrc_fill = WEAPON_RESONLEVEL_COLOR[rank.weapon_reson_level] + (int(0.8 * 255),)
        weapon_bg_temp_draw.rounded_rectangle([_x - 15, _y - 15, _x + 50, _y + 15], radius=7, fill=wrc_fill)
        weapon_bg_temp_draw.text((_x, _y), f"{rank.weapon_reson_level}阶", "white", waves_font_24, "lm")

        weapon_bg_temp.alpha_composite(weapon_icon_bg, dest=(45, 0))

        bar_bg.alpha_composite(weapon_bg_temp.resize((260, 130)), dest=(850, 25))

        # 伤害
        bar_star_draw.text(
            (1140, 45),
            f"{rank.expected_damage:,.0f}",
            SPECIAL_GOLD,
            waves_font_34,
            "mm",
        )
        bar_star_draw.text((1140, 75), f"{rank.expected_name}", "white", waves_font_16, "mm")

        # 排名
        rank_id = rank.rank
        if rank_id <= 0:
            continue
        draw_rank_badge(bar_bg, rank_id)

        # 名字
        name_font, name_text = fit_text(
            bar_star_draw,
            str(rank.kuro_name),
            130,
            (waves_font_20, waves_font_18, waves_font_16, waves_font_14, waves_font_12),
        )
        bar_star_draw.text((210, 75), name_text, "white", name_font, "lm")

        # uid
        uid_color = "white"
        if is_self_ck and self_uid == rank.waves_id:
            uid_color = RED
        if is_group:
            _uid_text = _mask_uid(rank.waves_id, rank.user_id)
        else:
            _uid_text = hide_uid(rank.waves_id, user_pref="on" if rank.hide_uid else "")
        bar_star_draw.text((350, 40), f"特征码: {_uid_text}", uid_color, waves_font_20, "lm")

        # bot主人名字
        botName = rank.alias_name if rank.alias_name else ""
        if botName:
            draw_bot_name_badge(bar_bg, getattr(rank, "background", ""), botName, (346, 60))

        # 贴到背景
        card_img.paste(bar_bg, (0, title_h + text_bar_h + index * bar_star_h), bar_bg)

        if index + 1 + (pages - 1) * page_num == rank_id:
            total_score += rank.overall_score if rank_type == "综合评分" else rank.phantom_score
            total_damage += rank.expected_damage
            avg_num += 1

    avg_score = f"{total_score / avg_num:.1f}" if avg_num != 0 else "0"
    avg_damage = f"{total_damage / avg_num:,.0f}" if avg_num != 0 else "0"

    title = TITLE_II.copy()
    title_draw = ImageDraw.Draw(title)
    # logo
    title.alpha_composite(logo_img.copy(), dest=(350, 65))

    title_draw.text((600, 335), f"{avg_score}", "white", waves_font_44, "mm")
    title_draw.text((600, 375), "平均综合评分" if rank_type == "综合评分" else "平均声骸分数", SPECIAL_GOLD, waves_font_20, "mm")

    title_draw.text((790, 335), f"{avg_damage}", "white", waves_font_44, "mm")
    title_draw.text(
        (790, 375), "平均治疗量" if "治疗" in damage_name else "平均伤害", SPECIAL_GOLD, waves_font_20, "mm"
    )

    if char_id in SPECIAL_CHAR_NAME:
        char_name = SPECIAL_CHAR_NAME[char_id]

    title_name = f"{char_name}{rank_type}{'群排行' if is_group else '总排行'}"
    title_draw.text((540, 265), f"{title_name}", "black", waves_font_30, "lm")

    # 时间
    time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    title_draw.text((470, 205), f"{time_str}", GREY, waves_font_20, "lm")

    # 版本
    info_block = Image.new("RGBA", (100, 30), color=(255, 255, 255, 0))
    info_block_draw = ImageDraw.Draw(info_block)
    info_block_draw.rounded_rectangle([0, 0, 100, 30], radius=6, fill=(0, 79, 152, int(0.9 * 255)))
    info_block_draw.text((50, 15), f"v{get_version()}", "white", waves_font_24, "mm")
    _x = 540 + 31 * len(title_name)
    title.alpha_composite(info_block, (_x, 255))

    img_temp = Image.new("RGBA", char_mask2.size)
    img_temp.alpha_composite(title, (-300, 0))
    # 人物bg
    pile, _ = await get_role_pile_default(char_id, custom=True)
    img_temp.alpha_composite(pile, (600, -120))

    img_temp2 = Image.new("RGBA", char_mask2.size)
    img_temp2.paste(img_temp, (0, 0), char_mask2.copy())

    card_img.alpha_composite(img_temp2, (0, 0))
    card_img = add_footer(card_img)
    card_img = await convert_img(card_img)

    logger.info(f"[鸣潮·练度排行] get_rank_info_for_user end: {time.time() - start_time}")
    return card_img


def get_chain_name(n: int) -> str:
    return f"{['零', '一', '二', '三', '四', '五', '六'][n]}链"


def get_breach(breach: Union[int, None], level: int):
    if breach is None:
        if level <= 20:
            breach = 0
        elif level <= 40:
            breach = 1
        elif level <= 50:
            breach = 2
        elif level <= 60:
            breach = 3
        elif level <= 70:
            breach = 4
        elif level <= 80:
            breach = 5
        elif level <= 90:
            breach = 6
        else:
            breach = 0

    return breach
