import json
from typing import Dict, Optional
from pathlib import Path

from PIL import Image

from gsuid_core.pool import to_thread
from gsuid_core.help.model import PluginHelp
from gsuid_core.help.draw_new_plugin_help import get_new_help

from ..version import XutheringWavesUID_version
from ..utils.image import get_footer
from ..wutheringwaves_config import PREFIX, ShowConfig, WutheringWavesConfig

ICON = Path(__file__).parent.parent.parent / "ICON.png"
HELP_DATA = Path(__file__).parent / "help.json"
ICON_PATH = Path(__file__).parent / "icon_path"
TEXT_PATH = Path(__file__).parent / "texture2d"


def match_icon(name: str, icons: Dict[str, Path]) -> Optional[Path]:
    """最长匹配优先, 同长取在名字里靠后的。"""
    best = None
    for stem, path in icons.items():
        pos = name.rfind(stem)
        if pos < 0:
            continue
        key = (len(stem), pos)
        if best is None or key > best[0]:
            best = (key, path)
    return best[1] if best else None


def attach_icons(help_data: Dict[str, PluginHelp], icon_dir: Path) -> Dict[str, PluginHelp]:
    icons = {p.stem: p for p in icon_dir.glob("*.png")}
    result = {}
    for cag, cag_data in help_data.items():
        items = []
        for item in cag_data["data"]:
            icon = match_icon(item["name"], icons)
            items.append({**item, "icon": str(icon)} if icon else item)
        result[cag] = {**cag_data, "data": items}
    return result

def get_help_data() -> Dict[str, PluginHelp]:
    # 读取文件内容
    with open(HELP_DATA, "r", encoding="utf-8") as file:
        help_content = json.load(file)

    # 获取额外模块配置
    extra_modules = WutheringWavesConfig.get_config("HelpExtraModules").data

    sign_help_items = [
        {
            "name": "签到",
            "desc": "鸣潮库街区每日签到（社区签到 + 完成日常任务）。用户主动让 AI 代签到合理；命令字也叫 `qd` / `社区签到` / `每日任务`。",
            "eg": "签到",
            "need_ck": True,
            "need_sk": False,
            "need_admin": False,
        },
        {
            "name": "签到日历",
            "desc": "查询自己当月签到日历图（哪天签了、当月累计签到多少天、累计奖励）。",
            "eg": "签到日历",
            "need_ck": True,
            "need_sk": False,
            "need_admin": False,
        },
        {
            "name": "开启/关闭自动签到",
            "desc": "为自己绑定的鸣潮账号开启或关闭每日自动签到。开启后由 bot 在每天固定时刻自动代签，不需要再手动 `签到`。命令字 `开启自动签到` / `关闭自动签到`。",
            "eg": "开启(鸣潮/战双)自动签到",
            "need_ck": True,
            "need_sk": False,
            "need_admin": False,
        },
    ]

    sign_admin_help_items = [
        {
            "name": "全部重新签到",
            "desc": "管理员一键给所有已开启自动签到的账号执行一次签到任务（管理员功能，普通用户不可调）。",
            "eg": "全部签到",
            "need_ck": False,
            "need_sk": False,
            "need_admin": True,
        },
        {
            "name": "订阅自动签到结果",
            "desc": "本群订阅每日自动签到结果汇总推送（管理员功能）。命令字 `订阅签到结果` / `取消订阅签到结果`。",
            "eg": "订阅签到结果",
            "need_ck": False,
            "need_sk": False,
            "need_admin": True,
        },
    ]

    todayecho_help = {
        "name": "梭哈",
        "desc": "本地模拟梭哈声骸（不消耗游戏内资源）。命令格式 `梭哈<次数>`，支持阿拉伯数字或中文数字（如「五次」「10次」）。每日上限 20 次（白名单 10 倍）。",
        "eg": "梭哈10次",
        "need_ck": False,
        "need_sk": False,
        "need_admin": False,
    }

    scoreecho_help_items = [
        {
            "name": "评分",
            "desc": "ScoreEcho 评分：发送一张声骸面板图 + `评分 <角色>{1c|3c|4c}(主词条)` 让插件给该声骸打分。例: `评分 卡提1c(生命)` 表示对卡提希娅 1 cost 生命主词条声骸评分。命令字 `评分` / `查分` / `pf`。",
            "eg": "评分 卡提1c(生命)",
            "need_ck": False,
            "need_sk": False,
            "need_admin": False,
        },
        {
            "name": "国际服使用",
            "desc": "ScoreEcho 国际服子模块（一套独立的分析功能）。先发 `分析帮助` 看完整命令列表，含 `分析登录`、`分析<角色>`、`分析练度`、`分析查看<角色>信息` 等。",
            "eg": "分析帮助",
            "need_ck": False,
            "need_sk": False,
            "need_admin": False,
        },
    ]

    roverreminder_help_items = [
        {
            "name": "推送邮箱",
            "desc": "设置体力到达阈值时邮件推送的收件邮箱。格式 `推送邮箱 <邮箱>`。若不设置且 user_id 是 QQ 号会自动用 <user_id>@qq.com。",
            "eg": "推送邮箱 123@qq.com",
            "need_ck": True,
            "need_sk": False,
            "need_admin": False,
        },
        {
            "name": "开启/关闭体力推送",
            "desc": "为自己绑定的鸣潮账号开关体力满阈值时的邮件推送提醒。命令字 `开启体力推送` / `关闭体力推送`。需先设置推送邮箱。",
            "eg": "开启/关闭体力推送",
            "need_ck": True,
            "need_sk": False,
            "need_admin": False,
        },
        {
            "name": "推送阈值",
            "desc": "设置体力到达多少时推送提醒，范围 120~240。格式 `推送阈值 <数字>`。默认按全局配置。",
            "eg": "推送阈值 180",
            "need_ck": True,
            "need_sk": False,
            "need_admin": False,
        },
    ]

    # 根据配置追加额外帮助
    if "todayecho" in extra_modules or "all" in extra_modules:
        if "个人服务" in help_content:
            help_content["个人服务"]["data"].append(todayecho_help)

    if "scoreecho" in extra_modules or "all" in extra_modules:
        if "信息查询" in help_content:
            help_content["信息查询"]["data"].extend(scoreecho_help_items)

    if "roversign" in extra_modules or "all" in extra_modules:
        if "个人服务" in help_content:
            help_content["个人服务"]["data"].extend(sign_help_items)
        if "bot主人功能" in help_content:
            help_content["bot主人功能"]["data"].extend(sign_admin_help_items)
            
    if "roverreminder" in extra_modules or "all" in extra_modules:
        if "个人服务" in help_content:
            help_content["个人服务"]["data"].extend(roverreminder_help_items)

    return help_content


plugin_help = get_help_data()


async def get_help(pm: int):
    # 从 ShowConfig 获取自定义配置，如果未配置或路径不存在则使用默认值
    banner_bg_config = ShowConfig.get_config("HelpBannerBgUpload").data
    help_bg_config = ShowConfig.get_config("HelpBgUpload").data
    plugin_icon_config = ShowConfig.get_config("HelpIconUpload").data
    column_config = ShowConfig.get_config("HelpColumn").data

    # 使用配置的路径（如果存在且配置了）或默认路径
    if banner_bg_config and Path(banner_bg_config).exists():
        banner_bg_path = Path(banner_bg_config)
    else:
        banner_bg_path = TEXT_PATH / "banner_bg.jpg"

    if help_bg_config and Path(help_bg_config).exists():
        help_bg_path = Path(help_bg_config)
    else:
        help_bg_path = TEXT_PATH / "bg.jpg"

    # plugin_icon: 插件主图标
    if plugin_icon_config and Path(plugin_icon_config).exists():
        plugin_icon_path = Path(plugin_icon_config)
    else:
        plugin_icon_path = ICON

    plugin_icon, banner_bg, help_bg, cag_bg, item_bg = await _load_help_images(
        plugin_icon_path, banner_bg_path, help_bg_path
    )

    return await get_new_help(
        plugin_name="XutheringWavesUID",
        plugin_info={f"v{XutheringWavesUID_version}": ""},
        plugin_icon=plugin_icon,
        plugin_help=attach_icons(plugin_help, ICON_PATH),
        plugin_prefix=PREFIX,
        help_mode="dark",
        banner_bg=banner_bg,
        banner_sub_text="漂泊者，欢迎在这个时代醒来。",
        help_bg=help_bg,
        cag_bg=cag_bg,
        item_bg=item_bg,
        icon_path=ICON_PATH,
        footer=get_footer(),
        enable_cache=False,
        column=column_config,
        pm=pm,
    )


@to_thread
def _load_help_images(plugin_icon_path: Path, banner_bg_path: Path, help_bg_path: Path):
    return (
        Image.open(plugin_icon_path).convert("RGBA"),
        Image.open(banner_bg_path).convert("RGBA"),
        Image.open(help_bg_path).convert("RGBA"),
        Image.open(TEXT_PATH / "cag_bg.png").convert("RGBA"),
        Image.open(TEXT_PATH / "item.png").convert("RGBA"),
    )
