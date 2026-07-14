"""怪物抗性查询 + 反推适合的输出角色。"""

from typing import Dict, List, Optional

from pydantic_ai import RunContext

from gsuid_core.ai_core.models import ToolContext
from gsuid_core.ai_core.register import ai_tools

from ._cache import ALL_ATTRS, load_chars, load_monster_resist


@ai_tools(category="common", context_tags=["鸣潮"], capability_domain="鸣潮攻略")
async def get_monster_resistance_wuwa(
    ctx: RunContext[ToolContext],
    monster_name: str,
) -> str:
    """查询鸣潮怪物的抗性属性。

    用于回答「云闪之鳞抗什么」「矩阵奇藏抗性」「伤痕怕什么」等。
    数据来自逆境深塔 Element 字段 + 全息矩阵 Tags 字段交叉聚合。
    支持模糊匹配（子串）。

    Args:
        monster_name: 怪物中文名。

    Returns:
        怪物名 + 抗性列表，未查到返回提示。
    """
    table = load_monster_resist()
    if not monster_name:
        return "请提供怪物名"
    matches: List[str] = []
    if monster_name in table:
        matches = [monster_name]
    else:
        for n in table:
            if monster_name in n or n in monster_name:
                matches.append(n)
    if not matches:
        return f"未在本地数据找到怪物「{monster_name}」（数据来源仅含深塔/矩阵收录的敌人）"
    lines = []
    for n in matches[:5]:
        resists = sorted(table[n])
        if resists:
            lines.append(f"- {n}: 抗性 = {', '.join(resists)}")
        else:
            lines.append(f"- {n}: 无标注抗性（可能是无属性 boss 如矩阵奇藏）")
    return "\n".join(lines)


@ai_tools(category="common", context_tags=["鸣潮"], capability_domain="鸣潮攻略")
async def recommend_against_monster_wuwa(
    ctx: RunContext[ToolContext],
    monster_name: str,
    star_filter: Optional[int] = 5,
) -> str:
    """根据怪物抗性推荐适合输出的角色（剔除被抗的属性）。

    用于回答「打云闪之鳞用谁好」「这期矩阵奇点扩张推荐谁」「伤痕怎么打」等。

    Args:
        monster_name: 怪物中文名。
        star_filter: 角色星级筛选，默认 5（只推 5 星）。传 None 则含 4 星。

    Returns:
        被抗性 / 推荐输出属性 / 候选角色按属性分组的列表。
    """
    if not monster_name:
        return "请提供怪物名"
    table = load_monster_resist()
    target = None
    if monster_name in table:
        target = monster_name
    else:
        for n in table:
            if monster_name in n or n in monster_name:
                target = n
                break
    if not target:
        return f"未在本地数据找到怪物「{monster_name}」"
    resists = sorted(table[target])
    safe_attrs = [a for a in ALL_ATTRS if a not in resists]
    chars = load_chars()
    cands = [c for c in chars if c["attr"] in safe_attrs]
    if star_filter is not None:
        cands = [c for c in cands if c["star"] == star_filter]
    if not cands:
        return f"怪物「{target}」抗 {resists}，无可用角色"
    parts = [f"# 打「{target}」推荐"]
    parts.append(f"- 被抗属性: {', '.join(resists) if resists else '无'}")
    parts.append(f"- 推荐输出属性: {', '.join(safe_attrs)}")
    parts.append(f"- 候选角色（{star_filter if star_filter else '不限'}★，共 {len(cands)} 名）:")
    by_attr: Dict[str, List[str]] = {}
    for c in cands:
        by_attr.setdefault(c["attr"], []).append(c["name"])
    for attr in safe_attrs:
        names = by_attr.get(attr)
        if names:
            parts.append(f"  - {attr}: {', '.join(names)}")
    return "\n".join(parts)
