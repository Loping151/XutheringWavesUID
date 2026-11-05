import time
import random
import asyncio
from typing import Dict, Optional
from pathlib import Path
from datetime import datetime, timedelta

from PIL import Image, ImageDraw

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.pool import to_thread
from gsuid_core.utils.image.convert import convert_img

from ..utils.image import (
    paste_masked_avatar,
    RED,
    GOLD,
    GREY,
    GREEN,
    YELLOW,
    _force_bg_path,
    _force_pile_path,
    add_footer,
    pil_to_b64,
    draw_text_with_shadow,
    get_event_avatar,
    get_random_waves_bg,
    get_random_waves_role_pile,
    mr_prefer_bg,
)
from ..utils.api.model import DailyData, AccountBaseInfo
from ..utils.api.launcher_chain import fetch_launcher_panel
from ..utils.util import hide_uid
from ..utils.constants import WAVES_GAME_ID
from ..utils.at_help import ruser_id
from ..utils.waves_api import waves_api
from ..utils.error_reply import ERROR_CODE, WAVES_CODE_102, WAVES_CODE_103
from ..utils.name_convert import char_name_to_char_id
from ..utils.database.models import (
    WavesBind,
    WavesUser,
    WavesStaminaRecord,
    WavesLangSettings,
)
from ..utils.localization import t
from ..utils.api.request_util import KuroApiResp
from ..utils.fonts.waves_fonts import (
    waves_font_12,
    waves_font_18,
    waves_font_24,
    waves_font_25,
    waves_font_26,
    waves_font_30,
    waves_font_32,
    waves_font_42,
)
from ..utils.resource.constant import SPECIAL_CHAR
from ..wutheringwaves_charinfo import card_hash_index
from ..wutheringwaves_charinfo.card_hash_index import compute_hash as _compute_pile_hash, detect_type as _detect_pile_type
from ..wutheringwaves_config.wutheringwaves_config import ShowConfig, WutheringWavesConfig
import io
import base64
from ..utils.render_utils import render_html, PLAYWRIGHT_AVAILABLE
from ..utils.resource.RESOURCE_PATH import waves_templates


TEXT_PATH = Path(__file__).parent / "texture2d"
YES = Image.open(TEXT_PATH / "yes.png")
YES = YES.resize((40, 40))
NO = Image.open(TEXT_PATH / "no.png")
NO = NO.resize((40, 40))
bar_down = Image.open(TEXT_PATH / "bar_down.png").convert("RGBA")

based_w = 1150
based_h = 850
URGENT_COLOR = "#ff4d4f"


async def seconds2hours(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return "%02d小时%02d分" % (h, m)


async def process_uid(uid, ev):
    if waves_api.is_net(uid):
        return await _process_uid_launcher(uid, ev)

    ck, err = await waves_api.check_self_login(uid, ruser_id(ev), ev.bot_id)
    if not ck:
        # 仅未绑定 cookie (err=None) 时同步 stamina 推送状态;
        # 维护/网络异常不能断言 ck 失效; cookie 真失效已由 check_self_login 内部 mark
        if err is None:
            try:
                await WavesStaminaRecord.update_ck_valid(
                    user_id=ruser_id(ev),
                    bot_id=ev.bot_id,
                    bot_self_id=ev.bot_self_id or "",
                    uid=uid,
                    is_ck_valid=False,
                )
            except Exception:
                logger.exception("[鸣潮·每日信息] 体力记录CK有效状态更新失败")
        return err  # 失效/维护/网络 → 透传; 未绑定 → None 由上层报 102

    # 并行请求所有相关 API
    results = await asyncio.gather(
        waves_api.get_daily_info(uid, ck),
        waves_api.get_base_info(uid, ck),
        return_exceptions=True,
    )

    (daily_info_res, account_info_res) = results
    if isinstance(daily_info_res, BaseException):
        logger.error(f"[鸣潮·每日信息] get_daily_info 异常 uid={uid}", exc_info=daily_info_res)
        return "获取每日信息失败：网络异常"
    if not daily_info_res.success:
        return f"获取每日信息失败：{daily_info_res.throw_msg() or '未知错误'}"

    if isinstance(account_info_res, BaseException):
        logger.error(f"[鸣潮·每日信息] get_base_info 异常 uid={uid}", exc_info=account_info_res)
        return "获取账户信息失败：网络异常"
    if not account_info_res.success:
        return f"获取账户信息失败：{account_info_res.throw_msg() or '未知错误'}"

    daily_info = DailyData.model_validate(daily_info_res.data)
    account_info = AccountBaseInfo.model_validate(account_info_res.data)

    try:
        mr_value = daily_info.energyData.cur if daily_info.energyData else None
        await WavesStaminaRecord.upsert_stamina_query(
            user_id=ruser_id(ev),
            bot_id=ev.bot_id,
            bot_self_id=ev.bot_self_id or "",
            uid=uid,
            mr_query_time=int(time.time()),
            mr_value=mr_value,
            is_ck_valid=True,
        )
    except Exception:
        logger.exception("[鸣潮·每日信息] 体力查询记录写入失败")

    return {
        "daily_info": daily_info,
        "account_info": account_info,
    }


async def _process_uid_launcher(uid, ev):
    user_id = ruser_id(ev)
    bot_id = ev.bot_id

    panel = await fetch_launcher_panel(user_id, bot_id, uid)
    if panel is None:
        logger.info(
            f"[鸣潮·每日信息] 国际服账号失效，无法拉取面板 uid={uid} user_id={user_id} bot_id={bot_id}"
        )
        try:
            await WavesStaminaRecord.update_ck_valid(
                user_id=user_id,
                bot_id=bot_id,
                bot_self_id=ev.bot_self_id or "",
                uid=uid,
                is_ck_valid=False,
            )
        except Exception:
            logger.exception("[鸣潮·每日信息] launcher CK 状态更新失败")
        return None

    base = panel.base
    daily_info = DailyData(
        gameId=WAVES_GAME_ID,
        userId=0,
        serverId="",
        roleId=str(uid),
        roleName=base.name,
        signInTxt="",
        hasSignIn=False,
        energyData=panel.energy,
        livenessData=panel.liveness,
        battlePassData=[panel.battlePass],
    )

    try:
        await WavesStaminaRecord.upsert_stamina_query(
            user_id=user_id,
            bot_id=bot_id,
            bot_self_id=ev.bot_self_id or "",
            uid=uid,
            mr_query_time=int(time.time()),
            mr_value=panel.energy.cur if panel.energy else None,
            is_ck_valid=True,
        )
    except Exception:
        logger.exception("[鸣潮·每日信息] launcher 体力记录写入失败")

    return {
        "daily_info": daily_info,
        "account_info": base,
        "from_sdk": True,
    }


async def draw_stamina_img(bot: Bot, ev: Event):
    try:
        uid_list = await WavesBind.get_uid_list_by_game(ruser_id(ev), ev.bot_id)
        logger.info(f"[鸣潮·每日信息] UID: {uid_list}")
        if uid_list is None:
            return ERROR_CODE[WAVES_CODE_103]

        # 获取用户语言设置
        locale = await WavesLangSettings.get_lang(ruser_id(ev))

        # 进行校验UID是否绑定CK
        tasks = [process_uid(uid, ev) for uid in uid_list]
        results = await asyncio.gather(*tasks)

        # dict = 数据成功; str = 错误透传消息; None = 未绑定
        valid_daily_list = [res for res in results if isinstance(res, dict)]

        if len(valid_daily_list) == 0:
            err_msgs = [res for res in results if isinstance(res, str)]
            if err_msgs:
                return "\n".join(err_msgs)
            return ERROR_CODE[WAVES_CODE_102]

        # 各 UID 并发渲染各自的 stamina_img, 主流程串行 paste 到画布,
        # 避免多个 to_thread 并发写同一 PIL Image (PIL paste 非线程安全)
        stamina_imgs = await asyncio.gather(
            *(_draw_stamina_img(ev, valid, locale) for valid in valid_daily_list)
        )
        img = await asyncio.to_thread(
            _assemble_stamina_canvas, stamina_imgs, based_w, based_h
        )
        res = await convert_img(img)
        logger.info("[鸣潮·每日信息] 绘图已完成,等待发送!")
    except TypeError:
        logger.exception("[鸣潮·每日信息] 绘图失败!")
        res = "你绑定过的UID中可能存在过期CK~请重新绑定一下噢~"

    return res


def _assemble_stamina_canvas(stamina_imgs: list, canvas_w: int, row_h: int) -> Image.Image:
    img = Image.new("RGBA", (canvas_w, row_h * len(stamina_imgs)), (0, 0, 0, 0))
    for index, stamina_img in enumerate(stamina_imgs):
        rgba = stamina_img.convert("RGBA")
        img.paste(rgba, (0, row_h * index), rgba)
    return img


async def _draw_stamina_img(ev: Event, valid: Dict, locale: str = "") -> Image.Image:
    """准备数据并调用绘制函数"""
    daily_info: DailyData = valid["daily_info"]
    account_info: AccountBaseInfo = valid["account_info"]
    from_sdk: bool = bool(valid.get("from_sdk", False))

    # 确定签到状态
    if daily_info.hasSignIn:
        sign_in_icon = YES
        sing_in_text = t("签到已完成！", locale)
    else:
        sign_in_icon = NO
        sing_in_text = t("今日未签到！", locale)

    # 确定活跃度状态
    if daily_info.livenessData.total != 0 and daily_info.livenessData.cur == daily_info.livenessData.total:
        active_icon = YES
        active_text = t("活跃度已满！", locale)
    else:
        active_icon = NO
        active_text = t("活跃度未满！", locale)

    # 加载基础图片资源
    img = Image.open(TEXT_PATH / "bg.jpg").convert("RGBA")
    info = Image.open(TEXT_PATH / "main_bar.png").convert("RGBA")
    base_info_bg = Image.open(TEXT_PATH / "base_info_bg.png")
    avatar_ring = Image.open(TEXT_PATH / "avatar_ring.png")

    # 头像
    avatar = await get_event_avatar(ev)

    # 随机获得pile
    user = await WavesUser.get_user_by_attr(ruser_id(ev), ev.bot_id, "uid", daily_info.roleId, game_id=WAVES_GAME_ID)
    pile_id = None
    force_use_bg = False
    force_not_use_bg = False
    force_not_use_custom = False
    pinned_path: Optional[Path] = None
    pinned_type: Optional[str] = None

    if user and user.stamina_bg_value:
        logger.debug(f"[鸣潮·每日信息] 使用自定义体力背景设置: {user.stamina_bg_value}")
        force_use_bg = "背景" in user.stamina_bg_value
        force_not_use_bg = "立绘" in user.stamina_bg_value
        force_not_use_custom = "官方" in user.stamina_bg_value
        stamina_bg_value = (
            user.stamina_bg_value.replace("背景", "").replace("立绘", "").replace("官方", "").replace("图", "").strip()
        )

        # hash 优先于角色名: modifier 既用作渲染分支选择, 也用作类型过滤,
        # "立绘abc12345" 命中失败时不会再尝试其它类型 — 用户写死了 stamina 就不该跑 bg。
        if force_use_bg and not force_not_use_bg:
            allowed_hash_types = ("bg",)
        elif force_not_use_bg and not force_use_bg:
            allowed_hash_types = ("stamina",)
        else:
            allowed_hash_types = ("bg", "stamina")
        hash_match = next(
            (m for m in card_hash_index.find(stamina_bg_value) if m[0] in allowed_hash_types),
            None,
        )

        if hash_match:
            pinned_type, h_ch_id, pinned_path = hash_match
            pile_id = h_ch_id
            # 锁渲染分支与 ContextVar 一致, 否则 MrUseBG 兜底分支会跑到不匹配的 fetcher
            force_use_bg = pinned_type == "bg"
            force_not_use_bg = pinned_type == "stamina"
            # hash 指向自定义图; 与 '官方' 矛盾, 后者会让 fetcher 跳过 custom_dir 而吃不到强制路径
            if force_not_use_custom:
                logger.debug(f"[鸣潮·每日信息] hash {stamina_bg_value} 与 '官方' 矛盾, 忽略 '官方'")
            force_not_use_custom = False
        else:
            char_id = char_name_to_char_id(stamina_bg_value)
            if char_id in SPECIAL_CHAR:
                variants = SPECIAL_CHAR[char_id]
                # 国际服走 SDK 路径，没有可用 ck 校验角色拥有情况，直接跳过校验逻辑
                if not from_sdk:
                    ck = await waves_api.get_self_waves_ck(daily_info.roleId, ruser_id(ev), ev.bot_id)
                    if ck:
                        for vid in variants:
                            role_detail_info = await waves_api.get_role_detail_info(vid, daily_info.roleId, ck)
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
                            pile_id = vid
                            break
                if pile_id is None:
                    # 国际服 / 无 ck / 所有变体校验均失败，退化为随机选一个变体
                    pile_id = random.choice(variants)
            else:
                pile_id = char_id

    logger.debug(f"[鸣潮·每日信息] 使用立绘ID: {pile_id}, 强制使用背景: {force_use_bg}, 强制不使用背景: {force_not_use_bg}")

    # 命中 hash 时短路 fetcher: 找不到对应文件 / 外部已设强制路径就静默回退到默认随机选图。
    # type 与对应 ContextVar 是 1:1 映射, 不再展开成两套 token。
    _pin_var = {"bg": _force_bg_path, "stamina": _force_pile_path}.get(pinned_type or "")
    _pin_token = None
    if (
        _pin_var is not None
        and pinned_path is not None
        and pinned_path.is_file()
        and _pin_var.get() is None
    ):
        _pin_token = _pin_var.set(pinned_path)
    try:
        if force_use_bg:
            pile, has_bg, pile_path = await get_random_waves_bg(pile_id, force_not_use_custom=force_not_use_custom)
        elif force_not_use_bg:
            pile, pile_path = await get_random_waves_role_pile(pile_id, force_not_use_custom=force_not_use_custom)
            has_bg = False
        elif mr_prefer_bg(pile_id, force_not_use_custom):
            pile, has_bg, pile_path = await get_random_waves_bg(pile_id, force_not_use_custom=force_not_use_custom)
        else:
            pile, pile_path = await get_random_waves_role_pile(pile_id, force_not_use_custom=force_not_use_custom)
            has_bg = False
    finally:
        if _pin_token is not None and _pin_var is not None:
            _pin_var.reset(_pin_token)

    # 仅自定义图绘制 hash; 官方图 detect_type 返回 None 不画。
    # 用户已通过 hash 指定体力背景时角落 hash 是冗余信息, 跳过绘制。
    pile_hash: Optional[str] = None
    if pinned_type is None and pile_path is not None and _detect_pile_type(pile_path) is not None:
        pile_hash = _compute_pile_hash(pile_path.name)

    # 尝试使用HTML渲染
    use_html_render = WutheringWavesConfig.get_config("UseHtmlRender").data
    user_pref = user.hide_uid_self_value if user else ""
    if not PLAYWRIGHT_AVAILABLE or not use_html_render:
        return await _render_stamina_card_pil(
            img=img,
            info=info,
            base_info_bg=base_info_bg,
            avatar_ring=avatar_ring,
            avatar=await draw_pic_with_ring(ev),
            pile=pile,
            has_bg=has_bg,
            daily_info=daily_info,
            account_info=account_info,
            sign_in_icon=sign_in_icon,
            sing_in_text=sing_in_text,
            active_icon=active_icon,
            active_text=active_text,
            locale=locale,
            pile_hash=pile_hash,
            user_pref=user_pref,
            from_sdk=from_sdk,
        )

    try:
        html_res = await _render_stamina_card(
            ev=ev,
            pile=pile,
            has_bg=has_bg,
            daily_info=daily_info,
            account_info=account_info,
            sign_in_status=daily_info.hasSignIn,
            sign_in_text=sing_in_text,
            active_status=(
                daily_info.livenessData.total != 0
                and daily_info.livenessData.cur == daily_info.livenessData.total
            ),
            active_text=active_text,
            avatar=avatar,
            locale=locale,
            from_sdk=from_sdk,
            pile_hash=pile_hash,
            user_pref=user_pref,
        )
        if html_res:
            return html_res
    except Exception:
        logger.exception("[鸣潮·每日信息] HTML渲染失败, 回退到PIL绘制")

    # 调用实际的绘制函数
    return await _render_stamina_card_pil(
        img=img,
        info=info,
        base_info_bg=base_info_bg,
        avatar_ring=avatar_ring,
        avatar=await draw_pic_with_ring(ev),
        pile=pile,
        has_bg=has_bg,
        daily_info=daily_info,
        account_info=account_info,
        sign_in_icon=sign_in_icon,
        sing_in_text=sing_in_text,
        active_icon=active_icon,
        active_text=active_text,
        locale=locale,
        pile_hash=pile_hash,
        user_pref=user_pref,
        from_sdk=from_sdk,
    )


@to_thread
def _prepare_stamina_b64_assets(
    pile: Image.Image, avatar: Image.Image, has_bg: bool = False
) -> Dict[str, str]:
    def load_b64(filename, quality=0):
        try:
            p = TEXT_PATH / filename
            if p.exists():
                return pil_to_b64(Image.open(p), quality=quality)
        except Exception:
            return ""
        return ""

    def fit_and_b64(img: Image.Image) -> str:
        # 按真实显示区归一(背景 cover 到 1150×850, 立绘归一到高 850), 只缩不放。
        # 旧逻辑按单一 max_size=1150 降采样, 会把某维压到显示所需之下, 再被浏览器
        # object-fit:cover / height:100% 放大回去 → 高清宽图发糊。resize/crop 返回
        # 新对象, 不污染调用方 pile(HTML 失败回退 PIL 时仍要原图)。
        try:
            if has_bg:
                tw, th = 1150, 850
                scale = max(tw / img.width, th / img.height)
                if scale < 1:  # 源够大才缩到刚好 cover 再裁剪; 不够大就原样交给浏览器
                    img = img.resize(
                        (round(img.width * scale), round(img.height * scale)),
                        Image.LANCZOS,
                    )
                    left, top = (img.width - tw) // 2, (img.height - th) // 2
                    img = img.crop((left, top, left + tw, top + th))
            else:
                th = 850  # 立绘 height:100%
                if img.height > th:
                    img = img.resize(
                        (max(1, round(img.width * th / img.height)), th), Image.LANCZOS
                    )
            return pil_to_b64(img, quality=75)
        except Exception:
            return pil_to_b64(img, quality=75)

    return {
        "yes_icon_b64": load_b64("yes.png"),
        "no_icon_b64": load_b64("no.png"),
        "stamina_icon_b64": load_b64("结晶波片.png"),
        "store_icon_b64": load_b64("结晶单质.png"),
        "liveness_icon_b64": load_b64("活跃度.png"),
        "bg_url_b64": load_b64("bg.jpg", quality=75),
        "pile_b64": fit_and_b64(pile),
        "avatar_b64": pil_to_b64(avatar, quality=75),
    }


async def _render_stamina_card(
    ev: Event,
    pile: Image.Image,
    has_bg: bool,
    daily_info: DailyData,
    account_info: AccountBaseInfo,
    sign_in_status: bool,
    sign_in_text: str,
    active_status: bool,
    active_text: str,
    avatar: Image.Image,
    locale: str = "",
    from_sdk: bool = False,
    pile_hash: Optional[str] = None,
    user_pref: str = "",
) -> Image.Image:
    # 准备上下文数据
    
    # 颜色定义
    color_red = URGENT_COLOR
    color_yellow = "#FFCB3B"
    
    b64_assets = await _prepare_stamina_b64_assets(pile, avatar, has_bg=has_bg)
    yes_icon_b64 = b64_assets["yes_icon_b64"]
    no_icon_b64 = b64_assets["no_icon_b64"]
    stamina_icon_b64 = b64_assets["stamina_icon_b64"]
    store_icon_b64 = b64_assets["store_icon_b64"]
    liveness_icon_b64 = b64_assets["liveness_icon_b64"]
    bg_url_b64 = b64_assets["bg_url_b64"]
    pile_b64 = b64_assets["pile_b64"]
    avatar_b64 = b64_assets["avatar_b64"]
    
    # 体力
    stamina_cur = daily_info.energyData.cur
    stamina_total = daily_info.energyData.total
    stamina_percent = min(100, (stamina_cur / stamina_total * 100)) if stamina_total else 0
    stamina_color = color_red if stamina_percent > 80 else color_yellow
    
    # 体力恢复时间
    curr_time = int(time.time())
    refreshTimeStamp = daily_info.energyData.refreshTimeStamp if daily_info.energyData.refreshTimeStamp else curr_time
    
    is_stamina_urgent = False
    if refreshTimeStamp != curr_time:
        date_from_timestamp = datetime.fromtimestamp(refreshTimeStamp)
        now = datetime.now()
        today = now.date()
        tomorrow = today + timedelta(days=1)
        
        if refreshTimeStamp - curr_time < 4 * 3600:
            is_stamina_urgent = True

        if date_from_timestamp.date() == today:
            recover_text = t("今天", locale) + " " + datetime.fromtimestamp(refreshTimeStamp).strftime("%H:%M:%S")
        elif date_from_timestamp.date() == tomorrow:
            recover_text = t("明天", locale) + " " + datetime.fromtimestamp(refreshTimeStamp).strftime("%H:%M:%S")
        else:
             recover_text = datetime.fromtimestamp(refreshTimeStamp).strftime("%m.%d %H:%M:%S")
    else:
        recover_text = t("漂泊者该上潮了", locale)
        is_stamina_urgent = True

    # 结晶
    store_cur = account_info.storeEnergy or 0
    store_total = account_info.storeEnergyLimit if account_info.storeEnergyLimit else 480
    store_percent = min(100, (store_cur / store_total * 100)) if store_total else 0
    store_color = color_red if store_percent > 80 else color_yellow

    # 活跃度
    live_cur = daily_info.livenessData.cur
    live_total = daily_info.livenessData.total
    live_percent = min(100, (live_cur / live_total * 100)) if live_total else 0
    
    # 战歌重奏 (Weekly Boss)
    boss_limit = account_info.weeklyInstCountLimit if account_info.weeklyInstCountLimit else 3
    boss_used = account_info.weeklyInstCount if account_info.weeklyInstCount else 0
    boss_left = max(0, boss_limit - boss_used)

    # 周度游历
    frame_data = getattr(daily_info, "weeklyFrameData", None)
    rogue_cur = (frame_data.cur or 0) if frame_data else 0
    rogue_total = (frame_data.total or 0) if frame_data else 0
    
    # Tower (逆境深塔) - 完成条件: cur == 36
    tower_data = getattr(daily_info, 'towerData', None)
    tower_cur = tower_data.cur if tower_data else 0
    tower_total = tower_data.total if tower_data else 0
    tower_refresh = tower_data.refreshTimeStamp if tower_data else 0
    tower_urgent = False
    if tower_refresh > curr_time:
         remain_days = (datetime.fromtimestamp(tower_refresh) - datetime.now()).days
         tower_time_text = t("余 {} 天", locale).format(remain_days)
         if tower_cur != 36 and remain_days < 7:
             tower_urgent = True
    else:
         tower_time_text = t("已结束", locale)

    # Slash Tower (冥歌海墟) - 只有name为'冥歌海墟·再生-湍渊'才视为完成
    slash_data = getattr(daily_info, 'slashTowerData', None)
    slash_cur = slash_data.cur if slash_data else 0
    slash_total = slash_data.total if slash_data else 0
    slash_refresh = slash_data.refreshTimeStamp if slash_data else 0
    slash_name = slash_data.name if slash_data else ""
    slash_urgent = False
    if slash_refresh > curr_time:
         remain_days = (datetime.fromtimestamp(slash_refresh) - datetime.now()).days
         slash_time_text = t("余 {} 天", locale).format(remain_days)
         slash_completed = (
             slash_name == '冥歌海墟·再生-湍渊'
             and slash_total
             and slash_cur >= slash_total
         )
         if not slash_completed and remain_days < 7:
             slash_urgent = True
    else:
         slash_time_text = t("已结束", locale)

    # 我去，我真变态！
    show_sign_in = not from_sdk
    show_rogue = frame_data is not None
    show_tower = tower_data is not None
    show_slash_tower = slash_data is not None

    context = {
        "locale": locale,
        "user_name": daily_info.roleName,
        "role_id": daily_info.roleId,
        "uid": hide_uid(daily_info.roleId, user_pref=user_pref),
        "avatar_url": avatar_b64,
        "pile_url": pile_b64,
        "has_bg": has_bg,
        "show_sign_in": show_sign_in,
        "show_rogue": show_rogue,
        "show_tower": show_tower,
        "show_slash_tower": show_slash_tower,

        # Icons
        "yes_icon_url": yes_icon_b64,
        "no_icon_url": no_icon_b64,
        "stamina_icon_url": stamina_icon_b64,
        "store_icon_url": store_icon_b64,
        "liveness_icon_url": liveness_icon_b64,
        "bg_url": bg_url_b64,

        # Data
        "stamina": {
            "cur": stamina_cur,
            "total": stamina_total,
            "percent": stamina_percent,
            "color": stamina_color,
            "recovery_text": recover_text,
            "urgent": is_stamina_urgent
        },
        "store_energy": {
            "cur": store_cur,
            "total": store_total,
            "percent": store_percent,
            "color": store_color
        },
        "liveness": {
            "cur": live_cur,
            "total": live_total,
            "percent": live_percent,
            "color": color_yellow
        },
        "battle_pass": {
            "level": daily_info.battlePassData[0].cur if daily_info.battlePassData else 0,
        },
        "weekly_boss": {
            "left": boss_left,
            "total": boss_limit,
        },
        "weekly_rogue": {
            "cur": rogue_cur,
            "total": rogue_total,
        },
        "tower": {
            "cur": tower_cur,
            "total": tower_total,
            "time_text": tower_time_text,
            "urgent": tower_urgent
        },
        "slash_tower": {
            "cur": slash_cur,
            "total": slash_total,
            "time_text": slash_time_text,
            "urgent": slash_urgent
        },
        "sign_in": {
            "status": sign_in_status,
            "text": sign_in_text
        },
        "active_reward": {
            "status": active_status,
            "text": active_text
        },
        "urgent_color": URGENT_COLOR,

        # 自定义图 hash 标记 (None 时模板不渲染)
        "pile_hash": pile_hash,

        # 本地化标签
        "label_daily_status": t("每日状态", locale),
        "label_recovery_time": t("回满时间：", locale),
        "label_stamina": t("结晶波片", locale),
        "label_store": t("结晶单质", locale),
        "label_liveness": t("活跃度", locale),
        "label_weekly_boss": t("战歌重奏", locale),
        "label_battle_pass": t("先约电台", locale),
        "label_rogue": t("周度游历", locale),
        "label_tower": t("逆境深塔", locale),
        "label_slash_tower": t("冥歌海墟", locale),
    }
    
    img_bytes = await render_html(waves_templates, "stamina_card.html", context)
    if img_bytes:
        return Image.open(io.BytesIO(img_bytes))
    return None


@to_thread
def _render_stamina_card_pil(
    img: Image.Image,
    info: Image.Image,
    base_info_bg: Image.Image,
    avatar_ring: Image.Image,
    avatar: Image.Image,
    pile: Image.Image,
    has_bg: bool,
    daily_info: DailyData,
    account_info: AccountBaseInfo,
    sign_in_icon: Image.Image,
    sing_in_text: str,
    active_icon: Image.Image,
    active_text: str,
    locale: str = "",
    pile_hash: Optional[str] = None,
    user_pref: str = "",
    from_sdk: bool = False,
) -> Image.Image:
    """实际的绘制逻辑"""
    # 处理背景图片
    if has_bg:
        bg_w, bg_h = pile.size
        target_w, target_h = 1150, 850
        ratio = max(target_w / bg_w, target_h / bg_h)
        new_size = (int(bg_w * ratio), int(bg_h * ratio))
        pile = pile.resize(new_size, Image.LANCZOS)

        left = (pile.width - target_w) // 2
        top = (pile.height - target_h) // 2
        pile = pile.crop((left, top, left + target_w, top + target_h))

        img.paste(pile, (0, 0))

        info = Image.open(TEXT_PATH / "main_bar_bg.png").convert("RGBA")

    # base_info 特例: GREY 名字 / roleName / 特征码 i18n, 不接公共 draw_base_info_bg
    base_info_draw = ImageDraw.Draw(base_info_bg)
    base_info_draw.text((275, 120), f"{daily_info.roleName[:7]}", GREY, waves_font_30, "lm")
    base_info_draw.text((226, 173), f"{t('特征码:', locale)}  {hide_uid(daily_info.roleId, user_pref=user_pref)}", GOLD, waves_font_25, "lm")
    # 账号基本信息，由于可能会没有，放在一起

    title_bar = Image.open(TEXT_PATH / "title_bar.png")
    title_bar_draw = ImageDraw.Draw(title_bar)
    hud_label_font = waves_font_18 if locale and locale != "chs" else waves_font_26
    title_bar_draw.text((480, 125), t("战歌重奏", locale), GREY, hud_label_font, "mm")
    color = URGENT_COLOR if account_info.weeklyInstCount != 0 else GREEN
    if account_info.weeklyInstCountLimit is not None and account_info.weeklyInstCount is not None:
        title_bar_draw.text(
            (480, 78),
            f"{account_info.weeklyInstCountLimit - account_info.weeklyInstCount} / {account_info.weeklyInstCountLimit}",
            color,
            waves_font_42,
            "mm",
        )

    title_bar_draw.text((630, 125), t("先约电台", locale), GREY, hud_label_font, "mm")
    bp_level = daily_info.battlePassData[0].cur if daily_info.battlePassData else 0
    title_bar_draw.text(
        (630, 78),
        f"Lv.{bp_level}",
        "white",
        waves_font_42,
        "mm",
    )

    frame_data = getattr(daily_info, "weeklyFrameData", None)
    frame_cur = (frame_data.cur or 0) if frame_data else 0
    frame_total = (frame_data.total or 0) if frame_data else 0
    color = RED if frame_cur != frame_total else GREEN
    title_bar_draw.text((810, 125), t("周度游历", locale), GREY, hud_label_font, "mm")
    title_bar_draw.text(
        (810, 78),
        f"{frame_cur}/{frame_total}",
        color,
        waves_font_32,
        "mm",
    )

    # 体力剩余恢复时间
    active_draw = ImageDraw.Draw(info)
    curr_time = int(time.time())
    refreshTimeStamp = daily_info.energyData.refreshTimeStamp if daily_info.energyData.refreshTimeStamp else curr_time
    # remain_time = await seconds2hours(refreshTimeStamp - curr_time)

    time_img = Image.new("RGBA", (180, 33), (255, 255, 255, 0))
    time_img_draw = ImageDraw.Draw(time_img)
    time_img_draw.rounded_rectangle([5, 0, 180, 33], radius=15, fill=(186, 55, 42, int(0.7 * 255)))

    if refreshTimeStamp != curr_time:
        date_from_timestamp = datetime.fromtimestamp(refreshTimeStamp)
        now = datetime.now()
        today = now.date()
        tomorrow = today + timedelta(days=1)

        remain_time = datetime.fromtimestamp(refreshTimeStamp).strftime("%m.%d %H:%M:%S")
        if date_from_timestamp.date() == today:
            remain_time = t("今天", locale) + " " + datetime.fromtimestamp(refreshTimeStamp).strftime("%H:%M:%S")
        elif date_from_timestamp.date() == tomorrow:
            remain_time = t("明天", locale) + " " + datetime.fromtimestamp(refreshTimeStamp).strftime("%H:%M:%S")

        time_img_draw.text((10, 15), f"{remain_time}", "white", waves_font_24, "lm")
    else:
        time_img_draw.text((10, 15), t("漂泊者该上潮了", locale), "white", waves_font_24, "lm")

    info.alpha_composite(time_img, (280, 50))

    max_len = 345

    if has_bg:
        dark_bg_color = (16, 26, 54, int(0.4 * 255))
        # 体力 (Y=115)
        active_draw.rounded_rectangle(
            (342 - 18 * len(f"{daily_info.energyData.cur}"), 98, 430, 135), radius=15, fill=dark_bg_color
        )
        # 结晶 (Y=230)
        active_draw.rounded_rectangle(
            (342 - 18 * len(f"{account_info.storeEnergy}"), 213, 430, 250), radius=15, fill=dark_bg_color
        )
        # 活跃度 (Y=350)
        active_draw.rounded_rectangle(
            (342 - 18 * len(f"{daily_info.livenessData.cur}"), 333, 430, 370), radius=15, fill=dark_bg_color
        )

    # 体力
    active_draw.text((350, 115), f"/{daily_info.energyData.total}", GREY, waves_font_30, "lm")
    active_draw.text((348, 115), f"{daily_info.energyData.cur}", GREY, waves_font_30, "rm")
    radio = daily_info.energyData.cur / daily_info.energyData.total if daily_info.energyData.total else 0
    color = RED if radio > 0.8 else YELLOW
    active_draw.rectangle((173, 142, int(173 + radio * max_len), 150), color)

    # 结晶单质
    active_draw.text((350, 230), f"/{account_info.storeEnergyLimit}", GREY, waves_font_30, "lm")
    active_draw.text((348, 230), f"{account_info.storeEnergy}", GREY, waves_font_30, "rm")
    radio = (
        account_info.storeEnergy / account_info.storeEnergyLimit
        if account_info.storeEnergyLimit is not None
        and account_info.storeEnergy is not None
        and account_info.storeEnergyLimit != 0
        else 0
    )
    color = RED if radio > 0.8 else YELLOW
    active_draw.rectangle((173, 254, int(173 + radio * max_len), 262), color)

    # 活跃度
    active_draw.text((350, 350), f"/{daily_info.livenessData.total}", GREY, waves_font_30, "lm")
    active_draw.text((348, 350), f"{daily_info.livenessData.cur}", GREY, waves_font_30, "rm")
    radio = daily_info.livenessData.cur / daily_info.livenessData.total if daily_info.livenessData.total != 0 else 0
    active_draw.rectangle((173, 374, int(173 + radio * max_len), 382), YELLOW)

    # 签到状态 (国际服走 launcher SDK, 无签到接口, 与 HTML 一致隐藏)
    if not from_sdk:
        status_img = Image.new("RGBA", (230, 40), (255, 255, 255, 0))
        status_img_draw = ImageDraw.Draw(status_img)
        status_img_draw.rounded_rectangle([0, 0, 230, 40], radius=15, fill=(0, 0, 0, int(0.3 * 255)))
        status_img.alpha_composite(sign_in_icon, (0, 0))
        status_img_draw.text((50, 20), f"{sing_in_text}", "white", waves_font_30, "lm")
        img.alpha_composite(status_img, (70, 80))
        if has_bg:
            img.alpha_composite(status_img, (70, 80))

    # 活跃状态
    status_img2 = Image.new("RGBA", (230, 40), (255, 255, 255, 0))
    status_img2_draw = ImageDraw.Draw(status_img2)
    status_img2_draw.rounded_rectangle([0, 0, 230, 40], radius=15, fill=(0, 0, 0, int(0.3 * 255)))
    status_img2.alpha_composite(active_icon, (0, 0))
    status_img2_draw.text((50, 20), f"{active_text}", "white", waves_font_30, "lm")
    img.alpha_composite(status_img2, (70, 140))
    if has_bg:
        img.alpha_composite(status_img2, (70, 140))

    # pile 放在背景上
    # 如果不是自定义背景，则按原样贴立绘
    if not has_bg:
        img.paste(pile, (550, -150), pile)

    # 贴个bar_down
    bar_down_alpha = bar_down.copy()
    if has_bg:
        bar_down_alpha.putalpha(90)
    img.alpha_composite(bar_down_alpha, (0, 624))

    # info 放在背景上
    img.paste(info, (0, 190), info)
    # base_info 放在背景上
    img.paste(base_info_bg, (40, 570), base_info_bg)
    # avatar_ring 放在背景上
    img.paste(avatar_ring, (40, 620), avatar_ring)
    img.paste(avatar, (40, 620), avatar)
    # account_info 放背景上
    img.paste(title_bar, (190, 620), title_bar)
    img = add_footer(img, 600, 25)

    if pile_hash:
        ImageDraw.Draw(img).text(
            (1140, 837), pile_hash,
            fill=(255, 255, 255, 80), font=waves_font_12, anchor="rb",
        )
    return img


async def draw_pic_with_ring(ev: Event):
    pic = await get_event_avatar(ev)
    return await _compose_pic_with_ring(pic)


@to_thread
def _compose_pic_with_ring(pic: Image.Image) -> Image.Image:
    mask_pic = Image.open(TEXT_PATH / "avatar_mask.png")
    img = Image.new("RGBA", (200, 200))
    paste_masked_avatar(img, pic, mask_pic, 160, (20, 20))

    return img
