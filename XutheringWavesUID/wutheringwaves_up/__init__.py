from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .pool import get_pool_data_by_type
from ..utils.util import use_longest_keyword

sv_pool_countdown = SV("鸣潮卡池倒计时")


_GET_POOL_COUNTDOWN_KEYWORDS = (
    "卡池倒计时",
    "复刻",
    "未复刻",
    "复刻统计",
    "复刻倒计时",
    "复刻时间",
    "角色复刻",
    "武器复刻",
    "復刻",
    "未復刻",
    "未复刻统计",
    "未复刻角色",
    "未复刻角色统计",
    "未复刻武器",
    "未复刻武器统计",
    "卡池倒計時",
    "未復刻統計",
    "未復刻角色",
    "未復刻角色統計",
    "未復刻武器",
    "未復刻武器統計",
)


@sv_pool_countdown.on_command(
    _GET_POOL_COUNTDOWN_KEYWORDS,
    block=True,
    to_ai="""查询鸣潮未复刻角色或武器倒计时一览图。

当用户问「哪些角色还没复刻 / 武器复刻倒计时 / 未复刻5星 / 卡池倒计时」时调用。
命令字本身决定查角色还是武器（"未复刻角色" vs "未复刻武器"）。text 可附星级。

Args:
    text: 可选 "4" 或 "5"，默认 5 星。
""",
)
async def get_pool_countdown(bot: Bot, ev: Event):
    use_longest_keyword(ev, _GET_POOL_COUNTDOWN_KEYWORDS)
    star = 5
    if ev.text.strip():
        text = ev.text.strip()
        if "4" in text or "四" in text:
            star = 4

    query_type = "角色"
    if "角色" in ev.command:
        query_type = "角色"
    elif "武器" in ev.command:
        query_type = "武器"

    msg = await get_pool_data_by_type(query_type, star)
    if msg:
        await bot.send(msg)
