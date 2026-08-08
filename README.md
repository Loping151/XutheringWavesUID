# XutheringWavesUID

<p align="center">
  <a href="https://github.com/Loping151/XutheringWavesUID"><img src="./ICON.png" width="256" height="256" alt="XutheringWavesUID"></a>
<h1 align = "center">XutheringWavesUID</h1>

## 说明

本插件为 [WutheringWavesUID](https://github.com/tyql688) 的构建版本，加强了评分和伤害计算的保护，确保本地计算的权重和伤害与服务器一致。

另外：目前提供可在网页直接使用的web版，无需在社交软件上使用：[WEBUID 传送门](https://ngabbs.com/read.php?tid=45645691)

国际服用户支持识别直出（ww分析帮助），同时支持小程序、库街区截图使用，无需任何登录绑定等操作：[用例](https://github.com/Loping151/ScoreEcho)，支持伤害计算功能。本插件不强行要求用户提供任何登录信息，登录信息仅用于查询更多游戏数据。

<details>
  <summary>用例</summary>
  <p align="center">
    <img src="https://img.nga.178.com/attachments/mon_202511/30/nqQ1aq-2wfzKwT1kSc6-80.jpg" alt="示例图" width="480" />
    <img src="https://img.nga.178.com/attachments/mon_202511/30/nqQ1aq-cqzxZjT1kShs-1ey.jpg" alt="示例图" width="480" />
    <img src="https://img.nga.178.com/attachments/mon_202511/30/nqQ1aq-leszKqToS5j-cn.jpg" alt="示例图" width="480" />
    <img src="https://img.nga.178.com/attachments/mon_202511/30/nqQ1aq-l5caZiT1kShs-1ey.jpg" alt="示例图" width="480" />
  </p>
</details><br>

在线使用：[识别计算 传送门](https://scoreecho.loping151.site/)

安装：参考 https://github.com/Genshin-bots/gsuid_core 安装插件的一般方式
```
# 直接clone到插件目录：
git clone https://github.com/Loping151/XutheringWavesUID.git
``` 

群友的拓展教程：
https://blog.ovoii.io/posts/notes/wwbot 

总排行申请、反馈（仅限主人）：群号 885617919（主群封禁中，备用群 387393347）（入群问题注意大小写）。如**完全**不使用QQ平台（如飞书、Discord等），可发邮件给客服小维 agent@loping151.com（记得写标题避免被小维当成垃圾邮件）申请计算token，要求附带具体使用平台、core信息截图和使用情况和规模说明，支持较少的请求量和用户量，但完全足以小范围使用，一般都欢迎入群。

- 为什么需要申请总排行进行使用：
  
    为了确保不被上传大量伪造数据影响持有率、排行等，以及 https://ngabbs.com/read.php?tid=45654606

- 总排行申请有无条件？

    待在群里，潜水不沙

- 除了总排行，插件本体功能是否有其他内容需要申请：

    无。评分与主插件可共用一个 token，也可脱离主插件独立使用。

## 丨网页面板/背景图编辑器

内置面板图/MR 背景图/MR 立绘的浏览·裁剪·上传·编辑·管理网页工具。控制台配置设置 `WavesPanelEditPassword` 为非空启用，入口 `http://<HOST>:<PORT>/waves/panel-edit/`（Basic Auth，用户名 `admin`）。

## 丨拓展

### 鸣潮相关

签到功能：[RoverSign](https://github.com/Loping151/RoverSign)

分析评分功能：[ScoreEcho](https://github.com/Loping151/ScoreEcho)

体力推送功能：[RoverReminder](https://github.com/Loping151/RoverReminder)

### 其他工具

自建外置渲染：[RemoteRender](https://github.com/Loping151/RemoteRender) （或者直接使用我的）

谁AT我功能：[AT_Tracker](https://github.com/Loping151/AT_Tracker)

表情包扩展：[core_plugin_memes](https://github.com/Loping151/core_plugin_memes)

## 丨安装提醒

> **注意：该插件为[早柚核心(gsuid_core)](https://github.com/Genshin-bots/gsuid_core)
的扩展，具体安装方式可参考[GenshinUID](https://github.com/KimigaiiWuyi/GenshinUID)**
>
> 可以直接对bot发送`core安装插件XutheringWavesUID`，然后重启core以应用安装**
>
> **权重和伤害计算更新时，仅需发送 ww下载全部资源 将自动重载**
>
> **建议安装以下额外依赖：**
> - `playwright`：用于渲染公告、wiki图等功能。**安装后还需执行 `uv run playwright install chromium` 下载浏览器内核**（core 不会自动下载）
> - `opencv-python`：用于面板图重复判断、提取面板图、相似度识别、矩阵显示共鸣链等功能
> - `fonttools`：用于多语言字体 fallback，未安装时日韩文可能显示为方框
> - `pypinyin`：用于模糊建议（含打错字、顺序颠倒等容错）
> - `rapidfuzz`：配合 `pypinyin` 加速模糊匹配，并启用近子串容错（typo 子串也能命中）
>
> **大多数情况下你不用手动装这些**：core 启动时会读取本插件 `pyproject.toml` 的 `[project].dependencies`，对未安装的依赖自动通过多镜像 fallback（字节 → 阿里 → 清华 → 官方）调用 `pip install`。core 日志中能看到 `[CMD执行] ... pip install ...` 即表示在自动装。
>
> **但 core 自动安装并不保证成功**（如全部镜像不通、网络异常、磁盘问题、AutoInstallDep 配置被关闭等）。如果启动后日志提示某依赖缺失，或上述功能未启用，请手动执行：
>
> ```bash
> # Linux/Mac
> source .venv/bin/activate && uv pip install playwright opencv-python fonttools pypinyin rapidfuzz && uv run playwright install chromium
> # Windows
> .venv\Scripts\activate; uv pip install playwright opencv-python fonttools pypinyin rapidfuzz; uv run playwright install chromium
> ```
>
> 如果 core 已经把 Python 包都装好了，`playwright` 浏览器内核（`playwright install chromium`）这一步仍需自己执行一次。
>
> **如有条件，建议为系统补充以下字体，避免官方公告使用特殊字符时渲染异常：**
> - emoji 字体：如 `Noto Color Emoji`、`Apple Color Emoji`、`Segoe UI Emoji`
> - 颜文字 / 符号字体：如 `Symbola`、`Noto Sans Symbols2`
> - 汉字字体：如 `Noto Sans CJK SC/TC/JP/KR`、`Source Han Sans` 等覆盖中日韩的字体

## 丨其他

+ 本项目仅供学习使用，请勿用于商业用途，禁止将**仅具有本插件功能**的服务进行收费。涉及本插件的一切收费行为与开发者无关，开发者不参与任何收费分成。本插件亦没有付费版本或付费解锁的功能，包括签到仓库和分析仓库。

+ 写给一般用户：但仍请考虑到即使仅具有本插件功能，部署也需要少量的服务器或电费。群内已尽可能提供其他技术支持，包含十分低价的流量和免费的网络服务。部署并非零成本的，但绝非高成本的。

+ 使用总排行功能可进行鉴别，总排行免费对所有有能力搭建的主人开放，总排行应包含各种各样的Bot

+ [GPL-3.0 License](https://github.com/Loping151/XutheringWavesUID/blob/main/LICENSE)

本仓库仅允许正常、可沟通、具有良知的个体部署，原因：https://ngabbs.com/read.php?tid=45654606 以及：[link](./assets/0428.md)。

## 支持设备列表：
win_amd64: python3.10-3.14<br>
win_arm64: not yet<br>
linux_x86_64: python3.10-3.14<br>
linux_aarch64: python3.10-3.14<br>
macos_intel: python3.10-3.14<br>
macos_apple: python3.10-3.14<br>
android_termux: python3.10-3.14<br>

**！本插件所含构建没有任何风险后门！本插件所含构建只读取gsuid_core目录下的文件，只请求非构建部分显示的域名！请随意进行流量检查和读写检查！**

## 致谢
- ⭐[Echo](https://github.com/tyql688)
- 特别鸣谢 [Wuyi无疑](https://github.com/KimigaiiWuyi) 为 WutheringWavesUID 作出的巨大贡献！本插件的设计图均出自 Wuyi无疑
  之手！！！
- [鸣潮声骸评分工具](http://asfaz.cn/mingchao/rule.html) 鸣潮声骸评分工具
- [waves-plugin](https://github.com/erzaozi/waves-plugin) Yunzai 鸣潮游戏数据查询插件
- [Yunzai-Kuro-Plugin](https://github.com/TomyJan/Yunzai-Kuro-Plugin) Yunzai 库洛插件
- [Kuro-API-Collection](https://github.com/TomyJan/Kuro-API-Collection) 库街区 API 文档
- 特别鸣谢以下攻略作者
  - [Moealkyne](https://www.taptap.cn/user/533395803)
  - [小沐XMu](https://www.kurobbs.com/person-center?id=10450567)
  - [金铃子攻略组](https://space.bilibili.com/487275027)
  - [結星](https://www.kurobbs.com/person-center?id=10015697)
  - [小羊早睡不遭罪](https://space.bilibili.com/37331716)
  - [吃我无痕](https://space.bilibili.com/347744)
  - [巡游天国FM](https://space.bilibili.com/444694026)
 
  
<img src="./assets/footer.png" alt="footer" width="1000" />
