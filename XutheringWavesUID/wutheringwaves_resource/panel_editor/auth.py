"""HTTP Basic Auth 鉴权 + per-IP 暴力破解防护 + CSRF 防护。

简单密码: 用户名固定为 admin, 密码读取 WutheringWavesConfig.WavesPanelEditPassword。
密码为空 -> 关闭工具 (返回 503)。
防爆两层: 单来源 (IPv6 按 /64) 失败超阈值锁定返 429; 全站失败速率超阈值后,
失败路径按速率拖延时 — 校验在拖延之前, 密码对的管理员不受影响。
跨站发起的请求一律 403; 写操作额外要求自定义请求头 (见 CSRF 小节)。
"""

import asyncio
import base64
import ipaddress
import secrets
import time
from collections import deque
from typing import Deque, Dict, Optional
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status
from gsuid_core.logger import logger

from ...wutheringwaves_config import WutheringWavesConfig


REALM = "WutheringWaves Panel Editor"

# 每个来源在 WINDOW 秒内最多失败 THRESHOLD 次, 触发后冷却 LOCKOUT_SECONDS。
_BF_WINDOW = 600          # 10 分钟滑动窗口
_BF_THRESHOLD = 5         # 5 次失败
_BF_LOCKOUT = 900         # 锁定 15 分钟
_BF_GC_INTERVAL = 300     # 每 5 分钟扫一次, 清掉无活动的旧条目
_BF_MAX_TRACKED = 8192    # 字典硬上限, 防海量来源把内存撑爆

# 全局闸: per-IP 锁挡不住换 IP 的分布式爆破 (僵尸网络 / 一个 IPv6 段随便切),
# 故再叠一层全站失败速率 -> 失败路径拖延时。密码校验在拖延之前, 因此拿对密码的
# 管理员永远不受影响, 攻击者刷得越狠自己越慢。
_GLOBAL_WINDOW = 600
_GLOBAL_SOFT = 20         # 全站 10 分钟内失败超过这个数开始拖
_GLOBAL_DELAY_STEP = 0.3  # 每多失败 1 次, 延迟加这么多秒
_GLOBAL_DELAY_MAX = 8.0
_FAIL_DELAY_BASE = 0.4    # 每次失败的基础延迟
_TARPIT_MAX_CONCURRENT = 32   # 同时被拖住的请求数上限, 防拖延本身变成资源占用

_bf_failures: Dict[str, Deque[float]] = {}
_bf_locks: Dict[str, float] = {}
_bf_last_gc = 0.0
_global_failures: Deque[float] = deque()
_tarpit_active = 0


def _client_ip(request: Request) -> str:
    """取真实客户端 IP。仅当上游是回环时才信任 X-Real-IP / X-Forwarded-For,
    否则可被攻击者伪造。"""
    direct = request.client.host if request.client else ""
    if direct in ("127.0.0.1", "::1", "localhost"):
        xri = request.headers.get("x-real-ip")
        if xri:
            return xri.strip()
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return direct or "?"


def _bf_key(ip: str) -> str:
    """限速用的来源键。IPv6 收敛到 /64: 一个家宽 IPv6 段就有 2^64 个地址,
    按整地址计数等于不限速。"""
    raw = ip.strip().strip("[]").split("%")[0]
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return ip
    if addr.version == 6:
        return f"{ipaddress.ip_network(f'{addr}/64', strict=False).network_address}/64"
    return str(addr)


def _bf_gc(now: float) -> None:
    global _bf_last_gc
    while _global_failures and now - _global_failures[0] > _GLOBAL_WINDOW:
        _global_failures.popleft()
    if now - _bf_last_gc < _BF_GC_INTERVAL:
        return
    _bf_last_gc = now
    expire_locks = [ip for ip, until in _bf_locks.items() if until <= now]
    for ip in expire_locks:
        _bf_locks.pop(ip, None)
    for ip, dq in list(_bf_failures.items()):
        while dq and now - dq[0] > _BF_WINDOW:
            dq.popleft()
        if not dq:
            _bf_failures.pop(ip, None)


def _bf_evict_if_full() -> None:
    """条目数触顶时丢掉最老的一批 (仍在锁定期的优先留)。"""
    if len(_bf_failures) < _BF_MAX_TRACKED:
        return
    victims = sorted(_bf_failures.items(), key=lambda kv: kv[1][-1] if kv[1] else 0.0)
    for ip, _ in victims[: max(1, _BF_MAX_TRACKED // 8)]:
        if ip not in _bf_locks:
            _bf_failures.pop(ip, None)
    if len(_bf_locks) >= _BF_MAX_TRACKED:
        for ip, _ in sorted(_bf_locks.items(), key=lambda kv: kv[1])[: _BF_MAX_TRACKED // 8]:
            _bf_locks.pop(ip, None)


def _bf_check_locked(ip: str, now: float) -> Optional[int]:
    until = _bf_locks.get(ip)
    if until is None:
        return None
    if until <= now:
        _bf_locks.pop(ip, None)
        _bf_failures.pop(ip, None)
        return None
    return int(until - now)


def _bf_record_failure(ip: str, now: float) -> None:
    _global_failures.append(now)
    _bf_evict_if_full()
    dq = _bf_failures.setdefault(ip, deque())
    dq.append(now)
    while dq and now - dq[0] > _BF_WINDOW:
        dq.popleft()
    if len(dq) >= _BF_THRESHOLD:
        _bf_locks[ip] = now + _BF_LOCKOUT
        logger.warning(
            f"[鸣潮·面板编辑] auth lockout ip={ip} "
            f"(连续 {len(dq)} 次失败, 冷却 {_BF_LOCKOUT}s)"
        )


def _bf_record_success(ip: str) -> None:
    _bf_failures.pop(ip, None)
    _bf_locks.pop(ip, None)


def _fail_delay() -> float:
    over = len(_global_failures) - _GLOBAL_SOFT
    delay = _FAIL_DELAY_BASE + (over * _GLOBAL_DELAY_STEP if over > 0 else 0.0)
    return min(delay, _GLOBAL_DELAY_MAX)


async def _throttle_failure() -> None:
    """密码错了之后压住这条连接再返回 401。只作用于失败路径。"""
    global _tarpit_active
    if _tarpit_active >= _TARPIT_MAX_CONCURRENT:
        return
    _tarpit_active += 1
    try:
        await asyncio.sleep(_fail_delay())
    finally:
        _tarpit_active -= 1


# ------------------------- CSRF -------------------------
# Basic Auth 是浏览器缓存后自动附带的环境凭据: 管理员登录过之后, 任意站点都能借他的
# 浏览器向本服务发出带凭据的请求 (响应读不到, 但副作用已经发生)。两道闸:
#   1. 同站校验: Sec-Fetch-Site 优先 — 它与 Host 头无关, 反代改写 Host 也不误伤;
#      老浏览器 (或明文 HTTP, 此时浏览器不发 Sec-Fetch-*) 回退 Origin -> Referer。
#   2. 自定义请求头: <form>/<img> 无法携带; 用 fetch 加则触发 CORS 预检, 而本服务不返
#      任何 Access-Control-* 头, 预检必失败。非 GET 一律强制, 昂贵的 GET 手动加。

CSRF_HEADER = "X-Waves-Panel-Edit"
_CSRF_HEADER_LC = CSRF_HEADER.lower()


def _forbidden(reason: str, request: Request) -> HTTPException:
    logger.warning(
        f"[鸣潮·面板编辑] 拒绝跨站请求 ip={_client_ip(request)} "
        f"path={request.url.path} {reason}"
    )
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-site request rejected")


def _browser_host(request: Request) -> str:
    """浏览器地址栏里的 host。反代下 Host 可能被改写, 故优先 X-Forwarded-Host。"""
    fwd = request.headers.get("x-forwarded-host")
    if fwd:
        return fwd.split(",")[0].strip().lower()
    return (request.headers.get("host") or "").strip().lower()


def _url_host(value: str) -> str:
    try:
        return (urlsplit(value).netloc or "").lower()
    except Exception:
        return ""


def _is_document_nav(request: Request) -> bool:
    """顶级文档导航: 从别处 (聊天窗/书签栏) 点链接进入本工具是正常用法, 不能当攻击拦。"""
    return (
        request.method == "GET"
        and request.headers.get("sec-fetch-mode", "").lower() == "navigate"
        and request.headers.get("sec-fetch-dest", "").lower() == "document"
    )


def require_same_origin(request: Request) -> None:
    # 自定义头到手即同站 (跨站加不上), 比 Origin/Referer 可靠: 后者会被
    # Referrer-Policy: no-referrer 抹成 null/缺失, 误伤自家页面。
    if request.headers.get(_CSRF_HEADER_LC) == "1":
        return

    site = request.headers.get("sec-fetch-site", "").lower()
    if site:
        # none = 地址栏/书签直达, same-origin = 本工具页面自己发起。
        if site in ("same-origin", "none") or _is_document_nav(request):
            return
        raise _forbidden(f"sec-fetch-site={site}", request)

    host = _browser_host(request)
    origin = request.headers.get("origin")
    if origin:
        # Referrer-Policy: no-referrer 会把跨站 Origin 序列化成 "null", 不能放行。
        if origin.lower() != "null" and _url_host(origin) == host:
            return
        raise _forbidden(f"origin={origin}", request)

    referer = request.headers.get("referer")
    if referer and _url_host(referer) != host:
        raise _forbidden(f"referer={referer}", request)


def require_csrf_header(request: Request) -> None:
    if request.headers.get(_CSRF_HEADER_LC) != "1":
        raise _forbidden(f"missing {CSRF_HEADER}", request)


# ------------------------- 预览限速 (per-IP rolling window) -------------------------
# 预览端点目前仅 admin 可达, 访客早被 require_auth 顶回。
# 这里只保护已登录管理员被脚本/笔误打爆 Playwright/CPU。

_PREVIEW_WINDOW = 60.0     # 秒
_PREVIEW_LIMIT = 30        # 60s 内最多 N 次
_preview_calls: Dict[str, Deque[float]] = {}


def check_preview_rate(request: Request) -> None:
    """命中预览端点前调用。超额抛 429。"""
    now = time.monotonic()
    ip = _client_ip(request)
    dq = _preview_calls.setdefault(ip, deque())
    while dq and now - dq[0] > _PREVIEW_WINDOW:
        dq.popleft()
    if len(dq) >= _PREVIEW_LIMIT:
        retry = int(_PREVIEW_WINDOW - (now - dq[0])) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Preview rate limit exceeded ({_PREVIEW_LIMIT}/min). Retry in {retry}s.",
            headers={"Retry-After": str(retry)},
        )
    dq.append(now)
    if len(_preview_calls) > 256:
        for k in list(_preview_calls.keys()):
            if not _preview_calls[k]:
                _preview_calls.pop(k, None)


_MIN_PASSWORD_LEN = 12
_weak_warned: set = set()


def _warn_if_weak(pwd: str) -> None:
    """限速只能压低尝试速率, 压不住太短的密码; 每种长度提醒一次, 不刷屏。"""
    if len(pwd) >= _MIN_PASSWORD_LEN or len(pwd) in _weak_warned:
        return
    _weak_warned.add(len(pwd))
    logger.warning(
        f"[鸣潮·面板编辑] WavesPanelEditPassword 仅 {len(pwd)} 位, "
        f"建议 ≥{_MIN_PASSWORD_LEN} 位且混合大小写/数字"
    )


def _configured_password() -> Optional[str]:
    pwd = WutheringWavesConfig.get_config("WavesPanelEditPassword").data
    if pwd is None:
        return None
    pwd = str(pwd).strip()
    if not pwd:
        return None
    _warn_if_weak(pwd)
    return pwd


def is_enabled() -> bool:
    return _configured_password() is not None


def is_guest_view_enabled() -> bool:
    """配置开关: 允许未登录的访客只读浏览。"""
    try:
        return bool(WutheringWavesConfig.get_config("WavesPanelEditGuestView").data)
    except Exception:
        return False


def _validate_basic(header: str, pwd: str) -> bool:
    if not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:].strip()).decode("utf-8", errors="ignore")
        user, _, given = decoded.partition(":")
    except Exception:
        return False
    return secrets.compare_digest(user, "admin") and secrets.compare_digest(given, pwd)


_UNAUTH_HEADERS = {"WWW-Authenticate": f'Basic realm="{REALM}"'}


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
        headers=_UNAUTH_HEADERS,
    )


async def require_auth(request: Request) -> None:
    """FastAPI dependency: 仅 admin 可通过, 其它一律 401/429。"""
    role = await _resolve_role(request, allow_guest=False)
    if role != "admin":
        raise _unauthorized()


async def require_auth_strict(request: Request) -> None:
    """require_auth + 强制自定义头。给有副作用的 GET 端点用 (非 GET 已在 _resolve_role 强制)。"""
    require_csrf_header(request)
    await require_auth(request)


async def auth_or_guest(request: Request) -> str:
    """读类接口的鉴权 dependency。返回 'admin' 或 'guest'。
    - 已配置密码且配置允许访客 + 请求无 Authorization → 'guest'
    - 已配置密码且 Authorization 正确 → 'admin'
    - 其它 → 401 / 429 / 503。
    """
    return await _resolve_role(request, allow_guest=is_guest_view_enabled())


async def _resolve_role(request: Request, *, allow_guest: bool) -> str:
    # 放在最前: 所有走鉴权的端点都自动获得 CSRF 防护, 新增路由不会漏。
    require_same_origin(request)
    if request.method not in ("GET", "HEAD"):
        require_csrf_header(request)

    pwd = _configured_password()
    if not pwd:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="面板图编辑工具未启用 (请在配置中设置 WavesPanelEditPassword)",
        )

    now = time.monotonic()
    _bf_gc(now)
    key = _bf_key(_client_ip(request))
    header = request.headers.get("authorization", "")

    # 无凭据: 访客模式直接放行只读, 否则要求登录。
    if not header.lower().startswith("basic "):
        if allow_guest:
            return "guest"
        raise _unauthorized()

    # 有凭据 → 进入登录路径, 受暴力破解保护
    locked = _bf_check_locked(key, now)
    if locked is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Retry in {locked}s.",
            headers={"Retry-After": str(locked)},
        )

    # 校验在拖延之前: 密码对的管理员任何时候都直接放行, 全局闸只压失败方。
    if _validate_basic(header, pwd):
        _bf_record_success(key)
        return "admin"

    _bf_record_failure(key, now)
    await _throttle_failure()
    raise _unauthorized()
