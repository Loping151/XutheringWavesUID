import asyncio
from typing import Any, List, Union, Optional
from pathlib import Path

from PIL import Image, ImageDraw
from pydantic import BaseModel

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.pool import to_thread
from gsuid_core.utils.image.convert import convert_img

from .rank_avatar import get_avatar
from .pagination import (
    group_rank_empty_page_message,
    paginate_group_rank,
)
from .draw_rank_card import find_role_detail, rank_standard
from ._permissions import get_rank_token_condition, filter_active_group_users
from .draw_phantom_total_rank_card import (
    CY,
    WIDTH,
    ITEM_H,
    TITLE_H,
    FRAME_LEFT,
    FRAME_RIGHT,
    FRAME_TOP,
    FRAME_BOTTOM,
    USER_INFO_X,
    _USER_INFO_BASE_X,
    _AVATAR_VISIBLE_X,
    _AVATAR_MAX_VISIBLE_W,
    PHANTOM_THUMB_X,
    _COL0,
    _COL1,
    _COL_SCORE_RIGHT,
    _EMBLEM_X,
    _EMBLEM_SIZE,
    _SCORE_CENTER_X,
    _SCORE_LABEL_X,
    _SCORE_NUM_LEFT,
    _SCORE_NUM_RIGHT,
    _SCORE_RIGHT_MARGIN,
    _THUMB_EXTENT_W,
    _detect_frame_inner_bounds,
    _stretch_bar,
    draw_props_2col,
    draw_score_cell,
    draw_phantom_thumb,
    draw_phantom_bar_bg,
    draw_rank_and_avatar,
    compose_cond_bar,
    compose_pile_header,
)
from ..utils.util import build_uid_masker
from ..utils.image import (
    RED,
    CHAIN_COLOR,
    SPECIAL_GOLD,
    add_footer,
    get_custom_waves_bg,
    get_attribute_effect,
)
from ..utils.api.model import EquipPhantom, RoleDetailData
from ..utils.calculate import get_calc_map, get_valid_color, calc_phantom_entry, calc_phantom_score
from ..utils.name_convert import alias_to_char_name, char_name_to_char_id
from ..utils.database.models import WavesBind
from ..utils.resource.download_file import get_phantom_img
from ..wutheringwaves_config import PREFIX, WutheringWavesConfig
from ..utils.fonts.waves_fonts import waves_font_18, waves_font_20
from ..utils.resource.constant import SPECIAL_CHAR, SPECIAL_CHAR_NAME

TEXT_PATH = Path(__file__).parent / "texture2d"

_CHAIN_BLOCK_SIZE = (46, 22)
_LEVEL_BLOCK_SIZE = (62, 22)
_INFO_BLOCK_GAP = 6
# 字体墨迹为实测固化值 (跨 Pillow 版本稳定)。
_GROUP_UID_BBOX = (0, -7, 102, 9)  # waves_font_20 "1****789" anchor=lm
_GROUP_INFO_W = _CHAIN_BLOCK_SIZE[0] + _INFO_BLOCK_GAP + _LEVEL_BLOCK_SIZE[0]
_GROUP_UID_W = 103  # waves_font_20 "1****789"
_GROUP_INFO_CONTENT_W = max(_GROUP_INFO_W, _GROUP_UID_W)
_GROUP_INFO_RIGHT = _USER_INFO_BASE_X + _GROUP_INFO_CONTENT_W
_GROUP_RENDERED_INFO_RIGHT = USER_INFO_X + _GROUP_INFO_CONTENT_W
_GROUP_INFO_THUMB_GAP = 10
_GROUP_INFO_THUMB_MIN_GAP = 8
GROUP_PHANTOM_THUMB_X = _GROUP_INFO_RIGHT + _GROUP_INFO_THUMB_GAP
_GROUP_LAYOUT_DX = GROUP_PHANTOM_THUMB_X - PHANTOM_THUMB_X

# bar1.png 两侧边框不参与横向拉伸，因此整条内容左移量也就是群卡宽度缩减量。
GROUP_WIDTH = WIDTH + _GROUP_LAYOUT_DX
with Image.open(TEXT_PATH / "bar1.png") as _group_frame_source:
    GROUP_FRAME_INNER_BOUNDS = _detect_frame_inner_bounds(
        _stretch_bar(_group_frame_source.convert("RGBA"), GROUP_WIDTH, ITEM_H)
    )

GROUP_FRAME_LEFT, GROUP_FRAME_RIGHT, GROUP_FRAME_TOP, GROUP_FRAME_BOTTOM = (
    GROUP_FRAME_INNER_BOUNDS
)
GROUP_COL0 = _COL0 + _GROUP_LAYOUT_DX
GROUP_COL1 = _COL1 + _GROUP_LAYOUT_DX
GROUP_EMBLEM_X = _EMBLEM_X + _GROUP_LAYOUT_DX
GROUP_SCORE_CENTER_X = _SCORE_CENTER_X + _GROUP_LAYOUT_DX

# 群排行无 bot 徽章: 命座行 + uid 拉大间距并整体垂直居中。
_GROUP_INFO_UID_GAP = 22
_GROUP_UID_H = _GROUP_UID_BBOX[3] - _GROUP_UID_BBOX[1]
_GROUP_MAIN_H = _CHAIN_BLOCK_SIZE[1] + _GROUP_INFO_UID_GAP + _GROUP_UID_H
_GROUP_STACK_TOP = GROUP_FRAME_TOP + (
    GROUP_FRAME_BOTTOM - GROUP_FRAME_TOP - _GROUP_MAIN_H
) // 2
_GROUP_INFO_Y = _GROUP_STACK_TOP
_GROUP_UID_Y = (
    _GROUP_INFO_Y
    + _CHAIN_BLOCK_SIZE[1]
    + _GROUP_INFO_UID_GAP
    - _GROUP_UID_BBOX[1]
)


class PhantomRankInfo(BaseModel):
    qid: str  # qq id
    uid: str  # uid
    score: float  # 单声骸分数
    grade: str  # 单声骸评级
    chain: int  # 命座
    chain_name: str  # 命座名
    level: int  # 角色等级
    cost: int  # 声骸 cost
    phantom: EquipPhantom  # 声骸
    entries: List[Any] = []  # 首主词条+5副词条 (name, value, score, is_main, name_color, num_color)


def _score_phantom_entries(role_detail: RoleDetailData, phantom: EquipPhantom, calc_temp) -> List[Any]:
    props = phantom.get_props()
    char_attr = role_detail.role.attributeName or ""
    main_len = len(phantom.mainProps or [])
    scored = []
    for pi, prop in enumerate(props):
        es = 0.0
        if calc_temp:
            try:
                _, es = calc_phantom_entry(pi, prop, phantom.cost, calc_temp, char_attr)
            except Exception as e:
                logger.debug(f"[鸣潮·声骸排行] 单词条分数计算失败: {e}")
        scored.append((prop.attributeName, prop.attributeValue, es))
    entries: List[Any] = []
    for n, v, s in scored[:main_len][:1]:
        entries.append((n, v, s, True, SPECIAL_GOLD, SPECIAL_GOLD))
    for n, v, s in scored[main_len:main_len + 5]:
        nc, vc = get_valid_color(n, v, calc_temp)
        entries.append((n, v, s, False, nc, vc))
    return entries


async def get_phantom_rank_for_user(
    user: WavesBind,
    find_char_id,
    tokenLimitFlag,
    wavesTokenUsersMap,
) -> List[PhantomRankInfo]:
    from ..utils.calc import WuWaCalc

    rankInfoList = []
    if not user.uid:
        return rankInfoList

    tasks = [find_role_detail(uid, find_char_id) for uid in user.uid.split("_")]
    role_details = await asyncio.gather(*tasks)

    for uid, role_detail in zip(user.uid.split("_"), role_details):
        if tokenLimitFlag and (user.user_id, uid) not in wavesTokenUsersMap:
            continue
        if not role_detail:
            continue
        if not role_detail.phantomData or not role_detail.phantomData.equipPhantomList:
            continue

        calc: WuWaCalc = WuWaCalc(role_detail)
        calc.phantom_pre = calc.prepare_phantom()
        calc.phantom_card = calc.enhance_summation_phantom_value(calc.phantom_pre)
        calc.calc_temp = get_calc_map(
            calc.phantom_card,
            role_detail.role.roleName,
            role_detail.role.roleId,
            role=role_detail,
        )

        for _phantom in role_detail.phantomData.equipPhantomList:
            if not _phantom or not _phantom.phantomProp:
                continue
            # 仅统计满 5 副词条的声骸
            if len(_phantom.subProps or []) != 5:
                continue
            props = _phantom.get_props()
            _score, _grade = calc_phantom_score(role_detail.role.roleId, props, _phantom.cost, calc.calc_temp)
            rankInfoList.append(
                PhantomRankInfo(
                    qid=user.user_id,
                    uid=uid,
                    score=_score,
                    grade=_grade,
                    chain=role_detail.get_chain_num(),
                    chain_name=role_detail.get_chain_name(),
                    level=role_detail.role.level,
                    cost=_phantom.cost,
                    phantom=_phantom,
                    entries=_score_phantom_entries(role_detail, _phantom, calc.calc_temp),
                )
            )

    return rankInfoList


async def get_all_phantom_rank_info(
    users: List[WavesBind],
    find_char_id,
    tokenLimitFlag,
    wavesTokenUsersMap,
) -> List[PhantomRankInfo]:
    semaphore = asyncio.Semaphore(50)

    async def process_user(user):
        async with semaphore:
            return await get_phantom_rank_for_user(user, find_char_id, tokenLimitFlag, wavesTokenUsersMap)

    tasks = [process_user(user) for user in users]
    results = await asyncio.gather(*tasks)
    return [rank_info for result in results for rank_info in result]


async def _safe_phantom_icon(phantom: EquipPhantom) -> Optional[Image.Image]:
    try:
        return await get_phantom_img(phantom.phantomProp.phantomId, phantom.phantomProp.iconUrl)
    except Exception as e:
        logger.debug(f"[鸣潮·声骸排行] 声骸图标获取失败 phantomId={phantom.phantomProp.phantomId}: {e}")
        return None


async def _safe_fetter_icon(phantom: EquipPhantom) -> Optional[Image.Image]:
    try:
        return await get_attribute_effect(phantom.fetterDetail.name)
    except Exception as e:
        logger.debug(f"[鸣潮·声骸排行] 套装图标获取失败: {e}")
        return None


async def draw_phantom_rank_img(
    bot: Bot,
    ev: Event,
    char: str,
    page: int = 1,
) -> Union[str, bytes]:
    char_id = char_name_to_char_id(char)
    if not char_id:
        return "未找到指定角色, 请检查输入是否正确！"
    char_name = alias_to_char_name(char)

    find_char_id = SPECIAL_CHAR[char_id] if char_id in SPECIAL_CHAR else char_id

    users = await WavesBind.get_group_all_uid(ev.group_id)
    if WutheringWavesConfig.get_config("RankActiveFilterGroup").data:
        users = await filter_active_group_users(list(users), ev.bot_id, ev.bot_self_id)

    tokenLimitFlag, wavesTokenUsersMap = await get_rank_token_condition(ev)
    if not users:
        msg = [f"[鸣潮] 群【{ev.group_id}】暂无【{char}】面板", f"请使用【{PREFIX}刷新面板】后再使用此功能！"]
        if tokenLimitFlag:
            msg.append(f"当前排行开启了登录验证，请使用命令【{PREFIX}登录】登录后此功能！")
        return "\n".join(msg)

    try:
        self_uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
        if self_uid:
            role_detail = await find_role_detail(self_uid, find_char_id)
            if role_detail:
                char_id = str(role_detail.role.roleId)
    except Exception:
        pass

    rankInfoList = await get_all_phantom_rank_info(list(users), find_char_id, tokenLimitFlag, wavesTokenUsersMap)
    if len(rankInfoList) == 0:
        msg = [f"[鸣潮] 群【{ev.group_id}】暂无【{char_name}】满5副词条声骸数据", f"请使用【{PREFIX}刷新面板】后再使用此功能！"]
        if tokenLimitFlag:
            msg.append(f"当前排行开启了登录验证，请使用命令【{PREFIX}登录】登录后此功能！")
        return "\n".join(msg)

    rankInfoList.sort(key=lambda i: (i.score, i.cost, i.phantom.level, i.qid), reverse=True)

    self_rankId, self_rankInfo = None, None
    if ev.user_id:
        self_rankId, self_rankInfo = next(
            ((rid, ri) for rid, ri in enumerate(rankInfoList, start=1) if ri.qid == ev.user_id),
            (None, None),
        )

    details, display_rank_ids, page_count, page_item_count = paginate_group_rank(
        rankInfoList,
        page,
        self_rankId,
        self_rankInfo,
    )
    if page_item_count == 0:
        return group_rank_empty_page_message(page, page_count)

    if char_id in SPECIAL_CHAR_NAME:
        char_name = SPECIAL_CHAR_NAME[char_id]

    text_bar_h = 130
    total_height = TITLE_H + text_bar_h + ITEM_H * len(details) + 60
    card_img = get_custom_waves_bg(GROUP_WIDTH, total_height, "bg3")

    top_scores = [r.score for r in details[:page_item_count]]
    avg_val = sum(top_scores) / len(top_scores) if top_scores else 0
    compose_cond_bar(card_img, rank_standard(char_id, char_name, "单声骸分数"), TITLE_H, text_bar_h, GROUP_WIDTH)
    await compose_pile_header(card_img, char_id, char_name, "声骸群排行", f"{avg_val:.1f}", GROUP_WIDTH)

    bar = draw_phantom_bar_bg(Image.open(TEXT_PATH / "bar1.png"), GROUP_WIDTH)
    _avatar_cid = int(char_id) if str(char_id).isdigit() else None
    avatar_tasks = [get_avatar(r.qid, "", char_id=_avatar_cid) for r in details]
    icon_tasks = [_safe_phantom_icon(r.phantom) for r in details]
    fetter_tasks = [_safe_fetter_icon(r.phantom) for r in details]
    avatars, phantom_icons, fetter_icons = await asyncio.gather(
        asyncio.gather(*avatar_tasks),
        asyncio.gather(*icon_tasks),
        asyncio.gather(*fetter_tasks),
    )

    _mask_uid = await build_uid_masker([(r.uid, r.qid) for r in details], ev.bot_id)
    uid_texts = [_mask_uid(r.uid, r.qid) for r in details]

    card_img = await _compose_group_rows(
        card_img, bar, details, display_rank_ids, uid_texts, avatars, phantom_icons, fetter_icons,
        ev.user_id, TITLE_H + text_bar_h,
    )
    return await convert_img(card_img)


@to_thread
def _compose_group_rows(card_img, bar, details, display_rank_ids, uid_texts, avatars, phantom_icons, fetter_icons, self_qid, top):
    for idx, temp in enumerate(zip(details, avatars, phantom_icons, fetter_icons)):
        rank, role_avatar, phantom_icon_img, fetter_icon_img = temp
        rank: PhantomRankInfo
        rank_id = display_rank_ids[idx]
        y_pos = top + idx * ITEM_H

        bar_bg = bar.copy()
        draw = ImageDraw.Draw(bar_bg)
        draw_rank_and_avatar(bar_bg, rank_id, role_avatar)

        # 命座 / 等级 (同款角色总排行圆角块)
        ib = Image.new("RGBA", _CHAIN_BLOCK_SIZE, (0, 0, 0, 0))
        ibd = ImageDraw.Draw(ib)
        ibd.rounded_rectangle(
            [0, 0, _CHAIN_BLOCK_SIZE[0] - 1, _CHAIN_BLOCK_SIZE[1] - 1],
            radius=6,
            fill=CHAIN_COLOR[rank.chain] + (int(0.9 * 255),),
        )
        ibd.text((6, 11), f"{rank.chain_name}", "white", waves_font_18, "lm")
        bar_bg.alpha_composite(ib, (USER_INFO_X, _GROUP_INFO_Y))
        ib = Image.new("RGBA", _LEVEL_BLOCK_SIZE, (0, 0, 0, 0))
        ibd = ImageDraw.Draw(ib)
        ibd.rounded_rectangle(
            [0, 0, _LEVEL_BLOCK_SIZE[0] - 1, _LEVEL_BLOCK_SIZE[1] - 1],
            radius=6,
            fill=(54, 54, 54, int(0.9 * 255)),
        )
        ibd.text((6, 11), f"Lv.{rank.level}", "white", waves_font_18, "lm")
        bar_bg.alpha_composite(
            ib,
            (USER_INFO_X + _CHAIN_BLOCK_SIZE[0] + _INFO_BLOCK_GAP, _GROUP_INFO_Y),
        )

        uid_color = RED if rank.qid == self_qid else "white"
        draw.text(
            (USER_INFO_X, _GROUP_UID_Y),
            f"{uid_texts[idx]}",
            uid_color,
            waves_font_20,
            "lm",
        )
        draw_phantom_thumb(
            bar_bg,
            phantom_icon_img,
            fetter_icon_img,
            rank.cost,
            _GROUP_LAYOUT_DX,
        )

        # 词条 (首主词条 + 5副 = 6, 2列) + 评级/分数
        draw_props_2col(bar_bg, draw, rank.entries, _GROUP_LAYOUT_DX)
        draw_score_cell(bar_bg, draw, rank.grade, rank.score, _GROUP_LAYOUT_DX)

        card_img.paste(bar_bg, (0, y_pos), bar_bg)

    return add_footer(card_img)
