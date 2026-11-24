from typing import Union
from pathlib import Path

from PIL import Image, ImageDraw

from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img

from .period import get_tower_period_number
from ..utils.hint import error_reply
from ..utils.util import get_version, hide_uid, get_hide_uid_pref
from ..utils.image import GREY, CHAIN_COLOR, add_footer, get_waves_bg, paste_skill_branch_emblem
from ..utils.api.model import (
    RoleList,
    AbyssFloor,
    AbyssChallenge,
    AccountBaseInfo,
)
from ..utils.api.wwapi import ABYSS_TYPE_MAP, AbyssItem, AbyssDetail
from ..utils.imagetool import draw_pic, draw_pic_with_ring, draw_base_info_bg
from ..utils.waves_api import waves_api
from ..utils.error_reply import WAVES_CODE_102
from ..utils.queues.const import QUEUE_ABYSS_RECORD
from ..utils.queues.queues import push_item
from ..utils.char_info_utils import get_all_roleid_detail_info, get_rover_detail_map, lookup_chain_with_rover
from ..wutheringwaves_config import PREFIX
from ..utils.fonts.waves_fonts import (
    waves_font_18,
    waves_font_26,
    waves_font_30,
    waves_font_32,
    waves_font_36,
    waves_font_40,
    waves_font_42,
)

TEXT_PATH = Path(__file__).parent / "texture2d"

ABYSS_ERROR_MESSAGE_NO_DATA = "当前暂无深塔数据\n"
ABYSS_ERROR_MESSAGE_NO_UNLOCK = "深塔暂未解锁\n"
ABYSS_ERROR_MESSAGE_NO_DEEP = "当前暂无深境区深塔数据\n"
no_login_msg = [
    "[鸣潮]",
    ">您当前为仅绑定鸣潮特征码",
    f">请使用命令【{PREFIX}登录】后查询详细深塔数据",
    "",
]
ABYSS_ERROR_MESSAGE_LOGIN = "\n".join(no_login_msg)


async def get_abyss_data(uid: str, ck: str, is_self_ck: bool):
    if is_self_ck:
        abyss_data = await waves_api.get_abyss_data(uid, ck)
    else:
        abyss_data = await waves_api.get_abyss_index(uid, ck)

    if not abyss_data.success:
        return abyss_data.throw_msg()

    abyss_data = abyss_data.data
    if not abyss_data or (isinstance(abyss_data, dict) and not abyss_data.get("isUnlock", False)):
        if not is_self_ck:
            return ABYSS_ERROR_MESSAGE_LOGIN
        return ABYSS_ERROR_MESSAGE_NO_DATA
    else:
        return AbyssChallenge.model_validate(abyss_data)


# TODO: PIL 卸到线程池 (循环里多处 await draw_pic / draw_pic_with_ring 与 PIL 操作交错)
async def draw_abyss_img(ev: Event, uid: str, user_id: str, peek: bool = False) -> Union[bytes, str]:
    is_self_ck, ck = await waves_api.get_ck_result(uid, user_id, ev.bot_id, peek=peek)
    if not ck:
        return error_reply(WAVES_CODE_102)
    user_pref = await get_hide_uid_pref(uid, user_id, ev.bot_id)

    # succ, game_info = await waves_api.get_game_role_info(ck)
    # if not succ:
    #     return game_info
    # game_info = KuroRoleInfo(**game_info)

    command = ev.command
    text = ev.text.strip()
    difficultyName = "深境区"
    if "超载" in text or "超载" in command:
        difficultyName = "超载区"
    elif "稳定" in text or "稳定" in command:
        difficultyName = "稳定区"
    elif "实验" in text or "实验" in command:
        difficultyName = "实验区"

    # 账户数据
    account_info = await waves_api.get_base_info(uid, ck)
    if not account_info.success:
        return account_info.throw_msg()
    if not account_info.data:
        return f"用户未展示数据, 请尝试【{PREFIX}登录】"
    account_info = AccountBaseInfo.model_validate(account_info.data)

    # 共鸣者信息
    role_info_res = await waves_api.get_role_info(uid, ck)
    role_info_list = []
    if role_info_res.success and role_info_res.data:
        try:
            role_info = RoleList.model_validate(role_info_res.data)
            role_info_list = role_info.roleList
        except Exception:
            pass

    # 深塔
    abyss_data = await get_abyss_data(uid, ck, is_self_ck)
    if isinstance(abyss_data, str) or not abyss_data:
        return abyss_data
    if not abyss_data.isUnlock:
        return ABYSS_ERROR_MESSAGE_NO_UNLOCK

    if not abyss_data.difficultyList:
        return ABYSS_ERROR_MESSAGE_NO_DEEP

    abyss_check = next(
        (abyss for abyss in abyss_data.difficultyList if abyss.difficultyName == "深境区"),
        None,
    )
    if not abyss_check:
        return ABYSS_ERROR_MESSAGE_NO_DEEP

    needAbyss = None
    for _abyss in abyss_data.difficultyList:
        if _abyss.difficultyName != difficultyName:
            continue
        needAbyss = _abyss
        break
    if not needAbyss:
        return ABYSS_ERROR_MESSAGE_NO_DEEP

    frameHigh = sum([len(i.floorList) * 141 + 90 + 50 for i in needAbyss.towerAreaList if i.floorList]) + 100 + 50

    h = frameHigh + 220
    card_img = get_waves_bg(950, h, "bg4")

    # 基础信息 名字 特征码
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

    # 添加深塔期数显示（右上角）
    period_text = f"第{get_tower_period_number()}期"
    card_draw = ImageDraw.Draw(card_img)
    card_draw.text((475, 50), period_text, "white", waves_font_30, "mm")

    # 根据面板数据获取详细信息
    role_detail_info_map = await get_all_roleid_detail_info(uid)
    rover_map = await get_rover_detail_map(uid)

    # frame
    frame = Image.open(TEXT_PATH / "frame.png")
    frame = frame.resize((frame.size[0], frameHigh))

    yset = 100  # 起始
    for _abyss in abyss_data.difficultyList:
        if _abyss.difficultyName != difficultyName:
            continue
        for tower_index, tower in enumerate(_abyss.towerAreaList):
            tower_name_bg = Image.open(TEXT_PATH / f"tower_name_bg{tower.areaId}.png")
            tower_name_bg_draw = ImageDraw.Draw(tower_name_bg)
            tower_name_bg_draw.text(
                (170, 50),
                f"{difficultyName}-{tower.areaName}",
                "white",
                waves_font_36,
                "lm",
            )
            if is_self_ck:
                tower_name_bg_draw.text(
                    (500, 60),
                    f"{tower.star}/{tower.maxStar}",
                    "white",
                    waves_font_32,
                    "mm",
                )
            frame.paste(tower_name_bg, (-20, yset), tower_name_bg)

            yset += 90  # tower_name_bg high
            if not tower.floorList:
                tower.floorList = [AbyssFloor(**{"floor": 1, "picUrl": "", "star": 0, "roleList": None})]
            for floor_index, floor in enumerate(tower.floorList):
                abyss_bg = Image.open(TEXT_PATH / f"abyss_bg_{floor.floor}.jpg").convert("RGBA")
                abyss_bg = abyss_bg.resize((abyss_bg.size[0] + 100, abyss_bg.size[1]))
                abyss_bg_temp = Image.new("RGBA", abyss_bg.size)
                name_bg = Image.open(TEXT_PATH / "name_bg.png")
                name_bg_draw = ImageDraw.Draw(name_bg)
                if floor.floor == 1:
                    _floor = "一"
                elif floor.floor == 2:
                    _floor = "二"
                elif floor.floor == 3:
                    _floor = "三"
                elif floor.floor == 4:
                    _floor = "四"
                name_bg_draw.text((70, 50), f"第{_floor}层", "white", waves_font_40, "lm")
                abyss_bg_temp.paste(name_bg, (0, 0), name_bg)

                # 星数
                for i in range(3):
                    if i + 1 <= floor.star:
                        star_bg = Image.open(TEXT_PATH / "star_full.png")
                    else:
                        star_bg = Image.open(TEXT_PATH / "star_empty.png")
                    abyss_bg_temp.paste(star_bg, (10 + i * 70, 50), star_bg)

                if floor.roleList:
                    for role_index, _role in enumerate(floor.roleList):
                        role = next(
                            (role for role in role_info_list if role.roleId == _role.roleId),
                            None,
                        )
                        if not role:
                            continue

                        avatar = await draw_pic(role.roleId)
                        char_bg = Image.open(TEXT_PATH / f"char_bg{role.starLevel}.png")
                        slot = Image.new("RGBA", char_bg.size, (255, 255, 255, 0))
                        slot.paste(avatar, (0, 0), avatar)
                        slot.alpha_composite(char_bg)
                        char_bg = slot
                        chain_num, chain_name, _ = lookup_chain_with_rover(role_detail_info_map, rover_map, role.roleId)
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

                        paste_skill_branch_emblem(char_bg, role.roleId, _role.skillBranchIndex, (138, 130))

                        abyss_bg_temp.alpha_composite(char_bg, (300 + role_index * 150, -20))

                abyss_bg.paste(abyss_bg_temp, (0, 0), abyss_bg_temp)
                frame.paste(abyss_bg, (80, yset), abyss_bg)
                yset += 141
            yset += 50
        break
    else:
        if not is_self_ck:
            return ABYSS_ERROR_MESSAGE_LOGIN
        return ABYSS_ERROR_MESSAGE_NO_DATA

    card_img.paste(frame, (0, 210), frame)

    card_img = add_footer(card_img, 600, 20)
    card_img = await convert_img(card_img)
    await upload_abyss_record(is_self_ck, uid, difficultyName, abyss_data)
    return card_img


async def upload_abyss_record(
    is_self_ck: bool,
    waves_id: str,
    difficultyName: str,
    abyss_data: AbyssChallenge,
):
    from ..wutheringwaves_config import WutheringWavesConfig

    WavesToken = WutheringWavesConfig.get_config("WavesToken").data
    if not WavesToken:
        return

    if difficultyName != "深境区":
        return
    if not abyss_data:
        return
    if not abyss_data.difficultyList:
        return
    if not is_self_ck:
        return
    abyss_record = []
    for _abyss in abyss_data.difficultyList:
        if _abyss.difficultyName != difficultyName:
            continue
        for tower_index, tower in enumerate(_abyss.towerAreaList):
            if not tower.floorList:
                continue
            # 深境之塔(中)四层等同难度, 各层分别上传(m1~m4); 残响/回音为爬塔, 只取顶层(l4/r4)
            if tower.areaName == "深境之塔":
                floors = tower.floorList
            else:
                if len(tower.floorList) <= 1:
                    continue
                floors = [tower.floorList[-1]]
            for floor in floors:
                if floor.star == 3 and floor.roleList:
                    abyss_record.append(
                        AbyssDetail.model_validate(
                            {
                                "area_type": f"{ABYSS_TYPE_MAP[tower.areaName]}{floor.floor}",
                                "area_name": tower.areaName,
                                "floor": floor.floor,
                                "char_ids": [role.roleId for role in floor.roleList],
                            }
                        )
                    )

    if not abyss_record:
        return
    abyss_item = AbyssItem.model_validate(
        {
            "waves_id": waves_id,
            "abyss_record": abyss_record,
            "version": get_version(dynamic=True, waves_id=waves_id, char_info=abyss_record),
        }
    )
    # logger.info(f"[鸣潮·深塔渲染] 上传深塔记录: {abyss_item.model_dump()}")
    push_item(QUEUE_ABYSS_RECORD, abyss_item.model_dump())
