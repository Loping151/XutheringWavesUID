from typing import Dict

from gsuid_core.data_store import get_res_path
from gsuid_core.utils.plugins_config.models import (
    GSC,
    GsIntConfig,
    GsStrConfig,
    GsBoolConfig,
    GsImageConfig,
)

show_path = get_res_path(["XutheringWavesUID", "show"])

SHOW_CONIFG: Dict[str, GSC] = {
    "LoginIndexHtmlPath": GsStrConfig(
        "登录页面HTML路径，一般不用改，可直接上传",
        "自定义登录页面HTML文件路径，请自行确保模板格式正确，尤其注意在移动端显示良好",
        str(show_path / "index.html"),
    ),
    "LoginIndexEmailHtmlPath": GsStrConfig(
        "邮箱登录页面HTML路径，一般不用改，可直接上传",
        "自定义邮箱登录页面HTML文件路径，请自行确保模板格式正确，尤其注意在移动端显示良好",
        str(show_path / "index_email.html"),
    ),
    "LoginIndexCloudHtmlPath": GsStrConfig(
        "抽卡登录页面HTML路径，一般不用改，可直接上传",
        "自定义抽卡登录页面HTML文件路径，请自行确保模板格式正确，尤其注意在移动端显示良好",
        str(show_path / "index_cloud.html"),
    ),
    "LoginAddTokenHtmlPath": GsStrConfig(
        "添加Token页面HTML路径，一般不用改，可直接上传",
        "自定义添加Token页面HTML文件路径，请自行确保模板格式正确",
        str(show_path / "add_token.html"),
    ),
    "LoginAddTokenHtmlUpload": GsImageConfig(
        "上传添加Token页面模板（上传格式html）",
        "",
        str(show_path / "add_token.html"),
        str(show_path),
        "add_token",
        "html",
    ),
    "Login404HtmlPath": GsStrConfig(
        "404页面HTML路径，一般不用改，可直接上传",
        "自定义404页面HTML文件路径，请自行确保模板格式正确，尤其注意在移动端显示良好",
        str(show_path / "404.html"),
    ),
    "LoginIndexHtmlUpload": GsImageConfig(
        "上传登录页面模板（上传格式html）",
        "",
        str(show_path / "index.html"),
        str(show_path),
        "index",
        "html",
    ),
    "LoginIndexEmailHtmlUpload": GsImageConfig(
        "上传邮箱登录页面模板（上传格式html）",
        "",
        str(show_path / "index_email.html"),
        str(show_path),
        "index_email",
        "html",
    ),
    "LoginIndexCloudHtmlUpload": GsImageConfig(
        "上传抽卡登录页面模板（上传格式html）",
        "",
        str(show_path / "index_cloud.html"),
        str(show_path),
        "index_cloud",
        "html",
    ),
    "Login404HtmlUpload": GsImageConfig(
        "上传404页面模板（上传格式html）",
        "",
        str(show_path / "404.html"),
        str(show_path),
        "404",
        "html",
    ),
    "BlurRadius": GsIntConfig(
        "毛玻璃半径越大，毛玻璃效果越明显，0为不开启",
        "毛玻璃半径越大，毛玻璃效果越明显",
        0,
        100,
    ),
    "BlurBrightness": GsStrConfig(
        "毛玻璃亮度",
        "毛玻璃亮度",
        "1.2",
        ["0.9", "1.0", "1.1", "1.2", "1.3", "1.4", "1.5"],
    ),
    "BlurContrast": GsStrConfig(
        "毛玻璃对比度",
        "毛玻璃对比度",
        "0.9",
        ["0.8", "0.85", "0.9", "0.95", "1.0", "1.05", "1.1"],
    ),
    "CardBg": GsBoolConfig(
        "是否开启自定义面板背景",
        "开启路径位于XutheringWavesUID/show",
        False,
    ),
    "CardBgPath": GsImageConfig(
        "自定义背景",
        "自定义背景图片，亦用于排行等背景",
        str(show_path / "card.jpg"),
        str(show_path),
        "card",
        "jpg",
    ),
    "MrUseBG": GsBoolConfig(
        "自定义每日使用立绘还是背景",
        "False为使用立绘，True为使用背景，没有背景时使用立绘，存放在custom_mr_bg内",
        False,
    ),
    "HelpBannerBgUpload": GsImageConfig(
        "帮助横幅背景图（建议1545x551）",
        "自定义帮助页面横幅背景图",
        str(show_path / "help_banner.png"),
        str(show_path),
        "help_banner",
        "png",
    ),
    "HelpBgUpload": GsImageConfig(
        "帮助背景图",
        "自定义帮助页面背景图",
        str(show_path / "help_bg.png"),
        str(show_path),
        "help_bg",
        "png",
    ),
    "HelpIconUpload": GsImageConfig(
        "帮助图标（建议256x256）",
        "自定义帮助页面图标",
        str(show_path / "help_icon.png"),
        str(show_path),
        "help_icon",
        "png",
    ),
    "HelpColumn": GsIntConfig(
        "帮助页面列数（建议5）",
        "帮助页面每列显示的功能数量",
        5,
        10,
    ),
}
