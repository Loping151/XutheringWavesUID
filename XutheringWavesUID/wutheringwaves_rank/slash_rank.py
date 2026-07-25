import time
import asyncio
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from datetime import datetime, timezone, timedelta

import httpx
from PIL import Image, ImageDraw

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img

from ..utils.util import get_version, hide_uid, build_uid_masker
from ..utils.player_store import read_player_json
from ..utils.image import (
    RED,
    GREY,
    CHAIN_COLOR,
    get_ICON,
    add_footer,
    get_waves_bg,
    get_square_avatar,
    pic_download_from_url,
)
from .rank_badge import draw_bot_name_badge, draw_rank_badge
from .pagination import (
    RANK_PAGE_SIZE,
    group_rank_empty_page_message,
    paginate_group_rank,
)
from ..utils.api.model import SlashDetail
from ..utils.api.wwapi import (
    GET_SLASH_RANK_URL,
    SlashRank,
    SlashRankRes,
    SlashRankItem,
)
from ..utils.ascension.char import get_char_model
from ..utils.database.models import WavesBind, WavesUser
from ..utils.resource.constant import SPECIAL_CHAR_INT_ALL, NORMAL_LIST_IDS, randomize_special_char_id
from ..wutheringwaves_config import PREFIX, WutheringWavesConfig
from ..utils.fonts.waves_fonts import (
    fit_text,
    waves_font_12,
    waves_font_14,
    waves_font_16,
    waves_font_18,
    waves_font_20,
    waves_font_34,
    waves_font_44,
    waves_font_58,
)
from ..wutheringwaves_abyss.period import (
    SLASH_BASE_TIMESTAMP,
    get_slash_period_number,
    is_slash_record_expired,
    parse_rank_date,
)
from ..utils.resource.RESOURCE_PATH import SLASH_PATH
from ..wutheringwaves_abyss.draw_slash_card import COLOR_QUALITY


async def get_endless_rank_token_condition(ev) -> Tuple[bool, Dict[Tuple[str, str], str]]:
    """检查无尽排行的权限配置，并返回登录用户映射"""
    tokenLimitFlag = False
    wavesTokenUsersMap: Dict[Tuple[str, str], str] = {}

    # 群组 不限制token
    WavesRankNoLimitGroup = WutheringWavesConfig.get_config("WavesRankNoLimitGroup").data
    if ev.group_id and WavesRankNoLimitGroup and ev.group_id in WavesRankNoLimitGroup:
        return tokenLimitFlag, wavesTokenUsersMap

    # 群组 自定义的 + 全局 主人定义的
    WavesRankUseTokenGroup = WutheringWavesConfig.get_config("WavesRankUseTokenGroup").data
    RankUseToken = WutheringWavesConfig.get_config("RankUseToken").data
    if (ev.group_id and WavesRankUseTokenGroup and ev.group_id in WavesRankUseTokenGroup) or RankUseToken:
        wavesTokenUsers = await WavesUser.get_waves_all_user()
        wavesTokenUsersMap = {(w.user_id, w.uid): w.cookie for w in wavesTokenUsers}
        tokenLimitFlag = True

    return tokenLimitFlag, wavesTokenUsersMap


TEXT_PATH = Path(__file__).parent / "texture2d"

CHINA_TZ = timezone(timedelta(hours=8))


from ._colors import (
    get_slash_local_rank_color as get_local_score_color,
    get_slash_total_rank_color as get_score_color,
)


async def get_rank(item: SlashRankItem) -> Optional[SlashRankRes]:
    WavesToken = WutheringWavesConfig.get_config("WavesToken").data

    if not WavesToken:
        return

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                GET_SLASH_RANK_URL,
                json=item.model_dump(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {WavesToken}",
                },
                timeout=httpx.Timeout(10),
            )
            if res.status_code == 200:
                return SlashRankRes.model_validate(res.json())
            else:
                logger.warning(f"[鸣潮·冥海排行] 获取远端排行失败: {res.status_code} - {res.text}")
        except Exception as e:
            logger.exception(f"[鸣潮·冥海排行] 获取远端排行失败: {e}")


def is_limited_5star(char_id: int) -> bool:
    """限定五星: 排除常驻/漂泊者/四星。金数 = 链数 + 1。"""
    if char_id in SPECIAL_CHAR_INT_ALL or char_id in NORMAL_LIST_IDS:
        return False
    char_model = get_char_model(char_id)
    return bool(char_model and char_model.starLevel == 5)


# TODO: PIL 卸到线程池 (loop 内 await get_square_avatar / pic_download_from_url 较多, 需要批量预取重构)
async def draw_all_slash_rank_card(bot: Bot, ev: Event, page: int = 1):
    waves_id = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    page_num = RANK_PAGE_SIZE
    item = SlashRankItem(
        page=page,
        page_num=page_num,
        waves_id=waves_id or "",
        version=get_version(dynamic=True, waves_id=waves_id or "", pages=page),
    )

    rankInfoList = await get_rank(item)
    if not rankInfoList:
        return "获取排行失败"

    if rankInfoList.message and not rankInfoList.data:
        return rankInfoList.message

    if not rankInfoList.data or not rankInfoList.data.rank_list:
        return "暂无排行数据"

    # 设置图像尺寸
    width = 1300
    item_spacing = 120
    header_height = 510
    footer_height = 50
    char_list_len = len(rankInfoList.data.rank_list)

    # 计算所需的总高度
    total_height = header_height + item_spacing * char_list_len + footer_height

    # 创建带背景的画布 - 使用bg9
    card_img = get_waves_bg(width, total_height, "bg9")

    # title
    title_bg = Image.open(TEXT_PATH / "slash.jpg")
    title_bg = title_bg.crop((0, 0, width, 500))

    # icon
    icon = get_ICON()
    icon = icon.resize((128, 128))
    title_bg.paste(icon, (60, 240), icon)

    # title
    title_text = "#无尽总排行"
    title_bg_draw = ImageDraw.Draw(title_bg)
    title_bg_draw.text((220, 290), title_text, "white", waves_font_58, "lm")
    period_label = None
    if rankInfoList.data and rankInfoList.data.start_date:
        rank_dt = parse_rank_date(rankInfoList.data.start_date)
        if rank_dt:
            period_label = f"第{get_slash_period_number(rank_dt)}期"
    date_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    if period_label:
        period_pos = (225, 360)
        title_bg_draw.text(period_pos, period_label, GREY, waves_font_20, "lm")
        try:
            period_width = title_bg_draw.textlength(period_label, font=waves_font_20)
        except Exception:
            period_width = waves_font_20.getsize(period_label)[0]
        title_bg_draw.text(
            (period_pos[0] + period_width + 16, period_pos[1]),
            date_text,
            GREY,
            waves_font_20,
            "lm",
        )
    else:
        title_bg_draw.text((225, 360), date_text, GREY, waves_font_20, "lm")

    # 遮罩
    char_mask = Image.open(TEXT_PATH / "char_mask.png").convert("RGBA")
    # 根据width扩图
    char_mask = char_mask.resize((width, char_mask.height * width // char_mask.width))
    char_mask = char_mask.crop((0, char_mask.height - 500, width, char_mask.height))
    char_mask_temp = Image.new("RGBA", char_mask.size, (0, 0, 0, 0))
    char_mask_temp.paste(title_bg, (0, 0), char_mask)

    card_img.paste(char_mask_temp, (0, 0), char_mask_temp)

    rank_list = rankInfoList.data.rank_list
    tasks = [get_avatar(rank.user_id, getattr(rank, "sender_avatar", "")) for rank in rank_list]
    results = await asyncio.gather(*tasks)

    for rank_temp_index, temp in enumerate(zip(rank_list, results)):
        rank_temp: SlashRank = temp[0]
        role_avatar: Image.Image = temp[1]
        role_bg = Image.open(TEXT_PATH / "bar1.png")
        # role_bg = Image.new("RGBA", (width, info_h), (255, 255, 255, 0))
        role_bg.paste(role_avatar, (100, 0), role_avatar)
        role_bg_draw = ImageDraw.Draw(role_bg)

        # 添加排名显示
        rank_id = rank_temp.rank
        draw_rank_badge(role_bg, rank_id)

        # 名字
        name_font, name_text = fit_text(
            role_bg_draw,
            str(rank_temp.kuro_name),
            130,
            (waves_font_20, waves_font_18, waves_font_16, waves_font_14, waves_font_12),
        )
        role_bg_draw.text((210, 75), name_text, "white", name_font, "lm")

        # uid
        uid_color = "white"
        if rank_temp.waves_id == item.waves_id:
            uid_color = RED
        role_bg_draw.text((350, 40), f"特征码: {hide_uid(rank_temp.waves_id, user_pref='on' if rank_temp.hide_uid else '')}", uid_color, waves_font_20, "lm")

        # bot主人名字
        botName = rank_temp.alias_name if rank_temp.alias_name else ""
        if botName:
            draw_bot_name_badge(role_bg, getattr(rank_temp, "background", ""), botName, (346, 61))

        # 总分数
        role_bg_draw.text(
            (1140, 55),
            f"{rank_temp.score}",
            get_score_color(rank_temp.score),
            waves_font_44,
            "mm",
        )

        char_gold_total = sum(
            cd.chain + 1
            for sh in rank_temp.half_list
            for cd in sh.char_detail
            if cd.chain >= 0 and is_limited_5star(cd.char_id)
        )
        role_bg_draw.text((210, 40), f"角色限定{char_gold_total}金", "white", waves_font_18, "lm")

        for half_index, slash_half in enumerate(rank_temp.half_list):
            for role_index, char_detail in enumerate(slash_half.char_detail):
                char_id = char_detail.char_id
                # char_level = char_detail.level
                char_chain = char_detail.chain

                char_id = randomize_special_char_id(char_id)
                char_model = get_char_model(char_id)
                if char_model is None:
                    continue
                char_avatar = await get_square_avatar(char_id)
                char_avatar = char_avatar.resize((45, 45))

                if char_chain != -1:
                    info_block = Image.new("RGBA", (20, 20), color=(255, 255, 255, 0))
                    info_block_draw = ImageDraw.Draw(info_block)
                    info_block_draw.rectangle([0, 0, 20, 20], fill=CHAIN_COLOR[char_chain] + (int(0.9 * 255),))
                    info_block_draw.text(
                        (8, 8),
                        f"{char_chain}",
                        "white",
                        waves_font_12,
                        "mm",
                    )
                    char_avatar.paste(info_block, (30, 30), info_block)

                role_bg.alpha_composite(char_avatar, (570 + half_index * 250 + role_index * 50, 20))

            # buff
            buff_bg = Image.new("RGBA", (50, 50), (255, 255, 255, 0))
            buff_bg_draw = ImageDraw.Draw(buff_bg)
            buff_bg_draw.rounded_rectangle(
                [0, 0, 50, 50],
                radius=5,
                fill=(0, 0, 0, int(0.8 * 255)),
            )
            buff_color = COLOR_QUALITY[slash_half.buff_quality]
            buff_bg_draw.rectangle(
                [0, 45, 50, 50],
                fill=buff_color,
            )
            buff_pic = await pic_download_from_url(SLASH_PATH, slash_half.buff_icon)
            buff_pic = buff_pic.resize((50, 50))
            buff_bg.paste(buff_pic, (0, 0), buff_pic)

            role_bg.alpha_composite(buff_bg, (720 + half_index * 250, 15))

            # 分数
            role_bg_draw.text(
                (670 + half_index * 250, 80),
                f"{slash_half.score}",
                get_score_color(slash_half.score),
                waves_font_20,
                "mm",
            )

        card_img.paste(role_bg, (0, 510 + rank_temp_index * item_spacing), role_bg)

    card_img = add_footer(card_img)
    card_img = await convert_img(card_img)
    return card_img


from .rank_avatar import get_avatar


class SlashRankListInfo:
    """无尽排行信息"""

    def __init__(self, user_id: str, uid: str, slash_data: Optional[SlashDetail] = None):
        self.user_id = user_id
        self.uid = uid
        self.slash_data = slash_data
        self.score = 0

        if slash_data and slash_data.difficultyList:
            # 获取难度12的分数
            difficulty_12 = next((k for k in slash_data.difficultyList if k.difficulty == 2), None)
            if difficulty_12:
                challenge = next(
                    (c for c in difficulty_12.challengeList if c.challengeId == 12),
                    None,
                )
                if challenge and challenge.halfList:
                    # 计算总分数
                    self.score = sum(half.score for half in challenge.halfList)


async def get_all_slash_rank_info(
    users: List[WavesBind],
    tokenLimitFlag: bool = False,
    wavesTokenUsersMap: Optional[Dict[Tuple[str, str], str]] = None,
) -> List[SlashRankListInfo]:
    """从本地获取所有用户的无尽排行信息"""
    from ..utils.resource.RESOURCE_PATH import PLAYER_PATH

    rankInfoList = []

    for user in users:
        if not user.uid:
            continue

        # 处理多个uid（用下划线连接）
        for uid in user.uid.split("_"):
            if tokenLimitFlag and wavesTokenUsersMap is not None:
                if (user.user_id, uid) not in wavesTokenUsersMap:
                    continue
            # 从本地读取该用户的无尽数据
            try:
                slash_data_path = PLAYER_PATH / uid / "slashData.json"
                slash_raw = await read_player_json(slash_data_path)
                if slash_raw is None:
                    continue

                record_time = None
                slash_data = slash_raw
                if isinstance(slash_raw, dict) and "slash_data" in slash_raw:
                    record_time = slash_raw.get("record_time", SLASH_BASE_TIMESTAMP)
                    slash_data = slash_raw.get("slash_data")

                if not isinstance(slash_data, dict) or not slash_data:
                    continue

                if is_slash_record_expired(record_time):
                    logger.debug(f"[鸣潮·冥海排行] 用户 uid={uid} 数据已过期, 跳过")
                    continue

                if not slash_data.get("isUnlock", False):
                    continue

                slash_data = SlashDetail.model_validate(slash_data)

                rankInfo = SlashRankListInfo(user.user_id, uid, slash_data)
                if rankInfo.score > 0:
                    rankInfoList.append(rankInfo)
            except Exception as e:
                logger.debug(f"[鸣潮·冥海排行] 获取 uid={uid} 本地数据失败: {e}")
                continue

    return rankInfoList


async def get_role_chain_count(uid: str, role_id: int) -> int:
    """获取角色共鸣链数量, 漂泊者走 rover.json"""
    from ..utils.resource.RESOURCE_PATH import PLAYER_PATH
    from ..utils.resource.constant import SPECIAL_CHAR, SPECIAL_CHAR_RANK_MAP
    from ..utils.char_info_utils import get_rover_detail_map

    try:
        if str(role_id) in SPECIAL_CHAR:
            temp = (await get_rover_detail_map(uid)).get(SPECIAL_CHAR_RANK_MAP[str(role_id)])
            return temp.get_chain_num() if temp else -1

        raw_data = await read_player_json(PLAYER_PATH / str(uid) / "rawData.json")
        if raw_data is None:
            return -1
        if isinstance(raw_data, list):
            for role_data in raw_data:
                if role_data.get("role", {}).get("roleId") == role_id:
                    return len([c for c in role_data.get("chainList", []) if c.get("unlocked", False)])
        return -1
    except Exception as e:
        logger.debug(f"[鸣潮·冥海排行] 获取角色 roleId={role_id} 共鸣链失败: {e}")
        return -1


async def get_five_star_chain_total(uid: str) -> int:
    """计算五星角色的金数（0链=1金，6链=7金，即链数+1）"""
    from ..utils.resource.RESOURCE_PATH import PLAYER_PATH

    try:
        raw_data_path = PLAYER_PATH / str(uid) / "rawData.json"
        raw_data = await read_player_json(raw_data_path)
        if raw_data is None:
            return 0

        total_gold = 0
        if isinstance(raw_data, list):
            for role_data in raw_data:
                role_id = role_data.get("role", {}).get("roleId")
                if role_id:
                    char_model = get_char_model(role_id)
                    # 检查是否是五星角色
                    if char_model and char_model.starLevel == 5:
                        chain_list = role_data.get("chainList", [])
                        unlocked_chains = [c for c in chain_list if c.get("unlocked", False)]
                        # 金数 = 共鸣链数 + 1
                        total_gold += len(unlocked_chains) + 1
        return total_gold
    except Exception as e:
        logger.debug(f"[鸣潮·冥海排行] 计算五星角色金数失败: {e}")
        return 0


# TODO: PIL 卸到线程池 (loop 内 await get_role_chain_count / get_square_avatar / pic_download_from_url 频繁, 需要批量预取重构)
async def draw_slash_rank_list(bot: Bot, ev: Event, page: int = 1):
    """绘制无尽排行"""
    start_time = time.time()
    logger.info(f"[鸣潮·冥海排行] 群排行 start: {start_time}")

    # 检查权限配置
    tokenLimitFlag, wavesTokenUsersMap = await get_endless_rank_token_condition(ev)

    # 获取群里的所有用户
    users = await WavesBind.get_group_all_uid(ev.group_id)
    if not users:
        msg = []
        msg.append(f"[鸣潮] 群【{ev.group_id}】暂无无尽排行数据")
        msg.append(f"请使用【{PREFIX}无尽】后再使用此功能！")
        if tokenLimitFlag:
            msg.append(f"当前排行开启了登录验证，请使用命令【{PREFIX}登录】登录后此功能！")
        msg.append("")
        return "\n".join(msg)

    rankInfoList = await get_all_slash_rank_info(list(users), tokenLimitFlag, wavesTokenUsersMap)
    if len(rankInfoList) == 0:
        msg = []
        msg.append(f"[鸣潮] 群【{ev.group_id}】暂无无尽排行数据")
        msg.append(f"请使用【{PREFIX}无尽】后再使用此功能！")
        if tokenLimitFlag:
            msg.append(f"当前排行开启了登录验证，请使用命令【{PREFIX}登录】登录后此功能！")
        msg.append("")
        return "\n".join(msg)

    # 按分数排序
    rankInfoList.sort(key=lambda i: i.score, reverse=True)

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
                    for rankId, rankInfo in enumerate(rankInfoList, start=1)
                    if rankInfo.uid == self_uid and ev.user_id == rankInfo.user_id
                ),
                (None, None),
            )
    except Exception as _:
        pass

    rankInfoList_display, display_rank_ids, page_count, page_item_count = (
        paginate_group_rank(rankInfoList, page, rankId, rankInfo)
    )
    if page_item_count == 0:
        return group_rank_empty_page_message(page, page_count)

    _mask_uid = await build_uid_masker([(ri.uid, ri.user_id) for ri in rankInfoList_display], ev.bot_id)

    # 设置图像尺寸
    width = 1000
    item_spacing = 120
    header_height = 510
    footer_height = 50

    # 计算所需的总高度
    total_height = header_height + item_spacing * len(rankInfoList_display) + footer_height

    # 创建带背景的画布
    card_img = get_waves_bg(width, total_height, "bg9")

    # title
    title_bg = Image.open(TEXT_PATH / "slash.jpg")
    title_bg = title_bg.crop((0, 0, width, 475))

    # icon
    icon = get_ICON()
    icon = icon.resize((128, 128))
    title_bg.paste(icon, (60, 240), icon)

    # title
    title_text = "#无尽群排行"
    title_bg_draw = ImageDraw.Draw(title_bg)
    title_bg_draw.text((220, 290), title_text, "white", waves_font_58, "lm")
    period_label = f"第{get_slash_period_number()}期"
    title_bg_draw.text((225, 360), period_label, GREY, waves_font_20, "lm")
    date_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    try:
        period_width = title_bg_draw.textlength(period_label, font=waves_font_20)
    except Exception:
        period_width = waves_font_20.getsize(period_label)[0]
    title_bg_draw.text((225 + period_width + 16, 360), date_text, GREY, waves_font_20, "lm")

    # 遮罩
    char_mask = Image.open(TEXT_PATH / "char_mask.png").convert("RGBA")
    # 根据width扩图
    char_mask = char_mask.resize((width, char_mask.height * width // char_mask.width))
    char_mask = char_mask.crop((0, char_mask.height - 475, width, char_mask.height))
    char_mask_temp = Image.new("RGBA", char_mask.size, (0, 0, 0, 0))
    char_mask_temp.paste(title_bg, (0, 0), char_mask)

    card_img.paste(char_mask_temp, (0, 0), char_mask_temp)

    # 获取头像
    tasks = [
        get_avatar(rank.user_id, getattr(rank, "sender_avatar", ""))
        for rank in rankInfoList_display
    ]
    results = await asyncio.gather(*tasks)

    # 绘制排行条目
    bar = Image.open(TEXT_PATH / "bar2.png")

    for rank_temp_index, temp in enumerate(zip(rankInfoList_display, results)):
        rankInfo = temp[0]
        role_avatar = temp[1]
        role_bg = bar.copy()
        role_bg.paste(role_avatar, (100, 0), role_avatar)
        role_bg_draw = ImageDraw.Draw(role_bg)

        # 排名
        rank_id = display_rank_ids[rank_temp_index]
        draw_rank_badge(role_bg, rank_id)

        char_gold_total = 0
        if rankInfo.slash_data and rankInfo.slash_data.difficultyList:
            difficulty_12 = next((k for k in rankInfo.slash_data.difficultyList if k.difficulty == 2), None)
            if difficulty_12:
                challenge = next(
                    (c for c in difficulty_12.challengeList if c.challengeId == 12),
                    None,
                )
                if challenge and challenge.halfList:
                    for slash_half in challenge.halfList:
                        for slash_role in slash_half.roleList:
                            if not is_limited_5star(slash_role.roleId):
                                continue
                            chain_count = await get_role_chain_count(rankInfo.uid, slash_role.roleId)
                            if chain_count >= 0:
                                char_gold_total += chain_count + 1

        role_bg_draw.text((210, 40), f"角色限定{char_gold_total}金", "white", waves_font_18, "lm")

        # 特征码（白色UID）
        uid_color = "white"
        if rankInfo.uid == self_uid:
            uid_color = RED
        role_bg_draw.text((210, 70), f"{_mask_uid(rankInfo.uid, rankInfo.user_id)}", uid_color, waves_font_20, "lm")

        # 总分数 (左移5px)
        role_bg_draw.text(
            (875, 55),
            f"{rankInfo.score}",
            get_local_score_color(rankInfo.score),
            waves_font_44,
            "mm",
        )

        # 绘制角色和信物信息
        if rankInfo.slash_data and rankInfo.slash_data.difficultyList:
            # 获取难度12的数据
            difficulty_12 = next((k for k in rankInfo.slash_data.difficultyList if k.difficulty == 2), None)
            if difficulty_12:
                challenge = next(
                    (c for c in difficulty_12.challengeList if c.challengeId == 12),
                    None,
                )
                if challenge and challenge.halfList:
                    for half_index, slash_half in enumerate(challenge.halfList):
                        # 绘制角色信息
                        for role_index, slash_role in enumerate(slash_half.roleList):
                            try:
                                char_avatar = await get_square_avatar(slash_role.roleId)
                                char_avatar = char_avatar.resize((45, 45))

                                # 获取角色共鸣链
                                chain_count = await get_role_chain_count(rankInfo.uid, slash_role.roleId)
                                if chain_count != -1:
                                    info_block = Image.new("RGBA", (20, 20), color=(255, 255, 255, 0))
                                    info_block_draw = ImageDraw.Draw(info_block)
                                    info_block_draw.rectangle([0, 0, 20, 20], fill=CHAIN_COLOR[chain_count] + (int(0.9 * 255),))
                                    info_block_draw.text(
                                        (8, 8),
                                        f"{chain_count}",
                                        "white",
                                        waves_font_12,
                                        "mm",
                                    )
                                    char_avatar.paste(info_block, (30, 30), info_block)

                                role_bg.alpha_composite(
                                    char_avatar,
                                    (350 + half_index * 235 + role_index * 50, 20),
                                )
                            except Exception as e:
                                logger.debug(f"[鸣潮·冥海排行] 绘制角色 roleId={slash_role.roleId} 失败: {e}")

                        # 绘制信物
                        try:
                            buff_bg = Image.new("RGBA", (50, 50), (255, 255, 255, 0))
                            buff_bg_draw = ImageDraw.Draw(buff_bg)
                            buff_bg_draw.rounded_rectangle(
                                [0, 0, 50, 50],
                                radius=5,
                                fill=(0, 0, 0, int(0.8 * 255)),
                            )
                            buff_color = COLOR_QUALITY[slash_half.buffQuality]
                            buff_bg_draw.rectangle(
                                [0, 45, 50, 50],
                                fill=buff_color,
                            )
                            buff_pic = await pic_download_from_url(SLASH_PATH, slash_half.buffIcon)
                            buff_pic = buff_pic.resize((50, 50))
                            buff_bg.paste(buff_pic, (0, 0), buff_pic)
                            role_bg.alpha_composite(buff_bg, (500 + half_index * 235, 15))
                        except Exception as e:
                            logger.debug(f"[鸣潮·冥海排行] 绘制信物失败: {e}")

                        # 显示半分数（在信物和角色下方）
                        role_bg_draw.text(
                            (450 + half_index * 230, 80),
                            f"{slash_half.score}",
                            get_local_score_color(slash_half.score),
                            waves_font_20,
                            "mm",
                        )

        card_img.paste(role_bg, (0, 510 + rank_temp_index * item_spacing), role_bg)

    card_img = add_footer(card_img)
    card_img = await convert_img(card_img)

    logger.info(f"[鸣潮·冥海排行] 群排行 end: {time.time() - start_time}")
    return card_img
