from typing import Any, Dict, List
import time

from gsuid_core.sv import SV
from gsuid_core.aps import scheduler
from gsuid_core.bot import Bot
from gsuid_core.gss import gss
from gsuid_core.config import core_config
from gsuid_core.logger import logger
from gsuid_core.models import Event

from .deal import add_cookie, get_cookie, refresh_bind, delete_cookie
from ..utils.util import get_hide_uid_pref, hide_uid
from ..utils.button import WavesButton
from ..utils.constants import WAVES_GAME_ID
from ..utils.database.models import WavesBind, WavesUser, WavesStaminaRecord
from ..utils.database.waves_user_activity import WavesUserActivity
from ..wutheringwaves_config import PREFIX, WutheringWavesConfig
from .login_succ import login_success_msg

waves_bind_uid = SV("鸣潮绑定特征码", priority=10)
waves_add_ck = SV("鸣潮添加token", priority=3)
waves_del_ck = SV("鸣潮删除token", priority=3)
waves_del_mem = SV("鸣潮删除群成员", priority=3)
waves_get_ck = SV("waves获取ck", area="DIRECT")
waves_del_all_invalid_ck = SV("鸣潮删除无效token", priority=1, pm=1)
waves_refresh_bind = SV("waves刷新绑定", priority=5)


def get_ck_and_devcode(text: str, split_str: str = ",") -> tuple[str, str]:
    ck, devcode = "", ""
    try:
        parts = text.split(split_str, maxsplit=1)
        ck = parts[0].strip()
        devcode = parts[1].strip() if len(parts) > 1 else ""
    except ValueError:
        pass
    return ck, devcode


msg_notify = [
    "[鸣潮] 格式错误！",
    f"例如【{PREFIX}添加token token】或【{PREFIX}添加token token,did】",
    "当前did位数不正确（32位、36位、40位），如无did则不需要加逗号，请检查后重新添加",
]


@waves_add_ck.on_command(("添加CK", "添加ck", "添加Token", "添加token", "添加TOKEN", "token登录", "Token登录"), block=True)
async def send_waves_add_ck_msg(bot: Bot, ev: Event):
    at_sender = True if ev.group_id else False
    text = ev.text.strip()

    ck, did = "", ""
    for i in ["，", ","]:
        if i in text:
            ck, did = get_ck_and_devcode(text, split_str=i)
            break
    if not ck:
        ck = text.strip()

    if did and len(did) not in (32, 36, 40):
        msg = "\n".join(msg_notify)
        return await bot.send(
            (" " if at_sender else "") + msg,
            at_sender,
        )

    if not ck:
        from .add_token_web import add_token_web

        return await add_token_web(bot, ev)

    ck_msg = await add_cookie(ev, ck, did, is_login=False)
    # 严格匹配 deal.add_cookie 的成功文案，避免 "请求成功" 等内部占位被误判为成功
    if isinstance(ck_msg, str) and ("登录成功" in ck_msg or "记录成功" in ck_msg):
        # 先发绑定概要
        await bot.send((" " if at_sender else "") + ck_msg.rstrip("\n"), at_sender)

        user = await WavesUser.get_user_by_attr(ev.user_id, ev.bot_id, "cookie", ck, game_id=WAVES_GAME_ID)
        if user:
            return await login_success_msg(bot, ev, user)
        return

    ck_msg = ck_msg.rstrip("\n") if isinstance(ck_msg, str) else ck_msg
    await bot.send((" " if at_sender and isinstance(ck_msg, str) else "") + ck_msg if isinstance(ck_msg, str) else ck_msg, at_sender)


@waves_del_ck.on_command(("删除ck", "删除CK", "删除Token", "删除token", "删除TOKEN"), block=True)
async def send_waves_del_ck_msg(bot: Bot, ev: Event):
    at_sender = True if ev.group_id else False
    uid = ''.join(filter(str.isdigit, ev.text.strip()))
    if not uid or len(uid) != 9:
        msg = f"[鸣潮] 该命令末尾需要跟正确的特征码!\n例如【{PREFIX}删除token123456】"
        return await bot.send(
            (" " if at_sender else "") + msg,
            at_sender,
        )
    del_msg = await delete_cookie(ev, uid)
    del_msg = del_msg.rstrip("\n") if isinstance(del_msg, str) else del_msg
    await bot.send((" " if at_sender and isinstance(del_msg, str) else "") + del_msg if isinstance(del_msg, str) else del_msg, at_sender)


@waves_get_ck.on_fullmatch(("获取ck", "获取CK", "获取Token", "获取token", "获取TOKEN"), block=True)
async def send_waves_get_ck_msg(bot: Bot, ev: Event):
    await bot.send(await get_cookie(bot, ev))


@waves_refresh_bind.on_fullmatch(("刷新绑定"), block=True)
async def send_waves_refresh_bind_msg(bot: Bot, ev: Event):
    at_sender = True if ev.group_id else False
    msg = await refresh_bind(ev)
    msg = msg.rstrip("\n") if isinstance(msg, str) else msg
    await bot.send((" " if at_sender and isinstance(msg, str) else "") + msg if isinstance(msg, str) else msg, at_sender)


@waves_del_all_invalid_ck.on_fullmatch(("删除无效token"), block=True)
async def delete_all_invalid_cookie(bot: Bot, ev: Event):
    at_sender = True if ev.group_id else False
    del_len = await WavesUser.delete_all_invalid_cookie()
    msg = f"[鸣潮] 已删除无效token【{del_len}】个"
    await bot.send((" " if at_sender else "") + msg, at_sender)


@waves_del_mem.on_regex(("^删除群成员\\s*(?:[uU][iI][dD])?\\s*(?P<uid>\\d+)$",), block=True)
async def waves_delete_group_member(bot: Bot, ev: Event):
    if not ev.group_id:
        return await bot.send("[鸣潮] 该命令仅限群聊使用")

    if ev.user_pm is None or ev.user_pm > 3:
        return await bot.send("[鸣潮] 需要群管理才可删除")

    target_uid = ev.regex_dict.get("uid") if hasattr(ev, "regex_dict") else None
    if not target_uid:
        return await bot.send(f"[鸣潮] 格式错误，例如：{PREFIX}删除群成员123456789（游戏UID）")
    binds = await WavesBind.get_binds_by_uid(target_uid)
    if not binds:
        return await bot.send(f"[鸣潮] 未找到 UID {hide_uid(target_uid)} 的绑定记录")

    updated = 0
    for bind in binds:
        uid_list = [u for u in (bind.uid or "").split("_") if u]
        pgr_uid_list = [u for u in (bind.pgr_uid or "").split("_") if u]
        if target_uid not in uid_list and target_uid not in pgr_uid_list:
            continue

        group_list = [g for g in (bind.group_id or "").split("_") if g]
        if ev.group_id not in group_list:
            continue

        group_list = [g for g in group_list if g != ev.group_id]
        new_group_id = "_".join(group_list)
        await WavesBind.update_data(
            user_id=bind.user_id,
            bot_id=bind.bot_id,
            **{"group_id": new_group_id},
        )
        updated += 1

    if updated == 0:
        return await bot.send(f"[鸣潮] UID {hide_uid(target_uid)} 在本群无绑定记录")

    return await bot.send(f"[鸣潮] 已移除 UID {hide_uid(target_uid)} 在本群的 {updated} 条绑定记录")


@waves_del_mem.on_regex(("^(删除|清除|清理)不活跃(?:群成员)?\\s*$",), block=True)
async def waves_delete_inactive_group_members(bot: Bot, ev: Event):
    if not ev.group_id:
        return await bot.send("[鸣潮] 该命令仅限群聊使用")

    if ev.user_pm is None or ev.user_pm > 3:
        return await bot.send("[鸣潮] 需要群管理才可删除")

    binds = await WavesBind.get_group_all_uid(ev.group_id)
    if not binds:
        return await bot.send(f"[鸣潮] 群【{ev.group_id}】暂无绑定记录")

    active_days = WutheringWavesConfig.get_config("ActiveUserDays").data
    threshold_time = int(time.time()) - (active_days * 24 * 60 * 60)
    bot_self_id = ev.bot_self_id or ""

    uid_to_user_pairs: Dict[str, set[tuple[str, str]]] = {}

    for bind in binds:
        if not bind.user_id:
            continue
        platform = bind.bot_id or ev.bot_id

        uid_list = [u for u in (bind.uid or "").split("_") if u]
        pgr_uid_list = [u for u in (bind.pgr_uid or "").split("_") if u]
        for uid in uid_list + pgr_uid_list:
            uid_to_user_pairs.setdefault(uid, set()).add((bind.user_id, platform))

    if not uid_to_user_pairs:
        return await bot.send(f"[鸣潮] 群【{ev.group_id}】暂无绑定记录")

    inactive_uids: set[str] = set()
    for uid, user_pairs in uid_to_user_pairs.items():
        latest_time = None
        for user_id, platform in user_pairs:
            last_active_time = await WavesUserActivity.get_user_last_active_time(
                user_id, platform, bot_self_id
            )
            if last_active_time is not None:
                if latest_time is None or last_active_time > latest_time:
                    latest_time = last_active_time
        # 无活跃记录视为宽限期, 不入集合
        if latest_time is not None and latest_time < threshold_time:
            inactive_uids.add(uid)

    if not inactive_uids:
        return await bot.send("[鸣潮] 本群暂无不活跃群成员")

    updated = 0
    for bind in binds:
        group_list = [g for g in (bind.group_id or "").split("_") if g]
        if ev.group_id not in group_list:
            continue
        uid_list = [u for u in (bind.uid or "").split("_") if u]
        pgr_uid_list = [u for u in (bind.pgr_uid or "").split("_") if u]
        # 任一 uid 仍活跃则整行豁免, 避免小号拖累大号
        all_uids = uid_list + pgr_uid_list
        if not all_uids or not all(uid in inactive_uids for uid in all_uids):
            continue

        new_group_list = [g for g in group_list if g != ev.group_id]
        await WavesBind.update_data(
            user_id=bind.user_id,
            bot_id=bind.bot_id,
            **{"group_id": "_".join(new_group_list)},
        )
        updated += 1
        
    logger.info(f"[鸣潮·用户] 已移除不活跃群成员 UID 数：{len(inactive_uids)}，更新绑定记录数：{updated}")

    if updated == 0:
        return await bot.send("[鸣潮] 本群暂无可清理的不活跃群成员")
    return await bot.send(
        f"[鸣潮] 已移除不活跃群成员，UID 数：{len(inactive_uids)}"
    )


@scheduler.scheduled_job("cron", hour=23, minute=30)
async def auto_delete_all_invalid_cookie():
    try:
        DelInvalidCookie = WutheringWavesConfig.get_config("DelInvalidCookie").data
        if not DelInvalidCookie:
            return
        del_len = await WavesUser.delete_all_invalid_cookie()
        if del_len == 0:
            return
        msg = f"[鸣潮] 删除无效token【{del_len}】个"
        config_masters = core_config.get_config("masters")

        if not config_masters:
            return
        for bot_id in gss.active_bot:
            try:
                await gss.active_bot[bot_id].target_send(
                    msg,
                    "direct",
                    config_masters[0],
                    "onebot",
                    "",
                    "",
                )
            except Exception as e:
                logger.warning(f"[鸣潮·用户] 推送主人删除结果失败 bot_id={bot_id}: {e}")
            break
        logger.info(f"[鸣潮·用户] 推送主人删除无效token结果: {msg}")
    except Exception as e:
        logger.exception(f"[鸣潮·用户] cron auto_delete_all_invalid_cookie 异常: {e}")


@waves_bind_uid.on_command(
    (
        "绑定",
        "切换",
        "删除全部特征码",
        "删除全部UID",
        "删除",
        "查看",
    ),
    block=True,
)
async def send_waves_bind_uid_msg(bot: Bot, ev: Event):
    uid = ''.join(filter(str.isdigit, ev.text.strip()))
    qid = ev.user_id

    at_sender = True if ev.group_id else False

    if "绑定" in ev.command:
        if not uid:
            msg = f"该命令需要带上正确的9位uid!\n如：{PREFIX}绑定123456789"
            return await bot.send((" " if at_sender else "") + msg, at_sender)
        uid_list = await WavesBind.get_uid_list_by_game(qid, ev.bot_id)
        cookie_uid_list = await WavesUser.select_user_cookie_uids(qid)
        if uid_list and uid not in uid_list:
            difference_uid_list = set(uid_list).difference(set(cookie_uid_list or []))
            max_bind_num: int = WutheringWavesConfig.get_config("MaxBindNum").data
            if len(difference_uid_list) >= max_bind_num:
                msg = "[鸣潮] 绑定特征码达到上限"
                return await bot.send((" " if at_sender else "") + msg, at_sender)

        code = await WavesBind.insert_waves_uid(qid, ev.bot_id, uid, ev.group_id, lenth_limit=9)
        if code == 0 or code == -2:
            retcode = await WavesBind.switch_uid_by_game(qid, ev.bot_id, uid)
        return await send_diff_msg(
            bot,
            code,
            {
                0: f"[鸣潮] 特征码[{hide_uid(uid)}]绑定成功！\n\n当前仅支持查询部分信息，完整功能请使用【{PREFIX}登录】\n使用【{PREFIX}查看】查看已绑定的特征码\n使用【{PREFIX}刷新面板】更新角色面板\n更新角色面板后可以使用【{PREFIX}暗主排行】查询暗主排行",
                -1: f"[鸣潮] 特征码[{hide_uid(uid)}]的位数不正确！",
                -2: f"[鸣潮] 特征码[{hide_uid(uid)}]已经绑定过了！",
                -3: "[鸣潮] 你输入了错误的格式!",
            },
            at_sender=at_sender,
        )
    elif "切换" in ev.command:
        retcode = await WavesBind.switch_uid_by_game(qid, ev.bot_id, uid)
        if retcode == 0:
            uid_list = await WavesBind.get_uid_list_by_game(qid, ev.bot_id)
            if uid_list:
                _buttons: List[Any] = []
                for uid in uid_list:
                    _buttons.append(WavesButton(hide_uid(uid), f"切换{uid}"))
                return await bot.send_option(f" [鸣潮] 切换特征码[{hide_uid(uid_list[0])}]成功！", _buttons)
            else:
                msg = "[鸣潮] 尚未绑定任何特征码"
                return await bot.send((" " if at_sender else "") + msg, at_sender)
        else:
            msg = f"[鸣潮] 尚未绑定该特征码[{hide_uid(uid)}]"
            return await bot.send((" " if at_sender else "") + msg, at_sender)
    elif "查看" in ev.command:
        uid_list = await WavesBind.get_uid_list_by_game(qid, ev.bot_id)
        if uid_list:
            uids = "\n".join(hide_uid(u) for u in uid_list)
            buttons: List[Any] = []
            for uid in uid_list:
                buttons.append(WavesButton(hide_uid(uid), f"切换{uid}"))
            return await bot.send_option(f" [鸣潮] 绑定的特征码列表为：\n{uids}", buttons)
        else:
            msg = "[鸣潮] 尚未绑定任何特征码"
            return await bot.send((" " if at_sender else "") + msg, at_sender)
    elif "删除全部" in ev.command:
        retcode = await WavesBind.update_data(
            user_id=qid,
            bot_id=ev.bot_id,
            **{WavesBind.get_gameid_name(None): None},
        )
        if retcode == 0:
            try:
                await WavesStaminaRecord.delete_by_user(qid, ev.bot_id)
            except Exception:
                logger.exception("[鸣潮·用户] 删除全部特征码时清理体力记录失败")
            msg = "[鸣潮] 删除全部特征码成功！"
            return await bot.send((" " if at_sender else "") + msg, at_sender)
        else:
            msg = "[鸣潮] 尚未绑定任何特征码"
            return await bot.send((" " if at_sender else "") + msg, at_sender)
    else:
        if not uid:
            msg = f"[鸣潮] 该命令末尾需要跟正确的特征码!\n例如【{PREFIX}删除123456】"
            return await bot.send(
                (" " if at_sender else "") + msg,
                at_sender,
            )
        user_pref = await get_hide_uid_pref(uid, qid, ev.bot_id)
        data = await WavesBind.delete_uid(qid, ev.bot_id, uid)
        return await send_diff_msg(
            bot,
            data,
            {
                0: f"[鸣潮] 删除特征码[{hide_uid(uid, user_pref)}]成功！",
                -1: f"[鸣潮] 该特征码[{hide_uid(uid, user_pref)}]不在已绑定列表中！",
            },
            at_sender=at_sender,
        )


async def send_diff_msg(bot: Bot, code: Any, data: Dict, at_sender=False):
    for retcode in data:
        if code == retcode:
            msg = data[retcode] if isinstance(data[retcode], str) else data[retcode]
            if at_sender and isinstance(msg, str):
                msg = " " + msg
            return await bot.send(msg, at_sender)
