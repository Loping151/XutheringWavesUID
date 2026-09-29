import sys
import types
from typing import List, Union, Optional

from gsuid_core.logger import logger

from .damage import DamageAttribute

# 跨命名空间共享: 锚定到 sys.modules 防止 abstract.py 在新命名空间重 exec 时
# 五个 Register 子类拿到全新空 dict。
_STATE_KEY = "__waves_register_state__"
_state = sys.modules.get(_STATE_KEY)
if _state is None:
    _state = types.SimpleNamespace(maps={})
    sys.modules[_STATE_KEY] = _state  # type: ignore[assignment]
_REGISTRY = _state.maps


def _shared_map(cls_name):
    return _REGISTRY.setdefault(cls_name, {})


class WavesRegister(object):
    _id_cls_map = _shared_map("WavesRegister")

    @classmethod
    def find_class(cls, _id):
        return cls._id_cls_map.get(_id)

    @classmethod
    def register_class(cls, _id, _clz):
        if _clz is None:
            return
        if isinstance(_clz, (list, dict)) and not _clz:
            return
        cls._id_cls_map[_id] = _clz


class WavesWeaponRegister(WavesRegister):
    _id_cls_map = _shared_map("WavesWeaponRegister")


class WavesEchoRegister(WavesRegister):
    _id_cls_map = _shared_map("WavesEchoRegister")


class WavesCharRegister(WavesRegister):
    _id_cls_map = _shared_map("WavesCharRegister")


class DamageDetailRegister(WavesRegister):
    _id_cls_map = _shared_map("DamageDetailRegister")


class DamageRankRegister(WavesRegister):
    _id_cls_map = _shared_map("DamageRankRegister")


class ScoreDetailRegister(WavesRegister):
    _id_cls_map = _shared_map("ScoreDetailRegister")


class WeaponAbstract(object):
    id = None
    type = None
    name = None

    def __init__(
        self,
        weapon_id: Union[str, int],
        weapon_level: int,
        weapon_breach: Union[int, None] = None,
        weapon_reson_level: int = 1,
    ):
        from ..ascension.weapon import (
            WavesWeaponResult,
            get_weapon_detail,
        )

        weapon_detail: WavesWeaponResult = get_weapon_detail(weapon_id, weapon_level, weapon_breach, weapon_reson_level)
        self.weapon_id = weapon_id
        self.weapon_level = weapon_level
        self.weapon_breach = weapon_breach
        self.weapon_reson_level = weapon_reson_level
        self.weapon_detail: WavesWeaponResult = weapon_detail

    def do_action(
        self,
        func_list: Union[List[str], str],
        attr: DamageAttribute,
        isGroup: bool = False,
    ):
        if isinstance(func_list, str):
            func_list = [func_list]

        if isGroup:
            func_list.append("cast_variation")

        if attr.env_spectro:
            func_list.append("env_spectro")

        if attr.env_aero_erosion:
            func_list.append("env_aero_erosion")

        if attr.env_havoc_bane:
            func_list.append("env_havoc_bane")

        if attr.env_fusion_burst:
            func_list.append("env_fusion_burst")

        if attr.env_glacio_chafe:
            func_list.append("env_glacio_chafe")

        if attr.env_tune_rupture:
            func_list.append("env_tune_rupture")

        if attr.env_tune_strain:
            func_list.append("env_tune_strain")

        if attr.env_tune_shifting():
            func_list.append("env_tune_shifting")

        if attr.env_unison:
            func_list.append("env_unison")

        if attr.trigger_shield:
            func_list.append("trigger_shield")

        func_list.append("cast_phantom")

        func_list = [x for i, x in enumerate(func_list) if func_list.index(x) == i]

        for func_name in func_list:
            method = getattr(self, func_name, None)
            if callable(method):
                if method(attr, isGroup):
                    return

    def get_title(self):
        return f"{self.name}-{self.weapon_detail.get_resonLevel_name()}"

    def param(self, param):
        return self.weapon_detail.param[param][min(self.weapon_reson_level, len(self.weapon_detail.param[param])) - 1]

    def buff(self, attr: DamageAttribute, isGroup: bool = False):
        """buff"""
        pass

    def damage(self, attr: DamageAttribute, isGroup: bool = False):
        """造成伤害"""
        pass

    def cast_attack(self, attr: DamageAttribute, isGroup: bool = False):
        """施放普攻"""
        pass

    def cast_hit(self, attr: DamageAttribute, isGroup: bool = False):
        """施放重击"""
        pass

    def cast_skill(self, attr: DamageAttribute, isGroup: bool = False):
        """施放共鸣技能"""
        pass

    def cast_liberation(self, attr: DamageAttribute, isGroup: bool = False):
        """施放共鸣解放"""
        pass

    def cast_phantom(self, attr: DamageAttribute, isGroup: bool = False):
        """施放声骸技能"""
        pass

    def cast_dodge_counter(self, attr: DamageAttribute, isGroup: bool = False):
        """施放闪避反击"""
        pass

    def cast_variation(self, attr: DamageAttribute, isGroup: bool = False):
        """施放变奏技能"""
        pass

    def cast_tunebreak(self, attr: DamageAttribute, isGroup: bool = False):
        """施放谐度破坏技"""
        pass

    def cast_fusion_burst(self, attr: DamageAttribute, isGroup: bool = False):
        """施加聚爆效应"""
        pass

    def cast_tune_strain(self, attr: DamageAttribute, isGroup: bool = False):
        """施加集谐·偏移"""
        pass

    def skill_create_healing(self, attr: DamageAttribute, isGroup: bool = False):
        """共鸣技能造成治疗"""
        pass

    def cast_unison(self, attr: DamageAttribute, isGroup: bool = False):
        """获得同奏"""
        pass

    def cast_concerto(self, attr: DamageAttribute, isGroup: bool = False):
        """消耗协奏能量"""
        pass

    def env_unison(self, attr: DamageAttribute, isGroup: bool = False):
        """同奏"""
        pass

    def env_spectro(self, attr: DamageAttribute, isGroup: bool = False):
        """光噪效应"""
        pass

    def env_aero_erosion(self, attr: DamageAttribute, isGroup: bool = False):
        """风蚀效应"""
        pass

    def env_havoc_bane(self, attr: DamageAttribute, isGroup: bool = False):
        """虚湮效应"""
        pass

    def env_fusion_burst(self, attr: DamageAttribute, isGroup: bool = False):
        """聚爆效应"""
        pass

    def env_glacio_chafe(self, attr: DamageAttribute, isGroup: bool = False):
        """霜渐效应"""
        pass

    def env_tune_shifting(self, attr: DamageAttribute, isGroup: bool = False):
        """具有偏移"""
        pass
    
    def env_tune_rupture(self, attr: DamageAttribute, isGroup: bool = False):
        """震谐·偏移"""
        pass
    
    def env_tune_strain(self, attr: DamageAttribute, isGroup: bool = False):
        """集谐·偏移"""
        pass

    def trigger_shield(self, attr: DamageAttribute, isGroup: bool = False):
        """触发护盾"""
        pass

    def cast_healing(self, attr: DamageAttribute, isGroup: bool = False):
        """施放治疗"""
        pass

    def cast_extension(self, attr: DamageAttribute, isGroup: bool = False):
        """施放延奏技能"""
        pass


class EchoAbstract(object):
    name = None
    id = None
    cost = None

    def do_echo(self, attr: DamageAttribute, isGroup: bool = False):
        self.damage(attr, isGroup)

    def damage(self, attr: DamageAttribute, isGroup: bool = False):
        """造成伤害"""
        pass

    def do_equipment_first(self, role_id: int):
        """首位装备"""
        return {}


class CharAbstract(object):
    name = None
    id: Optional[int] = None
    starLevel = None

    def do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """
        获得buff

        :param attr: 人物伤害属性
        :param chain: 命座
        :param resonLevel: 武器谐振
        :param isGroup: 是否组队

        """
        attr.add_teammate(self.id)
        self._do_buff(attr, chain, resonLevel, isGroup)

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """
        获得buff

        :param attr: 人物伤害属性
        :param chain: 命座
        :param resonLevel: 武器谐振
        :param isGroup: 是否组队

        """
        pass
