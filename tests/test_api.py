import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_create_and_list_cameras(client: AsyncClient):
    payload = {
        "name": "Test Cam 1",
        "location": "Warehouse A",
        "rtsp_url": "rtsp://192.168.1.100:554/stream",
    }
    resp = await client.post("/api/cameras/", json=payload)
    assert resp.status_code == 201
    cam = resp.json()
    assert cam["name"] == "Test Cam 1"
    assert cam["is_active"] is True

    resp = await client.get("/api/cameras/")
    assert resp.status_code == 200
    cameras = resp.json()
    assert len(cameras) >= 1


@pytest.mark.asyncio
async def test_create_zone(client: AsyncClient):
    cam_resp = await client.post("/api/cameras/", json={
        "name": "Zone Test Cam",
        "location": "Floor 1",
        "rtsp_url": "rtsp://localhost/test",
    })
    cam_id = cam_resp.json()["id"]

    zone_resp = await client.post("/api/zones/", json={
        "camera_id": cam_id,
        "name": "Restricted Area",
        "zone_type": "restricted",
        "polygon_points": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5], [0.1, 0.5]],
    })
    assert zone_resp.status_code == 201
    assert zone_resp.json()["zone_type"] == "restricted"


@pytest.mark.asyncio
async def test_get_thresholds(client: AsyncClient):
    resp = await client.get("/api/config/thresholds")
    assert resp.status_code == 200
    data = resp.json()
    assert "idle_threshold_seconds" in data
    assert "yolo_confidence_threshold" in data


@pytest.mark.asyncio
async def test_create_shift(client: AsyncClient):
    resp = await client.post("/api/shifts/", json={
        "name": "Night Shift",
        "start_time": "22:00",
        "end_time": "06:00",
        "days_of_week": ["mon", "tue", "wed", "thu", "fri"],
        "expected_min_workers": 3,
        "expected_supervisor_walkthroughs": 2,
    })
    assert resp.status_code == 201
    assert resp.json()["name"] == "Night Shift"


@pytest.mark.asyncio
async def test_events_empty_initially(client: AsyncClient):
    resp = await client.get("/api/events/")
    assert resp.status_code == 200
    assert resp.json() == []
