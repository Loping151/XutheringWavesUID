import json
import time
from typing import Any, Dict, Optional, Type, TypeVar

from sqlmodel import Field, SQLModel, select
from sqlalchemy.sql import and_
from sqlalchemy.ext.asyncio import AsyncSession

from gsuid_core.utils.database.base_models import BaseBotIDModel, engine

from ._session import with_read_session, with_session

T_Personal = TypeVar("T_Personal", bound="WavesCustomWeight")
T_Group = TypeVar("T_Group", bound="WavesGroupWeight")


def _loads(raw: str) -> Dict[str, str]:
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _dumps(data: Dict[str, str]) -> str:
    return json.dumps(dict(sorted(data.items())), ensure_ascii=False, separators=(",", ":"))


class WavesCustomWeight(BaseBotIDModel, table=True):
    """个人自定义权重: user + uid 维度, 角色 → 权重 ID, 外加跟随的订阅。"""

    __tablename__ = "WavesCustomWeight"
    __table_args__: Dict[str, Any] = {"extend_existing": True}

    user_id: str = Field(default="", title="用户ID", index=True)
    uid: str = Field(default="", title="特征码")
    weights: str = Field(default="{}", title="角色权重")
    sub_id: str = Field(default="", title="订阅ID")
    sub_hash: str = Field(default="", title="订阅内容hash")
    sub_items: str = Field(default="{}", title="订阅内容")
    updated_at: int = Field(default=0, title="更新时间")

    def weight_map(self) -> Dict[str, str]:
        return _loads(self.weights)

    def sub_map(self) -> Dict[str, str]:
        return _loads(self.sub_items)

    def set_maps(self, weights: Optional[Dict[str, str]] = None, sub_items: Optional[Dict[str, str]] = None):
        if weights is not None:
            self.weights = _dumps(weights)
        if sub_items is not None:
            self.sub_items = _dumps(sub_items)
        self.updated_at = int(time.time())

    @classmethod
    @with_read_session
    async def get_row(cls: Type[T_Personal], session: AsyncSession, user_id: str, bot_id: str, uid: str) -> Optional[T_Personal]:
        sql = select(cls).where(and_(cls.user_id == user_id, cls.bot_id == bot_id, cls.uid == uid))
        result = await session.execute(sql)
        return result.scalars().first()

    @classmethod
    @with_session
    async def save_row(cls: Type[T_Personal], session: AsyncSession, row: T_Personal) -> None:
        sql = select(cls).where(and_(cls.user_id == row.user_id, cls.bot_id == row.bot_id, cls.uid == row.uid))
        existing = (await session.execute(sql)).scalars().first()
        if existing:
            existing.weights = row.weights
            existing.sub_id = row.sub_id
            existing.sub_hash = row.sub_hash
            existing.sub_items = row.sub_items
            existing.updated_at = row.updated_at
            session.add(existing)
        else:
            session.add(row)

    @classmethod
    @with_session
    async def delete_row(cls: Type[T_Personal], session: AsyncSession, user_id: str, bot_id: str, uid: str) -> None:
        sql = select(cls).where(and_(cls.user_id == user_id, cls.bot_id == bot_id, cls.uid == uid))
        for row in (await session.execute(sql)).scalars().all():
            await session.delete(row)


class WavesGroupWeight(BaseBotIDModel, table=True):
    """群权重: 必须是公开订阅, 群内成员默认使用。"""

    __tablename__ = "WavesGroupWeight"
    __table_args__: Dict[str, Any] = {"extend_existing": True}

    group_id: str = Field(default="", title="群号", index=True)
    sub_id: str = Field(default="", title="订阅ID")
    sub_hash: str = Field(default="", title="订阅内容hash")
    sub_items: str = Field(default="{}", title="订阅内容")
    set_by: str = Field(default="", title="设置人")
    updated_at: int = Field(default=0, title="更新时间")

    def sub_map(self) -> Dict[str, str]:
        return _loads(self.sub_items)

    def set_items(self, items: Dict[str, str]):
        self.sub_items = _dumps(items)
        self.updated_at = int(time.time())

    @classmethod
    @with_read_session
    async def get_row(cls: Type[T_Group], session: AsyncSession, group_id: str, bot_id: str) -> Optional[T_Group]:
        sql = select(cls).where(and_(cls.group_id == group_id, cls.bot_id == bot_id))
        return (await session.execute(sql)).scalars().first()

    @classmethod
    @with_session
    async def save_row(cls: Type[T_Group], session: AsyncSession, row: T_Group) -> None:
        sql = select(cls).where(and_(cls.group_id == row.group_id, cls.bot_id == row.bot_id))
        existing = (await session.execute(sql)).scalars().first()
        if existing:
            existing.sub_id = row.sub_id
            existing.sub_hash = row.sub_hash
            existing.sub_items = row.sub_items
            existing.set_by = row.set_by
            existing.updated_at = row.updated_at
            session.add(existing)
        else:
            session.add(row)

    @classmethod
    @with_session
    async def delete_row(cls: Type[T_Group], session: AsyncSession, group_id: str, bot_id: str) -> None:
        sql = select(cls).where(and_(cls.group_id == group_id, cls.bot_id == bot_id))
        for row in (await session.execute(sql)).scalars().all():
            await session.delete(row)


async def ensure_tables() -> None:
    tables = [WavesCustomWeight.__table__, WavesGroupWeight.__table__]  # type: ignore[attr-defined]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=tables))
