from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    app_name: str = "VisionAI"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/vision_ai.db"

    # Video ingestion
    frame_sample_interval: int = Field(2, description="Seconds between sampled frames")
    max_concurrent_streams: int = 10
    video_storage_path: str = "./data/videos"
    frame_storage_path: str = "./data/frames"

    # YOLO
    yolo_model_path: str = "yolov8n.pt"
    yolo_confidence_threshold: float = 0.5
    yolo_device: str = "cpu"

    # Anomaly detection
    idle_threshold_seconds: int = 300
    unauthorized_zone_alert: bool = True
    shift_deviation_threshold: float = 0.3

    # Alerts
    alert_cooldown_seconds: int = 300
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_recipients: str = ""

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # GPU
    use_gpu: bool = False
    gpu_device_id: int = 0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def device(self) -> str:
        if self.use_gpu:
            return f"cuda:{self.gpu_device_id}"
        return self.yolo_device

    @property
    def base_dir(self) -> Path:
        return Path(__file__).resolve().parent.parent


settings = Settings()
