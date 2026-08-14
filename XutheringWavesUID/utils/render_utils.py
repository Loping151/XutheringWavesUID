import base64
import asyncio
import time
import logging
from typing import Union, Optional
from pathlib import Path

import httpx

from gsuid_core.pool import to_thread
from gsuid_core.logger import logger
from gsuid_core.config import core_config, CONFIG_DEFAULT
from gsuid_core.app_life import app as fastapi_app
from fastapi.staticfiles import StaticFiles
from .resource.RESOURCE_PATH import TEMP_PATH
from ..wutheringwaves_config.wutheringwaves_config import WutheringWavesConfig
from ..wutheringwaves_config.config_default import CONFIG_DEFAULT as WW_CONFIG_DEFAULT

logging.getLogger("uvicorn.access").addFilter(
    lambda record: "/waves/fonts" not in record.getMessage()
)

TEMPLATES_ABS_PATH = Path(__file__).parent.parent / "templates"

class CORSStaticFiles(StaticFiles):
    """Custom StaticFiles class to add CORS headers only for served files."""
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, HEAD"
        return response

def _import_playwright():
    try:
        from playwright.async_api import async_playwright
        return async_playwright
    except ImportError:
        if not WutheringWavesConfig.get_config("RemoteRenderEnable").data:
            logger.warning("[鸣潮·渲染工具] 未安装 playwright，无法使用渲染公告、wiki图等功能。")
            logger.warning("[鸣潮·渲染工具] 可选择配置外置渲染方法！")
            logger.info("[鸣潮·渲染工具] 安装方法 Linux/Mac: 在当前目录下执行 source .venv/bin/activate && uv pip install playwright && uv run playwright install chromium")
            logger.info("[鸣潮·渲染工具] 安装方法 Windows: 在当前目录下执行 .venv\\Scripts\\activate; uv pip install playwright; uv run playwright install chromium")
        return None


async_playwright = _import_playwright()
PLAYWRIGHT_AVAILABLE = async_playwright is not None

_playwright = None
_browser = None
_browser_lock = asyncio.Lock()
_browser_uses = 0
_last_used = 0.0
_active_renders = 0

_MAX_BROWSER_USES = 1000
_BROWSER_IDLE_TTL = 3600

# Page pool for reuse (avoids context/page creation overhead per render)
_page_pool: asyncio.Queue = asyncio.Queue()
_pool_ctx = None
_pool_generation = 0  # Incremented on browser restart to invalidate stale pages

_FONT_CSS_NAME = "fonts.css"
_FONTS_DIR = TEMP_PATH / "fonts"


def _get_font_css_url() -> str:
    url = WutheringWavesConfig.get_config("FontCssUrl").data
    if not url or not str(url).strip():
        return WW_CONFIG_DEFAULT["FontCssUrl"].data
    return url


def _mount_fonts() -> None:
    try:
        for route in fastapi_app.routes:
            if getattr(route, "path", None) == "/waves/fonts":
                return
        if _FONTS_DIR.exists():
            fastapi_app.mount(
                "/waves/fonts",
                CORSStaticFiles(directory=_FONTS_DIR),
                name="wwuid_fonts",
            )
        logger.debug("[鸣潮·渲染工具] 已挂载字体静态路由 (CORS Enabled)")
    except Exception as e:
        logger.warning(f"[鸣潮·渲染工具] 挂载字体静态路由失败: {e}")


def _get_local_base_url() -> str:
    host = core_config.get_config("HOST") or CONFIG_DEFAULT["HOST"]
    port = core_config.get_config("PORT") or CONFIG_DEFAULT["PORT"]
    if host in ("0.0.0.0", "0.0.0.0:"):
        host = "127.0.0.1"
    return f"http://{host}:{port}"


_mount_fonts()


async def _ensure_browser():
    """Get a reusable browser instance; restart periodically to bound memory."""
    global _playwright, _browser, _browser_uses, _last_used, _active_renders
    global _pool_ctx, _pool_generation

    if not PLAYWRIGHT_AVAILABLE or async_playwright is None:
        return None

    async with _browser_lock:
        now = time.monotonic()

        if _browser is not None and not _browser.is_connected():
            try:
                await _browser.close()
            except Exception:
                pass
            _browser = None

        need_restart = (
            _browser is None
            or _browser_uses >= _MAX_BROWSER_USES
            or (_last_used > 0 and now - _last_used > _BROWSER_IDLE_TTL)
        )

        if need_restart and _browser is not None and _active_renders > 0:
            need_restart = False

        if need_restart:
            if _browser is not None:
                try:
                    await _browser.close()
                except Exception:
                    pass
                _browser = None

            # Invalidate page pool (old pages belong to dead browser)
            _pool_ctx = None
            _pool_generation += 1
            # Drain stale pages
            while not _page_pool.empty():
                try:
                    _page_pool.get_nowait()
                except asyncio.QueueEmpty:
                    break

            if _playwright is None:
                _playwright = await async_playwright().start()

            _browser = await _playwright.chromium.launch(
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                    "--no-zygote",
                    "--renderer-process-limit=1",
                ]
            )
            _browser_uses = 0

        _last_used = now
        return _browser


_pool_lock = asyncio.Lock()


async def _acquire_page():
    """Get a reusable page from the pool, or create a new one."""
    global _pool_ctx, _active_renders

    browser = await _ensure_browser()
    if browser is None:
        return None, -1

    async with _pool_lock:
        gen = _pool_generation

        # Try to reuse a pooled page
        while not _page_pool.empty():
            try:
                page, page_gen = _page_pool.get_nowait()
                if page_gen == gen and not page.is_closed():
                    _active_renders += 1
                    return page, gen
            except asyncio.QueueEmpty:
                break

        # Create shared context if needed (rare, only first time)
        ctx_closed = _pool_ctx is None
        if not ctx_closed:
            try:
                ctx_closed = _pool_ctx._impl_obj._is_closed
            except AttributeError:
                # Playwright 版本不支持 _is_closed，尝试创建页面来检测
                ctx_closed = True
        if ctx_closed:
            _pool_ctx = await browser.new_context(
                viewport={"width": 1200, "height": 1000}
            )

    # Create page outside lock — allows parallel page creation
    page = await _pool_ctx.new_page()
    _active_renders += 1
    return page, _pool_generation


async def _release_page(page, gen: int):
    """Return a page to the pool for reuse, or discard if stale."""
    global _active_renders, _browser_uses, _last_used

    _active_renders = max(0, _active_renders - 1)
    _browser_uses += 1
    _last_used = time.monotonic()

    if gen == _pool_generation and not page.is_closed():
        await _page_pool.put((page, gen))
    else:
        try:
            await page.close()
        except Exception:
            pass


async def _render_via_remote(html_content: str, remote_url: str) -> Optional[bytes]:
    """使用外置渲染服务渲染 HTML"""
    start_time = time.time()
    try:
        logger.debug(f"[鸣潮·渲染工具] 尝试使用外置渲染服务: {remote_url}")

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                remote_url,
                json={"html": html_content},
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 200:
                image_data = response.content
                elapsed_time = time.time() - start_time
                html_kb = len(html_content) / 1024
                logger.info(f"[鸣潮·渲染工具] 外置渲染成功，耗时: {elapsed_time:.2f}s，HTML大小: {html_kb:.1f}KB，图片大小: {len(image_data)} bytes")
                return image_data
            else:
                logger.warning(f"[鸣潮·渲染工具] 外置渲染失败，状态码: {response.status_code}, 错误: {response.text}")
                return None
    except httpx.TimeoutException:
        elapsed_time = time.time() - start_time
        logger.warning(f"[鸣潮·渲染工具] 外置渲染超时 ({elapsed_time:.2f}s)，将回退到本地渲染")
        return None
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.warning(f"[鸣潮·渲染工具] 外置渲染异常 ({elapsed_time:.2f}s): {e}，将回退到本地渲染")
        return None


async def render_html(waves_templates, template_name: str, context: dict) -> Optional[bytes]:

    try:
        logger.debug(f"[鸣潮·渲染工具] HTML渲染开始: {template_name}")

        template = waves_templates.get_template(template_name)

        remote_render_enable = WutheringWavesConfig.get_config("RemoteRenderEnable").data
        remote_url = WutheringWavesConfig.get_config("RemoteRenderUrl").data if remote_render_enable else None

        if remote_render_enable and remote_url:
            try:
                font_css_url = _get_font_css_url()
                context["font_css_url"] = font_css_url
                html_content = template.render(**context)
                logger.debug(f"[鸣潮·渲染工具] 使用在线字体渲染 HTML: {template_name}")
                logger.debug(f"[鸣潮·渲染工具] 外置渲染已启用，尝试使用: {remote_url}")
                remote_result = await _render_via_remote(html_content, remote_url)
                if remote_result is not None:
                    return remote_result

                logger.info("[鸣潮·渲染工具] 外置渲染失败，回退到本地渲染")
            except Exception as e:
                logger.warning(f"[鸣潮·渲染工具] 外置渲染异常: {e}，回退到本地渲染")

        try:
            font_css_path = _FONTS_DIR / _FONT_CSS_NAME
            base_url = _get_local_base_url()

            if font_css_path.exists():
                context["font_css_url"] = f"{base_url}/waves/fonts/{_FONT_CSS_NAME}"
            else:
                context["font_css_url"] = _get_font_css_url()

            html_content = template.render(**context)
            logger.debug(f"[鸣潮·渲染工具] 使用本地字体渲染 HTML: {template_name}")
        except Exception as e:
            logger.error(f"[鸣潮·渲染工具] Template render failed: {e}")
            raise e

        # 本地渲染
        if not PLAYWRIGHT_AVAILABLE or async_playwright is None:
            logger.warning("[鸣潮·渲染工具] Playwright 未安装，无法渲染，将回退到 PIL 渲染（如有）")
            return None

        logger.debug(f"[鸣潮·渲染工具] 使用本地 Playwright 渲染")

        local_start_time = time.time()
        page, gen = None, -1
        try:
            t0 = time.perf_counter()
            page, gen = await _acquire_page()
            if page is None:
                return None
            t_acquire = time.perf_counter() - t0

            t0 = time.perf_counter()
            await page.set_content(html_content, wait_until='load')
            t_content = time.perf_counter() - t0

            t0 = time.perf_counter()
            container = page.locator(".container")
            await page.wait_for_selector(".container", timeout=2000)
            size = await container.evaluate(
                """(el) => {
                    const rect = el.getBoundingClientRect();
                    const width = Math.ceil(Math.max(rect.width, el.scrollWidth));
                    const height = Math.ceil(Math.max(rect.height, el.scrollHeight));
                    return { width, height };
                }"""
            )

            if size and size.get("width") and size.get("height"):
                await page.set_viewport_size(
                    {
                        "width": max(1, int(size["width"])),
                        "height": max(1, int(size["height"])),
                    }
                )
            t_layout = time.perf_counter() - t0

            t0 = time.perf_counter()
            screenshot = await container.screenshot(type='jpeg', quality=90)
            t_screenshot = time.perf_counter() - t0

            render_time = time.time() - local_start_time
            html_mb = len(html_content) / 1024 / 1024
            reused = "复用" if t_acquire < 0.01 else "新建"
            logger.info(
                f"[鸣潮·渲染工具] 渲染完成({reused}) {render_time:.2f}s | "
                f"传输HTML({html_mb:.1f}MB)={t_content*1000:.0f}ms "
                f"布局={t_layout*1000:.0f}ms 截图={t_screenshot*1000:.0f}ms"
            )
            return screenshot
        except Exception as e:
            logger.error(f"[鸣潮·渲染工具] Playwright execution failed: {e}")
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
                page = None
            raise e
        finally:
            if page is not None:
                await _release_page(page, gen)

    except Exception as e:
        logger.error(f"[鸣潮·渲染工具] HTML渲染失败: {e}")
        return None


def image_to_base64(image_path: Union[str, Path]) -> str:
    if not isinstance(image_path, Path):
        image_path = Path(image_path)
    if not image_path.exists():
        return ""
    try:
        with open(image_path, "rb") as f:
            data = f.read()
        ext = image_path.suffix.lstrip(".").lower()
        if ext == "jpg":
            ext = "jpeg"
        return f"data:image/{ext};base64,{base64.b64encode(data).decode('utf-8')}"
    except Exception as e:
        logger.warning(f"[鸣潮·渲染工具] 图片转 base64 失败: {image_path}, {e}")
        return ""


def get_logo_b64() -> Optional[str]:
    try:
        logo_path = TEMP_PATH / "imgs" / "kurobbs.png"

        if not logo_path.exists():
            return None

        with open(logo_path, "rb") as f:
            data = f.read()
            return f"data:image/png;base64,{base64.b64encode(data).decode('utf-8')}"
    except Exception as e:
        logger.warning(f"[鸣潮·渲染工具] Logo loading failed: {e}")
        return None


def get_footer_b64(footer_type: str = "black") -> Optional[str]:
    try:
        from pathlib import Path

        current_file_path = Path(__file__).resolve()
        footer_path = current_file_path.parent / "texture2d" / f"footer_{footer_type}.png"

        if not footer_path.exists():
            if footer_type == "black":
                footer_path = current_file_path.parent / "texture2d" / "footer_white.png"
            else:
                footer_path = current_file_path.parent / "texture2d" / "footer_black.png"

        if not footer_path.exists():
            return None

        with open(footer_path, "rb") as f:
            data = f.read()
            return f"data:image/png;base64,{base64.b64encode(data).decode('utf-8')}"
    except Exception as e:
        logger.warning(f"[鸣潮·渲染工具] Footer loading failed: {e}")
        return None


@to_thread
def _bake_image_to_webp(
    local_path: Path, bake_path: Path, cover_size, quality: int
) -> bytes:
    from PIL import Image

    img = Image.open(local_path)
    if cover_size is not None:
        tw, th = cover_size
        scale = max(tw / img.width, th / img.height)
        new_w, new_h = int(img.width * scale), int(img.height * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - tw) // 2
        top = (new_h - th) // 2
        img = img.crop((left, top, left + tw, top + th))

    img.save(bake_path, "WEBP", quality=quality)
    with open(bake_path, "rb") as f:
        return f.read()


async def get_image_b64_with_cache(
    url: str, cache_path: Path, quality=None, cover_size: tuple = None,
) -> str:
    """下载图片并转为base64。

    quality: None=原图, >0=WebP有损压缩
    cover_size: (w, h) 模拟 object-fit:cover 居中裁切到指定尺寸
    """
    if not url:
        return ""

    try:
        from .image import pic_download_from_url
        from .resource.RESOURCE_PATH import BAKE_PATH
        from PIL import Image
        from io import BytesIO

        await pic_download_from_url(cache_path, url)

        filename = url.split("/")[-1]
        local_path = cache_path / filename
        # pic_download_from_url 会将图片转为 webp 并删除原文件
        webp_path = local_path.with_suffix(".webp")
        if not local_path.exists() and webp_path.exists():
            local_path = webp_path

        # 不压缩也不裁切，直接返回原图
        if quality is None and cover_size is None:
            ext = local_path.suffix.lstrip(".").lower()
            if ext == "jpg":
                ext = "jpeg"
            with open(local_path, "rb") as f:
                data = f.read()
            return f"data:image/{ext};base64,{base64.b64encode(data).decode('utf-8')}"

        # 烘焙缓存: bake/{文件名}_{路径hash}_{quality}_{宽x高}.webp
        import hashlib
        path_hash = hashlib.md5(str(local_path.resolve()).encode()).hexdigest()[:8]
        stem = Path(filename).stem
        size_tag = f"_{cover_size[0]}x{cover_size[1]}" if cover_size else ""
        bake_name = f"{stem}_{path_hash}_q{quality or 80}{size_tag}.webp"
        bake_path = BAKE_PATH / bake_name

        # 命中烘焙缓存 — 直接读文件 + base64，跳过 PIL
        if bake_path.exists() and bake_path.stat().st_mtime >= local_path.stat().st_mtime:
            with open(bake_path, "rb") as f:
                data = f.read()
            return f"data:image/webp;base64,{base64.b64encode(data).decode('utf-8')}"

        # 未命中 — PIL 处理 + 写入烘焙缓存（卸到线程池）
        data = await _bake_image_to_webp(local_path, bake_path, cover_size, quality or 80)

        orig_size = local_path.stat().st_size
        logger.debug(
            f"[鸣潮·渲染工具] 烘焙: {filename} → {bake_name}, "
            f"原始: {orig_size} bytes, 烘焙后: {len(data)} bytes"
        )

        return f"data:image/webp;base64,{base64.b64encode(data).decode('utf-8')}"

    except Exception as e:
        logger.warning(f"[鸣潮·渲染工具] 获取图片 base64 失败: {url}, {e}")
        return ""
