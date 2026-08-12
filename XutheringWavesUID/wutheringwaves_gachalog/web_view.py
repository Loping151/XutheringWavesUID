"""抽卡记录网页查看：FastAPI 路由 + 链接生成。

启用方式: 配置 WavesGachaWebPage=True 后, 用户发送
[抽卡页面/抽卡网页/网页抽卡记录/抽卡记录网页] 即可获得 10 分钟内有效的链接。
"""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path

import httpx
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response

from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.web_app import app

from ..utils.api.model import AccountBaseInfo
from ..utils.cache import TimedCache
from ..utils.image import is_qq_default_avatar
from ..utils.util import hide_uid
from ..utils.player_store import read_player_json, player_json_exists
from ..utils.resource.RESOURCE_PATH import (
    AVATAR_PATH,
    MAIN_PATH,
    PLAYER_PATH,
    WEAPON_PATH,
)
from ..utils.resource.constant import NORMAL_LIST
from ..utils.waves_api import waves_api
from ..wutheringwaves_config import PREFIX, WutheringWavesConfig
from .get_gachalogs import gacha_type_meta_data
from .merge_utils import warn_gacha_pity_violations, has_history_gap_before

GACHA_WEB_TTL = 600  # 10 分钟

_token_cache = TimedCache(
    timeout=GACHA_WEB_TTL,
    maxsize=2000,
    persist_path=MAIN_PATH / "url_cache.db",
)

_TEMPLATE_PATH = Path(__file__).parent / "page.html"


def _is_feature_enabled() -> bool:
    return bool(WutheringWavesConfig.get_config("WavesGachaWebPage").data)


def feature_disabled_msg() -> str:
    return "该功能未开启，请联系主人开启该功能"


async def _build_account_info(uid: str, ev: Event) -> Dict:
    """尽力获取账号基础信息，失败回退到仅 uid。"""
    info: Dict = {"uid": hide_uid(uid)}
    # 优先：core 适配器传入的 avatar URL（QQ 官方 / Discord / KOOK 等都会带）
    sender_avatar = (ev.sender or {}).get("avatar") or ""
    if isinstance(sender_avatar, str) and sender_avatar.startswith(("http://", "https://")):
        info["sender_avatar"] = sender_avatar
    # QQ 头像 URL（仅 onebot + 纯数字 user_id）；用 // 协议相对，避免 mixed-content
    if ev.bot_id == "onebot" and str(ev.user_id).isdigit():
        info["qq_avatar"] = f"//q1.qlogo.cn/g?b=qq&nk={ev.user_id}&s=640"
    if waves_api.is_net(uid):
        info["name"] = f"漂泊者·{hide_uid(uid)}"
        info["is_net"] = True
        return info
    info["is_net"] = False
    try:
        _, ck = await waves_api.get_ck_result(uid, ev.user_id, ev.bot_id)
        if not ck:
            return info
        base = await waves_api.get_base_info(uid, ck)
        if not base.success or not base.data:
            return info
        acc = AccountBaseInfo.model_validate(base.data)
        info["name"] = acc.name
        info["level"] = acc.level
        info["worldLevel"] = acc.worldLevel
        info["activeDays"] = acc.activeDays
        info["roleNum"] = acc.roleNum
    except Exception as e:
        logger.debug(f"[鸣潮·抽卡网页] 获取账号信息失败: {e}")
    return info


async def make_gacha_web_url(uid: str, ev: Event) -> Tuple[Optional[str], str]:
    """生成 10 分钟内有效的查看链接。返回 (url, message)。

    - 本地 / 自有反代域名（is_local=True）: 走 gsuid_core 自带的 /waves/gacha 路由,
      与历史行为完全一致。
    - 外置登录服务（is_local=False）: 把摘要数据 + 头像 + 共享资源 PNG
      推送到 ww-login 服务缓存，链接指向那边的同名路由。
    """
    if not _is_feature_enabled():
        return None, feature_disabled_msg()

    gacha_path = PLAYER_PATH / str(uid) / "gacha_logs.json"
    if not player_json_exists(gacha_path):
        return None, f"[鸣潮] 你还没有抽卡记录噢!\n 请查看 {PREFIX}抽卡帮助 中的提示导入!"

    base = await _build_account_info(uid, ev)
    token = secrets.token_urlsafe(16)
    state = {"uid": uid, "user_id": ev.user_id, "bot_id": ev.bot_id, "base": base}

    # 延迟导入避免插件加载顺序导致的循环依赖
    from ..wutheringwaves_login.login import get_url
    url, is_local = await get_url()

    if is_local:
        _token_cache.set(token, state)
        return f"{url}/waves/gacha/{token}", "ok"

    # 外置模式：先把所有依赖推过去，再放出链接，避免页面打开时图片/数据 404。
    ok, msg = await _push_gacha_to_external(url, token, state)
    if not ok:
        return None, msg
    return f"{url}/waves/gacha/{token}", "ok"


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / (1024 * 1024):.2f}MB"


async def _fetch_avatar_url(target: str) -> Optional[Tuple[bytes, str]]:
    """从 URL 抓取头像字节。target 来自 adapter sender_avatar，未做域名 allowlist，依赖 adapter 可信。follow_redirects=False 只能挡跳板二次跳转，不能挡首跳到内网。"""
    try:
        async with httpx.AsyncClient(timeout=6, follow_redirects=False) as client:
            r = await client.get(target, headers={"Referer": ""})
            if r.status_code == 200 and r.content and not is_qq_default_avatar(r.content):
                return r.content, r.headers.get("content-type", "image/jpeg")
    except Exception as e:
        logger.debug(f"[鸣潮·抽卡网页] 头像抓取失败 {target}: {e}")
    return None


async def _resolve_userpic(state: Dict, seed: str) -> Optional[Tuple[bytes, str]]:
    """头像优先级: core 适配器 avatar -> QQ CDN -> 随机本地角色头像。"""
    base = state.get("base") or {}
    sender_avatar = base.get("sender_avatar") or ""
    if sender_avatar:
        got = await _fetch_avatar_url(sender_avatar)
        if got:
            return got
    qq_avatar = base.get("qq_avatar") or ""
    if qq_avatar:
        full = ("https:" + qq_avatar) if qq_avatar.startswith("//") else qq_avatar
        got = await _fetch_avatar_url(full)
        if got:
            return got
    fallback = _random_char_avatar(seed)
    if fallback and fallback.exists():
        try:
            return fallback.read_bytes(), "image/png"
        except Exception:
            pass
    return None


async def _push_gacha_to_external(url: str, token: str, state: Dict) -> Tuple[bool, str]:
    uid = state["uid"]
    base = state.get("base") or {}

    try:
        raw = await _load_gacha_data(uid)
    except Exception as e:
        logger.warning(f"[鸣潮·抽卡网页] 读取数据失败 uid={uid}: {e}")
        return False, "读取抽卡数据失败"

    data = raw.get("data", {})
    pools: List[Dict] = []
    ref_avatar: set = set()
    ref_weapon: set = set()

    def _add_ref(item: Dict) -> None:
        rid = item.get("resourceId")
        if rid is None:
            return
        bucket = ref_weapon if item.get("resourceType") == "武器" else ref_avatar
        bucket.add(int(rid))

    for name in gacha_type_meta_data.keys():
        logs = data.get(name, [])
        pool = _build_pool_view(name, logs)
        pools.append(pool)
        for fs in pool["five_stars"]:
            _add_ref(fs)
            for it in fs.get("top_4stars", []):
                _add_ref(it)

    payload = {
        "base": base,
        "data_time": raw.get("data_time", ""),
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pools": pools,
    }
    data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    userpic = await _resolve_userpic(state, token)

    ref_total = len(ref_avatar) + len(ref_weapon)
    asset_uploaded = 0
    asset_bytes = 0
    asset_failed = 0

    async def up_asset(client: httpx.AsyncClient, kind: str, rid: int) -> None:
        nonlocal asset_uploaded, asset_bytes, asset_failed
        path = (
            AVATAR_PATH / f"role_head_{rid}.png"
            if kind == "avatar"
            else WEAPON_PATH / f"weapon_{rid}.png"
        )
        if not path.exists():
            return
        try:
            content = path.read_bytes()
            r = await client.post(
                f"{url}/waves/gacha/asset/{kind}/{rid}",
                content=content,
                headers={"Content-Type": "image/png"},
            )
            if r.status_code == 200:
                asset_uploaded += 1
                asset_bytes += len(content)
            else:
                asset_failed += 1
                logger.debug(
                    f"[鸣潮·抽卡网页] asset {kind}/{rid} 上传失败 {r.status_code} {r.text[:120]}"
                )
        except Exception as e:
            asset_failed += 1
            logger.debug(f"[鸣潮·抽卡网页] asset {kind}/{rid} 上传异常: {e}")

    userpic_size = 0
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # 先一次询问哪些 asset ww-login 还没缓存。命中部分跳过上传，省带宽。
            try:
                check_resp = await client.post(
                    f"{url}/waves/gacha/asset-check",
                    content=json.dumps(
                        {
                            "avatar": list(ref_avatar),
                            "weapon": list(ref_weapon),
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                if check_resp.status_code == 200:
                    miss = check_resp.json().get("missing") or {}
                    miss_avatar = {int(x) for x in miss.get("avatar", [])} & ref_avatar
                    miss_weapon = {int(x) for x in miss.get("weapon", [])} & ref_weapon
                    ref_avatar, ref_weapon = miss_avatar, miss_weapon
                else:
                    logger.debug(
                        f"[鸣潮·抽卡网页] asset-check 非 200 ({check_resp.status_code})，退化全量上传"
                    )
            except Exception as e:
                logger.debug(f"[鸣潮·抽卡网页] asset-check 异常: {e}，退化全量上传")
            asset_skipped = ref_total - len(ref_avatar) - len(ref_weapon)
            await asyncio.gather(
                *(up_asset(client, "avatar", r) for r in ref_avatar),
                *(up_asset(client, "weapon", r) for r in ref_weapon),
            )
            r = await client.post(
                f"{url}/waves/gacha/data/{token}",
                content=data_bytes,
                headers={"Content-Type": "application/json"},
            )
            if r.status_code != 200:
                logger.error(
                    f"[鸣潮·抽卡网页] data 上传失败 {r.status_code} {r.text[:200]}"
                )
                return False, "外置抽卡页面上传失败"
            if userpic:
                up_bytes, up_mime = userpic
                try:
                    r2 = await client.post(
                        f"{url}/waves/gacha/userpic/{token}",
                        content=up_bytes,
                        headers={"Content-Type": up_mime or "image/png"},
                    )
                    if r2.status_code == 200:
                        userpic_size = len(up_bytes)
                    else:
                        logger.warning(
                            f"[鸣潮·抽卡网页] userpic 上传失败 {r2.status_code} {r2.text[:120]}"
                        )
                except Exception as e:
                    logger.warning(f"[鸣潮·抽卡网页] userpic 上传异常: {e}")
    except Exception as e:
        logger.exception(f"[鸣潮·抽卡网页] 外置上传异常: {e}")
        return False, "外置抽卡页面上传失败"

    total = len(data_bytes) + userpic_size + asset_bytes
    logger.info(
        f"[鸣潮·抽卡网页] 外置上传 token={token} uid={uid} "
        f"data={_fmt_size(len(data_bytes))} "
        f"userpic={_fmt_size(userpic_size)} "
        f"assets={asset_uploaded}个/{_fmt_size(asset_bytes)}"
        + (f" 命中跳过={asset_skipped}" if asset_skipped else "")
        + (f" 失败={asset_failed}" if asset_failed else "")
        + f" 合计={_fmt_size(total)}"
    )
    return True, ""


# ----------------------------- 数据计算 -----------------------------


def _build_pool_view(name: str, logs: List[Dict]) -> Dict:
    """把单池抽卡日志整理成前端使用的结构。

    分组: 把每两个 5 星之间的所有抽卡视为"一个 5 星周期",
    周期内的 4 星按抽到次数降序全部输出（前端滚动/换行容纳，不截断）。
    输出按 5 星倒序（最近的在前）。
    """
    total = len(logs)
    asc = list(reversed(logs))  # 老到新

    five_stars: List[Dict] = []
    period_4stars: Dict[int, Dict[str, Dict]] = {}
    pity = 0
    fs_index = 0
    cur_period: Dict[str, Dict] = {}

    five_pos: List[int] = []  # 5 星出现位置（按从老到新计算）

    for log in asc:
        if has_history_gap_before(log):
            pity = 0
            cur_period = {}
        pity += 1
        ql = log.get("qualityLevel")
        if ql == 4:
            key = log.get("name", "?")
            cur_period.setdefault(
                key,
                {
                    "name": key,
                    "resourceId": log.get("resourceId"),
                    "resourceType": log.get("resourceType"),
                    "count": 0,
                },
            )
            cur_period[key]["count"] += 1
        elif ql == 5:
            five_pos.append(pity)
            is_up = log.get("name") not in NORMAL_LIST
            five_stars.append(
                {
                    "name": log.get("name"),
                    "resourceId": log.get("resourceId"),
                    "resourceType": log.get("resourceType"),
                    "time": log.get("time"),
                    "pity": pity,
                    "is_up": is_up,
                }
            )
            period_4stars[fs_index] = cur_period
            fs_index += 1
            cur_period = {}
            pity = 0

    remain_since_last = pity  # 末尾未出 5 星的累积
    # 打包 4 星（按 count 降序，全部输出，不截断）
    # 注: 库洛接口 2025-11 之前未区分 4★, 旧记录全部 qualityLevel=3。
    # 周期内累计 ≥10 抽却 0 个 4★, 视为旧 API 的占位周期, 前端展示提示。
    fives_with_4 = []
    for i, fs in enumerate(five_stars):
        items = list(period_4stars.get(i, {}).values())
        items.sort(key=lambda x: -x["count"])
        fs2 = dict(fs)
        fs2["top_4stars"] = items
        fs2["is_stub"] = (len(items) == 0 and fs.get("pity", 0) >= 10)
        fives_with_4.append(fs2)
    fives_with_4.reverse()  # 新到老

    avg_5 = (sum(five_pos) / len(five_pos)) if five_pos else 0
    up_count = sum(1 for f in fives_with_4 if f["is_up"])
    avg_up = (sum(five_pos) / up_count) if up_count else 0

    time_range = ""
    if logs:
        time_range = f"{logs[-1]['time']} ~ {logs[0]['time']}"

    return {
        "name": name,
        "total": total,
        "five_count": len(fives_with_4),
        "up_count": up_count,
        "avg_5": round(avg_5, 2),
        "avg_up": round(avg_up, 2),
        "remain": remain_since_last,
        "time_range": time_range,
        "five_stars": fives_with_4,
    }


async def _load_gacha_data(uid: str) -> Dict:
    path = PLAYER_PATH / str(uid) / "gacha_logs.json"
    raw = await read_player_json(path) or {}
    warn_gacha_pity_violations(raw.get("data", {}), f"uid={uid} ")
    return raw


# ----------------------------- 路由 -----------------------------


def _check_token(token: str) -> Optional[Dict]:
    state = _token_cache.get(token)
    if not isinstance(state, dict):
        return None
    return state


_NOT_FOUND_HTML = """<!DOCTYPE html><html lang=zh-CN><meta charset=utf-8><title>页面已过期</title>
<style>html,body{height:100%;margin:0;background:#0a0d12;color:#dfe4ee;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;display:flex;align-items:center;justify-content:center;}
.box{padding:32px 36px;border:1px solid #1f2733;border-radius:14px;background:#11161e;max-width:420px;text-align:center;}
h1{font-size:18px;margin:0 0 8px;color:#f0c463}
p{font-size:13px;color:#8b95a7;line-height:1.7;margin:6px 0}</style>
<div class=box><h1>页面已过期或不存在</h1>
<p>抽卡记录网页仅在 10 分钟内有效。</p>
<p>请重新发送 <code>抽卡页面</code> 获取新链接。</p></div></html>"""


@app.get("/waves/gacha/{token}")
async def gacha_web_index(token: str):
    # 过期/未启用都用 200 返回 — 上游 nginx 常配 proxy_intercept_errors / error_page 404 /
    # 让 4xx 落到反代默认页, 用 200 + 页面内提示更稳。
    if not _is_feature_enabled():
        return HTMLResponse(_NOT_FOUND_HTML)
    state = _check_token(token)
    if not state:
        return HTMLResponse(_NOT_FOUND_HTML)
    if not _TEMPLATE_PATH.exists():
        return HTMLResponse("<h1>page template missing</h1>", status_code=500)
    return FileResponse(
        _TEMPLATE_PATH,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/waves/gacha/{token}/data")
async def gacha_web_data(token: str):
    if not _is_feature_enabled():
        return JSONResponse({"error": "disabled"}, status_code=404)
    state = _check_token(token)
    if not state:
        return JSONResponse({"error": "expired"}, status_code=404)

    uid = state["uid"]
    base = state.get("base", {"uid": uid})

    try:
        raw = await _load_gacha_data(uid)
    except Exception as e:
        logger.warning(f"[鸣潮·抽卡网页] 读取数据失败 uid={uid}: {e}")
        return JSONResponse({"error": "load_failed"}, status_code=500)

    data = raw.get("data", {})
    pools = []
    for name in gacha_type_meta_data.keys():
        logs = data.get(name, [])
        pools.append(_build_pool_view(name, logs))

    return JSONResponse(
        {
            "base": base,
            "data_time": raw.get("data_time", ""),
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pools": pools,
        },
        headers={"Cache-Control": "no-store"},
    )


def _safe_resource_id(rid: str) -> bool:
    return rid.isdigit() and len(rid) <= 10


@app.get("/waves/gacha/{token}/avatar/{rid}.png")
async def gacha_web_avatar(token: str, rid: str):
    if not _check_token(token) or not _safe_resource_id(rid):
        return JSONResponse({"error": "not_found"}, status_code=404)
    p = AVATAR_PATH / f"role_head_{rid}.png"
    if not p.exists():
        return JSONResponse({"error": "not_found"}, status_code=404)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@app.get("/waves/gacha/{token}/weapon/{rid}.png")
async def gacha_web_weapon(token: str, rid: str):
    if not _check_token(token) or not _safe_resource_id(rid):
        return JSONResponse({"error": "not_found"}, status_code=404)
    p = WEAPON_PATH / f"weapon_{rid}.png"
    if not p.exists():
        return JSONResponse({"error": "not_found"}, status_code=404)
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


def _random_char_avatar(seed: str) -> Optional[Path]:
    """挑一张本地角色头像作为兜底, 用 token 做种避免每次刷新都换。
    用 hashlib.md5 而不是内置 hash() 避免 PYTHONHASHSEED 跨进程飘移。"""
    import hashlib
    candidates = sorted(AVATAR_PATH.glob("role_head_*.png"))
    if not candidates:
        return None
    idx = int.from_bytes(hashlib.md5(seed.encode()).digest()[:4], "big") % len(candidates)
    return candidates[idx]


# /userpic 响应字节缓存: 每个 token 最多触发一次外部抓取, 后续请求走内存。
# 既消除了被当代理刷外网的滥用面, 也省掉了 q1.qlogo.cn 的重复往返开销。
from collections import OrderedDict as _OrderedDict
_userpic_bytes: "_OrderedDict[str, tuple[bytes, str]]" = _OrderedDict()
_USERPIC_CACHE_MAX = 4000


def _userpic_cache_set(token: str, content: bytes, mime: str) -> None:
    _userpic_bytes[token] = (content, mime)
    _userpic_bytes.move_to_end(token)
    while len(_userpic_bytes) > _USERPIC_CACHE_MAX:
        _userpic_bytes.popitem(last=False)


@app.get("/waves/gacha/{token}/userpic")
async def gacha_web_userpic(token: str):
    """用户头像代理: 适配器 avatar -> QQ 头像 -> 随机角色头像。
    走服务端代理避免 q1.qlogo.cn 的 CORS 限制, 同时保证 html2canvas 能正常导出。
    """
    state = _check_token(token)
    if not state:
        return JSONResponse({"error": "expired"}, status_code=404)

    cached = _userpic_bytes.get(token)
    if cached is not None:
        _userpic_bytes.move_to_end(token)
        return Response(cached[0], media_type=cached[1], headers={"Cache-Control": "max-age=600"})

    got = await _resolve_userpic(state, token)
    if got:
        content, mime = got
        _userpic_cache_set(token, content, mime)
        return Response(content, media_type=mime, headers={"Cache-Control": "max-age=600"})

    return JSONResponse({"error": "no_avatar"}, status_code=404)
