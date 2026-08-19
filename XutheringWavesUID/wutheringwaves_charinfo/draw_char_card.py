import re
import copy
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.pool import to_thread
from PIL import Image, ImageDraw, ImageEnhance
from gsuid_core.utils.image.convert import convert_img
from gsuid_core.utils.image.image_tools import crop_center_img

from ..utils import hint
from ..utils.util import hide_uid, get_hide_uid_pref
from ..utils.localization import t
from ..utils.database.models import WavesLangSettings
from ..utils.waves_api import waves_api
from ..wutheringwaves_config import PREFIX
from ..utils.error_reply import WAVES_CODE_102
from ..utils import panel_card_pref
from .card_hash_index import compute_hash, lookup_in_pair as _hash_lookup_in_pair
from .card_utils import resize_and_center_image
from .role_info_change import change_role_detail
from ..utils.ascension.char import get_char_model
from ..utils.api.model_other import EnemyDetailData
from ..utils.damage.utils import comma_separated_number
from ..utils.ascension.template import get_template_data
from ..utils.char_info_utils import get_all_roleid_detail_info, get_char_detail_for_id
from . import base_info_cache
from ..utils.name_convert import alias_to_char_name, char_name_to_char_id
from ..utils.api.wwapi import ONE_RANK_URL, OneRankRequest, OneRankResponse
from ..utils.damage.abstract import DamageRankRegister, DamageDetailRegister, ScoreDetailRegister
from ..utils.score import get_panel_score_grade
from ..utils.char_state import record_view, record_advice_sent, queue_pending_advice
from ..wutheringwaves_config.wutheringwaves_config import (
    ShowConfig,
    WutheringWavesConfig,
)
from ..utils.resource.download_file import (
    get_chain_img,
    get_skill_img,
    get_phantom_img,
)
from ..utils.api.model import (
    WeaponData,
    OnlineRoleList,
    RoleDetailData,
    AccountBaseInfo,
)
from ..utils.ascension.weapon import (
    WavesWeaponResult,
    get_breach,
    get_weapon_model,
    get_weapon_detail,
)
from ..utils.resource.constant import (
    SPECIAL_CHAR,
    SPECIAL_CHAR_RANK_MAP,
    ATTRIBUTE_ID_MAP,
    DEAFAULT_WEAPON_ID,
    WEAPON_TYPE_ID_MAP,
    get_short_name,
)
from ..utils.calculate import (
    get_calc_map,
    get_max_score,
    get_valid_color,
    calc_phantom_entry,
    calc_phantom_score,
    get_total_score_bg,
)
from ..utils.fonts.waves_fonts import (
    draw_text_with_fallback,
    waves_font_12,
    waves_font_16,
    waves_font_18,
    waves_font_20,
    waves_font_22,
    waves_font_24,
    waves_font_25,
    waves_font_26,
    waves_font_28,
    waves_font_30,
    waves_font_36,
    waves_font_40,
    waves_font_42,
    waves_font_50,
)
from ..utils.image import (
    GOLD,
    GREY,
    SPECIAL_GOLD,
    WAVES_MOONLIT,
    WAVES_FREEZING,
    WAVES_SHUXING_MAP,
    WEAPON_RESONLEVEL_COLOR,
    _force_pile_path,
    add_footer,
    change_color,
    get_waves_bg,
    get_attribute,
    get_small_logo,
    get_weapon_type,
    get_event_avatar,
    get_square_avatar,
    get_square_weapon,
    get_attribute_prop,
    get_attribute_skill,
    get_attribute_effect,
    draw_text_with_shadow,
    get_role_pile_with_path,
    get_custom_gaussian_blur,
)
from ..utils.imagetool import get_weapon_icon_bg

TEXT_PATH = Path(__file__).parent / "texture2d"


def _weapon_reson_text(level, locale: str = "") -> str:
    # 谐振阶: zh N阶 / cht N階 / en·jp·kr 官方 Rank(ランク/튜닝)→R 前缀
    if locale == "cht":
        return f"{level}階"
    if locale in ("en", "jp", "kr"):
        return f"R{level}"
    return f"{level}阶"


ph_sort_name = [
    [("生命", "0"), ("攻击", "0"), ("防御", "0"), ("共鸣效率", "0%")],
    [
        ("暴击", "0.0%"),
        ("暴击伤害", "0.0%"),
        ("属性伤害加成", "0.0%"),
        ("治疗效果加成", "0.0%"),
    ],
    [
        ("普攻伤害加成", "0.0%"),
        ("重击伤害加成", "0.0%"),
        ("共鸣技能伤害加成", "0.0%"),
        ("共鸣解放伤害加成", "0.0%"),
    ],
]

card_sort_map = {
    "生命": "0",
    "攻击": "0",
    "防御": "0",
    "共鸣效率": "0%",
    "暴击": "0.0%",
    "暴击伤害": "0.0%",
    "属性伤害加成": "0.0%",
    "治疗效果加成": "0.0%",
    "普攻伤害加成": "0.0%",
    "重击伤害加成": "0.0%",
    "共鸣技能伤害加成": "0.0%",
    "共鸣解放伤害加成": "0.0%",
}

card_sort_name = [
    ("生命", "0"),
    ("攻击", "0"),
    ("防御", "0"),
    ("谐度破坏增幅", "0"),
    ("共鸣效率", "0%"),
    ("偏谐值累积效率", "0%"),
    ("暴击", "0.0%"),
    ("暴击伤害", "0.0%"),
    ("属性伤害加成", "0.0%"),
    ("治疗效果加成", "0.0%"),
]

weight_list = [
    "属性,C4主词条权重,C3主词条权重,C1主词条权重,副词条权重",
    "生命",
    "生命%",
    "攻击",
    "攻击%",
    "防御",
    "防御%",
    "共鸣效率",
    "暴击",
    "暴击伤害",
    "属性伤害加成",
    "治疗效果加成",
    "普攻伤害加成",
    "重击伤害加成",
    "共鸣技能伤害加成",
    "共鸣解放伤害加成",
]

damage_bar1 = Image.open(TEXT_PATH / "damage_bar1.png")
damage_bar2 = Image.open(TEXT_PATH / "damage_bar2.png")


async def get_one_rank(item: OneRankRequest) -> Optional[OneRankResponse]:
    WavesToken = WutheringWavesConfig.get_config("WavesToken").data

    if not WavesToken:
        return

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                ONE_RANK_URL,
                json=item.model_dump(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {WavesToken}",
                },
                timeout=httpx.Timeout(10),
            )
            logger.debug(f"[鸣潮·角色面板渲染] 获取排行: {res.text}")
            if res.status_code == 200:
                return OneRankResponse.model_validate(res.json())
        except Exception as e:
            logger.exception(f"[鸣潮·角色面板渲染] 获取排行失败: {e}")


def parse_text_and_number(text):
    match = re.match(r"(.+?)伤害(\d*)", text)

    if match:
        text_part = match.group(1)  # 获取文字部分
        number_part = match.group(2)  # 获取数字部分，如果有的话
        return text_part, number_part if number_part else None
    else:
        return text, None


# TODO: PIL 卸到线程池 (await/PIL 深度交错)
async def ph_card_draw(
    ph_sum_value,
    role_detail: RoleDetailData,
    is_draw=True,
    change_command="",
    enemy_detail: Optional[EnemyDetailData] = None,
    is_limit_query=False,
    locale="",
    phantom_dirty: bool = False,
):
    from ..utils.calc import WuWaCalc
    char_name = role_detail.role.roleName

    phantom_temp = Image.new("RGBA", (1200, 1280 + ph_sum_value))
    banner3 = Image.open(TEXT_PATH / "banner3.png")
    phantom_temp.alpha_composite(banner3, dest=(0, 0))

    from .role_info_change import ensure_default_modal
    from ..utils.damage.modal import get_role_modal
    ensure_default_modal(role_detail)

    ph_0 = Image.open(TEXT_PATH / "ph_0.png")
    ph_1 = Image.open(TEXT_PATH / "ph_1.png")
    calc = WuWaCalc(role_detail, enemy_detail, is_limit=is_limit_query or phantom_dirty)
    phantom_score = 0  # 初始化声骸评分
    if role_detail.phantomData and role_detail.phantomData.equipPhantomList:
        equipPhantomList = role_detail.phantomData.equipPhantomList
        phantom_score = 0

        calc.phantom_pre = calc.prepare_phantom()
        calc.phantom_card = calc.enhance_summation_phantom_value(calc.phantom_pre)
        calc.calc_temp = get_calc_map(
            calc.phantom_card,
            role_detail.role.roleName,
            role_detail.role.roleId,
            get_role_modal(role_detail),
        )

        for i, _phantom in enumerate(equipPhantomList):
            sh_temp = Image.new("RGBA", (350, 550))
            sh_temp_draw = ImageDraw.Draw(sh_temp)
            sh_bg = Image.open(TEXT_PATH / "sh_bg.png")
            sh_temp.alpha_composite(sh_bg, dest=(0, 0))
            if _phantom and _phantom.phantomProp:
                props = _phantom.get_props()
                _score, _bg = calc_phantom_score(role_detail.role.roleId, props, _phantom.cost, calc.calc_temp)
                if _score > 49.95:
                    _score = 50.0

                phantom_score += _score
                sh_title = Image.open(TEXT_PATH / f"sh_title_{_bg}.png")

                sh_temp.alpha_composite(sh_title, dest=(0, 0))

                phantom_icon = await get_phantom_img(_phantom.phantomProp.phantomId, _phantom.phantomProp.iconUrl)
                fetter_icon = await get_attribute_effect(_phantom.fetterDetail.name)
                fetter_icon = fetter_icon.resize((50, 50))
                phantom_icon.alpha_composite(fetter_icon, dest=(205, 0))
                phantom_icon = phantom_icon.resize((100, 100))
                sh_temp.alpha_composite(phantom_icon, dest=(20, 20))
                phantomName = t(_phantom.phantomProp.name, locale).replace("·", " ").replace("（", " ").replace("）", "")
                short_name = phantomName if locale == 'en' else get_short_name(_phantom.phantomProp.phantomId, phantomName)
                draw_text_with_fallback(sh_temp_draw, (130, 40), f"{short_name}", SPECIAL_GOLD, waves_font_28, "lm")

                # 声骸等级背景
                ph_level_img = Image.new("RGBA", (84, 30), (255, 255, 255, 0))
                ph_level_img_draw = ImageDraw.Draw(ph_level_img)
                ph_level_img_draw.rounded_rectangle([0, 0, 84, 30], radius=8, fill=(0, 0, 0, int(0.8 * 255)))
                draw_text_with_fallback(ph_level_img_draw, (8, 13), f"Lv.{_phantom.level}", "white", waves_font_24, "lm")
                sh_temp.alpha_composite(ph_level_img, (128, 58))

                # 声骸分数背景
                _score_w = 120 if locale == 'en' else 100
                ph_score_img = Image.new("RGBA", (_score_w, 30), (255, 255, 255, 0))
                ph_score_img_draw = ImageDraw.Draw(ph_score_img)
                ph_score_img_draw.rounded_rectangle([0, 0, _score_w, 30], radius=8, fill=(186, 55, 42, int(0.8 * 255)))
                draw_text_with_fallback(ph_score_img_draw, (_score_w // 2, 13), f"{_score}{t('分', locale)}", "white", waves_font_24, "mm")
                sh_temp.alpha_composite(ph_score_img, (223, 58))

                for index in range(0, _phantom.cost):
                    promote_icon = Image.open(TEXT_PATH / "promote_icon.png")
                    promote_icon = promote_icon.resize((30, 30))
                    sh_temp.alpha_composite(promote_icon, dest=(128 + 30 * index, 90))

                for index, _prop in enumerate(props):
                    oset = 55
                    prop_img = await get_attribute_prop(_prop.attributeName)
                    prop_img = prop_img.resize((40, 40))
                    sh_temp.alpha_composite(prop_img, (15, 167 + index * oset))
                    sh_temp_draw = ImageDraw.Draw(sh_temp)
                    name_color = "white"
                    num_color = "white"
                    if index > 1:
                        name_color, num_color = get_valid_color(
                            _prop.attributeName, _prop.attributeValue, calc.calc_temp
                        )
                    _prop_display = t(_prop.attributeName, locale, partial=True)
                    draw_text_with_fallback(sh_temp_draw, 
                        (60, 187 + index * oset),
                        f"{_prop_display[:12 if locale == 'en' else 6]}",
                        name_color,
                        waves_font_24,
                        "lm",
                    )
                    draw_text_with_fallback(sh_temp_draw, 
                        (343, 187 + index * oset),
                        f"{_prop.attributeValue}",
                        num_color,
                        waves_font_24,
                        "rm",
                    )
            if is_draw:
                phantom_temp.alpha_composite(
                    sh_temp,
                    dest=(
                        30 + ((i + 1) % 3) * 385,
                        120 + ph_sum_value + ((i + 1) // 3) * 600,
                    ),
                )

        if phantom_score > 0:
            phantom_score = round(phantom_score, 2)
            if phantom_score > 249.9:
                phantom_score = 250.0
            _bg = get_total_score_bg(char_name, phantom_score, calc.calc_temp)
            sh_score_bg_c = Image.open(TEXT_PATH / f"sh_score_bg_{_bg}.png")
            score_temp = Image.new("RGBA", sh_score_bg_c.size)
            score_temp.alpha_composite(sh_score_bg_c)
            sh_score_c = Image.open(TEXT_PATH / f"sh_score_{_bg}.png")
            score_temp.alpha_composite(sh_score_c)
            score_temp_draw = ImageDraw.Draw(score_temp)

            draw_text_with_fallback(score_temp_draw, (180, 260), t("声骸评级", locale), GREY, waves_font_30 if locale == 'en' else waves_font_40, "mm")
            draw_text_with_fallback(score_temp_draw, (180, 380), f"{phantom_score:.2f}{t('分', locale)}", "white", waves_font_40, "mm")
            draw_text_with_fallback(score_temp_draw, (180, 440), t("声骸评分", locale), GREY, waves_font_30 if locale == 'en' else waves_font_40, "mm")
        else:
            abs_bg = Image.open(TEXT_PATH / "abs.png")
            score_temp = Image.new("RGBA", abs_bg.size)
            score_temp.alpha_composite(abs_bg)
            score_temp_draw = ImageDraw.Draw(score_temp)
            draw_text_with_fallback(score_temp_draw, (180, 130), t("暂无", locale), "white", waves_font_40, "mm")
            draw_text_with_fallback(score_temp_draw, (180, 380), f"- {t('分', locale)}", "white", waves_font_40, "mm")

        if is_draw:
            phantom_temp.alpha_composite(score_temp, dest=(30, 120 + ph_sum_value))

        shuxing = f"{role_detail.role.attributeName}伤害加成"
        for mi, m in enumerate(ph_sort_name):
            for ni, name_default in enumerate(m):
                name, default_value = name_default
                if name == "属性伤害加成":
                    value = calc.phantom_card.get(shuxing, default_value)
                    prop_img = await get_attribute_prop(shuxing)
                    name_color, _ = get_valid_color(shuxing, value, calc.calc_temp)
                    name = t(shuxing, locale)
                else:
                    value = calc.phantom_card.get(name, default_value)
                    prop_img = await get_attribute_prop(name)
                    name_color, _ = get_valid_color(name, value, calc.calc_temp)
                    name = t(name, locale)
                prop_img = prop_img.resize((40, 40))
                ph_bg = ph_0.copy() if ni % 2 == 0 else ph_1.copy()
                ph_bg.alpha_composite(prop_img, (20, 32))
                ph_bg_draw = ImageDraw.Draw(ph_bg)

                draw_text_with_fallback(ph_bg_draw, (70, 50), f"{name[:12 if locale == 'en' else 6]}", name_color, waves_font_24, "lm")
                draw_text_with_fallback(ph_bg_draw, (343, 50), f"{value}", name_color, waves_font_24, "rm")

                phantom_temp.alpha_composite(ph_bg, (40 + mi * 370, 100 + ni * 50))

        ph_tips = ph_1.copy()
        ph_tips_draw = ImageDraw.Draw(ph_tips)

        draw_text_with_fallback(ph_tips_draw, (20, 50), t("评分模板", locale), "white", waves_font_24, "lm")
        draw_text_with_fallback(ph_tips_draw, (350, 50), t(calc.calc_temp['name'], locale, partial=True), (255, 255, 0), waves_font_24, "rm")
        # phantom_temp.alpha_composite(ph_tips, (40 + 2 * 370, 100 + 4 * 50))
        phantom_temp.alpha_composite(ph_tips, (40 + 2 * 370, 45))

        if change_command:
            phantom_temp_text = ImageDraw.Draw(phantom_temp)
            draw_text_with_fallback(phantom_temp_text, (50, 90), f"{change_command}", SPECIAL_GOLD, waves_font_18, "lm")

    # img.paste(phantom_temp, (0, 1320 + jineng_len), phantom_temp)
    return calc, phantom_temp, phantom_score


async def get_role_need(
    ev,
    char_id,
    ck,
    uid,
    char_name,
    waves_id=None,
    is_force_avatar=False,
    force_resource_id=None,
    is_limit_query=False,
    change_list_regex: Optional[str] = None,
    fallback_to_generic=False,
    role_detail_override: Optional[RoleDetailData] = None,
):
    if waves_id:
        query_list = [char_id]
        if char_id in SPECIAL_CHAR:
            query_list = SPECIAL_CHAR.copy()[char_id]

        for char_id in query_list:
            role_detail_info = await waves_api.get_role_detail_info(char_id, waves_id, ck)
            if not role_detail_info.success:
                continue
            role_detail_info = role_detail_info.data
            if (
                not isinstance(role_detail_info, Dict)
                or "role" not in role_detail_info
                or role_detail_info["role"] is None
                or "level" not in role_detail_info
                or role_detail_info["level"] is None
            ):
                continue
            if role_detail_info["phantomData"]["cost"] == 0:
                role_detail_info["phantomData"]["equipPhantomList"] = None

            role_detail = RoleDetailData.model_validate(role_detail_info)

            avatar = await draw_char_with_ring(char_id)
            break
        else:
            return (
                None,
                f"[鸣潮] 特征码[{waves_id}]\n无法获取【{char_name}】角色信息，请在库街区展示此角色！",
            )
    else:
        avatar = await draw_pic_with_ring(ev, is_force_avatar, force_resource_id)
        if role_detail_override is not None:
            return avatar, role_detail_override

        role_detail = await get_char_detail_for_id(uid, char_id)
        if role_detail is None:
            if is_limit_query and not fallback_to_generic:
                return (
                    None,
                    f"[鸣潮] 未找到【{char_name}】角色极限面板信息，请等待适配!",
                )

            # rawData中未找到角色，请求listRole判断角色是否已上线
            if not change_list_regex and not is_limit_query:
                if not ck:
                    _, ck = await waves_api.get_ck_result(uid, ev.user_id, ev.bot_id)
                if ck:
                    online_list = await waves_api.get_online_list_role(ck)
                    if online_list.success and online_list.data:
                        online_list_role_model = OnlineRoleList.model_validate(online_list.data)
                        online_role_map = {str(i.roleId): i for i in online_list_role_model}
                        if char_id in online_role_map:
                            # 角色已上线但rawData中没有，提示刷新
                            return (
                                None,
                                f"[鸣潮] 未找到【{char_name}】角色信息, 请先使用[{PREFIX}刷新{char_name}面板]进行刷新!",
                            )

            # 未上线的角色，构造一个数据
            gen_role_detail = await generate_online_role_detail(char_id)
            if not gen_role_detail:
                return (
                    None,
                    f"[鸣潮] 未找到【{char_name}】角色信息!",
                )
            role_detail = gen_role_detail

    return avatar, role_detail


# TODO: PIL 卸到线程池 (await/PIL 深度交错)
async def draw_fixed_img(img, avatar, account_info, role_detail, locale="", uid=None, char_name=None, user_pref=""):
    # 头像部分
    avatar_ring = Image.open(TEXT_PATH / "avatar_ring.png")

    img.paste(avatar, (45, 20), avatar)
    avatar_ring = avatar_ring.resize((180, 180))
    img.paste(avatar_ring, (55, 30), avatar_ring)

    # base_info 特例: 名字/特征码走 draw_text_with_fallback(emoji)+i18n, 不接公共 draw_base_info_bg
    base_info_bg = Image.open(TEXT_PATH / "base_info_bg.png")
    base_info_draw = ImageDraw.Draw(base_info_bg)
    # account_info 缺失时(baseinfo API 失败) 用 uid 兜底
    _name = account_info.name[:10] if account_info else (uid or "")
    _id = account_info.id if account_info else (uid or "")
    draw_text_with_fallback(base_info_draw, (275, 120), f"{_name}", "white", waves_font_30, "lm")
    draw_text_with_fallback(base_info_draw, (226, 173), f"{t('特征码:', locale)}  {hide_uid(_id, user_pref=user_pref)}", GOLD, waves_font_25, "lm")
    img.paste(base_info_bg, (35, -30), base_info_bg)

    if account_info and account_info.is_full:
        title_bar = Image.open(TEXT_PATH / "title_bar.png")
        title_bar_draw = ImageDraw.Draw(title_bar)
        _level_font = waves_font_20 if locale == 'en' else waves_font_26
        draw_text_with_fallback(title_bar_draw, (510, 125), t("联觉等级", locale), GREY, _level_font, "mm")
        draw_text_with_fallback(title_bar_draw, (510, 78), f"Lv.{account_info.level}", "white", waves_font_42, "mm")

        draw_text_with_fallback(title_bar_draw, (660, 125), t("索拉等阶", locale), GREY, _level_font, "mm")
        draw_text_with_fallback(title_bar_draw, (660, 78), f"Lv.{account_info.worldLevel}", "white", waves_font_42, "mm")

        logo_img = get_small_logo(2)
        title_bar.alpha_composite(logo_img, dest=(780, 65))
        img.paste(title_bar, (200, 15), title_bar)

    # 左侧pile部分
    # 应用用户对该角色的面板图绑定: 仅在外部未强制 (面板编辑器预览路径) 时生效;
    # hash 不存在 / 文件不在就不强制, 落回默认随机选图。
    _pin_token = None
    if uid and char_name and _force_pile_path.get() is None:
        try:
            # 主角变体 pair 共享 pin 键 (1501/1502 同走"漂泊者·衍射"); 同 pair 内跨 char_id 查 hash。
            pin_key = panel_card_pref.pair_pin_key(role_detail.role.roleId, char_name)
            pinned_hash = panel_card_pref.get_pin(str(uid), pin_key)
            if pinned_hash:
                pinned_path = _hash_lookup_in_pair(
                    "card", str(role_detail.role.roleId), pinned_hash
                )
                if pinned_path is not None and pinned_path.is_file():
                    _pin_token = _force_pile_path.set(pinned_path)
        except Exception as _e:
            logger.debug(f"[鸣潮·角色面板渲染] 应用面板图绑定失败, 回退默认: {_e}")
    try:
        is_custom, role_pile, role_pile_path = await get_role_pile_with_path(role_detail.role.roleId, True)
    finally:
        if _pin_token is not None:
            _force_pile_path.reset(_pin_token)
    char_mask = Image.open(TEXT_PATH / "char_mask.png")
    char_fg = Image.open(TEXT_PATH / "char_fg.png")

    role_attribute = await get_attribute(role_detail.role.attributeName)
    role_attribute = role_attribute.resize((50, 50)).convert("RGBA")
    char_fg.paste(role_attribute, (434, 112), role_attribute)
    weapon_type = await get_weapon_type(role_detail.role.weaponTypeName)
    weapon_type = weapon_type.resize((40, 40)).convert("RGBA")
    char_fg.paste(weapon_type, (439, 182), weapon_type)

    char_fg_image = ImageDraw.Draw(char_fg)
    roleName = role_detail.role.roleName
    if "漂泊者" in roleName:
        roleName = "漂泊者"
    roleName = t(roleName, locale)

    draw_text_with_shadow(
        char_fg_image,
        f"{roleName} Lv.{role_detail.role.level}",
        285,
        867,
        waves_font_50,
        anchor="mm",
    )

    role_pile_image = Image.new("RGBA", (560, 1000))

    role_pile = resize_and_center_image(role_pile, is_custom=is_custom)
    role_pile_image.paste(
        role_pile,
        ((560 - role_pile.size[0]) // 2, (1000 - role_pile.size[1]) // 2),
        role_pile,
    )
    img.paste(role_pile_image, (25, 170), char_mask)
    img.paste(char_fg, (25, 170), char_fg)

    if is_custom and role_pile_path is not None:
        hash_id = compute_hash(role_pile_path.name)
        draw = ImageDraw.Draw(img)
        draw_text_with_shadow(draw, hash_id, 525, 270, waves_font_12, offset=(1, 1), shadow_color="gray", anchor="rm")


async def _rawdata_rover_canon(uid) -> Optional[str]:
    """rawData 当前漂泊者属性的 canonical id，无则 None。"""
    detail_map = await get_all_roleid_detail_info(uid)
    for rid in (detail_map or {}):
        if rid in SPECIAL_CHAR:
            return SPECIAL_CHAR_RANK_MAP[rid]
    return None


# TODO: PIL 卸到线程池 (await/PIL 深度交错)
async def draw_char_detail_img(
    ev: Event,
    uid: str,
    char: str,
    user_id,
    waves_id: Optional[str] = None,
    need_convert_img=True,
    is_force_avatar=False,
    change_list_regex=None,
    is_limit_query=False,
    show_score=True,
    fallback_to_generic=False,
    role_detail_override: Optional[RoleDetailData] = None,
):
    locale = await WavesLangSettings.get_lang(ev.user_id)
    # waves_id 时是查别人, 用 self uid 取本人偏好
    user_pref = await get_hide_uid_pref(waves_id or uid, user_id, ev.bot_id)
    char, damageId = parse_text_and_number(char)

    char_name = alias_to_char_name(char)
    char_id = char_name_to_char_id(char)
    if char_name == "漂泊者" and not waves_id:
        # 泛指漂泊者 → rawData 当前属性
        rover_canon = await _rawdata_rover_canon(uid)
        if rover_canon:
            char_id = rover_canon
    if not char_id or len(char_id) != 4 or not char_id.isdigit():
        return f"未找到指定角色, 请检查输入是否正确！"

    damageDetail = DamageDetailRegister.find_class(char_id)
    if damageDetail and not WutheringWavesConfig.get_config("WavesToken").data:
        logger.info(f"[鸣潮·角色面板渲染] {char_name} 未接入总服务器, 跳过伤害绘制")
        damageDetail = None
    ph_sum_value = 250
    jineng_len = 180
    dd_len = 0
    isDraw = False if damageId and damageDetail else True
    echo_list = 1400 if isDraw else 170
    if damageDetail and isDraw:
        dd_len = 60 + (len(damageDetail) + 1) * 60

    # 单条查询的编号跟随列表显示顺序(0值条目不占编号), 选取推迟到面板数据就绪后
    damage_calc = None
    if isDraw and damageId and not damageDetail:
        return f"[鸣潮] 角色【{char_name}】暂不支持伤害计算！\n"

    ck = ""

    # 账户数据
    if waves_id:
        uid = waves_id

    if not is_limit_query:
        info, ck, _ = await base_info_cache.load_account_context(
            uid, user_id, ev.bot_id, force_ck=bool(waves_id)
        )
        if isinstance(info, str):
            # ck 也失败 → 返错误; ck 有效但 baseinfo 失败 → 降级出图
            if not ck:
                return info
            account_info = None
        else:
            account_info = info
        force_resource_id = None
    else:
        account_info = AccountBaseInfo.model_validate(
            {
                "name": "库洛交个朋友",
                "id": uid,
                "level": 100,
                "worldLevel": 10,
                "creatTime": 1739375719,
            }
        )
        force_resource_id = char_id
    # 获取数据
    avatar, role_detail = await get_role_need(
        ev,
        char_id,
        ck,
        uid,
        char_name,
        waves_id,
        is_force_avatar,
        force_resource_id,
        is_limit_query,
        change_list_regex,
        fallback_to_generic=fallback_to_generic,
        role_detail_override=role_detail_override,
    )
    if isinstance(role_detail, str):
        return role_detail

    # def _ph_fp(rd):
    #     try:
    #         pd = rd.phantomData
    #         if pd is None:
    #             return "phantomData=None"
    #         ep = pd.equipPhantomList
    #         if ep is None:
    #             return f"phantomData.cost={pd.cost} equipPhantomList=None"
    #         slots = [bool(x and x.phantomProp) for x in ep]
    #         return f"phantomData.cost={pd.cost} equipPhantomList(len={len(ep)} bool={slots})"
    #     except Exception as ex:
    #         return f"_ph_fp_err: {type(ex).__name__}: {ex}"
    # logger.warning(
    #     f"[鸣潮·伤害诊断] entry char_id={char_id} char={char_name} "
    #     f"is_limit_query={is_limit_query} damageId={damageId} uid={uid} "
    #     f"role_id={getattr(getattr(role_detail, 'role', None), 'roleId', None)} "
    #     f"role_detail_id={id(role_detail)} {_ph_fp(role_detail)}"
    # )

    change_command = ""
    oneRank: Optional[OneRankResponse] = None
    enemy_detail: Optional[EnemyDetailData] = EnemyDetailData()
    if change_list_regex:
        temp = copy.deepcopy(role_detail)
        try:
            role_detail, change_command = await change_role_detail(
                uid, ck, role_detail, enemy_detail, change_list_regex,
                user_id=str(user_id), bot_id=ev.bot_id,
            )
            if change_command and change_command.startswith("[鸣潮]"):
                return change_command
        except Exception as e:
            logger.exception("[鸣潮·角色面板渲染] 角色数据转换错误", e)
            role_detail = temp

    from .role_info_change import is_phantom_dirty

    # 声骸
    calc, phantom_temp, phantom_score = await ph_card_draw(
        ph_sum_value, role_detail, isDraw, change_command, enemy_detail, is_limit_query, locale,
        phantom_dirty=is_phantom_dirty(change_command),
    )
    calc.role_card = calc.enhance_summation_card_value(calc.phantom_card)

    # 伤害列表预计算; 数值为0的条目(如命座未解锁的技能)不渲染
    damage_rows = []
    if isDraw and damageDetail and role_detail.phantomData and role_detail.phantomData.equipPhantomList:
        calc.damageAttribute = calc.card_sort_map_to_attribute(calc.role_card)
        for damage_temp in damageDetail:
            damage_title = damage_temp["title"]
            damageAttributeTemp = copy.deepcopy(calc.damageAttribute)
            setattr(damageAttributeTemp, "_log_title", damage_title)
            crit_damage, expected_damage = damage_temp["func"](damageAttributeTemp, role_detail)
            logger.debug(f"[鸣潮·角色面板渲染] {char_name}-{damage_title} 暴击伤害: {crit_damage}")
            logger.debug(f"[鸣潮·角色面板渲染] {char_name}-{damage_title} 期望伤害: {expected_damage}")
            if (not crit_damage or str(crit_damage) == "0") and str(expected_damage) == "0":
                continue
            damage_rows.append((damage_title, crit_damage, expected_damage))
        dd_len = 60 + (len(damage_rows) + 1) * 60

    damage_calc_img = None
    if not isDraw and damageDetail and role_detail.phantomData and role_detail.phantomData.equipPhantomList:
        # 与列表渲染同一套过滤: 0值条目不渲染也不占编号
        calc.damageAttribute = calc.card_sort_map_to_attribute(calc.role_card)
        seen = 0
        for damage_temp in damageDetail:
            damage_title = damage_temp["title"]
            damageAttributeTemp = copy.deepcopy(calc.damageAttribute)
            setattr(damageAttributeTemp, "_log_title", damage_title)
            crit_damage, expected_damage = damage_temp["func"](damageAttributeTemp, role_detail)
            if (not crit_damage or str(crit_damage) == "0") and str(expected_damage) == "0":
                continue
            seen += 1
            if seen == int(damageId):
                damage_calc = damage_temp
                break
        if damage_calc is None:
            return f"[鸣潮] 角色【{char_name}】未找到该伤害类型[{damageId}], 请先检查输入是否正确！\n"
        logger.debug(f"[鸣潮·角色面板渲染] {char_name}-{damage_title} 暴击伤害: {crit_damage}")
        logger.debug(f"[鸣潮·角色面板渲染] {char_name}-{damage_title} 期望伤害: {expected_damage}")

        damage_high = 100 + (len(damageAttributeTemp.effect) + 3) * 60
        damage_calc_img = Image.new("RGBA", (1200, damage_high))

        damage_title_bg = damage_bar1.copy()
        damage_title_bg_draw = ImageDraw.Draw(damage_title_bg)
        draw_text_with_fallback(damage_title_bg_draw, (400, 50), t("伤害类型", locale), SPECIAL_GOLD, waves_font_24, "rm")
        draw_text_with_fallback(damage_title_bg_draw, (700, 50), t("暴击伤害", locale), SPECIAL_GOLD, waves_font_24, "mm")
        draw_text_with_fallback(damage_title_bg_draw, (1000, 50), t("期望伤害", locale), SPECIAL_GOLD, waves_font_24, "mm")
        damage_calc_img.alpha_composite(damage_title_bg, dest=(0, 10))

        damage_bar = damage_bar2.copy()
        damage_bar_draw = ImageDraw.Draw(damage_bar)
        draw_text_with_fallback(damage_bar_draw, (400, 50), t(damage_title, locale, partial=True), "white", waves_font_24, "rm")
        if crit_damage and expected_damage:
            draw_text_with_fallback(damage_bar_draw, (700, 50), f"{crit_damage}", "white", waves_font_24, "mm")
            draw_text_with_fallback(damage_bar_draw, (1000, 50), f"{expected_damage}", "white", waves_font_24, "mm")
        else:
            draw_text_with_fallback(damage_bar_draw, (850, 50), f"{expected_damage}", "white", waves_font_24, "mm")
        damage_calc_img.alpha_composite(damage_bar, dest=(0, 70))

        damage_title_bg = damage_bar1.copy()
        damage_title_bg_draw = ImageDraw.Draw(damage_title_bg)
        draw_text_with_fallback(damage_title_bg_draw, (600, 50), t("buff列表", locale), "white", waves_font_24, "mm")
        damage_calc_img.alpha_composite(damage_title_bg, dest=(0, 130))

        for dindex, effect in enumerate(damageAttributeTemp.effect):
            buff_name = effect.element_msg
            buff_value = effect.element_value
            damage_bar = damage_bar2.copy() if dindex % 2 == 0 else damage_bar1.copy()
            damage_bar_draw = ImageDraw.Draw(damage_bar)
            draw_text_with_fallback(damage_bar_draw, (400, 50), t(buff_name, locale, partial=True), "white", waves_font_24, "rm")
            draw_text_with_fallback(damage_bar_draw, (800, 50), f"{buff_value}", "white", waves_font_24, "mm")
            damage_calc_img.alpha_composite(damage_bar, dest=(0, 10 + (dindex + 3) * 60))

        dd_len += damage_calc_img.size[1]

    score_report = None
    scoreDetail = ScoreDetailRegister.find_class(char_id)
    if scoreDetail and show_score and not is_limit_query and role_detail.phantomData and role_detail.phantomData.equipPhantomList:
        try:
            score_calc = scoreDetail[0] if isinstance(scoreDetail, list) else scoreDetail
            score_title = score_calc.get("title", f"综合评分-{char_name}")
            setattr(calc, "_score_title", score_title)
            score_report = score_calc["func"](calc, role_detail)
            if score_report is not None:
                logger.info(
                    f"[鸣潮·评分] {score_title}: {score_report.score:.1f}/150 "
                    f"(raw={score_report.raw:,.1f} / max={score_report.max_raw:,.1f})"
                )
        except Exception as e:
            logger.warning(f"[鸣潮·评分] {char_name} 计算失败: {e}")

    # 仅本人查询写 state: 他人/特征码查询不动本人 view 计数、脏标记与建议
    is_self = not waves_id and user_id == ev.user_id
    if not is_limit_query and not change_list_regex and is_self:
        try:
            char_state = await record_view(uid, char_id)
            if (
                char_state is not None
                and score_report is not None
                and score_report.partial_max
            ):
                grade = get_panel_score_grade(score_report.score)
                if (
                    grade in ("b", "c")
                    and score_report.score > 40
                    and char_state.get("advice_dirty", True)
                ):
                    dirs = score_report.partial_max[0]
                    advice = f"[鸣潮] {char_name} 建议提升词条方向: {dirs}"
                    if await record_advice_sent(uid, char_id, advice):
                        queue_pending_advice(ev, advice)
        except Exception as e:
            logger.warning(f"[鸣潮·角色状态] {char_name} 状态记录失败: {e}")

    score_offset = 115 if score_report else 0
    bar_shift = 25 if score_report else 0
    jineng_len += score_offset + bar_shift

    if not is_limit_query:
        # 非极限查询时，获取评分排名
        rank_expected_damage = None
        rankDetail = DamageRankRegister.find_class(char_id)
        if rankDetail and role_detail.phantomData and role_detail.phantomData.equipPhantomList:
            try:
                calc.damageAttribute = calc.card_sort_map_to_attribute(calc.role_card)
                _, rank_expected_damage_str = rankDetail["func"](calc.damageAttribute, role_detail)
                rank_expected_damage = comma_separated_number(rank_expected_damage_str)
            except Exception as e:
                logger.warning(f"[鸣潮·角色面板渲染] 获取排行伤害失败: {e}")
                rank_expected_damage = None

        oneRank = await get_one_rank(
            OneRankRequest(
                char_id=int(char_id),
                waves_id=uid,
                phantom_score=phantom_score if phantom_score > 0 else None,
                expected_damage=rank_expected_damage,
            )
        )
        if oneRank and len(oneRank.data) > 0:
            dd_len += 60 * 2

    # 创建背景
    img = await get_card_bg(1200, 1250 + echo_list + ph_sum_value + jineng_len + dd_len, "bg3")
    # 固定位置
    await draw_fixed_img(img, avatar, account_info, role_detail, locale, uid=uid, char_name=char_name, user_pref=user_pref)

    # 声骸
    img.paste(phantom_temp, (0, 1320 + jineng_len), phantom_temp)

    if damage_calc_img:
        img.alpha_composite(damage_calc_img, (0, img.size[1] - 10 - damage_calc_img.size[1]))

    # 右侧属性: 有评分时左半留分数位, 否则用旧布局
    right_image_temp = Image.new("RGBA", (600, 1100))
    if score_report is not None:
        right_prop_y = 100
        right_weapon_banner_y = 620
        weapon_name_y = 780
        weapon_bg_y = 750
    else:
        right_prop_y = 80
        right_weapon_banner_y = 550
        weapon_name_y = 680
        weapon_bg_y = 620

    # 武器banner
    banner2 = Image.open(TEXT_PATH / "banner2.png")
    right_image_temp.alpha_composite(banner2, dest=(-9, right_weapon_banner_y))

    # 右侧属性-武器-激活技能
    skill_branch = role_detail.get_skill_branch()
    if skill_branch:
        weapon_bg = Image.open(TEXT_PATH / "weapon_branch_bg.png")
    else:
        weapon_bg = Image.open(TEXT_PATH / "weapon_bg.png")

    weapon_bg_temp = Image.new("RGBA", right_image_temp.size)
    weapon_bg_temp.alpha_composite(weapon_bg, dest=(0, weapon_bg_y))

    weaponData: WeaponData = role_detail.weaponData

    weapon_icon = await get_square_weapon(weaponData.weapon.weaponId)
    weapon_icon = crop_center_img(weapon_icon, 110, 110)
    weapon_icon_bg = get_weapon_icon_bg(weaponData.weapon.weaponStarLevel, TEXT_PATH)
    weapon_icon_bg.paste(weapon_icon, (10, 20), weapon_icon)

    weapon_bg_temp_draw = ImageDraw.Draw(weapon_bg_temp)
    _weapon_name_width = draw_text_with_fallback(weapon_bg_temp_draw, (200, weapon_name_y), t(weaponData.weapon.weaponName, locale), SPECIAL_GOLD, waves_font_40, "lm")
    draw_text_with_fallback(weapon_bg_temp_draw, (203, weapon_name_y + 45), f"Lv.{weaponData.level}/90", "white", waves_font_30, "lm")

    _x = min(int(200 + _weapon_name_width + 20), weapon_bg.width - 50)
    _y = weapon_name_y + 7
    wrc_fill = WEAPON_RESONLEVEL_COLOR[weaponData.resonLevel] + (int(0.8 * 255),)  # type: ignore
    weapon_bg_temp_draw.rounded_rectangle([_x - 15, _y - 15, _x + 50, _y + 15], radius=7, fill=wrc_fill)

    draw_text_with_fallback(weapon_bg_temp_draw, (_x, _y), _weapon_reson_text(weaponData.resonLevel, locale), "white", waves_font_24, "lm")

    weapon_breach = get_breach(weaponData.breach, weaponData.level)
    for i in range(0, weapon_breach):  # type: ignore
        promote_icon = Image.open(TEXT_PATH / "promote_icon.png")
        weapon_bg_temp.alpha_composite(promote_icon, dest=(200 + 40 * i, weapon_name_y + 70))

    weapon_bg_temp.alpha_composite(weapon_icon_bg, dest=(45, weapon_name_y - 30))

    weapon_detail: WavesWeaponResult = get_weapon_detail(
        weaponData.weapon.weaponId,
        weaponData.level,
        weaponData.breach,
        weaponData.resonLevel,
    )
    stats_main = await get_attribute_prop(weapon_detail.stats[0]["name"])
    stats_main = stats_main.resize((40, 40))
    weapon_bg_temp.alpha_composite(stats_main, (65, weapon_bg_y + 187))
    stats_sub = await get_attribute_prop(weapon_detail.stats[1]["name"])
    stats_sub = stats_sub.resize((40, 40))
    weapon_bg_temp.alpha_composite(stats_sub, (65, weapon_bg_y + 237))

    _ws0_name = t(weapon_detail.stats[0]['name'], locale, partial=True)
    _ws1_name = t(weapon_detail.stats[1]['name'], locale, partial=True)
    if skill_branch:
        draw_text_with_fallback(weapon_bg_temp_draw, (115, weapon_bg_y + 207), _ws0_name, "white", waves_font_30, "lm")
        draw_text_with_fallback(weapon_bg_temp_draw, (115, weapon_bg_y + 257), _ws1_name, "white", waves_font_30, "lm")
        draw_text_with_fallback(weapon_bg_temp_draw, (115 + 300, weapon_bg_y + 207), f"{weapon_detail.stats[0]['value']}", "white", waves_font_30, "rm")
        draw_text_with_fallback(weapon_bg_temp_draw, (115 + 300, weapon_bg_y + 257), f"{weapon_detail.stats[1]['value']}", "white", waves_font_30, "rm")
        active_skill = await get_attribute_skill(skill_branch.branchName, locale)
        active_skill = active_skill.resize((100, 100))
        weapon_bg_temp.alpha_composite(active_skill, dest=(500 - 50, weapon_bg_y + 232 - 50))
    else:
        draw_text_with_fallback(weapon_bg_temp_draw, (130, weapon_bg_y + 207), _ws0_name, "white", waves_font_30, "lm")
        draw_text_with_fallback(weapon_bg_temp_draw, (130, weapon_bg_y + 257), _ws1_name, "white", waves_font_30, "lm")
        draw_text_with_fallback(weapon_bg_temp_draw, (500, weapon_bg_y + 207), f"{weapon_detail.stats[0]['value']}", "white", waves_font_30, "rm")
        draw_text_with_fallback(weapon_bg_temp_draw, (500, weapon_bg_y + 257), f"{weapon_detail.stats[1]['value']}", "white", waves_font_30, "rm")

    right_image_temp.alpha_composite(weapon_bg_temp, dest=(0, 0))

    # 命座部分
    mz_temp = Image.new("RGBA", (1200, 300))

    shuxing_color = WAVES_SHUXING_MAP[role_detail.role.attributeName]  # type: ignore
    for i, _mz in enumerate(role_detail.chainList):
        mz_bg = Image.open(TEXT_PATH / "mz_bg.png")
        mz_bg_temp = Image.new("RGBA", mz_bg.size)
        mz_bg_temp_draw = ImageDraw.Draw(mz_bg_temp)
        chain = await get_chain_img(role_detail.role.roleId, _mz.order, _mz.iconUrl)  # type: ignore
        chain = chain.resize((100, 100))
        mz_bg.paste(chain, (95, 75), chain)
        mz_bg_temp.alpha_composite(mz_bg, dest=(0, 0))
        if _mz.unlocked:
            mz_bg_temp = await change_color(mz_bg_temp, shuxing_color)

        name = re.sub(r'[",，]+', "", _mz.name) if _mz.name else ""
        name = t(name, locale, partial=True)
        if locale == 'en' and len(name) > 14 and ' ' in name:
            mid = len(name) // 2
            left = name.rfind(' ', 0, mid)
            right = name.find(' ', mid)
            if left == -1:
                split_pos = right
            elif right == -1:
                split_pos = left
            else:
                split_pos = left if (mid - left) <= (right - mid) else right
            name = name[:split_pos] + "\n" + name[split_pos + 1:]
        if len(name) >= 8:
            draw_text_with_fallback(mz_bg_temp_draw, (147, 230), name, "white", waves_font_16, "mm")
        else:
            draw_text_with_fallback(mz_bg_temp_draw, (147, 230), name, "white", waves_font_20, "mm")

        if not _mz.unlocked:
            mz_bg_temp = ImageEnhance.Brightness(mz_bg_temp).enhance(0.3)
        mz_temp.alpha_composite(mz_bg_temp, dest=(i * 190, 0))

    img.paste(mz_temp, (0, 1080 + jineng_len), mz_temp)

    if isDraw and damage_rows:
        damage_title_bg = damage_bar1.copy()
        damage_title_bg_draw = ImageDraw.Draw(damage_title_bg)
        draw_text_with_fallback(damage_title_bg_draw, (400, 50), t("伤害类型", locale), SPECIAL_GOLD, waves_font_24, "rm")
        draw_text_with_fallback(damage_title_bg_draw, (700, 50), t("暴击伤害", locale), SPECIAL_GOLD, waves_font_24, "mm")
        draw_text_with_fallback(damage_title_bg_draw, (1000, 50), t("期望伤害", locale), SPECIAL_GOLD, waves_font_24, "mm")
        img.alpha_composite(damage_title_bg, dest=(0, 2600 + ph_sum_value + jineng_len))
        for dindex, (damage_title, crit_damage, expected_damage) in enumerate(damage_rows):
            damage_bar = damage_bar2.copy() if dindex % 2 == 0 else damage_bar1.copy()
            damage_bar_draw = ImageDraw.Draw(damage_bar)
            draw_text_with_fallback(damage_bar_draw, (400, 50), t(damage_title, locale, partial=True), "white", waves_font_24, "rm")
            if crit_damage and expected_damage:
                draw_text_with_fallback(damage_bar_draw, (700, 50), f"{crit_damage}", "white", waves_font_24, "mm")
                draw_text_with_fallback(damage_bar_draw, (1000, 50), f"{expected_damage}", "white", waves_font_24, "mm")
            else:
                draw_text_with_fallback(damage_bar_draw, (850, 50), f"{expected_damage}", "white", waves_font_24, "mm")
            img.alpha_composite(
                damage_bar,
                dest=(0, 2600 + ph_sum_value + jineng_len + (dindex + 1) * 60),
            )

        if oneRank and len(oneRank.data) > 0:
            dindex += 1
            damage_bar = damage_bar2.copy() if dindex % 2 == 0 else damage_bar1.copy()
            damage_bar_draw = ImageDraw.Draw(damage_bar)
            damage_bar_draw = ImageDraw.Draw(damage_bar)
            draw_text_with_fallback(damage_bar_draw, 
                (400, 50),
                t("评分排名", locale) if oneRank.data[0].rank > 0 else t("估计评分排名", locale),
                "white",
                waves_font_24,
                "rm",
            )
            draw_text_with_fallback(damage_bar_draw, 
                (850, 50),
                f"{oneRank.data[0].rank}" if oneRank.data[0].rank > 0 else oneRank.data[0].inter_rank,
                SPECIAL_GOLD,
                waves_font_24,
                "mm",
            )
            img.alpha_composite(
                damage_bar,
                dest=(0, 2600 + ph_sum_value + jineng_len + (dindex + 1) * 60),
            )
            
            if len(oneRank.data) > 1:

                dindex += 1
                damage_bar = damage_bar2.copy() if dindex % 2 == 0 else damage_bar1.copy()
                damage_bar_draw = ImageDraw.Draw(damage_bar)
                damage_bar_draw = ImageDraw.Draw(damage_bar)
                draw_text_with_fallback(damage_bar_draw, 
                    (400, 50),
                    t("伤害排名", locale) if oneRank.data[1].rank > 0 else t("估计伤害排名", locale),
                    "white",
                    waves_font_24,
                    "rm",
                )
                draw_text_with_fallback(damage_bar_draw, 
                    (850, 50),
                    f"{oneRank.data[1].rank}" if oneRank.data[1].rank > 0 else oneRank.data[1].inter_rank,
                    SPECIAL_GOLD,
                    waves_font_24,
                    "mm",
                )
                img.alpha_composite(
                    damage_bar,
                    dest=(0, 2600 + ph_sum_value + jineng_len + (dindex + 1) * 60),
                )

    banner1 = Image.open(TEXT_PATH / "banner4.png")
    right_image_temp.alpha_composite(banner1, dest=(-9, 0)) # 因为属性图不是居中对称的，banner偏移和属性居中对齐
    sh_bg = Image.open(TEXT_PATH / "prop_bg.png")
    sh_bg_draw = ImageDraw.Draw(sh_bg)

    shuxing = f"{role_detail.role.attributeName}伤害加成"

    # 右侧面板最后一槽: 治疗 与 4 种技能伤害加成里数值最高的一项
    def _pct(v):
        try:
            return float(str(v).replace("%", ""))
        except (ValueError, TypeError):
            return 0.0

    _last_slot_candidates = (
        "治疗效果加成",
        "普攻伤害加成",
        "重击伤害加成",
        "共鸣技能伤害加成",
        "共鸣解放伤害加成",
    )
    _last_slot_name = max(
        _last_slot_candidates,
        key=lambda k: _pct(calc.role_card.get(k, "0")),
    )
    panel_items = list(card_sort_name[:-1]) + [(_last_slot_name, "0.0%")]

    for index, name_default in enumerate(panel_items):
        name, default_value = name_default
        if name == "属性伤害加成":
            value = calc.role_card.get(shuxing, default_value)
            prop_img = await get_attribute_prop(shuxing)
            name_color, _ = get_valid_color(shuxing, value, calc.calc_temp)
            name = t(shuxing, locale)
        else:
            value = calc.role_card.get(name, default_value)
            prop_img = await get_attribute_prop(name)
            name_color, _ = get_valid_color(name, value, calc.calc_temp)
            if index < 4:
                name = name.replace("破坏", "")
            name = t(name, locale)

        prop_img = prop_img.resize((40, 40))

        if index < 4:
            sh_bg.alpha_composite(prop_img, (60 + 251 * (index % 2), 40 + (index // 2) * 55))
            draw_text_with_fallback(sh_bg_draw, (115 + 251 * (index % 2), 58 + (index // 2) * 55), f"{name}", name_color, waves_font_24, "lm")
            draw_text_with_fallback(sh_bg_draw, (530 - 251 * ((index + 1) % 2), 58 + (index // 2) * 55), f"{value}", name_color, waves_font_24, "rm")
        else:
            sh_bg.alpha_composite(prop_img, (60, 40 + (index - 2) * 55))
            draw_text_with_fallback(sh_bg_draw, (115, 58 + (index - 2) * 55), f"{name}", name_color, waves_font_24, "lm")
            draw_text_with_fallback(sh_bg_draw, (530, 58 + (index - 2) * 55), f"{value}", name_color, waves_font_24, "rm")

    right_image_temp.alpha_composite(sh_bg, dest=(0, right_prop_y))
    img.paste(right_image_temp, (570, 200 + bar_shift), right_image_temp)

    # 技能
    skill_bar = Image.open(TEXT_PATH / "skill_bar.png")
    skill_bg_1 = Image.open(TEXT_PATH / "skill_bg.png")

    temp_i = 0
    for _, _skill in enumerate(role_detail.get_skill_list()):
        if _skill.skill.type in ["延奏技能", "谐度破坏"]:
            continue
        skill_bg = skill_bg_1.copy()
        # logger.debug(f"[鸣潮·角色面板渲染] {char_name}-{_skill.skill.name}")
        skill_img = await get_skill_img(role_detail.role.roleId, _skill.skill.name, _skill.skill.iconUrl)
        skill_img = skill_img.resize((70, 70))
        skill_bg.paste(skill_img, (57, 65), skill_img)

        skill_bg_draw = ImageDraw.Draw(skill_bg)
        _skill_font = waves_font_18 if locale == 'en' else waves_font_25
        draw_text_with_fallback(skill_bg_draw, (150, 83), t(_skill.skill.type, locale), "white", _skill_font, "lm")
        draw_text_with_fallback(skill_bg_draw, (150, 113), f"Lv.{_skill.level}", "white", waves_font_25, "lm")

        skill_bg_temp = Image.new("RGBA", skill_bg.size)
        skill_bg_temp = Image.alpha_composite(skill_bg_temp, skill_bg)

        _x = 20 + temp_i * 215
        _y = -20
        skill_bar.alpha_composite(skill_bg_temp, dest=(_x, _y))
        temp_i += 1
    img.alpha_composite(skill_bar, dest=(0, 1150 + score_offset + bar_shift))

    # 综合评分块: 立绘下方 / skill_bar 上方 (score_offset 同步)
    if score_report is not None:
        grade = get_panel_score_grade(score_report.score)
        grade_icon = Image.open(TEXT_PATH / f"panel_score_{grade}.png")
        grade_icon = grade_icon.resize((200, 200))
        img.alpha_composite(grade_icon, dest=(90, 1080 + bar_shift))
        score_draw = ImageDraw.Draw(img)
        draw_text_with_fallback(score_draw, (400, 1140 + bar_shift), f"{score_report.score:.2f}", "white", waves_font_40, "mm")
        draw_text_with_fallback(score_draw, (400, 1210 + bar_shift), t("综合评分", locale), GREY, waves_font_40, "mm")

    img = add_footer(img)
    if need_convert_img:
        img = await convert_img(img)
    return img


# TODO: PIL 卸到线程池 (await/PIL 深度交错)
async def draw_char_score_img(ev: Event, uid: str, char: str, user_id: str, waves_id: Optional[str] = None, is_limit_query=False):
    from ..utils.calc import WuWaCalc
    locale = await WavesLangSettings.get_lang(ev.user_id)
    user_pref = await get_hide_uid_pref(waves_id or uid, user_id, ev.bot_id)
    char, damageId = parse_text_and_number(char)

    char_id = char_name_to_char_id(char)
    if not char_id or len(char_id) != 4 or not char_id.isdigit():
        return f"未找到指定角色, 请检查输入是否正确！"
    char_name = alias_to_char_name(char)

    ck = ""

    # 账户数据
    if waves_id:
        uid = waves_id

    if not is_limit_query:
        info, ck, _ = await base_info_cache.load_account_context(
            uid, user_id, ev.bot_id, force_ck=bool(waves_id)
        )
        if isinstance(info, str):
            # ck 也失败 → 返错误; ck 有效但 baseinfo 失败 → 降级出图
            if not ck:
                return info
            account_info = None
        else:
            account_info = info
        force_resource_id = None
    else:
        account_info = AccountBaseInfo.model_validate(
            {
                "name": "库洛交个朋友",
                "id": uid,
                "level": 100,
                "worldLevel": 10,
                "creatTime": 1739375719,
            }
        )
        force_resource_id = char_id
    # 获取数据
    avatar, role_detail = await get_role_need(
        ev,
        char_id,
        ck,
        uid,
        char_name,
        waves_id,
        is_force_avatar=False,
        force_resource_id=force_resource_id,
        is_limit_query=is_limit_query,
    )
    if isinstance(role_detail, str):
        return role_detail

    from ..utils.damage.modal import get_modal_options, get_role_modal
    weight_modals = get_modal_options(int(role_detail.role.roleId))
    active_modal = get_role_modal(role_detail)
    weight_base_y = 2400
    weight_block_h = 900

    # 创建背景
    img = await get_card_bg(1200, weight_base_y + max(1, len(weight_modals)) * weight_block_h + 80, "bg3")
    # 固定位置
    await draw_fixed_img(img, avatar, account_info, role_detail, locale, uid=uid, char_name=char_name, user_pref=user_pref)

    # 声骸属性
    char_id = role_detail.role.roleId
    char_name = role_detail.role.roleName

    phantom_temp = Image.new("RGBA", (1200, 1380))
    right_image_temp = Image.new("RGBA", (600, 1100))

    from .role_info_change import ensure_default_modal
    ensure_default_modal(role_detail)

    ph_0 = Image.open(TEXT_PATH / "ph_0.png")
    ph_1 = Image.open(TEXT_PATH / "ph_1.png")
    # phantom_sum_value = {}
    calc: WuWaCalc = WuWaCalc(role_detail, is_limit=is_limit_query)
    if role_detail.phantomData and role_detail.phantomData.equipPhantomList:
        equipPhantomList = role_detail.phantomData.equipPhantomList
        phantom_score = 0

        calc.phantom_pre = calc.prepare_phantom()
        calc.phantom_card = calc.enhance_summation_phantom_value(calc.phantom_pre)
        calc.calc_temp = get_calc_map(
            calc.phantom_card,
            role_detail.role.roleName,
            role_detail.role.roleId,
            active_modal,
        )
        if is_limit_query:
            calc.role_card = calc.enhance_summation_card_value(calc.phantom_card)

        for i, _phantom in enumerate(equipPhantomList):
            sh_temp = Image.new("RGBA", (600, 1100))
            sh_temp_draw = ImageDraw.Draw(sh_temp)
            sh_bg = Image.open(TEXT_PATH / "sh_bg.png")
            sh_temp.alpha_composite(sh_bg, dest=(0, 0))
            if _phantom and _phantom.phantomProp:
                props = _phantom.get_props()
                _score, _bg = calc_phantom_score(char_id, props, _phantom.cost, calc.calc_temp)
                if _score > 49.95:
                    _score = 50.0

                phantom_score += _score
                sh_title = Image.open(TEXT_PATH / f"sh_title_{_bg}.png")

                sh_temp.alpha_composite(sh_title, dest=(0, 0))

                phantom_icon = await get_phantom_img(_phantom.phantomProp.phantomId, _phantom.phantomProp.iconUrl)
                fetter_icon = await get_attribute_effect(_phantom.fetterDetail.name)
                fetter_icon = fetter_icon.resize((50, 50))
                phantom_icon.alpha_composite(fetter_icon, dest=(205, 0))
                phantom_icon = phantom_icon.resize((100, 100))
                sh_temp.alpha_composite(phantom_icon, dest=(20, 20))
                phantomName = t(_phantom.phantomProp.name, locale).replace("·", " ").replace("（", " ").replace("）", "")
                short_name = phantomName if locale == 'en' else get_short_name(_phantom.phantomProp.phantomId, phantomName)
                draw_text_with_fallback(sh_temp_draw, (130, 40), f"{short_name}", SPECIAL_GOLD, waves_font_28, "lm")

                # 声骸等级背景
                ph_level_img = Image.new("RGBA", (84, 30), (255, 255, 255, 0))
                ph_level_img_draw = ImageDraw.Draw(ph_level_img)
                ph_level_img_draw.rounded_rectangle([0, 0, 84, 30], radius=8, fill=(0, 0, 0, int(0.8 * 255)))
                draw_text_with_fallback(ph_level_img_draw, (8, 13), f"Lv.{_phantom.level}", "white", waves_font_24, "lm")
                sh_temp.alpha_composite(ph_level_img, (128, 58))

                # 声骸分数背景
                _score_w = 120 if locale == 'en' else 100
                ph_score_img = Image.new("RGBA", (_score_w, 30), (255, 255, 255, 0))
                ph_score_img_draw = ImageDraw.Draw(ph_score_img)
                ph_score_img_draw.rounded_rectangle([0, 0, _score_w, 30], radius=8, fill=(186, 55, 42, int(0.8 * 255)))
                draw_text_with_fallback(ph_score_img_draw, (_score_w // 2, 13), f"{_score}{t('分', locale)}", "white", waves_font_24, "mm")
                sh_temp.alpha_composite(ph_score_img, (228, 58))

                for index in range(0, _phantom.cost):
                    promote_icon = Image.open(TEXT_PATH / "promote_icon.png")
                    promote_icon = promote_icon.resize((30, 30))
                    sh_temp.alpha_composite(promote_icon, dest=(128 + 30 * index, 90))

                for index, _prop in enumerate(props):
                    oset = 55
                    prop_img = await get_attribute_prop(_prop.attributeName)
                    prop_img = prop_img.resize((40, 40))
                    # sh_temp.alpha_composite(prop_img, (15, 167 + index * oset))
                    sh_temp_draw = ImageDraw.Draw(sh_temp)
                    name_color = "white"
                    num_color = "white"
                    if index > 1:
                        name_color, num_color = get_valid_color(
                            _prop.attributeName, _prop.attributeValue, calc.calc_temp
                        )
                    _prop_display = t(_prop.attributeName, locale, partial=True)
                    draw_text_with_fallback(sh_temp_draw, 
                        (15, 187 + index * oset),
                        f"{_prop_display[:12 if locale == 'en' else 6]}",
                        name_color,
                        waves_font_24,
                        "lm",
                    )
                    draw_text_with_fallback(sh_temp_draw, 
                        (273, 187 + index * oset),
                        f"{_prop.attributeValue}",
                        num_color,
                        waves_font_24,
                        "rm",
                    )

                    score, final_score = calc_phantom_entry(
                        index,
                        _prop,
                        _phantom.cost,
                        calc.calc_temp,
                        role_detail.role.attributeName or "",
                    )
                    score_color = WAVES_MOONLIT
                    if final_score > 0:
                        score_color = WAVES_FREEZING
                    draw_text_with_fallback(sh_temp_draw, 
                        (343, 191 + index * oset),
                        f"{final_score}{t('分', locale)}",
                        score_color,
                        waves_font_18,
                        "rm",
                    )

                max_score, _ = get_max_score(_phantom.cost, calc.calc_temp)
                draw_text_with_fallback(sh_temp_draw, 
                    (343, 191 + 7 * 55),
                    f"C{_phantom.cost}MAX:{max_score}{t('分', locale)}",
                    SPECIAL_GOLD,
                    waves_font_18,
                    "rm",
                )

                phantom_temp.alpha_composite(sh_temp, dest=(30 + ((i + 1) % 3) * 385, 120 + ((i + 1) // 3) * 630))

        if phantom_score > 0:
            phantom_score = round(phantom_score, 2)
            if phantom_score > 249.9:
                phantom_score = 250.0
            _bg = get_total_score_bg(char_name, phantom_score, calc.calc_temp)
            sh_score_bg_c = Image.open(TEXT_PATH / f"sh_score_bg_{_bg}.png")
            score_temp = Image.new("RGBA", sh_score_bg_c.size)
            score_temp.alpha_composite(sh_score_bg_c)
            sh_score_c = Image.open(TEXT_PATH / f"sh_score_{_bg}.png")
            score_temp.alpha_composite(sh_score_c)
            score_temp_draw = ImageDraw.Draw(score_temp)

            draw_text_with_fallback(score_temp_draw, (180, 260), t("声骸评级", locale), GREY, waves_font_30 if locale == 'en' else waves_font_40, "mm")
            draw_text_with_fallback(score_temp_draw, (180, 380), f"{phantom_score:.2f}{t('分', locale)}", "white", waves_font_40, "mm")
            draw_text_with_fallback(score_temp_draw, (180, 440), t("声骸评分", locale), GREY, waves_font_30 if locale == 'en' else waves_font_40, "mm")
        else:
            abs_bg = Image.open(TEXT_PATH / "abs.png")
            score_temp = Image.new("RGBA", abs_bg.size)
            score_temp.alpha_composite(abs_bg)
            score_temp_draw = ImageDraw.Draw(score_temp)
            draw_text_with_fallback(score_temp_draw, (180, 130), t("暂无", locale), "white", waves_font_40, "mm")
            draw_text_with_fallback(score_temp_draw, (180, 380), f"- {t('分', locale)}", "white", waves_font_40, "mm")

        phantom_temp.alpha_composite(score_temp, dest=(30, 120))

        shuxing = f"{role_detail.role.attributeName}伤害加成"
        panel_data = calc.role_card if is_limit_query and calc.role_card else calc.phantom_card
        for mi, m in enumerate(ph_sort_name):
            for ni, name_default in enumerate(m):
                name, default_value = name_default
                if name == "属性伤害加成":
                    value = panel_data.get(shuxing, default_value)
                    prop_img = await get_attribute_prop(shuxing)
                    name_color, _ = get_valid_color(shuxing, value, calc.calc_temp)
                    name = t(shuxing, locale)
                else:
                    value = panel_data.get(name, default_value)
                    prop_img = await get_attribute_prop(name)
                    name_color, _ = get_valid_color(name, value, calc.calc_temp)
                    name = t(name, locale)
                prop_img = prop_img.resize((40, 40))
                ph_bg = ph_0.copy() if ni % 2 == 0 else ph_1.copy()
                ph_bg.alpha_composite(prop_img, (20, 32))
                ph_bg_draw = ImageDraw.Draw(ph_bg)

                draw_text_with_fallback(ph_bg_draw, (70, 50), f"{name[:12 if locale == 'en' else 6]}", name_color, waves_font_24, "lm")
                draw_text_with_fallback(ph_bg_draw, (350, 50), f"{value}", name_color, waves_font_24, "rm")

                right_image_temp.alpha_composite(ph_bg.resize((500, 125)), (0, (ni + mi * 4) * 70))

        ph_tips = ph_1.copy()
        ph_tips_draw = ImageDraw.Draw(ph_tips)
        draw_text_with_fallback(ph_tips_draw, (20, 50), t("评分模板", locale), "white", waves_font_24, "lm")
        draw_text_with_fallback(ph_tips_draw, (350, 50), t(calc.calc_temp['name'], locale, partial=True), (255, 255, 0), waves_font_24, "rm")
        phantom_temp.alpha_composite(ph_tips, (40 + 2 * 370, 45))

        if weight_modals:
            weight_temps = [
                (
                    get_calc_map(calc.phantom_card, role_detail.role.roleName, role_detail.role.roleId, opt["key"]),
                    opt["name"],
                )
                for opt in weight_modals
            ]
        else:
            weight_temps = [(calc.calc_temp, "")]

        for ti, (ct, modal_name) in enumerate(weight_temps):
            weight_rows = _build_weight_rows(ct, shuxing)
            weight_table = Image.new("RGBA", (1500, 880), (0, 0, 0, 0))
            weight_table = await draw_weight(weight_table, role_detail.role.roleName, weight_rows, ct, modal_name)
            img.alpha_composite(weight_table, (0, weight_base_y + ti * weight_block_h))

    char_bg = Image.open(TEXT_PATH / "char.png")
    img.paste(char_bg, (1100, 220), char_bg)
    img.paste(phantom_temp, (0, 1050), phantom_temp)
    img.paste(right_image_temp, (605, 225), right_image_temp)

    img = add_footer(img)
    img = await convert_img(img)
    return img


# ─── 综合评分: 最优声骸卡 / 词条收益渲染 ──────────────────────────────

_OPT_STAT_DEFS = [
    # (display_name, card_key, is_percent_decimal)
    ("攻击",             "攻击",              False),
    ("生命",             "生命",              False),
    ("防御",             "防御",              False),
    ("暴击",             "crit_rate",         True),
    ("暴击伤害",         "crit_dmg",          True),
    ("共鸣效率",         "energy_regen",      True),
    ("属性伤害加成",     "shuxing_bonus",     True),
    ("普攻伤害加成",     "attack_damage",     True),
    ("重击伤害加成",     "hit_damage",        True),
    ("共鸣技能伤害加成", "skill_damage",      True),
    ("共鸣解放伤害加成", "liberation_damage", True),
]


_FLAT_SUB_NAMES = {"攻击", "生命", "防御"}


def _fmt_opt_val(name: str, value: float) -> str:
    """格式化 OptimalSlot 的词条值: flat 类显示整数, 其余显示 x.x%"""
    if name in _FLAT_SUB_NAMES:
        return str(int(round(value)))
    return f"{value:.1f}%"


def _render_optimal_phantom_card(slot) -> Image.Image:
    """渲染单张最优声骸卡片 (350×550), 不显示 score."""
    sh_temp = Image.new("RGBA", (350, 550))
    sh_bg = Image.open(TEXT_PATH / "sh_bg.png")
    sh_temp.alpha_composite(sh_bg, dest=(0, 0))

    sh_title = Image.open(TEXT_PATH / "sh_title_s.png")
    sh_temp.alpha_composite(sh_title, dest=(0, 0))

    draw = ImageDraw.Draw(sh_temp)

    # COST 星形图标
    promote_icon_raw = Image.open(TEXT_PATH / "promote_icon.png")
    promote_icon = promote_icon_raw.resize((24, 24))
    for idx in range(slot.cost):
        sh_temp.alpha_composite(promote_icon, dest=(10 + 26 * idx, 8))

    # "推荐声骸" 标题
    draw_text_with_fallback(draw, (10, 38), "推荐声骸", SPECIAL_GOLD, waves_font_20, "lm")

    # 主词条 1
    y_main = 90
    main1_val_str = f"{slot.main1_value_pct:.1f}%"
    draw_text_with_fallback(draw, (10, y_main), slot.main1_name, "white", waves_font_22, "lm")
    draw_text_with_fallback(draw, (340, y_main), main1_val_str, SPECIAL_GOLD, waves_font_22, "rm")

    # 主词条 2
    y_main2 = y_main + 45
    main2_val_str = _fmt_opt_val(slot.main2_name, slot.main2_value_flat)
    draw_text_with_fallback(draw, (10, y_main2), slot.main2_name, "white", waves_font_22, "lm")
    draw_text_with_fallback(draw, (340, y_main2), main2_val_str, SPECIAL_GOLD, waves_font_22, "rm")

    # 分隔线
    draw.line([(10, y_main2 + 25), (340, y_main2 + 25)], fill=(255, 255, 255, 80), width=1)

    # 副词条 (最多 5 个)
    y_sub0 = y_main2 + 40
    sub_gap = 52
    for si, (sname, sval) in enumerate(slot.subs[:5]):
        ys = y_sub0 + si * sub_gap
        sub_val_str = _fmt_opt_val(sname, sval)
        draw_text_with_fallback(draw, (10, ys), sname, (200, 200, 200, 255), waves_font_20, "lm")
        draw_text_with_fallback(draw, (340, ys), sub_val_str, "white", waves_font_20, "rm")

    return sh_temp


def _compute_panel_diffs(user_card, best_card, top_n=8):
    out = []
    for name, key, is_pct in _OPT_STAT_DEFS:
        try:
            u = float(str(user_card.get(key, 0)).replace("%", ""))
            b = float(str(best_card.get(key, 0)).replace("%", ""))
        except (TypeError, ValueError):
            continue
        delta = b - u
        if abs(delta) < 1e-6:
            continue
        if is_pct:
            user_str = f"{u*100:.1f}%"
            best_str = f"{b*100:.1f}%"
            delta_str = f"{delta*100:+.1f}%"
            rank = abs(delta) * 100
        else:
            user_str = f"{int(u)}"
            best_str = f"{int(b)}"
            delta_str = f"{int(delta):+d}"
            rank = abs(delta) / 100.0
        out.append((name, user_str, best_str, delta_str, delta > 0, rank))
    out.sort(key=lambda r: r[5], reverse=True)
    return out[:top_n]


async def ph_card_draw_optimal(
    score_report,
    calc,
    role_detail: RoleDetailData,
    ph_sum_value: int = 250,
    locale: str = "",
):
    """最优声骸区域: ph_card_draw 布局, 声骸卡使用 best_loadout, 评分槽显示培养目标 (SSS/150)."""
    best_loadout = getattr(score_report, "best_loadout", None) or []
    equipPhantomList = (
        role_detail.phantomData.equipPhantomList
        if role_detail.phantomData and role_detail.phantomData.equipPhantomList
        else []
    )

    phantom_temp = Image.new("RGBA", (1200, 1280 + ph_sum_value))
    banner3 = Image.open(TEXT_PATH / "banner3.png")
    phantom_temp.alpha_composite(banner3, dest=(0, 0))

    # "声骸培养目标参考" 标题条 (复用 damage_bar1)
    _tt_w = 500
    target_title = damage_bar1.copy().resize((_tt_w, damage_bar1.height))
    target_title_draw = ImageDraw.Draw(target_title)
    draw_text_with_fallback(
        target_title_draw, (_tt_w // 2, 50),
        t("声骸培养目标参考", locale),
        SPECIAL_GOLD, waves_font_30, "mm",
    )
    phantom_temp.alpha_composite(target_title, dest=((1200 - _tt_w) // 2, 85))

    ph_0 = Image.open(TEXT_PATH / "ph_0.png")
    ph_1 = Image.open(TEXT_PATH / "ph_1.png")

    async def _draw_best_card(i, slot):
        sh_temp = Image.new("RGBA", (350, 550))
        sh_temp_draw = ImageDraw.Draw(sh_temp)
        sh_bg = Image.open(TEXT_PATH / "sh_bg.png")
        sh_temp.alpha_composite(sh_bg, dest=(0, 0))

        # 优化卡顶栏统一用 S 级 (不算 score, 视觉中性)
        sh_title = Image.open(TEXT_PATH / "sh_title_s.png")
        sh_temp.alpha_composite(sh_title, dest=(0, 0))

        real_phantom = equipPhantomList[i] if i < len(equipPhantomList) else None
        if real_phantom and real_phantom.phantomProp:
            phantom_icon = await get_phantom_img(
                real_phantom.phantomProp.phantomId, real_phantom.phantomProp.iconUrl
            )
            fetter_icon = await get_attribute_effect(real_phantom.fetterDetail.name)
            fetter_icon = fetter_icon.resize((50, 50))
            phantom_icon.alpha_composite(fetter_icon, dest=(205, 0))
            phantom_icon = phantom_icon.resize((100, 100))
            sh_temp.alpha_composite(phantom_icon, dest=(20, 20))
            phantomName = t(real_phantom.phantomProp.name, locale).replace("·", " ").replace("（", " ").replace("）", "")
            short_name = phantomName if locale == "en" else get_short_name(real_phantom.phantomProp.phantomId, phantomName)
            draw_text_with_fallback(sh_temp_draw, (130, 40), f"{short_name}", SPECIAL_GOLD, waves_font_28, "lm")
        else:
            draw_text_with_fallback(sh_temp_draw, (130, 40), t("推荐声骸", locale), SPECIAL_GOLD, waves_font_28, "lm")

        _tpl_w = 175 if locale == "en" else 150
        tpl_badge = Image.new("RGBA", (_tpl_w, 30), (255, 255, 255, 0))
        tpl_badge_draw = ImageDraw.Draw(tpl_badge)
        tpl_badge_draw.rounded_rectangle([0, 0, _tpl_w, 30], radius=8, fill=(0, 0, 0, int(0.8 * 255)))
        draw_text_with_fallback(tpl_badge_draw, (_tpl_w // 2, 15), f"Lv.25 {t('模板声骸', locale)}", "white", waves_font_18, "mm")
        sh_temp.alpha_composite(tpl_badge, (128, 58))

        for ci in range(slot.cost):
            promote_icon = Image.open(TEXT_PATH / "promote_icon.png").resize((30, 30))
            sh_temp.alpha_composite(promote_icon, dest=(128 + 30 * ci, 90))

        props_display = []
        main1_val_str = f"{slot.main1_value_pct:.1f}%"
        props_display.append((slot.main1_name, main1_val_str))
        main2_val_str = _fmt_opt_val(slot.main2_name, slot.main2_value_flat)
        props_display.append((slot.main2_name, main2_val_str))
        for sname, sval in list(slot.subs)[:5]:
            props_display.append((sname, _fmt_opt_val(sname, float(str(sval).replace("%", "")))))

        for index, (prop_attr_name, prop_val_str) in enumerate(props_display[:7]):
            oset = 55
            prop_img = await get_attribute_prop(prop_attr_name)
            prop_img = prop_img.resize((40, 40))
            sh_temp.alpha_composite(prop_img, (15, 167 + index * oset))
            sh_temp_draw = ImageDraw.Draw(sh_temp)
            name_color = "white"
            if index > 1:
                # OptimalSlot.subs 名字带 "%" (e.g. "攻击%"), 但 calc.json 的 valid_s 通常存
                # bare 名 ("攻击"), 所以这里去掉 "%" 再查表
                name_color, _ = get_valid_color(prop_attr_name.rstrip("%"), prop_val_str, calc.calc_temp)
            _prop_display = t(prop_attr_name.rstrip("%"), locale, partial=True)
            draw_text_with_fallback(
                sh_temp_draw,
                (60, 187 + index * oset),
                f"{_prop_display[:12 if locale == 'en' else 6]}",
                name_color,
                waves_font_24,
                "lm",
            )
            draw_text_with_fallback(
                sh_temp_draw,
                (343, 187 + index * oset),
                f"{prop_val_str}",
                name_color,
                waves_font_24,
                "rm",
            )

        return sh_temp

    for i, slot in enumerate(best_loadout[:5]):
        sh_temp = await _draw_best_card(i, slot)
        phantom_temp.alpha_composite(
            sh_temp,
            dest=(
                30 + ((i + 1) % 3) * 385,
                120 + ph_sum_value + ((i + 1) // 3) * 600,
            ),
        )

    grade = "sss"
    sh_score_bg_c = Image.open(TEXT_PATH / f"sh_score_bg_{grade}.png")
    score_temp = Image.new("RGBA", sh_score_bg_c.size)
    score_temp.alpha_composite(sh_score_bg_c)
    sh_score_c = Image.open(TEXT_PATH / f"sh_score_{grade}.png")
    score_temp.alpha_composite(sh_score_c)
    score_temp_draw = ImageDraw.Draw(score_temp)
    draw_text_with_fallback(score_temp_draw, (180, 260), t("综合评级", locale), GREY, waves_font_30 if locale == "en" else waves_font_40, "mm")
    draw_text_with_fallback(score_temp_draw, (180, 380), f"150.00{t('分', locale)}", "white", waves_font_40, "mm")
    draw_text_with_fallback(score_temp_draw, (180, 440), t("综合评分", locale), GREY, waves_font_30 if locale == "en" else waves_font_40, "mm")
    phantom_temp.alpha_composite(score_temp, dest=(30, 120 + ph_sum_value))

    return phantom_temp


_SCORE_RULE_TITLE = "综合评分规则"
_SCORE_RULE_LINES = (
    "以2-3分钟的常规队伍循环为基础，根据当前套装和装备求解得到最优期望伤害的词条作为基准计分",
    "由于共鸣效率会影响限定时间内循环次数，作为分段的独立乘区。单通等特殊场景不适用综合评分",
    "显示的共鸣效率部分建议仅对于循环流畅度考虑，共效挂钩的加成等会另外计算收益得分",
    "最优面板共效可能由于词条取最大值导致偏高，请折算为常见效率词条数值",
    "部分角色4c可能显示为攻击，该计算基于副词条双爆满值，请根据实际情况进行搭配",
    "仅针对常见队伍和流程，请以实际情况为准。如有建议请联系开发者提供反馈",
)


def _wrap_plain(text: str, cjk_chars: int) -> List[str]:
    """按宽度折行。cjk_chars 是 CJK 字数预算; 含空格的拉丁文本字宽约为 CJK 的一半,
    故按词折行时预算翻倍。"""
    if not text:
        return [""]
    if " " in text:
        max_chars = cjk_chars * 2
        words = text.split(" ")
        lines: List[str] = []
        cur = ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_chars:
                lines.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}" if cur else w
        if cur:
            lines.append(cur)
        return lines
    return [text[i:i + cjk_chars] for i in range(0, len(text), cjk_chars)]


async def draw_char_optimize_img(ev: Event, uid: str, char: str, user_id: str, waves_id: Optional[str] = None, change_list_regex: Optional[str] = None, is_limit_query=False):
    """综合评分优化建议图: 复用无评分面板布局, 仅替换声骸评分槽/声骸卡和底部说明行.
    支持替换指令(换角色X链/换声骸…), 优化结果基于替换后的配置.
    is_limit_query=True 时基于角色极限面板出优化建议, 不读账号/CK."""
    locale = await WavesLangSettings.get_lang(ev.user_id)
    user_pref = await get_hide_uid_pref(waves_id or uid, user_id, ev.bot_id)

    char_id = char_name_to_char_id(char)
    if not char_id or len(char_id) != 4 or not char_id.isdigit():
        return "未找到指定角色, 请检查输入是否正确！"
    char_name = alias_to_char_name(char)

    scoreDetail = ScoreDetailRegister.find_class(char_id)
    if not scoreDetail:
        return f"[鸣潮] {char_name} 暂无综合评分"

    # ── 布局常量 (优化图: phantom_temp 顶部留 60px 给 "声骸培养目标参考" 标题条) ──
    ph_sum_value = 60
    jineng_len = 180
    echo_list = 1400
    score_offset = 115
    bar_shift = 25
    jineng_len += score_offset + bar_shift

    # ── 账户 / CK ────────────────────────────────────────────────────────
    if waves_id:
        uid = waves_id

    ck = ""
    force_resource_id = None
    if not is_limit_query:
        info, ck, _ = await base_info_cache.load_account_context(
            uid, user_id, ev.bot_id, force_ck=bool(waves_id)
        )
        if isinstance(info, str):
            # ck 也失败 → 返错误; ck 有效但 baseinfo 失败 → 降级出图
            if not ck:
                return info
            account_info = None
        else:
            account_info = info
    else:
        account_info = AccountBaseInfo.model_validate(
            {
                "name": "库洛交个朋友",
                "id": uid,
                "level": 100,
                "worldLevel": 10,
                "creatTime": 1739375719,
            }
        )
        force_resource_id = char_id

    # ── 获取数据 ─────────────────────────────────────────────────────────
    avatar, role_detail = await get_role_need(
        ev, char_id, ck, uid, char_name, waves_id,
        force_resource_id=force_resource_id, is_limit_query=is_limit_query,
        change_list_regex=change_list_regex,
    )
    if isinstance(role_detail, str):
        return role_detail

    enemy_detail: Optional[EnemyDetailData] = EnemyDetailData()

    # ── 替换指令 (换角色X链 / 换声骸… → 改写 role_detail, 优化基于替换后配置) ──
    change_command = ""
    if change_list_regex:
        _temp = copy.deepcopy(role_detail)
        try:
            role_detail, change_command = await change_role_detail(
                uid, ck, role_detail, enemy_detail, change_list_regex,
                user_id=str(user_id), bot_id=ev.bot_id,
            )
            if change_command and change_command.startswith("[鸣潮]"):
                return change_command
        except Exception as e:
            logger.exception("[鸣潮·角色面板渲染] 角色数据转换错误", e)
            role_detail = _temp

    pd = role_detail.phantomData
    eq_list = pd.equipPhantomList if pd else None
    if not eq_list or sum(1 for p in eq_list if p and getattr(p, "phantomProp", None)) < 5:
        return f"[鸣潮] {char_name} 声骸件数不足, 暂无优化建议"

    from .role_info_change import is_phantom_dirty

    # ── 声骸计算 (先跑 calc, 再用其数据渲染最优卡) ──
    calc, _phantom_temp_unused, _phantom_score = await ph_card_draw(
        ph_sum_value, role_detail, False, change_command, enemy_detail, False, locale,
        phantom_dirty=is_phantom_dirty(change_command),
    )
    calc.role_card = calc.enhance_summation_card_value(calc.phantom_card)

    # ── 综合评分 ──────────────────────────────────────────────────────────
    score_report = None
    if role_detail.phantomData and role_detail.phantomData.equipPhantomList:
        try:
            score_calc = scoreDetail[0] if isinstance(scoreDetail, list) else scoreDetail
            score_title = score_calc.get("title", f"综合评分-{char_name}")
            setattr(calc, "_score_title", score_title)
            score_report = score_calc["func"](calc, role_detail)
            if score_report is not None:
                logger.info(
                    f"[鸣潮·优化] {score_title}: {score_report.score:.1f}/150"
                )
        except Exception as e:
            logger.warning(f"[鸣潮·优化] {char_name} 计算失败: {e}")

    if score_report is None:
        return f"[鸣潮] {char_name} 优化计算失败，请检查服务器连接状态"

    partials = sorted(
        [
            (name, float(value))
            for name, value in (getattr(score_report, "partials", None) or {}).items()
            if abs(float(value)) > 1e-9
        ],
        key=lambda item: item[1],
        reverse=True,
    )
    def _loc_stat(name: str) -> str:
        base = t(name.rstrip("%"), locale, partial=True)
        return f"{base}%" if name.endswith("%") else base

    # 仅本人查询展示建议方向, 他人/特征码查询隐藏
    is_self = not waves_id and user_id == ev.user_id
    score_rows = []
    _pm = getattr(score_report, "partial_max", None)
    dirs = [_pm[0]] if _pm else []
    if dirs and is_self:
        rec = " / ".join(_loc_stat(d) for d in dirs)
        score_rows.append((t("建议提升词条方向", locale), rec))
    # 词条收益拆分成 3 项/行, 防止单行塞不下
    if partials:
        per_row = 3
        chunks = [partials[i:i + per_row] for i in range(0, len(partials), per_row)]
        for ci, group in enumerate(chunks):
            label = t("词条提升收益情况", locale) if ci == 0 else ""
            text = "    ".join(f"{_loc_stat(name)} {value:+.1f}" for name, value in group)
            score_rows.append((label, text))
    else:
        score_rows.append((t("词条提升收益情况", locale), t("暂无", locale)))
    score_rows.extend(
        (t("备注", locale), t(str(note), locale, partial=True))
        for note in (getattr(score_report, "notes", None) or [])
    )
    # 评分规则说明 (自绘圆角面板, 折行后逐行渲染)
    rule_lines = []
    for _s in _SCORE_RULE_LINES:
        rule_lines.extend(_wrap_plain(t(_s, locale), 46))
    _RULE_GAP = 24
    _RULE_TITLE_H = 58
    _RULE_LINE_H = 40
    rule_panel_h = _RULE_TITLE_H + 14 + len(rule_lines) * _RULE_LINE_H + 18
    # score 区: 标题条(100 高) + N 行(行距 60), 末行底部 = score_y + N*60 + 100
    _score_area_h = len(score_rows) * 60 + 100
    dd_len = _score_area_h + _RULE_GAP + rule_panel_h + 40

    # ── 背景 ──────────────────────────────────────────────────────────────
    img = await get_card_bg(1200, 1250 + echo_list + ph_sum_value + jineng_len + dd_len, "bg3")

    # ── 固定区域 (头像/title bar/立绘/角色名 Lv/元素/武器型 等) ──
    await draw_fixed_img(img, avatar, account_info, role_detail, locale, uid=uid, char_name=char_name, user_pref=user_pref)

    # ── 最优声骸区域 ──
    phantom_temp = await ph_card_draw_optimal(
        score_report, calc, role_detail, ph_sum_value, locale
    )
    img.paste(phantom_temp, (0, 1320 + jineng_len), phantom_temp)

    # ── 右侧属性/武器区 ───────────────────────────────────────────────────
    right_image_temp = Image.new("RGBA", (600, 1100))

    right_prop_y = 100
    right_weapon_banner_y = 620
    weapon_name_y = 780
    weapon_bg_y = 750

    # 武器 banner
    banner2 = Image.open(TEXT_PATH / "banner2.png")
    right_image_temp.alpha_composite(banner2, dest=(-9, right_weapon_banner_y))

    # 武器底板
    skill_branch = role_detail.get_skill_branch()
    if skill_branch:
        weapon_bg = Image.open(TEXT_PATH / "weapon_branch_bg.png")
    else:
        weapon_bg = Image.open(TEXT_PATH / "weapon_bg.png")

    weapon_bg_temp = Image.new("RGBA", right_image_temp.size)
    weapon_bg_temp.alpha_composite(weapon_bg, dest=(0, weapon_bg_y))

    weaponData: WeaponData = role_detail.weaponData
    weapon_icon = await get_square_weapon(weaponData.weapon.weaponId)
    weapon_icon = crop_center_img(weapon_icon, 110, 110)
    weapon_icon_bg = get_weapon_icon_bg(weaponData.weapon.weaponStarLevel, TEXT_PATH)
    weapon_icon_bg.paste(weapon_icon, (10, 20), weapon_icon)

    weapon_bg_temp_draw = ImageDraw.Draw(weapon_bg_temp)
    _weapon_name_width = draw_text_with_fallback(weapon_bg_temp_draw, (200, weapon_name_y), t(weaponData.weapon.weaponName, locale), SPECIAL_GOLD, waves_font_40, "lm")
    draw_text_with_fallback(weapon_bg_temp_draw, (203, weapon_name_y + 45), f"Lv.{weaponData.level}/90", "white", waves_font_30, "lm")

    _x = min(int(200 + _weapon_name_width + 20), weapon_bg.width - 50)
    _y = weapon_name_y + 7
    wrc_fill = WEAPON_RESONLEVEL_COLOR[weaponData.resonLevel] + (int(0.8 * 255),)
    weapon_bg_temp_draw.rounded_rectangle([_x - 15, _y - 15, _x + 50, _y + 15], radius=7, fill=wrc_fill)
    draw_text_with_fallback(weapon_bg_temp_draw, (_x, _y), _weapon_reson_text(weaponData.resonLevel, locale), "white", waves_font_24, "lm")

    weapon_breach = get_breach(weaponData.breach, weaponData.level)
    for i in range(0, weapon_breach):
        promote_icon = Image.open(TEXT_PATH / "promote_icon.png")
        weapon_bg_temp.alpha_composite(promote_icon, dest=(200 + 40 * i, weapon_name_y + 70))

    weapon_bg_temp.alpha_composite(weapon_icon_bg, dest=(45, weapon_name_y - 30))

    weapon_detail: WavesWeaponResult = get_weapon_detail(
        weaponData.weapon.weaponId,
        weaponData.level,
        weaponData.breach,
        weaponData.resonLevel,
    )
    stats_main = await get_attribute_prop(weapon_detail.stats[0]["name"])
    stats_main = stats_main.resize((40, 40))
    weapon_bg_temp.alpha_composite(stats_main, (65, weapon_bg_y + 187))
    stats_sub = await get_attribute_prop(weapon_detail.stats[1]["name"])
    stats_sub = stats_sub.resize((40, 40))
    weapon_bg_temp.alpha_composite(stats_sub, (65, weapon_bg_y + 237))

    _ws0_name = t(weapon_detail.stats[0]["name"], locale, partial=True)
    _ws1_name = t(weapon_detail.stats[1]["name"], locale, partial=True)
    if skill_branch:
        draw_text_with_fallback(weapon_bg_temp_draw, (115, weapon_bg_y + 207), _ws0_name, "white", waves_font_30, "lm")
        draw_text_with_fallback(weapon_bg_temp_draw, (115, weapon_bg_y + 257), _ws1_name, "white", waves_font_30, "lm")
        draw_text_with_fallback(weapon_bg_temp_draw, (115 + 300, weapon_bg_y + 207), f"{weapon_detail.stats[0]['value']}", "white", waves_font_30, "rm")
        draw_text_with_fallback(weapon_bg_temp_draw, (115 + 300, weapon_bg_y + 257), f"{weapon_detail.stats[1]['value']}", "white", waves_font_30, "rm")
        active_skill = await get_attribute_skill(skill_branch.branchName, locale)
        active_skill = active_skill.resize((100, 100))
        weapon_bg_temp.alpha_composite(active_skill, dest=(500 - 50, weapon_bg_y + 232 - 50))
    else:
        draw_text_with_fallback(weapon_bg_temp_draw, (130, weapon_bg_y + 207), _ws0_name, "white", waves_font_30, "lm")
        draw_text_with_fallback(weapon_bg_temp_draw, (130, weapon_bg_y + 257), _ws1_name, "white", waves_font_30, "lm")
        draw_text_with_fallback(weapon_bg_temp_draw, (500, weapon_bg_y + 207), f"{weapon_detail.stats[0]['value']}", "white", waves_font_30, "rm")
        draw_text_with_fallback(weapon_bg_temp_draw, (500, weapon_bg_y + 257), f"{weapon_detail.stats[1]['value']}", "white", waves_font_30, "rm")

    right_image_temp.alpha_composite(weapon_bg_temp, dest=(0, 0))

    # ── 命座 (mz_temp) ────────────────────────────────────────────────────
    mz_temp = Image.new("RGBA", (1200, 300))
    shuxing_color = WAVES_SHUXING_MAP[role_detail.role.attributeName]
    for i, _mz in enumerate(role_detail.chainList):
        mz_bg = Image.open(TEXT_PATH / "mz_bg.png")
        mz_bg_temp = Image.new("RGBA", mz_bg.size)
        mz_bg_temp_draw = ImageDraw.Draw(mz_bg_temp)
        chain = await get_chain_img(role_detail.role.roleId, _mz.order, _mz.iconUrl)
        chain = chain.resize((100, 100))
        mz_bg.paste(chain, (95, 75), chain)
        mz_bg_temp.alpha_composite(mz_bg, dest=(0, 0))
        if _mz.unlocked:
            mz_bg_temp = await change_color(mz_bg_temp, shuxing_color)
        name = re.sub(r'[",，]+', "", _mz.name) if _mz.name else ""
        name = t(name, locale, partial=True)
        if locale == "en" and len(name) > 14 and " " in name:
            mid = len(name) // 2
            left = name.rfind(" ", 0, mid)
            right = name.find(" ", mid)
            if left == -1:
                split_pos = right
            elif right == -1:
                split_pos = left
            else:
                split_pos = left if (mid - left) <= (right - mid) else right
            name = name[:split_pos] + "\n" + name[split_pos + 1:]
        if len(name) >= 8:
            draw_text_with_fallback(mz_bg_temp_draw, (147, 230), name, "white", waves_font_16, "mm")
        else:
            draw_text_with_fallback(mz_bg_temp_draw, (147, 230), name, "white", waves_font_20, "mm")
        if not _mz.unlocked:
            mz_bg_temp = ImageEnhance.Brightness(mz_bg_temp).enhance(0.3)
        mz_temp.alpha_composite(mz_bg_temp, dest=(i * 190, 0))
    img.paste(mz_temp, (0, 1080 + jineng_len), mz_temp)

    # ── 底部建议/收益条 (复用 damage 表 (400,rm)+(850,mm) + waves_font_24 样式) ──
    score_y = 2600 + ph_sum_value + jineng_len
    title_bg = damage_bar1.copy()
    title_bg_draw = ImageDraw.Draw(title_bg)
    draw_text_with_fallback(
        title_bg_draw, (600, 50),
        f"{t(char_name, locale)} {t('综合评分', locale)} {score_report.score:.1f} / 150",
        SPECIAL_GOLD, waves_font_30, "mm",
    )
    img.alpha_composite(title_bg, dest=(0, score_y))
    for dindex, (left, right) in enumerate(score_rows):
        damage_bar = damage_bar2.copy() if dindex % 2 == 0 else damage_bar1.copy()
        damage_bar_draw = ImageDraw.Draw(damage_bar)
        draw_text_with_fallback(damage_bar_draw, (300, 50), left, "white", waves_font_24, "rm")
        draw_text_with_fallback(damage_bar_draw, (700, 50), right, "white", waves_font_24, "mm")
        img.alpha_composite(damage_bar, dest=(0, score_y + (dindex + 1) * 60))

    # ── 评分规则说明 (自绘半透明圆角面板) ──
    rules_y = score_y + _score_area_h + _RULE_GAP
    _rule_w = 1140
    rule_panel = Image.new("RGBA", (_rule_w, rule_panel_h), (0, 0, 0, 0))
    rp_draw = ImageDraw.Draw(rule_panel)
    rp_draw.rounded_rectangle(
        [0, 0, _rule_w - 1, rule_panel_h - 1], radius=20, fill=(0, 0, 0, 110)
    )
    draw_text_with_fallback(
        rp_draw, (40, _RULE_TITLE_H // 2 + 4),
        t(_SCORE_RULE_TITLE, locale, partial=True),
        SPECIAL_GOLD, waves_font_28, "lm",
    )
    draw_text_with_fallback(
        rp_draw, (_rule_w - 40, _RULE_TITLE_H // 2 + 4),
        f"{t('评分细则请发送', locale)} {PREFIX}综合评分说明",
        SPECIAL_GOLD, waves_font_28, "rm",
    )
    rp_draw.line(
        [(40, _RULE_TITLE_H), (_rule_w - 40, _RULE_TITLE_H)],
        fill=(255, 255, 255, 45), width=2,
    )
    for li, line in enumerate(rule_lines):
        draw_text_with_fallback(
            rp_draw, (40, _RULE_TITLE_H + 14 + li * _RULE_LINE_H + _RULE_LINE_H // 2),
            line, GREY, waves_font_22, "lm",
        )
    img.alpha_composite(rule_panel, dest=(30, rules_y))

    # ── 右侧 banner1 + 单列 prop_bg_single (与最优 panel 的 diff) ─────────
    banner1 = Image.open(TEXT_PATH / "banner4.png")
    right_image_temp.alpha_composite(banner1, dest=(-9, 0))

    sh_bg = Image.open(TEXT_PATH / "prop_bg_single.png")
    sh_bg_draw = ImageDraw.Draw(sh_bg)

    shuxing = f"{role_detail.role.attributeName}伤害加成"
    best_card = getattr(score_report, "best_card", None) or {}

    def _pct(v):
        try:
            return float(str(v).replace("%", ""))
        except (ValueError, TypeError):
            return 0.0

    _last_slot_candidates = (
        "治疗效果加成",
        "普攻伤害加成",
        "重击伤害加成",
        "共鸣技能伤害加成",
        "共鸣解放伤害加成",
    )
    _last_slot_name = max(
        _last_slot_candidates,
        key=lambda k: _pct(calc.role_card.get(k, "0")),
    )
    # 优化图: 跳过 谐度破坏增幅 / 偏谐值累积效率 (tune-break, 不进综合评分), 留 8 项单列
    _skip_in_optimize = {"谐度破坏增幅", "偏谐值累积效率"}
    panel_items = [(n, d) for (n, d) in card_sort_name[:-1] if n not in _skip_in_optimize]
    panel_items.append((_last_slot_name, "0.0%"))

    # 按 delta 降序 (非绝对值, 否则生命减项会靠前)
    rows = []
    for name, default_value in panel_items:
        if name == "属性伤害加成":
            key = shuxing
            display_name = t(shuxing, locale)
        else:
            key = name
            display_name = t(name, locale)
        value = calc.role_card.get(key, default_value)
        best_value = best_card.get(key, value)
        try:
            cur_n = float(str(value).replace("%", ""))
            best_n = float(str(best_value).replace("%", ""))
            delta = best_n - cur_n
        except (TypeError, ValueError):
            delta = 0.0
        is_pct = "%" in str(value) or "%" in str(best_value)
        if abs(delta) < 1e-6:
            delta_str = ""
        elif is_pct:
            delta_str = f"{delta:+.1f}%"
        else:
            delta_str = f"{int(round(delta)):+d}"
        delta_color = SPECIAL_GOLD if delta > 0 else GREY
        rows.append({
            "key": key, "name": display_name, "current": str(value), "best": str(best_value),
            "delta": delta, "delta_str": delta_str, "delta_color": delta_color,
        })

    rows.sort(key=lambda r: r["delta"], reverse=True)

    for idx, row in enumerate(rows[:8]):
        y = 40 + idx * 55
        prop_img = (await get_attribute_prop(row["key"])).resize((40, 40))
        sh_bg.alpha_composite(prop_img, (65, y))
        val_text = f"{row['current']} → {row['best']}"
        name_text = row["name"]
        if locale == "en":  # 英文名较长, 截断防与右侧数值重合
            name_max_w = 480 - waves_font_20.getlength(val_text) - 20 - 120
            if waves_font_24.getlength(name_text) > name_max_w:
                while name_text and waves_font_24.getlength(name_text + "…") > name_max_w:
                    name_text = name_text[:-1]
                name_text = name_text.rstrip() + "…"
        draw_text_with_fallback(sh_bg_draw, (120, y + 18), name_text, "white", waves_font_24, "lm")
        draw_text_with_fallback(
            sh_bg_draw, (480, y + 18),
            val_text,
            "white", waves_font_20, "rm",
        )
        if row["delta_str"]:
            draw_text_with_fallback(
                sh_bg_draw, (578, y + 18),
                row["delta_str"], row["delta_color"], waves_font_20, "rm",
            )

    right_image_temp.alpha_composite(sh_bg, dest=(0, right_prop_y))
    img.paste(right_image_temp, (570, 200 + bar_shift), right_image_temp)

    # ── 技能条 (skill_bar) ────────────────────────────────────────────────
    skill_bar = Image.open(TEXT_PATH / "skill_bar.png")
    skill_bg_1 = Image.open(TEXT_PATH / "skill_bg.png")
    temp_i = 0
    for _, _skill in enumerate(role_detail.get_skill_list()):
        if _skill.skill.type in ["延奏技能", "谐度破坏"]:
            continue
        skill_bg = skill_bg_1.copy()
        skill_img = await get_skill_img(role_detail.role.roleId, _skill.skill.name, _skill.skill.iconUrl)
        skill_img = skill_img.resize((70, 70))
        skill_bg.paste(skill_img, (57, 65), skill_img)
        skill_bg_draw = ImageDraw.Draw(skill_bg)
        _skill_font = waves_font_18 if locale == "en" else waves_font_25
        draw_text_with_fallback(skill_bg_draw, (150, 83), t(_skill.skill.type, locale), "white", _skill_font, "lm")
        draw_text_with_fallback(skill_bg_draw, (150, 113), f"Lv.{_skill.level}", "white", waves_font_25, "lm")
        skill_bg_temp = Image.new("RGBA", skill_bg.size)
        skill_bg_temp = Image.alpha_composite(skill_bg_temp, skill_bg)
        _x = 20 + temp_i * 215
        _y = -20
        skill_bar.alpha_composite(skill_bg_temp, dest=(_x, _y))
        temp_i += 1
    img.alpha_composite(skill_bar, dest=(0, 1150 + score_offset + bar_shift))

    # 综合评分块: 立绘下方 / skill_bar 上方 (与面板一致)
    grade = get_panel_score_grade(score_report.score)
    grade_icon = Image.open(TEXT_PATH / f"panel_score_{grade}.png")
    grade_icon = grade_icon.resize((200, 200))
    img.alpha_composite(grade_icon, dest=(90, 1080 + bar_shift))
    score_draw = ImageDraw.Draw(img)
    draw_text_with_fallback(score_draw, (400, 1140 + bar_shift), f"{score_report.score:.2f}", "white", waves_font_40, "mm")
    draw_text_with_fallback(score_draw, (400, 1210 + bar_shift), t("综合评分", locale), GREY, waves_font_40, "mm")

    img = add_footer(img)
    img = await convert_img(img)
    return img



def _build_weight_rows(calc_temp, shuxing):
    weight_list_temp = weight_list.copy()
    entry_type_list = weight_list_temp[0].split(",")[1:]
    main_props = calc_temp["main_props"]
    sub_pros = calc_temp["sub_props"]
    skill_weight = calc_temp["skill_weight"]
    for i, entry in enumerate(weight_list_temp[1:], start=1):
        entry_list = []
        if entry == "属性伤害加成":
            entry_list.append(f"{shuxing}")
        elif "%" in entry:
            entry_list.append(entry.replace("%", "百分比"))
        else:
            entry_list.append(entry)
        for entry_type in entry_type_list:
            if "主词条权重" in entry_type:
                cost = re.search(r"C(\d+)主词条权重", entry_type).group(1)  # type: ignore
                pros_temp = main_props.get(str(cost))
            else:
                pros_temp = sub_pros

            if entry == "普攻伤害加成":
                value = pros_temp.get("技能伤害加成", 0) * skill_weight[0]
            elif entry == "重击伤害加成":
                value = pros_temp.get("技能伤害加成", 0) * skill_weight[1]
            elif entry == "共鸣技能伤害加成":
                value = pros_temp.get("技能伤害加成", 0) * skill_weight[2]
            elif entry == "共鸣解放伤害加成":
                value = pros_temp.get("技能伤害加成", 0) * skill_weight[3]
            else:
                value = pros_temp.get(entry, 0)

            if value == 0:
                value = "-"
            else:
                value = f"{value:.3f}"
            entry_list.append(value)
        weight_list_temp[i] = ",".join(entry_list)
    return weight_list_temp


@to_thread
def draw_weight(image, role_name, weight_list_temp, calc_temp, modal_name=""):
    draw = ImageDraw.Draw(image)
    draw.rectangle([10, 10, 1490, 870], fill=(0, 0, 0, int(0.7 * 255)))

    # 设置表格参数
    cell_width = 230
    cell_height = 40
    start_x, start_y = 25, 80

    # 绘制表格
    for i, row in enumerate(weight_list_temp):
        for j, cell in enumerate(row.split(",")):
            x = start_x + j * cell_width
            y = start_y + i * cell_height

            # 绘制单元格背景
            if i == 0:  # 标题行
                draw.rectangle([x, y, x + cell_width, y + cell_height], fill=(0, 0, 0, 90))
            elif i % 2 == 1:  # 奇数行
                draw.rectangle([x, y, x + cell_width, y + cell_height], fill=(255, 255, 255, 30))
            else:  # 偶数行
                draw.rectangle([x, y, x + cell_width, y + cell_height], fill=(0, 0, 0, 90))

            # 绘制文字
            font = waves_font_24 if i == 0 else waves_font_20
            left, top, right, bottom = font.getbbox(cell)
            text_width = right - left
            text_height = bottom - top
            text_x = x + (cell_width - text_width) / 2
            text_y = y + (cell_height - text_height) / 2

            if i == 0:
                color = "white"
            else:
                if j == 0:
                    name_color, _ = get_valid_color(cell, "", calc_temp)
                    color = name_color
                else:
                    color = "white"
            draw_text_with_fallback(draw, (text_x, text_y), cell, font=font, fill=color)

    # 添加标题
    title = f"#{role_name}词条权重表"
    if modal_name:
        title = f"#{role_name}（{modal_name}）词条权重表"
    draw_text_with_fallback(draw, (start_x, 20), title, font=waves_font_36, fill=SPECIAL_GOLD)

    # 添加其他
    text = "词条得分：词条数值 * 当前词条权重 / 声骸未对齐最高分 * 对齐分数(50)"
    draw_text_with_fallback(draw, (start_x, 750), text, font=waves_font_24, fill="white")
    s = calc_temp["total_grade"]
    text = f"声骸评分标准：SSS≥{s[-1] * 250:.2f}分/ SS≥{s[-2] * 250:.2f}分／S≥{s[-3] * 250:.2f}分 / A≥{s[-4] * 250:.2f}分 / B≥{s[-5] * 250:.2f}分 / C"
    draw_text_with_fallback(draw, (start_x, 800), text, font=waves_font_24, fill="white")
    text = "当前角色评分标准仅供参考与娱乐，不代表任何官方或权威的评价。"
    draw_text_with_fallback(draw, (start_x, 850), text, font=waves_font_24, fill="white")

    return image


async def draw_pic_with_ring(ev: Event, is_force_avatar=False, force_resource_id=None):
    if force_resource_id:
        pic = await get_square_avatar(force_resource_id)
    elif not is_force_avatar:
        pic = await get_event_avatar(ev)
    else:
        pic = await get_event_avatar(ev, is_valid_at_param=False)

    return await _compose_avatar_ring(pic)


async def draw_char_with_ring(char_id):
    pic = await get_square_avatar(char_id)
    return await _compose_avatar_ring(pic)


@to_thread
def _compose_avatar_ring(pic):
    mask_pic = Image.open(TEXT_PATH / "avatar_mask.png")
    img = Image.new("RGBA", (180, 180))
    mask = mask_pic.resize((160, 160))
    resize_pic = crop_center_img(pic, 160, 160)
    img.paste(resize_pic, (20, 20), mask)

    return img


async def generate_online_role_detail(char_id: str):
    char_model = get_char_model(char_id)
    if not char_model:
        return

    weapon_id = DEAFAULT_WEAPON_ID.get(char_model.weaponTypeId)
    if not weapon_id:
        return

    weapon_model = get_weapon_model(weapon_id)
    if not weapon_model:
        return

    char_template_data = copy.deepcopy(await get_template_data())

    def _safe_fmt(tmpl: str, args) -> str:
        try:
            return tmpl.format(*args)
        except (IndexError, KeyError, ValueError) as exc:
            logger.debug(f"[鸣潮·角色面板渲染] desc.format 失败, 用原文: char_id={char_id} err={exc}")
            return tmpl

    # 命座
    for i, j in zip(char_model.chains.values(), char_template_data["chainList"]):
        j["name"] = i.name
        j["description"] = _safe_fmt(i.desc, i.param)
        j["iconUrl"] = ""
        j["unlocked"] = False

    # 技能
    skill_map = {
        "常态攻击": "1",
        "共鸣技能": "2",
        "共鸣回路": "7",
        "共鸣解放": "3",
        "变奏技能": "6",
        "延奏技能": "8",
        "谐度破坏": "17"
    }
    for i in char_template_data["skillList"]:
        temp_skill = i["skill"]
        skill_type = temp_skill["type"]
        skill_detail = char_model.skillTree[skill_map[skill_type]]["skill"]

        temp_skill["name"] = skill_detail.name
        temp_skill["description"] = _safe_fmt(skill_detail.desc, skill_detail.param)
        temp_skill["iconUrl"] = ""

    # role
    temp_role = char_template_data["role"]
    temp_role["roleName"] = char_model.name
    temp_role["iconUrl"] = ""
    temp_role["roleId"] = char_id
    temp_role["starLevel"] = char_model.starLevel
    temp_role["weaponTypeId"] = char_model.weaponTypeId
    temp_role["weaponTypeName"] = WEAPON_TYPE_ID_MAP[char_model.weaponTypeId]
    temp_role["attributeId"] = char_model.attributeId
    temp_role["attributeName"] = ATTRIBUTE_ID_MAP[char_model.attributeId]

    # 武器
    char_template_data["weaponData"]["resonLevel"] = 1
    temp_weapon = char_template_data["weaponData"]["weapon"]
    temp_weapon["weaponEffectName"] = _safe_fmt(weapon_model.effect, [i[-1] for i in weapon_model.param])
    temp_weapon["weaponIcon"] = ""
    temp_weapon["weaponId"] = weapon_id
    temp_weapon["weaponName"] = weapon_model.name
    temp_weapon["weaponStarLevel"] = weapon_model.starLevel
    temp_weapon["weaponType"] = weapon_model.type

    # 声骸
    char_template_data["phantomData"] = {"cost": 0, "equipPhantomList": None}

    return RoleDetailData.model_validate(char_template_data)


async def get_card_bg(
    w: int,
    h: int,
    bg: str = "bg",
):
    img: Optional[Image.Image] = None
    if ShowConfig.get_config("CardBg").data:
        bg_path = Path(ShowConfig.get_config("CardBgPath").data)
        if bg_path.is_file():
            img = Image.open(bg_path).convert("RGBA")
            img = crop_center_img(img, w, h)

    if not img:
        img = get_waves_bg(w, h, bg)

    img = await get_custom_gaussian_blur(img)
    return img
