from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment

from .guide import get_guide, get_matrix_guide
from .draw_char import draw_char_wiki
from .draw_echo import draw_wiki_echo
from .draw_list import draw_sonata_list, draw_weapon_list
from .draw_tower import draw_slash_challenge_img, draw_tower_challenge_img, draw_matrix_challenge_img
from .draw_weapon import draw_wiki_weapon
from ..utils import name_convert
from ..utils.name_convert import char_name_to_char_id, ensure_data_loaded
from ..utils.fuzzy_match import fuzzy_suggest, fuzzy_suggest_multi
from ..utils.char_info_utils import PATTERN
from ..wutheringwaves_abyss.period import (
    get_tower_period_number,
    get_slash_period_number,
    get_matrix_period_number,
)

sv_waves_guide = SV("鸣潮攻略", priority=10)
sv_waves_tower = SV("waves查询深塔信息", priority=4)
sv_waves_slash_info = SV("waves查询海墟信息", priority=4)
sv_waves_matrix_info = SV("waves查询矩阵信息", priority=4)


_PERIOD_OFFSETS = {
    "下一期": 1, "下期": 1, "下下期": 2,
    "上一期": -1, "上期": -1, "上上期": -2,
}


def resolve_period_offset(period_val: str, current_period: int) -> int:
    """解析期数描述（数字 / 上一期/下期/上上期/下下期 等）为绝对期数。"""
    if not period_val:
        return current_period
    if period_val.isdigit():
        return int(period_val)
    return current_period + _PERIOD_OFFSETS.get(period_val, 0)


@sv_waves_guide.on_regex(
    rf"^(?P<wiki_name>{PATTERN})(?P<wiki_type>共鸣链|共鳴鏈|gml|命座|天赋|天賦|技能|jn|图鉴|圖鑑|专武|武器|專武|wiki|介绍|介紹|回路|操作|机制|機制|jz)$",
    block=True,
    to_ai="""查询鸣潮角色/武器/声骸的 wiki 图（图鉴、共鸣链、技能、机制、专武介绍等）。

当用户问以下场景时调用：
- 「<角色>共鸣链」/「<角色>命座」: 共鸣链详情
- 「<角色>技能」/「<角色>天赋」: 技能描述与倍率
- 「<角色>机制」/「<角色>操作」/「<角色>回路」: 玩法机制说明
- 「<武器>介绍」/「<角色>专武介绍」: 武器详情
- 「<声骸>介绍」: 声骸详情

text 必须是 "<对象名><wiki类型后缀>" 格式（regex 匹配）。例: "长离共鸣链"、"椿技能"、"维里奈机制"、"角介绍"。

Args:
    text: "<对象名><类型后缀>"。类型可选: 共鸣链/命座/技能/天赋/机制/操作/回路/介绍/专武。
""",
)
async def send_waves_wiki(bot: Bot, ev: Event):
    wiki_name = ev.regex_dict.get("wiki_name", "")
    wiki_type = ev.regex_dict.get("wiki_type", "")

    at_sender = True if ev.group_id else False
    if wiki_type in ("共鸣链", "共鳴鏈", "gml", "命座", "天赋", "天賦", "技能", "jn", "回路", "操作", "机制", "機制", "jz"):
        char_name = wiki_name

        if wiki_type in ("技能", "天赋", "天賦", "jn"):
            query_role_type = "技能"
        elif wiki_type in ("共鸣链", "共鳴鏈", "命座", "gml"):
            query_role_type = "共鸣链"
        elif wiki_type in ("回路", "操作", "机制", "機制", "jz"):
            query_role_type = "机制"
        else:
            query_role_type = wiki_type

        char_id = char_name_to_char_id(char_name)
        if char_id:
            img = await draw_char_wiki(char_id, query_role_type)
            if not isinstance(img, str):
                return await bot.send(img)

        ensure_data_loaded()
        suggestions = fuzzy_suggest(char_name, name_convert.char_alias_data, top_n=3)
        for cand_name, _ in suggestions:
            cand_id = char_name_to_char_id(cand_name)
            if not cand_id:
                continue
            cand_img = await draw_char_wiki(cand_id, query_role_type)
            if isinstance(cand_img, str):
                continue
            from ..wutheringwaves_config import PREFIX
            cmd = f"{PREFIX}{cand_name}{query_role_type}"
            msg = f"[鸣潮] 你可能想查询【{cmd}】，已执行该指令"
            return await bot.send([msg, MessageSegment.image(cand_img)], at_sender=at_sender)

        if suggestions:
            names = "、".join(n for n, _ in suggestions)
            msg = f"[鸣潮] 未找到指定角色。\n你可能想找: {names}"
        else:
            msg = "[鸣潮] 未找到指定角色, 请先检查输入是否正确！"
        return await bot.send(msg, at_sender)
    else:
        original_name = wiki_name
        if wiki_type in ("专武", "專武", "武器"):
            wiki_name = wiki_name + "专武"
        img = await draw_wiki_weapon(wiki_name)
        if isinstance(img, str) or not img:
            echo_name = original_name
            await bot.logger.info(f"[鸣潮·百科] 开始获取{echo_name}wiki")
            img = await draw_wiki_echo(echo_name)

        if not (isinstance(img, str) or not img):
            return await bot.send(img)

        ensure_data_loaded()
        suggestions = fuzzy_suggest_multi(
            wiki_name,
            [("武器", name_convert.weapon_alias_data), ("共鸣", name_convert.echo_alias_data)],
            top_n=3,
        )
        for label, cand_name, _ in suggestions:
            if label == "武器":
                cand_img = await draw_wiki_weapon(cand_name)
            else:
                cand_img = await draw_wiki_echo(cand_name)
            if isinstance(cand_img, str) or not cand_img:
                continue
            from ..wutheringwaves_config import PREFIX
            cmd = f"{PREFIX}{cand_name}介绍"
            msg = f"[鸣潮] 你可能想查询【{cmd}】，已执行该指令"
            return await bot.send([msg, MessageSegment.image(cand_img)], at_sender=at_sender)

        if suggestions:
            names = "、".join(n for _, n, _ in suggestions)
            msg = f"[鸣潮] wiki未找到指定内容。\n你可能想找: {names}"
        else:
            msg = "[鸣潮] wiki未找到指定内容, 请先检查输入是否正确！"
        return await bot.send(msg, at_sender)


@sv_waves_guide.on_fullmatch(("dps榜", "Dps榜", "DPS榜"), block=True)
@sv_waves_guide.on_regex(
    rf"^(?P<char>{PATTERN})(?:攻略|gl)$",
    block=True,
    to_ai="""查询某角色的攻略图（社区作者贡献的配装/共鸣链优先级/技能加点/伤害分析等）。

当用户问「<角色>怎么配 / <角色>攻略 / <角色>推荐配装」时调用。
text 必须是 "<角色名>攻略" 格式。例: "长离攻略"、"椿攻略"、"忌炎gl"。

Args:
    text: "<角色名>攻略" 或 "<角色名>gl"。
""",
)
async def send_role_guide_pic(bot: Bot, ev: Event):
    char_name = ev.regex_dict.get("char", "") or "dps"
    if "设置排除" in char_name:
        return
    if char_name in ("矩阵", "矩陣"):
        return await get_matrix_guide(bot, ev)

    await get_guide(bot, ev, char_name)


@sv_waves_guide.on_regex(
    r"^(?P<ver_pre>\d+\.\d+)?(?:矩阵|矩陣)(?P<ver_mid>\d+\.\d+)?(?:攻略|gl)(?P<ver_post>\d+\.\d+)?$",
    block=True,
    to_ai="""查询全息矩阵（终焉矩阵）攻略图（拉格朗日变分主义等攻略组按版本整理的配队/打法）。

当用户问「矩阵攻略 / 矩阵怎么打 / 3.5矩阵攻略」时调用。
不带版本号时发送最新版本；版本号为 X.Y 格式，可写在 "矩阵" 前、"矩阵" 与 "攻略" 之间或 "攻略" 后。

Args:
    text: 例: "矩阵攻略" (最新) / "矩阵3.5攻略" / "矩阵攻略3.5" / "3.5矩阵攻略"。
""",
)
async def send_matrix_guide_pic(bot: Bot, ev: Event):
    version = ev.regex_dict.get("ver_pre") or ev.regex_dict.get("ver_mid") or ev.regex_dict.get("ver_post") or ""
    await get_matrix_guide(bot, ev, version)


@sv_waves_guide.on_regex(
    r"^(?:(?P<type>长刃|迅刀|讯刀|佩枪|臂铠|臂甲|音感仪)(?:武器(?:列表)?|列表|wq(?:lb)?)|武器(?:列表)?|wq(?:lb)?)$",
    block=True,
    to_ai="""查询鸣潮武器一览图，可按武器类型过滤。

当用户问「鸣潮武器列表 / 5星武器 / 音感仪武器」时调用。
text 可选指定武器类型前缀：长刃 / 迅刀 / 佩枪 / 臂铠 / 音感仪 + "武器(列表)" 后缀。

Args:
    text: 例: "武器列表" (全部) / "音感仪武器列表" / "迅刀武器" / "wq"。
""",
)
async def send_weapon_list(bot: Bot, ev: Event):
    weapon_type = ev.regex_dict.get("type", "")
    img = await draw_weapon_list(weapon_type)
    await bot.send(img)


@sv_waves_guide.on_regex(
    r"^(?:(?P<version_pre>\d+\.\d+))?(?:套装|套裝)(列表)?(?:(?P<version_post>\d+\.\d+))?$",
    block=True,
    to_ai="""查询鸣潮全部合鸣套装一览图（含 2/5 件套效果）。

当用户问「套装列表 / 合鸣有哪些 / 3.0新套装」时调用。
text 可附版本号（X.Y 格式）筛选特定版本套装。

Args:
    text: 例: "套装列表" (全部) / "套装列表3.0" / "3.0套装" (筛 3.0 版本)。
""",
)
async def send_sonata_list(bot: Bot, ev: Event):
    # 版本号可以在前面或后面
    version = ev.regex_dict.get("version_pre") or ev.regex_dict.get("version_post") or ""
    await bot.send(await draw_sonata_list(version))


@sv_waves_tower.on_regex(
    r"^(?:第?(?P<period_pre>\d+|下(?:一)?期|下下期|上(?:一)?期|上上期)期?(?:深塔|st)(?:信息)?|(?:深塔|st)(?:(?:信息(?:第)?|第)(?P<period>\d+|下(?:一)?期|下下期|上(?:一)?期|上上期)?|(?P<period_force>\d+|下(?:一)?期|下下期|上(?:一)?期|上上期))期?)$",
    block=True,
    to_ai="""查询逆境深塔某期的关卡配置图（每层 Buff + 怪物 + 体力消耗）。

当用户问「深塔信息 / 这期深塔 / 第N期深塔 / 上期深塔」时调用。
text 必须含 "深塔" 或 "st" + 期数描述。期数可以是数字、"上一期"/"上期"、"下一期"/"下期"、"上上期"、"下下期"，留空查当期。

Args:
    text: 例: "深塔信息11" / "深塔上期" / "深塔下一期" / "st信息" (当期) / "深塔第10期"。
""",
)
async def send_tower_challenge_info(bot: Bot, ev: Event):
    """查询深塔挑战信息"""
    period_val = ev.regex_dict.get("period", "") or ev.regex_dict.get("period_force", "") or ev.regex_dict.get("period_pre", "")
    target_period = resolve_period_offset(period_val, get_tower_period_number())

    im = await draw_tower_challenge_img(ev, target_period)
    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        await bot.send(im, at_sender=at_sender)
    else:
        await bot.send(im)

@sv_waves_slash_info.on_regex(
    r"^(?:第?(?P<period_pre>\d+|下(?:一)?期|下下期|上(?:一)?期|上上期)期?(?:海墟|冥海|无尽|無盡|hx|wj)(?:信息)?|(?:海墟|冥海|无尽|無盡|hx|wj)(?:(?:信息(?:第)?|第)(?P<period>\d+|下(?:一)?期|下下期|上(?:一)?期|上上期)?|(?P<period_force>\d+|下(?:一)?期|下下期|上(?:一)?期|上上期))期?)$",
    block=True,
    to_ai="""查询冥歌海墟（无尽/冥海）某期的全 Buff 信物列表图。

当用户问「海墟信息 / 这期冥海 buff / 第N期海墟」时调用。
text 须包含 "海墟"/"冥海"/"无尽"/"hx"/"wj" + 期数描述。期数同 深塔信息。

Args:
    text: 例: "海墟信息11" / "冥海上期" / "无尽下期" / "hx信息" (当期)。
""",
)
async def send_slash_challenge_info(bot: Bot, ev: Event):
    """查询海墟挑战信息"""
    period_val = ev.regex_dict.get("period", "") or ev.regex_dict.get("period_force", "") or ev.regex_dict.get("period_pre", "")
    target_period = resolve_period_offset(period_val, get_slash_period_number())

    im = await draw_slash_challenge_img(ev, target_period)
    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        await bot.send(im, at_sender=at_sender)
    else:
        await bot.send(im)


@sv_waves_matrix_info.on_regex(
    r"^(?:第?(?P<period_pre>\d+|下(?:一)?期|下下期|上(?:一)?期|上上期)期?(?:矩阵|矩陣|jz信息|matrix)(?:信息)?|(?:矩阵|矩陣|jz信息|matrix)(?:(?:信息(?:第)?|第)(?P<period>\d+|下(?:一)?期|下下期|上(?:一)?期|上上期)?|(?P<period_force>\d+|下(?:一)?期|下下期|上(?:一)?期|上上期))期?)$",
    block=True,
    to_ai="""查询全息矩阵（终焉矩阵）某期的关卡配置图（稳态协议+奇点扩张，含 Buff、敌人、推荐角色）。

当用户问「矩阵信息 / 这期矩阵打法 / 第N期矩阵」时调用。
text 须含 "矩阵"/"matrix"/"jz信息" + 期数描述。

Args:
    text: 例: "矩阵信息11" / "矩阵上期" / "矩阵下期" / "matrix信息" (当期)。
""",
)
async def send_matrix_challenge_info(bot: Bot, ev: Event):
    """查询矩阵挑战信息"""
    period_val = ev.regex_dict.get("period", "") or ev.regex_dict.get("period_force", "") or ev.regex_dict.get("period_pre", "")
    target_period = resolve_period_offset(period_val, get_matrix_period_number())

    im = await draw_matrix_challenge_img(ev, target_period)
    if isinstance(im, str):
        at_sender = True if ev.group_id else False
        await bot.send(im, at_sender=at_sender)
    else:
        await bot.send(im)
