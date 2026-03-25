from __future__ import annotations

import datetime
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db_session import get_db
from src.models.database import IdleDemoVideo, IdleEvent, Employee, WorkSchedule, EmployeeAttendance, AttendanceCompliance
from src.services.idle_demo_processor import IdleDemoProcessor
from src.utils.youtube_downloader import download_youtube_video


router = APIRouter(tags=["Idle Demo"])
templates = Jinja2Templates(directory="templates")

_processor = IdleDemoProcessor()

_BASE_DIR = Path("data") / "demo" / "idle"
_VID_DIR = _BASE_DIR / "videos"
_OUT_DIR = _BASE_DIR / "outputs"


def _ensure_dirs() -> None:
    _VID_DIR.mkdir(parents=True, exist_ok=True)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)


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


@router.get("/demo/idle", response_class=HTMLResponse)
async def idle_demo_page(
    request: Request,
    vid_page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    error = request.query_params.get("err")

    # Video pagination — 5 per page
    vid_page_size = 5
    vid_total = (await db.execute(select(func.count()).select_from(IdleDemoVideo))).scalar() or 0
    vid_total_pages = max(1, (vid_total + vid_page_size - 1) // vid_page_size)
    vid_page = min(vid_page, vid_total_pages)
    vid_offset = (vid_page - 1) * vid_page_size
    videos = (
        await db.execute(
            select(IdleDemoVideo).order_by(IdleDemoVideo.created_at.desc()).offset(vid_offset).limit(vid_page_size)
        )
    ).scalars().all()

    employees = (await db.execute(select(Employee).order_by(Employee.name.asc()))).scalars().all()
    schedules = {
        s.employee_id: s
        for s in (await db.execute(select(WorkSchedule))).scalars().all()
    }

    events_by_video: dict[int, list[IdleEvent]] = {}
    compliance_by_video: dict[int, list[dict]] = {}
    for v in videos:
        evs = (
            await db.execute(
                select(IdleEvent)
                .where(IdleEvent.video_id == v.id)
                .order_by(IdleEvent.created_at.desc())
                .limit(10)
            )
        ).scalars().all()
        events_by_video[v.id] = evs

        items = []
        if getattr(v, "video_start_at", None) is not None:
            date_key = v.video_start_at.date().isoformat()
            for emp in employees:
                att = (
                    await db.execute(
                        select(EmployeeAttendance)
                        .where(EmployeeAttendance.employee_id == emp.id)
                        .where(EmployeeAttendance.date == date_key)
                    )
                ).scalar_one_or_none()
                comp = (
                    await db.execute(
                        select(AttendanceCompliance)
                        .where(AttendanceCompliance.employee_id == emp.id)
                        .where(AttendanceCompliance.date == date_key)
                    )
                ).scalar_one_or_none()

                if att is None and comp is None:
                    continue

                items.append(
                    {
                        "employee_id": emp.id,
                        "employee_name": emp.name,
                        "check_in": att.first_seen if att else None,
                        "check_out": att.last_seen if att else None,
                        "total_minutes": att.total_minutes if att else 0,
                        "status": comp.status if comp else "absent",
                        "deviation_minutes": comp.deviation_minutes if comp else 0,
                    }
                )

        compliance_by_video[v.id] = items

    return templates.TemplateResponse(
        "idle_demo.html",
        {
            "request": request,
            "error": error,
            "videos": videos,
            "employees": employees,
            "schedules": schedules,
            "events_by_video": events_by_video,
            "compliance_by_video": compliance_by_video,
            "vid_page": vid_page,
            "vid_total_pages": vid_total_pages,
        },
    )


@router.post("/demo/idle/videos")
async def upload_idle_video(
    video: UploadFile = File(...),
    video_start_at: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    _ensure_dirs()

    raw = await video.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty video upload")

    ext = Path(video.filename or "video.mp4").suffix.lower() or ".mp4"
    safe_stem = "idle_" + datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = _VID_DIR / f"{safe_stem}{ext}"

    with open(out_path, "wb") as f:
        f.write(raw)

    start_dt = None
    if video_start_at.strip():
        try:
            start_dt = datetime.datetime.strptime(video_start_at.strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return RedirectResponse(url="/demo/idle?err=Invalid%20Video%20Start%20DateTime%20(use%20YYYY-MM-DD%20HH:MM:SS)", status_code=303)

    rec = IdleDemoVideo(
        original_filename=video.filename or out_path.name,
        video_path=str(out_path),
        status="uploaded",
        video_start_at=start_dt,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)

    _processor.start_background(rec.id)
    return RedirectResponse(url="/demo/idle", status_code=303)


@router.post("/demo/idle/videos/youtube")
async def upload_idle_video_from_youtube(
    youtube_url: str = Form(...),
    video_start_at: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    _ensure_dirs()

    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    basename = f"youtube_{ts}"

    try:
        res = download_youtube_video(youtube_url, output_dir=_VID_DIR, basename=basename)
    except FileNotFoundError:
        return RedirectResponse(url="/demo/idle?err=yt-dlp%20not%20installed", status_code=303)
    except Exception as e:
        raw = str(e).replace("\n", " ")
        hint = raw
        if "ffmpeg" in raw.lower() and "not found" in raw.lower():
            hint = "ffmpeg not found. Install ffmpeg and ensure it is on PATH, then try again. " + raw
        msg = quote(hint)
        return RedirectResponse(url=f"/demo/idle?err={msg}", status_code=303)

    start_dt = None
    if video_start_at.strip():
        try:
            start_dt = datetime.datetime.strptime(video_start_at.strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return RedirectResponse(url="/demo/idle?err=Invalid%20Video%20Start%20DateTime%20(use%20YYYY-MM-DD%20HH:MM:SS)", status_code=303)

    original = f"{res.title}.mp4"
    rec = IdleDemoVideo(
        original_filename=original,
        video_path=str(res.file_path),
        status="uploaded",
        video_start_at=start_dt,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)

    _processor.start_background(rec.id)
    return RedirectResponse(url="/demo/idle", status_code=303)


@router.get("/demo/idle/videos/{video_id}/output")
async def get_idle_output_video(video_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    v = (await db.execute(select(IdleDemoVideo).where(IdleDemoVideo.id == video_id))).scalar_one_or_none()
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


@router.get("/demo/idle/status")
async def idle_demo_status(db: AsyncSession = Depends(get_db)):
    videos = (await db.execute(select(IdleDemoVideo).order_by(IdleDemoVideo.created_at.desc()))).scalars().all()
    out = []
    for v in videos:
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
                "video_start_at": v.video_start_at.isoformat() if getattr(v, "video_start_at", None) else None,
                "output_available": bool(v.output_video_path),
            }
        )
    return {"videos": out}


def _safe_unlink(path_str: str | None, allowed_base: Path) -> None:
    """Delete a file only if it resolves inside allowed_base."""
    if not path_str:
        return
    try:
        target = Path(path_str).resolve()
        base = allowed_base.resolve()
        if base in target.parents or base == target.parent:
            target.unlink(missing_ok=True)
    except Exception:
        pass


@router.post("/demo/idle/videos/clear")
async def clear_idle_videos(db: AsyncSession = Depends(get_db)):
    videos = (await db.execute(select(IdleDemoVideo))).scalars().all()
    for v in videos:
        _safe_unlink(v.video_path, _VID_DIR)
        _safe_unlink(v.output_video_path, _OUT_DIR)
        await db.delete(v)
    await db.commit()
    return RedirectResponse(url="/demo/idle", status_code=303)


@router.post("/demo/idle/videos/{video_id}/delete")
async def delete_idle_video(video_id: int, db: AsyncSession = Depends(get_db)):
    v = (await db.execute(select(IdleDemoVideo).where(IdleDemoVideo.id == video_id))).scalar_one_or_none()
    if v is None:
        raise HTTPException(status_code=404, detail="Video not found")
    _safe_unlink(v.video_path, _VID_DIR)
    _safe_unlink(v.output_video_path, _OUT_DIR)
    await db.delete(v)
    await db.commit()
    return RedirectResponse(url="/demo/idle", status_code=303)


@router.post("/demo/idle/schedule")
async def upsert_idle_schedule(
    employee_id: int = Form(...),
    expected_start_time: str = Form(...),
    expected_end_time: str = Form(...),
    grace_minutes: int = Form(10),
    db: AsyncSession = Depends(get_db),
):
    emp = (await db.execute(select(Employee).where(Employee.id == employee_id))).scalar_one_or_none()
    if emp is None:
        return RedirectResponse(url="/demo/idle?err=Employee%20not%20found", status_code=303)

    sched = (
        await db.execute(select(WorkSchedule).where(WorkSchedule.employee_id == employee_id))
    ).scalar_one_or_none()
    if sched is None:
        sched = WorkSchedule(
            employee_id=employee_id,
            expected_start_time=expected_start_time,
            expected_end_time=expected_end_time,
            grace_minutes=grace_minutes,
        )
        db.add(sched)
    else:
        sched.expected_start_time = expected_start_time
        sched.expected_end_time = expected_end_time
        sched.grace_minutes = grace_minutes
    await db.commit()

    return RedirectResponse(url="/demo/idle", status_code=303)
