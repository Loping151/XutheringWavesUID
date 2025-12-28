from typing import Any, List

from PIL import Image

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.help.utils import register_help

from .get_help import ICON, get_help
from .change_help import get_change_help
from ..utils.button import WavesButton
from ..wutheringwaves_config import PREFIX

sv_waves_help = SV("waves帮助")
sv_waves_change_help = SV("waves替换帮助")


@sv_waves_help.on_fullmatch(("帮助", "help", "bz"), block=False)
async def send_help_img(bot: Bot, ev: Event):
    buttons: List[Any] = [
        WavesButton("登录", "登录"),
        WavesButton("查看特征码", "查看"),
        WavesButton("切换特征码", "切换"),
        WavesButton("体力", "mr"),
        WavesButton("刷新面板", "刷新面板"),
        WavesButton("练度统计", "练度统计"),
    ]
    await bot.send_option(await get_help(ev.user_pm), buttons)


@sv_waves_change_help.on_fullmatch(("替换帮助", "面板替换帮助"))
async def send_change_help_img(bot: Bot, ev: Event):
    await bot.send(await get_change_help(ev.user_pm))


register_help("XutheringWavesUID", f"{PREFIX}帮助", Image.open(ICON))
