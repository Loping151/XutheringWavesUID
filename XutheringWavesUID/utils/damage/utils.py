import re
from typing import Dict, Literal, Optional

SONATA_FREEZING = "凝夜白霜"
SONATA_MOLTEN = "熔山裂谷"
SONATA_VOID = "彻空冥雷"
SONATA_SIERRA = "啸谷长风"
SONATA_CELESTIAL = "浮星祛暗"
SONATA_SINKING = "沉日劫明"
SONATA_REJUVENATING = "隐世回光"
SONATA_MOONLIT = "轻云出月"
SONATA_LINGERING = "不绝余音"

SONATA_FROSTY = "凌冽决断之心"
SONATA_EMPYREAN = "高天共奏之曲"
SONATA_MIDNIGHT = "幽夜隐匿之帷"
SONATA_ETERNAL = "此间永驻之光"
SONATA_TIDEBREAKING = "无惧浪涛之勇"
SONATA_WELKIN = "流云逝尽之空"
SONATA_PILGRIMAGE = "愿戴荣光之旅"
SONATA_CLAWPRINT = "奔狼燎原之焰"
SONATA_ANCIENT = "失序彼岸之梦"
SONATA_CROWN_OF_VALOR = "荣斗铸锋之冠"
SONATA_HARMONY = "息界同调之律"
SONATA_FIREWALL = "焚羽猎魔之影"
SONATA_SCISSOR = "命理崩毁之弦"

SONATA_NEONLIGHT = "逆光跃彩之约"
SONATA_HALO = "星构寻辉之环"
SONATA_GILDED = "流金溯真之式"
SONATA_STARBOUND = "长路启航之星"
SONATA_MOTTLED = "斑驳粉饰之沫"
SONATA_WHISPER = "听唤语义之愿"
SONATA_SNOWFALL = "雪落无声之愿"
SONATA_HEARTCUT = "剪心辑梦之影"
SONATA_NIGHTMARE = "碎梦亡鬼之魇"
SONATA_FEATHERFALL = "羽落空尘之歌"
SONATA_EXORCISM = "清邪荡煞之心"
SONATA_NIGHTLAMP = "冥途夜行之灯"

CHAR_ATTR_FREEZING = "冷凝"
CHAR_ATTR_CELESTIAL = "衍射"
CHAR_ATTR_VOID = "导电"
CHAR_ATTR_MOLTEN = "热熔"
CHAR_ATTR_SIERRA = "气动"
CHAR_ATTR_SINKING = "湮灭"

# 普攻伤害加成
attack_damage = "attack_damage"
# 重击伤害加成
hit_damage = "hit_damage"
# 共鸣技能伤害加成
skill_damage = "skill_damage"
# 共鸣解放伤害加成
liberation_damage = "liberation_damage"
# 声骸技能伤害加成
phantom_damage = "phantom_damage"
# 谐度破坏伤害加成
tunebreak_damage = "tunebreak_damage"
# 延奏技能伤害
extension_damage = "extension_damage"
# 治疗效果加成
heal_bonus = "heal_bonus"
# 护盾量加成
shield_bonus = "shield_bonus"

# 造成伤害
cast_damage = "cast_damage"
# 造成普攻伤害
cast_attack = "cast_attack"
# 造成重击伤害
cast_hit = "cast_hit"
# 造成共鸣技能伤害
cast_skill = "cast_skill"
# 造成共鸣解放伤害
cast_liberation = "cast_liberation"
# 造成声骸技能伤害
cast_phantom = "cast_phantom"
# 施放闪避反击
cast_dodge_counter = "cast_dodge_counter"
# 施放变奏技能
cast_variation = "cast_variation"
# 施放谐度破坏技
cast_tunebreak = "cast_tunebreak"
# 共鸣技能造成治疗
skill_create_healing = "skill_create_healing"
# 造成治疗
cast_healing = "cast_healing"
# 释放谐度破坏
cast_tunebreak = "cast_tunebreak"

# 定义一个类型别名
SkillType = Literal["常态攻击", "共鸣技能", "共鸣解放", "变奏技能", "共鸣回路", "谐度破坏"]

# 攻击模版
temp_atk = "temp_atk"
# 生命模版
temp_life = "temp_life"
# 防御模版
temp_def = "temp_def"
# 谐度破坏模板
temp_tunebreak = "temp_tunebreak"

SkillTreeMap = {
    "常态攻击": "1",
    "共鸣技能": "2",
    "共鸣解放": "3",
    "变奏技能": "6",
    "共鸣回路": "7",
    "谐度破坏": "17",
}

# 光噪效应
Spectro_Frazzle_Role_Ids = [1407, 1501, 1502, 1506, 1507]

# 虚湮效应
Havoc_Bane_Role_Ids = [1508, 1610]

# 聚爆效应
Fusion_Burst_Role_Ids = [1210, 1211]

# 霜渐效应
Glacio_Chafe_Role_Ids = [1108, 1109, 1110]

# 风蚀效应
Aero_Erosion_Role_Ids = [1406, 1407, 1408, 1409]

# 电磁效应
Electro_Flare_Role_Ids = [1309, 1310]

# 失序彼岸之梦 套装 (共鸣能量上限为0的角色: 弗洛洛 / 洛瑟菈)
Ancient_Role_Ids = [1608, 1109]

# 偏谐值累积效率 角色
Offtune_Buildup_Role_Ids = [1209]

# 附加震谐·偏移 角色
Tune_Rupture_Role_Ids = [1509, 1210]

# 附加集谐·偏移 角色
Tune_Strain_Role_Ids = [1509, 1211, 1510, 1413]

# 附加骇破·偏移 角色
Hack_Shifting_Role_Ids = [1308, 1511]

# 可施加任意【异常效应】的角色并集 (光噪/虚湮/聚爆/霜渐/风蚀/电磁)
Abnormal_Role_Ids = sorted(
    set(
        Spectro_Frazzle_Role_Ids
        + Havoc_Bane_Role_Ids
        + Fusion_Burst_Role_Ids
        + Glacio_Chafe_Role_Ids
        + Aero_Erosion_Role_Ids
        + Electro_Flare_Role_Ids
    )
)

# 异常
AbnormalType = Literal[
    "SpectroFrazzle",  # 光噪效应
    "AeroErosion",  # 风蚀效应
    "HavocBane",  # 虚湮效应
    "FusionBurst",  # 聚爆效应
    "GlacioChafe",  # 霜渐效应
    "ElectroFlare",  # 电磁效应
]

# 偏移
ShiftingType = Literal[
    "TuneRupture",  # 震谐·偏移
    "TuneStrain",  # 集谐·偏移
]

def skill_damage_calc(skillTree: Optional[Dict], skillTreeId: str, skillParamId: str, skillLevel: int) -> str:
    """
    获取技能伤害
    :param skillTree: 技能树
    :param skillTreeId: 技能树id
    :param skillParamId: 技能参数id
    :param skillLevel: 技能等级
    :return: 技能伤害
    """
    if skillTree is None:
        raise ValueError("技能树数据不能为空")
    level = skillTree[skillTreeId]["skill"]["level"]
    if skillParamId not in level:
        if skillParamId.endswith("伤害"):
            skillParamId = skillParamId[:-2]
        else:
            skillParamId = f"{skillParamId}伤害"
    return level[skillParamId]["param"][0][skillLevel]


def parse_skill_multi(temp):
    """
    解析 "1313+5.97%"
    """
    match = re.match(r"([0-9.]+)(\+([0-9.]+)%?)", temp)
    if match:
        value = float(match.group(1))  # 获取数字部分
        percent = float(match.group(3))  # 获取百分比部分
        return value, percent
    return 0, 0


def add_comma_separated_numbers(*nums: str) -> str:
    """
    接受多个带逗号的数字字符串，去除逗号后进行加法计算，并返回结果，结果也带逗号。
    :return: 计算后的整数和，格式化为带逗号的字符串
    """
    total = sum(float(num.replace(",", "")) for num in nums)
    return f"{total:,.0f}"


def comma_separated_number(num: str):
    num = num.replace(",", "")
    if num.isdigit():
        return float(num)
    return 0.0
