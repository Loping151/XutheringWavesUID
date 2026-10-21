from typing import Dict, List, Optional, Tuple

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.models import Event

from ..utils.char_info_utils import PATTERN
from ..utils.name_resolve import resolve_char
from ..utils.name_convert import char_name_to_char_id
from ..utils.database.models import WavesBind
from ..utils.database.waves_custom_weight import WavesCustomWeight, WavesGroupWeight
from ..utils.custom_weight import (
    CW_PATTERN,
    WS_PATTERN,
    api_base,
    brief,
    canon_char,
    char_entries,
    char_name_of,
    chars_of,
    check_sub,
    check_weight,
    clear_settings,
    enabled,
    format_text,
    merge_sub,
    norm_id,
    parse_text,
    replace_chars,
    save_settings,
    weight_author,
)
from ..wutheringwaves_config import PREFIX

sv_weight = SV("waves自定义权重", priority=1)
sv_weight_group = SV("waves群权重", priority=1)

CLEAR_WORDS = ("清空权重", "清空所有权重", "清空全部权重", "清除权重设置", "清空权重设置", "清除权重", "清除所有权重")


async def _say(bot: Bot, ev: Event, msg: str):
    at = bool(ev.group_id)
    await bot.send((" " if at else "") + msg, at)


async def _bound_uid(bot: Bot, ev: Event) -> Optional[str]:
    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not uid:
        await _say(bot, ev, f"[鸣潮] 请先【{PREFIX}绑定uid】，自定义权重按绑定的特征码保存")
        return None
    return uid


async def _row(ev: Event, uid: str) -> WavesCustomWeight:
    row = await WavesCustomWeight.get_row(ev.user_id, ev.bot_id, uid)
    if row is None:
        row = WavesCustomWeight(user_id=ev.user_id, bot_id=ev.bot_id, uid=uid)
    return row


def _desc(w: dict) -> str:
    """「名称」by 作者; 权重与订阅通用, 默认昵称不显示。"""
    author = weight_author(w)
    return f"「{w.get('name') or '未命名订阅'}」" + (f"by {author}" if author else "")


def _set_notice(row: WavesCustomWeight, cid: str, old: Optional[str], new: str, changed: bool = False) -> str:
    name = char_name_of(cid)
    if old == new:
        head = f"{name}的条件权重已更新" if changed else f"{name}的权重已经是{new}"
    elif old:
        head = f"{name}的权重已由{old}更新为{new}"
    else:
        head = f"{name}的权重已设置为{new}"
    if row.sub_id:
        if cid in chars_of(row.sub_map()):
            return f"{head}，但订阅{row.sub_id}包含该角色权重，下次订阅更新将被覆盖！"
        return f"{head}，如订阅{row.sub_id}之后加入该角色权重，将被覆盖！"
    return head


async def set_char_weight(bot: Bot, ev: Event, char: str, wid: Optional[str]):
    uid = await _bound_uid(bot, ev)
    if not uid:
        return
    res = resolve_char(char)
    cid = char_name_to_char_id(res.matched) if res.ok else None
    if not cid or len(cid) != 4 or not cid.isdigit():
        return await _say(bot, ev, res.fail_msg())
    cid = canon_char(cid)
    row = await _row(ev, uid)
    weights = row.weight_map()
    old = brief(char_entries(weights, cid))
    if not wid:
        if not old:
            return await _say(bot, ev, f"[鸣潮] {char_name_of(cid)}当前没有单独设置权重")
        for k in char_entries(weights, cid):
            weights.pop(k)
        row.set_maps(weights=weights)
        await save_settings(row)
        tail = f"，但订阅{row.sub_id}包含该角色权重，下次订阅更新会重新写入" if row.sub_id and cid in chars_of(row.sub_map()) else ""
        return await _say(bot, ev, f"[鸣潮] 已清除{char_name_of(cid)}的自定义权重（原 {old}），恢复默认{tail}")
    w, err = await check_weight(wid, [cid])
    if w is None:
        return await _say(bot, ev, f"[鸣潮] {err}")
    replace_chars(weights, {cid: wid})
    row.set_maps(weights=weights)
    await save_settings(row)
    await _say(bot, ev, f"[鸣潮] {_set_notice(row, cid, old, wid)}\n{_desc(w)}")


async def _apply_sub(row: WavesCustomWeight, ws: str) -> Tuple[Optional[dict], List[str]]:
    res = await check_sub(ws, "")
    if res is None:
        return None, ["订阅服务暂时无法连接，请稍后再试"]
    if res.get("missing"):
        return None, [f"订阅 {ws} 不存在，请检查 ID"]
    items: Dict[str, str] = res.get("items") or {}
    weights = row.weight_map()
    notices = [f"已从订阅{row.sub_id}切换为{ws}"] if row.sub_id and row.sub_id != ws else []
    notices += merge_sub(weights, ws, items)
    row.sub_id, row.sub_hash = ws, res.get("hash", "")
    row.set_maps(weights=weights, sub_items=items)
    return res, notices


async def subscribe(bot: Bot, ev: Event, text: str):
    uid = await _bound_uid(bot, ev)
    if not uid:
        return
    ws, entries, loose, errors = parse_text(text)
    if not ws and not entries and not loose and not errors:
        return await _say(
            bot,
            ev,
            f"[鸣潮] 请附上订阅 ID 或网站复制的文本，例如【{PREFIX}订阅权重ws_ab12cd34】\n权重站：{api_base()}",
        )
    row = await _row(ev, uid)
    lines: List[str] = []
    if ws:
        res, notices = await _apply_sub(row, ws)
        if res is None:
            return await _say(bot, ev, f"[鸣潮] {notices[0]}")
        lines.append(f"已订阅 {ws}{_desc(res)}，共 {len(chars_of(res.get('items') or {}))} 个角色；刷新面板时会自动同步作者的更新")
        lines.extend(notices)

    # 文本里出现的角色整体替换; 某角色有权重校验失败就整个跳过
    todo: List[Tuple[str, Dict[str, str]]] = [(cid, char_entries(entries, cid)) for cid in chars_of(entries)]
    weights = row.weight_map()
    failed = list(errors)
    for wid in loose:
        w, err = await check_weight(wid)
        if w is None:
            failed.append(err)
        else:
            todo.append((canon_char(w.get("char_id")), {canon_char(w.get("char_id")): wid}))
    for cid, new in todo:
        errs = [err for _, err in [await check_weight(wid, [cid]) for wid in set(new.values())] if err]
        if errs:
            failed.extend(errs)
            continue
        old = char_entries(weights, cid)
        if old != new:
            lines.append(_set_notice(row, cid, brief(old), brief(new), changed=True))
        replace_chars(weights, new)
    if todo:
        row.set_maps(weights=weights)
    if not ws and todo and not lines and not failed:
        lines.append("导入的权重与当前设置相同，无需更新")
    await save_settings(row)
    lines.extend(failed)
    await _say(bot, ev, "[鸣潮] " + "\n".join(lines))


async def unsubscribe(bot: Bot, ev: Event):
    uid = await _bound_uid(bot, ev)
    if not uid:
        return
    row = await WavesCustomWeight.get_row(ev.user_id, ev.bot_id, uid)
    if not row or not row.sub_id:
        return await _say(bot, ev, "[鸣潮] 当前没有订阅权重")
    old = row.sub_id
    row.sub_id, row.sub_hash = "", ""
    row.set_maps(sub_items={})
    await save_settings(row)
    await _say(bot, ev, f"[鸣潮] 已取消订阅 {old}，已同步的 {len(chars_of(row.weight_map()))} 个角色权重保留；如需全部清除请发送【{PREFIX}清空权重】")


async def clear_all(bot: Bot, ev: Event):
    uid = await _bound_uid(bot, ev)
    if not uid:
        return
    row = await WavesCustomWeight.get_row(ev.user_id, ev.bot_id, uid)
    if not row or (not row.sub_id and not row.weight_map()):
        return await _say(bot, ev, "[鸣潮] 当前没有自定义权重设置")
    text = format_text(row.sub_id, row.weight_map())
    await clear_settings(row)
    await bot.send(f"[鸣潮] 已清空自定义权重设置。如需恢复，复制下面整段发送【{PREFIX}导入权重】：\n{text}")


async def _group_admin(bot: Bot, ev: Event) -> bool:
    if not ev.group_id:
        await _say(bot, ev, "[鸣潮] 请在群聊中设置群权重")
        return False
    if ev.user_pm > 3:
        await _say(bot, ev, "[鸣潮] 群权重需要群主或管理员设置")
        return False
    return True


async def set_group(bot: Bot, ev: Event, text: str):
    if not await _group_admin(bot, ev):
        return
    ws = norm_id(text) if text else ""
    if not ws or ws.startswith("cw_") or len(ws) != 11 or not ws.startswith("ws_"):
        if text and ("cw_" in text.lower()):
            return await _say(bot, ev, "[鸣潮] 群权重必须使用订阅ID（ws_开头），可以在权重站把权重加入一个公开订阅")
        return await _say(bot, ev, f"[鸣潮] 用法：{PREFIX}设置群权重ws_ab12cd34（必须是公开展示的订阅）\n取消：{PREFIX}取消群权重")
    res = await check_sub(ws, "")
    if res is None:
        return await _say(bot, ev, "[鸣潮] 订阅服务暂时无法连接，请稍后再试")
    if res.get("missing"):
        return await _say(bot, ev, f"[鸣潮] 订阅 {ws} 不存在，请检查 ID")
    if not res.get("public"):
        return await _say(bot, ev, f"[鸣潮] 订阅 {ws} 未公开展示，请先在权重站公开展示该订阅")
    row = await WavesGroupWeight.get_row(str(ev.group_id), ev.bot_id) or WavesGroupWeight(group_id=str(ev.group_id), bot_id=ev.bot_id)
    row.sub_id = ws
    row.sub_hash = res.get("hash", "")
    row.set_by = ev.user_id
    row.set_items(res.get("items") or {})
    await WavesGroupWeight.save_row(row)
    chars = sorted(chars_of(res.get("items") or {}), key=lambda c: -int(c))
    names = "、".join(char_name_of(c) for c in chars[:12])
    await _say(
        bot,
        ev,
        f"[鸣潮] 本群已使用订阅 {ws}{_desc(res)}作为群权重（{len(chars)} 个角色：{names}）\n"
        "群内查询面板与群排行默认使用该权重；指令里直接带 cw_ID 时以指令为准",
    )


async def clear_group(bot: Bot, ev: Event):
    if not await _group_admin(bot, ev):
        return
    row = await WavesGroupWeight.get_row(str(ev.group_id), ev.bot_id)
    if not row:
        return await _say(bot, ev, "[鸣潮] 本群没有设置群权重")
    await WavesGroupWeight.delete_row(str(ev.group_id), ev.bot_id)
    await _say(bot, ev, f"[鸣潮] 已取消本群的群权重（原订阅 {row.sub_id}）")


async def _guard(bot: Bot, ev: Event) -> bool:
    if enabled():
        return True
    await _say(bot, ev, "[鸣潮] 未开启自定义权重")
    return False


@sv_weight.on_regex(rf"^设置(?P<char>{PATTERN})权重\s*(?P<wid>{CW_PATTERN}|{WS_PATTERN})?\s*(?P<reset>默认|清除|取消|删除)?\s*$", block=True)
async def cmd_set_weight(bot: Bot, ev: Event):
    if not await _guard(bot, ev):
        return
    char = ev.regex_dict.get("char") or ""
    wid = ev.regex_dict.get("wid") or ""
    if char == "群":
        return await set_group(bot, ev, wid)
    if wid.lower().startswith("ws_"):
        return await _say(bot, ev, f"[鸣潮] 单个角色请填写权重ID（cw_开头）；订阅请用【{PREFIX}订阅权重{norm_id(wid)}】")
    if not wid and not ev.regex_dict.get("reset"):
        return await _say(
            bot,
            ev,
            f"[鸣潮] 用法：{PREFIX}设置{char}权重cw_xxxxxxxx\n恢复默认：{PREFIX}设置{char}权重默认\n权重站：{api_base()}",
        )
    await set_char_weight(bot, ev, char, norm_id(wid) if wid else None)


@sv_weight.on_prefix(("订阅权重", "导入权重", "訂閱權重", "導入權重"), block=True)
async def cmd_subscribe(bot: Bot, ev: Event):
    if not await _guard(bot, ev):
        return
    await subscribe(bot, ev, ev.text)


@sv_weight.on_fullmatch(("取消订阅权重", "取消權重訂閱", "取消權重订阅", "退订权重"), block=True)
async def cmd_unsubscribe(bot: Bot, ev: Event):
    if not await _guard(bot, ev):
        return
    await unsubscribe(bot, ev)


@sv_weight.on_fullmatch(CLEAR_WORDS, block=True)
async def cmd_clear(bot: Bot, ev: Event):
    if not await _guard(bot, ev):
        return
    await clear_all(bot, ev)


@sv_weight.on_fullmatch(("查看权重", "我的权重", "权重设置", "查看權重"), block=True)
async def cmd_view(bot: Bot, ev: Event):
    if not await _guard(bot, ev):
        return
    from .draw_weight_list import draw_weight_settings

    im = await draw_weight_settings(bot, ev)
    if isinstance(im, str):
        return await _say(bot, ev, im)
    await bot.send(im)


@sv_weight.on_fullmatch(("权重帮助", "自定义权重帮助", "權重幫助"), block=True)
async def cmd_help(bot: Bot, ev: Event):
    from .weight_help import get_weight_help

    await bot.send(await get_weight_help(ev.user_pm))


@sv_weight_group.on_fullmatch(("取消群权重", "删除群权重", "清除群权重"), block=True)
async def cmd_clear_group(bot: Bot, ev: Event):
    await clear_group(bot, ev)
