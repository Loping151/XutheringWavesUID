import json
import time
import random
import string
import hashlib
from typing import Optional
from datetime import datetime, timedelta
from collections import Counter

import aiohttp
from aiohttp import TCPConnector

from gsuid_core.logger import logger

from .merge_utils import (
    GachaMergeError,
    validate_draw_total,
    group_flat_gacha_logs,
    warn_gacha_pity_violations,
)
from ..utils.resource.RESOURCE_PATH import MAP_PATH

# Mappings
POOL_TYPE_MAP = {
    "角色精准调谐": "1",
    "武器精准调谐": "2",
    "角色精准调谐-2": "2",  # 国际服
    "角色调谐（常驻池）": "3",
    "武器调谐（常驻池）": "4",
    "全频调谐": "4",  # 国际服
    "新手调谐": "5",
    "新手自选唤取": "6",
    "新手自选唤取（感恩定向唤取）": "7",
    "角色新旅唤取": "8",
    "武器新旅唤取": "9",
    "角色联动唤取": "10",
    "武器联动唤取": "11",
    "角色忆旅唤取": "12",
    "武器忆旅唤取": "13",
}
KNOWN_POOL_CODES = set(POOL_TYPE_MAP.values())

POOL_CODE_TO_NAME: dict[str, str] = {}
for _pool_name, _pool_code in POOL_TYPE_MAP.items():
    POOL_CODE_TO_NAME.setdefault(_pool_code, _pool_name)

FILLER_ITEM = {
    "resourceId": 21040023,
    "qualityLevel": 3,
    "resourceType": "武器",
    "name": "源能臂铠·测肆",
    "count": 1,
    "isFiller": True,
}


def _time_to_timestamp(time_str: str) -> float:
    if not time_str:
        return float("-inf")
    try:
        return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return float("-inf")


def _validate_gacha_time(value: object, source: str, name: str) -> str:
    time_str = str(value or "")
    try:
        datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise GachaMergeError(
            f"{source}五星[{name or '未知五星'}]的时间格式异常"
        ) from exc
    return time_str


def _sort_key_by_time(item: dict, idx_field: str = "_internal_idx"):
    ts = _time_to_timestamp(item.get("time", ""))
    order_idx = item.get(idx_field, float("inf"))
    return (-ts, order_idx)


def generate_random_string(length, chars):
    return "".join(random.choice(chars) for _ in range(length))


def generate_union_id(length=28):
    chars = string.ascii_letters + string.digits + "_"
    return generate_random_string(length, chars)


def generate_sign(length=32):
    chars = string.digits + "abcdef"
    return generate_random_string(length, chars)


def get_timestamp_minus_1s(time_str):
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        dt_new = dt - timedelta(seconds=1)
        return dt_new.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return time_str


def get_filler_time(current_time: str, prev_five_star_time: Optional[str] = None) -> str:
    if prev_five_star_time and prev_five_star_time == current_time:
        return current_time
    return get_timestamp_minus_1s(current_time)


async def fetch_mcgf_data(uid: str):
    logger.debug(f"[鸣潮·抽卡处理] 开始获取工坊数据 UID: {uid}")
    url = "https://api3.sanyueqi.cn/api/v2/game_user/get_sr_draw_v3"
    current_time_ms = str(int(time.time() * 1000))
    random_union_id = generate_union_id()
    random_sign = generate_sign()

    params = {"uid": uid, "union_id": random_union_id}

    headers = {
        "Host": "api3.sanyueqi.cn",
        "Connection": "keep-alive",
        "time": current_time_ms,
        "sign": random_sign,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541411) XWEB/16965",
        "xweb_xhr": "1",
        "Content-Type": "application/json",
        "version": "100",
        "platform": "weixin",
        "Accept": "*/*",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://servicewechat.com/wx715e22143bcda767/36/page-frame.html",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "WWUIDMSG": "We welcome data sharing. We can also provide method to import wwuid gacha data into your mini program.",
    }

    try:
        async with aiohttp.ClientSession(connector=TCPConnector(ssl=False)) as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("data", {}).get("uid"):
                        logger.success(f"[鸣潮·抽卡处理] 获取工坊数据成功 UID: {uid}")
                        return data
                    else:
                        logger.warning(f"[鸣潮·抽卡处理] 获取工坊数据失败 UID: {uid} 返回数据异常：{str(data)[:500]}")
                else:
                    logger.warning(f"[鸣潮·抽卡处理] 获取工坊数据失败 Status: {response.status}")
    except Exception as e:
        logger.error(f"[鸣潮·抽卡处理] 获取工坊数据发生异常: {e}")
    return None


def _five_star_key(item: dict) -> tuple[str, str]:
    return str(item.get("time", "")), str(item.get("name", ""))


def _validate_external_overlap(
    local_fives: list[dict],
    external_fives: list[dict],
    source: str,
    pool_id: str,
) -> None:
    if not local_fives or not external_fives:
        return

    source_start = external_fives[0]["time"]
    source_end = external_fives[-1]["time"]
    local_start = local_fives[0]["time"]
    local_end = local_fives[-1]["time"]
    source_counts = Counter(_five_star_key(item) for item in external_fives)
    local_in_source = Counter(
        _five_star_key(item)
        for item in local_fives
        if source_start <= item["time"] <= source_end
    )
    unexpected_local = local_in_source - source_counts
    if unexpected_local:
        raise GachaMergeError(
            f"{source}与本地卡池[{pool_id}]在相同时间范围内的五星记录不一致，已拒绝覆盖"
        )

    overlap_end = min(local_end, source_end)
    if local_start <= overlap_end:
        source_in_local = Counter(
            _five_star_key(item)
            for item in external_fives
            if local_start <= item["time"] <= overlap_end
        )
        local_overlap = Counter(
            _five_star_key(item)
            for item in local_fives
            if local_start <= item["time"] <= overlap_end
        )
        if source_in_local - local_overlap:
            raise GachaMergeError(
                f"本地卡池[{pool_id}]在{source}覆盖区间内存在五星断档，已拒绝不完整合并"
            )


def _find_five_star_anchor(
    local_fives: list[dict], external_fives: list[dict]
) -> Optional[int]:
    oldest_local = local_fives[0]
    for index, candidate in enumerate(external_fives):
        if _five_star_key(candidate) != _five_star_key(oldest_local):
            continue
        compare_count = min(3, len(local_fives), len(external_fives) - index)
        for offset in range(1, compare_count):
            if _five_star_key(external_fives[index + offset]) != _five_star_key(
                local_fives[offset]
            ):
                break
        else:
            return index
    return None


def _append_rebuilt_five_star(
    target: list[dict],
    card: dict,
    pool_id: str,
    source: str,
    previous_five_time: Optional[str],
) -> str:
    draw_total = validate_draw_total(
        card.get("draw_total"), source, pool_id, str(card.get("name", "未知五星"))
    )
    filler_time = get_filler_time(card["time"], previous_five_time)
    # target 始终按旧到新构建；同秒双金也必须保持“占位 -> 五星”的周期顺序。
    for _ in range(draw_total - 1):
        filler = FILLER_ITEM.copy()
        filler["cardPoolType"] = pool_id
        filler["time"] = filler_time
        target.append(filler)
    target.append(
        {
            "cardPoolType": pool_id,
            "resourceId": card["resourceId"],
            "qualityLevel": 5,
            "resourceType": card["resourceType"],
            "name": card["name"],
            "count": 1,
            "time": card["time"],
        }
    )
    return card["time"]


def _pool_display(pool_id: str) -> str:
    return POOL_CODE_TO_NAME.get(pool_id, pool_id)


def _build_pool_items(
    pool_id: str,
    source: str,
    local_all: list[dict],
    local_fives: list[dict],
    source_fives: list[dict],
) -> list[dict]:
    """构建单个卡池的合并结果，按旧到新返回。"""
    if not source_fives:
        return list(local_all)

    if not local_all:
        logger.debug(
            f"[鸣潮·抽卡合并] Pool {pool_id}: 本地池为空，使用{source}完整重建"
        )
        pool_items: list[dict] = []
        previous_time: Optional[str] = None
        for card in source_fives:
            previous_time = _append_rebuilt_five_star(
                pool_items, card, pool_id, source, previous_time
            )
        return pool_items

    if not local_fives:
        raise GachaMergeError(
            f"本地卡池[{pool_id}]有记录但没有五星，无法与{source}建立可靠锚点"
        )

    _validate_external_overlap(local_fives, source_fives, source, pool_id)
    match_idx = _find_five_star_anchor(local_fives, source_fives)
    if match_idx is None:
        raise GachaMergeError(
            f"本地卡池[{pool_id}]与{source}没有可靠五星锚点，已拒绝分离拼接"
        )

    oldest_local = local_fives[0]
    logger.debug(
        f"[鸣潮·抽卡合并] Pool {pool_id}: 在{source}索引{match_idx}对齐"
        f" {oldest_local.get('name')} ({oldest_local.get('time')})"
    )
    pool_items = []
    previous_time = None
    for card in source_fives[:match_idx]:
        previous_time = _append_rebuilt_five_star(
            pool_items, card, pool_id, source, previous_time
        )

    anchor = source_fives[match_idx]
    anchor_internal_idx = oldest_local.get("_internal_idx", -1)
    known_before_anchor = []
    for item in local_all:
        if item.get("_internal_idx", -2) == anchor_internal_idx:
            break
        known_before_anchor.append(item)

    expected_before_anchor = validate_draw_total(
        anchor.get("draw_total"),
        source,
        pool_id,
        str(anchor.get("name", "未知五星")),
    ) - 1
    missing = expected_before_anchor - len(known_before_anchor)
    if missing < 0:
        raise GachaMergeError(
            f"本地卡池[{pool_id}]锚点前已有{len(known_before_anchor)}抽，"
            f"超过{source}记录的{expected_before_anchor}抽"
        )
    filler_anchor_time = (
        known_before_anchor[0]["time"]
        if known_before_anchor
        else oldest_local["time"]
    )
    # 缺失抽位于已有真实抽之前，合成时间也必须早于最老的已知记录。
    filler_time = get_filler_time(filler_anchor_time, previous_time)
    for _ in range(missing):
        filler = FILLER_ITEM.copy()
        filler["cardPoolType"] = pool_id
        filler["time"] = filler_time
        pool_items.append(filler)
    pool_items.extend(local_all)
    return pool_items


def _merge_external_five_stars(
    original_data: dict,
    external_fives: list[dict],
    export_info: dict,
    source: str,
    skipped_pools: Optional[dict[str, str]] = None,
) -> tuple[dict, list[str]]:
    skipped: dict[str, str] = dict(skipped_pools or {})
    original_list = [
        {**item, "_internal_idx": index}
        for index, item in enumerate(original_data.get("list", []))
    ]
    for index, item in enumerate(external_fives):
        item.setdefault("_source_idx", index)

    original_pools = {
        str(item.get("cardPoolType"))
        for item in original_list
        if item.get("cardPoolType")
    }
    external_pools = {
        str(item.get("cardPoolType"))
        for item in external_fives
        if item.get("cardPoolType")
    }
    merged_list: list[dict] = []

    for pool_id in sorted(original_pools | external_pools):
        local_all = sorted(
            [
                item
                for item in original_list
                if str(item.get("cardPoolType")) == pool_id
            ],
            key=_sort_key_by_time,
        )
        local_all.reverse()
        source_fives = sorted(
            [
                item
                for item in external_fives
                if str(item.get("cardPoolType")) == pool_id
            ],
            key=lambda item: _sort_key_by_time(item, "_source_idx"),
        )
        source_fives.reverse()
        local_fives = [
            item for item in local_all if item.get("qualityLevel") == 5
        ]

        # 单池对齐失败只放弃该池，本地记录原样保留，留给下次合并。
        try:
            pool_items = _build_pool_items(
                pool_id, source, local_all, local_fives, source_fives
            )
        except GachaMergeError as exc:
            logger.warning(
                f"[鸣潮·抽卡合并] Pool {pool_id}: 放弃合并，保留本地记录: {exc}"
            )
            skipped[pool_id] = str(exc)
            pool_items = list(local_all)

        # 单池先按旧到新构建，再整体反转；不能再次只按秒排序。
        pool_items.reverse()
        for item in pool_items:
            item.pop("_internal_idx", None)
            item.pop("_source_idx", None)
        merged_list.extend(pool_items)

    warn_gacha_pity_violations(group_flat_gacha_logs(merged_list), source)
    notes = [
        f"[{_pool_display(pool_id)}] {reason}"
        for pool_id, reason in sorted(skipped.items())
    ]
    logger.success(
        f"[鸣潮·抽卡合并] {source}合并完成，共 {len(merged_list)} 条记录"
        f"，放弃 {len(notes)} 个卡池"
    )
    return {"info": export_info, "list": merged_list}, notes


def _parse_mcgf_card(card: dict, pool_id: str, source_idx: int) -> dict:
    card_name = str(card.get("name") or "")
    if not card_name:
        raise GachaMergeError("工坊五星记录缺少名称，无法安全导入")
    card_time = _validate_gacha_time(card.get("time"), "工坊", card_name)
    resource_id = card.get("resourceId", card.get("item_id"))
    if resource_id is None:
        raise GachaMergeError(f"工坊五星[{card_name}]缺少资源ID，无法安全导入")
    draw_total = validate_draw_total(
        card.get("draw_total"), "工坊", pool_id, card_name
    )
    return {
        "time": str(card_time),
        "name": card_name,
        "cardPoolType": pool_id,
        "draw_total": draw_total,
        "resourceId": resource_id,
        "qualityLevel": 5,
        "resourceType": card.get("resourceType", "角色"),
        "_source_idx": source_idx,
    }


def merge_gacha_data(
    original_data: dict, latest_data: dict
) -> tuple[dict, list[str]]:
    logger.debug("[鸣潮·抽卡处理] 开始合并工坊抽卡记录...")

    export_info = original_data.get("info", {})
    if not export_info:
        uid = latest_data.get("data", {}).get("uid")
        if uid:
            now = datetime.now()
            export_info = {
                "export_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "export_app": "WutheringWavesUID",
                "export_app_version": "v2.0",
                "export_timestamp": int(now.timestamp()),
                "version": "v2.0",
                "uid": str(uid),
            }
        else:
            logger.warning("[鸣潮·抽卡处理] 无法获取 UID，info 信息可能不完整")

    card_analysis = latest_data.get("data", {}).get(
        "card_analysis_json", {}
    )
    if not isinstance(card_analysis, dict):
        raise GachaMergeError("工坊抽卡分析数据格式异常")

    skipped_pools: dict[str, str] = {}
    pool_cards: dict[str, list[dict]] = {}
    # 只读取一级卡池汇总。嵌套版本统计会重复出现同一记录，且可能缺少卡池字段。
    for section in card_analysis.values():
        if not isinstance(section, dict):
            continue
        cards = section.get("five_cards")
        if not isinstance(cards, list):
            continue
        for card in cards:
            if not isinstance(card, dict):
                raise GachaMergeError("工坊五星记录格式异常")
            pool_type = card.get("cardPoolType")
            pool_id = str(POOL_TYPE_MAP.get(pool_type, pool_type or ""))
            if pool_id not in KNOWN_POOL_CODES:
                skipped_pools[pool_id or "未知"] = "该卡池类型暂不支持"
                continue
            pool_cards.setdefault(pool_id, []).append(card)

    latest_fives: list[dict] = []
    for pool_id, cards in pool_cards.items():
        try:
            parsed = [
                _parse_mcgf_card(card, pool_id, idx)
                for idx, card in enumerate(cards)
            ]
        except GachaMergeError as exc:
            logger.warning(f"[鸣潮·抽卡处理] 工坊卡池[{pool_id}]解析失败: {exc}")
            skipped_pools[pool_id] = str(exc)
            continue
        latest_fives.extend(parsed)

    # 国际服重定向: 存在全频调谐时, 武器精准调谐+角色 -> 角色常驻池。
    has_global_pool = any(
        item.get("cardPoolType") == "4" for item in latest_fives
    )
    if has_global_pool:
        for item in latest_fives:
            if (
                item.get("cardPoolType") == "2"
                and item.get("resourceType") == "角色"
            ):
                item["cardPoolType"] = "3"

    logger.debug(
        f"[鸣潮·抽卡处理] 解析出工坊五星记录 {len(latest_fives)} 条"
    )
    return _merge_external_five_stars(
        original_data, latest_fives, export_info, "工坊", skipped_pools
    )


# ========== 小黑盒导入 ==========

XHH_POOL_MAP = {
    "限定池": "1",
    "专武池": "2",
    "常驻池": "3",
    "武器池": "4",
    "新手池": "5",
    "联动角色池": "10",
    "联动武器池": "11",
}
# 小黑盒用 int64 上限标记“至今”垫抽汇总，它不是五星记录。
XHH_CURRENT_PITY_IDX = 2**63 - 1

_XHH_NAME_TO_ID: dict = {}


def _load_xhh_name_to_id():
    global _XHH_NAME_TO_ID
    if _XHH_NAME_TO_ID:
        return
    name_path = MAP_PATH / "id2name.json"
    if not name_path.exists():
        logger.warning(f"[鸣潮·小黑盒导入] 资源映射文件不存在: {name_path}")
        return
    with open(name_path, encoding="utf-8") as f:
        id2name = json.load(f)
    for resource_id, name in id2name.items():
        if name not in _XHH_NAME_TO_ID:
            _XHH_NAME_TO_ID[name] = int(resource_id)


def _xhh_ts_to_str(ts: object, name: str) -> str:
    if isinstance(ts, bool):
        raise GachaMergeError(f"小黑盒五星[{name}]的时间格式异常")
    try:
        timestamp = int(ts)  # type: ignore[arg-type]
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError) as exc:
        raise GachaMergeError(f"小黑盒五星[{name}]的时间格式异常") from exc


def _xhh_resource_type(rid: int) -> str:
    return "武器" if str(rid).startswith("21") else "角色"


# === 小黑盒 H5 签名纯 Python 实现 ===


def _xhh_md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _xhh_pick_chars(text: str, alphabet: str, end: int) -> str:
    chars = alphabet[:end]
    result = ""
    for ch in text:
        result += chars[ord(ch) % len(chars)]
    return result


def _xhh_pick_from_alphabet(text: str, alphabet: str) -> str:
    result = ""
    for ch in text:
        result += alphabet[ord(ch) % len(alphabet)]
    return result


def _xhh_interleave(parts: list) -> str:
    result = ""
    max_len = max(len(part) for part in parts)
    for idx in range(max_len):
        for part in parts:
            if idx < len(part):
                result += part[idx]
    return result


def _xhh_gf_double(value: int) -> int:
    return (255 & ((value << 1) ^ 27)) if (128 & value) else (value << 1)


def _xhh_mix_b(value: int) -> int:
    return _xhh_gf_double(value) ^ value


def _xhh_mix_n(value: int) -> int:
    return _xhh_mix_b(_xhh_gf_double(value))


def _xhh_mix_d(value: int) -> int:
    return _xhh_mix_n(_xhh_mix_b(_xhh_gf_double(value)))


def _xhh_mix_r(value: int) -> int:
    return _xhh_mix_d(value) ^ _xhh_mix_n(value) ^ _xhh_mix_b(value)


def _xhh_mix_vector(values: list) -> list:
    mixed = [0, 0, 0, 0]
    mixed[0] = (
        _xhh_mix_r(values[0])
        ^ _xhh_mix_d(values[1])
        ^ _xhh_mix_n(values[2])
        ^ _xhh_mix_b(values[3])
    )
    mixed[1] = (
        _xhh_mix_b(values[0])
        ^ _xhh_mix_r(values[1])
        ^ _xhh_mix_d(values[2])
        ^ _xhh_mix_n(values[3])
    )
    mixed[2] = (
        _xhh_mix_n(values[0])
        ^ _xhh_mix_b(values[1])
        ^ _xhh_mix_r(values[2])
        ^ _xhh_mix_d(values[3])
    )
    mixed[3] = (
        _xhh_mix_d(values[0])
        ^ _xhh_mix_n(values[1])
        ^ _xhh_mix_b(values[2])
        ^ _xhh_mix_r(values[3])
    )
    values[0] = mixed[0]
    values[1] = mixed[1]
    values[2] = mixed[2]
    values[3] = mixed[3]
    return values


def _xhh_hkey(path: str, ts: int, nonce: str) -> str:
    path_parts = [part for part in path.split("/") if part]
    sign_path = "/" + "/".join(path_parts) + "/"

    alphabet = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"
    time_part = _xhh_pick_chars(str(ts), alphabet, -2)
    path_part = _xhh_pick_from_alphabet(sign_path, alphabet)
    nonce_part = _xhh_pick_from_alphabet(nonce, alphabet)

    seed = _xhh_interleave([time_part, path_part, nonce_part])[:20]
    digest = _xhh_md5_hex(seed)

    tail_values = [ord(ch) for ch in digest[-6:]]
    mixed = _xhh_mix_vector(tail_values.copy())

    suffix = str(sum(mixed) % 100)
    if len(suffix) < 2:
        suffix = "0" + suffix

    return _xhh_pick_chars(digest[:5], alphabet, -4) + suffix


def gen_xhh_params(path: str, extra: Optional[dict] = None) -> dict:
    if extra is None:
        extra = {}
    ts = int(time.time())
    rand_str = str(random.random())
    nonce = _xhh_md5_hex(str(ts) + str(int(time.time() * 1000)) + rand_str).upper()

    params = {
        "hkey": _xhh_hkey(path, ts + 1, nonce),
        "nonce": nonce,
        "_time": ts,
        "os_type": "web",
        "version": "999.0.4",
    }
    params.update(extra)
    return params


# ================================


async def fetch_xhh_data(heybox_id: str) -> Optional[dict]:
    logger.debug(f"[鸣潮·小黑盒导入] 开始获取小黑盒数据 heybox_id: {heybox_id}")
    path = "/game/wuthering_waves/lottery_analyse"
    params = gen_xhh_params(path, {"heybox_id": heybox_id})
    url = "https://api.xiaoheihe.cn" + path

    try:
        async with aiohttp.ClientSession(connector=TCPConnector(ssl=False)) as session:
            async with session.get(url, params=params, timeout=15) as response:
                if response.status != 200:
                    logger.warning(f"[鸣潮·小黑盒导入] 请求失败 HTTP {response.status}")
                    return None
                resp = await response.json()

                if resp.get("status") != "ok":
                    logger.warning(f"[鸣潮·小黑盒导入] 上游返回错误: {resp.get('msg', '')}")
                    return None
                if not resp.get("result", {}).get("is_bind"):
                    logger.warning(f"[鸣潮·小黑盒导入] 该用户未导入鸣潮抽卡记录")
                    return None

                logger.success(
                    f"[鸣潮·小黑盒导入] 获取小黑盒数据成功 heybox_id: {heybox_id}"
                )
                return resp["result"]
    except Exception as e:
        logger.error(f"[鸣潮·小黑盒导入] 获取小黑盒数据发生异常: {e}")
    return None


def _parse_xhh_records(
    records: list, pool_code: str, pool_type: str
) -> list[dict]:
    parsed: list[dict] = []
    for rec in records:
        if not isinstance(rec, dict):
            raise GachaMergeError(f"小黑盒卡池[{pool_type}]五星记录格式异常")
        name = str(rec.get("name") or "")
        if not name:
            if rec.get("idx") in (
                XHH_CURRENT_PITY_IDX,
                str(XHH_CURRENT_PITY_IDX),
            ):
                continue
            raise GachaMergeError(f"小黑盒卡池[{pool_type}]五星记录缺少名称")
        time_str = _xhh_ts_to_str(rec.get("timestamp"), name)
        rid = _XHH_NAME_TO_ID.get(name)
        if rid is None:
            raise GachaMergeError(f"小黑盒五星[{name}]缺少资源映射，无法安全导入")
        draw_total = validate_draw_total(
            rec.get("diff"), "小黑盒", pool_code, name
        )
        parsed.append(
            {
                "time": time_str,
                "name": name,
                "cardPoolType": pool_code,
                "draw_total": draw_total,
                "resourceId": rid,
                "qualityLevel": 5,
                "resourceType": _xhh_resource_type(rid),
                "_source_idx": len(parsed),
            }
        )
    return parsed


def merge_xhh_data(
    original_data: dict, xhh_data: dict
) -> tuple[dict, list[str]]:
    logger.debug("[鸣潮·小黑盒导入] 开始合并抽卡记录...")
    _load_xhh_name_to_id()

    export_info = original_data.get("info", {})
    if not export_info:
        uid = str(xhh_data.get("user_info", {}).get("uid", ""))
        if uid:
            now = datetime.now()
            export_info = {
                "export_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "export_app": "XutheringWavesUID",
                "export_app_version": "v2.0",
                "export_timestamp": int(now.timestamp()),
                "version": "v2.0",
                "uid": uid,
            }

    # 从小黑盒 gacha_record 提取5★记录
    skipped_pools: dict[str, str] = {}
    xhh_5stars: list[dict] = []
    for pool in xhh_data.get("gacha_record", []):
        if not isinstance(pool, dict):
            raise GachaMergeError("小黑盒卡池记录格式异常")
        pool_type = pool.get("pool_type", "")
        pool_code = XHH_POOL_MAP.get(pool_type)
        records = pool.get("records", [])
        if not pool_code:
            if records:
                skipped_pools[pool_type or "未知"] = "该卡池类型暂不支持"
            continue
        if not isinstance(records, list):
            skipped_pools[pool_code] = "小黑盒返回的记录格式异常"
            continue
        try:
            parsed = _parse_xhh_records(records, pool_code, pool_type)
        except GachaMergeError as exc:
            logger.warning(f"[鸣潮·小黑盒导入] 卡池[{pool_code}]解析失败: {exc}")
            skipped_pools[pool_code] = str(exc)
            continue
        xhh_5stars.extend(parsed)

    logger.debug(f"[鸣潮·小黑盒导入] 解析出五星记录 {len(xhh_5stars)} 条")
    return _merge_external_five_stars(
        original_data, xhh_5stars, export_info, "小黑盒", skipped_pools
    )
