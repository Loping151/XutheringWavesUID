import asyncio
import re
from typing import Dict, Any, Union, Optional
from pathlib import Path

from PIL import Image

from ..wutheringwaves_config import WutheringWavesConfig
from ..utils.util import load_json_file
from ..utils.resource.RESOURCE_PATH import (
    MAP_CHALLENGE_PATH,
    waves_templates,
)
from ..utils.image import ELEMENT_COLOR_MAP, pil_to_b64, img_to_b64
from ..utils.image import get_square_avatar_path
from ..utils.name_convert import echo_name_to_echo_id, char_name_to_char_id
from ..utils.resource.RESOURCE_PATH import PHANTOM_PATH, MONSTER_PATH, SLASH_BUFF_PATH
from ..utils.render_utils import (
    PLAYWRIGHT_AVAILABLE,
    image_to_base64,
    render_html,
)
from .highlight import highlight
from ..wutheringwaves_abyss.period import (
    get_slash_period_number,
    get_tower_period_number,
    get_matrix_period_number,
)

TEXTURE2D_PATH = Path(__file__).parents[1] / "utils" / "texture2d"


def _load_bg_b64(bg_path) -> str:
    bg_img = Image.open(bg_path).transpose(Image.ROTATE_270)
    return pil_to_b64(bg_img, quality=75)

ELEMENT_NAME_MAP = {
    0: "无属性",
    1: "冷凝",
    2: "热熔",
    3: "导电",
    4: "气动",
    5: "衍射",
    6: "湮灭",
}




def get_monster_icon(monster_name: str, monster_id: Union[str, int]) -> Optional[str]:
    path = MONSTER_PATH / f"monster_{monster_id}.png"
    if not path.exists():
        echo_id = echo_name_to_echo_id(monster_name)
        if not echo_id:
            return None
        path = PHANTOM_PATH / f"phantom_{echo_id}.png"
        if not path.exists():
            path = PHANTOM_PATH / "phantom_390070051.png"
    b64 = img_to_b64(path, quality=75, bake=True, cover_size=(256, 256))
    return b64 if b64 else None


def get_monster_elements(m_info: Dict[str, Any]) -> list:
    return m_info.get("Elements") or [m_info.get("Element", 0)]


def get_monsters(floor_data: Dict[str, Any], level: int = 0) -> list:
    monsters = []
    for m_id, m_info in list(floor_data.get("Monsters", {}).items())[:8]:
        name = m_info.get("Name", "未知")
        elements = [
            {"name": e_name, "color": ELEMENT_COLOR_MAP.get(e_name, "#b4b4b4")}
            for e_name in (ELEMENT_NAME_MAP.get(e, "未知") for e in get_monster_elements(m_info))
        ]
        monsters.append({
            "name": name,
            "level": m_info.get("Level", 0) or level,
            "color": elements[0]["color"],
            "elements": elements,
            "icon": get_monster_icon(name, m_id),
        })
    return monsters


def get_matrix_bosses(level: Dict[str, Any]) -> list:
    """Waves 按名去重；后续轮次新增的说明行以【轮次N解锁】追加"""
    bosses: Dict[str, Dict[str, Any]] = {}
    for wave in level.get("Waves", []):
        name = wave.get("Name", "未知")
        lines = []
        for part in re.split(r"<br\s*/?>", wave.get("Desc", "")):
            cleaned = re.sub(r"<[^>]+>", "", part).strip()
            if cleaned and cleaned != name:
                lines.append(cleaned)
        boss = bosses.get(name)
        if boss is None:
            bosses[name] = {
                "name": name,
                "monster_id": wave.get("MonsterId", 0),
                "tags": wave.get("Tags", []),
                "desc_lines": lines,
                "round": 1,
            }
            continue
        boss["round"] += 1
        for line in lines:
            if not any(line in seen for seen in boss["desc_lines"]):
                boss["desc_lines"].append(f"【轮次{boss['round']}解锁】{line}")
    return list(bosses.values())


def _hl(text: str) -> str:
    return highlight(text, ELEMENT_COLOR_MAP)


def _clean_text(text: str) -> str:
    """清理文本中的HTML标签"""
    text = re.sub(r"<color[^>]*>", "", text)
    text = re.sub(r"</color>", "", text)
    return text


async def _process_floor_data(floor_data: Dict[str, Any]) -> Dict[str, Any]:
    """处理层级数据"""
    # 处理Buff
    buffs_text = []
    raw_buffs = floor_data.get("Buffs", {})
    for buff in raw_buffs.values():
        desc = _clean_text(buff.get("Desc", "")).rstrip("。")
        if desc:
            buffs_text.append(_hl(desc))

    monsters_data = get_monsters(floor_data)

    return {
        "cost": floor_data.get("Cost", 0),
        "buffs": buffs_text,
        "monsters": monsters_data
    }


async def draw_tower_wiki_render(period: Optional[int] = None) -> Optional[bytes]:
    """渲染深塔信息 (HTML)"""
    use_html_render = WutheringWavesConfig.get_config("UseHtmlRender").data
    if not PLAYWRIGHT_AVAILABLE or render_html is None or not use_html_render:
        return None

    if period is None:
        period = get_tower_period_number()

    # 加载数据
    json_path = MAP_CHALLENGE_PATH / "tower" / f"{period}.json"
    tower_data = load_json_file(json_path)
    if not tower_data:
        return None

    areas = tower_data.get("Area", {})
    if not areas:
        return None

    # 读取持续时间
    begin_date = tower_data.get("Begin", "")
    end_date = tower_data.get("End", "")
    duration = ""
    if begin_date and end_date:
        # 格式化日期显示（去掉年份，只保留月-日）
        begin_str = begin_date[5:] if len(begin_date) >= 10 else begin_date
        end_str = end_date[5:] if len(end_date) >= 10 else end_date
        duration = f"{begin_str} ~ {end_str}"

    # 1. 残响之塔 (左塔) - Area 1
    left_tower_floors = []
    if "1" in areas and "Floor" in areas["1"]:
        # 用户要求默认只显示第四层
        for i in [4]:
            floor_data = areas["1"]["Floor"].get(str(i))
            if floor_data:
                processed_floor = await _process_floor_data(floor_data)
                processed_floor["name"] = f"第 {i} 层"
                left_tower_floors.append(processed_floor)

    # 2. 回音之塔 (右塔) - Area 3
    right_tower_floors = []
    if "3" in areas and "Floor" in areas["3"]:
        # 用户要求默认只显示第四层
        for i in [4]:
            floor_data = areas["3"]["Floor"].get(str(i))
            if floor_data:
                processed_floor = await _process_floor_data(floor_data)
                processed_floor["name"] = f"第 {i} 层"
                right_tower_floors.append(processed_floor)

    # 3. 深境之塔 (中塔) - Area 2
    deep_tower_floors = []
    if "2" in areas and "Floor" in areas["2"]:
        # 尝试读取更多层级，虽一般只有1-2层
        for i in range(1, 10):
            floor_data = areas["2"]["Floor"].get(str(i))
            if floor_data:
                processed_floor = await _process_floor_data(floor_data)
                processed_floor["name"] = f"深境之塔 {i}层"
                deep_tower_floors.append(processed_floor)
            else:
                break

    # 使用相同方式加载背景
    bg_path = TEXTURE2D_PATH / "bg6.jpg"
    bg_b64 = await asyncio.to_thread(_load_bg_b64, bg_path)

    context = {
        "title": f"逆境深塔 第{period}期",
        "duration": duration,
        "bg_url": bg_b64,
        "theme_color": "#4e7cff", # Blue-ish for Tower
        "left_tower": {
            "name": "残响之塔 (左塔)",
            "floors": left_tower_floors
        },
        "right_tower": {
            "name": "回音之塔 (右塔)",
            "floors": right_tower_floors
        },
        "deep_tower": {
            "name": "深境之塔（中塔）",
            "floors": deep_tower_floors
        },
        "footer_url": image_to_base64(TEXTURE2D_PATH / "footer_white.png")
    }

    return await render_html(waves_templates, "wiki/challenge_card.html", context)


async def draw_matrix_wiki_render(season: Optional[int] = None) -> Optional[bytes]:
    """渲染矩阵信息 (HTML)"""
    use_html_render = WutheringWavesConfig.get_config("UseHtmlRender").data
    if not PLAYWRIGHT_AVAILABLE or render_html is None or not use_html_render:
        return None

    if season is None:
        season = get_matrix_period_number()

    # 加载数据
    json_path = MAP_CHALLENGE_PATH / "matrix" / f"{season}.json"
    matrix_data = load_json_file(json_path)
    if not matrix_data:
        return None

    levels = matrix_data.get("Levels", [])
    if not levels:
        return None

    # 找到 "奇点扩张" 关卡
    target_level = None
    for level in levels:
        if level.get("Name") == "奇点扩张":
            target_level = level
            break

    # 如果没有奇点扩张，取最后一个关卡
    if not target_level:
        target_level = levels[-1]

    level_name = target_level.get("Name", "奇点扩张")

    # 处理Buff
    buffs = []
    for buff in target_level.get("NewTowerBuffs", []):
        desc = _clean_text(buff.get("Desc", ""))
        desc = desc.replace("<br>", "\n").replace("<br/>", "\n")
        desc = re.sub(r"<[^>]+>", "", desc)
        buffs.append({
            "name": buff.get("Name", ""),
            "desc": _hl(desc),
        })

    bosses = []
    for boss in get_matrix_bosses(target_level):
        tags = []
        for tag in boss["tags"]:
            color = tag.get("Color", "ffffffff")
            tags.append({"name": tag.get("Name", ""), "color": color[:6] if len(color) == 8 else color})
        bosses.append({
            "name": boss["name"],
            "icon": get_monster_icon(boss["name"], boss["monster_id"]),
            "tags": tags,
            "desc_lines": [_hl(line) for line in boss["desc_lines"]],
        })

    # 处理角色增益
    roles = []
    for role_data in matrix_data.get("Roles", []):
        role_info = role_data.get("RoleInfo", {})
        name = role_info.get("Name", "未知")

        # 通过角色名反查本地头像
        role_icon = None
        char_id = char_name_to_char_id(name)
        if char_id:
            role_icon = img_to_b64(get_square_avatar_path(char_id), quality=75, bake=True, cover_size=(256, 256)) or None

        # 获取增益描述
        enhance_descs = role_data.get("EnhanceSkillDesc", [])
        desc = ""
        if enhance_descs:
            desc = enhance_descs[0].get("Value", "")

        roles.append({
            "name": name,
            "icon": role_icon,
            "desc": _hl(desc),
        })

    # 加载背景
    bg_path = TEXTURE2D_PATH / "bg6.jpg"
    bg_b64 = await asyncio.to_thread(_load_bg_b64, bg_path)

    context = {
        "title": f"矩阵叠兵 第{season}期",
        "subtitle": level_name,
        "bg_url": bg_b64,
        "theme_color": "#ff6b6b",
        "buffs": buffs,
        "bosses": bosses,
        "roles": roles,
        "footer_url": image_to_base64(TEXTURE2D_PATH / "footer_white.png"),
    }

    return await render_html(waves_templates, "wiki/matrix_card.html", context)


async def draw_slash_wiki_render(period: Optional[int] = None) -> Optional[bytes]:
    """渲染海墟信息 (HTML)"""
    use_html_render = WutheringWavesConfig.get_config("UseHtmlRender").data
    if not PLAYWRIGHT_AVAILABLE or render_html is None or not use_html_render:
        return None

    if period is None:
        period = get_slash_period_number()

    # 加载数据
    json_path = MAP_CHALLENGE_PATH / "slash" / f"{period}.json"
    slash_data = load_json_file(json_path)
    if not slash_data:
        return None

    challenges = slash_data.get("Id", {})

    # 读取持续时间
    begin_date = slash_data.get("Begin", "")
    end_date = slash_data.get("End", "")
    duration = ""
    if begin_date and end_date:
        # 格式化日期显示（去掉年份，只保留月-日）
        begin_str = begin_date[5:] if len(begin_date) >= 10 else begin_date
        end_str = end_date[5:] if len(end_date) >= 10 else end_date
        duration = f"{begin_str} ~ {end_str}"

    # 获取无尽湍渊(挑战12)的数据
    endless_data = None
    for challenge in challenges.values():
        if challenge.get("EndLess"):
            endless_data = challenge
            break

    # 兼容旧版本
    if not endless_data:
        endless_data = challenges.get("12")

    if not endless_data:
        return None

    # 加载额外的Buff数据 (可选)
    buff_json_path = MAP_CHALLENGE_PATH / "slash" / f"buff_{period}.json"
    buff_data = load_json_file(buff_json_path)

    # 处理全局Buff
    global_buffs = []
    if buff_data:
        buff_icons = load_json_file(MAP_CHALLENGE_PATH / "slash_buff_icon.json") or {}
        for b_name, b_desc in buff_data.items():
            icon = buff_icons.get(b_name)
            global_buffs.append({
                "name": b_name,
                "desc": _hl(_clean_text(b_desc).rstrip("。")),
                "icon": img_to_b64(SLASH_BUFF_PATH / f"{icon}.png", quality=75, bake=True) if icon else "",
            })

    # 处理海域特性
    desc = endless_data.get("Desc", "")
    desc = _clean_text(desc).rstrip("。")
    desc_lines = [_hl(line.strip()) for line in re.split(r"<br\s*/?>|\n", desc) if line.strip()]

    # 处理半场 (Floors)
    raw_floors = endless_data.get("Floor", {})
    floor_list = list(raw_floors.values())

    floors_render_data = []

    for i, floor_data in enumerate(floor_list):
        # Floor Desc
        f_desc = []
        f_desc_raw = _clean_text(floor_data.get("Desc", "")).rstrip("。")
        if f_desc_raw:
             f_desc.append(_hl(f_desc_raw))

        monsters_data = get_monsters(floor_data, floor_data.get("Level", 0))

        floors_render_data.append({
            "name": f"半场 {i + 1}",
            "desc": f_desc,
            "monsters": monsters_data
        })

    # 使用相同方式加载背景
    bg_path = TEXTURE2D_PATH / "bg6.jpg"
    bg_b64 = await asyncio.to_thread(_load_bg_b64, bg_path)

    context = {
        "title": f"冥歌海墟 第{period}期",
        "duration": duration,
        "bg_url": bg_b64,
        "theme_color": "#ffca28", # Gold-ish for Slash
        "desc": desc_lines,
        "global_buffs": global_buffs,
        "floors": floors_render_data,
        "footer_url": image_to_base64(TEXTURE2D_PATH / "footer_white.png")
    }

    return await render_html(waves_templates, "wiki/slash_card.html", context)
