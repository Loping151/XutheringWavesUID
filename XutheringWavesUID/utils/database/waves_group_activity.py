from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Set, Type, TypeVar

from sqlmodel import Field, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import and_

from gsuid_core.utils.database.base_models import BaseBotIDModel

from ._session import with_read_session, with_session

# 公告推送期间置位, 群活跃 hook 据此跳过推送自身
ANN_PUSH_GUARD: ContextVar[bool] = ContextVar("waves_ann_push_guard", default=False)

T_WavesGroupActivity = TypeVar("T_WavesGroupActivity", bound="WavesGroupActivity")


class WavesGroupActivity(BaseBotIDModel, table=True):
    """群活跃度记录表: 群最后有人使用本插件的时间"""

    __tablename__ = "WavesGroupActivity"
    __table_args__: Dict[str, Any] = {"extend_existing": True}

    group_id: str = Field(default="", title="群组ID")
    bot_self_id: str = Field(default="", title="BotSelfID")
    last_active_time: Optional[int] = Field(default=None, title="最后活跃时间")

    @classmethod
    @with_session
    async def update_group_activity(
        cls: Type[T_WavesGroupActivity],
        session: AsyncSession,
        group_id: str,
        bot_id: str,
        bot_self_id: str,
    ) -> bool:
        return await cls._touch(session, group_id, bot_id, bot_self_id)

    @classmethod
    @with_session
    async def update_many(
        cls: Type[T_WavesGroupActivity],
        session: AsyncSession,
        rows: List[tuple[str, str, str]],
    ) -> None:
        for group_id, bot_id, bot_self_id in rows:
            await cls._touch(session, group_id, bot_id, bot_self_id)

    @classmethod
    async def _touch(
        cls: Type[T_WavesGroupActivity],
        session: AsyncSession,
        group_id: str,
        bot_id: str,
        bot_self_id: str,
    ) -> bool:
        import time

        current_time = int(time.time())

        sql = select(cls).where(
            and_(
                cls.group_id == group_id,
                cls.bot_id == bot_id,
                cls.bot_self_id == bot_self_id,
            )
        )
        result = await session.execute(sql)
        existing = result.scalars().first()

        if existing:
            existing.last_active_time = current_time
            session.add(existing)
        else:
            session.add(
                cls(
                    group_id=group_id,
                    bot_id=bot_id,
                    bot_self_id=bot_self_id,
                    last_active_time=current_time,
                )
            )

        return True

    @classmethod
    @with_read_session
    async def get_active_group_ids(
        cls: Type[T_WavesGroupActivity],
        session: AsyncSession,
        active_days: int,
    ) -> Set[str]:
        """一次性取出所有活跃群的 group_id 集合"""
        import time

        threshold_time = int(time.time()) - active_days * 24 * 60 * 60

        sql = select(cls.group_id).where(
            and_(
                cls.last_active_time.is_not(None),
                cls.last_active_time >= threshold_time,
            )
        )
        result = await session.execute(sql)
        return {gid for gid in result.scalars().all() if gid}
