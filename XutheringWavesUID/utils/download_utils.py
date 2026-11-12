import os
import sys
import importlib
import json
import shutil
import hashlib
import tempfile
import threading
import time
from pathlib import Path
from contextlib import contextmanager

from gsuid_core.logger import logger

BUILD_COPY_LOCK = threading.RLock()

# 跨进程文件锁: 串行化多实例的 build 落盘, 防止自重启被进程管理器双拉起时
# 两个进程同时 _atomic_copy_tree 造成「半替换」的模块集被 import 到。
_BUILD_LOCK_PATH = None


def _get_build_lock_path() -> Path:
    global _BUILD_LOCK_PATH
    if _BUILD_LOCK_PATH is None:
        # 放数据目录: 持久, 不受 systemd PrivateTmp 隔离, 不落在仓库树内
        from .resource.RESOURCE_PATH import MAIN_PATH

        MAIN_PATH.mkdir(parents=True, exist_ok=True)
        _BUILD_LOCK_PATH = MAIN_PATH / ".build_copy.lock"
    return _BUILD_LOCK_PATH


@contextmanager
def build_interprocess_lock(timeout: float = 120.0):
    """跨进程独占锁。取锁超时则降级继续(仍有线程锁兜底), 不阻断启动。"""
    f = None
    acquired = False
    try:
        try:
            # 二进制模式: Windows 下 msvcrt.locking 按文件指针锁字节, 避免文本模式位置歧义
            f = open(_get_build_lock_path(), "a+b")
        except OSError as e:
            logger.warning(f"[鸣潮·下载工具] 构建锁文件打开失败, 降级继续: {e}")
            yield False
            return

        deadline = time.time() + timeout
        if sys.platform == "win32":
            import msvcrt

            while True:
                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError:
                    if time.time() >= deadline:
                        break
                    time.sleep(0.2)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except OSError:
                    if time.time() >= deadline:
                        break
                    time.sleep(0.2)

        if not acquired:
            logger.warning(
                "[鸣潮·下载工具] 跨进程构建锁获取超时, 降级继续。出现真实竞争时, "
                "请检查自动启动方式是否导致重启时带起了多个相同实例!!! "
                "(systemd/pm2/docker + 自重启的 kill+自 spawn 会双拉起)"
            )
        yield acquired
    finally:
        if f is not None:
            try:
                if acquired:
                    if sys.platform == "win32":
                        import msvcrt

                        try:
                            f.seek(0)
                            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                        except OSError:
                            pass
                    else:
                        import fcntl

                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            finally:
                f.close()


def count_files(directory: Path, pattern: str = "*") -> int:
    """统计目录下指定模式的文件数量"""
    if not directory.exists():
        return 0
    return sum(1 for file in directory.rglob(pattern) if file.is_file())


def get_file_hash(file_path):
    """计算单个文件的哈希值"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        hash_md5.update(f.read())
    return hash_md5.hexdigest()


def get_file_hash_sha256(file_path):
    """计算单个文件的 SHA256 哈希值"""
    hash_sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        hash_sha256.update(f.read())
    return hash_sha256.hexdigest()


def check_file_hash(path: Path) -> bool:
    # 兼容旧版构建的导入
    return False


def check_resource_hash(epath_map: dict, fix: bool = True) -> int:
    """按 resource/hash 清单校验资源, fix 时删除内容不符的文件; 全部一致的清单记下摘要, 未变化不再校验"""
    from .resource.download_cnb import resolve_local_path
    from .resource.RESOURCE_PATH import HASH_PATH, HASH_CHECKED_PATH

    try:
        checked = json.loads(HASH_CHECKED_PATH.read_text(encoding="utf-8"))
    except Exception:
        checked = {}

    mismatched = 0
    for manifest in sorted(HASH_PATH.glob("*.json")):
        try:
            raw = manifest.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if checked.get(manifest.name) == digest:
                continue
            hash_data = json.loads(raw)
        except Exception as e:
            logger.error(f"[鸣潮·下载工具] 读取清单 {manifest.name} 失败: {e}")
            continue

        passed = True
        for rel_path, expected_hash in hash_data.items():
            file = resolve_local_path(rel_path, epath_map)
            if file is None or not file.is_file():
                continue
            try:
                if get_file_hash_sha256(file) != expected_hash:
                    passed = False
                    mismatched += 1
                    if fix:
                        file.unlink()
            except Exception as e:
                passed = False
                logger.error(f"[鸣潮·下载工具] 检查文件 {rel_path} hash 失败: {e}")
        if passed:
            checked[manifest.name] = digest

    try:
        HASH_CHECKED_PATH.write_text(json.dumps(checked), encoding="utf-8")
    except Exception as e:
        logger.error(f"[鸣潮·下载工具] 写入清单校验记录失败: {e}")

    if mismatched and fix:
        logger.info(f"[鸣潮·下载工具] {mismatched} 个资源文件 hash 不匹配，已删除")
    elif mismatched:
        logger.warning(f"[鸣潮·下载工具] {mismatched} 个资源文件重下后仍与清单不符，下次同步重试")
    return mismatched


def _is_same_file(src_file: Path, dst_file: Path) -> bool:
    if not dst_file.exists():
        return False
    try:
        return get_file_hash(src_file) == get_file_hash(dst_file)
    except Exception:
        return False


def _replace_or_skip(tmp: str, dst_file: Path, src_file: Path) -> bool:
    try:
        if dst_file.exists():
            try:
                dst_file.chmod(0o666)
            except OSError:
                pass
        os.replace(tmp, dst_file)
        return True
    except OSError as e:
        # 被占用/竞争(已加载的 .pyd、多进程抢复制): 跳过该文件, 不抛
        logger.debug(f"[鸣潮·下载工具] 构建文件替换跳过: {dst_file} ({e})")
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def _atomic_copy_tree(src, dst):
    """逐文件 写临时文件 + os.replace 原子替换。"""
    src_path = Path(src)
    files = [f for f in src_path.rglob("*") if f.is_file()]
    # 锁敏感的编译扩展先复制
    files.sort(key=lambda p: p.suffix.lower() not in (".pyd", ".so", ".dll", ".dylib"))
    updated = 0
    for src_file in files:
        dst_file = Path(dst) / src_file.relative_to(src_path)
        if _is_same_file(src_file, dst_file):
            continue
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dst_file.parent, prefix=".tmp_")
        os.close(fd)
        try:
            shutil.copy2(src_file, tmp)
            if _replace_or_skip(tmp, dst_file, src_file):
                updated += 1
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return updated


def copy_build_files(soft=False):
    with BUILD_COPY_LOCK, build_interprocess_lock():
        return _copy_build_files(soft)


def import_after_build_copy(module_name, package=None):
    with BUILD_COPY_LOCK, build_interprocess_lock():
        _copy_build_files()
        return importlib.import_module(module_name, package=package)


def _copy_build_files(soft=False):
    from .resource.RESOURCE_PATH import (
        BUILD_PATH,
        BUILD_TEMP,
        MAP_BUILD_PATH,
        MAP_BUILD_TEMP,
    )

    build_updated = _copy_if_different(
        BUILD_TEMP,
        BUILD_PATH,
        "安全工具资源",
        soft=soft,
    )
    map_updated = _copy_if_different(
        MAP_BUILD_TEMP,
        MAP_BUILD_PATH,
        "伤害计算资源",
        soft=soft,
    )
    return build_updated, map_updated


def _copy_if_different(src, dst, name, soft=False):
    """复制并返回是否有更新"""
    if not os.path.exists(src):
        logger.debug(f"[鸣潮·下载工具] {name} 源目录不存在")
        return False

    src_path = Path(src)
    dst_path = Path(dst)
    if dst_path.exists() and count_files(dst_path, "*.py") > 0:
        return False

    needs_update = False

    for src_file in sorted(src_path.rglob("*")):
        if src_file.is_file() and not src_file.suffix == ".json":
            rel_path = src_file.relative_to(src)
            dst_file = Path(dst) / rel_path

            if not dst_file.exists():
                needs_update = True
                break

            if get_file_hash(src_file) != get_file_hash(dst_file):
                needs_update = True
                break

    if needs_update:
        if not soft:
            try:
                _atomic_copy_tree(src, dst)
            except Exception as e:
                logger.exception(f"[鸣潮·下载工具] {name} 更新失败！{e}")
                return False
        logger.info(f"[鸣潮·下载工具] {name} 更新完成！")
        return True
    else:
        logger.debug(f"[鸣潮·下载工具] {name} 无需更新")
        return False
