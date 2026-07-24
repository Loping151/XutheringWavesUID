"""per-uid 角色面板状态记录 (state.json)。

记录用户对每个角色的查看 / 刷新次数、最近时间戳, 以及培养建议发送状态。
建议透传到 caller 用模块级 _PENDING_ADVICE (key=uid), pop-once 语义。
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles
from gsuid_core.logger import logger

from .resource.RESOURCE_PATH import PLAYER_PATH


def _state_path(uid: str) -> Path:
    return PLAYER_PATH / uid / "state.json"


def _default_char_record() -> Dict[str, Any]:
    return {
        "view_count": 0,
        "refresh_count": 0,
        "last_view_at": 0,
        "last_refresh_at": 0,
        "last_advice_sent_at": 0,
        "last_advice_text": "",
        "advice_dirty": True,
    }


async def load_state(uid: str) -> Optional[Dict[str, Any]]:
    """None = 读取失败 (caller 应 skip); 文件不存在视为首次, 返回空骨架。"""
    path = _state_path(uid)
    if not path.exists():
        return {"chars": {}}
    try:
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            return json.loads(await f.read())
    except Exception as e:
        logger.warning(f"[鸣潮·角色状态] load {uid}: {e}")
        return None


async def save_state(uid: str, state: Dict[str, Any]) -> bool:
    path = _state_path(uid)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(state, ensure_ascii=False, indent=2))
        return True
    except Exception as e:
        logger.warning(f"[鸣潮·角色状态] save {uid}: {e}")
        return False


def _get_char(state: Dict[str, Any], char_id: str) -> Dict[str, Any]:
    chars = state.setdefault("chars", {})
    if char_id not in chars:
        chars[char_id] = _default_char_record()
    return chars[char_id]


async def record_view(uid: str, char_id: str) -> Optional[Dict[str, Any]]:
    """记录 view; 失败返回 None 让 caller skip advice 流程, 不重试。"""
    state = await load_state(uid)
    if state is None:
        return None
    rec = _get_char(state, char_id)
    rec["view_count"] = int(rec.get("view_count", 0)) + 1
    rec["last_view_at"] = int(time.time())
    if not await save_state(uid, state):
        return None
    return rec


async def record_advice_sent(uid: str, char_id: str, advice: str) -> bool:
    state = await load_state(uid)
    if state is None:
        return False
    rec = _get_char(state, char_id)
    rec["advice_dirty"] = False
    rec["last_advice_sent_at"] = int(time.time())
    rec["last_advice_text"] = advice
    return await save_state(uid, state)


async def record_refresh_batch(uid: str, changed_ids, unchanged_ids) -> bool:
    """一次性更新多角色刷新状态 (用于刷新场景, 单次落盘)。失败返回 False。"""
    state = await load_state(uid)
    if state is None:
        return False
    now = int(time.time())
    for cid in changed_ids:
        rec = _get_char(state, str(cid))
        rec["refresh_count"] = int(rec.get("refresh_count", 0)) + 1
        rec["last_refresh_at"] = now
        rec["advice_dirty"] = True
    for cid in unchanged_ids:
        rec = _get_char(state, str(cid))
        rec["refresh_count"] = int(rec.get("refresh_count", 0)) + 1
        rec["last_refresh_at"] = now
    return await save_state(uid, state)


# ─── 持有角色列表校验节流 (state.json 顶层) ──────────────────────────


async def bump_single_refresh(uid: str, every: int, max_interval: int) -> bool:
    """单角色刷新计数 +1; 计数达 every / 距上次校验超 max_interval / 从未校验 返回 True。"""
    state = await load_state(uid)
    if state is None:
        return False
    last = int(state.get("last_owned_check_at", 0) or 0)
    count = int(state.get("single_refresh_count", 0)) + 1
    if last == 0 or int(time.time()) - last > max_interval or count >= every:
        return True
    state["single_refresh_count"] = count
    await save_state(uid, state)
    return False


async def mark_owned_checked(uid: str) -> bool:
    """记录一次持有角色列表校验, 单刷计数清零。"""
    state = await load_state(uid)
    if state is None:
        return False
    state["single_refresh_count"] = 0
    state["last_owned_check_at"] = int(time.time())
    return await save_state(uid, state)


# ─── 跨函数透传 advice 文本 (key=id(ev), pop-once) ────────────────────

_PENDING_ADVICE: Dict[int, str] = {}


def queue_pending_advice(ev, text: str) -> None:
    _PENDING_ADVICE[id(ev)] = text


def pop_pending_advice(ev) -> Optional[str]:
    return _PENDING_ADVICE.pop(id(ev), None)
