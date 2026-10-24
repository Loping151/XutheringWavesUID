from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_period import draw_period_img
from ..utils.at_help import ruser_id, is_intl_uid, intl_unavailable_msg
from ..utils.error_reply import ERROR_CODE, WAVES_CODE_102
from ..utils.database.models import WavesBind
from ..utils.util import use_longest_keyword, with_refresh_alias

sv_period = SV("waves资源简报")


_SEND_PERIOD_KEYWORDS = with_refresh_alias((
    "星声",
    "xs",
    "星声统计",
    "简报",
    "资源简报",
), suffix=False)


@sv_period.on_command(
    _SEND_PERIOD_KEYWORDS,
    block=True,
    to_ai="""查询自己的鸣潮星声（鸣潮原石/月光波币）收入支出统计图。

当用户问「我花了多少钱 / 星声统计 / 这版本月卡多少 / 月星声花在哪了」时调用。
text 可附时间范围：版本号(如 "2.3版本") / "本月" / "上周"。无参数则统计全部。

Args:
    text: 可选时间范围。例: "2.3版本" / "本月" / "上周"。留空统计全部。
""",
)
async def send_period(bot: Bot, ev: Event):
    use_longest_keyword(ev, _SEND_PERIOD_KEYWORDS)
    uid = await WavesBind.get_uid_by_game(ruser_id(ev), ev.bot_id)
    if not uid:
        # 强需要登录的功能, uid 缺失直接报 102 (登录提示), 避免用户绑定 uid 后再被告知"还要登录"
        return await bot.send(ERROR_CODE[WAVES_CODE_102])
    if is_intl_uid(uid):
        return await bot.send(intl_unavailable_msg(uid))

    await bot.send(await draw_period_img(bot, ev))
