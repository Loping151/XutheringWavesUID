from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from ..utils.hint import error_reply
from ..utils.at_help import ruser_id, is_intl_uid, intl_unavailable_msg
from .draw_echo_list import get_draw_list
from ..utils.error_reply import WAVES_CODE_103
from ..utils.database.models import WavesBind

sv_waves_echo_list = SV("声骸展示", priority=3)


@sv_waves_echo_list.on_regex(
    r"^(?P<command>声骸列表|我的声骸|声骸仓库|声骸|声骇|sh)(?P<pages>\d+)?$",
    block=True,
    to_ai="""查询自己的声骸仓库列表（按 cost、套装、词条评分排序）。

当用户问「我的声骸 / 声骸列表 / 声骸仓库」时调用。需绑定 cookie。
text 可附页码（数字），分页查看。

Args:
    text: 命令字 + 可选页码。例: "声骸列表" / "声骸列表2" / "声骸"。
""",
)
async def send_echo_list_msg(bot: Bot, ev: Event):
    user_id = ruser_id(ev)
    uid = await WavesBind.get_uid_by_game(user_id, ev.bot_id)
    if not uid:
        return await bot.send(error_reply(WAVES_CODE_103))
    if is_intl_uid(uid):
        return await bot.send(intl_unavailable_msg(uid))

    # 更新groupid
    await WavesBind.insert_waves_uid(user_id, ev.bot_id, uid, ev.group_id, lenth_limit=9)

    pages = ev.regex_dict.get("pages")
    if pages:
        try:
            page_num = int(pages)
        except ValueError:
            page_num = 1
    else:
        page_num = 1

    im = await get_draw_list(ev, uid, user_id, page_num)
    return await bot.send(im)
