from __future__ import annotations

from fastapi import APIRouter

from config.settings import settings
from src.models.schemas import ThresholdConfig

router = APIRouter(prefix="/config", tags=["Configuration"])


@router.get("/thresholds", response_model=ThresholdConfig)
async def get_thresholds():
    return ThresholdConfig(
        idle_threshold_seconds=settings.idle_threshold_seconds,
        shift_deviation_threshold=settings.shift_deviation_threshold,
        alert_cooldown_seconds=settings.alert_cooldown_seconds,
        yolo_confidence_threshold=settings.yolo_confidence_threshold,
        frame_sample_interval=settings.frame_sample_interval,
    )


@router.patch("/thresholds", response_model=ThresholdConfig)
async def update_thresholds(payload: ThresholdConfig):
    """Runtime threshold tuning (does not persist across restarts — use .env for permanent changes)."""
    if payload.idle_threshold_seconds is not None:
        settings.idle_threshold_seconds = payload.idle_threshold_seconds
    if payload.shift_deviation_threshold is not None:
        settings.shift_deviation_threshold = payload.shift_deviation_threshold
    if payload.alert_cooldown_seconds is not None:
        settings.alert_cooldown_seconds = payload.alert_cooldown_seconds
    if payload.yolo_confidence_threshold is not None:
        settings.yolo_confidence_threshold = payload.yolo_confidence_threshold
    if payload.frame_sample_interval is not None:
        settings.frame_sample_interval = payload.frame_sample_interval
    return await get_thresholds()
