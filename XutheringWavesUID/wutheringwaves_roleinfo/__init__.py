from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event

from ..utils.hint import error_reply
from ..utils.util import with_refresh_alias
from ..utils.at_help import ruser_id, is_intl_uid, intl_unavailable_msg
from .draw_role_info import draw_role_img
from .draw_skin_info import draw_skin_img
from .draw_reward_card import draw_reward_img
from ..utils.waves_api import waves_api
from ..utils.error_reply import WAVES_CODE_102, WAVES_CODE_103
from ..utils.database.models import WavesBind

waves_role_info = SV("waves查询信息")
# 收藏图鉴优先级前置于百科图鉴(鸣潮攻略 priority=10), 避免"收藏图鉴"被 <名>图鉴 正则抢匹配
waves_skin_info = SV("waves收藏图鉴", priority=2)


@waves_role_info.on_fullmatch(
    with_refresh_alias(("查询", "卡片", "kp", "名片", "角色卡片")),
    block=True,
    to_ai="""查询自己的鸣潮账号总览卡片（等级 / 活跃天数 / 已激活角色数 / 探索进度等基本信息）。

当用户问「我账号怎样 / 卡片 / 看下我的总览」时调用。需绑定 cookie。

Args:
    text: 无需参数，留空即可。
""",
)
async def send_role_info(bot: Bot, ev: Event):
    logger.info("[鸣潮·角色信息] 开始执行[查询信息]")
    user_id = ruser_id(ev)
    uid = await WavesBind.get_uid_by_game(user_id, ev.bot_id)
    logger.info(f"[鸣潮·查询信息] user_id: {user_id} UID: {uid}")
    if not uid:
        await bot.send(error_reply(WAVES_CODE_103))
        return
    if is_intl_uid(uid):
        await bot.send(intl_unavailable_msg(uid))
        return

    _, ck = await waves_api.get_ck_result(uid, user_id, ev.bot_id)
    if not ck:
        await bot.send(error_reply(WAVES_CODE_102))
        return

    im = await draw_role_img(uid, ck, ev)
    await bot.send(im)  # type: ignore


@waves_skin_info.on_fullmatch(
    ("图鉴", "服饰", "皮肤", "收藏", "收藏图鉴", "皮肤图鉴", "服饰图鉴", "饰品", "饰品图鉴",
     "摩托", "摩托饰品", "涂装", "车架模组", "车架"),
    block=True,
    to_ai="""查询自己的鸣潮收藏图鉴（共鸣者服饰 / 服饰饰品 / 武器投影 / 声骸换影 / 终端替换 / 涂装 / 车架模组 / 摩托饰品）。

当用户问「我的服饰 / 皮肤图鉴 / 收藏了哪些外观 / 摩托涂装」时调用。需绑定 cookie。

Args:
    text: 无需参数，留空即可。
""",
)
async def send_skin_info(bot: Bot, ev: Event):
    logger.info("[鸣潮·服饰] 开始执行[收藏图鉴]")
    user_id = ruser_id(ev)
    uid = await WavesBind.get_uid_by_game(user_id, ev.bot_id)
    logger.info(f"[鸣潮·服饰] user_id: {user_id} UID: {uid}")
    if not uid:
        await bot.send(error_reply(WAVES_CODE_103))
        return
    if is_intl_uid(uid):
        await bot.send(intl_unavailable_msg(uid))
        return

    _, ck = await waves_api.get_ck_result(uid, user_id, ev.bot_id)
    if not ck:
        await bot.send(error_reply(WAVES_CODE_102))
        return

    im = await draw_skin_img(uid, ck, ev)
    await bot.send(im)  # type: ignore


@waves_role_info.on_fullmatch(("积分", "伴行", "伴行积分"), block=True)
async def send_score_info(bot: Bot, ev: Event):
    logger.info("[鸣潮·角色信息] 开始执行[伴行积分]")
    user_id = ruser_id(ev)
    uid = await WavesBind.get_uid_by_game(user_id, ev.bot_id)
    logger.info(f"[鸣潮·伴行积分] user_id: {user_id} UID: {uid}")
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

    im = await draw_reward_img(uid, ck, ev)
    if im:
        await bot.send(im)  # type: ignore
