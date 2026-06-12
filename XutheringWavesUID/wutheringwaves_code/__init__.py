import re
import json
import time
from datetime import datetime, timedelta

import httpx

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event

from ..utils.api.api import get_local_proxy_url
from ..utils.api.wwapi import GET_CODE_URL

sv_waves_code = SV("鸣潮兑换码")

invalid_code_list = ("MINGCHAO",)

url = "https://newsimg.5054399.com/comm/mlcxqcommon/static/wap/js/data_102.js?{}&callback=?&_={}"
request_headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://www.4399.com/",
    "Accept": "*/*",
}


@sv_waves_code.on_fullmatch(
    ("code", "兑换码", "兌換碼"),
    to_ai="""查询鸣潮当前所有可用的兑换码 + 奖励内容 + 过期时间。

当用户问「有什么兑换码 / 前瞻兑换码」时调用。不需要绑定。

Args:
    text: 无需参数，留空即可。
""",
)
async def get_sign_func(bot: Bot, ev: Event):
    code_list = await get_code_list()
    if not code_list:
        return await bot.send("[鸣潮·获取兑换码失败] 请稍后再试")

    msgs = []
    for code in code_list:
        is_fail = code.get("is_fail", "0")
        if is_fail == "1":
            continue
        order = code.get("order", "")
        if order in invalid_code_list or not order:
            continue
        label = code.get("label", "")
        if is_code_expired(label):
            continue
        reward = code.get("reward", "")
        msg = [f"兑换码: {order}", f"奖励: {reward}", label]
        msgs.append("\n".join(msg))

    if not msgs:
        return await bot.send("[鸣潮] 暂无可用兑换码")
    await bot.send(msgs)


async def get_code_list():
    now = datetime.now()
    time_string = f"{now.year - 1900}{now.month - 1}{now.day}{now.hour}{now.minute}"
    now_time = int(time.time() * 1000)
    new_url = url.format(time_string, now_time)

    async def fetch(proxy=None):
        async with httpx.AsyncClient(proxy=proxy, timeout=None) as client:
            res = await client.get(new_url, headers=request_headers, timeout=10)
            res.raise_for_status()
            json_data = res.text.split("=", 1)[1].strip().rstrip(";")
            logger.debug(f"[鸣潮·获取兑换码] url:{new_url}, codeList:{json_data}")
            return json.loads(json_data)

    try:
        return await fetch()
    except Exception as e:
        logger.exception("[鸣潮·获取兑换码失败] ", e)

    proxy_url = get_local_proxy_url()
    if proxy_url:
        for attempt in range(3):
            try:
                return await fetch(proxy_url)
            except Exception as e:
                logger.warning(f"[鸣潮·获取兑换码] 代理重试失败 ({attempt + 1}/3): {e}")

    try:
        from ..wutheringwaves_config import WutheringWavesConfig

        waves_token = WutheringWavesConfig.get_config("WavesToken").data
        async with httpx.AsyncClient(timeout=None) as client:
            res = await client.get(
                GET_CODE_URL,
                headers={"Authorization": f"Bearer {waves_token}"},
                timeout=10,
            )
            return res.json()["data"]
    except Exception as e:
        logger.warning(f"[鸣潮·获取兑换码] 备用接口失败: {e}")
    return


def is_code_expired(label: str) -> bool:
    if not label:
        return False

    # 使用正则提取月份和日期
    pattern = r"(\d{1,2})月(\d{1,2})日(\d{1,2})点"
    match = re.search(pattern, label)
    if not match:
        return False

    expire_month = int(match.group(1))
    expire_day = int(match.group(2))
    expire_hour = int(match.group(3))

    now = datetime.now()
    if expire_hour == 24:
        expire_hour, expire_min, expire_sec = 23, 59, 59
    else:
        expire_min, expire_sec = 0, 0

    # 取距 now 最近的候选年(±183 天窗口), 兼顾年初查去年末码 / 年末查明年初码两种跨年场景。
    # 整 183 天歧义点采用 >= 显式归前/后一年, 不留模糊地带。
    expire_date = datetime(now.year, expire_month, expire_day, expire_hour, expire_min, expire_sec)
    if expire_date - now >= timedelta(days=183):
        expire_date = expire_date.replace(year=now.year - 1)
    elif now - expire_date >= timedelta(days=183):
        expire_date = expire_date.replace(year=now.year + 1)

    return now > expire_date
