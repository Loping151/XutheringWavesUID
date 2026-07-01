import asyncio
from pathlib import Path
from typing import Any, Dict

from async_timeout import timeout
from pydantic import BaseModel
from starlette.responses import HTMLResponse

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.web_app import app

from ..utils.constants import WAVES_GAME_ID
from ..utils.database.models import WavesUser
from ..utils.resource.RESOURCE_PATH import custom_waves_template, waves_templates
from ..wutheringwaves_config import ShowConfig
from ..wutheringwaves_login.login import (
    cache,
    get_url,
    get_token,
    evict_user_login,
    send_login,
)
from . import deal
from .login_succ import login_success_msg


async def add_token_web(bot: Bot, ev: Event):
    url, is_local = await get_url()
    if not is_local:
        return await bot.send(
            "Web添加token不支持外置模式，请使用【添加token token,did】命令"
        )
    return await _add_token_web_local(bot, ev, url)


async def _add_token_web_local(bot: Bot, ev: Event, url: str):
    at_sender = True if ev.group_id else False
    evict_user_login(ev.user_id)
    user_token = get_token()

    cache.set(
        user_token,
        {
            "flow": "add_token",
            "token": None,
            "user_id": ev.user_id,
            "bot_id": ev.bot_id,
            "group_id": ev.group_id,
        },
    )
    await send_login(bot, ev, f"{url}/waves/add_token_page/{user_token}")

    try:
        async with timeout(180):
            while True:
                result = cache.get(user_token)
                if result is None:
                    return
                if not isinstance(result, dict) or result.get("flow") != "add_token":
                    return
                if result.get("token") is not None:
                    token = result["token"]
                    cache.delete(user_token)
                    break
                await asyncio.sleep(1)
    except asyncio.TimeoutError:
        return await bot.send("添加token超时!", at_sender=at_sender)
    except Exception as e:
        logger.exception(f"[鸣潮·添加token] 异常: {e}")
        return await bot.send("添加token失败，请稍后再试", at_sender=at_sender)

    if not token:
        return

    ck_msg = await deal.add_cookie(ev, token, "", is_login=False)
    if isinstance(ck_msg, str) and ("登录成功" in ck_msg or "记录成功" in ck_msg):
        await bot.send((" " if at_sender else "") + ck_msg.rstrip("\n"), at_sender)
        user = await WavesUser.get_user_by_attr(
            ev.user_id, ev.bot_id, "cookie", token, game_id=WAVES_GAME_ID
        )
        if user:
            return await login_success_msg(bot, ev, user)
        return
    ck_msg = ck_msg.rstrip("\n") if isinstance(ck_msg, str) else ck_msg
    await bot.send(
        (" " if at_sender and isinstance(ck_msg, str) else "") + ck_msg
        if isinstance(ck_msg, str)
        else ck_msg,
        at_sender,
    )


async def render_add_token_page(auth: str, state: Dict[str, Any]) -> HTMLResponse:
    url, _ = await get_url()

    custom_path = Path(ShowConfig.get_config("LoginAddTokenHtmlPath").data)
    if custom_path.exists():
        try:
            template = custom_waves_template.get_template("add_token.html")
        except Exception:
            template = waves_templates.get_template("add_token.html")
    else:
        template = waves_templates.get_template("add_token.html")

    return HTMLResponse(
        template.render(
            server_url=url,
            auth=auth,
            userId=state.get("user_id", ""),
        )
    )


class AddTokenModel(BaseModel):
    auth: str
    token: str


@app.get("/waves/add_token_page/{auth}")
async def waves_add_token_index(auth: str):
    state = cache.get(auth)
    if not isinstance(state, dict) or state.get("flow") != "add_token":
        return HTMLResponse("会话不存在或已超时", status_code=404)
    return await render_add_token_page(auth, state)


@app.post("/waves/add_token")
async def waves_add_token(data: AddTokenModel):
    temp = cache.get(data.auth)
    if temp is None:
        return {"success": False, "msg": "会话已超时"}
    if not isinstance(temp, dict) or temp.get("flow") != "add_token":
        return {"success": False, "msg": "会话不匹配"}

    temp["token"] = data.token
    cache.set(data.auth, temp)
    return {"success": True}
