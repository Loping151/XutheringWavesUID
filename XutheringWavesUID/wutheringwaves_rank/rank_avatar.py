"""rank 模块共用的头像逻辑（fallback：sender_avatar → DB → QQ → 角色头像）"""
import io
from pathlib import Path
from typing import Optional

import httpx
from PIL import Image

from gsuid_core.logger import logger
from gsuid_core.utils.image.image_tools import crop_center_img

from ..utils.cache import TimedCache
from ..utils.database.models import WavesUser
from ..utils.image import get_qq_avatar, get_square_avatar, is_qq_default_avatar
from ..utils.resource.constant import randomize_special_char_id
from ..wutheringwaves_config import WutheringWavesConfig

TEXT_PATH = Path(__file__).parent / "texture2d"

avatar_mask = Image.open(TEXT_PATH / "avatar_mask.png")
default_avatar_char_id = "1503"
pic_cache = TimedCache(600, 200)


async def _fetch_sender_avatar_image(url: str) -> Optional[Image.Image]:
    if not url or not url.startswith(("http://", "https://")):
        return None
    cache_key = f"sender:{url}"
    if WutheringWavesConfig.get_config("QQPicCache").data:
        cached = pic_cache.get(cache_key)
        if cached:
            return cached
    try:
        async with httpx.AsyncClient(timeout=6, follow_redirects=False) as client:
            r = await client.get(url, headers={"Referer": ""})
            if r.status_code != 200 or not r.content or is_qq_default_avatar(r.content):
                return None
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        pic_cache.set(cache_key, img)
        return img
    except Exception as e:
        logger.debug(f"[鸣潮·排行头像] sender_avatar 抓取失败 url={url}: {e}")
        return None


async def _fetch_db_avatar_image(user_id: Optional[str]) -> Optional[Image.Image]:
    """从 WavesUser.avatar_url 取头像 URL 并下载"""
    if not user_id:
        return None
    try:
        url = await WavesUser.get_avatar_url(user_id)
    except Exception as e:
        logger.debug(f"[鸣潮·排行头像] db avatar_url 查询失败 user_id={user_id}: {e}")
        return None
    if not url:
        return None
    return await _fetch_sender_avatar_image(url)


async def get_avatar(
    qid: Optional[str],
    sender_avatar: Optional[str] = None,
    char_id: Optional[int] = None,
) -> Image.Image:
    """fallback：sender_avatar → DB avatar_url → QQ → 角色头像。

    DB 优先于 QQ：qlogo 对未注册号也返回占位图（非 None），放后面会盖过真实头像。
    """
    qid = str(qid) if qid is not None else None
    pic: Optional[Image.Image] = None
    if sender_avatar:
        pic = await _fetch_sender_avatar_image(sender_avatar)

    if pic is None:
        pic = await _fetch_db_avatar_image(qid)

    if pic is None and qid and qid.isdigit():
        if WutheringWavesConfig.get_config("QQPicCache").data:
            pic = pic_cache.get(qid)
        if pic is None:
            try:
                pic = await get_qq_avatar(qid, size=100)
            except Exception as e:
                logger.debug(f"[鸣潮·排行头像] QQ 头像获取失败 qid={qid}: {e}")
                pic = None
            if pic:
                pic_cache.set(qid, pic)

    if pic is not None:
        pic_temp = crop_center_img(pic, 120, 120)
        img = Image.new("RGBA", (180, 180))
        avatar_mask_temp = avatar_mask.copy()
        mask_pic_temp = avatar_mask_temp.resize((120, 120))
        img.paste(pic_temp, (0, -5), mask_pic_temp)
        return img

    fallback_char_id = randomize_special_char_id(int(char_id)) if char_id else default_avatar_char_id
    try:
        pic = await get_square_avatar(fallback_char_id)
    except Exception as e:
        logger.warning(f"[鸣潮·排行头像] 角色头像获取失败 char_id={fallback_char_id}: {e}")
        return Image.new("RGBA", (180, 180))

    pic_temp = Image.new("RGBA", pic.size)
    pic_temp.paste(pic.resize((160, 160)), (10, 10))
    pic_temp = pic_temp.resize((160, 160))

    avatar_mask_temp = avatar_mask.copy()
    mask_pic_temp = Image.new("RGBA", avatar_mask_temp.size)
    mask_pic_temp.paste(avatar_mask_temp, (-20, -45), avatar_mask_temp)
    mask_pic_temp = mask_pic_temp.resize((160, 160))

    img = Image.new("RGBA", (180, 180))
    img.paste(pic_temp, (0, 0), mask_pic_temp)
    return img
