from datetime import datetime
from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

from gsuid_core.models import Event
from gsuid_core.utils.fonts.fonts import core_font
from gsuid_core.utils.image.convert import convert_img

from ..utils.image import get_event_avatar, get_square_avatar
from ..utils.ascension.char import get_char_id
from ..utils.util import hide_uid
from .line_data import BingoAnswer, BingoCell


SCALE = 2
W = 480 * SCALE
PAD = 12 * SCALE
YELLOW = (255, 234, 0)
YELLOW2 = (247, 255, 29)
BLACK = (20, 25, 30)
WHITE = (255, 255, 255)


def _font(size: int):
    return core_font(size * SCALE)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, max_size: int, min_size: int = 8):
    for size in range(max_size, min_size - 1, -1):
        font = _font(size)
        if _text_size(draw, text, font)[0] <= max_width:
            return font
    return _font(min_size)


def _draw_center(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, fill) -> None:
    w, h = _text_size(draw, text, font)
    draw.text((xy[0] - w / 2, xy[1] - h / 2), text, font=font, fill=fill)


def _gradient(size: tuple[int, int], start: tuple[int, int, int], end: tuple[int, int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size)
    px = img.load()
    for y in range(h):
        for x in range(w):
            # 近似 CSS: linear-gradient(46deg,#464b50,#14191e)
            t = min(1.0, max(0.0, (x / w * 0.42 + y / h * 0.58)))
            r = int(start[0] * (1 - t) + end[0] * t)
            g = int(start[1] * (1 - t) + end[1] * t)
            b = int(start[2] * (1 - t) + end[2] * t)
            px[x, y] = (r, g, b, 255)
    return img


def _yellow_gradient(size: tuple[int, int]) -> Image.Image:
    return _gradient(size, YELLOW2, YELLOW)


def _round_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _paste_round(base: Image.Image, patch: Image.Image, xy: tuple[int, int], radius: int) -> None:
    mask = _round_mask(patch.size, radius)
    base.paste(patch, xy, mask)


def _paste_cover(base: Image.Image, img: Image.Image, box: tuple[int, int, int, int], opacity: float = 1.0) -> None:
    x1, y1, x2, y2 = box
    target_w = x2 - x1
    target_h = y2 - y1
    img = img.convert("RGBA")
    scale = max(target_w / img.width, target_h / img.height)
    resized = img.resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS)
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    cropped = resized.crop((left, top, left + target_w, top + target_h))
    if opacity < 1:
        alpha = cropped.getchannel("A").point(lambda a: int(a * opacity))
        cropped.putalpha(alpha)
    base.alpha_composite(cropped, (x1, y1))


def _paste_circle_avatar(base: Image.Image, avatar: Image.Image, xy: tuple[int, int], size: int) -> None:
    avatar_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    _paste_cover(avatar_layer, avatar, (0, 0, size, size), opacity=1.0)

    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size - 1, size - 1), fill=255)

    ring = Image.new("RGBA", (size + 8 * SCALE, size + 8 * SCALE), (0, 0, 0, 0))
    ring_draw = ImageDraw.Draw(ring)
    ring_draw.ellipse(
        (1 * SCALE, 1 * SCALE, ring.width - 1 * SCALE, ring.height - 1 * SCALE),
        fill=(255, 234, 0, 55),
        outline=YELLOW,
        width=2 * SCALE,
    )
    base.alpha_composite(ring, (xy[0] - 4 * SCALE, xy[1] - 4 * SCALE))
    base.paste(avatar_layer, xy, mask)


def _make_placeholder(name: str, size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (247, 248, 249, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, size - 1, size - 1), fill=(247, 248, 249))
    font = _fit_text(draw, name, size - 16 * SCALE, 14, 8)
    _draw_center(draw, (size // 2, size // 2), name, font, BLACK)
    return img


async def _cell_avatar(cell: BingoCell, icon_size: int) -> Image.Image:
    role_id = cell.role_id or get_char_id(cell.role_name, loose=True)
    if role_id is None:
        return _make_placeholder(cell.role_name, icon_size)
    return await get_square_avatar(role_id)


def _draw_header(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    data: BingoAnswer,
    ev: Event,
    uid: str,
    user_avatar: Image.Image,
) -> int:
    title_y = 28 * SCALE
    _paste_circle_avatar(img, user_avatar, (18 * SCALE, 17 * SCALE), 42 * SCALE)

    title_font = _fit_text(draw, data.title, W - 120 * SCALE, 22, 14)
    _draw_center(draw, (W // 2, title_y), data.title, title_font, WHITE)

    subtitle = "只要连成一条线说明你是鸣潮老资历"
    _draw_center(draw, (W // 2, title_y + 27 * SCALE), subtitle, _font(13), (255, 255, 255, 205))

    sender_name = str(ev.user_id)
    if ev.sender and ev.sender.get("nickname"):
        sender_name = str(ev.sender["nickname"])
    owned = sum(1 for i in data.cells if i.owned)
    meta = f"填表人：{sender_name}    UID：{hide_uid(uid)}    已点亮 {owned}/{len(data.cells)}"
    _draw_center(
        draw,
        (W // 2, title_y + 49 * SCALE),
        meta,
        _fit_text(draw, meta, W - 80 * SCALE, 11, 8),
        (255, 255, 255, 165),
    )

    return title_y + 68 * SCALE


def _draw_title_bar(img: Image.Image, draw: ImageDraw.ImageDraw, y: int) -> int:
    h = 42 * SCALE
    bar = _yellow_gradient((W - PAD * 2, h))
    # 模拟小黑盒标题条的光斑
    shine = Image.new("RGBA", bar.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shine)
    sd.ellipse((-70 * SCALE, -150 * SCALE, 260 * SCALE, 170 * SCALE), fill=(255, 255, 255, 45))
    sd.ellipse((240 * SCALE, -210 * SCALE, 620 * SCALE, 180 * SCALE), fill=(255, 255, 255, 35))
    bar.alpha_composite(shine)
    _paste_round(img, bar, (PAD, y), 5 * SCALE)

    text = "只要连成一条线说明你是鸣潮老资历"
    _draw_center(
        draw,
        (W // 2, y + h // 2),
        text,
        _fit_text(draw, text, W - PAD * 4, 15, 10),
        BLACK,
    )
    return y + h + 10 * SCALE


def _draw_check_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, selected: bool) -> None:
    if selected:
        r = 8 * SCALE
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=YELLOW, outline=BLACK, width=1 * SCALE)
        draw.line(
            (
                cx - 4 * SCALE,
                cy,
                cx - 1 * SCALE,
                cy + 4 * SCALE,
                cx + 5 * SCALE,
                cy - 5 * SCALE,
            ),
            fill=BLACK,
            width=2 * SCALE,
            joint="curve",
        )
    else:
        r = 12 * SCALE
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 150), outline=(200, 205, 210), width=1 * SCALE)


async def _draw_grid_async(img: Image.Image, draw: ImageDraw.ImageDraw, data: BingoAnswer, top: int) -> tuple[int, int, int, int, int]:
    size = data.size
    grid_w = W - PAD * 2
    gap = 2 * SCALE
    cell = (grid_w - gap * (size - 1)) // size
    grid_h = cell * size + gap * (size - 1)
    left = PAD

    mask = _round_mask((grid_w, grid_h), 8 * SCALE)
    grid_layer = Image.new("RGBA", (grid_w, grid_h), (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid_layer)

    for cell_data in data.cells:
        row, col = divmod(cell_data.index, size)
        x = col * (cell + gap)
        y = row * (cell + gap)
        # 不铺浅色底，避免头像边缘/透明图出现白边。
        grid_draw.rectangle((x, y, x + cell, y + cell), fill=(20, 25, 30, 255))
        avatar = await _cell_avatar(cell_data, cell)
        _paste_cover(grid_layer, avatar, (x, y, x + cell, y + cell), opacity=1.0)

        if not cell_data.owned:
            # 不用原网页那种中间浅白字；未拥有角色直接压暗，效果接近之前自制 UI。
            dark = Image.new("RGBA", (cell, cell), (0, 0, 0, 125))
            grid_layer.alpha_composite(dark, (x, y))

        # 选中边框先画，名字最后画，避免边框挡字；边框也改细一点。
        if cell_data.owned:
            grid_draw.rectangle(
                (x + 2 * SCALE, y + 2 * SCALE, x + cell - 2 * SCALE, y + cell - 2 * SCALE),
                outline=YELLOW,
                width=2 * SCALE,
            )
            _draw_check_icon(
                grid_draw,
                x + cell - 13 * SCALE,
                y + 13 * SCALE,
                True,
            )

        # 名字直接浮在底部，无底框。
        font = _fit_text(grid_draw, cell_data.role_name, cell - 8 * SCALE, 11, 8)
        tw, th = _text_size(grid_draw, cell_data.role_name, font)
        bar_h = max(17 * SCALE, th + 8 * SCALE)
        text_x = x + (cell - tw) / 2
        text_y = y + cell - bar_h + (bar_h - th) / 2 - 1 * SCALE
        grid_draw.text(
            (text_x + 1 * SCALE, text_y + 1 * SCALE),
            cell_data.role_name,
            font=font,
            fill=(0, 0, 0, 90),
        )
        grid_draw.text(
            (text_x, text_y),
            cell_data.role_name,
            font=font,
            fill=(255, 255, 255, 185 if cell_data.owned else 155),
        )

    img.paste(grid_layer, (left, top), mask)
    return left, top, cell, gap, grid_h


def _draw_stamp(img: Image.Image, data: BingoAnswer) -> None:
    ok = data.line_count > 0
    sw, sh = 130 * SCALE, 115 * SCALE
    stamp = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    d = ImageDraw.Draw(stamp)

    outline = YELLOW if ok else (140, 145, 150)
    fill = (255, 234, 0, 30) if ok else (140, 145, 150, 28)
    d.rounded_rectangle((9 * SCALE, 12 * SCALE, sw - 12 * SCALE, sh - 14 * SCALE), radius=12 * SCALE, outline=outline, width=3 * SCALE, fill=fill)
    d.rounded_rectangle((18 * SCALE, 22 * SCALE, sw - 22 * SCALE, sh - 24 * SCALE), radius=8 * SCALE, outline=outline, width=2 * SCALE)

    title = "认证成功" if ok else "认证失败"
    line_text = f"连线 {data.line_count} 条"
    date = datetime.now().strftime("%Y.%m.%d")
    color = BLACK if ok else (140, 145, 150)
    _draw_center(d, (sw // 2, 39 * SCALE), line_text, _font(10), outline)
    _draw_center(d, (sw // 2, 58 * SCALE), title, _font(13), color)
    _draw_center(d, (sw // 2, 83 * SCALE), date, _font(10), outline)

    stamp = stamp.rotate(-19, expand=True, resample=Image.Resampling.BICUBIC)
    img.alpha_composite(stamp, (W - stamp.width - 2 * SCALE, 0))


async def draw_bingo_img(data: BingoAnswer, ev: Event, uid: str) -> bytes:
    header_h = 76 * SCALE
    title_h = 52 * SCALE
    grid_h = W - PAD * 2
    footer_h = 62 * SCALE
    height = header_h + title_h + grid_h + footer_h + 10 * SCALE

    img = _gradient((W, height), (70, 75, 80), (20, 25, 30))
    draw = ImageDraw.Draw(img)

    user_avatar = await get_event_avatar(ev, size=128, is_valid_at_param=False)
    y = _draw_header(img, draw, data, ev, uid, user_avatar)
    y = _draw_title_bar(img, draw, y)
    _, grid_top, _, _, actual_grid_h = await _draw_grid_async(img, draw, data, y)
    _draw_stamp(img, data)

    footer_y = grid_top + actual_grid_h + 18 * SCALE
    owned = sum(1 for i in data.cells if i.owned)
    footer = f"已点亮 {owned}/{len(data.cells)} · 连线 {data.line_count} 条 · XutheringWavesUID"
    _draw_center(draw, (W // 2, footer_y + 12 * SCALE), footer, _fit_text(draw, footer, W - 40 * SCALE, 12, 8), (255, 255, 255, 170))

    # 小黑盒截图是直角深色整图，不额外做浅色卡片。
    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return await convert_img(Image.open(BytesIO(buf.getvalue())))
