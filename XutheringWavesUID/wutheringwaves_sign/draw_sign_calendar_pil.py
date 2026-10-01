from io import BytesIO
from typing import Optional, Tuple

from PIL import Image, ImageDraw

from gsuid_core.pool import to_thread

from ..utils.api.model import SignInInitData
from ..utils.fonts.waves_fonts import waves_font_origin
from ..utils.image import add_footer, pic_download_from_url
from ..utils.resource.RESOURCE_PATH import SIGN_SURFACE_PATH


CANVAS_W = 750
BOX_W = 690
BOX_MARGIN_X = (CANVAS_W - BOX_W) // 2

CYCLE_PAD_TOP = 24
CYCLE_PAD_BOTTOM = 50
CYCLE_TITLE_H = 30
CYCLE_TIME_H = 22
CYCLE_TIME_GAP = 34
CYCLE_MARGIN_TOP = 20
CYCLE_MARGIN_BOTTOM = 30
BOX_BOTTOM_CROP_TOP = 36

CELL_W_MONTH = 134
CELL_H_MONTH = 146
CELL_DAY_H_MONTH = 40
CELL_GAP_MONTH = 30
CELLS_PER_ROW = 4
GRID_PAD_LEFT = 30
GRID_PAD_VERT = 15
BOX_BOTTOM_OVERLAP = 30

LOOP_CELL_SIZE = 78
LOOP_MARK_H = 30
LOOP_CELL_H = LOOP_CELL_SIZE + 8 + LOOP_MARK_H + 6 + 20

CYCLE_H = (
    CYCLE_PAD_TOP + CYCLE_TITLE_H + CYCLE_TIME_H + CYCLE_TIME_GAP + LOOP_CELL_H + CYCLE_PAD_BOTTOM
)


def _hex(s: Optional[str], default: str = "#FFFFFF") -> Tuple[int, int, int]:
    s = (s or default).lstrip("#")
    if len(s) == 6:
        try:
            return tuple(int(s[i : i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    return (255, 255, 255)


def _format_loop_range(start: str, end: str) -> str:
    def _strip_year(x: str) -> str:
        return x[5:] if len(x) >= 10 and x[4] == "-" else x

    if not start or not end:
        return ""
    return f"{_strip_year(start)} ~ {_strip_year(end)}"


def _has_loop(sign_data: SignInInitData) -> bool:
    if not sign_data.signLoopGoodsList:
        return False
    if sign_data.loopSignNum > 0:
        return True
    now = sign_data.nowServerTimes
    return bool(now) and sign_data.loopStartTimes <= now <= sign_data.loopEndTimes


async def _load(url: str) -> Optional[Image.Image]:
    if not url:
        return None
    try:
        return await pic_download_from_url(SIGN_SURFACE_PATH, url)
    except Exception:
        return None


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> Tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _draw_center(canvas: Image.Image, cx: int, cy: int, text: str, font, fill) -> None:
    draw = ImageDraw.Draw(canvas)
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    draw.text((cx - w // 2 - bbox[0], cy - h // 2 - bbox[1]), text, fill=fill, font=font)


def _paste(canvas: Image.Image, img: Optional[Image.Image], xy: Tuple[int, int]) -> None:
    if img is None:
        return
    canvas.paste(img, xy, img if img.mode == "RGBA" else None)


def _fit(img: Image.Image, size: Tuple[int, int]) -> Image.Image:
    return img.resize(size, Image.LANCZOS)


def _cell_box_y(row: int) -> int:
    return row * (CELL_H_MONTH + CELL_DAY_H_MONTH + CELL_GAP_MONTH)


def _render_month_cell(
    sign_data: SignInInitData,
    goods,
    icon: Optional[Image.Image],
    price_bg: Optional[Image.Image],
    today_no_sign: Optional[Image.Image],
    sign_day_bg: Optional[Image.Image],
    had_sign_in_bg: Optional[Image.Image],
) -> Image.Image:
    cell = Image.new("RGBA", (CELL_W_MONTH, CELL_H_MONTH + CELL_DAY_H_MONTH), (0, 0, 0, 0))
    is_gained = goods.serialNum < sign_data.sigInNum
    if sign_data.isSigIn:
        is_current = goods.serialNum == sign_data.sigInNum - 1
    else:
        is_current = goods.serialNum == sign_data.sigInNum

    top_bg = today_no_sign if is_current and today_no_sign else price_bg
    if top_bg is not None:
        _paste(cell, top_bg, (0, 0))

    if icon is not None:
        icon = _fit(icon.convert("RGBA"), (CELL_W_MONTH, CELL_H_MONTH))
        _paste(cell, icon, (0, 0))

    draw = ImageDraw.Draw(cell)
    f_num = waves_font_origin(16)
    num_text = f"x{goods.goodsNum}"
    nw, nh = _text_size(draw, num_text, f_num)
    draw.text(
        (CELL_W_MONTH - nw - 4, CELL_H_MONTH - nh - 8),
        num_text,
        fill=(51, 51, 51),
        font=f_num,
    )

    if sign_day_bg is not None:
        _paste(cell, sign_day_bg, (0, CELL_H_MONTH))
    f_day = waves_font_origin(20)
    _draw_center(
        cell,
        CELL_W_MONTH // 2,
        CELL_H_MONTH + CELL_DAY_H_MONTH // 2,
        f"第{goods.serialNum + 1}天",
        f_day,
        (255, 255, 255),
    )

    if is_gained and had_sign_in_bg is not None:
        overlay = _fit(had_sign_in_bg, (CELL_W_MONTH, CELL_H_MONTH + CELL_DAY_H_MONTH))
        _paste(cell, overlay, (0, 0))

    return cell


def _render_loop_cell(
    item,
    icon: Optional[Image.Image],
    loop_card_bg: Optional[Image.Image],
    process_grey: Optional[Image.Image],
    process_light: Optional[Image.Image],
    had_sign_in_bg: Optional[Image.Image],
    col_w: int,
    day_color: Tuple[int, int, int],
) -> Image.Image:
    cell_h = LOOP_CELL_H
    cell = Image.new("RGBA", (col_w, cell_h), (0, 0, 0, 0))

    card_x = (col_w - LOOP_CELL_SIZE) // 2
    if loop_card_bg is not None:
        bg = _fit(loop_card_bg.convert("RGBA"), (LOOP_CELL_SIZE, LOOP_CELL_SIZE))
        _paste(cell, bg, (card_x, 0))

    if icon is not None:
        icon_size = LOOP_CELL_SIZE - 8
        icon_img = _fit(icon.convert("RGBA"), (icon_size, icon_size))
        _paste(cell, icon_img, (card_x + 4, 4))

    draw = ImageDraw.Draw(cell)
    f_num = waves_font_origin(13)
    num_text = f"x{item['num']}"
    nw, nh = _text_size(draw, num_text, f_num)
    draw.text(
        (card_x + LOOP_CELL_SIZE - nw - 6, LOOP_CELL_SIZE - nh - 4),
        num_text,
        fill=(51, 51, 51),
        font=f_num,
    )

    if item["is_gained"] and had_sign_in_bg is not None:
        w, h = had_sign_in_bg.size
        icon_h = h * CELL_H_MONTH // (CELL_H_MONTH + CELL_DAY_H_MONTH)
        side = min(w, icon_h)
        top = (icon_h - side) // 2
        left = (w - side) // 2
        overlay = _fit(
            had_sign_in_bg.crop((left, top, left + side, top + side)),
            (LOOP_CELL_SIZE, LOOP_CELL_SIZE),
        )
        _paste(cell, overlay, (card_x, 0))

    mark = process_light if item["is_gained"] else process_grey
    if mark is not None:
        m = _fit(mark.convert("RGBA"), (col_w, LOOP_MARK_H))
        _paste(cell, m, (0, LOOP_CELL_SIZE + 8))

    f_day = waves_font_origin(16)
    _draw_center(
        cell,
        col_w // 2,
        LOOP_CELL_SIZE + 8 + LOOP_MARK_H + 6 + 10,
        f"第{item['day']}天",
        f_day,
        day_color,
    )

    return cell


async def render_sign_calendar_pil(
    sign_data: SignInInitData,
    img_info: dict,
    font_style: dict,
    role_name: str,
    uid_display: str,
    month: int,
) -> bytes:
    has_loop = _has_loop(sign_data)

    cover = await _load(img_info.get("main_coverBg", ""))
    box_top = await _load(img_info.get("common_boxTopBg", ""))
    box_center = await _load(img_info.get("common_boxCenterBg", ""))
    box_bottom = await _load(img_info.get("common_boxBottomBg", ""))
    price_bg = await _load(img_info.get("monthSign_priceBg", ""))
    sign_day_bg = await _load(img_info.get("month_signDayBg", ""))
    today_no_sign = await _load(img_info.get("month_todayNoSign", ""))
    had_sign_in_bg = await _load(img_info.get("month_hadSignInBg", ""))

    cycle_bg = loop_card_bg = process_grey = process_light = None
    loop_items = []
    if has_loop:
        cycle_bg = await _load(img_info.get("cycle_bg", ""))
        loop_card_bg = await _load(img_info.get("common_priceBg", ""))
        process_grey = await _load(img_info.get("cycle_process_grey", ""))
        process_light = await _load(img_info.get("cycle_process_light", ""))
        for goods in sorted(sign_data.signLoopGoodsList, key=lambda g: g.serialNum):
            loop_items.append(
                {
                    "day": goods.serialNum + 1,
                    "goods_url": goods.goodsUrl,
                    "num": goods.goodsNum,
                    "is_gained": goods.isGain,
                    "icon": await _load(goods.goodsUrl),
                }
            )

    month_icons = []
    for goods in sign_data.signInGoodsConfigs:
        month_icons.append(await _load(goods.goodsUrl))

    return await _render_sign_calendar_sync(
        sign_data,
        font_style,
        role_name,
        uid_display,
        month,
        cover,
        box_top,
        box_center,
        box_bottom,
        price_bg,
        sign_day_bg,
        today_no_sign,
        had_sign_in_bg,
        cycle_bg,
        loop_card_bg,
        process_grey,
        process_light,
        loop_items,
        month_icons,
        has_loop,
    )


@to_thread
def _render_sign_calendar_sync(
    sign_data: SignInInitData,
    font_style: dict,
    role_name: str,
    uid_display: str,
    month: int,
    cover,
    box_top,
    box_center,
    box_bottom,
    price_bg,
    sign_day_bg,
    today_no_sign,
    had_sign_in_bg,
    cycle_bg,
    loop_card_bg,
    process_grey,
    process_light,
    loop_items,
    month_icons,
    has_loop: bool,
) -> bytes:
    main_bg = _hex(font_style.get("main_bgColor"), "#D9C7BA")
    month_text = _hex(font_style.get("month_textColor"), "#1d1d1d")
    cycle_title_c = _hex(font_style.get("cycle_titleColor"), "#E58A4E")
    cycle_time_c = _hex(font_style.get("cycle_timeTextColor"), "#666666")

    cover_h = cover.height if cover else 0

    cycle_section_h = (
        CYCLE_MARGIN_TOP + CYCLE_H + CYCLE_MARGIN_BOTTOM if has_loop else 0
    )

    grid_rows = (len(sign_data.signInGoodsConfigs) + CELLS_PER_ROW - 1) // CELLS_PER_ROW
    row_h = CELL_H_MONTH + CELL_DAY_H_MONTH
    grid_h = (
        GRID_PAD_VERT * 2
        + grid_rows * row_h
        + max(0, grid_rows - 1) * CELL_GAP_MONTH
    )

    box_top_h = box_top.height if box_top else 100
    raw_bottom_h = box_bottom.height if box_bottom else 124
    box_bottom_h = max(raw_bottom_h - BOX_BOTTOM_CROP_TOP, 0)
    box_section_h = box_top_h + grid_h + box_bottom_h - BOX_BOTTOM_OVERLAP

    bottom_pad = 80
    canvas_h = cover_h + cycle_section_h + box_section_h + bottom_pad

    canvas = Image.new("RGBA", (CANVAS_W, canvas_h), main_bg + (255,))

    y = 0

    if cover is not None:
        cover_x = (CANVAS_W - cover.width) // 2
        _paste(canvas, cover, (cover_x, 0))
        y = cover_h

    if has_loop:
        y += CYCLE_MARGIN_TOP
        cx = BOX_MARGIN_X
        if cycle_bg is not None:
            scaled_bg = cycle_bg.convert("RGBA").resize((BOX_W, CYCLE_H), Image.BILINEAR)
            _paste(canvas, scaled_bg, (cx, y))

        y_cur = y + CYCLE_PAD_TOP
        title_h = CYCLE_TITLE_H
        f_title = waves_font_origin(26)
        _draw_center(
            canvas, CANVAS_W // 2, y_cur + title_h // 2, sign_data.loopSignName, f_title, cycle_title_c
        )
        y_cur += title_h

        time_h = CYCLE_TIME_H
        f_time = waves_font_origin(18)
        time_str = _format_loop_range(sign_data.loopStartTimes, sign_data.loopEndTimes)
        _draw_center(canvas, CANVAS_W // 2, y_cur + time_h // 2, time_str, f_time, cycle_time_c)
        y_cur += time_h + CYCLE_TIME_GAP

        strip_y = y_cur
        col_w = (BOX_W - 60) // 7
        strip_x_start = cx + 30
        for i, item in enumerate(loop_items):
            cell_img = _render_loop_cell(
                item,
                item.get("icon"),
                loop_card_bg,
                process_grey,
                process_light,
                had_sign_in_bg,
                col_w,
                cycle_time_c,
            )
            _paste(canvas, cell_img, (strip_x_start + i * col_w, strip_y))
        y += CYCLE_H + CYCLE_MARGIN_BOTTOM

    box_x = BOX_MARGIN_X
    if box_top is not None:
        _paste(canvas, box_top, (box_x, y))

    draw = ImageDraw.Draw(canvas)
    f_line1 = waves_font_origin(26)
    f_highlight = waves_font_origin(32)
    f_line2 = waves_font_origin(20)
    f_user = waves_font_origin(26)
    f_uid = waves_font_origin(20)

    box_top_cy = y + box_top_h // 2
    left_x = box_x + 40
    right_x = box_x + BOX_W - 44

    sign_text_a = f"{month}月累计签到 "
    sign_text_b = f"{sign_data.sigInNum}"
    sign_text_c = " 天"
    wa = _text_size(draw, sign_text_a, f_line1)[0]
    wb = _text_size(draw, sign_text_b, f_highlight)[0]
    line1_top = box_top_cy - 26
    draw.text((left_x, line1_top), sign_text_a, fill=month_text, font=f_line1)
    draw.text((left_x + wa, line1_top - 3), sign_text_b, fill=cycle_title_c, font=f_highlight)
    draw.text((left_x + wa + wb, line1_top), sign_text_c, fill=month_text, font=f_line1)

    line2_top = line1_top + 38
    draw.text(
        (left_x, line2_top),
        f"漏签{sign_data.omissionNnm}天",
        fill=cycle_title_c,
        font=f_line2,
    )

    name_text = role_name[:8] if len(role_name) > 8 else role_name
    if len(role_name) > 8:
        name_text = name_text + "..."
    user_w = _text_size(draw, name_text, f_user)[0]
    draw.text((right_x - user_w, line1_top), name_text, fill=month_text, font=f_user)
    uid_text = f"UID: {uid_display}"
    uid_w = _text_size(draw, uid_text, f_uid)[0]
    draw.text((right_x - uid_w, line2_top), uid_text, fill=month_text, font=f_uid)

    y += box_top_h

    grid_top = y
    if box_center is not None:
        center_scaled = _fit(box_center.convert("RGBA"), (BOX_W, grid_h))
        _paste(canvas, center_scaled, (box_x, grid_top))

    bottom_y = grid_top + grid_h - BOX_BOTTOM_OVERLAP
    if box_bottom is not None:
        cropped = box_bottom.crop(
            (0, BOX_BOTTOM_CROP_TOP, box_bottom.width, box_bottom.height)
        )
        _paste(canvas, cropped, (box_x, bottom_y))

    grid_x_start = box_x + GRID_PAD_LEFT
    grid_y_start = grid_top + GRID_PAD_VERT
    for idx, goods in enumerate(sign_data.signInGoodsConfigs):
        col = idx % CELLS_PER_ROW
        row = idx // CELLS_PER_ROW
        cx = grid_x_start + col * (CELL_W_MONTH + CELL_GAP_MONTH)
        cy = grid_y_start + row * (row_h + CELL_GAP_MONTH)
        icon = month_icons[idx] if idx < len(month_icons) else None
        cell_img = _render_month_cell(
            sign_data, goods, icon, price_bg, today_no_sign, sign_day_bg, had_sign_in_bg
        )
        _paste(canvas, cell_img, (cx, cy))

    y += grid_h

    add_footer(canvas, color="white")

    out = BytesIO()
    canvas.convert("RGB").save(out, format="PNG")
    return out.getvalue()
