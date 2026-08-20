import asyncio
from pathlib import Path

from PIL import Image
from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.pool import to_thread
from gsuid_core.segment import MessageSegment
from gsuid_core.utils.image.convert import convert_img

from ..utils.hint import error_reply
from ..utils.char_state import pop_pending_advice
from ..utils.char_info_utils import PATTERN
from ..utils.database.models import WavesBind
from ..utils.error_reply import WAVES_CODE_103
from ..utils.at_help import ruser_id, is_valid_at, is_intl_uid, intl_unavailable_msg
from ..utils.resource.constant import SPECIAL_CHAR
from ..utils.name_convert import char_name_to_char_id
from ..utils.name_resolve import resolve_char
from ..wutheringwaves_config import PREFIX, WutheringWavesConfig
from .draw_char_card import draw_char_score_img, draw_char_detail_img, draw_char_optimize_img
from .upload_card import (
    delete_custom_card,
    upload_custom_card,
    get_custom_card_list,
    delete_all_custom_card,
    compress_all_custom_card,
    recompute_all_orb_features,
)
from .card_utils import (
    CUSTOM_PATH_NAME_MAP,
    get_char_id_and_name,
    match_hash_id_from_event,
    send_custom_card_single,
    send_custom_card_single_by_id,
    send_repeated_custom_cards,
)


@to_thread
def _concat_refresh_and_detail(msg_bytes, im):
    from io import BytesIO
    refresh_img = Image.open(BytesIO(msg_bytes))
    total_width = max(refresh_img.width, im.width)
    new_im = Image.new("RGBA", (total_width, refresh_img.height + im.height))
    new_im.paste(refresh_img, ((total_width - refresh_img.width) // 2, 0))
    new_im.paste(im, ((total_width - im.width) // 2, refresh_img.height))
    return new_im


@to_thread
def _concat_pk_images(im1, im2):
    new_im = Image.new("RGBA", (im1.size[0] + im2.size[0], max(im1.size[1], im2.size[1])))
    new_im.paste(im1, (0, 0))
    new_im.paste(im2, (im1.size[0], 0))
    return new_im


def _has_phantom(role_detail) -> bool:
    """面板是否有声骸数据(有则出伤害计算部分)。"""
    pd = getattr(role_detail, "phantomData", None)
    eq = pd.equipPhantomList if pd else None
    return bool(eq) and any(p and p.phantomProp for p in eq)


def _space_hint() -> str:
    return f"[鸣潮] 尝试去掉{PREFIX}后的空格重试"


def _with_tip(payload, tip):
    """fuzzy 命中时在 payload 前补 tip; 否则原样返回。payload 可为单元素或列表。"""
    if not tip:
        return payload
    if isinstance(payload, list):
        return [tip, *payload]
    return [tip, payload]


def _append_advice(ev, payload):
    """把本次评分建议追加到消息末尾, 与图片同条发送; 无建议时原样返回。"""
    advice = pop_pending_advice(ev)
    if not advice:
        return payload
    if isinstance(payload, list):
        return [*payload, advice]
    if isinstance(payload, bytes):
        payload = MessageSegment.image(payload)
    return [payload, advice]


async def _resolve_self_uid(bot: Bot, ev: Event):
    """面板查询入口共享: 取 user_id(ruser_id) + 绑定 uid + 国际服拦截。

    返回 (uid, user_id); 已发完错误响应时返回 None, 调用方直接 return 即可。
    PK 路径需对"发起者本人"用 ev.user_id 的场景不适用, 仍走原模板。
    """
    user_id = ruser_id(ev)
    uid = await WavesBind.get_uid_by_game(user_id, ev.bot_id)
    if not uid:
        await bot.send(error_reply(WAVES_CODE_103))
        return None
    if is_intl_uid(uid):
        await bot.send(intl_unavailable_msg(uid))
        return None
    return uid, user_id

waves_upload_char = SV("waves上传面板图", priority=3, pm=1)
waves_char_card_single = SV("waves查看面板图", priority=3)
waves_char_card_list = SV("waves面板图列表", priority=3, pm=1)
waves_delete_char_card = SV("waves删除面板图", priority=3, pm=1)
waves_delete_all_card = SV("waves删除全部面板图", priority=3, pm=1)
waves_compress_card = SV("waves面板图压缩", priority=3, pm=1)
waves_recompute_orb = SV("waves重算ORB特征", priority=3, pm=1)
waves_repeated_card = SV("waves面板图查重", priority=2, pm=1)
waves_new_get_char_info = SV("waves新获取面板", priority=3)
waves_new_get_one_char_info = SV("waves新获取单个角色面板", priority=3)
waves_new_char_detail = SV("waves角色面板", priority=5)
waves_char_tips = SV("waves面板图权限提示和审核", priority=4)
waves_char_detail = SV("waves角色查询", priority=5)
waves_score_explain = SV("waves综合评分说明", priority=5)

_repeated_card_lock = asyncio.Lock()

SCORE_EXPLAIN_IMG = Path(__file__).parent / "综合评分说明.png"


# 类型别名 → 内部分类 (card/bg/stamina)。所有正则的 type 别名都从这里派生。
TYPE_MAP = {
    "面板": "card",
    "面版": "card",
    "面包": "card",
    "🍞": "card",
    "card": "card",
    "背景": "bg",
    "bg": "bg",
    "mr": "stamina",
    "每日": "stamina",
    "体力": "stamina",
}

# 正则用的别名 alternation; 与 TYPE_MAP 的 key 保持一致 (长别名优先, 避免 "面" 前缀冲突)。
_CARD_TYPES = "面板|面版|面包|🍞|card|体力|每日|mr|背景|bg"
_CARD_VERBS = "查看|提取|获取"


@waves_upload_char.on_regex(
    rf"^(?P<force>强制)?上传(?P<char>{PATTERN})(?P<type>{_CARD_TYPES})图$",
    block=True,
)
async def upload_char_img(bot: Bot, ev: Event):
    char = ev.regex_dict.get("char")
    if not char:
        return
    is_force = ev.regex_dict.get("force") is not None
    await upload_custom_card(
        bot,
        ev,
        char,
        target_type=TYPE_MAP.get(ev.regex_dict.get("type"), "card"),
        is_force=is_force,
    )
    

@waves_char_card_list.on_regex(rf"^(?P<char>{PATTERN})(?P<type>{_CARD_TYPES})图列表$", block=True)
async def get_char_card_list(bot: Bot, ev: Event):
    char = ev.regex_dict.get("char")
    if not char:
        return
    await get_custom_card_list(bot, ev, char, target_type=TYPE_MAP.get(ev.regex_dict.get("type"), "card"))


@waves_delete_char_card.on_regex(
    rf"^删除(?P<char>{PATTERN})(?P<type>{_CARD_TYPES})图\s*(?P<hash_id>[a-zA-Z0-9,，]+)$", block=True
)
async def delete_char_card(bot: Bot, ev: Event):
    char = ev.regex_dict.get("char")
    hash_id = ev.regex_dict.get("hash_id")
    if not char or not hash_id:
        return
    await delete_custom_card(bot, ev, char, hash_id, target_type=TYPE_MAP.get(ev.regex_dict.get("type"), "card"))


@waves_delete_all_card.on_regex(rf"^删除全部(?P<char>{PATTERN})(?P<type>{_CARD_TYPES})图$", block=True)
async def delete_all_char_card(bot: Bot, ev: Event):
    char = ev.regex_dict.get("char")
    if not char:
        return
    await delete_all_custom_card(bot, ev, char, target_type=TYPE_MAP.get(ev.regex_dict.get("type"), "card"))


# 任一别名都触发全量压缩 (card/bg/stamina 一锅压), 不按输入区分类型。
@waves_compress_card.on_fullmatch(("压缩面板图", "压缩面版图", "压缩面包图", "压缩🍞图", "压缩背景图", "压缩体力图", "压缩card图", "压缩bg图", "压缩mr图"), block=True)
async def compress_char_card(bot: Bot, ev: Event):
    await compress_all_custom_card(bot, ev)


@waves_recompute_orb.on_fullmatch(
    ("重新计算特征", "重新计算面板图特征", "重新计算orb", "重新计算面板图orb"),
    block=True,
)
async def recompute_orb_features_handler(bot: Bot, ev: Event):
    await recompute_all_orb_features(bot, ev)
    
    
# type 仅作触发文案不区分类型, send_repeated_custom_cards 始终遍历全部自定义图目录。
@waves_repeated_card.on_regex(
    rf"^查看重复(?:{_CARD_TYPES})图(?P<threshold>\s*\d+(?:\.\d+)?)?$",
    block=True,
)
async def repeated_char_card(bot: Bot, ev: Event):
    threshold = None
    raw_threshold = ev.regex_dict.get("threshold")
    if raw_threshold:
        try:
            threshold = float(raw_threshold.strip())
        except ValueError:
            threshold = None
    if threshold is None or not (0.5 <= threshold <= 1.0):
        threshold = None

    if _repeated_card_lock.locked():
        return
    await _repeated_card_lock.acquire()
    await bot.send("[鸣潮] 开始检查重复面板、背景、体力图，请稍后…")

    async def _run() -> None:
        try:
            if threshold is not None:
                await send_repeated_custom_cards(bot, ev, threshold=threshold)
            else:
                await send_repeated_custom_cards(bot, ev)
        finally:
            _repeated_card_lock.release()

    asyncio.create_task(_run())


async def _send_char_card_single(bot: Bot, ev: Event, char, hash_id, card_type):
    if not hash_id:
        at_sender = True if ev.group_id else False
        target_type = TYPE_MAP.get(card_type, "card")
        if char:
            char_id, _, msg = get_char_id_and_name(char)
            if msg:
                return await bot.send((" " if at_sender else "") + msg, at_sender)
            match = await match_hash_id_from_event(ev, target_type, char_id)
        else:
            match = await match_hash_id_from_event(ev, target_type, None)
        if not match:
            msg = "[鸣潮] 未找到相似图片，请提供id或附带图片。"
            return await bot.send((" " if at_sender else "") + msg, at_sender)
        hash_id = match[0]
    if not char:
        return await send_custom_card_single_by_id(bot, ev, hash_id)
    return await send_custom_card_single(
        bot,
        ev,
        char,
        hash_id,
        target_type=TYPE_MAP.get(card_type, "card"),
    )


@waves_char_card_single.on_regex(
    (
        rf"^(?:{_CARD_VERBS})(?P<char>{PATTERN})?(?P<type>{_CARD_TYPES})图(?P<hash_id>[a-zA-Z0-9]+)?$",
        rf"^(?P<char>{PATTERN})?(?P<type>{_CARD_TYPES})图(?:{_CARD_VERBS})(?P<hash_id>[a-zA-Z0-9]+)?$",
    ),
    block=True,
)
async def get_char_card_single(bot: Bot, ev: Event):
    return await _send_char_card_single(
        bot,
        ev,
        ev.regex_dict.get("char"),
        ev.regex_dict.get("hash_id"),
        ev.regex_dict.get("type"),
    )


@waves_char_card_single.on_fullmatch(("原图", "提取", "提取图片"), block=True)
async def get_char_card_shortcut(bot: Bot, ev: Event):
    return await _send_char_card_single(bot, ev, None, None, "面板")


# 触发时机: 用户输入命中下面 4 个 protected SV 的正则, 但 priority<4 处的 SV 因
# pm 检查未通过被跳过, 事件流到这里。如果用户对该 SV 实际有权限, priority=3 的
# 同 SV 会先 fire 并 block=True, 本 handler 永远不会进入。
# 单独存在的目的: 防止无权限输入 fall through 到 waves_char_detail 被错认为
# `char='上传X' / '删除X'` 之类的角色查询。
@waves_char_tips.on_regex(
    (
        rf"^(?P<kind_upload>(?:强制)?上传)(?P<char>{PATTERN})(?P<type>{_CARD_TYPES})图$",
        rf"^(?P<char>{PATTERN})(?P<type>{_CARD_TYPES})(?P<kind_list>图列表)$",
        rf"^(?P<kind_delete>删除)(?P<char>{PATTERN})(?P<type>{_CARD_TYPES})图\s*[a-zA-Z0-9,，]+$",
        rf"^(?P<kind_delete_all>删除全部)(?P<char>{PATTERN})(?P<type>{_CARD_TYPES})图$",
    ),
    block=True,
)
async def char_tips(bot: Bot, ev: Event):
    if ev.regex_dict.get("kind_upload") and WutheringWavesConfig.get_config("WavesUploadAudit").data:
        return await _forward_upload_to_master(bot, ev)
    await bot.send(
        "[鸣潮] 您没有「上传/查看列表/删除」面板图等权限，请联系主人处理面板图相关。"
    )


async def _forward_upload_to_master(bot: Bot, ev: Event):
    import time

    from gsuid_core.subscribe import gs_subscribe
    from ..utils.resource.RESOURCE_PATH import CUSTOM_CARD_PATH
    from .card_utils import (
        CUSTOM_PATH_MAP,
        delete_orb_cache,
        get_char_id_and_name,
        get_image,
        _fetch_image_bytes,
    )
    from .upload_card import check_image_dimensions, collect_blocked_duplicates

    images = await get_image(ev)
    if not images:
        return await bot.send("[鸣潮] 请同时发送要上传的图片。注意上传的图片应可用于体力背景/面板左上的角色图。")

    target_type = TYPE_MAP.get(ev.regex_dict.get("type"), "card")
    type_label = CUSTOM_PATH_NAME_MAP.get(target_type, "面板") + "图"

    char_id, char_name, err = get_char_id_and_name(ev.regex_dict.get("char") or "")
    if err or not char_id:
        return await bot.send(err or "[鸣潮] 角色名无法识别")

    # 下载到目标目录，复用主人上传同样的尺寸/查重校验，
    # 不通过则不转发主人；通过后清掉临时文件，等主人审核后再走正式上传
    temp_dir = CUSTOM_PATH_MAP.get(target_type, CUSTOM_CARD_PATH) / f"{char_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    image_bytes: list = []
    new_images: list = []
    size_check_failed: list = []
    try:
        for index, url in enumerate(images, start=1):
            b = await _fetch_image_bytes(url)
            if not b:
                logger.warning(f"[鸣潮·上传审核] 图片下载失败: {url}")
                continue
            temp_path = temp_dir / f"{char_id}_{int(time.time() * 1000)}_{index}.jpg"
            try:
                temp_path.write_bytes(b)
            except Exception as e:
                logger.warning(f"[鸣潮·上传审核] 写入临时文件失败: {e}")
                continue

            err_msg = check_image_dimensions(temp_path, target_type, index)
            if err_msg:
                size_check_failed.append(err_msg)
                temp_path.unlink(missing_ok=True)
                continue

            image_bytes.append(b)
            new_images.append(temp_path)

        if not new_images:
            if size_check_failed:
                return await bot.send("[鸣潮] 上传失败！\n" + "\n".join(size_check_failed))
            return await bot.send("[鸣潮] 上传图片下载失败，请稍后重试")

        block_msgs, blocked_paths = collect_blocked_duplicates(temp_dir, new_images)
        if blocked_paths:
            # 重复的清掉，不重复的继续转发
            for p in blocked_paths:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
                delete_orb_cache(p)
            kept = [(p, b) for p, b in zip(new_images, image_bytes) if p not in blocked_paths]
            new_images = [p for p, _ in kept]
            image_bytes = [b for _, b in kept]

        if not new_images:
            prefix_msg = ("\n".join(size_check_failed) + "\n") if size_check_failed else ""
            return await bot.send(
                f"[鸣潮]【{char_name}】{prefix_msg}全部疑似重复: {'；'.join(block_msgs)}，已拒绝转交主人审核"
            )

        if WutheringWavesConfig.get_config("WavesUploadAuditKeepLocal").data:
            try:
                from ..wutheringwaves_resource.panel_editor import storage as _pe_st
                for b in image_bytes:
                    _pe_st.save_pending(
                        target_type, char_id, b,
                        user_id=ev.user_id, group_id=ev.group_id,
                    )
            except Exception as e:
                logger.warning(f"[鸣潮·上传审核] 储存待审核图失败: {e}")

        subs = await gs_subscribe.get_subscribe("联系主人")
        logger.info(f"[鸣潮·上传审核] 取到 {len(subs) if subs else 0} 个主人订阅")
        if not subs:
            return await bot.send("[鸣潮] 当前无主人订阅审核通道，请联系主人配置")

        origin = f"用户 {ev.user_id}"
        if ev.group_id:
            origin += f" (群 {ev.group_id})"

        text = (
            f"[鸣潮·上传审核] {origin} 申请上传【{char_name}】的{type_label}\n"
            f"通过审核请发送: {PREFIX}上传{char_name}{type_label} 并附下方图片"
        )

        fail = 0
        for sub in subs:
            logger.info(
                f"[鸣潮·上传审核] 准备转发 sub bot_id={sub.bot_id} "
                f"user_id={sub.user_id} group_id={sub.group_id} "
                f"user_type={sub.user_type} bot_self_id={sub.bot_self_id} "
                f"WS_BOT_ID={sub.WS_BOT_ID}"
            )
            try:
                ret_text = await sub.send(text)
                logger.info(f"[鸣潮·上传审核] sub.send(text) 返回={ret_text}")
                for idx, b in enumerate(image_bytes):
                    ret_img = await sub.send(MessageSegment.image(b))
                    logger.info(f"[鸣潮·上传审核] sub.send(image#{idx}) 返回={ret_img}")
                    if ret_img == -1:
                        fail += 1
                if ret_text == -1:
                    fail += 1
            except Exception as e:
                fail += 1
                logger.exception(f"[鸣潮·上传审核] 转发失败 err={e}")

        if subs and fail == len(subs):
            return await bot.send("[鸣潮] 转发审核失败，请稍后再试或联系主人")
        tail = f"\n已剔除疑似重复: {'；'.join(block_msgs)}" if block_msgs else ""
        await bot.send(f"[鸣潮] 上传申请已提交给主人审核，请等待处理{tail}。注意上传的图片应可用于体力背景/面板左上的角色图。")
    finally:
        for p in new_images:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
            delete_orb_cache(p)


@waves_new_get_char_info.on_fullmatch(
    (
        "刷新面板",
        "刷新面版",
        "刷新面包",
        "刷新🍞",
        "更新面板",
        "更新面版",
        "更新面包",
        "更新🍞",
        "强制刷新",
        "面板刷新",
        "面包刷新",
        "🍞刷新",
        "面板更新",
        "面板",
        "面版",
        "面包",
        "🍞",
        "upd🍞",
        "updmb",
        "mb",
    ),
    block=True,
    to_ai="""从库街区**强制刷新**全部角色面板数据。

⚠️ 这是有 API 调用副作用的写操作（会更新本地数据库）。当用户问「刷新面板 / 更新面板 / 强制刷新」时调用。
需绑定 cookie。完成后会自动展示更新最大的角色面板。

如果用户只想看面板**不需要刷新**，应该用 search_knowledge 或 `角色面板` 命令。

Args:
    text: 无需参数，留空即可。
""",
)
async def send_card_info(bot: Bot, ev: Event):
    _ru = await _resolve_self_uid(bot, ev)
    if _ru is None:
        return
    uid, user_id = _ru

    from .draw_refresh_char_card import display_char_name, draw_refresh_char_detail_img

    buttons = []
    msg, num_updated, top_improver = await draw_refresh_char_detail_img(bot, ev, user_id, uid, buttons)
    if isinstance(msg, str) or isinstance(msg, bytes):
        await bot.send_option(msg, buttons)

    if (
        top_improver
        and isinstance(msg, bytes)
        and WutheringWavesConfig.get_config("AutoSendCharAfterRefresh").data
    ):
        char_name = display_char_name(top_improver["roleId"], top_improver["roleName"])
        delta = top_improver["delta"]
        old_score = top_improver["old"]
        new_score = top_improver["new"]
        tip = (
            f"[鸣潮] 你可能想查询【{PREFIX}{char_name}面板】，已执行该指令"
        )
        im = await draw_char_detail_img(ev, uid, char_name, user_id)
        if isinstance(im, str):
            await bot.send(_append_advice(ev, f"{tip}\n{im}"))
        elif isinstance(im, bytes):
            await bot.send(_append_advice(ev, [tip, MessageSegment.image(im)]))
    # if num_updated <= 1 and isinstance(msg, bytes):
    #     asyncio.sleep(10) # 先发完吧
    #     from ..wutheringwaves_config import PREFIX
    #     single_refresh_notice = f"本次刷新<2\n如仅需单刷新，可用 {PREFIX}刷新[角色]面板"
    #     await bot.send(f" {single_refresh_notice}" if ev.group_id else single_refresh_notice, at_sender=ev.group_id is not None)


@waves_new_get_one_char_info.on_regex(
    rf"^(?P<lead_space>\s+)?(?P<is_refresh>刷新|更新|upd)(?P<mid_space>\s+)?(?P<char>{PATTERN})(?P<query_type>面板|面版|面包|🍞|mb)$",
    block=True,
)
async def send_one_char_detail_msg(bot: Bot, ev: Event):
    logger.debug(f"[鸣潮·角色面板] RAW_TEXT: {ev.raw_text}")
    if ev.regex_dict.get("lead_space") or ev.regex_dict.get("mid_space"):
        return await bot.send(_space_hint())
    res = resolve_char(ev.regex_dict.get("char"))
    if not res.ok:
        return await bot.send(res.fail_msg("[鸣潮] 角色无法找到"))
    char = res.matched
    char_id = char_name_to_char_id(char)
    if not char_id or len(char_id) != 4:
        return await bot.send(res.fail_msg("[鸣潮] 角色无法找到"))
    tip = res.tip_text(f"{PREFIX}刷新{char}面板")
    refresh_type = SPECIAL_CHAR.copy()[char_id] if char_id in SPECIAL_CHAR else [char_id]

    _ru = await _resolve_self_uid(bot, ev)
    if _ru is None:
        return
    uid, user_id = _ru

    from .draw_refresh_char_card import draw_refresh_char_detail_img

    refresh_behavior = WutheringWavesConfig.get_config("RefreshSingleCharBehavior").data
    old_detail = None
    if refresh_behavior == "concat_diff":
        from ..utils.char_info_utils import get_char_detail_for_id
        old_detail = await get_char_detail_for_id(uid, char_id)
        if old_detail is not None and not _has_phantom(old_detail):
            old_detail = None

    buttons = []
    msg, num_updated, _top_improver = await draw_refresh_char_detail_img(bot, ev, user_id, uid, buttons, refresh_type)

    if num_updated <= 0:
        if isinstance(msg, str) or isinstance(msg, bytes):
            seg = MessageSegment.image(msg) if isinstance(msg, bytes) else msg
            await bot.send_option(_with_tip(seg, tip), buttons)
        return

    refresh_seg = MessageSegment.image(msg)

    if refresh_behavior == "refresh_only":
        return await bot.send_option(_with_tip(refresh_seg, tip), buttons)

    if refresh_behavior == "refresh_and_send_separately":
        # 唯一拆条发送的模式: tip 跟刷新结果同条, 面板图单独再发
        await bot.send(_with_tip(refresh_seg, tip))
        im = await draw_char_detail_img(ev, uid, char, user_id, None)
        await bot.send(_append_advice(ev, im))
        return

    if refresh_behavior == "concat_diff":
        new_im = await draw_char_detail_img(ev, uid, char, user_id, None, need_convert_img=False)
        old_im = None
        if old_detail is not None and isinstance(new_im, Image.Image):
            old_im = await draw_char_detail_img(
                ev, uid, char, user_id, None, need_convert_img=False, role_detail_override=old_detail
            )
        if isinstance(old_im, Image.Image) and isinstance(new_im, Image.Image):
            diff_im = await _concat_pk_images(old_im, new_im)
            seg = MessageSegment.image(await convert_img(diff_im))
            await bot.send(_append_advice(ev, _with_tip(seg, tip)))
            return
        # 无旧数据(无从对比): 退回 concatenate, 刷新小图与面板拼成一张
        if isinstance(new_im, str):
            await bot.send(_append_advice(ev, _with_tip([refresh_seg, new_im], tip)))
            return
        if isinstance(new_im, Image.Image):
            merged = await _concat_refresh_and_detail(msg, new_im)
            await bot.send(_append_advice(ev, _with_tip(MessageSegment.image(await convert_img(merged)), tip)))
            return
        await bot.send_option(_append_advice(ev, _with_tip(refresh_seg, tip)), buttons)
        return

    if refresh_behavior == "concatenate":
        im = await draw_char_detail_img(ev, uid, char, user_id, None, need_convert_img=False)
        if isinstance(im, str):
            await bot.send(_append_advice(ev, _with_tip([refresh_seg, im], tip)))
            return
        if isinstance(im, Image.Image):
            new_im = await _concat_refresh_and_detail(msg, im)
            await bot.send(_append_advice(ev, _with_tip(MessageSegment.image(await convert_img(new_im)), tip)))
            return
        await bot.send_option(_append_advice(ev, _with_tip(refresh_seg, tip)), buttons)
        return

    # refresh_and_send (default)
    im = await draw_char_detail_img(ev, uid, char, user_id, None)
    if isinstance(im, str):
        await bot.send(_append_advice(ev, _with_tip(im, tip)))
    else:
        await bot.send(_append_advice(ev, _with_tip([refresh_seg, MessageSegment.image(im)], tip)))


@waves_char_detail.on_prefix(
    ("角色面板", "查询"),
    to_ai="""查询自己某角色的完整面板图（属性 / 武器 / 声骸 / 共鸣链 / 实战伤害评分）。

当用户问「<角色>面板 / 角色面板 / 查询<角色>」时调用，是 XW 最核心的查询。
text 是角色名（已自动去掉前缀「角色面板」或「查询」）。需绑定 cookie。

注: 命令字为「查询」时不展示综合评分; 「角色面板」及其他面板入口照常显示。

Args:
    text: 角色名。例: "长离" / "椿" / "凌阳"。命令字 `角色面板` 或 `查询` 后跟角色名时 text 是角色名本身。
""",
)
async def send_char_detail_msg(bot: Bot, ev: Event):
    char = ev.text.strip(" ")
    logger.debug(f"[鸣潮·角色面板] CHAR: {char}")
    if not char:
        return
    _ru = await _resolve_self_uid(bot, ev)
    if _ru is None:
        return
    uid, user_id = _ru
    logger.debug(f"[鸣潮·角色面板] UID: {uid}")

    res = resolve_char(char)
    if not res.ok:
        return await bot.send(res.fail_msg())
    char = res.matched
    canonical_cmd = f"{PREFIX}角色面板{char}"

    # 「查询」走面板但不出综合评分；「角色面板」及其他入口照常显示
    im = await draw_char_detail_img(ev, uid, char, user_id, show_score=ev.command != "查询")
    if isinstance(im, str):
        await bot.send(_append_advice(ev, res.with_tip(im, canonical_cmd)))
        return
    if isinstance(im, bytes):
        await bot.send(_append_advice(ev, res.wrap(im, canonical_cmd)))
        return


@waves_new_char_detail.on_regex(
    rf"^(?P<waves_id>\d{{9}})?(?P<char>{PATTERN})(?P<query_type>练度|声骸)$",
    block=False,
)
async def send_char_detail_msg2_typo(bot: Bot, ev: Event):
    waves_id = ev.regex_dict.get("waves_id")
    char = ev.regex_dict.get("char")
    query_type = ev.regex_dict.get("query_type")

    if waves_id and len(waves_id) != 9:
        return
    if not char:
        return

    # 排除单独存在不算 typo 的输入: 刷新练度 / 我的声骸 等
    if query_type == "练度" and char in ("刷新", "更新", "upd"):
        return
    if query_type == "声骸" and char in ("我的",):
        return

    # char 带"刷新/更新/upd"前缀: 用户实际想刷新单角色, 转到刷新逻辑
    for kw in ("刷新", "更新", "upd"):
        if char.startswith(kw) and len(char) > len(kw):
            ev.regex_dict["is_refresh"] = kw
            ev.regex_dict["char"] = char[len(kw):]
            ev.regex_dict["query_type"] = "面板"
            return await send_one_char_detail_msg(bot, ev)

    res = resolve_char(char)
    if not res.ok:
        return await bot.send(res.fail_msg(), True if ev.group_id else False)
    char = res.matched

    _ru = await _resolve_self_uid(bot, ev)
    if _ru is None:
        return
    uid, user_id = _ru
    canonical_cmd = f"{PREFIX}{char}面板"
    im = await draw_char_detail_img(ev, uid, char, user_id, waves_id)
    # typo 路径: 即使精确命中也强制告知用户已按面板查询
    tip = res.tip_text(canonical_cmd) or f"[鸣潮] 已按【{canonical_cmd}】查询:"
    if isinstance(im, str):
        await bot.send(_append_advice(ev, f"{tip}\n{im}"), False)
        return
    if isinstance(im, bytes):
        await bot.send(_append_advice(ev, [tip, MessageSegment.image(im)]), False)
        return


@waves_new_char_detail.on_regex(
    rf"^(?P<lead_space>\s+)?(?P<waves_id>\d{{9}})?(?P<char>{PATTERN})(?P<query_type>面板|面版|面包|🍞|mb|伤害(?P<damage>(\d+)?))(?P<is_pk>pk|对比|PK|比|比较)?(\s*)?(?P<change_list>((换[^换]*)*)?)\s*$",
    block=True,
)
async def send_char_detail_msg2(bot: Bot, ev: Event):
    if ev.regex_dict.get("lead_space"):
        return await bot.send(_space_hint())
    waves_id = ev.regex_dict.get("waves_id")
    char = ev.regex_dict.get("char")
    damage = ev.regex_dict.get("damage")
    query_type = ev.regex_dict.get("query_type")
    is_pk = ev.regex_dict.get("is_pk") is not None
    change_list_regex = ev.regex_dict.get("change_list")

    if waves_id and len(waves_id) != 9:
        return
    if waves_id and is_intl_uid(waves_id):
        return await bot.send(intl_unavailable_msg(waves_id))

    if isinstance(query_type, str) and "伤害" in query_type and not damage:
        damage = "1"

    is_limit_query = False
    if isinstance(char, str) and ("极限" in char or "limit" in char):
        is_limit_query = True
        char = char.replace("极限", "").replace("limit", "")

    if not char:
        return

    res = resolve_char(char)
    if not res.ok:
        return await bot.send(res.fail_msg())
    matched = res.matched

    body = f"极限{matched}" if is_limit_query else matched
    base = f"伤害{damage}" if damage else "面板"
    canonical_cmd = f"{PREFIX}{body}{base}{'pk' if is_pk else ''}{change_list_regex or ''}"

    char = matched
    if damage:
        char = f"{char}伤害{damage}"
    logger.debug(f"[鸣潮·角色面板] CHAR: {char} {ev.regex_dict}")

    if is_limit_query:
        # is_limit_query=True 时 draw_char_detail_img 内部跳过 advice 队列, _append_advice 仍兜底清残留
        im = await draw_char_detail_img(ev, "1", char, ev.user_id, is_limit_query=is_limit_query)
        if isinstance(im, str):
            await bot.send(_append_advice(ev, res.with_tip(im, canonical_cmd)))
        elif isinstance(im, bytes):
            await bot.send(_append_advice(ev, res.wrap(im, canonical_cmd)))
        return

    at_sender = True if ev.group_id else False
    if is_pk:
        if not waves_id and not is_valid_at(ev):
            msg = f"[鸣潮] [角色面板] 角色【{char}】PK需要指定目标玩家!"
            return await bot.send((" " if at_sender else "") + msg, at_sender)

        uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
        if not uid:
            return await bot.send(error_reply(WAVES_CODE_103))
        if is_intl_uid(uid):
            return await bot.send(intl_unavailable_msg(uid))

        im1 = await draw_char_detail_img(
            ev,
            uid,
            char,
            ev.user_id,
            waves_id=None,
            need_convert_img=False,
            is_force_avatar=True,
            change_list_regex=change_list_regex,
        )
        if isinstance(im1, str):
            return await bot.send(res.with_tip(im1, canonical_cmd), at_sender)

        if not isinstance(im1, Image.Image):
            return

        try:
            _ru = await _resolve_self_uid(bot, ev)
            if _ru is None:
                return
            uid, user_id = _ru
            im2 = await draw_char_detail_img(ev, uid, char, user_id, waves_id, need_convert_img=False)
            if isinstance(im2, str):
                return await bot.send(res.with_tip(im2, canonical_cmd), at_sender)

            if not isinstance(im2, Image.Image):
                return

            new_im = await _concat_pk_images(im1, im2)
            new_im = await convert_img(new_im)
            await bot.send(res.wrap(new_im, canonical_cmd))
            return
        finally:
            # PK 为对比视图, 不展示单人 advice; 统一丢弃避免 id(ev) 残留串台
            pop_pending_advice(ev)
    else:
        _ru = await _resolve_self_uid(bot, ev)
        if _ru is None:
            return
        uid, user_id = _ru
        im = await draw_char_detail_img(ev, uid, char, user_id, waves_id, change_list_regex=change_list_regex)
        at_sender = False
        if isinstance(im, str):
            await bot.send(_append_advice(ev, res.with_tip(im, canonical_cmd)), at_sender)
            return
        if isinstance(im, bytes):
            await bot.send(_append_advice(ev, res.wrap(im, canonical_cmd)), at_sender)
            return


@waves_new_char_detail.on_regex(rf"^(?P<waves_id>\d{{9}})?(?P<char>{PATTERN})(权重|qz)$", block=True)
async def send_char_detail_msg2_weight(bot: Bot, ev: Event):
    waves_id = ev.regex_dict.get("waves_id")
    char = ev.regex_dict.get("char")

    if waves_id and len(waves_id) != 9:
        return
    if waves_id and is_intl_uid(waves_id):
        return await bot.send(intl_unavailable_msg(waves_id))

    is_limit_query = False
    if isinstance(char, str) and ("极限" in char or "limit" in char):
        is_limit_query = True
        char = char.replace("极限", "").replace("limit", "")

    if not char:
        return

    res = resolve_char(char)
    if not res.ok:
        return await bot.send(res.fail_msg())
    char = res.matched

    body = f"极限{char}" if is_limit_query else char
    canonical_cmd = f"{PREFIX}{body}权重"

    if is_limit_query:
        im = await draw_char_score_img(ev, "1", char, ev.user_id, is_limit_query=is_limit_query)
        if isinstance(im, str):
            return await bot.send(res.with_tip(im, canonical_cmd))
        if isinstance(im, bytes):
            return await bot.send(res.wrap(im, canonical_cmd))
        return

    _ru = await _resolve_self_uid(bot, ev)
    if _ru is None:
        return
    uid, user_id = _ru

    im = await draw_char_score_img(ev, uid, char, user_id, waves_id)  # type: ignore
    at_sender = False
    if isinstance(im, str) and ev.group_id:
        at_sender = True
    if isinstance(im, str):
        return await bot.send(res.with_tip(im, canonical_cmd), at_sender)
    if isinstance(im, bytes):
        return await bot.send(res.wrap(im, canonical_cmd), at_sender)


@waves_new_char_detail.on_regex(rf"^(?P<waves_id>\d{{9}})?(?P<char>{PATTERN})(优化建议|优化|提升建议|提升|yh)(\s*)?(?P<change_list>((换[^换]*)*)?)$", block=True)
async def send_char_optimize_msg(bot: Bot, ev: Event):
    waves_id = ev.regex_dict.get("waves_id")
    char = ev.regex_dict.get("char")
    change_list_regex = ev.regex_dict.get("change_list")
    if waves_id and len(waves_id) != 9:
        return
    if waves_id and is_intl_uid(waves_id):
        return await bot.send(intl_unavailable_msg(waves_id))

    is_limit_query = False
    if isinstance(char, str) and ("极限" in char or "limit" in char):
        is_limit_query = True
        char = char.replace("极限", "").replace("limit", "")
    if not char:
        return
    res = resolve_char(char)
    if not res.ok:
        return await bot.send(res.fail_msg())
    char = res.matched
    body = f"极限{char}" if is_limit_query else char
    canonical_cmd = f"{PREFIX}{body}优化{change_list_regex or ''}"

    if is_limit_query:
        im = await draw_char_optimize_img(ev, "1", char, ev.user_id, change_list_regex=change_list_regex, is_limit_query=True)
        at_sender = False
        if isinstance(im, str) and ev.group_id:
            at_sender = True
        if isinstance(im, str):
            return await bot.send(res.with_tip(im, canonical_cmd), at_sender)
        if isinstance(im, bytes):
            return await bot.send(res.wrap(im, canonical_cmd), at_sender)
        return

    _ru = await _resolve_self_uid(bot, ev)
    if _ru is None:
        return
    uid, user_id = _ru

    im = await draw_char_optimize_img(ev, uid, char, user_id, waves_id, change_list_regex=change_list_regex)
    at_sender = False
    if isinstance(im, str) and ev.group_id:
        at_sender = True
    if isinstance(im, str):
        return await bot.send(res.with_tip(im, canonical_cmd), at_sender)
    if isinstance(im, bytes):
        return await bot.send(res.wrap(im, canonical_cmd), at_sender)


@waves_score_explain.on_fullmatch(("综合评分说明", "综合评分细则", "综合评分规则"), block=True)
async def send_score_explain_msg(bot: Bot, ev: Event):
    if not SCORE_EXPLAIN_IMG.exists():
        return await bot.send("[鸣潮] 暂无综合评分说明图")
    img = await convert_img(SCORE_EXPLAIN_IMG)
    await bot.send(MessageSegment.image(img))
