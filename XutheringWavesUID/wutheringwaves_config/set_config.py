from gsuid_core.logger import logger
from gsuid_core.models import Event

from ..utils.constants import WAVES_GAME_ID
from ..utils.name_convert import is_valid_char_name, alias_to_char_name
from ..utils.database.models import WavesUser
from ..utils.util import get_hide_uid_pref, hide_uid

WAVES_USER_MAP = {
    "体力背景": "stamina_bg",
    "隐藏UID": "hide_uid_self",
}


def _is_valid_stamina_bg_hash(hash_id: str) -> bool:
    # 此模块在 wutheringwaves_config 包初始化阶段被加载, 而 card_hash_index 反向需要 PREFIX,
    # 顶层 import 会触发 partial init 循环; 所以下放到函数内, 命令真正调用时才解析。
    from ..wutheringwaves_charinfo.card_hash_index import is_valid_hash
    return is_valid_hash(hash_id, types=("bg", "stamina"))


async def set_waves_user_value(ev: Event, func: str, uid: str, value: str):
    if func in WAVES_USER_MAP:
        status = WAVES_USER_MAP[func]
    else:
        return "该配置项不存在!"
    logger.info("[鸣潮·设置{}] uid:{} value: {}".format(func, uid, value))

    # 体力背景: 先校验、归一化, 通过后再落库; 避免非法值持久化。
    bg_random_hint = False
    if func == "体力背景" and value:
        # 随机背景/随机立绘/随机官方背景: 分支词本身即随机语义, 存值剥掉"随机";
        # 只写"随机"则剥空, 等效清空设置回落全局默认
        value = value.replace("随机", "").strip()
    if func == "体力背景" and value:
        pure_value = value.replace("官方", "").replace("立绘", "").replace("背景", "").replace("图", "")
        if not pure_value.strip():
            if not any(k in value for k in ("背景", "立绘", "官方")):
                return "未找到对应体力背景!\n请检查输入的角色名称或图片ID是否正确!"
            bg_random_hint = True
        elif is_valid_char_name(pure_value):
            value = alias_to_char_name(pure_value) + ("官方" if "官方" in value else "") + ("立绘" if "立绘" in value else "") + ("背景" if "背景" in value else "")
        elif not _is_valid_stamina_bg_hash(pure_value):
            return "未找到对应体力背景!\n请检查输入的角色名称或图片ID是否正确!"

    if (
        await WavesUser.update_data_by_data(
            select_data={
                "user_id": ev.user_id,
                "bot_id": ev.bot_id,
                "uid": uid,
                "game_id": WAVES_GAME_ID,
            },
            update_data={f"{status}_value": value},
        )
        == 0
    ):
        if func == "隐藏UID":
            # 调度层只会传 on/off; 用 value 做即时回显, 无需再读 DB
            masked_uid = hide_uid(uid, user_pref=value)
            action = "已开启" if value == "on" else "已关闭"
            return f"{action}隐藏UID!\n特征码[{masked_uid}]"
        masked_uid = hide_uid(
            uid,
            user_pref=await get_hide_uid_pref(uid, ev.user_id, ev.bot_id),
        )
        if func == "体力背景":
            if not value:
                return f"已重置体力背景为默认!\n特征码[{masked_uid}]"
            if bg_random_hint:
                return f"设置成功!\n特征码[{masked_uid}]\n当前{func}:{value}\n(未指定角色, 将按类型随机选图)"
            return f"设置成功!\n特征码[{masked_uid}]\n当前{func}:{value}\n例:椿 官方 立绘/背景\n或直接设为固定图片ID"
        return f"设置成功!\n特征码[{masked_uid}]\n当前{func}:{value}"
    else:
        return "设置失败!\n请检查参数是否正确!"
