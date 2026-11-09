import time
from typing import Union
from pathlib import Path

from PIL import Image, ImageDraw

from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img

from .period import get_slash_period_number
from ..utils.hint import error_reply
from ..utils.at_help import safe_sender_avatar
from ..utils.util import hide_uid, get_hide_uid_pref
from ..utils.image import (
    GOLD,
    GREY,
    CHAIN_COLOR,
    SPECIAL_GOLD,
    add_footer,
    get_waves_bg,
    pic_download_from_url,
    paste_skill_branch_emblem,
)
from ..utils.api.model import (
    SlashDetail,
    AccountBaseInfo,
)
from ..utils.api.wwapi import SlashDetailRequest
from ..utils.imagetool import draw_pic, draw_pic_with_ring, draw_base_info_bg
from ..utils.waves_api import waves_api
from ..utils.error_reply import WAVES_CODE_102
from ..utils.queues.const import QUEUE_SLASH_RECORD
from ..utils.queues.queues import push_item
from ..utils.ascension.char import get_char_model
from ..utils.char_info_utils import get_all_roleid_detail_info, get_rover_detail_map, lookup_chain_with_rover
from ..utils.player_store import write_player_json
from ..utils.fonts.waves_fonts import (
    waves_font_18,
    waves_font_25,
    waves_font_26,
    waves_font_30,
    waves_font_40,
    waves_font_42,
)
from ..utils.resource.RESOURCE_PATH import SLASH_PATH, PLAYER_PATH
from ..wutheringwaves_config import WutheringWavesConfig, PREFIX

TEXT_PATH = Path(__file__).parent / "texture2d"

SLASH_ERROR = "数据获取失败，请稍后再试"
SLASH_ERROR_MESSAGE_NO_DATA = "当前暂无冥歌海墟数据"
SLASH_ERROR_MESSAGE_NO_UNLOCK = "无冥歌海墟暂未解锁"


difficulty_name_map = {
    "禁忌海域": [1, 2, 3, 4, 5, 6],
    "再生海域-海隙": [7, 8, 9, 10, 11],
    "再生海域-湍渊": [12],
}

challenge_name_map = {
    "海妖葬地": 1,
    "无光祸墟": 2,
    "湮雾深巢": 3,
    "哀潮雾廊": 4,
    "陨星流海": 5,
    "沉骨回湾": 6,
    "险滩": 7,
    "涡流": 8,
    "急潮": 9,
    "狂澜": 10,
    "海魇": 11,
    "无尽湍渊": 12,
}


COLOR_QUALITY = {
    1: (188, 188, 188),  # 白色 - 更自然的白色
    2: (76, 175, 80),  # 绿色 - 更柔和的绿色
    3: (33, 150, 243),  # 蓝色 - 更柔和的蓝色
    4: (171, 71, 188),  # 紫色 - 修正为紫色
    5: (255, 193, 7),  # 金色 - 更接近实际的金色
}


async def get_slash_data(uid: str, ck: str, is_self_ck: bool) -> Union[SlashDetail, str]:
    if is_self_ck:
        slash_data = await waves_api.get_slash_detail(uid, ck)
    else:
        slash_data = await waves_api.get_slash_index(uid, ck)

    if not slash_data.success:
        return slash_data.throw_msg()

    slash_data = slash_data.data
    if not slash_data or (isinstance(slash_data, dict) and not slash_data.get("isUnlock", False)):
        if not is_self_ck:
            if slash_data is None and await waves_api.is_hidden_to_guest(uid, ck):
                return f"用户未展示挑战数据, 请尝试【{PREFIX}登录】"
            return SLASH_ERROR_MESSAGE_NO_UNLOCK
        return SLASH_ERROR_MESSAGE_NO_DATA
    else:
        return SlashDetail.model_validate(slash_data)


# TODO: PIL 卸到线程池 (难度/挑战/队伍多层循环里 await pic_download_from_url / draw_pic 等)
async def draw_slash_img(ev: Event, uid: str, user_id: str) -> Union[bytes, str]:
    is_self_ck, ck = await waves_api.get_ck_result(uid, user_id, ev.bot_id)
    if not ck:
        return error_reply(WAVES_CODE_102)
    user_pref = await get_hide_uid_pref(uid, user_id, ev.bot_id)

    command = ev.command
    text = ev.text.strip()

    if not is_self_ck:
        challengeIds = [12]
    else:
        challengeIds = [7, 8, 9, 10, 11, 12]
        if "无尽" in text or "无尽" in command or "wj" in command or "wj" in text:
            challengeIds = [12]
        elif "禁忌" in text or "禁忌" in command:
            challengeIds = [1, 2, 3, 4, 5, 6]
        else:
            layer = text.replace("层", "").strip()
            if layer.isdigit() and 1 <= int(layer) <= 12:
                challengeIds = [int(layer)]

    # 冥海数据
    slash_detail: Union[SlashDetail, str] = await get_slash_data(uid, ck, is_self_ck)
    if isinstance(slash_detail, str):
        return slash_detail

    # check 冥海数据
    if not is_self_ck and not slash_detail.isUnlock:
        return SLASH_ERROR_MESSAGE_NO_UNLOCK

    owned_challenge_ids = [
        challenge.challengeId
        for difficulty in slash_detail.difficultyList
        for challenge in difficulty.challengeList
        if len(challenge.halfList) > 0
    ]
    if len(owned_challenge_ids) == 0:
        return SLASH_ERROR_MESSAGE_NO_DATA

    query_challenge_ids = []
    for challenge_id in challengeIds:
        if challenge_id not in owned_challenge_ids:
            continue
        query_challenge_ids.append(challenge_id)

    if len(query_challenge_ids) == 0:
        return SLASH_ERROR_MESSAGE_NO_DATA

    # 账户数据
    account_info = await waves_api.get_base_info(uid, ck)
    if not account_info.success:
        return account_info.throw_msg()
    if not account_info.data:
        return f"用户未展示数据, 请尝试【{PREFIX}登录】"
    account_info = AccountBaseInfo.model_validate(account_info.data)

    # 绘制图片
    footer_h = 50
    card_h = 300
    title_h = 130
    info_h = 300
    CHALLENGE_SPACING = 30

    h = footer_h + card_h + (info_h + title_h + CHALLENGE_SPACING) * len(query_challenge_ids) - CHALLENGE_SPACING
    card_img = get_waves_bg(1100, h, "bg9")

    # 绘制个人信息
    base_info_bg = draw_base_info_bg(
        f"{account_info.name[:10]}",
        f"特征码:  {hide_uid(account_info.id, user_pref=user_pref)}",
        TEXT_PATH,
    )
    card_img.paste(base_info_bg, (15, 20), base_info_bg)

    # 头像 头像环
    avatar, avatar_ring = await draw_pic_with_ring(ev)
    card_img.paste(avatar, (25, 70), avatar)
    card_img.paste(avatar_ring, (35, 80), avatar_ring)

    # 账号基本信息，由于可能会没有，放在一起
    if account_info.is_full:
        title_bar = Image.open(TEXT_PATH / "title_bar.png")
        title_bar_draw = ImageDraw.Draw(title_bar)
        title_bar_draw.text((660, 125), "账号等级", GREY, waves_font_26, "mm")
        title_bar_draw.text((660, 78), f"Lv.{account_info.level}", "white", waves_font_42, "mm")

        title_bar_draw.text((810, 125), "世界等级", GREY, waves_font_26, "mm")
        title_bar_draw.text((810, 78), f"Lv.{account_info.worldLevel}", "white", waves_font_42, "mm")
        card_img.paste(title_bar, (-20, 70), title_bar)

    # 根据面板数据获取详细信息
    role_detail_info_map = await get_all_roleid_detail_info(uid) or {}
    rover_map = await get_rover_detail_map(uid)

    # 绘制挑战信息
    # 倒序
    index = 0
    slash_detail.difficultyList.reverse()
    for difficulty in slash_detail.difficultyList:
        for challenge in difficulty.challengeList:
            if challenge.challengeId not in query_challenge_ids:
                continue

            if not challenge.halfList:
                continue

            # 获取title
            title_bar = Image.open(TEXT_PATH / f"difficulty_{difficulty.difficulty}.png")

            temp_bar_draw = ImageDraw.Draw(title_bar)
            # 层数
            if challenge.challengeId != 12:
                temp_bar_draw.text(
                    (70, 60),
                    f"{challenge.challengeId}",
                    "white",
                    waves_font_40,
                    "mm",
                )
            # 挑战名称
            temp_bar_draw.text(
                (140, 45),
                f"{challenge.challengeName}"
                + (f" 第{get_slash_period_number()}期" if challenge.challengeId == 12 else ""),
                "white",
                waves_font_40,
            )
            rank = challenge.get_rank()
            if len(rank) != 0:
                score_bar = Image.open(TEXT_PATH / f"score_{rank}.png")
                title_bar.paste(score_bar, (600, 10), score_bar)

            temp_bar_draw.text(
                (700, 50),
                f"挑战分数：{challenge.score}",
                SPECIAL_GOLD,
                waves_font_25,
            )

            role_bg = Image.open(TEXT_PATH / "role_hang_bg.png")
            # 获取角色信息
            for half_index, slash_half in enumerate(challenge.halfList):
                role_hang_bg = Image.new("RGBA", (1100, info_h // 2), (255, 255, 255, 0))
                role_hang_bg_draw = ImageDraw.Draw(role_hang_bg)
                text_dui = "队伍一" if half_index == 0 else "队伍二"
                role_hang_bg_draw.text(
                    (150, 30),
                    f"{text_dui}",
                    "white",
                    waves_font_30,
                )
                role_hang_bg_draw.text(
                    (150, 75),
                    f"{slash_half.score}",
                    GOLD,
                    waves_font_25,
                )
                team_pic = await pic_download_from_url(SLASH_PATH, difficulty.teamIcon)
                role_hang_bg.alpha_composite(team_pic, (30, 35))

                # buff
                buff_bg = Image.new("RGBA", (100, 100), (255, 255, 255, 0))
                buff_bg_draw = ImageDraw.Draw(buff_bg)
                buff_bg_draw.rounded_rectangle(
                    [0, 0, 100, 100],
                    radius=5,
                    fill=(0, 0, 0, int(0.8 * 255)),
                )
                buff_color = COLOR_QUALITY[slash_half.buffQuality]
                buff_bg_draw.rectangle(
                    [0, 95, 100, 100],
                    fill=buff_color,
                )
                buff_pic = await pic_download_from_url(SLASH_PATH, slash_half.buffIcon)
                buff_pic = buff_pic.resize((100, 100))
                buff_bg.paste(buff_pic, (0, 0), buff_pic)

                role_hang_bg.alpha_composite(buff_bg, (870, 20))

                for role_index, slash_role in enumerate(slash_half.roleList):
                    # 本地资源未同步时占位 (新角色发布期), 与深塔/全息一致
                    char_model = get_char_model(slash_role.roleId)
                    if char_model is None:
                        logger.warning(f"[鸣潮·冥海渲染] 本地未识别 roleId={slash_role.roleId}, 使用占位")
                        char_name = "未知"
                        char_star = 5
                    else:
                        char_name = char_model.name
                        char_star = char_model.starLevel
                    avatar = await draw_pic(slash_role.roleId)
                    char_bg = Image.open(TEXT_PATH / f"char_bg{char_star}.png")
                    slot = Image.new("RGBA", char_bg.size, (255, 255, 255, 0))
                    slot.paste(avatar, (0, 0), avatar)
                    slot.alpha_composite(char_bg)
                    char_bg = slot
                    chain_num, chain_name, _ = lookup_chain_with_rover(role_detail_info_map, rover_map, slash_role.roleId)
                    if chain_name:
                        info_block = Image.new("RGBA", (40, 20), color=(255, 255, 255, 0))
                        info_block_draw = ImageDraw.Draw(info_block)
                        info_block_draw.rectangle([0, 0, 40, 20], fill=CHAIN_COLOR[chain_num] + (int(0.9 * 255),))
                        info_block_draw.text(
                            (2, 10),
                            f"{chain_name}",
                            "white",
                            waves_font_18,
                            "lm",
                        )
                        char_bg.paste(info_block, (121, 30), info_block)

                    paste_skill_branch_emblem(char_bg, slash_role.roleId, slash_role.skillBranchIndex, (138, 130))

                    role_hang_bg.alpha_composite(char_bg, (350 + role_index * info_h // 2, -20))

                role_bg.paste(role_hang_bg, (0, info_h // 2 * half_index), role_hang_bg)

            temp_img = Image.new("RGBA", (1000, title_h + info_h), (255, 255, 255, 0))
            temp_img.paste(title_bar, (0, 0), title_bar)
            temp_img.paste(role_bg, (0, title_h), role_bg)
            card_img.paste(
                temp_img,
                (50, card_h + index * (info_h + title_h + CHALLENGE_SPACING)),
                temp_img,
            )
            index += 1

    sender_avatar = safe_sender_avatar(ev)

    card_img = add_footer(card_img, 600, 20)
    card_img = await convert_img(card_img)
    await save_slash_record(uid, slash_detail)
    await upload_slash_record(is_self_ck, uid, slash_detail, sender_avatar, user_id, ev.bot_id)
    return card_img


async def save_slash_record(
    uid: str,
    slash_data: SlashDetail,
):
    """保存无尽记录到本地文件"""
    try:
        _dir = PLAYER_PATH / uid
        _dir.mkdir(parents=True, exist_ok=True)
        path = _dir / "slashData.json"

        slash_dict = slash_data.model_dump()
        record_payload = {
            "record_time": int(time.time()),
            "slash_data": slash_dict,
        }
        await write_player_json(path, record_payload)
    except Exception as e:
        logger.warning(f"[鸣潮·冥海保存] 失败 uid={uid} error={e}")


async def upload_slash_record(
    is_self_ck: bool,
    waves_id: str,
    slash_data: SlashDetail,
    sender_avatar: str = "",
    user_id: str = "",
    bot_id: str = "",
):
    from ..utils.util import resolve_hide_uid

    WavesToken = WutheringWavesConfig.get_config("WavesToken").data
    if not WavesToken:
        return

    if not slash_data:
        return
    if not slash_data.difficultyList:
        return
    if not is_self_ck:
        return

    # 只要难度12
    difficulty = next(
        (k for k in slash_data.difficultyList if k.difficulty == 2),
        None,
    )
    if not difficulty:
        return

    challenge = next(
        (c for c in difficulty.challengeList if c.challengeId == 12),
        None,
    )
    if not challenge or not challenge.halfList:
        return

    if not challenge.get_rank():
        return

    half_list = []
    for half in challenge.halfList:
        half_list.append(
            {
                "buffIcon": half.buffIcon,
                "buffName": half.buffName,
                "buffQuality": half.buffQuality,
                "charIds": [role.roleId for role in half.roleList],
                "score": half.score,
            }
        )
    slash_item = SlashDetailRequest.model_validate(
        {
            "wavesId": waves_id,
            "challengeId": challenge.challengeId,
            "challengeName": challenge.challengeName,
            "halfList": half_list,
            "rank": challenge.get_rank(),
            "score": challenge.score,
            "sender_avatar": sender_avatar,
            "hide_uid": await resolve_hide_uid(waves_id, user_id, bot_id),
        }
    )
    # logger.info(f"[鸣潮·冥海保存] 上传冥海记录: {slash_item.model_dump()}")
    push_item(QUEUE_SLASH_RECORD, slash_item.model_dump())
