import random
import asyncio

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.aps import scheduler
from gsuid_core.logger import logger

from ..wutheringwaves_config import WutheringWavesConfig
from ..utils.download_utils import copy_build_files, check_file_hash
from ..utils.resource.download_all_resource import (
    reload_all_modules,
    download_all_resource,
    notify_master_and_restart,
)
from ..utils.resource.RESOURCE_PATH import (
    BUILD_TEMP,
    MAP_BUILD_TEMP,
)

# 网页面板编辑器 (导入即注册路由 /waves/panel-edit/, 由 WavesPanelEditPassword 启停)
from . import panel_editor  # noqa: F401

_raw_dl_time = WutheringWavesConfig.get_config("ResourceDownloadTime").data
try:
    if not _raw_dl_time or len(_raw_dl_time) != 2:
        raise ValueError("expects [hour, minute]")
    RESOURCE_DOWNLOAD_HOUR = int(_raw_dl_time[0])
    RESOURCE_DOWNLOAD_MINUTE = int(_raw_dl_time[1])
except (TypeError, ValueError, LookupError) as _e:
    logger.warning(
        f"[鸣潮·资源] ResourceDownloadTime 解析失败 ({_raw_dl_time!r}: {_e})，跳过定时下载"
    )
    RESOURCE_DOWNLOAD_HOUR = -1
    RESOURCE_DOWNLOAD_MINUTE = -1

sv_download_config = SV("ww资源下载", pm=1)


@sv_download_config.on_fullmatch(("强制下载全部资源", "下载全部资源", "补充资源", "刷新补充资源"))
async def send_download_resource_msg(bot: Bot, ev: Event):
    await bot.send("[鸣潮] 正在开始下载~可能需要较久的时间！请勿重复执行！")
    try:
        await download_all_resource(force="强制" in ev.raw_text)

        if check_file_hash(BUILD_TEMP) or check_file_hash(MAP_BUILD_TEMP):
            await download_all_resource()

        build_updated, map_updated = copy_build_files(soft=True)
    except Exception as e:
        logger.exception(f"[鸣潮·资源] 手动下载失败: {e}")
        return await bot.send(f"[鸣潮] 资源下载/校验失败: {e}")

    if build_updated or map_updated:
        await bot.send("[鸣潮] 构建文件已更新，正在重启...")
        try:
            from gsuid_core.buildin_plugins.core_command.core_restart.restart import (
                restart_genshinuid,
            )
            await restart_genshinuid(event=ev, is_send=True)
        except Exception as e:
            logger.exception(f"[鸣潮·资源] 重启失败: {e}")
            return await bot.send(f"[鸣潮] 下载完成但重启失败: {e}")
    else:
        try:
            await reload_all_modules()
        except Exception as e:
            logger.exception(f"[鸣潮·资源] 重载模块失败: {e}")
            return await bot.send(f"[鸣潮] 下载完成但重载失败: {e}")
        await bot.send("[鸣潮] 下载完成！")


async def startup():
    await reload_all_modules()  # 已有资源，先加载，不然检查资源列表太久了
    logger.info("[鸣潮·资源] 等待资源下载完成...")
    await download_all_resource()

    logger.info("[鸣潮·资源] 资源下载完成，开始校验...")
    if check_file_hash(BUILD_TEMP) or check_file_hash(MAP_BUILD_TEMP):
        await download_all_resource()

    build_updated, map_updated = copy_build_files(soft=True)

    if build_updated or map_updated:
        logger.info("[鸣潮·资源] 构建文件已更新，正在重启...")
        await notify_master_and_restart()
    else:
        await reload_all_modules()

    logger.info("[鸣潮·资源] 资源下载完成！完成启动！")


async def auto_download_resource():
    delay_seconds = random.randint(0, 3600)
    if delay_seconds:
        await asyncio.sleep(delay_seconds)
    logger.info("[鸣潮·资源] 定时任务: 开始下载全部资源...")
    await download_all_resource()

    if check_file_hash(BUILD_TEMP) or check_file_hash(MAP_BUILD_TEMP):
        await download_all_resource()

    build_updated, map_updated = copy_build_files(soft=True)
    if build_updated or map_updated:
        logger.info("[鸣潮·资源] 定时任务: 构建文件已更新，正在重启...")
        await notify_master_and_restart("定时任务: 构建文件已更新，正在重启...")
    else:
        await reload_all_modules()
    logger.info("[鸣潮·资源] 定时任务: 资源下载完成")

if 0 <= RESOURCE_DOWNLOAD_HOUR < 24 and 0 <= RESOURCE_DOWNLOAD_MINUTE < 60:
    scheduler.add_job(
        auto_download_resource,
        "cron",
        id="ww_resource_download",
        hour=RESOURCE_DOWNLOAD_HOUR,
        minute=RESOURCE_DOWNLOAD_MINUTE,
        replace_existing=True,
    )
