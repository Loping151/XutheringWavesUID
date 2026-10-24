"""角色名解析: 先精确 alias, 再 fuzzy 取首个能命中的候选作为"自动猜"。

设计目标: 把"是否命中""错误文案""图文包装"封装到一个结果对象, 让 call site
只需 res.ok / res.fail_msg() / res.wrap(im) 三个调用, 不再各自做样板。

防回显: 完全无匹配时, fail_msg 不会把用户原串塞进【】里; fuzzy 命中时
回显的也只是已验证的规范名。这样用户构造的特殊字符不会出现在机器人回复中。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

from . import name_convert
from .name_convert import char_name_to_char_id, ensure_data_loaded
from .fuzzy_match import fuzzy_suggest

_REFRESH_RE = re.compile("刷新|更新")


@dataclass(frozen=True)
class CharResolution:
    matched: Optional[str]
    suggestions: List[str] = field(default_factory=list)
    fuzzy_used: bool = False

    @property
    def ok(self) -> bool:
        return self.matched is not None

    def fail_msg(self, prefix: str = "[鸣潮] 未找到指定角色") -> str:
        """无匹配时给用户的提示文案。仅用静态文案 + 已验证的候选, 不回显输入。"""
        if self.suggestions:
            return f"{prefix}。\n你可能想找: {'、'.join(self.suggestions)}"
        return f"{prefix}, 请先检查输入是否正确！"

    def tip_text(self, command: Optional[str] = None) -> Optional[str]:
        """fuzzy 命中时的提示文案; 精确命中或失败时为 None。

        Args:
            command: 完整的规范指令字符串(含 PREFIX, 如 "xw刷新椿面板")。
                     未传则只显示规范角色名。建议传完整指令, 让用户能直接看出
                     该如何输入。
        """
        if not self.fuzzy_used or self.matched is None:
            return None
        body = command if command else self.matched
        return f"[鸣潮] 你可能想查询【{body}】，已执行该指令"

    def wrap(self, im: Any, command: Optional[str] = None) -> Any:
        """fuzzy 命中: 把 tip + 图片打包成单条发送; 精确命中: 原样返回 im。"""
        tip = self.tip_text(command)
        if tip is None:
            return im
        from gsuid_core.segment import MessageSegment
        return [tip, MessageSegment.image(im)]

    def with_tip(self, msg: str, command: Optional[str] = None) -> str:
        """字符串版的 wrap: fuzzy 命中时在前面补一行 tip。"""
        tip = self.tip_text(command)
        if tip is None:
            return msg
        return f"{tip}\n{msg}"


def resolve_char(char_name: Optional[str], top_n: int = 3) -> CharResolution:
    if not char_name:
        return CharResolution(None)

    if char_name_to_char_id(char_name):
        return CharResolution(char_name)
    stripped = _REFRESH_RE.sub("", char_name)
    if stripped and stripped != char_name and char_name_to_char_id(stripped):
        return CharResolution(stripped)

    ensure_data_loaded()
    suggestions = fuzzy_suggest(char_name, name_convert.char_alias_data, top_n=top_n)
    names = [n for n, _ in suggestions]
    for cand in names:
        if char_name_to_char_id(cand):
            return CharResolution(cand, names, fuzzy_used=True)
    return CharResolution(None, names)
