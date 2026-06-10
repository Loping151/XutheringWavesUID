import re
import json
import shutil
import asyncio
from datetime import datetime

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment
from gsuid_core.data_store import get_res_path
from gsuid_core.logger import logger

from ..utils.single_flight import SingleFlightLock
from ..utils.util import get_hide_uid_pref, hide_uid
from .gacha_handler import (
    fetch_mcgf_data,
    fetch_xhh_data,
    merge_gacha_data,
    merge_xhh_data,
)
from .get_gachalogs import (
    save_gachalogs,
    export_gachalogs,
    import_gachalogs,
    prune_gacha_backups,
)
from .draw_gachalogs import draw_card, draw_card_help
from .web_view import (  # 导入即注册路由
    _is_feature_enabled as _gacha_web_enabled,
    feature_disabled_msg,
    make_gacha_web_url,
)
from ..utils.waves_api import waves_api
from ..utils.error_reply import ERROR_CODE, WAVES_CODE_102, WAVES_CODE_103
from ..utils.database.models import WavesBind
from ..wutheringwaves_config import PREFIX
from ..utils.resource.RESOURCE_PATH import GACHA_BACKUP_PATH, PLAYER_PATH
from ..wutheringwaves_rank.draw_gacha_rank_card import draw_gacha_rank_card

sv_gacha_log = SV("waves抽卡记录")
sv_gacha_help_log = SV("waves抽卡记录帮助")
sv_gacha_rank = SV("waves抽卡排行", priority=0)
sv_get_gachalog_by_link = SV("waves导入抽卡链接") # , area="DIRECT"
sv_update_gacha_log = SV("waves更新抽卡记录")
sv_import_gacha_log = SV("waves导入抽卡记录") # , area="DIRECT"
sv_export_json_gacha_log = SV("waves导出抽卡记录")
sv_delete_gacha_log = SV("waves删除抽卡记录")
sv_delete_import_gacha_log = SV("waves删除抽卡导入", pm=0)
sv_gacha_web = SV("waves抽卡网页")

ERROR_MSG_NOTIFY = f"请给出正确的抽卡记录链接, 可发送【{PREFIX}抽卡帮助】"
ERROR_MSG_IMPORT_TYPE = (
    "请指定导入类型，支持的方式：\n"
    f"{PREFIX}导入工坊抽卡记录+uid\n"
    f"{PREFIX}导入小黑盒抽卡记录+uid\n"
    "请将【+uid】替换为对应的9位数字UID"
)
IMPORT_UID_RE = re.compile(r"^\s*\+?\s*(\d{9})\s*$")


def _migrate_legacy_gacha_backups():
    """一次性把旧路径的抽卡备份迁移到 GACHA_BACKUP_PATH。"""
    def _move(src, target_dir, dst_name):
        target_dir.mkdir(parents=True, exist_ok=True)
        dst = target_dir / dst_name
        while dst.exists():
            dst = target_dir / f"{dst.stem}_dup{dst.suffix}"
        try:
            shutil.move(str(src), str(dst))
        except Exception as e:
            logger.warning(f"[鸣潮·抽卡备份迁移] 移动失败 {src} -> {dst}: {e}")

    # 旧路径1: data/backup/gacha_backup/{uid}/(gacha_logs*.json)  → delete 备份
    legacy_delete_root = get_res_path() / "backup" / "gacha_backup"
    if legacy_delete_root.exists():
        for uid_dir in legacy_delete_root.iterdir():
            if not uid_dir.is_dir():
                continue
            for src in uid_dir.glob("gacha_logs*.json"):
                ts = datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d.%H%M%S")
                _move(src, GACHA_BACKUP_PATH / uid_dir.name, f"delete_gacha_logs_{ts}.json")
            prune_gacha_backups(uid_dir.name, "delete")
            try:
                uid_dir.rmdir()
            except OSError:
                pass
        try:
            legacy_delete_root.rmdir()
        except OSError:
            pass

    # 旧路径2: PLAYER_PATH/{uid}/{import|update}_gacha_logs_*.json
    if PLAYER_PATH.exists():
        for uid_dir in PLAYER_PATH.iterdir():
            if not uid_dir.is_dir():
                continue
            for type_ in ("import", "update"):
                moved = False
                for src in uid_dir.glob(f"{type_}_gacha_logs_*.json"):
                    _move(src, GACHA_BACKUP_PATH / uid_dir.name, src.name)
                    moved = True
                if moved:
                    prune_gacha_backups(uid_dir.name, type_)

    # 旧路径3: MAIN_PATH/backup/{uid}/(delete|import|update)_gacha_logs_*.json
    # 新路径加了 gacha_backup 子层避免与其他模块同名 backup 撞目录
    legacy_flat_root = GACHA_BACKUP_PATH.parent
    if legacy_flat_root.exists():
        for uid_dir in legacy_flat_root.iterdir():
            if not uid_dir.is_dir() or uid_dir.name == GACHA_BACKUP_PATH.name:
                continue
            if not uid_dir.name.isdigit():
                continue
            moved_types = set()
            for src in uid_dir.glob("*_gacha_logs_*.json"):
                _move(src, GACHA_BACKUP_PATH / uid_dir.name, src.name)
                prefix = src.name.split("_", 1)[0]
                if prefix in ("import", "update", "delete"):
                    moved_types.add(prefix)
            for t in moved_types:
                prune_gacha_backups(uid_dir.name, t)
            try:
                uid_dir.rmdir()
            except OSError:
                pass


_migrate_legacy_gacha_backups()

# 导入抽卡记录的触发锁
gacha_import_lock = SingleFlightLock()
gacha_json_import_lock = SingleFlightLock()


def _is_bot_self_event(ev: Event) -> bool:
    bot_self_id = str(ev.bot_self_id or "")
    if not bot_self_id:
        return False

    sender_ids = {str(ev.user_id or "")}
    sender = getattr(ev, "sender", None) or {}
    for key in ("user_id", "userId", "id", "sender_id", "uin", "open_id"):
        value = sender.get(key)
        if value:
            sender_ids.add(str(value))

    return bot_self_id in sender_ids


def _parse_import_uid(text: str):
    match = IMPORT_UID_RE.fullmatch(text)
    return match.group(1) if match else None


async def _merge_mcgf_gacha(bot: Bot, ev: Event, uid: str, target_uid: str):
    try:
        latest_data = await fetch_mcgf_data(target_uid)
        if not latest_data:
            return await bot.send("获取工坊数据失败或数据为空")

        export_res = await export_gachalogs(uid)
        original_data = {"info": {}, "list": []}

        if export_res["retcode"] == "ok":
            import aiofiles

            async with aiofiles.open(export_res["url"], "r", encoding="utf-8") as f:
                original_data = json.loads(await f.read())

        if len(original_data.get("list", [])) == 0:
            return await bot.send(
                "当前抽卡记录无有效记录，无法对齐导入数据，请先用链接导入抽卡记录后再尝试合并！"
            )

        if not original_data["info"].get("uid") == latest_data["data"].get("uid"):
            return await bot.send("导入数据UID与当前UID不匹配，无法合并！")
        merged_data = await asyncio.to_thread(
            merge_gacha_data, original_data, latest_data
        )

        merged_json_str = json.dumps(merged_data, ensure_ascii=False)
        im = await import_gachalogs(
            ev, merged_json_str, "json", uid, force_overwrite=True
        )
        if im.startswith("🌱"):
            await bot.send(
                "导入仅包含早于本地记录的部分，此后请使用链接导入更新数据，"
                "或删除抽卡记录后再次链接导入+合并！"
            )
        return await bot.send(im)

    except Exception as e:
        logger.exception(f"[鸣潮·抽卡导入] 工坊合并失败 uid={uid}: {e}")
        return await bot.send("处理过程中发生错误，请稍后重试")


@sv_get_gachalog_by_link.on_command("导入抽卡记录", block=True)
async def send_gacha_import_type(bot: Bot, ev: Event):
    return await bot.send(ERROR_MSG_IMPORT_TYPE)


@sv_get_gachalog_by_link.on_command("导入工坊抽卡记录", block=True)
async def get_gacha_log_by_mcgf(bot: Bot, ev: Event):
    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(ERROR_CODE[WAVES_CODE_103])

    target_uid = _parse_import_uid(ev.text)
    if not target_uid:
        return await bot.send(
            f"请带上UID，例如：{PREFIX}导入工坊抽卡记录123456789"
        )

    if not gacha_import_lock.acquire(f"{ev.user_id}_{uid}"):
        return
    try:
        return await _merge_mcgf_gacha(bot, ev, uid, target_uid)
    finally:
        gacha_import_lock.release(f"{ev.user_id}_{uid}")


@sv_get_gachalog_by_link.on_command("导入抽卡链接", block=True)
async def get_gacha_log_by_link(bot: Bot, ev: Event):
    # 没有uid 就别导了吧
    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(ERROR_CODE[WAVES_CODE_103])

    user_pref = await get_hide_uid_pref(uid, ev.user_id, ev.bot_id)

    if not gacha_import_lock.acquire(f"{ev.user_id}_{uid}"):
        return
    try:
        raw = ev.text.strip()
        if not raw:
            return await bot.send(ERROR_MSG_NOTIFY)

        text = re.sub(r'["\n\t ]+', "", raw)
        if "https://" in text:
            # 使用正则表达式匹配参数
            match_record_id = re.search(r"record_id=([a-zA-Z0-9]+)", text)
            match_player_id = re.search(r"player_id=(\d+)", text)
        elif "{" in text:
            match_record_id = re.search(r"recordId:([a-zA-Z0-9]+)", text)
            match_player_id = re.search(r"playerId:(\d+)", text)
        elif "recordId=" in text:
            match_record_id = re.search(r"recordId=([a-zA-Z0-9]+)", text)
            match_player_id = re.search(r"playerId=(\d+)", text)
        else:
            match_record_id = re.search(r"recordId=([a-zA-Z0-9]+)", "recordId=" + text)
            match_player_id = ""

        # 提取参数值
        record_id = match_record_id.group(1) if match_record_id else None
        player_id = match_player_id.group(1) if match_player_id else None

        if not record_id or len(record_id) != 32:
            return await bot.send(ERROR_MSG_NOTIFY)

        if player_id and player_id != uid:
            ERROR_MSG = f"请保证抽卡链接的特征码与当前正在使用的特征码一致\n\n请使用以下命令核查:\n{PREFIX}查看\n{PREFIX}切换{hide_uid(player_id, user_pref)}"
            return await bot.send(ERROR_MSG)

        is_force = False
        if ev.command.startswith("强制"):
            await bot.logger.info("[鸣潮·抽卡] 本次为强制刷新")
            is_force = True
        await bot.send(f"UID{hide_uid(uid, user_pref)}开始执行[更新抽卡记录]，需要一定时间，请稍等!\n官方仅保存近180天抽卡记录，仅更新该部分。")
        im = await save_gachalogs(ev, uid, record_id, is_force)

        if im.startswith("🌱"):
            card_img = await draw_card(uid, ev)
            if isinstance(card_img, str):
                await bot.send(im)
            else:
                await bot.send([im, MessageSegment.image(card_img)])
        else:
            await bot.send(im)
    finally:
        gacha_import_lock.release(f"{ev.user_id}_{uid}")


@sv_get_gachalog_by_link.on_command("导入小黑盒抽卡记录", block=True)
async def get_gacha_log_by_xhh(bot: Bot, ev: Event):
    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(ERROR_CODE[WAVES_CODE_103])

    heybox_id = ev.text.strip()
    if not heybox_id:
        return await bot.send(
            f"请带上小黑盒ID，例如：{PREFIX}导入小黑盒抽卡记录12345678"
        )

    if not gacha_import_lock.acquire(f"{ev.user_id}_{uid}"):
        return
    try:
        xhh_data = await fetch_xhh_data(heybox_id)
        if not xhh_data:
            return await bot.send(
                "获取小黑盒数据失败，请检查ID是否正确或该用户是否已导入鸣潮抽卡记录"
            )

        xhh_uid = str(xhh_data.get("user_info", {}).get("uid", ""))
        if xhh_uid != uid:
            return await bot.send(
                f"小黑盒对应的鸣潮UID为{xhh_uid}，与当前绑定UID {uid}不匹配！"
            )

        export_res = await export_gachalogs(uid)
        original_data = {"info": {}, "list": []}

        if export_res["retcode"] == "ok":
            import aiofiles

            async with aiofiles.open(export_res["url"], "r", encoding="utf-8") as f:
                original_data = json.loads(await f.read())

        if len(original_data.get("list", [])) == 0:
            return await bot.send(
                "当前抽卡记录无有效记录，无法对齐导入数据，请先用链接导入抽卡记录后再尝试合并！"
            )

        merged_data = await asyncio.to_thread(merge_xhh_data, original_data, xhh_data)

        merged_json_str = json.dumps(merged_data, ensure_ascii=False)
        im = await import_gachalogs(
            ev, merged_json_str, "json", uid, force_overwrite=True
        )
        if im.startswith("🌱"):
            await bot.send(
                "小黑盒导入仅补充早于本地记录的历史数据，不会覆盖已有记录！"
            )
        return await bot.send(im)

    except Exception as e:
        logger.exception(f"[鸣潮·小黑盒导入] 合并失败 uid={uid}: {e}")
        return await bot.send("处理过程中发生错误，请稍后重试")
    finally:
        gacha_import_lock.release(f"{ev.user_id}_{uid}")


async def pull_cloud_gacha(bot: Bot, ev: Event, uid: str, record_id: str):
    """用 recordId 走导入抽卡记录链路，复用导入锁，直接发送 save_gachalogs 结果。"""
    if not gacha_import_lock.acquire(f"{ev.user_id}_{uid}"):
        return
    try:
        im = await save_gachalogs(ev, uid, record_id)
        if im.startswith("🌱"):
            card_img = await draw_card(uid, ev)
            if isinstance(card_img, str):
                await bot.send(im)
            else:
                await bot.send([im, MessageSegment.image(card_img)])
        else:
            await bot.send(im)
    finally:
        gacha_import_lock.release(f"{ev.user_id}_{uid}")


@sv_update_gacha_log.on_fullmatch(("刷新抽卡记录", "更新抽卡记录", "刷新抽卡", "更新抽卡"), block=True)
async def update_gacha_log_by_cloud(bot: Bot, ev: Event):
    from ..utils.database.waves_gacha_cloud import WavesGachaCloud
    from ..wutheringwaves_login.cloud_login import fetch_cloud_record_id

    at_sender = True if ev.group_id else False

    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(ERROR_CODE[WAVES_CODE_103])

    user_pref = await get_hide_uid_pref(uid, ev.user_id, ev.bot_id)

    record = await WavesGachaCloud.select_record(ev.user_id, ev.bot_id, uid)
    if not record:
        return await bot.send(
            (" " if at_sender else "")
            + f"当前绑定 UID{hide_uid(uid, user_pref)} 未找到云鸣潮登录记录\n"
            + f"请确认已对该 UID 使用【{PREFIX}抽卡登录】",
            at_sender=at_sender,
        )

    record_id = await fetch_cloud_record_id(ev.user_id, ev.bot_id, uid)
    if not record_id:
        return await bot.send(
            (" " if at_sender else "")
            + f"UID{hide_uid(uid, user_pref)} 云鸣潮登录已失效或请求出错\n"
            + f"请稍后重试或重新使用【{PREFIX}抽卡登录】",
            at_sender=at_sender,
        )

    await bot.send(
        (" " if at_sender else "")
        + f"UID{hide_uid(uid, user_pref)} 正在更新抽卡记录，请稍候...\n"
        + "官方仅保存近180天抽卡记录，仅更新该部分。",
        at_sender=at_sender,
    )
    await pull_cloud_gacha(bot, ev, uid, record_id)


@sv_gacha_log.on_fullmatch(
    ("抽卡记录", "查看抽卡记录", "gacha", "ckjl"),
    to_ai="""查询用户已导入的鸣潮抽卡记录统计图（各卡池总抽数、距离保底、出货历史、欧非指数等）。

当用户问「我的抽卡 / 抽卡记录 / 出货怎样 / 多少保底了」时调用。需绑定 cookie + 已导入抽卡记录。
若没有抽卡数据，AI 应告知用户先 `抽卡帮助` 看如何导入。

Args:
    text: 无需参数。
""",
)
async def send_gacha_log_card_info(bot: Bot, ev: Event):
    await bot.logger.info("[鸣潮·抽卡] 开始执行 抽卡记录")
    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(ERROR_CODE[WAVES_CODE_103])
    _, ck = await waves_api.get_ck_result(uid, ev.user_id, ev.bot_id)
    if not ck:
        return await bot.send(ERROR_CODE[WAVES_CODE_102])

    im = await draw_card(uid, ev)
    await bot.send(im)


@sv_gacha_help_log.on_fullmatch("抽卡帮助")
async def send_gacha_log_help(bot: Bot, ev: Event):
    im = await draw_card_help()
    await bot.send(im)


@sv_import_gacha_log.on_file("json", prefix=False)
async def get_gacha_log_by_file(bot: Bot, ev: Event):
    if _is_bot_self_event(ev):
        await bot.logger.info(
            f"[鸣潮·JSON导入抽卡] 忽略机器人自身发送的JSON文件: {ev.file_name}"
        )
        return

    # 没有uid 就别导了吧
    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not uid:
        await bot.logger.info(f"[鸣潮·JSON导入抽卡] 用户 {ev.user_id} 未绑定UID，忽略此次导入")
        return
    _, ck = await waves_api.get_ck_result(uid, ev.user_id, ev.bot_id)
    if not ck:
        await bot.logger.info(f"[鸣潮·JSON导入抽卡] 用户 {ev.user_id} (UID:{uid}) 未登录或Cookie失效，忽略此次导入。这是为了避免被别人绑定uid后上传json覆盖真实玩家的抽卡数据")
        return

    json_lock_key = f"json_{uid}"
    user_lock_key = f"{ev.user_id}_{uid}"
    if not gacha_json_import_lock.acquire(json_lock_key):
        await bot.logger.info(
            f"[鸣潮·JSON导入抽卡] UID:{uid} 正在导入JSON文件，忽略并发文件: {ev.file_name}"
        )
        return
    if not gacha_import_lock.acquire(user_lock_key):
        gacha_json_import_lock.release(json_lock_key)
        return
    try:
        if ev.file and ev.file_type:
            # 误触就不说话了
            # await bot.send("正在尝试导入抽卡记录中，请耐心等待……")
            im = await import_gachalogs(ev, ev.file, ev.file_type, uid)
            return await bot.send(im)
        else:
            return await bot.send("导入抽卡记录异常...")
    finally:
        gacha_import_lock.release(user_lock_key)
        gacha_json_import_lock.release(json_lock_key)


@sv_export_json_gacha_log.on_fullmatch(("导出抽卡记录"))
async def send_export_gacha_info(bot: Bot, ev: Event):
    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(ERROR_CODE[WAVES_CODE_103])
    _, ck = await waves_api.get_ck_result(uid, ev.user_id, ev.bot_id)
    if not ck:
        return await bot.send(ERROR_CODE[WAVES_CODE_102])

    # await bot.send("🔜即将为你导出XutheringWavesUID抽卡记录文件，请耐心等待...")
    export = await export_gachalogs(uid)
    if export["retcode"] == "ok":
        file_name = export["name"]
        file_path = export["url"]
        await bot.send(MessageSegment.file(file_path, file_name))
        await bot.send("✅导出抽卡记录成功！")
    else:
        await bot.send("导出抽卡记录失败...")


@sv_delete_gacha_log.on_command("删除抽卡记录", block=True)
async def delete_gacha_history(bot: Bot, ev: Event):
    uid = ev.text.strip()
    if not uid.isdigit() or len(uid) != 9:
        return await bot.send(f"请附带特征码，例如【{PREFIX}删除抽卡记录123456789】")

    is_self, ck = await waves_api.get_ck_result(uid, ev.user_id, ev.bot_id)
    user_pref = await get_hide_uid_pref(uid, ev.user_id, ev.bot_id)
    if (not ck or not is_self) and not ev.user_pm == 0:
        return await bot.send(f"UID{hide_uid(uid, user_pref)}未登录或Cookie失效，不允许删除抽卡记录")

    if not gacha_import_lock.acquire(f"{ev.user_id}_{uid}"):
        return await bot.send(f"UID{hide_uid(uid, user_pref)}抽卡导入正在进行，请稍后再试")
    try:
        player_dir = PLAYER_PATH / uid
        gacha_log_file = player_dir / "gacha_logs.json"
        if not gacha_log_file.exists():
            return await bot.send(f"UID{hide_uid(uid, user_pref)}暂无抽卡记录文件")

        backup_dir = GACHA_BACKUP_PATH / uid
        backup_dir.mkdir(parents=True, exist_ok=True)
        dst_file = backup_dir / f"delete_gacha_logs_{datetime.now().strftime('%Y-%m-%d.%H%M%S')}.json"

        try:
            shutil.move(str(gacha_log_file), dst_file)
        except Exception as e:
            logger.exception(f"[鸣潮·抽卡删除] 移动失败 uid={uid}: {e}")
            return await bot.send("移动抽卡记录失败，请稍后重试")
        # 同步失效 stats 缓存，避免抽卡排行读到已删数据
        (player_dir / "gachaStats.json").unlink(missing_ok=True)
        prune_gacha_backups(uid, "delete")

        await bot.send(f"UID{hide_uid(uid, user_pref)}抽卡记录已删除！")
    finally:
        gacha_import_lock.release(f"{ev.user_id}_{uid}")


@sv_delete_import_gacha_log.on_command(("删除抽卡导入", "删除导入记录", "删除导入抽卡"), block=True)
async def delete_import_gacha_files(bot: Bot, ev: Event):
    delete_count = 0
    if GACHA_BACKUP_PATH.exists():
        for uid_dir in GACHA_BACKUP_PATH.iterdir():
            if not uid_dir.is_dir():
                continue
            for file_path in uid_dir.glob("import_gacha_logs_*.json"):
                try:
                    file_path.unlink()
                    delete_count += 1
                except Exception as e:
                    await bot.logger.warning(f"[鸣潮·抽卡] 删除导入记录失败 {file_path}: {e}")

    await bot.send(f"删除导入记录{delete_count}个")


@sv_gacha_rank.on_command(
    ("抽卡排行", "抽卡排名", "群抽卡排行", "群抽卡排名", "ckph", "ckpm"),
    block=True,
    to_ai="""查询本群抽卡排行（要求在群聊中使用）。

当用户在群聊问「群里谁最欧 / 抽卡排行欧 / 谁抽得最多」时调用。
text 可附筛选: "欧" (按5星出货数) / "非" (按歪4星比例) / "抽数" (按总抽数)。

私聊调用会被拒绝。

Args:
    text: 可选 "欧" / "非" / "抽数"，留空默认按抽数。
""",
)
async def send_gacha_rank_info(bot: Bot, ev: Event):
    if not ev.group_id:
        return await bot.send("请在群聊中使用本功能！")

    await bot.logger.info("[鸣潮·抽卡] 开始执行 抽卡排行")
    im = await draw_gacha_rank_card(bot, ev)
    await bot.send(im)


@sv_gacha_web.on_fullmatch(("抽卡页面", "抽卡网页", "网页抽卡记录", "抽卡记录网页"))
async def send_gacha_web_link(bot: Bot, ev: Event):
    if not _gacha_web_enabled():
        return await bot.send(feature_disabled_msg())

    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not uid:
        return await bot.send(ERROR_CODE[WAVES_CODE_103])

    user_pref = await get_hide_uid_pref(uid, ev.user_id, ev.bot_id)

    url, msg = await make_gacha_web_url(uid, ev)
    if not url:
        return await bot.send(msg)

    title = f"[鸣潮] UID{hide_uid(uid, user_pref)} 的抽卡记录网页"
    expire = "该链接 10 分钟内有效，过期后请重新发送指令。"
    if not ev.group_id and ev.bot_id == "onebot":
        # 私聊+onebot 不支持转发节点，回退为多行单条
        await bot.send("\n".join([title, url, expire]))
    else:
        await bot.send(MessageSegment.node([title, f" {url}", expire]))
