from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from .draw_rank_card import draw_rank_img
from .draw_all_rank_card import draw_all_rank_card
from .draw_rank_list_card import draw_rank_list
from .draw_total_rank_card import draw_total_rank
from .draw_phantom_rank_card import draw_phantom_rank_img
from .draw_phantom_total_rank_card import draw_phantom_total_rank
from .pagination import normalize_rank_page
from ..utils.char_info_utils import PATTERN
from ..utils.name_resolve import resolve_char
from ..utils.name_convert import char_name_to_char_id
from ..utils.damage.modal import get_modal_key_by_name
from ..utils.util import use_longest_keyword

sv_waves_phantom_rank = SV("ww声骸排行", priority=2)
sv_waves_rank_list = SV("ww角色排行", priority=3)
sv_waves_rank_all_list = SV("ww角色总排行", priority=1)
sv_waves_rank_total_list = SV("ww练度总排行", priority=0)
sv_waves_rank_local_list = SV("ww练度排行", priority=0)
sv_waves_phantom_total_rank = SV("ww声骸总排行", priority=0)


@sv_waves_rank_list.on_regex(
    rf"^(?P<char>{PATTERN})(?:排行|排行榜|排名|ph|pm)(?P<pages>\d+)?\s*(?P<cw>[cC][wW]_[0-9a-zA-Z]{{8}})?\s*$",
    block=True,
    to_ai="""查询本群某角色的排行（伤害或评分），仅群聊可用。

当用户在群里问「<角色>排行 / <角色>评分排行 / 群里谁<角色>最强」时调用。
text 必须是 "<角色名>排行<页码?>" 或 "<角色名>评分排行<页码?>"。
名字中含「评分」/「pf」/「练度」会走评分模式，否则走伤害模式。

私聊会被拒绝。

Args:
    text: 例: "长离排行"、"椿评分排行2"。
""",
)
async def send_rank_card(bot: Bot, ev: Event):
    if not ev.group_id:
        return await bot.send("请在群聊中使用")

    char = ev.regex_dict.get("char")
    pages = normalize_rank_page(ev.regex_dict.get("pages"))

    rank_type = "伤害"
    if "综合" in char:
        rank_type = "综合评分"
    elif "评分" in char or "pf" in char or "练度" in char:
        rank_type = "评分"

    char = (
        char.replace("综合评分", "").replace("综合", "")
        .replace("伤害", "").replace("评分", "").replace("pf", "")
        .replace("练度", "").replace("本群", "").replace("群", "")
    )

    from ..wutheringwaves_config import PREFIX, WutheringWavesConfig
    if rank_type in ("伤害", "综合评分") and not WutheringWavesConfig.get_config("WavesToken").data:
        rank_type = "评分"

    res = None
    canonical_cmd = None
    if char:
        res = resolve_char(char)
        if not res.ok:
            return await bot.send(res.fail_msg())
        char = res.matched
        if rank_type == "评分":
            canonical_cmd = f"{PREFIX}{char}评分排行"
        elif rank_type == "综合评分":
            canonical_cmd = f"{PREFIX}{char}综合评分排行"
        else:
            canonical_cmd = f"{PREFIX}{char}排行"

    from ..utils.custom_weight import find_cw, prepare_plan, using
    from ..utils.resource.constant import SPECIAL_CHAR

    plan = None
    cid = char_name_to_char_id(char) if char else None
    if cid:
        plan = await prepare_plan(bot, ev, SPECIAL_CHAR.get(cid, [cid]), explicit=find_cw(ev.regex_dict.get("cw") or ""), rank=True)
        if plan is None:
            return
    with using(plan):
        im = await draw_rank_img(bot, ev, char, rank_type, pages)

    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        await bot.send(res.with_tip(im, canonical_cmd) if res else im, at_sender)
    elif isinstance(im, bytes):
        await bot.send(res.wrap(im, canonical_cmd) if res else im)


@sv_waves_phantom_rank.on_regex(
    rf"^(?P<char>{PATTERN})(?:声骸排行|声骸排名|声骸排行榜|shph|shpm)(?P<pages>\d+)?$",
    block=True,
    to_ai="""查询本群某角色的单声骸分数排行，仅群聊可用。

当用户在群里问「<角色>声骸排行 / 群里谁<角色>声骸最强」时调用。
text 必须是 "<角色名>声骸排行<页码?>"。

私聊会被拒绝。

Args:
    text: 例: "长离声骸排行"、"椿声骸排行2"。
""",
)
async def send_phantom_rank_card(bot: Bot, ev: Event):
    if not ev.group_id:
        return await bot.send("请在群聊中使用")

    char = ev.regex_dict.get("char")
    pages = normalize_rank_page(ev.regex_dict.get("pages"))

    res = None
    canonical_cmd = None
    if char:
        res = resolve_char(char)
        if not res.ok:
            return await bot.send(res.fail_msg())
        char = res.matched
        from ..wutheringwaves_config import PREFIX
        canonical_cmd = f"{PREFIX}{char}声骸排行"

    from ..utils.custom_weight import prepare_plan, using
    from ..utils.resource.constant import SPECIAL_CHAR

    cid = char_name_to_char_id(char) if char else None
    plan = await prepare_plan(bot, ev, SPECIAL_CHAR.get(cid, [cid]), rank=True) if cid else None
    with using(plan):
        im = await draw_phantom_rank_img(bot, ev, char, pages)

    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        await bot.send(res.with_tip(im, canonical_cmd) if res else im, at_sender)
    elif isinstance(im, bytes):
        await bot.send(res.wrap(im, canonical_cmd) if res else im)


@sv_waves_rank_all_list.on_regex(
    rf"^(?P<char>{PATTERN})(?:总排行|总排行榜|总排名|zph|zpm)\s*(?P<pages>\d+)?\s*(?P<modal>\S+)?$",
    block=True,
    to_ai="""查询全体某角色的排行（伤害或评分，跨群）。

当用户问「<角色>总排行 / 全体<角色>最强」时调用。
text 是 "<角色名>总排行<页码?>"，页码 1-50（默认 1）。名字中含「评分」/「练度」走评分模式。

Args:
    text: 例: "长离总排行1" / "椿评分总排行" / "忌炎总排行3"。
""",
)
async def send_all_rank_card(bot: Bot, ev: Event):
    char = ev.regex_dict.get("char")
    pages = normalize_rank_page(ev.regex_dict.get("pages"))

    rank_type = "伤害"
    if "综合" in char:
        rank_type = "综合评分"
    elif "评分" in char or "练度" in char:
        rank_type = "评分"
    char = char.replace("综合评分", "").replace("综合", "").replace("伤害", "").replace("评分", "").replace("练度", "")

    res = None
    canonical_cmd = None
    if char:
        res = resolve_char(char)
        if not res.ok:
            return await bot.send(res.fail_msg())
        char = res.matched
        from ..wutheringwaves_config import PREFIX
        if rank_type == "评分":
            canonical_cmd = f"{PREFIX}{char}评分总排行"
        elif rank_type == "综合评分":
            canonical_cmd = f"{PREFIX}{char}综合评分总排行"
        else:
            canonical_cmd = f"{PREFIX}{char}总排行"

    modal = ""
    modal_text = ev.regex_dict.get("modal")
    if modal_text and char:
        cid = char_name_to_char_id(char)
        if cid:
            modal = get_modal_key_by_name(int(cid), modal_text)
    im = await draw_all_rank_card(bot, ev, char, rank_type, pages, modal)

    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        await bot.send(res.with_tip(im, canonical_cmd) if res else im, at_sender)
    elif isinstance(im, bytes):
        await bot.send(res.wrap(im, canonical_cmd) if res else im)


@sv_waves_rank_total_list.on_regex(
    r"^(练度总排行|练度总排行榜|练度总排名|ldzph|ldzpm)(?P<pages>\d+)?$",
    block=True,
    to_ai="""查询全体练度总排行（账号综合练度评分跨群）。

当用户问「练度总排行 / 全体练度最强」时调用。
text 是 "练度总排行<页码?>"，页码 1-50。

Args:
    text: 例: "练度总排行1" / "ldzph2"。
""",
)
async def send_total_rank_card(bot: Bot, ev: Event):
    pages = normalize_rank_page(ev.regex_dict.get("pages"))

    im = await draw_total_rank(bot, ev, pages)
    await bot.send(im)


@sv_waves_phantom_total_rank.on_regex(
    rf"^(?P<char>{PATTERN})(?:声骸总排行|声骸总榜|shzph|shzpm)\s*(?P<pages>\d+)?$",
    block=True,
    to_ai="""查询全体某角色的单声骸分数排行（跨群）。

当用户问「<角色>声骸总排行 / 全体谁<角色>声骸最强」时调用。
text 是 "<角色名>声骸总排行<页码?>"，页码 1-50（默认 1）。

Args:
    text: 例: "卡提希娅声骸总排行" / "长离声骸总排行1" / "椿shzph2"。
""",
)
async def send_phantom_total_rank_card(bot: Bot, ev: Event):
    char = ev.regex_dict.get("char")
    pages = normalize_rank_page(ev.regex_dict.get("pages"))

    res = None
    canonical_cmd = None
    if char:
        res = resolve_char(char)
        if not res.ok:
            return await bot.send(res.fail_msg())
        char = res.matched
        from ..wutheringwaves_config import PREFIX
        canonical_cmd = f"{PREFIX}{char}声骸总排行"

    im = await draw_phantom_total_rank(bot, ev, char, pages)

    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        await bot.send(res.with_tip(im, canonical_cmd) if res else im, at_sender)
    elif isinstance(im, bytes):
        await bot.send(res.wrap(im, canonical_cmd) if res else im)


_SEND_RANK_LIST_CARD_KEYWORDS = ("练度排行", "群练度排行", "练度群排行", "练度群排行榜", "练度排名", "群练度排名", "练度群排名", "ldph", "ldpm")


@sv_waves_rank_local_list.on_command(
    _SEND_RANK_LIST_CARD_KEYWORDS,
    block=True,
    to_ai="""查询本群练度排行（按账号综合练度评分），仅群聊可用。

当用户在群里问「群里谁练度最高 / 练度排行」时调用。
text 可附评级筛选 a / s / ss，并可在末尾加页码，留空看第1页全部。

私聊会被拒绝。

Args:
    text: 例: "s"、"ss2"、"3"。
""",
)
async def send_rank_list_card(bot: Bot, ev: Event):
    use_longest_keyword(ev, _SEND_RANK_LIST_CARD_KEYWORDS)
    if not ev.group_id:
        return await bot.send("请在群聊中使用")

    from ..utils.custom_weight import prepare_plan, using

    plan = await prepare_plan(bot, ev, rank=True)
    with using(plan):
        im = await draw_rank_list(bot, ev)
    await bot.send(im)
