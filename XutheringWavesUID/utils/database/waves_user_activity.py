from typing import Any, Dict, List, Optional, Set, Type, TypeVar

from sqlmodel import Field, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import and_, or_

from gsuid_core.utils.database.base_models import BaseBotIDModel

from ._session import with_read_session, with_session

T_WavesUserActivity = TypeVar("T_WavesUserActivity", bound="WavesUserActivity")


class WavesUserActivity(BaseBotIDModel, table=True):
    """用户活跃度记录表

    记录每个用户（user_id + bot_id）的最后活跃时间
    通过 hook 机制自动更新，用于判断用户活跃度
    """

    __tablename__ = "WavesUserActivity"
    __table_args__: Dict[str, Any] = {"extend_existing": True}

    user_id: str = Field(default="", title="用户ID")
    bot_self_id: str = Field(default="", title="BotSelfID")
    last_active_time: Optional[int] = Field(default=None, title="最后活跃时间")

    @classmethod
    @with_session
    async def update_user_activity(
        cls: Type[T_WavesUserActivity],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        bot_self_id: str,
    ) -> bool:
        return await cls._touch(session, user_id, bot_id, bot_self_id)

    @classmethod
    @with_session
    async def update_many(
        cls: Type[T_WavesUserActivity],
        session: AsyncSession,
        rows: List[tuple[str, str, str]],
    ) -> None:
        for user_id, bot_id, bot_self_id in rows:
            await cls._touch(session, user_id, bot_id, bot_self_id)

    @classmethod
    async def _touch(
        cls: Type[T_WavesUserActivity],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        bot_self_id: str,
    ) -> bool:
        """更新用户活跃时间

        如果记录不存在则创建，存在则更新时间

        Args:
            user_id: 用户ID
            bot_id: 机器人ID

        Returns:
            bool: 是否成功更新
        """
        import time

        current_time = int(time.time())

        # 查询现有记录（新字段）
        sql = select(cls).where(
            and_(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                cls.bot_self_id == bot_self_id,
            )
        )
        result = await session.execute(sql)
        existing = result.scalars().first()

        if existing:
            # 更新时间
            existing.last_active_time = current_time
            session.add(existing)
        else:
            # 兼容旧数据：bot_id 里存的是 bot_self_id，且 bot_self_id 为空
            legacy_sql = select(cls).where(
                and_(
                    cls.user_id == user_id,
                    cls.bot_id == bot_self_id,
                    or_(cls.bot_self_id == "", cls.bot_self_id.is_(None)),
                )
            )
            legacy_result = await session.execute(legacy_sql)
            legacy = legacy_result.scalars().first()
            if legacy:
                legacy.bot_id = bot_id
                legacy.bot_self_id = bot_self_id
                legacy.last_active_time = current_time
                session.add(legacy)
                return True
            # 创建新记录
            new_record = cls(
                user_id=user_id,
                bot_id=bot_id,
                bot_self_id=bot_self_id,
                last_active_time=current_time,
            )
            session.add(new_record)

        return True

    @classmethod
    @with_read_session
    async def get_user_last_active_time(
        cls: Type[T_WavesUserActivity],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        bot_self_id: str,
    ) -> Optional[int]:
        """获取用户最后活跃时间

        Args:
            user_id: 用户ID
            bot_id: 机器人ID

        Returns:
            Optional[int]: 最后活跃时间戳，不存在返回 None
        """
        sql = select(cls).where(
            and_(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                cls.bot_self_id == bot_self_id,
            )
        )
        result = await session.execute(sql)
        record = result.scalars().first()
        if record:
            return record.last_active_time

        # 兼容旧数据：bot_id 里存的是 bot_self_id，且 bot_self_id 为空
        legacy_sql = select(cls).where(
            and_(
                cls.user_id == user_id,
                cls.bot_id == bot_self_id,
                or_(cls.bot_self_id == "", cls.bot_self_id.is_(None)),
            )
        )
        legacy_result = await session.execute(legacy_sql)
        legacy = legacy_result.scalars().first()
        return legacy.last_active_time if legacy else None

    @classmethod
    @with_read_session
    async def get_active_user_count(
        cls: Type[T_WavesUserActivity],
        session: AsyncSession,
        active_days: int,
    ) -> int:
        """获取活跃用户数量

        Args:
            active_days: 活跃认定天数

        Returns:
            int: 活跃用户数量
        """
        import time

        current_time = int(time.time())
        threshold_time = current_time - (active_days * 24 * 60 * 60)

        sql = select(cls).where(
            and_(
                cls.last_active_time.is_not(None),
                cls.last_active_time >= threshold_time,
            )
        )

        result = await session.execute(sql)
        data = result.scalars().all()
        return len(data)

    @classmethod
    @with_read_session
    async def get_active_user_ids(
        cls: Type[T_WavesUserActivity],
        session: AsyncSession,
        active_days: int,
    ) -> Set[str]:
        """一次性取出所有活跃用户的 user_id 集合"""
        import time

        threshold_time = int(time.time()) - active_days * 24 * 60 * 60
        sql = select(cls.user_id).where(
            and_(
                cls.last_active_time.is_not(None),
                cls.last_active_time >= threshold_time,
            )
        )
        result = await session.execute(sql)
        return {uid for uid in result.scalars().all() if uid}

    @classmethod
    @with_read_session
    async def is_user_active(
        cls: Type[T_WavesUserActivity],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        bot_self_id: str,
        active_days: int,
    ) -> bool:
        """判断用户是否活跃

        Args:
            user_id: 用户ID
            bot_id: 机器人ID
            active_days: 活跃认定天数

        Returns:
            bool: 是否活跃
        """
        import time

        last_active_time = await cls.get_user_last_active_time(user_id, bot_id, bot_self_id)
        if last_active_time is None:
            return False

        current_time = int(time.time())
        threshold_time = current_time - (active_days * 24 * 60 * 60)

        return last_active_time >= threshold_time
