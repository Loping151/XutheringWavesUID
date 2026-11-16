from typing import List, Tuple, Optional
from datetime import datetime

from pydantic import BaseModel


class LinkConfig(BaseModel):
    linkUrl: Optional[str] = None
    linkType: int
    entryId: str


class ProgressData(BaseModel):
    progressType: int
    dataRange: List[str]
    title: str


class RepeatConfig(BaseModel):
    endDate: str
    isNeverEnd: bool
    repeatInterval: int
    dataRanges: List[ProgressData]


class CountDown(BaseModel):
    dateRange: Optional[List[str]] = None


class ContentData(BaseModel):
    contentUrl: str
    countDown: Optional[CountDown] = None
    title: str


class VersionActivity(BaseModel):
    content: List[ContentData]


class ImageItem(BaseModel):
    linkConfig: LinkConfig
    img: str
    title: str


class SpecialImages(BaseModel):
    name: str
    imgs: List[ImageItem]


class CalendarAxis(BaseModel):
    t0: datetime
    x0: float
    t1: datetime
    x1: float
    y_top: float
    y_bottom: float
    y_label: Optional[float] = None
    avoid: List[Tuple[float, float]] = []


class CalendarStyle(BaseModel):
    color: str = "#FF4D5E"
    text: str = "#FFFFFF"
    width: float = 4
    font: float = 34
    alpha: float = 0.55
    tag_alpha: float = 0.9


class CalendarVersion(BaseModel):
    """resource/calendar/versions.json 的单个版本, 坐标按原图 size 计"""

    file: str
    start: datetime
    size: Tuple[int, int]
    axis: Optional[CalendarAxis] = None
    style: Optional[CalendarStyle] = None
