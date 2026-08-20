from typing import Dict, List, Union, Literal, Optional

from pydantic import BaseModel


class RoleSkin(BaseModel):
    """角色皮肤"""
    isAddition: Optional[bool] = None
    picUrl: Optional[str] = None
    priority: Optional[int] = None
    quality: Optional[int] = None
    qualityName: Optional[str] = None
    skinIcon: Optional[str] = None
    skinId: Optional[int] = None
    skinName: Optional[str] = None


class Role(BaseModel):
    roleId: int
    level: int
    breach: Optional[int] = None
    roleName: str
    roleIconUrl: Optional[str] = None
    rolePicUrl: Optional[str] = None
    starLevel: int
    attributeId: int
    attributeName: Optional[str] = None
    weaponTypeId: int
    weaponTypeName: Optional[str] = None
    acronym: Optional[str] = None
    chainUnlockNum: Optional[int] = None
    isMainRole: Optional[bool] = None
    totalSkillLevel: Optional[int] = None
    roleSkin: Optional[RoleSkin] = None
    # mapRoleId: int | None


class RoleList(BaseModel):
    roleList: List[Role]
    showRoleIdList: Optional[List[int]] = None
    showToGuest: bool


class Chain(BaseModel):
    name: Optional[str]
    order: int
    description: Optional[str]
    iconUrl: Optional[str]
    unlocked: bool


class Weapon(BaseModel):
    weaponId: int
    weaponName: str
    weaponType: int
    weaponStarLevel: int
    weaponIcon: Optional[str]
    weaponEffectName: Optional[str]
    # effectDescription: Optional[str]


class WeaponData(BaseModel):
    weapon: Weapon
    level: int
    breach: Optional[int] = None
    resonLevel: Optional[int]


class PhantomProp(BaseModel):
    phantomPropId: int
    name: str
    phantomId: int
    quality: int
    cost: int
    iconUrl: str
    skillDescription: Optional[str]


class FetterDetail(BaseModel):
    groupId: int
    name: str = ""
    iconUrl: Optional[str] = None
    num: int = 0
    firstDescription: Optional[str] = None
    secondDescription: Optional[str] = None


class Props(BaseModel):
    attributeName: str
    iconUrl: Optional[str] = None
    attributeValue: str


class EquipPhantom(BaseModel):
    phantomProp: PhantomProp
    cost: int
    quality: int
    level: int
    fetterDetail: FetterDetail
    mainProps: Optional[List[Props]] = None
    subProps: Optional[List[Props]] = None

    def get_props(self):
        props = []
        if self.mainProps:
            props.extend(self.mainProps)
        if self.subProps:
            props.extend(self.subProps)

        return props


class EquipPhantomData(BaseModel):
    cost: int
    equipPhantomList: Union[List[Optional[EquipPhantom]], None, List[None]] = None


class Skill(BaseModel):
    id: int
    type: str
    name: str
    description: str
    iconUrl: str


class SkillData(BaseModel):
    skill: Skill
    level: int

class SkillBranch(BaseModel):
    activePic: str
    branchId: int
    branchName: str
    desc: str
    pic: str
    skillIcon: str

class RoleDetailData(BaseModel):
    role: Role
    level: int
    chainList: List[Chain]
    weaponData: WeaponData
    phantomData: Optional[EquipPhantomData] = None
    equipPhantomAddPropList: Optional[List[Props]] = None
    skillList: List[SkillData]
    activeBranchId: int = 0
    skillBranchList: Optional[List[SkillBranch]] = None

    def get_chain_num(self):
        """获取命座数量"""
        num = 0
        for index, chain in enumerate(self.chainList):
            if chain.unlocked:
                num += 1
        return num

    def get_chain_name(self):
        n = self.get_chain_num()
        return f"{['零', '一', '二', '三', '四', '五', '六'][n]}链"

    def get_skill_level(
        self,
        skill_type: Literal["常态攻击", "共鸣技能", "共鸣解放", "变奏技能", "共鸣回路", "谐度破坏"],
    ):
        skill_level = 1
        _skill = self._dedup_skills().get(skill_type)
        if _skill:
            skill_level = _skill.level - 1
        return skill_level

    def _dedup_skills(self) -> Dict[str, SkillData]:
        """同类型技能只留等级最高的一条(清宵等角色接口会返回两条变奏技能)。"""
        best: Dict[str, SkillData] = {}
        for _skill in self.skillList:
            cur = best.get(_skill.skill.type)
            if cur is None or _skill.level > cur.level:
                best[_skill.skill.type] = _skill
        return best

    def get_skill_list(self):
        sort = ["常态攻击", "共鸣技能", "共鸣回路", "共鸣解放", "变奏技能", "延奏技能", "谐度破坏"]
        return sorted(self._dedup_skills().values(), key=lambda x: sort.index(x.skill.type))

    def get_skill_branch(self) -> str:
        if self.activeBranchId and self.skillBranchList:
            for branch in self.skillBranchList:
                if branch.branchId == self.activeBranchId:
                    return branch
        return None


class CalabashData(BaseModel):
    """数据坞"""

    level: Optional[int]  # 数据坞等级
    baseCatch: Optional[str]  # 基础吸收概率
    strengthenCatch: Optional[str]  # 强化吸收概率
    catchQuality: Optional[int]  # 最高可吸收品质
    cost: Optional[int]  # cost上限
    maxCount: Optional[int]  # 声骸收集进度-max
    unlockCount: Optional[int]  # 声骸收集进度-curr
    isUnlock: bool  # 解锁
