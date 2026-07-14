"""目录类工具：角色/武器/声骸筛选 + 套装-声骸反查 + 角色专武查询。"""

from typing import Any, Dict, List, Optional

from pydantic_ai import RunContext

from gsuid_core.ai_core.models import ToolContext
from gsuid_core.ai_core.register import ai_tools

from ._cache import load_chars, load_echoes, load_weapons, load_weapon_alias


@ai_tools(category="common", context_tags=["鸣潮"], capability_domain="鸣潮资料库")
async def filter_chars_wuwa(
    ctx: RunContext[ToolContext],
    attribute: Optional[str] = None,
    weapon_type: Optional[str] = None,
    star: Optional[int] = None,
) -> str:
    """按条件筛选鸣潮角色列表。

    用于回答「5 星湮灭角色」「迅刀角色列表」「4 星冷凝角色」等类似问题。
    不需要用户绑定 UID，纯查 wiki 数据。

    Args:
        attribute: 角色共鸣属性。可选: 冷凝, 热熔, 导电, 气动, 衍射, 湮灭。留空不限。
        weapon_type: 角色武器类型。可选: 长刃, 迅刀, 佩枪, 臂铠, 音感仪。留空不限。
        star: 角色星级，4 或 5。留空不限。

    Returns:
        匹配角色的 Markdown 表格 (ID/名字/星级/属性/武器)。
    """
    chars = load_chars()
    filt = [
        c for c in chars
        if (not attribute or c["attr"] == attribute)
        and (not weapon_type or c["wt"] == weapon_type)
        and (star is None or c["star"] == star)
    ]
    if not filt:
        return f"无匹配角色 (attr={attribute} weapon_type={weapon_type} star={star})"
    parts = [f"匹配 {len(filt)} 名角色:", "| ID | 名字 | 星级 | 属性 | 武器 |", "|---|---|---|---|---|"]
    for c in filt:
        parts.append(f"| {c['cid']} | {c['name']} | {c['star']}★ | {c['attr']} | {c['wt']} |")
    return "\n".join(parts)


@ai_tools(category="common", context_tags=["鸣潮"], capability_domain="鸣潮资料库")
async def filter_weapons_wuwa(
    ctx: RunContext[ToolContext],
    weapon_type: Optional[str] = None,
    star: Optional[int] = None,
) -> str:
    """按条件筛选鸣潮武器列表。

    用于回答「5 星音感仪」「4 星迅刀」「3 星长刃」等。

    Args:
        weapon_type: 武器类型。可选: 长刃, 迅刀, 佩枪, 臂铠, 音感仪。留空不限。
        star: 武器星级，3/4/5。留空不限。

    Returns:
        匹配武器的 Markdown 表格 (ID/名字/星级/类型)。
    """
    weapons = load_weapons()
    filt = [
        w for w in weapons
        if (not weapon_type or w["wt"] == weapon_type)
        and (star is None or w["star"] == star)
    ]
    if not filt:
        return f"无匹配武器 (weapon_type={weapon_type} star={star})"
    parts = [f"匹配 {len(filt)} 件武器:", "| ID | 名字 | 星级 | 类型 |", "|---|---|---|---|"]
    for w in filt:
        parts.append(f"| {w['wid']} | {w['name']} | {w['star']}★ | {w['wt']} |")
    return "\n".join(parts)


@ai_tools(category="common", context_tags=["鸣潮"], capability_domain="鸣潮资料库")
async def filter_echoes_wuwa(
    ctx: RunContext[ToolContext],
    cost: Optional[int] = None,
    sonata_name: Optional[str] = None,
) -> str:
    """按 cost / 所属合鸣套装筛选鸣潮声骸列表。

    用于回答「1 cost 声骸有哪些」「彻空冥雷套有什么声骸」「3 费声骸列表」等。

    Args:
        cost: 声骸 cost 值（intensityCode），常见 1/3/4。留空不限。
        sonata_name: 合鸣套装名（如「彻空冥雷」「凝夜白霜」）。留空不限。

    Returns:
        匹配声骸的 Markdown 表格 (ID/名字/cost/所属套装)。
    """
    echoes = load_echoes()
    filt = []
    for e in echoes:
        if cost is not None and e["cost"] != cost:
            continue
        if sonata_name and not any(sonata_name in g for g in e["groups"]):
            continue
        filt.append(e)
    if not filt:
        return f"无匹配声骸 (cost={cost} sonata={sonata_name})"
    parts = [f"匹配 {len(filt)} 个声骸:", "| ID | 名字 | cost | 所属套装 |", "|---|---|---|---|"]
    for e in filt[:40]:
        parts.append(f"| {e['eid']} | {e['name']} | {e['cost']} | {', '.join(e['groups']) or '-'} |")
    if len(filt) > 40:
        parts.append(f"...（还有 {len(filt) - 40} 条已省略，可缩窄条件再查）")
    return "\n".join(parts)


@ai_tools(category="common", context_tags=["鸣潮"], capability_domain="鸣潮资料库")
async def get_sonata_echoes_wuwa(
    ctx: RunContext[ToolContext],
    sonata_name: str,
) -> str:
    """查询某个合鸣套装包含的全部声骸。

    用于回答「彻空冥雷套装有哪些声骸」「凝夜白霜的成员声骸」等。

    Args:
        sonata_name: 合鸣套装中文名（如「彻空冥雷」「熔山裂谷」「不绝余音」）。

    Returns:
        套装名 + 该套装下声骸的列表 (按 cost 分组)。
    """
    if not sonata_name:
        return "请提供合鸣套装名"
    echoes = load_echoes()
    matched = [e for e in echoes if any(sonata_name in g for g in e["groups"])]
    if not matched:
        return f"未找到合鸣「{sonata_name}」相关声骸"
    by_cost: Dict[Any, List[str]] = {}
    for e in matched:
        by_cost.setdefault(e["cost"], []).append(e["name"])
    parts = [f"# 合鸣「{sonata_name}」包含声骸（共 {len(matched)} 个）"]
    for c in sorted(by_cost.keys(), key=lambda x: (x is None, x)):
        parts.append(f"- cost {c}: {', '.join(by_cost[c])}")
    return "\n".join(parts)


@ai_tools(category="common", context_tags=["鸣潮"], capability_domain="鸣潮资料库")
async def get_char_signature_weapon_wuwa(
    ctx: RunContext[ToolContext],
    char_name: str,
) -> str:
    """查询某角色的专属武器。

    用于回答「长离专武是哪把」「卡提希娅专武叫什么」等。
    数据来自 weapon_alias.json 中显式标注「X专武」「X 专武」的条目。

    Args:
        char_name: 角色中文名。

    Returns:
        角色名 + 对应专武名（如有），未查到给提示。
    """
    if not char_name:
        return "请提供角色名"
    aliases = load_weapon_alias()
    matched: List[str] = []
    for weapon_name, alias_list in aliases.items():
        if not isinstance(alias_list, list):
            continue
        for a in alias_list:
            if not isinstance(a, str):
                continue
            if "专武" in a and char_name in a:
                matched.append(weapon_name)
                break
    if not matched:
        return f"未在 weapon_alias 数据中找到「{char_name}」的专武标注"
    return f"「{char_name}」的专武: {', '.join(matched)}"
