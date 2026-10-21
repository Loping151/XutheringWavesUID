import asyncio
import math
from contextlib import contextmanager
from typing import TYPE_CHECKING, List, Optional, Tuple

from pydantic import BaseModel

from gsuid_core.logger import logger

from .calculate import get_calc_map, get_builtin_calc_map, calc_phantom_entry, calc_phantom_score, get_total_score_bg
from .damage.utils import Hack_Shifting_Role_Ids, comma_separated_number
from .char_info_utils import get_all_role_detail_info
from .damage.abstract import DamageRankRegister, ScoreDetailRegister
from .damage.modal import get_role_modal, get_modal_name
from .api.model import RoleDetailData
from .ascension.sonata import detect_combo_sonata
from .score import ScoreReport

if TYPE_CHECKING:
    from .calc import WuWaCalc


def is_custom_temp(calc_temp) -> bool:
    return isinstance(calc_temp, dict) and bool(calc_temp.get("_cw_id"))


@contextmanager
def builtin_calc_temp(calc, role_detail: RoleDetailData):
    """临时把 calc.calc_temp 换成内置权重。"""
    saved = calc.calc_temp
    if is_custom_temp(saved):
        calc.calc_temp = get_builtin_calc_map(
            calc.phantom_card, role_detail.role.roleName, role_detail.role.roleId, get_role_modal(role_detail)
        )
    try:
        yield
    finally:
        calc.calc_temp = saved


def phantom_total(role_detail: RoleDetailData, calc_temp) -> float:
    """面板口径的声骸总分: 单件封顶 50, 总分封顶 250。"""
    total = 0.0
    pd = role_detail.phantomData
    for _phantom in (pd.equipPhantomList if pd else None) or []:
        if _phantom and _phantom.phantomProp:
            _score, _ = calc_phantom_score(role_detail.role.roleId, _phantom.get_props(), _phantom.cost, calc_temp)
            total += 50.0 if _score > 49.95 else _score
    return round(min(total, 250.0), 2)


def overall_report(calc, role_detail: RoleDetailData) -> Optional[ScoreReport]:
    """综合评分 (始终按内置权重); calc 需已备好 phantom_card / calc_temp。未接入评分的角色返回 None。"""
    scoreDetail = ScoreDetailRegister.find_class(str(role_detail.role.roleId))
    if not scoreDetail:
        return None
    score_calc = scoreDetail[0] if isinstance(scoreDetail, list) else scoreDetail
    setattr(calc, "_score_title", score_calc.get("title", f"综合评分-{role_detail.role.roleName}"))
    with builtin_calc_temp(calc, role_detail):
        return score_calc["func"](calc, role_detail)


class WavesPhantomProp(BaseModel):
    name: str  # 词条名 (Props.attributeName)
    value: str  # 词条值 (Props.attributeValue)
    score: float = 0  # 单词条分数


class WavesPhantomRank(BaseModel):
    phantom_id: int  # 声骸id
    name: str  # 声骸名
    icon_url: str  # 声骸图标
    cost: int
    level: int
    set: str  # 套装名
    main_props: List[WavesPhantomProp] = []
    sub_props: List[WavesPhantomProp] = []
    score: float  # 单声骸分数
    grade: str  # 单声骸评级


class WavesCharRank(BaseModel):
    roleId: int  # 角色id
    roleName: str  # 角色名字
    starLevel: int  # 角色星级
    level: int  # 角色等级
    chain: int  # 命座
    chainName: str  # 命座
    score: float  # 角色评分
    score_bg: str  # 评分背景
    overall_score: float = 0.0  # 综合评分
    expected_damage: Optional[float]  # 期望伤害

    weaponId: int  # 武器id
    weaponLevel: int  # 武器等级
    weaponResonLevel: int  # 武器共鸣等级
    sonataName: str  # 合鸣效果
    expected_name: str  # 期望伤害名字
    modal: str = ""  # 模态 key (无模态角色为空)
    modal_name: str = ""
    phantoms: Optional[List[WavesPhantomRank]] = None  # 单声骸评分明细 (仅有效套装时上传)
    weight_id: str = ""  # 自定义权重 ID (仅展示, 不上传)

    def to_rank_dict(self):
        data = {
            "char_id": self.roleId,
            "level": self.level,
            "chain": self.chain,
            "weapon_id": self.weaponId,
            "weapon_level": self.weaponLevel,
            "weapon_reson_level": self.weaponResonLevel,
            "sonata_name": self.sonataName,
            "phantom_score": self.score,
            "phantom_score_bg": self.score_bg,
            "overall_score": self.overall_score,
            "expected_damage": self.expected_damage if self.expected_damage else 0,
            "expected_name": self.expected_name if self.expected_name else "",
            "modal": self.modal,
            "modal_name": self.modal_name,
        }
        if self.phantoms:
            data["phantoms"] = [p.model_dump() for p in self.phantoms]
        return data


async def get_waves_char_rank(uid, all_role_detail, need_expected_damage=False, need_overall_score=False):
    if not all_role_detail:
        all_role_detail = await get_all_role_detail_info(uid)
    return _compute_char_rank(all_role_detail, need_expected_damage, need_overall_score)


def _compute_one_char_rank(role_detail, need_expected_damage=False, need_overall_score=False):
    """单角色评分计算; role_detail 可为 dict 或 RoleDetailData。

    入参/返回值均可 pickle, 供 gsuid_core.pool.to_process 丢进程池并行调用。
    """
    from .calc import WuWaCalc
    if not isinstance(role_detail, RoleDetailData):
        role_detail = RoleDetailData(**role_detail)

    phantom_score = 0
    overall_score = 0.0
    calc: WuWaCalc = WuWaCalc(role_detail)
    expected_damage = None

    sonataName = ""
    expected_name = ""
    phantom_ranks: List[WavesPhantomRank] = []
    if role_detail.phantomData and role_detail.phantomData.equipPhantomList:
        equipPhantomList = role_detail.phantomData.equipPhantomList

        calc.phantom_pre = calc.prepare_phantom()
        calc.phantom_card = calc.enhance_summation_phantom_value(calc.phantom_pre)
        calc.calc_temp = get_calc_map(
            calc.phantom_card,
            role_detail.role.roleName,
            role_detail.role.roleId,
            get_role_modal(role_detail),
            role=role_detail,
        )
        for i, _phantom in enumerate(equipPhantomList):
            if not (_phantom and _phantom.phantomProp):
                continue
            props = _phantom.get_props()
            _score, _bg = calc_phantom_score(role_detail.role.roleId, props, _phantom.cost, calc.calc_temp)
            phantom_score += _score
            # 声骸总排行仅统计满 5 副词条的声骸
            if len(_phantom.subProps or []) != 5:
                continue
            _char_attr = role_detail.role.attributeName or ""
            _scored_props = []
            for _pi, _prop in enumerate(props):
                _entry_score = 0.0
                if calc.calc_temp:
                    try:
                        _, _entry_score = calc_phantom_entry(
                            _pi, _prop, _phantom.cost, calc.calc_temp, _char_attr
                        )
                    except Exception as e:
                        logger.debug(f"[鸣潮·评分] 单词条分数计算失败: {e}")
                _scored_props.append(
                    {
                        "name": _prop.attributeName,
                        "value": _prop.attributeValue,
                        "score": _entry_score,
                    }
                )
            _main_len = len(_phantom.mainProps or [])
            phantom_ranks.append(
                WavesPhantomRank(
                    **{
                        "phantom_id": _phantom.phantomProp.phantomId,
                        "name": _phantom.phantomProp.name,
                        "icon_url": _phantom.phantomProp.iconUrl,
                        "cost": _phantom.cost,
                        "level": _phantom.level,
                        "set": _phantom.fetterDetail.name,
                        "main_props": _scored_props[:_main_len],
                        "sub_props": _scored_props[_main_len:],
                        "score": _score,
                        "grade": _bg,
                    }
                )
            )

        if need_expected_damage:
            rankDetail = DamageRankRegister.find_class(str(role_detail.role.roleId))
            if rankDetail:
                calc.role_card = calc.enhance_summation_card_value(calc.phantom_card)
                calc.damageAttribute = calc.card_sort_map_to_attribute(calc.role_card)
                _, expected_damage = rankDetail["func"](calc.damageAttribute, role_detail)
                expected_damage = comma_separated_number(expected_damage)
                expected_name = rankDetail["title"]

        if need_overall_score:
            try:
                score_report = overall_report(calc, role_detail)
                if score_report is not None:
                    overall_score = round(float(score_report.score), 2)
            except Exception as e:
                logger.debug(f"[鸣潮·评分] 综合评分计算失败 {role_detail.role.roleId}: {e}")

        for ph_detail in calc.phantom_pre.get("ph_detail", []):
            if ph_detail.get("ph_name") and ph_detail.get("ph_num") == 5:
                sonataName = ph_detail["ph_name"]
                break

            if ph_detail.get("ph_name") and ph_detail.get("isFull"):
                # 1件套(碎梦亡鬼之魇)仅露西/丽贝卡算完整套装, 其他角色需凑齐3/5件
                if ph_detail.get("ph_num") == 1 and role_detail.role.roleId not in Hack_Shifting_Role_Ids:
                    continue
                sonataName = ph_detail["ph_name"]
                break

        combo_sonata = detect_combo_sonata(role_detail.role.roleId, calc.phantom_pre.get("ph_detail", []))
        if combo_sonata:
            sonataName = combo_sonata

    phantom_score = round(phantom_score, 2)
    modal = get_role_modal(role_detail)
    return WavesCharRank(
        **{
            "roleId": role_detail.role.roleId,
            "roleName": role_detail.role.roleName,
            "starLevel": role_detail.role.starLevel,
            "level": role_detail.level,
            "chain": role_detail.get_chain_num(),
            "chainName": role_detail.get_chain_name(),
            "score": phantom_score,
            "score_bg": get_total_score_bg(role_detail.role.roleName, phantom_score, calc.calc_temp),
            "overall_score": overall_score,
            "expected_damage": expected_damage,
            "weaponId": role_detail.weaponData.weapon.weaponId,
            "weaponLevel": role_detail.weaponData.level,
            "weaponResonLevel": role_detail.weaponData.resonLevel,
            "sonataName": sonataName,
            "expected_name": expected_name,
            "modal": modal,
            "modal_name": get_modal_name(role_detail.role.roleId, modal),
            "phantoms": phantom_ranks if sonataName else None,
            "weight_id": (calc.calc_temp or {}).get("_cw_id", "") if isinstance(calc.calc_temp, dict) else "",
        }
    )


def _compute_char_rank(all_role_detail, need_expected_damage=False, need_overall_score=False):
    if isinstance(all_role_detail, dict):
        temp = all_role_detail.values()
    else:
        temp = all_role_detail if all_role_detail else []
    return [
        _compute_one_char_rank(role_detail, need_expected_damage, need_overall_score)
        for role_detail in temp
    ]


# ─── 刷新前后对比: 声骸评分涨而综合评分跌时, 按乘区变化指出溢出 / 被挤占的乘区 ───

PHANTOM_MIN_GAIN = 1.0
OVERALL_MIN_DROP = 1.0
ZONE_MIN_SHIFT = 0.005
CRIT_IMBALANCE = 1.5
_NOTE_ZONES = (("暴击率", "双爆"), ("共鸣效率", "共效"))


def _builtin_panel(role_detail: RoleDetailData) -> Tuple["WuWaCalc", float]:
    from .calc import WuWaCalc

    calc = WuWaCalc(role_detail)
    calc.phantom_pre = calc.prepare_phantom()
    calc.phantom_card = calc.enhance_summation_phantom_value(calc.phantom_pre)
    calc.calc_temp = get_builtin_calc_map(
        calc.phantom_card, role_detail.role.roleName, role_detail.role.roleId, get_role_modal(role_detail)
    )
    calc.role_card = calc.enhance_summation_card_value(calc.phantom_card)
    return calc, phantom_total(role_detail, calc.calc_temp)


def _crit_balance(report: ScoreReport) -> str:
    cr, cd = report.partials.get("暴击"), report.partials.get("暴击伤害")
    if cr is None or not cd:
        return ""
    if cr > cd * CRIT_IMBALANCE:
        return "暴击偏低, 暴击伤害偏高"
    if cr * CRIT_IMBALANCE < cd:
        return "暴击偏高, 暴击伤害偏低"
    return ""


def _note_zone(note: str) -> str:
    return next((z for prefix, z in _NOTE_ZONES if note.startswith(prefix)), "")


def compose_drift_advice(char_name: str, phantom_gain: float, prev: ScoreReport, cur: ScoreReport) -> str:
    shifts = {z: math.log(v / prev.zones[z]) for z, v in cur.zones.items() if prev.zones.get(z)}
    moved = {z: s for z, s in shifts.items() if abs(s) >= ZONE_MIN_SHIFT}
    gains = sorted((z for z in moved if moved[z] > 0), key=moved.__getitem__, reverse=True)
    losses = sorted((z for z in moved if moved[z] < 0), key=moved.__getitem__)

    reasons = []
    if gains and losses:
        # 上涨乘区的达成率高于所有下跌乘区 → 相对饱和
        ceiling = max(cur.zones[z] for z in losses)
        saturated = [z for z in gains if cur.zones[z] > ceiling]
        if saturated:
            reasons.append(f"{'、'.join(saturated)}区相对饱和")
    crit_tag = _crit_balance(cur)
    if "双爆" in moved and crit_tag:
        reasons.append(crit_tag)

    lines = [f"[鸣潮] {char_name} 声骸评分 +{phantom_gain:.1f}, 综合评分 {cur.score - prev.score:.1f}"]
    if moved:
        lines.append("乘区变化: " + ", ".join(f"{z} {math.expm1(moved[z]):+.1%}" for z in gains + losses))
    if reasons:
        lines.append("可能原因: " + "; ".join(reasons))
    lines.extend(n for n in cur.notes if n not in prev.notes or _note_zone(n) in moved)
    if cur.partial_max:
        lines.append(f"建议提升词条方向: {cur.partial_max[0]}")
    return "\n".join(lines)


def _setup(d: RoleDetailData):
    w = d.weaponData
    return (d.get_chain_num(), w.weapon.weaponId if w and w.weapon else None, w.resonLevel if w else None)


async def drift_advice(
    char_name: str, prev_detail: RoleDetailData, cur_detail: RoleDetailData, phantom: float, report: ScoreReport
) -> Optional[str]:
    """phantom / report 为刷新后面板的内置权重声骸总分与综合评分; 声骸评分涨了才重算旧面板综合评分。
    换了武器/谐振/共鸣链的跌分不是乘区问题, 不提示。"""
    if _setup(prev_detail) != _setup(cur_detail):
        return None
    calc, prev_phantom = await asyncio.to_thread(_builtin_panel, prev_detail)
    if phantom - prev_phantom < PHANTOM_MIN_GAIN:
        return None
    prev_report = await asyncio.to_thread(overall_report, calc, prev_detail)
    if prev_report is None or prev_report.score - report.score < OVERALL_MIN_DROP:
        return None
    return compose_drift_advice(char_name, phantom - prev_phantom, prev_report, report)
