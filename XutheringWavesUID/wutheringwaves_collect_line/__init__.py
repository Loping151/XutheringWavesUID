from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event

from ..utils.hint import error_reply
from ..utils.at_help import ruser_id, is_intl_uid, intl_unavailable_msg
from ..utils.error_reply import WAVES_CODE_103
from ..utils.database.models import WavesBind
from .line_data import build_bingo_answer
from .draw_line import draw_bingo_img

sv_waves_bingo = SV("ww角色连线收集图", priority=3)


@sv_waves_bingo.on_fullmatch(
    (
        "收集图",
        "角色收集图",
        "lx",
        "连线",
        "mclx",
        "鸣潮角色连线",
        "mcjslx",
        "sjt",
        "jssjt",
    ),
    block=True,
    to_ai="""根据用户鸣潮账号已有角色生成 6x6 Bingo 收集图。

当用户问「收集图 / 角色收集图 / 连线 / 鸣潮角色连线」时调用。
需要用户已绑定鸣潮 UID，并且本地已有角色面板缓存。

Args:
    text: 无需参数，留空即可。
""",
)
async def send_waves_bingo(bot: Bot, ev: Event) -> None:
    logger.info("[鸣潮·收集图] 开始生成角色收集图")
    user_id = ruser_id(ev)
    uid = await WavesBind.get_uid_by_game(user_id, ev.bot_id)
    if not uid:
        await bot.send(error_reply(WAVES_CODE_103))
        return
    if is_intl_uid(uid):
        await bot.send(intl_unavailable_msg(uid))
        return

    data = await build_bingo_answer(uid)
    if isinstance(data, str):
        await bot.send(data)
        return

    im = await draw_bingo_img(data, ev, uid)
    await bot.send(im)
