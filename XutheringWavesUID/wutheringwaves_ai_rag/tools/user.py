"""用户绑定 + 个人面板数据查询。

数据源：
- DB: `WavesBind` (`get_uid_list_by_game(game_name=None)` = 鸣潮 uid 列；与战双 pgr_uid 区分)
- 磁盘: `PLAYER_PATH/<uid>/rawData.json` (角色展柜) / `charListData.json` (评分缓存) / `baseInfo.json` (账号总览)
"""

from typing import Any, List, Optional

from pydantic_ai import RunContext

from gsuid_core.logger import logger
from gsuid_core.ai_core.models import ToolContext
from gsuid_core.ai_core.register import ai_tools

from ...utils.database.models import WavesBind
from ...utils.char_info_utils import get_all_role_detail_info
from ...utils.resource.RESOURCE_PATH import PLAYER_PATH
from ._cache import load_char_id_to_name


def _is_master(ev) -> bool:
    return ev is not None and getattr(ev, "user_pm", None) == 0


def _validate_uid(uid) -> bool:
    if uid is None:
        return False
    s = str(uid)
    return s.isdigit() and len(s) == 9


async def _check_uid_belongs(ev, uid: str) -> bool:
    if _is_master(ev):
        return True
    if ev is None:
        return False
    try:
        bound = await WavesBind.get_uid_list_by_game(ev.user_id, ev.bot_id) or []
    except Exception as e:
        logger.warning(f"[鸣潮·AI工具] 归属校验查询失败 user_id={ev.user_id}: {e}")
        return False
    return str(uid) in [str(u) for u in bound]


async def _resolve_user_default_uid(ev) -> Optional[str]:
    if ev is None:
        return None
    try:
        return await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    except Exception as e:
        logger.warning(f"[鸣潮·AI工具] get_uid_by_game 失败: {e}")
        return None


async def _read_player_json(uid, filename: str) -> Optional[Any]:
    if not _validate_uid(uid):
        return None
    from ...utils.player_store import read_player_json
    return await read_player_json(PLAYER_PATH / str(uid) / filename)


def _score_rating(score: float) -> str:
    """与 calculate.py 的 total_grade × 250 阈值一致 (C/B/A/S/SS/SSS)。"""
    if score >= 210:
        return "SSS"
    if score >= 195:
        return "SS"
    if score >= 175:
        return "S"
    if score >= 150:
        return "A"
    if score >= 120:
        return "B"
    return "C"


# ─── get_user_wuwa_uids ───────────────────────────────

@ai_tools(category="common", context_tags=["鸣潮"], capability_domain="鸣潮面板")
async def get_user_wuwa_uids(
    ctx: RunContext[ToolContext],
    target_user_id: Optional[str] = None,
) -> str:
    """查询用户已绑定的全部鸣潮 UID 列表（与战双等其它游戏 UID 区分）。

    用于回答「我绑定了哪些 UID / 我有几个鸣潮号 / 我当前默认 UID 是多少」。
    默认查当前对话用户；管理员/主人路径可传 target_user_id 查别人。

    Args:
        target_user_id: 可选，要查的 user_id（如 QQ 号）。留空则查当前对话发起者。

    Returns:
        绑定的鸣潮 UID 列表 + 默认 UID。未绑定则提示。
    """
    logger.info(f"[鸣潮·AI工具] get_user_wuwa_uids 入口 target_user_id={target_user_id!r}")
    ev = ctx.deps.ev if ctx and ctx.deps else None
    if ev is None:
        return "无法获取当前对话 Event"
    if target_user_id and str(target_user_id) != str(ev.user_id) and not _is_master(ev):
        return "仅主人可查询他人绑定，普通用户请留空 target_user_id 查自己"
    uid_q = target_user_id or ev.user_id
    try:
        uid_list = await WavesBind.get_uid_list_by_game(uid_q, ev.bot_id)
    except Exception as e:
        return f"查询 WavesBind 失败: {e}"
    if not uid_list:
        return f"user_id={uid_q} 未绑定任何鸣潮 UID（提示用户用 `绑定<UID>` 命令绑定）"
    default_uid = uid_list[0] if uid_list else None
    parts = [f"user_id={uid_q} 已绑定 {len(uid_list)} 个鸣潮 UID:"]
    for u in uid_list:
        flag = "（默认）" if u == default_uid else ""
        parts.append(f"- {u}{flag}")
    return "\n".join(parts)


# ─── get_user_wuwa_char_list ──────────────────────────

@ai_tools(category="common", context_tags=["鸣潮"], capability_domain="鸣潮面板")
async def get_user_wuwa_char_list(
    ctx: RunContext[ToolContext],
    uid: Optional[str] = None,
    target_user_id: Optional[str] = None,
) -> str:
    """查询某 UID 的鸣潮角色列表（已在展柜或绑定 cookie 拉取过），含等级/共鸣链/武器/谐振。

    数据来自 PLAYER_PATH/<uid>/rawData.json（XW 缓存）。
    用于回答「我有哪些角色 / 我练到哪几个了 / 列出我的角色」。

    Args:
        uid: 鸣潮 9 位 UID。留空则用当前对话用户的默认绑定 UID。
        target_user_id: 可选，目标用户 user_id（QQ 号）。和 uid 二选一即可，uid 优先。

    Returns:
        角色 Markdown 表格 (名字 / 等级 / 共鸣链 / 武器 + 谐振)。
    """
    logger.info(
        f"[鸣潮·AI工具] get_user_wuwa_char_list 入口 uid={uid!r} target_user_id={target_user_id!r}"
    )
    ev = ctx.deps.ev if ctx and ctx.deps else None
    target_uid = uid
    if target_uid:
        if not _validate_uid(target_uid):
            return "uid 格式错误，须为 9 位数字"
        target_uid = str(target_uid)
        if ev is not None and not await _check_uid_belongs(ev, target_uid):
            return "uid 不属于当前用户，仅主人可查他人 UID"
    else:
        if target_user_id and ev is not None:
            if str(target_user_id) != str(ev.user_id) and not _is_master(ev):
                return "仅主人可按他人 user_id 查询 UID"
            try:
                target_uid = await WavesBind.get_uid_by_game(target_user_id, ev.bot_id)
            except Exception as e:
                return f"按 user_id 查 UID 失败: {e}"
        elif ev is not None:
            target_uid = await _resolve_user_default_uid(ev)
    if not target_uid:
        return "未提供 UID 也找不到默认绑定 UID；告知用户先 `绑定<UID>`"

    role_map = await get_all_role_detail_info(target_uid)
    if not role_map:
        return (
            f"UID {target_uid} 暂无角色面板缓存（rawData.json 不存在或为空）。\n"
            "提示用户先发 `刷新面板` 命令从库街区拉取数据。"
        )

    parts = [f"UID {target_uid} 共 {len(role_map)} 个角色:"]
    parts.append("| 角色 | 等级 | 共鸣链 | 武器 | 谐振 |")
    parts.append("|---|---|---|---|---|")
    items = sorted(role_map.values(), key=lambda r: r.level, reverse=True)
    for r in items:
        chain_num = r.get_chain_num()
        weapon = r.weaponData.weapon.weaponName if r.weaponData and r.weaponData.weapon else "-"
        reson = r.weaponData.resonLevel if r.weaponData else None
        reson_str = f"{reson}阶" if reson else "-"
        parts.append(f"| {r.role.roleName} | Lv{r.level} | {chain_num}链 | {weapon} | {reson_str} |")
    return "\n".join(parts)


# ─── get_user_wuwa_char_detail ────────────────────────

@ai_tools(category="common", context_tags=["鸣潮"], capability_domain="鸣潮面板")
async def get_user_wuwa_char_detail(
    ctx: RunContext[ToolContext],
    char_name: str,
    uid: Optional[str] = None,
) -> str:
    """查询某 UID 某角色的完整面板详情（等级 / 共鸣链 / 武器谐振 / 技能等级 / 装备的 5 个声骸）。

    鸣潮（Wuthering Waves）游戏内的角色面板。用户说「<角色>面板 / <角色>练度 / 看看我的
    <角色> / 我的<角色>几链」时调用；char_name 直接填用户原话里的角色名（如长离、玄翎秧秧、
    卡提希娅），别名/俗称均可，后端会模糊匹配。

    Args:
        char_name: 角色中文名。模糊匹配。
        uid: 鸣潮 9 位 UID。留空则用当前对话用户的默认绑定 UID。

    Returns:
        Markdown 格式的角色完整面板详情。
    """
    logger.info(
        f"[鸣潮·AI工具] get_user_wuwa_char_detail 入口 char_name={char_name!r} uid={uid!r}"
    )
    if not char_name:
        return "请提供 char_name 角色名"
    ev = ctx.deps.ev if ctx and ctx.deps else None
    target_uid = uid
    if target_uid:
        if not _validate_uid(target_uid):
            return "uid 格式错误，须为 9 位数字"
        target_uid = str(target_uid)
        if ev is not None and not await _check_uid_belongs(ev, target_uid):
            return "uid 不属于当前用户，仅主人可查他人 UID"
    elif ev is not None:
        target_uid = await _resolve_user_default_uid(ev)
    if not target_uid:
        return "未提供 UID 也找不到默认绑定 UID"

    role_map = await get_all_role_detail_info(target_uid)
    if not role_map:
        return f"UID {target_uid} 暂无角色面板数据，提示用户先 `刷新面板`"

    target = role_map.get(char_name)
    if not target:
        for name, r in role_map.items():
            if char_name in name or name in char_name:
                target = r
                break
    if not target:
        return f"UID {target_uid} 未练习/展示「{char_name}」（可能未拥有或未上展柜）"

    lines = [
        f"# {target.role.roleName} (UID {target_uid})",
        f"- 等级: Lv{target.level} / 突破 {target.role.breach or '?'}",
        f"- 共鸣链: {target.get_chain_num()} / 6 链 ({target.get_chain_name()})",
        f"- 总技能等级: {target.role.totalSkillLevel or '?'}",
    ]
    if target.weaponData and target.weaponData.weapon:
        w = target.weaponData.weapon
        lines.append(
            f"- 武器: {w.weaponName} (Lv{target.weaponData.level}, "
            f"突破{target.weaponData.breach or '?'}, {target.weaponData.resonLevel or '?'}阶)"
        )
    skill_parts = []
    for skill_data in target.get_skill_list():
        sk_type = skill_data.skill.type
        skill_parts.append(f"{sk_type}{skill_data.level}")
    if skill_parts:
        lines.append(f"- 技能等级: {' / '.join(skill_parts)}")
    chains_unlocked = [c.name for c in target.chainList if c.unlocked and c.name]
    if chains_unlocked:
        lines.append(f"- 已解锁链: {', '.join(chains_unlocked)}")
    if target.phantomData and target.phantomData.equipPhantomList:
        lines.append("\n## 装备声骸")
        for p in target.phantomData.equipPhantomList:
            if not p:
                continue
            ph_name = getattr(p.phantomProp, "name", "?") if p.phantomProp else "?"
            cost = getattr(p.phantomProp, "cost", "?") if p.phantomProp else "?"
            quality = getattr(p, "quality", "?")
            lvl = getattr(p, "level", "?")
            lines.append(f"- {ph_name} cost{cost} {quality}★ Lv{lvl}")
    return "\n".join(lines)


# ─── get_user_wuwa_char_scores ────────────────────────

@ai_tools(category="common", context_tags=["鸣潮"], capability_domain="鸣潮面板")
async def get_user_wuwa_char_scores(
    ctx: RunContext[ToolContext],
    uid: Optional[str] = None,
    top_n: int = 20,
) -> str:
    """查询某 UID 的练度评分排行（来自 charListData.json，XW 评分缓存）。

    数据来源 `PLAYER_PATH/<uid>/charListData.json`，格式 `{roleId: score}`。
    用户练度统计图 `练度统计` 命令计算后会落盘到这里，AI 用同一份数据。
    用于回答「我练度最高的角色是谁 / 我前 N 强角色 / 我的鸣潮练度统计」。

    Args:
        uid: 鸣潮 9 位 UID。留空则用当前对话用户的默认绑定 UID。
        top_n: 返回前 N 个角色，默认 20。

    Returns:
        Markdown 表格 (排名 / 角色名 / 评分 / 评级)。
    """
    logger.info(
        f"[鸣潮·AI工具] get_user_wuwa_char_scores 入口 uid={uid!r} top_n={top_n}"
    )
    ev = ctx.deps.ev if ctx and ctx.deps else None
    target_uid = uid
    if target_uid:
        if not _validate_uid(target_uid):
            return "uid 格式错误，须为 9 位数字"
        target_uid = str(target_uid)
        if ev is not None and not await _check_uid_belongs(ev, target_uid):
            return "uid 不属于当前用户，仅主人可查他人 UID"
    elif ev is not None:
        target_uid = await _resolve_user_default_uid(ev)
    if not target_uid:
        return "未提供 UID 也找不到默认绑定 UID"

    data = await _read_player_json(target_uid, "charListData.json")
    if not isinstance(data, dict) or not data:
        return (
            f"UID {target_uid} 暂无练度评分缓存（charListData.json 不存在）。\n"
            "提示用户先发 `练度统计` 命令生成评分。"
        )

    id2name = load_char_id_to_name()
    ranked: List = []
    for cid_str, score in data.items():
        if not isinstance(score, (int, float)):
            continue
        ranked.append((cid_str, id2name.get(str(cid_str), f"未知({cid_str})"), float(score)))
    ranked.sort(key=lambda x: x[2], reverse=True)
    if not ranked:
        return f"UID {target_uid} 评分数据为空"

    parts = [f"UID {target_uid} 练度评分 Top {min(top_n, len(ranked))}（总 {len(ranked)} 个角色）:"]
    parts.append("| # | 角色 | 评分 | 评级 |")
    parts.append("|---|---|---|---|")
    for i, (_, name, score) in enumerate(ranked[:top_n], 1):
        parts.append(f"| {i} | {name} | {score:.2f} | {_score_rating(score)} |")
    return "\n".join(parts)


# ─── get_user_wuwa_baseinfo ───────────────────────────

@ai_tools(category="common", context_tags=["鸣潮"], capability_domain="鸣潮面板")
async def get_user_wuwa_baseinfo(
    ctx: RunContext[ToolContext],
    uid: Optional[str] = None,
) -> str:
    """查询某 UID 的鸣潮账号基本信息（漂泊者等级 / 世界等级 / 活跃天数 / 成就 / 角色数 / 奇藏箱数 / 周本进度等）。

    数据源 `PLAYER_PATH/<uid>/baseInfo.json`，由 `卡片` 命令拉取后落盘。
    用于回答「我鸣潮账号怎样 / 我等级多少 / 多少天了 / 多少成就」。

    Args:
        uid: 鸣潮 9 位 UID。留空则用当前对话用户的默认绑定 UID。

    Returns:
        Markdown 文本，含账号概览各项数值。
    """
    logger.info(f"[鸣潮·AI工具] get_user_wuwa_baseinfo 入口 uid={uid!r}")
    ev = ctx.deps.ev if ctx and ctx.deps else None
    target_uid = uid
    if target_uid:
        if not _validate_uid(target_uid):
            return "uid 格式错误，须为 9 位数字"
        target_uid = str(target_uid)
        if ev is not None and not await _check_uid_belongs(ev, target_uid):
            return "uid 不属于当前用户，仅主人可查他人 UID"
    elif ev is not None:
        target_uid = await _resolve_user_default_uid(ev)
    if not target_uid:
        return "未提供 UID 也找不到默认绑定 UID"

    data = await _read_player_json(target_uid, "baseInfo.json")
    if not isinstance(data, dict) or not data:
        return (
            f"UID {target_uid} 暂无 baseInfo 缓存。\n"
            "提示用户先发 `卡片` 或 `刷新面板` 命令拉取账号信息。"
        )

    lines = [f"# UID {target_uid} 账号概览"]
    name = data.get("name")
    if name:
        lines.append(f"- 玩家名: {name}")
    if data.get("level"):
        wl = data.get("worldLevel")
        lines.append(f"- 漂泊者等级: Lv{data['level']}" + (f" / 世界等级 {wl}" if wl else ""))
    if data.get("activeDays") is not None:
        lines.append(f"- 活跃天数: {data['activeDays']}")
    if data.get("roleNum") is not None:
        lines.append(f"- 已获得角色数: {data['roleNum']}")
    if data.get("achievementCount") is not None:
        ach_star = data.get("achievementStar", "?")
        lines.append(f"- 成就: {data['achievementCount']} 个 / {ach_star} ★")
    if data.get("bigCount") is not None or data.get("smallCount") is not None:
        lines.append(
            f"- 宝箱: 大 {data.get('bigCount', '?')} / 小 {data.get('smallCount', '?')}"
        )
    if data.get("storeEnergy") is not None and data.get("storeEnergyLimit") is not None:
        lines.append(f"- 结晶波片: {data['storeEnergy']} / {data['storeEnergyLimit']}")
    if data.get("weeklyInstCount") is not None and data.get("weeklyInstCountLimit") is not None:
        lines.append(
            f"- 周本: {data['weeklyInstCount']} / {data['weeklyInstCountLimit']}"
        )
    boxes = data.get("boxList") or []
    if isinstance(boxes, list) and boxes:
        lines.append("\n## 奇藏箱收集")
        for b in boxes:
            if isinstance(b, dict) and b.get("boxName"):
                lines.append(f"- {b['boxName']}: {b.get('num', '?')}")
    return "\n".join(lines)
