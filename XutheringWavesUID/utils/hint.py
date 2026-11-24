from typing import Optional

from gsuid_core.logger import logger
from .error_reply import ERROR_CODE
from ..wutheringwaves_config import PREFIX

BIND_UID_HINT = f"你还没有添加ck哦, 请使用 {PREFIX}添加CK 完成绑定！"

WAVES_ERROR_CODE = {}
WAVES_ERROR_CODE.update(ERROR_CODE)


def not_shown_msg(uid: str, peek: bool, what: str = "数据") -> str:
    if peek:
        return f"[鸣潮] 特征码[{uid}] 未在库街区展示{what}"
    return f"用户未展示{what}, 请尝试【{PREFIX}登录】"


def error_reply(code: Optional[int] = None, msg: str = "") -> str:
    msg_list = []
    if msg:
        msg_list.append(msg)
    elif code in WAVES_ERROR_CODE:
        msg_list.append(WAVES_ERROR_CODE[code])
    reply = "\n".join(msg_list)
    if isinstance(code, int):
        logger.error(f"[鸣潮·错误提示] ❌ 错误代码：{code} 📤 发送消息：{reply}")
    if msg:
        logger.error(f"[鸣潮·错误提示] 📝 错误信息：{msg}")
    return reply
