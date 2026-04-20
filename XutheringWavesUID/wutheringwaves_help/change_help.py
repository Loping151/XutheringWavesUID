import json
from typing import Dict
from pathlib import Path

from PIL import Image

from gsuid_core.help.model import PluginHelp
from gsuid_core.help.draw_new_plugin_help import get_new_help

from ..version import XutheringWavesUID_version
from ..utils.image import get_footer
from ..wutheringwaves_config import PREFIX, ShowConfig

ICON = Path(__file__).parent.parent.parent / "ICON.png"
HELP_DATA = Path(__file__).parent / "change_help.json"
ICON_PATH = Path(__file__).parent / "change_icon_path"
TEXT_PATH = Path(__file__).parent / "texture2d"


def get_help_data() -> Dict[str, PluginHelp]:
    # 读取文件内容
    with open(HELP_DATA, "r", encoding="utf-8") as file:
        return json.load(file)


plugin_help = get_help_data()


async def get_change_help(pm: int):
    # 与主帮助图共享 ShowConfig 的头像/背景配置
    banner_bg_config = ShowConfig.get_config("HelpBannerBgUpload").data
    help_bg_config = ShowConfig.get_config("HelpBgUpload").data
    plugin_icon_config = ShowConfig.get_config("HelpIconUpload").data
    column_config = ShowConfig.get_config("HelpColumn").data

    if banner_bg_config and Path(banner_bg_config).exists():
        banner_bg_path = Path(banner_bg_config)
    else:
        banner_bg_path = TEXT_PATH / "banner_bg.jpg"

    if help_bg_config and Path(help_bg_config).exists():
        help_bg_path = Path(help_bg_config)
    else:
        help_bg_path = TEXT_PATH / "bg.jpg"

    if plugin_icon_config and Path(plugin_icon_config).exists():
        plugin_icon_path = Path(plugin_icon_config)
    else:
        plugin_icon_path = ICON

    return await get_new_help(
        plugin_name="XutheringWavesUID",
        plugin_info={f"v{XutheringWavesUID_version}": ""},
        plugin_icon=Image.open(plugin_icon_path).convert("RGBA"),
        plugin_help=plugin_help,
        plugin_prefix=PREFIX,
        help_mode="dark",
        banner_bg=Image.open(banner_bg_path).convert("RGBA"),
        banner_sub_text="面板替换帮助",
        help_bg=Image.open(help_bg_path).convert("RGBA"),
        cag_bg=Image.open(TEXT_PATH / "cag_bg.png").convert("RGBA"),
        item_bg=Image.open(TEXT_PATH / "item.png").convert("RGBA"),
        icon_path=ICON_PATH,
        footer=get_footer(),
        enable_cache=False,
        column=column_config,
        pm=pm,
    )
