from typing import Any
from dataclasses import dataclass
from collections.abc import Mapping, Sequence, MutableMapping

from gsuid_core.logger import logger

GACHA_HARD_PITY = 80
GACHA_PITY_RESET_FIELD = "historyGapBefore"


class GachaMergeError(ValueError):
    """抽卡数据无法安全合并。"""


@dataclass(frozen=True)
class GachaPityViolation:
    pool: str
    kind: str
    pity: int
    time: str = ""
    name: str = ""


def _get_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def has_history_gap_before(item: Any) -> bool:
    return bool(_get_value(item, GACHA_PITY_RESET_FIELD, False))


def mark_history_gap_before(item: Any) -> None:
    """标记该条记录之前存在未知历史，统计时从该条重新计数。"""
    if isinstance(item, MutableMapping):
        item[GACHA_PITY_RESET_FIELD] = True
    else:
        setattr(item, GACHA_PITY_RESET_FIELD, True)


def clear_history_gap_before(item: Any) -> None:
    """移除误带到另一条同内容重复记录上的断档标记。"""
    if isinstance(item, MutableMapping):
        item.pop(GACHA_PITY_RESET_FIELD, None)
    elif hasattr(item, GACHA_PITY_RESET_FIELD):
        delattr(item, GACHA_PITY_RESET_FIELD)


def validate_draw_total(value: Any, source: str, pool: str, name: str) -> int:
    """外部源自报抽数超过硬保底时按硬保底截断，不阻断合并。"""
    if isinstance(value, bool):
        raise GachaMergeError(f"{source}卡池[{pool}]五星[{name}]的抽数格式异常")
    try:
        draw_total = int(value)
    except (TypeError, ValueError) as exc:
        raise GachaMergeError(f"{source}卡池[{pool}]五星[{name}]的抽数格式异常") from exc
    if draw_total < 1:
        raise GachaMergeError(f"{source}卡池[{pool}]五星[{name}]抽数为{draw_total}，不足1抽")
    if draw_total > GACHA_HARD_PITY:
        logger.warning(
            f"[鸣潮·抽卡合并] {source}卡池[{pool}]五星[{name}]抽数{draw_total}"
            f"超过硬保底，按{GACHA_HARD_PITY}抽计入"
        )
        return GACHA_HARD_PITY
    return draw_total


def find_gacha_pity_violations(
    pools: Mapping[str, Sequence[Any]],
) -> list[GachaPityViolation]:
    """校验按新到旧保存的卡池记录，不把 UP 平均抽数误当成单金 pity。"""
    violations: list[GachaPityViolation] = []
    for pool, logs in pools.items():
        pity = 0
        for item in reversed(logs):
            if has_history_gap_before(item):
                if pity >= GACHA_HARD_PITY:
                    violations.append(
                        GachaPityViolation(
                            pool=str(pool),
                            kind="remain",
                            pity=pity,
                            time=str(_get_value(item, "time", "")),
                        )
                    )
                pity = 0

            pity += 1
            if _get_value(item, "qualityLevel") != 5:
                continue

            if pity > GACHA_HARD_PITY:
                violations.append(
                    GachaPityViolation(
                        pool=str(pool),
                        kind="five_star",
                        pity=pity,
                        time=str(_get_value(item, "time", "")),
                        name=str(_get_value(item, "name", "")),
                    )
                )
            pity = 0

        # 80 抽硬保底下，当前连续垫抽最多只能到 79。
        if pity >= GACHA_HARD_PITY:
            last = logs[0] if logs else {}
            violations.append(
                GachaPityViolation(
                    pool=str(pool),
                    kind="remain",
                    pity=pity,
                    time=str(_get_value(last, "time", "")),
                )
            )
    return violations


def _violation_detail(violation: GachaPityViolation) -> str:
    if violation.kind == "remain":
        return f"当前连续垫抽为{violation.pity}"
    return f"五星[{violation.name}]被计算为{violation.pity}抽"


def assert_valid_gacha_pity(pools: Mapping[str, Sequence[Any]]) -> None:
    violations = find_gacha_pity_violations(pools)
    if not violations:
        return
    first = violations[0]
    raise GachaMergeError(
        f"卡池[{first.pool}]{_violation_detail(first)}，已超过{GACHA_HARD_PITY}抽限制"
    )


def warn_gacha_pity_violations(
    pools: Mapping[str, Sequence[Any]], source: str = ""
) -> list[GachaPityViolation]:
    """超过硬保底只告警、不阻断：重叠段因历史断开而跨段计数时，真实抽数已不可还原，
    拒绝合并只会让用户永远导不进来。记录原样写入，统计侧自行判断。"""
    violations = find_gacha_pity_violations(pools)
    for violation in violations:
        logger.warning(
            f"[鸣潮·抽卡] {source}卡池[{violation.pool}]{_violation_detail(violation)}，"
            f"超过{GACHA_HARD_PITY}抽硬保底，按历史缺失处理并照常写入"
        )
    return violations


def group_flat_gacha_logs(logs: Sequence[Any]) -> dict[str, list[Any]]:
    pools: dict[str, list[Any]] = {}
    for item in logs:
        pool = str(_get_value(item, "cardPoolType", ""))
        if not pool:
            continue
        pools.setdefault(pool, []).append(item)
    return pools
