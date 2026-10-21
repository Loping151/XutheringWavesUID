import sys
import types
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, Union

# 锚定类对象: 重 exec 时复用首次定义的类, 保持身份一致
_STATE_KEY = "__waves_score_state__"
_state = sys.modules.get(_STATE_KEY)
if _state is None:
    _state = types.SimpleNamespace(classes={})
    sys.modules[_STATE_KEY] = _state  # type: ignore[assignment]
_SHARED_CLASSES = _state.classes

ApplyBuffsFunc = Callable[[Dict[str, Any], Any], None]


CharTemplate = Literal["temp_atk", "temp_life", "temp_def"]


@dataclass
class EchoSlotConfig:
    cost: int
    main_options: List[str]
    sub_options: List[str]


def make_43311(sub_options: List[str], cost4_main: Optional[List[str]] = None,
               cost3_main: Optional[List[str]] = None) -> List["EchoSlotConfig"]:
    """构造标准 43311 cost 布局 (cost4 / cost3×2 含元素加成 / cost1×2)。"""
    c4 = list(cost4_main) if cost4_main else ["暴击", "暴击伤害", "攻击"]
    c3 = list(cost3_main) if cost3_main else ["属性伤害加成", "攻击%"]
    return [
        EchoSlotConfig(cost=4, main_options=c4, sub_options=sub_options),
        EchoSlotConfig(cost=3, main_options=c3, sub_options=sub_options),
        EchoSlotConfig(cost=3, main_options=c3, sub_options=sub_options),
        EchoSlotConfig(cost=1, main_options=["攻击%"], sub_options=sub_options),
        EchoSlotConfig(cost=1, main_options=["攻击%"], sub_options=sub_options),
    ]


def make_44111(sub_options: List[str], cost4_main: Optional[List[str]] = None) -> List["EchoSlotConfig"]:
    """构造 44111 cost 布局 (双 cost4 主词条, 牺牲 1 费), 供 slot_config_alts 用。"""
    c4 = list(cost4_main) if cost4_main else ["暴击", "暴击伤害", "攻击"]
    return [
        EchoSlotConfig(cost=4, main_options=c4, sub_options=sub_options),
        EchoSlotConfig(cost=4, main_options=c4, sub_options=sub_options),
        EchoSlotConfig(cost=1, main_options=["攻击%"], sub_options=sub_options),
        EchoSlotConfig(cost=1, main_options=["攻击%"], sub_options=sub_options),
        EchoSlotConfig(cost=1, main_options=["攻击%"], sub_options=sub_options),
    ]


DEFAULT_ENERGY_RECOMMENDED = 120.0
DEFAULT_W_LOW = 0.7
DEFAULT_W_MID = 0.8
DEFAULT_W_PEAK = 1.025


@dataclass
class ScoreHyperParams:
    energy_recommended: float = DEFAULT_ENERGY_RECOMMENDED
    energy_low_anchor: Optional[float] = None
    energy_high_anchor: Optional[float] = None
    energy_w_floor: float = DEFAULT_W_LOW
    energy_w_mid: float = DEFAULT_W_MID
    energy_w_peak: float = DEFAULT_W_PEAK
    slot_config: Optional[List[EchoSlotConfig]] = None
    # 备选 cost 布局: 优化器会把 slot_config 与这里每一组都各搜一遍, 取分最高的。
    # 用于"有时 43311、有时 44111"的角色 —— 例如主 slot_config 给 43311(cost3 元素加成),
    # 再在此追加一组 44111(双 cost4 暴击/暴伤, 牺牲 1 费换主词条)。每组都是完整 5 槽 EchoSlotConfig。
    slot_config_alts: Optional[List[List[EchoSlotConfig]]] = None
    template_override: Optional[CharTemplate] = None
    apply_buffs: Optional[ApplyBuffsFunc] = None
    skill_weight_overrides: Optional[Dict[int, List[float]]] = None
    # {chain_threshold: [普攻, 重击, 共鸣技能, 共鸣解放, 其它, 声骸技能]}, 取 ≤ 当前命座的最大键。
    # idx4=其它(变奏/延奏等, 不吃技能加成); idx5=声骸技能(独立加成区, 吃 char_damage 门控套装/武器
    # buff + 攻击 + 属性)。旧 5 元素模板自动补 0 (声骸技能段=0), 向后兼容。

    # ── 自动套装/声骸/武器增益的战斗场景 ──
    # 循环 cast 列表 (可选覆盖)。默认 None = 所有通用招式段 (四种伤害+声骸技能+闪避反击+变奏+
    # 谐度破坏), 这些动作所有角色都能做, 评分假设玩家可刻意补一段来触发对应武器 buff。一般不用传。
    score_damage_func: Optional[List[str]] = None
    # 评分按组队环境取增益 (变奏登场类套装才生效); 个别纯单人角色可设 False
    score_is_group: bool = True
    # (attr, role) -> None: 在此 attr.set_env_*() 设置该角色具备的效应/偏移 (震谐/集谐/光噪…);
    # 没有效应能力的角色不传 (这才是真正按角色配置的)。char_damage / template 由核心负责, 勿设。
    score_attr_setup: Optional[Callable[[Any, Any], None]] = None

    def resolved_anchors(self) -> Tuple[float, float, float]:
        R = self.energy_recommended
        p_low = self.energy_low_anchor if self.energy_low_anchor is not None else R - 10
        p_high = self.energy_high_anchor if self.energy_high_anchor is not None else R + 5
        return p_low, R, p_high


HyperparamsLike = Union[ScoreHyperParams, Callable[[Any], ScoreHyperParams], None]


@dataclass
class OptimalSlot:
    cost: int
    main1_name: str
    main1_value_pct: float
    main2_name: str
    main2_value_flat: float
    subs: List[Tuple[str, float]] = field(default_factory=list)


@dataclass
class ScoreReport:
    score: float
    raw: float
    max_raw: float
    partials: Dict[str, float] = field(default_factory=dict)
    partial_max: Optional[Tuple[str, float]] = None  # 提升收益最高 (边际)
    partial_min: Optional[Tuple[str, float]] = None
    gap_max: Optional[Tuple[str, float]] = None      # 离最优最远 (落后档数)
    improve_dirs: List[str] = field(default_factory=list)  # 推荐方向 (收益最高 + 离最优最远, 去重)
    main_advice: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    breakdown: List[str] = field(default_factory=list)
    best_card: Dict[str, Any] = field(default_factory=dict)
    best_loadout: List[OptimalSlot] = field(default_factory=list)
    zones: Dict[str, float] = field(default_factory=dict)  # 各乘区 当前/最优 (攻击|生命|防御/双爆/加成/共效)

    def format(self, title: str = "综合评分") -> str:
        lines = [f"[鸣潮·评分] {title}"]
        lines.append(f"  得分: {self.score:.1f} / 150  (raw={self.raw:,.1f} / max={self.max_raw:,.1f})")
        if self.partial_max:
            lines.append(f"  最优提升: {self.partial_max[0]} (+{self.partial_max[1]:.3f}/半档)")
        if self.partial_min:
            lines.append(f"  最低收益: {self.partial_min[0]} (+{self.partial_min[1]:.3f}/半档)")
        if self.partials:
            ranked = sorted(self.partials.items(), key=lambda kv: kv[1], reverse=True)
            detail = ", ".join(f"{k}=+{v:.3f}" for k, v in ranked)
            lines.append(f"  全梯度: {detail}")
        if self.zones:
            lines.append("  乘区达成: " + ", ".join(f"{k}={v:.1%}" for k, v in self.zones.items()))
        if self.main_advice:
            lines.append("  主词条建议:")
            for s in self.main_advice:
                lines.append(f"    - {s}")
        if self.notes:
            lines.append("  备注:")
            for s in self.notes:
                lines.append(f"    - {s}")
        if self.breakdown:
            lines.append("  公式拆分:")
            for s in self.breakdown:
                lines.append(f"    {s}")
        return "\n".join(lines)


# 综合评分等级阈值: 125 sss / 115 ss / 105 s / 90 a / 72 b / 其余 c
_PANEL_GRADE_THRESHOLDS = (
    (125.0, "sss"),
    (115.0, "ss"),
    (105.0, "s"),
    (90.0,  "a"),
    (72.0,  "b"),
)


def get_panel_score_grade(score: float) -> str:
    for threshold, label in _PANEL_GRADE_THRESHOLDS:
        if score >= threshold:
            return label
    return "c"


for _cls_name in ("EchoSlotConfig", "ScoreHyperParams", "OptimalSlot", "ScoreReport", "HyperparamsLike"):
    if _cls_name in _SHARED_CLASSES:
        globals()[_cls_name] = _SHARED_CLASSES[_cls_name]
    else:
        _SHARED_CLASSES[_cls_name] = globals()[_cls_name]
