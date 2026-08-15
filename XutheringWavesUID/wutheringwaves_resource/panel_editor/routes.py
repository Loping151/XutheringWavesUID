"""FastAPI 路由入口 — 面板图编辑器。

路径前缀: /waves/panel-edit/
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import List, Optional

from PIL import Image

from fastapi import Depends, File, HTTPException, Request, UploadFile
from gsuid_core.logger import logger
from gsuid_core.web_app import app
from starlette.responses import FileResponse, HTMLResponse, Response

from .auth import (
    auth_or_guest,
    check_preview_rate,
    is_enabled,
    is_guest_view_enabled,
    require_auth,
    require_auth_strict,
    require_same_origin,
)
from . import storage as st


_STATIC_DIR = Path(__file__).parent / "static"

# 框选可超出原图(越界部分白色填充)后, 画布尺寸的安全上限, 防 OOM:
# 单边 ≤ 原图各边 3 倍且 ≤ 8000px; 同时总像素 ≤ 40MP(单边限幅挡不住极端长宽比)。
_MAX_CROP_DIM = 8000
_MAX_CROP_PIXELS = 40_000_000

# 禁止被他站 iframe 嵌套 (点击劫持: 管理员 Basic Auth 已缓存, 隐形 iframe 里的点击即操作)。
_FRAME_DENY = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


def _try_update_orb_cache(p: Path) -> None:
    try:
        from ...wutheringwaves_charinfo.card_utils import update_orb_cache
        update_orb_cache(p)
    except Exception as e:
        logger.debug(f"[鸣潮·面板编辑] 更新 ORB 缓存跳过: {e}")


def _try_delete_orb_cache(p: Path) -> None:
    try:
        from ...wutheringwaves_charinfo.card_utils import delete_orb_cache
        delete_orb_cache(p)
    except Exception:
        pass


def _index_add(t: str, char_id: str, p: Path) -> None:
    try:
        from ...wutheringwaves_charinfo import card_hash_index
        card_hash_index.add(t, char_id, p)
    except Exception as e:
        logger.debug(f"[鸣潮·面板编辑] hash 索引 add 跳过: {e}")


def _index_remove(t: str, char_id: str, p: Path) -> None:
    try:
        from ...wutheringwaves_charinfo import card_hash_index
        card_hash_index.remove(t, char_id, p)
    except Exception as e:
        logger.debug(f"[鸣潮·面板编辑] hash 索引 remove 跳过: {e}")


_DISABLED_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="UTF-8"/>
<meta name="robots" content="noindex,nofollow"/>
<meta name="referrer" content="no-referrer"/>
<title>面板图编辑器未启用</title>
<style>
  html,body{margin:0;height:100%;background:#07090d;color:#c7cdd9;
    font-family:-apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;}
  body{display:flex;align-items:center;justify-content:center;}
  .card{max-width:520px;padding:32px 36px;background:#11161e;
    border:1px solid #1d2533;border-radius:8px;line-height:1.6;}
  h1{margin:0 0 6px 0;font-size:14px;letter-spacing:.04em;color:#eef1f6;}
  p{margin:8px 0;color:#8b95a7;font-size:13px;}
  code,pre{font-family:"JetBrains Mono","SF Mono",Consolas,monospace;
    color:#7aa3ff;background:#161c26;padding:2px 6px;border-radius:4px;}
  pre{display:block;padding:12px 14px;color:#c7cdd9;font-size:12px;
    border:1px solid #1d2533;overflow:auto;}
  .tag{display:inline-block;padding:2px 8px;border-radius:999px;
    background:rgba(248,113,113,.12);color:#f87171;font-size:11px;
    letter-spacing:.08em;text-transform:uppercase;
    border:1px solid rgba(248,113,113,.3);}
</style></head><body><div class="card">
  <span class="tag">DISABLED</span>
  <h1>鸣潮 · 面板/背景图编辑台 未启用</h1>
  <p>请在 <code>WutheringWavesConfig</code> 控制台中设置配置项，赋值非空密码以启用该工具：</p>
  <pre>WavesPanelEditPassword = &lt;你的密码&gt;</pre>
  <p>设置完成并重启 / 刷新配置后再次访问本页面，会通过 HTTP Basic Auth 提示输入凭据（用户名固定为 <code>admin</code>）。</p>
</div></body></html>"""


# ------------------------- 前端 -------------------------


@app.get("/waves/panel-edit/")
async def panel_edit_index(request: Request):
    """入口页。
    - 未配置密码 → 提示页。
    - 配置后:
      - 访客模式开启 → 直接返 SPA, 不弹 Basic Auth, 由前端区分访客/管理员。
      - 否则要求 Basic Auth (401 让浏览器弹登录框)。
    """
    if not is_enabled():
        return HTMLResponse(_DISABLED_HTML, status_code=200)
    require_same_origin(request)
    if not is_guest_view_enabled():
        await require_auth(request)
    index = _STATIC_DIR / "index.html"
    if not index.exists():
        return HTMLResponse("<h1>Panel editor static files missing.</h1>", status_code=500)
    return FileResponse(index, media_type="text/html; charset=utf-8", headers=_FRAME_DENY)


@app.get("/waves/panel-edit/static/{name:path}")
async def panel_edit_static(name: str):
    """SPA 静态资源 (CSS/JS): 永远 public, 仅扁平文件名。
    内容公开 (开源), 无需鉴权; 访客模式下 SPA 本身要能加载。"""
    if not st.is_safe_name(name):
        raise HTTPException(404, "Not found")
    target = st.safe_join(_STATIC_DIR, name)
    if target is None or not target.is_file():
        raise HTTPException(404, "Not found")
    media_type = None
    if target.suffix == ".js":
        media_type = "application/javascript; charset=utf-8"
    elif target.suffix == ".css":
        media_type = "text/css; charset=utf-8"
    return FileResponse(target, media_type=media_type)


@app.get("/waves/panel-edit/api/login")
async def api_login(_: None = Depends(require_auth)):
    """仅用于强制弹 Basic Auth: 访客模式下前端"登录"按钮命中此处。"""
    return {"role": "admin"}


# ------------------------- 列表 -------------------------


@app.get("/waves/panel-edit/api/folders")
async def api_folders(type: str, role: str = Depends(auth_or_guest)):
    if not st.is_valid_type(type):
        raise HTTPException(400, "invalid type")
    folders = st.list_folders(type)
    if role == "admin":
        counts = st.pending_counts(type)
        for f in folders:
            f["pending"] = counts.get(f["char_id"], 0)
    return {"type": type, "folders": folders}


@app.get("/waves/panel-edit/api/images")
async def api_images(type: str, char_id: str, _: str = Depends(auth_or_guest)):
    folder = st.safe_char_dir(type, char_id)
    if folder is None:
        raise HTTPException(400, "invalid type or char_id")
    if not folder.exists():
        return {"type": type, "char_id": char_id, "images": []}
    from ...utils.name_convert import easy_id_to_name
    images = st.list_images(type, char_id)
    return {
        "type": type,
        "char_id": char_id,
        "char_name": easy_id_to_name(char_id, char_id),
        "images": images,
    }


# ------------------------- 缩略图 / 原图 -------------------------


_THUMB_SIZES = {180, 360, 720}


@app.get("/waves/panel-edit/api/thumb")
async def api_thumb(
    type: str,
    char_id: str,
    name: str,
    size: int = 360,
    _: str = Depends(auth_or_guest),
):
    # 缩略图档位收敛, 防 disk-fill: 只接受三档之一, 其它一律 360。
    if size not in _THUMB_SIZES:
        size = 360
    target = st.safe_target_image(type, char_id, name)
    if target is None or not target.is_file():
        raise HTTPException(404, "image not found")
    cache = st.get_or_make_thumb(target, size, type)
    if cache is None:
        return FileResponse(target)
    return FileResponse(cache, media_type="image/webp", headers={"Cache-Control": "max-age=86400"})


@app.get("/waves/panel-edit/api/image")
async def api_image(
    type: str,
    char_id: str,
    name: str,
    trim: int = 0,
    _: str = Depends(auth_or_guest),
):
    target = st.safe_target_image(type, char_id, name)
    if target is None or not target.is_file():
        raise HTTPException(404, "image not found")
    headers = {"Cache-Control": "no-store"}
    if trim and type == "card":
        from ...wutheringwaves_charinfo.card_utils import _trim_card_file
        img = await _trim_card_file(target)
        with Image.open(target) as orig:
            orig_size = orig.size
        if img is not None and img.size != orig_size:
            buf = BytesIO()
            ext = target.suffix.lower()
            if ext in (".jpg", ".jpeg"):
                img.convert("RGB").save(buf, "JPEG", quality=95)
                mt = "image/jpeg"
            elif ext == ".webp":
                img.save(buf, "WEBP", quality=95)
                mt = "image/webp"
            else:
                img.save(buf, "PNG")
                mt = "image/png"
            return Response(buf.getvalue(), media_type=mt, headers=headers)
    return FileResponse(target, headers=headers)


# ------------------------- 临时上传 / 裁剪 -------------------------


_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB 防手滑


async def _stage_upload(file: UploadFile) -> Optional[dict]:
    """读 + 校验 + 落盘一份 tmp; 失败返回 None；超大抛 413。"""
    raw = await file.read()
    if not raw:
        return None
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file too large (>{_MAX_UPLOAD_BYTES // 1024 // 1024}MB)")
    try:
        with Image.open(BytesIO(raw)) as im:
            im.load()
            w, h = im.size
    except Exception:
        return None
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in st.IMAGE_EXTS:
        suffix = ".jpg"
    token = st.new_tmp_token()
    st.write_tmp_image(token, suffix, raw)
    st.write_tmp_image(f"{token}.orig", suffix, raw)
    return {
        "token": token, "name": filename, "suffix": suffix,
        "width": w, "height": h, "size": len(raw),
    }


@app.post("/waves/panel-edit/api/tmp/upload")
async def api_tmp_upload(
    file: UploadFile = File(...),
    _: None = Depends(require_auth),
):
    """上传单文件到 tmp。返回 token, 后续操作 (裁剪/确认) 用它。"""
    st.gc_tmp()
    item = await _stage_upload(file)
    if not item:
        raise HTTPException(400, "not an image or empty file")
    return item


@app.post("/waves/panel-edit/api/tmp/upload-batch")
async def api_tmp_upload_batch(
    files: List[UploadFile] = File(...),
    _: None = Depends(require_auth),
):
    """批量上传到 tmp, 返回 token 列表。"""
    st.gc_tmp()
    out = []
    for f in files:
        item = await _stage_upload(f)
        if item:
            out.append(item)
    if not out:
        raise HTTPException(400, "no valid images")
    return {"items": out}


_LQ_WEBP_MAX_DIM = 16383  # WebP 编码尺寸上限


def _lq_webp(data: bytes) -> Optional[bytes]:
    """低清模式: 转同尺寸高压缩 WebP, 仅省传输; 失败/超限返回 None 由调用方回退原图。"""
    try:
        with Image.open(BytesIO(data)) as im:
            im.load()
            if max(im.size) > _LQ_WEBP_MAX_DIM:
                return None
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            out = BytesIO()
            im.save(out, "WEBP", quality=40)
            return out.getvalue()
    except Exception:
        logger.warning("[鸣潮·面板编辑] 低清转码失败, 回退原图")
        return None


@app.get("/waves/panel-edit/api/tmp/image")
async def api_tmp_image(token: str, lq: int = 0, _: None = Depends(require_auth)):
    if not st.is_safe_token(token):
        raise HTTPException(400, "invalid token")
    current, _orig = st.find_tmp_files(token)
    if current is None:
        raise HTTPException(404, "tmp not found")
    if lq:
        data = _lq_webp(current.read_bytes())
        if data is not None:
            return Response(data, media_type="image/webp",
                            headers={"Cache-Control": "no-store"})
    return FileResponse(current, headers={"Cache-Control": "no-store"})


@app.post("/waves/panel-edit/api/tmp/crop")
async def api_tmp_crop(
    payload: dict,
    _: None = Depends(require_auth),
):
    """对 tmp 图执行裁剪。
    payload: token; x,y,w,h = 相对【原图】的绝对像素坐标 (前端用 current 在原图内的 offset 换算),
    越界部分白色填充。始终从 original 裁, 故放大裁剪框能找回先前被裁掉的内容; current 仅是裁剪结果缓存。
    """
    token = payload.get("token")
    if not st.is_safe_token(token):
        raise HTTPException(400, "invalid token")
    try:
        x = int(round(float(payload["x"])))
        y = int(round(float(payload["y"])))
        w = int(round(float(payload["w"])))
        h = int(round(float(payload["h"])))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "x/y/w/h required and numeric")
    if w <= 0 or h <= 0:
        raise HTTPException(400, "invalid crop size")

    current, original = st.find_tmp_files(token)
    if current is None or original is None:
        raise HTTPException(404, "tmp not found")

    with Image.open(original) as im:
        im.load()
        ow, oh = im.size

        # 允许框选超出原图: 越界部分白色填充, 不再 clamp 到原图范围。仍限制画布尺寸防 OOM。
        if w > min(_MAX_CROP_DIM, ow * 3) or h > min(_MAX_CROP_DIM, oh * 3):
            raise HTTPException(400, "crop size too large")
        if w * h > _MAX_CROP_PIXELS:
            raise HTTPException(400, "crop size too large")

        is_jpeg = current.suffix.lower() in (".jpg", ".jpeg")
        keep_alpha = (not is_jpeg) and im.mode in ("RGBA", "LA", "P")
        mode = "RGBA" if keep_alpha else "RGB"
        fill = (255, 255, 255, 255) if keep_alpha else (255, 255, 255)
        canvas = Image.new(mode, (w, h), fill)

        # 原图与框选框的重叠区域(原图坐标系), 仅在有重叠时把对应内容贴回白底画布。
        ix0, iy0 = max(0, x), max(0, y)
        ix1, iy1 = min(ow, x + w), min(oh, y + h)
        if ix1 > ix0 and iy1 > iy0:
            region = im.crop((ix0, iy0, ix1, iy1))
            if region.mode != mode:
                region = region.convert(mode)
            canvas.paste(region, (ix0 - x, iy0 - y))
        cropped = canvas

    suffix = current.suffix
    out = BytesIO()
    if suffix.lower() in (".jpg", ".jpeg"):
        cropped.convert("RGB").save(out, "JPEG", quality=92)
    elif suffix.lower() == ".webp":
        cropped.save(out, "WEBP", quality=90)
    else:
        cropped.save(out, "PNG")
    current.write_bytes(out.getvalue())

    with Image.open(current) as im:
        nw, nh = im.size
    return {"token": token, "width": nw, "height": nh, "size": current.stat().st_size}


@app.post("/waves/panel-edit/api/tmp/restore")
async def api_tmp_restore(payload: dict, _: None = Depends(require_auth)):
    token = payload.get("token")
    if not st.is_safe_token(token):
        raise HTTPException(400, "invalid token")
    current, original = st.find_tmp_files(token)
    if current is None or original is None:
        raise HTTPException(404, "tmp not found")
    # 连后缀一并回退: compress 可能把 current 改成了 .webp, 避免还原后扩展名与内容错配。
    restored = current.with_suffix(original.suffix)
    if restored != current:
        current.unlink(missing_ok=True)
    restored.write_bytes(original.read_bytes())
    with Image.open(restored) as im:
        w, h = im.size
    return {"token": token, "width": w, "height": h, "size": restored.stat().st_size, "suffix": restored.suffix}


def _save_resized(p: Path, im: Image.Image) -> None:
    out = BytesIO()
    suffix = p.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        im.convert("RGB").save(out, "JPEG", quality=92)
    elif suffix == ".webp":
        im.save(out, "WEBP", quality=90)
    else:
        im.save(out, "PNG")
    p.write_bytes(out.getvalue())


@app.post("/waves/panel-edit/api/tmp/resize")
async def api_tmp_resize(payload: dict, _: None = Depends(require_auth)):
    """按 scale 倍率等比缩放 tmp 图; current 与 original 同步缩放。
    compress=true 时额外把 current 转 webp(q80, 同「压缩面板图」), original 保留原格式供再裁剪。
    """
    token = payload.get("token")
    if not st.is_safe_token(token):
        raise HTTPException(400, "invalid token")
    try:
        scale = float(payload.get("scale"))
    except (TypeError, ValueError):
        raise HTTPException(400, "scale required")
    if not (0.05 <= scale <= 8.0):
        raise HTTPException(400, "scale out of range (0.05 - 8.0)")
    compress = bool(payload.get("compress"))

    current, original = st.find_tmp_files(token)
    if current is None or original is None:
        raise HTTPException(404, "tmp not found")

    def _scale(p: Path):
        with Image.open(p) as im:
            im.load()
            nw = max(1, int(round(im.width * scale)))
            nh = max(1, int(round(im.height * scale)))
            if max(nw, nh) > _MAX_CROP_DIM or nw * nh > _MAX_CROP_PIXELS:
                raise HTTPException(400, "resize result too large")
            resized = im.resize((nw, nh), Image.Resampling.LANCZOS)
        _save_resized(p, resized)
        return nw, nh

    if abs(scale - 1.0) > 1e-6:
        ow, oh = _scale(original)
        cw, ch = _scale(current)
    else:
        with Image.open(original) as im:
            ow, oh = im.size
        with Image.open(current) as im:
            cw, ch = im.size

    if compress and current.suffix.lower() != ".webp":
        webp = current.with_suffix(".webp")
        with Image.open(current) as im:
            im.load()
            im.save(webp, "WEBP", quality=80, method=6)
        if webp != current:
            current.unlink(missing_ok=True)
        current = webp

    return {
        "token": token,
        "width": cw, "height": ch,
        "source_width": ow, "source_height": oh,
        "size": current.stat().st_size,
        "suffix": current.suffix,
    }


@app.post("/waves/panel-edit/api/tmp/discard")
async def api_tmp_discard(payload: dict, _: None = Depends(require_auth)):
    token = payload.get("token")
    if not st.is_safe_token(token):
        raise HTTPException(400, "invalid token")
    st.cleanup_tmp(token)
    return {"ok": True}


# ------------------------- 确认入库 / 编辑现有 -------------------------


# 与待审核(pending)图比对: 阈值更高, 且允许并存 2 张, 命中 ≥3 张才阻止 (避免误判)。
_PENDING_DUP_THRESHOLD = 0.95
_PENDING_DUP_BLOCK_AT = 3


def _dup_matches(dups, pending: bool) -> List[dict]:
    return [
        {"name": p.name, "hash_id": st.hash_id_for(p.name), "sim": round(float(sim), 3), "pending": pending}
        for p, sim in dups
    ]


async def _check_duplicates(t: str, char_id: str, image: Path) -> Optional[dict]:
    """与目标目录已有图 + 待审核图查重 (复用指令侧 ORB)。
    - 已有图: 任一 sim≥ORB_BLOCK_THRESHOLD 即阻止 (matches 含全部 ≥WARN 项)。
    - 待审核图: 阈值更高(_PENDING_DUP_THRESHOLD), 命中 ≥_PENDING_DUP_BLOCK_AT 张才阻止。
    阻止时返回 {matches:[{name,hash_id,sim,pending}]}; 否则 None。cv2 缺失静默放行。
    pending 图实时扫描不缓存 ORB, 删除/过审后自动移出匹配池。
    """
    try:
        from ...wutheringwaves_charinfo.card_utils import (
            ORB_BLOCK_THRESHOLD,
            cv2,
            duplicates_for_single,
        )
    except Exception:
        return None
    if cv2 is None:
        return None

    matches: List[dict] = []
    blocked = False

    char_dir = st.safe_char_dir(t, char_id)
    if char_dir is not None and char_dir.exists():
        dups = await asyncio.to_thread(duplicates_for_single, char_dir, image, as_type=t)
        if any(sim >= ORB_BLOCK_THRESHOLD for _, sim in dups):
            blocked = True
        matches += _dup_matches(dups, pending=False)

    pending_dir = st.PANEL_EDIT_PENDING / t / char_id
    if pending_dir.exists():
        pdups = await asyncio.to_thread(
            duplicates_for_single, pending_dir, image, _PENDING_DUP_THRESHOLD, as_type=t
        )
        if len(pdups) >= _PENDING_DUP_BLOCK_AT:
            blocked = True
        matches += _dup_matches(pdups, pending=True)

    return {"matches": matches} if blocked else None


@app.post("/waves/panel-edit/api/confirm")
async def api_confirm(payload: dict, _: None = Depends(require_auth)):
    """确认 tmp 文件入库。
    payload: { token, type, char_id, force? }
    force 缺省时先查重, 命中疑似重复返回 {duplicate:true, matches}, 不入库。
    """
    token = payload.get("token")
    target_type = payload.get("type")
    char_id = payload.get("char_id")
    force = bool(payload.get("force"))
    if not st.is_safe_token(token):
        raise HTTPException(400, "invalid token")
    if not st.is_valid_type(target_type or ""):
        raise HTTPException(400, "invalid type")
    if not st.is_safe_char_id(char_id):
        raise HTTPException(400, "invalid char_id")

    current, original = st.find_tmp_files(token)
    if current is None:
        raise HTTPException(404, "tmp not found")

    if not force:
        dup = await _check_duplicates(target_type, char_id, current)
        if dup:
            return {"ok": False, "duplicate": True, **dup}

    final = st.relocate_to_target(target_type, char_id, current, suffix_hint=current.suffix)
    _try_update_orb_cache(final)
    _index_add(target_type, char_id, final)
    if original is not None:
        try:
            original.unlink()
        except OSError:
            pass
    return {"ok": True, "name": final.name, "hash_id": st.hash_id_for(final.name)}


@app.post("/waves/panel-edit/api/replace-existing")
async def api_replace_existing(payload: dict, _: None = Depends(require_auth)):
    """用裁剪后的 tmp 内容覆盖一张已有图。删除旧图的 ORB 缓存, 重新生成。"""
    token = payload.get("token")
    target_type = payload.get("type")
    char_id = payload.get("char_id")
    name = payload.get("name")
    if not st.is_safe_token(token):
        raise HTTPException(400, "invalid token")
    if not st.is_valid_type(target_type or ""):
        raise HTTPException(400, "invalid type")
    if not st.is_safe_char_id(char_id):
        raise HTTPException(400, "invalid char_id")
    if not st.is_safe_name(name):
        raise HTTPException(400, "invalid name")

    current, _ = st.find_tmp_files(token)
    if current is None:
        raise HTTPException(404, "tmp not found")
    target = st.safe_target_image(target_type, char_id, name)
    if target is None or not target.is_file():
        raise HTTPException(404, "target image not found")

    _try_delete_orb_cache(target)
    target.write_bytes(current.read_bytes())
    _try_update_orb_cache(target)
    _index_add(target_type, char_id, target)

    st.cleanup_tmp(token)
    return {"ok": True, "name": target.name, "hash_id": st.hash_id_for(target.name)}


# ------------------------- 删除 (单/全部) -------------------------


@app.post("/waves/panel-edit/api/delete")
async def api_delete(payload: dict, _: None = Depends(require_auth)):
    target_type = payload.get("type")
    char_id = payload.get("char_id")
    name = payload.get("name")
    target = st.safe_target_image(target_type or "", char_id or "", name or "")
    if target is None or not target.is_file():
        raise HTTPException(404, "image not found")
    _try_delete_orb_cache(target)
    target.unlink()
    _index_remove(target_type, char_id, target)
    return {"ok": True}


# ------------------------- 全库查重 -------------------------


_dup_scan_lock = asyncio.Lock()


def _scan_all_duplicates(threshold: float) -> List[dict]:
    """遍历所有自定义图角色目录, 各目录内分组查重 (复用 find_duplicate_groups_in_dir)。"""
    from ...utils.name_convert import easy_id_to_name
    from ...wutheringwaves_charinfo.card_hash_index import compute_hash
    from ...wutheringwaves_charinfo.card_utils import find_duplicate_groups_in_dir

    char_dirs = [
        (t, d)
        for t, base in st.TYPE_PATHS.items() if base.exists()
        for d in sorted(base.iterdir(), key=lambda p: p.name) if d.is_dir()
    ]
    use_cores = max((os.cpu_count() or 1) - 2, 1)
    out: List[dict] = []
    with ThreadPoolExecutor(max_workers=use_cores) as ex:
        futs = {ex.submit(find_duplicate_groups_in_dir, d, threshold): (t, d) for t, d in char_dirs}
        for fut in as_completed(futs):
            t, d = futs[fut]
            char_id = d.name
            char_name = easy_id_to_name(char_id, char_id)
            for group, sim_map in fut.result():
                gs = sorted(group, key=lambda p: p.name)
                images = [{
                    "type": t, "char_id": char_id, "char_name": char_name,
                    "name": p.name, "hash_id": compute_hash(p.name),
                } for p in gs]
                pairs = []
                for i in range(len(gs)):
                    for j in range(i + 1, len(gs)):
                        s = sim_map.get((gs[i], gs[j])) or sim_map.get((gs[j], gs[i]))
                        if s is not None:
                            pairs.append({
                                "a": compute_hash(gs[i].name),
                                "b": compute_hash(gs[j].name),
                                "sim": round(float(s), 3),
                            })
                out.append({"images": images, "pairs": pairs})
    out.sort(key=lambda g: len(g["images"]), reverse=True)
    return out


@app.get("/waves/panel-edit/api/duplicates")
async def api_duplicates(threshold: float = 0.7, _: None = Depends(require_auth_strict)):
    try:
        from ...wutheringwaves_charinfo.card_utils import cv2
    except Exception:
        raise HTTPException(500, "charinfo 不可用")
    if cv2 is None:
        raise HTTPException(400, "未安装 opencv-python, 无法查重")
    if not (0.5 <= threshold <= 1.0):
        threshold = 0.7
    if _dup_scan_lock.locked():
        raise HTTPException(429, "查重进行中, 请稍候")
    async with _dup_scan_lock:
        groups = await asyncio.to_thread(_scan_all_duplicates, threshold)
    return {"threshold": threshold, "groups": groups}


# ------------------------- 待审核储存 -------------------------


@app.get("/waves/panel-edit/api/pending/list")
async def api_pending_list(_: None = Depends(require_auth)):
    return {"groups": st.list_pending()}


@app.get("/waves/panel-edit/api/pending/image")
async def api_pending_image(type: str, char_id: str, name: str, _: None = Depends(require_auth)):
    target = st.safe_pending_image(type, char_id, name)
    if target is None or not target.is_file():
        raise HTTPException(404, "pending not found")
    return FileResponse(target, headers={"Cache-Control": "no-store"})


@app.get("/waves/panel-edit/api/pending/thumb")
async def api_pending_thumb(
    type: str, char_id: str, name: str, size: int = 360, crop: int = 0,
    _: None = Depends(require_auth),
):
    # 默认按原图缩略(待审核浏览看完整内容); crop=1 时裁到角色卡可见区(查重展示与已入库图同口径)。
    if size not in _THUMB_SIZES:
        size = 360
    target = st.safe_pending_image(type, char_id, name)
    if target is None or not target.is_file():
        raise HTTPException(404, "pending not found")
    cache = st.get_or_make_thumb(target, size, type if crop else None)
    if cache is None:
        return FileResponse(target)
    return FileResponse(cache, media_type="image/webp", headers={"Cache-Control": "max-age=86400"})


@app.post("/waves/panel-edit/api/pending/stage")
async def api_pending_stage(payload: dict, _: None = Depends(require_auth)):
    """把待审核图复制进 tmp, 返回 token, 之后复用裁剪/确认流程。"""
    st.gc_tmp()
    item = st.stage_pending(
        payload.get("type") or "", payload.get("char_id") or "", payload.get("name") or "",
    )
    if item is None:
        raise HTTPException(404, "pending not found")
    return item


@app.post("/waves/panel-edit/api/pending/delete")
async def api_pending_delete(payload: dict, _: None = Depends(require_auth)):
    t = payload.get("type")
    char_id = payload.get("char_id")
    name = payload.get("name")
    if not st.delete_pending(t or "", char_id or "", name or ""):
        raise HTTPException(404, "pending not found")
    return {"ok": True}


# ------------------------- 预览 -------------------------


@app.get("/waves/panel-edit/api/preview")
async def api_preview(
    request: Request,
    type: str,
    char_id: str,
    name: str,
    renderer: str = "html",
    lq: int = 0,
    _: None = Depends(require_auth),
):
    """type=card -> 角色面板预览; type=bg/stamina -> MR 预览。
    访客不渲染 (走 require_auth), 避免占用 Playwright/CPU 资源。
    """
    check_preview_rate(request)
    from .preview import render_panel_preview, render_mr_preview, render_rank_preview

    target = st.safe_target_image(type, char_id, name)
    if target is None or not target.is_file():
        raise HTTPException(404, "image not found")

    try:
        if type == "card":
            data = await render_panel_preview(char_id, target)
        elif type == "stamina" and renderer == "rank":
            data = await render_rank_preview(char_id, target)
        else:
            use_html = renderer != "pil"
            role_kind = "bg" if type == "bg" else "stamina"
            data = await render_mr_preview(char_id, target, use_html=use_html, role_kind=role_kind)
    except Exception as e:
        logger.exception(f"[鸣潮·面板编辑] 预览渲染失败: {e}")
        raise HTTPException(500, f"render failed: {e}")
    if not data:
        raise HTTPException(500, "preview empty")
    if lq:
        lq_data = _lq_webp(data)
        if lq_data is not None:
            return Response(content=lq_data, media_type="image/webp", headers={"Cache-Control": "no-store"})
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/waves/panel-edit/api/preview-tmp")
async def api_preview_tmp(
    request: Request,
    type: str,
    char_id: str,
    token: str,
    renderer: str = "html",
    lq: int = 0,
    _: None = Depends(require_auth),
):
    """裁剪/上传过程中, 用 tmp 图渲染预览。"""
    check_preview_rate(request)
    from .preview import render_panel_preview, render_mr_preview, render_rank_preview

    if not st.is_valid_type(type):
        raise HTTPException(400, "invalid type")
    if not st.is_safe_char_id(char_id):
        raise HTTPException(400, "invalid char_id")
    if not st.is_safe_token(token):
        raise HTTPException(400, "invalid token")
    current, _orig = st.find_tmp_files(token)
    if current is None:
        raise HTTPException(404, "tmp not found")
    try:
        if type == "card":
            data = await render_panel_preview(char_id, current)
        elif type == "stamina" and renderer == "rank":
            data = await render_rank_preview(char_id, current)
        else:
            use_html = renderer != "pil"
            role_kind = "bg" if type == "bg" else "stamina"
            data = await render_mr_preview(char_id, current, use_html=use_html, role_kind=role_kind)
    except Exception as e:
        logger.exception(f"[鸣潮·面板编辑] tmp 预览渲染失败: {e}")
        raise HTTPException(500, f"render failed: {e}")
    if not data:
        raise HTTPException(500, "preview empty")
    if lq:
        lq_data = _lq_webp(data)
        if lq_data is not None:
            return Response(content=lq_data, media_type="image/webp", headers={"Cache-Control": "no-store"})
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ------------------------- 元数据: 类型 / 角色名 -------------------------


def _orb_available() -> bool:
    try:
        from ...wutheringwaves_charinfo.card_utils import cv2
        return cv2 is not None
    except Exception:
        return False


@app.get("/waves/panel-edit/api/meta")
async def api_meta(role: str = Depends(auth_or_guest)):
    """前端启动时拉取: 类型 / id->name / 当前角色 (admin|guest) / 待审核数 / 查重可用性。"""
    from ...utils.name_convert import ensure_data_loaded, id2name
    try:
        ensure_data_loaded()
    except Exception:
        pass
    return {
        "types": [
            {"key": "card", "label": "面板图 (custom_role_pile)", "preview": "panel"},
            {"key": "bg", "label": "MR 背景图 (custom_mr_bg)", "preview": "mr"},
            {"key": "stamina", "label": "MR 立绘 (custom_mr_role_pile)", "preview": "mr"},
        ],
        "id2name": dict(id2name),
        "role": role,
        "guest_view_enabled": is_guest_view_enabled(),
        "thumb_ver": st._THUMB_VERSION,
        "pending_count": st.pending_count() if role == "admin" else 0,
        "orb_available": _orb_available(),
    }
