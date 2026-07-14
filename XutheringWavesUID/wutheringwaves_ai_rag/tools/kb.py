"""XW 自己的 KB 搜索 wrapper。

主 agent 默认只把 `search_knowledge` 当 `buildin` 类工具按相似度阈值动态加载，
实战里命中率不稳定（query 跟工具描述相似度低于阈值就上不了桌）。

这里在 XW 插件里挂一个 `category="self"` 的 KB 搜索工具，保证只要 AI 启用，
主 agent 每次 chat 都能调到，专门用来取 ww_tower_N / ww_slash_N / ww_matrix_N
等鸣潮内容详细 KP。
"""

from pydantic_ai import RunContext

from gsuid_core.logger import logger
from gsuid_core.ai_core.models import ToolContext
from gsuid_core.ai_core.register import ai_tools


@ai_tools(category="common", context_tags=["鸣潮"], capability_domain="鸣潮资料库")
async def search_wuwa_kb(
    ctx: RunContext[ToolContext],
    query: str,
    limit: int = 6,
    score_threshold: float = 0.45,
) -> str:
    """检索鸣潮知识库（XW 插件注册的 KP），用于取「当期深塔/海墟/矩阵详情」、
    「角色资料」、「武器/声骸/合鸣套」、「玩法/命令/帮助」等细节。

    比起内置 `search_knowledge`，本工具会强制限制 `plugin=XutheringWavesUID`
    避免被其它插件知识淹没；并且在 XW 插件层用 `category=self` 注册，保证
    永远在主 agent tool list 里，不会被阈值丢掉。

    Args:
        query: 自然语言查询。例 "鸣潮深塔第N期" / "卡卡罗 角色档案" / "凋亡 武器" /
            "守岸人 攻略" / "签到 命令" 等。
        limit: 最多返回多少条 KP，默认 6。
        score_threshold: 相似度过滤阈值，低于此值的结果丢弃。默认 0.45。

    Returns:
        命中 KP 列表的 str (含 title / content / tags / _score)；没结果时返回提示。
    """
    logger.info(
        f"[鸣潮·知识库搜索] query={query!r} limit={limit} "
        f"score_threshold={score_threshold}"
    )
    try:
        from gsuid_core.ai_core.rag import query_knowledge
    except ImportError:
        return "AI 知识库模块不可用（AI 未启用）"

    plugin_filter = ["XutheringWavesUID"]
    try:
        points = await query_knowledge(
            query=query,
            limit=limit,
            plugin_filter=plugin_filter,
        )
    except Exception as e:
        logger.exception("[鸣潮·知识库搜索] query_knowledge 失败")
        return f"KB 检索失败: {e}"

    items = []
    for p in points:
        if p.payload is None:
            continue
        if p.score < score_threshold:
            continue
        entry = dict(p.payload)
        entry["_score"] = round(p.score, 4)
        items.append(entry)

    logger.info(
        f"[鸣潮·知识库搜索] 命中 {len(items)} 条（raw {len(points)} 条，"
        f"score_threshold={score_threshold}）"
    )
    if not items:
        return (
            f"未在鸣潮知识库找到与 {query!r} 匹配的条目（阈值 {score_threshold}）。"
            "可换个表达再试，或检查 query 是否拼写正确。"
        )
    return str(items)
