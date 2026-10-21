"""自定义权重 (www.loping151.site): 下载缓存、订阅同步、每条指令的生效方案、使用上报。

生效优先级: 指令里的 cw_ID > 群权重(群订阅含该角色) > 个人设置/个人订阅 > 内置。
总排行上传与综合评分始终走内置权重。

角色设置存成扁平条目 {键: 权重ID}: 键 "1603" 是无条件权重, "1603[00,61]" 是条件权重,
配置码 = 共鸣链数 + 专武谐振阶(没装专武为 0)。角色配置命中条件用条件权重, 否则用无条件权重。
"""

import json
import time
import asyncio
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

import httpx

from gsuid_core.logger import logger
from gsuid_core.data_store import get_res_path

CW_PATTERN = r"[cC][wW]_[0-9a-zA-Z]{8}"
WS_PATTERN = r"[wW][sS]_[0-9a-zA-Z]{8}"
CW_RE = re.compile(CW_PATTERN)
WS_RE = re.compile(WS_PATTERN)
CW_ID = re.compile(r"cw_[0-9a-z]{8}")
WS_ID = re.compile(r"ws_[0-9a-z]{8}")
ENTRY_RE = re.compile(r"\s*[\"']?(\d{4})\s*(?:[\[【(（]([^\]】)）]*)[\]】)）])?[\"']?\s*[-:：=]\s*[\"']?(" + CW_PATTERN + r")")
NEXT_RE = re.compile(r"\s*[,，;；|]\s*|\s+(?=\d{4})")
KEY_RE = re.compile(r"(\d{4})(?:\[([0-9,]+)\])?")
CODE_RE = re.compile(r"[0-6][0-5]")
DEFAULT_AUTHOR = re.compile(r"用户[0-9a-z]{8}")

CACHE_DIR: Path = get_res_path("XutheringWavesUID") / "custom_weights"
ROVER = {"1502": "1501", "1605": "1604", "1408": "1406", "1310": "1309"}
REFRESH_AFTER = 86400
CHECK_TTL = 30
MISS_TTL = 600
SITE = "https://www.loping151.site"

_client: Optional[httpx.AsyncClient] = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=5.0), headers={"User-Agent": "XutheringWavesUID"})
    return _client


def norm_id(raw: str) -> str:
    s = (raw or "").strip().lower()
    if len(s) < 3:
        return s
    return s[:3] + s[3:].replace("i", "1").replace("l", "1").replace("o", "0")


def find_cw(text: str) -> Optional[str]:
    m = CW_RE.search(text or "")
    return norm_id(m.group(0)) if m else None


def find_ws(text: str) -> Optional[str]:
    m = WS_RE.search(text or "")
    return norm_id(m.group(0)) if m else None


def canon_char(cid) -> str:
    s = str(cid)
    return ROVER.get(s, s)


# ---------------- 条目与配置码 ----------------


def entry_key(cid, codes: Iterable[str] = ()) -> str:
    codes = sorted(set(codes))
    return f"{canon_char(cid)}[{','.join(codes)}]" if codes else canon_char(cid)


def split_key(key: str) -> Tuple[str, FrozenSet[str]]:
    m = KEY_RE.fullmatch(key)
    if not m:
        return key, frozenset()
    return m.group(1), frozenset(m.group(2).split(",")) if m.group(2) else frozenset()


def chars_of(entries: Dict[str, str]) -> Set[str]:
    return {split_key(k)[0] for k in entries}


def char_entries(entries: Dict[str, str], cid) -> Dict[str, str]:
    cid = canon_char(cid)
    return {k: v for k, v in entries.items() if split_key(k)[0] == cid}


def replace_chars(entries: Dict[str, str], new: Dict[str, str]) -> None:
    """new 里出现的角色整体替换(无条件 + 条件一起)。"""
    chars = chars_of(new)
    for k in [k for k in entries if split_key(k)[0] in chars]:
        entries.pop(k)
    entries.update(new)


def pick_key(entries: Dict[str, str], cid, code: Optional[str]) -> Optional[str]:
    """该角色在这份设置里实际生效的条目键: 命中的条件优先, 否则无条件。"""
    default = None
    for k in char_entries(entries, cid):
        codes = split_key(k)[1]
        if not codes:
            default = k
        elif code in codes:
            return k
    return default


def pick_entry(entries: Dict[str, str], cid, code: Optional[str]) -> Optional[str]:
    k = pick_key(entries, cid, code)
    return entries[k] if k else None


def code_text(code: str) -> str:
    return f"{code[0]}链 · " + ("无专武" if code[1] == "0" else f"专武谐振{code[1]}阶")


def brief(entries: Dict[str, str]) -> str:
    """某角色设置的简述: cw_xxx / cw_xxx+2个条件权重 / 2个条件权重。"""
    default = next((w for k, w in entries.items() if not split_key(k)[1]), "")
    n = len(entries) - (1 if default else 0)
    if not n:
        return default
    return f"{default}+{n}个条件权重" if default else f"{n}个条件权重"


def sub_entries(data: dict) -> Dict[str, str]:
    """订阅接口的 items(无条件) + rules(条件) 转成条目。"""
    out: Dict[str, str] = {}
    for k, v in (data.get("items") or {}).items():
        wid = norm_id(str(v))
        if str(k).isdigit() and CW_ID.fullmatch(wid):
            out[entry_key(k)] = wid
    for k, rules in (data.get("rules") or {}).items():
        if not str(k).isdigit() or not isinstance(rules, list):
            continue
        for r in rules:
            if not isinstance(r, dict):
                continue
            wid = norm_id(str(r.get("weight") or ""))
            codes = [c for c in r.get("codes") or [] if CODE_RE.fullmatch(str(c))]
            if codes and CW_ID.fullmatch(wid):
                out[entry_key(k, codes)] = wid
    return out


_sig: Tuple[int, Dict[str, str]] = (0, {})


def _build_signatures(nc) -> Dict[str, str]:
    ids: Dict[str, List[str]] = {}
    weapons: Dict[str, str] = {}
    for i, name in nc.id2name.items():
        if len(i) == 4:
            ids.setdefault(name, []).append(i)
        elif len(i) == 8 and i.startswith("21"):
            weapons[name] = i

    def chars(a: str) -> List[str]:
        if a in ids:
            return ids[a]
        hits = {n for n, aliases in nc.char_alias_data.items() if a in aliases}
        return ids.get(hits.pop(), []) if len(hits) == 1 else []

    sig: Dict[str, str] = {}
    for wname, aliases in nc.weapon_alias_data.items():
        wid = weapons.get(wname)
        for a in aliases if wid else []:
            a = a.strip()
            if a.endswith("专武"):
                for cid in chars(a[:-2].strip()):
                    sig[cid] = wid
    return sig


def signature_weapon(cid) -> Optional[str]:
    """专武: 武器别名里「角色名/别名+专武」, 与权重站一致。"""
    global _sig
    from . import name_convert as nc

    nc.ensure_data_loaded()
    src = (nc.weapon_alias_data, nc.char_alias_data, nc.id2name)
    if _sig[0] is None or any(a is not b for a, b in zip(_sig[0], src)):
        _sig = (src, _build_signatures(nc))
    return _sig[1].get(str(cid))


def _field(o, name: str):
    return o.get(name) if isinstance(o, dict) else getattr(o, name, None)


def role_code(role) -> Optional[str]:
    """角色配置码, 如 "61" = 6 链 + 专武 1 阶; role 可以是 RoleDetailData / 原始 dict / 现成的码。"""
    if role is None or isinstance(role, str):
        return role if role and CODE_RE.fullmatch(role) else None
    try:
        chain = sum(1 for c in _field(role, "chainList") or [] if _field(c, "unlocked"))
        wd = _field(role, "weaponData")
        rid = _field(_field(role, "role"), "roleId")
        sig = str(_field(_field(wd, "weapon"), "weaponId")) == signature_weapon(rid)
        rank = (_field(wd, "resonLevel") or 0) if sig else 0
        return f"{min(chain, 6)}{min(max(int(rank), 0), 5)}"
    except Exception as e:
        logger.debug(f"[鸣潮·自定义权重] 配置码解析失败: {e}")
        return None


def _config(key: str, default):
    try:
        from ..wutheringwaves_config import WutheringWavesConfig

        v = WutheringWavesConfig.get_config(key).data
        return default if v is None or v == "" else v
    except Exception:
        return default


def enabled() -> bool:
    return bool(_config("CustomWeightEnable", True))


def api_base() -> str:
    return str(_config("CustomWeightApi", SITE)).rstrip("/")


# ---------------- 权重文件 ----------------

_mem: Dict[str, dict] = {}
_miss: Dict[str, float] = {}
_inflight: Dict[str, "asyncio.Task[Optional[dict]]"] = {}


def _valid(w) -> bool:
    try:
        c = w["calc"]
        return (
            isinstance(w.get("id"), str)
            and int(w.get("char_id"))
            and len(c["score_max"]) == 3
            and all(float(x) > 0 for x in c["score_max"])
            and isinstance(c["sub_props"], dict)
            and isinstance(c["main_props"], dict)
            and len(c["props_grade"]) == 3
            and isinstance(c["total_grade"], list)
            and isinstance(c["grade"], dict)
        )
    except Exception:
        return False


def _path(wid: str) -> Path:
    return CACHE_DIR / f"{wid}.json"


def cached_weight(wid: str) -> Optional[dict]:
    wid = norm_id(wid)
    if not CW_ID.fullmatch(wid):
        return None
    w = _mem.get(wid)
    if w is not None:
        return w
    p = _path(wid)
    if not p.exists():
        return None
    try:
        w = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not _valid(w):
        return None
    if len(_mem) > 2000:
        _mem.clear()
    _mem[wid] = w
    return w


async def _download(wid: str) -> Optional[dict]:
    old = cached_weight(wid)
    etag = (old or {}).get("_etag")
    try:
        resp = await _http().get(f"{api_base()}/api/w/{wid}", headers={"If-None-Match": etag} if etag else None)
    except Exception as e:
        logger.warning(f"[鸣潮·自定义权重] 下载 {wid} 失败: {e}")
        return None
    if resp.status_code == 304 and old is not None:
        w = old
    elif resp.status_code == 404:
        _note_miss(wid)
        return None
    elif resp.status_code != 200:
        logger.warning(f"[鸣潮·自定义权重] 下载 {wid} 状态码 {resp.status_code}")
        return None
    else:
        try:
            w = resp.json()
        except Exception:
            return None
        if not _valid(w) or norm_id(w["id"]) != wid:
            logger.warning(f"[鸣潮·自定义权重] {wid} 内容无效")
            return None
        w["_etag"] = resp.headers.get("ETag", "")
    w["_fetched_at"] = int(time.time())
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(wid).with_suffix(".tmp")
    tmp.write_text(json.dumps(w, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_path(wid))
    _mem[wid] = w
    return w


def _note_miss(wid: str):
    now = time.time()
    if len(_miss) > 5000:
        for k in [k for k, t in _miss.items() if now - t >= MISS_TTL]:
            _miss.pop(k, None)
        if len(_miss) > 5000:
            _miss.clear()
    _miss[wid] = now


async def _download_safe(wid: str) -> Optional[dict]:
    try:
        return await _download(wid)
    except Exception as e:
        logger.warning(f"[鸣潮·自定义权重] 下载 {wid} 异常: {e}")
        return None


async def fetch_weight(wid: str) -> Optional[dict]:
    """下载(并发合并到同一个任务); 调用方取消不影响别的等待者。失败返回 None。"""
    wid = norm_id(wid)
    if not CW_ID.fullmatch(wid):
        return None
    task = _inflight.get(wid)
    if task is None:
        task = asyncio.create_task(_download_safe(wid))
        _inflight[wid] = task
        task.add_done_callback(lambda _t, k=wid: _inflight.pop(k, None))
    return await asyncio.shield(task)


_bg: set = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _bg.add(task)
    task.add_done_callback(_bg.discard)


async def get_weight(wid: str) -> Optional[dict]:
    """本地有就用(权重内容按 ID 不变), 名称/作者过期后台刷新。"""
    wid = norm_id(wid)
    if not CW_ID.fullmatch(wid):
        return None
    w = cached_weight(wid)
    if w is not None:
        if time.time() - float(w.get("_fetched_at", 0)) > REFRESH_AFTER and wid not in _inflight:
            _spawn(fetch_weight(wid))
        return w
    if time.time() - _miss.get(wid, 0) < MISS_TTL:
        return None
    return await fetch_weight(wid)


def weight_author(w: dict) -> str:
    a = (w.get("author") or "").strip()
    return "" if DEFAULT_AUTHOR.fullmatch(a) else a


def weight_label(w: dict) -> str:
    return "-".join(x for x in (weight_author(w), w.get("name") or "未命名", w["id"]) if x)


def calc_of(w: dict) -> dict:
    c = dict(w["calc"])
    c["name"] = weight_label(w)
    c["_cw_id"] = w["id"]
    c["_cw_label"] = c["name"]
    return c


def char_name_of(cid) -> str:
    try:
        from .name_convert import easy_id_to_name

        return easy_id_to_name(str(cid), str(cid)) or str(cid)
    except Exception:
        return str(cid)


async def check_weight(wid: str, want: Optional[Iterable] = None) -> Tuple[Optional[dict], str]:
    """取权重并核对角色(want=None 不限)。返回 (权重, 错误)。"""
    w = await get_weight(wid)
    if w is None:
        return None, f"权重 {wid} 不存在或暂时无法下载，请检查 ID"
    cids = _cids(want)
    cid = canon_char(w.get("char_id"))
    if cids is not None and cid not in cids:
        names = "、".join(char_name_of(c) for c in sorted(cids))
        return None, f"权重 {wid} 属于【{w.get('char_name') or char_name_of(cid)}】，与【{names}】不符"
    return w, ""


# ---------------- 订阅 ----------------

_check_cache: Dict[Tuple[str, str], Tuple[float, dict]] = {}


async def check_sub(sub_id: str, sub_hash: str = "") -> Optional[dict]:
    """None = 网络失败; {"missing": True} = 订阅不存在; 否则 {"hash","changed","items"?(条目),"public","name"}。"""
    sub_id = norm_id(sub_id)
    if not WS_ID.fullmatch(sub_id):
        return {"missing": True}
    key = (sub_id, sub_hash)
    hit = _check_cache.get(key)
    if hit and time.time() - hit[0] < CHECK_TTL:
        return hit[1]
    try:
        resp = await _http().get(f"{api_base()}/api/subs/{sub_id}/check", params={"h": sub_hash})
    except Exception as e:
        logger.warning(f"[鸣潮·自定义权重] 订阅 {sub_id} 检查失败: {e}")
        return None
    if resp.status_code == 404:
        data = {"missing": True}
    elif resp.status_code != 200:
        return None
    else:
        try:
            data = resp.json().get("data") or {}
        except Exception:
            return None
        if data.get("changed"):
            data["items"] = sub_entries(data)
    if len(_check_cache) > 5000:
        _check_cache.clear()
    _check_cache[key] = (time.time(), data)
    return data


# ---------------- 热度上报 ----------------
# 只报「某 UID 当前设了哪些权重 / 跟随哪个订阅」, 经编译模块签名发给总排行再转权重站;
# 设置变化时报一次, 平时每个 UID 每天最多报一次心跳。只统计登录绑定的 UID。

_heartbeat: Dict[str, str] = {}


def _heat_uploader():
    try:
        from .waves_build.upload_gateway import upload_weight_heat
    except ImportError:
        return None
    return upload_weight_heat


async def _login_bound(uid: str, user_id: str, bot_id: str) -> bool:
    from .constants import WAVES_GAME_ID
    from .database.models import WavesUser

    try:
        user = await WavesUser.select_waves_user(uid, user_id, bot_id, game_id=WAVES_GAME_ID)
    except Exception:
        return False
    return bool(user and user.cookie and user.status != "无效")


async def role_codes(uid) -> Dict[str, Optional[str]]:
    """该 UID 本地面板缓存里各角色当前的配置码(rawData 只有当前属性的漂泊者, 其余在 rover.json)。"""
    from .player_store import read_player_json
    from .resource.RESOURCE_PATH import PLAYER_PATH

    roles = list(await read_player_json(PLAYER_PATH / str(uid) / "rawData.json") or [])
    rover = await read_player_json(PLAYER_PATH / str(uid) / "rover.json")
    if isinstance(rover, dict):
        roles.extend(rover.values())
    return {canon_char(_field(_field(r, "role"), "roleId")): role_code(r) for r in roles}


async def _heat_slots(uid: str, entries: Dict[str, str]) -> Dict[str, str]:
    """条目按该 UID 各角色当前配置取实际生效的权重, 每个角色一个。"""
    codes = await role_codes(uid) if any(split_key(k)[1] for k in entries) else {}
    out = {}
    for cid in chars_of(entries):
        wid = pick_entry(entries, cid, codes.get(cid))
        if wid:
            out[cid] = wid
    return out


async def _heat_job(upload, item: dict, user_id: str, bot_id: str):
    if await _login_bound(item["waves_id"], user_id, bot_id):
        item["weights"] = await _heat_slots(item["waves_id"], item["weights"])
        await upload(item)


def _send_heat(uid, weights: Dict[str, str], sub_id: str, user_id, bot_id, group_subs: Optional[List[str]] = None):
    upload = _heat_uploader()
    uid = str(uid or "")
    if upload is None or not uid.isdigit() or not enabled():
        return
    item = {"waves_id": uid, "snapshot": True, "weights": dict(weights), "sub": sub_id or "",
            "group_subs": group_subs or [], "ts": int(time.time() * 1000)}
    _spawn(_heat_job(upload, item, str(user_id or ""), str(bot_id or "")))


def report_settings(row) -> None:
    """个人设置变化后立即上报快照(清空时报空表)。"""
    _heartbeat[str(row.uid)] = time.strftime("%Y%m%d")
    _send_heat(row.uid, row.weight_map(), row.sub_id, row.user_id, row.bot_id)


async def save_settings(row) -> None:
    from .database.waves_custom_weight import WavesCustomWeight

    await WavesCustomWeight.save_row(row)
    report_settings(row)


async def clear_settings(row) -> None:
    from .database.waves_custom_weight import WavesCustomWeight

    await WavesCustomWeight.delete_row(row.user_id, row.bot_id, row.uid)
    row.sub_id, row.sub_hash = "", ""
    row.set_maps(weights={}, sub_items={})
    report_settings(row)


def _report_heartbeat(uid, weights: Dict[str, str], sub_id: str, group_sub: str, user_id, bot_id):
    day = time.strftime("%Y%m%d")
    if _heartbeat.get(str(uid)) == day or not (weights or sub_id or group_sub):
        return
    if len(_heartbeat) > 50000:
        _heartbeat.clear()
    _heartbeat[str(uid)] = day
    _send_heat(uid, weights, sub_id, user_id, bot_id, [group_sub] if group_sub else [])


# ---------------- 生效方案 ----------------

SOURCE_NAME = {"cmd": "指令指定", "group": "群权重", "personal": "个人设置", "sub": "个人订阅"}


@dataclass
class Choice:
    wid: str
    source: str
    weight: dict
    codes: FrozenSet[str] = frozenset()  # 空 = 无条件


@dataclass
class WeightPlan:
    # 每个角色按优先级排好的候选: 逐层先条件后无条件, 取第一个命中的
    choices: Dict[str, List[Choice]] = field(default_factory=dict)
    notices: List[str] = field(default_factory=list)
    error: str = ""
    echo: bool = True  # False: 只给综合评分提供达标共效, 声骸评分仍用内置

    def candidates(self, cid) -> List[Choice]:
        """外部模块(wwcalc/OcrCalc)仍可能直接塞单个 Choice。"""
        v = self.choices.get(canon_char(cid))
        return v if isinstance(v, list) else ([v] if v else [])

    def choice(self, cid, role=None) -> Optional[Choice]:
        """role 为该角色面板数据或配置码; 拿不到配置时只看无条件权重。"""
        code = role_code(role)
        for c in self.candidates(cid):
            if not c.codes or code in c.codes:
                return c
        return None

    def calc_for(self, cid, role=None) -> Optional[dict]:
        c = self.choice(cid, role)
        return calc_of(c.weight) if c else None

    def label_for(self, cid, role=None) -> Optional[str]:
        c = self.choice(cid, role)
        return weight_label(c.weight) if c else None

    def cond_count(self, cid) -> int:
        return len({c.wid for c in self.candidates(cid) if c.codes})

    def resolved(self, codes: Dict[str, Optional[str]]) -> Dict[str, str]:
        """按各角色配置码取定的 {角色: 权重ID}, 给只认单个权重的服务。"""
        out = {}
        for cid in self.choices:
            c = self.choice(cid, codes.get(cid))
            if c:
                out[cid] = c.wid
        return out


_PLAN: ContextVar[Optional[WeightPlan]] = ContextVar("waves_custom_weight_plan", default=None)


def current_plan() -> Optional[WeightPlan]:
    return _PLAN.get()


def override_calc(char_id, role=None) -> Optional[dict]:
    plan = _PLAN.get()
    if plan is None or not plan.echo or char_id is None:
        return None
    return plan.calc_for(char_id, role)


def custom_energy(char_id, role=None) -> Optional[Tuple[float, str]]:
    """当前方案里该角色自定义权重的 (达标共鸣效率%, 权重标签); 没设则 None。"""
    plan = _PLAN.get()
    c = plan.choice(char_id, role) if plan and char_id is not None else None
    v = (c.weight.get("spec") or {}).get("energy_target") if c else None
    return (float(v), weight_label(c.weight)) if v else None


def activate(plan: Optional[WeightPlan]):
    return _PLAN.set(plan)


@contextmanager
def using(plan: Optional[WeightPlan]):
    token = _PLAN.set(plan)
    try:
        yield plan
    finally:
        _PLAN.reset(token)


def builtin_only():
    return using(None)


def _cids(char_ids: Optional[Iterable]) -> Optional[set]:
    if char_ids is None:
        return None
    return {canon_char(c) for c in char_ids if c}


def merge_sub(weights: Dict[str, str], sub_id: str, items: Dict[str, str]) -> List[str]:
    """把订阅内容按角色整体写进设置, 返回被覆盖角色的提示。"""
    notices = []
    for cid in sorted(chars_of(items), key=_cid_order):
        old, new = char_entries(weights, cid), char_entries(items, cid)
        if old and old != new:
            a, b = brief(old), brief(new)
            notices.append(f"{char_name_of(cid)}的权重已由{a}更新为订阅{sub_id}中的{b}" if a != b else f"{char_name_of(cid)}的条件权重已按订阅{sub_id}更新")
    replace_chars(weights, items)
    return notices


def _cid_order(cid: str) -> int:
    return int(cid) if cid.isdigit() else 0


async def sync_personal(row) -> List[str]:
    """跟随订阅: 内容变化时覆盖订阅包含的角色并提示; 订阅被删则自动取消。"""
    if not row or not row.sub_id:
        return []
    res = await check_sub(row.sub_id, row.sub_hash)
    if res is None or not (res.get("missing") or res.get("changed")):
        return []
    weights = row.weight_map()
    if res.get("missing"):
        notices = [f"订阅 {row.sub_id} 已不存在，已自动取消订阅（已同步的角色权重保留）"]
        row.sub_id, row.sub_hash = "", ""
        row.set_maps(weights=weights, sub_items={})
    else:
        new_items: Dict[str, str] = res.get("items") or {}
        notices = merge_sub(weights, row.sub_id, new_items)
        gone = set()
        for key, wid in row.sub_map().items():
            cid = split_key(key)[0]
            if cid not in chars_of(new_items) and weights.get(key) == wid:
                weights.pop(key, None)
                gone.add(cid)
        for cid in sorted(gone - chars_of(weights), key=_cid_order):
            notices.append(f"订阅{row.sub_id}已移除{char_name_of(cid)}，该角色恢复默认权重")
        row.sub_hash = res.get("hash", "")
        row.set_maps(weights=weights, sub_items=new_items)
    await save_settings(row)
    return notices


async def sync_group(row) -> List[str]:
    from .database.waves_custom_weight import WavesGroupWeight

    if not row or not row.sub_id:
        return []
    res = await check_sub(row.sub_id, row.sub_hash)
    if res is None:
        return []
    if res.get("missing"):
        await WavesGroupWeight.delete_row(row.group_id, row.bot_id)
        return [f"群权重订阅 {row.sub_id} 已不存在，本群已恢复默认权重"]
    if res.get("changed"):
        row.sub_hash = res.get("hash", "")
        row.set_items(res.get("items") or {})
        await WavesGroupWeight.save_row(row)
    return []


async def _load_choices(picks: List[Tuple[str, FrozenSet[str], str, str]], plan: WeightPlan):
    sem = asyncio.Semaphore(8)

    async def one(wid: str):
        async with sem:
            return await get_weight(wid)

    wids = list(dict.fromkeys(wid for _, _, wid, _ in picks))
    got = dict(zip(wids, await asyncio.gather(*(one(w) for w in wids))))
    failed = set()
    for cid, codes, wid, source in picks:
        w = got.get(wid)
        if w is None:
            if wid not in failed:
                failed.add(wid)
                plan.notices.append(f"{char_name_of(cid)}的权重 {wid} 获取失败，本次使用默认权重")
            continue
        if canon_char(w.get("char_id")) == cid:
            plan.choices.setdefault(cid, []).append(Choice(wid=wid, source=source, weight=w, codes=codes))


async def bound_uid(ev) -> Optional[str]:
    """个人设置按 xwuid 当前绑定的 UID 取。"""
    from .database.models import WavesBind

    return await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)


async def build_plan(ev, char_ids: Optional[Iterable] = None, explicit: Optional[str] = None, rank: bool = False, uid: Optional[str] = None) -> WeightPlan:
    """按优先级解析本条指令要用的权重。char_ids=None 表示全部已设置的角色。"""
    from .database.waves_custom_weight import WavesCustomWeight, WavesGroupWeight

    plan = WeightPlan()
    if not enabled():
        if explicit:
            plan.error = "未开启自定义权重"
        return plan
    want = _cids(char_ids)
    # 某层给了无条件权重的角色就此封顶, 只有条件权重的角色继续往下一层找
    closed: Set[str] = set()
    picks: List[Tuple[str, FrozenSet[str], str, str]] = []

    def take(entries: Dict[str, str], source_of):
        layer = []
        for key, wid in entries.items():
            cid, codes = split_key(key)
            if cid not in closed and (want is None or cid in want):
                layer.append((cid, codes, wid, source_of(key, wid)))
        layer.sort(key=lambda x: not x[1])
        picks.extend(layer)
        closed.update(cid for cid, codes, _, _ in layer if not codes)

    if explicit:
        wid = norm_id(explicit)
        w, plan.error = await check_weight(wid, want)
        if w is None:
            return plan
        cid = canon_char(w.get("char_id"))
        plan.choices[cid] = [Choice(wid=wid, source="cmd", weight=w)]
        closed.add(cid)
        if want is not None and want <= {cid}:
            return plan

    group_sub = ""
    group_id = getattr(ev, "group_id", None)
    if group_id:
        grow = await WavesGroupWeight.get_row(str(group_id), ev.bot_id)
        if grow and grow.sub_id:
            plan.notices.extend(await sync_group(grow))
            grow = await WavesGroupWeight.get_row(str(group_id), ev.bot_id)
            if grow:
                group_sub = grow.sub_id
                take(grow.sub_map(), lambda k, w: "group")

    if not rank:
        if uid is None:
            uid = await bound_uid(ev)
        if uid:
            row = await WavesCustomWeight.get_row(ev.user_id, ev.bot_id, str(uid))
            weights: Dict[str, str] = {}
            sub_id = ""
            if row:
                plan.notices.extend(await sync_personal(row))
                weights, sub_id = row.weight_map(), row.sub_id
                sub_items = row.sub_map()
                take(weights, lambda k, w: "sub" if sub_id and sub_items.get(k) == w else "personal")
            _report_heartbeat(uid, weights, sub_id, group_sub, ev.user_id, ev.bot_id)

    if picks:
        await _load_choices(picks, plan)
    return plan


async def send_notices(bot, ev, plan: Optional[WeightPlan]):
    if plan and plan.notices:
        try:
            await bot.send("\n".join(f"[鸣潮] {n}" for n in plan.notices))
        except Exception as e:
            logger.debug(f"[鸣潮·自定义权重] 提示发送失败: {e}")


async def prepare_plan(bot, ev, char_ids: Optional[Iterable] = None, explicit: Optional[str] = None, rank: bool = False) -> Optional[WeightPlan]:
    """构建本条指令的权重方案并发提示; 指令里的 ID 有误时回复错误并返回 None。"""
    plan = await build_plan(ev, char_ids, explicit=explicit, rank=rank)
    if plan.error:
        await bot.send(f"[鸣潮] {plan.error}")
        return None
    await send_notices(bot, ev, plan)
    return plan


# ---------------- 文本格式 ----------------


def _entries(text: str):
    """逐行取条目: 只认行首(或紧跟分隔符的下一条), 行尾的角色名/权重名是注释。"""
    for line in text.splitlines():
        pos = 0
        while (m := ENTRY_RE.match(line, pos)):
            yield m
            sep = NEXT_RE.match(line, m.end())
            if not sep:
                break
            pos = sep.end()


def parse_text(text: str) -> Tuple[Optional[str], Dict[str, str], List[str], List[str]]:
    """返回 (订阅ID, 条目, 单独的权重ID列表, 错误)。条件码写在角色ID后的方括号里。"""
    entries: Dict[str, str] = {}
    errors: List[str] = []
    dup: Dict[str, set] = {}
    for m in _entries(text or ""):
        cid, raw, wid = canon_char(m.group(1)), m.group(2), norm_id(m.group(3))
        toks = [t for t in re.split(r"[\s,，、;；/|]+", raw or "") if t]
        bad = [t for t in toks if not CODE_RE.fullmatch(t)]
        if bad:
            errors.append(f"{char_name_of(cid)}的配置 {' '.join(bad)} 无法识别（共鸣链 0-6 + 专武谐振 0-5，如 61）")
            continue
        key = entry_key(cid, toks)
        if toks and entries.get(key, wid) != wid:
            dup.setdefault(cid, set()).update(toks)
        same = next((k for k, w in char_entries(entries, cid).items() if w == wid and split_key(k)[1] and toks), None)
        if same:
            entries.pop(same)
            key = entry_key(cid, set(toks) | split_key(same)[1])
        entries[key] = wid
    for cid in sorted(chars_of(entries), key=_cid_order):
        seen: Dict[str, str] = {}
        clash = set(dup.get(cid, ()))
        for k, w in char_entries(entries, cid).items():
            for c in split_key(k)[1]:
                if seen.setdefault(c, w) != w:
                    clash.add(c)
        if clash:
            errors.append(f"{char_name_of(cid)}的配置 {' '.join(sorted(clash))} 同时对应了多个权重，已跳过该角色")
            for k in list(char_entries(entries, cid)):
                entries.pop(k)
    ws = find_ws(text)
    loose = []
    if not entries and not errors:
        loose = [norm_id(m.group(0)) for m in CW_RE.finditer(text or "")]
    return ws, entries, loose, errors


def entry_order(key: str):
    cid, codes = split_key(key)
    return (_cid_order(cid), sorted(codes)[0] if codes else "")


def format_text(sub_id: str, items: Dict[str, str], title: str = "") -> str:
    head = "【鸣潮权重订阅】" if sub_id else "【鸣潮权重设置】"
    head += sub_id + (f" {title}" if title else "")
    lines = [head.strip()]
    for key in sorted(items, key=entry_order):
        w = cached_weight(items[key])
        extra = f"·{w.get('name')}" if w and w.get("name") else ""
        lines.append(f"{key}-{items[key]} {char_name_of(split_key(key)[0])}{extra}")
    return "\n".join(lines)
