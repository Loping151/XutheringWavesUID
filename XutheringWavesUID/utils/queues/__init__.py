from typing import Any, Awaitable, Callable

from gsuid_core.logger import logger

from .const import QUEUE_SCORE_RANK, QUEUE_ABYSS_RECORD, QUEUE_SLASH_RECORD, QUEUE_MATRIX_RECORD
from .queues import event_handler, start_dispatcher


# queue_name -> 构建模块内的上传入口
_UPLOAD_JOBS = {
    QUEUE_SCORE_RANK: ("upload_score", "面板"),
    QUEUE_ABYSS_RECORD: ("upload_abyss", "深渊"),
    QUEUE_SLASH_RECORD: ("upload_slash", "冥海"),
    QUEUE_MATRIX_RECORD: ("upload_matrix", "矩阵"),
}


async def _dispatch_upload(item: Any, entrypoint: str, label: str) -> None:
    if not item or not isinstance(item, dict):
        return
    try:
        from ..waves_build import upload_gateway

        uploader: Callable[[Any], Awaitable[None]] = getattr(upload_gateway, entrypoint)
        await uploader(item)
    except Exception as e:
        logger.exception(f"[鸣潮·队列] 构建上传入口不可用，{label}上传跳过: {e}")


def _make_handler(queue: str, entrypoint: str, label: str):
    async def _handler(item: Any):
        await _dispatch_upload(item, entrypoint, label)
    _handler.__name__ = f"send_{queue.removeprefix('waves_')}"
    return _handler


for _queue, (_entrypoint, _label) in _UPLOAD_JOBS.items():
    event_handler(_queue)(_make_handler(_queue, _entrypoint, _label))


def init_queues():
    # 启动任务分发器
    start_dispatcher(daemon=True)
