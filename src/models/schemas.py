from __future__ import annotations

import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Camera ──

class CameraCreate(BaseModel):
    name: str
    location: str
    rtsp_url: str
    resolution_w: int = 1920
    resolution_h: int = 1080
    fps: int = 15

class CameraUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    rtsp_url: Optional[str] = None
    is_active: Optional[bool] = None
    resolution_w: Optional[int] = None
    resolution_h: Optional[int] = None
    fps: Optional[int] = None

class CameraOut(BaseModel):
    id: int
    name: str
    location: str
    rtsp_url: str
    is_active: bool
    resolution_w: int
    resolution_h: int
    fps: int
    created_at: datetime.datetime
    model_config = {"from_attributes": True}


# ── Zone ──

class ZoneCreate(BaseModel):
    camera_id: int
    name: str
    zone_type: str = Field(..., pattern="^(restricted|work_area|walkway|equipment|entry_exit)$")
    polygon_points: list[list[float]] = Field(..., min_length=3, description="Normalised [x,y] vertices")

class ZoneOut(BaseModel):
    id: int
    camera_id: int
    name: str
    zone_type: str
    polygon_points: list[list[float]]
    is_active: bool
    model_config = {"from_attributes": True}


# ── Shift Schedule ──

class ShiftScheduleCreate(BaseModel):
    name: str
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    days_of_week: list[str]
    expected_min_workers: int = 1
    expected_supervisor_walkthroughs: int = 2

class ShiftScheduleOut(BaseModel):
    id: int
    name: str
    start_time: str
    end_time: str
    days_of_week: list[str]
    expected_min_workers: int
    expected_supervisor_walkthroughs: int
    is_active: bool
    model_config = {"from_attributes": True}


# ── Event ──

class EventOut(BaseModel):
    id: int
    camera_id: int
    event_type: str
    severity: str
    description: Optional[str] = None
    zone_id: Optional[int] = None
    frame_path: Optional[str] = None
    metadata_json: Optional[dict] = None
    timestamp: datetime.datetime
    is_acknowledged: bool
    model_config = {"from_attributes": True}

class EventQuery(BaseModel):
    camera_id: Optional[int] = None
    event_type: Optional[str] = None
    severity: Optional[str] = None
    start_time: Optional[datetime.datetime] = None
    end_time: Optional[datetime.datetime] = None
    limit: int = Field(50, le=500)
    offset: int = 0


# ── Alert ──

class AlertOut(BaseModel):
    id: int
    event_id: int
    channel: str
    recipient: str
    status: str
    sent_at: Optional[datetime.datetime] = None
    created_at: datetime.datetime
    model_config = {"from_attributes": True}


# ── Incident Summary ──

class IncidentSummaryOut(BaseModel):
    id: int
    period_start: datetime.datetime
    period_end: datetime.datetime
    summary_text: str
    event_count: int
    camera_ids: Optional[list[int]] = None
    created_at: datetime.datetime
    model_config = {"from_attributes": True}


# ── Dashboard ──

class DashboardStats(BaseModel):
    active_cameras: int
    total_events_today: int
    unacknowledged_alerts: int
    anomalies_last_hour: int
    cameras_online: list[CameraOut]
    recent_events: list[EventOut]


# ── Pipeline ──

class PipelineStatus(BaseModel):
    camera_id: int
    camera_name: str
    status: str
    frames_processed: int = 0
    detections: int = 0
    anomalies_found: int = 0
    started_at: Optional[datetime.datetime] = None


# ── Config ──

class ThresholdConfig(BaseModel):
    idle_threshold_seconds: Optional[int] = None
    shift_deviation_threshold: Optional[float] = None
    alert_cooldown_seconds: Optional[int] = None
    yolo_confidence_threshold: Optional[float] = None
    frame_sample_interval: Optional[int] = None
