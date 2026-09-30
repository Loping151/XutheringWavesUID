import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from gsuid_core.models import Event

from ..utils.api.model import AccountBaseInfo, SignInInitData, SignInSurfaceData
from ..utils.api.request_util import KuroApiResp
from ..utils.at_help import ruser_id
from ..utils.util import get_hide_uid_pref, hide_uid
from ..utils.error_reply import ERROR_CODE, WAVES_CODE_102
from ..utils.render_utils import render_html, get_image_b64_with_cache, get_footer_b64, PLAYWRIGHT_AVAILABLE
from ..utils.resource.RESOURCE_PATH import (
    SIGN_SURFACE_PATH,
    waves_templates,
)
from ..utils.waves_api import waves_api
from ..wutheringwaves_config.wutheringwaves_config import WutheringWavesConfig
from .draw_sign_calendar_pil import _format_loop_range, _has_loop, render_sign_calendar_pil


async def draw_sign_calendar(uid: str, ev: Event) -> Optional[bytes | str]:
    user_id = ruser_id(ev)
    ck, err = await waves_api.check_self_login(uid, user_id, ev.bot_id)
    if not ck:
        return err or ERROR_CODE[WAVES_CODE_102]
    user_pref = await get_hide_uid_pref(uid, user_id, ev.bot_id)

    sign_init_res, surface_res, base_info_res = await asyncio.gather(
        waves_api.get_sign_in_init(uid, ck),
        waves_api.get_sign_in_surface(ck),
        waves_api.get_base_info(uid, ck),
        return_exceptions=True,
    )

    # 签到初始化数据
    if not isinstance(sign_init_res, KuroApiResp) or not sign_init_res.success:
        return "获取签到数据失败"
    sign_data = SignInInitData.model_validate(sign_init_res.data)

    # 签到皮肤数据
    if not isinstance(surface_res, KuroApiResp) or not surface_res.success:
        return "获取签到皮肤数据失败"
    surface_data = SignInSurfaceData.model_validate(surface_res.data)

    # 基础信息 (角色名)
    role_name = uid
    if isinstance(base_info_res, KuroApiResp) and base_info_res.success:
        try:
            base_info = AccountBaseInfo.model_validate(base_info_res.data)
            role_name = base_info.name or uid
        except Exception:
            pass

    # 解析皮肤资源
    try:
        img_info = json.loads(surface_data.imgInfo) if surface_data.imgInfo else {}
    except Exception:
        img_info = {}

    try:
        font_style = json.loads(surface_data.fontStyle) if surface_data.fontStyle else {}
    except Exception:
        font_style = {}

    # 提取颜色
    main_bgColor = font_style.get("main_bgColor", "#D9C7BA")
    month_textColor = font_style.get("month_textColor", "#1d1d1d")
    cycle_titleColor = font_style.get("cycle_titleColor", "#E58A4E")
    cycle_timeTextColor = font_style.get("cycle_timeTextColor", "#666666")

    # 计算当前月份 (0点更新, CN tz)
    cn_tz = timezone(timedelta(hours=8))
    month = datetime.now(cn_tz).month

    # UseHtmlRender 关 / Playwright 不可用 → 走 PIL 分支
    use_html_render = WutheringWavesConfig.get_config("UseHtmlRender").data
    if not PLAYWRIGHT_AVAILABLE or not use_html_render:
        return await render_sign_calendar_pil(
            sign_data=sign_data,
            img_info=img_info,
            font_style=font_style,
            role_name=role_name,
            uid_display=hide_uid(uid, user_pref=user_pref),
            month=month,
        )

    # 下载素材图片 (download with cache, 大背景 bake)
    cover_bg = await get_image_b64_with_cache(
        img_info.get("main_coverBg", ""), SIGN_SURFACE_PATH, quality=80
    )
    box_top_bg = await get_image_b64_with_cache(
        img_info.get("common_boxTopBg", ""), SIGN_SURFACE_PATH
    )
    box_center_bg = await get_image_b64_with_cache(
        img_info.get("common_boxCenterBg", ""), SIGN_SURFACE_PATH
    )
    box_bottom_bg = await get_image_b64_with_cache(
        img_info.get("common_boxBottomBg", ""), SIGN_SURFACE_PATH
    )
    price_bg = await get_image_b64_with_cache(
        img_info.get("monthSign_priceBg", ""), SIGN_SURFACE_PATH
    )
    sign_day_bg = await get_image_b64_with_cache(
        img_info.get("month_signDayBg", ""), SIGN_SURFACE_PATH
    )
    today_no_sign = await get_image_b64_with_cache(
        img_info.get("month_todayNoSign", ""), SIGN_SURFACE_PATH
    )
    had_sign_in_bg = await get_image_b64_with_cache(
        img_info.get("month_hadSignInBg", ""), SIGN_SURFACE_PATH
    )

    # 限时签到（loop）资源 — 仅在活动存在时拉取
    cycle_bg = None
    loop_card_bg = None
    cycle_process_grey = None
    cycle_process_light = None
    loop_items = []
    if _has_loop(sign_data):
        cycle_bg = await get_image_b64_with_cache(
            img_info.get("cycle_bg", ""), SIGN_SURFACE_PATH
        )
        loop_card_bg = await get_image_b64_with_cache(
            img_info.get("common_priceBg", ""), SIGN_SURFACE_PATH
        )
        cycle_process_grey = await get_image_b64_with_cache(
            img_info.get("cycle_process_grey", ""), SIGN_SURFACE_PATH
        )
        cycle_process_light = await get_image_b64_with_cache(
            img_info.get("cycle_process_light", ""), SIGN_SURFACE_PATH
        )

        for goods in sorted(sign_data.signLoopGoodsList, key=lambda g: g.serialNum):
            icon = await get_image_b64_with_cache(goods.goodsUrl, SIGN_SURFACE_PATH)
            loop_items.append(
                {
                    "day": goods.serialNum + 1,
                    "icon": icon,
                    "num": goods.goodsNum,
                    "name": goods.goodsName,
                    "is_gained": goods.isGain,
                }
            )

    # 构建日历行, 每行 4 个
    goods_list = sign_data.signInGoodsConfigs
    rows = []
    items_per_row = 4

    for i in range(0, len(goods_list), items_per_row):
        chunk = goods_list[i : i + items_per_row]
        row_items = []
        for goods in chunk:
            day = goods.serialNum + 1  # serialNum 从 0 开始
            # sigInNum 是已签到天数，serialNum < sigInNum 即为已签
            is_gained = goods.serialNum < sign_data.sigInNum
            # 高亮项：未签时=下一个待签(sigInNum)，已签时=刚签的那天(sigInNum-1)
            if sign_data.isSigIn:
                is_current = goods.serialNum == sign_data.sigInNum - 1
            else:
                is_current = goods.serialNum == sign_data.sigInNum

            # 下载物品icon (download with cache)
            icon = await get_image_b64_with_cache(
                goods.goodsUrl, SIGN_SURFACE_PATH
            )

            row_items.append(
                {
                    "day": day,
                    "icon": icon,
                    "num": goods.goodsNum,
                    "name": goods.goodsName,
                    "is_current": is_current,
                    "is_gained": is_gained,
                }
            )

        rows.append({"goods": row_items})

    context = {
        "main_bgColor": main_bgColor,
        "month_textColor": month_textColor,
        "cycle_titleColor": cycle_titleColor,
        "cycle_timeTextColor": cycle_timeTextColor,
        "role_name": role_name,
        "uid": hide_uid(uid, user_pref=user_pref),
        "month": month,
        "sign_num": sign_data.sigInNum,
        "omission_num": sign_data.omissionNnm,
        "cover_bg": cover_bg,
        "box_top_bg": box_top_bg,
        "box_center_bg": box_center_bg,
        "box_bottom_bg": box_bottom_bg,
        "price_bg": price_bg,
        "sign_day_bg": sign_day_bg,
        "today_no_sign": today_no_sign,
        "had_sign_in_bg": had_sign_in_bg,
        "rows": rows,
        "loop_sign_name": sign_data.loopSignName,
        "loop_time_text": _format_loop_range(
            sign_data.loopStartTimes, sign_data.loopEndTimes
        ),
        "loop_items": loop_items,
        "cycle_bg": cycle_bg,
        "loop_card_bg": loop_card_bg,
        "cycle_process_grey": cycle_process_grey,
        "cycle_process_light": cycle_process_light,
        "footer_b64": get_footer_b64(footer_type="white") or "",
    }

    img = await render_html(waves_templates, "sign/sign_calendar.html", context)
    if img is None:
        return "渲染签到日历失败，请检查 Playwright 是否安装"
    return img
