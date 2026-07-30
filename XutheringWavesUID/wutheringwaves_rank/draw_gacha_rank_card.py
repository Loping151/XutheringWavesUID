import time
import asyncio
from typing import Dict, List, Tuple, Union, Optional
from pathlib import Path

from PIL import Image, ImageDraw

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
    get_waves_bg,
)
from ..utils.database.models import WavesBind, WavesUser
from ..utils.database.waves_user_activity import WavesUserActivity
from ..wutheringwaves_config import PREFIX, WutheringWavesConfig
from ..utils.fonts.waves_fonts import (
    waves_font_18,
    waves_font_20,
    waves_font_28,
    waves_font_34,
    waves_font_58,
)
from ..wutheringwaves_gachalog.draw_gachalogs import get_gacha_stats

TEXT_PATH = Path(__file__).parent / "texture2d"
GACHA_GREEN = (90, 220, 120)


class GachaRankCard:
    """抽卡排行卡片信息"""

    def __init__(self, user_id: str, uid: str, stats: dict):
        self.user_id = user_id
        self.uid = uid
        self.stats = stats
        # 获取角色和武器的抽数
        char_pool = stats.get("角色精准调谐", {})
        weapon_pool = stats.get("武器精准调谐", {})

        # 平均抽数
        self.char_avg = char_pool.get("avg_up", 0) or char_pool.get("avg", 0)
        self.weapon_avg = weapon_pool.get("avg_up", 0) or weapon_pool.get("avg", 0)

        # 总抽数
        self.total_count = char_pool.get("total", 0) + weapon_pool.get("total", 0)

        # 角色/武器金数（含歪到常驻，仅展示用）
        self.char_gold = char_pool.get("char_gold", 0)
        self.weapon_gold = weapon_pool.get("weapon_gold", 0)
        self.gold_total = self.char_gold + self.weapon_gold

        # 限定金数（UP金），加权按每UP期望抽数(角色81/武器54)计
        self.char_up = char_pool.get("up_count", 0)
        self.weapon_up = weapon_pool.get("up_count", 0)

        denominator = 81 * self.char_up + 54 * self.weapon_up
        if denominator > 0:
            self.weighted = (self.char_avg * self.char_up + self.weapon_avg * self.weapon_up) / denominator * 100
        else:
            self.weighted = 1000


async def get_all_gacha_rank_info(
    users: List[WavesBind],
    min_pull: int,
    tokenLimitFlag: bool = False,
    wavesTokenUsersMap: Optional[Dict[Tuple[str, str], str]] = None,
) -> Tuple[List[GachaRankCard], int, int]:
    """获取所有用户的抽卡排行信息，附带未达阈值的人数与其中最高总抽数"""
    rankInfoList = []
    below_count = 0
    below_max = 0

    for user in users:
        if not user.user_id:
            continue

        if not user.uid:
            continue

        for uid in user.uid.split("_"):
            if tokenLimitFlag and wavesTokenUsersMap is not None:
                if (user.user_id, uid) not in wavesTokenUsersMap:
                    continue
            try:
                stats = await get_gacha_stats(uid)
                if not stats:
                    continue

                rankInfo = GachaRankCard(user.user_id, uid, stats)
                if rankInfo.total_count < min_pull:
                    below_count += 1
                    below_max = max(below_max, rankInfo.total_count)
                    continue

                rankInfoList.append(rankInfo)
            except Exception as e:
                logger.debug(f"[鸣潮·唤取排行] 获取 uid={uid} 数据失败: {e}")
                continue

    return rankInfoList, below_count, below_max


async def draw_gacha_rank_card(bot, ev: Event) -> Union[str, bytes]:
    """绘制抽卡排行"""
    # 检查权限配置
    tokenLimitFlag, wavesTokenUsersMap = await get_rank_token_condition(ev)

    # 获取配置的最小抽数阈值
    from ..wutheringwaves_config.gacha_config import get_group_gacha_min

    min_pull = get_group_gacha_min(ev.group_id) or WutheringWavesConfig.get_config("GachaRankMin").data

    # 解析参数以获取排序类型
    text, page = split_rank_page(ev.text or "")
    sort_reverse = False
    sort_gacha_num = False
    if text:
        if "非" in text:
            sort_reverse = True
        elif "欧" in text:
            sort_reverse = False
        elif "抽" in text:
            sort_gacha_num = True

    # 获取群里的所有用户
    users = await WavesBind.get_group_all_uid(ev.group_id)
    if WutheringWavesConfig.get_config("RankActiveFilterGroup").data:
        users = await filter_active_group_users(list(users), ev.bot_id, ev.bot_self_id)
    if not users:
        msg = []
        msg.append(f"[鸣潮] 群【{ev.group_id}】暂无抽卡排行数据")
        msg.append(f"请使用【{PREFIX}导入抽卡记录】后再使用此功能！")
        if tokenLimitFlag:
            msg.append(f"当前排行开启了登录验证，请使用命令【{PREFIX}登录】登录后此功能！")
        return "\n".join(msg)

    rankInfoList, below_count, below_max = await get_all_gacha_rank_info(
        list(users), min_pull, tokenLimitFlag, wavesTokenUsersMap
    )
    if len(rankInfoList) == 0:
        msg = []
        if below_count:
            msg.append(f"[鸣潮] 群【{ev.group_id}】暂无满足条件的抽卡排行数据")
            msg.append(f"已有{below_count}位玩家导入抽卡记录，但总抽数均未达到阈值{min_pull}（当前最高{below_max}）")
            msg.append(f"群管理可使用【{PREFIX}设置抽卡条件{below_max}】调整本群阈值")
        else:
            msg.append(f"[鸣潮] 群【{ev.group_id}】暂无抽卡排行数据")
            msg.append(f"请使用【{PREFIX}导入抽卡记录】后再使用此功能！")
            if tokenLimitFlag:
                msg.append(f"当前排行开启了登录验证，请使用命令【{PREFIX}登录】登录后此功能！")
        return "\n".join(msg)

    # 按加权抽数排序（分数越低越欧，反向排序则是非）
    if sort_gacha_num:
        rankInfoList.sort(key=lambda i: i.total_count, reverse=True)
    else:
        rankInfoList.sort(key=lambda i: i.weighted, reverse=sort_reverse)
    rankInfoList_with_id = list(enumerate(rankInfoList, start=1))

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
                    for rankId, rankInfo in rankInfoList_with_id
                    if rankInfo.uid == self_uid and ev.user_id == rankInfo.user_id
                ),
                (None, None),
            )
    except Exception:
        pass

    display_items, display_rank_ids, page_count, page_item_count = (
        paginate_group_rank(rankInfoList, page, rankId, rankInfo)
    )
    if page_item_count == 0:
        return group_rank_empty_page_message(page, page_count)
    rankInfoList_display = list(zip(display_rank_ids, display_items))

    # 获取头像
    tasks = [
        get_avatar(rank_info.user_id, getattr(rank_info, "sender_avatar", ""))
        for _, rank_info in rankInfoList_display
    ]
    results = await asyncio.gather(*tasks)

    active_filter = WutheringWavesConfig.get_config("RankActiveFilterGroup").data
    if sort_gacha_num:
        mode_label = "·抽数"
    elif sort_reverse:
        mode_label = "·非"
    else:
        mode_label = "·欧"
    _mask_uid = await build_uid_masker([(ri.uid, ri.user_id) for _, ri in rankInfoList_display], ev.bot_id)
    card_img = await _compose_gacha_rank(rankInfoList_display, results, self_uid, min_pull, active_filter, mode_label, _mask_uid)
    card_img = await convert_img(card_img)
    return card_img


@to_thread
def _compose_gacha_rank(rankInfoList_display, results, self_uid, min_pull, active_filter, mode_label: str = "", mask_uid=None):
    width = 1000
    text_bar_height = 130
    item_spacing = 120
    header_height = 510
    footer_height = 50

    total_height = header_height + text_bar_height + item_spacing * len(rankInfoList_display) + footer_height

    card_img = get_waves_bg(width, total_height, "bg9")

    text_bar_img = Image.new("RGBA", (width, 130), color=(0, 0, 0, 0))
    text_bar_draw = ImageDraw.Draw(text_bar_img)
    bar_bg_color = (36, 36, 41, 230)
    text_bar_draw.rounded_rectangle([20, 20, width - 40, 110], radius=8, fill=bar_bg_color)

    accent_color = (203, 161, 95)
    text_bar_draw.rectangle([20, 20, width - 40, 26], fill=accent_color)

    text_bar_draw.text((40, 60), "排行说明", (150, 150, 150), waves_font_28, "lm")
    text_bar_draw.text(
        (185, 50),
        f"1. 仅显示导入总抽数≥{min_pull}且近期活跃的玩家（至少为前6个月的连续记录）" if active_filter else f"1. 仅显示导入总抽数≥{min_pull}的玩家（至少为前6个月的连续记录）",
        SPECIAL_GOLD,
        waves_font_20,
        "lm",
    )
    text_bar_draw.text(
        (185, 85), "2. 加权抽数 = 实际抽数 / (角色数×81 + 武器数×54)，欧非分界线为 100", SPECIAL_GOLD, waves_font_20, "lm"
    )

    card_img.alpha_composite(text_bar_img, (0, header_height))

    title_bg = Image.open(TEXT_PATH / "totalrank.jpg")
    title_bg = title_bg.crop((0, 0, width, 475))

    icon = get_ICON()
    icon = icon.resize((128, 128))
    title_bg.paste(icon, (60, 240), icon)

    title_text = f"#抽卡群排行{mode_label}"
    title_bg_draw = ImageDraw.Draw(title_bg)
    title_bg_draw.text((220, 290), title_text, "white", waves_font_58, "lm")
    time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    title_bg_draw.text((225, 360), time_str, GREY, waves_font_20, "lm")

    char_mask = Image.open(TEXT_PATH / "char_mask.png").convert("RGBA")
    char_mask = char_mask.resize((width, char_mask.height * width // char_mask.width))
    char_mask = char_mask.crop((0, char_mask.height - 475, width, char_mask.height))
    char_mask_temp = Image.new("RGBA", char_mask.size, (0, 0, 0, 0))
    char_mask_temp.paste(title_bg, (0, 0), char_mask)

    card_img.paste(char_mask_temp, (0, 0), char_mask_temp)

    bar = Image.open(TEXT_PATH / "bar2.png")

    def get_stat_color(value: float, low: float, high: float):
        if value > high:
            return RED
        if value < low:
            return GACHA_GREEN
        return "white"

    for rank_temp_index, temp in enumerate(zip(rankInfoList_display, results)):
        rank_id, rankInfo = temp[0]
        role_avatar = temp[1]
        y_pos = header_height + 130 + rank_temp_index * item_spacing

        role_bg = bar.copy()
        role_bg.paste(role_avatar, (100, 0), role_avatar)
        role_bg_draw = ImageDraw.Draw(role_bg)

        draw_rank_badge(role_bg, rank_id)

        role_bg_draw.text(
            (210, 40), f"角色{rankInfo.char_gold}金 武器{rankInfo.weapon_gold}金", "white", waves_font_18, "lm"
        )

        uid_color = "white"
        if rankInfo.uid == self_uid:
            uid_color = RED
        role_bg_draw.text((210, 70), f"{mask_uid(rankInfo.uid, rankInfo.user_id)}", uid_color, waves_font_20, "lm")

        up_color = get_stat_color(rankInfo.char_avg, 76, 86)
        role_bg_draw.text((460, 30), "UP平均", SPECIAL_GOLD, waves_font_20, "mm")
        role_bg_draw.text((460, 70), f"{rankInfo.char_avg:.1f}", up_color, waves_font_28, "mm")

        weapon_color = get_stat_color(rankInfo.weapon_avg, 49, 59)
        role_bg_draw.text((600, 30), "武器平均", SPECIAL_GOLD, waves_font_20, "mm")
        role_bg_draw.text((600, 70), f"{rankInfo.weapon_avg:.1f}", weapon_color, waves_font_28, "mm")

        weighted_color = get_stat_color(rankInfo.weighted, 90, 110)
        role_bg_draw.text((740, 30), "加权", SPECIAL_GOLD, waves_font_20, "mm")
        role_bg_draw.text((740, 70), f"{rankInfo.weighted:.1f}", weighted_color, waves_font_28, "mm")

        role_bg_draw.text((880, 30), "总抽数", SPECIAL_GOLD, waves_font_20, "mm")
        role_bg_draw.text((880, 70), f"{rankInfo.total_count}", "white", waves_font_28, "mm")

        card_img.paste(role_bg, (0, y_pos), role_bg)

    card_img = add_footer(card_img)
    return card_img
