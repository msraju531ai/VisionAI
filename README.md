# VisionAI — AI-Powered Video Surveillance Analytics

Real-time video analysis platform for manufacturing and warehouse environments.  
Detects anomalous behaviour, monitors worker activity, and generates actionable alerts.

## Features
test
- **RTSP Camera Ingestion** — connects to IP cameras via RTSP/ONVIF
- **YOLOv8 Person Detection** — real-time person detection on sampled frames
- **Activity Tracking** — centroid-based tracker detects idle time and movement patterns
- **Zone Management** — define restricted, work, equipment, and walkway zones per camera
- **Shift Scheduling** — enforce expected staffing levels per shift (day/night)
- **Anomaly Detection** — unauthorized presence, absence, idle workers, shift deviations
- **Timestamped Alerts** — email, webhook, and dashboard notifications with cooldown
- **AI Incident Summaries** — LLM-generated management reports (OpenAI) with template fallback
- **Searchable Event Logs** — filter by camera, type, severity, and time range
- **Live Dashboard** — dark-themed web UI with real-time stats, camera controls, event table
- **Runtime Tuning** — adjust confidence, idle thresholds, and alert cooldowns via API
- **Docker Ready** — CPU and GPU (NVIDIA) compose profiles

## Quick Start

```bash
# 1. Clone & enter project
cd vision-ai

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy & edit config
copy .env.example .env       # Windows
# cp .env.example .env       # Linux/Mac

# 5. Seed sample data
python -m scripts.seed_data

# 6. Run the server
python run.py
```

Open http://localhost:8000 for the dashboard.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET/POST/PATCH/DELETE | `/api/cameras/` | CRUD for cameras |
| GET/POST/DELETE | `/api/zones/` | CRUD for detection zones |
| GET/POST | `/api/shifts/` | Shift schedule management |
| GET | `/api/shifts/current` | Current active shift |
| GET | `/api/events/` | Search events (filterable) |
| GET | `/api/events/count` | Event count |
| POST | `/api/events/{id}/acknowledge` | Acknowledge an event |
| GET | `/api/alerts/` | List alerts |
| GET/PATCH | `/api/config/thresholds` | View/update detection thresholds |
| GET/POST | `/api/summaries/` | Incident summaries |
| POST | `/api/pipeline/start/{camera_id}` | Start analysis on a camera |
| POST | `/api/pipeline/stop/{camera_id}` | Stop analysis |
| POST | `/api/pipeline/start-all` | Start all active cameras |
| POST | `/api/pipeline/stop-all` | Stop all cameras |
| GET | `/api/pipeline/status` | Pipeline status per camera |
| GET | `/api/dashboard/stats` | Dashboard statistics |

## Project Structure

```
vision-ai/
├── config/             # App settings (pydantic-settings)
├── src/
│   ├── api/routes/     # FastAPI route handlers
│   ├── core/           # Pipeline orchestrator & scheduler
│   ├── models/         # SQLAlchemy models & Pydantic schemas
│   ├── services/       # Business logic
│   │   ├── video_ingestion.py
│   │   ├── frame_processor.py
│   │   ├── person_detector.py
│   │   ├── activity_analyzer.py
│   │   ├── zone_manager.py
│   │   ├── anomaly_detector.py
│   │   ├── alert_service.py
│   │   ├── incident_summarizer.py
│   │   └── event_logger.py
│   └── utils/
├── static/             # CSS & JS for dashboard
├── templates/          # Jinja2 HTML templates
├── tests/              # Pytest test suite
├── docker/             # Dockerfile & docker-compose
├── scripts/            # Seed data & utilities
├── data/               # SQLite DB, frames, video storage
├── requirements.txt
├── run.py              # Entry point
└── .env.example
```

## Docker

```bash
cd docker
docker-compose up --build
```

For GPU support, uncomment the `vision-ai-gpu` service in `docker-compose.yml`.

## Testing

```bash
pytest tests/ -v
```

## Tech Stack

- **FastAPI** + Uvicorn
- **YOLOv8** (Ultralytics) for person detection
- **OpenCV** for video ingestion & frame processing
- **SQLAlchemy** (async) + SQLite (swappable to PostgreSQL)
- **OpenAI** API for incident summaries (optional)
- **Jinja2** + vanilla JS dashboard

## Architecture Diagram
RTSP Cameras
    ↓
Frame Sampling (OpenCV)
    ↓
YOLOv8 Detection
    ↓
Tracking Layer
    ↓
Zone + Shift Logic
    ↓
Anomaly Engine
    ↓
Event & Alert Storage
    ↓
Dashboard / Email / Webhook

## Future Improvements

- 