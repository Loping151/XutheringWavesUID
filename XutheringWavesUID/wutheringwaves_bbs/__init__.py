from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event

from .bbs_card import kuro_coin_card
from ..utils.hint import error_reply
from ..utils.at_help import ruser_id, is_intl_uid, intl_unavailable_msg
from ..utils.waves_api import waves_api
from ..utils.error_reply import WAVES_CODE_102, WAVES_CODE_103
from ..utils.database.models import WavesBind

sv_bbs = SV("鸣潮库洛币")

@sv_bbs.on_fullmatch(
    ("库洛币", "库币", "coin"),
    block=True,
    to_ai="""查询用户鸣潮账号的库洛币余额 + 月卡/每日签到状态。

当用户问「我库洛币多少 / 月卡续了吗 / 今天签到了吗」时调用。需绑定 cookie。
返回图片。

Args:
    text: 无需参数，留空即可。
    user_id: 可选，调用方用户 ID（如 QQ 号），MCP 跨平台调用时传入以定位当前用户绑定。留空则使用当前对话发起者。
""",
)
async def kuro_coin_(bot: Bot, ev: Event):
    """查询库洛币"""
    logger.info("[鸣潮·库街区] 开始执行[库洛币]")
    user_id = ruser_id(ev)
    uid = await WavesBind.get_uid_by_game(user_id, ev.bot_id)
    logger.info(f"[鸣潮·库洛币] user_id: {user_id} UID: {uid}")
    if not uid:
        # 强需要登录的功能, uid 缺失直接报 102 (登录提示), 避免用户绑定 uid 后再被告知"还要登录"
        await bot.send(error_reply(WAVES_CODE_102))
        return
    if is_intl_uid(uid):
        await bot.send(intl_unavailable_msg(uid))
        return

    ck, err = await waves_api.check_self_login(uid, user_id, ev.bot_id)
    if not ck:
        await bot.send(err or error_reply(WAVES_CODE_102))
        return

    im = await kuro_coin_card(ck)
    if im:
        await bot.send(im)
