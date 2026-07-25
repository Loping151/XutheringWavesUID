import json
from typing import Dict, List, Union

from gsuid_core.bot import msgjson
from gsuid_core.logger import logger

from ..utils.name_convert import (
    alias_to_char_name_list,
    alias_to_char_name_optional,
    char_name_to_char_id,
)
from ..utils.resource.RESOURCE_PATH import CUSTOM_CHAR_ALIAS_PATH, waves_templates
from ..utils.render_utils import (
    PLAYWRIGHT_AVAILABLE,
    render_html,
    get_footer_b64,
)
from ..wutheringwaves_config import WutheringWavesConfig
from ..utils.image import (
    get_square_avatar,
    pil_to_b64,
    get_custom_waves_bg,
)
from .char_alias_pil import draw_char_alias_pil


class CharAliasOps:
    def __init__(self):
        self.custom_data = None
        self.load_custom_data()

    def load_custom_data(self):
        with open(CUSTOM_CHAR_ALIAS_PATH, "r", encoding="UTF-8") as f:
            self.custom_data = msgjson.decode(f.read(), type=Dict[str, List[str]])

    def save_custom_data(self):
        with open(CUSTOM_CHAR_ALIAS_PATH, "w", encoding="UTF-8") as f:
            json.dump(self.custom_data, f, ensure_ascii=False, indent=2)

    def delete_char_alias(self, char_name: str, new_alias: str, save: bool = True) -> str:
        if not self.custom_data:
            return "别名配置文件不存在，请检查文件路径"

        std_char_name = alias_to_char_name_optional(char_name)
        if not std_char_name:
            return "未找到指定角色，请检查输入！"

        # 删除路径只校验目标角色 + alias 是否在该角色 list 内,
        # 不再要求 alias 本身能反解 (脏数据 / 旧 alias 未加载到全局索引也得能清掉)。
        if std_char_name not in self.custom_data:
            return f"角色【{char_name}】不存在别名文件内，请检查文件"

        if new_alias not in self.custom_data[std_char_name]:
            return f"别名【{new_alias}】不存在，无法删除"

        self.custom_data[std_char_name].remove(new_alias)
        if save:
            self.save_custom_data()
        return f"成功为角色【{std_char_name}】删除别名【{new_alias}】"

    def add_char_alias(self, char_name: str, new_alias: str, save: bool = True) -> str:
        if not self.custom_data:
            return "别名配置文件不存在，请检查文件路径"

        std_char_name = alias_to_char_name_optional(char_name)
        if not std_char_name:
            return "未找到指定角色，请检查输入！"

        check_new_alias = alias_to_char_name_optional(new_alias)
        if check_new_alias:
            return f"别名【{new_alias}】已被角色【{check_new_alias}】占用"

        self.custom_data.setdefault(std_char_name, []).append(new_alias)
        if save:
            self.save_custom_data()
        return f"成功为角色【{char_name}】添加别名【{new_alias}】"


async def action_char_alias_batch(
    action: str, char_name: str, new_aliases: List[str]
) -> List[str]:
    """批量增/删别名：一次 load + 一次 save。任一别名校验通过即生效；
    失败者只回错误消息但不丢已成功的修改。"""
    if not CUSTOM_CHAR_ALIAS_PATH.exists():
        return ["别名配置文件不存在，请检查文件路径"]
    if action not in ("添加", "删除"):
        return ["无效的操作，请检查操作"]

    cao = CharAliasOps()
    msgs: List[str] = []
    mutated = False
    for alias in new_aliases:
        if action == "添加":
            msg = cao.add_char_alias(char_name, alias, save=False)
        else:
            msg = cao.delete_char_alias(char_name, alias, save=False)
        msgs.append(msg)
        if "成功" in msg:
            mutated = True
    if mutated:
        cao.save_custom_data()
    return msgs


async def char_alias_list(char_name: str) -> Union[str, bytes]:
    std_char_name = alias_to_char_name_optional(char_name)
    if not std_char_name:
        return "未找到指定角色，请检查输入！"

    alias_list = alias_to_char_name_list(char_name)
    if not alias_list:
        return "未找到指定角色，请检查输入！"
    
    alias_list = [std_char_name] + [alias for alias in alias_list if alias != std_char_name]

    avatar_url = ""
    char_id = char_name_to_char_id(std_char_name)
    if char_id:
        try:
            avatar = await get_square_avatar(char_id)
            avatar_url = pil_to_b64(avatar, quality=75)
        except Exception as e:
            logger.warning(f"[鸣潮·别名] 角色【{std_char_name}】头像读取失败: {e}")

    # 尝试HTML渲染
    use_html_render = WutheringWavesConfig.get_config("UseHtmlRender").data
    if PLAYWRIGHT_AVAILABLE and use_html_render:
        try:
            logger.debug(f"[鸣潮·别名] 正在渲染角色【{std_char_name}】的别名列表...")

            bg_img = get_custom_waves_bg(bg="bg12", crop=False)
            bg_url = pil_to_b64(bg_img, quality=75)

            # 准备模板数据
            footer_b64 = get_footer_b64(footer_type="white") or ""
            context = {
                "char_name": std_char_name,
                "alias_list": alias_list,
                "footer_b64": footer_b64,
                "avatar_url": avatar_url,
                "bg_url": bg_url,
            }

            # 渲染HTML
            img_bytes = await render_html(waves_templates, "alias_card.html", context)
            if img_bytes:
                logger.info(f"[鸣潮·别名] 角色【{std_char_name}】别名列表渲染成功")
                return img_bytes
            else:
                logger.warning("[鸣潮·别名] HTML渲染返回空，回退到PIL")
        except Exception as e:
            logger.warning(f"[鸣潮·别名] HTML渲染失败: {e}，回退到PIL")

    try:
        return await draw_char_alias_pil(
            std_char_name,
            alias_list,
            avatar_url,
            str(char_id or ""),
        )
    except Exception as e:
        logger.exception(f"[鸣潮·别名] 角色别名PIL渲染失败: {e}")

    # 回退到文本发送
    return f"角色{std_char_name}别名列表：" + " ".join(alias_list)
