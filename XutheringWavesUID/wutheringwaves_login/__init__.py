import re

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event

from .email_login import email_login_entry
from .cloud_login import cloud_login_entry
from .login import code_login, page_login
from ..wutheringwaves_config import PREFIX

sv_kuro_login = SV("街区登录")
# sv_kuro_login_help = SV("库洛登录帮助", pm=0, priority=4)
sv_email_login = SV("邮箱登录")
sv_cloud_login = SV("抽卡登录")


@sv_kuro_login.on_command(("登录", "登陆", "登入", "登龙", "login", "dl"), block=True)
async def get_login_msg(bot: Bot, ev: Event):
    game_title = "[鸣潮]"

    text = re.sub(r"^(\d+)\s+(\d+)$", r"\1,\2", ev.text.strip())
    text = re.sub(r'["\s]+', "", text)
    text = text.replace("，", ",")
    has_text = bool(text)
    branch = "page" if not text else ("code" if "," in text else ("digit_skip" if text.isdigit() else "invalid"))
    logger.debug(
        f"[鸣潮·登录] get_login_msg user_id={ev.user_id} bot_id={ev.bot_id} "
        f"group_id={ev.group_id} has_text={has_text} branch={branch}"
    )
    if text == "":
        return await page_login(bot, ev)

    elif "," in text:
        return await code_login(bot, ev, text)

    at_sender = True if ev.group_id else False
    if text.isdigit():
        msg = (
            f"{game_title} 登录命令格式错误\n"
            f"网页扫码：仅发【{PREFIX}登录】\n"
            f"短信登录：【{PREFIX}登录 手机号,验证码】"
        )
    else:
        msg = f"{game_title} 账号登录失败\n请重新输入命令【{PREFIX}登录】进行登录"
    return await bot.send(
        (" " if at_sender else "") + msg,
        at_sender=at_sender,
    )


@sv_email_login.on_fullmatch(("邮箱登录", "国际服登录"), block=True)
async def get_email_login_msg(bot: Bot, ev: Event):
    logger.debug(
        f"[鸣潮·登录] email_login user_id={ev.user_id} bot_id={ev.bot_id} "
        f"group_id={ev.group_id}"
    )
    return await email_login_entry(bot, ev)


@sv_cloud_login.on_fullmatch(
    (
        "抽卡登录",
        "抽卡登陆",
        "抽卡登入",
        "云鸣潮登录",
        "云鸣潮登陆",
        "云鸣潮登入",
        "云登录",
        "云登陆",
        "云登入",
    ),
    block=True,
)
async def get_cloud_login_msg(bot: Bot, ev: Event):
    logger.debug(
        f"[鸣潮·登录] cloud_login user_id={ev.user_id} bot_id={ev.bot_id} "
        f"group_id={ev.group_id}"
    )
    return await cloud_login_entry(bot, ev)
