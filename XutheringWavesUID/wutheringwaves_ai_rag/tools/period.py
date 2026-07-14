"""当期玩法概况 + 日期-期数索引：逆境深塔 / 冥歌海墟 / 全息矩阵。

数据来源:
- tower / slash: JSON 直接给的 `Begin` + `End` (YYYY-MM-DD) 字段
- matrix: JSON 仅 `EndVersion`，没有精确起止日期，**只标注版本号**
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from pydantic_ai import RunContext

from gsuid_core.logger import logger
from gsuid_core.ai_core.models import ToolContext
from gsuid_core.ai_core.register import ai_tools

from ...utils.resource.RESOURCE_PATH import MAP_CHALLENGE_PATH


def _read_challenge(subdir: str) -> List[Tuple[int, Dict]]:
    """读 challenge/<subdir>/N.json，返回 [(期数, json_dict)] 按期数升序。"""
    p = MAP_CHALLENGE_PATH / subdir
    if not p.exists():
        return []
    out: List[Tuple[int, Dict]] = []
    for f in sorted(os.listdir(p)):
        if not f.endswith(".json"):
            continue
        stem = f[:-5]
        if not stem.isdigit():
            continue
        try:
            with open(p / f, "r", encoding="utf-8") as fp:
                d = json.load(fp)
        except Exception:
            continue
        if isinstance(d, dict):
            out.append((int(stem), d))
    return sorted(out, key=lambda x: x[0])


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except (TypeError, ValueError):
            continue
    return None


def _tower_index() -> List[Dict]:
    """[{period, begin, end}]，begin/end 来自 JSON。"""
    return [
        {"period": k, "begin": d.get("Begin", ""), "end": d.get("End", "")}
        for k, d in _read_challenge("tower")
    ]


def _slash_index() -> List[Dict]:
    return [
        {"period": k, "begin": d.get("Begin", ""), "end": d.get("End", "")}
        for k, d in _read_challenge("slash")
    ]


def _matrix_index() -> List[Dict]:
    """matrix 期 JSON 无 Begin/End，只能给 EndVersion + Name。"""
    items = []
    for k, d in _read_challenge("matrix"):
        items.append({
            "period": k,
            "name": d.get("Name") or d.get("SeasonName") or "",
            "end_version": d.get("EndVersion") or "",
            "season_name": d.get("SeasonName") or "",
        })
    return items


@ai_tools(category="common", context_tags=["鸣潮"], capability_domain="鸣潮攻略")
async def get_current_period_wuwa(
    ctx: RunContext[ToolContext],
    mode: str = "all",
) -> str:
    """查询鸣潮当期玩法概况：逆境深塔 / 冥歌海墟 / 全息矩阵。

    用于回答「当期深塔什么样」「现在矩阵推荐谁」「这期海墟 buff」等。
    期数优先来自每期 JSON 的 Begin/End 字段（tower/slash），matrix 无日期字段则走 cycle 推算。
    详细配置建议再调 search_wuwa_kb 拿 ww_tower_N / ww_slash_N / ww_matrix_N 完整 KP。

    Args:
        mode: 可选 tower / slash / matrix / all，默认 all 三个都返回。

    Returns:
        当期期数 + 起止日期（如有）+ 跟进 search_wuwa_kb 查询建议。
    """
    logger.info(f"[鸣潮·AI工具] get_current_period_wuwa 入口 mode={mode!r}")
    from ...wutheringwaves_abyss.period import (
        get_tower_period_number,
        get_slash_period_number,
        get_matrix_period_number,
    )
    today = datetime.now()
    want = (mode or "all").lower()
    lines: List[str] = []
    if want in ("all", "tower"):
        # 优先用 JSON 的 Begin/End 找当前期
        cur = next(
            (
                e for e in _tower_index()
                if _parse_date(e["begin"]) and _parse_date(e["end"])
                and _parse_date(e["begin"]) <= today <= _parse_date(e["end"])
            ),
            None,
        )
        if cur:
            t = cur["period"]
            lines.append(f"## 逆境深塔 第 {t} 期")
            lines.append(f"- 起止：{cur['begin']} ~ {cur['end']}")
        else:
            t = get_tower_period_number()
            lines.append(f"## 逆境深塔 第 {t} 期")
            lines.append("- 起止日期：JSON 未含当期，回退 cycle 推算")
        lines.append(f"- 完整数据: search_wuwa_kb('鸣潮深塔第{t}期') → ww_tower_{t} KP")
    if want in ("all", "slash"):
        if lines:
            lines.append("")
        cur = next(
            (
                e for e in _slash_index()
                if _parse_date(e["begin"]) and _parse_date(e["end"])
                and _parse_date(e["begin"]) <= today <= _parse_date(e["end"])
            ),
            None,
        )
        if cur:
            s = cur["period"]
            lines.append(f"## 冥歌海墟 第 {s} 期")
            lines.append(f"- 起止：{cur['begin']} ~ {cur['end']}")
        else:
            s = get_slash_period_number()
            lines.append(f"## 冥歌海墟 第 {s} 期")
            lines.append("- 起止日期：JSON 未含当期，回退 cycle 推算")
        lines.append(f"- 本期 Buff: search_wuwa_kb('鸣潮海墟第{s}期') → ww_slash_{s}")
    if want in ("all", "matrix"):
        if lines:
            lines.append("")
        m = get_matrix_period_number()
        idx = {e["period"]: e for e in _matrix_index()}
        meta = idx.get(m, {})
        title = meta.get("name") or ""
        end_ver = meta.get("end_version") or ""
        lines.append(f"## 全息矩阵 第 {m} 期" + (f" - {title}" if title else ""))
        if end_ver:
            lines.append(f"- 截止版本：{end_ver}（JSON 不含精确日期，需以游戏公告为准）")
        lines.append("- 玩家口中的「矩阵」一般特指当期奇点扩张关卡")
        lines.append(f"- 完整数据: search_wuwa_kb('鸣潮矩阵第{m}期') → ww_matrix_{m}")
    if not lines:
        result = f"未知 mode='{mode}'，可选: tower / slash / matrix / all"
        logger.warning(f"[鸣潮·AI工具] get_current_period_wuwa 出口 (未知 mode): {result}")
        return result
    result = "\n".join(lines)
    logger.info(
        f"[鸣潮·AI工具] get_current_period_wuwa 出口 mode={mode!r} len={len(result)} 行={len(lines)}"
    )
    return result


def get_tower_index() -> List[Dict]:
    """暴露给 __init__.py 注册 KP 用。"""
    return _tower_index()


def get_slash_index() -> List[Dict]:
    return _slash_index()


def get_matrix_index() -> List[Dict]:
    return _matrix_index()
