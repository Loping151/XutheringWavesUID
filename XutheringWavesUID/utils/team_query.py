"""矩阵队伍参数解析: 三个角色名/别名, 或三字首字缩写 (如 爱达千); 角色前可加共鸣链 (如 6爱0达0千)。"""

import re
from typing import Dict, List, Tuple, Optional

from .name_convert import (
    get_all_char_id,
    ensure_data_loaded,
    char_id_to_char_name,
    char_name_to_char_id,
    alias_to_char_name_optional,
)
from .ascension.char import get_char_model
from .resource.constant import SPECIAL_CHAR_RANK_MAP

TEAM_SIZE = 3

_SEP = re.compile(r"[\s,，、/|]+")
_INITIAL = re.compile(r"[0-6]?\D")
_CHAIN_PREFIX = re.compile(r"^([0-6])?(\D.*)$")
_FORMAT_HINT = f"请输入{TEAM_SIZE}个角色名, 或{TEAM_SIZE}字首字缩写(如: 爱达千、6爱达千)"
_NOT_FOUND_HINT = "未找到指定角色，请检查输入！"

_initial_index: Dict[str, List[int]] = {}
_initial_index_size = 0


def _get_initial_index() -> Dict[str, List[int]]:
    """首字 -> 角色 id 列表; 漂泊者归一到主 id, 排除非四位数字的自定义角色。"""
    global _initial_index, _initial_index_size
    ensure_data_loaded()
    all_char_id = get_all_char_id()
    if _initial_index_size != len(all_char_id):
        index: Dict[str, List[int]] = {}
        for char_id in all_char_id:
            if not (char_id.isdigit() and len(char_id) == 4):
                continue
            name = char_id_to_char_name(char_id)
            if not name:
                continue
            mapped_id = int(SPECIAL_CHAR_RANK_MAP.get(char_id, char_id))
            char_ids = index.setdefault(name[0], [])
            if mapped_id not in char_ids:
                char_ids.append(mapped_id)
        for char_ids in index.values():
            char_ids.sort()
        _initial_index = index
        _initial_index_size = len(all_char_id)
    return _initial_index


def _pick_by_reference(candidates: List[int], ref_id: int) -> int:
    """优先同属性; 同属性内/无同属性时取角色 id 后两位最接近的。"""
    ref_model = get_char_model(ref_id)
    ref_attr = ref_model.attributeId if ref_model else None

    same_attr = []
    if ref_attr is not None:
        for char_id in candidates:
            model = get_char_model(char_id)
            if model and model.attributeId == ref_attr:
                same_attr.append(char_id)

    pool = same_attr or candidates
    return min(pool, key=lambda char_id: (abs(char_id % 100 - ref_id % 100), char_id))


def _token_candidates(token: str) -> List[int]:
    """单字按首字取候选, 其余走别名解析"""
    if len(token) == 1:
        return list(_get_initial_index().get(token, []))

    char_name = alias_to_char_name_optional(token)
    char_id = char_name_to_char_id(char_name) if char_name else None
    if not (char_id and char_id.isdigit()):
        return []
    return [int(char_id)]


def _resolve_tokens(tokens: List[str]) -> Tuple[List[int], Optional[str]]:
    candidates = []
    for token in tokens:
        matched = _token_candidates(token)
        if not matched:
            return [], _NOT_FOUND_HINT
        candidates.append(matched)

    resolved: List[Optional[int]] = [m[0] if len(m) == 1 else None for m in candidates]
    ref_id = next((char_id for char_id in resolved if char_id is not None), None)
    if ref_id is None:
        ref_id = candidates[0][0]
        resolved[0] = ref_id

    for index, matched in enumerate(candidates):
        if resolved[index] is None:
            resolved[index] = _pick_by_reference(matched, ref_id)

    return [char_id for char_id in resolved if char_id is not None], None


def split_team_and_page(text: Optional[str]) -> Tuple[str, Optional[str]]:
    """从队伍参数里摘出首/尾的页码, 返回 (队伍文本, 页码)。"""
    tokens = [t for t in _SEP.split((text or "").strip()) if t]
    page = None
    if tokens and tokens[-1].isdigit():
        page = tokens.pop()
    elif tokens and tokens[0].isdigit():
        page = tokens.pop(0)
    return " ".join(tokens), page


def parse_matrix_team(text: str) -> Tuple[List[int], List[Optional[int]], Optional[str]]:
    """返回 (char_ids, 各角色共鸣链筛选, 错误提示); 均为空表示未传队伍参数, 链为 None 表示不限。"""
    text = (text or "").strip()
    if not text:
        return [], [], None

    tokens = [t for t in _SEP.split(text) if t]
    initials = _INITIAL.findall(tokens[0]) if len(tokens) == 1 else []
    abbreviated = len(initials) == TEAM_SIZE and "".join(initials) == tokens[0]
    if abbreviated:
        tokens = initials
    matches = [_CHAIN_PREFIX.match(t) for t in tokens]
    if len(tokens) != TEAM_SIZE or not all(matches):
        return [], [], _FORMAT_HINT

    chains = [int(m.group(1)) if m.group(1) else None for m in matches]
    char_ids, err = _resolve_tokens([m.group(2) for m in matches])
    if err:
        return [], [], _FORMAT_HINT if abbreviated else err

    if len(set(char_ids)) != TEAM_SIZE:
        return [], [], "队伍中出现重复角色"
    return char_ids, chains, None
