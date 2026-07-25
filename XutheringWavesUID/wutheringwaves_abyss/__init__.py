from typing import Any, List

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from ..utils.hint import error_reply
from ..utils.button import WavesButton
from ..utils.at_help import ruser_id, is_intl_uid, intl_unavailable_msg
from .draw_slash_card import draw_slash_img
from .draw_matrix_card import draw_matrix_img
from ..utils.error_reply import WAVES_CODE_103
from .draw_challenge_card import draw_challenge_img
from ..utils.database.models import WavesBind
from .draw_abyss_card import draw_abyss_img

sv_waves_abyss = SV("waves查询深渊")
sv_waves_challenge = SV("waves查询全息")
sv_waves_slash = SV("waves查询冥海")
sv_waves_matrix = SV("waves查询矩阵")
sv_waves_rank_slash = SV("waves冥海总排行", priority=0)
sv_waves_rank_slash_list = SV("waves无尽排行", priority=0)
sv_waves_rank_matrix = SV("waves矩阵总排行", priority=0)
sv_waves_rank_matrix_list = SV("waves矩阵排行", priority=0)


def _is_matrix_single_team_command(ev: Event) -> bool:
    return "单队" in ev.raw_text or "队伍" in ev.raw_text or "dd" in ev.raw_text or "dw" in ev.raw_text


def _parse_matrix_rank_args(ev: Event, strict: bool):
    """返回 (char_ids, page, 错误提示); strict=False 时队伍解析失败按无队伍参数处理"""
    from ..utils.team_query import parse_matrix_team, split_team_and_page
    from ..wutheringwaves_rank.pagination import normalize_rank_page

    team_text, tail_page = split_team_and_page(ev.regex_dict.get("team"))
    page = normalize_rank_page(ev.regex_dict.get("pages") or tail_page)
    char_ids, err = parse_matrix_team(team_text)
    if err and not strict:
        return [], page, None
    return char_ids, page, err


@sv_waves_abyss.on_fullmatch(
    (
        "查询深渊",
        "sy",
        "st",
        "深渊",
        "逆境深塔",
        "深塔",
        "超载",
        "超载区",
        "稳定",
        "稳定区",
        "实验",
        "实验区",
    ),
    block=True,
    to_ai="""查询用户本人在鸣潮「逆境深塔」（深境区/超载/稳定/实验）当前期数的挑战记录。

当用户问「我深塔打到几层 / 这期超载怎么样 / 我深塔满星了吗 / 看看我的稳定区」时调用。
需要绑定 UID + cookie。返回图片，含通关层数、用时、上阵角色等。
注意：本工具查的是**用户自己已有的挑战记录**，不是查"本期深塔关卡配置/Buff"——那应该用 search_knowledge 查 ww_tower_* 知识库。

Args:
    text: 无需参数，留空即可。命令本身已涵盖默认深境区。
""",
)
async def send_waves_abyss_info(bot: Bot, ev: Event):
    await bot.logger.info("[鸣潮·查询深塔] 开始执行")

    user_id = ruser_id(ev)
    uid = await WavesBind.get_uid_by_game(user_id, ev.bot_id)
    if not uid:
        return await bot.send(error_reply(WAVES_CODE_103))
    if is_intl_uid(uid):
        return await bot.send(intl_unavailable_msg(uid))
    await bot.logger.info(f"[鸣潮·查询深塔] user_id={user_id} uid={uid}")

    im = await draw_abyss_img(ev, uid, user_id)
    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        await bot.send(f" {im}" if at_sender else im, at_sender)
    else:
        buttons: List[Any] = [
            WavesButton("深塔", "深塔"),
            WavesButton("超载", "超载"),
            WavesButton("稳定", "稳定"),
            WavesButton("实验", "实验"),
        ]
        await bot.send_option(im, buttons)


@sv_waves_challenge.on_fullmatch(
    (
        "查询全息",
        "查询全息战略",
        "全息",
        "qx",
        "全息战略",
    ),
    block=True,
    to_ai="""查询用户本人在鸣潮「全息战略」（同步挑战）的通关记录。

「全息战略」是鸣潮的 boss 单挑模拟玩法（如朔雷之鳞、无妄者等），与逆境深塔/矩阵不同。
当用户问「我全息战略打到哪 / 同步挑战进度 / 朔雷之鳞过了吗」时调用。
需要绑定 UID + cookie。返回图片，含每个 boss 难度通关情况。

Args:
    text: 无需参数，留空即可。
""",
)
async def send_waves_challenge_info(bot: Bot, ev: Event):
    await bot.logger.info("[鸣潮·查询全息] 开始执行")

    user_id = ruser_id(ev)
    uid = await WavesBind.get_uid_by_game(user_id, ev.bot_id)
    if not uid:
        return await bot.send(error_reply(WAVES_CODE_103))
    if is_intl_uid(uid):
        return await bot.send(intl_unavailable_msg(uid))
    await bot.logger.info(f"[鸣潮·查询全息] user_id={user_id} uid={uid}")

    im = await draw_challenge_img(ev, uid, user_id)
    at_sender = True if ev.group_id else False
    if isinstance(im, str):
        return await bot.send(f" {im}" if at_sender else im, at_sender)
    else:
        return await bot.send(im)


@sv_waves_slash.on_command(
    (
        "冥海",
        "mh",
        "hx",
        "海墟",
        "冥歌海墟",
        "查询冥海",
        "查询无尽",
        "查询海墟",
        "无尽",
        "wj",
        "无尽深渊",
        "禁忌",
        "禁忌海域",
        "再生海域",
    ),
    block=True,
    to_ai="""查询用户本人在鸣潮「冥歌海墟」（海墟 / 无尽深渊 / 禁忌海域 / 再生海域）的通关记录。

当用户问「我海墟打到几层 / 冥海多少分 / 无尽深渊进度 / 禁忌过了吗」时调用。
需要绑定 UID + cookie。返回图片。
本工具查**用户的挑战记录**，不是查"本期 Buff 列表"——后者用 search_knowledge 查 ww_slash_* 知识库。

Args:
    text: 无需参数，留空即可。
""",
)
async def send_waves_slash_info(bot: Bot, ev: Event):
    user_id = ruser_id(ev)
    uid = await WavesBind.get_uid_by_game(user_id, ev.bot_id)
    if not uid:
        return await bot.send(error_reply(WAVES_CODE_103))
    if is_intl_uid(uid):
        return await bot.send(intl_unavailable_msg(uid))

    im = await draw_slash_img(ev, uid, user_id)
    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        return await bot.send(f" {im}" if at_sender else im, at_sender)
    else:
        buttons: List[Any] = [
            WavesButton("冥歌海墟", "冥海"),
            WavesButton("冥海前6层", "禁忌"),
            WavesButton("冥海11层", "冥海11"),
            WavesButton("冥海12层", "无尽"),
        ]
        return await bot.send_option(im, buttons)


@sv_waves_matrix.on_fullmatch(
    (
        "矩阵",
        "终焉",
        "终焉矩阵",
        "矩阵叠兵",
        "查询矩阵",
        "奇点扩张",
        "稳态协议",
        "囚笼",
        "jz"
    ),
    block=True,
    to_ai="""查询用户本人在鸣潮「全息矩阵」（矩阵叠兵 / 终焉矩阵 / 奇点扩张 / 稳态协议）的挑战记录。

当用户问「我矩阵打到哪 / 这期奇点扩张过了吗 / 矩阵积分多少」时调用。
需要绑定 UID + cookie。返回图片，含队伍配置、关卡通关状态、积分。
本工具查**用户的挑战记录**；查"本期矩阵关卡 / 怪物 / Buff"用 search_knowledge 查 ww_matrix_* 知识库。

Args:
    text: 无需参数，留空即可。
""",
)
async def send_waves_matrix_info(bot: Bot, ev: Event):
    user_id = ruser_id(ev)
    uid = await WavesBind.get_uid_by_game(user_id, ev.bot_id)
    if not uid:
        return await bot.send(error_reply(WAVES_CODE_103))
    if is_intl_uid(uid):
        return await bot.send(intl_unavailable_msg(uid))

    im = await draw_matrix_img(ev, uid, user_id)
    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        return await bot.send(f" {im}" if at_sender else im, at_sender)
    else:
        return await bot.send(im)


@sv_waves_rank_slash.on_regex(
    r"^(?:无尽总排行|wjzph|wjzpm|无尽总排行榜|冥海总排行|冥海总排行榜)(?P<pages>\d+)?$",
    block=True,
    to_ai='''查询全体冥歌海墟无尽层总排行（跨群）。

当用户问「无尽总排行 / 冥海总排行」时调用。

Args:
    text: 可在命令末尾加页码。例: "无尽总排行2"。
''',
)
async def send_waves_rank_slash_info(bot: Bot, ev: Event):
    from ..wutheringwaves_rank.slash_rank import draw_all_slash_rank_card
    from ..wutheringwaves_rank.pagination import normalize_rank_page

    page = normalize_rank_page(ev.regex_dict.get("pages"))
    im = await draw_all_slash_rank_card(bot, ev, page)
    return await bot.send(im)


@sv_waves_rank_slash_list.on_regex(
    r"^(?:无尽排行|wjph|wjpm|无尽排行榜|无尽排名|无尽群排行|无尽群排行榜|无尽群排名|群无尽排行|群无尽排名)(?P<pages>\d+)?$",
    block=True,
    to_ai='''查询本群冥歌海墟无尽层排行，仅群聊可用。

当用户在群里问「群里谁海墟最强 / 无尽排行」时调用。私聊会被拒绝。

Args:
    text: 可在命令末尾加页码。例: "无尽排行2"。
''',
)
async def send_waves_rank_slash_list_info(bot: Bot, ev: Event):
    if not ev.group_id:
        return await bot.send("请在群聊中使用")
    from ..wutheringwaves_rank.slash_rank import draw_slash_rank_list
    from ..wutheringwaves_rank.pagination import normalize_rank_page

    page = normalize_rank_page(ev.regex_dict.get("pages"))
    im = await draw_slash_rank_list(bot, ev, page)
    return await bot.send(im)


@sv_waves_rank_matrix.on_regex(
    r"^(?:矩阵总排行|jzzph|jzzpm|jzddzph|jzddzpm|jzdwzph|jzdwzpm|矩阵总排行榜|矩阵单队总排行|矩阵单队总排行榜|矩阵队伍总排行|矩阵队伍总排行榜)(?P<pages>\d+)?(?P<team>[\s,，、/|]*[一-鿿\d][\s\S]*)?$",
    block=True,
    to_ai='''查询全体终焉矩阵积分总排行（跨群）。

当用户问「矩阵总排行 / 全体矩阵积分」时调用；问「矩阵单队总排行 / 矩阵队伍总排行」时按最高单队积分查询。

Args:
    text: 可加页码（命令后或末尾均可）。带三个角色名 / 三字首字缩写时只排该队伍（顺序无关、buff 不限）。
        例: "矩阵总排行2"、"矩阵单队总排行 今汐 折枝 守岸人"、"矩阵单队总排行 今折守 2"。
''',
)
async def send_waves_rank_matrix_info(bot: Bot, ev: Event):
    from ..wutheringwaves_rank.matrix_rank import draw_all_matrix_rank_card

    single_team_cmd = _is_matrix_single_team_command(ev)
    char_ids, page, err = _parse_matrix_rank_args(ev, single_team_cmd)
    if err:
        return await bot.send(err)

    single_team = single_team_cmd or bool(char_ids)
    im = await draw_all_matrix_rank_card(
        bot,
        ev,
        single_team=single_team,
        page=page,
        char_ids=char_ids,
    )
    return await bot.send(im)


@sv_waves_rank_matrix_list.on_regex(
    r"^(?:矩阵排行|jzph|jzpm|jzddph|jzddpm|jzdwph|jzdwpm|矩阵排行榜|矩阵排名|矩阵群排行|矩阵群排行榜|矩阵群排名|群矩阵排行|群矩阵排名|矩阵单队排行|矩阵单队排行榜|矩阵队伍排行|矩阵队伍排行榜)(?P<pages>\d+)?(?P<team>[\s,，、/|]*[一-鿿\d][\s\S]*)?$",
    block=True,
    to_ai='''查询本群终焉矩阵积分排行，仅群聊可用。

当用户在群里问「群里谁矩阵积分最高 / 矩阵排行」时调用；问「矩阵单队排行 / 矩阵队伍排行」时按最高单队积分查询。私聊会被拒绝。

Args:
    text: 可加页码（命令后或末尾均可）。带三个角色名 / 三字首字缩写时只排该队伍（顺序无关、buff 不限）。
        例: "矩阵排行2"、"矩阵单队排行 今汐 折枝 守岸人"、"矩阵单队排行 今折守 2"。
''',
)
async def send_waves_rank_matrix_list_info(bot: Bot, ev: Event):
    if not ev.group_id:
        return await bot.send("请在群聊中使用")
    from ..wutheringwaves_rank.matrix_rank import draw_matrix_rank_list

    single_team_cmd = _is_matrix_single_team_command(ev)
    char_ids, page, err = _parse_matrix_rank_args(ev, single_team_cmd)
    if err:
        return await bot.send(err)

    single_team = single_team_cmd or bool(char_ids)
    im = await draw_matrix_rank_list(
        bot, ev, single_team=single_team, page=page, char_ids=char_ids
    )
    return await bot.send(im)
