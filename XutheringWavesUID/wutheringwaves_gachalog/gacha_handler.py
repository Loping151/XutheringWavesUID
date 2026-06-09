import json
import hashlib
import time
import random
import string
import traceback
from typing import Optional
from datetime import datetime, timedelta

import aiohttp
from aiohttp import TCPConnector

from gsuid_core.logger import logger

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
}

FILLER_ITEM = {"resourceId": 21040023, "qualityLevel": 3, "resourceType": "武器", "name": "源能臂铠·测肆", "count": 1}


def _time_to_timestamp(time_str: str) -> float:
    if not time_str:
        return float("-inf")
    try:
        return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return float("-inf")


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


def merge_gacha_data(original_data: dict, latest_data: dict) -> dict:
    logger.debug("[鸣潮·抽卡处理] 开始合并抽卡记录...")

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
            logger.debug(f"[鸣潮·抽卡处理] 本地记录为空，已重建 info 信息 (UID: {uid})")
        else:
            logger.warning("[鸣潮·抽卡处理] 无法获取 UID，info 信息可能不完整")

    original_list = original_data.get("list", [])

    for idx, item in enumerate(original_list):
        item["_internal_idx"] = idx

    latest_5stars = []
    card_analysis = latest_data.get("data", {}).get("card_analysis_json", {})

    # 防御 card_analysis_json 多层嵌套都带 five_cards 时被同一张卡重复 append
    seen_5stars = set()

    def extract_five_cards(d):
        if isinstance(d, dict):
            if "five_cards" in d and isinstance(d["five_cards"], list):
                for card in d["five_cards"]:
                    p_type = card.get("cardPoolType")
                    p_type_code = POOL_TYPE_MAP.get(p_type, p_type)

                    card_name = card.get("name", "未知五星")
                    card_time = card.get("time", "")
                    draw_total = card.get("draw_total", 1)

                    if not card_time:
                        continue

                    dedup_key = (str(p_type_code), card_time, card_name, card.get("resourceId", card.get("item_id")))
                    if dedup_key in seen_5stars:
                        continue
                    seen_5stars.add(dedup_key)

                    latest_5stars.append(
                        {
                            "time": card_time,
                            "name": card_name,
                            "cardPoolType": p_type_code,
                            "draw_total": draw_total,
                            "resourceId": card.get("resourceId", card.get("item_id")),
                            "qualityLevel": 5,
                            "resourceType": card.get("resourceType", "角色"),
                            "is_latest": True,
                        }
                    )
            for k, v in d.items():
                extract_five_cards(v)
        elif isinstance(d, list):
            for item in d:
                extract_five_cards(item)

    extract_five_cards(card_analysis)

    # 国际服重定向: 存在全频调谐时, 武器精准调谐+角色 -> 角色调谐（常驻池）
    has_global_pool = any(x.get("cardPoolType") == "4" for x in latest_5stars)
    if has_global_pool:
        for x in latest_5stars:
            if x.get("cardPoolType") == "2" and x.get("resourceType") == "角色":
                x["cardPoolType"] = "3"

    logger.debug(f"[鸣潮·抽卡处理] 解析出最新五星记录 {len(latest_5stars)} 条")

    orig_types = [str(x.get("cardPoolType")) for x in original_list if x.get("cardPoolType")]
    latest_types = [str(x.get("cardPoolType")) for x in latest_5stars if x.get("cardPoolType")]

    all_pools = set(orig_types + latest_types)

    merged_list = []

    for pool_id in sorted(list(all_pools)):
        O_all = sorted(
            [x for x in original_list if str(x.get("cardPoolType")) == str(pool_id)],
            key=_sort_key_by_time,
        )
        O_all.reverse()
        L_5s = sorted(
            [x for x in latest_5stars if str(x.get("cardPoolType")) == str(pool_id)],
            key=_sort_key_by_time,
        )
        L_5s.reverse()

        O_5s = [x for x in O_all if x.get("qualityLevel") == 5]

        if O_5s:
            newest_local_time = _time_to_timestamp(O_5s[min(1, len(O_5s) - 1)]["time"])
            L_5s_filtered = [x for x in L_5s if _time_to_timestamp(x["time"]) < newest_local_time]
            logger.debug(
                f"[鸣潮·抽卡处理] Pool {pool_id}: 本地最早五星时间 {O_5s[min(1, len(O_5s) - 1)]['time']}, "
                f"过滤后保留 {len(L_5s_filtered)}/{len(L_5s)} 条工坊记录"
            )
            L_5s = L_5s_filtered

        pool_merged_items = []

        if not O_5s:
            if not int(pool_id) > 4:
                logger.debug(f"[鸣潮·抽卡处理] Pool {pool_id}: 无本地五星记录，不进行合并")
                pool_merged_items.extend(O_all)
            else:
                logger.debug(f"[鸣潮·抽卡处理] Pool {pool_id}: 无本地五星记录，重建所有历史")
                prev_five_star_time: Optional[str] = None
                for cp in L_5s:
                    filler_count = cp["draw_total"] - 1
                    filler_time = get_filler_time(cp["time"], prev_five_star_time)
                    for _ in range(filler_count):
                        f = FILLER_ITEM.copy()
                        f["cardPoolType"] = str(pool_id)
                        f["time"] = filler_time
                        pool_merged_items.append(f)
                    cp_item = {
                        "cardPoolType": str(pool_id),
                        "resourceId": cp["resourceId"],
                        "qualityLevel": 5,
                        "resourceType": cp["resourceType"],
                        "name": cp["name"],
                        "count": 1,
                        "time": cp["time"],
                    }
                    pool_merged_items.append(cp_item)
                    prev_five_star_time = cp["time"]
                pool_merged_items.extend(O_all)

        else:
            x = O_5s[0]
            logger.debug(f"[鸣潮·抽卡处理] Pool {pool_id}: 最早本地五星为 {x.get('name')} ({x.get('time')})")

            match_idx = None
            for i, cand in enumerate(L_5s):
                if cand["time"] == x["time"] and cand["name"] == x["name"]:
                    is_match = True
                    for offset in range(1, 3):
                        if (i + offset < len(L_5s)) and (offset < len(O_5s)):
                            l_next = L_5s[i + offset]
                            o_next = O_5s[offset]
                            if l_next["time"] != o_next["time"] or l_next["name"] != o_next["name"]:
                                is_match = False
                                break
                    if is_match:
                        match_idx = i
                        break

            if match_idx is None:
                logger.warning(f"[鸣潮·抽卡处理] Pool {pool_id}: 未找到五星匹配点，执行分离合并")
                prev_five_star_time: Optional[str] = None
                for cp in L_5s:
                    filler_count = cp["draw_total"] - 1
                    filler_time = get_filler_time(cp["time"], prev_five_star_time)
                    cp_item = {
                        "cardPoolType": str(pool_id),
                        "resourceId": cp["resourceId"],
                        "qualityLevel": 5,
                        "resourceType": cp["resourceType"],
                        "name": cp["name"],
                        "count": 1,
                        "time": cp["time"],
                    }
                    pool_merged_items.append(cp_item)
                    for _ in range(filler_count):
                        f = FILLER_ITEM.copy()
                        f["cardPoolType"] = str(pool_id)
                        f["time"] = filler_time
                        pool_merged_items.append(f)
                    prev_five_star_time = cp["time"]
                pool_merged_items.extend(O_all)

            else:
                logger.debug(f"[鸣潮·抽卡处理] Pool {pool_id}: 在索引 {match_idx} 处对其，重建之前历史")
                prev_five_star_time: Optional[str] = None
                for i in range(match_idx):
                    cp = L_5s[i]
                    filler_count = cp["draw_total"] - 1
                    filler_time = get_filler_time(cp["time"], prev_five_star_time)
                    cp_item = {
                        "cardPoolType": str(pool_id),
                        "resourceId": cp["resourceId"],
                        "qualityLevel": 5,
                        "resourceType": cp["resourceType"],
                        "name": cp["name"],
                        "count": 1,
                        "time": cp["time"],
                    }
                    pool_merged_items.append(cp_item)
                    for _ in range(filler_count):
                        f = FILLER_ITEM.copy()
                        f["cardPoolType"] = str(pool_id)
                        f["time"] = filler_time
                        pool_merged_items.append(f)
                    prev_five_star_time = cp["time"]

                cp_x = L_5s[match_idx]

                items_before_x = []
                target_internal_idx = x.get("_internal_idx", -1)

                for item in O_all:
                    if item.get("_internal_idx", -2) == target_internal_idx:
                        break
                    items_before_x.append(item)

                count_existing = len(items_before_x)
                target_count = cp_x["draw_total"] - 1

                diff = target_count - count_existing
                logger.debug(
                    f"[鸣潮·抽卡处理] Pool {pool_id}: 连接点需填充 {diff} (目标 {target_count} - 现有 {count_existing})"
                )

                if diff > 0:
                    filler_time = get_filler_time(x["time"], prev_five_star_time)
                    fillers = []
                    for _ in range(diff):
                        f = FILLER_ITEM.copy()
                        f["cardPoolType"] = str(pool_id)
                        f["time"] = filler_time
                        fillers.append(f)
                    pool_merged_items.extend(fillers)

                pool_merged_items.extend(O_all)

        merged_list.extend(pool_merged_items)

    merged_list.sort(key=_sort_key_by_time)
    for item in merged_list:
        if "_internal_idx" in item:
            del item["_internal_idx"]
    logger.success(f"[鸣潮·抽卡处理] 合并完成，共 {len(merged_list)} 条记录")

    return {"info": export_info, "list": merged_list}


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

_XHH_NAME2ID: dict = {}


def _load_xhh_name2id():
    global _XHH_NAME2ID
    if _XHH_NAME2ID:
        return
    p = MAP_PATH / "id2name.json"
    if not p.exists():
        logger.warning(f"[鸣潮·小黑盒导入] 资源映射文件不存在: {p}")
        return
    with open(p, encoding="utf-8") as f:
        id2name = json.load(f)
    for k, v in id2name.items():
        if v not in _XHH_NAME2ID:
            _XHH_NAME2ID[v] = int(k)


def _xhh_ts_to_str(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _xhh_resource_type(rid: int) -> str:
    return "武器" if str(rid).startswith("21") else "角色"


# === 小黑盒 H5 签名纯 Python 实现 ===

def _xhh_md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _xhh_dollar(t: str, e: str, n: int) -> str:
    r = e[:n] if n < 0 else e[:n]
    i = ""
    for o in range(len(t)):
        a = ord(t[o])
        s = a % len(r)
        i += r[s]
    return i


def _xhh_U(t: str, e: str) -> str:
    n = ""
    for i in range(len(t)):
        r = ord(t[i])
        o = r % len(e)
        n += e[o]
    return n


def _xhh_J(t: list) -> str:
    e = ""
    max_len = max(len(x) for x in t)
    for n in range(max_len):
        for p in t:
            if n < len(p):
                e += p[n]
    return e


def _xhh_j(t: int) -> int:
    return (255 & ((t << 1) ^ 27)) if (128 & t) else (t << 1)


def _xhh_B(t: int) -> int:
    return _xhh_j(t) ^ t


def _xhh_N(t: int) -> int:
    return _xhh_B(_xhh_j(t))


def _xhh_D(t: int) -> int:
    return _xhh_N(_xhh_B(_xhh_j(t)))


def _xhh_R(t: int) -> int:
    return _xhh_D(t) ^ _xhh_N(t) ^ _xhh_B(t)


def _xhh_V(t: list) -> list:
    e = [0, 0, 0, 0]
    e[0] = _xhh_R(t[0]) ^ _xhh_D(t[1]) ^ _xhh_N(t[2]) ^ _xhh_B(t[3])
    e[1] = _xhh_B(t[0]) ^ _xhh_R(t[1]) ^ _xhh_D(t[2]) ^ _xhh_N(t[3])
    e[2] = _xhh_N(t[0]) ^ _xhh_B(t[1]) ^ _xhh_R(t[2]) ^ _xhh_D(t[3])
    e[3] = _xhh_D(t[0]) ^ _xhh_N(t[1]) ^ _xhh_B(t[2]) ^ _xhh_R(t[3])
    t[0] = e[0]
    t[1] = e[1]
    t[2] = e[2]
    t[3] = e[3]
    return t


def _xhh_q(t: list) -> int:
    return sum(t)


def _xhh_W(path: str, ts: int, nonce: str) -> str:
    path_parts = [p for p in path.split("/") if p]
    t = "/" + "/".join(path_parts) + "/"

    i = "AB45STUVWZEFGJ6CH01D237IXYPQRKLMN89"
    r = _xhh_dollar(str(ts), i, -2)
    o = _xhh_U(t, i)
    a = _xhh_U(nonce, i)

    s = _xhh_J([r, o, a])[:20]
    c = _xhh_md5(s)

    t_arr = [ord(ch) for ch in c[-6:]]
    vt = _xhh_V(t_arr.copy())

    u = str(_xhh_q(vt) % 100)
    if len(u) < 2:
        u = "0" + u

    return _xhh_dollar(c[:5], i, -4) + u


def gen_xhh_params(path: str, extra: dict = None) -> dict:
    if extra is None:
        extra = {}
    ts = int(time.time())
    rand_str = str(random.random())
    nonce = _xhh_md5(str(ts) + str(int(time.time() * 1000)) + rand_str).upper()

    params = {
        "hkey": _xhh_W(path, ts + 1, nonce),
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

                logger.success(f"[鸣潮·小黑盒导入] 获取小黑盒数据成功 heybox_id: {heybox_id}")
                return resp["result"]
    except Exception as e:
        logger.error(f"[鸣潮·小黑盒导入] 获取小黑盒数据发生异常: {e}")
    return None


def merge_xhh_data(original_data: dict, xhh_data: dict) -> dict:
    logger.debug("[鸣潮·小黑盒导入] 开始合并抽卡记录...")
    _load_xhh_name2id()

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

    original_list = original_data.get("list", [])
    for idx, item in enumerate(original_list):
        item["_internal_idx"] = idx

    # 从小黑盒 gacha_record 提取5★记录
    xhh_5stars = []
    for pool in xhh_data.get("gacha_record", []):
        pool_type = pool.get("pool_type", "")
        pool_code = XHH_POOL_MAP.get(pool_type)
        if not pool_code:
            continue
        for idx, rec in enumerate(pool.get("records", [])):
            if "name" not in rec:
                continue
            name = rec["name"]
            ts = rec["timestamp"]
            time_str = _xhh_ts_to_str(ts)
            rid = _XHH_NAME2ID.get(name)
            if rid is None:
                logger.warning(f"[鸣潮·小黑盒导入] 未找到 name->id 映射: {name}")
                continue
            xhh_5stars.append({
                "time": time_str,
                "name": name,
                "cardPoolType": pool_code,
                "draw_total": rec["diff"],
                "resourceId": rid,
                "qualityLevel": 5,
                "resourceType": _xhh_resource_type(rid),
                "_xhh_idx": idx,  # 记录原始 JSON 数组中的顺序 (0=最新, 1=较旧...)
            })

    logger.debug(f"[鸣潮·小黑盒导入] 解析出五星记录 {len(xhh_5stars)} 条")

    orig_types = [str(x.get("cardPoolType")) for x in original_list if x.get("cardPoolType")]
    xhh_types = [str(x.get("cardPoolType")) for x in xhh_5stars if x.get("cardPoolType")]
    all_pools = set(orig_types + xhh_types)

    merged_list = []

    for pool_id in sorted(list(all_pools)):
        order_idx = 0

        def append_xhh_5star(items: list, cp: dict) -> None:
            nonlocal order_idx
            cp_item = {
                "cardPoolType": str(pool_id),
                "resourceId": cp["resourceId"],
                "qualityLevel": 5,
                "resourceType": cp["resourceType"],
                "name": cp["name"],
                "count": 1,
                "time": cp["time"],
                "_internal_idx": order_idx,
            }
            items.append(cp_item)
            order_idx += 1
            for _ in range(max(cp["draw_total"] - 1, 0)):
                f = FILLER_ITEM.copy()
                f["cardPoolType"] = str(pool_id)
                f["time"] = cp["time"]
                f["_internal_idx"] = order_idx
                items.append(f)
                order_idx += 1

        O_all = sorted(
            [x for x in original_list if str(x.get("cardPoolType")) == str(pool_id)],
            key=_sort_key_by_time,
        )
        O_all.reverse()
        L_5s = sorted(
            [x for x in xhh_5stars if str(x.get("cardPoolType")) == str(pool_id)],
            key=lambda x: (_sort_key_by_time(x), -x.get("_xhh_idx", 0)),
        )
        L_5s.reverse()

        O_5s = [x for x in O_all if x.get("qualityLevel") == 5]

        # 只保留比本地最早5★更早的小黑盒5★
        if O_5s:
            newest_local_time = _time_to_timestamp(O_5s[min(1, len(O_5s) - 1)]["time"])
            L_5s_filtered = [x for x in L_5s if _time_to_timestamp(x["time"]) < newest_local_time]
            logger.debug(
                f"[鸣潮·小黑盒导入] Pool {pool_id}: 本地最早五星时间 {O_5s[min(1, len(O_5s) - 1)]['time']}, "
                f"过滤后保留 {len(L_5s_filtered)}/{len(L_5s)} 条小黑盒记录"
            )
            L_5s = L_5s_filtered

        pool_merged_items = []

        if not O_5s:
            if not int(pool_id) > 4:
                logger.debug(f"[鸣潮·小黑盒导入] Pool {pool_id}: 无本地五星记录，不进行合并")
                pool_merged_items.extend(O_all)
            else:
                logger.debug(f"[鸣潮·小黑盒导入] Pool {pool_id}: 无本地五星记录，重建所有历史")
                for cp in L_5s:
                    append_xhh_5star(pool_merged_items, cp)
                pool_merged_items.extend(O_all)

        else:
            x = O_5s[0]
            logger.debug(f"[鸣潮·小黑盒导入] Pool {pool_id}: 最早本地五星为 {x.get('name')} ({x.get('time')})")

            match_idx = None
            for i, cand in enumerate(L_5s):
                if cand["time"] == x["time"] and cand["name"] == x["name"]:
                    is_match = True
                    for offset in range(1, 3):
                        if (i + offset < len(L_5s)) and (offset < len(O_5s)):
                            l_next = L_5s[i + offset]
                            o_next = O_5s[offset]
                            if l_next["time"] != o_next["time"] or l_next["name"] != o_next["name"]:
                                is_match = False
                                break
                    if is_match:
                        match_idx = i
                        break

            if match_idx is None:
                logger.warning(f"[鸣潮·小黑盒导入] Pool {pool_id}: 未找到五星匹配点，执行分离合并")
                for cp in L_5s:
                    append_xhh_5star(pool_merged_items, cp)
                pool_merged_items.extend(O_all)

            else:
                logger.debug(f"[鸣潮·小黑盒导入] Pool {pool_id}: 在索引 {match_idx} 处对其，重建之前历史")
                for i in range(match_idx):
                    append_xhh_5star(pool_merged_items, L_5s[i])

                cp_x = L_5s[match_idx]

                items_before_x = []
                target_internal_idx = x.get("_internal_idx", -1)

                for item in O_all:
                    if item.get("_internal_idx", -2) == target_internal_idx:
                        break
                    items_before_x.append(item)

                count_existing = len(items_before_x)
                target_count = cp_x["draw_total"] - 1

                diff = target_count - count_existing
                logger.debug(
                    f"[鸣潮·小黑盒导入] Pool {pool_id}: 连接点需填充 {diff} (目标 {target_count} - 现有 {count_existing})"
                )

                if diff > 0:
                    for _ in range(diff):
                        f = FILLER_ITEM.copy()
                        f["cardPoolType"] = str(pool_id)
                        f["time"] = x["time"]
                        pool_merged_items.append(f)

                pool_merged_items.extend(O_all)

        merged_list.extend(pool_merged_items)

    merged_list.sort(key=_sort_key_by_time)
    for item in merged_list:
        if "_internal_idx" in item:
            del item["_internal_idx"]
        if "_xhh_idx" in item:
            del item["_xhh_idx"]
    logger.success(f"[鸣潮·小黑盒导入] 合并完成，共 {len(merged_list)} 条记录")

    return {"info": export_info, "list": merged_list}
