import os
import json
import random
import warnings
from typing import Dict, List
from pathlib import Path

import aiofiles
from PIL import Image, ImageDraw, ImageFilter

# 忽略PIL解压缩炸弹警告
warnings.filterwarnings('ignore', category=Image.DecompressionBombWarning)

from gsuid_core.pool import to_thread
from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img
from gsuid_core.utils.image.image_tools import crop_center_img

from ..utils import hint
from ..utils.util import hide_uid, get_hide_uid_pref
from ..utils.image import (
    GOLD,
    add_footer,
    get_waves_bg,
    get_event_avatar,
    get_square_avatar,
    get_square_weapon,
    cropped_square_avatar,
)
from ..utils.api.model import AccountBaseInfo
from ..utils.waves_api import waves_api
from ..utils.error_reply import WAVES_CODE_102
from ..wutheringwaves_config import PREFIX
from ..utils.fonts.waves_fonts import (
    waves_font_18,
    waves_font_20,
    waves_font_23,
    waves_font_24,
    waves_font_25,
    waves_font_30,
    waves_font_32,
    waves_font_40,
)
from ..utils.resource.constant import NORMAL_LIST
from ..utils.resource.RESOURCE_PATH import PLAYER_PATH

TEXT_PATH = Path(__file__).parent / "texture2d"
HOMO_TAG = ["非到极致", "运气不好", "平稳保底", "小欧一把", "欧狗在此"]

gacha_type_meta_rename = {
    "角色精准调谐": "角色精准调谐",
    "武器精准调谐": "武器精准调谐",
    "角色调谐（常驻池）": "角色常驻调谐",
    "武器调谐（常驻池）": "武器常驻调谐",
    "新手调谐": "新手调谐",
    "新手自选唤取": "新手自选唤取",
    "新手自选唤取（感恩定向唤取）": "感恩定向唤取",
    "角色新旅唤取": "角色新旅唤取",
    "武器新旅唤取": "武器新旅唤取",
    "角色联动唤取": "角色联动唤取",
    "武器联动唤取": "武器联动唤取",
}


def get_num_h(num: int, column: int):
    if num == 0:
        return 0
    row = ((num - 1) // column) + 1
    return row


def get_level_from_list(ast: int, lst: List) -> int:
    if ast == 0:
        return 2

    for num_index, num in enumerate(lst):
        if ast <= num:
            level = 4 - num_index
            break
    else:
        level = 0
    return level


async def draw_card_help():
    text = "\n".join(
        [
            "如何导入抽卡记录",
            f"1. 使用命令【{PREFIX}抽卡登录】登录一次后，可直接刷新抽卡数据",
            "",
            f"2. 传统方法：使用命令【{PREFIX}导入抽卡链接 + 你复制的内容】即可开始进行抽卡分析",
            "抽卡链接具有有效期，请在有效期内尽快导入",
            "",
            f"3. 导入有效数据后，可以从其他来源合并较旧抽卡数据，只能合并一次",
            "工坊/小黑盒导入：",
            "要求先使用任意方式更新最近180天记录后，",
            f"{PREFIX}导入工坊抽卡记录UID（9位特征码）",
            f"{PREFIX}导入小黑盒抽卡记录ID（8位小黑盒ID）",
            "",
            f"4. 文件导入：请尝试私聊发送json文件",
            "",
            "以下为传统方法的链接/记录获取方式",
        ]
    )

    yun = "\n".join(
        [
            "网页获取方式",
            "1.复制以下链接到浏览器打开",
            "https://ga.loping151.site",
            "2.登录后,依次点击`刷新记录`,`复制记录`按钮",
        ]
    )

    # pc = "\n".join(
    #     [
    #         "PC获取方式（已失效，建议使用上方两种获取方式）",
    #         "1.打开游戏抽卡界面，点开换取记录",
    #         "2.在鸣潮安装的目录下进入目录：`Wuthering Waves\\Wuthering Waves Game\\Client\\Saved\\Logs`",
    #         "3.找到文件`Client.log`并用记事本打开",
    #         "4.搜索关键字：aki-gm-resources.aki-game",
    #         "5.复制一整行链接"
    #     ]
    # )

    android = "\n".join(
        [
            "安卓手机获取链接方式",
            "1.打开游戏抽卡界面",
            "2.关闭网络或打开飞行模式",
            "3.点开换取记录",
            "4.长按左上角区域，全选，复制"
        ]
    )

    ios = "\n".join(
        [
            "苹果手机获取方式",
            "1.使用Stream抓包（详细教程网上搜索）",
            "2.关键字搜索:[game2]的请求",
            "3.点击`请求`",
            "4.点击最下方的`查看JSON`，全选，复制",
            "国服域名：[gmserver-api.aki-game2.com]",
            "国际服域名：[gmserver-api.aki-game2.net]"
        ]
    )

    wechat = "\n".join(
        [
            "微信小程序编辑抽卡记录：",
            "搜索微信小程序：【XWUID】",
            "从机器人导入抽卡记录后，在小程序中使用文件导入抽卡记录，完成编辑后导出文件，并重新导入到机器人中",
        ]
    )

    msg = [text, yun, android, ios, wechat]
    return msg


def _compute_pool_stats(gachalogs: Dict) -> Dict:
    """对每个卡池计算 total/avg/avg_up/remain/r_num/up_list/rank_s_list/level/time_range."""
    total_data = {}
    for gacha_name in gachalogs:
        total_data[gacha_name] = {
            "total": 0,
            "avg": 0,
            "avg_up": 0,
            "remain": 0,
            "time_range": "",
            "r_num": [],
            "up_list": [],
            "rank_s_list": [],
            "level": 0,
        }

    for gacha_name in gachalogs:
        num = 1
        gacha_data = gachalogs[gacha_name]
        current_data = total_data[gacha_name]

        for index, data in enumerate(gacha_data[::-1]):
            if index == 0:
                current_data["time_range"] = data["time"]
            if index == len(gacha_data) - 1:
                current_data["time_range"] += "~" + data["time"]

            if data["qualityLevel"] == 5:
                data["gacha_num"] = num
                data["is_up"] = data["name"] not in NORMAL_LIST

                current_data["r_num"].append(num)
                current_data["rank_s_list"].append(data)
                if data["is_up"]:
                    current_data["up_list"].append(data)
                num = 1
            else:
                num += 1
            current_data["total"] += 1

        current_data["remain"] = num - 1
        if current_data["rank_s_list"]:
            _d = sum(current_data["r_num"]) / len(current_data["r_num"])
            current_data["avg"] = float("{:.2f}".format(_d))
        if current_data["up_list"]:
            _u = sum(current_data["r_num"]) / len(current_data["up_list"])
            current_data["avg_up"] = float("{:.2f}".format(_u))

        current_data["level"] = 2
        if current_data["avg_up"] or current_data["avg"]:
            if gacha_name == "角色精准调谐":
                if current_data["avg_up"]:
                    current_data["level"] = get_level_from_list(current_data["avg_up"], [68, 81, 93, 99, 114])
                elif current_data["avg"]:
                    current_data["level"] = get_level_from_list(current_data["avg"], [47, 54, 62, 67, 69])
            elif gacha_name in [
                "武器精准调谐",
                "角色调谐（常驻池）",
                "武器调谐（常驻池）",
                "新手自选唤取",
            ]:
                if current_data["avg"]:
                    current_data["level"] = get_level_from_list(current_data["avg"], [45, 52, 59, 65, 70])
            elif gacha_name == "新手调谐":
                if current_data["avg"]:
                    current_data["level"] = get_level_from_list(current_data["avg"], [10, 20, 30, 40, 45])

    return total_data


async def get_gacha_stats(uid: str) -> Dict:
    """获取抽卡统计信息，优先从缓存读取，否则从原始数据计算"""
    _dir = PLAYER_PATH / str(uid)
    _dir.mkdir(parents=True, exist_ok=True)

    gacha_log_path = _dir / "gacha_logs.json"
    stats_path = _dir / "gachaStats.json"
    if gacha_log_path.exists() and stats_path.exists():
        try:
            async with aiofiles.open(stats_path, "r", encoding="utf-8") as f:
                cached = json.loads(await f.read())
            if all(
                isinstance(v.get("avg"), (int, float))
                and isinstance(v.get("avg_up"), (int, float))
                for v in cached.values()
                if isinstance(v, dict)
            ):
                return cached
        except Exception:
            pass

    if not gacha_log_path.exists():
        return {}

    try:
        async with aiofiles.open(gacha_log_path, "r", encoding="utf-8") as f:
            raw_data = json.loads(await f.read())

        total_data = _compute_pool_stats(raw_data.get("data", {}))
        stats_data = _total_to_stats(total_data)
        await save_gacha_stats(uid, total_data)
        return stats_data
    except Exception:
        return {}


def _total_to_stats(total_data: Dict) -> Dict:
    stats_data = {}
    for gacha_name, data in total_data.items():
        combined_avg = data["avg_up"] or data["avg"] or 0
        stats_data[gacha_name] = {
            "total": data["total"],
            "avg": data["avg"],
            "avg_up": data["avg_up"],
            "combined_avg": combined_avg,
            "remain": data["remain"],
            "r_num": data["r_num"],
            "up_count": len(data["up_list"]),
            "rank_s_count": len(data["rank_s_list"]),
            "level": data["level"],
            "char_gold": len(data["rank_s_list"]) if gacha_name == "角色精准调谐" else 0,
            "weapon_gold": len(data["rank_s_list"]) if gacha_name == "武器精准调谐" else 0,
        }
    return stats_data


async def save_gacha_stats(uid: str, total_data: Dict):
    """保存抽卡统计信息到本地文件"""
    try:
        _dir = PLAYER_PATH / str(uid)
        _dir.mkdir(parents=True, exist_ok=True)
        path = _dir / "gachaStats.json"
        stats_data = _total_to_stats(total_data)
        async with aiofiles.open(path, "w", encoding="utf-8") as file:
            await file.write(json.dumps(stats_data, ensure_ascii=False))
    except Exception:
        pass


async def draw_card(uid: str, ev: Event):
    # 获取数据
    gacha_log_path = PLAYER_PATH / str(uid) / "gacha_logs.json"
    if not gacha_log_path.exists():
        return f"[鸣潮] 你还没有抽卡记录噢!\n 请查看 {PREFIX}抽卡帮助 中的提示导入!"
    async with aiofiles.open(gacha_log_path, "r", encoding="UTF-8") as f:
        raw_data: Dict = json.loads(await f.read())

    gachalogs = raw_data["data"]
    title_num = len([1 for i in gachalogs.keys() if "新手" not in i])

    total_data = _compute_pool_stats(gachalogs)
    stats_path = PLAYER_PATH / str(uid) / "gachaStats.json"
    if not stats_path.exists():
        await save_gacha_stats(uid, total_data)

    # 预加载所有抽卡物品的图标
    item_icon_cache: Dict[str, Image.Image] = {}
    for gacha_name, gacha_data in total_data.items():
        for item in gacha_data["rank_s_list"]:
            key = f"{item['resourceType']}:{item['resourceId']}"
            if key in item_icon_cache:
                continue
            if item["resourceType"] == "武器":
                icon = await get_square_weapon(item["resourceId"])
            else:
                avatar = await get_square_avatar(item["resourceId"])
                icon = await cropped_square_avatar(avatar, 130)
            item_icon_cache[key] = icon

    card_img = await _render_gacha_card(total_data, title_num, item_icon_cache)

    await draw_uid_avatar(uid, ev, card_img)

    card_img = add_footer(card_img, 600, 20)
    card_img = await convert_img(card_img)
    return card_img


@to_thread
def _render_gacha_card(
    total_data: Dict,
    title_num: int,
    item_icon_cache: Dict[str, Image.Image],
) -> Image.Image:
    oset = 280
    bset = 170
    pitch = 162
    row_h = bset
    _header = 430
    footer = 50

    # 仅展示有抽卡记录（总抽数 > 0）的卡池
    show_main = [n for n in total_data if "新手" not in n and total_data[n]["total"] > 0]
    show_newbie = [n for n in total_data if "新手" in n and total_data[n]["total"] > 0]
    drawable_newbie = [n for n in show_newbie if total_data[n]["rank_s_list"]]
    title_num = len(show_main)
    _newbielen = 395 if drawable_newbie else 0

    def _content_h(col: int) -> int:
        body = 0
        for n in show_main:
            _num = len(total_data[n]["rank_s_list"])
            body += 50 if _num == 0 else row_h * get_num_h(_num, col)
        return _header + title_num * oset + body + _newbielen + footer

    # 列数：让「角色精准调谐」池的 5 星网格接近 2:3（宽:高），图标原尺寸、列数 5~15。
    # 没有该池数据时退用展示池中金数最多者。
    ref_n = len(total_data.get("角色精准调谐", {}).get("rank_s_list", []))
    if ref_n == 0:
        ref_n = max((len(total_data[n]["rank_s_list"]) for n in show_main), default=0)
    column = 5
    if ref_n > 0:
        best_diff = None
        for col in range(5, 16):
            ratio = (pitch * col) / (row_h * get_num_h(ref_n, col))
            diff = abs(ratio - 2 / 3)
            if best_diff is None or diff < best_diff:
                column, best_diff = col, diff
    w = pitch * column + 190
    h = _content_h(column)

    card_img = get_waves_bg(w, h, bg="bg13")
    card_draw = ImageDraw.Draw(card_img)

    item_fg = Image.open(TEXT_PATH / "char_bg.png")
    up_icon = Image.open(TEXT_PATH / "up_tag.png")
    up_icon = up_icon.resize((68, 52))
    title_overlays = []
    for overlay_name in (
        "gacha_title_sky_overlay.png",
        "gacha_title_sky_overlay_1.png",
        "gacha_title_sky_overlay_2.png",
        "gacha_title_sky_overlay_3.png",
    ):
        overlay_path = TEXT_PATH / overlay_name
        if overlay_path.exists():
            title_overlays.append(Image.open(overlay_path).convert("RGBA"))

    def _shuffle_title_overlays() -> List[Image.Image]:
        overlay_pool = title_overlays.copy()
        random.shuffle(overlay_pool)
        return overlay_pool

    title_overlay_pool = _shuffle_title_overlays()

    def _take_title_overlay() -> Image.Image:
        nonlocal title_overlay_pool
        if not title_overlay_pool:
            title_overlay_pool = _shuffle_title_overlays()
        return title_overlay_pool.pop()

    def _crop_title_overlay(overlay: Image.Image, width: int) -> Image.Image:
        overlay_x_max = overlay.width - width
        overlay_x = 0 if overlay_x_max <= 0 else random.randint(0, overlay_x_max)
        return overlay.crop((overlay_x, 0, overlay_x + width, 300))

    def draw_pic(item) -> Image.Image:
        item_bg = Image.new("RGBA", (167, 170))
        item_fg_cp = item_fg.copy()
        item_bg.paste(item_fg_cp, (0, 0), item_fg_cp)

        item_temp = Image.new("RGBA", (167, 170))
        key = f"{item['resourceType']}:{item['resourceId']}"
        item_icon = item_icon_cache[key]
        if item["resourceType"] == "武器":
            item_icon = item_icon.resize((130, 130)).convert("RGBA")
            item_temp.paste(item_icon, (22, 0), item_icon)
        else:
            item_temp.paste(item_icon, (22, 0), item_icon)

        item_bg.paste(item_temp, (-2, -2), item_temp)
        gnum = item["gacha_num"]
        if gnum >= 70:
            # gcolor = (223, 88, 75)
            gcolor = (230, 58, 58)
        elif gnum <= 40:
            gcolor = (43, 210, 43)
        else:
            gcolor = "white"
        info_block = Image.new("RGBA", (137, 28), color=(255, 255, 255, 0))
        info_block_draw = ImageDraw.Draw(info_block)
        info_block_draw.rectangle([0, 0, 137, 28], fill=(0, 0, 0, int(0.6 * 255)))
        info_block_draw.text((65, 12), f"{item['gacha_num']}抽", gcolor, waves_font_20, "mm")

        item_bg.paste(info_block, (15, 130), info_block)

        if item["is_up"]:
            up_icon_cp = up_icon.copy()
            item_bg.paste(up_icon_cp, (88, 3), up_icon_cp)
        return item_bg

    def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    def _draw_metric(
        draw: ImageDraw.ImageDraw,
        box: tuple,
        value: str,
        label: str,
        accent: tuple,
    ):
        x1, y1, x2, y2 = box
        draw.rounded_rectangle(
            box,
            radius=16,
            fill=(6, 20, 29, 186),
            outline=(128, 213, 213, 58),
            width=1,
        )
        draw.rounded_rectangle(
            [x1 + 12, y1 + 10, x2 - 12, y1 + 14],
            radius=2,
            fill=accent,
        )
        draw.text(
            ((x1 + x2) // 2, y1 + 40),
            value,
            (255, 255, 255),
            waves_font_32,
            "mm",
            stroke_width=1,
            stroke_fill=(0, 0, 20, 110),
        )
        draw.text(
            ((x1 + x2) // 2, y1 + 72),
            label,
            (205, 230, 230),
            waves_font_20,
            "mm",
        )

    y = 0
    gindex = 0
    for gacha_name in show_main:
        gacha_data = total_data[gacha_name]
        title_overlay = _take_title_overlay()
        title_w = max(980, min(w - 20, title_overlay.width))
        title = Image.new("RGBA", (title_w, 300), (0, 0, 0, 0))

        shadow = Image.new("RGBA", title.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.rounded_rectangle([66, 24, title_w - 66, 258], radius=28, fill=(3, 16, 24, 145))
        shadow = shadow.filter(ImageFilter.GaussianBlur(12))
        title.alpha_composite(shadow)

        panel_box = [70, 16, title_w - 70, 248]
        panel = Image.new("RGBA", title.size, (0, 0, 0, 0))
        panel_draw = ImageDraw.Draw(panel)
        panel_draw.rounded_rectangle(panel_box, radius=28, fill=(6, 24, 34, 238))
        panel_draw.rounded_rectangle([panel_box[0], panel_box[1], panel_box[2], 88], radius=28, fill=(18, 54, 65, 66))
        panel.alpha_composite(_crop_title_overlay(title_overlay, title_w))

        panel_mask = Image.new("L", title.size, 0)
        panel_mask_draw = ImageDraw.Draw(panel_mask)
        panel_mask_draw.rounded_rectangle(panel_box, radius=28, fill=255)
        panel.putalpha(panel_mask)
        title.alpha_composite(panel)

        title_draw = ImageDraw.Draw(title)
        content_left = panel_box[0] + 28
        right_panel_w = 232
        right_panel_x = panel_box[2] - right_panel_w - 26
        title_draw.rounded_rectangle(panel_box, radius=28, outline=(161, 224, 223, 94), width=2)
        title_draw.rounded_rectangle(
            [panel_box[0] + 6, panel_box[1] + 6, panel_box[2] - 6, panel_box[3] - 6],
            radius=22,
            outline=(234, 255, 253, 23),
            width=1,
        )
        title_draw.line([right_panel_x - 42, 54, right_panel_x - 42, 226], fill=(175, 232, 229, 38), width=1)

        remain_s = f"{gacha_data['remain']}"
        avg_s = "-" if not gacha_data["avg"] else f"{gacha_data['avg']}"
        avg_up_s = "-" if not gacha_data["avg_up"] else f"{gacha_data['avg_up']}"
        total = f"{gacha_data['total']}"
        level = gacha_data["level"]

        if gacha_data["time_range"]:
            time_range = gacha_data["time_range"]
        else:
            time_range = "暂未抽过卡!"

        level_path = TEXT_PATH / f"{level}"
        level_icon = Image.open(random.choice(list(level_path.iterdir())))
        level_icon = level_icon.resize((140, 140)).convert("RGBA")
        tag = HOMO_TAG[level]

        title_name = gacha_type_meta_rename[gacha_name]
        title_draw.text(
            (content_left, 58),
            title_name,
            (255, 255, 255),
            waves_font_40,
            "lm",
            stroke_width=1,
            stroke_fill=(0, 0, 24, 130),
        )

        remain_prefix = "已"
        remain_suffix = "抽未出金"
        remain_content_w = (
            _text_width(title_draw, remain_prefix, waves_font_23)
            + 10
            + _text_width(title_draw, remain_s, waves_font_40)
            + 8
            + _text_width(title_draw, remain_suffix, waves_font_23)
        )
        remain_w = max(238, remain_content_w + 46)
        title_name_w = _text_width(title_draw, title_name, waves_font_40)
        remain_x0 = min(content_left + title_name_w + 48, right_panel_x - remain_w - 56)
        remain_x0 = max(content_left + 300, remain_x0)
        remain_box = [remain_x0, 38, remain_x0 + remain_w, 82]
        title_draw.rounded_rectangle(
            remain_box,
            radius=23,
            fill=(10, 22, 31, 178),
            outline=(166, 226, 224, 62),
            width=1,
        )
        remain_x = remain_box[0] + 23
        title_draw.text((remain_x, 60), remain_prefix, (224, 245, 244), waves_font_23, "lm")
        remain_x += _text_width(title_draw, remain_prefix, waves_font_23) + 10
        title_draw.text(
            (remain_x, 58),
            remain_s,
            (245, 86, 105),
            waves_font_40,
            "lm",
            stroke_width=1,
            stroke_fill=(66, 0, 24, 150),
        )
        remain_x += _text_width(title_draw, remain_s, waves_font_40) + 8
        title_draw.text((remain_x, 60), remain_suffix, (224, 245, 244), waves_font_23, "lm")

        time_text_w = _text_width(title_draw, time_range, waves_font_18)
        time_box_w = min(time_text_w + 34, right_panel_x - content_left - 82)
        title_draw.rounded_rectangle(
            [content_left, 100, content_left + time_box_w, 128],
            radius=14,
            fill=(5, 18, 28, 126),
        )
        title_draw.text(
            (content_left + 17, 114),
            time_range,
            (209, 229, 230),
            waves_font_18,
            "lm",
        )

        metric_gap = 14
        metric_w = min(172, max(150, (right_panel_x - content_left - 82 - metric_gap * 2) // 3))
        metric_y1 = 152
        metric_y2 = 238
        _draw_metric(
            title_draw,
            [content_left, metric_y1, content_left + metric_w, metric_y2],
            avg_s,
            "平均出金",
            (133, 210, 224, 184),
        )
        metric_x = content_left + metric_w + metric_gap
        _draw_metric(
            title_draw,
            [metric_x, metric_y1, metric_x + metric_w, metric_y2],
            avg_up_s,
            "平均UP",
            (151, 222, 194, 184),
        )
        metric_x += metric_w + metric_gap
        _draw_metric(
            title_draw,
            [metric_x, metric_y1, metric_x + metric_w, metric_y2],
            total,
            "总抽数",
            (222, 211, 139, 178),
        )

        title_draw.rounded_rectangle(
            [right_panel_x, 38, right_panel_x + right_panel_w, 236],
            radius=22,
            fill=(8, 20, 30, 142),
            outline=(166, 226, 224, 68),
            width=1,
        )
        avatar_x = right_panel_x + (right_panel_w - 140) // 2
        title_draw.rounded_rectangle(
            [avatar_x - 6, 50, avatar_x + 146, 202],
            radius=22,
            fill=(5, 15, 24, 184),
        )
        icon_mask = Image.new("L", (140, 140), 0)
        icon_mask_draw = ImageDraw.Draw(icon_mask)
        icon_mask_draw.rounded_rectangle([0, 0, 139, 139], radius=18, fill=255)
        title.paste(level_icon, (avatar_x, 56), icon_mask)
        tag_center_x = right_panel_x + right_panel_w // 2
        title_draw.text(
            (tag_center_x, 219),
            tag,
            (255, 255, 255),
            waves_font_24,
            "mm",
            stroke_width=1,
            stroke_fill=(0, 0, 22, 130),
        )

        card_img.paste(title, (10, _header + y + gindex * oset), title)
        gindex += 1
        s_list = gacha_data["rank_s_list"]
        s_list.reverse()
        for index, item in enumerate(s_list):
            item_bg = draw_pic(item)

            _x = 95 + pitch * (index % column)
            _y = _header + row_h * (index // column) + y + gindex * oset

            card_img.paste(
                item_bg,
                (_x, _y),
                item_bg,
            )
        if not s_list:
            card_draw.text(
                (w // 2, _header + y + gindex * oset + 25),
                "当前该卡池暂未有5星数据噢!",
                (157, 157, 157),
                waves_font_20,
                "mm",
            )
            y += 50
        else:
            y += get_num_h(len(s_list), column) * row_h

    newbie_card_w = 250
    newbie_card_h = 360
    newbie_gap = 30
    newbie_total_w = len(drawable_newbie) * newbie_card_w + max(0, len(drawable_newbie) - 1) * newbie_gap
    newbie_start_x = max(10, (w - newbie_total_w) // 2)
    nindex = 0
    for gacha_name in drawable_newbie:
        gacha_data = total_data[gacha_name]

        s_list = gacha_data["rank_s_list"]
        item_bg = draw_pic(s_list[0])

        newbie_bg_cp = Image.new("RGBA", (newbie_card_w, newbie_card_h), (0, 0, 0, 0))
        newbie_shadow = Image.new("RGBA", newbie_bg_cp.size, (0, 0, 0, 0))
        newbie_shadow_draw = ImageDraw.Draw(newbie_shadow)
        newbie_shadow_draw.rounded_rectangle(
            [10, 12, newbie_card_w - 10, newbie_card_h - 20],
            radius=24,
            fill=(3, 16, 24, 150),
        )
        newbie_shadow = newbie_shadow.filter(ImageFilter.GaussianBlur(10))
        newbie_bg_cp.alpha_composite(newbie_shadow)

        newbie_panel = Image.new("RGBA", newbie_bg_cp.size, (0, 0, 0, 0))
        newbie_panel_draw = ImageDraw.Draw(newbie_panel)
        newbie_panel_box = [8, 8, newbie_card_w - 8, newbie_card_h - 24]
        newbie_panel_draw.rounded_rectangle(newbie_panel_box, radius=24, fill=(6, 24, 34, 238))
        newbie_overlay = _take_title_overlay()
        newbie_panel.alpha_composite(_crop_title_overlay(newbie_overlay, newbie_card_w), (0, 18))
        newbie_mask = Image.new("L", newbie_bg_cp.size, 0)
        newbie_mask_draw = ImageDraw.Draw(newbie_mask)
        newbie_mask_draw.rounded_rectangle(newbie_panel_box, radius=24, fill=255)
        clipped_newbie = Image.new("RGBA", newbie_bg_cp.size, (0, 0, 0, 0))
        clipped_newbie.paste(newbie_panel, (0, 0), newbie_mask)
        newbie_bg_cp.alpha_composite(clipped_newbie)

        newbie_bg_cp_draw = ImageDraw.Draw(newbie_bg_cp)
        newbie_bg_cp_draw.rounded_rectangle(newbie_panel_box, radius=24, outline=(161, 224, 223, 94), width=2)
        newbie_bg_cp_draw.rounded_rectangle(
            [16, 16, newbie_card_w - 16, newbie_card_h - 32],
            radius=20,
            outline=(234, 255, 253, 24),
            width=1,
        )
        newbie_bg_cp_draw.text(
            (newbie_card_w // 2, 54),
            gacha_type_meta_rename[gacha_name],
            "white",
            waves_font_32,
            "mm",
            stroke_width=1,
            stroke_fill=(0, 0, 22, 130),
        )
        if gacha_data["time_range"]:
            time_range = (
                gacha_data["time_range"].split("~")[1] if "~" in gacha_data["time_range"] else gacha_data["time_range"]
            )
        else:
            time_range = "暂未抽过卡!"
        newbie_bg_cp_draw.rounded_rectangle(
            [28, 82, newbie_card_w - 28, 110],
            radius=14,
            fill=(5, 18, 28, 140),
        )
        newbie_bg_cp_draw.text(
            (newbie_card_w // 2, 96),
            time_range,
            (209, 229, 230),
            waves_font_18,
            "mm",
        )
        item_frame_x = (newbie_card_w - 184) // 2
        newbie_bg_cp_draw.rounded_rectangle(
            [item_frame_x, 132, item_frame_x + 184, 322],
            radius=18,
            fill=(5, 15, 24, 148),
            outline=(128, 213, 213, 58),
            width=1,
        )
        newbie_bg_cp.paste(item_bg, ((newbie_card_w - 167) // 2, 142), item_bg)

        card_img.paste(
            newbie_bg_cp,
            (newbie_start_x + nindex * (newbie_card_w + newbie_gap), _header + y + gindex * oset + 35),
            newbie_bg_cp,
        )
        nindex += 1

    return card_img


async def draw_pic_with_ring(ev: Event):
    pic = await get_event_avatar(ev, is_valid_at_param=False)

    mask_pic = Image.open(TEXT_PATH / "avatar_mask.png")
    img = Image.new("RGBA", (320, 320))
    mask = mask_pic.resize((250, 250))
    resize_pic = crop_center_img(pic, 250, 250)
    img.paste(resize_pic, (20, 20), mask)
    return img


async def get_random_card_polygon(ev: Event):
    CARD_POLYGON_PATH = TEXT_PATH / "card_polygon"
    path = random.choice(os.listdir(f"{CARD_POLYGON_PATH}"))
    card_img = Image.open(f"{CARD_POLYGON_PATH}/{path}").convert("RGBA")

    avatar = await draw_pic_with_ring(ev)
    avatar = avatar.resize((500, 500))
    card_img.paste(avatar, (-10, 150), avatar)

    avatar_ring = Image.open(TEXT_PATH / "avatar_ring.png")
    avatar_ring = avatar_ring.resize((450, 450))
    card_img.paste(avatar_ring, (-10, 150), avatar_ring)

    return card_img.resize((280, 400))


async def draw_uid_avatar(uid, ev, card_img):
    user_pref = await get_hide_uid_pref(uid, ev.user_id, ev.bot_id)
    if waves_api.is_net(uid):
        title = Image.open(TEXT_PATH / "title.png")
        base_info_draw = ImageDraw.Draw(title)
        base_info_draw.text((346, 370), f"特征码:  {hide_uid(uid, user_pref=user_pref)}", GOLD, waves_font_25, "lm")

        avatar = await draw_pic_with_ring(ev)
        avatar_ring = Image.open(TEXT_PATH / "avatar_ring.png")

        card_img.paste(avatar, (346, 40), avatar)
        avatar_ring = avatar_ring.resize((300, 300))
        card_img.paste(avatar_ring, (340, 35), avatar_ring)

        card_img.paste(title, (0, 0), title)

    else:
        _, ck = await waves_api.get_ck_result(uid, ev.user_id, ev.bot_id)
        if not ck:
            return hint.error_reply(WAVES_CODE_102)
        account_info = await waves_api.get_base_info(uid, ck)
        if not account_info.success:
            return account_info.throw_msg()
        if not account_info.data:
            return f"用户未展示数据, 请尝试【{PREFIX}登录】"
        account_info = AccountBaseInfo.model_validate(account_info.data)

        base_info_bg = Image.open(TEXT_PATH / "base_info_bg.png")
        base_info_draw = ImageDraw.Draw(base_info_bg)
        base_info_draw.text((275, 120), f"{account_info.name[:10]}", "white", waves_font_30, "lm")
        base_info_draw.text((226, 173), f"特征码:  {hide_uid(account_info.id, user_pref=user_pref)}", GOLD, waves_font_25, "lm")
        base_info_bg = base_info_bg.resize((900, 450))
        card_img.alpha_composite(base_info_bg, (110, 30))
        #
        card_polygon = await get_random_card_polygon(ev)
        card_img.alpha_composite(card_polygon, (80, 0))
