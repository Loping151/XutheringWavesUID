import time
from typing import Union
from pathlib import Path
from datetime import datetime, timezone, timedelta

from PIL import Image

from gsuid_core.logger import logger
from gsuid_core.models import Event

from ..utils.hint import error_reply
from ..utils.at_help import safe_sender_avatar
from ..utils.util import hide_uid, get_hide_uid_pref
from ..utils.waves_api import waves_api
from ..utils.error_reply import WAVES_CODE_102
from ..utils.api.model import MatrixDetail, AccountBaseInfo
from ..utils.api.wwapi import MatrixDetailRequest, MatrixTeamDetail
from ..utils.avatar_match import match_role_icons_to_char_ids
from ..utils.char_info_utils import get_all_roleid_detail_info, get_rover_detail_map, lookup_chain_with_rover
from ..utils.player_store import write_player_json
from ..utils.queues.const import QUEUE_MATRIX_RECORD
from ..utils.queues.queues import push_item
from ..utils.resource.RESOURCE_PATH import PLAYER_PATH, MATRIX_PATH, waves_templates
from ..utils.image import pil_to_b64, get_waves_bg, get_event_avatar, CHAIN_COLOR, get_skill_branch_emblem_b64
from ._colors import get_matrix_score_class
from .period import get_matrix_period_number
from .draw_matrix_card_pil import (
    draw_matrix_index_img as draw_matrix_index_img_pil,
    draw_matrix_detail_img as draw_matrix_detail_img_pil,
)
from ..utils.render_utils import (
    PLAYWRIGHT_AVAILABLE,
    render_html,
    get_image_b64_with_cache,
    get_footer_b64,
)
from ..wutheringwaves_config import WutheringWavesConfig, PREFIX

TEXT_PATH = Path(__file__).parent / "texture2d"

MATRIX_ERROR = "数据获取失败，请稍后再试"
MATRIX_ERROR_NO_DATA = "当前暂无终焉矩阵数据"
MATRIX_ERROR_NO_UNLOCK = "终焉矩阵暂未解锁"

MODE_NAME_MAP = {
    1: "奇点扩张",
    0: "稳态协议",
}


async def _get_account_info(uid: str, ck: str) -> Union[AccountBaseInfo, str]:
    account_info_res = await waves_api.get_base_info(uid, ck)
    if not account_info_res.success:
        return account_info_res.throw_msg()
    if not account_info_res.data:
        return f"用户未展示数据, 请尝试【{PREFIX}登录】"
    return AccountBaseInfo.model_validate(account_info_res.data)


async def get_matrix_data(uid: str, ck: str, is_self_ck: bool) -> Union[MatrixDetail, str]:
    if is_self_ck:
        matrix_data = await waves_api.get_matrix_detail(uid, ck)
    else:
        matrix_data = await waves_api.get_matrix_index(uid, ck)

    if not matrix_data.success:
        return matrix_data.throw_msg()

    matrix_data = matrix_data.data
    if not matrix_data or (isinstance(matrix_data, dict) and not matrix_data.get("isUnlock", False)):
        if not is_self_ck:
            if matrix_data is None and await waves_api.is_hidden_to_guest(uid, ck):
                return f"用户未展示挑战数据, 请尝试【{PREFIX}登录】"
            return MATRIX_ERROR_NO_UNLOCK
        return MATRIX_ERROR_NO_DATA
    else:
        return MatrixDetail.model_validate(matrix_data)


async def match_all_char_ids(matrix_data: MatrixDetail) -> dict:
    """获取所有模式所有队伍的 char_ids (与 roleIcons 同序)

    优先用接口自带的 roleList.roleId，缺失时才回退到头像相似度匹配。

    Returns:
        {(modeId, team_index): [char_id, ...], ...}
    """
    result: dict = {}
    for mode in matrix_data.modeDetails:
        if not mode.hasRecord or not mode.teams:
            continue
        for idx, team in enumerate(mode.teams):
            if team.roleList:
                char_ids = [r.roleId for r in team.roleList]
            elif team.roleIcons:
                try:
                    char_ids = await match_role_icons_to_char_ids(
                        team.roleIcons, MATRIX_PATH
                    )
                except Exception:
                    char_ids = []
            else:
                char_ids = []
            result[(mode.modeId, idx)] = char_ids
    return result


async def save_matrix_record(
    uid: str,
    matrix_data: MatrixDetail,
    char_ids_map: dict,
):
    """保存矩阵记录到本地文件，包含匹配到的角色ID"""
    try:
        _dir = PLAYER_PATH / uid
        _dir.mkdir(parents=True, exist_ok=True)
        path = _dir / "matrixData.json"

        matrix_dict = matrix_data.model_dump()

        # 将 char_ids 存入 matched_char_ids，key 为 "modeId_teamIndex"
        matched = {}
        for (mode_id, team_idx), ids in char_ids_map.items():
            matched[f"{mode_id}_{team_idx}"] = ids

        record_payload = {
            "record_time": int(time.time()),
            "matrix_data": matrix_dict,
            "matched_char_ids": matched,
        }
        await write_player_json(path, record_payload)
    except Exception as e:
        logger.warning(f"[鸣潮·矩阵保存] 失败 uid={uid} error={e}")


async def upload_matrix_record(
    is_self_ck: bool,
    waves_id: str,
    matrix_data: MatrixDetail,
    char_ids_map: dict,
    sender_avatar: str = "",
    user_id: str = "",
    bot_id: str = "",
):
    from ..utils.util import resolve_hide_uid
    WavesToken = WutheringWavesConfig.get_config("WavesToken").data
    if not WavesToken:
        return

    if not matrix_data:
        return
    if not matrix_data.modeDetails:
        return
    if not is_self_ck:
        return

    # 上传奇点扩张 (modeId=1) 的数据
    mode = next(
        (m for m in matrix_data.modeDetails if m.modeId == 1 and m.hasRecord),
        None,
    )
    if not mode:
        return

    if not mode.teams:
        return

    teams = []
    for idx, team in enumerate(mode.teams):
        buff = team.buffs[0] if team.buffs else None
        char_ids = char_ids_map.get((mode.modeId, idx), [])
        teams.append(
            MatrixTeamDetail(
                buff_icon=buff.buffIcon if buff else "",
                buff_name=buff.buffName if buff else "",
                buff_id=buff.buffId if buff else 0,
                role_icons=team.roleIcons,
                char_ids=char_ids,
                score=team.score,
            )
        )

    matrix_item = MatrixDetailRequest(
        wavesId=waves_id,
        modeId=mode.modeId,
        rank=mode.rank,
        score=mode.score,
        teamCount=len(mode.teams),
        teams=teams,
        sender_avatar=sender_avatar,
        hide_uid=await resolve_hide_uid(waves_id, user_id, bot_id),
    )
    push_item(QUEUE_MATRIX_RECORD, matrix_item.model_dump())


def _get_rank_img_b64(rank: int) -> str:
    return _get_texture_b64(f"rank-{max(0, min(rank, 7))}.png")


def _get_rank_detail_b64(rank: int) -> str:
    return _get_texture_b64(f"rank-detail-{max(0, min(rank, 7))}.png")


def _get_texture_b64(name: str) -> str:
    """获取 texture2d 目录下图片的 base64"""
    path = TEXT_PATH / name
    if path.exists():
        img = Image.open(path)
        return pil_to_b64(img, quality=75)
    return ""


def _resolve_mode_id(ev) -> int:
    """根据命令/文本决定展示哪个模式，默认奇点扩张(1)，含'稳态'则稳态协议(0)"""
    command = ev.command if hasattr(ev, 'command') else ""
    text = ev.text.strip() if hasattr(ev, 'text') and ev.text else ""
    combined = command + text
    if "稳态" in combined:
        return 0
    return 1


async def draw_matrix_img(ev: Event, uid: str, user_id: str) -> Union[bytes, str]:
    is_self_ck, ck = await waves_api.get_ck_result(uid, user_id, ev.bot_id)
    if not ck:
        return error_reply(WAVES_CODE_102)

    # 矩阵数据
    matrix_detail: Union[MatrixDetail, str] = await get_matrix_data(uid, ck, is_self_ck)
    if isinstance(matrix_detail, str):
        return matrix_detail

    if not matrix_detail.isUnlock:
        return MATRIX_ERROR_NO_UNLOCK

    if not matrix_detail.modeDetails:
        return MATRIX_ERROR_NO_DATA

    has_record = any(m.hasRecord for m in matrix_detail.modeDetails)
    if not has_record:
        return MATRIX_ERROR_NO_DATA

    # 匹配角色ID (一次匹配，save + upload 共用)
    char_ids_map = await match_all_char_ids(matrix_detail) if is_self_ck else {}

    sender_avatar = safe_sender_avatar(ev)

    if is_self_ck:
        target_mode_id = _resolve_mode_id(ev)
        result = await _draw_matrix_detail_html(
            ev,
            uid,
            user_id,
            ck,
            matrix_detail,
            is_self_ck,
            target_mode_id,
            char_ids_map,
        )
    else:
        # 未登录: 展示所有模式，不区分稳态/奇点
        result = await _draw_matrix_index_html(ev, uid, user_id, ck, matrix_detail)

    if isinstance(result, bytes):
        await save_matrix_record(uid, matrix_detail, char_ids_map)
        await upload_matrix_record(is_self_ck, uid, matrix_detail, char_ids_map, sender_avatar, user_id, ev.bot_id)
    return result


async def _get_common_context(ev: Event, uid: str, user_id: str, ck: str) -> Union[dict, str]:
    """获取用户卡片等通用上下文"""
    account_info = await _get_account_info(uid, ck)
    if isinstance(account_info, str):
        return account_info

    user_pref = await get_hide_uid_pref(uid, user_id, ev.bot_id)

    avatar = await get_event_avatar(ev)
    avatar_url = pil_to_b64(avatar, quality=75)

    bg_img = get_waves_bg(bg="bg9", crop=False)
    bg_url = pil_to_b64(bg_img, quality=75)

    current_date = datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=8))
    ).strftime("%Y-%m-%d")

    return {
        "user_name": account_info.name,
        "user_id": hide_uid(account_info.id, user_pref=user_pref),
        "level": account_info.level,
        "world_level": account_info.worldLevel,
        "show_stats": account_info.is_full,
        "avatar_url": avatar_url,
        "bg_url": bg_url,
        "current_date": current_date,
        "period": get_matrix_period_number(),
        "footer_b64": get_footer_b64(footer_type="white") or "",
    }


def _get_current_date() -> str:
    return datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=8))
    ).strftime("%Y-%m-%d")


async def _draw_matrix_index_pil(
    ev: Event, uid: str, user_id: str, ck: str, matrix_detail: MatrixDetail
) -> Union[bytes, str]:
    user_pref = await get_hide_uid_pref(uid, user_id, ev.bot_id)
    try:
        account_info = await _get_account_info(uid, ck)
        if isinstance(account_info, str):
            return account_info

        return await draw_matrix_index_img_pil(
            ev,
            account_info,
            user_pref,
            _get_current_date(),
            matrix_detail,
        )
    except Exception as e:
        logger.exception(f"[鸣潮·矩阵渲染] PIL Index 失败: {e}")
        return "[鸣潮] 矩阵卡片渲染失败, 请稍后重试"


async def _draw_matrix_detail_pil(
    ev: Event,
    uid: str,
    user_id: str,
    ck: str,
    matrix_detail: MatrixDetail,
    target_mode_id: int = 1,
    char_ids_map: dict = None,
) -> Union[bytes, str]:
    user_pref = await get_hide_uid_pref(uid, user_id, ev.bot_id)
    try:
        account_info = await _get_account_info(uid, ck)
        if isinstance(account_info, str):
            return account_info

        role_detail_info_map = await get_all_roleid_detail_info(uid)
        rover_map = await get_rover_detail_map(uid)
        return await draw_matrix_detail_img_pil(
            ev,
            account_info,
            user_pref,
            _get_current_date(),
            matrix_detail,
            role_detail_info_map or {},
            target_mode_id,
            char_ids_map,
            rover_map,
        )
    except Exception as e:
        logger.exception(f"[鸣潮·矩阵渲染] PIL Detail 失败: {e}")
        return "[鸣潮] 矩阵卡片渲染失败, 请稍后重试"


async def _draw_matrix_index_html(
    ev: Event, uid: str, user_id: str, ck: str, matrix_detail: MatrixDetail
) -> Union[bytes, str]:
    """未登录用户的 HTML 渲染 — 所有模式显示在一起，不区分稳态/奇点"""
    use_html_render = WutheringWavesConfig.get_config("UseHtmlRender").data
    if not PLAYWRIGHT_AVAILABLE or not use_html_render:
        return await _draw_matrix_index_pil(ev, uid, user_id, ck, matrix_detail)

    try:
        ctx = await _get_common_context(ev, uid, user_id, ck)
        if isinstance(ctx, str):
            return ctx

        # 全图背景: matrix-home-bg (不存在则回退 matrix-detail-bg-1)
        home_bg = TEXT_PATH / "matrix-home-bg.png"
        if home_bg.exists():
            ctx["bg_url"] = _get_texture_b64("matrix-home-bg.png")
        else:
            ctx["bg_url"] = _get_texture_b64("matrix-detail-bg-1.png")

        # reward 图标
        reward_icon_url = _get_texture_b64("reward.png")

        # 展示所有有记录的模式 (奇点扩张 modeId=1 排在前面)
        modes_data = []
        for mode in sorted(matrix_detail.modeDetails, key=lambda m: m.modeId, reverse=True):
            if not mode.hasRecord:
                continue
            modes_data.append({
                "mode_id": mode.modeId,
                "mode_name": MODE_NAME_MAP.get(mode.modeId, f"模式{mode.modeId}"),
                "score": mode.score,
                "rank": mode.rank,
                "rank_img_url": _get_rank_img_b64(mode.rank),
            })

        if not modes_data:
            return MATRIX_ERROR_NO_DATA

        context = {
            **ctx,
            "modes": modes_data,
            "reward": matrix_detail.reward,
            "total_reward": matrix_detail.totalReward,
            "reward_icon_url": reward_icon_url,
        }

        logger.debug("[鸣潮·矩阵渲染] 准备 HTML 渲染 (Index)")
        img_bytes = await render_html(waves_templates, "abyss/matrix_card.html", context)
        if img_bytes:
            return img_bytes
        else:
            logger.warning("[鸣潮·矩阵渲染] Playwright 返回空, 回退到 PIL (Index)")
            return await _draw_matrix_index_pil(ev, uid, user_id, ck, matrix_detail)

    except Exception as e:
        logger.exception(f"[鸣潮·矩阵渲染] HTML Index 失败: {e}")
        return await _draw_matrix_index_pil(ev, uid, user_id, ck, matrix_detail)


async def _draw_matrix_detail_html(
    ev: Event, uid: str, user_id: str, ck: str, matrix_detail: MatrixDetail,
    is_self_ck: bool, target_mode_id: int = 1, char_ids_map: dict = None
) -> Union[bytes, str]:
    """已登录用户的 HTML 渲染 (详细队伍数据)"""
    use_html_render = WutheringWavesConfig.get_config("UseHtmlRender").data
    if not PLAYWRIGHT_AVAILABLE or not use_html_render:
        return await _draw_matrix_detail_pil(
            ev, uid, user_id, ck, matrix_detail, target_mode_id, char_ids_map
        )

    try:
        ctx = await _get_common_context(ev, uid, user_id, ck)
        if isinstance(ctx, str):
            return ctx

        # 静态资源
        overview_bg_url = _get_texture_b64("overview-bg.png")
        boss_icon_url = _get_texture_b64("boss.png")
        matrix_score_icon_url = _get_texture_b64("matrix_score.png")

        # 全图背景: matrix-detail-bg-{modeId}
        bg_url = _get_texture_b64(f"matrix-detail-bg-{target_mode_id}.png")
        # 覆盖通用 bg
        ctx["bg_url"] = bg_url

        # 根据面板数据获取共鸣链详细信息 (与外层 match_all_char_ids 共用一次)
        role_detail_info_map = await get_all_roleid_detail_info(uid) or {}
        rover_map = await get_rover_detail_map(uid)
        _char_ids_map = char_ids_map or {}

        # 只展示目标模式
        modes_data = []
        for mode in matrix_detail.modeDetails:
            if mode.modeId != target_mode_id:
                continue
            if not mode.hasRecord or not mode.teams:
                continue

            # 挑战进度
            boss_count = mode.bossCount or 0
            pass_boss = mode.passBoss or 0
            progress_pct = (pass_boss / boss_count * 100) if boss_count > 0 else 0

            # 队伍数据
            teams_data = []
            for team_idx, team in enumerate(mode.teams):
                # 该队伍匹配到的角色ID列表
                team_char_ids = _char_ids_map.get((mode.modeId, team_idx), [])

                roles_data = []
                for role_idx, icon_url in enumerate(team.roleIcons):
                    role_b64 = ""
                    if icon_url:
                        try:
                            role_b64 = await get_image_b64_with_cache(
                                icon_url, MATRIX_PATH,
                                quality=75, cover_size=(128, 128)
                            )
                        except Exception:
                            pass

                    char_id = team_char_ids[role_idx] if role_idx < len(team_char_ids) else None
                    chain_num, chain_name, _ = lookup_chain_with_rover(role_detail_info_map, rover_map, char_id)

                    _r = team.roleList[role_idx] if role_idx < len(team.roleList) else None
                    roles_data.append({
                        "icon_url": role_b64,
                        "chain": chain_num,
                        "chain_name": chain_name,
                        "branch_icon": get_skill_branch_emblem_b64(_r.roleId, _r.skillBranchIndex) if _r else "",
                    })

                # 不足3人时补占位
                for _ in range(len(roles_data), 3):
                    roles_data.append({
                        "icon_url": "",
                        "chain": None,
                        "chain_name": "",
                        "is_placeholder": True,
                    })

                # buff图标
                buff_icon_url = ""
                if team.buffs:
                    buff = team.buffs[0]
                    if buff.buffIcon:
                        try:
                            buff_icon_url = await get_image_b64_with_cache(
                                buff.buffIcon, MATRIX_PATH,
                                quality=75, cover_size=(100, 100)
                            )
                        except Exception:
                            pass

                teams_data.append({
                    "roles": roles_data,
                    "buff_icon_url": buff_icon_url,
                    "round": team.round,
                    "pass_boss": team.passBoss,
                    "boss_count": team.bossCount,
                    "score": team.score,
                })

            modes_data.append({
                "mode_id": mode.modeId,
                "mode_name": MODE_NAME_MAP.get(mode.modeId, f"模式{mode.modeId}"),
                "score": mode.score,
                "score_color": get_matrix_score_class(mode.score),
                "rank": mode.rank,
                "rank_detail_url": _get_rank_detail_b64(mode.rank),
                "boss_count": boss_count,
                "pass_boss": pass_boss,
                "progress_pct": progress_pct,
                "teams": teams_data,
            })

        if not modes_data:
            return MATRIX_ERROR_NO_DATA

        chain_colors = {i: f"rgba({r}, {g}, {b}, 0.8)" for i, (r, g, b) in CHAIN_COLOR.items()}

        context = {
            **ctx,
            "modes": modes_data,
            "overview_bg_url": overview_bg_url,
            "boss_icon_url": boss_icon_url,
            "matrix_score_icon_url": matrix_score_icon_url,
            "is_self_ck": is_self_ck,
            "chain_colors": chain_colors,
        }

        logger.debug("[鸣潮·矩阵渲染] 准备 HTML 渲染 (Detail)")
        img_bytes = await render_html(waves_templates, "abyss/matrix_detail_card.html", context)
        if img_bytes:
            return img_bytes
        else:
            logger.warning("[鸣潮·矩阵渲染] Playwright 返回空, 回退到 PIL (Detail)")
            return await _draw_matrix_detail_pil(
                ev, uid, user_id, ck, matrix_detail, target_mode_id, char_ids_map
            )

    except Exception as e:
        logger.exception(f"[鸣潮·矩阵渲染] HTML Detail 失败: {e}")
        return await _draw_matrix_detail_pil(
            ev, uid, user_id, ck, matrix_detail, target_mode_id, char_ids_map
        )


