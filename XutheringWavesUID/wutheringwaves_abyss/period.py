from typing import Optional
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

CHINA_TZ = timezone(timedelta(hours=8))


def parse_rank_date(date_str: str) -> Optional[datetime]:
    """解析远端排行接口返回的 start_date (多格式容错)"""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=CHINA_TZ)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=CHINA_TZ)
        return dt.astimezone(CHINA_TZ)
    except ValueError:
        return None


@dataclass(frozen=True)
class CycleSpec:
    """玩法周期。base_time 是 base_period 开启的边界 (含)；早于 base_time 视为 base_period - 1。

    anchors 为可选的显式周期边界 ((期号, 开始时间), …) 升序；用于非匀速排期(某期提前/延后几天)。
    不填=纯匀速(base_time+N×refresh)。填了则按显式边界判定, 末端边界之后再按 refresh_seconds 外推。"""
    base_time: datetime
    refresh_seconds: int
    base_period: int
    anchors: tuple = ()

    @property
    def base_timestamp(self) -> int:
        return int(self.base_time.astimezone(timezone.utc).timestamp())

    def _resolve(self, ref: datetime) -> tuple:
        """显式边界模式: 返回 (期号, 当期开始时间)。早于首边界向前外推, 晚于末边界向后外推。"""
        first_p, first_st = self.anchors[0]
        last_p, last_st = self.anchors[-1]
        step = self.refresh_seconds
        if ref < first_st:
            n = -int(-(first_st - ref).total_seconds() // step)  # 向上取整
            return first_p - n, first_st - timedelta(seconds=n * step)
        cur_p, cur_st = first_p, first_st
        for p, st in self.anchors:
            if ref >= st:
                cur_p, cur_st = p, st
            else:
                break
        if (cur_p, cur_st) == (last_p, last_st):
            n = int((ref - last_st).total_seconds() // step)
            return last_p + n, last_st + timedelta(seconds=n * step)
        return cur_p, cur_st

    def cycle_start(self, ref_time: Optional[datetime] = None) -> datetime:
        now = ref_time or datetime.now(CHINA_TZ)
        if self.anchors:
            return self._resolve(now)[1]
        if now <= self.base_time:
            return self.base_time
        elapsed = int((now - self.base_time).total_seconds())
        cycles = elapsed // self.refresh_seconds
        return self.base_time + timedelta(seconds=cycles * self.refresh_seconds)

    def is_record_expired(
        self,
        record_timestamp: Optional[int],
        ref_time: Optional[datetime] = None,
    ) -> bool:
        now = ref_time or datetime.now(CHINA_TZ)
        if not self.anchors and now <= self.base_time:
            return False
        if record_timestamp is None:
            return True
        try:
            record_ts = int(record_timestamp)
        except (TypeError, ValueError):
            return True
        record_time = datetime.fromtimestamp(record_ts, tz=timezone.utc).astimezone(CHINA_TZ)
        if not self.anchors and record_time < self.base_time:
            return True
        return record_time < self.cycle_start(now)

    def period_number(self, ref_time: Optional[datetime] = None) -> int:
        ref = ref_time or datetime.now(CHINA_TZ)
        if self.anchors:
            return self._resolve(ref)[0]
        if ref < self.base_time:
            return self.base_period - 1
        elapsed = int((ref - self.base_time).total_seconds())
        cycles = elapsed // self.refresh_seconds
        return self.base_period + cycles


# 2025-11-24 04:00 为第 11 期开始边界
SLASH_CYCLE = CycleSpec(
    base_time=datetime(2025, 11, 24, 4, 0, 0, tzinfo=CHINA_TZ),
    refresh_seconds=28 * 24 * 60 * 60,
    base_period=11,
)

# 2025-11-10 04:00 为第 29 期开始边界
TOWER_CYCLE = CycleSpec(
    base_time=datetime(2025, 11, 10, 4, 0, 0, tzinfo=CHINA_TZ),
    refresh_seconds=28 * 24 * 60 * 60,
    base_period=29,
)

# 矩阵非匀速排期: 第4期 2026-05-07 04:00 开启; 第5期 2026-06-14 04:00 开启;
# 第6期实际 2026-07-17 04:00 开启 (比 42 天匀速的 07-26 提前 9 天);
# 第7期实际 2026-08-27 04:00 开启 (比 42 天匀速的 08-28 提前 1 天)。
# 第7期之后按 42 天外推。base 锚定到末边界(第7期)。
MATRIX_CYCLE = CycleSpec(
    base_time=datetime(2026, 8, 27, 4, 0, 0, tzinfo=CHINA_TZ),
    refresh_seconds=42 * 24 * 60 * 60,
    base_period=7,
    anchors=(
        (4, datetime(2026, 5, 7, 4, 0, 0, tzinfo=CHINA_TZ)),
        (5, datetime(2026, 6, 14, 4, 0, 0, tzinfo=CHINA_TZ)),
        (6, datetime(2026, 7, 17, 4, 0, 0, tzinfo=CHINA_TZ)),
        (7, datetime(2026, 8, 27, 4, 0, 0, tzinfo=CHINA_TZ)),
    ),
)


# 老调用方的兼容入口 (常量 + 函数), 实际逻辑都在 CycleSpec
SLASH_BASE_TIME = SLASH_CYCLE.base_time
SLASH_BASE_TIMESTAMP = SLASH_CYCLE.base_timestamp
SLASH_REFRESH_SECONDS = SLASH_CYCLE.refresh_seconds
SLASH_BASE_PERIOD = SLASH_CYCLE.base_period

TOWER_BASE_TIME = TOWER_CYCLE.base_time
TOWER_BASE_TIMESTAMP = TOWER_CYCLE.base_timestamp
TOWER_REFRESH_SECONDS = TOWER_CYCLE.refresh_seconds
TOWER_BASE_PERIOD = TOWER_CYCLE.base_period

MATRIX_BASE_TIME = MATRIX_CYCLE.base_time
MATRIX_BASE_TIMESTAMP = MATRIX_CYCLE.base_timestamp
MATRIX_REFRESH_SECONDS = MATRIX_CYCLE.refresh_seconds
MATRIX_BASE_PERIOD = MATRIX_CYCLE.base_period


def get_current_slash_cycle_start(reference_time: Optional[datetime] = None) -> datetime:
    return SLASH_CYCLE.cycle_start(reference_time)


def is_slash_record_expired(
    record_timestamp: Optional[int],
    reference_time: Optional[datetime] = None,
) -> bool:
    return SLASH_CYCLE.is_record_expired(record_timestamp, reference_time)


def get_slash_period_number(reference_time: Optional[datetime] = None) -> int:
    return SLASH_CYCLE.period_number(reference_time)


def get_current_tower_cycle_start(reference_time: Optional[datetime] = None) -> datetime:
    return TOWER_CYCLE.cycle_start(reference_time)


def is_tower_record_expired(
    record_timestamp: Optional[int],
    reference_time: Optional[datetime] = None,
) -> bool:
    return TOWER_CYCLE.is_record_expired(record_timestamp, reference_time)


def get_tower_period_number(reference_time: Optional[datetime] = None) -> int:
    return TOWER_CYCLE.period_number(reference_time)


def get_current_matrix_cycle_start(reference_time: Optional[datetime] = None) -> datetime:
    return MATRIX_CYCLE.cycle_start(reference_time)


def is_matrix_record_expired(
    record_timestamp: Optional[int],
    reference_time: Optional[datetime] = None,
) -> bool:
    return MATRIX_CYCLE.is_record_expired(record_timestamp, reference_time)


def get_matrix_period_number(reference_time: Optional[datetime] = None) -> int:
    return MATRIX_CYCLE.period_number(reference_time)
