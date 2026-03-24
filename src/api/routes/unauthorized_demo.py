from __future__ import annotations

import datetime
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db_session import get_db
from src.models.database import UnauthorizedDemoVideo, UnauthorizedEntryEvent
from src.services.unauthorized_demo_processor import UnauthorizedDemoProcessor
from src.utils.youtube_downloader import download_youtube_video


router = APIRouter(tags=["Unauthorized Demo"])
templates = Jinja2Templates(directory="templates")

_processor = UnauthorizedDemoProcessor()

_BASE_DIR = Path("data") / "demo" / "unauthorized"
_VID_DIR = _BASE_DIR / "videos"
_OUT_DIR = _BASE_DIR / "outputs"


def _ensure_dirs() -> None:
    _VID_DIR.mkdir(parents=True, exist_ok=True)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)


def _safe_unlink(path: Path, allowed_base: Path) -> None:
    try:
        base = allowed_base.resolve()
        target = path.resolve()
        if base not in target.parents and base != target:
            return
        if target.exists() and target.is_file():
            target.unlink()
    except Exception:
        return


def _range_stream(request: Request, file_path: Path, media_type: str):
    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        def iterfile():
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk

        return StreamingResponse(
            iterfile(),
            media_type=media_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Content-Disposition": "inline",
            },
            status_code=200,
        )

    m = re.match(r"bytes=(\d*)-(\d*)", range_header)
    if not m:
        raise HTTPException(status_code=416, detail="Invalid Range")

    start_s, end_s = m.groups()
    start = int(start_s) if start_s else 0
    end = int(end_s) if end_s else file_size - 1
    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        raise HTTPException(status_code=416, detail="Range Not Satisfiable")

    length = end - start + 1

    def iter_range():
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        iter_range(),
        media_type=media_type,
        status_code=206,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(length),
            "Content-Disposition": "inline",
        },
    )


@router.get("/demo/unauthorized", response_class=HTMLResponse)
async def unauthorized_demo_page(request: Request, db: AsyncSession = Depends(get_db)):
    error = request.query_params.get("err")
    videos = (
        await db.execute(select(UnauthorizedDemoVideo).order_by(UnauthorizedDemoVideo.created_at.desc()))
    ).scalars().all()

    # latest event per video (if any)
    events: dict[int, UnauthorizedEntryEvent] = {}
    for v in videos:
        ev = (
            await db.execute(
                select(UnauthorizedEntryEvent)
                .where(UnauthorizedEntryEvent.video_id == v.id)
                .order_by(UnauthorizedEntryEvent.created_at.asc())
                .limit(1)
            )
        ).scalars().first()
        if ev is not None:
            events[v.id] = ev

    return templates.TemplateResponse(
        "unauthorized_demo.html",
        {
            "request": request,
            "error": error,
            "videos": videos,
            "events": events,
        },
    )


@router.get("/demo/unauthorized/status")
async def unauthorized_demo_status(db: AsyncSession = Depends(get_db)):
    videos = (
        await db.execute(select(UnauthorizedDemoVideo).order_by(UnauthorizedDemoVideo.created_at.desc()))
    ).scalars().all()

    out = []
    for v in videos:
        ev = (
            await db.execute(
                select(UnauthorizedEntryEvent)
                .where(UnauthorizedEntryEvent.video_id == v.id)
                .order_by(UnauthorizedEntryEvent.created_at.asc())
                .limit(1)
            )
        ).scalars().first()

        out.append(
            {
                "id": v.id,
                "original_filename": v.original_filename,
                "status": v.status,
                "outcome_status": getattr(v, "outcome_status", None),
                "processed_frames": v.processed_frames,
                "total_samples": getattr(v, "total_samples", None),
                "started_at": v.started_at.isoformat() if v.started_at else None,
                "finished_at": v.finished_at.isoformat() if v.finished_at else None,
                "first_unauthorized_time": ev.timestamp_seconds if ev else None,
                "output_available": bool(v.output_video_path),
            }
        )

    return {"videos": out}


@router.post("/demo/unauthorized/videos")
async def upload_unauthorized_video(
    video: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    _ensure_dirs()

    raw = await video.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty video upload")

    ext = Path(video.filename or "video.mp4").suffix.lower() or ".mp4"
    safe_stem = "unauthorized_" + datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = _VID_DIR / f"{safe_stem}{ext}"

    with open(out_path, "wb") as f:
        f.write(raw)

    rec = UnauthorizedDemoVideo(
        original_filename=video.filename or out_path.name,
        video_path=str(out_path),
        status="uploaded",
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)

    _processor.start_background(rec.id)
    return RedirectResponse(url="/demo/unauthorized", status_code=303)


@router.post("/demo/unauthorized/clear")
async def clear_unauthorized_videos(db: AsyncSession = Depends(get_db)):
    _ensure_dirs()
    videos = (
        await db.execute(select(UnauthorizedDemoVideo).order_by(UnauthorizedDemoVideo.created_at.desc()))
    ).scalars().all()

    for v in videos:
        if v.video_path:
            _safe_unlink(Path(v.video_path), _VID_DIR)
        if v.output_video_path:
            _safe_unlink(Path(v.output_video_path), _OUT_DIR)
        await db.delete(v)

    await db.commit()
    return RedirectResponse(url="/demo/unauthorized", status_code=303)


@router.post("/demo/unauthorized/videos/youtube")
async def upload_unauthorized_video_from_youtube(
    youtube_url: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    _ensure_dirs()

    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    basename = f"youtube_{ts}"

    try:
        res = download_youtube_video(youtube_url, output_dir=_VID_DIR, basename=basename)
    except FileNotFoundError:
        return RedirectResponse(url="/demo/unauthorized?err=yt-dlp%20not%20installed", status_code=303)
    except Exception as e:
        raw = str(e).replace("\n", " ")
        hint = raw
        if "ffmpeg" in raw.lower() and "not found" in raw.lower():
            hint = "ffmpeg not found. Install ffmpeg and ensure it is on PATH, then try again. " + raw
        msg = quote(hint)
        return RedirectResponse(url=f"/demo/unauthorized?err={msg}", status_code=303)

    original = f"{res.title}.mp4"
    rec = UnauthorizedDemoVideo(
        original_filename=original,
        video_path=str(res.file_path),
        status="uploaded",
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)

    _processor.start_background(rec.id)
    return RedirectResponse(url="/demo/unauthorized", status_code=303)


@router.get("/demo/unauthorized/videos/{video_id}/output")
async def get_unauthorized_output_video(video_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    v = (await db.execute(select(UnauthorizedDemoVideo).where(UnauthorizedDemoVideo.id == video_id))).scalar_one_or_none()
    if v is None:
        raise HTTPException(status_code=404, detail="Video not found")
    if not v.output_video_path:
        raise HTTPException(status_code=404, detail="Output not available")

    path = Path(v.output_video_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Output file missing")

    try:
        base = _OUT_DIR.resolve()
        target = path.resolve()
        if base not in target.parents and base != target:
            raise HTTPException(status_code=403, detail="Invalid output path")
    except RuntimeError:
        raise HTTPException(status_code=403, detail="Invalid output path")

    return _range_stream(request, target, media_type="video/mp4")
