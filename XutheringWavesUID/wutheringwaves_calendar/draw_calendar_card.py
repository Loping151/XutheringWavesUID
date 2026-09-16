import random
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
import re

from PIL import Image, ImageDraw
from PIL.ImageFile import ImageFile

from gsuid_core.models import Event
from gsuid_core.pool import to_thread
from gsuid_core.utils.image.convert import convert_img
from gsuid_core.utils.image.image_tools import crop_center_img

from ..utils.image import (
    SPECIAL_GOLD,
    add_footer,
    get_square_avatar,
    get_square_weapon,
    pic_download_from_url,
)
from .calendar_model import ImageItem, SpecialImages, VersionActivity
from ..utils.waves_api import waves_api
from ..wutheringwaves_up.pool import get_pool_data
from ..wutheringwaves_up.model import WavesPool
from ..utils.ascension.char import get_char_id, get_char_model
from ..utils.ascension.weapon import get_weapon_id, get_weapon_model
from ..utils.fonts.waves_fonts import ww_font_20, ww_font_24, ww_font_30
from ..utils.resource.RESOURCE_PATH import CALENDAR_PATH

TEXT_PATH = Path(__file__).parent / "texture2d"
time_icon = Image.open(TEXT_PATH / "time_icon.png")

# 忆旅唤取会与活动唤取同期开启且四星不同, 不并入卡池栏
POOL_GACHA_TYPE = {
    "角色活动唤取": "角色",
    "角色联动唤取": "角色",
    "武器活动唤取": "武器",
    "武器联动唤取": "武器",
}

_CALENDAR_DATE_PATTERNS = (
    re.compile(r"^(\d{4})(\d{2})(\d{2})\."),  # YYYYMMDD
    re.compile(r"^(\d{2})-(\d{2})-(\d{2})\."),  # YY-MM-DD
)


def _parse_calendar_date(name: str) -> datetime | None:
    for pattern in _CALENDAR_DATE_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue
        y, m, d = map(int, match.groups())
        if pattern is _CALENDAR_DATE_PATTERNS[1]:
            y += 2000
        try:
            return datetime(y, m, d)
        except ValueError:
            return None
    return None


def get_latest_calendar_image(now: datetime) -> Path | None:
    if not CALENDAR_PATH.exists():
        return None

    best_date = None
    best_path = None
    for file_path in CALENDAR_PATH.iterdir():
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
        date = _parse_calendar_date(file_path.name)
        if not date or date >= now:
            continue
        if best_date is None or date > best_date:
            best_date = date
            best_path = file_path
    return best_path


def tower_node(now: datetime):
    start_time = datetime(2025, 2, 3, 4, 0)
    date_range = 86400 * 28  # 28天为一周期（秒）
    # 将秒数转为 timedelta 对象
    date_range_td = timedelta(seconds=date_range)

    # 计算周期编号
    elapsed_time = (now - start_time).total_seconds()  # 当前时间与开始时间的差值（秒）
    period_index = int(elapsed_time // date_range)  # 周期编号（从 0 开始）

    # 当前周期的起始和结束时间
    period_start = start_time + period_index * date_range_td
    period_end = period_start + date_range_td

    start_date_str = period_start.strftime("%Y-%m-%d %H:%M")
    end_date_str = period_end.strftime("%Y-%m-%d %H:%M")

    return {
        "title": "逆境深塔",
        "contentUrl": "tower.png",
        "countDown": {"dateRange": [start_date_str, end_date_str]},
    }


def shenhai_node(now: datetime):
    start_time = datetime(2025, 3, 17, 4, 0)
    date_range = 86400 * 28  # 28天为一周期（秒）
    # 将秒数转为 timedelta 对象
    date_range_td = timedelta(seconds=date_range)

    # 计算周期编号
    elapsed_time = (now - start_time).total_seconds()  # 当前时间与开始时间的差值（秒）
    period_index = int(elapsed_time // date_range)  # 周期编号（从 0 开始）

    # 当前周期的起始和结束时间
    period_start = start_time + period_index * date_range_td
    period_end = period_start + date_range_td

    start_date_str = period_start.strftime("%Y-%m-%d %H:%M")
    end_date_str = period_end.strftime("%Y-%m-%d %H:%M")

    return {
        "title": "冥歌海墟",
        "contentUrl": "shenhai.png",
        "countDown": {"dateRange": [start_date_str, end_date_str]},
    }


def _resolve_gacha_id(name: str, resource_id: str, gacha_type: str):
    if gacha_type == "角色":
        if get_char_model(resource_id):
            return resource_id
        return get_char_id(name, loose=True)
    if get_weapon_model(resource_id):
        return resource_id
    return get_weapon_id(name, loose=True)


async def _build_gacha_node(name: str, resource_id: str, gacha_type: str):
    name = name.replace("-前瞻", "")
    if not name:
        return None
    id = _resolve_gacha_id(name, resource_id, gacha_type)
    if id is None:
        return None
    if gacha_type == "角色":
        pic = await get_square_avatar(id)
    else:
        pic = await get_square_weapon(id)
    return {"name": name, "id": id, "pic": pic.resize((180, 180))}


async def get_gacha_from_pool(now: datetime):
    """从卡池接口取当前 UP, 返回 (角色, 武器); 取不到的一栏留空由 wiki 兜底"""
    pools = await get_pool_data()
    if not pools:
        return [], []

    current = {"角色": [], "武器": []}
    for raw in pools:
        try:
            pool = WavesPool.model_validate(raw)
        except Exception:
            continue
        gacha_type = POOL_GACHA_TYPE.get(pool.pool_type)
        if not gacha_type:
            continue
        try:
            start_time = datetime.strptime(pool.start_time, "%Y-%m-%d %H:%M:%S")
            end_time = datetime.strptime(pool.end_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if not start_time <= now <= end_time:
            continue
        date_range = [start_time.strftime("%Y-%m-%d %H:%M"), end_time.strftime("%Y-%m-%d %H:%M")]
        current[gacha_type].append((pool, date_range))

    result = {}
    for gacha_type, items in current.items():
        res_list = []
        for i, (pool, date_range) in enumerate(items):
            up_list = list(zip(pool.five_star_names, pool.five_star_ids))
            # 四星只挂最后一栏, 对齐 draw_gacha 只取非末栏首个节点的排布
            if i == len(items) - 1:
                up_list += list(zip(pool.four_star_names, pool.four_star_ids))
            tasks = [_build_gacha_node(name, resource_id, gacha_type) for name, resource_id in up_list]
            nodes = await asyncio.gather(*tasks, return_exceptions=True)
            res_list.append(
                {
                    "title": pool.pool_type,
                    "dateRange": date_range,
                    "description": pool.name,
                    "nodes": [node for node in nodes if isinstance(node, dict)],
                }
            )
        result[gacha_type] = res_list

    return result["角色"], result["武器"]


async def draw_calendar_img(ev: Event, uid: str):
    wiki_home = await waves_api.get_wiki_home()
    if not isinstance(wiki_home, dict) or wiki_home.get("code") != 200:
        return "获取日历失败"

    # 当前时间
    now = datetime.now()

    pool_char_list, pool_weapon_list = await get_gacha_from_pool(now)
    gacha_char_list = list(pool_char_list)
    gacha_weapon_list = list(pool_weapon_list)
    content = None
    side_modules = wiki_home.get("data", {}).get("contentJson", {}).get("sideModules", [])
    for side_module in side_modules:
        if side_module["title"] in ("角色活动唤取", "角色联动唤取"):
            if not pool_char_list:
                gacha_char_list += await draw_calendar_gacha(side_module, "角色")

        elif side_module["title"] in ("武器活动唤取", "武器联动唤取"):
            if not pool_weapon_list:
                gacha_weapon_list += await draw_calendar_gacha(side_module, "武器")

        elif side_module["title"] == "版本活动":
            side_module["content"].insert(0, tower_node(now))
            side_module["content"].insert(1, shenhai_node(now))
            content = VersionActivity(**side_module)

    title_high = 150
    banner_high = 550
    bar1_high = 60
    char_bar_high = 150
    star_fg_high = 150
    weapon_bar_high = 150
    bar2_high = 60
    event_high = 170
    temp_high = 20
    footer_high = 70

    content_total_row = 1 + (len(content.content) - 1) // 2 if content else 0
    total_high = title_high + banner_high + temp_high + content_total_row * event_high + bar2_high + footer_high
    # 总高度按角色和武器卡池中行数较多的一栏算 (并排布局), 防武器多于角色时越界裁切 (F3.3)
    max_gacha_len = max(len(gacha_char_list), len(gacha_weapon_list))
    if max_gacha_len:
        total_high += (char_bar_high + star_fg_high * (max_gacha_len + 4) // 2)
        total_high += temp_high
        total_high += bar1_high

    bg = f"bg{random.choice([1, 2])}"
    # banner 图片预加载
    banner_bg_img = await _load_banner_bg(wiki_home)

    # 预加载活动图标
    activity_icons = []
    for cont in content.content if content else []:
        if "http" in cont.contentUrl:
            activity_icons.append(await pic_download_from_url(CALENDAR_PATH, cont.contentUrl))
        else:
            activity_icons.append(None)

    img = await _compose_calendar_img(
        total_high,
        bg,
        banner_bg_img,
        gacha_char_list,
        gacha_weapon_list,
        content,
        activity_icons,
        now,
        title_high,
        banner_high,
        bar1_high,
        char_bar_high,
        weapon_bar_high,
        bar2_high,
        event_high,
        temp_high,
    )

    img = await convert_img(img)
    return img


@to_thread
def _compose_calendar_img(
    total_high,
    bg,
    banner_bg_img,
    gacha_char_list,
    gacha_weapon_list,
    content,
    activity_icons,
    now,
    title_high,
    banner_high,
    bar1_high,
    char_bar_high,
    weapon_bar_high,
    bar2_high,
    event_high,
    temp_high,
) -> Image.Image:
    img = _build_calendar_bg(1200, total_high, bg)
    # title
    title_img = Image.open(TEXT_PATH / "title.png")

    img.paste(title_img, (0, 50), title_img)

    # banner
    _draw_banner_sync(banner_bg_img, img)

    _high = title_high + banner_high
    _max_gacha_height = _high
    # 卡池title
    if gacha_char_list:
        bar1 = Image.open(TEXT_PATH / "bar1.png")
        img.paste(bar1, (0, _max_gacha_height), bar1)
        _max_gacha_height = _high + bar1_high
        char_bar = Image.open(TEXT_PATH / "char_bar_half.png")

        if gacha_char_list[0]["dateRange"]:
            char_bar_draw = ImageDraw.Draw(char_bar)
            dateRange = gacha_char_list[0]["dateRange"]
            status, left, color = get_date_range(dateRange, now)
            if left:
                status = f"{status}: "
                char_bar_draw.text((310, 110), f"{left}", color, ww_font_24, "lm")
            char_bar_draw.text((220, 110), f"{status}", "white", ww_font_24, "lm")

        img.paste(char_bar, (0, _max_gacha_height), char_bar)
        _max_gacha_height += char_bar_high
        _max_gacha_height = draw_gacha(gacha_char_list, img, _max_gacha_height)

    if gacha_weapon_list:
        weapon_bar: ImageFile = Image.open(TEXT_PATH / "weapon_bar_half.png")
        _high = _high + bar1_high
        if gacha_weapon_list[0]["dateRange"]:
            weapon_bar_draw = ImageDraw.Draw(weapon_bar)
            dateRange = gacha_weapon_list[0]["dateRange"]
            status, left, color = get_date_range(dateRange, now)
            if left:
                status = f"{status}: "
                weapon_bar_draw.text((310-83, 110), f"{left}", color, ww_font_24, "lm")
            weapon_bar_draw.text((210-83, 110), f"{status}", "white", ww_font_24, "lm")

        img.paste(weapon_bar, (600, _high), weapon_bar)
        _high += weapon_bar_high
        _high = draw_gacha(gacha_weapon_list, img, _high, x_shift=517)
        _max_gacha_height = max(_max_gacha_height, _high)

    _high = _max_gacha_height

    # 活动bar
    _high += temp_high
    bar2 = Image.open(TEXT_PATH / "bar2.png")

    img.paste(bar2, (0, _high), bar2)
    _high += bar2_high
    for i, cont in enumerate(content.content if content else []):  # type: ignore
        event_bg = Image.open(TEXT_PATH / "event_bg.png")
        event_bg_draw = ImageDraw.Draw(event_bg)
        dateRange = []
        if cont.countDown:
            dateRange = cont.countDown.dateRange

        if dateRange and len(dateRange) == 2 and dateRange[0] and dateRange[1]:
            start_time = datetime.strptime(dateRange[0], "%Y-%m-%d %H:%M")
            end_time = datetime.strptime(dateRange[1], "%Y-%m-%d %H:%M")

            status, left, color = get_date_range(dateRange, now)
            if left:
                event_bg_draw.text((260, 130), f"{left}", color, ww_font_20, "lm")
                status = f"{status}: "

            # 格式化
            formatted_start = start_time.strftime("%m.%d %H:%M")
            formatted_end = end_time.strftime("%m.%d %H:%M")

            # 起止时间
            formatted_date_range = f"{formatted_start} ~ {formatted_end}"
            event_bg_draw.text((160, 95), f"{formatted_date_range}", "white", ww_font_20, "lm")
            # 时间小图标
            event_bg.alpha_composite(time_icon, (155, 115))
            # 状态
            event_bg_draw.text((190, 130), f"{status}", "white", ww_font_20, "lm")

            # 添加进度条
            progress_x = 25
            progress_y = 155
            progress_width = 485
            progress_height = 8

            # 计算进度百分比
            if status == "已结束":
                # 已结束
                progress = 1
                fill_color = "white"
            else:
                # 进行中
                total_duration = (end_time - start_time).total_seconds()
                elapsed_duration = (now - start_time).total_seconds()
                progress = elapsed_duration / total_duration if total_duration > 0 else 0
                fill_color = "gold" if color == "white" else color

            # 绘制进度条背景
            event_bg_draw.rectangle(
                [
                    progress_x,
                    progress_y,
                    progress_x + progress_width,
                    progress_y + progress_height,
                ],
                fill=(100, 100, 100),  # 灰色背景
            )

            # 绘制进度条前景
            if progress > 0:
                progress_fill_width = int(progress_width * progress)

                event_bg_draw.rectangle(
                    [
                        progress_x,
                        progress_y,
                        progress_x + progress_fill_width,
                        progress_y + progress_height,
                    ],
                    fill=fill_color,
                )

        if "http" in cont.contentUrl:
            linkUrl = activity_icons[i]
        else:
            linkUrl = Image.open(TEXT_PATH / cont.contentUrl)
        if linkUrl is None:
            continue
        linkUrl = linkUrl.resize((100, 100))  # type: ignore
        event_bg.paste(linkUrl, (40, 40), linkUrl)
        event_bg_draw.text((160, 60), f"{cont.title}", SPECIAL_GOLD, ww_font_30, "lm")

        img.alpha_composite(event_bg, (70 + (i % 2) * 540, _high))
        if i % 2 == 1:
            _high += event_high

    img = add_footer(img)

    kuro_calendar_path = get_latest_calendar_image(now)
    if kuro_calendar_path is None:
        kuro_calendar_path = CALENDAR_PATH / "calendar.png"
    if kuro_calendar_path.exists():
        try:
            custom_calendar = Image.open(kuro_calendar_path).convert("RGBA")
            calendar_width = int(custom_calendar.width * img.height / custom_calendar.height)
            custom_calendar = custom_calendar.resize((calendar_width, img.height), Image.Resampling.LANCZOS)

            new_img = Image.new("RGBA", (img.width + custom_calendar.width, img.height), (255, 255, 255, 0))
            new_img.paste(img, (0, 0))
            new_img.paste(custom_calendar, (img.width, 0), custom_calendar)
            img = new_img
        except Exception:
            pass

    return img


async def draw_calendar_gacha(side_module, gacha_type):
    res_list = []
    tabs = side_module["content"]["tabs"]

    for tab in tabs:
        try:
            special_images = SpecialImages.model_validate(tab)
        except Exception as _:
            continue
        res = {
            "title": side_module["title"],
            "dateRange": tab["countDown"]["dateRange"],
            "description": tab["name"],
            "nodes": [],
        }

        async def process_item(img_item: ImageItem, special_images: SpecialImages):
            if img_item.linkConfig.linkType == 1:
                item_detail = await get_unsafe_entry_detail(img_item.linkConfig.entryId)
                if not item_detail:
                    return None
                if item_detail["code"] != 200:
                    return None

                name = item_detail["data"]["name"]
            else:
                name = special_images.name

            name = name.replace("-前瞻", "")
            if not name:
                return None

            if gacha_type == "角色":
                id = get_char_id(name, loose=True)
                if id is None:
                    return None
                pic = await get_square_avatar(id)
            else:
                id = get_weapon_id(name)
                if id is None:
                    return None
                pic = await get_square_weapon(id)

            pic = pic.resize((180, 180))
            return {"name": name, "id": id, "pic": pic}

        tasks = [process_item(img_item, special_images) for img_item in special_images.imgs]
        nodes = await asyncio.gather(*tasks, return_exceptions=True)

        res["nodes"].extend(filter(None, nodes))
        res_list.append(res)

    return res_list


async def _load_banner_bg(wiki_home):
    banners = wiki_home.get("data", {}).get("contentJson", {}).get("banner", [])
    if not banners:
        return None
    banner_bg = banners[0]["url"]
    for banner in banners:
        if "版本PV" in banner["describe"]:
            banner_bg = banner["url"]
            break
        elif "版本" in banner["describe"]:
            banner_bg = banner["url"]
            break

    return await pic_download_from_url(CALENDAR_PATH, banner_bg)


def _draw_banner_sync(banner_bg, img):
    if banner_bg is None:
        return
    banner_bg = banner_bg.resize((1200, 675))  # type: ignore
    banner_mask = Image.open(TEXT_PATH / "banner_mask.png")
    banner_bg = crop_center_img(banner_bg, banner_mask.size[0], banner_mask.size[1])

    banner_bg_temp = Image.new("RGBA", banner_mask.size, (255, 255, 255, 0))
    banner_bg_temp.paste(banner_bg, (0, 0), banner_mask)
    banner_frame_img = Image.open(TEXT_PATH / "banner_frame.png")

    img.paste(banner_bg, (0, 150), banner_mask)
    img.paste(banner_frame_img, (0, 150), banner_frame_img)


# 兼容旧调用入口（如有其他模块直接使用）
async def draw_banner(wiki_home, img):
    banner_bg = await _load_banner_bg(wiki_home)
    _draw_banner_sync(banner_bg, img)


def _build_calendar_bg(w: int, h: int, bg: str = "bg1") -> Image.Image:
    img = Image.open(TEXT_PATH / f"{bg}.jpg").convert("RGBA")
    return crop_center_img(img, w, h)


async def get_calendar_bg(w: int, h: int, bg: str = "bg1") -> Image.Image:
    return _build_calendar_bg(w, h, bg)


def draw_gacha(gacha_list, img, _high, x_shift = 0):
    star_fg_high = 150
    if not gacha_list:
        return _high
    all_nodes = [gacha["nodes"][0] for gacha in gacha_list[:-1] if gacha.get("nodes")] + (gacha_list[-1].get("nodes") or [])
    if not all_nodes:
        return _high
    gacha_nodes = [all_nodes[i:i+2] for i in range(0, len(all_nodes), 2)]
    # for i, gacha_list in enumerate(gacha_list):
    for i, gacha_list in enumerate(gacha_nodes):
        gacha_bg = Image.new("RGBA", (1200, star_fg_high), (0, 0, 0, 0))
        # for j, gacha in enumerate(gacha_list["nodes"]):
        for j, gacha in enumerate(gacha_list):
            if 2 * i + j < len(all_nodes) - 3:
                star_fg = Image.open(TEXT_PATH / "star5_fg.png")
                star_bg = Image.open(TEXT_PATH / "star5_bg.png")
            else:
                star_fg = Image.open(TEXT_PATH / "star4_fg.png")
                star_bg = Image.open(TEXT_PATH / "star4_bg.png")

            star_bg_temp = Image.new("RGBA", star_bg.size)
            star_bg_temp.paste(star_bg, (0, 0))
            star_bg_temp.alpha_composite(gacha["pic"], (80, -10))

            gacha_name = gacha["name"]
            if len(gacha_name) <= 2:
                name_bg = Image.new("RGBA", (60, 25), color=(255, 255, 255, 0))
                rank_draw = ImageDraw.Draw(name_bg)
                rank_draw.rectangle([0, 0, 60, 25], fill=(255, 255, 255) + (int(0.9 * 255),))
                rank_draw.text((30, 12), f"{gacha_name}", "black", ww_font_20, "mm")
            else:
                name_bg = Image.new("RGBA", (10 + 20 * len(gacha_name), 25), color=(255, 255, 255, 0))
                rank_draw = ImageDraw.Draw(name_bg)
                rank_draw.rectangle([0, 0, 10 + 20 * len(gacha_name), 25], fill=(255, 255, 255) + (int(0.9 * 255),))
                rank_draw.text((5 + 10 * len(gacha_name), 12), f"{gacha_name}", "black", ww_font_20, "mm")

            gacha_bg.paste(star_bg_temp, (80 + j * 260, 0))
            gacha_bg.alpha_composite(star_fg, (80 + j * 260, 0))
            gacha_bg.alpha_composite(name_bg, (90 + j * 260, 110))

        img.alpha_composite(gacha_bg, (x_shift, _high))
        _high += star_fg_high
    return _high


def get_left_time_str(remaining_time):
    # 提取天数、小时数和分钟数
    remaining_days = remaining_time.days
    remaining_hours, remaining_minutes = divmod(remaining_time.seconds, 3600)
    remaining_minutes, remaining_seconds = divmod(remaining_minutes, 60)
    # 剩余时间
    return f"还剩{remaining_days}天{remaining_hours}小时{remaining_minutes}分钟"


def get_date_range(dateRange, now):
    start_time = datetime.strptime(dateRange[0], "%Y-%m-%d %H:%M")
    end_time = datetime.strptime(dateRange[1], "%Y-%m-%d %H:%M")
    left = ""
    color = "white"
    if start_time <= now <= end_time:
        # 进行中
        status = "进行中"
        if end_time >= now:
            remaining_time = end_time - now
            left = get_left_time_str(remaining_time)
            if remaining_time.days <= 3:
                color = "red"
    elif now > end_time:
        # 已结束
        status = "已结束"
    else:
        # 未开始
        status = "未开始"

    return status, left, color


cache = {}


async def get_unsafe_entry_detail(entryId):
    if entryId in cache:
        return cache[entryId]
    item_detail = await waves_api.get_entry_detail(entryId)
    if item_detail["code"] != 200:
        return None

    cache[entryId] = item_detail
    return item_detail
