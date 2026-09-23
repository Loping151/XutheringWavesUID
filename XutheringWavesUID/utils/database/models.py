from typing import Any, Dict, List, Type, TypeVar, Optional

from sqlmodel import Field, col, select
from sqlalchemy import null, delete, update
from sqlalchemy.sql import or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from gsuid_core.logger import logger
from gsuid_core.webconsole.mount_app import PageSchema, GsAdminModel, site
from gsuid_core.utils.database.startup import exec_list
from gsuid_core.utils.database.base_models import (
    Bind,
    User,
    BaseIDModel,
    BaseModel,
    with_session,
)

from .waves_subscribe import WavesSubscribe
from .waves_user_activity import WavesUserActivity
from .waves_user_sdk import WavesUserSdk
from .waves_gacha_cloud import WavesGachaCloud

from gsuid_core.server import on_core_start
from .auto_migrate import auto_add_missing_columns

exec_list.extend(
    [
        "ALTER TABLE WavesUserActivity ADD COLUMN bot_self_id TEXT DEFAULT ''",
        "ALTER TABLE WavesUser ADD COLUMN pgr_uid TEXT DEFAULT ''",
        "ALTER TABLE WavesUser ADD COLUMN platform TEXT DEFAULT ''",
        "ALTER TABLE WavesUser ADD COLUMN stamina_bg_value TEXT DEFAULT ''",
        "ALTER TABLE WavesUser ADD COLUMN hide_uid_self_value TEXT DEFAULT ''",
        'ALTER TABLE WavesUser ADD COLUMN bbs_sign_switch TEXT DEFAULT "off"',
        "ALTER TABLE WavesUser ADD COLUMN bat TEXT DEFAULT ''",
        "ALTER TABLE WavesUser ADD COLUMN did TEXT DEFAULT ''",
        "ALTER TABLE WavesUser ADD COLUMN game_id INTEGER DEFAULT 3 NOT NULL",
        'ALTER TABLE WavesUser ADD COLUMN is_login INTEGER DEFAULT 0 NOT NULL',
        "ALTER TABLE WavesBind ADD COLUMN pgr_uid TEXT DEFAULT ''",
        'ALTER TABLE WavesUser ADD COLUMN created_time INTEGER',
        'ALTER TABLE WavesUser ADD COLUMN last_used_time INTEGER',
        "ALTER TABLE WavesUser ADD COLUMN avatar_url TEXT DEFAULT ''",
        'ALTER TABLE WavesUserSdk ADD COLUMN bat_expires_at INTEGER',
        "UPDATE WavesUser SET uid = COALESCE(NULLIF(uid, ''), pgr_uid) WHERE IFNULL(uid, '') = '' AND IFNULL(pgr_uid, '') != ''",
        "UPDATE WavesUser SET game_id = 2 WHERE IFNULL(pgr_uid, '') != ''",
        "UPDATE WavesUser SET game_id = CASE WHEN IFNULL(game_id, 0) = 0 THEN 3 ELSE game_id END WHERE IFNULL(pgr_uid, '') = ''",
        "UPDATE WavesUser SET game_id = 3 WHERE game_id IS NULL",
        "ALTER TABLE WavesUser DROP COLUMN pgr_sign_switch",
        "ALTER TABLE WavesUser DROP COLUMN pgr_uid",
        "DELETE FROM WavesStaminaRecord WHERE id NOT IN (SELECT MAX(id) FROM WavesStaminaRecord GROUP BY user_id, bot_id, uid)",
        'CREATE TABLE IF NOT EXISTS "WavesGachaCloud" (id INTEGER NOT NULL, bot_id VARCHAR NOT NULL, user_id VARCHAR NOT NULL, uid VARCHAR NOT NULL, login_info VARCHAR NOT NULL, is_valid BOOLEAN NOT NULL, created_time INTEGER, last_used_time INTEGER, PRIMARY KEY (id))',
        'CREATE INDEX IF NOT EXISTS "ix_WavesGachaCloud_uid" ON "WavesGachaCloud" (uid)',
    ]
)

T_WavesBind = TypeVar("T_WavesBind", bound="WavesBind")
T_WavesUser = TypeVar("T_WavesUser", bound="WavesUser")
T_WavesStaminaRecord = TypeVar("T_WavesStaminaRecord", bound="WavesStaminaRecord")


class WavesBind(Bind, table=True):
    __table_args__: Dict[str, Any] = {"extend_existing": True}
    uid: Optional[str] = Field(default=None, title="鸣潮UID")
    pgr_uid: Optional[str] = Field(default=None, title="战双UID")

    @classmethod
    @with_session
    async def get_group_all_uid(cls: Type[T_WavesBind], session: AsyncSession, group_id: Optional[str] = None):
        """根据传入`group_id`获取该群号下所有绑定`uid`列表"""
        result = await session.scalars(select(cls).where(col(cls.group_id).contains(group_id)))
        return result.all()

    @classmethod
    @with_session
    async def get_binds_by_uid(
        cls: Type[T_WavesBind],
        session: AsyncSession,
        uid: str,
    ) -> List[T_WavesBind]:
        """根据鸣潮UID或战双UID查找绑定记录（含包含匹配）"""
        stmt = select(cls).where(
            or_(
                col(cls.uid).contains(uid),
                col(cls.pgr_uid).contains(uid),
            )
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def insert_waves_uid(
        cls: Type[T_WavesBind],
        user_id: str,
        bot_id: str,
        uid: str,
        group_id: Optional[str] = None,
        lenth_limit: Optional[int] = None,
        is_digit: Optional[bool] = True,
        game_name: Optional[str] = None,
    ) -> int:
        if lenth_limit:
            if len(uid) != lenth_limit:
                return -1

        if is_digit:
            if not uid.isdigit():
                return -3
        if not uid:
            return -1

        # 第一次绑定
        if not await cls.bind_exists(user_id, bot_id):
            code = await cls.insert_data(
                user_id=user_id,
                bot_id=bot_id,
                **{"uid": uid, "group_id": group_id},
            )
            return code

        result = await cls.select_data(user_id, bot_id)
        # await user_bind_cache.set(user_id, result)

        uid_list = result.uid.split("_") if result and result.uid else []
        uid_list = [i for i in uid_list if i] if uid_list else []

        # 已经绑定了该UID
        res = 0 if uid not in uid_list else -2

        # 强制更新库表
        force_update = False
        if uid not in uid_list:
            uid_list.append(uid)
            force_update = True
        new_uid = "_".join(uid_list)

        group_list = result.group_id.split("_") if result and result.group_id else []
        group_list = [i for i in group_list if i] if group_list else []

        if group_id and group_id not in group_list:
            group_list.append(group_id)
            force_update = True
        new_group_id = "_".join(group_list)

        if force_update:
            await cls.update_data(
                user_id=user_id,
                bot_id=bot_id,
                **{"uid": new_uid, "group_id": new_group_id},
            )
        return res

    @classmethod
    async def delete_uid(
        cls: Type[T_WavesBind],
        user_id: str,
        bot_id: str,
        uid: str,
        game_name: Optional[str] = None,
    ) -> int:
        """删除特征码并清理体力记录"""
        res = await super().delete_uid(
            user_id=user_id,
            bot_id=bot_id,
            uid=uid,
            game_name=game_name,
        )
        if res == 0:
            try:
                await WavesStaminaRecord.delete_by_uid(user_id, bot_id, uid)
            except Exception:
                logger.exception("[鸣潮·数据库] 删除特征码时清理体力记录失败")
        return res


class WavesUser(User, table=True):
    __table_args__: Dict[str, Any] = {"extend_existing": True}
    cookie: str = Field(default="", title="Cookie")
    uid: str = Field(default=None, title="游戏UID")
    platform: str = Field(default="", title="ck平台")
    stamina_bg_value: str = Field(default="", title="体力背景")
    hide_uid_self_value: str = Field(default="", title="隐藏UID")
    bbs_sign_switch: str = Field(default="off", title="自动社区签到")
    bat: str = Field(default="", title="bat")
    did: str = Field(default="", title="did")
    game_id: int = Field(default=3, title="GameID", nullable=False, sa_column_kwargs={"server_default": "3"})
    is_login: bool = Field(default=False, title="是否waves登录")
    created_time: Optional[int] = Field(default=None, title="创建时间")
    last_used_time: Optional[int] = Field(default=None, title="最后使用时间")
    avatar_url: str = Field(default="", title="头像URL")

    @classmethod
    @with_session
    async def mark_cookie_invalid(cls: Type[T_WavesUser], session: AsyncSession, uid: str, cookie: str, mark: str):
        sql = update(cls).where(col(cls.uid) == uid).where(col(cls.cookie) == cookie).values(status=mark)
        await session.execute(sql)
        return True

    @classmethod
    @with_session
    async def select_cookie(
        cls: Type[T_WavesUser],
        session: AsyncSession,
        uid: str,
        user_id: str,
        bot_id: str,
    ) -> Optional[str]:
        sql = select(cls).where(
            cls.user_id == user_id,
            cls.uid == uid,
            cls.bot_id == bot_id,
        )
        result = await session.execute(sql)
        data = result.scalars().all()
        return data[0].cookie if data else None

    @classmethod
    @with_session
    async def select_waves_user(
        cls: Type[T_WavesUser],
        session: AsyncSession,
        uid: str,
        user_id: str,
        bot_id: str,
        game_id: Optional[int] = None,
    ) -> Optional[T_WavesUser]:
        filters: List[Any] = [
            cls.user_id == user_id,
            cls.uid == uid,
            cls.bot_id == bot_id,
        ]
        if game_id is not None:
            filters.append(cls.game_id == game_id)
        sql = select(cls).where(*filters)
        result = await session.execute(sql)
        data = result.scalars().all()
        return data[0] if data else None

    @classmethod
    @with_session
    async def select_user_cookie_uids(
        cls: Type[T_WavesUser],
        session: AsyncSession,
        user_id: str,
    ) -> List[str]:
        sql = select(cls).where(
            and_(
                col(cls.user_id) == user_id,
                col(cls.cookie) != null(),
                col(cls.cookie) != "",
                or_(col(cls.status) == null(), col(cls.status) == ""),
            )
        )
        result = await session.execute(sql)
        data = result.scalars().all()
        return [i.uid for i in data] if data else []

    @classmethod
    @with_session
    async def select_data_by_cookie(
        cls: Type[T_WavesUser], session: AsyncSession, cookie: str
    ) -> Optional[T_WavesUser]:
        sql = select(cls).where(cls.cookie == cookie)
        result = await session.execute(sql)
        data = result.scalars().all()
        return data[0] if data else None

    @classmethod
    @with_session
    async def select_data_by_cookie_and_uid(
        cls: Type[T_WavesUser],
        session: AsyncSession,
        cookie: str,
        uid: str,
        game_id: Optional[int] = None,
    ) -> Optional[T_WavesUser]:
        filters = [cls.cookie == cookie, cls.uid == uid]
        if game_id is not None:
            filters.append(cls.game_id == game_id)
        sql = select(cls).where(*filters)
        result = await session.execute(sql)
        data = result.scalars().all()
        return data[0] if data else None

    @classmethod
    async def get_user_by_attr(
        cls: Type[T_WavesUser],
        user_id: str,
        bot_id: str,
        attr_key: str,
        attr_value: str,
        game_id: Optional[int] = None,
    ) -> Optional[Any]:
        user_list = await cls.select_data_list(user_id=user_id, bot_id=bot_id)
        if not user_list:
            return None
        for user in user_list:
            if getattr(user, attr_key) != attr_value:
                continue
            if game_id is not None and user.game_id not in (0, game_id):
                continue
            return user

    @classmethod
    @with_session
    async def get_waves_all_user(cls: Type[T_WavesUser], session: AsyncSession) -> List[T_WavesUser]:
        """获取所有有效用户"""
        sql = select(cls).where(
            and_(
                or_(col(cls.status) == null(), col(cls.status) == ""),
                col(cls.cookie) != null(),
                col(cls.cookie) != "",
            )
        )

        result = await session.execute(sql)
        data = result.scalars().all()
        return list(data)

    @classmethod
    @with_session
    async def delete_all_invalid_cookie(cls, session: AsyncSession):
        """删除所有无效缓存"""
        sql = delete(cls).where(
            or_(col(cls.status) == "无效", col(cls.cookie) == ""),
        )
        result = await session.execute(sql)
        return result.rowcount

    @classmethod
    @with_session
    async def delete_cookie(
        cls,
        session: AsyncSession,
        uid: str,
        user_id: str,
        bot_id: str,
        game_id: Optional[int] = None,
    ):
        # 先查询该用户的这个uid记录，检查is_login状态
        query_conditions = [
            col(cls.user_id) == user_id,
            col(cls.uid) == uid,
            col(cls.bot_id) == bot_id,
        ]
        if game_id is not None:
            query_conditions.append(col(cls.game_id) == game_id)

        query_sql = select(cls).where(and_(*query_conditions))
        query_result = await session.execute(query_sql)
        user_record = query_result.scalars().first()

        # 如果该记录存在且is_login为True，删除所有相同uid的记录
        if user_record and user_record.is_login:
            conditions = [col(cls.uid) == uid]
            if game_id is not None:
                conditions.append(col(cls.game_id) == game_id)
            sql = delete(cls).where(and_(*conditions))
        else:
            # 否则只删除当前用户的记录
            conditions = [
                col(cls.user_id) == user_id,
                col(cls.uid) == uid,
                col(cls.bot_id) == bot_id,
            ]
            if game_id is not None:
                conditions.append(col(cls.game_id) == game_id)
            sql = delete(cls).where(and_(*conditions))

        result = await session.execute(sql)
        return result.rowcount

    @classmethod
    @with_session
    async def update_token_by_login(
        cls,
        session: AsyncSession,
        uid: str,
        game_id: int,
        new_token: str,
        new_did: str,
    ):
        """根据uid和game_id查找WavesUser，如果is_login为True且在活跃天数内则更新cookie和did"""
        import time

        # 获取活跃天数配置
        from ...wutheringwaves_config import WutheringWavesConfig
        active_days = WutheringWavesConfig.get_config("ActiveUserDays").data
        current_time = int(time.time())
        threshold_time = current_time - (active_days * 24 * 60 * 60)

        sql = (
            update(cls)
            .where(
                and_(
                    col(cls.uid) == uid,
                    col(cls.game_id) == game_id,
                    col(cls.is_login) == True,
                    col(cls.last_used_time) != null(),
                    col(cls.last_used_time) >= threshold_time,
                )
            )
            .values(cookie=new_token, did=new_did)
        )
        result = await session.execute(sql)
        return result.rowcount

    @classmethod
    @with_session
    async def update_last_used_time(
        cls,
        session: AsyncSession,
        uid: str,
        user_id: str,
        bot_id: str,
        game_id: Optional[int] = None,
    ):
        """更新最后使用时间，如果创建时间为空则同时设置创建时间

        会更新所有具有相同 uid 和 cookie 的记录
        """
        import time

        current_time = int(time.time())

        # 先查询当前用户获取 cookie
        filters = [
            cls.user_id == user_id,
            cls.uid == uid,
            cls.bot_id == bot_id,
        ]
        if game_id is not None:
            filters.append(cls.game_id == game_id)

        result = await session.execute(select(cls).where(*filters))
        user = result.scalars().first()

        if user and user.cookie:
            # 更新所有具有相同 user_id 和 cookie 的记录
            all_users_result = await session.execute(
                select(cls).where(
                    and_(
                        col(cls.user_id) == user_id,
                        col(cls.cookie) == user.cookie,
                    )
                )
            )
            all_users = all_users_result.scalars().all()

            # 批量更新
            for u in all_users:
                u.last_used_time = current_time
                if u.created_time is None:
                    u.created_time = current_time

            return True
        return False

    @classmethod
    @with_session
    async def get_avatar_url(
        cls: Type[T_WavesUser],
        session: AsyncSession,
        user_id: str,
    ) -> str:
        """取该 user_id 名下最新一条非空头像 URL（按 last_used_time DESC）；都为空则返回空串"""
        sql = (
            select(cls.avatar_url)
            .where(
                and_(
                    col(cls.user_id) == user_id,
                    col(cls.avatar_url) != null(),
                    col(cls.avatar_url) != "",
                )
            )
            .order_by(col(cls.last_used_time).desc())
            .limit(1)
        )
        result = await session.execute(sql)
        return result.scalar() or ""

    @classmethod
    @with_session
    async def update_avatar_url(
        cls: Type[T_WavesUser],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        avatar_url: str,
    ) -> int:
        """非空时更新该 (user_id, bot_id) 下所有行的头像 URL"""
        if not avatar_url:
            return 0
        sql = (
            update(cls)
            .where(
                and_(
                    col(cls.user_id) == user_id,
                    col(cls.bot_id) == bot_id,
                )
            )
            .values(avatar_url=avatar_url)
        )
        result = await session.execute(sql)
        return result.rowcount

    @classmethod
    @with_session
    async def update_avatar_many(
        cls: Type[T_WavesUser],
        session: AsyncSession,
        rows: List[tuple[str, str, str]],
    ) -> None:
        for user_id, bot_id, avatar_url in rows:
            await session.execute(
                update(cls)
                .where(
                    and_(
                        col(cls.user_id) == user_id,
                        col(cls.bot_id) == bot_id,
                        or_(col(cls.avatar_url).is_(None), col(cls.avatar_url) != avatar_url),
                    )
                )
                .values(avatar_url=avatar_url)
            )

    @classmethod
    @with_session
    async def get_active_user_count(
        cls: Type[T_WavesUser],
        session: AsyncSession,
        active_days: int,
    ) -> int:
        """获取活跃用户数量

        Args:
            active_days: 活跃认定天数

        Returns:
            活跃用户数量
        """
        import time

        current_time = int(time.time())
        threshold_time = current_time - (active_days * 24 * 60 * 60)

        sql = select(cls).where(
            and_(
                or_(col(cls.status) == null(), col(cls.status) == ""),
                col(cls.cookie) != null(),
                col(cls.cookie) != "",
                col(cls.last_used_time) != null(),
                col(cls.last_used_time) >= threshold_time,
            )
        )

        result = await session.execute(sql)
        data = result.scalars().all()
        return len(data)


class WavesStaminaRecord(BaseModel, table=True):
    """体力查询记录表"""

    __tablename__ = "WavesStaminaRecord"
    __table_args__: Dict[str, Any] = {"extend_existing": True}

    uid: str = Field(default="", title="鸣潮UID")
    bot_self_id: str = Field(default="", title="BotSelfID")
    mr_query_time: Optional[int] = Field(default=None, title="体力查询时间")
    mr_value: Optional[int] = Field(default=None, title="结晶波片值")
    user_email: str = Field(default="", title="用户邮箱")
    email_last_try_time: Optional[int] = Field(default=None, title="邮件上次尝试发送时间")
    email_send_success: Optional[bool] = Field(default=None, title="邮箱发送成功")
    email_last_success_time: Optional[int] = Field(default=None, title="邮件上次发送成功时间")
    email_fail_count: int = Field(default=0, title="连续发送失败次数")
    stamina_push_switch: str = Field(default="off", title="体力推送开关")
    stamina_threshold: Optional[int] = Field(default=None, title="体力阈值")
    is_ck_valid: Optional[bool] = Field(default=None, title="CK是否有效")

    @classmethod
    @with_session
    async def upsert_stamina_query(
        cls: Type[T_WavesStaminaRecord],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        bot_self_id: str,
        uid: str,
        mr_query_time: int,
        mr_value: Optional[int],
        is_ck_valid: Optional[bool],
    ) -> bool:
        """更新或创建体力查询记录，仅更新查询时间/MR值/CK有效状态"""
        sql = select(cls).where(
            and_(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                cls.uid == uid,
            )
        )
        result = await session.execute(sql)
        record = result.scalars().first()

        if record:
            record.bot_self_id = bot_self_id
            record.mr_query_time = mr_query_time
            record.mr_value = mr_value
            record.is_ck_valid = is_ck_valid
            session.add(record)
            return True

        new_record = cls(
            user_id=user_id,
            bot_id=bot_id,
            bot_self_id=bot_self_id,
            uid=uid,
            mr_query_time=mr_query_time,
            mr_value=mr_value,
            is_ck_valid=is_ck_valid,
        )
        session.add(new_record)
        return True

    @classmethod
    @with_session
    async def update_ck_valid(
        cls: Type[T_WavesStaminaRecord],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        bot_self_id: str,
        uid: str,
        is_ck_valid: bool,
    ) -> bool:
        """更新或创建体力记录的 CK 有效状态"""
        sql = select(cls).where(
            and_(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                cls.uid == uid,
            )
        )
        result = await session.execute(sql)
        record = result.scalars().first()

        if record:
            record.bot_self_id = bot_self_id
            record.is_ck_valid = is_ck_valid
            session.add(record)
            return True

        session.add(
            cls(
                user_id=user_id,
                bot_id=bot_id,
                bot_self_id=bot_self_id,
                uid=uid,
                is_ck_valid=is_ck_valid,
            )
        )
        return True

    @classmethod
    @with_session
    async def delete_by_uid(
        cls: Type[T_WavesStaminaRecord],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
        uid: str,
    ) -> int:
        """删除指定用户/平台/UID的体力记录"""
        sql = delete(cls).where(
            and_(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
                cls.uid == uid,
            )
        )
        result = await session.execute(sql)
        return result.rowcount

    @classmethod
    @with_session
    async def delete_by_user(
        cls: Type[T_WavesStaminaRecord],
        session: AsyncSession,
        user_id: str,
        bot_id: str,
    ) -> int:
        """删除指定用户/平台的全部体力记录"""
        sql = delete(cls).where(
            and_(
                cls.user_id == user_id,
                cls.bot_id == bot_id,
            )
        )
        result = await session.execute(sql)
        return result.rowcount


T_WavesLangSettings = TypeVar("T_WavesLangSettings", bound="WavesLangSettings")


class WavesLangSettings(BaseIDModel, table=True):
    """用户语言设置表"""

    __tablename__ = "WavesLangSettings"
    __table_args__: Dict[str, Any] = {"extend_existing": True}

    user_id: str = Field(default="", title="账号", unique=True)
    lang: str = Field(default="", title="语言设置")

    @classmethod
    @with_session
    async def get_lang(
        cls: Type[T_WavesLangSettings],
        session: AsyncSession,
        user_id: str,
    ) -> str:
        """获取用户语言设置，默认返回空字符串（即 chs）"""
        result = await session.execute(
            select(cls).where(cls.user_id == user_id)
        )
        record = result.scalars().first()
        return record.lang if record else ""

    @classmethod
    @with_session
    async def set_lang(
        cls: Type[T_WavesLangSettings],
        session: AsyncSession,
        user_id: str,
        lang: str,
    ) -> None:
        """设置用户语言"""
        result = await session.execute(
            select(cls).where(cls.user_id == user_id)
        )
        record = result.scalars().first()
        if record:
            record.lang = lang
        else:
            session.add(cls(user_id=user_id, lang=lang))


@site.register_admin
class WavesBindAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(
        label="鸣潮绑定管理",
        icon="fa fa-users",
    )  # type: ignore

    # 配置管理模型
    model = WavesBind


@site.register_admin
class WavesUserAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(
        label="鸣潮用户管理",
        icon="fa fa-users",
    )  # type: ignore

    # 配置管理模型
    model = WavesUser


@site.register_admin
class WavesSubscribeAdmin(GsAdminModel):
    pk_name = "group_id"
    page_schema = PageSchema(
        label="鸣潮发送-群组绑定",
        icon="fa fa-link",
    )  # type: ignore

    # 配置管理模型
    model = WavesSubscribe


@site.register_admin
class WavesUserActivityAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(
        label="鸣潮用户活跃度",
        icon="fa fa-clock-o",
    )  # type: ignore

    # 配置管理模型
    model = WavesUserActivity


@site.register_admin
class WavesStaminaRecordAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(
        label="鸣潮体力推送",
        icon="fa fa-battery-full",
    )  # type: ignore

    # 配置管理模型
    model = WavesStaminaRecord


@site.register_admin
class WavesUserSdkAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(
        label="鸣潮launcher扩展",
        icon="fa fa-globe",
    )  # type: ignore

    model = WavesUserSdk


@site.register_admin
class WavesGachaCloudAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(
        label="鸣潮云登录",
        icon="fa fa-cloud",
    )  # type: ignore

    model = WavesGachaCloud


@on_core_start
async def _waves_auto_migrate():
    await auto_add_missing_columns(__name__, log_prefix="[鸣潮·补列]")
