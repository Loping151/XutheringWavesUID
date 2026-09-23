"""init"""

import asyncio

from gsuid_core.sv import SL, Plugins
from gsuid_core.logger import logger
from gsuid_core.server import on_core_shutdown

# 幂等: 防止跨插件 cross-import 让本文件在新 namespace 下重 exec 时
# 把 disable_force_prefix 用默认值 False 覆盖掉。
if "XutheringWavesUID" not in SL.plugins:
    Plugins(name="XutheringWavesUID", force_prefix=["ww"], allow_empty_prefix=False)

# 迁移遗留: 旧版锁文件落在仓库树内, 删掉; 过期后可整段注释
from .utils.resource.RESOURCE_PATH import BUILD_ROOT
_legacy_lock = BUILD_ROOT / ".build_copy.lock"
if _legacy_lock.exists():
    try:
        _legacy_lock.unlink()
    except OSError:
        pass

# 扩展(.pyd/.so)被 import 前先落盘新构建; Windows 下 .pyd 加载后锁定无法替换
from .utils.download_utils import copy_build_files
copy_build_files()

# glibc malloc 调参 + 定期 malloc_trim, 缓解本地渲染 RSS 驻留 (仅 glibc/Linux, WAVES_MALLOC_TUNING=0 可关)
try:
    from .utils import malloc_tuning  # noqa: F401
except Exception as _e:
    logger.warning(f"[鸣潮·插件] malloc 调参加载失败: {_e}")

# 安装 Bot 消息发送 Hook
from .utils.bot_send_hook import install_bot_hooks
from .utils.database.models import WavesUser
from .utils.database.waves_subscribe import WavesSubscribe
from .utils.database.waves_user_activity import WavesUserActivity
from .utils.database.waves_group_activity import WavesGroupActivity, ANN_PUSH_GUARD
from .utils.database.waves_user_sdk import WavesUserSdk  # noqa: F401
from .utils.plugin_checker import is_from_waves_plugin

# ===== 活跃度 / 头像 / Bot 绑定批量写入缓冲 =====
# 内存中暂存，定时批量写入，hook 本身不碰数据库
_activity_buffer: dict[str, tuple[str, str, str]] = {}
_avatar_buffer: dict[str, tuple[str, str, str]] = {}
_group_activity_buffer: dict[str, tuple[str, str, str]] = {}
_bot_buffer: dict[str, tuple[str, str]] = {}
_bot_cache: dict[str, tuple[str, str]] = {}
_FLUSH_INTERVAL = 60  # 秒
_FLUSH_CHUNK = 200


async def _flush_rows(buffer: dict, writer, label: str):
    if not buffer:
        return
    items = list(buffer.items())
    buffer.clear()
    for start in range(0, len(items), _FLUSH_CHUNK):
        chunk = items[start : start + _FLUSH_CHUNK]
        try:
            await writer([row for _, row in chunk])
        except Exception as e:
            for key, row in chunk:
                buffer.setdefault(key, row)
            logger.warning(f"[鸣潮·插件] {label}写入失败, 下轮重试: {e}")


async def _flush_bot_buffer():
    if not _bot_buffer:
        return
    items = list(_bot_buffer.items())
    _bot_buffer.clear()
    for group_id, (bot_id, bot_self_id) in items:
        try:
            await WavesSubscribe.check_and_update_bot(group_id, bot_id, bot_self_id)
            _bot_cache[group_id] = (bot_id, bot_self_id)
        except Exception as e:
            _bot_buffer.setdefault(group_id, (bot_id, bot_self_id))
            logger.warning(f"[鸣潮·插件] Bot检测失败, 下轮重试: {e}")


async def _flush_activity_buffer():
    """将缓冲区中的记录批量写入数据库"""
    await _flush_rows(_activity_buffer, WavesUserActivity.update_many, "活跃度")
    await _flush_rows(_avatar_buffer, WavesUser.update_avatar_many, "头像")
    await _flush_rows(_group_activity_buffer, WavesGroupActivity.update_many, "群活跃度")
    await _flush_bot_buffer()


_shutdown_event = asyncio.Event()


async def _activity_flush_loop():
    """后台定时刷写循环"""
    while not _shutdown_event.is_set():
        try:
            await asyncio.wait_for(_shutdown_event.wait(), timeout=_FLUSH_INTERVAL)
            break
        except asyncio.TimeoutError:
            pass
        try:
            await _flush_activity_buffer()
        except Exception as e:
            logger.warning(f"[鸣潮·插件] 活跃度刷写循环异常: {e}")

# 启动后台刷写任务
_flush_task = asyncio.get_event_loop().create_task(_activity_flush_loop())


@on_core_shutdown
async def _flush_on_shutdown():
    """退出前刷写缓冲区，防止数据丢失"""
    logger.info("[鸣潮·插件] 退出前停止活跃度刷写循环...")
    _shutdown_event.set()
    try:
        await asyncio.wait_for(_flush_task, timeout=5)
    except asyncio.TimeoutError:
        _flush_task.cancel()
    logger.info("[鸣潮·插件] 刷写活跃度缓冲区...")
    await _flush_activity_buffer()
    logger.info("[鸣潮·插件] 活跃度缓冲区刷写完成")


# 注册 WavesSubscribe 的 hook
async def waves_bot_check_hook(group_id: str, bot_id: str, bot_self_id: str):
    """XutheringWavesUID 的 bot 检测 hook"""
    logger.debug(f"[鸣潮·Hook] bot_check_hook 被调用: group_id={group_id}, bot_id={bot_id}, bot_self_id={bot_self_id}")

    if not group_id:
        return
    bot = (bot_id, bot_self_id)
    if _bot_cache.get(group_id) == bot:
        _bot_buffer.pop(group_id, None)
    else:
        _bot_buffer[group_id] = bot

# 注册用户活跃度 hook
async def waves_user_activity_hook(
    user_id: str,
    bot_id: str,
    bot_self_id: str,
    sender_avatar: str = "",
):
    """XutheringWavesUID 的用户活跃度 hook

    只记录由本插件触发的消息的用户活跃度
    写入内存缓冲区，由后台任务定时批量写入数据库
    """
    if ANN_PUSH_GUARD.get():
        return
    if not is_from_waves_plugin():
        return

    if not user_id:
        return

    _activity_buffer[f"{user_id}:{bot_id}:{bot_self_id}"] = (user_id, bot_id, bot_self_id)
    if sender_avatar:
        _avatar_buffer[f"{user_id}:{bot_id}"] = (user_id, bot_id, sender_avatar)

# 注册群活跃度 hook
async def waves_group_activity_hook(group_id: str, bot_id: str, bot_self_id: str):
    if ANN_PUSH_GUARD.get():
        return
    if not is_from_waves_plugin():
        return
    if not group_id:
        return
    _group_activity_buffer[f"{group_id}:{bot_id}:{bot_self_id}"] = (group_id, bot_id, bot_self_id)

# 安装 hooks 并注册
install_bot_hooks()
from .utils.bot_send_hook import (
    register_target_send_hook,
    register_user_activity_hook,
    register_group_activity_hook,
)
register_target_send_hook(waves_bot_check_hook)
register_user_activity_hook(waves_user_activity_hook)
register_group_activity_hook(waves_group_activity_hook)

logger.debug("[鸣潮·插件] Bot 消息发送 hook 已注册")
logger.debug("[鸣潮·插件] 用户活跃度 hook 已注册")

# 初始化本地化
from .utils.localization import init_localization
init_localization()

# 构建自定义图 hash 索引 (面板/背景/体力), 用于 hash → 路径 O(1) 查询。
try:
    from .wutheringwaves_charinfo.card_hash_index import build as _build_card_hash_index
    _build_card_hash_index()
except Exception as _e:
    logger.warning(f"[鸣潮·插件] 自定义图 hash 索引构建失败: {_e}")


# 迁移: 删除旧的 login_cache.db (已重命名为 url_cache.db)
from .utils.resource.RESOURCE_PATH import MAIN_PATH as _MAIN_PATH
_old_login_cache = _MAIN_PATH / "login_cache.db"
if _old_login_cache.exists():
    try:
        _old_login_cache.unlink()
        logger.info("[鸣潮·插件] 已删除旧的 login_cache.db")
    except Exception as _e:
        logger.warning(f"[鸣潮·插件] 删除旧的 login_cache.db 失败: {_e}")

# 修正: API曾错误地将陆·赫斯的resourceType标记为武器
# from .utils.resource.RESOURCE_PATH import PLAYER_PATH as _PLAYER_PATH
# from .utils.player_store import read_player_json_sync, write_player_json_sync, player_json_exists
# _fix_flag = _PLAYER_PATH / ".fix_hesi_done"
# if not _fix_flag.exists():
#     _fix_count = 0
#     for _uid_dir in _PLAYER_PATH.iterdir():
#         _gl = _uid_dir / "gacha_logs.json"
#         if not player_json_exists(_gl):
#             continue
#         try:
#             _raw = read_player_json_sync(_gl)
#             if not _raw:
#                 continue
#             _modified = False
#             for _records in _raw.get("data", {}).values():
#                 for _r in _records:
#                     if "赫斯" in _r.get("name", "") and _r.get("resourceType") == "武器":
#                         _r["resourceType"] = "角色"
#                         _modified = True
#             if _modified:
#                 write_player_json_sync(_gl, _raw)
#                 _fix_count += 1
#         except Exception:
#             continue
#     _fix_flag.write_text(f"fixed {_fix_count} players")
#     if _fix_count:
#         logger.info(f"[鸣潮·插件] 已修正 {_fix_count} 个玩家的赫斯 resourceType: 武器->角色")

# 修正: 仇远calc.json 热熔->气动
# _calc_1411 = get_res_path() / "XutheringWavesUID" / "resource" / "map" / "character" / "1411" / "calc.json"
# if _calc_1411.exists():
#     _content = _calc_1411.read_text(encoding="utf-8")
#     if "热熔" in _content:
#         _calc_1411.write_text(_content.replace("热熔", "气动"), encoding="utf-8")
#         logger.info("[鸣潮·插件] 已修正仇远calc.json: 热熔->气动")

# 以下是2025年的迁移
# # 迁移部分
# MAIN_PATH = get_res_path()
# PLAYERS_PATH = MAIN_PATH / "XutheringWavesUID" / "players"
# cfg_path = MAIN_PATH / "config.json"
# show_cfg_path = MAIN_PATH / "XutheringWavesUID" / "show_config.json"
# BACKUP_PATH = MAIN_PATH / "backup"

# # 此次迁移是为了删除错误的资源
# if (MAIN_PATH / "XutheringWavesUID" / "resuorce" / "map" / "detail_json" / "sonata" / "15.json").exists():
#     shutil.rmtree(MAIN_PATH / "XutheringWavesUID" / "resuorce" / "map" / "detail_json" / "sonata" / "15.json")
#     logger.info("[鸣潮·插件] 资源已更新，已删除错误资源 15.json")

# # 此次迁移是更改JieXing为VanZi
# if (MAIN_PATH / "XutheringWavesUID" / "guide_new" / "JieXing").exists():
#     shutil.rmtree(MAIN_PATH / "XutheringWavesUID" / "guide_new" / "JieXing")
#     logger.info("[鸣潮·插件] 资源已更新，已删除旧资源")

# # 此次迁移是删除错误的背景id
# TO_DEL = MAIN_PATH / "XutheringWavesUID" / "resuorce" / "role_bg" / "1402.webp"
# if TO_DEL.exists():
#     TO_DEL.unlink()
#     logger.info("[鸣潮·插件] 已删除错误的背景图片 1402.webp")

# # 此次迁移是直接把显示配置改为上传内容配置
# BG_PATH = MAIN_PATH / "XutheringWavesUID" / "bg"
# if BG_PATH.exists():
#     shutil.move(str(BG_PATH), str(BG_PATH.parent / "show"))
#     logger.info("[鸣潮·插件] 已将bg重命名为show以适应新配置")

# if show_cfg_path.exists():
#     with open(show_cfg_path, "r", encoding="utf-8") as f:
#         show_cfg_text = f.read()
#     if "bg" in show_cfg_text:
#         logger.info("[鸣潮·插件] 正在更新显示配置文件中的背景路径...")
#         shutil.copyfile(show_cfg_path, MAIN_PATH / "show_config_back.json")
#         show_cfg_text = show_cfg_text.replace("/bg", "/show")
#         with open(show_cfg_path, "w", encoding="utf-8") as f:
#             f.write(show_cfg_text)
#         Path(MAIN_PATH / "show_config_back.json").unlink()

# # 此次迁移是因为初次实现抽卡排行时，uid字段拿错导致的下划线连接多uid
# if PLAYERS_PATH.exists():
#     BACKUP_PATH.mkdir(parents=True, exist_ok=True)
#     pattern = re.compile(r"^\d+_\d+")
#     for item in PLAYERS_PATH.iterdir():
#         if item.is_dir() and pattern.match(item.name):
#             try:
#                 backup_item = BACKUP_PATH / item.name
#                 if backup_item.exists():
#                     shutil.rmtree(backup_item)
#                 shutil.move(str(item), str(backup_item))
#                 logger.info(f"[鸣潮·插件] 已移动错误的players文件夹到备份: {item.name}")
#             except Exception as e:
#                 logger.warning(f"[鸣潮·插件] 移动players文件夹失败 {item.name}: {e}")


# # 此次迁移是因为从WWUID改名为XutheringWavesUID
# if "WutheringWavesUID" in str(Path(__file__)):
#     logger.error("[鸣潮·插件] 请修改插件文件夹名称为 XutheringWavesUID 以支持后续指令更新")

# if not Path(MAIN_PATH / "XutheringWavesUID").exists() and Path(MAIN_PATH / "WutheringWavesUID").exists():
#     logger.info("[鸣潮·插件] 存在旧版插件资源，正在进行重命名...")
#     shutil.copytree(MAIN_PATH / "WutheringWavesUID", MAIN_PATH / "XutheringWavesUID")

# if Path(MAIN_PATH / "WutheringWavesUID").exists():
#     logger.warning("[鸣潮·插件] 检测到旧版资源 WutheringWavesUID，建议删除以节省空间")

# with open(cfg_path, "r", encoding="utf-8") as f:
#     cfg_text = f.read()
# if "WutheringWavesUID" in cfg_text and "XutheringWavesUID" not in cfg_text:
#     logger.info("[鸣潮·插件] 正在更新配置文件中的插件名称...")
#     shutil.copyfile(cfg_path, MAIN_PATH / "config_backup.json")
#     cfg_text = cfg_text.replace("WutheringWavesUID", "XutheringWavesUID")
#     with open(cfg_path, "w", encoding="utf-8") as f:
#         f.write(cfg_text)
#     Path(MAIN_PATH / "config_backup.json").unlink()
# elif "WutheringWavesUID" in cfg_text and "XutheringWavesUID" in cfg_text:
#     logger.warning(
#         "[鸣潮·插件] 同时存在 WutheringWavesUID 和 XutheringWavesUID 配置，可保留老的配置文件后重启，请自己编辑 gsuid_core/data/config.json 删除冗余配置（将 XutheringWavesUID 条目删除后将 WutheringWavesUID 改名为 XutheringWavesUID）"
#     )

# if Path(show_cfg_path).exists():
#     with open(show_cfg_path, "r", encoding="utf-8") as f:
#         show_cfg_text = f.read()
#     if "WutheringWavesUID" in show_cfg_text:
#         logger.info("[鸣潮·插件] 正在更新显示配置文件中的插件名称...")
#         shutil.copyfile(show_cfg_path, MAIN_PATH / "show_config_back.json")
#         show_cfg_text = show_cfg_text.replace("WutheringWavesUID", "XutheringWavesUID")
#         with open(show_cfg_path, "w", encoding="utf-8") as f:
#             f.write(show_cfg_text)
#         Path(MAIN_PATH / "show_config_back.json").unlink()
