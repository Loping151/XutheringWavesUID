from typing import Dict, List, Tuple, Union, Optional
from pathlib import Path

from PIL import Image, ImageDraw
from pydantic import BaseModel

from gsuid_core.models import Event
from gsuid_core.pool import to_thread
from gsuid_core.utils.image.convert import convert_img

from ..utils.util import hide_uid, get_hide_uid_pref
from ..utils.image import (
    GREY,
    SPECIAL_GOLD,
    add_footer,
    get_waves_bg,
    get_small_logo,
    get_square_avatar,
    get_attribute_prop,
    get_attribute_effect,
)
from ..utils.api.model import (
    Props,
    EquipPhantom,
    RoleDetailData,
)
from ..utils.calculate import get_calc_map, get_valid_color, calc_phantom_score
from ..utils.imagetool import draw_pic_with_ring, draw_base_info_bg
from ..utils.char_info_utils import get_all_role_detail_info
from ..wutheringwaves_charinfo import base_info_cache
from ..wutheringwaves_config import PREFIX
from ..utils.fonts.waves_fonts import (
    waves_font_24,
    waves_font_26,
    waves_font_28,
    waves_font_30,
    waves_font_42,
)
from ..utils.resource.download_file import get_phantom_img

TEXT_PATH = Path(__file__).parent / "texture2d"


class WavesEchoRank(BaseModel):
    roleId: int  # 角色id
    roleName: str  # 角色名字
    score: float  # 声骸评分
    score_bg: str  # 声骸评分背景
    props: List[Props]  # 声骸词条
    name_colors: List[Union[str, Tuple]]  # 颜色
    num_colors: List[Union[str, Tuple]]  # 颜色
    phantom: EquipPhantom  # 声骸


async def get_draw_list(ev: Event, uid: str, user_id: str, page: int = 1) -> Union[str, bytes]:
    from ..utils.calc import WuWaCalc
    info, _ck, _ = await base_info_cache.load_account_context(uid, user_id, ev.bot_id)
    if isinstance(info, str):
        return info
    user_pref = await get_hide_uid_pref(uid, user_id, ev.bot_id)
    account_info = info

    all_role_detail: Optional[Dict[str, RoleDetailData]] = await get_all_role_detail_info(uid)
    if not all_role_detail:
        return f"[鸣潮] 未找到角色信息, 请先使用[{PREFIX}刷新面板]进行刷新!"

    waves_echo_rank = []
    for char_name, role_detail in all_role_detail.items():
        if not role_detail.phantomData:
            continue
        if not role_detail.phantomData.equipPhantomList:
            continue
        equipPhantomList = role_detail.phantomData.equipPhantomList

        calc: WuWaCalc = WuWaCalc(role_detail)
        calc.phantom_pre = calc.prepare_phantom()
        calc.phantom_card = calc.enhance_summation_phantom_value(calc.phantom_pre)
        calc.calc_temp = get_calc_map(
            calc.phantom_card,
            role_detail.role.roleName,
            role_detail.role.roleId,
        )

        for i, _phantom in enumerate(equipPhantomList):  # type: ignore
            if not _phantom:
                continue
            if not _phantom.phantomProp:
                continue
            _phantom: EquipPhantom
            props = _phantom.get_props()
            _score, _bg = calc_phantom_score(role_detail.role.roleId, props, _phantom.cost, calc.calc_temp)
            name_colors = []
            num_colors = []
            for index, _prop in enumerate(props):
                name_color = "white"
                num_color = "white"
                if index > 1:
                    name_color, num_color = get_valid_color(_prop.attributeName, _prop.attributeValue, calc.calc_temp)
                name_colors.append(name_color)
                num_colors.append(num_color)

            wcr = WavesEchoRank(
                **{
                    "roleId": role_detail.role.roleId,
                    "roleName": role_detail.role.roleName,
                    "score": _score,
                    "score_bg": _bg,
                    "props": props,
                    "name_colors": name_colors,
                    "num_colors": num_colors,
                    "phantom": _phantom,
                }
            )
            waves_echo_rank.append(wcr)

    if not waves_echo_rank:
        return "[鸣潮] 未找到角色的声骸评分! 请检查角色声骸是否在库街区正确显示"

    waves_echo_rank.sort(key=lambda i: (i.score, i.roleId), reverse=True)

    page_size = 20
    total_count = len(waves_echo_rank)
    max_page_by_total = (total_count + page_size - 1) // page_size
    max_page = max(1, max_page_by_total)
    if page > max_page:
        page = max_page
    elif page < 1:
        page = 1
    start_index = (page - 1) * page_size
    end_index = min(start_index + page_size, total_count)
    waves_echo_rank_page = waves_echo_rank[start_index:end_index]

    # 头像部分
    avatar, avatar_ring = await draw_pic_with_ring(ev)

    # 预取每张卡所需图像
    echo_assets = []
    for _echo in waves_echo_rank_page:
        phantom: EquipPhantom = _echo.phantom
        role_avatar = await draw_pic(_echo.roleId)
        phantom_icon = await get_phantom_img(phantom.phantomProp.phantomId, phantom.phantomProp.iconUrl)
        fetter_icon = await get_attribute_effect(phantom.fetterDetail.name)
        prop_imgs = []
        for _prop in _echo.props:
            prop_imgs.append(await get_attribute_prop(_prop.attributeName))
        echo_assets.append(
            {
                "echo": _echo,
                "role_avatar": role_avatar,
                "phantom_icon": phantom_icon,
                "fetter_icon": fetter_icon,
                "prop_imgs": prop_imgs,
            }
        )

    title_bar_logo = get_small_logo(2) if account_info.is_full else None

    img = await _compose_echo_list(
        account_info,
        avatar,
        avatar_ring,
        echo_assets,
        page,
        max_page,
        user_pref,
        title_bar_logo,
    )
    return await convert_img(img)


@to_thread
def _compose_echo_list(
    account_info,
    avatar,
    avatar_ring,
    echo_assets,
    page,
    max_page,
    user_pref,
    title_bar_logo,
) -> Image.Image:
    img = get_waves_bg(1600, 3230, "bg3")
    img_draw = ImageDraw.Draw(img)

    img.paste(avatar, (45, 20), avatar)
    img.paste(avatar_ring, (55, 30), avatar_ring)

    base_info_bg = draw_base_info_bg(
        f"{account_info.name[:10]}",
        f"特征码:  {hide_uid(account_info.id, user_pref=user_pref)}",
        TEXT_PATH,
    )
    img.paste(base_info_bg, (35, -30), base_info_bg)

    if page > 1:
        img_draw.text(
            (1550, 60),
            f"第{page}/{max_page}页",
            GREY,
            waves_font_26,
            "rm",
        )

    if account_info.is_full:
        title_bar = Image.open(TEXT_PATH / "title_bar.png")
        title_bar_draw = ImageDraw.Draw(title_bar)
        title_bar_draw.text((510, 125), "账号等级", GREY, waves_font_26, "mm")
        title_bar_draw.text((510, 78), f"Lv.{account_info.level}", "white", waves_font_42, "mm")

        title_bar_draw.text((660, 125), "世界等级", GREY, waves_font_26, "mm")
        title_bar_draw.text((660, 78), f"Lv.{account_info.worldLevel}", "white", waves_font_42, "mm")

        if title_bar_logo is not None:
            title_bar.alpha_composite(title_bar_logo, dest=(780, 65))
        img.paste(title_bar, (200, 15), title_bar)

    _sh_bg = Image.open(TEXT_PATH / "sh_bg.png")

    promote_icon = Image.open(TEXT_PATH / "promote_icon.png")
    promote_icon = promote_icon.resize((30, 30))
    for index, asset in enumerate(echo_assets):
        _echo: WavesEchoRank = asset["echo"]
        sh_bg = _sh_bg.copy()
        head_high = 50
        sh_temp = Image.new("RGBA", (350, 550 + head_high))
        sh_temp_draw = ImageDraw.Draw(sh_temp)

        sh_temp.alpha_composite(sh_bg, dest=(0, head_high))
        sh_title = Image.open(TEXT_PATH / f"sh_title_{_echo.score_bg}.png")
        sh_temp.alpha_composite(sh_title, dest=(0, head_high))

        # 角色头像
        role_avatar = asset["role_avatar"]
        sh_temp.paste(role_avatar, (230, -40 + head_high), role_avatar)

        # 声骸
        phantom: EquipPhantom = _echo.phantom
        phantom_icon = asset["phantom_icon"]
        fetter_icon = asset["fetter_icon"].resize((50, 50))
        phantom_icon.alpha_composite(fetter_icon, dest=(205, 0))
        phantom_icon = phantom_icon.resize((100, 100))
        sh_temp.alpha_composite(phantom_icon, dest=(20, 20 + head_high))
        phantomName = phantom.phantomProp.name.replace("·", " ").replace("（", " ").replace("）", "")
        sh_temp_draw.text((130, 40 + head_high), f"{phantomName}", SPECIAL_GOLD, waves_font_28, "lm")

        # 声骸等级背景
        ph_level_img = Image.new("RGBA", (84, 30), (255, 255, 255, 0))
        ph_level_img_draw = ImageDraw.Draw(ph_level_img)
        ph_level_img_draw.rounded_rectangle([0, 0, 84, 30], radius=8, fill=(0, 0, 0, int(0.8 * 255)))
        ph_level_img_draw.text((8, 13), f"Lv.{phantom.level}", "white", waves_font_24, "lm")
        sh_temp.alpha_composite(ph_level_img, (128, 58 + head_high))

        # 声骸分数背景
        ph_score_img = Image.new("RGBA", (92, 30), (255, 255, 255, 0))
        ph_score_img_draw = ImageDraw.Draw(ph_score_img)
        ph_score_img_draw.rounded_rectangle([0, 0, 92, 30], radius=8, fill=(186, 55, 42, int(0.8 * 255)))
        ph_score_img_draw.text((5, 13), f"{_echo.score}分", "white", waves_font_24, "lm")
        sh_temp.alpha_composite(ph_score_img, (228, 58 + head_high))

        for j in range(0, phantom.cost):
            sh_temp.alpha_composite(promote_icon, dest=(128 + 30 * j, 90 + head_high))

        for i, temp in enumerate(zip(_echo.props, _echo.name_colors, _echo.num_colors)):
            _prop, name_color, num_color = temp
            oset = 55
            prop_img = asset["prop_imgs"][i].resize((40, 40))
            sh_temp.alpha_composite(prop_img, (15, 167 + i * oset + head_high))
            sh_temp_draw = ImageDraw.Draw(sh_temp)

            sh_temp_draw.text(
                (60, 187 + i * oset + head_high),
                f"{_prop.attributeName[:6]}",
                name_color,
                waves_font_24,
                "lm",
            )
            sh_temp_draw.text(
                (343, 187 + i * oset + head_high),
                f"{_prop.attributeValue}",
                num_color,
                waves_font_24,
                "rm",
            )

        _x = 40 + 390 * (index % 4)
        _y = 220 + 570 * (index // 4)

        img.alpha_composite(sh_temp, (_x, _y))

    img = add_footer(img)
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
