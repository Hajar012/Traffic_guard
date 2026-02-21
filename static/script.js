// =============================
// HELPERS
// =============================
function hide(viewName) {
  const btn = document.querySelector(`.menu-item[data-view="${viewName}"]`);
  if (btn) btn.style.display = "none";
}

// =============================
// SIDEBAR VIEW SWITCHING
// =============================
const menuItems = document.querySelectorAll('.menu-item');
const views = document.querySelectorAll('.view');

menuItems.forEach(item => {
  item.addEventListener('click', () => {
    const viewName = item.getAttribute('data-view');

    menuItems.forEach(i => i.classList.remove('active'));
    item.classList.add('active');

    views.forEach(v => {
      v.classList.toggle('active', v.id === `view-${viewName}`);
    });
  });
});

// =============================
// LIVE CLOCK
// =============================
function updateClock() {
  const now = new Date();

  const time = now.toLocaleTimeString('en-GB', { hour12: false });
  const date = now.toLocaleDateString('en-GB', {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    year: 'numeric'
  });

  const clockEl = document.querySelector('.time');
  if (clockEl) clockEl.textContent = `${time} — ${date}`;
}

setInterval(updateClock, 1000);
updateClock();


// =============================
// TRAFFIC CHART (Chart.js)
// =============================
let trafficChart;

async function loadTrafficData() {
  const canvas = document.getElementById('trafficChart');
  if (!canvas) return;

  const response = await fetch('/traffic_data');
  const data = await response.json();

  const ctx = canvas.getContext('2d');

  if (trafficChart) {
    trafficChart.data.labels = data.labels;
    trafficChart.data.datasets[0].data = data.vehicles;
    trafficChart.data.datasets[1].data = data.alerts;
    trafficChart.update();
    return;
  }

  trafficChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.labels,
      datasets: [
        {
          label: 'Vehicles Detected',
          data: data.vehicles,
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59, 130, 246, 0.15)',
          borderWidth: 2,
          tension: 0.4,
          pointRadius: 0
        },
        {
          label: 'Alerts Generated',
          data: data.alerts,
          borderColor: '#ef4444',
          backgroundColor: 'rgba(239, 68, 68, 0.15)',
          borderWidth: 2,
          tension: 0.4,
          pointRadius: 0,
          yAxisID: 'y1'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true },
        y1: {
          beginAtZero: true,
          position: 'right',
          grid: { drawOnChartArea: false }
        }
      },
      plugins: { legend: { display: false } }
    }
  });
}

setInterval(loadTrafficData, 5000);
loadTrafficData();


// =============================
// LIVE MAP (Leaflet) - FIXED (no duplicates)
// =============================
let map = null;
let deviceMarkers = {};

function initMapOnce() {
  if (map) return;

  const el = document.getElementById('riyadhMap');
  if (!el) return;

  map = L.map('riyadhMap').setView([24.7136, 46.6753], 12);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '©️ OpenStreetMap'
  }).addTo(map);
}

async function updateDeviceMarkers() {
  if (!map) return;

  const response = await fetch('/device_status');
  const devices = await response.json();

  devices.forEach(device => {
    const { id, lat, lon, status } = device;
    const color = status === "Online" ? "green" : "red";

    const icon = L.divIcon({
      className: "device-icon",
      html: `<div style="
        width:14px;height:14px;border-radius:50%;
        background:${color};border:2px solid white;
        box-shadow:0 0 6px rgba(0,0,0,0.4);
      "></div>`
    });

    if (deviceMarkers[id]) {
      deviceMarkers[id].setLatLng([lat, lon]);
      deviceMarkers[id].setIcon(icon);
    } else {
      deviceMarkers[id] = L.marker([lat, lon], { icon })
        .addTo(map)
        .bindPopup(`<b>${id}</b><br>Status: ${status}`);
    }
  });
}

// Load map when user clicks Live Map
const liveMapBtn = document.querySelector('[data-view="liveMap"]');
if (liveMapBtn) {
  liveMapBtn.addEventListener('click', () => {
    setTimeout(() => {
      initMapOnce();
      updateDeviceMarkers();
    }, 300);
  });
}

// Update markers periodically
setInterval(() => {
  if (map) updateDeviceMarkers();
}, 5000);


// =============================
// ALERTS (Upgraded Workflow)
// =============================
let alertsCache = [];
let selectedAlertId = null;

function statusPill(status) {
  const map = {
    Pending:   { label: "Pending", cls: "pill pill-orange" },
    Verified:  { label: "Verified", cls: "pill pill-green" },
    FalseAlarm:{ label: "False Alarm", cls: "pill pill-red" },
    Resolved:  { label: "Resolved", cls: "pill pill-gray" }
  };
  const s = map[status] || map.Pending;
  return `<span class="${s.cls}" style="margin-left:10px">${s.label}</span>`;
}

async function loadAlerts() {
  const response = await fetch('/alerts_data');
  alertsCache = await response.json();


  alertsCache = alertsCache.map(a => ({ ...a, status: a.status || "Pending" }));

  renderAlertList();

  if (selectedAlertId) {
    const found = alertsCache.find(a => a.id === selectedAlertId);
    if (found) showAlertDetails(found);
  }
}

function renderAlertList() {
  const list = document.getElementById('alertList');
  if (!list) return;

  list.innerHTML = '';

  alertsCache.forEach(alert => {
    const row = document.createElement('div');
    row.className = 'alert-row';

    if (alert.id === selectedAlertId) row.classList.add('active');

    row.innerHTML = `
      <div>
        <p class="alert-title">${alert.title} ${statusPill(alert.status)}</p>
        <p class="alert-meta">${alert.location}</p>
      </div>
      <span class="status-badge ${alert.severity}">${alert.severity_label}</span>
    `;

    row.onclick = () => showAlertDetails(alert);
    list.appendChild(row);
  });
}

function showAlertDetails(alert) {
  selectedAlertId = alert.id;
  renderAlertList();

  const details = document.getElementById('alertDetails');
  if (!details) return;

  const canAct = (alert.status === "Pending" || alert.status === "Verified");
  const canResolve = (alert.status === "Verified");

  details.innerHTML = `
    <h4 style="margin-bottom:8px">${alert.title}</h4>

    <div style="display:flex;gap:10px;align-items:center;margin-bottom:10px;flex-wrap:wrap">
      ${statusPill(alert.status)}
      <span class="status-badge ${alert.severity}">${alert.severity_label}</span>
    </div>

    <p><strong>Location:</strong> ${alert.location}</p>
    <p><strong>Time:</strong> ${alert.time}</p>
    <p><strong>Description:</strong> ${alert.description}</p>

    <div style="display:flex;gap:10px;margin-top:14px;flex-wrap:wrap">
      <button id="btnVerify" class="action-btn" ${canAct ? "" : "disabled"}>Verify</button>
      <button id="btnFalse" class="action-btn danger" ${canAct ? "" : "disabled"}>False Alarm</button>
      <button id="btnResolve" class="action-btn success" ${canResolve ? "" : "disabled"}>Resolve</button>
    </div>

    <p id="alertMsg" class="muted" style="margin-top:10px"></p>
  `;

  const btnVerify = document.getElementById("btnVerify");
  const btnFalse = document.getElementById("btnFalse");
  const btnResolve = document.getElementById("btnResolve");

  if (btnVerify) btnVerify.onclick = () => updateAlertStatus(alert.id, "Verified");
  if (btnFalse) btnFalse.onclick = () => updateAlertStatus(alert.id, "FalseAlarm");
  if (btnResolve) btnResolve.onclick = () => updateAlertStatus(alert.id, "Resolved");
}

async function updateAlertStatus(alertId, newStatus) {
  const msg = document.getElementById("alertMsg");
  if (msg) msg.textContent = "Updating...";

  try {
    const res = await fetch('/alerts_update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: alertId, status: newStatus })
    });

    if (!res.ok) throw new Error("Server error");

    const updated = await res.json();

    alertsCache = alertsCache.map(a => (a.id === updated.id ? updated : a));
    renderAlertList();

    const current = alertsCache.find(a => a.id === updated.id);
    if (current) showAlertDetails(current);

    if (msg) msg.textContent = "Updated successfully.";
  } catch (e) {
    if (msg) msg.textContent = "Failed to update. Add /alerts_update in Flask.";
  }
}

// Load alerts when Alerts page is opened
const alertsBtn = document.querySelector('[data-view="alerts"]');
if (alertsBtn) {
  alertsBtn.addEventListener('click', () => {
    loadAlerts();
  });
}


// =============================
// EDGE DEVICES FILTER
// =============================
function filterDevices() {
  const input = document.getElementById("deviceSearch");
  const activeBtn = document.querySelector(".filter-btn.active");
  if (!input || !activeBtn) return;

  const searchValue = input.value.toLowerCase();
  const filter = activeBtn.dataset.filter;

  document.querySelectorAll(".device-row").forEach(row => {
    const id = (row.dataset.id || "").toLowerCase();
    const location = (row.dataset.location || "").toLowerCase();
    const status = row.dataset.status;

    const matchesSearch = id.includes(searchValue) || location.includes(searchValue);
    const matchesFilter = (filter === "all" || filter === status);

    row.style.display = (matchesSearch && matchesFilter) ? "flex" : "none";
  });
}

const deviceSearch = document.getElementById("deviceSearch");
if (deviceSearch) deviceSearch.addEventListener("input", filterDevices);

document.querySelectorAll(".filter-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const current = document.querySelector(".filter-btn.active");
    if (current) current.classList.remove("active");
    btn.classList.add("active");
    filterDevices();
  });
});


// =============================
// MODEL PERFORMANCE CHART
// =============================
const perfCanvas = document.getElementById('performanceChart');
if (perfCanvas) {
  new Chart(perfCanvas, {
    type: 'line',
    data: {
      labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
      datasets: [{
        label: 'Accuracy (%)',
        data: [92.5, 93.1, 93.8, 94.0, 94.2],
        borderColor: '#6366f1',
        backgroundColor: 'rgba(99,102,241,0.2)',
        tension: 0.4,
        borderWidth: 3,
        fill: true
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: false, min: 90, max: 100 } }
    }
  });
}


// =============================
// ROLE BASED UI (basic hide)
// =============================
if (typeof userRole !== "undefined" && userRole === "Guest") {
  hide("edgeDevices");
  hide("modelPerformance");
  hide("analytics");
  hide("settings");
}