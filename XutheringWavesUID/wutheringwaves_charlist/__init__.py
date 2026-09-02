import re

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment

from ..utils.hint import error_reply
from ..utils.at_help import ruser_id, is_intl_uid, intl_unavailable_msg
from .draw_char_list import draw_char_list_img
from ..utils.error_reply import WAVES_CODE_103
from ..utils.database.models import WavesBind

sv_waves_char_list = SV("ww角色练度统计", priority=3)

PARAM_RE = r"全部|all|五星|5星|四星|4星|五|四|5|4|1|2"


@sv_waves_char_list.on_regex(
    rf"^(\d+)?(练度|ld|练度统计|角色列表|刷新练度|刷新练度统计|刷新角色列表|updld)(?:\s*(?:{PARAM_RE}))*$",
    block=True,
    to_ai="""查询账号下全部角色的练度统计图（按等级/共鸣链/武器谐振/声骸主词条评分排序）。

当用户问「练度统计 / 我有哪些角色 / 角色列表」时调用。需绑定 cookie。
text 也可以是「刷新练度统计」从库街区拉新后再统计（写操作）。
可选 9 位 UID 前缀窥视别人。可附星级 五星/四星/全部 筛选；可附 1/2 指定单列/双列排版（不传则按角色数量自动）。

Args:
    text: 例: "练度统计" / "练度" / "ld" (查自己) / "刷新练度统计" (强制刷新后统计) / "123456789练度统计" (窥视别人) / "练度统计 五星" (按星级筛选) / "练度2" (双列) / "练度1 五星" (单列+五星)。
""",
)
async def send_char_list_msg_new(bot: Bot, ev: Event):
    match = re.search(
        r"(?P<waves_id>\d+)?(?P<query_type>刷新练度统计|刷新角色列表|刷新练度|练度统计|角色列表|练度|updld|ld)",
        ev.raw_text,
    )
    if not match:
        return
    query_waves_id = match.group("waves_id")
    query_type = match.group("query_type")

    star_filter = None
    col = None
    for token in re.findall(PARAM_RE, ev.raw_text[match.end():]):
        if token in ("1", "2"):
            col = int(token)
        elif token in ("全部", "all"):
            star_filter = "all"
        elif token in ("四星", "4星", "四", "4"):
            star_filter = "4"
        else:
            star_filter = "5"

    is_refresh = False
    if "刷新" in query_type or "upd" in query_type:
        is_refresh = True

    is_peek = False
    if query_waves_id:
        is_peek = True
        if not query_waves_id.isdigit() or len(query_waves_id) != 9:
            return await bot.send("请输入正确的查询特征码")

    user_id = ruser_id(ev)
    user_waves_id = await WavesBind.get_uid_by_game(user_id, ev.bot_id) or ""
    if not query_waves_id:
        query_waves_id = user_waves_id

    # 参数校验
    if not query_waves_id:
        return await bot.send(error_reply(WAVES_CODE_103))
    if is_intl_uid(query_waves_id):
        return await bot.send(intl_unavailable_msg(query_waves_id))

    if not is_peek:
        # 更新groupid
        await WavesBind.insert_waves_uid(user_id, ev.bot_id, query_waves_id, ev.group_id, lenth_limit=9)

    im = await draw_char_list_img(
        query_waves_id,
        ev,
        user_id,
        is_refresh,
        is_peek,
        user_waves_id,
        star_filter,
        col,
    )
    if isinstance(im, bytes) and (is_peek or is_refresh):
        return await bot.send(["[鸣潮] 数据已刷新", MessageSegment.image(im)])
    return await bot.send(im)
