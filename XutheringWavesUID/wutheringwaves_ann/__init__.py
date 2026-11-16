import os
import time
import asyncio
from pathlib import Path

from gsuid_core.sv import SV
from gsuid_core.aps import scheduler
from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.server import on_core_start
from gsuid_core.subscribe import gs_subscribe

from .ann_card import ann_list_card, ann_detail_card
from .anniv_report import anniv_report
from ..utils.single_flight import SingleFlightLock
from ..utils.waves_api import waves_api
from ..utils.hint import error_reply
from ..utils.at_help import ruser_id
from ..utils.error_reply import WAVES_CODE_102
from ..utils.constants import WAVES_GAME_ID
from ..utils.database.models import WavesBind, WavesUser
from ..utils.database.waves_user_sdk import WavesUserSdk
from ..wutheringwaves_config import WutheringWavesConfig
from ..wutheringwaves_config.ann_config import get_ann_new_ids, set_ann_new_ids
from ..utils.resource.RESOURCE_PATH import ANN_CARD_PATH, BAKE_PATH, WIKI_CACHE_PATH, CALENDAR_CACHE_PATH
from ..wutheringwaves_resource.panel_editor.storage import PANEL_EDIT_TMP
from ..utils.database.waves_subscribe import WavesSubscribe
from ..utils.database.waves_group_activity import WavesGroupActivity, ANN_PUSH_GUARD
from ..utils.database.waves_user_activity import WavesUserActivity

sv_ann = SV("鸣潮公告")
sv_ann_clear_cache = SV("鸣潮公告缓存清理", pm=0, priority=3)
sv_ann_sub = SV("订阅鸣潮公告", pm=3)
sv_anniv_report = SV("鸣潮周年庆")

task_name_ann = "订阅鸣潮公告"
ann_minute_check: int = WutheringWavesConfig.get_config("AnnMinuteCheck").data
ann_push_tasks: set[asyncio.Task] = set()
_ann_poll_lock = asyncio.Lock()
ANN_PUSH_CONCURRENCY = 1

# 周年报告触发锁
anniv_report_lock = SingleFlightLock()


async def _send_ann_to_one_subscribe(subscribe, img, ann_id, semaphore: asyncio.Semaphore) -> bool:
    async with semaphore:
        try:
            await asyncio.sleep(3)
            token = ANN_PUSH_GUARD.set(True)
            try:
                await subscribe.send(img)  # type: ignore
            finally:
                ANN_PUSH_GUARD.reset(token)
            return True
        except Exception as e:
            target_id = subscribe.group_id or subscribe.user_id
            logger.exception(
                f"[鸣潮·公告] 公告 {ann_id} 推送到订阅 {target_id} 失败: {e}"
            )
            return False


async def _push_new_announcements(new_ann_need_send, datas) -> None:
    active_days = WutheringWavesConfig.get_config("AnnActiveGroupDays").data
    if active_days:
        try:
            active_gids = await WavesGroupActivity.get_active_group_ids(active_days)
            active_uids = await WavesUserActivity.get_active_user_ids(active_days)
            kept = [
                s for s in datas
                if (s.group_id and s.group_id in active_gids)
                or (not s.group_id and s.user_id in active_uids)
            ]
            skipped = len(datas) - len(kept)
            if skipped:
                logger.info(f"[鸣潮·公告] 跳过 {skipped} 个不活跃订阅")
            datas = kept
        except Exception as e:
            logger.warning(f"[鸣潮·公告] 活跃过滤失败, 不过滤: {e}")

    logger.info(
        f"[鸣潮·公告] 后台推送开始: 公告数={len(new_ann_need_send)}, 订阅数={len(datas)}"
    )
    semaphore = asyncio.Semaphore(ANN_PUSH_CONCURRENCY)
    # 渲染返字符串 (过期 / 未找到) 视为永久失败, 保留在已处理集合;
    # 渲染异常或订阅全失败视为临时失败, 回退让下次轮询重试。
    retry_ids: list = []

    for ann_id in new_ann_need_send:
        try:
            img = await ann_detail_card(ann_id, is_check_time=True)
            if isinstance(img, str):
                logger.info(f"[鸣潮·公告] 公告 {ann_id} 跳过推送: {img}")
                continue

            results = await asyncio.gather(
                *[
                    _send_ann_to_one_subscribe(subscribe, img, ann_id, semaphore)
                    for subscribe in datas
                ]
            )
            success_count = sum(1 for result in results if result is True)
            logger.info(
                f"[鸣潮·公告] 公告 {ann_id} 推送完成: {success_count}/{len(datas)}"
            )
            if datas and success_count == 0:
                retry_ids.append(ann_id)
        except Exception as e:
            logger.exception(f"[鸣潮·公告] 公告 {ann_id} 后台推送失败: {e}")
            retry_ids.append(ann_id)

    if retry_ids:
        existing = get_ann_new_ids() or []
        kept = [x for x in existing if x not in retry_ids]
        set_ann_new_ids(kept)
        logger.info(f"[鸣潮·公告] {len(retry_ids)} 个公告本轮未成功推送, 下次轮询重试")

    logger.info("[鸣潮·公告] 推送完毕")


def _create_ann_push_task(new_ann_need_send, datas) -> None:
    task = asyncio.create_task(_push_new_announcements(list(new_ann_need_send), list(datas)))
    ann_push_tasks.add(task)

    def _on_done(done_task: asyncio.Task) -> None:
        ann_push_tasks.discard(done_task)
        try:
            done_task.result()
        except Exception as e:
            logger.exception(f"[鸣潮·公告] 后台推送任务异常: {e}")

    task.add_done_callback(_on_done)


@sv_ann.on_command(
    "公告",
    to_ai="""查询鸣潮游戏公告。

无参数: 列出当前公告索引列表（图）。
text 是 "#<id>": 查看指定公告全文。例: text="#1456"。

当用户问「最新公告 / 鸣潮公告 / 看下公告」时调用列表；用户给具体编号时查明细。

Args:
    text: 留空查公告列表；或 "#<公告ID>" 查指定公告明细。例: "#1456"。
""",
)
async def ann_(bot: Bot, ev: Event):
    ann_id = ev.text
    if not ann_id or ann_id.strip() == "列表":
        img = await ann_list_card()
        return await bot.send(img)

    if ann_id.startswith("列表"):
        user_id = ann_id[2:].strip()
        if user_id in ["飞行雪绒", "爱弥斯"]:
            user_id = "30374418"
        if not user_id.isdigit():
            return await bot.send("请输入正确的用户ID")
        img = await ann_list_card(user_id=user_id)
        return await bot.send(img)

    ann_id = ann_id.replace("#", "")

    if ann_id.isdigit():
        img = await ann_detail_card(int(ann_id))
    else:
        from .utils.post_id_mapper import get_post_id_from_short
        post_id = get_post_id_from_short(ann_id)
        if post_id:
            if post_id.isdigit():
                img = await ann_detail_card(int(post_id))
            else:
                img = await ann_detail_card(post_id)
        else:
            return await bot.send("未找到对应的公告ID，请确认输入是否正确")

    return await bot.send(img)  # type: ignore


# @sv_anniv_report.on_fullmatch(("周年庆", "周年报", "周年回顾"), block=True)
async def anniv_report_(bot: Bot, ev: Event):
    """查询鸣潮 2 周年《探秘！记忆程序》报告"""
    logger.info("[鸣潮·公告] 开始执行[周年庆]")
    user_id = ruser_id(ev)
    uid = await WavesBind.get_uid_by_game(user_id, ev.bot_id)
    if not uid:
        # 强需要登录的功能, uid 缺失直接报 102 (登录提示), 避免用户绑定 uid 后再被告知"还要登录"
        return await bot.send(error_reply(WAVES_CODE_102))

    if not anniv_report_lock.acquire(f"{user_id}_{uid}"):
        return
    try:
        waves_token = WutheringWavesConfig.get_config("WavesToken").data
        if not waves_token:
            return await bot.send("未配置 WavesToken（总排行 token），请先在配置中填写")

        waves_user = await WavesUser.select_waves_user(
            uid, user_id, ev.bot_id, game_id=WAVES_GAME_ID
        )
        if not waves_user or not waves_user.cookie:
            return await bot.send(error_reply(WAVES_CODE_102))

        result = await anniv_report(
            uid,
            waves_token,
            waves_user.cookie,
            waves_user.did or "",
        )
        if isinstance(result, str):
            return await bot.send(result)
        if result.new_token or result.new_bat:
            update_data = {"status": ""}
            if result.new_token:
                update_data["cookie"] = result.new_token
            if result.new_bat:
                update_data["bat"] = result.new_bat
            if waves_user.did:
                update_data["did"] = waves_user.did
            await WavesUser.update_data_by_data(
                select_data={
                    "user_id": user_id,
                    "bot_id": ev.bot_id,
                    "uid": uid,
                    "game_id": WAVES_GAME_ID,
                },
                update_data=update_data,
            )
            if result.bat_expires_in > 0:
                await WavesUserSdk.update_bat_expires_at(
                    user_id,
                    ev.bot_id,
                    uid,
                    int(time.time()) + result.bat_expires_in,
                )
        from base64 import b64encode
        from gsuid_core.segment import MessageSegment
        nodes = [f"base64://{b64encode(p).decode()}" for p in result.parts]
        if ev.group_id:
            await bot.send(" 周年报告已完成", at_sender=True)
        await bot.send(MessageSegment.node(nodes))
    finally:
        anniv_report_lock.release(f"{user_id}_{uid}")


@sv_ann_sub.on_fullmatch(("订阅公告", "訂閱公告"))
async def sub_ann_(bot: Bot, ev: Event):

    if ev.group_id is None:
        return await bot.send("请在群聊中订阅")
    if not WutheringWavesConfig.get_config("WavesAnnOpen").data:
        return await bot.send("鸣潮公告推送功能已关闭")

    logger.info(f"[鸣潮·公告] 群 {ev.group_id} 订阅公告，bot_id={ev.bot_id}, bot_self_id={ev.bot_self_id}")

    if ev.group_id:
        await WavesSubscribe.check_and_update_bot(ev.group_id, ev.bot_id, ev.bot_self_id)

    data = await gs_subscribe.get_subscribe(task_name_ann)
    is_resubscribe = False
    if data:
        for subscribe in data:
            if subscribe.group_id == ev.group_id:
                await gs_subscribe.delete_subscribe("session", task_name_ann, ev)
                is_resubscribe = True
                logger.info(f"[鸣潮·公告] 群 {ev.group_id} 重新订阅，已删除旧订阅")
                break

    await gs_subscribe.add_subscribe(
        "session",
        task_name=task_name_ann,
        event=ev,
        extra_message="",
    )

    if is_resubscribe:
        await bot.send("已重新订阅鸣潮公告！")
    else:
        await bot.send("成功订阅鸣潮公告!")


@sv_ann_sub.on_fullmatch(("取消订阅公告", "取消公告", "退订公告", "取消訂閱公告", "退訂公告"))
async def unsub_ann_(bot: Bot, ev: Event):

    if ev.group_id is None:
        return await bot.send("请在群聊中取消订阅")

    data = await gs_subscribe.get_subscribe(task_name_ann)
    if data:
        for subscribe in data:
            if subscribe.group_id == ev.group_id:
                await gs_subscribe.delete_subscribe("session", task_name_ann, ev)
                return await bot.send("成功取消订阅鸣潮公告!")
    else:
        if not WutheringWavesConfig.get_config("WavesAnnOpen").data:
            return await bot.send("鸣潮公告推送功能已关闭")

    return await bot.send("未曾订阅鸣潮公告！")


@scheduler.scheduled_job("interval", minutes=ann_minute_check)
async def waves_check_ann_job():
    if not WutheringWavesConfig.get_config("WavesAnnOpen").data:
        return
    await check_waves_ann_state()


async def check_waves_ann_state():
    logger.info("[鸣潮·公告] 定时任务: 鸣潮公告查询..")
    datas = await gs_subscribe.get_subscribe(task_name_ann)
    if not datas:
        logger.info("[鸣潮·公告] 暂无群订阅")
        return

    if _ann_poll_lock.locked() or any(not t.done() for t in ann_push_tasks):
        logger.info("[鸣潮·公告] 上一轮轮询或推送尚未结束, 本轮跳过")
        return

    async with _ann_poll_lock:
        await _do_ann_poll(datas)


async def _do_ann_poll(datas) -> None:
    ids = get_ann_new_ids()
    new_ann_list = await waves_api.get_ann_list()
    if not new_ann_list:
        return

    new_ann_ids = [x["id"] for x in new_ann_list]
    if not ids:
        set_ann_new_ids(new_ann_ids)
        logger.info("[鸣潮·公告] 初始成功, 将在下个轮询中更新.")
        return

    new_ann_need_send = []
    for ann_id in new_ann_ids:
        if ann_id not in ids:
            new_ann_need_send.append(ann_id)

    if not new_ann_need_send:
        logger.info("[鸣潮·公告] 没有最新公告")
        return

    logger.info(f"[鸣潮·公告] 更新公告id: {new_ann_need_send}")
    save_ids = sorted(ids, reverse=True) + new_ann_ids
    set_ann_new_ids(list(set(save_ids)))

    _create_ann_push_task(new_ann_need_send, datas)
    logger.info("[鸣潮·公告] 已创建后台推送任务")


def clean_old_cache_files(directory: Path, days: int) -> tuple[int, float]:
    if not directory.exists():
        logger.debug(f"[鸣潮·缓存清理] 目录不存在: {directory}")
        return 0, 0.0

    current_time = time.time()
    cutoff_time = current_time - (days * 86400)  # 转换为秒

    deleted_count = 0
    freed_space = 0.0

    try:
        for file_path in directory.iterdir():
            if not file_path.is_file():
                continue

            file_ctime = file_path.stat().st_ctime

            if file_ctime < cutoff_time:
                try:
                    file_size = file_path.stat().st_size
                    file_path.unlink()
                    deleted_count += 1
                    freed_space += file_size
                    logger.debug(f"[鸣潮·缓存清理] 删除过期缓存文件: {file_path.name}")
                except Exception as e:
                    logger.error(f"[鸣潮·缓存清理] 删除文件失败 {file_path.name}: {e}")
    except Exception as e:
        logger.error(f"[鸣潮·缓存清理] 清理目录失败 {directory}: {e}")

    freed_space_mb = freed_space / (1024 * 1024)
    return deleted_count, freed_space_mb


def clean_all_cache_files(directory: Path):
    deleted_count = 0
    freed_space = 0.0

    if not directory.exists():
        return deleted_count, freed_space

    try:
        for file_path in directory.iterdir():
            if not file_path.is_file():
                continue

            try:
                file_size = file_path.stat().st_size
                file_path.unlink()
                deleted_count += 1
                freed_space += file_size
                logger.debug(f"[鸣潮·缓存清理] 删除缓存文件: {file_path.name}")
            except Exception as e:
                logger.error(f"[鸣潮·缓存清理] 删除文件失败 {file_path.name}: {e}")
    except Exception as e:
        logger.error(f"[鸣潮·缓存清理] 清理目录失败 {directory}: {e}")

    freed_space_mb = freed_space / (1024 * 1024)
    return deleted_count, freed_space_mb


async def clean_cache_directories(days: int) -> str:
    results = []
    total_count = 0
    total_space = 0.0

    ann_count, ann_space = clean_old_cache_files(ANN_CARD_PATH, days)
    if ann_count > 0:
        results.append(f"公告: {ann_count}个文件, {ann_space:.2f}MB")
        total_count += ann_count
        total_space += ann_space

    cal_count, cal_space = clean_old_cache_files(CALENDAR_CACHE_PATH, days)
    if cal_count > 0:
        results.append(f"日历: {cal_count}个文件, {cal_space:.2f}MB")
        total_count += cal_count
        total_space += cal_space

    wiki_count, wiki_space = clean_all_cache_files(WIKI_CACHE_PATH)
    if wiki_count > 0:
        results.append(f"Wiki: {wiki_count}个文件, {wiki_space:.2f}MB")
        total_count += wiki_count
        total_space += wiki_space

    # 烘焙缓存（含子目录）
    bake_count, bake_space = 0, 0.0
    if BAKE_PATH.exists():
        cutoff = time.time() - (days * 86400)
        for f in BAKE_PATH.rglob("*"):
            if f.is_file() and f.stat().st_ctime < cutoff:
                try:
                    sz = f.stat().st_size
                    f.unlink()
                    bake_count += 1
                    bake_space += sz
                except Exception:
                    pass
    if bake_count > 0:
        results.append(f"烘焙: {bake_count}个文件, {bake_space / 1024 / 1024:.2f}MB")
        total_count += bake_count
        total_space += bake_space / 1024 / 1024

    # 面板编辑临时目录（无条件全清，不计入统计）
    if PANEL_EDIT_TMP.exists():
        for f in PANEL_EDIT_TMP.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                except Exception:
                    pass

    if total_count == 0:
        return f"没有找到需要清理的缓存文件(公告/日历/烘焙保留{days}天内的文件，wiki全部删除)"

    result_msg = f"[鸣潮] 清理完成！共删除{total_count}个文件，{total_space:.2f}MB\n"
    result_msg += "\n".join(f" - {r}" for r in results)
    return result_msg


@sv_ann_clear_cache.on_fullmatch(("清理缓存", "删除缓存", "清理緩存", "刪除緩存"), block=True)
async def clean_cache_(bot: Bot, ev: Event):
    """手动清理缓存指令"""
    days = WutheringWavesConfig.get_config("CacheDaysToKeep").data
    logger.info(f"[鸣潮·缓存清理] 手动触发清理，保留{days}天内的文件")

    result = await clean_cache_directories(days)
    await bot.send(result)


@scheduler.scheduled_job("cron", hour=3, minute=0)
async def waves_auto_clean_cache_daily():
    """每天凌晨3点自动清理缓存"""
    days = WutheringWavesConfig.get_config("CacheDaysToKeep").data
    logger.info(f"[鸣潮·缓存清理] 定时任务: 开始清理缓存，保留{days}天内的文件")

    result = await clean_cache_directories(days)
    logger.info(f"[鸣潮·缓存清理] {result}")


@on_core_start
async def waves_clean_cache_on_startup():
    """启动时清理一次缓存"""
    await asyncio.sleep(5)

    days = WutheringWavesConfig.get_config("CacheDaysToKeep").data
    logger.info(f"[鸣潮·缓存清理] 启动时清理，保留{days}天内的文件")

    result = await clean_cache_directories(days)
    logger.info(f"[鸣潮·缓存清理] {result}")


def migrate_ann_config_to_json():
    """迁移公告配置到独立JSON文件"""
    try:
        try:
            config_new_ids = WutheringWavesConfig.get_config("WavesAnnNewIds").data
        except Exception:
            return

        if config_new_ids:
            current_json_ids = get_ann_new_ids()
            if not current_json_ids:
                logger.info("[鸣潮·公告] 开始迁移公告ID数据到独立JSON文件...")
                set_ann_new_ids(config_new_ids)
                logger.info(f"[鸣潮·公告] 成功迁移 {len(config_new_ids)} 个公告ID")

                try:
                    WutheringWavesConfig.set_config("WavesAnnNewIds", [])
                    logger.info("[鸣潮·公告] 已清空配置文件中的公告ID数据")
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"[鸣潮·公告] 迁移公告配置时出现异常: {e}")


migrate_ann_config_to_json()
