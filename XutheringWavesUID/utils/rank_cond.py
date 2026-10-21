"""排行配置筛选: 共鸣链 + 专武谐振阶。

`01` = 0 链且专武 1 阶; `0链` / `零链` / `0命` 只筛共鸣链; 单个数字是页码。没装专武(含装他人专武)按 0 阶。
"""

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

_CN_DIGITS = "零一二三四五六"

COND_PATTERN = rf"(?:[0-6][0-5](?!\d)|[0-6{_CN_DIGITS}][链命鏈])"
_COND_RE = re.compile(rf"^(?:(?P<code>[0-6][0-5])|(?P<chain>[0-6{_CN_DIGITS}])[链命鏈])$")
_TRAILING_COND_RE = re.compile(rf"(?<!\d)(?:[0-6][0-5]|[0-6{_CN_DIGITS}][链命鏈])$")


def _digit(ch: str) -> int:
    return int(ch) if ch.isdigit() else _CN_DIGITS.index(ch)


@dataclass(frozen=True)
class RankCond:
    chain: Optional[int] = None
    signature_reson: Optional[int] = None

    @property
    def active(self) -> bool:
        return self.chain is not None or self.signature_reson is not None

    @property
    def token(self) -> str:
        """规范指令里的写法, 如 `01` / `0链`。"""
        if not self.active:
            return ""
        if self.signature_reson is None:
            return f"{self.chain}链"
        return f"{self.chain}{self.signature_reson}"

    @property
    def label(self) -> str:
        if not self.active:
            return ""
        if self.signature_reson is None:
            return f"{self.chain}链"
        reson = "无专武" if self.signature_reson == 0 else f"专武{self.signature_reson}阶"
        return f"{self.chain}链·{reson}"

    def params(self) -> Dict[str, int]:
        """总排行接口的筛选参数, 不限的不传。"""
        out = {"chain": self.chain, "signature_reson": self.signature_reson}
        return {k: v for k, v in out.items() if v is not None}

    def match_role(self, role) -> bool:
        """本地面板是否符合, 规则同 custom_weight.role_code。"""
        from .custom_weight import role_code

        code = role_code(role)
        if code is None:
            return False
        return (self.chain is None or int(code[0]) == self.chain) and (
            self.signature_reson is None or int(code[1]) == self.signature_reson
        )


def parse_rank_cond(text: Optional[str]) -> RankCond:
    m = _COND_RE.match((text or "").replace(" ", ""))
    if not m:
        return RankCond()
    if m.group("code"):
        return RankCond(int(m.group("code")[0]), int(m.group("code")[1]))
    return RankCond(_digit(m.group("chain")))


def split_char_cond(char: str) -> Tuple[str, RankCond]:
    """角色名后面跟的筛选(`长离01` / `长离0链`); 整串本身是角色名或别名时不拆。"""
    from .name_convert import char_name_to_char_id

    m = _TRAILING_COND_RE.search(char)
    if not m or m.start() == 0 or char_name_to_char_id(char):
        return char, RankCond()
    return char[: m.start()], parse_rank_cond(m.group(0))


def signature_hint(cond: RankCond, char_id: str, char_name: str) -> Optional[str]:
    """要求专武谐振阶但角色没有专武时给提示。"""
    from .custom_weight import signature_weapon

    if not cond.signature_reson or signature_weapon(char_id):
        return None
    return f"[鸣潮] {char_name}没有专武，只能按共鸣链筛选，如【{cond.chain}链】"
