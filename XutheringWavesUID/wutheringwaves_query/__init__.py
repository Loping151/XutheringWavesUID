from typing import Any, List

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from ..utils.button import WavesButton
from .draw_char_hold_rate import get_char_hold_rate_img
from .draw_matrix_appear_rate import draw_matrix_appear_rate
from .draw_slash_appear_rate import draw_slash_use_rate
from .draw_tower_appear_rate import draw_tower_use_rate
from ..utils.util import use_longest_keyword
from ..utils.name_convert import is_valid_char_name
from ..utils.char_info_utils import PATTERN

sv_char_hold_rate = SV("waves角色持有率")
sv_tower_appear_rate = SV("waves深塔出场率", priority=1)
sv_slash_appear_rate = SV("waves冥想出场率", priority=1)
sv_matrix_appear_rate = SV("waves矩阵出场率", priority=1)


# 角色持有率指令
_HANDLE_CHAR_HOLD_RATE_KEYWORDS = (
    "角色持有率",
    "角色持有率列表",
    "持有率",
    "群角色持有率",
    "群角色持有率列表",
    "群持有率",
    "本群持有率",
    "总持有率",
    "全服持有率",
    "查看持有率",
    "持有度",
)


@sv_char_hold_rate.on_command(
    _HANDLE_CHAR_HOLD_RATE_KEYWORDS,
    block=True,
    to_ai="""查询鸣潮角色持有率统计图。

当用户问「哪些角色冷门 / 谁持有率最高 / UP 池谁多 / 群里大家都抽了谁」时调用。
命令字带 "群" 前缀则限本群范围，否则全局；text 可附 "up" / "all" / "4" / "5" 进一步筛选。

Args:
    text: 可选 "up" (UP池) / "all" (全角色) / "4" / "5" (星级)，留空默认全角色。
""",
)
async def handle_char_hold_rate(bot: Bot, ev: Event):
    use_longest_keyword(ev, _HANDLE_CHAR_HOLD_RATE_KEYWORDS)
    await _send_char_hold_rate(bot, ev, "群" in ev.command)


@sv_char_hold_rate.on_regex(rf"^(?P<char>{PATTERN}?)(?P<group>群)?持有率$")
async def handle_one_char_hold_rate(bot: Bot, ev: Event):
    if is_valid_char_name(ev.regex_dict.get("char") or ""):
        await _send_char_hold_rate(bot, ev, bool(ev.regex_dict.get("group")))


async def _send_char_hold_rate(bot: Bot, ev: Event, in_group: bool):
    if in_group:
        if not ev.group_id:
            return await bot.send("请在群聊中使用")
        img = await get_char_hold_rate_img(ev, ev.group_id)
    else:
        img = await get_char_hold_rate_img(ev)
    buttons: List[Any] = [
        WavesButton("UP持有率", "角色持有率UP"),
        WavesButton("持有率", "角色持有率"),
        WavesButton("持有率4星", "角色持有率4"),
        WavesButton("持有率5星", "角色持有率5"),
        WavesButton("群持有率", "群角色持有率"),
    ]
    await bot.send_option(img, buttons)


# 深塔出场率指令
_HANDLE_TOWER_APPEAR_RATE_KEYWORDS = (
    "深塔使用率",
    "深塔出场率",
    "深塔出场率列表",
    "出场率",
)


@sv_tower_appear_rate.on_command(
    _HANDLE_TOWER_APPEAR_RATE_KEYWORDS,
    block=True,
    to_ai="""查询本期逆境深塔角色使用率/出场率统计图。

当用户问「这期深塔谁用得最多 / 深塔出场率 / 哪些角色打深塔好用」时调用。
text 可指定深塔的具体区域（左/右/中）筛选。

Args:
    text: 可选 "左" / "右" / "中"，分别看左4区域/右4区域/中2区域出场率。留空看总出场率。
""",
)
async def handle_tower_appear_rate(bot: Bot, ev: Event):
    use_longest_keyword(ev, _HANDLE_TOWER_APPEAR_RATE_KEYWORDS)
    img = await draw_tower_use_rate(ev)
    buttons: List[Any] = [
        WavesButton("深塔出场率", "深塔使用率"),
        WavesButton("左4出场率", "深塔出场率左"),
        WavesButton("右4出场率", "深塔出场率右"),
        WavesButton("中2出场率", "深塔出场率中"),
    ]
    await bot.send_option(img, buttons)


# 冥想出场率指令
_HANDLE_SLASH_APPEAR_RATE_KEYWORDS = (
    "无尽总使用率",
    "无尽总出场率",
    "无尽总出场率列表",
    "无尽使用率",
    "无尽出场率",
    "无尽出场率列表",
    "冥海总使用率",
    "冥海总出场率",
    "冥海总出场率列表",
    "冥海使用率",
    "冥海出场率",
    "冥海出场率列表",
    "冥歌海墟总使用率",
    "冥歌海墟总出场率",
    "冥歌海墟总出场率列表",
    "冥歌海墟使用率",
    "冥歌海墟出场率",
    "冥歌海墟出场率列表",
)


@sv_slash_appear_rate.on_command(
    _HANDLE_SLASH_APPEAR_RATE_KEYWORDS,
    block=True,
    to_ai="""查询本期冥歌海墟（海墟/无尽）角色使用率/出场率统计图。

当用户问「这期海墟谁用得多 / 无尽出场率 / 冥海最强角色」时调用。

Args:
    text: 无需参数，留空即可。
""",
)
async def handle_slash_appear_rate(bot: Bot, ev: Event):
    use_longest_keyword(ev, _HANDLE_SLASH_APPEAR_RATE_KEYWORDS)
    img = await draw_slash_use_rate(ev)
    buttons: List[Any] = [
        WavesButton("总出场率", "冥海出场率"),
        WavesButton("总使用率", "冥海总使用率"),
        WavesButton("上半出场率", "冥海出场率上半"),
        WavesButton("下半出场率", "冥海出场率下半"),
    ]
    await bot.send_option(img, buttons)


# 矩阵出场率指令
@sv_matrix_appear_rate.on_command(
    (
        "矩阵出场率",
        "矩阵热门队",
        "矩阵热门配队",
        "矩阵高分队",
        "矩阵高分配队",
        "矩阵配队",
    ),
    block=True,
    to_ai="""查询本期矩阵 (奇点扩张) 队伍出场率统计图。

当用户问「矩阵谁用得多 / 矩阵热门队 / 矩阵高分队 / 矩阵配队推荐」时调用。
可选附带一个角色名/别名，只查含该角色的队伍。

Args:
    text: 可选角色名/别名（严格匹配，不模糊）。留空看全局热门/高分队。

Examples:
    矩阵热门队        → 本期全局热门 + 高分队
    矩阵高分队 椿     → 仅含「椿」的热门 + 高分队
""",
)
async def handle_matrix_appear_rate(bot: Bot, ev: Event):
    img = await draw_matrix_appear_rate(ev)
    await bot.send(img)
