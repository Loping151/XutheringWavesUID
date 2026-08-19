from .utils import (
    CHAR_ATTR_VOID,
    CHAR_ATTR_MOLTEN,
    CHAR_ATTR_SIERRA,
    CHAR_ATTR_SINKING,
    CHAR_ATTR_FREEZING,
    CHAR_ATTR_CELESTIAL,
    Hack_Shifting_Role_Ids,
    Tune_Strain_Role_Ids,
    temp_atk,
    temp_def,
    hit_damage,
    skill_damage,
    attack_damage,
    phantom_damage,
    cast_variation,
    cast_attack,
    liberation_damage,
    Abnormal_Role_Ids,
)
from .damage import DamageAttribute, check_char_id
from .abstract import (
    CharAbstract,
    WavesCharRegister,
    WavesWeaponRegister,
)


class Char_1102(CharAbstract):
    id = 1102
    name = "散华"
    starLevel = 4

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """获得buff"""
        if attr.char_template == temp_atk:
            if chain >= 6:
                title = "散华-六链"
                msg = "队伍中的角色攻击提升20%"
                attr.add_atk_percent(0.2, title, msg)

            title = "散华-合鸣效果-轻云出月"
            msg = "下一个登场的共鸣者攻击提升22.5%"
            attr.add_atk_percent(0.225, title, msg)

        # 无常凶鹭
        title = "散华-声骸技能-无常凶鹭"
        msg = "施放延奏技能，则可使下一个变奏登场的角色伤害提升12%"
        attr.add_dmg_bonus(0.12, title, msg)

        if attack_damage == attr.char_damage:
            title = "散华-延奏技能"
            msg = "下一位登场角色普攻伤害加深38%"
            attr.add_dmg_deepen(0.38, title, msg)


class Char_1103(CharAbstract):
    id = 1103
    name = "白芷"
    starLevel = 4


class Char_1104(CharAbstract):
    id = 1104
    name = "凌阳"
    starLevel = 5


class Char_1105(CharAbstract):
    id = 1105
    name = "折枝"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        if attr.char_template == temp_atk:
            if chain >= 4:
                title = f"{self.name}-四链"
                msg = "折枝施放共鸣解放虚实境趣时，队伍中角色攻击提升20%"
                attr.add_atk_percent(0.2, title, msg)

            title = f"{self.name}-合鸣效果-轻云出月"
            msg = "使用延奏技能后，下一个登场的共鸣者攻击提升22.5%"
            attr.add_atk_percent(0.225, title, msg)

        # 无常凶鹭
        title = f"{self.name}-声骸技能-无常凶鹭"
        msg = "施放延奏技能，则可使下一个变奏登场的角色伤害提升12%"
        attr.add_dmg_bonus(0.12, title, msg)

        if attr.char_attr == CHAR_ATTR_FREEZING:
            title = f"{self.name}-延奏技能"
            msg = "下一位登场角色冷凝伤害加深20%"
            attr.add_dmg_bonus(0.2, title, msg)

        if skill_damage == attr.char_damage:
            title = f"{self.name}-延奏技能"
            msg = "下一位登场角色共鸣技能伤害加深25%"
            attr.add_dmg_deepen(0.25, title, msg)


class Char_1106(CharAbstract):
    id = 1106
    name = "釉瑚"
    starLevel = 4


class Char_1107(CharAbstract):
    id = 1107
    name = "珂莱塔"
    starLevel = 5


class Char_1108(CharAbstract):
    id = 1108
    name = "绯雪"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        # 共鸣回路-万世霜天: 绯雪在编队时, 队伍附加的【霜渐效应】改为【霜冻效应】,
        # 而【霜冻效应】伤害可视为【霜渐效应】伤害, 让队友的霜渐条件 buff 能触发
        attr.set_env_glacio_chafe()
        title = f"{self.name}-共鸣回路-万世霜天"
        msg = "队伍附加【霜冻效应】(可视为【霜渐效应】)"
        attr.add_effect(title, msg)

        # 四链 - 有如苇草浮沉: 施放共鸣技能·常世身、霜罚·白玉切或霜罚·落华时,
        # 附近队伍中所有角色造成的伤害提升 20%, 持续 30 秒
        if chain >= 4:
            title = f"{self.name}-四链"
            msg = "队伍中的角色伤害提升20%"
            attr.add_dmg_bonus(0.2, title, msg)

        # 延奏技能-挽雪照身: 附近队伍中除绯雪以外的角色对拥有【霜渐效应】的敌人
        # 造成的冷凝伤害加深 20%
        if attr.char_attr == CHAR_ATTR_FREEZING:
            title = f"{self.name}-延奏技能-挽雪照身"
            msg = "对拥有【霜渐效应】的敌人冷凝伤害加深20%"
            attr.add_dmg_deepen(0.2, title, msg)

        # 套装-雪落无声之愿(绯雪 5pc): 拥有【落雪】时, 施放延奏技能将清除【落雪】,
        # 使下一个变奏登场角色冷凝伤害提升25%, 持续15秒。
        if attr.char_attr == CHAR_ATTR_FREEZING:
            title = f"{self.name}-套装-雪落无声之愿"
            msg = "施放延奏清除【落雪】, 下一变奏登场角色冷凝伤害+25%"
            attr.add_dmg_bonus(0.25, title, msg)

        # 六链 - 纵使前路永夜无终: 持有 3 层【雪锈】时, 队伍中登场角色一定范围内
        # 的目标受到【霜冻效应】的最终伤害提升 25% (独立乘区, 仅结算霜渐/霜冻效应伤害时生效)
        if chain >= 6 and attr.env_glacio_chafe_deepen:
            title = f"{self.name}-六链"
            msg = "3层【雪锈】, 目标受到【霜冻效应】最终伤害提升25%"
            attr.add_effect_easy_damage(0.25, title, msg)


class Char_1109(CharAbstract):
    id = 1109
    name = "洛瑟菈"
    starLevel = 5

    # 两种共鸣模态的 team buff 按当前结算伤害类型分别作用:
    #   霜渐模态 → 冷凝/霜渐 伤害段; 声骸模态 → 声骸技能伤害段。
    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        # 两模态互斥: DPS 为冷凝 → 霜渐模态; 否则结算声骸技能伤害 → 声骸模态。
        # (冰系角色的声骸技能伤害也归霜渐模态, 不吃声骸 buff)
        if attr.char_attr == CHAR_ATTR_FREEZING:
            attr.set_env_glacio_chafe()

            # 固有技能-慢镜头(霜渐): 目标冷凝抗性降低8%
            title = f"{self.name}-固有技能-慢镜头"
            attr.add_enemy_resistance(-0.08, title, "霜渐模态, 目标冷凝抗性降低8%")

            # 延奏技能-蒙太奇(霜渐): 目标受到【霜渐效应】伤害加深60% (仅结算霜渐效应伤害时)
            if attr.env_glacio_chafe_deepen:
                title = f"{self.name}-延奏技能-蒙太奇"
                attr.add_effect_dmg_deepen(0.6, title, "目标受到【霜渐效应】伤害加深60%")

            # 二链-酣睡的月光(共鸣解放·历历在目, 霜渐模态): 目标受到【霜渐效应】伤害加深80%
            if chain >= 2 and attr.env_glacio_chafe_deepen:
                title = f"{self.name}-二链"
                attr.add_effect_dmg_deepen(0.8, title, "目标受到【霜渐效应】伤害加深80%")

        elif attr.char_damage == phantom_damage:
            # 固有技能-慢镜头(声骸): 队伍中角色声骸技能伤害加成提升25%
            title = f"{self.name}-固有技能-慢镜头"
            attr.add_dmg_bonus(0.25, title, "声骸模态, 声骸技能伤害加成提升25%")

            # 共鸣回路-变焦(声骸): 每层声骸技能暴击伤害+10%, 满4层(铭记上限)假定满层
            title = f"{self.name}-共鸣回路-变焦"
            attr.add_crit_dmg(0.4, title, "声骸模态满4层, 声骸技能暴击伤害提升40%")

            # 延奏技能-蒙太奇(声骸): 下一个登场角色声骸技能伤害加深50%
            title = f"{self.name}-延奏技能-蒙太奇"
            attr.add_dmg_deepen(0.5, title, "下一个登场角色声骸技能伤害加深50%")

            # 二链-酣睡的月光(声骸): 队伍中角色声骸技能伤害加成提升40%
            if chain >= 2:
                title = f"{self.name}-二链"
                attr.add_dmg_bonus(0.4, title, "声骸模态, 声骸技能伤害加成提升40%")

        # 套装-延奏效果 (按当前模态选套装): 冷凝→雪落无声之愿, 否则→轻云出月
        if attr.char_attr == CHAR_ATTR_FREEZING:
            title = f"{self.name}-套装-雪落无声之愿"
            msg = "下一个变奏登场角色冷凝伤害提升25%"
            attr.add_dmg_bonus(0.25, title, msg)

            # 声骸技能-格洛犸图: 施放延奏后, 下一个变奏登场角色冷凝伤害加成提升12%
            title = f"{self.name}-声骸技能-格洛犸图"
            msg = "下一个变奏登场角色冷凝伤害加成提升12%"
            attr.add_dmg_bonus(0.12, title, msg)
        elif attr.char_template == temp_atk:
            title = f"{self.name}-套装-轻云出月"
            msg = "下一个登场角色攻击提升22.5%"
            attr.add_atk_percent(0.225, title, msg)

        # 角色武器-存帧 (21050086): 上方已 set 霜渐 env, 驱动武器把"队伍攻击提升"段作用到队友
        weapon_id = 21050086
        weapon_clz = WavesWeaponRegister.find_class(weapon_id)
        if weapon_clz:
            w = weapon_clz(weapon_id, 90, 6, resonLevel)
            w.do_action(["buff"], attr, isGroup)


class Char_1110(CharAbstract):
    id = 1110
    name = "穗穗"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        # 延奏技能-渌水盈盈: 队伍中的角色全伤害加深25%
        title = f"{self.name}-延奏技能"
        attr.add_dmg_deepen(0.25, title, "队伍中的角色全伤害加深25%")

        # 延奏(消耗≥400芳菲信)-重明照影: 共鸣效率超200%部分转伤害提升, 按上限12%
        title = f"{self.name}-延奏技能-重明照影"
        attr.add_dmg_bonus(0.12, title, "山河水境内持有重明照影, 伤害提升按上限12%")

        # 延奏(消耗≥600芳菲信)-烟岚: 持有烟岚的角色消耗目标【异常效应】或【电磁爆发】层数后攻击提升,
        # 穗穗共效超200%部分转化, 按上限50%。受益者需能消耗层数(如玄翎剑式流转消耗虚湮);
        # 一链变更: 持有烟岚的角色 附加【异常效应】或造成异常效应伤害 也可触发(不再要求消耗层)
        if attr.char_template == temp_atk:
            title = f"{self.name}-延奏技能-烟岚"
            attr.add_atk_percent(0.5, title, "消耗目标【异常效应】层数后, 攻击提升按上限50%")

        # 共鸣解放-山河水境 (水境内队伍角色, 各条均持续15秒且不可叠加):
        # ·为目标附加【光噪/聚爆/霜渐/风蚀效应】或造成对应异常效应伤害后, 对应【异常效应】层数上限+3
        # ·为目标附加【电磁效应】或造成对应异常效应伤害后, 【电磁效应】和【电磁爆发】层数上限+3
        # ·不含【虚湮效应】(虚湮只有下方"消耗后减防减抗"条款)
        title = f"{self.name}-共鸣解放-山河水境"
        msg = "使目标除【虚湮效应】外的【异常效应】层数上限增加3层"
        attr.add_effect(title, msg)
        # 注：这个记得单独写，是几层就是几层，好多加上限还是手动算得了

        # 共鸣解放-山河水境: 消耗目标【虚湮效应】层数后, 自身湮灭伤害无视目标6%防御、
        # 12%湮灭抗性, 持续30秒, 不可叠加 (受益者需能消耗虚湮层)
        if attr.char_attr == CHAR_ATTR_SINKING:
            title = f"{self.name}-共鸣解放-山河水境"
            attr.add_defense_ignore(0.06, title, "消耗【虚湮效应】后, 湮灭伤害无视目标6%防御")
            attr.add_enemy_resistance(-0.12, title, "消耗【虚湮效应】后, 无视目标12%湮灭抗性")

        # 二链: 山河水境内队伍角色触发以下任一后, 该角色暴击伤害提升50%, 持续30秒:
        # ·为目标附加【光噪/聚爆/霜渐/风蚀/电磁效应】或造成对应异常效应伤害
        # ·消耗目标【虚湮效应】层数
        # 登场角色不处于山河水境内时该效果暂时失效
        if chain >= 2:
            title = f"{self.name}-二链"
            attr.add_crit_dmg(0.5, title, "山河水境内触发后, 暴击伤害提升50%")

        # 栖霞饮露
        weapon_clz = WavesWeaponRegister.find_class(21050096)
        if weapon_clz:
            w = weapon_clz(21050096, 90, 6, resonLevel)
            w.do_action(["buff"], attr, isGroup)


class Char_1202(CharAbstract):
    id = 1202
    name = "炽霞"
    starLevel = 4


class Char_1203(CharAbstract):
    id = 1203
    name = "安可"
    starLevel = 5


class Char_1204(CharAbstract):
    id = 1204
    name = "莫特斐"
    starLevel = 4

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """获得buff"""
        if attr.char_template == temp_atk:
            if chain >= 6:
                title = "莫特斐-六链"
                msg = "施放共鸣解放暴烈终曲时，队伍中的角色攻击提升20%"
                attr.add_atk_percent(0.2, title, msg)

            title = "莫特斐-合鸣效果-轻云出月"
            msg = "使用延奏技能后，下一个登场的共鸣者攻击提升22.5%"
            attr.add_atk_percent(0.225, title, msg)

        # 无常凶鹭
        title = "莫特斐-声骸技能-无常凶鹭"
        msg = "施放延奏技能，则可使下一个变奏登场的角色伤害提升12%"
        attr.add_dmg_bonus(0.12, title, msg)

        if hit_damage == attr.char_damage:
            title = "莫特斐-延奏技能"
            msg = "下一位登场角色重击伤害加深38%"
            attr.add_dmg_deepen(0.38, title, msg)

        # 停驻之烟
        weapon_id = 21030015
        weapon_clz = WavesWeaponRegister.find_class(weapon_id)
        if weapon_clz:
            w = weapon_clz(weapon_id, 90, 6, resonLevel)
            w.do_action("buff", attr, isGroup)


class Char_1205(CharAbstract):
    id = 1205
    name = "长离"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """获得buff"""
        if attr.char_template == temp_atk:
            if chain >= 4:
                title = "长离-四链"
                msg = "施放变奏技能后，队伍中的角色攻击提升20%"
                attr.add_atk_percent(0.2, title, msg)

        if attr.char_attr == CHAR_ATTR_MOLTEN:
            title = "长离-延奏技能"
            msg = "下一位登场角色热熔伤害加深20%"
            attr.add_dmg_deepen(0.2, title, msg)

        if liberation_damage == attr.char_damage:
            title = "长离-延奏技能"
            msg = "下一位登场角色共鸣解放伤害加深25%"
            attr.add_dmg_deepen(0.25, title, msg)


class Char_1206(CharAbstract):
    id = 1206
    name = "布兰特"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """获得buff"""
        # 下一位登场角色热熔伤害加深20%，共鸣技能伤害加深25%
        if attr.char_attr == CHAR_ATTR_MOLTEN:
            title = "布兰特-延奏技能"
            msg = "下一位登场角色热熔伤害加深20%"
            attr.add_dmg_deepen(0.2, title, msg)

        if skill_damage == attr.char_damage:
            title = "布兰特-延奏技能"
            msg = "下一位登场角色共鸣解放伤害加深25%"
            attr.add_dmg_deepen(0.25, title, msg)


class Char_1209(CharAbstract):
    id = 1209
    name = "莫宁"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """获得buff"""
        attr.increment_tune_strain_interfered()
        
        title = "莫宁-延奏技能"
        msg = "队伍中所有角色全伤害加深25%"
        attr.add_dmg_deepen(0.25, title, msg)

        title = "莫宁-谐振场"
        msg = "谐振场生效范围内偏谐值累积效率提升50%"
        attr.add_offtune_buildup_rate(0.5, title, msg)

        if attr.char_template == temp_def:
            title = "莫宁-强谐振场"
            msg = "强谐振场生效范围内防御提升20%"
            attr.add_def_percent(0.2, title, msg)

        if attr.env_tune_rupture or attr.env_tune_strain:
            title = "莫宁-干涉标记"
            msg = "对干涉标记目标伤害提升40%"
            attr.add_dmg_bonus(0.4, title, msg)
        
        if attr.char_template == temp_atk:
            title = "莫宁-合鸣效果-星构寻辉之环"
            msg = "偏谐值累积效率累计使攻击提升25%"
            attr.add_atk_percent(0.25, title, msg)

        if chain >= 2:
            title = "莫宁-二链"
            msg = f"共鸣效率超过100%时，对干涉标记目标暴击伤害提升32%"
            attr.add_crit_dmg(0.32, title, msg)

            title = "莫宁-二链"
            msg = "谐振场、强谐振场偏谐值累积效率额外提升20%"
            attr.add_offtune_buildup_rate(0.2, title, msg)

        # 宙算仪轨
        weapon_clz = WavesWeaponRegister.find_class(21010066)
        if weapon_clz:
            w = weapon_clz(21010066, 90, 6, resonLevel)
            w.do_action("cast_healing", attr, isGroup)


class Char_1210(CharAbstract):
    id = 1210
    name = "爱弥斯"
    starLevel = 5


class Char_1211(CharAbstract):
    id = 1211
    name = "达妮娅"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        # === 共鸣模态·聚爆 (装配 斑驳粉饰之沫) ===
        if attr.env_fusion_burst:
            # 固有技能-蚀刻繁彩: 队伍中角色热熔伤害加成提升 30%
            if attr.char_attr == CHAR_ATTR_MOLTEN:
                title = f"{self.name}-固有技能-蚀刻繁彩"
                msg = "聚爆模态时, 热熔伤害加成提升30%"
                attr.add_dmg_bonus(0.3, title, msg)

            # 延奏技能-未竟的谎言: 队伍中登场角色周围目标受到【聚爆效应】
            # 伤害加深 60% (仅在结算聚爆效应伤害时生效)
            if attr.env_fusion_burst_deepen:
                title = f"{self.name}-延奏技能-未竟的谎言"
                msg = "目标受到【聚爆效应】伤害加深60%"
                attr.add_effect_dmg_deepen(0.6, title, msg)

            # 二链 为何给我安慰: 队伍中角色施加【聚爆效应】后, 热熔伤害加成 +50%
            if chain >= 2 and attr.char_attr == CHAR_ATTR_MOLTEN:
                title = f"{self.name}-二链"
                msg = "施加【聚爆效应】后, 热熔伤害加成提升50%"
                attr.add_dmg_bonus(0.5, title, msg)

            # 声骸技能-共鸣回响·达妮娅 (6000200):
            # 施放延奏技能后, 下一个变奏登场角色热熔伤害加成提升 12%
            if attr.char_attr == CHAR_ATTR_MOLTEN:
                title = f"{self.name}-声骸技能-共鸣回响·达妮娅"
                msg = "下一个变奏登场角色热熔伤害加成提升12%"
                attr.add_dmg_bonus(0.12, title, msg)

            # 套装-斑驳粉饰之沫 (5pc): 添加聚爆效应后施放延奏技能, 下一变奏登场角色
            # 热熔伤害提升 25%。聚爆模态下达妮娅默认装配该套装, 故此处直接给出。
            if attr.char_attr == CHAR_ATTR_MOLTEN:
                title = f"{self.name}-套装-斑驳粉饰之沫"
                msg = "下一个变奏登场角色热熔伤害提升25%"
                attr.add_dmg_bonus(0.25, title, msg)

        # === 共鸣模态·集谐 (装配 剪心辑梦之影) ===
        elif attr.env_tune_strain:
            # 谐度破坏-一场关于光的默辩: 达妮娅在编队中时, 目标的【集谐·干涉】层数上限+1
            attr.increment_tune_strain_interfered(1)

            # 固有技能-蚀刻繁彩 (1/2): 集谐模态时, 队伍中角色谐度破坏增幅 +10
            title = f"{self.name}-固有技能-蚀刻繁彩"
            msg = "集谐模态时, 谐度破坏增幅提升10点"
            attr.add_tune_break_boost(10, title, msg)

            # 固有技能-蚀刻繁彩 (2/2): 偏谐值累积效率超 100% 时,
            # 每超 10% 谐度破坏增幅 +8, 上限 40 点。
            # 假定与莫宁组队 (+50% 偏谐值累积效率), 直接按上限 +40 计入
            title = f"{self.name}-固有技能-蚀刻繁彩"
            msg = "莫宁队, 谐度破坏增幅 +40"
            attr.add_tune_break_boost(40, title, msg)

            # 套装-剪心辑梦之影 (5pc): 添加震谐/集谐·偏移时, 队伍中角色谐度破坏增幅 +20。
            # 集谐模态下达妮娅默认装配该套装, 故此处直接给出。
            title = f"{self.name}-套装-剪心辑梦之影"
            msg = "添加震谐/集谐时, 队伍中角色谐度破坏增幅+20"
            attr.add_tune_break_boost(20, title, msg)

            # 延奏技能-未竟的谎言: 下一登场角色全伤害加深 15%, 在该角色附加【集谐·偏移】
            # 时提升至 40%。集谐模态下集谐·偏移由队伍持续附加。注意默认了能吃到40。
            title = f"{self.name}-延奏技能-未竟的谎言"
            msg = "下一登场角色全伤害加深40%"
            attr.add_dmg_deepen(0.4, title, msg)

            # 二链 为何给我安慰: 队伍中角色施加【集谐·偏移】后, 谐度破坏增幅 +20
            if chain >= 2:
                title = f"{self.name}-二链"
                msg = "施加【集谐·偏移】后, 谐度破坏增幅提升20点"
                attr.add_tune_break_boost(20, title, msg)

        # 角色武器 - 赝作的矮星 (21050076): 显式触发 cast_fusion_burst / cast_tune_strain
        # 队友路径 (isGroup=True) 在钩子内 if not isGroup 守卫拦掉持有者段, 只触发 atk%
        weapon_id = 21050076
        weapon_clz = WavesWeaponRegister.find_class(weapon_id)
        if weapon_clz:
            w = weapon_clz(weapon_id, 90, 6, resonLevel)
            w.do_action(["cast_fusion_burst", "cast_tune_strain"], attr, isGroup)


class Char_1301(CharAbstract):
    id = 1301
    name = "卡卡罗"
    starLevel = 5


class Char_1302(CharAbstract):
    id = 1302
    name = "吟霖"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        if attr.char_template == temp_atk:
            if chain >= 4:
                title = "吟霖-四链"
                msg = "共鸣回路审判之雷命中时，队伍中的角色攻击提升20%"
                attr.add_atk_percent(0.2, title, msg)

            title = "吟霖-合鸣效果-轻云出月"
            msg = "使用延奏技能后，下一个登场的共鸣者攻击提升22.5%"
            attr.add_atk_percent(0.225, title, msg)

        # 无常凶鹭
        title = "吟霖-声骸技能-无常凶鹭"
        msg = "施放延奏技能，则可使下一个变奏登场的角色伤害提升12%"
        attr.add_dmg_bonus(0.12, title, msg)

        # 下一位登场角色导电伤害加深20%，共鸣解放伤害加深25%
        if attr.char_attr == CHAR_ATTR_VOID:
            title = "吟霖-延奏技能"
            msg = "下一位登场角色导电伤害加深20%"
            attr.add_dmg_deepen(0.2, title, msg)

        if liberation_damage == attr.char_damage:
            title = "吟霖-延奏技能"
            msg = "下一位登场角色共鸣解放伤害加深25%"
            attr.add_dmg_deepen(0.25, title, msg)


class Char_1303(CharAbstract):
    id = 1303
    name = "渊武"
    starLevel = 4


class Char_1304(CharAbstract):
    id = 1304
    name = "今汐"
    starLevel = 5


class Char_1305(CharAbstract):
    id = 1305
    name = "相里要"
    starLevel = 5


class Char_1402(CharAbstract):
    id = 1402
    name = "秧秧"
    starLevel = 4


class Char_1403(CharAbstract):
    id = 1403
    name = "秋水"
    starLevel = 4


class Char_1404(CharAbstract):
    id = 1404
    name = "忌炎"
    starLevel = 5


class Char_1405(CharAbstract):
    id = 1405
    name = "鉴心"
    starLevel = 5


class Char_1406(CharAbstract):
    id = 1406
    name = "漂泊者·气动"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        if attr.char_attr == CHAR_ATTR_SIERRA:
            #  血誓盟约
            title = "风主-血誓盟约"
            msg = "风主施放共鸣技能时，附近队伍中登场角色气动伤害加深10%"
            attr.add_dmg_deepen(0.1, title, msg)

            # 流云逝尽之空
            # 角色为敌人添加【风蚀效应】时，队伍中角色气动伤害提升15%
            title = "风主-流云逝尽之空"
            msg = "队伍中的角色气动伤害提升15%"
            attr.add_dmg_bonus(0.15, title, msg)


class Char_1407(CharAbstract):
    id = 1407
    name = "夏空"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        # 音律独奏 / 二链 均为气动伤害加成, 仅对气动队友生效
        if attr.char_attr == CHAR_ATTR_SIERRA:
            title = f"{self.name}-音律独奏"
            attr.add_dmg_bonus(0.24, title, "队伍中所有角色气动伤害加成提升24%")

            # 二链-三重华彩: 队伍中角色气动伤害加成提升40%
            if chain >= 2:
                title = f"{self.name}-二链"
                attr.add_dmg_bonus(0.4, title, "三重华彩期间队伍中角色气动伤害加成提升40%")

        # 延奏技能: 目标受到风蚀效应伤害加深100% (效应加深, 仅结算风蚀效应伤害时)
        if attr.env_aero_erosion_deepen:
            title = f"{self.name}-延奏技能"
            attr.add_effect_dmg_deepen(1.0, title, "目标受到风蚀效应伤害加深100%")


class Char_1408(Char_1406):
    id = 1408
    name = "漂泊者·气动"
    starLevel = 5


class Char_1309(CharAbstract):
    id = 1309
    name = "漂泊者·导电"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        # 共鸣回路-超负荷(短按): 清空【电涌】, 队伍中的角色攻击提升10%
        if attr.char_template == temp_atk:
            title = "雷主-共鸣回路-超负荷"
            msg = "施放超负荷后，队伍中的角色攻击提升10%"
            attr.add_atk_percent(0.1, title, msg)

        # 延奏技能-殷殷其雷: 下一位登场角色获得电髓, 附加【异常效应】后消耗电髓, 全伤害加深25%
        if check_char_id(attr, Abnormal_Role_Ids):
            title = "雷主-延奏技能-电髓"
            msg = "持有电髓的角色附加【异常效应】后，全伤害加深25%"
            attr.add_dmg_deepen(0.25, title, msg)


class Char_1310(Char_1309):
    id = 1310
    name = "漂泊者·导电"
    starLevel = 5


class Char_1308(CharAbstract):
    id = 1308
    name = "丽贝卡"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        # 骇破·偏移: 丽贝卡编队时持续附加【骇破·偏移】, 让队友/武器的骇破条件 buff 触发
        attr.set_env_hack_shifting()

        # 固有技能-有破绽！: 施放共鸣解放时, 附近队伍中所有角色攻击提升20%
        if attr.char_template == temp_atk:
            title = f"{self.name}-固有技能-有破绽！"
            msg = "施放共鸣解放时, 队伍中所有角色攻击提升20%"
            attr.add_atk_percent(0.2, title, msg)

        # 固有技能-该你了！: 队伍中角色附加【骇破·偏移】时, 谐度破坏增幅提升30点
        if check_char_id(attr, Hack_Shifting_Role_Ids):
            title = f"{self.name}-固有技能-该你了！"
            msg = "附加【骇破·偏移】时, 谐度破坏增幅提升30点"
            attr.add_tune_break_boost(30, title, msg)

        # 延奏技能-好搭档: 下一位登场角色获得【浪客羁绊】, 全伤害加深15%
        title = f"{self.name}-延奏技能-好搭档"
        msg = "下一位登场角色全伤害加深15%"
        attr.add_dmg_deepen(0.15, title, msg)

        # 延奏技能-好搭档: 【浪客羁绊】期间每0.2秒叠1层【超限】(重击伤害加深0.5%), 上限35%
        # (露西持有则直接满层) — 假定满层
        if attr.char_damage == hit_damage:
            title = f"{self.name}-延奏技能-好搭档"
            msg = "【超限】满层, 重击伤害加深35%"
            attr.add_dmg_deepen(0.35, title, msg)

        # 二链-哦, 原来是你啊！: 施放变奏/共鸣解放时, 队伍中角色全属性伤害加成提升20%
        if chain >= 2:
            title = f"{self.name}-二链"
            msg = "队伍中角色全属性伤害加成提升20%"
            attr.add_dmg_bonus(0.2, title, msg)

            # 二链: 队伍中角色附加【骇破·偏移】时, 全伤害加深15%
            if check_char_id(attr, Hack_Shifting_Role_Ids):
                title = f"{self.name}-二链"
                msg = "附加【骇破·偏移】时, 全伤害加深15%"
                attr.add_dmg_deepen(0.15, title, msg)

        # 角色武器-碎骨 (21030066): 上方已 set 骇破 env, 驱动武器把"队伍攻击提升"段作用到队友
        weapon_id = 21030066
        weapon_clz = WavesWeaponRegister.find_class(weapon_id)
        if weapon_clz:
            w = weapon_clz(weapon_id, 90, 6, resonLevel)
            w.do_action(["buff"], attr, isGroup)


class Char_1501(CharAbstract):
    id = 1501
    name = "漂泊者·衍射"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """获得buff"""
        attr.set_env_spectro()
        title = "光主"
        msg = "触发光噪效应"
        attr.add_effect(title, msg)
        if chain >= 6:
            title = "光主-六链"
            msg = "施放共鸣技能时，目标衍射伤害抗性降低10%"
            attr.add_enemy_resistance(-0.1, title, msg)

        if attr.char_template == temp_atk:
            title = "光主-合鸣效果-轻云出月"
            msg = "下一个登场的共鸣者攻击提升22.5%"
            attr.add_atk_percent(0.225, title, msg)

        # 无常凶鹭
        title = "光主-声骸技能-无常凶鹭"
        msg = "施放延奏技能，则可使下一个变奏登场的角色伤害提升12%"
        attr.add_dmg_bonus(0.12, title, msg)


class Char_1502(Char_1501):
    id = 1502
    name = "漂泊者·衍射"
    starLevel = 5


class Char_1503(CharAbstract):
    id = 1503
    name = "维里奈"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """获得buff"""
        if attr.char_template == temp_atk:
            title = "维里奈-固有技能-自然的献礼"
            msg = "队伍中的角色攻击提升20%"
            attr.add_atk_percent(0.2, title, msg)

        if chain >= 4 and attr.char_attr == CHAR_ATTR_CELESTIAL:
            title = "维里奈-四链"
            msg = "队伍中的角色衍射伤害加成提升15%"
            attr.add_dmg_bonus(0.4, title, msg)

        if attr.char_template == temp_atk:
            title = "维里奈-合鸣效果-隐世回光"
            msg = "全队共鸣者攻击提升15%"
            attr.add_atk_percent(0.15, title, msg)

        title = "维里奈-声骸技能-鸣钟之龟"
        msg = "全队角色10.00%的伤害提升"
        attr.add_dmg_bonus(0.1, title, msg)

        title = "维里奈-延奏技能"
        msg = "队伍中的角色全伤害加深15%"
        attr.add_dmg_deepen(0.15, title, msg)


class Char_1504(CharAbstract):
    id = 1504
    name = "灯灯"
    starLevel = 4

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        if attr.char_template == temp_atk:
            if chain >= 6:
                title = f"{self.name}-六链"
                msg = "施放共鸣解放时，队伍中的角色的攻击提升20%"
                attr.add_atk_percent(0.2, title, msg)

            title = f"{self.name}-合鸣效果-轻云出月"
            msg = "使用延奏技能后，下一个登场的共鸣者攻击提升22.5%"
            attr.add_atk_percent(0.225, title, msg)

        # 无常凶鹭
        title = f"{self.name}-声骸技能-无常凶鹭"
        msg = "施放延奏技能，则可使下一个变奏登场的角色伤害提升12%"
        attr.add_dmg_bonus(0.12, title, msg)

        if skill_damage == attr.char_damage:
            title = f"{self.name}-延奏技能"
            msg = "下一位登场角色共鸣技能伤害加深38%"
            attr.add_dmg_deepen(0.38, title, msg)


class Char_1411(CharAbstract):
    id = 1411
    name = "仇远"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """获得buff"""
        # 暴击>50%时，暴击伤害+30% (假设满层)
        title = "仇远-共鸣解放"
        msg = "暴击伤害提升30%"
        attr.add_crit_dmg(0.3, title, msg)

        if attr.char_damage == phantom_damage:
            # 竹照: 声骸技能伤害加成+30%
            title = "仇远-竹照"
            msg = "声骸技能伤害加成提升30%"
            attr.add_dmg_bonus(0.3, title, msg)

            # 延奏技能: 下一个登场角色声骸技能伤害加深50%
            title = "仇远-延奏技能"
            msg = "下一个登场角色声骸技能伤害加深50%"
            attr.add_dmg_deepen(0.5, title, msg)

            # 武器-裁竹
            weapon_clz = WavesWeaponRegister.find_class(21020066)
            if weapon_clz:
                w = weapon_clz(21020066, 90, 6, resonLevel)
                w.do_action("cast_variation", attr, isGroup)

        # 套装-轻云出月: 延奏后下一个登场角色攻击+22.5%
        if attr.char_template == temp_atk:
            title = "仇远-轻云出月"
            msg = "延奏后下一个登场角色攻击提升22.5%"
            attr.add_atk_percent(0.225, title, msg)

        if attr.char_damage == phantom_damage:

            # 二链: 竹照额外效果，声骸技能伤害加深30%
            if chain >= 2:
                title = "仇远-二链"
                msg = "竹照额外: 声骸技能伤害加深30%"
                attr.add_dmg_deepen(0.3, title, msg)


class Char_1505(CharAbstract):
    id = 1505
    name = "守岸人"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """获得buff"""
        if attr.char_template == temp_atk:
            if chain >= 2:
                title = "守岸人-二链"
                msg = "队伍中的角色攻击提升40%"
                attr.add_atk_percent(0.4, title, msg)

            title = "守岸人-合鸣效果-隐世回光"
            msg = "全队共鸣者攻击提升15%"
            attr.add_atk_percent(0.15, title, msg)

        # 星序协响
        weapon_clz = WavesWeaponRegister.find_class(21050036)
        if weapon_clz:
            w = weapon_clz(21050036, 90, 6, resonLevel)
            w.do_action("skill_create_healing", attr, isGroup)

        if attr.char_template == temp_atk:
            title = "守岸人-声骸技能-无归的谬误"
            msg = "全队角色攻击提升10%"
            attr.add_atk_percent(0.1, title, msg)

        title = "守岸人-共鸣解放"
        msg = "暴击提升12.5%+暴击伤害提升25%"
        attr.add_crit_rate(0.125)
        attr.add_crit_dmg(0.25)
        attr.add_effect(title, msg)

        title = "守岸人-延奏技能"
        msg = "队伍中的角色全伤害加深15%"
        attr.add_dmg_deepen(0.15, title, msg)


class Char_1506(CharAbstract):
    id = 1506
    name = "菲比"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """获得buff"""
        attr.set_env_spectro()
        title = "菲比"
        msg = "触发光噪效应"
        attr.add_effect(title, msg)

        if attr.char_attr == CHAR_ATTR_CELESTIAL:
            title = "菲比-延奏技能-告解"
            msg = "使一定范围内的目标衍射伤害抗性减少10%"
            attr.add_enemy_resistance(-0.1, title, msg)

        if attr.char_template == temp_atk:
            title = f"{self.name}-合鸣效果-轻云出月"
            msg = "使用延奏技能后，下一个登场的共鸣者攻击提升22.5%"
            attr.add_atk_percent(0.225, title, msg)

        # 无常凶鹭
        title = f"{self.name}-声骸技能-无常凶鹭"
        msg = "施放延奏技能，则可使下一个变奏登场的角色伤害提升12%"
        attr.add_dmg_bonus(0.12, title, msg)

        if attr.env_spectro_deepen:
            title = f"{self.name}-延奏技能-告解"
            msg = "下一个变奏登场角色【光噪效应】伤害加深100%。"
            attr.add_effect_dmg_deepen(1, title, msg)

            if chain >= 2:
                title = f"{self.name}-二链"
                msg = "告解状态下，默祷的【光噪效应】伤害加深效果额外提升120%。"
                attr.add_effect_dmg_deepen(1.2, title, msg)

            if chain >= 4:
                title = f"{self.name}-四链"
                msg = "目标衍射伤害抗性降低10%，持续30秒"
                attr.add_enemy_resistance(-0.1, title, msg)

        # 和光回唱
        weapon_clz = WavesWeaponRegister.find_class(21050046)
        if weapon_clz:
            w = weapon_clz(21050046, 90, 6, resonLevel)
            method = getattr(w, "cast_extension", None)
            if callable(method):
                method(attr, isGroup)


class Char_1507(CharAbstract):
    id = 1507
    name = "赞妮"
    starLevel = 5


class Char_1508(CharAbstract):
    id = 1508
    name = "千咲"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """获得buff"""
        attr.set_env_havoc_bane()

        title = "千咲-共鸣回路-虚湮之线"
        msg = "对拥有虚无绞痕的目标造成伤害时，可无视其18%防御"
        attr.add_defense_ignore(0.18, title, msg)

        # 异常效应层数上限增加3层
        title = "千咲-延奏技能-解弦式第零定律"
        msg = "使目标层数上限增加3层"
        attr.add_effect(title, msg)
        # 注：这个记得单独写，是几层就是几层

        # 二链效果
        if chain >= 2:
            if attr.char_attr == CHAR_ATTR_SINKING:
                title = "千咲-二链"
                msg = "无视目标10%湮灭伤害抗性"
                attr.add_enemy_resistance(-0.1, title, msg)

            title = "千咲-二链"
            msg = "队伍中的角色处于虚湮之线状态时，全属性伤害加成提升50%"
            attr.add_dmg_bonus(0.5, title, msg)

        # 六链效果：异常效应伤害加深
        if chain >= 6 and attr.env_abnormal_deepen:
            title = "千咲-六链"
            msg = "拥有虚无绞痕·终焉的目标受到异常效应伤害加深30%"
            attr.add_effect_dmg_deepen(0.3, title, msg)

        weapon_clz = WavesWeaponRegister.find_class(21010056)
        if weapon_clz:
            w = weapon_clz(21010056, 90, 6, resonLevel)
            method = getattr(w, "do_action", None)
            if callable(method):
                method([cast_variation], attr, isGroup)


class Char_1509(CharAbstract):
    id = 1509
    name = "琳奈"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """获得buff"""
        attr.set_env_tune_rupture()
        attr.set_env_tune_strain()
        attr.increment_tune_strain_interfered()
        title = "琳奈-延奏技能"
        msg = "下一个登场的角色全伤害加深15%"
        attr.add_dmg_deepen(0.15, title, msg)

        if attr.char_damage == liberation_damage:
            msg = "下一个登场的角色共鸣解放伤害加深25%"
            attr.add_dmg_deepen(0.25, title, msg)

        title = "琳奈-爆炸喷涂"
        msg = "施放共鸣解放时，所有角色伤害加成提升24%"
        attr.add_dmg_bonus(0.24, title, msg)

        title = "琳奈-视觉冲击-本色"
        msg = "附近队伍中所有角色谐度破坏增幅提升40点"
        attr.add_tune_break_boost(40, title, msg)

        if attr.char_template == temp_atk:
            title = "琳奈-合鸣效果-逆光跃彩之约"
            msg = "攻击提升15%，谐度破坏增幅累计提升攻击15%"
            attr.add_atk_percent(0.3, title, msg)
            
        if chain >= 2:
            title = "琳奈-二链"
            msg = "施放延奏技能时，使下一个登场的角色全伤害加深25%"
            attr.add_dmg_deepen(0.25, title, msg)

        title = "琳奈-声骸技能-海维夏"
        msg = "全属性伤害加成提升10.00%"
        attr.add_dmg_bonus(0.1, title, msg)
        
        # 溢彩荧辉
        weapon_clz = WavesWeaponRegister.find_class(21030046)
        if weapon_clz:
            w = weapon_clz(21030046, 90, 6, resonLevel)
            w.do_action("env_tune_rupture", attr, isGroup) # 反正buff是一样的数值


class Char_1510(CharAbstract):
    id = 1510
    name = "陆·赫斯"
    starLevel = 5
    
    
class Char_1511(CharAbstract):
    id = 1511
    name = "露西"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        # 骇破·偏移: 露西编队时持续附加【骇破·偏移】, 让队友/武器的骇破条件 buff 触发
        attr.set_env_hack_shifting()

        # 延奏技能-反制程序: 下一名登场角色普攻伤害加深25%
        if attr.char_damage == attack_damage:
            title = f"{self.name}-延奏技能-反制程序"
            msg = "下一名登场角色普攻伤害加深25%"
            attr.add_dmg_deepen(0.25, title, msg)

        # 延奏技能-反制程序: 队伍中(除露西)附加【骇破·偏移】的角色全伤害加深20%
        if check_char_id(attr, Hack_Shifting_Role_Ids):
            title = f"{self.name}-延奏技能-反制程序"
            msg = "附加【骇破·偏移】的角色全伤害加深20%"
            attr.add_dmg_deepen(0.2, title, msg)

        # 共鸣解放·网络行者-欺骗程式 (大招标记目标后选取, 对全队均生效):
        # 义体故障: 标记目标受到伤害提升5%
        attr.add_easy_damage(0.05, f"{self.name}-欺骗程式·义体故障", "标记目标受到伤害提升5%")
        # 突破协议: 标记目标降低5%防御
        attr.add_defense_reduction(0.05, f"{self.name}-欺骗程式·突破协议", "标记目标降低5%防御")

        # 固有技能-进程破解【网络后门】: 丽贝卡在队伍中时同获网络后门 (条件型, 假定满2层)
        if check_char_id(attr, 1308):
            title = f"{self.name}-固有技能-网络后门"
            attr.add_dmg_deepen(0.25, title, "丽贝卡同获满2层全伤害加深25%")

        # 四链-夜之城没有活着的传奇: 队伍附加【骇破·偏移】后(露西编队即满足),
        # 队伍中角色全属性伤害加成提升20%
        if chain >= 4:
            title = f"{self.name}-四链"
            msg = "队伍附加【骇破·偏移】后, 全属性伤害加成提升20%"
            attr.add_dmg_bonus(0.2, title, msg)


class Char_1601(CharAbstract):
    id = 1601
    name = "桃祈"
    starLevel = 4


class Char_1602(CharAbstract):
    id = 1602
    name = "丹瑾"
    starLevel = 4

    # 下一位登场角色湮灭伤害加深23%，效果持续14秒，若切换至其他角色则该效果提前结束。

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """获得buff"""
        if CHAR_ATTR_SINKING == attr.char_attr:
            title = "丹瑾-延奏技能"
            msg = "下一位登场角色湮灭伤害加深23%"
            attr.add_dmg_deepen(0.23, title, msg)

            # 幽夜隐匿之帷
            title = "丹瑾-合鸣效果-幽夜隐匿之帷"
            msg = "下一位登场角色湮灭伤害加成提升15%"
            attr.add_dmg_bonus(0.15, title, msg)


class Char_1603(CharAbstract):
    id = 1603
    name = "椿"
    starLevel = 5


class Char_1604(CharAbstract):
    id = 1604
    name = "漂泊者·湮灭"
    starLevel = 5


class Char_1605(CharAbstract):
    id = 1605
    name = "漂泊者·湮灭"
    starLevel = 5


class Char_1606(CharAbstract):
    id = 1606
    name = "洛可可"
    starLevel = 5

    # 下一位登场角色湮灭伤害加深20%，普攻伤害加深25%，效果持续14秒，若切换至其他角色则该效果提前结束。

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        """获得buff"""
        if attr.char_template == temp_atk:
            title = "洛可可-共鸣解放"
            msg = "施放共鸣解放最多提供200点攻击"
            attr.add_atk_flat(200, title, msg)

            title = "洛可可-合鸣效果-轻云出月"
            msg = "下一个登场的共鸣者攻击提升22.5%"
            attr.add_atk_percent(0.225, title, msg)

        # 无常凶鹭
        title = "洛可可-声骸技能-无常凶鹭"
        msg = "施放延奏技能，则可使下一个变奏登场的角色伤害提升12%"
        attr.add_dmg_bonus(0.12, title, msg)

        if attack_damage == attr.char_damage:
            title = "洛可可-延奏技能"
            msg = "下一位登场角色普攻伤害加深25%"
            attr.add_dmg_deepen(0.25, title, msg)

        if CHAR_ATTR_SINKING == attr.char_attr:
            # # 幽夜隐匿之帷
            # title = "洛可可-合鸣效果-幽夜隐匿之帷"
            # msg = "下一个登场角色湮灭属性伤害加成提升15%"
            # attr.add_dmg_bonus(0.15, title, msg)

            title = "洛可可-延奏技能"
            msg = "下一位登场角色湮灭伤害加深20%"
            attr.add_dmg_deepen(0.2, title, msg)

            if chain >= 2:
                # 施放普攻幻想照进现实时，队伍中的角色湮灭伤害加成提升10%，可叠加3层
                title = "洛可可-二链"
                msg = "队伍中的角色湮灭伤害提升10%*4"
                attr.add_dmg_bonus(0.1 * 4, title, msg)


class Char_1410(CharAbstract):
    id = 1410
    name = "尤诺"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        # 延奏技能-晦渡为明: 下一个登场角色重击伤害加深50%
        if attr.char_damage == hit_damage:
            title = f"{self.name}-延奏技能-晦渡为明"
            msg = "下一个登场角色重击伤害加深50%"
            attr.add_dmg_deepen(0.5, title, msg)

        # 满月领域-苍白死光的祝颂: 领域中登场角色获得护盾时叠1层(每0.5秒一次),
        # 每层全伤害加深4%, 上限10层; 层数取主体短时间产盾次数 trigger_shield
        if attr.trigger_shield:
            layers = min(attr.trigger_shield, 10)
            title = f"{self.name}-满月领域-苍白死光的祝颂"
            msg = f"{layers}层祝颂, 全伤害加深{layers * 4}%"
            attr.add_dmg_deepen(0.04 * layers, title, msg)

            # 二链: 队伍中的角色的祝颂叠加至10层时, 额外获得40%全伤害加深
            if chain >= 2 and layers >= 10:
                title = f"{self.name}-二链"
                msg = "祝颂叠至10层, 额外全伤害加深40%"
                attr.add_dmg_deepen(0.4, title, msg)


class Char_1212(CharAbstract):
    id = 1212
    name = "景燃"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        # 四链: 队伍中的角色获得护盾时(画地常驻自产盾), 队伍中角色全属性伤害加成提升20%
        if chain >= 4:
            title = f"{self.name}-四链"
            msg = "队伍中角色获得护盾后, 全属性伤害加成提升20%"
            attr.add_dmg_bonus(0.2, title, msg)


class Char_1413(CharAbstract):
    id = 1413
    name = "清宵"
    starLevel = 5

    def _do_buff(
        self,
        attr: DamageAttribute,
        chain: int = 0,
        resonLevel: int = 1,
        isGroup: bool = True,
    ):
        # 引剑破万法: 清宵技能造成伤害后附加【集谐·偏移】, 编队即持续激活
        attr.set_env_tune_strain()

        # 引剑破万法: 清宵在编队中时, 目标的【集谐·干涉】层数上限+1
        attr.increment_tune_strain_interfered(1)

        # 四链: 队伍中的角色附加【集谐·偏移】后, 该角色攻击提升20%
        if chain >= 4 and check_char_id(attr, Tune_Strain_Role_Ids):
            title = f"{self.name}-四链"
            msg = "附加【集谐·偏移】后, 攻击提升20%"
            attr.add_atk_percent(0.2, title, msg)


def register_char():
    # 自动注册所有以 Char_ 开头的类
    for name, obj in globals().items():
        if name.startswith("Char_") and hasattr(obj, "id"):
            WavesCharRegister.register_class(obj.id, obj)
