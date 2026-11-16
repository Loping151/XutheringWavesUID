import json
from typing import List, Tuple, Optional
from pathlib import Path
from datetime import datetime

from PIL import Image, ImageDraw, ImageColor, ImageFilter

from .calendar_model import CalendarStyle, CalendarVersion
from ..utils.fonts.waves_fonts import waves_font_origin
from ..utils.resource.RESOURCE_PATH import CALENDAR_PATH


def get_current_calendar(now: datetime) -> Optional[Tuple[Path, CalendarVersion]]:
    """取已开始的最新版本日历图; 索引缺失、损坏或缺图时返回 None"""
    try:
        raw = json.loads((CALENDAR_PATH / "versions.json").read_text(encoding="utf-8"))
        versions = {tuple(map(int, k.split("."))): CalendarVersion.model_validate(v) for k, v in raw.items()}
    except Exception:
        return None
    started = [k for k, v in versions.items() if v.start <= now]
    if not started:
        return None
    entry = versions[max(started)]
    path = CALENDAR_PATH / entry.file
    return (path, entry) if path.is_file() else None


def _place_tag(x: float, w: float, width: int, avoid: List[Tuple[float, float]], gap: float, span: Tuple[float, float]):
    """标签左缘: 默认居中于竖线, 压到 avoid 时取离竖线最近的空位, 出时间轴另加 0.6 倍标签宽的代价"""
    want = x - w / 2
    cands = [want, span[0], span[1] - w]
    for a, b in avoid:
        cands += [a - gap - w, b + gap]
    cands = [min(max(c, 4), width - w - 4) for c in cands]
    free = [c for c in cands if all(c + w + gap <= a or c >= b + gap for a, b in avoid)]
    if not free:
        return cands[0]

    def cost(c: float):
        inside = span[0] - gap <= c and c + w <= span[1] + gap
        return abs(c - want) + (0 if inside else 0.6 * w)

    return min(free, key=cost)


def draw_now_pointer(img: Image.Image, entry: CalendarVersion, now: datetime) -> Image.Image:
    """在日历图上画「现在」竖线和时间标签, 精确到小时; img 可已等比缩放"""
    axis = entry.axis
    t = now.replace(minute=0, second=0, microsecond=0)
    if axis is None or not axis.t0 <= t <= axis.t1:
        return img

    k = img.width / entry.size[0]
    x = (axis.x0 + (t - axis.t0) / (axis.t1 - axis.t0) * (axis.x1 - axis.x0)) * k
    style = entry.style or CalendarStyle()
    color = ImageColor.getrgb(style.color)[:3]
    line_a = round(255 * min(max(style.alpha, 0), 1))
    tag_a = round(255 * min(max(style.tag_alpha, 0), 1))
    u = style.width * k / 4

    font = waves_font_origin(max(10, round(style.font * k)))
    text = f"{t.month}.{t.day:02d} {t.hour:02d}:00"
    left, top, right, bottom = font.getbbox(text)
    tag_w, tag_h = right - left + 28 * u, bottom - top + 18 * u
    avoid = [(a * k, b * k) for a, b in axis.avoid]
    tag_x = _place_tag(x, tag_w, img.width, avoid, 8 * u, (axis.x0 * k, axis.x1 * k))
    tag_y = (axis.y_top if axis.y_label is None else axis.y_label) * k - tag_h / 2
    arrow = 11 * u
    y1, y2 = tag_y + tag_h + arrow * 1.3, axis.y_bottom * k

    img = img.convert("RGBA")
    glow = Image.new("RGBA", img.size)
    ImageDraw.Draw(glow).line((x, y1, x, y2), color + (round(line_a * 0.45),), max(3, round(12 * u)))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(max(1, 5 * u))))

    layer = Image.new("RGBA", img.size)
    draw = ImageDraw.Draw(layer)
    draw.line((x, y1, x, y2), (20, 10, 20, round(line_a * 0.35)), max(2, round(7 * u)))
    draw.line((x, y1, x, y2), color + (line_a,), max(1, round(4 * u)))
    draw.rounded_rectangle(
        (tag_x, tag_y, tag_x + tag_w, tag_y + tag_h),
        radius=10 * u,
        fill=color + (tag_a,),
        outline=(255, 255, 255, round(tag_a * 0.92)),
        width=max(1, round(3 * u)),
    )
    draw.polygon([(x - arrow, tag_y + tag_h), (x + arrow, tag_y + tag_h), (x, y1)], color + (tag_a,))
    draw.text((tag_x + tag_w / 2, tag_y + tag_h / 2), text, ImageColor.getrgb(style.text), font, "mm")
    img.alpha_composite(layer)
    return img
