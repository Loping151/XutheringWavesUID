from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.data_store import get_res_path

from ..utils.hint import error_reply
from ..utils.util import get_hide_uid_pref, hide_uid
from ..utils.waves_api import waves_api
from ..wutheringwaves_config import WutheringWavesConfig, PREFIX
from ..utils.error_reply import WAVES_CODE_102
from ..utils.api.model import (
    ExploreList,
    AccountBaseInfo,
)
from ..utils.render_utils import (
    PLAYWRIGHT_AVAILABLE,
    render_html,
    get_image_b64_with_cache,
    get_footer_b64,
)
from ..utils.resource.RESOURCE_PATH import waves_templates
from ..utils.image import pil_to_b64, get_waves_bg, get_event_avatar

from .draw_explore_card_pil import split_explore_areas, draw_explore_img as draw_explore_img_pil

EXPLORE_IMAGE_PATH = get_res_path("XutheringWavesUID") / "other" / "explore"


async def draw_explore_img(ev: Event, uid: str, user_id: str):
    use_html_render = WutheringWavesConfig.get_config("UseHtmlRender").data
    if not PLAYWRIGHT_AVAILABLE or not use_html_render:
        return await draw_explore_img_pil(ev, uid, user_id)

    try:
        is_self_ck, ck = await waves_api.get_ck_result(uid, user_id, ev.bot_id)
        if not ck:
            return error_reply(WAVES_CODE_102)
        user_pref = await get_hide_uid_pref(uid, user_id, ev.bot_id)

        account_info_res = await waves_api.get_base_info(uid, ck)
        if not account_info_res.success:
            return account_info_res.throw_msg()
        if not account_info_res.data:
            return f"用户未展示数据, 请尝试【{PREFIX}登录】"
        account_info = AccountBaseInfo.model_validate(account_info_res.data)

        explore_data_res = await waves_api.get_explore_data(uid, ck)
        if not explore_data_res.success:
            return explore_data_res.throw_msg()
        explore_data = ExploreList.model_validate(explore_data_res.data)
        
        if not is_self_ck and not explore_data.open:
            return "探索数据未开启"

        if not explore_data.exploreList:
            return "探索数据为空"

        avatar = await get_event_avatar(ev)
        avatar_url = pil_to_b64(avatar, quality=75)

        async def icon_b64(url) -> str:
            return await get_image_b64_with_cache(url, EXPLORE_IMAGE_PATH) if url else ""

        explore_list_data = []
        for _explore in reversed(explore_data.exploreList):
            done, todo = split_explore_areas(_explore)
            explore_list_data.append({
                "name": _explore.country.countryName,
                "progress": _explore.countryProgress,
                "color": _explore.country.detailPageProgressColor,
                "icon_url": await icon_b64(_explore.country.homePageIcon),
                "done": done,
                "areas": [
                    {
                        "name": area.areaName,
                        "progress": area.areaProgress,
                        "item_list": [
                            {"name": item.name, "progress": item.progress, "icon_url": await icon_b64(item.icon)}
                            for item in items
                        ],
                    }
                    for area, items in todo
                ],
            })

        bg_img = get_waves_bg(bg="bg3", crop=False)
        bg_url = pil_to_b64(bg_img, quality=75)

        context = {
            "user_name": account_info.name,
            "user_id": hide_uid(account_info.id, user_pref=user_pref),
            "level": account_info.level,
            "world_level": account_info.worldLevel,
            "show_stats": account_info.is_full,
            "avatar_url": avatar_url,
            "explore_list": explore_list_data,
            "footer_b64": get_footer_b64(footer_type="white") or "",
            "bg_url": bg_url,
        }

        logger.debug("[鸣潮·探索卡片] 准备通过HTML渲染探索卡片")
        img_bytes = await render_html(waves_templates, "explore_card.html", context)
        if img_bytes:
            return img_bytes
        else:
            logger.warning("[鸣潮·探索卡片] Playwright 渲染返回空, 正在回退到 PIL 渲染")
            return await draw_explore_img_pil(ev, uid, user_id)

    except Exception as e:
        logger.exception(f"[鸣潮·探索卡片] HTML渲染失败: {e}")
        return await draw_explore_img_pil(ev, uid, user_id)
