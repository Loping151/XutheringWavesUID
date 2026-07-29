import copy
import json
import base64
import asyncio
from typing import Dict, List, Tuple, Union, Optional
from datetime import datetime
from collections import Counter, defaultdict

import aiohttp
import msgspec
from aiohttp import TCPConnector

from gsuid_core.logger import logger
from gsuid_core.models import Event

from .model import WWUIDGacha
from ..version import XutheringWavesUID_version
from ..utils.util import hide_uid, get_hide_uid_pref
from .merge_utils import (
    GACHA_HARD_PITY,
    GachaMergeError,
    clear_history_gap_before,
    has_history_gap_before,
    mark_history_gap_before,
    warn_gacha_pity_violations,
)
from ..utils.api.model import GachaLog
from ..utils.waves_api import waves_api
from ..utils.player_store import write_gz_json, read_player_json, write_player_json, player_json_exists
from .model_for_waves_plugin import WavesPluginGacha
from ..utils.resource.RESOURCE_PATH import PLAYER_PATH, GACHA_BACKUP_PATH

GACHA_BACKUP_LIMIT = 10

gacha_type_meta_data = {
    "角色精准调谐": "1",
    "武器精准调谐": "2",
    "角色调谐（常驻池）": "3",
    "武器调谐（常驻池）": "4",
    "角色忆旅唤取": "12",
    "武器忆旅唤取": "13",
    "角色联动唤取": "10",
    "武器联动唤取": "11",
    "新手调谐": "5",
    "新手自选唤取": "6",
    "新手自选唤取（感恩定向唤取）": "7",
    "角色新旅唤取": "8",
    "武器新旅唤取": "9",
}

gacha_type_meta_data_reverse = {v: k for k, v in gacha_type_meta_data.items()}

gachalogs_history_meta = {
    "角色精准调谐": [],
    "武器精准调谐": [],
    "角色调谐（常驻池）": [],
    "武器调谐（常驻池）": [],
    "角色忆旅唤取": [],
    "武器忆旅唤取": [],
    "角色联动唤取": [],
    "武器联动唤取": [],
    "新手调谐": [],
    "新手自选唤取": [],
    "新手自选唤取（感恩定向唤取）": [],
    "角色新旅唤取": [],
    "武器新旅唤取": [],
}

ERROR_MSG_INVALID_LINK = "当前抽卡链接已经失效，请重新导入抽卡链接"


# 找到两个数组中最长公共子串的下标（忽略resourceType字段差异）。
# 仅遍历 match_key 真正相同的位置，避免旧实现申请 n*m 的二维 Python 表。
def find_longest_common_subarray_indices(
    a: List[GachaLog], b: List[GachaLog]
) -> Optional[Tuple[Tuple[int, int], Tuple[int, int]]]:
    if not a or not b:
        return None

    positions: dict[tuple, list[int]] = defaultdict(list)
    for index, item in enumerate(b):
        positions[item.match_key()].append(index)

    previous: dict[int, int] = {}
    best_length = 0
    best_a_end = best_b_end = -1
    for a_index, item in enumerate(a):
        current: dict[int, int] = {}
        for b_index in positions.get(item.match_key(), []):
            length = previous.get(b_index - 1, 0) + 1
            current[b_index] = length
            if length > best_length:
                best_length = length
                best_a_end = a_index
                best_b_end = b_index
        previous = current

    if best_length == 0:
        return None
    return (
        (best_a_end - best_length + 1, best_a_end),
        (best_b_end - best_length + 1, best_b_end),
    )


def _time_bounds(logs: List[GachaLog]) -> Optional[Tuple[str, str]]:
    if not logs:
        return None
    times = [log.time for log in logs]
    return min(times), max(times)


def _ranges_overlap(a: List[GachaLog], b: List[GachaLog]) -> bool:
    a_bounds = _time_bounds(a)
    b_bounds = _time_bounds(b)
    if not a_bounds or not b_bounds:
        return False
    return max(a_bounds[0], b_bounds[0]) <= min(a_bounds[1], b_bounds[1])


def _is_filler(log: GachaLog) -> bool:
    return bool(getattr(log, "isFiller", False))


def _five_star_cycles(
    logs: List[GachaLog],
) -> tuple[
    dict[tuple[tuple, int], tuple[int, int, Optional[tuple]]],
    Counter,
]:
    """Return newest-to-oldest five-star cycles with occurrence-aware keys.

    A cycle starts at its five-star and contains the older pulls up to (but not
    including) the next five-star.  The next five-star key is retained as the
    older boundary so a partial 180-day cycle cannot masquerade as a complete
    replacement for synthetic workshop/XHH fillers.
    """
    five_indices = [
        index for index, log in enumerate(logs) if log.qualityLevel == 5
    ]
    key_counts = Counter(logs[index].match_key() for index in five_indices)
    occurrences = Counter()
    cycles: dict[tuple[tuple, int], tuple[int, int, Optional[tuple]]] = {}
    for position, start in enumerate(five_indices):
        key = logs[start].match_key()
        token = (key, occurrences[key])
        occurrences[key] += 1
        end = (
            five_indices[position + 1]
            if position + 1 < len(five_indices)
            else len(logs)
        )
        older_boundary = logs[end].match_key() if end < len(logs) else None
        cycles[token] = (start, end, older_boundary)
    return cycles, key_counts


def _is_key_subsequence(smaller: List[GachaLog], larger: List[GachaLog]) -> bool:
    if not smaller:
        return True
    target = [log.match_key() for log in smaller]
    index = 0
    for log in larger:
        if log.match_key() == target[index]:
            index += 1
            if index == len(target):
                return True
    return False


def _real_cycle_details_are_preserved(
    removed_cycle: List[GachaLog], kept_cycle: List[GachaLog]
) -> bool:
    """Ensure replacing placeholders never discards known real local pulls."""
    removed_real = [
        log for log in removed_cycle[1:] if not _is_filler(log)
    ]
    kept_real = [log for log in kept_cycle[1:] if not _is_filler(log)]
    return _is_key_subsequence(removed_real, kept_real)


def _truncated_cycle_matches_local(
    local_cycle: List[GachaLog], incoming_cycle: List[GachaLog]
) -> bool:
    """截断侧逐抽须与本地同位置的已知真实记录一致，占位可匹配任意。"""
    for local_log, incoming_log in zip(local_cycle[1:], incoming_cycle[1:]):
        if _is_filler(local_log):
            continue
        if local_log.match_key() != incoming_log.match_key():
            return False
    return True


def _reconcile_filler_cycles(
    local: List[GachaLog],
    incoming: List[GachaLog],
    *,
    incoming_may_be_truncated: bool = False,
) -> tuple[List[GachaLog], List[GachaLog]]:
    """Replace a complete synthetic cycle with a complete real cycle.

    Synthetic fillers encode a known cycle length, not additional pulls.  A
    plain multiset union would count both the placeholders and later imported
    real records.  Replacement is only safe when both five-star boundaries and
    the complete cycle length agree; otherwise the import is rejected.
    """
    local_cycles, local_key_counts = _five_star_cycles(local)
    incoming_cycles, incoming_key_counts = _five_star_cycles(incoming)
    remove_local: set[int] = set()
    remove_incoming: set[int] = set()

    for token in local_cycles.keys() & incoming_cycles.keys():
        local_start, local_end, local_older = local_cycles[token]
        incoming_start, incoming_end, incoming_older = incoming_cycles[token]
        local_cycle = local[local_start:local_end]
        incoming_cycle = incoming[incoming_start:incoming_end]
        local_has_filler = any(_is_filler(log) for log in local_cycle)
        incoming_has_filler = any(_is_filler(log) for log in incoming_cycle)
        if not local_has_filler and not incoming_has_filler:
            continue

        key = token[0]
        if (
            local_key_counts[key] != incoming_key_counts[key]
            and max(local_key_counts[key], incoming_key_counts[key]) > 1
        ):
            raise GachaMergeError(
                "同秒重复五星对应的占位周期无法唯一对齐"
            )

        if local_older != incoming_older:
            if any(
                has_history_gap_before(log)
                for log in local_cycle + incoming_cycle
            ):
                raise GachaMergeError(
                    "占位周期边界存在历史断档，无法安全对齐"
                )
            # A 180-day source commonly ends halfway through its oldest cycle.
            # The side that reaches the next older five-star has the complete
            # cycle; retain it and discard only the partial side's non-anchor
            # records.  This keeps the known pity length without double-counting
            # placeholders and real pulls.
            if local_older is not None and incoming_older is None:
                remove_incoming.update(
                    range(incoming_start + 1, incoming_end)
                )
                continue
            if incoming_older is not None and local_older is None:
                if not _real_cycle_details_are_preserved(
                    local_cycle, incoming_cycle
                ):
                    raise GachaMergeError(
                        "导入的完整周期不能覆盖本地已有且无法对齐的真实逐抽"
                    )
                remove_local.update(range(local_start + 1, local_end))
                continue
            raise GachaMergeError(
                "占位周期的前后五星边界不一致，无法安全合并"
            )

        # 两侧都含占位数据时，只有完全同一周期才能普通去重；否则
        # 无法判断哪些占位应被哪一侧的真实记录替换。
        if local_has_filler and incoming_has_filler:
            if [log.match_key() for log in local_cycle] != [
                log.match_key() for log in incoming_cycle
            ]:
                raise GachaMergeError(
                    "两份数据的占位周期内容不一致，无法安全合并"
                )
            continue
        if len(local_cycle) != len(incoming_cycle):
            # 官方链接只返回近180天：最老周期常被窗口截断，真实长度不可知。
            # 此时本地占位周期长度来自完整历史，保留本地，仅丢弃截断侧逐抽；
            # 文件导入不放宽，两侧都有更老五星边界时也不放宽。
            if (
                incoming_may_be_truncated
                and incoming_older is None
                and local_has_filler
                and not incoming_has_filler
                and len(incoming_cycle) < len(local_cycle)
                and not any(
                    has_history_gap_before(log)
                    for log in local_cycle + incoming_cycle
                )
            ):
                if not _truncated_cycle_matches_local(
                    local_cycle, incoming_cycle
                ):
                    raise GachaMergeError(
                        "导入的截断周期与本地已知逐抽记录冲突，已拒绝合并"
                    )
                remove_incoming.update(
                    range(incoming_start + 1, incoming_end)
                )
                continue
            raise GachaMergeError(
                f"占位周期为{len(local_cycle)}抽，导入的真实周期为"
                f"{len(incoming_cycle)}抽，已拒绝合并"
            )
        if any(
            has_history_gap_before(log)
            for log in local_cycle + incoming_cycle
        ):
            raise GachaMergeError(
                "占位周期内存在历史断档，无法安全替换真实记录"
            )
        if local_has_filler:
            if not _real_cycle_details_are_preserved(
                local_cycle, incoming_cycle
            ):
                raise GachaMergeError(
                    "真实替换周期与本地已有逐抽冲突，已拒绝覆盖"
                )
            # Keep the shared five-star itself as an overlap anchor.  Removing
            # the entire cycle would make the remaining adjacent segments look
            # disjoint and incorrectly add a history-gap marker.
            remove_local.update(range(local_start + 1, local_end))
        else:
            remove_incoming.update(range(incoming_start + 1, incoming_end))

    return (
        [
            log
            for index, log in enumerate(local)
            if index not in remove_local
        ],
        [
            log
            for index, log in enumerate(incoming)
            if index not in remove_incoming
        ],
    )


def _merge_timestamp_groups(
    a: List[GachaLog], b: List[GachaLog]
) -> List[GachaLog]:
    """Merge records without inventing an order inside a one-second bucket."""
    a_groups: dict[str, List[GachaLog]] = defaultdict(list)
    b_groups: dict[str, List[GachaLog]] = defaultdict(list)
    for log in a:
        a_groups[log.time].append(log)
    for log in b:
        b_groups[log.time].append(log)

    try:
        times = sorted(
            a_groups.keys() | b_groups.keys(),
            key=lambda value: datetime.strptime(value, "%Y-%m-%d %H:%M:%S"),
            reverse=True,
        )
    except ValueError as exc:
        raise GachaMergeError("抽卡记录时间格式异常，无法安全合并") from exc

    merged: List[GachaLog] = []
    for time_value in times:
        local_group = a_groups.get(time_value, [])
        incoming_group = b_groups.get(time_value, [])
        if not local_group:
            chosen = incoming_group
        elif not incoming_group:
            chosen = local_group
        elif _is_key_subsequence(local_group, incoming_group):
            chosen = incoming_group
        elif _is_key_subsequence(incoming_group, local_group):
            chosen = local_group
        else:
            raise GachaMergeError(
                f"{time_value}同秒记录在两份数据中的先后顺序无法唯一确定"
            )
        merged.extend(log.model_copy(deep=True) for log in chosen)
    return merged


def _merge_without_common_anchor(
    a: List[GachaLog],
    b: List[GachaLog],
    *,
    reject_overlapping: bool,
) -> List[GachaLog]:
    if not a:
        return [log.model_copy(deep=True) for log in b]
    if not b:
        return [log.model_copy(deep=True) for log in a]
    if reject_overlapping and _ranges_overlap(a, b):
        raise GachaMergeError("两份抽卡记录时间范围重叠，但没有任何可靠公共记录")

    # 保留单侧内部合法的同秒重复，只去掉两侧重复的多重集合部分。
    target_counts = Counter(log.match_key() for log in a) | Counter(
        log.match_key() for log in b
    )
    marker_flags: dict[tuple, list[bool]] = {
        key: [False] * count for key, count in target_counts.items()
    }
    for source in (a, b):
        source_ordinals = Counter()
        for log in source:
            key = log.match_key()
            ordinal = source_ordinals[key]
            source_ordinals[key] += 1
            if has_history_gap_before(log):
                marker_flags[key][ordinal] = True

    merged = _merge_timestamp_groups(a, b)
    if Counter(log.match_key() for log in merged) != target_counts:
        raise GachaMergeError("两份抽卡记录的同秒多重数据无法安全对齐")

    output_ordinals = Counter()
    for item in merged:
        key = item.match_key()
        ordinal = output_ordinals[key]
        output_ordinals[key] += 1
        if marker_flags[key][ordinal]:
            mark_history_gap_before(item)
        elif has_history_gap_before(item):
            clear_history_gap_before(item)

    if not _ranges_overlap(a, b):
        a_bounds = _time_bounds(a)
        b_bounds = _time_bounds(b)
        assert a_bounds and b_bounds
        newer = a if a_bounds[0] > b_bounds[1] else b
        newer_keys = Counter(log.match_key() for log in newer)
        # 新段最老的一抽，是按旧到新遍历时越过未知缺口后的第一抽。
        for item in reversed(merged):
            if newer_keys[item.match_key()] <= 0:
                continue
            mark_history_gap_before(item)
            break
    return merged


# 两侧已由调用方确认可合并后，按记录多重集合一次完成合并。
# 不再围绕每个公共片段递归，避免长历史或交错记录触发递归深度风险。
def merge_gacha_logs_by_common_subarray(a: List[GachaLog], b: List[GachaLog]) -> List[GachaLog]:
    return _merge_without_common_anchor(a, b, reject_overlapping=False)


def _merge_gacha_pool_records(
    local: List[GachaLog],
    incoming: List[GachaLog],
    *,
    incoming_may_be_truncated: bool = False,
) -> tuple[List[GachaLog], int]:
    """统一合并官方链接与文件的单池记录，并返回真实新增数。"""
    common_indices = find_longest_common_subarray_indices(local, incoming)
    reconciled_local, reconciled_incoming = _reconcile_filler_cycles(
        local, incoming, incoming_may_be_truncated=incoming_may_be_truncated
    )
    if local and incoming and not common_indices:
        merged = _merge_without_common_anchor(
            reconciled_local,
            reconciled_incoming,
            reject_overlapping=True,
        )
    else:
        # 有锚点时必须合并整个多重集合；只拼 incoming 的公共段前缀会复制
        # 本地前缀，并漏掉公共段中间恰好缺失的记录。
        merged = merge_gacha_logs_by_common_subarray(
            reconciled_local, reconciled_incoming
        )

    local_counts = Counter(log.match_key() for log in local)
    merged_counts = Counter(log.match_key() for log in merged)
    return merged, sum((merged_counts - local_counts).values())


async def get_new_gachalog(
    uid: str, record_id: str, full_data: Dict[str, List[GachaLog]], is_force: bool
) -> tuple[Union[str, None], Dict[str, List[GachaLog]], Dict[str, int], Dict[str, List[GachaLog]]]:
    new = {}
    new_count = {}
    link_source_data: Dict[str, List[GachaLog]] = {}
    for gacha_name, card_pool_type in gacha_type_meta_data.items():
        res = await waves_api.get_gacha_log(card_pool_type, record_id, uid)
        if not res.success or not res.data:
            # 抽卡记录获取失败
            if res.code == -1:  # type: ignore
                return ERROR_MSG_INVALID_LINK, None, None, {}  # type: ignore

        if res.data and isinstance(res.data, list):
            temp = res.data
        else:
            temp = []

        gacha_log = [GachaLog.model_validate(log) for log in temp]  # type: ignore
        for log in gacha_log:
            if log.cardPoolType != card_pool_type:
                log.cardPoolType = card_pool_type
        link_source_data[gacha_name] = list(gacha_log)
        try:
            new[gacha_name], new_count[gacha_name] = _merge_gacha_pool_records(
                full_data[gacha_name],
                gacha_log,
                incoming_may_be_truncated=True,
            )
        except GachaMergeError as exc:
            return (
                f"卡池[{gacha_name}]的新记录与本地历史无法安全对齐：{exc}",
                None,
                None,
                link_source_data,
            )  # type: ignore
        await asyncio.sleep(1)

    return None, new, new_count, link_source_data


async def get_new_gachalog_for_file(
    full_data: Dict[str, List[GachaLog]],
    import_data: Dict[str, List[GachaLog]],
) -> tuple[Union[str, None], Dict[str, List[GachaLog]], Dict[str, int]]:
    new = {}
    new_count = {}

    for cardPoolType, item in import_data.items():
        item: List[GachaLog]
        if cardPoolType not in gacha_type_meta_data:
            continue
        gacha_name = cardPoolType
        gacha_log = [GachaLog(**log.model_dump()) for log in item]
        try:
            new_gacha_log, added = _merge_gacha_pool_records(
                full_data[gacha_name], gacha_log
            )
        except GachaMergeError as exc:
            return (
                f"卡池[{gacha_name}]的导入文件与本地历史无法安全对齐：{exc}",
                None,
                None,
            )  # type: ignore
        new[gacha_name] = new_gacha_log
        new_count[gacha_name] = added
    return None, new, new_count


def count_new_gachalogs(
    full_data: Dict[str, List[GachaLog]],
    import_data: Dict[str, List[GachaLog]],
) -> Dict[str, int]:
    new_count = {}
    for gacha_name in gacha_type_meta_data:
        full_logs = Counter(log.match_key() for log in full_data.get(gacha_name, []))
        import_logs = Counter(log.match_key() for log in import_data.get(gacha_name, []))
        new_count[gacha_name] = sum((import_logs - full_logs).values())
    return new_count


def prune_gacha_backups(uid: str, type: str, limit: int = GACHA_BACKUP_LIMIT):
    backup_dir = GACHA_BACKUP_PATH / str(uid)
    if not backup_dir.exists():
        return
    files = sorted(
        [*backup_dir.glob(f"{type}_gacha_logs_*.json"), *backup_dir.glob(f"{type}_gacha_logs_*.json.gz")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in files[limit:]:
        try:
            old.unlink()
        except Exception as e:
            logger.warning(f"[鸣潮·抽卡备份] 清理旧备份失败 {old}: {e}")


async def backup_gachalogs(uid: str, gachalogs_history: Dict, type: str):
    backup_dir = GACHA_BACKUP_PATH / str(uid)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{type}_gacha_logs_{datetime.now().strftime('%Y-%m-%d.%H%M%S')}.json.gz"
    await write_gz_json(backup_path, gachalogs_history)
    prune_gacha_backups(uid, type)


async def save_link_source_gachalogs(uid: str, record_id: str, data: Dict[str, List[GachaLog]]):
    """保存通过链接获取的抽卡原始数据"""
    path = PLAYER_PATH / str(uid)
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)

    content = {
        "uid": uid,
        "record_id": record_id,
        "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data": {gacha_name: [log.model_dump() for log in logs] for gacha_name, logs in data.items()},
    }

    await write_player_json(path / "link_gacha_logs.json", content)


async def save_gachalogs(
    ev: Event,
    uid: str,
    record_id: str,
    is_force: bool = False,
    import_data: Optional[Dict[str, List[GachaLog]]] = None,
    force_overwrite: bool = False,
) -> str:
    path = PLAYER_PATH / str(uid)
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)

    # 抽卡记录json路径
    gachalogs_path = path / "gacha_logs.json"

    temp_gachalogs_history = {}
    gachalogs_history = await read_player_json(gachalogs_path)
    if gachalogs_history is None and player_json_exists(gachalogs_path):
        return "[鸣潮] 抽卡记录读取失败，已中止以防覆盖，请稍后重试"
    if gachalogs_history is not None:
        if not record_id:
            await backup_gachalogs(uid, gachalogs_history, type="import")
        temp_gachalogs_history = copy.deepcopy(gachalogs_history)
        gachalogs_history = gachalogs_history["data"]
    else:
        gachalogs_history = copy.deepcopy(gachalogs_history_meta)

    temp = copy.deepcopy(gachalogs_history_meta)
    temp.update(gachalogs_history)
    gachalogs_history = temp

    is_need_backup = False
    for gacha_name, card_pool_type in gacha_type_meta_data.items():
        for log in range(len(gachalogs_history[gacha_name]) - 1, -1, -1):
            pool_type = gachalogs_history[gacha_name][log]["cardPoolType"]
            if pool_type == card_pool_type:
                continue
            if card_pool_type == "武器精准调谐" and pool_type == "角色精准调谐-2":
                del gachalogs_history[gacha_name][log]
            elif card_pool_type == "角色调谐（常驻池）" and pool_type == "武器精准调谐":
                del gachalogs_history[gacha_name][log]
            elif card_pool_type == "武器调谐（常驻池）" and pool_type == "全频调谐":
                del gachalogs_history[gacha_name][log]
            else:
                gachalogs_history[gacha_name][log]["cardPoolType"] = card_pool_type

            is_need_backup = True

    if is_need_backup:
        await backup_gachalogs(uid, temp_gachalogs_history, type="update")

    for gacha_name in gacha_type_meta_data.keys():
        gachalogs_history[gacha_name] = [GachaLog(**log) for log in gachalogs_history[gacha_name]]

    link_source_data: Dict[str, List[GachaLog]] = {}
    if record_id:
        code, gachalogs_new, gachalogs_count_add, link_source_data = await get_new_gachalog(
            uid, record_id, gachalogs_history, is_force
        )
    elif not force_overwrite:
        code, gachalogs_new, gachalogs_count_add = await get_new_gachalog_for_file(
            gachalogs_history,
            import_data,  # type: ignore
        )
    else:
        code = None
        gachalogs_new = import_data
        gachalogs_count_add = count_new_gachalogs(gachalogs_history, import_data)  # type: ignore

    if isinstance(code, str) or not gachalogs_new:
        return code or ERROR_MSG_INVALID_LINK

    if record_id and link_source_data:
        await save_link_source_gachalogs(uid, record_id, link_source_data)

    # 获取当前时间
    current_time = datetime.now().strftime("%Y-%m-%d %H-%M-%S")

    # 检查时间降序。异常数据直接拒绝，不能通过截断一整段历史来“修正”。
    for gacha_name in gacha_type_meta_data.keys():
        logs = gachalogs_new.get(gacha_name, [])
        if len(logs) > 1:
            for i in range(len(logs) - 1, 0, -1):
                time_current = datetime.strptime(logs[i].time, "%Y-%m-%d %H:%M:%S")
                time_prev = datetime.strptime(logs[i - 1].time, "%Y-%m-%d %H:%M:%S")

                if time_prev < time_current:
                    logger.warning(
                        f"[鸣潮·抽卡导入] 卡池[{gacha_name}] "
                        f"索引{i - 1}/{i}时间顺序异常，拒绝写入"
                    )
                    return (
                        f"卡池[{gacha_name}]记录时间顺序异常，导入已中止，原记录未修改"
                    )

    pity_violations = warn_gacha_pity_violations(gachalogs_new, f"uid={uid} ")

    # 初始化最后保存的数据
    result = {"uid": uid, "data_time": current_time}

    # 保存数量
    for gacha_name in gacha_type_meta_data.keys():
        result[gacha_name] = len(gachalogs_new.get(gacha_name, []))  # type: ignore

    result["data"] = {  # type: ignore
        gacha_name: [log.model_dump() for log in gachalogs_new.get(gacha_name, [])]
        for gacha_name in gacha_type_meta_data.keys()
    }

    if record_id and temp_gachalogs_history:
        await backup_gachalogs(uid, temp_gachalogs_history, type="update")

    vo = msgspec.to_builtins(result)
    await write_player_json(gachalogs_path, vo)

    # 失效 stats 缓存：下次抽卡记录/抽卡排行查询时 lazy 重建
    (path / "gachaStats.json").unlink(missing_ok=True)

    # 计算数据
    all_add = sum(gachalogs_count_add.values())

    # 回复文字
    user_pref = await get_hide_uid_pref(uid, ev.user_id, ev.bot_id)
    im = []
    if all_add == 0:
        im.append(f"🌱UID{hide_uid(uid, user_pref)}没有新增唤取数据!")
    else:
        im.append(f"🌱UID{hide_uid(uid, user_pref)}数据更新成功！")
        for k, v in gachalogs_count_add.items():
            if v > 0:
                im.append(f"[{k}]新增{v}个数据！")
        from .web_view import _is_feature_enabled as _gw_enabled
        from ..wutheringwaves_config import PREFIX as _gw_prefix
        if _gw_enabled():
            im.append(f"可发送 {_gw_prefix}抽卡页面 查看更具体记录")
    gap_pools = [
        name
        for name, logs in gachalogs_new.items()
        if any(has_history_gap_before(log) for log in logs)
    ]
    if gap_pools:
        im.append(
            "⚠️检测到历史断档，已在断点处重新计算保底，避免跨缺失记录产生80抽以上数据："
            + "、".join(gap_pools)
        )
    if pity_violations:
        im.append(
            f"⚠️以下卡池存在超过{GACHA_HARD_PITY}抽的区间（历史记录缺失所致），"
            "已照常合并，保底统计仅供参考："
            + "、".join(sorted({v.pool for v in pity_violations}))
        )
    im = "\n".join(im)
    return im




async def import_gachalogs(ev: Event, history_url: str, type: str, uid: str, force_overwrite=False) -> str:
    history_data: Dict = {}
    if type == "json":
        history_data = json.loads(history_url)
    elif type == "url":
        try:
            async with aiohttp.ClientSession(connector=TCPConnector(ssl=False)) as session:
                async with session.get(history_url, timeout=30) as response:
                    if response.status != 200:
                        return f"下载文件失败，HTTP状态码: {response.status}"
                    content_type = response.headers.get("Content-Type", "")
                    if "application/json" in content_type:
                        history_data = await response.json()
                    else:
                        data_bytes = await response.read()
                        try:
                            history_data = json.loads(data_bytes.decode("utf-8"))
                        except UnicodeDecodeError:
                            try:
                                history_data = json.loads(data_bytes.decode("gbk"))
                            except UnicodeDecodeError:
                                return "无法解码文件内容，请检查文件编码格式"
        except Exception as e:
            return f"下载文件失败: {str(e)}"
    else:
        data_bytes = base64.b64decode(history_url)
        try:
            history_data = json.loads(data_bytes.decode())
        except UnicodeDecodeError:
            history_data = json.loads(data_bytes.decode("gbk"))
        except json.decoder.JSONDecodeError:
            return "请传入正确的JSON格式文件!"

    def turn_wwuid_gacha(data: Dict) -> Optional[WWUIDGacha]:
        if "info" in data and "export_app" in data["info"]:
            if "Waves-Plugin" == data["info"]["export_app"]:
                return WavesPluginGacha.model_validate(data).turn_wwuid_gacha()
            elif "XutheringWavesUID" == data["info"]["export_app"] or "WutheringWavesUID" == data["info"]["export_app"]:
                return WWUIDGacha.model_validate(data)
        return None

    wwuid_gacha = turn_wwuid_gacha(history_data)
    if not wwuid_gacha:
        err_res = [
            "你当前导入的抽卡记录文件不支持, 目前支持的文件类型有:",
            "1.WutheringWavesUID",
            "2.XutheringWavesUID",
            "3.Waves-Plugin",
        ]
        return "\n".join(err_res)

    if wwuid_gacha.info.uid != uid:
        return "你当前导入的抽卡记录文件的UID与当前UID不匹配!"

    import_data = copy.deepcopy(gachalogs_history_meta)
    for item in wwuid_gacha.list:
        gacha_name = item.cardPoolType
        if gacha_name in gacha_type_meta_data:
            # 此时cardPoolType是名字 -> 如角色精准调谐
            item.cardPoolType = gacha_type_meta_data[gacha_name]
        else:
            # 此时cardPoolType是类型 -> 如 "1"
            gacha_name = gacha_type_meta_data_reverse.get(item.cardPoolType)
            if not gacha_name:
                continue
        import_data[gacha_name].append(GachaLog(**item.model_dump()))

    res = await save_gachalogs(ev, uid, "", import_data=import_data, force_overwrite=force_overwrite)
    return res


async def export_gachalogs(uid: str) -> dict:
    path = PLAYER_PATH / uid
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)

    # 获取当前时间
    now = datetime.now()
    current_time = now.strftime("%Y-%m-%d %H:%M:%S")

    # 抽卡记录json路径
    gachalogs_path = path / "gacha_logs.json"
    raw_data = await read_player_json(gachalogs_path)
    if raw_data is not None:
        result = {
            "info": {
                "export_time": current_time,
                "export_app": "XutheringWavesUID",
                "export_app_version": XutheringWavesUID_version,
                "export_timestamp": round(now.timestamp()),
                "version": "v2.0",
                "uid": uid,
            },
            "list": [],
        }
        gachalogs_history = raw_data["data"]
        for name, gachalogs in gachalogs_history.items():
            result["list"].extend(gachalogs)

        # async with aiofiles.open(path / f"export_{uid}.json", "w", encoding="UTF-8") as file:
        #     await file.write(json.dumps(result, ensure_ascii=False, indent=4))
        logger.success("[鸣潮·导出抽卡记录] 导出成功!")
        im = {
            "retcode": "ok",
            "json": result,
            "name": f"export_{uid}.json",
        }
    else:
        logger.error("[鸣潮·导出抽卡记录] 没有找到抽卡记录!")
        im = {
            "retcode": "error",
            "data": "你还没有抽卡记录可以导出!",
            "name": "",
            "url": "",
        }

    return im
