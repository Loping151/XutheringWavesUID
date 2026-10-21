import json
from pathlib import Path

from gsuid_core.help.draw_new_plugin_help import get_new_help

from ..version import XutheringWavesUID_version
from ..utils.image import get_footer
from ..wutheringwaves_config import PREFIX, ShowConfig
from ..wutheringwaves_help.get_help import ICON, ICON_PATH, attach_icons
from ..wutheringwaves_help.change_help import _load_change_help_images, TEXT_PATH

HELP_DATA = Path(__file__).parent / "weight_help.json"


async def get_weight_help(pm: int):
    banner_bg_config = ShowConfig.get_config("HelpBannerBgUpload").data
    help_bg_config = ShowConfig.get_config("HelpBgUpload").data
    plugin_icon_config = ShowConfig.get_config("HelpIconUpload").data
    column_config = ShowConfig.get_config("HelpColumn").data

    banner_bg_path = Path(banner_bg_config) if banner_bg_config and Path(banner_bg_config).exists() else TEXT_PATH / "banner_bg.jpg"
    help_bg_path = Path(help_bg_config) if help_bg_config and Path(help_bg_config).exists() else TEXT_PATH / "bg.jpg"
    plugin_icon_path = Path(plugin_icon_config) if plugin_icon_config and Path(plugin_icon_config).exists() else ICON

    plugin_icon, banner_bg, help_bg, cag_bg, item_bg = await _load_change_help_images(plugin_icon_path, banner_bg_path, help_bg_path)
    help_data = json.loads(HELP_DATA.read_text(encoding="utf-8"))
    return await get_new_help(
        plugin_name="XutheringWavesUID",
        plugin_info={f"v{XutheringWavesUID_version}": ""},
        plugin_icon=plugin_icon,
        plugin_help=attach_icons(help_data, ICON_PATH),
        plugin_prefix=PREFIX,
        help_mode="dark",
        banner_bg=banner_bg,
        banner_sub_text="自定义权重 · www.loping151.site",
        help_bg=help_bg,
        cag_bg=cag_bg,
        item_bg=item_bg,
        icon_path=ICON_PATH,
        footer=get_footer(),
        enable_cache=False,
        column=column_config,
        pm=pm,
    )
