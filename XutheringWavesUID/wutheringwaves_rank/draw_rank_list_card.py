import time
import asyncio
from typing import Dict, List, Tuple, Union, Optional
from pathlib import Path

from PIL import Image, ImageDraw
from pydantic import BaseModel

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.pool import to_thread
from gsuid_core.utils.image.convert import convert_img

from .rank_avatar import get_avatar
from .rank_badge import draw_rank_badge
from .pagination import (
    group_rank_empty_page_message,
    paginate_group_rank,
    split_rank_page,
)
from ._permissions import get_rank_token_condition, filter_active_group_users
from ..utils.util import build_uid_masker
from ..utils.image import (
    RED,
    GREY,
    SPECIAL_GOLD,
    get_ICON,
    add_footer,
    get_square_avatar,
    get_custom_waves_bg,
)
from ..utils.api.model import RoleDetailData
from ..utils.calculate import (
    get_calc_map,
    calc_phantom_score,
)
from ..utils.custom_weight import current_plan
from ..utils.char_info_utils import get_all_role_detail_info_list
from ..utils.database.models import WavesBind, WavesUser
from ..utils.database.waves_user_activity import WavesUserActivity
from ..wutheringwaves_config import PREFIX, WutheringWavesConfig
from ..utils.fonts.waves_fonts import (
    waves_font_12,
    waves_font_16,
    waves_font_18,
    waves_font_20,
    waves_font_28,
    waves_font_30,
    waves_font_34,
    waves_font_58,
)
from ..utils.resource.RESOURCE_PATH import PLAYER_PATH


def calculate_role_phantom_score(role_detail: RoleDetailData) -> float:
    """计算单个角色的声骸总分

    Args:
        role_detail: 角色详情

    Returns:
        角色的声骸总分
    """
    from ..utils.calc import WuWaCalc
    if not role_detail.phantomData or not role_detail.phantomData.equipPhantomList:
        return 0.0

    calc: WuWaCalc = WuWaCalc(role_detail)
    calc.phantom_pre = calc.prepare_phantom()
    calc.phantom_card = calc.enhance_summation_phantom_value(calc.phantom_pre)
    calc.calc_temp = get_calc_map(
        calc.phantom_card,
        role_detail.role.roleName,
        role_detail.role.roleId,
        role=role_detail,
    )

    phantom_score = 0.0
    for _phantom in role_detail.phantomData.equipPhantomList:
        if _phantom and _phantom.phantomProp:
            props = _phantom.get_props()
            _score, _ = calc_phantom_score(role_detail.role.roleId, props, _phantom.cost, calc.calc_temp)
            phantom_score += _score

    return phantom_score


async def save_char_list_data(uid: str, char_list_data: Dict):
    """保存角色评分数据到charListData.json

    Args:
        uid: 用户uid
        char_list_data: 角色评分字典，格式为 {roleId: score}
    """
    try:
        from ..utils.player_store import write_player_json
        await write_player_json(PLAYER_PATH / uid / "charListData.json", char_list_data)
    except Exception as e:
        logger.debug(f"[鸣潮·练度排行] 保存 charListData.json 失败 uid={uid}: {e}")


async def load_char_list_data(uid: str) -> Optional[Dict]:
    """从charListData.json读取角色评分数据

    Args:
        uid: 用户uid

    Returns:
        角色评分字典，格式为 {roleId: score}，如果文件不存在返回None
    """
    from ..utils.player_store import read_player_json
    return await read_player_json(PLAYER_PATH / uid / "charListData.json")


TEXT_PATH = Path(__file__).parent / "texture2d"
char_mask = Image.open(TEXT_PATH / "char_mask.png")


class PracticeRankInfo(BaseModel):
    qid: str  # qq id
    uid: str  # uid
    kuro_name: str  # 玩家名字
    total_score: float  # 总声骸分数
    role_details: List[RoleDetailData]  # 角色详情列表


async def _build_practice_rank_for_uid(
    user_id: str, uid: str, threshold: int
) -> Optional[PracticeRankInfo]:
    """单 UID 的练度信息计算，供并发调度。"""
    from ..utils.resource.constant import SPECIAL_CHAR_RANK_MAP
    from ..utils.custom_weight import builtin_only, canon_char, current_plan

    plan = current_plan()
    custom_ids = set(plan.choices) if plan and plan.choices else set()

    char_list_data = await load_char_list_data(uid)

    if char_list_data and custom_ids:
        role_details_list = await get_all_role_detail_info_list(uid)
        char_list_data = dict(char_list_data)
        for r in role_details_list or []:
            mapped_id = SPECIAL_CHAR_RANK_MAP.get(str(r.role.roleId), str(r.role.roleId))
            if canon_char(mapped_id) in custom_ids:
                char_list_data[mapped_id] = calculate_role_phantom_score(r)

    if char_list_data:
        total_score = 0.0
        valid_role_ids = []
        for role_id_str, score in char_list_data.items():
            if score >= threshold:
                total_score += score
                valid_role_ids.append(role_id_str)

        if total_score == 0:
            return None

        role_details_list = await get_all_role_detail_info_list(uid)
        if role_details_list is None:
            return None

        role_details = [
            r for r in role_details_list
            if SPECIAL_CHAR_RANK_MAP.get(str(r.role.roleId), str(r.role.roleId)) in valid_role_ids
        ]
        return PracticeRankInfo(
            qid=user_id, uid=uid, kuro_name=uid,
            total_score=round(total_score, 2), role_details=role_details,
        )

    # charListData.json 不存在，从 rawData 计算并保存
    role_details_list = await get_all_role_detail_info_list(uid)
    if role_details_list is None:
        return None
    role_details = list(role_details_list)
    if not role_details:
        return None

    total_score = 0.0
    valid_role_details = []
    char_list_data = {}
    for role_detail in role_details:
        role_id_str = str(role_detail.role.roleId)
        mapped_id = SPECIAL_CHAR_RANK_MAP.get(role_id_str, role_id_str)
        with builtin_only():
            char_list_data[mapped_id] = calculate_role_phantom_score(role_detail)
        phantom_score = char_list_data[mapped_id]
        if canon_char(mapped_id) in custom_ids:
            phantom_score = calculate_role_phantom_score(role_detail)
        if phantom_score >= threshold:
            total_score += phantom_score
            valid_role_details.append(role_detail)

    if char_list_data:
        await save_char_list_data(uid, char_list_data)

    if total_score == 0:
        return None

    return PracticeRankInfo(
        qid=user_id, uid=uid, kuro_name=uid,
        total_score=round(total_score, 2), role_details=valid_role_details,
    )


async def get_all_rank_list_info(
    users: List[WavesBind],
    threshold: int = 175,
    tokenLimitFlag: bool = False,
    wavesTokenUsersMap: Optional[Dict[Tuple[str, str], str]] = None,
) -> List[PracticeRankInfo]:
    """获取所有用户的练度排行信息（基于声骸分数）

    Args:
        users: 用户列表
        threshold: 计入排行的角色声骸分数阈值 (150-195)
    """
    tasks = []
    semaphore = asyncio.Semaphore(8)

    async def _wrapped(user_id: str, uid: str):
        async with semaphore:
            return await _build_practice_rank_for_uid(user_id, uid, threshold)

    for user in users:
        if not user.uid:
            continue
        for uid in user.uid.split("_"):
            if tokenLimitFlag and wavesTokenUsersMap is not None:
                if (user.user_id, uid) not in wavesTokenUsersMap:
                    continue
            tasks.append(_wrapped(user.user_id, uid))

    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


async def draw_rank_list(bot: Bot, ev: Event, threshold: int = 175) -> Union[str, bytes]:
    from ..utils.calc import WuWaCalc
    start_time = time.time()
    logger.info(f"[鸣潮·练度排行] draw_practice_rank_list start: {start_time}")

    # 检查权限配置
    tokenLimitFlag, wavesTokenUsersMap = await get_rank_token_condition(ev)

    # 解析参数以获取阈值
    text, page = split_rank_page(ev.text or "")
    if text:
        # 支持 s/a/ss 或数字形式
        if text.lower() == "ss":
            threshold = 195
        elif text.lower() == "a":
            threshold = 150
        elif text.lower() == "s":
            threshold = 175

    # 获取群里的所有用户
    users = await WavesBind.get_group_all_uid(ev.group_id)
    if WutheringWavesConfig.get_config("RankActiveFilterGroup").data:
        users = await filter_active_group_users(list(users), ev.bot_id, ev.bot_self_id)
    if not users:
        msg = []
        msg.append(f"[鸣潮] 群【{ev.group_id}】暂无练度排行数据")
        msg.append(f"请使用【{PREFIX}刷新面板】后再使用此功能！")
        if tokenLimitFlag:
            msg.append(f"当前排行开启了登录验证，请使用命令【{PREFIX}登录】登录后此功能！")
        msg.append("")
        return "\n".join(msg)

    rankInfoList = await get_all_rank_list_info(list(users), threshold, tokenLimitFlag, wavesTokenUsersMap)
    if len(rankInfoList) == 0:
        msg = []
        msg.append(f"[鸣潮] 群【{ev.group_id}】暂无练度排行数据")
        msg.append(f"请使用【{PREFIX}刷新面板】后再使用此功能！")
        if tokenLimitFlag:
            msg.append(f"当前排行开启了登录验证，请使用命令【{PREFIX}登录】登录后此功能！")
        msg.append("")
        return "\n".join(msg)

    # 按总声骸分数排序
    rankInfoList.sort(key=lambda i: i.total_score, reverse=True)

    # 获取自己的排名
    self_uid = None
    rankId = None
    rankInfo = None
    try:
        self_uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
        if self_uid:
            rankId, rankInfo = next(
                (
                    (rankId, rankInfo)
                    for rankId, rankInfo in enumerate(rankInfoList, start=1)
                    if rankInfo.uid == self_uid and ev.user_id == rankInfo.qid
                ),
                (None, None),
            )
    except Exception as _:
        pass

    rankInfoList_display, display_rank_ids, page_count, page_item_count = (
        paginate_group_rank(rankInfoList, page, rankId, rankInfo)
    )
    if page_item_count == 0:
        return group_rank_empty_page_message(page, page_count)

    _mask_uid = await build_uid_masker([(ri.uid, ri.qid) for ri in rankInfoList_display], ev.bot_id)

    # 获取等级标签 (S/A/SS)
    threshold_label = "S"  # 默认值
    if threshold == 195:
        threshold_label = "SS"
    elif threshold == 150:
        threshold_label = "A"
    elif threshold == 175:
        threshold_label = "S"

    # 设置图像尺寸 - 变窄
    width = 1000
    text_bar_height = 140
    item_spacing = 120
    header_height = 510
    footer_height = 50
    char_list_len = len(rankInfoList_display)

    # 计算所需的总高度
    total_height = header_height + text_bar_height + item_spacing * char_list_len + footer_height

    # 创建带背景的画布
    card_img = get_custom_waves_bg(width, total_height, "bg9")

    text_bar_img = Image.new("RGBA", (width, 140), color=(0, 0, 0, 0))
    text_bar_draw = ImageDraw.Draw(text_bar_img)
    # 绘制深灰色背景
    bar_bg_color = (36, 36, 41, 230)
    text_bar_draw.rounded_rectangle([20, 20, width - 40, 120], radius=8, fill=bar_bg_color)

    # 绘制顶部的金色高亮线
    accent_color = (203, 161, 95)
    text_bar_draw.rectangle([20, 20, width - 40, 26], fill=accent_color)

    # 左侧标题
    text_bar_draw.text((40, 60), "排行说明", GREY, waves_font_28, "lm")
    text_bar_draw.text(
        (185, 50),
        "1. 综合所有角色的声骸分数。仅计算本地评分，不考虑套装和共享声骸。",
        SPECIAL_GOLD,
        waves_font_20,
        "lm",
    )
    text_bar_draw.text((185, 85), "2. 仅显示近期活跃用户，至多显示声骸分数最高的前8个角色" if WutheringWavesConfig.get_config("RankActiveFilterGroup").data else "2. 至多显示声骸分数最高的前8个角色", SPECIAL_GOLD, waves_font_20, "lm")

    # 备注 - 排行标准，根据阈值动态生成文案
    temp_notes = f"排行标准：以所有角色声骸分数总和（角色分数>={threshold}（{threshold_label}级））为排序的综合排名"
    text_bar_draw.text((width - 40, 110), temp_notes, SPECIAL_GOLD, waves_font_16, "rm")

    card_img.alpha_composite(text_bar_img, (0, header_height))

    # 导入必要的图片资源
    bar = Image.open(TEXT_PATH / "bar2.png")

    # 获取头像
    tasks = [
        get_avatar(rank.qid, getattr(rank, "sender_avatar", ""))
        for rank in rankInfoList_display
    ]
    results = await asyncio.gather(*tasks)

    # 预取每个排名内角色头像（去重）
    all_role_ids = set()
    for rankInfo in rankInfoList_display:
        for role in rankInfo.role_details:
            if role.phantomData and role.phantomData.equipPhantomList:
                all_role_ids.add(role.role.roleId)
    char_avatar_map: Dict[int, Image.Image] = {}
    if all_role_ids:
        fetched = await asyncio.gather(*[get_square_avatar(rid) for rid in all_role_ids])
        char_avatar_map = dict(zip(all_role_ids, fetched))

    card_img = await _compose_rank_list(
        card_img, bar, rankInfoList_display, display_rank_ids, results, char_avatar_map,
        self_uid, threshold_label, header_height, item_spacing, width, _mask_uid,
        plan=current_plan(),
    )
    card_img = await convert_img(card_img)

    return card_img


@to_thread
def _compose_rank_list(*args, plan=None, **kwargs):
    from ..utils.custom_weight import using

    with using(plan):
        return _compose_rank_list_impl(*args, **kwargs)


def _compose_rank_list_impl(card_img, bar, rankInfoList_display, display_rank_ids, results, char_avatar_map,
                            self_uid, threshold_label, header_height, item_spacing, width, mask_uid=None):
    from ..utils.calc import WuWaCalc
    for rank_temp_index, temp in enumerate(zip(rankInfoList_display, results)):
        rankInfo = temp[0]
        role_avatar = temp[1]
        y_pos = header_height + 130 + rank_temp_index * item_spacing

        bar_bg = bar.copy()
        bar_bg.paste(role_avatar, (100, 0), role_avatar)
        bar_draw = ImageDraw.Draw(bar_bg)

        rank_id = display_rank_ids[rank_temp_index]
        draw_rank_badge(bar_bg, rank_id)

        uid_color = "white"
        if rankInfo.uid == self_uid:
            uid_color = RED
        bar_draw.text((210, 40), f"{mask_uid(rankInfo.uid, rankInfo.qid)}", uid_color, waves_font_20, "lm")

        char_count = len(rankInfo.role_details)
        bar_draw.text((210, 75), f"{threshold_label}角色数: {char_count}", "white", waves_font_18, "lm")

        if rankInfo.role_details:
            role_scores = []
            for role in rankInfo.role_details:
                if not role.phantomData or not role.phantomData.equipPhantomList:
                    continue
                calc: WuWaCalc = WuWaCalc(role)
                calc.phantom_pre = calc.prepare_phantom()
                calc.phantom_card = calc.enhance_summation_phantom_value(calc.phantom_pre)
                calc.calc_temp = get_calc_map(
                    calc.phantom_card,
                    role.role.roleName,
                    role.role.roleId,
                    role=role,
                )
                phantom_score = 0.0
                for _phantom in role.phantomData.equipPhantomList:
                    if _phantom and _phantom.phantomProp:
                        props = _phantom.get_props()
                        _score, _ = calc_phantom_score(role.role.roleId, props, _phantom.cost, calc.calc_temp)
                        phantom_score += _score
                role_scores.append((role, phantom_score))

            sorted_roles = sorted(role_scores, key=lambda x: x[1], reverse=True)[:8]

            char_size = 40
            char_spacing = 45
            char_start_x = 350
            char_start_y = 35

            char_mask_img = Image.open(TEXT_PATH / "char_mask.png")
            char_mask_resized = char_mask_img.resize((char_size, char_size))
            for i, (role, score) in enumerate(sorted_roles):
                char_x = char_start_x + i * char_spacing

                char_avatar = char_avatar_map.get(role.role.roleId)
                if char_avatar is None:
                    continue
                char_avatar = char_avatar.resize((char_size, char_size))

                char_avatar_masked = Image.new("RGBA", (char_size, char_size))
                char_avatar_masked.paste(char_avatar, (0, 0), char_mask_resized)

                bar_bg.paste(char_avatar_masked, (char_x, char_start_y), char_avatar_masked)

                score_text = f"{int(score)}"
                bar_draw.text(
                    (char_x + char_size // 2, char_start_y + char_size + 2),
                    score_text,
                    SPECIAL_GOLD,
                    waves_font_12,
                    "mm",
                )

            if sorted_roles:
                best_score = f"{int(sorted_roles[0][1])}"
                bar_draw.text((760, 45), best_score, "lightgreen", waves_font_30, "mm")
                bar_draw.text((760, 75), "最高分", "white", waves_font_16, "mm")

        bar_draw.text(
            (880, 45),
            f"{rankInfo.total_score}",
            (255, 255, 255),
            waves_font_34,
            "mm",
        )
        bar_draw.text((880, 75), "总分", "white", waves_font_16, "mm")

        card_img.paste(bar_bg, (0, y_pos), bar_bg)

    title_bg = Image.open(TEXT_PATH / "totalrank.jpg")
    title_bg = title_bg.crop((0, 0, width, 475))

    icon = get_ICON()
    icon = icon.resize((128, 128))
    title_bg.paste(icon, (60, 240), icon)

    title_text = "#练度群排行"
    title_bg_draw = ImageDraw.Draw(title_bg)
    title_bg_draw.text((220, 290), title_text, "white", waves_font_58, "lm")
    date_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    title_bg_draw.text((225, 360), date_text, GREY, waves_font_20, "lm")

    char_mask_img = Image.open(TEXT_PATH / "char_mask.png").convert("RGBA")
    char_mask_img = char_mask_img.resize((width, char_mask_img.height * width // char_mask_img.width))
    char_mask_img = char_mask_img.crop((0, char_mask_img.height - 475, width, char_mask_img.height))
    char_mask_temp = Image.new("RGBA", char_mask_img.size, (0, 0, 0, 0))
    char_mask_temp.paste(title_bg, (0, 0), char_mask_img)

    card_img.paste(char_mask_temp, (0, 0), char_mask_temp)

    card_img = add_footer(card_img)
    return card_img
