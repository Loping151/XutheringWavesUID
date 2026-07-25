import time
import asyncio
from math import ceil
from typing import Any, List, Union, Optional
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from gsuid_core.bot import Bot
from gsuid_core.pool import to_thread
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img

from .rank_bar import stretch_rank_bar as _stretch_bar
from .pagination import RANK_PAGE_SIZE
from .rank_badge import _load_badge, draw_bot_name_badge
from ..utils.util import hide_uid, get_version
from .rank_avatar import get_avatar
from ..utils.image import (
    RED,
    GREY,
    SPECIAL_GOLD,
    WAVES_FREEZING,
    add_footer,
    get_custom_waves_bg,
    get_attribute_effect,
    get_role_pile_default,
)
from .draw_rank_card import find_role_detail
from ..utils.api.wwapi import (
    GET_PHANTOM_TOTAL_RANK_URL,
    PhantomRankProp,
    PhantomTotalRankDetail,
    PhantomTotalRankRequest,
    PhantomTotalRankResponse,
)
from ..utils.calculate import get_calc_map, get_valid_color, calc_phantom_entry, calc_phantom_score
from ..utils.name_convert import char_id_to_char_name, char_name_to_char_id
from ..utils.database.models import WavesBind
from ..wutheringwaves_config import WutheringWavesConfig
from ..utils.fonts.waves_fonts import (
    fit_text,
    waves_font_14,
    waves_font_16,
    waves_font_18,
    waves_font_20,
    waves_font_22,
    waves_font_24,
    waves_font_30,
    waves_font_34,
    waves_font_40,
    waves_font_44,
)
from ..utils.resource.constant import SPECIAL_CHAR, SPECIAL_CHAR_NAME
from ..utils.resource.download_file import get_phantom_img

TEXT_PATH = Path(__file__).parent / "texture2d"
TITLE_II = Image.open(TEXT_PATH / "title2.png")
char_mask = Image.open(TEXT_PATH / "char_mask.png")
logo_img = Image.open(TEXT_PATH / "logo_small_2.png")
promote_icon = Image.open(TEXT_PATH / "promote_icon.png")

# 由左侧内容收紧后的实测列宽反推：第二词条列右边界 1151px，随后依次保留
# 14px 评分区间距、84px 评级图、12px 图文间距、144px 最大分数、16px 内边距和
# bar1.png 实测 43px 右框外沿。
WIDTH = 1416
ITEM_H = 150  # 单条声骸高度 (内容全部落在金线框内)
CY = ITEM_H // 2
TITLE_H = 500

SCORE_POS = WAVES_FREEZING  # 词条分>0
SCORE_ZERO = (120, 120, 120)  # 词条分=0


def _bright_runs(points: List[int]) -> List[tuple[int, int]]:
    """把扫描线上的亮点整理成闭区间，供金线边界检测使用。"""
    if not points:
        return []
    runs: List[tuple[int, int]] = []
    start = previous = points[0]
    for point in points[1:]:
        if point != previous + 1:
            runs.append((start, previous))
            start = point
        previous = point
    runs.append((start, previous))
    return runs


def _detect_frame_inner_bounds(bar: Image.Image) -> tuple[int, int, int, int]:
    """从横/纵中线检测亮金线，返回 PIL 半开内框 (left, right, top, bottom)。"""

    def is_bright_line(pixel) -> bool:
        red, green, blue, alpha = pixel
        luminance = (299 * red + 587 * green + 114 * blue) / 1000
        return alpha > 60 and luminance > 110

    mid_x, mid_y = bar.width // 2, bar.height // 2
    x_runs = _bright_runs(
        [x for x in range(bar.width) if is_bright_line(bar.getpixel((x, mid_y)))]
    )
    y_runs = _bright_runs(
        [y for y in range(bar.height) if is_bright_line(bar.getpixel((mid_x, y)))]
    )
    left_line = max((run for run in x_runs if run[1] < mid_x), key=lambda run: run[1])
    right_line = min((run for run in x_runs if run[0] > mid_x), key=lambda run: run[0])
    top_line = max((run for run in y_runs if run[1] < mid_y), key=lambda run: run[1])
    bottom_line = min((run for run in y_runs if run[0] > mid_y), key=lambda run: run[0])
    return left_line[1] + 1, right_line[0], top_line[1] + 1, bottom_line[0]


with Image.open(TEXT_PATH / "bar1.png") as _frame_source:
    FRAME_INNER_BOUNDS = _detect_frame_inner_bounds(
        _stretch_bar(_frame_source.convert("RGBA"), WIDTH, ITEM_H)
    )

FRAME_LEFT, FRAME_RIGHT, FRAME_TOP, FRAME_BOTTOM = FRAME_INNER_BOUNDS
_FRAME_W = FRAME_RIGHT - FRAME_LEFT
_FRAME_H = FRAME_BOTTOM - FRAME_TOP

# 左区: 排名在金框外；头像、用户信息、bot 徽章、声骸图在框内。
# 所有锚点均由实测内框和图片尺寸推导。
_RANK_MEDAL_SIZE = (55, 55)
_RANK_BOX_SIZE = (50, 50)
_RANK_X = FRAME_LEFT // 4
_RANK_MEDAL_Y = FRAME_TOP + (_FRAME_H - _RANK_MEDAL_SIZE[1]) // 2
_RANK_BOX_Y = FRAME_TOP + (_FRAME_H - _RANK_BOX_SIZE[1]) // 2
_AVATAR_FRAME_INSET = -40
_AVATAR_VISIBLE_X = FRAME_LEFT + _AVATAR_FRAME_INSET
_AVATAR_VISIBLE_W = 120
_USER_INFO_BASE_GAP = 14
_USER_INFO_BASE_X = _AVATAR_VISIBLE_X + _AVATAR_VISIBLE_W + _USER_INFO_BASE_GAP
# get_avatar 两条实际遮罩路径的 alpha bbox 实测宽度。
_AVATAR_QQ_DB_VISIBLE_W = 94
_AVATAR_CHAR_VISIBLE_W = 101
_AVATAR_MAX_VISIBLE_W = max(_AVATAR_QQ_DB_VISIBLE_W, _AVATAR_CHAR_VISIBLE_W)
_AVATAR_INFO_SAFE_GAP = 8
USER_INFO_X = _AVATAR_VISIBLE_X + _AVATAR_MAX_VISIBLE_W + _AVATAR_INFO_SAFE_GAP

_BOT_BADGE_SIZE = (208, 39)
_BOT_BADGE_BOTTOM_INSET = 8
_BOT_BADGE_X_OFFSET = -4
_BOT_BADGE_POS = (
    USER_INFO_X + _BOT_BADGE_X_OFFSET,
    FRAME_BOTTOM - _BOT_BADGE_SIZE[1] - _BOT_BADGE_BOTTOM_INSET,
)
_BOT_THUMB_GAP = 12
_PHANTOM_ICON_SIZE = (84, 84)
_FETTER_ICON_SIZE = (28, 28)
_PROMOTE_SIZE = (18, 18)
_THUMB_EXTENT_W = max(_PHANTOM_ICON_SIZE[0], 58 + _FETTER_ICON_SIZE[0])
PHANTOM_THUMB_X = (
    _USER_INFO_BASE_X
    + _BOT_BADGE_X_OFFSET
    + _BOT_BADGE_SIZE[0]
    + _BOT_THUMB_GAP
)
_USER_NAME_MAX_WIDTH = PHANTOM_THUMB_X - USER_INFO_X - _BOT_THUMB_GAP
_PHANTOM_ICON_Y = FRAME_TOP + (_FRAME_H - _PHANTOM_ICON_SIZE[1]) // 2
_FETTER_ICON_POS = (
    PHANTOM_THUMB_X + 58,
    FRAME_BOTTOM - _FETTER_ICON_SIZE[1] - _PROMOTE_SIZE[1],
)
_PROMOTE_Y = FRAME_BOTTOM - _PROMOTE_SIZE[1]
_THUMB_SHIFT = 14  # 声骸头像/套装/cost 整体左移 (词条列不动)

# 词条表: 名称/数值/分数列宽为固定字体墨迹的实测固化值 (跨 Pillow 版本稳定)。
_NAME_FONTS = (waves_font_18, waves_font_16, waves_font_14)
_NAME_MAX = 128  # waves_font_16 "共鸣解放伤害加成"
_VALUE_MAX = 53  # waves_font_16 max("2400","30.0%")
_PROP_SCORE_MAX = 69  # waves_font_16 "+120.55"
_NAME_VALUE_GAP = 8
_VALUE_SCORE_GAP = 10
_PROP_COL_GAP = 12
_PROP_COL_W = (
    _NAME_MAX
    + _NAME_VALUE_GAP
    + _VALUE_MAX
    + _VALUE_SCORE_GAP
    + _PROP_SCORE_MAX
)
_COL0 = PHANTOM_THUMB_X + _THUMB_EXTENT_W + 12
_COL1 = _COL0 + _PROP_COL_W + _PROP_COL_GAP
_COL_NAME_X = (_COL0, _COL1)
_COL_VALUE_RIGHT = tuple(
    x + _NAME_MAX + _NAME_VALUE_GAP + _VALUE_MAX for x in _COL_NAME_X
)
_COL_SCORE_RIGHT = tuple(
    x + _PROP_COL_W for x in _COL_NAME_X
)
_PROP_ROW_GAP = 31
_PROP_ROW_Y = (CY - _PROP_ROW_GAP, CY, CY + _PROP_ROW_GAP)

# 评分区: 40px 分数和标签共用固定中心，再以最宽样例反推 84px 评级图位置。
_EMBLEM_SIZE = (96, 96)  # 评级图放大, 中心不变
_PROP_SCORE_CELL_GAP = 14
_SCORE_RIGHT_MARGIN = 16
_SCORE_NUM_MAX = 144  # waves_font_40 "999.99"
_SCORE_LABEL_MAX = 80  # waves_font_16 "单声骸分数"
_SCORE_BLOCK_HALF_W = ceil(max(_SCORE_NUM_MAX, _SCORE_LABEL_MAX) / 2)
_SCORE_CENTER_X = FRAME_RIGHT - _SCORE_RIGHT_MARGIN - _SCORE_BLOCK_HALF_W
_SCORE_NUM_LEFT = _SCORE_CENTER_X - _SCORE_BLOCK_HALF_W
_SCORE_NUM_RIGHT = _SCORE_CENTER_X + _SCORE_BLOCK_HALF_W
_EMBLEM_NUM_GAP = 12
_EMBLEM_CENTER_X = _SCORE_NUM_LEFT - _EMBLEM_NUM_GAP - 42  # 沿用原 84px 图中心, 放大不移位
_EMBLEM_X = _EMBLEM_CENTER_X - _EMBLEM_SIZE[0] // 2
_EMBLEM_Y = FRAME_TOP + (_FRAME_H - _EMBLEM_SIZE[1]) // 2
_SCORE_NUM_X = _SCORE_CENTER_X
_SCORE_LABEL_X = _SCORE_CENTER_X
_SCORE_NUM_BBOX = (-72, -13, 72, 18)  # waves_font_40 "999.99" anchor=mm
_SCORE_LABEL_BBOX = (-40, -7, 40, 9)  # waves_font_16 "单声骸分数" anchor=mm
_SCORE_STACK_GAP = 16
_SCORE_NUM_H = _SCORE_NUM_BBOX[3] - _SCORE_NUM_BBOX[1]
_SCORE_LABEL_H = _SCORE_LABEL_BBOX[3] - _SCORE_LABEL_BBOX[1]
_SCORE_STACK_H = _SCORE_NUM_H + _SCORE_STACK_GAP + _SCORE_LABEL_H
_SCORE_STACK_TOP = FRAME_TOP + (_FRAME_H - _SCORE_STACK_H) // 2
_SCORE_NUM_Y = _SCORE_STACK_TOP - _SCORE_NUM_BBOX[1]
_SCORE_LABEL_Y = (
    _SCORE_STACK_TOP + _SCORE_NUM_H + _SCORE_STACK_GAP - _SCORE_LABEL_BBOX[1]
)

# 总排行用户文字在 bot 徽章上方按字体墨迹高度垂直居中。
_USER_NAME_BBOX = (0, -10, 110, 12)  # waves_font_22 "库洛玩家名" anchor=lm
_USER_UID_BBOX = (0, -9, 157, 9)  # waves_font_18 "特征码: 1****789" anchor=lm
_USER_TEXT_GAP = 8
_USER_UID_EXTRA = 5  # UID 相对居中位置再往下一点
_USER_TEXT_H = (
    _USER_NAME_BBOX[3]
    - _USER_NAME_BBOX[1]
    + _USER_TEXT_GAP
    + _USER_UID_BBOX[3]
    - _USER_UID_BBOX[1]
)
_USER_TEXT_TOP = FRAME_TOP + (_BOT_BADGE_POS[1] - FRAME_TOP - _USER_TEXT_H) // 2
_USER_NAME_Y = _USER_TEXT_TOP - _USER_NAME_BBOX[1]
_USER_UID_Y = (
    _USER_TEXT_TOP
    + _USER_NAME_BBOX[3]
    - _USER_NAME_BBOX[1]
    + _USER_TEXT_GAP
    + _USER_UID_EXTRA
    - _USER_UID_BBOX[1]
)


def draw_phantom_bar_bg(bar: Image.Image, width: int = WIDTH) -> Image.Image:
    return _stretch_bar(bar, width, ITEM_H)


def draw_rank_and_avatar(bar_bg: Image.Image, rank_id: int, avatar: Optional[Image.Image]) -> None:
    """左侧独立排名 + 头像；头像按 alpha 墨迹框在实测金线上下居中。"""
    if avatar is not None:
        alpha_bbox = avatar.getchannel("A").getbbox()
        if alpha_bbox is not None:
            visible_w = alpha_bbox[2] - alpha_bbox[0]
            visible_h = alpha_bbox[3] - alpha_bbox[1]
            avatar_x = _AVATAR_VISIBLE_X - alpha_bbox[0]
            avatar_y = FRAME_TOP + (_FRAME_H - visible_h) // 2 - alpha_bbox[1]
            assert _AVATAR_VISIBLE_X + visible_w <= USER_INFO_X
            assert FRAME_TOP <= avatar_y + alpha_bbox[1]
            assert avatar_y + alpha_bbox[3] <= FRAME_BOTTOM
            bar_bg.alpha_composite(avatar, (avatar_x, avatar_y))
    badge = _load_badge(rank_id)
    if badge is not None:
        bar_bg.alpha_composite(badge, (_RANK_X, _RANK_MEDAL_Y))
    else:
        if rank_id > 999:  # 4 位/999+: 加宽底板, 受左侧金框外空间限制字号略小
            _rt = "999+" if rank_id > 1000 else f"{rank_id}"
            _rf, box_w = waves_font_30, 88
        elif rank_id > 99:
            _rt, _rf, box_w = f"{rank_id}", waves_font_34, 72
        else:
            _rt, _rf, box_w = f"{rank_id}", waves_font_34, _RANK_BOX_SIZE[0]
        box_h = _RANK_BOX_SIZE[1]
        box = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        bd = ImageDraw.Draw(box)
        bd.rounded_rectangle(
            [0, 0, box_w - 1, box_h - 1],
            radius=8,
            fill=(54, 54, 54, int(0.9 * 255)),
        )
        bd.text((box_w // 2, box_h // 2), _rt, "white", _rf, "mm")
        cx = _RANK_X + _RANK_BOX_SIZE[0] // 2
        bar_bg.alpha_composite(box, (cx - box_w // 2, _RANK_BOX_Y))


def draw_phantom_thumb(
    bar_bg: Image.Image,
    icon: Optional[Image.Image],
    fetter: Optional[Image.Image],
    cost: int,
    dx: int = 0,
) -> None:
    """声骸头像 + 套装图标 + cost, 全部落在金线框内。"""
    x = PHANTOM_THUMB_X + dx - _THUMB_SHIFT
    if icon is not None:
        bar_bg.alpha_composite(
            icon.resize(_PHANTOM_ICON_SIZE),
            (x, _PHANTOM_ICON_Y),
        )
    if fetter is not None:
        bar_bg.alpha_composite(
            fetter.resize(_FETTER_ICON_SIZE),
            (x + 58, _FETTER_ICON_POS[1]),
        )
    promote = promote_icon.resize(_PROMOTE_SIZE)
    # cost 在声骸头像正下方水平居中 (最大 4c, 均匀排布)
    _pip_gap = 3
    _pip_step = _PROMOTE_SIZE[0] + _pip_gap
    _pips_w = cost * _PROMOTE_SIZE[0] + max(cost - 1, 0) * _pip_gap
    _pips_x = x + (_PHANTOM_ICON_SIZE[0] - _pips_w) // 2
    for j in range(0, cost):
        bar_bg.alpha_composite(
            promote,
            (_pips_x + _pip_step * j, _PROMOTE_Y),
        )


def draw_props_2col(
    bar_bg: Image.Image,
    draw: ImageDraw.ImageDraw,
    entries: List[Any],
    dx: int = 0,
) -> None:
    """词条 2 列对齐表: 名左对齐、数值/分数分别按固定右边界对齐。
    entries: (name, value, score, is_main, name_color, num_color)"""
    for i, entry in enumerate(entries[:6]):
        name, value, pscore, is_main, name_color, num_color = entry
        r, c = divmod(i, 2)
        name_x = _COL_NAME_X[c] + dx
        value_right = _COL_VALUE_RIGHT[c] + dx
        score_right = _COL_SCORE_RIGHT[c] + dx
        y = _PROP_ROW_Y[r]
        nf, name = fit_text(draw, name, _NAME_MAX, _NAME_FONTS)
        if is_main:
            hl_size = (score_right - name_x + 12, 26)
            hl = Image.new("RGBA", hl_size, (0, 0, 0, 0))
            ImageDraw.Draw(hl).rounded_rectangle(
                [0, 0, hl_size[0] - 1, hl_size[1] - 1],
                radius=6,
                fill=(234, 183, 4, 46),
            )
            bar_bg.alpha_composite(hl, (name_x - 6, y - hl_size[1] // 2))
        draw.text((name_x, y), name, name_color, nf, "lm")
        draw.text((value_right, y), value, num_color, waves_font_16, "rm")
        draw.text(
            (score_right, y),
            f"+{pscore:.2f}",
            SCORE_POS if pscore > 0 else SCORE_ZERO,
            waves_font_16,
            "rm",
        )


def draw_score_cell(
    bar_bg: Image.Image,
    draw: ImageDraw.ImageDraw,
    grade: str,
    score: float,
    dx: int = 0,
) -> None:
    """右侧评级贴图 + 单声骸总分, 落在金线框内。"""
    try:
        em = Image.open(TEXT_PATH / f"score_{grade}.png").resize(_EMBLEM_SIZE)
        bar_bg.alpha_composite(em, (_EMBLEM_X + dx, _EMBLEM_Y))
    except Exception as e:
        logger.debug(f"[鸣潮·声骸排行] 评级贴图缺失 grade={grade}: {e}")
    draw.text(
        (_SCORE_NUM_X + dx, _SCORE_NUM_Y),
        f"{score:.2f}",
        "white",
        waves_font_40,
        "mm",
    )
    draw.text(
        (_SCORE_LABEL_X + dx, _SCORE_LABEL_Y),
        "单声骸分数",
        SPECIAL_GOLD,
        waves_font_16,
        "mm",
    )


def build_entries(main_props, sub_props, calc_map) -> List[Any]:
    """首个主词条(金色) + 5 副词条(按有效性上色, 照角色面板 get_valid_color)。
    *_props 元素需有 .name/.value/.score。"""
    entries: List[Any] = []
    for p in main_props[:1]:
        entries.append((p.name, p.value, p.score, True, SPECIAL_GOLD, SPECIAL_GOLD))
    for p in sub_props[:5]:
        nc, vc = get_valid_color(p.name, p.value, calc_map)
        entries.append((p.name, p.value, p.score, False, nc, vc))
    return entries


async def compose_pile_header(
    card_img: Image.Image, char_id: str, char_name: str, title_suffix: str, avg_score: str, width: int = WIDTH
) -> None:
    """人物立绘头部 (照角色总排行版式)。就地写入 card_img。"""
    if char_id in SPECIAL_CHAR_NAME:
        char_name = SPECIAL_CHAR_NAME[char_id]
    title_name = f"{char_name}{title_suffix}"

    title = TITLE_II.copy()
    title_draw = ImageDraw.Draw(title)
    title.alpha_composite(logo_img.copy(), dest=(350, 65))

    title_draw.text((600, 335), f"{avg_score}", "white", waves_font_44, "mm")
    title_draw.text((600, 375), "平均单声骸分数", SPECIAL_GOLD, waves_font_20, "mm")
    title_draw.text((540, 265), f"{title_name}", "black", waves_font_30, "lm")
    time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    title_draw.text((470, 205), f"{time_str}", GREY, waves_font_20, "lm")

    info_block = Image.new("RGBA", (100, 30), color=(255, 255, 255, 0))
    info_block_draw = ImageDraw.Draw(info_block)
    info_block_draw.rounded_rectangle([0, 0, 100, 30], radius=6, fill=(0, 79, 152, int(0.9 * 255)))
    info_block_draw.text((50, 15), f"v{get_version()}", "white", waves_font_24, "mm")
    title.alpha_composite(info_block, (540 + 31 * len(title_name), 255))

    mask = char_mask.resize((width, char_mask.size[1]))
    img_temp = Image.new("RGBA", mask.size)
    img_temp.alpha_composite(title, (-300, 0))
    pile, _ = await get_role_pile_default(char_id, custom=True)
    img_temp.alpha_composite(pile, (width - 700, -120))

    img_temp2 = Image.new("RGBA", mask.size)
    img_temp2.paste(img_temp, (0, 0), mask.copy())
    card_img.alpha_composite(img_temp2, (0, 0))


def compose_cond_bar(card_img: Image.Image, notes: str, y: int, height: int = 130, width: int = WIDTH) -> None:
    """上榜条件说明栏 (照角色总排行版式)。"""
    text_bar = Image.new("RGBA", (width, height), color=(0, 0, 0, 0))
    d = ImageDraw.Draw(text_bar)
    d.rounded_rectangle([20, 20, width - 20, height - 15], radius=8, fill=(36, 36, 41, 230))
    d.rectangle([20, 20, width - 20, 26], fill=(203, 161, 95))
    d.text((40, 60), "上榜条件", GREY, waves_font_24, "lm")
    d.text((185, 50), "1. 声骸满 5 副词条 & 常规有效套装", SPECIAL_GOLD, waves_font_20, "lm")
    d.text((185, 85), "2. 登录用户 & 刷新面板", SPECIAL_GOLD, waves_font_20, "lm")
    d.text((width - 40, height - 30), notes, SPECIAL_GOLD, waves_font_16, "rm")
    card_img.alpha_composite(text_bar, (0, y))


async def get_phantom_total_rank(item: PhantomTotalRankRequest) -> Optional[PhantomTotalRankResponse]:
    WavesToken = WutheringWavesConfig.get_config("WavesToken").data

    if not WavesToken:
        return

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                GET_PHANTOM_TOTAL_RANK_URL,
                json=item.model_dump(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {WavesToken}",
                },
                timeout=httpx.Timeout(10),
            )
            if res.status_code == 200:
                return PhantomTotalRankResponse.model_validate(res.json())
            else:
                logger.warning(f"[鸣潮·声骸总排行] 获取远端排行失败: {res.status_code} - {res.text}")
        except Exception as e:
            logger.exception(f"[鸣潮·声骸总排行] 获取远端排行失败: {e}")


async def _safe_phantom_icon(detail: PhantomTotalRankDetail) -> Optional[Image.Image]:
    try:
        return await get_phantom_img(detail.phantom_id, detail.icon_url)
    except Exception as e:
        logger.debug(f"[鸣潮·声骸总排行] 声骸图标获取失败 phantomId={detail.phantom_id}: {e}")
        return None


async def _safe_fetter_icon(set_name: str) -> Optional[Image.Image]:
    try:
        if not set_name:
            return None
        return await get_attribute_effect(set_name)
    except Exception as e:
        logger.debug(f"[鸣潮·声骸总排行] 套装图标获取失败: {e}")
        return None


async def draw_phantom_total_rank(bot: Bot, ev: Event, char: str, pages: int) -> Union[str, bytes]:
    char_id = char_name_to_char_id(char)
    if not char_id:
        return "未找到指定角色, 请检查输入是否正确！"
    char = char_id_to_char_name(char_id) or char
    self_uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not self_uid:
        self_uid = ""
    item = PhantomTotalRankRequest(
        char_id=int(char_id),
        page=pages,
        page_num=RANK_PAGE_SIZE,
        waves_id=self_uid,
        version=get_version(dynamic=True, waves_id=self_uid, pages=pages),
    )

    rankInfoList = await get_phantom_total_rank(item)
    if not rankInfoList:
        return "获取声骸总排行失败"
    if rankInfoList.message and not rankInfoList.data:
        return rankInfoList.message
    if not rankInfoList.data or not rankInfoList.data.rank_list:
        return "暂无排行数据"

    ranking = rankInfoList.data.rank_list
    details = list(ranking)

    # 自己行(仅登录/绑定时): 在榜用服务器数据; 未上榜用本地最高 5 副词条声骸 + 999+
    self_entry = getattr(rankInfoList.data, "self_entry", None)
    if self_uid and self_entry is not None:
        if self_entry.rank and self_entry.rank > 0:
            self_row = self_entry
        else:
            self_row = await _build_local_self_row(self_uid, char_id, self_entry)
        if self_row is not None:
            details.append(self_row)

    if not details:
        return f"[鸣潮] 暂无【{char}】声骸总排行数据"

    try:
        calc_map = get_calc_map({}, char, char_id)
    except Exception as e:
        logger.debug(f"[鸣潮·声骸总排行] calc_map 获取失败 char_id={char_id}: {e}")
        calc_map = None

    text_bar_h = 130
    total_height = TITLE_H + text_bar_h + ITEM_H * len(details) + 60
    card_img = get_custom_waves_bg(WIDTH, total_height, "bg3")

    compose_cond_bar(card_img, "排行标准：以单声骸分数排序 (评分高不代表实际伤害高)", TITLE_H, text_bar_h)

    avg_val = sum(d.score for d in ranking) / len(ranking) if ranking else 0
    await compose_pile_header(card_img, char_id, char, "声骸总排行", f"{avg_val:.1f}")

    bar = draw_phantom_bar_bg(Image.open(TEXT_PATH / "bar1.png"))
    avatar_tasks = [get_avatar(d.user_id, getattr(d, "sender_avatar", ""), char_id=d.char_id) for d in details]
    phantom_tasks = [_safe_phantom_icon(d) for d in details]
    fetter_tasks = [_safe_fetter_icon(d.set) for d in details]
    avatars, phantom_icons, fetter_icons = await asyncio.gather(
        asyncio.gather(*avatar_tasks),
        asyncio.gather(*phantom_tasks),
        asyncio.gather(*fetter_tasks),
    )

    card_img = await _compose_rows(
        card_img, bar, details, avatars, phantom_icons, fetter_icons, self_uid, calc_map, TITLE_H + text_bar_h
    )
    return await convert_img(card_img)


async def _build_local_self_row(
    self_uid: str,
    char_id,
    self_entry: PhantomTotalRankDetail,
) -> Optional[PhantomTotalRankDetail]:
    """未上榜时: 用本地最高分(满 5 副词条)声骸拼一条 999+ 自己行, 用户信息取服务端 self。"""
    from ..utils.calc import WuWaCalc

    find_char_id = SPECIAL_CHAR[char_id] if char_id in SPECIAL_CHAR else char_id
    role_detail = await find_role_detail(self_uid, find_char_id)
    if not role_detail or not role_detail.phantomData or not role_detail.phantomData.equipPhantomList:
        return None

    calc = WuWaCalc(role_detail)
    calc.phantom_pre = calc.prepare_phantom()
    calc.phantom_card = calc.enhance_summation_phantom_value(calc.phantom_pre)
    calc.calc_temp = get_calc_map(calc.phantom_card, role_detail.role.roleName, role_detail.role.roleId)

    best = None
    for ph in role_detail.phantomData.equipPhantomList:
        if not ph or not ph.phantomProp or len(ph.subProps or []) != 5:
            continue
        _score, _grade = calc_phantom_score(role_detail.role.roleId, ph.get_props(), ph.cost, calc.calc_temp)
        if best is None or _score > best[1]:
            best = (ph, _score, _grade)
    if best is None:
        return None
    ph, score, grade = best

    char_attr = role_detail.role.attributeName or ""
    props = ph.get_props()
    main_len = len(ph.mainProps or [])
    scored = []
    for pi, prop in enumerate(props):
        es = 0.0
        if calc.calc_temp:
            try:
                _, es = calc_phantom_entry(pi, prop, ph.cost, calc.calc_temp, char_attr)
            except Exception as e:
                logger.debug(f"[鸣潮·声骸总排行] 自己行单词条分失败: {e}")
        scored.append(PhantomRankProp(name=prop.attributeName, value=prop.attributeValue, score=es))

    return PhantomTotalRankDetail(
        rank=1001,  # → 999+
        user_id=self_entry.user_id,
        username="",
        alias_name=self_entry.alias_name,
        background=self_entry.background or "",
        kuro_name=self_entry.kuro_name,
        waves_id=self_entry.waves_id,
        char_id=int(char_id),
        char_name="",
        phantom_id=ph.phantomProp.phantomId,
        phantom_name=ph.phantomProp.name,
        icon_url=ph.phantomProp.iconUrl,
        cost=ph.cost,
        level=ph.level,
        set=ph.fetterDetail.name,
        main_props=scored[:main_len],
        sub_props=scored[main_len:main_len + 5],
        score=score,
        grade=grade,
        sender_avatar=self_entry.sender_avatar or "",
        hide_uid=self_entry.hide_uid,
    )


@to_thread
def _compose_rows(card_img, bar, details, avatars, phantom_icons, fetter_icons, self_uid, calc_map, top):
    for idx, temp in enumerate(zip(details, avatars, phantom_icons, fetter_icons)):
        detail, role_avatar, phantom_icon_img, fetter_icon_img = temp
        detail: PhantomTotalRankDetail
        y_pos = top + idx * ITEM_H

        bar_bg = bar.copy()
        draw = ImageDraw.Draw(bar_bg)
        draw_rank_and_avatar(bar_bg, detail.rank, role_avatar)

        # 库洛名 / 特征码 / bot主人徽章
        name_font, name_text = fit_text(
            draw,
            str(detail.kuro_name),
            _USER_NAME_MAX_WIDTH,
            (waves_font_22, waves_font_20, waves_font_18, waves_font_16, waves_font_14),
        )
        draw.text(
            (USER_INFO_X, _USER_NAME_Y),
            name_text,
            "white",
            name_font,
            "lm",
        )
        uid_color = RED if detail.waves_id == self_uid else "white"
        draw.text(
            (USER_INFO_X, _USER_UID_Y),
            f"特征码: {hide_uid(detail.waves_id, user_pref='on' if detail.hide_uid else '')}",
            uid_color,
            waves_font_18,
            "lm",
        )
        if getattr(detail, "alias_name", None):
            draw_bot_name_badge(
                bar_bg,
                getattr(detail, "background", ""),
                detail.alias_name,
                _BOT_BADGE_POS,
            )

        draw_phantom_thumb(bar_bg, phantom_icon_img, fetter_icon_img, detail.cost)
        draw_props_2col(bar_bg, draw, build_entries(detail.main_props, detail.sub_props, calc_map))
        draw_score_cell(bar_bg, draw, detail.grade, detail.score)

        card_img.paste(bar_bg, (0, y_pos), bar_bg)

    return add_footer(card_img)
