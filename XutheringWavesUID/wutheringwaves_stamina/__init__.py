from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from ..utils.at_help import ruser_id
from ..utils.util import with_refresh_alias
from ..utils.error_reply import ERROR_CODE, WAVES_CODE_102
from .draw_waves_stamina import draw_stamina_img
from ..utils.database.models import WavesBind

waves_daily_info = SV("waves查询体力")


@waves_daily_info.on_fullmatch(
    with_refresh_alias((
        "每日",
        "mr",
        "实时便笺",
        "便笺",
        "便签",
        "体力",
    )),
    to_ai="""查询用户当前鸣潮账号的体力 / 每日实时便笺 / 任务进度。

当用户问「我体力多少 / 现在还有多少结晶波片 / 每日做完了吗 / 看下便笺」时调用。
需要用户已绑定 UID 和 cookie，否则返回未绑定提示。
返回结果是一张图片，包含体力数值、恢复时间、每日任务进度等。

Args:
    text: 无需参数，留空即可。
""",
)
async def send_daily_info_pic(bot: Bot, ev: Event):
    await bot.logger.info(f"[鸣潮·体力] 开始执行[每日信息]: {ruser_id(ev)}")
    uid = await WavesBind.get_uid_by_game(ruser_id(ev), ev.bot_id)
    if not uid:
        # 强需要登录的功能, uid 缺失直接报 102 (登录提示), 避免用户绑定 uid 后再被告知"还要登录"
        return await bot.send(ERROR_CODE[WAVES_CODE_102])
    return await bot.send(await draw_stamina_img(bot, ev))
