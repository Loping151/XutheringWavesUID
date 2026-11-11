from ..wutheringwaves_config import PREFIX
from typing import List, Tuple
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from gsuid_core.models import Event
from gsuid_core.pool import to_thread
from gsuid_core.utils.image.utils import sget
from gsuid_core.utils.image.convert import convert_img

from ..utils import hint
from ..utils.util import get_hide_uid_pref, hide_uid
from ..utils.image import GREY, YELLOW, add_footer, get_waves_bg
from ..utils.api.model import (
    AreaInfo,
    ExploreArea,
    ExploreItem,
    ExploreList,
    AccountBaseInfo,
)
from ..utils.imagetool import draw_pic_with_ring, draw_base_info_bg
from ..utils.waves_api import waves_api
from ..utils.error_reply import WAVES_CODE_102
from ..utils.fonts.waves_fonts import (
    waves_font_24,
    waves_font_26,
    waves_font_30,
    waves_font_36,
    waves_font_42,
    waves_font_50,
)

TEXT_PATH = Path(__file__).parent / "texture2d"

WIDTH = 1500
PAD = 70
COLS = 3
COL_GAP = 50
COL_W = (WIDTH - PAD * 2 - COL_GAP * (COLS - 1)) // COLS
BASE_INFO_H = 250
COUNTRY_HEAD_H = 150
DONE_LINE_H = 44
AREA_HEAD_H = 66
ITEM_H = 50
AREA_GAP = 36
COUNTRY_GAP = 50

BODY = (205, 209, 217)
ZERO = (135, 142, 155)
NEAR = (255, 217, 138)
RULE = (58, 62, 72)

TodoArea = Tuple[AreaInfo, List[ExploreItem]]


def split_explore_areas(explore: ExploreArea) -> Tuple[List[str], List[TodoArea]]:
    """(已完成区域名, [(区域, 未完成项按进度从高到低)])"""
    done: List[str] = []
    todo: List[TodoArea] = []
    for area in explore.areaInfoList or []:
        items = sorted((item for item in area.itemList if item.progress < 100), key=lambda item: -item.progress)
        if items:
            todo.append((area, items))
        else:
            done.append(area.areaName)
    return done, todo


def _country_color(explore: ExploreArea) -> Tuple[int, int, int]:
    color = explore.country.detailPageProgressColor.lstrip("#")
    try:
        return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore
    except ValueError:
        return YELLOW[:3]


def _soft(color: Tuple[int, int, int]) -> Tuple[int, int, int]:
    return tuple(int(c + (255 - c) * 0.22) for c in color)  # type: ignore


def _tone(progress, color: Tuple[int, int, int]) -> Tuple[Tuple[int, int, int], Tuple[int, ...]]:
    """(百分比文字色, 进度线色): 0 灰 / <50 淡 / <90 实 / 其余金"""
    progress = float(progress)
    if progress <= 0:
        return ZERO, color
    if progress < 50:
        return BODY, tuple(int(c * 0.45 + 16) for c in color)
    if progress < 90:
        return (255, 255, 255), color
    return NEAR, NEAR


def _wrap_done(draw: ImageDraw.ImageDraw, names: List[str]) -> List[List[str]]:
    lines: List[List[str]] = [[]]
    x = 130
    for name in names:
        w = draw.textlength(name, waves_font_26) + 40
        if lines[-1] and x + w > WIDTH - PAD * 2:
            lines.append([])
            x = 130
        lines[-1].append(name)
        x += w
    return lines


def _layout_columns(todo: List[TodoArea]) -> Tuple[List[Tuple[int, int, TodoArea]], int]:
    """瀑布流: 每块放进当前最矮的列。返回 ([(列, y, 区域)], 总高)"""
    heights = [0] * COLS
    placed = []
    for area in todo:
        col = heights.index(min(heights))
        placed.append((col, heights[col], area))
        heights[col] += AREA_HEAD_H + ITEM_H * len(area[1]) + AREA_GAP
    return placed, max(heights)


def _progress_line(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, progress, color, thick: int):
    draw.rectangle((x, y, x + w, y + 1), fill=RULE)
    filled = int(w * min(float(progress), 100) / 100)
    if filled > 0:
        draw.rectangle((x, y - thick + 2, x + filled, y + 1), fill=color)


async def draw_explore_img(ev: Event, uid: str, user_id: str):
    is_self_ck, ck = await waves_api.get_ck_result(uid, user_id, ev.bot_id)
    if not ck:
        return hint.error_reply(WAVES_CODE_102)
    user_pref = await get_hide_uid_pref(uid, user_id, ev.bot_id)
    # 账户数据
    account_info = await waves_api.get_base_info(uid, ck)
    if not account_info.success:
        return account_info.throw_msg()
    if not account_info.data:
        return f"用户未展示数据, 请尝试【{PREFIX}登录】"
    account_info = AccountBaseInfo.model_validate(account_info.data)

    explore_data = await waves_api.get_explore_data(uid, ck)
    if not explore_data.success:
        return explore_data.throw_msg()
    explore_data = ExploreList.model_validate(explore_data.data)
    if not is_self_ck and not explore_data.open:
        return hint.error_reply(msg="探索数据未开启")

    if not explore_data.exploreList:
        return hint.error_reply(msg="探索数据为空")

    # 头像部分
    avatar, avatar_ring = await draw_pic_with_ring(ev)

    # 预取每个大区图标
    country_icons = []
    for _explore in explore_data.exploreList[::-1]:
        try:
            country_icons.append(
                Image.open(BytesIO((await sget(_explore.country.homePageIcon)).content)).convert("RGBA")
            )
        except Exception:
            country_icons.append(None)

    img = await _compose_explore_img(account_info, explore_data, avatar, avatar_ring, country_icons, user_pref)
    img = await convert_img(img)
    return img


@to_thread
def _compose_explore_img(account_info, explore_data, avatar, avatar_ring, country_icons, user_pref) -> Image.Image:
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    blocks = []
    h = BASE_INFO_H
    for explore in explore_data.exploreList[::-1]:
        done, todo = split_explore_areas(explore)
        done_lines = _wrap_done(measure, done) if done else []
        placed, todo_h = _layout_columns(todo)
        blocks.append((explore, done_lines, placed))
        h += COUNTRY_HEAD_H + len(done_lines) * DONE_LINE_H + (20 if done_lines else 0) + todo_h + COUNTRY_GAP
    h += 60

    img = get_waves_bg(WIDTH, h, "bg3")
    img.paste(avatar, (85, 70), avatar)
    img.paste(avatar_ring, (95, 80), avatar_ring)

    base_info_bg = draw_base_info_bg(
        f"{account_info.name[:10]}",
        f"特征码:  {hide_uid(account_info.id, user_pref=user_pref)}",
        TEXT_PATH,
    )
    img.paste(base_info_bg, (75, 20), base_info_bg)

    if account_info.is_full:
        title_bar = Image.open(TEXT_PATH / "title_bar.png")
        title_bar_draw = ImageDraw.Draw(title_bar)
        title_bar_draw.text((660, 125), "账号等级", GREY, waves_font_26, "mm")
        title_bar_draw.text((660, 78), f"Lv.{account_info.level}", "white", waves_font_42, "mm")

        title_bar_draw.text((810, 125), "世界等级", GREY, waves_font_26, "mm")
        title_bar_draw.text((810, 78), f"Lv.{account_info.worldLevel}", "white", waves_font_42, "mm")
        img.paste(title_bar, (40, 70), title_bar)

    draw = ImageDraw.Draw(img)
    y = BASE_INFO_H
    for mi, (explore, done_lines, placed) in enumerate(blocks):
        color = _country_color(explore)
        soft = _soft(color)

        bar = (PAD - 20, y, WIDTH - PAD + 20, y + 120)
        draw.rectangle(bar, fill=tuple(int(c * 0.42 + 8) for c in color))
        _progress_line(draw, bar[0], bar[3] - 2, bar[2] - bar[0], explore.countryProgress, soft, 6)

        icon = country_icons[mi] if mi < len(country_icons) else None
        name_x = PAD
        if icon is not None:
            icon = icon.resize((100, 100), Image.LANCZOS)
            img.alpha_composite(icon, (PAD - 8, y + 8))
            name_x = PAD + 110
        draw.text((name_x, y + 58), explore.country.countryName, "white", waves_font_42, "lm")
        draw.text((WIDTH - PAD, y + 58), f"{explore.countryProgress}%", "white", waves_font_50, "rm")
        y += COUNTRY_HEAD_H

        if done_lines:
            draw.text((PAD, y + 22), "已完成", soft, waves_font_24, "lm")
            for line in done_lines:
                x = PAD + 130
                for name in line:
                    draw.text((x, y + 22), name, BODY, waves_font_26, "lm")
                    x += int(draw.textlength(name, waves_font_26)) + 40
                y += DONE_LINE_H
            y += 20

        todo_h = 0
        for col, top, (area, items) in placed:
            x = PAD + col * (COL_W + COL_GAP)
            ay = y + top
            draw.text((x, ay + 30), area.areaName, "white", waves_font_36, "lm")
            text_color, line_color = _tone(area.areaProgress, color)
            draw.text((x + COL_W, ay + 30), f"{area.areaProgress}%", text_color, waves_font_30, "rm")
            _progress_line(draw, x, ay + 58, COL_W, area.areaProgress, line_color, 4)
            iy = ay + AREA_HEAD_H
            for item in items:
                text_color, line_color = _tone(item.progress, color)
                draw.text((x, iy + 22), item.name, ZERO if item.progress <= 0 else BODY, waves_font_26, "lm")
                draw.text((x + COL_W, iy + 22), f"{item.progress}%", text_color, waves_font_26, "rm")
                _progress_line(draw, x, iy + ITEM_H - 6, COL_W, item.progress, line_color, 3)
                iy += ITEM_H
            todo_h = max(todo_h, top + AREA_HEAD_H + ITEM_H * len(items) + AREA_GAP)
        y += todo_h + COUNTRY_GAP

    img = add_footer(img)
    return img
