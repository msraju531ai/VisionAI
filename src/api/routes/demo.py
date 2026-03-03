from __future__ import annotations

import datetime
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db_session import get_db
from src.models.database import Employee, DemoVideo, DemoDetection
from src.services.employee_identifier import EmployeeIdentifier
from src.services.video_demo_processor import VideoDemoProcessor

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
async def demo_page(request: Request, db: AsyncSession = Depends(get_db)):
    employees = (await db.execute(select(Employee).order_by(Employee.created_at.desc()))).scalars().all()
    videos = (await db.execute(select(DemoVideo).order_by(DemoVideo.created_at.desc()))).scalars().all()

    det_stmt = (
        select(DemoDetection, Employee, DemoVideo)
        .join(Employee, DemoDetection.employee_id == Employee.id)
        .join(DemoVideo, DemoDetection.video_id == DemoVideo.id)
        .order_by(DemoDetection.created_at.desc())
        .limit(200)
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
            "employees": employees,
            "videos": videos,
            "detections": detections,
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
