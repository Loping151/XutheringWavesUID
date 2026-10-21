from typing import Dict, List, Optional, Tuple, Union

from PIL import Image, ImageDraw

from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.logger import logger
from gsuid_core.pool import to_thread
from gsuid_core.utils.image.convert import convert_img

from ..utils.util import hide_uid, get_hide_uid_pref
from ..utils.image import (
    GOLD,
    GREY,
    SPECIAL_GOLD,
    pil_to_b64,
    add_footer,
    get_waves_bg,
    get_event_avatar,
    get_square_avatar,
)
from ..utils.render_utils import PLAYWRIGHT_AVAILABLE, render_html, get_footer_b64
from ..utils.resource.RESOURCE_PATH import waves_templates
from ..utils.fonts.waves_fonts import (
    draw_text_with_fallback,
    waves_font_16,
    waves_font_18,
    waves_font_20,
    waves_font_24,
    waves_font_30,
)
from ..utils.database.models import WavesBind
from ..utils.database.waves_custom_weight import WavesCustomWeight, WavesGroupWeight
from ..utils.custom_weight import (
    api_base,
    char_entries,
    char_name_of,
    chars_of,
    check_sub,
    code_text,
    get_weight,
    pick_key,
    role_codes,
    split_key,
    sync_group,
    sync_personal,
    weight_author,
)
from ..utils.weight_spectrum import SPEC_COLOR, spectrum
from ..wutheringwaves_config import PREFIX, WutheringWavesConfig

SOURCE = {"personal": ("单独设置", "personal"), "sub": ("订阅", "sub"), "off": ("被群权重覆盖", "off")}


def _bars(calc) -> List[Dict]:
    """行内迷你频谱: 高度为百分比, 颜色按 S/A/B 档, 空串表示该词条为 0。"""
    bands = spectrum(calc)
    peak = max([1.0] + [v for _, v, _ in bands])
    return [{"h": max(10, round(v / peak * 100)), "c": "#%02x%02x%02x" % SPEC_COLOR[lv]} if v > 0 else {"h": 6, "c": ""} for _, v, lv in bands]


async def _weight_row(key: str, wid: str, conf: str = "") -> Dict:
    cid, codes = split_key(key)
    w = await get_weight(wid)
    line = " · ".join(x for x in (w.get("name"), weight_author(w)) if x) if w else "（暂时无法获取权重信息）"
    return {"cid": cid, "char": char_name_of(cid), "wid": wid, "weight": line, "cond": " ".join(sorted(codes)), "conf": conf, "bars": _bars(w["calc"]) if w else []}


def _sort_key(key: str):
    cid, codes = split_key(key)
    return (-int(cid) if cid.isdigit() else 0, min(codes) if codes else "")


def _shown(entries: Dict[str, str], codes: Dict[str, Optional[str]]) -> List[Tuple[str, str]]:
    """要列出的 (键, 配置说明): 有面板缓存时只列拥有的角色实际生效的那条, 没有缓存就全列。"""
    if not codes:
        return [(k, "") for k in sorted(entries, key=_sort_key)]
    out = []
    for cid in sorted(chars_of(entries), key=lambda c: -int(c) if c.isdigit() else 0):
        if cid not in codes:
            continue
        key = pick_key(entries, cid, codes[cid])
        if key:
            conditional = any(split_key(k)[1] for k in char_entries(entries, cid))
            out.append((key, code_text(codes[cid]) if conditional and codes[cid] else ""))
    return out


def _sub_info(sub_id: str, res: Optional[dict], items: Dict[str, str]) -> Dict:
    res = res or {}
    return {"id": sub_id, "name": res.get("name") or "", "author": weight_author(res), "count": len(chars_of(items))}


async def _collect(ev: Event) -> Union[str, Dict]:
    uid = await WavesBind.get_uid_by_game(ev.user_id, ev.bot_id)
    if not uid:
        return f"[鸣潮] 请先【{PREFIX}绑定uid】"
    data: Dict = {"uid": uid, "rows": [], "group_rows": [], "sub": None, "group": None, "notices": [], "settled": False}
    codes = await role_codes(uid)
    group_items: Dict[str, str] = {}
    if ev.group_id:
        grow = await WavesGroupWeight.get_row(str(ev.group_id), ev.bot_id)
        if grow:
            data["notices"] += await sync_group(grow)
            grow = await WavesGroupWeight.get_row(str(ev.group_id), ev.bot_id)
        if grow:
            group_items = grow.sub_map()
            data["group"] = _sub_info(grow.sub_id, await check_sub(grow.sub_id, grow.sub_hash), group_items)
            for key, conf in _shown(group_items, codes):
                data["group_rows"].append(await _weight_row(key, group_items[key], conf))
    row = await WavesCustomWeight.get_row(ev.user_id, ev.bot_id, uid)
    if row:
        data["notices"] += await sync_personal(row)
        row = await WavesCustomWeight.get_row(ev.user_id, ev.bot_id, uid)
    if row:
        weights = row.weight_map()
        sub_items = row.sub_map()
        data["settled"] = bool(weights)
        if row.sub_id:
            data["sub"] = _sub_info(row.sub_id, await check_sub(row.sub_id, row.sub_hash), sub_items)
        for key, conf in _shown(weights, codes):
            wid = weights[key]
            cid = split_key(key)[0]
            covered = pick_key(group_items, cid, codes.get(cid)) if codes else any(not split_key(k)[1] for k in char_entries(group_items, cid))
            src = "off" if covered else ("sub" if row.sub_id and sub_items.get(key) == wid else "personal")
            label, cls = SOURCE[src]
            data["rows"].append({**await _weight_row(key, wid, conf), "source": label, "cls": cls, "off": src == "off"})
    return data


async def draw_weight_settings(bot: Bot, ev: Event) -> Union[str, bytes]:
    data = await _collect(ev)
    if isinstance(data, str):
        return data
    if data["notices"]:
        await bot.send("\n".join(f"[鸣潮] {n}" for n in data["notices"]))
    user_pref = await get_hide_uid_pref(data["uid"], ev.user_id, ev.bot_id)
    data["uid_masked"] = hide_uid(data["uid"], user_pref=user_pref)

    use_html = WutheringWavesConfig.get_config("UseHtmlRender").data
    if PLAYWRIGHT_AVAILABLE and use_html:
        try:
            avatar = await get_event_avatar(ev)
            for r in data["rows"] + data["group_rows"]:
                r["avatar"] = pil_to_b64((await get_square_avatar(r["cid"])).resize((92, 92)), quality=80)
            context = {
                "uid": data["uid_masked"],
                "avatar_url": pil_to_b64(avatar, quality=75) if avatar else "",
                "bg_url": pil_to_b64(get_waves_bg(760, 1200, "bg3"), quality=70),
                "rows": data["rows"],
                "group_rows": data["group_rows"],
                "sub": data["sub"],
                "group": data["group"],
                "empty": _empty_text(data),
                "site": api_base().replace("https://", ""),
                "prefix": PREFIX,
                "footer_b64": get_footer_b64(footer_type="white") or "",
            }
            img = await render_html(waves_templates, "custom_weight.html", context)
            if img:
                return img
        except Exception as e:
            logger.warning(f"[鸣潮·自定义权重] HTML 渲染失败, 回退 PIL: {e}")
    return await _draw_pil(ev, data)


def _empty_text(data: Dict) -> str:
    if data["group_rows"]:
        return "其余角色都在用默认权重"
    return "拥有的角色都在用默认权重" if data["settled"] else "还没有单独设置或订阅的角色权重"


def _fit(draw, text: str, font, max_w: int) -> str:
    """超出宽度的文字截断加省略号。"""
    if draw.textlength(text, font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font) > max_w:
        text = text[:-1]
    return text + "…"


async def _draw_pil(ev: Event, data: Dict) -> bytes:
    avatars = {}
    for r in data["rows"] + data["group_rows"]:
        avatars[r["cid"]] = (await get_square_avatar(r["cid"])).resize((56, 56))
    avatar = await get_event_avatar(ev)
    img = await _compose(data, avatars, avatar)
    return await convert_img(img)


def _fit_codes(codes: str, width: int) -> str:
    parts = codes.split()
    while len(parts) > 1 and waves_font_16.getlength(" ".join(parts) + " …") > width:
        parts.pop()
    return " ".join(parts) + (" …" if len(parts) < len(codes.split()) else "")


@to_thread
def _compose(data: Dict, avatars: Dict[str, Image.Image], avatar: Optional[Image.Image]) -> Image.Image:
    W = 760
    rows: List[Dict] = data["rows"]
    grows: List[Dict] = data["group_rows"]
    h = 150 + 70 + max(1, len(rows)) * 72 + 40
    if data["sub"]:
        h += 40
    if data["group"]:
        h += 90 + len(grows) * 72
    h += 124
    img = get_waves_bg(W, h, "bg3")
    shade = Image.new("RGBA", (W, h), (12, 14, 18, 150))
    img.alpha_composite(shade)
    draw = ImageDraw.Draw(img)

    def panel(y0: int, y1: int):
        layer = Image.new("RGBA", (W, h), (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle([24, y0, W - 24, y1], radius=16, fill=(22, 26, 33, 215))
        img.alpha_composite(layer)
        ImageDraw.Draw(img).line([(60, y0 + 1), (W - 60, y0 + 1)], fill=GOLD + (180,), width=2)

    def row_line(y: int, r: Dict, tag: str, tag_color):
        av = avatars.get(r["cid"])
        if av is not None:
            mask = Image.new("L", av.size, 0)
            ImageDraw.Draw(mask).ellipse([0, 0, av.size[0], av.size[1]], fill=255)
            img.paste(av, (44, y + 4), mask)
        d = ImageDraw.Draw(img)
        alpha = 110 if r.get("off") else 255
        draw_text_with_fallback(d, (114, y + 20), r["char"], (255, 255, 255, alpha), waves_font_24, "lm")
        if r.get("conf") or r.get("cond"):
            x = 126 + round(waves_font_24.getlength(r["char"]))
            draw_text_with_fallback(d, (x, y + 22), r["conf"] or _fit_codes(r["cond"], W - 310 - x), GOLD + (alpha,), waves_font_16, "lm")
        draw_text_with_fallback(d, (114, y + 48), r["weight"][:20], GREY + (alpha,), waves_font_16, "lm")
        for i, b in enumerate(r.get("bars") or []):
            x = W - 290 + i * 10
            h = round(36 * b["h"] / 100)
            color = tuple(int(b["c"][k:k + 2], 16) for k in (1, 3, 5)) if b["c"] else (255, 255, 255)
            d.rounded_rectangle([x, y + 54 - h, x + 7, y + 54], radius=2, fill=color + ((alpha if b["c"] else 46),))
        draw_text_with_fallback(d, (W - 44, y + 20), r["wid"], GOLD + (alpha,), waves_font_20, "rm")
        draw_text_with_fallback(d, (W - 44, y + 48), tag, tag_color, waves_font_16, "rm")

    y = 24
    panel(y, y + 110)
    if avatar is not None:
        av = avatar.resize((80, 80))
        mask = Image.new("L", (80, 80), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, 80, 80], fill=255)
        img.paste(av, (48, y + 15), mask)
    draw = ImageDraw.Draw(img)
    draw_text_with_fallback(draw, (148, y + 40), "自定义权重", "white", waves_font_30, "lm")
    draw_text_with_fallback(draw, (148, y + 78), f"特征码 {data['uid_masked']}", GREY, waves_font_18, "lm")
    y += 130

    if data["group"]:
        g = data["group"]
        top = y
        panel(top, top + 70 + len(grows) * 72)
        draw = ImageDraw.Draw(img)
        draw_text_with_fallback(draw, (48, y + 32), _fit(draw, f"本群权重  订阅 {g['id']} {g['name']}" + (f" · {g['author']}" if g["author"] else ""), waves_font_20, W - 44 - 48 - 120), SPECIAL_GOLD, waves_font_20, "lm")
        draw_text_with_fallback(draw, (W - 44, y + 32), f"{g['count']} 个角色", GREY, waves_font_16, "rm")
        y += 60
        for r in grows:
            row_line(y, r, "群权重", SPECIAL_GOLD)
            y += 72
        y += 30

    top = y
    body = max(1, len(rows)) * 72 + (40 if data["sub"] else 0)
    panel(top, top + 60 + body)
    draw = ImageDraw.Draw(img)
    draw_text_with_fallback(draw, (48, y + 32), "个人设置", SPECIAL_GOLD, waves_font_20, "lm")
    y += 60
    if data["sub"]:
        s = data["sub"]
        by = f" · {s['author']}" if s["author"] else ""
        draw_text_with_fallback(draw, (48, y + 12), _fit(draw, f"跟随订阅 {s['id']} {s['name']}{by}（{s['count']} 个角色）", waves_font_18, W - 44 - 48), "white", waves_font_18, "lm")
        y += 40
    if not rows:
        draw_text_with_fallback(draw, (48, y + 30), _empty_text(data), GREY, waves_font_18, "lm")
        y += 72
    tag_color = {"personal": (142, 200, 240), "sub": (215, 168, 234), "off": GREY}
    for r in rows:
        row_line(y, r, r["source"], tag_color.get(r["cls"], GREY))
        y += 72
    y += 20
    panel(y, y + 84)
    draw = ImageDraw.Draw(img)
    draw_text_with_fallback(draw, (48, y + 30), "生效顺序：指令里的 cw_ID ＞ 群权重 ＞ 个人设置/订阅 ＞ 内置", GOLD, waves_font_18, "lm")
    draw_text_with_fallback(draw, (48, y + 60), f"权重站 {api_base().replace('https://', '')} · 【{PREFIX}权重帮助】", GREY, waves_font_16, "lm")
    return add_footer(img)
