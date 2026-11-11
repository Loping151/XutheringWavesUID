"""挑战 wiki 文案自动高亮（纯函数，输出带 <em> 的 HTML）"""

import re
from typing import Dict

ELEMENTS = "冷凝|热熔|导电|气动|衍射|湮灭"
EFFECT_ELEMENT = {"霜渐": "冷凝", "聚爆": "热熔", "电磁": "导电", "风蚀": "气动", "光噪": "衍射", "虚湮": "湮灭"}
SKILLS = "普攻|重击|共鸣技能|共鸣解放|共鸣回路|变奏技能|延奏技能|声骸技能|协同攻击|下落攻击|空中攻击|闪避反击|变奏|延奏|同奏|声骸"

_PATTERN = re.compile(
    "|".join(
        (
            rf"(?P<element>(?:{ELEMENTS})(?:伤害加成|伤害|抗性)?)",
            rf"(?P<effect>(?:{'|'.join(EFFECT_ELEMENT)})效应)",
            r"(?P<num>\d+(?:\.\d+)?%)",
            rf"(?P<kw>(?:{SKILLS})(?:伤害加成|伤害)?"
            r"|全属性(?:伤害加成|伤害|抗性)?|异常效应"
            r"|[一-龥]{2}[·・](?:偏移|干涉)(?:状态)?|谐度破坏(?:伤害)?|震谐(?:伤害)?|偏谐值|共振度"
            r"|暴击伤害|暴击率|暴击|护盾|失谐状态"
            r"|(?<=附加)[^，。；、时%<>]{2,10}?(?=状态时|时)"
            r"|(?<=[入于])[^，。；、的时%<>]{2,6}?状态)",
        )
    )
)
_TAG = re.compile(r"(<[^>]+>)")


def highlight(text: str, colors: Dict[str, str]) -> str:
    """colors: 属性名 → hex。已有的 HTML 标签原样保留，只处理标签外文本"""

    def repl(m: re.Match) -> str:
        kind, word = m.lastgroup, m.group()
        if kind == "num":
            return f'<em class="hl-num">{word}</em>'
        if kind == "kw":
            return f'<em class="hl-kw">{word}</em>'
        element = EFFECT_ELEMENT[word[:2]] if kind == "effect" else word[:2]
        return f'<em class="hl-el" style="--el: {colors.get(element, "#b4b4b4")};">{word}</em>'

    return "".join(part if part.startswith("<") else _PATTERN.sub(repl, part) for part in _TAG.split(str(text or "")))
