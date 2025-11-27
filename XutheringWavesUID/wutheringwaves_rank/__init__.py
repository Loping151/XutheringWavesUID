import re

from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.sv import SV

from .darw_rank_card import draw_rank_img
from .draw_all_rank_card import draw_all_rank_card
from .draw_total_rank_card import draw_total_rank
from ..utils.char_info_utils import PATTERN

sv_waves_rank_list = SV("ww角色排行")
sv_waves_rank_all_list = SV("ww角色总排行", priority=1)
sv_waves_rank_total_list = SV("ww练度总排行", priority=0)


@sv_waves_rank_list.on_regex(rf"^(?P<char>{PATTERN})(?:排行|排名)$", block=True)
async def send_rank_card(bot: Bot, ev: Event):
    if not ev.group_id:
        return await bot.send("请在群聊中使用")
    
    char = ev.regex_dict.get("char")

    rank_type = "伤害"
    if "评分" in char:
        rank_type = "评分"
    
    char = char.replace("伤害", "").replace("评分", "").replace("本群", "").replace("群", "")

    im = await draw_rank_img(bot, ev, char, rank_type)

    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        await bot.send(im, at_sender)
    elif isinstance(im, bytes):
        await bot.send(im)


@sv_waves_rank_all_list.on_regex(
    rf"^(?P<char>{PATTERN})(?:总排行|总排名)(?P<pages>\d+)?$", block=True
)
async def send_all_rank_card(bot: Bot, ev: Event):
    
    char = ev.regex_dict.get("char")
    pages = ev.regex_dict.get("pages")

    if pages:
        pages = int(pages)
    else:
        pages = 1

    if pages > 5:
        pages = 5
    elif pages < 1:
        pages = 1

    rank_type = "伤害"
    if "评分" in char:
        rank_type = "评分"
    char = char.replace("伤害", "").replace("评分", "")

    im = await draw_all_rank_card(bot, ev, char, rank_type, pages)

    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        await bot.send(im, at_sender)
    elif isinstance(im, bytes):
        await bot.send(im)


@sv_waves_rank_total_list.on_command(("练度总排行", "练度总排名"), block=True)
async def send_total_rank_card(bot: Bot, ev: Event):

    pages = 1
    im = await draw_total_rank(bot, ev, pages)
    await bot.send(im)
