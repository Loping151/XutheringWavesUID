"""charinfo 私有的 24h 内存 baseinfo 缓存。"""
import sys
import time
from typing import Dict, Optional, Tuple

from gsuid_core.logger import logger

from ..utils.api.model import AccountBaseInfo

_TTL = 24 * 3600
_cache: Dict[str, Tuple[float, AccountBaseInfo]] = {}


def _entry_bytes(uid: str, info: AccountBaseInfo) -> int:
    """近似单条缓存项内存占用（key 字节 + 模型 JSON 字节 + 元组开销）。"""
    try:
        payload = len(info.model_dump_json().encode("utf-8"))
    except Exception:
        payload = 0
    return sys.getsizeof(uid) + payload + 64  # 64 ≈ tuple+float overhead


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / 1024 / 1024:.2f}MB"


def stats() -> Tuple[int, int]:
    """返回 (条目数, 估算总字节数)。"""
    total = 0
    for uid, (_, info) in _cache.items():
        total += _entry_bytes(uid, info)
    return len(_cache), total


def _log_stats(action: str, uid: str) -> None:
    count, total = stats()
    logger.debug(
        f"[鸣潮·角色基础信息缓存] {action} uid={uid} entries={count} ~{_fmt_bytes(total)}"
    )


def get(uid: str) -> Optional[AccountBaseInfo]:
    entry = _cache.get(uid)
    if not entry:
        return None
    ts, info = entry
    if time.time() - ts > _TTL:
        _cache.pop(uid, None)
        _log_stats("expire", uid)
        return None
    return info


def set(uid: str, info: AccountBaseInfo) -> None:
    _cache[uid] = (time.time(), info)
    _log_stats("set", uid)


def invalidate(uid: str) -> None:
    if _cache.pop(uid, None) is not None:
        _log_stats("invalidate", uid)


async def get_or_fetch_account_info(
    target_uid: str,
    ck: str,
    *,
    use_cache: bool = True,
    require_fresh: bool = False,
) -> "AccountBaseInfo | str":
    """取 base_info; 优先内存/落盘缓存命中, 然后走 API。返回 AccountBaseInfo 或错误文案。"""
    from ..wutheringwaves_config import PREFIX
    from ..utils.waves_api import waves_api
    from ..utils.refresh_char_detail import load_base_info_cache, save_base_info_cache

    if use_cache and not require_fresh:
        info = get(target_uid)
        if info is None:
            info = await load_base_info_cache(target_uid)
            if info is not None:
                set(target_uid, info)
        if info is not None:
            return info

    api_result = await waves_api.get_base_info(target_uid, ck)
    if not api_result.success:
        return api_result.throw_msg()
    if not api_result.data:
        return f"用户未展示数据, 请尝试【{PREFIX}登录】"
    info = AccountBaseInfo.model_validate(api_result.data)
    await save_base_info_cache(target_uid, info)
    set(target_uid, info)
    return info


async def load_account_context(
    target_uid: str,
    user_id: str,
    bot_id: str,
    *,
    use_cache: bool = True,
    require_fresh: bool = False,
    force_ck: bool = False,
    peek: bool = False,
) -> "tuple[AccountBaseInfo | str, str, bool]":
    """统一账号上下文获取, 返回 (info_or_err, ck, self_ck)。

    use_cache: 是否优先读内存/落盘缓存。
    require_fresh: True 时即便命中缓存也走 API 强制刷新。
    force_ck: 即便命中缓存也强制取 ck (peek/refresh 后续仍需 ck 调其它 API)。
    peek: 以他人视角取 ck, 不用目标本人的凭据。
    """
    from ..utils import hint
    from ..utils.waves_api import waves_api
    from ..utils.error_reply import WAVES_CODE_102
    from ..utils.refresh_char_detail import load_base_info_cache

    if use_cache and not require_fresh and not force_ck:
        info = get(target_uid)
        if info is None:
            info = await load_base_info_cache(target_uid)
            if info is not None:
                set(target_uid, info)
        if info is not None:
            return info, "", False

    self_ck, ck = await waves_api.get_ck_result(target_uid, user_id, bot_id, peek=peek)
    if not ck:
        return hint.error_reply(WAVES_CODE_102), "", False

    info = await get_or_fetch_account_info(
        target_uid, ck, use_cache=use_cache, require_fresh=require_fresh
    )
    return info, ck, self_ck
