"""
Shared FastAPI dependencies — DB sessions and singleton service instances.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db_session import get_db
from src.services.video_ingestion import VideoIngestionService
from src.services.frame_processor import FrameProcessor
from src.services.person_detector import PersonDetector
from src.services.activity_analyzer import ActivityAnalyzer
from src.services.zone_manager import ZoneManager
from src.services.anomaly_detector import AnomalyDetector
from src.services.alert_service import AlertService
from src.services.event_logger import EventLogger
from src.services.incident_summarizer import IncidentSummarizer
from src.core.scheduler import ShiftScheduler

# Singletons (created once, reused across requests)
_ingestion = VideoIngestionService()
_frame_processor = FrameProcessor()
_person_detector = PersonDetector()
_activity_analyzer = ActivityAnalyzer()
_zone_manager = ZoneManager()
_shift_scheduler = ShiftScheduler()
_anomaly_detector = AnomalyDetector(_activity_analyzer, _zone_manager, _shift_scheduler)


def get_ingestion() -> VideoIngestionService:
    return _ingestion

def get_frame_processor() -> FrameProcessor:
    return _frame_processor

def get_person_detector() -> PersonDetector:
    return _person_detector

def get_activity_analyzer() -> ActivityAnalyzer:
    return _activity_analyzer

def get_zone_manager() -> ZoneManager:
    return _zone_manager

def get_shift_scheduler() -> ShiftScheduler:
    return _shift_scheduler

def get_anomaly_detector() -> AnomalyDetector:
    return _anomaly_detector

async def get_event_logger(db: AsyncSession = Depends(get_db)) -> EventLogger:
    return EventLogger(db)

async def get_alert_service(db: AsyncSession = Depends(get_db)) -> AlertService:
    return AlertService(db)

async def get_incident_summarizer(db: AsyncSession = Depends(get_db)) -> IncidentSummarizer:
    return IncidentSummarizer(db)
