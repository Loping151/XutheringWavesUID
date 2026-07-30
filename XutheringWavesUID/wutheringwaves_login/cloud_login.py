from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from async_timeout import timeout
from pydantic import BaseModel
from starlette.responses import HTMLResponse

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.web_app import app

from ..utils.database.models import WavesBind
from ..utils.database.waves_gacha_cloud import WavesGachaCloud
from ..utils.download_utils import import_after_build_copy
from ..utils.resource.RESOURCE_PATH import (
    custom_waves_template,
    waves_templates,
)
from ..utils.util import get_hide_uid_pref, hide_uid
from ..wutheringwaves_config import PREFIX, ShowConfig
from .login import cache, evict_user_login, get_token, get_url, send_login

GAME_TITLE = "[鸣潮]"
LOGIN_FLOW = "cloud"

_CLOUD_API_MODULE = None
_CLOUD_API_IMPORT_LOCK = threading.RLock()


def _get_cloud_api_module():
    global _CLOUD_API_MODULE
    if _CLOUD_API_MODULE is None:
        with _CLOUD_API_IMPORT_LOCK:
            if _CLOUD_API_MODULE is None:
                _CLOUD_API_MODULE = import_after_build_copy(
                    "..utils.waves_build.cloud_api",
                    package=__package__,
                )
    return _CLOUD_API_MODULE


def _cloud_api():
    return _get_cloud_api_module().cloud_api


# ===== 复用续期（DB 薄封装，请求链在 cloud_api）=================
async def fetch_cloud_record_id(
    user_id: str, bot_id: str, uid: str
) -> Optional[str]:
    """复用已存登录信息取 recordId。失效才标记无效；网络等临时失败保留记录。"""
    record = await WavesGachaCloud.select_record(user_id, bot_id, uid)
    if not record or not record.is_valid or not record.login_info:
        return None
    try:
        info: Dict[str, Any] = json.loads(record.login_info)
    except Exception:
        await WavesGachaCloud.mark_invalid(user_id, bot_id, uid)
        return None

    record_id, new_info, status = await _cloud_api().refresh_record_id(info)
    if status == "ok":
        if new_info is not None:
            await WavesGachaCloud.update_login_info(
                user_id, bot_id, uid, json.dumps(new_info, ensure_ascii=False)
            )
        else:
            await WavesGachaCloud.update_last_used(user_id, bot_id, uid)
        return record_id
    if status == "invalid":
        await WavesGachaCloud.mark_invalid(user_id, bot_id, uid)
    else:
        logger.warning(f"[鸣潮·云登录] recordId 续期临时失败 uid={uid}，保留记录")
    return None


# ===== 存表 + 绑定 + 拉抽卡 =====================================
async def _persist_and_bind(
    user_id: str,
    bot_id: str,
    group_id: Optional[str],
    uid: str,
    login_info: Dict[str, Any],
) -> None:
    await WavesGachaCloud.upsert(
        user_id, bot_id, uid, json.dumps(login_info, ensure_ascii=False)
    )
    res = await WavesBind.insert_waves_uid(user_id, bot_id, uid, group_id, lenth_limit=9)
    if res in (0, -2):
        await WavesBind.switch_uid_by_game(user_id, bot_id, uid)


# ===== 登录成功 → 入库后尝试更新一次抽卡记录 ===================
async def _login_then_update(bot: Bot, ev: Event, uid: str, record_id: str):
    at_sender = True if ev.group_id else False
    user_pref = await get_hide_uid_pref(uid, ev.user_id, ev.bot_id)

    await bot.send(
        (" " if at_sender else "")
        + f"{GAME_TITLE} 云登录成功，已记录 UID{hide_uid(uid, user_pref)}\n"
        + f"正在尝试更新抽卡记录！以后更新可使用【{PREFIX}更新抽卡记录】",
        at_sender=at_sender,
    )
    from ..wutheringwaves_gachalog import pull_cloud_gacha

    await pull_cloud_gacha(bot, ev, uid, record_id)


# ===== 指令入口 ===============================================
async def cloud_login_entry(bot: Bot, ev: Event):
    # 每次抽卡登录都走完整登录流程, 允许为不同 uid 各建一条记录
    # (复用/续期已有记录交给 更新抽卡记录)
    url, is_local = await get_url()
    url = url.rstrip("/")
    if is_local:
        return await _cloud_login_web(bot, ev, url)
    return await _cloud_login_other(bot, ev, url)


async def _cloud_login_web(bot: Bot, ev: Event, url: str):
    at_sender = True if ev.group_id else False
    evict_user_login(ev.user_id)  # 撤销同用户旧登录会话, 新链接唯一有效
    user_token = get_token()

    cache.set(
        user_token,
        {
            "flow": LOGIN_FLOW,
            "phase": "init",
            "user_id": ev.user_id,
            "bot_id": ev.bot_id,
            "group_id": ev.group_id,
            "device_num": _get_cloud_api_module().gen_device_num(),
            "did": _get_cloud_api_module().gen_did(),
        },
    )

    await send_login(bot, ev, f"{url}/waves/i/{user_token}", refresh_panel=False)

    uid = ""
    try:
        async with timeout(180):
            while True:
                state = cache.get(user_token)
                if state is None:
                    return await bot.send("登录超时!", at_sender=at_sender)
                if not isinstance(state, dict) or state.get("flow") != LOGIN_FLOW:
                    return

                phase = state.get("phase")
                if phase == "done":
                    uid = str(state.get("uid") or "")
                    cache.delete(user_token)
                    if not uid:
                        return await bot.send(
                            f"{GAME_TITLE} 登录完成但数据异常，请重试",
                            at_sender=at_sender,
                        )
                    break

                if phase == "failed":
                    err = state.get("error_msg") or "云登录失败"
                    cache.delete(user_token)
                    return await bot.send(
                        (" " if at_sender else "") + f"{GAME_TITLE} {err}",
                        at_sender=at_sender,
                    )

                await asyncio.sleep(1)
    except asyncio.TimeoutError:
        return await bot.send("登录超时!", at_sender=at_sender)
    except Exception as e:
        logger.exception(f"[鸣潮·云登录] 异常: {e}")
        return

    record_id = await fetch_cloud_record_id(ev.user_id, ev.bot_id, uid)
    if not record_id:
        user_pref = await get_hide_uid_pref(uid, ev.user_id, ev.bot_id)
        return await bot.send(
            (" " if at_sender else "")
            + f"{GAME_TITLE} 云登录成功，UID{hide_uid(uid, user_pref)} 已记录\n"
            + "抽卡记录拉取失败",
            at_sender=at_sender,
        )
    return await _login_then_update(bot, ev, uid, record_id)


async def _cloud_login_other(bot: Bot, ev: Event, url: str):
    # 外置 ww-login 处理网页与请求链，bot 仅领 token、转发链接、轮询结果后本地落库
    at_sender = True if ev.group_id else False
    auth = {"bot_id": ev.bot_id, "user_id": ev.user_id}
    uid = ""
    login_info: Dict[str, Any] = {}

    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(
                url + "/waves/c/token",
                json=auth,
                headers={"Content-Type": "application/json"},
            )
            text = r.text
            if not text or text.strip() == "":
                logger.error(f"[鸣潮·云登录] 取 token 空响应 status={r.status_code}")
                token = ""
            else:
                try:
                    token = r.json().get("token", "")
                except Exception as e:
                    logger.error(f"[鸣潮·云登录] 取 token 解析失败: {e} | {text[:200]}")
                    token = ""
        except Exception as e:
            token = ""
            logger.error(f"[鸣潮·云登录] 取 token 请求失败: {e}")
        if not token:
            return await bot.send("服务请求失败! 请稍后再试\n", at_sender=at_sender)

        await send_login(bot, ev, f"{url}/waves/i/{token}", refresh_panel=False)

        times = 3
        try:
            async with timeout(180):
                while True:
                    if times <= 0:
                        return await bot.send(
                            "服务请求失败! 请稍后再试\n", at_sender=at_sender
                        )

                    result = await client.post(
                        url + "/waves/c/get", json={"token": token}
                    )
                    if result.status_code != 200:
                        times -= 1
                        await asyncio.sleep(5)
                        continue

                    try:
                        data = result.json()
                    except Exception as e:
                        logger.error(
                            f"[鸣潮·云登录] /waves/c/get 解析失败: {e} | {result.text[:200]}"
                        )
                        times -= 1
                        await asyncio.sleep(5)
                        continue

                    if data.get("done") and not data.get("success", True):
                        return await bot.send(
                            (" " if at_sender else "")
                            + f"{GAME_TITLE} {data.get('msg') or '云登录失败'}",
                            at_sender=at_sender,
                        )

                    if not data.get("done"):
                        await asyncio.sleep(1)
                        continue

                    uid = str(data.get("uid") or "")
                    login_info = data.get("login_info") or {}
                    if not uid or not login_info:
                        return await bot.send(
                            f"{GAME_TITLE} 服务返回数据异常，请稍后重试",
                            at_sender=at_sender,
                        )
                    break
        except asyncio.TimeoutError:
            return await bot.send("登录超时!", at_sender=at_sender)
        except Exception as e:
            logger.exception(f"[鸣潮·云登录] 外置异常: {e}")
            return

    try:
        await _persist_and_bind(ev.user_id, ev.bot_id, ev.group_id, uid, login_info)
    except Exception as e:
        logger.exception("[鸣潮·云登录] 外置存表/绑定失败")
        return await bot.send(f"{GAME_TITLE} 绑定失败：{e}", at_sender=at_sender)

    record_id = await fetch_cloud_record_id(ev.user_id, ev.bot_id, uid)
    if not record_id:
        user_pref = await get_hide_uid_pref(uid, ev.user_id, ev.bot_id)
        return await bot.send(
            (" " if at_sender else "")
            + f"{GAME_TITLE} 云登录成功，UID{hide_uid(uid, user_pref)} 已记录\n"
            + "抽卡记录拉取失败",
            at_sender=at_sender,
        )
    return await _login_then_update(bot, ev, uid, record_id)


# ===== 网页渲染 ===============================================
async def render_cloud_login_page(auth: str, state: Dict[str, Any]) -> HTMLResponse:
    url, _ = await get_url()
    url = url.rstrip("/")

    custom_path = Path(ShowConfig.get_config("LoginIndexCloudHtmlPath").data)
    template = None
    if custom_path.exists():
        try:
            template = custom_waves_template.get_template("index_cloud.html")
        except Exception:
            template = None
    if template is None:
        template = waves_templates.get_template("index_cloud.html")

    return HTMLResponse(
        template.render(
            server_url=url,
            auth=auth,
            userId=state.get("user_id", ""),
            captchaId=_get_cloud_api_module().GEETEST_CAPTCHA_ID,
            product=_get_cloud_api_module().GEETEST_PRODUCT,
        )
    )


# ===== FastAPI 端点 ===========================================
class CloudSendCodeRequest(BaseModel):
    auth: str
    phone: str
    geetest: Optional[Dict[str, Any]] = None


class CloudLoginRequest(BaseModel):
    auth: str
    phone: str
    code: str
    # 机房/异常 IP 二次要求滑块时，前端补滑块后带 geetest 重试本接口
    geetest: Optional[Dict[str, Any]] = None


@app.post("/waves/c/sendCode")
async def waves_cloud_send_code(data: CloudSendCodeRequest):
    state = cache.get(data.auth)
    if not isinstance(state, dict) or state.get("flow") != LOGIN_FLOW:
        return {"success": False, "msg": "登录会话已超时，请重新发起命令"}
    if len(data.phone) != 11 or not data.phone.isdigit():
        return {"success": False, "msg": "手机号格式错误"}

    device_num = str(
        state.get("device_num") or _get_cloud_api_module().gen_device_num()
    )
    resp = await _cloud_api().send_phone_code(data.phone, data.geetest, device_num)
    if not resp.success:
        return {"success": False, "msg": resp.msg or "验证码发送失败"}
    return {"success": True}


@app.post("/waves/c/login")
async def waves_cloud_login(data: CloudLoginRequest):
    state = cache.get(data.auth)
    if not isinstance(state, dict) or state.get("flow") != LOGIN_FLOW:
        return {"success": False, "msg": "登录会话已超时，请重新发起命令"}
    if len(data.phone) != 11 or not data.phone.isdigit() or not data.code.strip():
        return {"success": False, "msg": "手机号或验证码格式错误"}

    device_num = str(
        state.get("device_num") or _get_cloud_api_module().gen_device_num()
    )
    did = str(state.get("did") or _get_cloud_api_module().gen_did())

    try:
        ok, msg, result = await _cloud_api().do_cloud_login(
            data.phone, data.code, device_num, did, data.geetest
        )
    except Exception as e:
        logger.exception("[鸣潮·云登录] 登录链路异常")
        state["phase"] = "failed"
        state["error_msg"] = f"登录异常：{e}"
        cache.set(data.auth, state)
        return {"success": False, "msg": "登录异常，请稍后重试"}

    # 机房/异常 IP 在 phoneCode 步被风控二次要求滑块：不置 failed，让前端补一次
    # 滑块后带 geetest 重试本接口（登录会话保持，指令侧继续轮询等待结果）。
    if msg == _get_cloud_api_module().NEED_GEETEST:
        return {"success": False, "need_captcha": True, "msg": "请完成滑块验证"}

    if not ok or not result:
        state["phase"] = "failed"
        state["error_msg"] = msg or "云登录失败"
        cache.set(data.auth, state)
        return {"success": False, "msg": msg or "云登录失败"}

    uid = result["uid"]
    login_info = result["login_info"]

    try:
        await _persist_and_bind(
            str(state.get("user_id") or ""),
            str(state.get("bot_id") or ""),
            state.get("group_id"),
            uid,
            login_info,
        )
    except Exception as e:
        logger.exception("[鸣潮·云登录] 存表/绑定失败")
        state["phase"] = "failed"
        state["error_msg"] = f"绑定失败：{e}"
        cache.set(data.auth, state)
        return {"success": False, "msg": str(e)}

    state["phase"] = "done"
    state["uid"] = uid
    cache.set(data.auth, state)
    return {"success": True}
