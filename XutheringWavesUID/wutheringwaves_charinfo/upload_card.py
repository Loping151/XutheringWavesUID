import os
import ssl
import time
import shutil
import asyncio
from pathlib import Path
from typing import List, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from PIL import Image

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.utils.image.convert import convert_img
from gsuid_core.utils.download_resource.download_file import download

from ..utils.image import compress_to_webp
from ..utils.pile_offset import delete_rank_offset, move_rank_offset
from ..wutheringwaves_config import WutheringWavesConfig
from ..utils.name_convert import easy_id_to_name
from ..utils.resource.RESOURCE_PATH import CUSTOM_CARD_PATH, CUSTOM_ORB_PATH
from . import card_hash_index
from .card_hash_index import compute_hash as get_hash_id
from .card_utils import (
    CUSTOM_PATH_MAP,
    CUSTOM_PATH_NAME_MAP,
    cv2 as _cv2,
    delete_orb_cache,
    find_duplicates_for_new_images,
    get_char_id_and_name,
    get_image,
    get_orb_dir_for_char,
    ORB_BLOCK_THRESHOLD,
    update_orb_cache,
)


def check_image_dimensions(temp_path: Path, target_type: str, index: int) -> Optional[str]:
    try:
        with Image.open(temp_path) as img:
            w, h = img.size
            if target_type in ["card", "stamina"] and w > h:
                return f"第{index}张图片尺寸错误，面板图和体力图需要竖版图片（宽 ≤ 高），可能想上传：背景图"
            if target_type == "bg" and h > w:
                return f"第{index}张图片尺寸错误，背景图需要横版图片（高 ≤ 宽），可能想上传：面板图"
    except Exception as e:
        logger.warning(f"[鸣潮·卡片上传] 检查图片尺寸失败: {e}")
    return None


def collect_blocked_duplicates(
    temp_dir: Path, new_images: List[Path]
) -> Tuple[List[str], Set[Path]]:
    dup_map = find_duplicates_for_new_images(temp_dir, new_images)
    block_msgs: List[str] = []
    blocked_paths: Set[Path] = set()
    for index, new_path in enumerate(new_images, start=1):
        dup_list = dup_map.get(new_path)
        if not dup_list:
            continue
        dup_list = sorted(dup_list, key=lambda x: -x[1])
        top_path, top_sim = dup_list[0]
        top_id = get_hash_id(top_path.name)
        if top_sim >= ORB_BLOCK_THRESHOLD:
            block_msgs.append(f"第{index}张和已有id {top_id} 重复")
            blocked_paths.add(new_path)
    return block_msgs, blocked_paths


async def upload_custom_card(
    bot: Bot,
    ev: Event,
    char: str,
    target_type: str = "card",
    is_force: bool = False,
):
    at_sender = True if ev.group_id else False
    type_label = CUSTOM_PATH_NAME_MAP.get(target_type, target_type)

    upload_images = await get_image(ev)
    if not upload_images:
        msg = f"[鸣潮] 上传角色{type_label}图失败\n请同时发送图片及其命令\n支持上传的图片类型：面板图/体力图/背景图"
        return await bot.send(
            (" " if at_sender else "") + msg,
            at_sender,
        )

    char_id, char, msg = get_char_id_and_name(char)
    if msg:
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    temp_dir = CUSTOM_PATH_MAP.get(target_type, CUSTOM_CARD_PATH) / f"{char_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    success = True
    new_images = []
    size_check_failed = []
    for index, upload_image in enumerate(upload_images, start=1):
        name = f"{char_id}_{int(time.time() * 1000)}.jpg"
        temp_path = temp_dir / name

        if not temp_path.exists():
            try:
                if httpx.__version__ >= "0.28.0":
                    ssl_context = ssl.create_default_context()
                    # ssl_context.set_ciphers("AES128-GCM-SHA256")
                    ssl_context.set_ciphers("DEFAULT")
                    sess = httpx.AsyncClient(verify=ssl_context)
                else:
                    sess = httpx.AsyncClient()
            except Exception as e:
                logger.exception(f"[鸣潮·卡片上传] {httpx.__version__} - {e}")
                sess = None
            code = await download(upload_image, temp_dir, name, tag="[鸣潮]", sess=sess)
            if not isinstance(code, int) or code != 200:
                # 成功
                success = False
                break

            err_msg = check_image_dimensions(temp_path, target_type, index)
            if err_msg:
                size_check_failed.append(err_msg)
                temp_path.unlink()
                continue

            new_images.append(temp_path)

    if size_check_failed:
        if not new_images:
            return await bot.send(
                (" " if at_sender else "") + "[鸣潮] 上传失败！\n" + "\n".join(size_check_failed),
                at_sender,
            )

    if success:
        msg = f"[鸣潮]【{char}】上传{type_label}图成功！"
        if new_images:
            block_msgs, blocked_paths = collect_blocked_duplicates(temp_dir, new_images)

            if block_msgs and not is_force:
                for img_path in blocked_paths:
                    try:
                        img_path.unlink()
                    except Exception:
                        pass
                    delete_orb_cache(img_path)
                block_text = "；".join(block_msgs)
                msg = f"{msg} 疑似重复: {block_text}，请使用强制上传继续上传"

            success_ids = []
            for img_path in new_images:
                if img_path not in blocked_paths:
                    update_orb_cache(img_path)
                    card_hash_index.add(target_type, char_id, img_path)
                    success_ids.append(get_hash_id(img_path.name))

            if success_ids:
                msg = f"{msg} 上传成功id: {', '.join(success_ids)}"

        await bot.send((" " if at_sender else "") + msg, at_sender)
        return
    else:
        msg = f"[鸣潮]【{char}】上传{type_label}图失败！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)


async def get_custom_card_list(bot: Bot, ev: Event, char: str, target_type: str = "card"):
    at_sender = True if ev.group_id else False
    char_id, char, msg = get_char_id_and_name(char)
    if msg:
        return await bot.send((" " if at_sender else "") + msg, at_sender)
    type_label = CUSTOM_PATH_NAME_MAP.get(target_type, target_type)

    files_map = card_hash_index.list_dir(target_type, char_id)
    if not files_map:
        msg = f"[鸣潮] 角色【{char}】暂未上传过{type_label}图！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    imgs = []
    for hash_id, f in files_map.items():
        img = await convert_img(f)
        imgs.append(f"{char}{type_label}图id : {hash_id}")
        imgs.append(img)

    card_num = WutheringWavesConfig.get_config("CharCardNum").data
    card_num = max(5, min(card_num, 30))

    for i in range(0, len(imgs), card_num * 2):
        send = imgs[i : i + card_num * 2]
        await bot.send(send)
        await asyncio.sleep(0.5)


async def delete_custom_card(bot: Bot, ev: Event, char: str, hash_id: str, target_type: str = "card"):
    at_sender = True if ev.group_id else False
    char_id, char, msg = get_char_id_and_name(char)
    if msg:
        return await bot.send((" " if at_sender else "") + msg, at_sender)
    type_label = CUSTOM_PATH_NAME_MAP.get(target_type, target_type)

    files_map = card_hash_index.list_dir(target_type, char_id)
    if not files_map:
        msg = f"[鸣潮] 角色【{char}】暂未上传过{type_label}图！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    hash_ids = [id.strip() for id in hash_id.replace("，", ",").split(",") if id.strip()]

    if not hash_ids:
        msg = f"[鸣潮] 未提供有效的{type_label}图ID！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    not_found_ids = []
    found_in_other = []
    deleted_ids = []

    for single_hash_id in hash_ids:
        if single_hash_id not in files_map:
            not_found_ids.append(single_hash_id)
        else:
            try:
                target_file = files_map[single_hash_id]
                target_file.unlink()
                delete_rank_offset(target_file)
                delete_orb_cache(target_file)
                card_hash_index.remove(target_type, char_id, target_file)
                deleted_ids.append(single_hash_id)
            except Exception as e:
                logger.exception(f"[鸣潮·卡片上传] 删除文件失败: {target_file} - {e}")
                not_found_ids.append(single_hash_id)

    msg_parts = []
    if deleted_ids:
        msg_parts.append(f"成功删除id: {', '.join(deleted_ids)}")
    else:
        if not_found_ids:
            for single_hash_id in not_found_ids:
                matches = card_hash_index.find(single_hash_id)
                if matches:
                    for t, other_char_id, _ in matches:
                        char_name = easy_id_to_name(other_char_id, other_char_id)
                        type_name = CUSTOM_PATH_NAME_MAP.get(t, t)
                        found_in_other.append(
                            f"{single_hash_id} 在{char_name}的{type_name}图中找到"
                        )
                else:
                    msg_parts.append(f"未找到id: {single_hash_id}")
        if found_in_other:
            msg_parts.append("；".join(found_in_other))

    msg = f"[鸣潮] 角色【{char}】{type_label}图 " + "；".join(msg_parts)
    return await bot.send((" " if at_sender else "") + msg, at_sender)


async def delete_all_custom_card(bot: Bot, ev: Event, char: str, target_type: str = "card"):
    at_sender = True if ev.group_id else False
    char_id, char, msg = get_char_id_and_name(char)
    if msg:
        return await bot.send((" " if at_sender else "") + msg, at_sender)
    type_label = CUSTOM_PATH_NAME_MAP.get(target_type, target_type)

    if not card_hash_index.list_dir(target_type, char_id):
        msg = f"[鸣潮] 角色【{char}】暂未上传过{type_label}图！"
        return await bot.send((" " if at_sender else "") + msg, at_sender)

    temp_dir = CUSTOM_PATH_MAP.get(target_type, CUSTOM_CARD_PATH) / f"{char_id}"
    try:
        if temp_dir.exists() and temp_dir.is_dir():
            shutil.rmtree(temp_dir)
        orb_dir = get_orb_dir_for_char(target_type, char_id)
        if orb_dir.exists() and orb_dir.is_dir():
            shutil.rmtree(orb_dir)
    except Exception:
        pass
    card_hash_index.clear_dir(target_type, char_id)

    msg = f"[鸣潮] 删除角色【{char}】的所有{type_label}图成功！"
    return await bot.send((" " if at_sender else "") + msg, at_sender)


async def compress_all_custom_card(bot: Bot, ev: Event):
    count = 0
    rename_count = 0
    use_cores = max(os.cpu_count() - 2 if os.cpu_count() else 0, 1)  # 避免2c服务器卡死
    await bot.send(f"[鸣潮] 开始压缩面板、体力、背景图, 使用 {use_cores} 核心")

    # 重命名含中文的文件名为 char_id 格式，避免 opencv 不兼容中文路径
    for PATH in CUSTOM_PATH_MAP.values():
        for char_id_path in PATH.iterdir():
            if not char_id_path.is_dir():
                continue
            char_id = char_id_path.name
            for img_path in list(char_id_path.iterdir()):
                if not img_path.is_file():
                    continue
                if img_path.suffix.lower() not in [".jpg", ".png", ".jpeg", ".webp"]:
                    continue
                if img_path.stem.isascii():
                    continue
                base_ts = int(time.time() * 1000)
                new_name = f"{char_id}_{base_ts}{img_path.suffix}"
                new_path = char_id_path / new_name
                counter = 1
                while new_path.exists():
                    new_name = f"{char_id}_{base_ts + counter}{img_path.suffix}"
                    new_path = char_id_path / new_name
                    counter += 1
                try:
                    delete_orb_cache(img_path)
                    img_path.rename(new_path)
                    move_rank_offset(img_path, new_path)
                    if new_path.suffix.lower() == ".webp":
                        update_orb_cache(new_path)
                    rename_count += 1
                except Exception as e:
                    logger.error(f"[鸣潮·卡片上传] 重命名失败 {img_path}: {e}")

    task_list = []
    for PATH in CUSTOM_PATH_MAP.values():
        for char_id_path in PATH.iterdir():
            if not char_id_path.is_dir():
                continue
            for img_path in char_id_path.iterdir():
                if not img_path.is_file():
                    continue
                if img_path.suffix.lower() in [".jpg", ".png", ".jpeg"]:
                    task_list.append((img_path, 80, True))

    with ThreadPoolExecutor(max_workers=use_cores) as executor:
        future_to_file = {executor.submit(compress_to_webp, *task): task for task in task_list}

        for future in as_completed(future_to_file):
            file_info = future_to_file[future]
            try:
                success, _ = future.result()
                if success:
                    count += 1
                    delete_orb_cache(file_info[0])
                    update_orb_cache(file_info[0].with_suffix(".webp"))

            except Exception as exc:
                logger.error(f"[鸣潮·卡片上传] Error processing {file_info[0]}: {exc}")

    if rename_count or count:
        card_hash_index.build()

    msgs = []
    if rename_count > 0:
        msgs.append(f"重命名【{rename_count}】张中文命名图片")
    if count > 0:
        msgs.append(f"压缩【{count}】张图")
    if msgs:
        return await bot.send(f"[鸣潮] {'，'.join(msgs)}成功！")
    else:
        return await bot.send("[鸣潮] 暂未找到需要压缩或重命名的资源！")


async def recompute_all_orb_features(bot: Bot, ev: Event):
    """重算所有 ORB 特征 npz: 有对应图片 → 重算覆盖, 无对应图片 → 视为孤儿删除。"""
    if _cv2 is None:
        return await bot.send("[鸣潮] 未安装opencv-python，无法重算ORB特征。")

    if not CUSTOM_ORB_PATH.exists():
        return await bot.send("[鸣潮] 暂无ORB缓存目录，无需重算。")

    to_recompute: List[Path] = []
    orphans: List[Path] = []
    for npz_path in CUSTOM_ORB_PATH.rglob("*.npz"):
        rel_parts = npz_path.relative_to(CUSTOM_ORB_PATH).parts
        if len(rel_parts) < 2 or rel_parts[0] not in CUSTOM_PATH_MAP:
            orphans.append(npz_path)
            continue
        # 反向映射: <type>/<...>.<ext>.npz -> CUSTOM_PATH_MAP[type]/<...>.<ext>
        image_path = CUSTOM_PATH_MAP[rel_parts[0]] / Path(*rel_parts[1:]).with_suffix("")
        if image_path.is_file():
            to_recompute.append(image_path)
        else:
            orphans.append(npz_path)

    deleted = 0
    for n in orphans:
        try:
            n.unlink()
            deleted += 1
        except Exception as e:
            logger.warning(f"[鸣潮·卡片上传] 删除孤儿ORB缓存失败 {n}: {e}")

    if not to_recompute:
        if deleted:
            return await bot.send(f"[鸣潮] 已清理 {deleted} 个孤儿ORB缓存，无图片需重算。")
        return await bot.send("[鸣潮] 未找到任何ORB缓存。")

    use_cores = max(os.cpu_count() - 2 if os.cpu_count() else 0, 1)
    await bot.send(f"[鸣潮] 开始重算 {len(to_recompute)} 个ORB特征, 使用 {use_cores} 核心...")

    recomputed = 0
    failed = 0
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=use_cores) as executor:
        tasks = [loop.run_in_executor(executor, update_orb_cache, p) for p in to_recompute]
        for ok in await asyncio.gather(*tasks, return_exceptions=True):
            if ok is True:
                recomputed += 1
            else:
                failed += 1
                if isinstance(ok, BaseException):
                    logger.warning(f"[鸣潮·卡片上传] 重算ORB异常: {ok}")

    parts = [f"重算 {recomputed} 个"]
    if failed:
        parts.append(f"失败 {failed} 个")
    if deleted:
        parts.append(f"清理孤儿 {deleted} 个")
    await bot.send(f"[鸣潮] ORB特征重算完成: {'，'.join(parts)}。")
