import json
from typing import Dict, List, Optional

from msgspec import json as msgjson

from gsuid_core.logger import logger

from .resource.RESOURCE_PATH import (
    MAP_PATH,
    MAP_ALIAS_PATH,
    LOCALIZATION_PATH,
    CUSTOM_ID2NAME_PATH,
    CUSTOM_CHAR_ALIAS_PATH,
    CUSTOM_ECHO_ALIAS_PATH,
    CUSTOM_SONATA_ALIAS_PATH,
    CUSTOM_WEAPON_ALIAS_PATH,
)

# 别名数据已移动到 resource/map/alias
ALIAS_LIST = MAP_ALIAS_PATH
CHAR_ALIAS = ALIAS_LIST / "char_alias.json"
WEAPON_ALIAS = ALIAS_LIST / "weapon_alias.json"
SONATA_ALIAS = ALIAS_LIST / "sonata_alias.json"
ECHO_ALIAS = ALIAS_LIST / "echo_alias.json"

char_alias_data: Dict[str, List[str]] = {}
weapon_alias_data: Dict[str, List[str]] = {}
sonata_alias_data: Dict[str, List[str]] = {}
echo_alias_data: Dict[str, List[str]] = {}
char_id_data: Dict[str, Dict[str, str]] = {}
id2name: Dict[str, str] = {}

# i18n 反向查找表: {normalized_foreign_name: chs_name}
_char_i18n_reverse: Dict[str, str] = {}
_weapon_i18n_reverse: Dict[str, str] = {}
_echo_i18n_reverse: Dict[str, str] = {}

_data_loaded = False


def _normalize(name: str) -> str:
    """归一化名称: 小写并去除空格"""
    return name.lower().replace(" ", "").replace("\u3000", "")


def _build_i18n_reverse(i18n_path) -> Dict[str, str]:
    """从 i18n JSON 文件构建反向查找表"""
    reverse_map: Dict[str, str] = {}
    if not i18n_path.exists():
        return reverse_map
    try:
        with open(i18n_path, "r", encoding="UTF-8") as f:
            data = msgjson.decode(f.read(), type=Dict[str, Dict[str, str]])
        for chs_name, translations in data.items():
            for foreign_name in translations.values():
                normalized = _normalize(foreign_name)
                if normalized and normalized != _normalize(chs_name):
                    reverse_map[normalized] = chs_name
    except Exception as e:
        logger.exception(f"[鸣潮·伤害诊断] Failed to load i18n file {i18n_path}: {e}")
    return reverse_map


def _i18n_to_chs(name: str, reverse_map: Dict[str, str]) -> Optional[str]:
    """尝试将其它语言名称解析为简体中文名称"""
    normalized = _normalize(name)
    return reverse_map.get(normalized)


def add_dictionaries(dict1, dict2):
    all_keys = set(dict1.keys()) | set(dict2.keys())
    return {key: list(set(dict1.get(key, []) + dict2.get(key, []))) for key in all_keys}


def load_alias_data():
    global char_alias_data, weapon_alias_data, sonata_alias_data, echo_alias_data
    if CHAR_ALIAS.exists():
        with open(CHAR_ALIAS, "r", encoding="UTF-8") as f:
            char_alias_data = msgjson.decode(f.read(), type=Dict[str, List[str]])

    if SONATA_ALIAS.exists():
        with open(SONATA_ALIAS, "r", encoding="UTF-8") as f:
            sonata_alias_data = msgjson.decode(f.read(), type=Dict[str, List[str]])

    if WEAPON_ALIAS.exists():
        with open(WEAPON_ALIAS, "r", encoding="UTF-8") as f:
            weapon_alias_data = msgjson.decode(f.read(), type=Dict[str, List[str]])

    if ECHO_ALIAS.exists():
        with open(ECHO_ALIAS, "r", encoding="UTF-8") as f:
            echo_alias_data = msgjson.decode(f.read(), type=Dict[str, List[str]])

    if CUSTOM_CHAR_ALIAS_PATH.exists():
        try:
            with open(CUSTOM_CHAR_ALIAS_PATH, "r", encoding="UTF-8") as f:
                custom_char_alias_data = msgjson.decode(f.read(), type=Dict[str, List[str]])
        except Exception as e:
            logger.exception(f"[鸣潮·伤害诊断] 读取自定义角色别名失败 {CUSTOM_CHAR_ALIAS_PATH} - {e}")
            custom_char_alias_data = {}

        char_alias_data = add_dictionaries(char_alias_data, custom_char_alias_data)
        char_alias_data = dict(sorted(char_alias_data.items(), key=lambda item: len(item[0])))

    if CUSTOM_SONATA_ALIAS_PATH.exists():
        try:
            with open(CUSTOM_SONATA_ALIAS_PATH, "r", encoding="UTF-8") as f:
                custom_sonata_alias_data = msgjson.decode(f.read(), type=Dict[str, List[str]])
        except Exception as e:
            logger.exception(f"[鸣潮·伤害诊断] 读取自定义合鸣别名失败 {CUSTOM_SONATA_ALIAS_PATH} - {e}")
            custom_sonata_alias_data = {}

        sonata_alias_data = add_dictionaries(sonata_alias_data, custom_sonata_alias_data)
        sonata_alias_data = dict(sorted(sonata_alias_data.items(), key=lambda item: len(item[0])))

    if CUSTOM_WEAPON_ALIAS_PATH.exists():
        try:
            with open(CUSTOM_WEAPON_ALIAS_PATH, "r", encoding="UTF-8") as f:
                custom_weapon_alias_data = msgjson.decode(f.read(), type=Dict[str, List[str]])
        except Exception as e:
            logger.exception(f"[鸣潮·伤害诊断] 读取自定义武器别名失败 {CUSTOM_WEAPON_ALIAS_PATH} - {e}")
            custom_weapon_alias_data = {}

        weapon_alias_data = add_dictionaries(weapon_alias_data, custom_weapon_alias_data)
        weapon_alias_data = dict(sorted(weapon_alias_data.items(), key=lambda item: len(item[0])))

    if CUSTOM_ECHO_ALIAS_PATH.exists():
        try:
            with open(CUSTOM_ECHO_ALIAS_PATH, "r", encoding="UTF-8") as f:
                custom_echo_alias_data = msgjson.decode(f.read(), type=Dict[str, List[str]])
        except Exception as e:
            logger.exception(f"[鸣潮·伤害诊断] 读取自定义声骸别名失败 {CUSTOM_ECHO_ALIAS_PATH} - {e}")
            custom_echo_alias_data = {}

        echo_alias_data = add_dictionaries(echo_alias_data, custom_echo_alias_data)
        echo_alias_data = dict(sorted(echo_alias_data.items(), key=lambda item: len(item[0])))

    with open(CUSTOM_CHAR_ALIAS_PATH, "w", encoding="UTF-8") as f:
        f.write(json.dumps(char_alias_data, indent=2, ensure_ascii=False))

    with open(CUSTOM_SONATA_ALIAS_PATH, "w", encoding="UTF-8") as f:
        f.write(json.dumps(sonata_alias_data, indent=2, ensure_ascii=False))

    with open(CUSTOM_WEAPON_ALIAS_PATH, "w", encoding="UTF-8") as f:
        f.write(json.dumps(weapon_alias_data, indent=2, ensure_ascii=False))

    with open(CUSTOM_ECHO_ALIAS_PATH, "w", encoding="UTF-8") as f:
        f.write(json.dumps(echo_alias_data, indent=2, ensure_ascii=False))


def ensure_data_loaded(force: bool = False):
    """确保所有数据已加载

    Args:
        force: 如果为 True，强制重新加载所有数据，即使已经加载过
    """
    global _data_loaded, char_id_data, id2name
    global _char_i18n_reverse, _weapon_i18n_reverse, _echo_i18n_reverse

    if _data_loaded and not force:
        return

    load_alias_data()

    # 加载 i18n 反向查找表
    _char_i18n_reverse = _build_i18n_reverse(LOCALIZATION_PATH / "char_i18n.json")
    _weapon_i18n_reverse = _build_i18n_reverse(LOCALIZATION_PATH / "weapon_i18n.json")
    _echo_i18n_reverse = _build_i18n_reverse(LOCALIZATION_PATH / "echo_i18n.json")

    _prev_char_id_data_len = len(char_id_data)
    _prev_id2name_len = len(id2name)
    try:
        with open(MAP_PATH / "CharId2Data.json", "r", encoding="UTF-8") as f:
            char_id_data = msgjson.decode(f.read(), type=Dict[str, Dict[str, str]])
    except FileNotFoundError:
        logger.warning(
            f"[鸣潮·伤害诊断] CharId2Data.json not found at "
            f"{MAP_PATH / 'CharId2Data.json'}, char_id_data 从 {_prev_char_id_data_len} 项重置为空 dict"
        )
        char_id_data = {}
    except Exception as e:
        logger.exception(
            f"[鸣潮·伤害诊断] Failed to load CharId2Data.json (char_id_data 从 "
            f"{_prev_char_id_data_len} 项重置为空 dict): {e}"
        )
        char_id_data = {}
    # if _prev_char_id_data_len > 0 and len(char_id_data) == 0:
    #     logger.error(
    #         f"[鸣潮·伤害诊断] char_id_data 在本次 reload 中由 {_prev_char_id_data_len} "
    #         f"项变成空 dict, force={force}"
    #     )

    try:
        with open(MAP_PATH / "id2name.json", "r", encoding="UTF-8") as f:
            id2name = msgjson.decode(f.read(), type=Dict[str, str])
    except FileNotFoundError:
        logger.warning(
            f"[鸣潮·伤害诊断] id2name.json not found at "
            f"{MAP_PATH / 'id2name.json'}, id2name 从 {_prev_id2name_len} 项重置为空 dict"
        )
        id2name = {}
    except Exception as e:
        logger.exception(
            f"[鸣潮·伤害诊断] Failed to load id2name.json (id2name 从 "
            f"{_prev_id2name_len} 项重置为空 dict): {e}"
        )
        id2name = {}
    # if _prev_id2name_len > 0 and len(id2name) == 0:
    #     logger.error(
    #         f"[鸣潮·伤害诊断] id2name 在本次 reload 中由 {_prev_id2name_len} "
    #         f"项变成空 dict, force={force}"
    #     )

    # 加载自定义 id2name.json
    if CUSTOM_ID2NAME_PATH.exists():
        try:
            with open(CUSTOM_ID2NAME_PATH, "r", encoding="UTF-8") as f:
                custom_id2name = msgjson.decode(f.read(), type=Dict[str, str])
        except Exception as e:
            logger.exception(f"[鸣潮·伤害诊断] 读取自定义id2name失败 {CUSTOM_ID2NAME_PATH} - {e}")
            custom_id2name = {}

        # 合并自定义数据：资源中已存在的 key 以资源 value 为准，
        # custom 仅能新增资源中没有的 kv 对，不允许覆盖资源
        for k, v in custom_id2name.items():
            id2name.setdefault(k, v)

    # 将合并后的数据写回到自定义文件中
    with open(CUSTOM_ID2NAME_PATH, "w", encoding="UTF-8") as f:
        f.write(json.dumps(id2name, indent=2, ensure_ascii=False))

    _data_loaded = True


def alias_to_char_name(char_name: str) -> str:
    ensure_data_loaded()
    # 先尝试 i18n 反向查找（忽略大小写和空格）
    chs = _i18n_to_chs(char_name, _char_i18n_reverse)
    if chs:
        char_name = chs
    for key, aliases in char_alias_data.items():
        if char_name == key or char_name in aliases:
            return key
    for i in char_alias_data:
        if (char_name in i) or (char_name in char_alias_data[i]):
            return i
    return char_name


def is_valid_char_name(char_name: str) -> bool:
    ensure_data_loaded()
    all_names = set(char_alias_data.keys()) | {alias for aliases in char_alias_data.values() for alias in aliases}
    return char_name in sorted(all_names, key=len, reverse=True)


def alias_to_char_name_optional(char_name: Optional[str]) -> Optional[str]:
    ensure_data_loaded()
    if not char_name:
        return None
    # 先尝试 i18n 反向查找（忽略大小写和空格）
    chs = _i18n_to_chs(char_name, _char_i18n_reverse)
    if chs:
        char_name = chs
    for key, aliases in char_alias_data.items():
        if char_name == key or char_name in aliases:
            return key
    for i in char_alias_data:
        if (char_name in i) or (char_name in char_alias_data[i]):
            return i
    return None


def alias_to_char_name_list(char_name: str) -> List[str]:
    ensure_data_loaded()
    # 先尝试 i18n 反向查找（忽略大小写和空格）
    chs = _i18n_to_chs(char_name, _char_i18n_reverse)
    if chs:
        char_name = chs
    for key, aliases in char_alias_data.items():
        if char_name == key or char_name in aliases:
            return aliases
    for i in char_alias_data:
        if (char_name in i) or (char_name in char_alias_data[i]):
            return char_alias_data[i]
    return []


def char_id_to_char_name(char_id: str) -> Optional[str]:
    ensure_data_loaded()
    char_id = str(char_id)
    if char_id in char_id_data:
        return char_id_data[char_id]["name"]
    else:
        return None


def char_name_to_char_id(char_name: str) -> Optional[str]:
    ensure_data_loaded()
    char_name = alias_to_char_name(char_name)
    for id, name in id2name.items():
        if char_name == name:
            from .resource.constant import SPECIAL_CHAR_RANK_MAP
            mapped_id = SPECIAL_CHAR_RANK_MAP.get(id, id)
            return mapped_id
    else:
        return None


def alias_to_weapon_name(weapon_name: str) -> str:
    ensure_data_loaded()
    # 先尝试 i18n 反向查找（忽略大小写和空格）
    chs = _i18n_to_chs(weapon_name, _weapon_i18n_reverse)
    if chs:
        weapon_name = chs
    hit = _match_weapon(weapon_name)
    if hit:
        return hit

    if "专武" in weapon_name:
        char_name = weapon_name.replace("专武", "")
        name = alias_to_char_name(char_name)
        weapon_name = f"{name}专武"

    return _match_weapon(weapon_name) or weapon_name


def _match_weapon(weapon_name: str) -> Optional[str]:
    for i, aliases in weapon_alias_data.items():
        if weapon_name == i or weapon_name in aliases:
            return i
    for i in weapon_alias_data:
        if weapon_name in i:
            return i
    return None


def weapon_name_to_weapon_id(weapon_name: str) -> Optional[str]:
    ensure_data_loaded()
    weapon_name = alias_to_weapon_name(weapon_name)
    for id, name in id2name.items():
        if weapon_name == name:
            return id
    else:
        return None


def alias_to_sonata_name(sonata_name: str | None) -> str | None:
    ensure_data_loaded()
    if sonata_name is None:
        return None
    # Remove "套" character to make it optional
    normalized_sonata_name = sonata_name.rstrip('套')
    for i in sonata_alias_data:
        if normalized_sonata_name == i.rstrip('套') or any(
            normalized_sonata_name == alias.rstrip('套') for alias in sonata_alias_data[i]
        ):
            return i
    for i in sonata_alias_data:
        # Check if normalized input matches the key (with "套" stripped)
        normalized_key = i.rstrip('套')
        if normalized_sonata_name in normalized_key:
            return i
        # Check if normalized input matches any alias (with "套" stripped)
        for alias in sonata_alias_data[i]:
            if normalized_sonata_name in alias.rstrip('套'):
                return i
    return None


def alias_to_echo_name(echo_name: str) -> str:
    ensure_data_loaded()
    # 先尝试 i18n 反向查找（忽略大小写和空格）
    chs = _i18n_to_chs(echo_name, _echo_i18n_reverse)
    if chs:
        echo_name = chs
    for i, j in echo_alias_data.items():
        if echo_name == i or echo_name in j:
            return i
    for i, j in echo_alias_data.items():
        for k in j:
            if k and echo_name in k:
                return i
        if echo_name in i:
            return i
    return echo_name


def echo_name_to_echo_id(echo_name: str) -> Optional[str]:
    ensure_data_loaded()
    echo_name = alias_to_echo_name(echo_name)
    for id, name in id2name.items():
        if echo_name == name:
            return id
    else:
        return None


def easy_id_to_name(id: str, default: str = "") -> str:
    ensure_data_loaded()
    return id2name.get(id, default)


def get_all_char_id() -> List[str]:
    ensure_data_loaded()
    return list(char_id_data.keys())
