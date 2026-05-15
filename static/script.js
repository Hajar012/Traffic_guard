let liveMapInstance = null;
let alertMarkers = [];
let deviceMarkers = [];

let cachedAlerts = [];
let cachedDevices = [];
let currentDeviceFilter = "all";
let selectedAlert = null;

// Determine if current user is a guest (injected by template)
const IS_GUEST = (typeof userRole !== 'undefined' && userRole === 'guest');

// -----------------------------
// SECTION NAVIGATION
// -----------------------------
function showSection(sectionId, button = null) {
  // Block navigating to restricted sections in guest mode
  if (IS_GUEST && (sectionId === "alertsSection" || sectionId === "federatedSection")) {
    return;
  }
  document.querySelectorAll(".section").forEach((section) => {
    section.style.display = "none";
  });

  const targetSection = document.getElementById(sectionId);
  if (targetSection) {
    targetSection.style.display = "block";
  }

  document.querySelectorAll(".menu-item").forEach((item) => {
    item.classList.remove("active");
  });

  if (button) {
    button.classList.add("active");
  }

  // Load fresh data based on selected section
  if (sectionId === "dashboardSection") {
    refreshAll();
  }

  if (sectionId === "alertsSection") {
    loadAlerts();
  }

  if (sectionId === "devicesSection") {
    loadDevices();
  }

  if (sectionId === "mapSection") {
    loadDevices().then(() => {
      loadAlerts().then(() => {
        setTimeout(() => {
          loadMap();
        }, 200);
      });
    });
  }

  if (sectionId === "federatedSection") {
    loadGlobalModel();
  }
}

// Expose for inline onclick handlers
window.showSection = showSection;

// -----------------------------
// INIT
// -----------------------------
document.addEventListener("DOMContentLoaded", () => {
  updateClock();
  setInterval(updateClock, 1000);

  setupDeviceFilters();

  refreshAll();

  setInterval(() => {
    if (!IS_GUEST) {
      loadAlerts();
    }
    loadDevices();
    if (!IS_GUEST) {
      loadGlobalModel();
    }

    if (liveMapInstance) {
      loadMap();
    }
  }, 5000);

  // Admin-only: wire Add Device modal if present
  const deviceForm = document.getElementById('deviceForm');
  if (deviceForm) {
    deviceForm.addEventListener('submit', submitAddDevice);
  }

  // Admin-only: wire Add User modal if present (in Devices section)
  const addUserForm = document.getElementById('addUserForm');
  if (addUserForm) {
    addUserForm.addEventListener('submit', submitAddUser);
  }
});

// -----------------------------
// CLOCK
// -----------------------------
function updateClock() {
  const timeEl = document.querySelector(".time");
  if (!timeEl) return;

  const now = new Date();

  timeEl.textContent = now.toLocaleString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric"
  }).replace(",", " —");
}

// -----------------------------
// REFRESH EVERYTHING
// -----------------------------
async function refreshAll() {
  if (!IS_GUEST) {
    await loadAlerts();
  } else {
    // Set clean placeholders in guest mode
    const dashboardAlertList = document.getElementById("dashboardAlertList");
    if (dashboardAlertList) {
      dashboardAlertList.innerHTML = "<p>Alerts are hidden in Guest mode.</p>";
    }
    const alertCount = document.getElementById("alertCount");
    const notifCount = document.getElementById("notifCount");
    const alertStatusSummary = document.getElementById("alertStatusSummary");
    if (alertCount) alertCount.textContent = 0;
    if (notifCount) notifCount.textContent = 0;
    if (alertStatusSummary) alertStatusSummary.textContent = "Guest mode";
  }
  await loadDevices();
  if (!IS_GUEST) {
    await loadGlobalModel();
  } else {
    const globalModel = document.getElementById("globalModel");
    if (globalModel) {
      globalModel.innerHTML = "<p>Federated details are hidden in Guest mode.</p>";
    }
  }

  if (liveMapInstance) {
    await loadMap();
  }
}

// -----------------------------
// ALERTS
// -----------------------------
async function loadAlerts() {
  if (IS_GUEST) {
    // Prevent network call in guest mode
    const dashboardAlertList = document.getElementById("dashboardAlertList");
    if (dashboardAlertList) {
      dashboardAlertList.innerHTML = "<p>Alerts are hidden in Guest mode.</p>";
    }
    const alertList = document.getElementById("alertList");
    if (alertList) {
      alertList.innerHTML = "<p>Alerts are hidden in Guest mode.</p>";
    }
    updateAlertStats([]);
    return [];
  }
  try {
    const response = await fetch("/alerts_data");
    const data = await response.json();

    cachedAlerts = Array.isArray(data) ? data : [];

    renderDashboardAlerts(cachedAlerts);
    renderAlertsSection(cachedAlerts);
    updateAlertStats(cachedAlerts);

    return cachedAlerts;
  } catch (error) {
    console.error("Failed to load alerts:", error);

    const alertList = document.getElementById("alertList");
    const dashboardAlertList = document.getElementById("dashboardAlertList");

    if (alertList) {
      alertList.innerHTML = "<p>Failed to load alerts.</p>";
    }

    if (dashboardAlertList) {
      dashboardAlertList.innerHTML = "<p>Failed to load alerts.</p>";
    }

    return [];
  }
}

function renderDashboardAlerts(alerts) {
  const container = document.getElementById("dashboardAlertList");
  if (!container) return;

  container.innerHTML = "";

  if (!alerts.length) {
    container.innerHTML = "<p>No alerts found.</p>";
    return;
  }

  alerts.slice(0, 5).forEach((alert) => {
    container.appendChild(createAlertCard(alert, false));
  });
}

function renderAlertsSection(alerts) {
  const container = document.getElementById("alertList");
  if (!container) return;

  container.innerHTML = "";

  if (!alerts.length) {
    container.innerHTML = "<p>No alerts found.</p>";
    return;
  }

  alerts.forEach((alert) => {
    container.appendChild(createAlertCard(alert, true));
  });
}

function createAlertCard(alert, includeActions) {
  const card = document.createElement("div");
  card.className = "alert-row";
  card.dataset.id = alert.id;

  const status = alert.status || "Unknown";
  const confidence =
    alert.confidence !== null && alert.confidence !== undefined
      ? `${Math.round(Number(alert.confidence) * 100)}%`
      : "N/A";

  const imgHtml = alert.image_path
    ? `<img src="/static/${alert.image_path}"
             alt="alert image"
             class="alert-thumb"
             onclick="openImagePreview('/static/${alert.image_path}')" />`
    : "";

  card.innerHTML = `
    <div style="display:flex; gap:12px; align-items:flex-start;">
      ${imgHtml}
      <div>
        <p class="alert-title">Alert #${alert.id} — ${alert.type || "accident"}</p>
        <p class="alert-meta">
          Device: ${alert.device_id || "Unknown"} •
          Status: ${status}
        </p>
        <p class="alert-meta">
          Confidence: ${confidence} •
          Time: ${alert.timestamp || alert.time || ""}
        </p>
        <p class="alert-meta">
          Location: ${alert.location || "Unknown location"}
        </p>
      </div>
    </div>

    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
      <span class="pill ${getStatusPillClass(status)}">${status}</span>

      ${includeActions ? renderAlertButtons(alert) : ""}
    </div>
  `;

  card.addEventListener("click", (event) => {
    if (event.target.tagName.toLowerCase() === "button") return;

    selectedAlert = alert;
    renderAlertDetails(alert);

    document.querySelectorAll("#alertList .alert-row").forEach((row) => {
      row.classList.remove("active");
    });

    card.classList.add("active");
  });

  return card;
}

function renderAlertButtons(alert) {
  if (userRole === "guest") {
    return "";
  }

  const locked = alert.status && alert.status !== "Pending";
  const disabledAttr = locked ? "disabled" : "";
  const titleAttr = locked ? "title=\"Decision Locked\"" : "";

  return `
    <button class="action-btn success" ${disabledAttr} ${titleAttr} onclick="updateAlert(${alert.id}, 'Verified')">
      ✅ Verify
    </button>

    <button class="action-btn danger" ${disabledAttr} ${titleAttr} onclick="updateAlert(${alert.id}, 'Rejected')">
      ❌ Reject
    </button>
    ${locked ? '<span class="lock-msg">Decision Locked</span>' : ''}
  `;
}

function renderAlertDetails(alert) {
  const container = document.getElementById("alertDetails");
  if (!container) return;

  const confidence =
    alert.confidence !== null && alert.confidence !== undefined
      ? `${Math.round(Number(alert.confidence) * 100)}%`
      : "N/A";

  const imgHtml = alert.image_path
    ? `<div style="margin:8px 0;">
         <img src="/static/${alert.image_path}" alt="alert image" class="alert-image"
              onclick="openImagePreview('/static/${alert.image_path}')" />
       </div>`
    : "";

  container.innerHTML = `
    <p><strong>ID:</strong> ${alert.id}</p>
    <p><strong>Device:</strong> ${alert.device_id || "Unknown"}</p>
    <p><strong>Type:</strong> ${alert.type || "accident"}</p>
    <p><strong>Confidence:</strong> ${confidence}</p>
    <p><strong>Location:</strong> ${alert.location || "Unknown location"}</p>
    <p><strong>Status:</strong> ${alert.status || "Unknown"}</p>
    <p><strong>Timestamp:</strong> ${alert.timestamp || alert.time || ""}</p>
    <p><strong>Coordinates:</strong> ${alert.lat || "N/A"}, ${alert.lon || "N/A"}</p>
    ${imgHtml}

    <p style="margin-top:10px;">
      <strong>Description:</strong><br>
      ${alert.description || "No description available."}
    </p>

    <div style="display:flex; gap:10px; margin-top:14px; flex-wrap:wrap;">
      <button class="action-btn" onclick="focusAlertOnMap(${alert.id})">
        Show on Map
      </button>

      ${renderAlertButtons(alert)}
    </div>
  `;
}

function getStatusPillClass(status) {
  if (status === "Pending") return "pill-orange";
  if (status === "Verified") return "pill-green";
  if (status === "Rejected") return "pill-red";
  if (status === "Resolved") return "pill-green";
  if (status === "FalseAlarm") return "pill-red";
  return "pill-red";
}

function updateAlertStats(alerts) {
  const pendingCount = alerts.filter((alert) => alert.status === "Pending").length;

  const alertCount = document.getElementById("alertCount");
  const notifCount = document.getElementById("notifCount");
  const alertStatusSummary = document.getElementById("alertStatusSummary");

  if (alertCount) {
    alertCount.textContent = pendingCount;
  }

  if (notifCount) {
    notifCount.textContent = pendingCount;
  }

  if (alertStatusSummary) {
    alertStatusSummary.textContent = `${pendingCount} pending verification`;
  }
}

// -----------------------------
// ALERT ACTION → BACKEND → FEDERATED
// -----------------------------
async function updateAlert(id, status) {
  try {
    const response = await fetch("/update_alert", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        id: id,
        status: status
      })
    });

    const result = await response.json();

    if (!response.ok) {
      alert(result.error || "Failed to update alert.");
      return;
    }

    console.log("Alert updated:", result);

    await loadAlerts();
    await loadDevices();
    await loadGlobalModel();

    if (liveMapInstance) {
      await loadMap();
    }
  } catch (error) {
    console.error("Update alert error:", error);
    alert("Could not update alert. Please check the server.");
  }
}

// -----------------------------
// IMAGE PREVIEW POPUP
// -----------------------------
function openImagePreview(src) {
  const modal = document.getElementById('imagePreviewModal');
  const img = document.getElementById('imagePreview');
  if (!modal || !img) return;
  img.src = src;
  modal.style.display = 'flex';
}

function closeImagePreview() {
  const modal = document.getElementById('imagePreviewModal');
  if (!modal) return;
  modal.style.display = 'none';
}

// expose for inline handlers
window.openImagePreview = openImagePreview;
window.closeImagePreview = closeImagePreview;

// Expose for inline onclick handlers
window.updateAlert = updateAlert;

// -----------------------------
// DEVICES
// -----------------------------
async function loadDevices() {
  try {
    const response = await fetch("/device_status");
    const data = await response.json();

    cachedDevices = Array.isArray(data) ? data : [];

    renderDashboardDevices(cachedDevices);
    renderDevicesSection(cachedDevices);
    updateDeviceStats(cachedDevices);

    return cachedDevices;
  } catch (error) {
    console.error("Failed to load devices:", error);

    const dashboardDeviceList = document.getElementById("dashboardDeviceList");
    const deviceList = document.getElementById("deviceList");

    if (dashboardDeviceList) {
      dashboardDeviceList.innerHTML = "<p>Failed to load devices.</p>";
    }

    if (deviceList) {
      deviceList.innerHTML = "<p>Failed to load devices.</p>";
    }

    return [];
  }
}

function renderDashboardDevices(devices) {
  const container = document.getElementById("dashboardDeviceList");
  if (!container) return;

  container.innerHTML = "";

  if (!devices.length) {
    container.innerHTML = "<p>No devices found. Run addDevice.py first.</p>";
    return;
  }

  devices.slice(0, 5).forEach((device) => {
    const isOnline = device.status === "Online";

    const row = document.createElement("div");
    row.className = "device-row";

    row.innerHTML = `
      <div>
        <p class="device-id">${device.device_id || device.id}</p>
        <p class="device-loc">${device.location || "Unknown location"}</p>
        <p class="device-loc">Last update: ${device.last_update || "No model update yet"}</p>
      </div>

      <span class="status-badge ${isOnline ? "green" : "red"}">
        ${device.status || "Unknown"}
      </span>
    `;

    container.appendChild(row);
  });
}

function renderDevicesSection(devices) {
  const container = document.getElementById("deviceList");
  if (!container) return;

  container.innerHTML = "";

  const searchInput = document.getElementById("deviceSearch");
  const searchValue = searchInput ? searchInput.value.toLowerCase().trim() : "";

  const filteredDevices = devices.filter((device) => {
    const deviceStatus = device.status === "Online" ? "online" : "offline";

    const matchesSearch =
      (device.device_id || device.id || "").toLowerCase().includes(searchValue) ||
      (device.location || "").toLowerCase().includes(searchValue);

    const matchesFilter =
      currentDeviceFilter === "all" || currentDeviceFilter === deviceStatus;

    return matchesSearch && matchesFilter;
  });

  if (!filteredDevices.length) {
    container.innerHTML = "<p>No devices match the current filter.</p>";
    return;
  }

  filteredDevices.forEach((device) => {
    const isOnline = device.status === "Online";

    const row = document.createElement("div");
    row.className = `device-row ${isOnline ? "online" : "offline"}`;
    row.dataset.id = device.device_id || device.id;
    row.dataset.location = device.location || "";
    row.dataset.status = isOnline ? "online" : "offline";

    row.innerHTML = `
      <div class="device-left">
        <h3>${device.device_id || device.id}</h3>
        <p class="device-location">📌 ${device.location || "Unknown location"}</p>
        <p class="device-model">🤖 Federated local model</p>
      </div>

      <div class="device-middle">
        <p><strong>Status:</strong> ${device.status || "Unknown"}</p>
        <p><strong>Last Update:</strong> ${device.last_update || "No model update yet"}</p>
        <p><strong>Latitude:</strong> ${device.lat ?? "N/A"}</p>
        <p><strong>Longitude:</strong> ${device.lon ?? "N/A"}</p>
      </div>

      <div class="device-right">
        <span class="status-badge ${isOnline ? "green" : "red"}">
          ${device.status || "Unknown"}
        </span>
      </div>
    `;

    container.appendChild(row);
  });
}

function updateDeviceStats(devices) {
  const onlineCount = devices.filter((device) => device.status === "Online").length;
  const totalCount = devices.length;
  const offlineCount = totalCount - onlineCount;

  const activeDeviceCount = document.getElementById("activeDeviceCount");
  const deviceStatusSummary = document.getElementById("deviceStatusSummary");
  const onlineDeviceSummary = document.getElementById("onlineDeviceSummary");
  const offlineDeviceSummary = document.getElementById("offlineDeviceSummary");

  if (activeDeviceCount) {
    activeDeviceCount.textContent = `${onlineCount}/${totalCount}`;
  }

  if (deviceStatusSummary) {
    deviceStatusSummary.textContent = `${onlineCount} online, ${offlineCount} without updates`;
  }

  if (onlineDeviceSummary) {
    onlineDeviceSummary.textContent = `${onlineCount} Online`;
  }

  if (offlineDeviceSummary) {
    offlineDeviceSummary.textContent = `${offlineCount} Offline`;
  }
}

function setupDeviceFilters() {
  const deviceSearch = document.getElementById("deviceSearch");
  const filterButtons = document.querySelectorAll(".filter-btn");

  if (deviceSearch) {
    deviceSearch.addEventListener("input", () => {
      renderDevicesSection(cachedDevices);
    });
  }

  filterButtons.forEach((button) => {
    button.addEventListener("click", () => {
      filterButtons.forEach((btn) => btn.classList.remove("active"));

      button.classList.add("active");
      currentDeviceFilter = button.dataset.filter;

      renderDevicesSection(cachedDevices);
    });
  });
}

// -----------------------------
// FEDERATED GLOBAL MODEL
// -----------------------------
async function loadGlobalModel() {
  if (IS_GUEST) {
    const container = document.getElementById("globalModel");
    if (container) {
      container.innerHTML = "<p>Federated details are hidden in Guest mode.</p>";
    }
    updateGlobalModelStats(null);
    return null;
  }
  try {
    const response = await fetch("/global_model");
    const data = await response.json();

    renderGlobalModel(data);
    updateGlobalModelStats(data);

    return data;
  } catch (error) {
    console.error("Failed to load global model:", error);

    const container = document.getElementById("globalModel");
    if (container) {
      container.innerHTML = "<p>Failed to load global model.</p>";
    }

    return null;
  }
}

function flattenWeights(globalWeights) {
  if (!globalWeights) return [];

  return Object.values(globalWeights).flatMap((layerValues) => {
    return Array.isArray(layerValues) ? layerValues : [];
  });
}

function renderGlobalModel(data) {
  const container = document.getElementById("globalModel");
  if (!container) return;

  if (!data || !data.global_weights) {
    container.innerHTML = `
      <p>No global model yet.</p>
      <p class="muted">
        Verify or reject an alert to trigger federated learning.
      </p>
    `;
    return;
  }

  const allWeights = flattenWeights(data.global_weights);
  const weightCount = allWeights.length;

  const averageWeight = weightCount
    ? allWeights.reduce((sum, value) => sum + Number(value), 0) / weightCount
    : 0;

  container.innerHTML = `
    <div class="grid grid-4 mb-24">
      <div class="stat-card">
        <p class="stat-title">Devices Participating</p>
        <p class="stat-value">${data.num_devices || 0}</p>
        <p class="stat-sub">Unique edge devices</p>
      </div>

      <div class="stat-card">
        <p class="stat-title">Total Updates</p>
        <p class="stat-value">${data.num_updates || 0}</p>
        <p class="stat-sub">Stored model updates</p>
      </div>

      <div class="stat-card">
        <p class="stat-title">Weights Length</p>
        <p class="stat-value">${weightCount}</p>
        <p class="stat-sub">Flattened parameters</p>
      </div>

      <div class="stat-card">
        <p class="stat-title">Model Status</p>
        <p class="stat-value">Active</p>
        <p class="stat-sub">FedAvg aggregation</p>
      </div>
    </div>

    <div class="card">
      <h3>Weights Summary</h3>
      <p><strong>Average Weight:</strong> ${averageWeight.toFixed(6)}</p>
      <p><strong>Layers:</strong> ${Object.keys(data.global_weights).join(", ")}</p>
    </div>
  `;
}

function updateGlobalModelStats(data) {
  const federatedDeviceCount = document.getElementById("federatedDeviceCount");
  const globalUpdateCount = document.getElementById("globalUpdateCount");
  const globalModelStatus = document.getElementById("globalModelStatus");

  if (federatedDeviceCount) {
    federatedDeviceCount.textContent = data && data.num_devices ? data.num_devices : 0;
  }

  if (globalUpdateCount) {
    globalUpdateCount.textContent =
      data && data.num_updates
        ? `${data.num_updates} model updates`
        : "Waiting for updates";
  }

  if (globalModelStatus) {
    globalModelStatus.textContent =
      data && data.global_weights
        ? "Active"
        : "N/A";
  }
}

// -----------------------------
// MAP
// -----------------------------
async function loadMap() {
  const mapEl = document.getElementById("riyadhMap");
  if (!mapEl) return;

  if (!liveMapInstance) {
    liveMapInstance = L.map("riyadhMap").setView([24.7136, 46.6753], 11);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap"
    }).addTo(liveMapInstance);
  }

  clearMapMarkers();

  cachedDevices.forEach((device) => {
    if (!device.lat || !device.lon) return;

    const isOnline = device.status === "Online";
    const color = isOnline ? "green" : "red";

    const icon = L.divIcon({
      className: "custom-marker",
      html: `<div style="
        width:14px;
        height:14px;
        border-radius:50%;
        background:${color};
        border:2px solid white;
        box-shadow:0 0 0 2px rgba(0,0,0,0.15);
      "></div>`,
      iconSize: [14, 14],
      iconAnchor: [7, 7]
    });

    const marker = L.marker([Number(device.lat), Number(device.lon)], { icon })
      .addTo(liveMapInstance)
      .bindPopup(`
        <strong>${device.device_id || device.id}</strong><br>
        ${device.location || "Unknown location"}<br>
        Status: ${device.status || "Unknown"}<br>
        Last update: ${device.last_update || "No model update yet"}
      `);

    deviceMarkers.push(marker);
  });

  cachedAlerts.forEach((alert) => {
    if (alert.status !== "Pending") return;
    if (!alert.lat || !alert.lon) return;

    const icon = L.divIcon({
      className: "alert-marker",
      html: `<div style="
        width:16px;
        height:16px;
        border-radius:50%;
        background:red;
        border:2px solid white;
        box-shadow:0 0 10px rgba(255,0,0,0.6);
      "></div>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8]
    });

    const marker = L.marker([Number(alert.lat), Number(alert.lon)], { icon })
      .addTo(liveMapInstance)
      .bindPopup(`
        <strong>Alert #${alert.id}</strong><br>
        ${alert.location || "Unknown location"}<br>
        Device: ${alert.device_id || "Unknown"}<br>
        Status: ${alert.status}
      `);

    alertMarkers.push({
      alertId: alert.id,
      marker: marker
    });
  });

  setTimeout(() => {
    liveMapInstance.invalidateSize();
  }, 200);
}

function clearMapMarkers() {
  if (!liveMapInstance) return;

  deviceMarkers.forEach((marker) => {
    liveMapInstance.removeLayer(marker);
  });

  alertMarkers.forEach((item) => {
    liveMapInstance.removeLayer(item.marker);
  });

  deviceMarkers = [];
  alertMarkers = [];
}

function focusAlertOnMap(alertId) {
  const alert = cachedAlerts.find((item) => item.id === alertId);
  if (!alert || !alert.lat || !alert.lon) return;

  const mapButton = Array.from(document.querySelectorAll(".menu-item"))
    .find((button) => button.textContent.includes("Map"));

  showSection("mapSection", mapButton);

  setTimeout(async () => {
    await loadMap();

    liveMapInstance.setView([Number(alert.lat), Number(alert.lon)], 14);

    const markerItem = alertMarkers.find((item) => item.alertId === alertId);
    if (markerItem) {
      markerItem.marker.openPopup();
    }
  }, 250);
}

// Expose for inline onclick handlers
window.focusAlertOnMap = focusAlertOnMap;

// -----------------------------
// ADD DEVICE (ADMIN)
// -----------------------------
function openAddDeviceModal() {
  const modal = document.getElementById('addDeviceModal');
  if (!modal) return;
  // clear any previous error
  const err = document.getElementById('deviceErrorMsg');
  if (err) err.textContent = '';
  // clear inputs
  const idInput = document.getElementById('deviceIdInput');
  const nameInput = document.getElementById('deviceNameInput');
  const typeInput = document.getElementById('deviceTypeInput');
  const statusInput = document.getElementById('deviceStatusInput');
  const locInput = document.getElementById('deviceLocationInput');
  const latInput = document.getElementById('deviceLatInput');
  const lonInput = document.getElementById('deviceLonInput');
  if (idInput) idInput.value = '';
  if (nameInput) nameInput.value = '';
  if (typeInput) typeInput.value = '';
  if (statusInput) statusInput.value = 'online';
  if (locInput) locInput.value = '';
  if (latInput) latInput.value = '';
  if (lonInput) lonInput.value = '';
  modal.style.display = 'flex';
}

function closeAddDeviceModal() {
  const modal = document.getElementById('addDeviceModal');
  if (!modal) return;
  modal.style.display = 'none';
}

async function submitAddDevice(event) {
  event.preventDefault();
  const idInput = document.getElementById('deviceIdInput');
  const nameInput = document.getElementById('deviceNameInput');
  const typeInput = document.getElementById('deviceTypeInput');
  const statusInput = document.getElementById('deviceStatusInput');
  const locInput = document.getElementById('deviceLocationInput');
  const latInput = document.getElementById('deviceLatInput');
  const lonInput = document.getElementById('deviceLonInput');
  const err = document.getElementById('deviceErrorMsg');

  if (!idInput || !nameInput || !typeInput || !statusInput || !locInput || !latInput || !lonInput) return;

  const device_id = (idInput.value || '').trim();
  const name = (nameInput.value || '').trim();
  const type = (typeInput.value || '').trim();
  const status = (statusInput.value || '').trim();
  const location = (locInput.value || '').trim();
  const lat = (latInput.value || '').trim();
  const lon = (lonInput.value || '').trim();

  if (!device_id || !name || !type || !status || !location || !lat || !lon) {
    if (err) err.textContent = 'All fields are required';
    return;
  }

  try {
    const resp = await fetch('/admin/devices', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id, name, type, status, location, lat, lon })
    });

    const data = await resp.json().catch(() => ({}));

    if (!resp.ok) {
      if (err) err.textContent = data && data.error ? data.error : 'Failed to add device';
      return;
    }

    // Refresh devices list and map
    await loadDevices();
    if (liveMapInstance) {
      await loadMap();
    }

    closeAddDeviceModal();
  } catch (e) {
    console.error('Add device failed:', e);
    if (err) err.textContent = 'Could not reach server. Try again.';
  }
}

// expose for inline handlers
window.openAddDeviceModal = openAddDeviceModal;
window.closeAddDeviceModal = closeAddDeviceModal;

// -----------------------------
// ADD USER (ADMIN in Devices section)
// -----------------------------
function openAddUserModal() {
  const modal = document.getElementById('addUserModal');
  const err = document.getElementById('addUserError');
  if (err) { err.textContent = ''; err.style.display = 'none'; }
  const name = document.getElementById('au_name');
  const email = document.getElementById('au_email');
  const role = document.getElementById('au_role');
  const password = document.getElementById('au_password');
  if (name) name.value = '';
  if (email) email.value = '';
  if (role) role.value = 'authority';
  if (password) password.value = '';
  if (modal) modal.style.display = 'flex';
}

function closeAddUserModal() {
  const modal = document.getElementById('addUserModal');
  if (modal) modal.style.display = 'none';
}

async function submitAddUser(e) {
  e.preventDefault();
  const name = document.getElementById('au_name')?.value.trim();
  const email = document.getElementById('au_email')?.value.trim().toLowerCase();
  const role = document.getElementById('au_role')?.value.trim().toLowerCase();
  const password = document.getElementById('au_password')?.value;
  const err = document.getElementById('addUserError');

  if (!name || !email || !role || !password) {
    if (err) { err.textContent = 'All fields are required.'; err.style.display = 'block'; }
    return;
  }
  if (!email.endsWith('@traffic.com')) {
    if (err) { err.textContent = 'Only @traffic.com emails are allowed.'; err.style.display = 'block'; }
    return;
  }

  try {
    const resp = await fetch('/admin/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, role, password })
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      if (err) { err.textContent = data && data.error ? data.error : 'Failed to create user.'; err.style.display = 'block'; }
      return;
    }
    // Close modal on success
    closeAddUserModal();
  } catch (ex) {
    if (err) { err.textContent = 'Network error. Please try again.'; err.style.display = 'block'; }
  }
}

// Expose
window.openAddUserModal = openAddUserModal;
window.closeAddUserModal = closeAddUserModal;