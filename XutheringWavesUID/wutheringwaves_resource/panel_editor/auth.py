"""HTTP Basic Auth 鉴权 + per-IP 暴力破解防护 + CSRF 防护。

简单密码: 用户名固定为 admin, 密码读取 WutheringWavesConfig.WavesPanelEditPassword。
密码为空 -> 关闭工具 (返回 503)。
失败 >= LOCKOUT_THRESHOLD 次 / WINDOW 秒 -> 锁该 IP LOCKOUT_SECONDS 秒 (返 429)。
跨站发起的请求一律 403; 写操作额外要求自定义请求头 (见 CSRF 小节)。
"""

import base64
import secrets
import time
from collections import deque
from typing import Deque, Dict, Optional
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status
from gsuid_core.logger import logger

from ...wutheringwaves_config import WutheringWavesConfig


REALM = "WutheringWaves Panel Editor"

# 每 IP 在 WINDOW 秒内最多失败 THRESHOLD 次, 触发后冷却 LOCKOUT_SECONDS。
_BF_WINDOW = 600          # 10 分钟滑动窗口
_BF_THRESHOLD = 5         # 5 次失败
_BF_LOCKOUT = 900         # 锁定 15 分钟
_BF_GC_INTERVAL = 300     # 每 5 分钟扫一次, 清掉无活动的旧条目

_bf_failures: Dict[str, Deque[float]] = {}
_bf_locks: Dict[str, float] = {}
_bf_last_gc = 0.0


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


def _bf_gc(now: float) -> None:
    global _bf_last_gc
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


def _configured_password() -> Optional[str]:
    pwd = WutheringWavesConfig.get_config("WavesPanelEditPassword").data
    if pwd is None:
        return None
    pwd = str(pwd).strip()
    return pwd or None


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


def require_auth(request: Request) -> None:
    """FastAPI dependency: 仅 admin 可通过, 其它一律 401/429。"""
    role = _resolve_role(request, allow_guest=False)
    if role != "admin":
        raise _unauthorized()


def require_auth_strict(request: Request) -> None:
    """require_auth + 强制自定义头。给有副作用的 GET 端点用 (非 GET 已在 _resolve_role 强制)。"""
    require_csrf_header(request)
    require_auth(request)


def auth_or_guest(request: Request) -> str:
    """读类接口的鉴权 dependency。返回 'admin' 或 'guest'。
    - 已配置密码且配置允许访客 + 请求无 Authorization → 'guest'
    - 已配置密码且 Authorization 正确 → 'admin'
    - 其它 → 401 / 429 / 503。
    """
    return _resolve_role(request, allow_guest=is_guest_view_enabled())


def _resolve_role(request: Request, *, allow_guest: bool) -> str:
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
    ip = _client_ip(request)
    header = request.headers.get("authorization", "")

    # 无凭据: 访客模式直接放行只读, 否则要求登录。
    if not header.lower().startswith("basic "):
        if allow_guest:
            return "guest"
        raise _unauthorized()

    # 有凭据 → 进入登录路径, 受暴力破解保护
    locked = _bf_check_locked(ip, now)
    if locked is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Retry in {locked}s.",
            headers={"Retry-After": str(locked)},
        )

    if _validate_basic(header, pwd):
        _bf_record_success(ip)
        return "admin"

    _bf_record_failure(ip, now)
    raise _unauthorized()
