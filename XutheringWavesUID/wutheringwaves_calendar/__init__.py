from typing import Any, List

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from ..utils.button import WavesButton
from .draw_calendar_card import draw_calendar_img

sv_waves_calendar = SV("waves日历")


@sv_waves_calendar.on_fullmatch(
    ("个人日历", "日历", "個人日曆", "日曆", "rl", "活动", "活動", "活动日历", "卡池", "当期卡池", "当前卡池"),
    block=True,
    to_ai="""查询鸣潮活动日历 + 卡池倒计时一览图。

当用户问「最近有什么活动 / 当前活动 / 卡池什么时候结束 / 下期卡池开多久」时调用。
不需要绑定。返回一张图。

Args:
    text: 无需参数，留空即可。
""",
)
async def send_waves_calendar_pic(bot: Bot, ev: Event):
    uid = ""
    im = await draw_calendar_img(ev, uid)
    if isinstance(im, str):
        return await bot.send(im)
    else:
        buttons: List[Any] = [
            WavesButton("深塔", "深塔"),
            WavesButton("冥海", "冥海"),
        ]
        return await bot.send_option(im, buttons)
