let liveMapInstance = null;
let alertMarkers = [];
let deviceMarkers = [];

let cachedAlerts = [];
let cachedDevices = [];
let currentDeviceFilter = "all";
let selectedAlert = null;

// -----------------------------
// SECTION NAVIGATION
// -----------------------------
function showSection(sectionId, button = null) {
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
    loadAlerts();
    loadDevices();
    loadGlobalModel();

    if (liveMapInstance) {
      loadMap();
    }
  }, 5000);
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
  await loadAlerts();
  await loadDevices();
  await loadGlobalModel();

  if (liveMapInstance) {
    await loadMap();
  }
}

// -----------------------------
// ALERTS
// -----------------------------
async function loadAlerts() {
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

  card.innerHTML = `
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

    <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
      <span class="pill ${getStatusPillClass(status)}">${status}</span>

      ${includeActions ? renderAlertButtons(alert.id) : ""}
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

function renderAlertButtons(alertId) {
  if (userRole === "guest") {
    return "";
  }

  return `
    <button class="action-btn success" onclick="updateAlert(${alertId}, 'Verified')">
      ✅ Verify
    </button>

    <button class="action-btn danger" onclick="updateAlert(${alertId}, 'Rejected')">
      ❌ Reject
    </button>
  `;
}

function renderAlertDetails(alert) {
  const container = document.getElementById("alertDetails");
  if (!container) return;

  const confidence =
    alert.confidence !== null && alert.confidence !== undefined
      ? `${Math.round(Number(alert.confidence) * 100)}%`
      : "N/A";

  container.innerHTML = `
    <p><strong>ID:</strong> ${alert.id}</p>
    <p><strong>Device:</strong> ${alert.device_id || "Unknown"}</p>
    <p><strong>Type:</strong> ${alert.type || "accident"}</p>
    <p><strong>Confidence:</strong> ${confidence}</p>
    <p><strong>Location:</strong> ${alert.location || "Unknown location"}</p>
    <p><strong>Status:</strong> ${alert.status || "Unknown"}</p>
    <p><strong>Timestamp:</strong> ${alert.timestamp || alert.time || ""}</p>
    <p><strong>Coordinates:</strong> ${alert.lat || "N/A"}, ${alert.lon || "N/A"}</p>

    <p style="margin-top:10px;">
      <strong>Description:</strong><br>
      ${alert.description || "No description available."}
    </p>

    <div style="display:flex; gap:10px; margin-top:14px; flex-wrap:wrap;">
      <button class="action-btn" onclick="focusAlertOnMap(${alert.id})">
        Show on Map
      </button>

      ${renderAlertButtons(alert.id)}
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