import time
import asyncio
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from datetime import timezone, timedelta

import httpx
from PIL import Image, ImageDraw

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img

from ._colors import (
    CRYSTAL_SENTINEL,
    draw_crystal_text,
    get_matrix_local_rank_color as get_local_score_color,
    get_matrix_total_rank_color as get_score_color,
    get_matrix_single_local_rank_color as get_local_team_score_color,
    get_matrix_single_total_rank_color as get_team_score_color,
)
from .rank_bar import stretch_rank_bar
from .pagination import (
    RANK_PAGE_SIZE,
    paginate_group_rank,
    group_rank_empty_page_message,
)
from .rank_badge import draw_rank_badge, draw_bot_name_badge
from .slash_rank import is_limited_5star
from ..utils.util import hide_uid, get_version, build_uid_masker
from .rank_avatar import get_avatar
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
from ..utils.api.model import MatrixDetail
from ..utils.api.wwapi import (
    GET_MATRIX_RANK_URL,
    MatrixRank,
    MatrixRankRes,
    MatrixRankItem,
    MatrixRankTeam,
)
from ..utils.player_store import read_player_json
from ..utils.ascension.char import get_char_model
from ..utils.name_convert import char_id_to_char_name
from ..utils.database.models import WavesBind, WavesUser
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
from ..utils.resource.constant import randomize_special_char_id
from ..wutheringwaves_abyss.period import (
    MATRIX_BASE_TIMESTAMP,
    parse_rank_date,
    get_matrix_period_number,
    is_matrix_record_expired,
)
from ..utils.resource.RESOURCE_PATH import MATRIX_PATH

TEXT_PATH = Path(__file__).parent / "texture2d"

CHINA_TZ = timezone(timedelta(hours=8))

MATRIX_TOTAL_WIDTH = 1300
MATRIX_SINGLE_TOTAL_WIDTH = 1100
MATRIX_GROUP_WIDTH = 1000
MATRIX_SINGLE_GROUP_WIDTH = 800
MATRIX_SINGLE_TOTAL_BASE_WIDTH = 1050
MATRIX_BAR_RIGHT_CAP_WIDTH = 400
MATRIX_SINGLE_NAME_MAX_WIDTH = 120
MATRIX_TOTAL_NAME_MAX_WIDTH = 130


def _crop_matrix_rank_bar(source: Image.Image, width: int) -> Image.Image:
    right_cap_width = MATRIX_BAR_RIGHT_CAP_WIDTH
    left_width = width - right_cap_width
    bar = Image.new("RGBA", (width, source.height), (0, 0, 0, 0))
    bar.alpha_composite(source.crop((0, 0, left_width, source.height)), (0, 0))
    bar.alpha_composite(
        source.crop((source.width - right_cap_width, 0, source.width, source.height)),
        (left_width, 0),
    )
    return bar


def _get_matrix_rank_bar(width: int) -> Image.Image:
    """裁去多余中段；单队总榜加宽时沿用声骸榜的中段拉伸。"""
    source = Image.open(TEXT_PATH / "bar1.png").convert("RGBA")
    if width >= source.width:
        return stretch_rank_bar(source, width, source.height)

    base_width = min(width, MATRIX_SINGLE_TOTAL_BASE_WIDTH)
    bar = _crop_matrix_rank_bar(source, base_width)
    if width > base_width:
        bar = stretch_rank_bar(bar, width, source.height)
    return bar


def _get_matrix_rank_score(
    rank_info: "MatrixRankListInfo", single_team: bool
) -> int:
    if single_team:
        return rank_info.top_teams[0].score if rank_info.top_teams else 0
    return rank_info.score


def _get_matrix_team_char_gold_count(teams: List[MatrixRankTeam]) -> int:
    """直接使用排行 API 返回的角色命座，计算上场限定角色金数。"""
    return sum(
        char_detail.chain + 1
        for team in teams
        for char_detail in team.char_detail
        if char_detail.chain >= 0 and is_limited_5star(char_detail.char_id)
    )


def _paste_matrix_chain_badge(
    avatar: Image.Image, chain_count: int, badge_size: int
) -> None:
    """把共鸣链色块完整贴在头像右下角，并让数字几何居中。"""
    badge = Image.new(
        "RGBA", (badge_size, badge_size), color=(255, 255, 255, 0)
    )
    badge_draw = ImageDraw.Draw(badge)
    badge_draw.rectangle(
        [0, 0, badge_size - 1, badge_size - 1],
        fill=CHAIN_COLOR[chain_count] + (int(0.9 * 255),),
    )
    badge_draw.text(
        (badge_size / 2, badge_size / 2),
        str(chain_count),
        "white",
        waves_font_12,
        "mm",
    )
    badge_pos = (
        max(0, avatar.width - badge_size),
        max(0, avatar.height - badge_size),
    )
    avatar.paste(badge, badge_pos, badge)


def _matrix_team_label(char_ids: Optional[List[int]]) -> str:
    if not char_ids:
        return ""
    names = [char_id_to_char_name(str(cid)) or str(cid) for cid in char_ids]
    return " / ".join(names)


def _draw_subtitle_suffix(draw, text: str, pos, prev_text: str) -> None:
    if not text:
        return
    try:
        prev_width = draw.textlength(prev_text, font=waves_font_20)
    except Exception:
        prev_width = waves_font_20.getsize(prev_text)[0]
    draw.text((pos[0] + prev_width + 16, pos[1]), text, GREY, waves_font_20, "lm")


async def get_rank(item: MatrixRankItem) -> Optional[MatrixRankRes]:
    WavesToken = WutheringWavesConfig.get_config("WavesToken").data

    if not WavesToken:
        return

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                GET_MATRIX_RANK_URL,
                json=item.model_dump(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {WavesToken}",
                },
                timeout=httpx.Timeout(10),
            )
            if res.status_code == 200:
                return MatrixRankRes.model_validate(res.json())
            else:
                logger.warning(f"[鸣潮·矩阵排行] 获取远端排行失败: {res.status_code} - {res.text}")
        except Exception as e:
            logger.exception(f"[鸣潮·矩阵排行] 获取远端排行失败: {e}")


# TODO: PIL 卸到线程池 (loop 内 await get_square_avatar / pic_download_from_url 频繁, 需要批量预取重构)
async def draw_all_matrix_rank_card(
    bot: Bot,
    ev: Event,
    single_team: bool = False,
    page: int = 1,
    char_ids: Optional[List[int]] = None,
):
    waves_id = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    page_num = RANK_PAGE_SIZE
    item = MatrixRankItem(
        page=page,
        page_num=page_num,
        waves_id=waves_id or "",
        version=get_version(dynamic=True, waves_id=waves_id or "", pages=page),
        single_team=single_team,
        char_ids=char_ids or [],
    )

    rankInfoList = await get_rank(item)
    if not rankInfoList:
        return "获取矩阵排行失败"

    if rankInfoList.message and not rankInfoList.data:
        return rankInfoList.message

    if not rankInfoList.data or not rankInfoList.data.rank_list:
        return "暂无该队伍的排行数据" if char_ids else "暂无排行数据"

    # 设置图像尺寸
    width = MATRIX_SINGLE_TOTAL_WIDTH if single_team else MATRIX_TOTAL_WIDTH
    item_spacing = 120
    header_height = 510
    footer_height = 50
    char_list_len = len(rankInfoList.data.rank_list)

    total_height = header_height + item_spacing * char_list_len + footer_height

    card_img = get_waves_bg(width, total_height, "bg9")

    # title — 使用 matrix.png
    title_bg = Image.open(TEXT_PATH / "matrix.png").convert("RGBA")
    title_scale = width / title_bg.width
    title_bg = title_bg.resize((width, int(title_bg.height * title_scale)))
    if title_bg.height > 500:
        title_bg = title_bg.crop((0, 0, width, 500))
    else:
        temp = Image.new("RGBA", (width, 500), (0, 0, 0, 0))
        temp.paste(title_bg, (0, 500 - title_bg.height))
        title_bg = temp

    # icon
    icon = get_ICON()
    icon = icon.resize((128, 128))
    title_bg.paste(icon, (60, 240), icon)

    # title text
    title_text = "#矩阵单队总排行" if single_team else "#矩阵总排行"
    title_bg_draw = ImageDraw.Draw(title_bg)
    title_bg_draw.text((220, 290), title_text, "white", waves_font_58, "lm")

    period_label = None
    if rankInfoList.data and rankInfoList.data.start_date:
        rank_dt = parse_rank_date(rankInfoList.data.start_date)
        if rank_dt:
            period_label = f"第{get_matrix_period_number(rank_dt)}期"
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
        _draw_subtitle_suffix(
            title_bg_draw,
            _matrix_team_label(char_ids),
            (period_pos[0] + period_width + 16, period_pos[1]),
            date_text,
        )

    # 遮罩
    char_mask = Image.open(TEXT_PATH / "char_mask.png").convert("RGBA")
    char_mask = char_mask.resize((width, char_mask.height * width // char_mask.width))
    char_mask = char_mask.crop((0, char_mask.height - 500, width, char_mask.height))
    char_mask_temp = Image.new("RGBA", char_mask.size, (0, 0, 0, 0))
    char_mask_temp.paste(title_bg, (0, 0), char_mask)

    card_img.paste(char_mask_temp, (0, 0), char_mask_temp)

    rank_list = rankInfoList.data.rank_list
    board_7digit = any(rank.score >= 1_000_000 for rank in rank_list)
    board_6digit = any(rank.score >= 100_000 for rank in rank_list)
    tasks = [get_avatar(rank.user_id, getattr(rank, "sender_avatar", "")) for rank in rank_list]
    results = await asyncio.gather(*tasks)
    bar = _get_matrix_rank_bar(width)

    for rank_temp_index, temp in enumerate(zip(rank_list, results)):
        rank_temp: MatrixRank = temp[0]
        role_avatar: Image.Image = temp[1]
        role_bg = bar.copy()
        role_bg.paste(role_avatar, (100, 0), role_avatar)
        role_bg_draw = ImageDraw.Draw(role_bg)

        # 排名
        rank_id = rank_temp.rank
        draw_rank_badge(role_bg, rank_id)

        # 名字：昵称过长时统一缩字/截断。
        role_name = str(rank_temp.kuro_name)
        name_max_width = (
            MATRIX_SINGLE_NAME_MAX_WIDTH if single_team else MATRIX_TOTAL_NAME_MAX_WIDTH
        )
        role_name_font, role_name = fit_text(
            role_bg_draw,
            role_name,
            name_max_width,
            (
                waves_font_20,
                waves_font_18,
                waves_font_16,
                waves_font_14,
                waves_font_12,
            ),
        )
        role_bg_draw.text((210, 75), role_name, "white", role_name_font, "lm")

        # 单队榜沿用角色总排行的信息关系：UID 在右上、角色名在左下、Bot 名片在右下。
        uid_color = "white"
        if rank_temp.waves_id == item.waves_id:
            uid_color = RED
        uid_text = hide_uid(
            rank_temp.waves_id,
            user_pref="on" if rank_temp.hide_uid else "",
        )
        if single_team:
            role_bg_draw.text(
                (350, 40),
                f"特征码: {uid_text}",
                uid_color,
                waves_font_20,
                "lm",
            )
        else:
            role_bg_draw.text((210, 40), uid_text, uid_color, waves_font_20, "lm")

        # 上场队伍数量 居中对齐 bot名徽章（徽章 208 宽，名字居中于 +104）。
        team_info_x = 350
        team_info_cx = team_info_x + 104
        if single_team:
            # 单队响应只含最高分队伍；角色命座已随 API 返回，无需额外查询。
            char_gold_total = _get_matrix_team_char_gold_count(rank_temp.teams)
            gold_label = "上场队伍角色金数:"
            role_bg_draw.text((210, 40), gold_label, "white", waves_font_12, "lm")
            label_width = role_bg_draw.textlength(gold_label, font=waves_font_12)
            role_bg_draw.text(
                (210 + label_width + 4, 40),
                str(char_gold_total),
                RED,
                waves_font_18,
                "lm",
            )
        else:
            # 原特征码位置 → 显示上场队伍数量（未登录时为0，不显示）
            team_count = rank_temp.team_count if rank_temp.team_count else len(rank_temp.teams)
            if team_count:
                role_bg_draw.text(
                    (team_info_cx, 40),
                    f"上场队伍数量: {team_count}",
                    GREY,
                    waves_font_20,
                    "mm",
                )

        # bot主人名字
        botName = rank_temp.alias_name if rank_temp.alias_name else ""
        if botName:
            bot_badge_pos = (346, 60) if single_team else (team_info_x, 60)
            draw_bot_name_badge(
                role_bg,
                getattr(rank_temp, "background", ""),
                botName,
                bot_badge_pos,
            )

        # 单队六位数需避开右侧金框。
        score_color = (
            get_team_score_color(rank_temp.score)
            if single_team
            else get_score_color(rank_temp.score)
        )
        score_center_x = 950 if single_team else 1150
        if score_color == CRYSTAL_SENTINEL:
            draw_crystal_text(role_bg, f"{rank_temp.score}", score_center_x, 55, waves_font_44, "mm")
        else:
            role_bg_draw.text(
                (score_center_x, 55),
                f"{rank_temp.score}",
                score_color,
                waves_font_44,
                "mm",
            )

        team_base_x = (580 if board_6digit else 600) if single_team else 575
        team_spacing = 230 if (not single_team and board_7digit) else 250

        # 按分数排序取最高和次高
        sorted_teams = sorted(rank_temp.teams, key=lambda t: t.score, reverse=True)

        team_limit = 1 if single_team else 2
        for team_index, matrix_team in enumerate(sorted_teams[:team_limit]):
            char_size = 55 if single_team else 45
            char_spacing = 60 if single_team else 50
            char_y = 28 if single_team else 20
            buff_size = 60 if single_team else 50
            buff_y = 25 if single_team else 15

            # 角色头像
            for role_index, char_detail in enumerate(matrix_team.char_detail):
                char_id = char_detail.char_id
                char_chain = char_detail.chain

                char_id = randomize_special_char_id(char_id)
                char_model = get_char_model(char_id)
                if char_model is None:
                    continue
                char_avatar = await get_square_avatar(char_id)
                char_avatar = char_avatar.resize((char_size, char_size))

                if char_chain != -1:
                    _paste_matrix_chain_badge(
                        char_avatar,
                        char_chain,
                        20 if single_team else 15,
                    )

                role_bg.alpha_composite(
                    char_avatar,
                    (
                        team_base_x + team_index * team_spacing + role_index * char_spacing,
                        char_y,
                    ),
                )

            # 角色头像为空时，尝试用 role_icons URL 下载显示
            if not matrix_team.char_detail and matrix_team.role_icons:
                for role_index, icon_url in enumerate(matrix_team.role_icons):
                    try:
                        role_pic = await pic_download_from_url(MATRIX_PATH, icon_url)
                        role_pic = role_pic.resize((char_size, char_size))
                        circle_mask = Image.new("L", (char_size, char_size), 0)
                        circle_draw = ImageDraw.Draw(circle_mask)
                        circle_draw.ellipse(
                            [0, 0, char_size - 1, char_size - 1],
                            fill=255,
                        )
                        role_circle = Image.new(
                            "RGBA", (char_size, char_size), (0, 0, 0, 0)
                        )
                        role_circle.paste(role_pic, (0, 0), circle_mask)
                        role_bg.alpha_composite(
                            role_circle,
                            (
                                team_base_x
                                + team_index * team_spacing
                                + role_index * char_spacing,
                                char_y,
                            ),
                        )
                    except Exception:
                        pass

            # 不足3人时用 "模版\n角色" 文字占位
            actual_count = len(matrix_team.char_detail) or len(matrix_team.role_icons)
            for empty_idx in range(actual_count, 3):
                placeholder = Image.new(
                    "RGBA",
                    (char_size, char_size),
                    (60, 60, 60, int(0.5 * 255)),
                )
                ph_draw = ImageDraw.Draw(placeholder)
                ph_draw.rectangle(
                    [0, 0, char_size - 1, char_size - 1],
                    outline=(120, 120, 120, 200),
                    width=1,
                )
                placeholder_first_y = 19 if single_team else 16
                placeholder_second_y = 35 if single_team else 32
                ph_draw.text(
                    (char_size // 2, placeholder_first_y),
                    "模版",
                    GREY,
                    waves_font_12,
                    "mm",
                )
                ph_draw.text(
                    (char_size // 2, placeholder_second_y),
                    "角色",
                    GREY,
                    waves_font_12,
                    "mm",
                )
                role_bg.alpha_composite(
                    placeholder,
                    (
                        team_base_x + team_index * team_spacing + empty_idx * char_spacing,
                        char_y,
                    ),
                )

            # buff icon
            if matrix_team.buff_icon:
                try:
                    buff_bg = Image.new(
                        "RGBA", (buff_size, buff_size), (255, 255, 255, 0)
                    )
                    buff_bg_draw = ImageDraw.Draw(buff_bg)
                    buff_bg_draw.rounded_rectangle(
                        [0, 0, buff_size, buff_size],
                        radius=5,
                        fill=(0, 0, 0, int(0.8 * 255)),
                    )
                    buff_pic = await pic_download_from_url(MATRIX_PATH, matrix_team.buff_icon)
                    buff_pic = buff_pic.resize((buff_size, buff_size))
                    buff_bg.paste(buff_pic, (0, 0), buff_pic)
                    # 角色头像最多3个，buff 保持10px间距并与条目垂直居中。
                    role_bg.alpha_composite(
                        buff_bg,
                        (
                            team_base_x + team_index * team_spacing + char_spacing * 3 + 10,
                            buff_y,
                        ),
                    )
                except Exception as e:
                    logger.debug(f"[鸣潮·矩阵排行] 绘制 buff 图标失败: {e}")

            if not single_team:
                # 总榜展示两队时标明最高/次高；单队榜右侧大号分数已经是该队分数，不重复。
                block_center_x = team_base_x + team_index * team_spacing + 105
                score_label = "最高单队得分" if team_index == 0 else "次高单队得分"
                team_score_text = f"{score_label}: {matrix_team.score}"
                team_score_color = get_team_score_color(matrix_team.score)
                if team_score_color == CRYSTAL_SENTINEL:
                    draw_crystal_text(
                        role_bg,
                        team_score_text,
                        block_center_x,
                        80,
                        waves_font_18,
                        "mm",
                    )
                else:
                    role_bg_draw.text(
                        (block_center_x, 80),
                        team_score_text,
                        team_score_color,
                        waves_font_18,
                        "mm",
                    )

        card_img.paste(role_bg, (0, 510 + rank_temp_index * item_spacing), role_bg)

    card_img = add_footer(card_img)
    card_img = await convert_img(card_img)
    return card_img


class MatrixTeamInfo:
    """排行中的队伍摘要"""

    def __init__(self, score: int, role_icons: List[str],
                 buff_icon: str = "", char_ids: Optional[List[int]] = None):
        self.score = score
        self.role_icons = role_icons  # URL 列表
        self.buff_icon = buff_icon  # buff图标 URL
        self.char_ids = char_ids or []  # 匹配到的角色ID (可能为空)


class MatrixRankListInfo:
    """矩阵排行信息"""

    def __init__(self, user_id: str, uid: str,
                 matrix_data: Optional[MatrixDetail] = None,
                 matched_char_ids: Optional[Dict] = None,
                 team_key: Optional[Tuple[int, ...]] = None):
        self.user_id = user_id
        self.uid = uid
        self.matrix_data = matrix_data
        self.score = 0
        self.top_teams: List[MatrixTeamInfo] = []

        self.all_char_ids: List[int] = []  # 所有队伍的角色ID (用于计算总金数)

        matched = matched_char_ids or {}

        if matrix_data and matrix_data.modeDetails:
            mode_1 = next((m for m in matrix_data.modeDetails if m.modeId == 1 and m.hasRecord), None)
            if mode_1:
                self.score = mode_1.score
                if mode_1.teams:
                    # 收集所有队伍的 char_ids
                    for idx in range(len(mode_1.teams)):
                        ids = matched.get(f"1_{idx}", [])
                        self.all_char_ids.extend(ids)

                    # 按分数降序取前两队展示; 指定队伍时只留该组合的最高分队
                    indexed_teams = list(enumerate(mode_1.teams))
                    indexed_teams.sort(key=lambda x: x[1].score, reverse=True)
                    if team_key is not None:
                        indexed_teams = [
                            (idx, t)
                            for idx, t in indexed_teams
                            if tuple(sorted(matched.get(f"1_{idx}", []))) == team_key
                        ][:1]
                    for orig_idx, t in indexed_teams[:2]:
                        ids = matched.get(f"1_{orig_idx}", [])
                        self.top_teams.append(
                            MatrixTeamInfo(
                                t.score,
                                t.roleIcons,
                                t.buffs[0].buffIcon if t.buffs else "",
                                ids,
                            )
                        )


async def get_all_matrix_rank_info(
    users: List[WavesBind],
    tokenLimitFlag: bool = False,
    wavesTokenUsersMap: Optional[Dict[Tuple[str, str], str]] = None,
    team_key: Optional[Tuple[int, ...]] = None,
) -> List[MatrixRankListInfo]:
    """从本地获取所有用户的矩阵排行信息"""
    from ..utils.resource.RESOURCE_PATH import PLAYER_PATH

    rankInfoList = []

    for user in users:
        if not user.uid:
            continue

        for uid in user.uid.split("_"):
            if tokenLimitFlag and wavesTokenUsersMap is not None:
                if (user.user_id, uid) not in wavesTokenUsersMap:
                    continue
            try:
                matrix_data_path = PLAYER_PATH / uid / "matrixData.json"
                matrix_raw = await read_player_json(matrix_data_path)
                if matrix_raw is None:
                    continue

                record_time = None
                matrix_data = matrix_raw
                matched_char_ids = None
                if isinstance(matrix_raw, dict) and "matrix_data" in matrix_raw:
                    record_time = matrix_raw.get("record_time", MATRIX_BASE_TIMESTAMP)
                    matrix_data = matrix_raw.get("matrix_data")
                    matched_char_ids = matrix_raw.get("matched_char_ids")

                if not isinstance(matrix_data, dict) or not matrix_data:
                    continue

                if is_matrix_record_expired(record_time):
                    logger.debug(f"[鸣潮·矩阵排行] 用户 uid={uid} 数据已过期, 跳过")
                    continue

                if not matrix_data.get("isUnlock", False):
                    continue

                matrix_data = MatrixDetail.model_validate(matrix_data)

                rankInfo = MatrixRankListInfo(
                    user.user_id, uid, matrix_data, matched_char_ids, team_key
                )
                if rankInfo.score > 0:
                    rankInfoList.append(rankInfo)
            except Exception as e:
                logger.debug(f"[鸣潮·矩阵排行] 获取 uid={uid} 本地数据失败: {e}")
                continue

    return rankInfoList


async def get_matrix_rank_token_condition(ev) -> Tuple[bool, Dict[Tuple[str, str], str]]:
    """检查矩阵排行的权限配置 (与冥海一致)"""
    tokenLimitFlag = False
    wavesTokenUsersMap: Dict[Tuple[str, str], str] = {}

    WavesRankNoLimitGroup = WutheringWavesConfig.get_config("WavesRankNoLimitGroup").data
    if ev.group_id and WavesRankNoLimitGroup and ev.group_id in WavesRankNoLimitGroup:
        return tokenLimitFlag, wavesTokenUsersMap

    WavesRankUseTokenGroup = WutheringWavesConfig.get_config("WavesRankUseTokenGroup").data
    RankUseToken = WutheringWavesConfig.get_config("RankUseToken").data
    if (ev.group_id and WavesRankUseTokenGroup and ev.group_id in WavesRankUseTokenGroup) or RankUseToken:
        wavesTokenUsers = await WavesUser.get_waves_all_user()
        wavesTokenUsersMap = {(w.user_id, w.uid): w.cookie for w in wavesTokenUsers}
        tokenLimitFlag = True

    return tokenLimitFlag, wavesTokenUsersMap


async def get_role_chain_count(uid: str, role_id: int) -> int:
    """获取角色共鸣链数量, 漂泊者走 rover.json"""
    from ..utils.char_info_utils import get_rover_detail_map
    from ..utils.resource.constant import SPECIAL_CHAR, SPECIAL_CHAR_RANK_MAP
    from ..utils.resource.RESOURCE_PATH import PLAYER_PATH

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
        logger.debug(f"[鸣潮·矩阵排行] 获取角色 roleId={role_id} 共鸣链失败: {e}")
        return -1


# TODO: PIL 卸到线程池 (loop 内 await get_role_chain_count / pic_download_from_url 频繁, 需要批量预取重构)
async def draw_matrix_rank_list(
    bot: Bot,
    ev: Event,
    single_team: bool = False,
    page: int = 1,
    char_ids: Optional[List[int]] = None,
):
    """绘制矩阵群排行 (PIL)"""
    team_key = tuple(sorted(char_ids)) if char_ids else None
    start_time = time.time()
    logger.info(f"[鸣潮·矩阵排行] 群排行 start: {start_time}")

    # 检查权限配置
    tokenLimitFlag, wavesTokenUsersMap = await get_matrix_rank_token_condition(ev)

    # 获取群里的所有用户
    users = await WavesBind.get_group_all_uid(ev.group_id)
    if not users:
        msg = []
        msg.append(f"[鸣潮] 群【{ev.group_id}】暂无矩阵排行数据")
        msg.append(f"请使用【{PREFIX}矩阵】后再使用此功能！")
        if tokenLimitFlag:
            msg.append(f"当前排行开启了登录验证，请使用命令【{PREFIX}登录】登录后此功能！")
        msg.append("")
        return "\n".join(msg)

    rankInfoList = await get_all_matrix_rank_info(
        list(users), tokenLimitFlag, wavesTokenUsersMap, team_key
    )
    if len(rankInfoList) == 0:
        msg = []
        msg.append(f"[鸣潮] 群【{ev.group_id}】暂无矩阵排行数据")
        msg.append(f"请使用【{PREFIX}矩阵】后再使用此功能！")
        if tokenLimitFlag:
            msg.append(f"当前排行开启了登录验证，请使用命令【{PREFIX}登录】登录后此功能！")
        msg.append("")
        return "\n".join(msg)

    if single_team:
        rankInfoList = [i for i in rankInfoList if _get_matrix_rank_score(i, True) > 0]
        if not rankInfoList:
            if team_key:
                return f"[鸣潮] 群【{ev.group_id}】暂无该队伍的矩阵记录"
            return (
                f"[鸣潮] 群【{ev.group_id}】暂无矩阵单队排行数据\n"
                f"请先使用【{PREFIX}矩阵】保存单队记录！"
            )

    # 总排行按总分，单队排行按最高单队分排序
    rankInfoList.sort(key=lambda i: _get_matrix_rank_score(i, single_team), reverse=True)

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
    except Exception:
        pass

    rankInfoList_display, display_rank_ids, page_count, page_item_count = (
        paginate_group_rank(rankInfoList, page, rankId, rankInfo)
    )
    if page_item_count == 0:
        return group_rank_empty_page_message(page, page_count)

    _mask_uid = await build_uid_masker([(ri.uid, ri.user_id) for ri in rankInfoList_display], ev.bot_id)

    # 设置图像尺寸
    width = MATRIX_SINGLE_GROUP_WIDTH if single_team else MATRIX_GROUP_WIDTH
    item_spacing = 120
    header_height = 510
    footer_height = 50

    total_height = header_height + item_spacing * len(rankInfoList_display) + footer_height

    card_img = get_waves_bg(width, total_height, "bg9")

    # title — 统一按普通矩阵群榜的1000px基准画布绘制；单队窄图只在最后裁右侧。
    # 不能直接按800px缩放，否则 matrix.png 和 char_mask 高度不足会被向下补透明区。
    header_canvas_width = MATRIX_GROUP_WIDTH
    title_bg = Image.open(TEXT_PATH / "matrix.png").convert("RGBA")
    title_scale = header_canvas_width / title_bg.width
    title_bg = title_bg.resize(
        (header_canvas_width, int(title_bg.height * title_scale))
    )
    # 裁剪到 475 高度
    if title_bg.height > 475:
        title_bg = title_bg.crop((0, 0, header_canvas_width, 475))
    else:
        # 如果不够高，创建一个 475 高度的画布
        temp = Image.new(
            "RGBA", (header_canvas_width, 475), (0, 0, 0, 0)
        )
        temp.paste(title_bg, (0, 475 - title_bg.height))
        title_bg = temp

    # icon
    icon = get_ICON()
    icon = icon.resize((128, 128))
    title_bg.paste(icon, (60, 240), icon)

    # title text
    title_text = "#矩阵单队群排行" if single_team else "#矩阵群排行"
    title_bg_draw = ImageDraw.Draw(title_bg)
    title_bg_draw.text((220, 290), title_text, "white", waves_font_58, "lm")
    period_label = f"第{get_matrix_period_number()}期"
    title_bg_draw.text((225, 360), period_label, GREY, waves_font_20, "lm")
    date_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    try:
        period_width = title_bg_draw.textlength(period_label, font=waves_font_20)
    except Exception:
        period_width = waves_font_20.getsize(period_label)[0]
    title_bg_draw.text((225 + period_width + 16, 360), date_text, GREY, waves_font_20, "lm")
    _draw_subtitle_suffix(
        title_bg_draw, _matrix_team_label(char_ids), (225 + period_width + 16, 360), date_text
    )

    # 遮罩
    char_mask = Image.open(TEXT_PATH / "char_mask.png").convert("RGBA")
    char_mask = char_mask.resize(
        (
            header_canvas_width,
            char_mask.height * header_canvas_width // char_mask.width,
        )
    )
    char_mask = char_mask.crop(
        (
            0,
            char_mask.height - 475,
            header_canvas_width,
            char_mask.height,
        )
    )
    char_mask_temp = Image.new("RGBA", char_mask.size, (0, 0, 0, 0))
    char_mask_temp.paste(title_bg, (0, 0), char_mask)
    if width < header_canvas_width:
        char_mask_temp = char_mask_temp.crop((0, 0, width, 475))

    card_img.paste(char_mask_temp, (0, 0), char_mask_temp)

    # 获取头像
    tasks = [get_avatar(rank.user_id, getattr(rank, "sender_avatar", "")) for rank in rankInfoList_display]
    results = await asyncio.gather(*tasks)

    # 绘制排行条目
    bar = _get_matrix_rank_bar(width) if single_team else Image.open(TEXT_PATH / "bar2.png")

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
        seen_ids = set()
        gold_char_ids = (
            rankInfo.top_teams[0].char_ids
            if single_team and rankInfo.top_teams
            else rankInfo.all_char_ids
        )
        for role_id in gold_char_ids:
            if role_id in seen_ids:
                continue
            seen_ids.add(role_id)
            if not is_limited_5star(role_id):
                continue
            chain_count = await get_role_chain_count(rankInfo.uid, role_id)
            if chain_count >= 0:
                char_gold_total += chain_count + 1

        role_bg_draw.text((210, 40), f"角色限定{char_gold_total}金", "white", waves_font_18, "lm")

        # 特征码
        uid_color = "white"
        if rankInfo.uid == self_uid:
            uid_color = RED
        role_bg_draw.text((210, 70), f"{_mask_uid(rankInfo.uid, rankInfo.user_id)}", uid_color, waves_font_20, "lm")

        # 单队六位数需避开右侧金框。
        rank_score = _get_matrix_rank_score(rankInfo, single_team)
        total_color = (
            get_local_team_score_color(rank_score)
            if single_team
            else get_local_score_color(rank_score)
        )
        score_center_x = 675 if single_team else 875
        if total_color == CRYSTAL_SENTINEL:
            draw_crystal_text(role_bg, f"{rank_score}", score_center_x, 55, waves_font_34, "mm")
        else:
            role_bg_draw.text(
                (score_center_x, 55),
                f"{rank_score}",
                total_color,
                waves_font_34,
                "mm",
            )

        # 上下两队: 角色头像 + buff + 得分
        team_limit = 1 if single_team else 2
        for half_index, team_info in enumerate(rankInfo.top_teams[:team_limit]):
            base_x = 375 if single_team else 365 + half_index * 230
            role_spacing = 55 if single_team else 50
            buff_offset = role_spacing * 3 if single_team else 150

            # 角色头像 (从URL下载, 方形) + 共鸣链
            for role_index, icon_url in enumerate(team_info.role_icons):
                try:
                    role_pic = await pic_download_from_url(MATRIX_PATH, icon_url)
                    role_pic = role_pic.resize((45, 45))

                    # 如果有对应的 char_id，绘制共鸣链
                    if role_index < len(team_info.char_ids) and team_info.char_ids[role_index]:
                        char_id = team_info.char_ids[role_index]
                        chain_count = await get_role_chain_count(rankInfo.uid, char_id)
                        if chain_count != -1:
                            _paste_matrix_chain_badge(
                                role_pic,
                                chain_count,
                                15,
                            )

                    role_bg.alpha_composite(
                        role_pic,
                        (base_x + role_index * role_spacing, 20),
                    )
                except Exception as e:
                    logger.debug(f"[鸣潮·矩阵排行] 绘制角色头像失败: {e}")

            # buff图标 (与slash信物位置一致)
            if team_info.buff_icon:
                try:
                    buff_bg = Image.new("RGBA", (50, 50), (255, 255, 255, 0))
                    buff_bg_draw = ImageDraw.Draw(buff_bg)
                    buff_bg_draw.rounded_rectangle(
                        [0, 0, 50, 50],
                        radius=5,
                        fill=(0, 0, 0, int(0.8 * 255)),
                    )
                    buff_pic = await pic_download_from_url(MATRIX_PATH, team_info.buff_icon)
                    buff_pic = buff_pic.resize((50, 50))
                    buff_bg.paste(buff_pic, (0, 0), buff_pic)
                    role_bg.alpha_composite(buff_bg, (base_x + buff_offset, 15))
                except Exception as e:
                    logger.debug(f"[鸣潮·矩阵排行] 绘制 buff 失败: {e}")

            # 队伍分数 (在角色和buff下方)
            team_color = get_local_team_score_color(team_info.score)
            team_score_center_x = base_x + (107 if single_team else 100)
            if team_color == CRYSTAL_SENTINEL:
                draw_crystal_text(
                    role_bg,
                    f"{team_info.score}",
                    team_score_center_x,
                    80,
                    waves_font_20,
                    "mm",
                )
            else:
                role_bg_draw.text(
                    (team_score_center_x, 80),
                    f"{team_info.score}",
                    team_color,
                    waves_font_20,
                    "mm",
                )

        card_img.paste(role_bg, (0, 510 + rank_temp_index * item_spacing), role_bg)

    card_img = add_footer(card_img)
    card_img = await convert_img(card_img)

    logger.info(f"[鸣潮·矩阵排行] 群排行 end: {time.time() - start_time}")
    return card_img
