"深塔和海墟挑战信息绘制"

import re
import base64
from typing import Any, Dict, Union, Optional
from pathlib import Path
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageOps

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
)
from ..utils.fonts.waves_fonts import (
    fit_text,
    waves_font_10,
    waves_font_12,
    waves_font_14,
    waves_font_15,
    waves_font_16,
    waves_font_18,
    waves_font_20,
    waves_font_22,
    waves_font_24,
    waves_font_26,
    waves_font_28,
    waves_font_30,
    waves_font_32,
    waves_font_60,
    waves_font_origin,
)
from ..wutheringwaves_abyss.period import (
    get_slash_period_number,
    get_tower_period_number,
    get_matrix_period_number,
)
from ..utils.resource.RESOURCE_PATH import MAP_CHALLENGE_PATH, SLASH_BUFF_PATH
from ..utils.name_convert import char_name_to_char_id
from .tower_wiki_render import (
    get_monster_icon,
    get_monster_elements,
    get_matrix_bosses,
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

WIDTH = 1000
PAD = 44
INNER = WIDTH - PAD * 2
COL_GAP = 48
HALF = (INNER - COL_GAP) // 2

INK = (9, 11, 16)
BODY = (205, 209, 217)
SUB = (143, 150, 163)
RULE = (48, 52, 62)
DASH = (38, 41, 50)
GOLD = (255, 217, 138)
THEME = {"tower": (78, 124, 255), "slash": (255, 202, 40), "matrix": (255, 107, 107)}

waves_font_96 = waves_font_origin(96)
NAME_FONTS = (waves_font_18, waves_font_16, waves_font_15, waves_font_14, waves_font_12, waves_font_10)
BOSS_FONTS = (waves_font_24, waves_font_20, waves_font_18, waves_font_16, waves_font_14)



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

        card_img = await _render_tower_pil(period, _duration(tower_data), sections)
        card_img = await convert_img(card_img)
        return card_img

    except Exception as e:
        logger.error(f"[鸣潮·百科挑战] Error drawing tower challenge: {e}")
        return f"绘制深塔信息失败: {str(e)}"


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

        card_img = await _render_slash_pil(period, _duration(slash_data), endless_data, buff_data)
        card_img = await convert_img(card_img)
        return card_img

    except Exception as e:
        logger.error(f"[鸣潮·百科挑战] Error drawing slash challenge: {e}")
        return f"绘制海墟信息失败: {str(e)}"


def _clean_matrix_text(text: str) -> str:
    text = str(text or "")
    text = text.replace("<br/>", "\n").replace("<br />", "\n").replace("<br>", "\n")
    text = clean_tags(text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("&nbsp;", " ").strip()


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
            if _text_width(test, font) <= max_width or (line and char in "%，。；、：）」"):
                line = test
                continue

            if line:
                cut = len(line)
                while char.isdigit() and cut and line[cut - 1].isdigit():
                    cut -= 1
                cut = cut or len(line)
                lines.append(line[:cut])
                line = line[cut:] + char
            else:
                lines.append(char)
                line = ""

        if line:
            lines.append(line)

    return lines


def _parse_matrix_tag_color(raw_color: str) -> tuple[int, int, int]:
    color = str(raw_color or "").strip().lstrip("#")
    if len(color) >= 6:
        try:
            return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore
        except ValueError:
            pass
    return (230, 205, 140)


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


def _mix(color, other, ratio: float) -> tuple:
    return tuple(int(c + (o - c) * ratio) for c, o in zip(color[:3], other))


def _edge_mask(size: tuple[int, int]) -> Image.Image:
    """中间实、四周渐隐"""
    mask = Image.radial_gradient("L").point(lambda v: max(0, min(255, int((176 - v) * 3.2))))
    return mask.resize(size, Image.LANCZOS)


def _duration(data: Dict[str, Any]) -> str:
    begin, end = data.get("Begin", ""), data.get("End", "")
    if not begin or not end:
        return ""
    return f"{begin[5:] if len(begin) >= 10 else begin} ~ {end[5:] if len(end) >= 10 else end}"


class _Poster:
    """先画在足够高的画布上, finish 时按实际高度裁切"""

    def __init__(self, kind: str):
        self.accent = THEME[kind]
        self.soft = _mix(self.accent, (255, 255, 255), 0.45)
        self.img = Image.new("RGBA", (WIDTH, 7000), (*INK, 255))
        top = get_waves_bg(WIDTH, 420, "bg9").convert("RGBA")
        top.putalpha(Image.linear_gradient("L").resize((WIDTH, 420)).point(lambda v: int((255 - v) * 0.5)))
        self.img.alpha_composite(top)
        haze = Image.new("RGBA", (900, 480), (*self.accent, 0))
        haze.putalpha(_edge_mask((900, 480)).point(lambda v: int(v * 0.42)))
        self.img.alpha_composite(haze, (330, -200))
        self.draw = ImageDraw.Draw(self.img)
        self.y = 0

    def finish(self) -> Image.Image:
        return add_footer(self.img.crop((0, 0, WIDTH, self.y + 70)), color="white")

    def hero(self, title: str, tag: str, sub: str, arts: list) -> None:
        x = WIDTH + 36
        for i, art in enumerate([a for a in arts if a][:3]):
            size = (336, 302, 268)[i]
            art = art.resize((size, size), Image.LANCZOS)
            duo = ImageOps.colorize(art.convert("L"), _mix(self.accent, (0, 0, 0), 0.8), self.soft).convert("RGBA")
            alpha = ImageChops.multiply(art.getchannel("A"), _edge_mask((size, size)))
            duo.putalpha(alpha.point(lambda v, k=(0.92, 0.62, 0.36)[i]: int(v * k)))
            x -= size if i == 0 else 208
            self.img.alpha_composite(duo, (x, 330 - size))
        fade = Image.new("RGBA", (WIDTH, 150), (*INK, 0))
        fade.putalpha(Image.linear_gradient("L").resize((WIDTH, 150)).point(lambda v: int(v * 0.96)))
        self.img.alpha_composite(fade, (0, 168))
        self.draw.text((PAD, 226), title, "white", waves_font_96, "ls")
        tag_w = _text_width(tag, waves_font_32)
        self.draw.text((PAD, 280), tag, self.soft, waves_font_32, "ls")
        self.draw.text((PAD + tag_w + 22, 280), sub, (223, 226, 232), waves_font_28, "ls")
        self.y = 340

    def head(self, x: int, w: int, title: str, note: str = "", value: str = "") -> None:
        self.draw.text((x, self.y + 34), title, "white", waves_font_32, "ls")
        right = x + w
        if value:
            self.draw.text((right, self.y + 34), value, self.soft, waves_font_26, "rs")
            right -= _text_width(value, waves_font_26) + 8
        if note:
            self.draw.text((right, self.y + 34), note, SUB, waves_font_18, "rs")
            right -= _text_width(note, waves_font_18) + 18
        left = x + _text_width(title, waves_font_32) + 18
        if right > left:
            self.draw.line((left, self.y + 22, right, self.y + 22), RULE, 1)

    def paragraphs(self, x: int, y: int, w: int, texts: list, font=waves_font_18, color=BODY, center=False) -> int:
        """返回占用高度"""
        line_h = font.size + 11
        top = y
        for i, text in enumerate(texts):
            if i:
                self.draw.line((x, y + 8, x + w, y + 8), DASH, 1)
                y += 17
            for line in _wrap_matrix_text_px(text, font, w):
                if center:
                    self.draw.text((x + w // 2, y + line_h // 2), line, color, font, "mm")
                else:
                    self.draw.text((x, y + line_h // 2), line, color, font, "lm")
                y += line_h
        return y - top

    def art(self, x: int, y: int, size: int, icon, color) -> int:
        """半身像 + 脚下属性色光。返回图高"""
        art_h = int(size * 0.94)
        glow = Image.new("RGBA", (size, size // 2), (*color, 0))
        glow.putalpha(_edge_mask(glow.size).point(lambda v: int(v * 0.62)))
        self.img.alpha_composite(glow, (x, y + art_h - size // 2 + 10))
        if icon is not None:
            art = icon.resize((size, size), Image.LANCZOS).crop((0, 0, size, art_h))
            mask = _edge_mask((size, int(size * 1.1))).crop((0, 0, size, art_h))
            art.putalpha(ImageChops.multiply(art.getchannel("A"), mask))
            self.img.alpha_composite(art, (x, y))
        self.draw.line((x + size // 8, y + art_h, x + size - size // 8, y + art_h), _mix(color, (255, 255, 255), 0.2), 2)
        return art_h

    def foe(
        self, x: int, y: int, size: int, name: str, icon, color, meta: list, fonts=NAME_FONTS, meta_font=waves_font_14
    ) -> int:
        """meta: [(文字, 颜色)]。返回占用高度"""
        art_h = self.art(x, y, size, icon, color)
        cx = x + size // 2
        name_font, name = fit_text(self.draw, name, size - 6, fonts)
        name_h = fonts[0].size + 8
        self.draw.text((cx, y + art_h + 10 + name_h // 2), name, "white", name_font, "mm")
        my = y + art_h + 12 + name_h + meta_font.size // 2
        tx = cx - (sum(_text_width(t, meta_font) for t, _ in meta) + 6 * (len(meta) - 1)) // 2
        for text, text_color in meta:
            self.draw.text((tx, my), text, text_color, meta_font, "lm")
            tx += _text_width(text, meta_font) + 6
        return art_h + 12 + name_h + meta_font.size + 8

    def lineup(self, x: int, y: int, w: int, monsters: Dict[str, Any], size: int, level: int = 0) -> int:
        monsters = list(monsters.items())[:8]
        if not monsters:
            return 0
        size = min(size, w // len(monsters))
        height = 0
        for i, (monster_id, info) in enumerate(monsters):
            name = info.get("Name", "未知")
            elements = get_monster_elements(info)
            color = ELEMENT_COLOR.get(elements[0], (180, 180, 180))
            meta = []
            monster_level = info.get("Level", 0) or level
            if monster_level:
                meta.append((f"Lv.{monster_level}", SUB))
            meta += [
                (ELEMENT_NAME_MAP.get(e, "未知"), _mix(ELEMENT_COLOR.get(e, (180, 180, 180)), (255, 255, 255), 0.3))
                for e in elements
            ]
            icon = _decode_data_url(get_monster_icon(name, monster_id), 256)
            height = self.foe(x + i * size, y, size, name, icon, color, meta)
        return height


def _floor_buffs(floor_data: Dict[str, Any]) -> list[str]:
    return [desc for buff in floor_data.get("Buffs", {}).values() if (desc := clean_tags(buff.get("Desc", "")).rstrip("。."))]


def _top_arts(monsters: Dict[str, Any]) -> list:
    return [_decode_data_url(get_monster_icon(info.get("Name", ""), mid), 336) for mid, info in list(monsters.items())[:3]]


@to_thread
def _render_tower_pil(period: int, duration: str, sections):
    wings = [s for s in sections if not s[0].startswith("深境")]
    deep = [s for s in sections if s[0].startswith("深境")]
    p = _Poster("tower")
    p.hero("逆境深塔", f"第{period}期", duration, _top_arts((deep or wings)[-1][1].get("Monsters", {})))

    if wings:
        heights = []
        for i, (name, floor_data) in enumerate(wings):
            x = PAD + i * (HALF + COL_GAP)
            p.head(x, HALF, name, "第4层 · 疲劳", str(floor_data.get("Cost", 0)))
            h = 60 + p.paragraphs(x, p.y + 60, HALF, _floor_buffs(floor_data))
            h += 18 + p.lineup(x, p.y + h + 18, HALF, floor_data.get("Monsters", {}), 136)
            heights.append(h)
        p.y += max(heights) + 34

    if deep:
        costs = {floor_data.get("Cost", 0) for _, floor_data in deep}
        same_cost = len(costs) == 1
        p.head(PAD, INNER, "深境之塔", *(("每层 · 疲劳", str(min(costs))) if same_cost else ()))
        p.y += 60
        groups: list = []
        for no, (_, floor_data) in enumerate(deep, 1):
            buffs = _floor_buffs(floor_data)
            if groups and groups[-1][0] == buffs:
                groups[-1][1].append((no, floor_data))
            else:
                groups.append((buffs, [(no, floor_data)]))
        text_w = 394
        right_x = PAD + text_w + 40
        for gi, (buffs, floors) in enumerate(groups):
            if gi:
                p.draw.line((PAD, p.y, WIDTH - PAD, p.y), RULE, 1)
                p.y += 22
            text_h = p.paragraphs(PAD, p.y, text_w, buffs)
            ly = p.y
            for no, floor_data in floors:
                p.draw.text((right_x, ly - 6), str(no), INK, waves_font_60, "la", stroke_width=2, stroke_fill=p.soft)
                if not same_cost:
                    p.draw.text((right_x, ly + 78), f"疲劳 {floor_data.get('Cost', 0)}", SUB, waves_font_14, "lm")
                ly += max(96, p.lineup(right_x + 76, ly, WIDTH - PAD - right_x - 76, floor_data.get("Monsters", {}), 112)) + 14
            p.y += max(text_h, ly - p.y) + 8
    return p.finish()


@to_thread
def _render_slash_pil(period: int, duration: str, endless_data: Dict[str, Any], buff_data):
    floors = list(endless_data.get("Floor", {}).values())
    p = _Poster("slash")
    p.hero("冥歌海墟", f"第{period}期", duration, _top_arts(floors[-1].get("Monsters", {}) if floors else {}))

    desc = [
        line
        for part in re.split(r"<br\s*/?>|\n", endless_data.get("Desc", ""))
        if (line := clean_tags(part).strip().rstrip("。."))
    ]
    if desc:
        p.head(PAD, INNER, "海域特性")
        p.y += 60 + p.paragraphs(PAD, p.y + 60, INNER, desc) + 34

    if buff_data:
        p.head(PAD, INNER, "本期信物")
        p.y += 66
        icons = load_json_file(MAP_CHALLENGE_PATH / "slash_buff_icon.json") or {}
        col_w = (INNER - 60) // 3
        buffs = list(buff_data.items())
        for row in range(0, len(buffs), 3):
            heights = []
            for i, (name, desc_text) in enumerate(buffs[row : row + 3]):
                x = PAD + i * (col_w + 30)
                path = SLASH_BUFF_PATH / f"{icons.get(name)}.png"
                if path.exists():
                    art = Image.open(path).convert("RGBA").resize((132, 132), Image.LANCZOS)
                    p.img.alpha_composite(art, (x + (col_w - 132) // 2, p.y))
                    mirror = ImageOps.flip(art).crop((0, 0, 132, 56))
                    mirror.putalpha(
                        ImageChops.multiply(
                            mirror.getchannel("A"),
                            Image.linear_gradient("L").resize((132, 56)).point(lambda v: int((255 - v) * 0.4)),
                        )
                    )
                    p.img.alpha_composite(mirror, (x + (col_w - 132) // 2, p.y + 112))
                p.draw.text((x + col_w // 2, p.y + 196), name, p.soft, waves_font_22, "mm")
                heights.append(
                    216 + p.paragraphs(x, p.y + 216, col_w, [clean_tags(desc_text).rstrip("。.")], center=True)
                )
            p.y += max(heights) + 30

    heights = []
    for i, floor_data in enumerate(floors[:2]):
        x = PAD + i * (HALF + COL_GAP)
        p.head(x, HALF, f"半场{i + 1}")
        floor_desc = clean_tags(floor_data.get("Desc", "")).rstrip("。.")
        h = 60 + p.paragraphs(x, p.y + 60, HALF, [floor_desc] if floor_desc else [])
        h += 18 + p.lineup(x, p.y + h + 18, HALF, floor_data.get("Monsters", {}), 108, floor_data.get("Level", 0))
        heights.append(h)
    p.y += max(heights, default=0)
    return p.finish()


def _prepare_matrix_info(matrix_data: Dict[str, Any]) -> tuple[str, list, list, list]:
    """(关卡名, [(buff名, 说明)], [boss], [(增益说明, [角色])])"""
    levels = matrix_data.get("Levels", [])
    if not levels:
        return "", [], [], []
    target_level = next((level for level in levels if level.get("Name") == "奇点扩张"), None) or levels[-1]

    buffs = [
        (buff.get("Name", "增益"), _clean_matrix_text(buff.get("Desc", "")))
        for buff in target_level.get("NewTowerBuffs", [])
    ]

    bosses = []
    for boss in get_matrix_bosses(target_level):
        later = [line.split("】", 1) for line in boss["desc_lines"] if line.startswith("【轮次")]
        bosses.append({
            "name": boss["name"],
            "tags": [
                (tag["Name"], _parse_matrix_tag_color(tag.get("Color", ""))) for tag in boss["tags"] if tag.get("Name")
            ],
            "base": [line for line in boss["desc_lines"] if not line.startswith("【轮次")],
            "later": [(head.lstrip("【").replace("解锁", " 起"), line) for head, line in later],
            "icon": _decode_data_url(get_monster_icon(boss["name"], boss["monster_id"]), 256),
        })

    groups: Dict[str, list] = {}
    for role_data in matrix_data.get("Roles", []):
        name = role_data.get("RoleInfo", {}).get("Name", "未知")
        enhance_descs = role_data.get("EnhanceSkillDesc", [])
        desc = _clean_matrix_text(enhance_descs[0].get("Value", "")) if enhance_descs else ""
        groups.setdefault(desc, []).append((name, _load_role_icon(role_data.get("Id"), name, 116)))
    roles = sorted(groups.items(), key=lambda group: len(group[1]) <= 2)

    return target_level.get("Name", "奇点扩张"), buffs, bosses, roles


async def _draw_matrix_challenge_pil(season: int, matrix_data: Dict[str, Any]) -> Union[bytes, str]:
    level_name, buffs, bosses, roles = _prepare_matrix_info(matrix_data)
    if not level_name:
        return f"矩阵第{season}期数据为空"
    card_img = await _render_matrix_pil(season, level_name, buffs, bosses, roles)
    return await convert_img(card_img)


def _role_tile(name: str, icon: Optional[Image.Image]) -> Image.Image:
    w, h = 96, 116
    body = Image.new("RGBA", (w, h), (27, 30, 38, 255))
    if icon is not None:
        body.alpha_composite(icon, (-10, 0))
    fade = Image.new("RGBA", (w, 46), (8, 9, 14, 0))
    fade.putalpha(Image.linear_gradient("L").resize((w, 46)).point(lambda v: min(255, int(v * 1.7))))
    body.alpha_composite(fade, (0, h - 46))
    draw = ImageDraw.Draw(body)
    font, name = fit_text(draw, name, 62, (waves_font_14, waves_font_12, waves_font_10))
    draw.text((w // 2 - 6, h - 13), name, "white", font, "mm")
    mask = Image.new("L", (w * 2, h * 2), 0)
    ImageDraw.Draw(mask).polygon([(32, 0), (w * 2, 0), (w * 2 - 32, h * 2), (0, h * 2)], fill=255)
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    tile.paste(body, mask=mask.resize((w, h), Image.LANCZOS))
    return tile


@to_thread
def _render_matrix_pil(season, level_name, buffs, bosses, roles):
    p = _Poster("matrix")
    p.hero("矩阵叠兵", f"第{season}期", level_name, [boss["icon"] for boss in bosses])

    if buffs:
        p.head(PAD, INNER, "选择Buff")
        p.y += 60
        for row in range(0, len(buffs), 2):
            if row:
                p.draw.line((PAD, p.y, WIDTH - PAD, p.y), DASH, 1)
                p.y += 14
            heights = []
            for i, (name, desc) in enumerate(buffs[row : row + 2]):
                x = PAD + i * (HALF + COL_GAP)
                p.draw.text((x, p.y + 14), name, p.soft, waves_font_22, "lm")
                heights.append(34 + p.paragraphs(x, p.y + 34, HALF, [desc], waves_font_16))
            p.y += max(heights) + 14
        p.y += 20

    if bosses:
        p.head(PAD, INNER, "Boss列表")
        p.y += 62
        if any(boss["base"] or boss["later"] for boss in bosses):
            text_x = PAD + 170
            for i, boss in enumerate(bosses):
                if i:
                    p.draw.line((PAD, p.y, WIDTH - PAD, p.y), DASH, 1)
                    p.y += 14
                color = boss["tags"][0][1] if boss["tags"] else (139, 147, 163)
                art_h = p.art(PAD, p.y, 140, boss["icon"], color)
                p.draw.text((text_x, p.y + 32), boss["name"], "white", waves_font_30, "ls")
                tag_x = text_x + _text_width(boss["name"], waves_font_30) + 16
                for tag_name, tag_color in boss["tags"]:
                    p.draw.text((tag_x, p.y + 32), tag_name, _mix(tag_color, (255, 255, 255), 0.3), waves_font_16, "ls")
                    tag_x += _text_width(tag_name, waves_font_16) + 10
                col_w = (WIDTH - PAD - text_x - 30) // 2 if boss["later"] else WIDTH - PAD - text_x
                text_h = p.paragraphs(text_x, p.y + 46, col_w, boss["base"], waves_font_16)
                ly = p.y + 46
                for label, line in boss["later"]:
                    p.draw.text((text_x + col_w + 30, ly + 8), label, SUB, waves_font_14, "lm")
                    ly += 20 + p.paragraphs(text_x + col_w + 30, ly + 20, col_w, [line], waves_font_16, GOLD) + 6
                p.y += max(art_h + 10, 46 + text_h, ly - p.y) + 14
        else:
            size = min(186, INNER // len(bosses))
            x = PAD + (INNER - size * len(bosses)) // 2
            for i, boss in enumerate(bosses):
                color = boss["tags"][0][1] if boss["tags"] else (139, 147, 163)
                meta = [(name, _mix(tag_color, (255, 255, 255), 0.3)) for name, tag_color in boss["tags"]]
                height = p.foe(x + i * size, p.y, size, boss["name"], boss["icon"], color, meta, BOSS_FONTS, waves_font_16)
            p.y += height
        p.y += 20

    if roles:
        p.head(PAD, INNER, "角色增益")
        p.y += 62
        col = 0
        row_h = 0
        for i, (desc, members) in enumerate(roles):
            wide = len(members) > 2
            if wide and col:
                p.y += row_h
                col = row_h = 0
            x = PAD + col * (HALF + COL_GAP)
            if i and not col:
                p.draw.line((PAD, p.y, WIDTH - PAD, p.y), DASH, 1)
                p.y += 14
            tx = x
            for name, icon in members:
                p.img.alpha_composite(_role_tile(name, icon), (tx, p.y))
                tx += 82
            tx += 32
            lines = _wrap_matrix_text_px(desc, waves_font_16, x + (INNER if wide else HALF) - tx)
            ty = p.y + 58 - len(lines) * 27 // 2
            for line in lines:
                p.draw.text((tx, ty + 13), line, BODY, waves_font_16, "lm")
                ty += 27
            cell_h = max(116, len(lines) * 27) + 14
            if wide:
                p.y += cell_h
            else:
                row_h = max(row_h, cell_h)
                col += 1
                if col == 2:
                    p.y += row_h
                    col = row_h = 0
        p.y += row_h
    return p.finish()


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
