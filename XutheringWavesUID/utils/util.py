import re
import json
import time
import random
import string
import asyncio
import inspect
import textwrap
from pathlib import Path
from typing import Any, Dict, List, TypeVar, Callable, Optional, Coroutine, overload
from functools import wraps

import httpx

from gsuid_core.logger import logger
from gsuid_core.subscribe import gs_subscribe


def timed_async_cache(expiration, condition=lambda x: True, key=None):
    def decorator(func):
        cache = {}
        locks = {}

        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        is_cls_method = params and params[0] in ["self", "cls"]

        def _make_key(args, kwargs):
            if key is not None:
                return key(*args, **kwargs)
            if is_cls_method and args and hasattr(args[0], "__class__"):
                base_key = f"{args[0].__class__.__name__}.{func.__name__}"
                key_args = args[1:]
            else:
                base_key = func.__name__
                key_args = args
            try:
                ck = (base_key, key_args, tuple(sorted(kwargs.items())))
                hash(ck)
            except TypeError:
                ck = (base_key, repr(key_args), repr(sorted(kwargs.items())))
            return ck

        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_time = time.time()
            cache_key = _make_key(args, kwargs)

            if cache_key not in locks:
                locks[cache_key] = asyncio.Lock()

            if cache_key in cache:
                value, timestamp = cache[cache_key]
                if current_time - timestamp < expiration:
                    return value

            async with locks[cache_key]:
                if cache_key in cache:
                    value, timestamp = cache[cache_key]
                    if current_time - timestamp < expiration:
                        return value

                value = await func(*args, **kwargs)
                if condition(value):
                    cache[cache_key] = (value, current_time)

                for stale in [
                    k for k, (_, ts) in cache.items()
                    if k != cache_key and current_time - ts >= expiration
                ]:
                    cache.pop(stale, None)
                    stale_lock = locks.get(stale)
                    if stale_lock is not None and not stale_lock.locked():
                        locks.pop(stale, None)
                return value

        return wrapper

    return decorator


F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])


@overload
def async_func_lock(*, keys: List[str] | None = None) -> Callable[[F], F]: ...


@overload
def async_func_lock(_func: F, *, keys: List[str] | None = None) -> F: ...


# 异步函数参数锁
def async_func_lock(
    _func: F | None = None,
    *,
    keys: List[str] | None = None,
) -> Callable[[F], F] | F:
    """
    异步函数参数锁
    使用示例:
    @async_func_lock(keys=["user_id"])
    async def get_user_info(user_id: str, uid: str):
        return await get_user_info(user_id, uid)
    """

    def decorator(func: F) -> F:
        locks: Dict[tuple, asyncio.Lock] = {}
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        is_cls_method = params and params[0] in ["self", "cls"]

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if is_cls_method and args and hasattr(args[0], "__class__"):
                # 对于类方法, 使用实例id来确保锁是实例级别的
                cache_key_parts = [args[0].__class__.__name__, func.__name__]
            else:
                # 对于普通函数, 锁是函数级别的
                cache_key_parts = [func.__name__]

            if keys:
                bound_args = sig.bind(*args, **kwargs)
                bound_args.apply_defaults()
                for key in keys:
                    if key in bound_args.arguments:
                        cache_key_parts.append(repr(bound_args.arguments[key]))

            lock_key = tuple(cache_key_parts)
            if lock_key not in locks:
                locks[lock_key] = asyncio.Lock()

            async with locks[lock_key]:
                return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    if _func is None:
        return decorator
    else:
        return decorator(_func)


# 使用示例
@timed_async_cache(86400)
async def get_public_ip(host="127.127.127.127"):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://event.kurobbs.com/event/ip", timeout=4)
            ip = r.text
            return ip
    except Exception:
        pass

    # 尝试从 ipify 获取 IP 地址
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.ipify.org/?format=json", timeout=4)
            ip = r.json()["ip"]
            return ip
    except Exception:
        pass

    # 尝试从 httpbin.org 获取 IP 地址
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://httpbin.org/ip", timeout=4)
            ip = r.json()["origin"]
            return ip
    except Exception:
        pass

    return host


def generate_random_string(length=32):
    # 定义可能的字符集合
    characters = string.ascii_letters + string.digits + string.punctuation
    # 使用random.choice随机选择字符，并连接成字符串
    random_string = "".join(random.choice(characters) for i in range(length))
    return random_string


def generate_random_ipv6_manual():
    return ":".join([hex(random.randint(0, 0xFFFF))[2:].zfill(4) for _ in range(8)])


def generate_random_ipv4_manual():
    return ".".join([str(random.randint(0, 255)) for _ in range(4)])


async def get_hide_uid_pref(uid: str, user_id: str, bot_id: str, game_id=None) -> str:
    """读 WavesUser.hide_uid_self_value, 没绑定就回空 (走全局 HideUid)。

    渲染入口在自己拿 ck 之外多一次 SELECT, 换来 hide_uid 可以纯按入参决策、
    避免反向查 + cache 多实例不同步的坑。
    """
    from .database.models import WavesUser
    from .constants import WAVES_GAME_ID
    try:
        user = await WavesUser.select_waves_user(uid, user_id, bot_id, game_id=game_id or WAVES_GAME_ID)
        return user.hide_uid_self_value if user else ""
    except Exception:
        return ""


def hide_uid(uid, user_pref: str = "") -> str:
    """
    user_pref: 该 uid 的 WavesUser.hide_uid_self_value, 由调用方从已取到的
        user 行传入。"on" 强制隐藏 / "off" 强制不隐藏 / "" 跟随全局 HideUid。
        没有 user 上下文的调用 (日志/无 ck 渲染等) 不传, 自然走全局配置。
    """
    from ..wutheringwaves_config import WutheringWavesConfig

    uid_str = str(uid) if uid is not None else ""
    if user_pref == "off":
        return uid_str
    if user_pref != "on":
        if not WutheringWavesConfig.get_config("HideUid").data:
            return uid_str
    if len(uid_str) < 2:
        return uid_str
    return uid_str[:2] + "*" * 4 + uid_str[-2:]


async def resolve_hide_uid(uid, user_id: str, bot_id: str):
    pref = await get_hide_uid_pref(uid, user_id, bot_id)
    if pref == "on":
        return True
    if pref == "off":
        return False
    return None


async def build_uid_masker(pairs, bot_id: str):
    """pairs: (uid, user_id) 序列; 返回同步 mask(uid, user_id), 按各自本地 pref 打码。"""
    prefs = {}
    for uid, user_id in pairs:
        key = (user_id, uid)
        if key not in prefs:
            prefs[key] = await get_hide_uid_pref(uid, user_id, bot_id)

    def mask(uid, user_id) -> str:
        return hide_uid(uid, user_pref=prefs.get((user_id, uid), ""))

    return mask


def clean_tags(text: str) -> str:
    """清理文本中的XML/HTML标签（如<color>等）"""
    text = re.sub(r"<color[^>]*>", "", text)
    text = re.sub(r"</color>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text


def wrap_text_with_manual_newlines(text: str, width: int = 70) -> str:
    """保留原文 \\n 的前提下按 width 换行"""
    lines = text.split("\n")
    return "\n".join(textwrap.fill(line, width=width) for line in lines)


def load_json_file(json_path: Path) -> Optional[Dict[str, Any]]:
    """加载 JSON 文件。文件不存在返回 None；解析或 IO 异常记录日志后返回 None"""
    try:
        if not json_path.exists():
            return None
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[鸣潮·工具] Failed to load json {json_path}: {e}")
        return None


def _collapse_repeated_slash_values(text: str) -> str:
    """将 '10/10/10/10/10' 这样全部相同的重复值折叠为 '10'"""
    def _replace(m):
        parts = m.group(0).split('/')
        if len(set(parts)) == 1:
            return parts[0]
        return m.group(0)
    return re.sub(r'[\d.]+(?:/[\d.]+)+', _replace, text)


def format_with_defaults(desc: str, params: List[Any], default_value: str = "N/A"):
    num_placeholders = desc.count("{")  # 简单估计位置参数数量
    params_list = list(params)
    while len(params_list) < num_placeholders:
        params_list.append(default_value)
    result = desc.format(*params_list)
    return _collapse_repeated_slash_values(result)


def get_version(dynamic: bool = False, **kwargs):
    from ..version import XutheringWavesUID_version

    if dynamic:
        from .safety import generate_dynamic_version

        dynamic_version = generate_dynamic_version(**kwargs)
        return XutheringWavesUID_version + dynamic_version

    return XutheringWavesUID_version


filter_msg = [
    "角色查询失败",
    "漂泊者绑定角色",
]


# 发送主人信息
async def _send_master_info_impl(msg: str):
    # 过滤
    for i in filter_msg:
        if i in msg:
            return

    subscribes = await gs_subscribe.get_subscribe("联系主人")
    if not subscribes:
        return
    for sub in subscribes:
        await sub.send(f"【联系主人】：{msg}")
    return True


@timed_async_cache(300, lambda x: x)
async def send_master_info(msg: str):
    return await _send_master_info_impl(msg)


# 系统维护提示 cd 单独加长(1小时), 避免维护期间频繁打扰主人
@timed_async_cache(3600, lambda x: x)
async def send_master_info_maintenance(msg: str):
    return await _send_master_info_impl(msg)


def login_platform() -> str:
    # from ..wutheringwaves_config import WutheringWavesConfig

    # LoginType = WutheringWavesConfig.get_config("WavesLoginTypeNew").data
    # return LoginType if LoginType else "ios"
    return "ios"
