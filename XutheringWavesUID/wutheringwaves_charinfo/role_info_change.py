import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional

from gsuid_core.logger import logger

from ..utils.api.model import RoleDetailData, EquipPhantomData
from ..utils.waves_api import waves_api
from ..utils.util import hide_uid
from ..utils import name_convert
from ..utils.fuzzy_match import fuzzy_suggest
from ..utils.name_convert import (
    easy_id_to_name,
    is_valid_char_name,
    alias_to_sonata_name,
    alias_to_weapon_name,
    char_name_to_char_id,
    weapon_name_to_weapon_id,
)
from ..utils.api.model_other import EnemyDetailData
from ..utils.char_info_utils import get_all_role_detail_info_list, parse_skill_levels
from ..utils.ascension.sonata import WavesSonataResult, get_sonata_detail
from ..utils.ascension.weapon import WavesWeaponResult, get_weapon_detail
from ..utils.calc import resolve_node_state
from ..utils.resource.constant import SPECIAL_CHAR, SONATA_FIRST_ID, SONATA_FIRST_ID_BY_ROLE

phantom_main_value = [
    {"name": "攻击", "values": ["18%", "30%", "33%"]},
    {"name": "生命", "values": ["22.8%", "30%", "33%"]},
    {"name": "防御", "values": ["18%", "38%", "41.8%"]},
    {"name": "暴击", "values": ["0%", "0%", "22%"]},
    {"name": "暴击伤害", "values": ["0%", "0%", "44%"]},
    {"name": "共鸣效率", "values": ["0%", "32%", "0%"]},
    {"name": "属性伤害加成", "values": ["0%", "30%", "0%"]},
    {"name": "治疗效果加成", "values": ["0%", "0%", "26.4%"]},
]
phantom_main_value_map = {i["name"]: i["values"] for i in phantom_main_value}


async def get_remote_role_detail_info(find_char_id: List[str], waves_id, ck) -> Optional[RoleDetailData]:
    role_detail_info = None

    gen_temp = await get_all_role_detail_info_list(waves_id)  # type: ignore
    if gen_temp:
        role_detail_info = next(
            (role for role in gen_temp if str(role.role.roleId) in find_char_id),
            None,
        )

    if not role_detail_info:
        for char_id in find_char_id:
            temp = await waves_api.get_role_detail_info(char_id, waves_id, ck)
            if not temp.success:
                continue
            role_detail_info = temp.data
            if (
                not isinstance(role_detail_info, Dict)
                or "role" not in role_detail_info
                or role_detail_info["role"] is None
                or "level" not in role_detail_info
                or role_detail_info["level"] is None
            ):
                return None
            if role_detail_info["phantomData"]["cost"] == 0:
                role_detail_info["phantomData"]["equipPhantomList"] = None

            role_detail_info = RoleDetailData(**role_detail_info)
            break

    return role_detail_info


class ReplaceRole:
    def __init__(self):
        self.roleId: str | None = None  # 角色id
        self.roleName: str | None = None  # 角色名字
        self.level: str | None = None  # 等级
        self.chain: str | None = None  # 共鸣链
        self.skill: list[int] | None = None  # 技能


class ReplaceWeapon:
    def __init__(self):
        self.weaponId: str | None = None  # 武器id
        self.weaponName: str | None = None  # 武器名字
        self.level: str | None = None  # 等级
        self.resonLevel: str | None = None  # 谐振


class ReplaceSonata:
    def __init__(self):
        self.sonataName: list[str] = []  # 套装名字


class PhantomInfo:
    def __init__(self):
        self.uid: str | None = None  # 谁的
        self.charName: str | None = None  # 哪个角色身上的
        self.positions: List[str] | None = None  # 哪些位置
        self.toPositions: List[str] | None = None  # 到哪个位置
        self.cost: int | None = None  # 只换该 cost 的声骸

    def __str__(self):
        return f"{self.uid} {self.charName} {self.positions} {self.toPositions} {self.cost}"


class ReplacePhantom:
    def __init__(self):
        self.mainc4: List[str] | None = None  # 主词条更换
        self.mainc3: List[str] | None = None  # 主词条更换
        self.mainc1: List[str] | None = None  # 主词条更换
        self.phantomList: List[PhantomInfo] = []

    def __str__(self):
        return f"{self.mainc4} {self.mainc3} {self.mainc1} \n {[str(phantom) for phantom in self.phantomList]}"


class ReplaceEnemy:
    def __init__(self):
        self.enemyLevel: str | None = None  # 敌人等级
        self.enemyResistance: str | None = None  # 敌人抗性


class ReplaceModal:
    def __init__(self):
        self.modal: str | None = None  # 用户原始输入, 合法性交给 change_role_detail


class ReplaceResult:
    def __init__(self):
        self.role: ReplaceRole = ReplaceRole()
        self.weapon: ReplaceWeapon = ReplaceWeapon()
        self.sonata: ReplaceSonata = ReplaceSonata()
        self.phantom: ReplacePhantom = ReplacePhantom()
        self.enemy: ReplaceEnemy = ReplaceEnemy()
        self.modal: ReplaceModal = ReplaceModal()


MAX_CHANGE_LEN = 200
MAX_PHANTOM_SWAP = 5

_CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "双": 2, "三": 3, "四": 4, "五": 5, "六": 6}


def _to_int(s: str, full: int) -> int:
    if s == "满":
        return full
    if s.isdigit():
        return int(s)
    return _CN_NUM.get(s, 0)


_HUAN_ALIASES = ("替换成", "替换为", "替换", "更换", "换成", "换为", "改成", "改为")
_TYPOS = (
    ("声骇", "声骸"),
    ("生骸", "声骸"),
    ("声孩", "声骸"),
    ("生孩", "声骸"),
    ("圣遗物", "声骸"),
    ("振谐", "谐振"),
    ("磁条", "词条"),
)


def normalize_change_text(text: str) -> str:
    """全角/错字/同义词归一: 替换成→换, 声骇→声骸, 去标点和 [图片] 之类占位"""
    text = unicodedata.normalize("NFKC", text or "")[:MAX_CHANGE_LEN]
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"[,、;。:|/]+", " ", text)
    for src, dst in _TYPOS:
        text = text.replace(src, dst)
    for alias in _HUAN_ALIASES:
        text = text.replace(alias, "换")
    text = re.sub(r"(\d)\s+级", r"\1级", text)
    text = re.sub(r"(精炼|谐振|精|阶)\s+(\d)", r"\1\2", text)
    return re.sub(r"\s+", " ", text).strip()


_KW_KIND = {
    "声骸": "phantom",
    "武器": "weapon",
    "装备": "weapon",
    "合鸣": "sonata",
    "套装": "sonata",
    "角色": "role",
    "人物": "role",
    "敌人": "enemy",
    "怪物": "enemy",
    "环境": "enemy",
    "模态": "modal",
}
_KW_RE = re.compile("|".join(_KW_KIND))
_HEAD_KW = (("个人信息", "角色"), ("面板", "角色"), ("信息", "角色"), ("怪", "敌人"))
_BARE_RE = re.compile(r"主词条|主属性|主词|词条|[cC]\s*[134]|[134]\s*[cC]|共鸣链|命座|技能等级|技能|天赋|等级|\s")

_CHAIN_RE = re.compile(
    r"(?:共鸣链|命之座|命座|链)\s*([0-6零一二三四五六满])(?!\d)\s*(?:链|命)?"
    r"|([0-6零一二三四五六满])\s*(?:共鸣链|链|命座|命(?!理))"
)
_RESON_RE = re.compile(
    r"(?:精炼|谐振|精|阶|谐|振)\s*([1-5一二三四五满])(?!\d)\s*阶?"
    r"|([1-5一二三四五满])\s*(?:精炼|谐振|阶|精)"
)
_LEVEL_RE = re.compile(r"(?:等级|[lL][vV]\.?)\s*(\d{1,3})|(\d{1,3})\s*(?:级|等级)|(满级)")
_SKILL_RE = re.compile(r"(?:技能等级|技能|天赋)\s*(满级|满|(?:\d{1,2}\s+){1,4}\d{1,2}|\d{1,20})\s*级?")
_UID_RE = re.compile(r"(?<!\d)\d{9}(?!\d)")
_POS_RE = re.compile(r"([1-5])\s*到\s*([1-5])")
_SIG_RE = re.compile(r"([^\s专]*)专武")

_ATTR_ALIASES = (
    ("暴击伤害", "暴击伤害"),
    ("暴伤", "暴击伤害"),
    ("爆伤", "暴击伤害"),
    ("暴击", "暴击"),
    ("攻击", "攻击"),
    ("生命", "生命"),
    ("防御", "防御"),
    ("共鸣效率", "共鸣效率"),
    ("共效", "共鸣效率"),
    ("效率", "共鸣效率"),
    ("充能", "共鸣效率"),
    ("治疗效果加成", "治疗效果加成"),
    ("治疗效果", "治疗效果加成"),
    ("治疗", "治疗效果加成"),
    ("属性伤害加成", "属性伤害加成"),
    ("属性伤害", "属性伤害加成"),
    ("属伤", "属性伤害加成"),
    ("属性", "属性伤害加成"),
    ("共鸣", "共鸣效率"),
    ("暴", "暴击"),
    ("爆", "暴击伤害"),
    ("攻", "攻击"),
    ("生", "生命"),
    ("防", "防御"),
    ("充", "共鸣效率"),
    ("治", "治疗效果加成"),
    ("疗", "治疗效果加成"),
    ("属", "属性伤害加成"),
)
_ATTR_MAP = dict(_ATTR_ALIASES)
_ELEM = "冷凝|热熔|导电|气动|衍射|湮灭"
_MAIN_TOKEN_RE = re.compile(
    r"(?P<mark>[cC]\s*(?P<m1>[134])|(?P<m2>[134])\s*[cC])"
    rf"|(?P<cnt>[1-5一二两双三四五])?\s*(?P<attr>(?:{_ELEM})(?:属性)?(?:伤害加成|伤害|增伤|伤)?|"
    + "|".join(sorted(_ATTR_MAP, key=len, reverse=True))
    + ")"
)
_MAIN_HINT_RE = re.compile(r"主词条|主属性|主词|词条|[cC]\s*[134]|[134]\s*[cC]")
_MAIN_FILLER_RE = re.compile(r"主词条|主属性|主词|词条|伤害加成|加成|伤害|属性|率|[cC]\d|\s")
_COST_ONLY = {4: {"暴击", "暴击伤害", "治疗效果加成"}, 3: {"属性伤害加成", "共鸣效率"}}
_NAME_JUNK_RE = re.compile(r"\d+|pk|PK|对比|面板|面版|面包|mb|的|\s")
_NAME_STRAY = {"级", "等级", "阶", "满", "精", "精炼", "谐振", "链", "共鸣链", "技能", "天赋", "主词条", "词条"}


def _cost_of(attr: str, cost: int) -> int:
    for c, only in _COST_ONLY.items():
        if attr in only:
            return c
    return cost


def _put_main(slots: Dict[int, List[str]], cost: int, attr: str, n: int) -> None:
    cost = _cost_of(attr, cost)
    room = 5 - len(slots[cost])
    slots[cost].extend([attr] * max(0, min(n, room)))


def parse_main_stats(text: str) -> tuple[Dict[int, List[str]], str, int | None]:
    """主词条: 返回 ({cost: [词条...]}, 未识别剩余, 首个 cost 标记)。

    支持 c4/4C、一攻一属/双属/2攻、冷凝伤害等写法; 无 cost 时按词条可出现的位置推断。
    """
    slots: Dict[int, List[str]] = {4: [], 3: [], 1: []}
    loose: list[tuple[str, int]] = []
    first_mark: int | None = None
    current: int | None = None
    rest: list[str] = []
    last = 0
    for m in _MAIN_TOKEN_RE.finditer(text):
        rest.append(text[last : m.start()])
        last = m.end()
        if m.group("mark"):
            current = int(m.group("m1") or m.group("m2"))
            first_mark = current if first_mark is None else first_mark
            continue
        raw = m.group("attr")
        attr = "属性伤害加成" if re.match(_ELEM, raw) else _ATTR_MAP[raw]
        n = min(max(_to_int(m.group("cnt") or "1", 1), 1), 5)
        if current is None:
            loose.append((attr, n))
        else:
            _put_main(slots, current, attr, n)
    rest.append(text[last:])

    if loose:
        if first_mark is not None:
            target = first_mark
        elif any(a in _COST_ONLY[3] for a, _ in loose):
            target = 3
        elif any(a in _COST_ONLY[4] for a, _ in loose):
            target = 4
        else:
            target = 3 if sum(n for _, n in loose) >= 2 else 4
        for attr, n in loose:
            _put_main(slots, target, attr, n)

    leftover = _MAIN_FILLER_RE.sub("", "".join(rest))
    return {k: v for k, v in slots.items() if v}, leftover, first_mark


def _is_pure_main(text: str) -> bool:
    slots, leftover, _ = parse_main_stats(text)
    return bool(slots) and not leftover


def _take(pattern: re.Pattern[str], text: str) -> tuple[str, re.Match[str] | None]:
    """取最后一个命中, 并删掉所有命中"""
    matches = list(pattern.finditer(text))
    if not matches:
        return text, None
    return pattern.sub(" ", text), matches[-1]


def _take_level(text: str) -> tuple[str, str | None]:
    text, m = _take(_LEVEL_RE, text)
    if not m:
        return text, None
    level = 90 if m.group(3) else int(m.group(1) or m.group(2))
    return text, str(min(max(level, 1), 90))


def _bare_level(text: str) -> tuple[str, str | None]:
    m = re.search(r"(?<![\d精阶振谐链命])([1-9]\d)(?!\d)", text)
    if not m:
        return text, None
    return text[: m.start()] + text[m.end() :], str(min(int(m.group(1)), 90))


def _clean_name(text: str) -> str:
    name = _NAME_JUNK_RE.sub("", text)
    return "" if name in _NAME_STRAY else name


def _is_char_id(cid: str | None) -> bool:
    return bool(cid) and len(cid) == 4 and cid.isdigit()


def _fuzzy_one(name: str, table: Dict[str, List[str]], min_score: float) -> str | None:
    hits = fuzzy_suggest(name, table, top_n=2, min_score=min_score)
    if not hits or (len(hits) > 1 and hits[0][1] - hits[1][1] < 0.05):
        return None
    return hits[0][0]


def resolve_change_char(name: str) -> str | None:
    if _is_char_id(char_name_to_char_id(name)):
        return name_convert.alias_to_char_name(name)
    cand = _fuzzy_one(name, name_convert.char_alias_data, 0.8)
    return cand if cand and _is_char_id(char_name_to_char_id(cand)) else None


def _weapon_exact(name: str) -> str | None:
    for formal, aliases in name_convert.weapon_alias_data.items():
        if name == formal or name in aliases:
            return formal
    return None


def _resolve_weapon(name: str) -> tuple[str, str] | None:
    weapon_id = weapon_name_to_weapon_id(name)
    if weapon_id:
        return alias_to_weapon_name(name), weapon_id
    cand = _fuzzy_one(name, name_convert.weapon_alias_data, 0.75)
    weapon_id = weapon_name_to_weapon_id(cand) if cand else None
    return (cand, weapon_id) if cand and weapon_id else None


def _sonata_exact(name: str) -> str | None:
    key = name.rstrip("套")
    for formal, aliases in name_convert.sonata_alias_data.items():
        if key == formal.rstrip("套") or any(key == a.rstrip("套") for a in aliases):
            return formal
    return None


def _resolve_sonata(name: str) -> str | None:
    formal = alias_to_sonata_name(name)
    if formal:
        return formal
    return _fuzzy_one(name, name_convert.sonata_alias_data, 0.9)


def _sonata_tokens(text: str) -> list[tuple[str, str]]:
    return re.findall(r"([^\d\s]+)\s*(\d{1,3})?", text)


def parse_three_level(content: str) -> tuple[str, str] | None:
    pattern = r"(?:(等级|级)([1-9][0-9]?[0-9]?)|([1-9][0-9]?[0-9]?)(等级|级))"
    match = re.search(pattern, content)
    if match:
        # 角色/武器等级上限 90, 超出在 get_breach 没对应突破档会返回 0; 入口处 clamp 兜底
        matched_string = match.group(0)
        level = match.group(2) or match.group(3)
        return matched_string, str(min(int(level), 90))
    return None


def parse_enemy_resistance(content: str) -> tuple[str, str] | None:
    pattern = r"(?:(抗性|抗)([-+]?[0-9][0-9]?)|([-+]?[0-9][0-9]?)(抗性|抗))"
    match = re.search(pattern, content)
    if match:
        matched_string = match.group(0)
        level = match.group(2) or match.group(3)
        return matched_string, level
    return None


def get_breach(level: int):
    if level <= 20:
        breach = 0
    elif level <= 40:
        breach = 1
    elif level <= 50:
        breach = 2
    elif level <= 60:
        breach = 3
    elif level <= 70:
        breach = 4
    elif level <= 80:
        breach = 5
    elif level <= 90:
        breach = 6
    else:
        breach = 0
    return breach


@dataclass
class _Piece:
    kind: str | None
    text: str


def _is_bare(p: _Piece) -> bool:
    if p.kind in (None, "phantom", "role"):
        return not _BARE_RE.sub("", p.text)
    return not p.text


def _split_chunk(chunk: str) -> tuple[list[_Piece], bool]:
    for head, kw in _HEAD_KW:
        if chunk.startswith(head) and not _KW_RE.match(chunk):
            chunk = kw + chunk[len(head) :]
            break
    ms = list(_KW_RE.finditer(chunk))
    raw_lead = chunk[: ms[0].start()] if ms else chunk
    out = [_Piece(None, raw_lead.strip())] if raw_lead.strip() else []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(chunk)
        out.append(_Piece(_KW_KIND[m.group()], chunk[m.end() : end].strip()))
    return out, bool(ms) and not raw_lead[-1:].isspace()


def split_change_pieces(text: str) -> list[_Piece]:
    """按「换」和类别词切段; 只有类别词的段与下一段合并"""
    pieces: list[_Piece] = []
    pending: _Piece | None = None
    for chunk in text.split("换"):
        chunk = chunk.strip()
        if not chunk:
            continue
        sub, adjoin = _split_chunk(chunk)
        if pending is not None and sub and sub[0].kind in (None, pending.kind):
            sub[0] = _Piece(pending.kind or sub[0].kind, f"{pending.text} {sub[0].text}".strip())
        elif adjoin and len(sub) >= 2 and sub[0].kind is None and sub[1].kind and not sub[1].text:
            # 后置写法: 安可声骸 / 聚爆模态
            sub = [_Piece(sub[1].kind, sub[0].text), *sub[2:]]
        pending = None
        for i, p in enumerate(sub):
            if not _is_bare(p):
                pieces.append(p)
            elif i == len(sub) - 1:
                pending = p
    return pieces


class ChangeParser:
    def __init__(self, content: str, char_name: str = ""):
        self.rr: ReplaceResult = ReplaceResult()
        self.char_name = char_name
        self.char_id = char_name_to_char_id(char_name) if char_name else None
        self.unknown: list[str] = []
        self.text = normalize_change_text(content)
        handlers = {
            None: self._parse_implicit,
            "role": self._parse_role,
            "weapon": self._parse_weapon,
            "phantom": self._parse_phantom,
            "sonata": self._parse_sonata,
            "enemy": self._parse_enemy,
            "modal": self._parse_modal,
        }
        for piece in split_change_pieces(self.text)[:20]:
            handlers[piece.kind](piece.text)

    def _take_chain(self, text: str) -> str:
        text, m = _take(_CHAIN_RE, text)
        if m:
            self.rr.role.chain = str(min(_to_int(m.group(1) or m.group(2), 6), 6))
        return text

    def _take_skill(self, text: str, strict: bool = False) -> str:
        for m in _SKILL_RE.finditer(text):
            value = m.group(1)
            if strict and value.isdigit() and len(value) == 1:
                continue
            if value.startswith("满"):
                self.rr.role.skill = [10] * 5
            else:
                self.rr.role.skill = parse_skill_levels(value)
            return text.replace(m.group(0), " ")
        return text

    def _take_reson(self, text: str) -> tuple[str, bool]:
        text, m = _take(_RESON_RE, text)
        if m:
            self.rr.weapon.resonLevel = str(_to_int(m.group(1) or m.group(2), 5))
        return text, m is not None

    def _take_signature(self, text: str) -> str:
        m = _SIG_RE.search(text)
        if not m:
            return text
        self._set_weapon(f"{m.group(1)}专武")
        return text.replace(m.group(0), " ")

    def _set_weapon(self, name: str) -> bool:
        sigs = [m.group(1) for m in _SIG_RE.finditer(name)]
        if sigs:
            owner = next((s for s in reversed(sigs) if s), "")
            name = f"{owner or self.char_name}专武"
        hit = _resolve_weapon(name) if name else None
        if hit:
            self.rr.weapon.weaponName, self.rr.weapon.weaponId = hit
        return hit is not None

    def _add_swap(self, text: str, cost: int | None = None) -> None:
        info = PhantomInfo()
        uid = _UID_RE.search(text)
        if uid:
            info.uid = uid.group(0)
            text = text.replace(info.uid, " ")
        pairs = _POS_RE.findall(text)
        info.positions = [p for p, _ in pairs]
        info.toPositions = [t for _, t in pairs]
        text = re.sub(r"\d?\s*到\s*\d?", " ", text)
        name = _clean_name(text) or (self.char_name if info.uid else "")
        if not name or len(self.rr.phantom.phantomList) >= MAX_PHANTOM_SWAP:
            return
        info.charName = resolve_change_char(name) or name
        info.cost = cost if not pairs else None
        self.rr.phantom.phantomList.append(info)

    def _apply_main(self, slots: Dict[int, List[str]]) -> None:
        if 4 in slots:
            self.rr.phantom.mainc4 = slots[4]
        if 3 in slots:
            self.rr.phantom.mainc3 = slots[3]
        if 1 in slots:
            self.rr.phantom.mainc1 = slots[1]

    def _parse_phantom(self, text: str) -> None:
        text = self._take_signature(text)
        char_part, main_part = text, ""
        hint = _MAIN_HINT_RE.search(text)
        if hint:
            head = text[: hint.start()]
            if not head.strip() or _is_pure_main(head):
                char_part, main_part = "", text
            else:
                char_part, main_part = head, text[hint.start() :]
        elif _is_pure_main(text):
            char_part, main_part = "", text
        cost = None
        if main_part:
            slots, leftover, mark = parse_main_stats(main_part)
            if slots:
                self._apply_main(slots)
            else:
                cost = mark
            char_part = f"{char_part} {leftover}"
        self._add_swap(char_part, cost)

    def _parse_weapon(self, text: str) -> None:
        text = self._take_chain(self._take_skill(text))
        text, _ = self._take_reson(text)
        text, level = _take_level(text)
        if level is None:
            text, level = _bare_level(text)
        if level:
            self.rr.weapon.level = level
        name = _clean_name(text)
        if name and not self._set_weapon(name):
            self.unknown.append(name)

    def _parse_role(self, text: str) -> None:
        text = self._take_chain(self._take_skill(text))
        text, _ = self._take_reson(self._take_signature(text))
        text, level = _take_level(text)
        if level is None:
            text, level = _bare_level(text)
        if level:
            self.rr.role.level = level

    def _parse_sonata(self, text: str) -> None:
        text = self._take_skill(text, strict=True)
        names = self.rr.sonata.sonataName
        for name, num in _sonata_tokens(text):
            amount = min(int(num) if num else 5, 5 - len(names))
            if amount <= 0:
                break
            formal = _resolve_sonata(name)
            if formal:
                names.extend([formal] * amount)
            else:
                self.unknown.append(name)

    def _parse_enemy(self, text: str) -> None:
        level = parse_three_level(text)
        if level:
            self.rr.enemy.enemyLevel = level[1]
        resistance = parse_enemy_resistance(text)
        if resistance:
            self.rr.enemy.enemyResistance = resistance[1]

    def _parse_modal(self, text: str) -> None:
        if text.strip():
            self.rr.modal.modal = text.strip()

    def _parse_implicit(self, text: str) -> None:
        if _POS_RE.search(text) or _UID_RE.search(text):
            return self._parse_phantom(text)
        text = self._take_chain(self._take_skill(text))
        text, has_reson = self._take_reson(text)
        text, level = _take_level(text)
        name = _clean_name(text)
        exact_char = bool(name) and is_valid_char_name(name)
        if not exact_char and (_MAIN_HINT_RE.search(text) or _is_pure_main(text)):
            return self._parse_phantom(text)
        if "专武" in name:
            self._set_weapon(name)
            if level:
                self.rr.weapon.level = level
            return
        if not name:
            if level:
                target = self.rr.weapon if has_reson else self.rr.role
                target.level = level
            return
        cid = char_name_to_char_id(name)
        if exact_char and _is_char_id(cid):
            if level:
                self.rr.role.level = level
            if cid != self.char_id or not (level or has_reson or self.rr.role.chain or self.rr.role.skill):
                self._add_swap(name)
            return
        tokens = _sonata_tokens(text)
        if tokens and all(_sonata_exact(n) or (num and alias_to_sonata_name(n)) for n, num in tokens):
            return self._parse_sonata(text)
        fuzzy_char = resolve_change_char(name)
        if _weapon_exact(name) or (len(name) > 1 and not fuzzy_char and _resolve_weapon(name)):
            self._set_weapon(name)
            if level:
                self.rr.weapon.level = level
            return
        if fuzzy_char:
            if level:
                self.rr.role.level = level
            return self._add_swap(name)
        self.unknown.append(name)

    def has_changes(self) -> bool:
        rr = self.rr
        return any(
            (
                rr.role.level,
                rr.role.chain,
                rr.role.skill,
                rr.weapon.weaponId,
                rr.weapon.level,
                rr.weapon.resonLevel,
                rr.sonata.sonataName,
                rr.phantom.phantomList,
                rr.phantom.mainc4,
                rr.phantom.mainc3,
                rr.phantom.mainc1,
                rr.enemy.enemyLevel,
                rr.enemy.enemyResistance,
                rr.modal.modal,
            )
        )

    def has_phantom_change(self) -> bool:
        ph = self.rr.phantom
        return bool(ph.phantomList or ph.mainc4 or ph.mainc3 or ph.mainc1)

    def get_matched_content(self) -> str:
        rr = self.rr
        segments: list[str] = []
        role = []
        if rr.role.level:
            role.append(f"{rr.role.level}级")
        if rr.role.chain:
            role.append(f"{rr.role.chain}链")
        if rr.role.skill:
            role.append(f"技能{' '.join(map(str, rr.role.skill))}")
        if role:
            segments.append(f"换角色 {' '.join(role)}")
        weapon = []
        if rr.weapon.level:
            weapon.append(f"{rr.weapon.level}级")
        if rr.weapon.resonLevel:
            weapon.append(f"谐振{rr.weapon.resonLevel}")
        if rr.weapon.weaponName:
            weapon.append(rr.weapon.weaponName)
        if weapon:
            segments.append(f"换武器 {' '.join(weapon)}")
        for info in rr.phantom.phantomList:
            moves = " ".join(f"{p}到{t}" for p, t in zip(info.positions or [], info.toPositions or []))
            cost = f" {info.cost}c" if info.cost else ""
            segments.append(f"换声骸 {info.uid or ''}{info.charName}{' ' + moves if moves else ''}{cost}")
        mains = [
            f"c{c}{''.join(v)}"
            for c, v in ((4, rr.phantom.mainc4), (3, rr.phantom.mainc3), (1, rr.phantom.mainc1))
            if v
        ]
        if mains:
            segments.append(f"换声骸 {' '.join(mains)}")
        if rr.sonata.sonataName:
            counts: Dict[str, int] = {}
            for name in rr.sonata.sonataName:
                counts[name] = counts.get(name, 0) + 1
            segments.append(f"换合鸣 {' '.join(f'{k}{v}' for k, v in counts.items())}")
        enemy = []
        if rr.enemy.enemyLevel:
            enemy.append(f"{rr.enemy.enemyLevel}级")
        if rr.enemy.enemyResistance:
            enemy.append(f"{rr.enemy.enemyResistance}抗")
        if enemy:
            segments.append(f"换敌人 {' '.join(enemy)}")
        if rr.modal.modal:
            segments.append(f"换模态{rr.modal.modal}")
        return ";".join(segments)


def has_phantom_change(change_text: str | None) -> bool:
    if not change_text:
        return False
    return ChangeParser(change_text).has_phantom_change()


def is_phantom_dirty(change_command: str) -> bool:
    """change_command 含 '换声骸' / '换合鸣' 即视为改动了声骸/套装/主词条。"""
    if not change_command:
        return False
    return "换声骸" in change_command or "换合鸣" in change_command


def ensure_default_modal(role_detail: RoleDetailData) -> None:
    """有 wiki skillBranches 但未激活任何模态时, 注入默认 (isDefault, 否则首项)。in-place。"""
    if role_detail.activeBranchId and role_detail.skillBranchList:
        return
    from ..utils.ascension.char import get_char_model, ensure_data_loaded
    from ..utils.api.model.role import SkillBranch

    ensure_data_loaded()
    char_model = get_char_model(str(role_detail.role.roleId))
    branches = char_model.skillBranches if char_model else None
    if not branches:
        return
    default_idx = next(
        (i for i, b in enumerate(branches) if getattr(b, "isDefault", False)),
        0,
    )
    role_detail.skillBranchList = [
        SkillBranch(
            activePic="", branchId=i + 1, branchName=b.name,
            desc=b.desc, pic="", skillIcon="",
        )
        for i, b in enumerate(branches)
    ]
    role_detail.activeBranchId = default_idx + 1


async def change_role_detail(
    waves_id: str,
    ck: str,
    role_detail: RoleDetailData,
    enemy_detail: EnemyDetailData,
    change_list_regex: str,
    user_id: str = "",
    bot_id: str = "",
) -> tuple[RoleDetailData, str]:
    resolve_node_state(role_detail)
    parser: ChangeParser = ChangeParser(change_list_regex, role_detail.role.roleName)
    parserResult: ReplaceResult = parser.rr
    if parser.unknown and not parser.has_changes():
        from ..wutheringwaves_config import PREFIX

        return role_detail, f"[鸣潮] 没看懂要替换什么, 可发送{PREFIX}替换帮助查看写法"
    if parserResult.role.skill:
        skill_list = role_detail.get_skill_list()
        for i, level in zip(skill_list[:5], parserResult.role.skill):
            for j in role_detail.skillList:
                if j.skill.type != i.skill.type:
                    continue
                j.level = int(level)

    if parserResult.role.level:
        roleLevel = int(parserResult.role.level)
        role_detail.role.level = roleLevel
        role_detail.level = roleLevel
        role_detail.role.breach = get_breach(roleLevel)

    if parserResult.role.chain:
        chain = int(parserResult.role.chain)
        if chain == 0:
            for temp in role_detail.chainList:
                temp.unlocked = False

        for chainNum, temp in enumerate(role_detail.chainList, start=1):
            if chainNum <= chain:
                temp.unlocked = True
            else:
                temp.unlocked = False

    # 武器
    if parserResult.weapon.weaponId:
        weapon_detail: WavesWeaponResult | None = get_weapon_detail(parserResult.weapon.weaponId, 90)
        if weapon_detail:
            weapon = role_detail.weaponData.weapon
            if weapon.weaponType == weapon_detail.type:
                weapon.weaponId = int(parserResult.weapon.weaponId)
                weapon.weaponName = weapon_detail.name
                weapon.weaponStarLevel = weapon_detail.starLevel

    if parserResult.weapon.level:
        weaponLevel = int(parserResult.weapon.level)
        role_detail.weaponData.level = weaponLevel
        role_detail.weaponData.breach = get_breach(weaponLevel)

    if parserResult.weapon.resonLevel:
        role_detail.weaponData.resonLevel = int(parserResult.weapon.resonLevel)

    if parserResult.phantom.phantomList:
        for ph_info in parserResult.phantom.phantomList:
            logger.debug(f"[鸣潮·GsCore] 声骸替换：{ph_info}")
            err = await change_role_phantom(waves_id, ck, role_detail, ph_info, user_id, bot_id)
            if err:
                return role_detail, err

    logger.debug(
        f"[鸣潮·声骸解析] 声骸主词条: c4-{parserResult.phantom.mainc4}， c3-{parserResult.phantom.mainc3}, c1-{parserResult.phantom.mainc1}"
    )
    if parserResult.phantom.mainc4:
        index = 0
        mainc = parserResult.phantom.mainc4
        if role_detail.phantomData and role_detail.phantomData.equipPhantomList:
            for ep in role_detail.phantomData.equipPhantomList:
                if not ep:
                    continue
                if ep.cost != 4:
                    continue
                props = ep.mainProps
                if not props:
                    continue
                if index >= len(mainc):
                    break
                props[0].attributeName = mainc[index]
                props[0].attributeValue = phantom_main_value_map[mainc[index]][2]
                index += 1
    if parserResult.phantom.mainc3:
        index = 0
        mainc = parserResult.phantom.mainc3
        if role_detail.phantomData and role_detail.phantomData.equipPhantomList:
            for ep in role_detail.phantomData.equipPhantomList:
                if not ep:
                    continue
                if ep.cost != 3:
                    continue
                props = ep.mainProps
                if not props:
                    continue
                if index >= len(mainc):
                    break
                if mainc[index] == "属性伤害加成":
                    shuxing = f"{role_detail.role.attributeName}伤害加成"
                else:
                    shuxing = mainc[index]
                props[0].attributeName = shuxing
                props[0].attributeValue = phantom_main_value_map[mainc[index]][1]
                index += 1

    if parserResult.phantom.mainc1:
        index = 0
        mainc = parserResult.phantom.mainc1
        if role_detail.phantomData and role_detail.phantomData.equipPhantomList:
            for ep in role_detail.phantomData.equipPhantomList:
                if not ep:
                    continue
                if ep.cost != 1:
                    continue
                props = ep.mainProps
                if not props:
                    continue
                if index >= len(mainc):
                    break
                props[0].attributeName = mainc[index]
                props[0].attributeValue = phantom_main_value_map[mainc[index]][0]
                index += 1

    if parserResult.sonata.sonataName:
        sonata_results = []
        for sonataName in parserResult.sonata.sonataName[:5]:
            sonata_result: WavesSonataResult = get_sonata_detail(sonataName)
            sonata_results.append(sonata_result)
        if sonata_results and role_detail.phantomData and role_detail.phantomData.equipPhantomList:
            for index, ep in enumerate(role_detail.phantomData.equipPhantomList):
                if not ep:
                    continue
                if index >= len(sonata_results):
                    break
                ep.fetterDetail.name = sonata_results[index].name
                if index == 0:
                    sonata_name = sonata_results[index].name
                    valid_first = SONATA_FIRST_ID.get(sonata_name, [])
                    if valid_first and ep.phantomProp.phantomId not in valid_first:
                        role_first = SONATA_FIRST_ID_BY_ROLE.get(sonata_name, {})
                        ep.phantomProp.phantomId = role_first.get(role_detail.role.roleId, valid_first[0])
                        ep.phantomProp.name = easy_id_to_name(str(ep.phantomProp.phantomId), ep.phantomProp.name)

    # 敌人
    if parserResult.enemy.enemyResistance:
        enemy_detail.enemy_resistance = int(parserResult.enemy.enemyResistance)
    if parserResult.enemy.enemyLevel:
        enemy_detail.enemy_level = int(parserResult.enemy.enemyLevel)

    # 模态切换: wiki 数据校验; 极限模式 (skillBranchList=None) 用 wiki 构造 mock 注入
    if parserResult.modal.modal:
        from ..utils.ascension.char import get_char_model, ensure_data_loaded
        from ..utils.api.model.role import SkillBranch

        ensure_data_loaded()
        role_name = role_detail.role.roleName
        char_model = get_char_model(str(role_detail.role.roleId))
        wiki_branches = char_model.skillBranches if char_model else None
        if not wiki_branches:
            return role_detail, f"[鸣潮] 角色【{role_name}】无可切换的共鸣模态"

        target_idx = next(
            (i for i, b in enumerate(wiki_branches) if parserResult.modal.modal in b.name),
            None,
        )
        if target_idx is None:
            available = "、".join(b.name for b in wiki_branches)
            return role_detail, (
                f"[鸣潮] 角色【{role_name}】没有【{parserResult.modal.modal}】模态, 可选: {available}"
            )

        runtime_match = None
        if role_detail.skillBranchList:
            runtime_match = next(
                (b for b in role_detail.skillBranchList if parserResult.modal.modal in b.branchName),
                None,
            )
        if runtime_match:
            role_detail.activeBranchId = runtime_match.branchId
        else:
            role_detail.skillBranchList = [
                SkillBranch(
                    activePic="", branchId=i + 1, branchName=b.name,
                    desc=b.desc, pic="", skillIcon="",
                )
                for i, b in enumerate(wiki_branches)
            ]
            role_detail.activeBranchId = target_idx + 1

    return role_detail, parser.get_matched_content()


async def change_role_phantom(
    waves_id: str,
    ck: str,
    role_detail: RoleDetailData,
    phantom: PhantomInfo,
    user_id: str = "",
    bot_id: str = "",
) -> Optional[str]:
    parserCharName = phantom.charName
    parserWavesUid = phantom.uid
    parserPositions = phantom.positions
    parserToPositions = phantom.toPositions

    logger.debug(f"[鸣潮·声骸解析] change_role_phantom {parserWavesUid}{parserCharName}{parserPositions}到{parserToPositions}")

    char_id = char_name_to_char_id(parserCharName) if parserCharName else None
    if not char_id or len(char_id) != 4 or not char_id.isdigit():
        return "[鸣潮] 未找到替换目标角色, 请检查输入是否正确！"
    find_char_id = []
    if char_id in SPECIAL_CHAR:
        find_char_id = SPECIAL_CHAR[char_id]
    elif char_id:
        find_char_id = [char_id]
    if parserWavesUid:
        waves_id = parserWavesUid

    if not find_char_id:
        return "[鸣潮] 未找到替换目标角色, 请检查输入是否正确！"

    # 使用与查看他人面板一致的ck获取逻辑
    if parserWavesUid and user_id and bot_id:
        _, ck = await waves_api.get_ck_result(waves_id, user_id, bot_id)
        if not ck:
            return f"[鸣潮] 替换目标UID【{hide_uid(waves_id)}】的声骸数据查询失败"

    remote_role_detail_info = await get_remote_role_detail_info(find_char_id, waves_id, ck)
    if not remote_role_detail_info:
        return f"[鸣潮] 替换目标UID【{hide_uid(waves_id)}】的声骸数据查询失败"

    if not remote_role_detail_info.phantomData or not remote_role_detail_info.phantomData.equipPhantomList:
        return f"[鸣潮] 替换目标UID【{hide_uid(waves_id)}】没有声骸数据"

    if phantom.cost and not parserPositions:
        src = [i for i, ep in enumerate(remote_role_detail_info.phantomData.equipPhantomList) if ep and ep.cost == phantom.cost]
        own = role_detail.phantomData.equipPhantomList if role_detail.phantomData else None
        dst = [i for i, ep in enumerate(own or []) if ep and ep.cost == phantom.cost] or src
        if not src:
            return f"[鸣潮] 替换目标没有{phantom.cost}c声骸"
        parserPositions = [str(i + 1) for i in src[: len(dst)]]
        parserToPositions = [str(i + 1) for i in dst[: len(src)]]

    if not parserPositions or not parserToPositions:
        role_detail.phantomData = remote_role_detail_info.phantomData
    else:
        if not role_detail.phantomData or not role_detail.phantomData.equipPhantomList:
            role_detail.phantomData = EquipPhantomData(
                **{
                    "cost": 0,
                    "equipPhantomList": [None, None, None, None, None],
                }
            )

        for parserPosition, parserToPosition in zip(parserPositions, parserToPositions):
            new = remote_role_detail_info.phantomData.equipPhantomList[int(parserPosition) - 1]
            newCost = 0
            if new:
                newCost = new.cost

            temp = role_detail.phantomData.equipPhantomList
            if not temp:
                continue

            old = temp[int(parserToPosition) - 1]
            oldCost = 0
            if old:
                oldCost = old.cost

            totalCost = 0
            for eq in temp:
                if not eq:
                    continue
                totalCost += eq.cost

            if totalCost - oldCost + newCost <= 12:
                temp[int(parserToPosition) - 1] = new  # type: ignore
