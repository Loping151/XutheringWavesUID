"""矩阵队伍参数解析: 三个角色名/别名, 或三字首字缩写 (如 爱达千)。"""

import re
from typing import List, Tuple, Optional

from . import name_convert
from .name_convert import (
    ensure_data_loaded,
    char_name_to_char_id,
    alias_to_char_name_optional,
)
from .ascension.char import get_char_model
from .resource.constant import SPECIAL_CHAR_RANK_MAP

TEAM_SIZE = 3

_SEP = re.compile(r"[\s,，、/|]+")
_FORMAT_HINT = f"请输入{TEAM_SIZE}个角色名, 或{TEAM_SIZE}字首字缩写(如: 爱达千)"


def _all_char_id2name() -> List[Tuple[int, str]]:
    """(char_id, name) 列表; 过滤非四位数字的自定义角色, 漂泊者归一到主 id。"""
    ensure_data_loaded()
    seen = set()
    result = []
    for char_id, name in name_convert.id2name.items():
        if not (char_id.isdigit() and len(char_id) == 4):
            continue
        mapped_id = int(SPECIAL_CHAR_RANK_MAP.get(char_id, char_id))
        if mapped_id in seen:
            continue
        seen.add(mapped_id)
        result.append((mapped_id, name))
    return result


def _candidates_by_initial(initial: str) -> List[int]:
    return sorted(cid for cid, name in _all_char_id2name() if name.startswith(initial))


def _pick_by_reference(candidates: List[int], ref_id: int) -> int:
    """优先同属性; 同属性内/无同属性时取角色 id 后两位最接近的。"""
    ref_model = get_char_model(ref_id)
    ref_attr = ref_model.attributeId if ref_model else None

    same_attr = []
    if ref_attr is not None:
        for cid in candidates:
            model = get_char_model(cid)
            if model and model.attributeId == ref_attr:
                same_attr.append(cid)

    pool = same_attr or candidates
    return min(pool, key=lambda cid: (abs(cid % 100 - ref_id % 100), cid))


def _resolve_by_initials(text: str) -> Tuple[List[int], Optional[str]]:
    candidates = []
    for initial in text:
        matched = _candidates_by_initial(initial)
        if not matched:
            return [], "未找到首字对应的角色，请检查输入！"
        candidates.append(matched)

    resolved: List[Optional[int]] = [m[0] if len(m) == 1 else None for m in candidates]
    ref_id = next((cid for cid in resolved if cid is not None), None)
    if ref_id is None:
        ref_id = candidates[0][0]
        resolved[0] = ref_id

    for index, matched in enumerate(candidates):
        if resolved[index] is None:
            resolved[index] = _pick_by_reference(matched, ref_id)

    return [cid for cid in resolved if cid is not None], None


def split_team_and_page(text: Optional[str]) -> Tuple[str, Optional[str]]:
    """从队伍参数里摘出首/尾的页码, 返回 (队伍文本, 页码)。"""
    tokens = [t for t in _SEP.split((text or "").strip()) if t]
    page = None
    if tokens and tokens[-1].isdigit():
        page = tokens.pop()
    elif tokens and tokens[0].isdigit():
        page = tokens.pop(0)
    return " ".join(tokens), page


def parse_matrix_team(text: str) -> Tuple[List[int], Optional[str]]:
    """返回 (char_ids, 错误提示); 均为空表示未传队伍参数。"""
    text = (text or "").strip()
    if not text:
        return [], None

    tokens = [t for t in _SEP.split(text) if t]
    if len(tokens) == TEAM_SIZE:
        char_ids = []
        for token in tokens:
            char_name = alias_to_char_name_optional(token)
            char_id = char_name_to_char_id(char_name) if char_name else None
            if not (char_id and char_id.isdigit()):
                return [], "未找到指定角色，请检查输入！"
            char_ids.append(int(char_id))
    elif len(tokens) == 1 and len(tokens[0]) == TEAM_SIZE:
        char_ids, err = _resolve_by_initials(tokens[0])
        if err:
            return [], _FORMAT_HINT
    else:
        return [], _FORMAT_HINT

    if len(set(char_ids)) != TEAM_SIZE:
        return [], "队伍中出现重复角色"
    return char_ids, None
