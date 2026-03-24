from __future__ import annotations

import datetime
from pathlib import Path
from urllib.parse import quote

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db_session import get_db
from src.models.database import Employee, DemoVideo, DemoDetection
from src.services.employee_identifier import EmployeeIdentifier
from src.services.video_demo_processor import VideoDemoProcessor
from src.utils.youtube_downloader import download_youtube_video

router = APIRouter(tags=["Demo"])
templates = Jinja2Templates(directory="templates")

_identifier = EmployeeIdentifier()
_processor = VideoDemoProcessor()

_BASE_DIR = Path("data") / "demo"
_EMP_DIR = _BASE_DIR / "employees"
_VID_DIR = _BASE_DIR / "videos"


def _ensure_dirs() -> None:
    _EMP_DIR.mkdir(parents=True, exist_ok=True)
    _VID_DIR.mkdir(parents=True, exist_ok=True)


@router.get("/demo", response_class=HTMLResponse)
async def demo_page(
    request: Request,
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    error = request.query_params.get("err")
    employees = (await db.execute(select(Employee).order_by(Employee.created_at.desc()))).scalars().all()
    videos = (await db.execute(select(DemoVideo).order_by(DemoVideo.created_at.desc()))).scalars().all()

    page_size = 10
    ranked = (
        select(
            DemoDetection.id.label("det_id"),
            func.row_number()
            .over(
                partition_by=DemoDetection.video_id,
                order_by=DemoDetection.created_at.desc(),
            )
            .label("rn"),
        )
        .subquery()
    )

    filtered = select(ranked.c.det_id).where(ranked.c.rn <= 5).subquery()

    total = (await db.execute(select(func.count()).select_from(filtered))).scalar() or 0
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    offset = (page - 1) * page_size

    det_stmt = (
        select(DemoDetection, Employee, DemoVideo)
        .join(filtered, filtered.c.det_id == DemoDetection.id)
        .join(Employee, DemoDetection.employee_id == Employee.id)
        .join(DemoVideo, DemoDetection.video_id == DemoVideo.id)
        .order_by(DemoDetection.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    det_rows = (await db.execute(det_stmt)).all()
    detections = [
        {
            "employee_name": emp.name,
            "timestamp_seconds": det.timestamp_seconds,
            "confidence": det.confidence,
            "video_id": vid.id,
            "video_filename": vid.original_filename,
            "created_at": det.created_at,
        }
        for det, emp, vid in det_rows
    ]

    return templates.TemplateResponse(
        "demo.html",
        {
            "request": request,
            "error": error,
            "employees": employees,
            "videos": videos,
            "detections": detections,
            "page": page,
            "total_pages": total_pages,
        },
    )


@router.post("/demo/employees")
async def register_employee(
    name: str = Form(...),
    photo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    _ensure_dirs()

    existing = (await db.execute(select(Employee).where(Employee.name == name))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Employee name already exists")

    raw = await photo.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty photo upload")

    img_arr = np.frombuffer(raw, dtype=np.uint8)
    bgr = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise HTTPException(status_code=400, detail="Invalid image")

    emb_res = _identifier.detect_and_embed(bgr)
    if emb_res is None:
        raise HTTPException(status_code=400, detail="No face detected in uploaded photo")

    safe_name = "".join(c for c in name if c.isalnum() or c in ("-", "_", " ")).strip().replace(" ", "_")
    ext = Path(photo.filename or "photo.jpg").suffix.lower() or ".jpg"
    out_path = _EMP_DIR / f"{safe_name}{ext}"

    with open(out_path, "wb") as f:
        f.write(raw)

    emp = Employee(name=name, image_path=str(out_path), embedding=emb_res.embedding)
    db.add(emp)
    await db.commit()

    return RedirectResponse(url="/demo", status_code=303)


@router.post("/demo/videos/youtube")
async def upload_video_from_youtube(
    youtube_url: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    _ensure_dirs()

    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    basename = f"youtube_{ts}"

    try:
        res = download_youtube_video(youtube_url, output_dir=_VID_DIR, basename=basename)
    except FileNotFoundError:
        return RedirectResponse(url="/demo?err=yt-dlp%20not%20installed", status_code=303)
    except Exception as e:
        raw = str(e).replace("\n", " ")
        hint = raw
        if "ffmpeg" in raw.lower() and "not found" in raw.lower():
            hint = "ffmpeg not found. Install ffmpeg and ensure it is on PATH, then try again. " + raw
        msg = quote(hint)
        return RedirectResponse(url=f"/demo?err={msg}", status_code=303)

    original = f"{res.title}.mp4"
    demo_video = DemoVideo(original_filename=original, video_path=str(res.file_path), status="uploaded")
    db.add(demo_video)
    await db.commit()
    await db.refresh(demo_video)

    _processor.start_background(demo_video.id)
    return RedirectResponse(url="/demo", status_code=303)


@router.get("/demo/employees/{employee_id}/photo")
async def get_employee_photo(employee_id: int, db: AsyncSession = Depends(get_db)):
    emp = (await db.execute(select(Employee).where(Employee.id == employee_id))).scalar_one_or_none()
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    if not emp.image_path:
        raise HTTPException(status_code=404, detail="Employee photo not available")

    path = Path(emp.image_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Employee photo missing")

    try:
        base = _EMP_DIR.resolve()
        target = path.resolve()
        if base not in target.parents and base != target:
            raise HTTPException(status_code=403, detail="Invalid image path")
    except RuntimeError:
        raise HTTPException(status_code=403, detail="Invalid image path")

    ext = target.suffix.lower()
    media_type = "image/jpeg"
    if ext == ".png":
        media_type = "image/png"
    elif ext == ".webp":
        media_type = "image/webp"

    return FileResponse(str(target), media_type=media_type)


@router.get("/demo/videos/{video_id}/file")
async def get_demo_video_file(video_id: int, db: AsyncSession = Depends(get_db)):
    video = (await db.execute(select(DemoVideo).where(DemoVideo.id == video_id))).scalar_one_or_none()
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")

    path = Path(video.video_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Video file missing")

    try:
        base = _VID_DIR.resolve()
        target = path.resolve()
        if base not in target.parents and base != target:
            raise HTTPException(status_code=403, detail="Invalid video path")
    except RuntimeError:
        raise HTTPException(status_code=403, detail="Invalid video path")

    ext = target.suffix.lower()
    media_type = "video/mp4" if ext == ".mp4" else "video/x-msvideo"
    return FileResponse(str(target), media_type=media_type)


@router.post("/demo/videos")
async def upload_video(
    video: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    _ensure_dirs()

    filename = video.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in (".mp4", ".avi"):
        raise HTTPException(status_code=400, detail="Only .mp4 and .avi supported")

    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c for c in Path(filename).stem if c.isalnum() or c in ("-", "_"))
    out_path = _VID_DIR / f"{safe_name}_{ts}{ext}"

    with open(out_path, "wb") as f:
        while True:
            chunk = await video.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)

    demo_video = DemoVideo(original_filename=filename, video_path=str(out_path), status="uploaded")
    db.add(demo_video)
    await db.commit()
    await db.refresh(demo_video)

    _processor.start_background(demo_video.id)

    return RedirectResponse(url="/demo", status_code=303)
