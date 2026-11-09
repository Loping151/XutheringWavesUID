import json
import random
import string
import asyncio
import inspect
from typing import Any, Dict, List, Tuple, Union, Literal, Mapping, Optional

import aiohttp
from gsuid_core.logger import logger
from aiohttp import ClientTimeout, ContentTypeError

from .captcha import get_solver
from ..hint import WAVES_ERROR_CODE
from ..util import timed_async_cache
from .captcha.base import CaptchaResult
from ..error_reply import WAVES_CODE_999, WAVES_CODE_104
from .captcha.errors import CaptchaError
from ..constants import WAVES_GAME_ID
from ..database.models import WavesUser
from ..resource.RESOURCE_PATH import CACHE_PATH
from ...wutheringwaves_config import WutheringWavesConfig
from .request_util import (
    KURO_VERSION,
    KuroApiResp,
    get_base_header,
    get_community_header,
)

from .api import (
    BBS_LIST,
    LOGIN_URL,
    SERVER_ID,
    REFRESH_URL,
    ANN_LIST_URL,
    BASE_DATA_URL,
    GACHA_LOG_URL,
    GAME_DATA_URL,
    LOGIN_LOG_URL,
    MINE_V2_URL,
    REQUEST_TOKEN,
    ROLE_DATA_URL,
    ROLE_LIST_URL,
    SERVER_ID_NET,
    WEEK_LIST_URL,
    WIKI_HOME_URL,
    WIKI_TREE_URL,
    MONTH_LIST_URL,
    ANN_CONTENT_URL,
    BATCH_ROLE_COST,
    DATA_REVIEW_URL,
    OWNED_ROLE_INFO,
    PERIOD_LIST_URL,
    ROLE_DETAIL_URL,
    SLASH_INDEX_URL,
    TOWER_INDEX_URL,
    WIKI_DETAIL_URL,
    EXPLORE_DATA_URL,
    ONLINE_LIST_ROLE,
    SLASH_DETAIL_URL,
    TOWER_DETAIL_URL,
    MATRIX_INDEX_URL,
    MATRIX_DETAIL_URL,
    VERSION_LIST_URL,
    SKIN_DATA_URL,
    MOTOR_DATA_URL,
    CALABASH_DATA_URL,
    GACHA_NET_LOG_URL,
    MORE_ACTIVITY_URL,
    NET_SERVER_ID_MAP,
    CHALLENGE_DATA_URL,
    ONLINE_LIST_WEAPON,
    ONLINE_LIST_PHANTOM,
    ROLE_CULTIVATE_STATUS,
    SIGNIN_TASK_LIST_URL,
    SIGNIN_SURFACE_URL,
    WIKI_ENTRY_DETAIL_URL,
    CALCULATOR_REFRESH_DATA_URL,
    get_local_proxy_url,
    get_need_proxy_func,
)


def generate_random_jwt_token() -> str:
    chars = string.ascii_letters + string.digits
    payload = "".join(random.choice(chars) for _ in range(58))
    signature = "".join(random.choice(chars) for _ in range(43))
    return f"eyJhbGciOiJIUzI1NiJ9.{payload}.{signature}"


class WavesApi:
    ssl_verify = True
    ann_map = {}
    ann_list_data = []
    event_type = {"2": "资讯", "3": "公告", "1": "活动"}

    entry_detail_map = {}

    _sessions: Dict[str, aiohttp.ClientSession] = {}
    _session_lock = asyncio.Lock()

    def __init__(self):
        self.captcha_solver = get_solver()
        if self.captcha_solver:
            logger.success(f"[鸣潮·API] 使用过码器: {self.captcha_solver.get_name()}")

    async def get_session(self, proxy: Optional[str] = None) -> aiohttp.ClientSession:
        key = f"{proxy or 'no_proxy'}"

        if key in self._sessions and not self._sessions[key].closed:
            return self._sessions[key]

        async with self._session_lock:
            if key in self._sessions and not self._sessions[key].closed:
                return self._sessions[key]

            session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=self.ssl_verify),
            )

            self._sessions[key] = session
            return session

    # 与 utils.at_help.is_intl_uid 同一判定 (>=2e8 即国际服),
    # 区别仅在于这里是类方法、那边是模块级函数; 改动需保持两处一致。
    def is_net(self, roleId):
        _temp = int(roleId)
        return _temp >= 200000000

    def get_server_id(self, roleId, serverId: Optional[str] = None):
        if serverId:
            return serverId
        if self.is_net(roleId):
            return NET_SERVER_ID_MAP.get(int(roleId) // 100000000, SERVER_ID_NET)
        return SERVER_ID

    async def refresh_bat_token(self, waves_user: WavesUser):
        success, access_token = await self.get_request_token(waves_user.uid, waves_user.cookie, waves_user.did)
        if not success:
            return None  # bat refresh 失败, caller 据此区分成功/失败

        waves_user.bat = access_token
        await WavesUser.update_data_by_data(
            select_data={
                # "user_id": waves_user.user_id,
                # "bot_id": waves_user.bot_id,
                "uid": waves_user.uid,
                "game_id": waves_user.game_id,
            },
            update_data={"bat": access_token},
        )
        return waves_user

    async def refresh_bat_by_value(self, bat: str) -> Optional[str]:
        if not bat:
            return None
        waves_user = await WavesUser.select_data_by_bat(bat)
        if not waves_user or not await self.refresh_bat_token(waves_user):
            return None
        return waves_user.bat

    async def get_used_headers(
        self, cookie: str, uid: str, needToken=False, game_id: Optional[int] = WAVES_GAME_ID
    ) -> Dict[str, Any]:
        headers = {
            # "token": cookie,
            "did": "",
            "b-at": "",
        }
        if needToken:
            headers["token"] = cookie
        waves_user: Optional[WavesUser] = await WavesUser.select_data_by_cookie_and_uid(
            cookie=cookie,
            uid=uid,
            game_id=game_id,
        ) or await WavesUser.select_data_by_cookie(
            cookie=cookie,
            game_id=game_id,
        )

        if not waves_user:
            return headers

        headers["did"] = waves_user.did or ""
        headers["b-at"] = waves_user.bat or ""
        return headers

    async def get_ck_result(self, uid, user_id, bot_id) -> tuple[bool, Optional[str]]:
        try:
            ck = await self.get_self_waves_ck(uid, user_id, bot_id)
            if ck:
                return True, ck
            ck = await self.get_waves_random_cookie(uid, user_id)
            return False, ck
        except Exception:
            # 兜底
            return False, generate_random_jwt_token()

    async def check_self_login(
        self, uid: str, user_id: str, bot_id: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """检查 self CK 并透传错误。

        Returns: (cookie, error_msg)
          (cookie, None)    成功 (含维护中静默继续用旧 ck)
          (None, error)     ck 失效 / 网络异常 / 异常, 上层透传 error 给用户
          (None, None)      未绑定 cookie, 上层报 WAVES_CODE_102
        """
        try:
            waves_user = await WavesUser.select_waves_user(uid, user_id, bot_id, game_id=WAVES_GAME_ID)
            if not waves_user or not waves_user.cookie:
                return None, None
            if self.is_net(uid):
                return None, None  # 国际服走 launcher SDK 链路, 不走 self ck
            if waves_user.status == "无效":
                return None, "登录已过期，请重新登录"

            data = await self.login_log(uid, waves_user.cookie)
            if not data.success:
                await data.mark_cookie_invalid(uid, waves_user.cookie)
                return None, data.throw_msg() or "登录已过期"

            data = await self.refresh_data(uid, waves_user.cookie)
            if not data.success:
                if data.is_server_maintenance:
                    logger.warning(f"[鸣潮·API] 维护中 uid={uid}")
                    return None, data.throw_msg() or "服务器维护中，请稍后再试"
                if data.is_bat_token_invalid:
                    refreshed = await self.refresh_bat_token(waves_user)
                    if refreshed:
                        await WavesUser.update_last_used_time(uid, user_id, bot_id, game_id=WAVES_GAME_ID)
                        return refreshed.cookie, None
                    # bat 失效且 refresh 也失败: 原 cookie 可能仍有效, 不 mark_invalid
                    return None, "登录态过期，请重新登录"
                await data.mark_cookie_invalid(uid, waves_user.cookie)
                return None, data.throw_msg() or "登录已过期"

            await WavesUser.update_last_used_time(uid, user_id, bot_id, game_id=WAVES_GAME_ID)
            return waves_user.cookie, None
        except Exception as e:
            logger.exception(f"[鸣潮·登录检查] uid={uid}: {e}")
            return None, "网络异常，请稍后重试"

    async def get_self_waves_ck(self, uid: str, user_id: str, bot_id: str) -> Optional[str]:
        # 返回空串 表示绑定已失效
        waves_user = await WavesUser.select_waves_user(uid, user_id, bot_id, game_id=WAVES_GAME_ID)
        if not waves_user or not waves_user.cookie:
            return ""

        # 国际服账号走 launcher SDK auto_token，cookie 不是 kurobbs JWT，
        # 不能跑 login_log，否则会被错误地标记 status="无效"。SDK 链路自行处理凭据。
        # is_login=True 不能用作判别（kurobbs 登录流也会写 is_login=True）。
        if self.is_net(uid):
            return ""

        if waves_user.status == "无效":
            return ""

        data = await self.login_log(uid, waves_user.cookie)
        if not data.success:
            await data.mark_cookie_invalid(uid, waves_user.cookie)
            return ""

        data = await self.refresh_data(uid, waves_user.cookie)
        if not data.success:
            if data.is_server_maintenance:
                logger.warning(f"[鸣潮·API] 官方系统维护中，跳过刷新，UID: {uid}")
                await WavesUser.update_last_used_time(uid, user_id, bot_id, game_id=WAVES_GAME_ID)
                return waves_user.cookie
            if data.is_bat_token_invalid:
                if waves_user := await self.refresh_bat_token(waves_user):
                    # 更新最后使用时间
                    await WavesUser.update_last_used_time(uid, user_id, bot_id, game_id=WAVES_GAME_ID)
                    return waves_user.cookie
            else:
                await data.mark_cookie_invalid(uid, waves_user.cookie)
            return ""

        # 更新最后使用时间
        await WavesUser.update_last_used_time(uid, user_id, bot_id, game_id=WAVES_GAME_ID)
        return waves_user.cookie

    async def get_waves_random_cookie(self, uid: str, user_id: str) -> Optional[str]:
        if WutheringWavesConfig.get_config("WavesOnlySelfCk").data:
            return None

        # 公共 ck 随机抽一个可用的; login_log 失败不计次, refresh 最多深探 5 个 (耗配额)
        user_list = await WavesUser.get_waves_all_user()
        random.shuffle(user_list)
        deep_probe = 0
        for user in user_list:
            if user.game_id != WAVES_GAME_ID:
                continue
            if self.is_net(user.uid):
                # 国际服账号 cookie 是 launcher auto_token，作为 kurobbs JWT 用必失败
                continue
            if not await WavesUser.cookie_validate(user.uid):
                continue

            data = await self.login_log(user.uid, user.cookie)
            if not data.success:
                await data.mark_cookie_invalid(user.uid, user.cookie)
                continue

            if deep_probe >= 5:
                break
            deep_probe += 1

            data = await self.refresh_data(user.uid, user.cookie)
            if not data.success and data.is_bat_token_invalid:
                # bat 失效但 login 仍有效: 续 bat 后重探, 不算 cookie 失效
                await self.refresh_bat_token(user)
                data = await self.refresh_data(user.uid, user.cookie)
            if not data.success:
                # 维护 / 续 bat 后仍失败: cookie 未必失效, 不标失效
                if not (data.is_server_maintenance or data.is_bat_token_invalid):
                    await data.mark_cookie_invalid(user.uid, user.cookie)
                continue

            return user.cookie

    async def get_kuro_role_list(self, token: str, did: str, game_id: Union[int, str] = WAVES_GAME_ID):
        header = await get_base_header()
        header.update(
            {
                "token": token,
                "devCode": did,
            }
        )
        data = {"gameId": game_id}

        return await self._waves_request(ROLE_LIST_URL, "POST", header, data=data)

    async def get_daily_info(self, roleId: str, token: str, gameId: Union[str, int] = WAVES_GAME_ID):
        """每日"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId, needToken=True)
        header.update(used_headers)
        data = {
            "type": "2",
            "sizeType": "1",
            "gameId": gameId,
            "serverId": self.get_server_id(roleId),
            "roleId": roleId,
        }
        return await self._waves_request(
            GAME_DATA_URL,
            "POST",
            header,
            data=data,
        )

    async def refresh_data(self, roleId: str, token: str, serverId: Optional[str] = None):
        """刷新数据"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)
        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        return await self._waves_request(REFRESH_URL, "POST", header, data=data, renew_bat=False)

    async def login_log(self, roleId: str, token: str):
        """登录校验"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(
            {
                "token": token,
                "devCode": used_headers.get("did", ""),
                "version": KURO_VERSION,
            }
        )

        data = {}
        return await self._waves_request(LOGIN_LOG_URL, "POST", header, data=data)

    async def get_base_info(self, roleId: str, token: str, serverId: Optional[str] = None):
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)

        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        if WutheringWavesConfig.get_config("CacheEverything").data:
            try:
                info = await self._waves_request(BASE_DATA_URL, "POST", header, data=data)
                base_info_path = CACHE_PATH / "base_info"
                base_info_path.mkdir(parents=True, exist_ok=True)
                with open(base_info_path / f"{roleId}.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(info.model_dump(), ensure_ascii=False, indent=4))
            except Exception as e:
                logger.error(f"[鸣潮·API] 获取基础信息失败，返回缓存数据 {e}")
                with open(CACHE_PATH / "base_info" / f"{roleId}.json", "r", encoding="utf-8") as f:
                    info = json.load(f)
                info = KuroApiResp(**info)
        else:
            info = await self._waves_request(BASE_DATA_URL, "POST", header, data=data)
        return info

    async def is_hidden_to_guest(self, roleId: str, token: str) -> bool:
        info = await self.get_base_info(roleId, token)
        return info.success and isinstance(info.data, dict) and info.data.get("showToGuest") is False

    async def get_sign_in_init(
        self, roleId: str, token: str, gameId: int = WAVES_GAME_ID, serverId: Optional[str] = None
    ):
        """签到日历 initSignInV2"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(
            cookie=token, uid=roleId, needToken=True, game_id=gameId
        )
        header.update(used_headers)
        header["devcode"] = ""
        data = {
            "gameId": gameId,
            "serverId": serverId or self.get_server_id(roleId),
            "roleId": roleId,
        }
        return await self._waves_request(SIGNIN_TASK_LIST_URL, "POST", header, data=data)

    async def get_sign_in_surface(self, token: str, gameId: int = WAVES_GAME_ID):
        """签到皮肤资源 signIn/surface"""
        header = await get_base_header()
        header["token"] = token
        data = {"gameId": gameId}
        return await self._waves_request(SIGNIN_SURFACE_URL, "POST", header, data=data)

    async def get_role_info(self, roleId: str, token: str, serverId: Optional[str] = None):
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)

        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        if WutheringWavesConfig.get_config("CacheEverything").data:
            try:
                role_info = await self._waves_request(ROLE_DATA_URL, "POST", header, data=data)
                role_info_path = CACHE_PATH / "role_info"
                role_info_path.mkdir(parents=True, exist_ok=True)
                with open(role_info_path / f"{roleId}.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(role_info.model_dump(), ensure_ascii=False, indent=4))
            except Exception as e:
                logger.error(f"[鸣潮·API] 获取基础信息失败，返回缓存数据 {e}")
                with open(CACHE_PATH / "role_info" / f"{roleId}.json", "r", encoding="utf-8") as f:
                    role_info = json.load(f)
                role_info = KuroApiResp(**role_info)
        else:
            role_info = await self._waves_request(ROLE_DATA_URL, "POST", header, data=data)
        return role_info

    async def get_tree(self):
        header = await get_community_header()
        header.update({"wiki_type": "9"})
        data = {"devcode": ""}
        return await self._waves_request(WIKI_TREE_URL, "POST", header, data=data)

    async def get_wiki(self, catalogueId: str):
        header = await get_community_header()
        header.update({"wiki_type": "9"})
        data = {"catalogueId": catalogueId, "limit": 1000}
        return await self._waves_request(WIKI_DETAIL_URL, "POST", header, data=data)

    async def get_role_detail_info(self, charId: str, roleId: str, token: str, serverId: Optional[str] = None):
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)

        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
            "channelId": "19",
            "countryCode": "1",
            "id": charId,
        }
        if WutheringWavesConfig.get_config("CacheEverything").data:
            try:
                role_detail = await self._waves_request(ROLE_DETAIL_URL, "POST", header, data=data)
                role_detail_path = CACHE_PATH / "role_detail"
                role_detail_path.mkdir(parents=True, exist_ok=True)
                with open(role_detail_path / f"{roleId}_{charId}.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(role_detail.model_dump(), ensure_ascii=False, indent=4))
            except Exception as e:
                logger.error(f"[鸣潮·API] 获取角色详情失败，返回缓存数据 {e}")
                with open(CACHE_PATH / "role_detail" / f"{roleId}_{charId}.json", "r", encoding="utf-8") as f:
                    role_detail = json.load(f)
                role_detail = KuroApiResp(**role_detail)
        else:
            role_detail = await self._waves_request(ROLE_DETAIL_URL, "POST", header, data=data)
        return role_detail

    async def get_calabash_data(self, roleId: str, token: str, serverId: Optional[str] = None):
        """数据坞"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)

        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        if WutheringWavesConfig.get_config("CacheEverything").data:
            try:
                calabash_data = await self._waves_request(CALABASH_DATA_URL, "POST", header, data=data)
                calabash_data_path = CACHE_PATH / "calabash_data"
                calabash_data_path.mkdir(parents=True, exist_ok=True)
                with open(calabash_data_path / f"{roleId}.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(calabash_data.model_dump(), ensure_ascii=False, indent=4))
            except Exception as e:
                logger.error(f"[鸣潮·API] 获取数据坞失败，返回缓存数据 {e}")
                with open(CACHE_PATH / "calabash_data" / f"{roleId}.json", "r", encoding="utf-8") as f:
                    calabash_data = json.load(f)
                calabash_data = KuroApiResp(**calabash_data)
        else:
            calabash_data = await self._waves_request(CALABASH_DATA_URL, "POST", header, data=data)
        return calabash_data

    async def get_skin_data(self, roleId: str, token: str, serverId: Optional[str] = None):
        """服饰"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)

        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        if WutheringWavesConfig.get_config("CacheEverything").data:
            try:
                skin_data = await self._waves_request(SKIN_DATA_URL, "POST", header, data=data)
                skin_data_path = CACHE_PATH / "skin_data"
                skin_data_path.mkdir(parents=True, exist_ok=True)
                with open(skin_data_path / f"{roleId}.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(skin_data.model_dump(), ensure_ascii=False, indent=4))
            except Exception as e:
                logger.error(f"[鸣潮·API] 获取服饰失败，返回缓存数据 {e}")
                with open(CACHE_PATH / "skin_data" / f"{roleId}.json", "r", encoding="utf-8") as f:
                    skin_data = json.load(f)
                skin_data = KuroApiResp(**skin_data)
        else:
            skin_data = await self._waves_request(SKIN_DATA_URL, "POST", header, data=data)
        return skin_data

    async def get_motor_data(self, roleId: str, token: str, serverId: Optional[str] = None):
        """科考摩托"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)

        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        if WutheringWavesConfig.get_config("CacheEverything").data:
            try:
                motor_data = await self._waves_request(MOTOR_DATA_URL, "POST", header, data=data)
                motor_data_path = CACHE_PATH / "motor_data"
                motor_data_path.mkdir(parents=True, exist_ok=True)
                with open(motor_data_path / f"{roleId}.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(motor_data.model_dump(), ensure_ascii=False, indent=4))
            except Exception as e:
                logger.error(f"[鸣潮·API] 获取摩托失败，返回缓存数据 {e}")
                with open(CACHE_PATH / "motor_data" / f"{roleId}.json", "r", encoding="utf-8") as f:
                    motor_data = json.load(f)
                motor_data = KuroApiResp(**motor_data)
        else:
            motor_data = await self._waves_request(MOTOR_DATA_URL, "POST", header, data=data)
        return motor_data

    async def get_explore_data(
        self,
        roleId: str,
        token: str,
        serverId: Optional[str] = None,
        countryCode: str = "1",
    ):
        """探索度"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)

        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
            "countryCode": countryCode,
        }
        if WutheringWavesConfig.get_config("CacheEverything").data:
            try:
                explore_data = await self._waves_request(EXPLORE_DATA_URL, "POST", header, data=data)
                explore_data_path = CACHE_PATH / "explore_data"
                explore_data_path.mkdir(parents=True, exist_ok=True)
                with open(explore_data_path / f"{roleId}.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(explore_data.model_dump(), ensure_ascii=False, indent=4))
            except Exception as e:
                logger.error(f"[鸣潮·API] 获取探索度失败，返回缓存数据 {e}")
                with open(CACHE_PATH / "explore_data" / f"{roleId}.json", "r", encoding="utf-8") as f:
                    explore_data = json.load(f)
                explore_data = KuroApiResp(**explore_data)
        else:
            explore_data = await self._waves_request(EXPLORE_DATA_URL, "POST", header, data=data)
        return explore_data

    async def get_challenge_data(self, roleId: str, token: str, serverId: Optional[str] = None):
        """全息"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)

        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        if WutheringWavesConfig.get_config("CacheEverything").data:
            try:
                challenge_data = await self._waves_request(CHALLENGE_DATA_URL, "POST", header, data=data)
                challenge_data_path = CACHE_PATH / "challenge_data"
                challenge_data_path.mkdir(parents=True, exist_ok=True)
                with open(challenge_data_path / f"{roleId}.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(challenge_data.model_dump(), ensure_ascii=False, indent=4))
            except Exception as e:
                logger.error(f"[鸣潮·API] 获取全息数据失败，返回缓存数据 {e}")
                with open(CACHE_PATH / "challenge_data" / f"{roleId}.json", "r", encoding="utf-8") as f:
                    challenge_data = json.load(f)
                challenge_data = KuroApiResp(**challenge_data)
        else:
            challenge_data = await self._waves_request(CHALLENGE_DATA_URL, "POST", header, data=data)
        return challenge_data

    async def get_abyss_data(self, roleId: str, token: str, serverId: Optional[str] = None):
        """深渊"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)
        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        if WutheringWavesConfig.get_config("CacheEverything").data:
            try:
                abyss_data = await self._waves_request(TOWER_DETAIL_URL, "POST", header, data=data)
                abyss_data_path = CACHE_PATH / "abyss_data"
                abyss_data_path.mkdir(parents=True, exist_ok=True)
                with open(abyss_data_path / f"{roleId}.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(abyss_data.model_dump(), ensure_ascii=False, indent=4))
            except Exception as e:
                logger.error(f"[鸣潮·API] 获取深渊数据失败，返回缓存数据 {e}")
                with open(CACHE_PATH / "abyss_data" / f"{roleId}.json", "r", encoding="utf-8") as f:
                    abyss_data = json.load(f)
                abyss_data = KuroApiResp(**abyss_data)
        else:
            abyss_data = await self._waves_request(TOWER_DETAIL_URL, "POST", header, data=data)
        return abyss_data

    async def get_abyss_index(self, roleId: str, token: str, serverId: Optional[str] = None):
        """深渊"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)

        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        if WutheringWavesConfig.get_config("CacheEverything").data:
            try:
                abyss_index = await self._waves_request(TOWER_INDEX_URL, "POST", header, data=data)
                abyss_index_path = CACHE_PATH / "abyss_index"
                abyss_index_path.mkdir(parents=True, exist_ok=True)
                with open(abyss_index_path / f"{roleId}.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(abyss_index.model_dump(), ensure_ascii=False, indent=4))
            except Exception as e:
                logger.error(f"[鸣潮·API] 获取深渊索引失败，返回缓存数据 {e}")
                with open(CACHE_PATH / "abyss_index" / f"{roleId}.json", "r", encoding="utf-8") as f:
                    abyss_index = json.load(f)
                abyss_index = KuroApiResp(**abyss_index)
        else:
            abyss_index = await self._waves_request(TOWER_INDEX_URL, "POST", header, data=data)
        return abyss_index

    async def get_slash_index(self, roleId: str, token: str, serverId: Optional[str] = None):
        """冥海"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)

        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        if WutheringWavesConfig.get_config("CacheEverything").data:
            try:
                slash_index = await self._waves_request(SLASH_INDEX_URL, "POST", header, data=data)
                slash_index_path = CACHE_PATH / "slash_index"
                slash_index_path.mkdir(parents=True, exist_ok=True)
                with open(slash_index_path / f"{roleId}.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(slash_index.model_dump(), ensure_ascii=False, indent=4))
            except Exception as e:
                logger.error(f"[鸣潮·API] 获取冥海索引失败，返回缓存数据 {e}")
                with open(CACHE_PATH / "slash_index" / f"{roleId}.json", "r", encoding="utf-8") as f:
                    slash_index = json.load(f)
                slash_index = KuroApiResp(**slash_index)
        else:
            slash_index = await self._waves_request(SLASH_INDEX_URL, "POST", header, data=data)
        return slash_index

    async def get_slash_detail(self, roleId: str, token: str, serverId: Optional[str] = None):
        """冥海"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)

        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        if WutheringWavesConfig.get_config("CacheEverything").data:
            try:
                slash_detail = await self._waves_request(SLASH_DETAIL_URL, "POST", header, data=data)
                slash_detail_path = CACHE_PATH / "slash_detail"
                slash_detail_path.mkdir(parents=True, exist_ok=True)
                with open(slash_detail_path / f"{roleId}.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(slash_detail.model_dump(), ensure_ascii=False, indent=4))
            except Exception as e:
                logger.error(f"[鸣潮·API] 获取冥海详情失败，返回缓存数据 {e}")
                with open(CACHE_PATH / "slash_detail" / f"{roleId}.json", "r", encoding="utf-8") as f:
                    slash_detail = json.load(f)
                slash_detail = KuroApiResp(**slash_detail)
        else:
            slash_detail = await self._waves_request(SLASH_DETAIL_URL, "POST", header, data=data)
        return slash_detail

    async def get_matrix_index(self, roleId: str, token: str, serverId: Optional[str] = None):
        """终焉矩阵 (公开)"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)

        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        if WutheringWavesConfig.get_config("CacheEverything").data:
            try:
                matrix_index = await self._waves_request(MATRIX_INDEX_URL, "POST", header, data=data)
                matrix_index_path = CACHE_PATH / "matrix_index"
                matrix_index_path.mkdir(parents=True, exist_ok=True)
                with open(matrix_index_path / f"{roleId}.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(matrix_index.model_dump(), ensure_ascii=False, indent=4))
            except Exception as e:
                logger.error(f"[鸣潮·API] 获取矩阵索引失败，返回缓存数据 {e}")
                with open(CACHE_PATH / "matrix_index" / f"{roleId}.json", "r", encoding="utf-8") as f:
                    matrix_index = json.load(f)
                matrix_index = KuroApiResp(**matrix_index)
        else:
            matrix_index = await self._waves_request(MATRIX_INDEX_URL, "POST", header, data=data)
        return matrix_index

    async def get_matrix_detail(self, roleId: str, token: str, serverId: Optional[str] = None):
        """终焉矩阵 (详情)"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)

        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        if WutheringWavesConfig.get_config("CacheEverything").data:
            try:
                matrix_detail = await self._waves_request(MATRIX_DETAIL_URL, "POST", header, data=data)
                matrix_detail_path = CACHE_PATH / "matrix_detail"
                matrix_detail_path.mkdir(parents=True, exist_ok=True)
                with open(matrix_detail_path / f"{roleId}.json", "w", encoding="utf-8") as f:
                    f.write(json.dumps(matrix_detail.model_dump(), ensure_ascii=False, indent=4))
            except Exception as e:
                logger.error(f"[鸣潮·API] 获取矩阵详情失败，返回缓存数据 {e}")
                with open(CACHE_PATH / "matrix_detail" / f"{roleId}.json", "r", encoding="utf-8") as f:
                    matrix_detail = json.load(f)
                matrix_detail = KuroApiResp(**matrix_detail)
        else:
            matrix_detail = await self._waves_request(MATRIX_DETAIL_URL, "POST", header, data=data)
        return matrix_detail

    async def get_more_activity(self, roleId: str, token: str, serverId: Optional[str] = None):
        """浸梦海床+激斗！向着荣耀之丘"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId)
        header.update(used_headers)

        data = {
            "gameId": WAVES_GAME_ID,
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        return await self._waves_request(MORE_ACTIVITY_URL, "POST", header, data=data)

    async def get_request_token(
        self, roleId: str, token: str, did: str, serverId: Optional[str] = None
    ) -> tuple[bool, str]:
        """请求token"""
        header = await get_base_header()
        header.update(
            {
                "token": token,
                "did": did,
                "b-at": "",
            }
        )
        data = {
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        raw_data = await self._waves_request(REQUEST_TOKEN, "POST", header, data=data)
        if raw_data.success and isinstance(raw_data.data, dict):
            if accessToken := raw_data.data.get("accessToken", ""):
                return True, accessToken

        return False, ""

    async def calculator_refresh_data(
        self,
        roleId: str,
        token: str,
        serverId: Optional[str] = None,
    ):
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId, needToken=True)
        header.update(used_headers)

        data = {
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        return await self._waves_request(CALCULATOR_REFRESH_DATA_URL, "POST", header, data=data)

    @timed_async_cache(
        86400,
        lambda x: x.success and isinstance(x.data, (dict, list)),
        key=lambda self, token: "online_list_role",
    )
    async def get_online_list_role(self, token: str):
        """所有的角色列表"""
        header = await get_base_header()
        header.update({"token": token})
        data = {}
        return await self._waves_request(ONLINE_LIST_ROLE, "POST", header, data=data)

    @timed_async_cache(
        86400,
        lambda x: x.success and isinstance(x.data, (dict, list)),
        key=lambda self, token: "online_list_weapon",
    )
    async def get_online_list_weapon(self, token: str):
        """所有的武器列表"""
        header = await get_base_header()
        header.update({"token": token})
        data = {}
        return await self._waves_request(ONLINE_LIST_WEAPON, "POST", header, data=data)

    @timed_async_cache(
        86400,
        lambda x: x.success and isinstance(x.data, (dict, list)),
        key=lambda self, token: "online_list_phantom",
    )
    async def get_online_list_phantom(self, token: str):
        """所有的声骸列表"""
        header = await get_base_header()
        header.update({"token": token})
        data = {}
        return await self._waves_request(ONLINE_LIST_PHANTOM, "POST", header, data=data)

    async def get_owned_role_info(
        self,
        roleId: str,
        token: str,
        userId: Optional[str] = None,
        serverId: Optional[str] = None,
    ):
        """已拥有角色信息（包含等级）"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId, needToken=True)
        header.update(used_headers)
        data = {
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
        }
        if userId:
            data["userId"] = userId
        return await self._waves_request(OWNED_ROLE_INFO, "POST", header, data=data)

    async def get_develop_role_cultivate_status(
        self,
        roleId: str,
        token: str,
        char_ids: List[str],
        serverId: Optional[str] = None,
    ):
        """角色培养状态"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId, needToken=True)
        header.update(used_headers)
        data = {
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
            "ids": ",".join(char_ids),
        }
        return await self._waves_request(ROLE_CULTIVATE_STATUS, "POST", header, data=data)

    async def get_batch_role_cost(
        self,
        roleId: str,
        token: str,
        content: List[Any],
        serverId: Optional[str] = None,
    ):
        """角色培养成本"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId, needToken=True)
        header.update(used_headers)
        data = {
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
            "content": json.dumps(content),
        }
        return await self._waves_request(BATCH_ROLE_COST, "POST", header, data=data)

    async def get_period_list(
        self,
        roleId: str,
        token: str,
    ):
        """资源简报列表"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId, needToken=True)
        header.update(used_headers)
        return await self._waves_request(PERIOD_LIST_URL, "GET", header)

    async def get_period_detail(
        self,
        type: Literal["month", "week", "version"],
        period: Union[str, int],
        roleId: str,
        token: str,
        serverId: Optional[str] = None,
    ):
        """资源简报详情"""
        header = await get_base_header()
        used_headers = await self.get_used_headers(cookie=token, uid=roleId, needToken=True)
        header.update(used_headers)
        data = {
            "serverId": self.get_server_id(roleId, serverId),
            "roleId": roleId,
            "period": period,
        }
        if type == "month":
            url = MONTH_LIST_URL
        elif type == "week":
            url = WEEK_LIST_URL
        elif type == "version":
            url = VERSION_LIST_URL
        return await self._waves_request(url, "POST", header, data=data)

    async def get_gacha_log(
        self,
        cardPoolType: str,
        recordId: str,
        roleId: str,
        serverId: Optional[str] = None,
    ):
        """抽卡记录"""
        header = {"Content-Type": "application/json;charset=UTF-8"}
        data = {
            "playerId": roleId,
            "cardPoolType": cardPoolType,
            "serverId": self.get_server_id(roleId, serverId),
            "languageCode": "zh-Hans",
            "recordId": recordId,
        }
        url = GACHA_NET_LOG_URL if self.is_net(roleId) else GACHA_LOG_URL
        return await self._waves_request(url, "POST", header, json_data=data)

    async def get_ann_list_by_type(self, eventType: str = "", pageSize: Optional[int] = None):
        """获取公告列表"""
        data: Dict[str, Any] = {"gameId": WAVES_GAME_ID}
        if eventType:
            data.update({"eventType": eventType})
        if pageSize:
            data.update({"pageSize": pageSize})
        headers = await get_community_header()
        return await self._waves_request(ANN_LIST_URL, "POST", headers, data=data)

    async def get_ann_detail(self, post_id: str):
        """获取公告详情"""
        if post_id in self.ann_map:
            return self.ann_map[post_id]

        headers = await get_community_header()
        headers.update({"token": "", "devcode": ""})
        data = {"isOnlyPublisher": 1, "postId": post_id, "showOrderType": 2}
        res = await self._waves_request(ANN_CONTENT_URL, "POST", headers, data=data)
        if res.success:
            raw_data = res.model_dump()
            if "headCodeUrl" in raw_data["data"]:
                raw_data["data"]["postDetail"]["headCodeUrl"] = raw_data["data"]["headCodeUrl"]
            self.ann_map[post_id] = raw_data["data"]["postDetail"]
            return raw_data["data"]["postDetail"]
        return {}

    async def get_ann_list(self, is_cache: bool = False):
        """获取公告列表"""
        if is_cache and self.ann_list_data:
            return self.ann_list_data

        self.ann_list_data = []
        for _event in self.event_type.keys():
            res = await self.get_ann_list_by_type(eventType=_event, pageSize=9)
            if res.success:
                raw_data = res.model_dump()
                value = [{**x, "id": int(x["id"])} for x in raw_data["data"]["list"]]
                self.ann_list_data.extend(value)

        bbs_sub = WutheringWavesConfig.get_config("WavesAnnBBSSub").data
        for bbs_id in bbs_sub:
            res = await self.get_bbs_list(bbs_id, pageIndex=1, pageSize=9)
            if not res.success:
                continue
            raw_data = res.model_dump()
            value = [{**x, "id": int(x["postId"])} for x in raw_data["data"]["postList"]]
            self.ann_list_data.extend(value)

        res = await self.get_bbs_list("10011001", pageIndex=1, pageSize=20)
        if res.success:
            raw_data = res.model_dump()
            post_list = [x for x in raw_data["data"]["postList"] if x.get("gameId") == WAVES_GAME_ID]
            post_list.sort(key=lambda x: x.get("showTime", 0), reverse=True)
            value = [{**x, "id": int(x["postId"]), "eventType": 4} for x in post_list[:9]]
            self.ann_list_data.extend(value)

        return self.ann_list_data

    async def get_bbs_list(
        self,
        otherUserId: Union[int, str],
        pageIndex: int = 1,
        pageSize: int = 10,
    ):
        """获取BBS列表"""
        headers = await get_community_header()
        headers.update({"token": "", "devCode": ""})
        data = {
            "searchType": 1,
            "type": 2,
            "otherUserId": otherUserId,
            "pageIndex": pageIndex,
            "pageSize": pageSize,
        }
        res = await self._waves_request(BBS_LIST, "POST", headers, data=data)
        return res

    async def get_user_mine_v2(self, token: str):
        """获取用户信息（库洛币等）"""
        headers = await get_base_header()
        headers.update({"token": token})
        data = {}
        res = await self._waves_request(MINE_V2_URL, "POST", headers, data=data)
        return res

    async def get_data_review(self, token: str):
        """获取签到数据回顾"""
        headers = await get_base_header()
        headers.update({"token": token, "version": KURO_VERSION})
        return await self._waves_request(DATA_REVIEW_URL, "GET", headers)

    async def get_wiki_home(self):
        """获取wiki首页"""
        headers = await get_community_header()
        headers.update({"wiki_type": "9"})
        res = await self._waves_request(WIKI_HOME_URL, "POST", headers)
        if res.success:
            return res.model_dump()
        return {}

    async def get_entry_detail(self, entry_id: str):
        """获取entry详情"""
        if entry_id in self.entry_detail_map:
            return self.entry_detail_map[entry_id]

        headers = await get_community_header()
        headers.update({"wiki_type": "9"})
        data = {"id": entry_id}
        res = await self._waves_request(WIKI_ENTRY_DETAIL_URL, "POST", headers, data=data)
        if res.success:
            raw_data = res.model_dump()
            self.entry_detail_map[entry_id] = raw_data
            return raw_data
        return {}

    async def login(self, mobile: Union[int, str], code: str, did: str):
        """登录
        Args:
            mobile (Union[int, str]): 手机号
            code (str): 验证码
            did (str): 设备ID
        """
        header = await get_base_header()
        data = {
            "mobile": mobile,
            "code": code,
            "devCode": did,
        }
        return await self._waves_request(LOGIN_URL, "POST", header, data=data)

    async def _waves_request(
        self,
        url: str,
        method: Literal["GET", "POST"] = "GET",
        header: Optional[Mapping[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        renew_bat: bool = True,
    ) -> KuroApiResp[Union[str, Dict[str, Any], List[Any]]]:
        if header is None:
            header = await get_base_header()

        proxy_func = get_need_proxy_func()
        if inspect.stack()[1].function in proxy_func or "all" in proxy_func:
            proxy_url = get_local_proxy_url()
        else:
            proxy_url = None

        async def do_request(req_data, client_session: aiohttp.ClientSession) -> KuroApiResp[Any]:
            async with client_session.request(
                method,
                url=url,
                headers=header,
                params=params,
                json=json_data,
                data=req_data,
                proxy=proxy_url,
                timeout=ClientTimeout(total=10),
            ) as resp:
                try:
                    raw_data = await resp.json()
                except ContentTypeError:
                    _raw_data = await resp.text()
                    raw_data = {"code": WAVES_CODE_999, "data": _raw_data}

                if isinstance(raw_data, dict):
                    try:
                        raw_data["data"] = json.loads(raw_data.get("data", ""))
                    except Exception:
                        pass

                logger.debug(f"[鸣潮·API] url:[{url}] params:[{params}] headers:[{header}] data:[{req_data}] raw_data:{raw_data}")
                # 统一解析为 KuroApiResp
                return KuroApiResp[Any].model_validate(raw_data)

        async def solve_captcha():
            if not self.captcha_solver:
                return
            for _ in range(max_retries):
                try:
                    return await self.captcha_solver.solve()
                except CaptchaError as e:
                    logger.error(f"[鸣潮·API] url:[{url}] 验证码破解失败: {e}")

            return {"code": WAVES_CODE_999, "data": "验证码破解失败"}

        for attempt in range(max_retries):
            try:
                client = await self.get_session(proxy=proxy_url)
                if not client:
                    logger.warning(f"[鸣潮·API] url:[{url}] 获取session失败")
                    continue

                response = await do_request(data, client)
                if (
                    renew_bat
                    and response.is_bat_token_invalid
                    and (bat := await self.refresh_bat_by_value(header.get("b-at", "")))
                ):
                    header = {**header, "b-at": bat}
                    response = await do_request(data, client)

                res_data = response.data or {}
                if self.captcha_solver and isinstance(res_data, dict) and res_data.get("geeTest") is True:
                    seccode_data = await solve_captcha()
                    if isinstance(seccode_data, CaptchaResult):
                        seccode_data = seccode_data.model_dump_json()

                    if isinstance(seccode_data, dict):
                        seccode_data = json.dumps(seccode_data)

                    # 重试数据准备
                    retry_data = data.copy() if data else {}
                    retry_data["geeTestData"] = seccode_data
                    return await do_request(retry_data, client)
                elif isinstance(res_data, dict) and res_data.get("geeTest") is True:
                    logger.warning(f"[鸣潮·API] url:[{url}] 触发验证码！")
                    return KuroApiResp(code=WAVES_CODE_104, msg=WAVES_ERROR_CODE[WAVES_CODE_104], data=res_data)
                    #return {"code": WAVES_CODE_999, "msg": "验证码破解失败"}

                return response

            except aiohttp.ClientError as e:
                logger.warning(f"[鸣潮·API] url:[{url}] 网络请求失败, 尝试次数 {attempt + 1}", e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
            except Exception as e:
                logger.warning(f"[鸣潮·API] url:[{url}] 发生未知错误, 尝试次数 {attempt + 1}", e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)

        raise TypeError("请求服务器失败，已达最大重试次数")
