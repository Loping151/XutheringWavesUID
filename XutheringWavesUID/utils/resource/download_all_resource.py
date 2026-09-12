import os
import sys
import platform
import asyncio
import time

from gsuid_core.logger import logger
from gsuid_core.utils.download_resource.download_core import download_all_file
import httpx

from .download_cnb import download_all_file_cnb
from .RESOURCE_PATH import (
    MAP_PATH,
    BUILD_TEMP,
    AVATAR_PATH,
    CALENDAR_PATH,
    WEAPON_PATH,
    PHANTOM_PATH,
    ROLE_BG_PATH,
    MAP_CHALLENGE_PATH,
    MAP_CHAR_PATH,
    MAP_FORTE_PATH,
    MATERIAL_PATH,
    SHARE_BG_PATH,
    TITLE_BG_PATH,
    CARD_POLYGON_PATH,
    MAP_ALIAS_PATH,
    LOCALIZATION_PATH,
    MAP_BUILD_TEMP,
    ROLE_PILE_PATH,
    XFM_GUIDE_PATH,
    XMU_GUIDE_PATH,
    KUROBBS_GUIDE_PATH,
    CHRYSOBERYL_GUIDE_PATH,
    MAP_DETAIL_PATH,
    WUHEN_GUIDE_PATH,
    VANZI_GUIDE_PATH,
    XIAOYANG_GUIDE_PATH,
    JINLINGZI_GUIDE_PATH,
    MOEALKYNE_GUIDE_PATH,
    ROLE_DETAIL_SKILL_PATH,
    ROLE_DETAIL_CHAINS_PATH,
    WIKI_CACHE_PATH,
)

async def check_speed(plugin_name, exclude_cnb: bool = False):
    URL_LIB = {
        "小维1号": "https://ww1.loping151.top/",
        "小维2号": "https://ww2.loping151.top/",
        "小维3号": "https://ww3.loping151.cn/",
        "小维CNB": "https://cnb.cool/loping151/XutheringWavesUID-Resources/-/git/raw/main/",
    }
    from ...wutheringwaves_config import WutheringWavesConfig

    if exclude_cnb or not WutheringWavesConfig.get_config("ResourceUseCNB").data:
        URL_LIB = {tag: url for tag, url in URL_LIB.items() if "cnb.cool" not in url}

    async def _measure_speed(
        client: httpx.AsyncClient, base_url: str, deadline: float
    ) -> float:
        test_url = f"{base_url}{plugin_name}/speedtest"
        size = 0
        start = None
        try:
            async with client.stream("GET", test_url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    if start is None:
                        start = time.perf_counter()
                    size += len(chunk)
                    if time.perf_counter() >= deadline:
                        break
        except Exception as exc:
            logger.warning(f"[鸣潮·资源下载] 资源测速失败: {test_url} {exc}")
            return 0.0
        if start is None:
            return 0.0
        elapsed = time.perf_counter() - start
        if elapsed <= 0:
            return 0.0
        return size / elapsed

    async def _race_speedtest(timeout_seconds: float):
        deadline = time.perf_counter() + max(0.0, timeout_seconds - 0.1)
        timeout = httpx.Timeout(timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            task_meta: dict[asyncio.Task, tuple[str, str]] = {}
            for tag, base_url in URL_LIB.items():
                coro = asyncio.wait_for(
                    _measure_speed(client, base_url, deadline),
                    timeout=timeout_seconds,
                )
                task_meta[asyncio.create_task(coro)] = (tag, base_url)

            winner = None
            pending = set(task_meta.keys())
            try:
                while pending:
                    done, pending = await asyncio.wait(
                        pending, return_when=asyncio.FIRST_COMPLETED
                    )
                    for t in done:
                        tag, base_url = task_meta[t]
                        try:
                            speed = t.result()
                        except Exception:
                            speed = 0.0
                        if speed > 0:
                            winner = (tag, base_url, speed)
                            break
                    if winner is not None:
                        break
            finally:
                for t in task_meta:
                    if not t.done():
                        t.cancel()
                await asyncio.gather(*task_meta.keys(), return_exceptions=True)
            return winner

    winner = await _race_speedtest(5.0)
    if winner is None:
        logger.warning(f"[鸣潮·资源下载] 资源测速超时，尝试 20 秒超时重试")
        winner = await _race_speedtest(20.0)

    if winner is not None:
        tag, url, speed = winner
        logger.info(
            f"[鸣潮·资源下载] 资源测速选择: {tag} "
            f"{speed / 1024 / 1024:.2f} MB/s"
        )
        return url, tag

    logger.error(f"[鸣潮·资源下载] 资源测速失败！请检查网络连通性！一般而言无需代理")
    tags = list(URL_LIB.keys())
    urls = list(URL_LIB.values())
    return urls[0], tags[0]


def get_target_package():
    system = sys.platform
    machine = platform.machine().lower()

    py_ver = f"py{sys.version_info.major}.{sys.version_info.minor}"

    if py_ver not in ["py3.10", "py3.11", "py3.12", "py3.13"]:
        logger.error(f"[鸣潮·资源下载] 不支持的Python版本: {py_ver}")
        return ""

    if system == "win32":
        if "64" in machine:
            return f"win-x86_64-{py_ver}"
        else:
            logger.error("[鸣潮·资源下载] 暂不支持32位Windows")
            return ""

    elif system == "linux":
        if "x86_64" in machine:
            return f"linux-x86_64-{py_ver}"
        elif "aarch64" in machine:
            return f"linux-aarch64-{py_ver}"
        else:
            logger.error("[鸣潮·资源下载] 暂不支持非x86_64架构的Linux")

    is_android = "ANDROID_ROOT" in os.environ or "ANDROID_DATA" in os.environ
    if is_android:
        if py_ver == "py3.12":
            return "android-aarch64-ndk"
        else:
            logger.error("[鸣潮·资源下载] 安卓环境仅支持Python 3.12")
            return f"linux-x86_64-{py_ver}"

    elif system == "darwin":
        if "arm64" in machine:
            return f"macos-arm64-{py_ver}"
        elif "x86_64" in machine:
            logger.error("[鸣潮·资源下载] 暂不支持Intel架构的Mac")
            return ""

    logger.error(f"[鸣潮·资源下载] 不支持的操作系统: {system} {machine}")
    return f"linux-x86_64-{py_ver}"


PLATFORM = get_target_package()
_download_lock = asyncio.Lock()


async def download_all_resource(force: bool = False):
    async with _download_lock:
        if force:
            import shutil

            shutil.rmtree(BUILD_TEMP, ignore_errors=True)
            shutil.rmtree(MAP_BUILD_TEMP, ignore_errors=True)
            shutil.rmtree(MAP_CHAR_PATH, ignore_errors=True)
            shutil.rmtree(WIKI_CACHE_PATH, ignore_errors=True)
            BUILD_TEMP.mkdir(parents=True, exist_ok=True)
            MAP_BUILD_TEMP.mkdir(parents=True, exist_ok=True)
            MAP_CHAR_PATH.mkdir(parents=True, exist_ok=True)
            WIKI_CACHE_PATH.mkdir(parents=True, exist_ok=True)
            
        plugin_name = "XutheringWavesUID"
        url, tag = await check_speed(plugin_name)

        epath_map = {
            "resource/avatar": AVATAR_PATH,
            "resource/weapon": WEAPON_PATH,
            "resource/role_pile": ROLE_PILE_PATH,
            "resource/role_bg": ROLE_BG_PATH,
            "resource/role_detail/skill": ROLE_DETAIL_SKILL_PATH,
            "resource/role_detail/chains": ROLE_DETAIL_CHAINS_PATH,
            "resource/share": SHARE_BG_PATH,
            "resource/title_bg": TITLE_BG_PATH,
            "resource/card_polygon": CARD_POLYGON_PATH,
            "resource/phantom": PHANTOM_PATH,
            "resource/material": MATERIAL_PATH,
            "resource/calendar": CALENDAR_PATH,
            "resource/guide/XMu": XMU_GUIDE_PATH,
            "resource/guide/Moealkyne": MOEALKYNE_GUIDE_PATH,
            "resource/guide/JinLingZi": JINLINGZI_GUIDE_PATH,
            "resource/guide/VanZi": VANZI_GUIDE_PATH,
            "resource/guide/XiaoYang": XIAOYANG_GUIDE_PATH,
            "resource/guide/WuHen": WUHEN_GUIDE_PATH,
            "resource/guide/XFM": XFM_GUIDE_PATH,
            "resource/guide/KuroBBS": KUROBBS_GUIDE_PATH,
            "resource/guide/Chrysoberyl": CHRYSOBERYL_GUIDE_PATH,
            f"resource/build/{PLATFORM}/waves_build": BUILD_TEMP,
            f"resource/build/{PLATFORM}/map/waves_build": MAP_BUILD_TEMP,
            "resource/map": MAP_PATH,
            "resource/map/character": MAP_CHAR_PATH,
            "resource/map/detail_json": MAP_DETAIL_PATH,
            "resource/map/detail_json/challenge": MAP_CHALLENGE_PATH,
            "resource/map/detail_json/forte": MAP_FORTE_PATH,
            "resource/map/alias": MAP_ALIAS_PATH,
            "resource/map/i18n": LOCALIZATION_PATH,
        }

        if "cnb.cool" in url:
            if await download_all_file_cnb(plugin_name, epath_map, url, tag):
                return
            logger.warning("[鸣潮·资源下载] CNB 清单不可用, 改用 http 镜像")
            url, tag = await check_speed(plugin_name, exclude_cnb=True)

        await download_all_file(plugin_name, epath_map, url, tag)


async def reload_all_modules():
    # 强制加载所有 map 数据
    from ..name_convert import ensure_data_loaded as ensure_name_convert_loaded
    from ..ascension.char import ensure_data_loaded as ensure_char_loaded
    from ..ascension.echo import ensure_data_loaded as ensure_echo_loaded
    from ..ascension.sonata import ensure_data_loaded as ensure_sonata_loaded
    from ..ascension.weapon import ensure_data_loaded as ensure_weapon_loaded
    from ..map.damage.register import reload_all_register
    from ..limit_user_card import load_limit_user_card
    from ..calc import reload_wuwacalc_module
    from ..damage.damage import reload_damage_module
    from ...wutheringwaves_wiki.char_wiki_render import clear_wiki_cache

    # 在下载完成后强制加载所有数据
    ensure_name_convert_loaded(force=True)
    ensure_char_loaded(force=True)
    ensure_weapon_loaded(force=True)
    ensure_echo_loaded(force=True)
    ensure_sonata_loaded(force=True)
    
    reload_wuwacalc_module()
    reload_damage_module()
    reload_all_register()
    clear_wiki_cache()
    card_list = await load_limit_user_card()
    if card_list:
        logger.info(f"[鸣潮·加载角色极限面板] 数量: {len(card_list)}")

    # 重新加载本地化字典
    from ..localization import init_localization
    init_localization()

    # 重新注册 AI 知识库（仅 AI 启用时生效）
    from ...wutheringwaves_ai_rag import reload_ai_rag
    await reload_ai_rag()


async def notify_master_and_restart(reason: str = "构建文件已更新，正在重启..."):
    from gsuid_core.subscribe import gs_subscribe
    from gsuid_core.buildin_plugins.core_command.core_restart.restart import (
        restart_genshinuid,
    )

    try:
        subs = await gs_subscribe.get_subscribe("联系主人")
    except Exception as e:
        subs = None
        logger.warning(f"[鸣潮·资源下载] 获取主人订阅失败: {e}")

    if subs:
        for sub in subs:
            try:
                await sub.send(f"[鸣潮] {reason}")
            except Exception as e:
                logger.warning(f"[鸣潮·资源下载] 重启通知发送失败: {e}")
    else:
        logger.info("[鸣潮·资源下载] 无【联系主人】订阅, 跳过重启通知")

    await restart_genshinuid(is_send=False)