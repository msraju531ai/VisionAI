import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, Enum,
    JSON,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    location = Column(String(256), nullable=False)
    rtsp_url = Column(String(512), nullable=False)
    is_active = Column(Boolean, default=True)
    resolution_w = Column(Integer, default=1920)
    resolution_h = Column(Integer, default=1080)
    fps = Column(Integer, default=15)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    zones = relationship("Zone", back_populates="camera", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="camera", cascade="all, delete-orphan")


class Zone(Base):
    __tablename__ = "zones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False)
    name = Column(String(128), nullable=False)
    zone_type = Column(
        Enum("restricted", "work_area", "walkway", "equipment", "entry_exit", name="zone_type_enum"),
        nullable=False,
    )
    polygon_points = Column(JSON, nullable=False, comment="List of [x,y] normalised coordinates")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    camera = relationship("Camera", back_populates="zones")


class ShiftSchedule(Base):
    __tablename__ = "shift_schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)
    start_time = Column(String(5), nullable=False, comment="HH:MM 24-hr format")
    end_time = Column(String(5), nullable=False)
    days_of_week = Column(JSON, nullable=False, comment='e.g. ["mon","tue","wed","thu","fri"]')
    expected_min_workers = Column(Integer, default=1)
    expected_supervisor_walkthroughs = Column(Integer, default=2)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False)
    event_type = Column(
        Enum(
            "unauthorized_presence", "unauthorized_absence", "idle_time",
            "shift_deviation", "supervisor_walkthrough", "anomaly",
            name="event_type_enum",
        ),
        nullable=False,
    )
    severity = Column(Enum("low", "medium", "high", "critical", name="severity_enum"), default="medium")
    description = Column(Text, nullable=True)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True)
    frame_path = Column(String(512), nullable=True)
    metadata_json = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    is_acknowledged = Column(Boolean, default=False)

    camera = relationship("Camera", back_populates="events")
    zone = relationship("Zone")
    alerts = relationship("Alert", back_populates="event", cascade="all, delete-orphan")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    channel = Column(Enum("email", "webhook", "sms", "dashboard", name="alert_channel_enum"), nullable=False)
    recipient = Column(String(256), nullable=False)
    status = Column(Enum("pending", "sent", "failed", name="alert_status_enum"), default="pending")
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    event = relationship("Event", back_populates="alerts")


class IncidentSummary(Base):
    __tablename__ = "incident_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    summary_text = Column(Text, nullable=False)
    event_count = Column(Integer, default=0)
    camera_ids = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class PipelineRun(Base):
    """Tracks each execution of the analysis pipeline for observability."""
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False)
    started_at = Column(DateTime, default=datetime.datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    frames_processed = Column(Integer, default=0)
    detections = Column(Integer, default=0)
    anomalies_found = Column(Integer, default=0)
    status = Column(Enum("running", "completed", "failed", name="pipeline_status_enum"), default="running")
    error_message = Column(Text, nullable=True)


class Employee(Base):
    __tablename__ = "demo_employees"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True, index=True)
    image_path = Column(String(512), nullable=True)
    embedding = Column(JSON, nullable=False, comment="Face embedding as list[float]")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    detections = relationship("DemoDetection", back_populates="employee", cascade="all, delete-orphan")


class DemoVideo(Base):
    __tablename__ = "demo_videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    original_filename = Column(String(256), nullable=False)
    video_path = Column(String(512), nullable=False)
    status = Column(
        Enum("uploaded", "processing", "completed", "failed", name="demo_video_status_enum"),
        default="uploaded",
        nullable=False,
    )
    error_message = Column(Text, nullable=True)
    processed_frames = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    detections = relationship("DemoDetection", back_populates="video", cascade="all, delete-orphan")


class DemoDetection(Base):
    __tablename__ = "demo_detections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, ForeignKey("demo_videos.id"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("demo_employees.id"), nullable=False, index=True)
    timestamp_seconds = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    frame_index = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    metadata_json = Column(JSON, nullable=True)

    video = relationship("DemoVideo", back_populates="detections")
    employee = relationship("Employee", back_populates="detections")


class UnauthorizedDemoVideo(Base):
    __tablename__ = "unauthorized_demo_videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    original_filename = Column(String(256), nullable=False)
    video_path = Column(String(512), nullable=False)
    output_video_path = Column(String(512), nullable=True)
    status = Column(String(32), default="uploaded")
    error_message = Column(Text, nullable=True)
    processed_frames = Column(Integer, default=0)
    total_samples = Column(Integer, nullable=True)
    outcome_status = Column(String(16), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    events = relationship("UnauthorizedEntryEvent", back_populates="video", cascade="all, delete-orphan")


class UnauthorizedEntryEvent(Base):
    __tablename__ = "unauthorized_entry_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, ForeignKey("unauthorized_demo_videos.id"), nullable=False, index=True)
    timestamp_seconds = Column(Float, nullable=False)
    confidence = Column(Float, nullable=True)
    frame_index = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    video = relationship("UnauthorizedDemoVideo", back_populates="events")


class IdleDemoVideo(Base):
    __tablename__ = "idle_demo_videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    original_filename = Column(String(256), nullable=False)
    video_path = Column(String(512), nullable=False)
    output_video_path = Column(String(512), nullable=True)
    status = Column(String(32), default="uploaded")
    error_message = Column(Text, nullable=True)
    processed_frames = Column(Integer, default=0)
    total_samples = Column(Integer, nullable=True)
    video_start_at = Column(DateTime, nullable=True)
    outcome_status = Column(String(16), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    events = relationship("IdleEvent", back_populates="video", cascade="all, delete-orphan")


class IdleEvent(Base):
    __tablename__ = "idle_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, ForeignKey("idle_demo_videos.id"), nullable=False, index=True)
    employee_id = Column(Integer, ForeignKey("demo_employees.id"), nullable=True, index=True)
    start_ts_seconds = Column(Float, nullable=False)
    end_ts_seconds = Column(Float, nullable=False)
    duration_seconds = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    video = relationship("IdleDemoVideo", back_populates="events")
    employee = relationship("Employee")


class EmployeeDetection(Base):
    __tablename__ = "employee_detections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, ForeignKey("demo_employees.id"), nullable=False, index=True)
    camera_id = Column(Integer, nullable=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    confidence = Column(Float, nullable=False)

    employee = relationship("Employee")


class EmployeeAttendance(Base):
    __tablename__ = "employee_attendance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, ForeignKey("demo_employees.id"), nullable=False, index=True)
    date = Column(String(10), nullable=False, index=True, comment="YYYY-MM-DD")
    first_seen = Column(DateTime, nullable=False)
    last_seen = Column(DateTime, nullable=False)
    total_minutes = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    employee = relationship("Employee")


class WorkSchedule(Base):
    __tablename__ = "work_schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, ForeignKey("demo_employees.id"), nullable=False, unique=True, index=True)
    expected_start_time = Column(String(5), nullable=False, comment="HH:MM")
    expected_end_time = Column(String(5), nullable=False, comment="HH:MM")
    grace_minutes = Column(Integer, default=10)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    employee = relationship("Employee")


class AttendanceCompliance(Base):
    __tablename__ = "attendance_compliance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, ForeignKey("demo_employees.id"), nullable=False, index=True)
    date = Column(String(10), nullable=False, index=True, comment="YYYY-MM-DD")
    status = Column(
        Enum("compliant", "late", "early_exit", "absent", name="attendance_status_enum"),
        nullable=False,
        default="absent",
    )
    deviation_minutes = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    employee = relationship("Employee")
