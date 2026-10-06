import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from gsuid_core.data_store import get_res_path

MAIN_PATH = get_res_path() / "XutheringWavesUID"
sys.path.append(str(MAIN_PATH))

# 配置文件
CONFIG_PATH = MAIN_PATH / "config.json"
GUIDE_CONFIG_PATH = MAIN_PATH / "guide_config.json"
GACHA_CONFIG_PATH = MAIN_PATH / "gacha_config.json"
ANN_DATA_PATH = MAIN_PATH / "ann_data.json"

# 用户数据保存文件
PLAYER_PATH = MAIN_PATH / "players"

# 抽卡记录备份目录（import/update/delete 三类备份均在此目录下，按 uid 分子目录）
GACHA_BACKUP_PATH = MAIN_PATH / "backup" / "gacha_backup"

# 储存数据保存路径
CACHE_PATH = MAIN_PATH / "cache"

# 游戏素材
RESOURCE_PATH = MAIN_PATH / "resource"
PHANTOM_PATH = RESOURCE_PATH / "phantom"
MATERIAL_PATH = RESOURCE_PATH / "material"
AVATAR_PATH = RESOURCE_PATH / "waves_avatar"
WEAPON_PATH = RESOURCE_PATH / "waves_weapon"
ROLE_PILE_PATH = RESOURCE_PATH / "role_pile"
ROLE_BG_PATH = RESOURCE_PATH / "role_bg"
ROLE_DETAIL_PATH = RESOURCE_PATH / "role_detail"
ROLE_DETAIL_SKILL_PATH = ROLE_DETAIL_PATH / "skill"
ROLE_DETAIL_CHAINS_PATH = ROLE_DETAIL_PATH / "chains"
SHARE_BG_PATH = RESOURCE_PATH / "share"
TITLE_BG_PATH = RESOURCE_PATH / "title_bg"
CARD_POLYGON_PATH = RESOURCE_PATH / "card_polygon"

# 攻略
GUIDE_PATH = MAIN_PATH / "guide_new"
# 小沐XMu 攻略库
XMU_GUIDE_PATH = GUIDE_PATH / "XMu"
# Moealkyne 攻略库
MOEALKYNE_GUIDE_PATH = GUIDE_PATH / "Moealkyne"
# 金铃子攻略组 攻略库
JINLINGZI_GUIDE_PATH = GUIDE_PATH / "JinLingZi"
# 結星 攻略库
VANZI_GUIDE_PATH = GUIDE_PATH / "VanZi"
# 小羊 攻略库
XIAOYANG_GUIDE_PATH = GUIDE_PATH / "XiaoYang"
# 吃我无痕 攻略库
WUHEN_GUIDE_PATH = GUIDE_PATH / "WuHen"
# 巡游天国 攻略库
XFM_GUIDE_PATH = GUIDE_PATH / "XFM"
# 社区攻略 攻略库
KUROBBS_GUIDE_PATH = GUIDE_PATH / "KuroBBS"
# 猫眼石 攻略库
CHRYSOBERYL_GUIDE_PATH = GUIDE_PATH / "Chrysoberyl"
# 拉格朗日变分主义 攻略库
LAGVAR_GUIDE_PATH = GUIDE_PATH / "Lagvar"

# 构建 和 详情文件
BUILD_ROOT = Path(__file__).parent.parent
BUILD_PATH = BUILD_ROOT / "waves_build"
BUILD_TEMP = MAIN_PATH / "build" / "waves_build"
MAP_PATH = RESOURCE_PATH / "map"
MAP_CHAR_PATH = RESOURCE_PATH / "map" / "character"
MAP_DETAIL_PATH = RESOURCE_PATH / "map" / "detail_json"
MAP_CHALLENGE_PATH = RESOURCE_PATH / "map" / "detail_json" / "challenge"
MAP_FORTE_PATH = RESOURCE_PATH / "map" / "detail_json" / "forte"
MAP_BUILD_PATH = BUILD_ROOT / "map" / "waves_build"
MAP_BUILD_TEMP = MAIN_PATH / "build" / "map" / "waves_build"
MAP_ALIAS_PATH = MAP_PATH / "alias"
LOCALIZATION_PATH = MAP_PATH / "i18n"

# 自定义背景图
CUSTOM_CARD_PATH = MAIN_PATH / "custom_role_pile"
CUSTOM_MR_CARD_PATH = MAIN_PATH / "custom_mr_role_pile"
CUSTOM_MR_BG_PATH = MAIN_PATH / "custom_mr_bg"
CUSTOM_ORB_PATH = MAIN_PATH / "custom_orb"

# 三类自定义图 type → 根目录, 全插件唯一来源。
# card_utils.CUSTOM_PATH_MAP / card_hash_index.TYPE_BASES / storage.TYPE_PATHS 都从这里读。
CUSTOM_DIRS = {
    "card": CUSTOM_CARD_PATH,
    "bg": CUSTOM_MR_BG_PATH,
    "stamina": CUSTOM_MR_CARD_PATH,
}

# 自定义图允许的后缀, 同样是单一来源。
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# 其他的素材
OTHER_PATH = MAIN_PATH / "other"
CALENDAR_PATH = OTHER_PATH / "calendar"
SLASH_PATH = OTHER_PATH / "slash"
MATRIX_PATH = OTHER_PATH / "matrix"
CHALLENGE_PATH = OTHER_PATH / "challenge"
ANN_CARD_PATH = OTHER_PATH / "ann_card"
BAKE_PATH = OTHER_PATH / "bake"
POKER_PATH = OTHER_PATH / "poker"
WIKI_CACHE_PATH = OTHER_PATH / "wiki"
BBS_PATH = OTHER_PATH / "bbs"
SIGN_SURFACE_PATH = OTHER_PATH / "sign_surface"

# 基础别名文件路径
ALIAS_PATH = MAIN_PATH / "alias"
CUSTOM_CHAR_ALIAS_PATH = ALIAS_PATH / "char_alias.json"
CUSTOM_SONATA_ALIAS_PATH = ALIAS_PATH / "sonata_alias.json"
CUSTOM_WEAPON_ALIAS_PATH = ALIAS_PATH / "weapon_alias.json"
CUSTOM_ECHO_ALIAS_PATH = ALIAS_PATH / "echo_alias.json"
CUSTOM_ID2NAME_PATH = ALIAS_PATH / "id2name.json"


def init_dir():
    for i in [
        MAIN_PATH,
        PLAYER_PATH,
        GACHA_BACKUP_PATH,
        RESOURCE_PATH,
        PHANTOM_PATH,
        MATERIAL_PATH,
        AVATAR_PATH,
        WEAPON_PATH,
        ROLE_PILE_PATH,
        ROLE_DETAIL_PATH,
        ROLE_DETAIL_SKILL_PATH,
        ROLE_DETAIL_CHAINS_PATH,
        SHARE_BG_PATH,
        TITLE_BG_PATH,
        CARD_POLYGON_PATH,
        GUIDE_PATH,
        XMU_GUIDE_PATH,
        MOEALKYNE_GUIDE_PATH,
        JINLINGZI_GUIDE_PATH,
        VANZI_GUIDE_PATH,
        XIAOYANG_GUIDE_PATH,
        XFM_GUIDE_PATH,
        KUROBBS_GUIDE_PATH,
        CHRYSOBERYL_GUIDE_PATH,
        CUSTOM_CARD_PATH,
        OTHER_PATH,
        CALENDAR_PATH,
        MATRIX_PATH,
        ANN_CARD_PATH,
        BAKE_PATH,
        WIKI_CACHE_PATH,
        BBS_PATH,
        SIGN_SURFACE_PATH,
        BUILD_PATH,
        BUILD_TEMP,
        MAP_BUILD_PATH,
        MAP_BUILD_TEMP,
        MAP_PATH,
        MAP_CHAR_PATH,
        MAP_DETAIL_PATH,
        MAP_CHALLENGE_PATH,
        MAP_ALIAS_PATH,
        CUSTOM_MR_CARD_PATH,
        CUSTOM_MR_BG_PATH,
        CUSTOM_ORB_PATH,
        ALIAS_PATH,
    ]:
        i.mkdir(parents=True, exist_ok=True)


init_dir()

# 设置 Jinja2 环境
TEMP_PATH = Path(__file__).parents[1].parent / "templates"
waves_templates = Environment(
    loader=FileSystemLoader(
        [
            str(TEMP_PATH),
        ]
    )
)

# 自定义模板路径
CUSTOM_TEMP_PATH = get_res_path(["XutheringWavesUID", "show"])
custom_waves_template = Environment(
    loader=FileSystemLoader(
        [
            str(CUSTOM_TEMP_PATH),
        ]
    )
)

# 设置captcha目录
CAPTCHA_PATH = Path(__file__).parents[1].parent / "utils/api/captcha"
