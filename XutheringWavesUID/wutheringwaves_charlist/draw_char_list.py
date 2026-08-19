from typing import Union, Optional
from pathlib import Path

from PIL import Image, ImageDraw

from gsuid_core.models import Event
from gsuid_core.pool import to_thread
from gsuid_core.utils.image.convert import convert_img
from gsuid_core.utils.image.image_tools import crop_center_img

from ..utils.hint import error_reply
from ..utils.util import hide_uid, get_hide_uid_pref
from ..utils.image import (
    GREY,
    CHAIN_COLOR,
    SPECIAL_GOLD,
    CHAIN_COLOR_LIST,
    WEAPON_RESONLEVEL_COLOR,
    add_footer,
    get_attribute,
    get_event_avatar,
    get_square_avatar,
    get_square_weapon,
    get_custom_waves_bg,
)
from ..utils.api.model import WeaponData, RoleDetailData
from ..utils.waves_api import waves_api
from ..utils.error_reply import WAVES_CODE_102
from ..utils.ascension.char import char_id_data, ensure_data_loaded
from ..utils.expression_ctx import WavesCharRank, get_waves_char_rank
from ..utils.char_info_utils import get_all_roleid_detail_info_int
from ..wutheringwaves_config import PREFIX, WutheringWavesConfig
from ..wutheringwaves_charinfo import base_info_cache
from ..utils.ascension.weapon import get_breach
from ..utils.fonts.waves_fonts import (
    waves_font_16,
    waves_font_18,
    waves_font_20,
    waves_font_22,
    waves_font_24,
    waves_font_26,
    waves_font_30,
    waves_font_38,
    waves_font_40,
    waves_font_42,
)
from ..utils.resource.constant import NORMAL_LIST, NORMAL_LIST_IDS, SPECIAL_CHAR_NAME
from ..utils.refresh_char_detail import refresh_char, refresh_lock
from ..utils.resource.download_file import get_skill_img
from ..utils.imagetool import get_weapon_icon_bg, draw_base_info_bg

TEXT_PATH = Path(__file__).parent / "texture2d"


async def get_all_roleid_detail_info(
    ev: Event,
    uid: str,
    user_id: str,
    ck: str,
    is_refresh: bool = False,
    is_peek: bool = False,
):
    if not WutheringWavesConfig.get_config("RoleListQuery").data:
        all_role_detail = await get_all_roleid_detail_info_int(uid)
        if all_role_detail:
            return all_role_detail
    else:
        # 根据面板数据获取详细信息
        is_self = not is_peek and user_id == ev.user_id
        if is_refresh or is_peek:
            async with refresh_lock(uid, "all"):
                await refresh_char(ev, uid, user_id, ck, is_self=is_self)
        all_role_detail = await get_all_roleid_detail_info_int(uid)
        if all_role_detail:
            return all_role_detail

        if is_refresh or is_peek:
            # 已经刷新过，但是没有获取到数据
            return None

        # 尝试刷新
        async with refresh_lock(uid, "all"):
            await refresh_char(ev, uid, user_id, ck, is_self=is_self)
        all_role_detail = await get_all_roleid_detail_info_int(uid)
        if all_role_detail:
            return all_role_detail


async def draw_char_list_img(
    uid: str,
    ev: Event,
    user_id: str,
    is_refresh: bool = False,
    is_peek: bool = False,
    user_waves_id: str = "",
    star_filter: Optional[str] = None,
) -> Union[str, bytes]:
    is_self_ck, ck = await waves_api.get_ck_result(user_waves_id, user_id, ev.bot_id)
    if not ck:
        return error_reply(WAVES_CODE_102)
    user_pref = await get_hide_uid_pref(user_waves_id, user_id, ev.bot_id)

    is_self_ck = is_self_ck and (uid == user_waves_id)

    info = await base_info_cache.get_or_fetch_account_info(uid, ck)
    if isinstance(info, str):
        return info
    account_info = info

    all_role_detail = await get_all_roleid_detail_info(
        ev,
        uid,
        user_id,
        ck,
        is_refresh,
        is_peek,
    )
    if not all_role_detail:
        return error_reply(code=-111, msg="练度获取失败，请先刷新角色面板")

    waves_char_rank = await get_waves_char_rank(uid, all_role_detail)
    waves_char_rank.sort(key=lambda i: (i.score, i.starLevel, i.level, i.chain, i.roleId), reverse=True)

    total_count = len(waves_char_rank)
    is_default = star_filter is None
    if is_default:
        star_filter = "all"
    if star_filter == "5":
        display_rank = [r for r in waves_char_rank if r.starLevel == 5]
    elif star_filter == "4":
        display_rank = [r for r in waves_char_rank if r.starLevel == 4]
    else:
        display_rank = list(waves_char_rank)
    # 默认视图: 角色 >100 时隐藏 0 分角色 (显式传星级参数不过滤)
    if is_default and total_count > 100:
        display_rank = [r for r in display_rank if r.score > 0]
    if not display_rank:
        return "[鸣潮] 暂无对应星级的角色"

    two_col = total_count > 60

    # 头像 头像环
    avatar = await draw_pic_with_ring(ev, is_peek)

    # 预取每个角色的图像资源 (仅展示的)
    char_assets = []
    for _rank in display_rank:
        role_detail: RoleDetailData = all_role_detail[_rank.roleId]
        role_avatar = await draw_pic(role_detail.role.roleId)
        role_attribute = await get_attribute(
            role_detail.role.attributeName,
            is_simple=True,  # type: ignore
        )
        skill_imgs = []
        for _skill in role_detail.get_skill_list():
            if _skill.skill.type in ["延奏技能", "谐度破坏"]:
                skill_imgs.append(None)
                continue
            skill_imgs.append(
                await get_skill_img(role_detail.role.roleId, _skill.skill.name, _skill.skill.iconUrl)
            )
        weaponData: WeaponData = role_detail.weaponData
        weapon_icon = await get_square_weapon(weaponData.weapon.weaponId)
        char_assets.append(
            {
                "rank": _rank,
                "role_detail": role_detail,
                "role_avatar": role_avatar,
                "role_attribute": role_attribute,
                "skill_imgs": skill_imgs,
                "weapon_icon": weapon_icon,
            }
        )

    ensure_data_loaded()
    all_up_num = 0
    for char_id, char_data in char_id_data.items():
        if (
            char_data.get("starLevel") == 5
            and int(char_id) not in NORMAL_LIST_IDS
            and str(char_id) not in SPECIAL_CHAR_NAME
        ):
            all_up_num += 1

    # 数量统计按全账号计算, 不随星级过滤变化
    up_num = level_num = chain_num = chain_num_5 = all_num = all_num_5 = 0
    for _rank in waves_char_rank:
        rd: RoleDetailData = all_role_detail[_rank.roleId]
        if _rank.starLevel == 5 and _rank.roleName not in NORMAL_LIST:
            up_num += 1
        if _rank.score >= 175 and _rank.score_bg in ["s", "ss", "sss"]:
            level_num += 1
        if rd.get_chain_num() == 6:
            if _rank.starLevel == 5:
                chain_num_5 += 1
            else:
                chain_num += 1
        all_num += 1
        if _rank.starLevel == 5:
            all_num_5 += 1
    stats = {
        "up_num": up_num,
        "all_up_num": all_up_num,
        "level_num": level_num,
        "all_num": all_num,
        "chain_num": chain_num,
        "all_num_5": all_num_5,
        "chain_num_5": chain_num_5,
    }

    card_img = await _compose_char_list(
        account_info,
        avatar,
        char_assets,
        stats,
        user_pref,
        two_col,
    )
    return await convert_img(card_img)


def _render_bar(asset) -> Image.Image:
    _rank: WavesCharRank = asset["rank"]
    role_detail: RoleDetailData = asset["role_detail"]
    bar_star = Image.open(TEXT_PATH / f"bar_{_rank.starLevel}star.png")
    bar_star_draw = ImageDraw.Draw(bar_star)
    role_avatar = asset["role_avatar"]

    bar_star.paste(role_avatar, (60, 0), role_avatar)

    role_attribute = asset["role_attribute"].resize((40, 40)).convert("RGBA")
    bar_star.alpha_composite(role_attribute, (170, 20))
    bar_star_draw.text((180, 83), f"Lv.{_rank.level}", GREY, waves_font_22, "mm")

    # 命座
    info_block = Image.new("RGBA", (40, 20), color=(255, 255, 255, 0))
    info_block_draw = ImageDraw.Draw(info_block)
    fill = CHAIN_COLOR[role_detail.get_chain_num()] + (int(0.9 * 255),)
    info_block_draw.rectangle([0, 0, 40, 20], fill=fill)
    info_block_draw.text((2, 10), f"{role_detail.get_chain_name()}", "white", waves_font_18, "lm")
    bar_star.alpha_composite(info_block, (120, 15))

    # 评分
    if _rank.score > 0.0:
        score_bg = Image.open(TEXT_PATH / f"score_{_rank.score_bg}.png")
        bar_star.alpha_composite(score_bg, (200, 2))
        bar_star_draw.text(
            (348, 42),
            f"{int(_rank.score * 100) / 100:.2f}",
            "white",
            waves_font_30,
            "mm",
        )
        bar_star_draw.text((348, 75), "声骸分数", SPECIAL_GOLD, waves_font_16, "mm")

    # 技能
    skill_img_temp = Image.new("RGBA", (1500, 300))
    for i, _skill in enumerate(role_detail.get_skill_list()):
        if _skill.skill.type in ["延奏技能", "谐度破坏"]:
            continue
        temp = Image.new("RGBA", (120, 140))
        skill_bg = Image.open(TEXT_PATH / "skill_bg.png")
        temp.alpha_composite(skill_bg)

        skill_img = asset["skill_imgs"][i]
        if skill_img is not None:
            skill_img = skill_img.resize((70, 70))
            temp.alpha_composite(skill_img, (25, 25))

        temp_draw = ImageDraw.Draw(temp)
        color = "white"
        if _skill.level == 10:
            color = CHAIN_COLOR_LIST[-1]
        elif _skill.level == 9:
            color = CHAIN_COLOR_LIST[-2]
        elif _skill.level == 8:
            color = CHAIN_COLOR_LIST[-3]
        elif _skill.level == 7:
            color = CHAIN_COLOR_LIST[-4]
        elif _skill.level == 6:
            color = CHAIN_COLOR_LIST[-5]
        temp_draw.text((62, 120), f"{_skill.level}", color, waves_font_38, "mm")

        _x = 100 + i * 65
        skill_img_temp.alpha_composite(temp.resize((70, 82)), dest=(_x, 0))
    bar_star.alpha_composite(skill_img_temp, dest=(300, 10))

    # 武器
    weapon_bg_temp = Image.new("RGBA", (600, 300))

    weaponData: WeaponData = role_detail.weaponData
    weapon_icon = crop_center_img(asset["weapon_icon"], 110, 110)
    weapon_icon_bg = get_weapon_icon_bg(weaponData.weapon.weaponStarLevel, TEXT_PATH)
    weapon_icon_bg.paste(weapon_icon, (10, 20), weapon_icon)

    weapon_bg_temp_draw = ImageDraw.Draw(weapon_bg_temp)
    weapon_bg_temp_draw.text(
        (200, 30),
        f"{weaponData.weapon.weaponName}",
        SPECIAL_GOLD,
        waves_font_40,
        "lm",
    )
    weapon_bg_temp_draw.text((203, 75), f"Lv.{weaponData.level}/90", "white", waves_font_30, "lm")

    weapon_breach = get_breach(weaponData.breach, weaponData.level)
    for i in range(0, weapon_breach):  # type: ignore
        promote_icon = Image.open(TEXT_PATH / "promote_icon.png")
        weapon_bg_temp.alpha_composite(promote_icon, dest=(200 + 40 * i, 100))

    weapon_bg_temp.alpha_composite(weapon_icon_bg, dest=(45, 0))

    # N阶 打在武器图右下角: 彩色圆角块+白字; 亮底(5阶 AMBER)压暗以保证白字清晰
    rc = WEAPON_RESONLEVEL_COLOR[weaponData.resonLevel]
    if 0.299 * rc[0] + 0.587 * rc[1] + 0.114 * rc[2] > 135:
        rc = tuple(int(c * 0.6) for c in rc)
    weapon_bg_temp_draw.rounded_rectangle([112, 95, 170, 125], radius=8, fill=rc + (int(0.85 * 255),))  # type: ignore
    weapon_bg_temp_draw.text((141, 110), f"{weaponData.resonLevel}阶", "white", waves_font_24, "mm")

    bar_star.alpha_composite(weapon_bg_temp.resize((260, 130)), dest=(710, 25))

    return bar_star


def _draw_info_bg(stats) -> Image.Image:
    info_bg = Image.open(TEXT_PATH / "info_bg.png")
    info_bg_draw = ImageDraw.Draw(info_bg)
    info_bg_draw.text((240, 120), f"{stats['up_num']}/{stats['all_up_num']}", "white", waves_font_40, "mm")
    info_bg_draw.text((240, 160), "up角色", "white", waves_font_20, "mm")
    info_bg_draw.text((410, 120), f"{stats['level_num']}/{stats['all_num']}", "white", waves_font_40, "mm")
    info_bg_draw.text((410, 160), "高练角色", "white", waves_font_20, "mm")
    info_bg_draw.text((580, 120), f"{stats['chain_num']}/{stats['all_num'] - stats['all_num_5']}", "white", waves_font_40, "mm")
    info_bg_draw.text((580, 160), "高链4星", "white", waves_font_20, "mm")
    info_bg_draw.text((750, 120), f"{stats['chain_num_5']}/{stats['all_num_5']}", "white", waves_font_40, "mm")
    info_bg_draw.text((750, 160), "高链5星", "white", waves_font_20, "mm")
    return info_bg


@to_thread
def _compose_char_list(
    account_info,
    avatar,
    char_assets,
    stats,
    user_pref,
    two_col,
) -> Image.Image:
    bar_star_h = 110
    n = len(char_assets)
    if two_col:
        col_w = 920
        width = col_w + 1000
        header_h = 280
        rows = (n + 1) // 2
        h = header_h + rows * bar_star_h + 130
    else:
        width = 1000
        header_h = 230 + 260
        h = header_h + n * bar_star_h + 80
    card_img = get_custom_waves_bg(width, h, "bg3")

    # 基础信息 名字 特征码
    base_info_bg = draw_base_info_bg(
        f"{account_info.name[:10]}",
        f"特征码:  {hide_uid(account_info.id, user_pref=user_pref)}",
        TEXT_PATH,
    )
    card_img.paste(base_info_bg, (15, 20), base_info_bg)

    avatar_ring = Image.open(TEXT_PATH / "avatar_ring.png")
    card_img.paste(avatar, (25, 70), avatar)
    avatar_ring = avatar_ring.resize((180, 180))
    card_img.paste(avatar_ring, (35, 80), avatar_ring)

    # 账号基本信息，由于可能会没有，放在一起
    if account_info.is_full:
        title_bar = Image.open(TEXT_PATH / "title_bar.png")
        title_bar_draw = ImageDraw.Draw(title_bar)
        title_bar_draw.text((660, 125), "账号等级", GREY, waves_font_26, "mm")
        title_bar_draw.text((660, 78), f"Lv.{account_info.level}", "white", waves_font_42, "mm")

        title_bar_draw.text((810, 125), "世界等级", GREY, waves_font_26, "mm")
        title_bar_draw.text((810, 78), f"Lv.{account_info.worldLevel}", "white", waves_font_42, "mm")
        card_img.paste(title_bar, (-20, 70), title_bar)

    # 角色数量统计: 双列时横排到右侧, 单列时在头像下方
    info_bg = _draw_info_bg(stats)
    if two_col:
        card_img.paste(info_bg, (col_w, 35), info_bg)
    else:
        card_img.paste(info_bg, (0, 230), info_bg)

    # 角色 bar: 单列纵向; 双列左侧先排前半, 右侧接后半
    for index, asset in enumerate(char_assets):
        bar_star = _render_bar(asset)
        if two_col:
            col = 0 if index < rows else 1
            row = index if col == 0 else index - rows
            _x = col * col_w
            _y = header_h + row * bar_star_h
        else:
            _x = 0
            _y = header_h + index * bar_star_h
        card_img.paste(bar_star, (_x, _y), bar_star)

    if two_col:
        hint_draw = ImageDraw.Draw(card_img)
        hint = f"可指定  {PREFIX}练度统计 五星/四星/全部"
        hint_draw.text((width // 2, header_h + rows * bar_star_h + 35), hint, SPECIAL_GOLD, waves_font_24, "mm")

    card_img = add_footer(card_img)
    return card_img


async def draw_pic_with_ring(ev: Event, is_peek: bool = False):
    if is_peek:
        pic = await get_square_avatar(1505)
    else:
        pic = await get_event_avatar(ev)

    mask_pic = Image.open(TEXT_PATH / "avatar_mask.png")
    img = Image.new("RGBA", (180, 180))
    mask = mask_pic.resize((160, 160))
    resize_pic = crop_center_img(pic, 160, 160)
    img.paste(resize_pic, (20, 20), mask)

    return img


async def draw_pic(roleId):
    pic = await get_square_avatar(roleId)
    pic_temp = Image.new("RGBA", pic.size)
    pic_temp.paste(pic.resize((160, 160)), (10, 10))

    mask_pic = Image.open(TEXT_PATH / "avatar_mask.png")
    mask_pic_temp = Image.new("RGBA", mask_pic.size)
    mask_pic_temp.paste(mask_pic, (-20, -45), mask_pic)

    img = Image.new("RGBA", (180, 180))
    mask_pic_temp = mask_pic_temp.resize((160, 160))
    resize_pic = pic_temp.resize((160, 160))
    img.paste(resize_pic, (0, 0), mask_pic_temp)

    return img
