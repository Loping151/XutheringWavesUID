from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from ..utils.hint import error_reply
from ..utils.util import with_refresh_alias
from ..utils.at_help import ruser_id, is_intl_uid, intl_unavailable_msg
from .draw_explore_card import draw_explore_img
from ..utils.error_reply import WAVES_CODE_103
from ..utils.database.models import WavesBind

waves_get_explore = SV("waves获取探索度")


@waves_get_explore.on_fullmatch(
    with_refresh_alias((
        "ts",
        "探索",
        "tsd",
        "探索度",
        "探索进度",
        "地图探索",
        "地图探索度",
        "查看探索度",
    )),
    block=True,
    to_ai="""查询用户鸣潮账号的世界探索度。

当用户问「我的探索度多少 / 各地区探索进度 / 还剩什么没探完」时调用。
需要绑定 UID 和 cookie。返回图片，按地区列出各项探索进度（声笺、地图收集、宝箱等）。

Args:
    text: 无需参数，留空即可。
""",
)
async def send_card_info(bot: Bot, ev: Event):
    user_id = ruser_id(ev)

    uid = await WavesBind.get_uid_by_game(user_id, ev.bot_id)
    if not uid:
        return await bot.send(error_reply(WAVES_CODE_103))
    if is_intl_uid(uid):
        return await bot.send(intl_unavailable_msg(uid))

    msg = await draw_explore_img(ev, uid, user_id)
    return await bot.send(msg)
