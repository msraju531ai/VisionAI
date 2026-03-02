const API = '/api';

async function fetchJSON(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// ── Stats ──

async function loadStats() {
  try {
    const s = await fetchJSON(`${API}/dashboard/stats`);
    document.getElementById('stat-cameras').textContent = s.active_cameras;
    document.getElementById('stat-events').textContent = s.total_events_today;
    document.getElementById('stat-alerts').textContent = s.unacknowledged_alerts;
    document.getElementById('stat-anomalies').textContent = s.anomalies_last_hour;
  } catch (e) {
    console.error('Failed to load stats', e);
  }
}

// ── Cameras ──

async function loadCameras() {
  try {
    const cameras = await fetchJSON(`${API}/cameras/`);
    let statuses = {};
    try {
      const pipelineStatus = await fetchJSON(`${API}/pipeline/status`);
      pipelineStatus.forEach(p => { statuses[p.camera_id] = p; });
    } catch (_) {}

    const grid = document.getElementById('camera-list');
    grid.innerHTML = cameras.map(cam => {
      const ps = statuses[cam.id];
      const running = ps && ps.status === 'running';
      return `
        <div class="camera-card">
          <div class="cam-name">${cam.name}</div>
          <div class="cam-loc">${cam.location}</div>
          <div class="cam-status">
            <span class="dot ${running ? 'online' : 'offline'}"></span>
            ${running ? 'Analysing' : 'Idle'}
            ${ps ? ` — ${ps.frames_processed} frames, ${ps.detections} detections` : ''}
          </div>
          <div class="cam-actions">
            ${running
              ? `<button class="btn btn-danger btn-sm" onclick="stopCamera(${cam.id})">Stop</button>`
              : `<button class="btn btn-success btn-sm" onclick="startCamera(${cam.id})">Start</button>`
            }
          </div>
        </div>`;
    }).join('');
  } catch (e) {
    console.error('Failed to load cameras', e);
  }
}

async function startCamera(id) {
  await fetchJSON(`${API}/pipeline/start/${id}`, { method: 'POST' });
  loadCameras();
}

async function stopCamera(id) {
  await fetchJSON(`${API}/pipeline/stop/${id}`, { method: 'POST' });
  loadCameras();
}

async function startAll() {
  await fetchJSON(`${API}/pipeline/start-all`, { method: 'POST' });
  loadCameras();
}

async function stopAll() {
  await fetchJSON(`${API}/pipeline/stop-all`, { method: 'POST' });
  loadCameras();
}

// ── Events ──

async function loadEvents() {
  const type = document.getElementById('filter-type').value;
  const severity = document.getElementById('filter-severity').value;
  let url = `${API}/events/?limit=50`;
  if (type) url += `&event_type=${type}`;
  if (severity) url += `&severity=${severity}`;

  try {
    const events = await fetchJSON(url);
    const tbody = document.getElementById('events-body');
    tbody.innerHTML = events.map(e => `
      <tr>
        <td>${new Date(e.timestamp).toLocaleString()}</td>
        <td>Camera ${e.camera_id}</td>
        <td>${e.event_type.replace(/_/g, ' ')}</td>
        <td><span class="severity-badge severity-${e.severity}">${e.severity}</span></td>
        <td>${e.description || '-'}</td>
        <td>
          ${e.is_acknowledged
            ? '<span style="color:var(--success)">Acked</span>'
            : `<button class="btn btn-primary btn-sm" onclick="ackEvent(${e.id})">Ack</button>`
          }
        </td>
      </tr>`
    ).join('');
  } catch (e) {
    console.error('Failed to load events', e);
  }
}

async function ackEvent(id) {
  await fetchJSON(`${API}/events/${id}/acknowledge`, { method: 'POST' });
  loadEvents();
  loadStats();
}

// ── Config ──

async function loadConfig() {
  try {
    const cfg = await fetchJSON(`${API}/config/thresholds`);
    document.getElementById('cfg-idle').value = cfg.idle_threshold_seconds;
    document.getElementById('cfg-deviation').value = cfg.shift_deviation_threshold;
    document.getElementById('cfg-cooldown').value = cfg.alert_cooldown_seconds;
    document.getElementById('cfg-confidence').value = cfg.yolo_confidence_threshold;
    document.getElementById('cfg-interval').value = cfg.frame_sample_interval;
  } catch (e) {
    console.error('Failed to load config', e);
  }
}

async function saveConfig(event) {
  event.preventDefault();
  const body = {
    idle_threshold_seconds: parseInt(document.getElementById('cfg-idle').value),
    shift_deviation_threshold: parseFloat(document.getElementById('cfg-deviation').value),
    alert_cooldown_seconds: parseInt(document.getElementById('cfg-cooldown').value),
    yolo_confidence_threshold: parseFloat(document.getElementById('cfg-confidence').value),
    frame_sample_interval: parseInt(document.getElementById('cfg-interval').value),
  };
  await fetchJSON(`${API}/config/thresholds`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  alert('Thresholds saved');
}

// ── Section Toggle ──

function showSection(name) {
  document.querySelectorAll('.nav-links a').forEach(a => a.classList.remove('active'));
  ['cameras', 'events', 'config'].forEach(s => {
    const el = document.getElementById(`section-${s}`);
    if (el) el.classList.toggle('hidden', s !== name);
  });
  document.getElementById('stats-grid').classList.toggle('hidden', name === 'config');
  event.target.classList.add('active');
  if (name === 'config') loadConfig();
}

// ── Init ──

document.addEventListener('DOMContentLoaded', () => {
  loadStats();
  loadCameras();
  loadEvents();
  setInterval(loadStats, 15000);
  setInterval(loadCameras, 20000);
  setInterval(loadEvents, 30000);
});
