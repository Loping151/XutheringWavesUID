import copy
import time
import asyncio
from typing import Dict, Union
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from gsuid_core.pool import to_thread
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img

from ..utils.util import timed_async_cache
from ..utils.image import (
    GOLD,
    SPECIAL_GOLD,
    CHAIN_COLOR_LIST,
    get_ICON,
    add_footer,
    get_waves_bg,
    get_attribute,
    get_square_avatar,
)
from ..utils.api.wwapi import GET_HOLD_RATE_URL
from ..utils.ascension.char import get_char_model
from ..utils.char_info_utils import get_all_role_detail_info_list
from ..utils.database.models import WavesBind
from ..utils.fonts.waves_fonts import (
    waves_font_20,
    waves_font_24,
    waves_font_36,
    waves_font_58,
)
from ..utils.resource.constant import (
    NAME_ALIAS,
    NORMAL_LIST,
    NORMAL_LIST_IDS,
    ATTRIBUTE_ID_MAP,
    SPECIAL_CHAR_NAME,
)

TEXT_PATH = Path(__file__).parent / "texture2d"
bar1 = Image.open(TEXT_PATH / "bar1.png")
avatar_mask = Image.open(TEXT_PATH / "avatar_mask.png")


# 常驻颜色
STAR_FOUR = (219, 68, 255)
STAR_FIVE = SPECIAL_GOLD
OTHER_STAR = GOLD


async def new_draw_char_hold_rate(ev: Event, data, group_id: str = "") -> bytes:
    text = ev.text.strip() if ev.text else ""
    if "4" in text or "四" in text:
        filter_type = "四"
    elif "5" in text or "五" in text:
        filter_type = "五"
    elif "up" in text or "UP" in text:
        filter_type = "UP"
    elif "all" in text or "ALL" in text or "全" in text:
        filter_type = ""
    else:
        filter_type = "UP"  # 默认显示UP角色

    # 加载数据
    char_list = data["char_hold_rate"]
    if filter_type:
        temp = []
        for char in char_list:
            char_model = get_char_model(char["char_id"])
            if not char_model:
                continue
            if filter_type == "UP":
                if (
                    char_model.starLevel == 5
                    and int(char["char_id"]) not in NORMAL_LIST_IDS
                    and str(char["char_id"]) not in SPECIAL_CHAR_NAME
                ):
                    temp.append(char)
            elif filter_type == "五":
                if char_model.starLevel == 5 and str(char["char_id"]) not in SPECIAL_CHAR_NAME:
                    temp.append(char) # 漂子还是忽略吧
            elif filter_type == "四":
                if char_model.starLevel == 4:
                    temp.append(char)
            else:
                temp.append(char)
        char_list = temp

    # 按持有率从高到低排序
    char_list = sorted(char_list, key=lambda x: x["hold_rate"], reverse=True)

    # 预加载头像 / 属性图（在线程池里跑 PIL 前先把 await 走完）
    attr_cache: Dict[str, Image.Image] = {}
    avatar_cache: Dict[str, Image.Image] = {}
    for char_data in char_list:
        char_id = char_data["char_id"]
        char_model = get_char_model(char_id)
        if not char_model:
            continue
        attribute_name = ATTRIBUTE_ID_MAP[char_model.attributeId]
        if attribute_name not in attr_cache:
            attr_cache[attribute_name] = await get_attribute(attribute_name, is_simple=True)
        if char_id not in avatar_cache:
            pic = await get_square_avatar(char_id)
            avatar_cache[char_id] = _build_avatar(pic)

    img = await _render_char_hold_rate(
        char_list, data, filter_type, group_id, attr_cache, avatar_cache
    )

    return await convert_img(img)


@to_thread
def _render_char_hold_rate(
    char_list,
    data,
    filter_type,
    group_id,
    attr_cache,
    avatar_cache,
) -> Image.Image:
    # 设置图像尺寸
    width = 1300
    margin = 30
    item_spacing = 130
    header_height = 700
    footer_height = 50

    # 计算所需的总高度
    total_height = header_height + item_spacing * len(char_list) + margin * 2 + footer_height

    # 创建带背景的画布 - 使用bg9
    img = get_waves_bg(width, total_height, "bg9")

    # title_bg
    title_bg = Image.open(TEXT_PATH / "title2.png")
    title_mask = Image.open(TEXT_PATH / "title1.png")
    title_mask_draw = ImageDraw.Draw(title_mask)

    # icon
    icon = get_ICON()
    icon = icon.resize((180, 180))
    title_mask.paste(icon, (60, 380), icon)

    # title
    if filter_type:
        if filter_type == "UP":
            title_text = f"#UP角色持有率{group_id}"
        else:
            title_text = f"#{filter_type}星角色持有率{group_id}"
    else:
        title_text = f"#角色持有率{group_id}"
    title_mask_draw.text((300, 430), title_text, "white", waves_font_58, "lm")

    # count
    title = f"样本数量: {data.get('total_player_count', 0)} 人" if group_id else "仅统计90天内活跃，数据仅供参考，不代表全体玩家"
    title_mask_draw.text(
        (300, 500),
        title,
        "white",
        waves_font_36,
        "lm",
    )
    declar = "本数据库从未公开样本总数和具体数据，请注意辨别"
    title_mask_draw.text(
        (610, 560),
        declar,
        (180, 180, 180),
        waves_font_20,
        "lm",
    )
    time_str = time.strftime("%Y-%m-%d", time.localtime())
    title_mask_draw.text((1090, 560), time_str, "white", waves_font_20, "lm")

    img.paste(title_bg, (0, 0), title_bg)
    img.paste(title_mask, (0, 0), title_mask)

    # 绘制角色列表项
    for idx, char_data in enumerate(char_list):
        char_id = char_data["char_id"]
        char_model = get_char_model(char_id)
        if not char_model:
            continue

        # bar_bg
        bar_bg = copy.deepcopy(bar1)
        bar_bg_draw = ImageDraw.Draw(bar_bg)

        # 角色名字
        name_text = SPECIAL_CHAR_NAME.get(
            f"{char_id}", NAME_ALIAS.get(char_model.name, char_model.name)
        )
        bar_bg_draw.text((190, 40), name_text, "white", waves_font_24, "lm")

        # 属性
        attribute_name = ATTRIBUTE_ID_MAP[char_model.attributeId]
        role_attribute = attr_cache[attribute_name].resize((40, 40)).convert("RGBA")
        bar_bg.alpha_composite(role_attribute, (150, 20))

        # 绘制共鸣链持有率
        chain_data = char_data["chain_hold_rate"]
        for i in range(7):
            c_key = str(i)
            c_percent = chain_data.get(c_key, 0)

            chain_text = f"{c_key}链"

            temp_bg = Image.new("RGBA", (125, 30), (0, 0, 0, 0))
            temp_bg_draw = ImageDraw.Draw(temp_bg)

            c_color_hex = CHAIN_COLOR_LIST[i]
            temp_bg_draw.rounded_rectangle((35, 0, 125, 30), 8, fill=c_color_hex + (100,))
            temp_bg_draw.text((0, 15), chain_text, "white", waves_font_20, "lm")
            temp_bg_draw.text((80, 15), f"{c_percent:.2f}%", "white", waves_font_20, "mm")

            bar_bg.alpha_composite(temp_bg, (310 + i * 135, 26))

        # 绘制持有率
        hold_rate = char_data["hold_rate"]
        hold_rate_text = f"{hold_rate:.2f}%"
        hold_length = 1100
        real_length = int(hold_length * hold_rate / 100)
        hole_progress_bg = Image.new("RGBA", (hold_length, 24), (0, 0, 0, 0))
        hole_progress_bg_draw = ImageDraw.Draw(hole_progress_bg)

        color = OTHER_STAR
        if char_model.starLevel == 5 and char_model.name not in NORMAL_LIST:
            color = STAR_FIVE
        elif char_model.starLevel == 4:
            color = STAR_FOUR

        hole_progress_bg_draw.rounded_rectangle((0, 0, real_length, 24), 15, fill=color + (170,))
        if hold_rate < 10:
            xy = (real_length + 50, 12)
        else:
            xy = (real_length - 50, 12)
        hole_progress_bg_draw.text(
            xy,
            hold_rate_text,
            "white",
            waves_font_20,
            "mm",
        )
        bar_bg.alpha_composite(hole_progress_bg, (135, 71))

        # 绘制角色头像
        avatar = avatar_cache.get(char_id)
        if avatar is not None:
            bar_bg.paste(avatar, (50, 20), avatar)

        img.alpha_composite(bar_bg, (0, header_height + idx * item_spacing))

    # 添加页脚
    img = add_footer(img)

    return img


def _build_avatar(pic: Image.Image) -> Image.Image:
    pic_temp = Image.new("RGBA", pic.size)
    pic_temp.paste(pic.resize((160, 160)), (10, 10))

    avatar_mask_temp = copy.deepcopy(avatar_mask)
    mask_pic_temp = Image.new("RGBA", avatar_mask_temp.size)
    mask_pic_temp.paste(avatar_mask_temp, (-20, -45), avatar_mask_temp)

    img = Image.new("RGBA", (180, 180))
    mask_pic_temp = mask_pic_temp.resize((160, 160))
    resize_pic = pic_temp.resize((160, 160))
    img.paste(resize_pic, (0, 0), mask_pic_temp)

    return img


@timed_async_cache(
    expiration=3600,
    condition=lambda x: x,
)
async def get_char_hold_rate_data() -> Dict:
    """获取角色持有率数据"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(GET_HOLD_RATE_URL, timeout=10)
            response.raise_for_status()
            if response.status_code == 200:
                return response.json().get("data", {})
    except Exception as e:
        logger.error(f"[鸣潮·角色持有率] 获取角色持有率数据失败: {e}")

    return {}


async def get_group_char_hold_rate_data(group_id: str) -> Dict:
    """获取群组角色持有率数据"""
    res = {}

    users = await WavesBind.get_group_all_uid(group_id)
    if not users:
        return res

    uid_fiter = {}

    # 创建用于处理并发请求的Semaphore
    semaphore = asyncio.Semaphore(20)

    async def process_uid(uid):
        """处理单个UID的数据"""
        role_details = await get_all_role_detail_info_list(uid)
        if role_details is None:
            return None

        uid_data = {}
        for role_detail in role_details:
            uid_data[role_detail.role.roleId] = role_detail.get_chain_num()

        return uid, uid_data

    # 提取所有需要处理的UID,入口去重避免重复并发请求
    uid_set = set()
    for user in users:
        if not user.uid:
            continue
        for uid in user.uid.split("_"):
            uid_set.add(uid)
    all_uids = list(uid_set)

    # 使用Semaphore限制并发处理UID
    async def process_with_semaphore(uid):
        async with semaphore:
            return await process_uid(uid)

    # 并发执行所有UID的任务
    tasks = [process_with_semaphore(uid) for uid in all_uids]
    results = await asyncio.gather(*tasks)

    # 合并结果
    for result in results:
        if result:
            uid, uid_data = result
            uid_fiter[uid] = uid_data

    # 计算持有率
    total_player_count = len(uid_fiter)

    if total_player_count == 0:
        return res

    # 统计角色持有情况
    char_stats = {}

    for uid, chars in uid_fiter.items():
        for char_id, chain_num in chars.items():
            if char_id not in char_stats:
                char_stats[char_id] = {
                    "player_count": 0,
                    "chains": {str(i): 0 for i in range(7)},
                }

            # 增加持有人数
            char_stats[char_id]["player_count"] += 1

            # 增加对应共鸣链数量
            char_stats[char_id]["chains"][str(chain_num)] += 1

    # 构建结果数据
    char_hold_rate = []

    for char_id, stats in char_stats.items():
        player_count = stats["player_count"]
        hold_rate = round(player_count / total_player_count * 100, 1)

        # 计算共鸣链分布百分比
        chain_hold_rate = {}
        for chain, count in stats["chains"].items():
            if count > 0:
                chain_hold_rate[chain] = round(count / player_count * 100, 2)

        char_data = {
            "char_id": char_id,
            "player_count": player_count,
            "hold_rate": hold_rate,
            "chain_hold_rate": chain_hold_rate,
        }

        char_hold_rate.append(char_data)

    # 构建最终结果
    res = {"total_player_count": total_player_count, "char_hold_rate": char_hold_rate}

    return res


# 主入口函数
async def get_char_hold_rate_img(ev: Event, group_id: str = "") -> Union[bytes, str]:
    """获取角色持有率图像"""
    if group_id:
        data = await get_group_char_hold_rate_data(group_id)
        if not data:
            return "群组持有率数据获取失败，请稍后再试"
    else:
        data = await get_char_hold_rate_data()
        if not data:
            return "鸣潮角色持有率数据获取失败，请稍后再试"

    return await new_draw_char_hold_rate(ev, data, group_id=group_id)
