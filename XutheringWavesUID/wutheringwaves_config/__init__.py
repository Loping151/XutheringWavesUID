import re

from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.sv import SV, get_plugin_available_prefix

from ..utils.database.models import WavesBind
from ..utils.name_convert import alias_to_char_name
from .set_config import set_waves_user_value
from .wutheringwaves_config import WutheringWavesConfig

sv_self_config = SV("鸣潮配置")


PREFIX = get_plugin_available_prefix("XutheringWavesUID")


@sv_self_config.on_prefix("设置")
async def send_config_ev(bot: Bot, ev: Event):
    at_sender = True if ev.group_id else False

    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if uid is None:
        return await bot.send(
            f"您还未绑定鸣潮特征码, 请使用【{PREFIX}绑定uid】 完成绑定！\n", at_sender
        )

    if "体力背景" in ev.text:
        from ..utils.waves_api import waves_api

        ck = await waves_api.get_self_waves_ck(uid, ev.user_id, ev.bot_id)
        if not ck:
            from ..utils.error_reply import ERROR_CODE, WAVES_CODE_102

            return await bot.send(
                f"当前特征码：{uid}\n{ERROR_CODE[WAVES_CODE_102]}", at_sender
            )
        func = "体力背景"
        value = ev.text.replace("体力背景", "").strip()
        if not value:
            char_name = ""
        #     return await bot.send("[鸣潮] 请输入正确的角色名...\n", at_sender)
        char_name = alias_to_char_name(value)
        # if not char_name:
        #     return await bot.send(
        #         f"[鸣潮] 角色名【{value}】无法找到, 可能暂未适配, 请先检查输入是否正确！\n",
        #         at_sender,
        #     )
        im = await set_waves_user_value(ev, func, uid, char_name)
    elif "群排行" in ev.text:
        if ev.user_pm > 3:
            return await bot.send("[鸣潮] 群排行设置需要群管理才可设置\n", at_sender)
        if not ev.group_id:
            return await bot.send("[鸣潮] 请使用群聊进行设置\n", at_sender)

        WavesRankUseTokenGroup = set(
            WutheringWavesConfig.get_config("WavesRankUseTokenGroup").data
        )
        WavesRankNoLimitGroup = set(
            WutheringWavesConfig.get_config("WavesRankNoLimitGroup").data
        )

        if "1" in ev.text:
            # 设置为 无限制
            WavesRankNoLimitGroup.add(ev.group_id)
            # 删除token限制
            WavesRankUseTokenGroup.discard(ev.group_id)
            msg = f"[鸣潮] 【{ev.group_id}】群排行已设置为[无限制上榜]\n"
        elif "2" in ev.text:
            # 设置为 token限制
            WavesRankUseTokenGroup.add(ev.group_id)
            # 删除无限制
            WavesRankNoLimitGroup.discard(ev.group_id)
            msg = f"[鸣潮] 群【{ev.group_id}】群排行已设置为[登录后上榜]\n"
        else:
            return await bot.send(
                "[鸣潮] 群排行设置参数失效\n1.无限制上榜\2.登录后上榜\n", at_sender
            )

        WutheringWavesConfig.set_config(
            "WavesRankUseTokenGroup", list(WavesRankUseTokenGroup)
        )
        WutheringWavesConfig.set_config(
            "WavesRankNoLimitGroup", list(WavesRankNoLimitGroup)
        )
        return await bot.send(msg, at_sender)
    else:
        return await bot.send("请输入正确的设置信息...\n", at_sender)

    await bot.send(im, at_sender)
