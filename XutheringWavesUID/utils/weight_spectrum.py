"""词条频谱(同权重站): 每类副词条满档单条收益 / 满档暴伤, 附 S/A/B 档。"""

SPEC_COLOR = {"s": (234, 183, 4), "a": (185, 106, 217), "b": (22, 145, 121), "": (130, 136, 140)}

_SUB_MAX = {"攻击%": 11.6, "生命%": 11.6, "防御%": 14.7, "暴击": 10.5, "暴击伤害": 21.0, "技能伤害加成": 11.6, "共鸣效率": 12.4}
_CD_BASE = 21.0
_BANDS = [("暴击", "暴击", "暴击"), ("暴击伤害", "暴伤", "暴击伤害"), ("攻击%", "攻击", "攻击"), ("生命%", "生命", "生命"), ("防御%", "防御", "防御")]
_SKILLS = [("普攻伤害加成", "普攻"), ("重击伤害加成", "重击"), ("共鸣技能伤害加成", "共技"), ("共鸣解放伤害加成", "解放")]


def spectrum(calc) -> list:
    """[(标签, 值, 档位 s/a/b/空字符串)], 共 10 项。"""
    sub = calc.get("sub_props") or {}
    skill = list(calc.get("skill_weight") or []) + [0, 0, 0, 0]
    grade = calc.get("grade") or {}

    def level(name: str) -> str:
        n = name.replace("百分比", "").replace("%", "")
        return next((lv for lv in ("s", "a", "b") if n in (grade.get(f"valid_{lv}") or [])), "")

    def value(key: str, ratio: float = 1.0) -> float:
        return float(sub.get(key) or 0) * float(ratio or 0) * _SUB_MAX[key] / _CD_BASE

    bands = [(label, value(key), level(name)) for key, label, name in _BANDS]
    bands += [(label, value("技能伤害加成", skill[i]), level(name)) for i, (name, label) in enumerate(_SKILLS)]
    bands.append(("共效", value("共鸣效率"), level("共鸣效率")))
    return bands
