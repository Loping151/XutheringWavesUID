import re
import json
import asyncio
from typing import Dict, List, Union, Optional

import aiofiles

from gsuid_core.logger import logger
from gsuid_core.models import Event

from .hint import error_reply
from .util import get_version, hide_uid
from .api.model import RoleList, AccountBaseInfo, OwnedRoleInfoResponse
from .waves_api import waves_api
from .resource.constant import SPECIAL_CHAR_INT_ALL
from .error_reply import WAVES_CODE_101, WAVES_CODE_102
from .queues.const import QUEUE_SCORE_RANK
from .queues.queues import push_item
from .expression_ctx import WavesCharRank, get_waves_char_rank, _compute_one_char_rank
from ..wutheringwaves_config import PREFIX, WutheringWavesConfig
from .resource.RESOURCE_PATH import PLAYER_PATH, CACHE_PATH
from .char_info_utils import get_all_roleid_detail_info_int
from .char_state import record_refresh_batch
from .api.model import AccountBaseInfo as _AccountBaseInfo

_BG_TASKS: set = set()


async def save_base_info_cache(uid: str, account_info: _AccountBaseInfo):
    """将账户基本信息（世界等级等）缓存到文件"""
    _dir = PLAYER_PATH / uid
    _dir.mkdir(parents=True, exist_ok=True)
    path = _dir / "baseInfo.json"
    try:
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(account_info.model_dump_json())
    except Exception as e:
        logger.exception(f"save_base_info_cache failed {path}:", e)


async def load_base_info_cache(uid: str) -> Optional[_AccountBaseInfo]:
    """从缓存文件读取账户基本信息"""
    path = PLAYER_PATH / uid / "baseInfo.json"
    if not path.exists():
        return None
    try:
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            data = json.loads(await f.read())
        return _AccountBaseInfo.model_validate(data)
    except Exception as e:
        logger.exception(f"load_base_info_cache failed {path}:", e)
        return None


def is_use_global_semaphore() -> bool:
    return WutheringWavesConfig.get_config("UseGlobalSemaphore").data or False


def get_refresh_card_concurrency() -> int:
    return WutheringWavesConfig.get_config("RefreshCardConcurrency").data or 2


class SemaphoreManager:
    def __init__(self):
        self._last_config: int = get_refresh_card_concurrency()
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(value=self._last_config)
        self._semaphore_lock = asyncio.Lock()

    async def get_semaphore(self) -> asyncio.Semaphore:
        current_config = get_refresh_card_concurrency()

        if is_use_global_semaphore():
            return await self._get_semaphore(current_config)  # 全局模式
        else:
            return asyncio.Semaphore(value=current_config)  # 独立模式

    async def _get_semaphore(self, current_config: int) -> asyncio.Semaphore:
        if self._last_config != current_config:
            async with self._semaphore_lock:
                if self._last_config != current_config:
                    self._semaphore = asyncio.Semaphore(value=current_config)
                    self._last_config = current_config

        return self._semaphore


semaphore_manager = SemaphoreManager()


def remove_urls_from_data(data):
    url_pattern = re.compile(r'https?://[^\s"\'<>]+')

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key == "description":
                result[key] = ""
            else:
                result[key] = remove_urls_from_data(value)
        return result
    elif isinstance(data, list):
        return [remove_urls_from_data(item) for item in data]
    elif isinstance(data, str):
        return url_pattern.sub('', data)
    else:
        return data


async def send_card(
    uid: str,
    user_id: str,
    save_data: List,
    is_self_ck: bool = False,
    token: Optional[str] = "",
    role_info: Optional[RoleList] = None,
    waves_data: Optional[List] = None,
    sender_avatar: str = "",
):
    WavesToken = WutheringWavesConfig.get_config("WavesToken").data
    if not WavesToken:
        return

    if not (is_self_ck and token and save_data and role_info and waves_data and user_id):
        return
    # 单角色上传排行
    if len(waves_data) != 1 and len(role_info.roleList) != len(save_data):
        logger.warning(
            f"角色数量不一致，role_info.roleNum:{len(role_info.roleList)} != save_data:{len(save_data)}"
        )
        return
    account_info = await waves_api.get_base_info(uid, token=token)
    if not account_info.success:
        return account_info.throw_msg()
    if not account_info.data:
        return f"用户未展示数据, 请尝试【{PREFIX}登录】"
    account_info = AccountBaseInfo.model_validate(account_info.data)
    if len(waves_data) != 1 and account_info.roleNum != len(save_data):
        logger.warning(
            f"角色数量不一致，role_info.roleNum:{account_info.roleNum} != save_data:{len(save_data)}"
        )
        return

    def _build_meta(rank):
        meta = {
            "user_id": user_id,
            "waves_id": f"{account_info.id}",
            "kuro_name": account_info.name,
            "version": get_version(
                dynamic=True, user_id=user_id, waves_id=f"{account_info.id}", char_info=str(len(rank))
            ),
            "char_info": [r.to_rank_dict() for r in rank],
            "role_num": account_info.roleNum,
            "single_refresh": 1 if len(waves_data) == 1 else 0,
        }
        if sender_avatar:
            meta["sender_avatar"] = sender_avatar
        return meta

    # 全量刷新不算综合评分, 仅单角色刷新时算; 后台上传不阻塞出图
    # 只算本次刷新的角色
    async def _upload_rank():
        try:
            if len(waves_data) == 1:
                results = await asyncio.gather(
                    *(asyncio.to_thread(_compute_one_char_rank, rd, True, True) for rd in waves_data),
                    return_exceptions=True,
                )
                ranks = [r for r in results if isinstance(r, WavesCharRank)]
                errs = [r for r in results if isinstance(r, BaseException)]
                if errs:
                    logger.warning(f"[鸣潮·评分] 综合评分计算失败 uid={uid}: {errs[0]!r}")
            else:
                ranks = await get_waves_char_rank(uid, save_data, True, need_overall_score=False)
            if ranks:
                push_item(QUEUE_SCORE_RANK, _build_meta(ranks))
        except Exception as e:
            logger.warning(f"[鸣潮·评分] 排行上传失败 uid={uid}: {e}")

    task = asyncio.create_task(_upload_rank())
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


async def save_card_info(
    uid: str,
    waves_data: List,
    waves_map: Optional[Dict] = None,
    user_id: str = "",
    is_self_ck: bool = False,
    token: str = "",
    role_info: Optional[RoleList] = None,
    sender_avatar: str = "",
    is_self: bool = True,
):
    if len(waves_data) == 0:
        return
    _dir = PLAYER_PATH / uid
    _dir.mkdir(parents=True, exist_ok=True)
    path = _dir / "rawData.json"

    old_data = {}
    if path.exists():
        try:
            async with aiofiles.open(path, mode="r", encoding="utf-8") as f:
                old = json.loads(await f.read())
                old_data = {d["role"]["roleId"]: d for d in old}
        except Exception as e:
            logger.exception(f"save_card_info get failed {path}:", e)
            path.unlink(missing_ok=True)

    #
    refresh_update = {}
    refresh_unchanged = {}
    for item in waves_data:
        role_id = item["role"]["roleId"]

        if role_id in SPECIAL_CHAR_INT_ALL:
            # 漂泊者预处理
            for piaobo_id in SPECIAL_CHAR_INT_ALL:
                old = old_data.get(piaobo_id)
                if not old:
                    continue
                if piaobo_id != role_id:
                    del old_data[piaobo_id]

        old = old_data.get(role_id)
        cleaned_item = remove_urls_from_data(item)
        if old != cleaned_item:
            refresh_update[role_id] = item
        else:
            refresh_unchanged[role_id] = item

        old_data[role_id] = item

    save_data = list(old_data.values())

    if is_self:
        try:
            await record_refresh_batch(uid, refresh_update.keys(), refresh_unchanged.keys())
        except Exception as e:
            logger.warning(f"[鸣潮·state] refresh 状态记录失败 uid={uid}: {e}")

    await send_card(uid, user_id, save_data, is_self_ck, token, role_info, waves_data, sender_avatar)

    try:
        # 移除所有 URL 后再保存
        cleaned_data = remove_urls_from_data(save_data)
        async with aiofiles.open(path, "w", encoding="utf-8") as file:
            await file.write(json.dumps(cleaned_data, ensure_ascii=False))
    except Exception as e:
        logger.exception(f"save_card_info save failed {path}:", e)

    # 保存charListData.json（角色评分缓存）
    # 只有本次发生变化的角色才重新评分
    rank_source = list(refresh_update.values())
    if rank_source:
        waves_char_rank = await get_waves_char_rank(uid, rank_source, True)
    else:
        waves_char_rank = []

    # 候选门槛: 不在漂泊者列表、本次确有变更、有旧分、旧分>140、
    #   跨档 / 单角色刷新 delta∈(0,50) ; 否则 delta∈(3,50)
    # 选取: 优先跨越档位 (210 > 195 > 175) 的角色; 同档位中挑 new 最高
    # 一次刷了 >=20 个角色, 不再提示 top_improver(全量刷新场景)
    TIER_THRESHOLDS = (210.0, 195.0, 175.0)
    top_improver = None
    if waves_char_rank and refresh_update and len(refresh_update) < 20:
        from ..wutheringwaves_rank.draw_rank_list_card import load_char_list_data
        old_scores = await load_char_list_data(uid) or {}
        single_char = len(refresh_update) == 1
        candidates = []
        for cr in waves_char_rank:
            if cr.roleId in SPECIAL_CHAR_INT_ALL:
                continue
            if cr.roleId not in refresh_update:
                continue
            old_raw = old_scores.get(str(cr.roleId))
            if old_raw is None:
                continue
            try:
                old = float(old_raw)
                new = float(cr.score or 0)
            except (TypeError, ValueError):
                continue
            if old <= 140:
                continue
            delta = new - old
            crossed_tier = any(new >= tier > old for tier in TIER_THRESHOLDS)
            lo, hi = (0, 50) if (crossed_tier or single_char) else (3, 50)
            if not (lo < delta < hi):
                continue
            candidates.append({
                "roleId": cr.roleId,
                "roleName": cr.roleName,
                "old": old,
                "new": new,
                "delta": delta,
            })

        def _priority(c):
            for idx, tier in enumerate(TIER_THRESHOLDS):
                if c["new"] >= tier > c["old"]:
                    return (len(TIER_THRESHOLDS) - idx, c["new"])
            return (0, c["new"])
        if candidates:
            top_improver = max(candidates, key=_priority)

    await save_char_list_cache(uid, waves_char_rank)

    if waves_map:
        waves_map["refresh_update"] = refresh_update
        waves_map["refresh_unchanged"] = refresh_unchanged
        waves_map["top_improver"] = top_improver


async def save_char_list_cache(uid: str, waves_char_rank: Optional[List[WavesCharRank]]):
    """保存角色评分数据到charListData.json供练度排行使用

    只更新改动的角色，而不是重写整个文件。

    Args:
        uid: 用户uid
        waves_char_rank: WavesCharRank列表（只包含改动的角色）
    """
    if not waves_char_rank:
        return

    try:
        from ..wutheringwaves_rank.draw_rank_list_card import (
            load_char_list_data,
            save_char_list_data,
        )
        from .resource.constant import SPECIAL_CHAR_RANK_MAP

        # 加载现有的角色评分数据
        existing_char_list_data = await load_char_list_data(uid)
        if not existing_char_list_data:
            existing_char_list_data = {}

        # 只更新改动的角色
        for char_rank in waves_char_rank:
            role_id_str = str(char_rank.roleId)
            mapped_id = SPECIAL_CHAR_RANK_MAP.get(role_id_str, role_id_str)
            existing_char_list_data[mapped_id] = char_rank.score

        larger_special_ids = [k for k, v in SPECIAL_CHAR_RANK_MAP.items() if k != v]
        for large_id in larger_special_ids:
            if large_id in existing_char_list_data:
                del existing_char_list_data[large_id]

        # 保存更新后的数据
        if existing_char_list_data:
            await save_char_list_data(uid, existing_char_list_data)
    except Exception as e:
        logger.debug(f"保存charListData.json失败 uid={uid}: {e}")


async def refresh_char(
    ev: Event,
    uid: str,
    user_id: str,
    ck: Optional[str] = None,  # type: ignore
    waves_map: Optional[Dict] = None,
    is_self_ck: bool = False,
    refresh_type: Union[str, List[str]] = "all",
    is_self: bool = True,
) -> Union[str, List]:
    waves_datas = []
    if not ck:
        is_self_ck, ck = await waves_api.get_ck_result(uid, user_id, ev.bot_id)
    if not ck:
        return error_reply(WAVES_CODE_102)
    # 共鸣者信息
    role_info = await waves_api.get_role_info(uid, ck)
    if not role_info.success:
        return role_info.throw_msg()

    if isinstance(role_info.data, dict) and "roleList" not in role_info.data:
        return f"鸣潮特征码[{hide_uid(uid)}]的角色数据未公开展示，请【{PREFIX}登录】或在库街区展示角色"

    try:
        role_info = RoleList.model_validate(role_info.data)
    except Exception as e:
        logger.exception(f"{uid} 角色信息解析失败", e)
        msg = f"鸣潮特征码[{hide_uid(uid)}]获取数据失败\n1.是否注册过库街区\n2.库街区能否查询当前鸣潮特征码数据"
        return msg

    request_role_ids: List[int] = []
    if refresh_type != "all":
        if isinstance(refresh_type, list):
            request_role_ids = [int(r) for r in refresh_type if str(r).isdigit()]
        elif str(refresh_type).isdigit():
            request_role_ids = [int(refresh_type)]

    if request_role_ids:
        local_roles = await get_all_roleid_detail_info_int(uid)
        has_local_role = bool(local_roles and any(rid in local_roles for rid in request_role_ids))
        if not has_local_role and is_self_ck:
            owned_role_info = await waves_api.get_owned_role_info(uid, ck)
            if not owned_role_info.success or isinstance(owned_role_info.data, str):
                return owned_role_info.throw_msg()
            owned_role_info = OwnedRoleInfoResponse.model_validate(owned_role_info.data)
            owned_role_ids = {r.roleId for r in owned_role_info.roleInfoList}
            if not any(rid in owned_role_ids for rid in request_role_ids):
                return error_reply(code=-110, msg="未拥有该角色，无法刷新面板")

    semaphore = await semaphore_manager.get_semaphore()

    async def limited_get_role_detail_info(role_id, uid, ck):
        async with semaphore:
            return await waves_api.get_role_detail_info(role_id, uid, ck)

    if is_self_ck:
        tasks = [
            limited_get_role_detail_info(f"{r.roleId}", uid, ck)
            for r in role_info.roleList
            if refresh_type == "all" or (isinstance(refresh_type, list) and f"{r.roleId}" in refresh_type)
        ]
    else:
        if role_info.showRoleIdList:
            tasks = [
                limited_get_role_detail_info(f"{r}", uid, ck)
                for r in role_info.showRoleIdList
                if refresh_type == "all" or (isinstance(refresh_type, list) and f"{r}" in refresh_type)
            ]
        else:
            tasks = [
                limited_get_role_detail_info(f"{r.roleId}", uid, ck)
                for r in role_info.roleList
                if refresh_type == "all" or (isinstance(refresh_type, list) and f"{r.roleId}" in refresh_type)
            ]
    results = await asyncio.gather(*tasks)

    charId2chainNum: Dict[int, int] = {
        r.roleId: r.chainUnlockNum for r in role_info.roleList if isinstance(r.chainUnlockNum, int)
    }
    # 处理返回的数据
    for role_detail_info in results:
        if not role_detail_info.success:
            return error_reply(role_detail_info.code, role_detail_info.msg)
            #continue

        role_detail_info = role_detail_info.data
        if (
            not isinstance(role_detail_info, dict)
            or "role" not in role_detail_info
            or role_detail_info["role"] is None
            or "level" not in role_detail_info
            or role_detail_info["level"] is None
        ):
            continue
        if role_detail_info["phantomData"]["cost"] == 0:
            role_detail_info["phantomData"]["equipPhantomList"] = None
        try:
            # 扰我道心 难道谐振几阶还算不明白吗
            del role_detail_info["weaponData"]["weapon"]["effectDescription"]
        except Exception as _:
            pass

        # 修正共鸣链
        try:
            role_id = role_detail_info["role"]["roleId"]
            for i in role_detail_info["chainList"]:
                if i["order"] <= charId2chainNum[role_id]:
                    i["unlocked"] = True
                else:
                    i["unlocked"] = False
        except Exception as e:
            logger.exception(f"{uid} 共鸣链修正失败", e)

        # 修正合鸣效果
        try:
            if role_detail_info["phantomData"] and role_detail_info["phantomData"]["equipPhantomList"]:
                for i in role_detail_info["phantomData"]["equipPhantomList"]:
                    if not isinstance(i, dict):
                        continue
                    sonata_name = i.get("fetterDetail", {}).get("name", "")
                    if sonata_name == "雷曜日冕之冠":
                        i["fetterDetail"]["name"] = "荣斗铸锋之冠"  # type: ignore
        except Exception as e:
            logger.exception(f"{uid} 合鸣效果修正失败", e)

        # 下载共鸣模态图片
        try:
            skill_branch_list = role_detail_info.get("skillBranchList")
            if skill_branch_list:
                cache_dir = CACHE_PATH / "attribute_skill"
                cache_dir.mkdir(parents=True, exist_ok=True)
                for branch in skill_branch_list:
                    branch_name = branch.get("branchName", "")
                    pic_url = branch.get("pic", "")
                    if pic_url and branch_name:
                        save_name = f"{branch_name}.png"
                        if not (cache_dir / save_name).exists():
                            from gsuid_core.utils.download_resource.download_file import download
                            await download(pic_url, cache_dir, save_name, tag="[鸣潮]")
        except Exception as e:
            logger.exception(f"{uid} 共鸣模态图片下载失败", e)

        waves_datas.append(role_detail_info)

    sender_avatar = (ev.sender or {}).get("avatar") or ""
    if not (isinstance(sender_avatar, str) and sender_avatar.startswith(("http://", "https://"))):
        sender_avatar = ""

    await save_card_info(
        uid,
        waves_datas,
        waves_map,
        user_id,
        is_self_ck=is_self_ck,
        token=ck,
        role_info=role_info,
        sender_avatar=sender_avatar,
        is_self=is_self,
    )

    if not waves_datas:
        if refresh_type == "all":
            return error_reply(WAVES_CODE_101)
        else:
            return error_reply(code=-110, msg="库街区暂未查询到角色数据，应为登陆失效")

    return waves_datas
