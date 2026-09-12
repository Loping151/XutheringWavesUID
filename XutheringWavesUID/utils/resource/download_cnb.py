import asyncio
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from gsuid_core.logger import logger

from .RESOURCE_PATH import MAIN_PATH

# CNB 镜像走 git 协议: 一次连接把整棵资源树拉下来, 服务端自己算 delta,
# 之后每次同步只传变化的那几个 blob (实测换一个文件 ≈16KB), 不吃 raw 接口的 IP 限流。
# 仓库停在 .cnb_res, 再按 EPATH_MAP 硬链接到各资源目录, 不额外占一份资源副本。
REPO_PATH = MAIN_PATH / ".cnb_res"
RAW_MARK = "/-/git/raw/"


def parse_repo_url(url: str) -> Optional[Tuple[str, str]]:
    """URL_LIB 里的 raw 地址 -> (clone 地址, 分支)"""
    if RAW_MARK not in url:
        return None

    repo, _, branch = url.partition(RAW_MARK)
    branch = branch.strip("/").split("/")[0]
    if not branch:
        return None

    return f"{repo}.git", branch


async def run_git(*args: str, cwd: Optional[Path] = None) -> Tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode("utf-8", "ignore").strip()


def resolve_local_path(rel_path: str, EPATH_MAP: Dict[str, Path]) -> Optional[Path]:
    """仓库内路径 -> 本地路径; 取最长前缀, 让 resource/map/character 优先于 resource/map。"""
    if ".." in rel_path.split("/"):
        return None

    endpoint = ""
    for e in EPATH_MAP:
        if rel_path.startswith(f"{e}/") and len(e) > len(endpoint):
            endpoint = e

    if not endpoint:
        return None

    return EPATH_MAP[endpoint] / rel_path[len(endpoint) + 1 :]


def place_file(src: Path, dst: Path) -> bool:
    """把仓库里的文件落到资源目录; 优先硬链接, 跨盘再退化成拷贝。"""
    src_stat = src.stat()
    if dst.exists():
        dst_stat = dst.stat()
        if dst_stat.st_ino == src_stat.st_ino and dst_stat.st_dev == src_stat.st_dev:
            return False
        if (
            dst_stat.st_size == src_stat.st_size
            and int(dst_stat.st_mtime) == int(src_stat.st_mtime)
        ):
            return False
        dst.unlink()

    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
    return True


async def sync_repo(repo_url: str, branch: str, sparse: List[str], TAG: str) -> bool:
    if not (REPO_PATH / ".git").exists():
        shutil.rmtree(REPO_PATH, ignore_errors=True)
        logger.info(f"[鸣潮·资源下载] {TAG} 首次拉取资源仓库, 约 1GB, 请耐心等待...")
        code, out = await run_git(
            "clone",
            "--depth=1",
            "--filter=blob:none",
            "--sparse",
            "--branch",
            branch,
            repo_url,
            str(REPO_PATH),
        )
        if code != 0:
            logger.warning(f"[鸣潮·资源下载] {TAG} 仓库克隆失败: {out}")
            return False
        # 每次同步都是 force push 的新根提交, 旧 blob 立即变不可达, 让 gc 能收掉
        await run_git("config", "gc.pruneExpire", "now", cwd=REPO_PATH)
    else:
        code, out = await run_git(
            "fetch", "--depth=1", "origin", branch, cwd=REPO_PATH
        )
        if code != 0:
            logger.warning(f"[鸣潮·资源下载] {TAG} 仓库更新失败: {out}")
            return False
        code, out = await run_git("reset", "--hard", "FETCH_HEAD", cwd=REPO_PATH)
        if code != 0:
            logger.warning(f"[鸣潮·资源下载] {TAG} 仓库重置失败: {out}")
            return False

    # 只签出本平台用得到的目录, 其余 19 个平台的构建产物连 blob 都不会下载
    code, out = await run_git(
        "sparse-checkout", "set", "--cone", *sparse, cwd=REPO_PATH
    )
    if code != 0:
        logger.warning(f"[鸣潮·资源下载] {TAG} 稀疏签出失败: {out}")
        return False

    return True


async def download_all_file_cnb(
    plugin_name: str,
    EPATH_MAP: Dict[str, Path],
    URL: str,
    TAG: str,
) -> bool:
    """从 CNB 镜像仓 git 同步资源; 失败时返回 False 交由上层回退到 http 镜像。"""
    parsed = parse_repo_url(URL)
    if parsed is None:
        return False
    repo_url, branch = parsed

    if not shutil.which("git"):
        logger.warning(f"[鸣潮·资源下载] {TAG} 未找到 git, 无法使用该资源源")
        return False

    # PLATFORM 取不到时 endpoint 会带空段, 这种 pattern 直接扔掉
    sparse = [
        f"{plugin_name}/{endpoint}" for endpoint in EPATH_MAP if "//" not in endpoint
    ]
    start = time.perf_counter()
    if not await sync_repo(repo_url, branch, sparse, TAG):
        return False

    root = REPO_PATH / plugin_name
    placed = 0
    for src in root.rglob("*"):
        if not src.is_file():
            continue
        dst = resolve_local_path(src.relative_to(root).as_posix(), EPATH_MAP)
        if dst is None:
            continue
        try:
            if place_file(src, dst):
                placed += 1
        except OSError as e:
            logger.warning(f"[鸣潮·资源下载] {TAG} {dst.name} 落盘失败: {e}")

    logger.success(
        f"[鸣潮·资源下载] {TAG} {plugin_name} 资源同步完成, "
        f"更新 {placed} 个文件, 耗时 {time.perf_counter() - start:.0f}s"
    )
    return True
