"深塔和海墟挑战信息绘制"

import asyncio
import re
import base64
from typing import Any, Dict, Union, Optional
from pathlib import Path
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw

from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.pool import to_thread
from gsuid_core.utils.image.convert import convert_img

from ..utils.util import clean_tags, load_json_file
from ..utils.image import (
    add_footer,
    clean_alpha_matte,
    get_waves_bg,
    get_square_avatar_path,
    draw_text_with_shadow,
    make_smooth_circle_mask,
    make_smooth_rounded_mask,
)
from ..utils.fonts.waves_fonts import (
    waves_font_14,
    waves_font_16,
    waves_font_18,
    waves_font_20,
    waves_font_24,
    waves_font_32,
)
from ..wutheringwaves_abyss.period import (
    get_slash_period_number,
    get_tower_period_number,
    get_matrix_period_number,
)
from ..utils.resource.RESOURCE_PATH import MAP_CHALLENGE_PATH
from ..utils.name_convert import char_name_to_char_id
from .tower_wiki_render import (
    get_monster_icon,
    draw_tower_wiki_render,
    draw_slash_wiki_render,
    draw_matrix_wiki_render,
    PLAYWRIGHT_AVAILABLE,
)

TEXT_PATH = Path(__file__).parent / "texture2d"

# 元素映射
ELEMENT_NAME_MAP = {
    0: "无属性",
    1: "冷凝",
    2: "热熔",
    3: "导电",
    4: "气动",
    5: "衍射",
    6: "湮灭",
}

# 元素颜色（RGB）
ELEMENT_COLOR = {
    0: (180, 180, 180),  # 无属性
    1: (53, 152, 219),  # 冷凝 (Glacio)
    2: (186, 55, 42),  # 热熔 (Fusion)
    3: (185, 106, 217),  # 导电 (Electro)
    4: (22, 145, 121),  # 气动 (Aero)
    5: (241, 196, 15),  # 衍射 (Spectro)
    6: (132, 63, 161),  # 湮灭 (Havoc)
}

MONSTER_CARD_H = 82
MONSTER_COLS = 4
MONSTER_ROW_GAP = 10
MONSTER_COL_GAP = 12


async def draw_tower_challenge_img(ev: Event, period: Optional[int] = None) -> Union[bytes, str]:
    """绘制深塔信息"""
    try:
        # 确定期数
        if period is None:
            text = ev.text.strip()
            match = re.search(r"(\d+)", text)
            period = int(match.group(1)) if match else get_tower_period_number()

        # 先检查数据是否存在
        json_path = MAP_CHALLENGE_PATH / "tower" / f"{period}.json"
        if not json_path.exists():
            return f"暂无深塔第{period}期的数据"

        if PLAYWRIGHT_AVAILABLE:
            try:
                res = await draw_tower_wiki_render(period)
                if res:
                    return res
            except Exception:
                logger.warning("[鸣潮·百科挑战] Failed to render tower wiki with playwright, fallback to PIL")

        # 加载数据
        tower_data = load_json_file(json_path)
        if not tower_data:
            return f"无法找到深塔第{period}期的数据"

        areas = tower_data.get("Area", {})
        if not areas:
            return f"深塔第{period}期数据格式错误"

        # 收集层级信息
        sections = []

        # 残响之塔第4层
        if "1" in areas and "Floor" in areas["1"]:
            floor_4_1 = areas["1"]["Floor"].get("4")
            if floor_4_1:
                sections.append(("残响之塔", floor_4_1))

        # 深境之塔 - 与 HTML 对齐，读 1..9 直到断层
        if "2" in areas and "Floor" in areas["2"]:
            for i in range(1, 10):
                floor_data = areas["2"]["Floor"].get(str(i))
                if floor_data:
                    sections.append((f"深境之塔 {i}层", floor_data))
                else:
                    break

        # 回音之塔第4层
        if "3" in areas and "Floor" in areas["3"]:
            floor_4_3 = areas["3"]["Floor"].get("4")
            if floor_4_3:
                sections.append(("回音之塔", floor_4_3))

        if not sections:
            return f"深塔第{period}期没有有效的层级数据"

        card_img = await _render_tower_pil(period, sections)
        card_img = await convert_img(card_img)
        return card_img

    except Exception as e:
        logger.error(f"[鸣潮·百科挑战] Error drawing tower challenge: {e}")
        return f"绘制深塔信息失败: {str(e)}"


@to_thread
def _render_tower_pil(period: int, sections):
    width = 900
    total_height = 150
    section_heights = []
    for area_name, floor_data in sections:
        h = _calculate_section_height(area_name, floor_data, width - 80)
        section_heights.append(h)
        total_height += h + 20

    total_height += 30

    card_img = get_waves_bg(width, total_height, "bg9")
    draw = ImageDraw.Draw(card_img)

    draw_text_with_shadow(draw, "深塔", width // 2, 50, waves_font_32, "white", anchor="mm")
    draw_text_with_shadow(draw, f"第{period}期", 50, 95, waves_font_20, (180, 180, 180), anchor="lm")

    current_y = 130
    for i, (area_name, floor_data) in enumerate(sections):
        section_h = section_heights[i]
        _draw_floor_section(card_img, (40, current_y), area_name, floor_data, width - 80, section_h)
        current_y += section_h + 20

    card_img = add_footer(card_img, color="white")
    return card_img


async def draw_slash_challenge_img(ev: Event, period: Optional[int] = None) -> Union[bytes, str]:
    """绘制海墟信息"""
    try:
        # 确定期数
        if period is None:
            text = ev.text.strip()
            match = re.search(r"(\d+)", text)
            period = int(match.group(1)) if match else get_slash_period_number()

        # 先检查数据是否存在
        json_path = MAP_CHALLENGE_PATH / "slash" / f"{period}.json"
        if not json_path.exists():
            return f"暂无海墟第{period}期的数据"

        if PLAYWRIGHT_AVAILABLE:
            try:
                res = await draw_slash_wiki_render(period)
                if res:
                    return res
            except Exception:
                logger.warning("[鸣潮·百科挑战] Failed to render slash wiki with playwright, fallback to PIL")

        # 加载数据
        slash_data = load_json_file(json_path)
        if not slash_data:
            return f"无法找到海墟第{period}期的数据"

        challenges = slash_data.get("Id", {})
        if not challenges:
            return f"海墟第{period}期数据为空"

        # 获取无尽湍渊(挑战12)的数据
        endless_data = None
        for challenge in challenges.values():
            if challenge.get("EndLess"):
                endless_data = challenge
                break

        # 兼容旧版本逻辑，如果没找到EndLess标记，尝试获取ID 12
        if not endless_data:
            endless_data = challenges.get("12")

        if not endless_data:
            return f"海墟第{period}期无无尽湍渊数据"

        # 加载额外的Buff数据 (可选)
        buff_json_path = MAP_CHALLENGE_PATH / "slash" / f"buff_{period}.json"
        buff_data = load_json_file(buff_json_path)

        card_img = await _render_slash_pil(period, endless_data, buff_data)
        card_img = await convert_img(card_img)
        return card_img

    except Exception as e:
        logger.error(f"[鸣潮·百科挑战] Error drawing slash challenge: {e}")
        return f"绘制海墟信息失败: {str(e)}"


@to_thread
def _render_slash_pil(period: int, endless_data: Dict[str, Any], buff_data):
    width = 900
    title = endless_data.get("Title", "无尽湍渊")
    desc = endless_data.get("Desc", "")
    desc = clean_tags(desc).rstrip("。.")

    floors = endless_data.get("Floor", {})
    floor_list = list(floors.values())

    header_height = 120

    desc_start_y = header_height + 10
    desc_lines = _wrap_matrix_text_px(desc, waves_font_18, width - 130) if desc else []

    desc_height = 30 + len(desc_lines) * 26 + 10

    buff_height = 0
    buff_layouts = []
    if buff_data:
        buff_height += 40
        for b_name, b_desc in buff_data.items():
            b_desc = clean_tags(b_desc).rstrip("。.")
            b_lines = _wrap_matrix_text_px(b_desc, waves_font_16, width - 170) or [""]
            buff_layouts.append((b_name, b_lines))
            buff_height += 30 + len(b_lines) * 24 + 16

    floor_heights = []
    for floor_data in floor_list:
        h = 40
        f_desc = clean_tags(floor_data.get("Desc", "")).rstrip("。.")
        if f_desc:
            f_desc_lines = _wrap_matrix_text_px(f_desc, waves_font_16, width - 150)
            h += len(f_desc_lines) * 24 + 12

        monsters = floor_data.get("Monsters", {})
        monster_count = len(monsters)
        monster_rows = (min(monster_count, 8) + MONSTER_COLS - 1) // MONSTER_COLS
        if monster_count > 0:
            h += 35 + monster_rows * MONSTER_CARD_H + max(0, monster_rows - 1) * MONSTER_ROW_GAP + 10

        floor_heights.append(h)

    monster_area_height = sum(floor_heights) + 20

    total_height = desc_start_y + desc_height + buff_height + monster_area_height + 30

    card_img = get_waves_bg(width, total_height, "bg9")
    draw = ImageDraw.Draw(card_img)

    draw_text_with_shadow(draw, f"海墟 第{period}期", width // 2, 50, waves_font_32, "white", anchor="mm")
    draw_text_with_shadow(draw, f"无尽 - {title}", width // 2, 90, waves_font_24, (255, 200, 100), anchor="mm")

    current_y = desc_start_y
    draw_text_with_shadow(draw, "【海域特性】", 50, current_y, waves_font_20, (255, 200, 100), anchor="lm")
    current_y += 30

    for line in desc_lines:
        draw.text((65, current_y), line, (230, 230, 230), waves_font_18, "lm")
        current_y += 26

    if buff_data:
        current_y += 10
        draw_text_with_shadow(draw, "【本期信物】", 50, current_y, waves_font_20, (255, 215, 0), anchor="lm")
        current_y += 35

        for b_name, lines in buff_layouts:
            draw.text((65, current_y), f"◆ {b_name}", (255, 200, 100), waves_font_18, "lm")
            current_y += 25

            for i, line in enumerate(lines):
                if i == 0:
                    draw.text((85, current_y), line, (220, 220, 220), waves_font_16, "lm")
                else:
                    draw.text((85, current_y), line, (220, 220, 220), waves_font_16, "lm")
                current_y += 24
            current_y += 10

    current_y += 10
    for i, floor_data in enumerate(floor_list):
        draw_text_with_shadow(draw, f"【半场 {i + 1}】", 50, current_y, waves_font_20, (100, 200, 255), anchor="lm")
        current_y += 30

        f_desc = clean_tags(floor_data.get("Desc", "")).rstrip("。.")
        if f_desc:
            lines = _wrap_matrix_text_px(f_desc, waves_font_16, width - 150)
            for i, line in enumerate(lines):
                if i == 0:
                    draw.text((65, current_y), f"· {line}", (200, 200, 200), waves_font_16, "lm")
                else:
                    draw.text((65 + 12, current_y), line, (200, 200, 200), waves_font_16, "lm")
                current_y += 24
            current_y += 10

        monsters = floor_data.get("Monsters", {})
        floor_level = floor_data.get("Level", 0)

        if monsters:
            draw_text_with_shadow(draw, "敌人配置", 65, current_y, waves_font_18, (255, 150, 150), anchor="lm")
            current_y += 35

            x_pos_start = 60
            x_pos = x_pos_start
            col = 0
            card_w = (width - 120 - MONSTER_COL_GAP * (MONSTER_COLS - 1)) // MONSTER_COLS
            card_h = MONSTER_CARD_H

            for monster_id, monster_info in list(monsters.items())[:8]:
                name = monster_info.get("Name", "未知")
                element_id = monster_info.get("Element", 0)
                element_name = ELEMENT_NAME_MAP.get(element_id, "无")
                color = ELEMENT_COLOR.get(element_id, (200, 200, 200))
                level = monster_info.get("Level", 0) or floor_level
                _draw_challenge_monster_card(
                    card_img,
                    (x_pos, current_y),
                    card_w,
                    card_h,
                    name,
                    monster_id,
                    element_name,
                    color,
                    level,
                )

                col += 1
                if col >= MONSTER_COLS:
                    col = 0
                    current_y += card_h + MONSTER_ROW_GAP
                    x_pos = x_pos_start
                else:
                    x_pos += card_w + MONSTER_COL_GAP

            if col > 0:
                current_y += card_h + MONSTER_ROW_GAP

        current_y += 30

    card_img = add_footer(card_img, color="white")
    return card_img


def _calculate_section_height(area_name: str, floor_data: Dict[str, Any], width: int) -> int:
    """预计算区域高度"""
    buffs = floor_data.get("Buffs", {})
    monsters = floor_data.get("Monsters", {})

    buff_lines = 0

    for buff_info in list(buffs.values()):
        buff_desc = clean_tags(buff_info.get("Desc", "")).rstrip("。.")
        buff_lines += len(_wrap_matrix_text_px(buff_desc, waves_font_16, width - 90))

    monster_rows = (min(len(monsters), 8) + MONSTER_COLS - 1) // MONSTER_COLS


    section_height = 80 + buff_lines * 25
    if buffs:
        section_height += 30
    if monsters:
        section_height += 45 + monster_rows * MONSTER_CARD_H + max(0, monster_rows - 1) * MONSTER_ROW_GAP + 10

    if section_height < 180:
        section_height = 180
    return section_height


def _draw_floor_section(
    img: Image.Image, pos: tuple, area_name: str, floor_data: Dict[str, Any], width: int, section_height: int
) -> None:
    """在图片上绘制一个层级的信息"""
    x, y = pos
    draw = ImageDraw.Draw(img)

    # 背景框
    draw.rounded_rectangle(
        (x, y, x + width, y + section_height), radius=10, fill=(30, 30, 30, 180), outline=(100, 100, 100), width=1
    )

    # 区域名称和消耗
    cost = floor_data.get("Cost", 0)
    title = f"{area_name}"
    cost_text = f"消耗疲劳: {cost}"

    draw_text_with_shadow(draw, title, x + 20, y + 25, waves_font_24, (255, 215, 0), anchor="lm")
    draw.text((x + width - 150, y + 25), cost_text, (200, 200, 200), waves_font_18, "lm")

    # 分割线
    draw.line((x + 20, y + 50, x + width - 20, y + 50), fill=(100, 100, 100), width=1)

    current_y = y + 75

    buffs = floor_data.get("Buffs", {})
    monsters = floor_data.get("Monsters", {})

    # Buff信息
    if buffs:
        draw.text((x + 20, current_y), "【环境Buff】", (100, 200, 255), waves_font_18, "lm")
        current_y += 25

        for buff_info in list(buffs.values()):
            buff_desc = clean_tags(buff_info.get("Desc", "")).rstrip("。.")

            # 分行显示
            lines = _wrap_matrix_text_px(buff_desc, waves_font_16, width - 90)
            for i, line in enumerate(lines):
                if i == 0:
                    draw.text((x + 30, current_y), f"· {line}", (220, 220, 220), waves_font_16, "lm")
                else:
                    draw.text((x + 30 + 12, current_y), line, (220, 220, 220), waves_font_16, "lm")
                current_y += 22
            current_y += 5

    # 怪物信息
    if monsters:
        current_y += 10
        draw.text((x + 20, current_y), "【敌人列表】", (255, 100, 100), waves_font_18, "lm")
        current_y += 40

        col = 0
        x_start = x + 30
        curr_x = x_start

        card_w = (width - 60 - MONSTER_COL_GAP * (MONSTER_COLS - 1)) // MONSTER_COLS
        card_h = MONSTER_CARD_H

        for monster_id, monster_info in list(monsters.items())[:8]:
            name = monster_info.get("Name", "未知")
            element_id = monster_info.get("Element", 0)
            element_name = ELEMENT_NAME_MAP.get(element_id, "未知")
            color = ELEMENT_COLOR.get(element_id, (200, 200, 200))
            level = monster_info.get("Level", 0)

            _draw_challenge_monster_card(
                img,
                (curr_x, current_y),
                card_w,
                card_h,
                name,
                monster_id,
                element_name,
                color,
                level,
            )

            col += 1
            if col >= MONSTER_COLS:
                col = 0
                current_y += card_h + MONSTER_ROW_GAP
                curr_x = x_start
            else:
                curr_x += card_w + MONSTER_COL_GAP


def _clean_matrix_text(text: str) -> str:
    text = str(text or "")
    text = text.replace("<br/>", "\n").replace("<br />", "\n").replace("<br>", "\n")
    text = clean_tags(text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("&nbsp;", " ").strip()


def _wrap_matrix_text(text: str, max_chars: int) -> list[str]:
    lines = []
    for part in _clean_matrix_text(text).split("\n"):
        part = part.strip()
        if not part:
            continue
        while part:
            lines.append(part[:max_chars])
            part = part[max_chars:]
    return lines


def _text_width(text: str, font) -> int:
    return int(font.getlength(text)) if hasattr(font, "getlength") else int(font.getsize(text)[0])


def _wrap_matrix_text_px(text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    for part in _clean_matrix_text(text).split("\n"):
        part = part.strip()
        if not part:
            continue

        line = ""
        for char in part:
            test = line + char
            if _text_width(test, font) <= max_width:
                line = test
                continue

            if line:
                lines.append(line)
                line = char
            else:
                lines.append(char)
                line = ""

        if line:
            lines.append(line)

    return lines


def _draw_round_icon(base: Image.Image, icon: Optional[Image.Image], box: tuple[int, int, int, int], color) -> None:
    draw = ImageDraw.Draw(base, "RGBA")
    draw.ellipse(box, fill=(42, 46, 53, 220), outline=(*color, 210), width=2)
    if icon is None:
        return
    size = box[2] - box[0]
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    icon = clean_alpha_matte(icon, (42, 46, 53, 255))
    layer.alpha_composite(icon.resize((size, size), Image.LANCZOS), (0, 0))
    mask = make_smooth_circle_mask(size)
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
    base.alpha_composite(layer, (box[0], box[1]))


def _draw_challenge_monster_card(
    base: Image.Image,
    pos: tuple[int, int],
    width: int,
    height: int,
    name: str,
    monster_id: Union[str, int],
    element_name: str,
    color,
    level: int = 0,
) -> None:
    x, y = pos
    draw = ImageDraw.Draw(base, "RGBA")
    draw.rounded_rectangle(
        (x, y, x + width, y + height),
        radius=12,
        fill=(0, 0, 0, 115),
        outline=(*color, 180),
        width=1,
    )

    icon_size = 48
    icon = _decode_data_url(get_monster_icon(name, monster_id), icon_size)
    _draw_round_icon(base, icon, (x + 8, y + 8, x + 8 + icon_size, y + 8 + icon_size), color)

    text_x = x + 64
    text_w = max(40, width - 72)
    name_lines = _wrap_matrix_text_px(name, waves_font_18, text_w)
    name_max_lines = 1 if level else 2
    for idx, line in enumerate(name_lines[:name_max_lines]):
        draw.text((text_x, y + 18 + idx * 20), line, "white", waves_font_18, "lm")

    if level:
        draw.text((text_x, y + 42), f"Lv.{level}", (210, 210, 210), waves_font_14, "lm")

    meta_y = y + height - 18
    tag_text = f"{element_name}抗性" if element_name not in ("无", "无属性", "未知") else element_name
    elem_w = min(_text_width(tag_text, waves_font_14) + 14, max(34, width - 72))
    elem_x = text_x
    _draw_matrix_tag(draw, (elem_x, meta_y - 11, elem_x + elem_w, meta_y + 11), tag_text, color)


def _parse_matrix_tag_color(raw_color: str) -> tuple[int, int, int]:
    color = str(raw_color or "").strip().lstrip("#")
    if len(color) >= 6:
        try:
            return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore
        except ValueError:
            pass
    return (230, 205, 140)


def _contrast_text_color(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    luminance = rgb[0] * 0.299 + rgb[1] * 0.587 + rgb[2] * 0.114
    return (24, 24, 28) if luminance > 165 else (255, 255, 255)


def _draw_matrix_tag(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    color: tuple[int, int, int],
) -> None:
    text_color = _contrast_text_color(color)
    shadow_color = (255, 255, 255, 105) if text_color[0] < 100 else (0, 0, 0, 145)
    draw.rounded_rectangle(
        box,
        radius=11,
        fill=(*color, 185),
        outline=(*color, 235),
        width=1,
    )
    tx, ty = box[0] + 9, (box[1] + box[3]) // 2
    draw.text((tx + 1, ty + 1), text, shadow_color, waves_font_14, "lm")
    draw.text((tx, ty), text, text_color, waves_font_14, "lm")


def _decode_data_url(data_url: Optional[str], size: int) -> Optional[Image.Image]:
    if not data_url:
        return None
    try:
        if "," in data_url:
            data_url = data_url.split(",", 1)[1]
        img = Image.open(BytesIO(base64.b64decode(data_url))).convert("RGBA")
        img = clean_alpha_matte(img, (42, 46, 53, 255))
        return img.resize((size, size), Image.LANCZOS)
    except Exception:
        return None


def _load_role_icon(role_id: Optional[int], role_name: str, size: int) -> Optional[Image.Image]:
    try:
        char_id = role_id or char_name_to_char_id(role_name)
        if not char_id:
            return None
        return Image.open(get_square_avatar_path(char_id)).convert("RGBA").resize((size, size), Image.LANCZOS)
    except Exception:
        return None


def _paste_matrix_icon(
    base: Image.Image,
    icon: Optional[Image.Image],
    xy: tuple[int, int],
    size: int,
    radius: int = 8,
) -> None:
    if icon is None:
        return
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    icon = clean_alpha_matte(icon, (42, 46, 53, 255))
    layer.alpha_composite(icon.resize((size, size), Image.LANCZOS), (0, 0))
    mask = make_smooth_rounded_mask((size, size), radius)
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
    base.alpha_composite(layer, xy)


def _draw_matrix_info_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    title_color=(255, 200, 100),
) -> None:
    draw.rounded_rectangle(
        box,
        radius=10,
        fill=(18, 22, 28, 190),
        outline=(255, 255, 255, 28),
        width=1,
    )
    draw.text((box[0] + 20, box[1] + 30), title, title_color, waves_font_20, "lm")
    draw.line((box[0] + 20, box[1] + 54, box[2] - 20, box[1] + 54), fill=(212, 177, 99, 90), width=1)


def _prepare_matrix_info(matrix_data: Dict[str, Any]) -> tuple[str, list[Dict], list[Dict], list[Dict]]:
    levels = matrix_data.get("Levels", [])
    if not levels:
        return "", [], [], []

    target_level = next((level for level in levels if level.get("Name") == "奇点扩张"), None) or levels[-1]
    level_name = target_level.get("Name", "奇点扩张")

    buffs = []
    for buff in target_level.get("NewTowerBuffs", []):
        desc_lines = _wrap_matrix_text(buff.get("Desc", ""), 40)
        buffs.append({
            "name": buff.get("Name", "增益"),
            "desc_lines": desc_lines,
        })

    bosses = []
    seen_names = set()
    for wave in target_level.get("Waves", []):
        name = wave.get("Name", "未知")
        if name in seen_names:
            continue
        seen_names.add(name)

        tags = []
        for tag in wave.get("Tags", []):
            tag_name = tag.get("Name", "")
            if not tag_name:
                continue
            tags.append({
                "name": tag_name,
                "color": _parse_matrix_tag_color(tag.get("Color", "")),
            })
        desc_lines = []
        for part in re.split(r"<br\s*/?>", wave.get("Desc", "")):
            cleaned = _clean_matrix_text(part)
            if not cleaned or cleaned == name:
                continue
            desc_lines.extend(_wrap_matrix_text(cleaned, 36))

        bosses.append({
            "name": name,
            "tags": tags,
            "desc_lines": desc_lines[:4],
            "icon": _decode_data_url(get_monster_icon(name, wave.get("MonsterId", 0)), 62),
        })

    roles = []
    for role_data in matrix_data.get("Roles", []):
        role_info = role_data.get("RoleInfo", {})
        name = role_info.get("Name", "未知")
        enhance_descs = role_data.get("EnhanceSkillDesc", [])
        desc = enhance_descs[0].get("Value", "") if enhance_descs else ""
        roles.append({
            "id": role_data.get("Id"),
            "name": name,
            "desc": desc,
            "icon": _load_role_icon(role_data.get("Id"), name, 58),
        })

    return level_name, buffs, bosses, roles


async def _draw_matrix_challenge_pil(season: int, matrix_data: Dict[str, Any]) -> Union[bytes, str]:
    level_name, buffs, bosses, roles = _prepare_matrix_info(matrix_data)
    if not level_name:
        return f"矩阵第{season}期数据为空"
    card_img = await _render_matrix_pil(season, level_name, buffs, bosses, roles)
    return await convert_img(card_img)


@to_thread
def _render_matrix_pil(season, level_name, buffs, bosses, roles):

    width = 900
    buff_item_heights = [
        62 + max(1, len(item["desc_lines"])) * 24
        for item in buffs
    ]
    buff_h = 70 + sum(item_h + 10 for item_h in buff_item_heights) + 16
    if not buffs:
        buff_h = 150
    boss_h = 76 + sum(92 + max(1, len(item["desc_lines"])) * 21 for item in bosses)
    role_gap = 20
    col_w = (width - 120 - role_gap) // 2
    text_max_w = col_w - 102
    role_layouts = []
    for role in roles:
        name_lines = _wrap_matrix_text_px(role["name"], waves_font_18, text_max_w) or [role["name"]]
        desc_lines = _wrap_matrix_text_px(role.get("desc", ""), waves_font_14, text_max_w) or ["暂无增益描述"]
        item_h = max(96, 24 + len(name_lines) * 22 + 6 + len(desc_lines) * 18 + 16)
        role_layouts.append({**role, "name_lines": name_lines, "desc_lines": desc_lines, "height": item_h})

    role_rows = (len(role_layouts) + 1) // 2
    role_row_gap = 14
    row_heights = []
    for row in range(role_rows):
        left = role_layouts[row * 2]["height"]
        right = role_layouts[row * 2 + 1]["height"] if row * 2 + 1 < len(role_layouts) else left
        row_heights.append(max(left, right))
    role_h = 96 + sum(row_heights) + max(0, role_rows - 1) * role_row_gap
    total_height = 145 + buff_h + boss_h + role_h + 85

    card_img = get_waves_bg(width, total_height, "bg9")
    draw = ImageDraw.Draw(card_img, "RGBA")

    draw_text_with_shadow(draw, f"矩阵叠兵 第{season}期", width // 2, 50, waves_font_32, "white", anchor="mm")
    draw_text_with_shadow(draw, level_name, width // 2, 92, waves_font_24, (255, 200, 100), anchor="mm")

    current_y = 125
    _draw_matrix_info_panel(draw, (40, current_y, width - 40, current_y + buff_h), "全局增益")
    y = current_y + 70
    if not buffs:
        draw.text((65, y + 28), "暂无增益数据", (220, 220, 220), waves_font_16, "lm")
    for idx, buff in enumerate(buffs):
        item_h = buff_item_heights[idx]
        draw.rounded_rectangle(
            (60, y, width - 60, y + item_h),
            radius=8,
            fill=(0, 0, 0, 80),
            outline=(255, 255, 255, 22),
            width=1,
        )
        draw.text((78, y + 24), f"◆ {buff['name']}", (255, 200, 100), waves_font_18, "lm")
        desc_y = y + 52
        for line in buff["desc_lines"] or ["暂无描述"]:
            draw.text((98, desc_y), line, (220, 220, 220), waves_font_16, "lm")
            desc_y += 24
        y += item_h + 10

    current_y += buff_h + 20
    _draw_matrix_info_panel(draw, (40, current_y, width - 40, current_y + boss_h), "Boss 信息", (255, 150, 150))
    y = current_y + 74
    for boss in bosses:
        card_top = y - 18
        card_h = 78 + max(1, len(boss["desc_lines"])) * 21
        draw.rounded_rectangle(
            (60, card_top, width - 60, card_top + card_h),
            radius=8,
            fill=(0, 0, 0, 95),
            outline=(255, 255, 255, 24),
            width=1,
        )
        draw.rounded_rectangle((75, card_top + 12, 137, card_top + 74), radius=8, fill=(42, 46, 53, 210))
        _paste_matrix_icon(card_img, boss["icon"], (75, card_top + 12), 62)
        draw.text((155, y), boss["name"], "white", waves_font_20, "lm")
        if boss["tags"]:
            tag_x = 155
            for tag in boss["tags"][:3]:
                tag_name = tag["name"]
                tag_w = _text_width(tag_name, waves_font_14) + 18
                if tag_x + tag_w > width - 75:
                    break
                _draw_matrix_tag(
                    draw,
                    (tag_x, y + 18, tag_x + tag_w, y + 40),
                    tag_name,
                    tag["color"],
                )
                tag_x += tag_w + 8
        desc_y = y + 50
        for line in boss["desc_lines"] or ["暂无机制描述"]:
            draw.text((155, desc_y), line, (210, 210, 210), waves_font_16, "lm")
            desc_y += 21
        y = card_top + card_h + 16

    current_y += boss_h + 20
    _draw_matrix_info_panel(draw, (40, current_y, width - 40, current_y + role_h), "推荐角色增益", (100, 200, 255))
    y = current_y + 74
    row_tops = []
    row_y = 0
    for height in row_heights:
        row_tops.append(row_y)
        row_y += height + role_row_gap
    for idx, role in enumerate(role_layouts):
        col = idx % 2
        row = idx // 2
        x = 60 + col * (col_w + role_gap)
        item_y = y + row_tops[row]
        draw.rounded_rectangle(
            (x, item_y, x + col_w, item_y + role["height"]),
            radius=8,
            fill=(0, 0, 0, 100),
            outline=(255, 255, 255, 22),
            width=1,
        )
        draw.rounded_rectangle((x + 14, item_y + 15, x + 72, item_y + 73), radius=8, fill=(42, 46, 53, 210))
        _paste_matrix_icon(card_img, role["icon"], (x + 14, item_y + 15), 58)
        text_y = item_y + 24
        for line in role["name_lines"]:
            draw.text((x + 88, text_y), line, "white", waves_font_18, "lm")
            text_y += 22
        desc_y = text_y + 6
        for line in role["desc_lines"]:
            draw.text((x + 88, desc_y), line, (210, 210, 210), waves_font_14, "lm")
            desc_y += 18

    card_img = add_footer(card_img, color="white")
    return card_img


async def draw_matrix_challenge_img(ev: Event, season: Optional[int] = None) -> Union[bytes, str]:
    """绘制矩阵信息"""
    try:
        if season is None:
            text = ev.text.strip()
            match = re.search(r"(\d+)", text)
            season = int(match.group(1)) if match else get_matrix_period_number()

        # 先检查数据是否存在
        json_path = MAP_CHALLENGE_PATH / "matrix" / f"{season}.json"
        if not json_path.exists():
            return f"暂无矩阵第{season}期的数据"

        if PLAYWRIGHT_AVAILABLE:
            try:
                res = await draw_matrix_wiki_render(season)
                if res:
                    return res
            except Exception:
                logger.warning("[鸣潮·百科挑战] Failed to render matrix wiki with playwright, fallback to PIL")

        matrix_data = load_json_file(json_path)
        if not matrix_data:
            return f"无法找到矩阵第{season}期的数据"

        return await _draw_matrix_challenge_pil(season, matrix_data)

    except Exception as e:
        logger.error(f"[鸣潮·百科挑战] Error drawing matrix challenge: {e}")
        return f"绘制矩阵信息失败: {str(e)}"
