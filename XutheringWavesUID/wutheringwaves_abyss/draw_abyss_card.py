from typing import Union
from pathlib import Path
from datetime import datetime, timezone, timedelta

from PIL import Image

from gsuid_core.models import Event
from gsuid_core.logger import logger

from ..utils.hint import error_reply, not_shown_msg
from ..utils.util import hide_uid, get_hide_uid_pref
from ..utils.waves_api import waves_api
from ..utils.error_reply import WAVES_CODE_102
from ..utils.api.model import (
    AccountBaseInfo,
    RoleList,
)
from ..utils.ascension.char import get_char_detail
from ..wutheringwaves_config import WutheringWavesConfig
from ..utils.render_utils import (
    PLAYWRIGHT_AVAILABLE,
    render_html,
    get_footer_b64,
)
from ..utils.resource.RESOURCE_PATH import waves_templates
from ..utils.image import (
    pil_to_b64,
    img_to_b64,
    get_waves_bg,
    get_event_avatar,
    get_square_avatar_path,
    get_skill_branch_emblem_b64,
    CHAIN_COLOR,
)
from ..utils.char_info_utils import get_all_roleid_detail_info, get_rover_detail_map, lookup_chain_with_rover
from .period import get_tower_period_number
from .draw_abyss_card_pil import (
    draw_abyss_img as draw_abyss_img_pil,
    get_abyss_data,
    upload_abyss_record,
    ABYSS_ERROR_MESSAGE_NO_UNLOCK,
    ABYSS_ERROR_MESSAGE_NO_DEEP,
)

TEXT_PATH = Path(__file__).parent / "texture2d"


async def draw_abyss_img(ev: Event, uid: str, user_id: str, peek: bool = False) -> Union[bytes, str]:
    use_html_render = WutheringWavesConfig.get_config("UseHtmlRender").data
    if not PLAYWRIGHT_AVAILABLE or not use_html_render:
        return await draw_abyss_img_pil(ev, uid, user_id, peek=peek)

    try:
        is_self_ck, ck = await waves_api.get_ck_result(uid, user_id, ev.bot_id, peek=peek)
        if not ck:
            return error_reply(WAVES_CODE_102)
        user_pref = await get_hide_uid_pref(uid, user_id, ev.bot_id)

        command = ev.command
        text = ev.text.strip()
        difficultyName = "深境区"
        if "超载" in text or "超载" in command:
            difficultyName = "超载区"
        elif "稳定" in text or "稳定" in command:
            difficultyName = "稳定区"
        elif "实验" in text or "实验" in command:
            difficultyName = "实验区"

        account_info_res = await waves_api.get_base_info(uid, ck)
        if not account_info_res.success:
            return account_info_res.throw_msg()
        if not account_info_res.data:
            return not_shown_msg(uid, peek)
        account_info = AccountBaseInfo.model_validate(account_info_res.data)

        abyss_data = await get_abyss_data(uid, ck, is_self_ck, peek)
        if isinstance(abyss_data, str) or not abyss_data:
            return abyss_data
        if not abyss_data.isUnlock:
            return ABYSS_ERROR_MESSAGE_NO_UNLOCK

        if not abyss_data.difficultyList:
            return ABYSS_ERROR_MESSAGE_NO_DEEP

        abyss_check = next(
            (abyss for abyss in abyss_data.difficultyList if abyss.difficultyName == "深境区"),
            None,
        )
        if not abyss_check:
            return ABYSS_ERROR_MESSAGE_NO_DEEP

        needAbyss = None
        for _abyss in abyss_data.difficultyList:
            if _abyss.difficultyName != difficultyName:
                continue
            needAbyss = _abyss
            break
        if not needAbyss:
            return ABYSS_ERROR_MESSAGE_NO_DEEP

        avatar = await get_event_avatar(ev)
        avatar_url = pil_to_b64(avatar, quality=75)

        role_detail_info_map = await get_all_roleid_detail_info(uid)
        rover_map = await get_rover_detail_map(uid)

        role_info_res = await waves_api.get_role_info(uid, ck)
        role_info_list = []
        if role_info_res.success and role_info_res.data:
            try:
                role_info = RoleList.model_validate(role_info_res.data)
                role_info_list = role_info.roleList
            except Exception:
                pass

        towers_data = []
        for tower in needAbyss.towerAreaList:
            floors_data = []
            for floor in (tower.floorList or []):
                floor_num_map = {1: "一", 2: "二", 3: "三", 4: "四"}
                floor_name = floor_num_map.get(floor.floor, str(floor.floor))

                try:
                    abyss_bg = Image.open(TEXT_PATH / f"abyss_bg_{floor.floor}.jpg").convert("RGBA")
                    abyss_bg_url = pil_to_b64(abyss_bg, quality=75)
                except Exception:
                    abyss_bg_url = ""

                roles_data = []
                if floor.roleList:
                    for _role in floor.roleList:
                        star_level = 5
                        role_level = 90
                        try:
                            char_detail = get_char_detail(_role.roleId, 1)
                            star_level = char_detail.starLevel
                        except Exception:
                            pass

                        role = next(
                            (r for r in role_info_list if r.roleId == _role.roleId),
                            None,
                        )
                        if role:
                            role_level = role.level

                        chain_num, chain_name, hide_detail = lookup_chain_with_rover(role_detail_info_map, rover_map, _role.roleId)

                        role_icon_b64 = img_to_b64(get_square_avatar_path(_role.roleId), quality=75, bake=True, cover_size=(128, 128))

                        roles_data.append({
                            "id": _role.roleId,
                            "level": role_level,
                            "star": star_level,
                            "chain_num": chain_num,
                            "chain_name": chain_name,
                            "hide_detail": hide_detail,
                            "icon_url": role_icon_b64,
                            "branch_icon": get_skill_branch_emblem_b64(_role.roleId, _role.skillBranchIndex),
                        })

                floors_data.append({
                    "floor": floor.floor,
                    "floor_name": floor_name,
                    "star": floor.star,
                    "abyss_bg_url": abyss_bg_url,
                    "roles": roles_data,
                })

            towers_data.append({
                "name": tower.areaName,
                "area_id": tower.areaId,
                "star": tower.star if is_self_ck else None,
                "max_star": tower.maxStar if is_self_ck else None,
                "floors": floors_data,
            })

        bg_img = get_waves_bg(bg = "bg4", crop=False)
        bg_url = pil_to_b64(bg_img, quality=75)

        tower_name_bg = Image.open(TEXT_PATH / "tower_name_bg.png")
        tower_name_bg_url = pil_to_b64(tower_name_bg)

        star_full = Image.open(TEXT_PATH / "star_full.png")
        star_full_url = pil_to_b64(star_full)

        star_empty = Image.open(TEXT_PATH / "star_empty.png")
        star_empty_url = pil_to_b64(star_empty)

        current_date = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

        chain_colors = {i: f"rgba({r}, {g}, {b}, 0.8)" for i, (r, g, b) in CHAIN_COLOR.items()}

        context = {
            "user_name": account_info.name,
            "user_id": hide_uid(account_info.id, user_pref=user_pref),
            "level": account_info.level,
            "world_level": account_info.worldLevel,
            "show_stats": account_info.is_full,
            "avatar_url": avatar_url,
            "difficulty_name": difficultyName,
            "period": get_tower_period_number(),
            "current_date": current_date,
            "towers": towers_data,
            "is_self_ck": is_self_ck,
            "tower_name_bg_url": tower_name_bg_url,
            "star_full_url": star_full_url,
            "star_empty_url": star_empty_url,
            "footer_b64": get_footer_b64(footer_type="black") or "",
            "bg_url": bg_url,
            "chain_colors": chain_colors,
        }

        logger.debug("[鸣潮·深塔渲染] 准备 HTML 渲染")
        img_bytes = await render_html(waves_templates, "abyss/abyss_card.html", context)
        if img_bytes:
            await upload_abyss_record(is_self_ck, uid, difficultyName, abyss_data)
            return img_bytes
        else:
            logger.warning("[鸣潮·深塔渲染] Playwright 返回空, 回退到 PIL")
            return await draw_abyss_img_pil(ev, uid, user_id, peek=peek)

    except Exception as e:
        logger.exception(f"[鸣潮·深塔渲染] HTML 失败: {e}")
        return await draw_abyss_img_pil(ev, uid, user_id, peek=peek)