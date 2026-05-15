import argparse
import json
import socket
import socketserver
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

import cv2
import numpy as np
from ultralytics import YOLO


# ============================================================
# CONFIG
# ============================================================

MODEL_PATH = "yolo11n.pt"

VIDEOS = {
    "North": "north-lane.mp4",
    "East": "east-lane.mp4",
    "West": "west-lane.mp4",
    "South": "south-lane.mp4",
}

ORDER = ["North", "West", "South", "East"]
CHECKPOINT = "East"

DEFAULT_GREEN = 20
REDUCED_GREEN = 15
YELLOW_TIME = 3
MIN_GREEN = 15

STALE_SECONDS = 8
REQUIRE_ALL_EDGES = True
REPORT_INTERVAL = 3

FRAME_DELAY = 300
CONFIDENCE = 0.35

# UI scale factor to fit laptop screens comfortably
UI_SCALE = 0.85

HOST = "0.0.0.0"
PORT = 5000

VEHICLE_CLASSES = [1, 2, 3, 5, 7]  # bicycle, car, motorcycle, bus, truck

WEIGHTS = {
    "bicycle": 0.5,
    "motorcycle": 0.5,
    "car": 1.0,
    "bus": 2.0,
    "truck": 2.0,
}


# ============================================================
# HELPERS
# ============================================================

def density_label(score):
    if score < 3:
        return "LOW"
    elif score < 8:
        return "MEDIUM"
    return "HIGH"


def previous_roads(heavy_road):
    index = ORDER.index(heavy_road)
    return ORDER[:index]


def get_light_color(state):
    if state == "GREEN":
        return (0, 255, 0)
    if state == "YELLOW":
        return (0, 255, 255)
    return (0, 0, 255)


def safe_json_send(sock: socket.socket, payload: dict) -> None:
    data = (json.dumps(payload) + "\n").encode("utf-8")
    sock.sendall(data)


def safe_json_recv_line(sock: socket.socket) -> dict:
    buffer = b""

    while not buffer.endswith(b"\n"):
        chunk = sock.recv(4096)
        if not chunk:
            break
        buffer += chunk

    if not buffer:
        return {}

    return json.loads(buffer.decode("utf-8").strip())


# ============================================================
# MASTER STATE
# ============================================================

@dataclass
class RoadData:
    raw_count: int = 0
    weighted_score: float = 0.0
    ts: float = 0.0


class MasterState:
    def __init__(self):
        self.lock = threading.Lock()

        self.counts: Dict[str, RoadData] = {
            road: RoadData() for road in ORDER
        }

        self.mode = "DEFAULT"
        self.heavy_road: Optional[str] = None
        self.green_times = {road: DEFAULT_GREEN for road in ORDER}

        self.current_road = ORDER[0]
        self.current_phase = "GREEN"
        self.phase_start = time.time()
        self.current_duration = DEFAULT_GREEN

        self.initialized = False

    def has_enough_data(self) -> bool:
        now = time.time()
        fresh = 0

        for road in ORDER:
            data = self.counts[road]
            if data.ts > 0 and now - data.ts <= STALE_SECONDS:
                fresh += 1

        if REQUIRE_ALL_EDGES:
            return fresh == len(ORDER)

        return fresh > 0

    def update_edge_data(self, road: str, raw_count: int, weighted_score: float):
        with self.lock:
            self.counts[road] = RoadData(
                raw_count=raw_count,
                weighted_score=weighted_score,
                ts=time.time()
            )

    def get_latest_scores(self):
        now = time.time()
        scores = {}

        for road in ORDER:
            data = self.counts[road]
            if data.ts > 0 and now - data.ts <= STALE_SECONDS:
                scores[road] = data.weighted_score
            else:
                scores[road] = 0.0

        return scores

    def get_latest_counts(self):
        now = time.time()
        counts = {}

        for road in ORDER:
            data = self.counts[road]
            if data.ts > 0 and now - data.ts <= STALE_SECONDS:
                counts[road] = data.raw_count
            else:
                counts[road] = 0

        return counts

    def build_signal_plan(self):
        green_times = {road: DEFAULT_GREEN for road in ORDER}

        if not self.has_enough_data():
            self.mode = "DEFAULT"
            self.heavy_road = None
            self.green_times = green_times
            return

        scores = self.get_latest_scores()
        heavy = max(scores, key=scores.get)

        self.mode = "ADAPTIVE"
        self.heavy_road = heavy

        for road in previous_roads(heavy):
            green_times[road] = max(REDUCED_GREEN, MIN_GREEN)

        self.green_times = green_times

    def reset_cycle(self):
        self.build_signal_plan()
        self.current_road = ORDER[0]
        self.current_phase = "GREEN"
        self.phase_start = time.time()
        self.current_duration = self.green_times[self.current_road]
        self.initialized = True

    def advance_phase(self):
        elapsed = time.time() - self.phase_start

        if elapsed < self.current_duration:
            return

        if self.current_phase == "GREEN":
            self.current_phase = "YELLOW"
            self.current_duration = YELLOW_TIME
            self.phase_start = time.time()
            return

        if self.current_road == CHECKPOINT:
            self.reset_cycle()
            return

        current_index = ORDER.index(self.current_road)
        next_index = (current_index + 1) % len(ORDER)

        self.current_road = ORDER[next_index]
        self.current_phase = "GREEN"
        self.current_duration = self.green_times[self.current_road]
        self.phase_start = time.time()

    def get_lights(self):
        lights = {road: "RED" for road in ORDER}
        lights[self.current_road] = self.current_phase
        return lights

    def get_remaining(self):
        remaining = int(self.current_duration - (time.time() - self.phase_start))
        return max(0, remaining)

    def ensure_running(self):
        if not self.initialized:
            self.reset_cycle()
        else:
            self.advance_phase()

    def current_state(self):
        with self.lock:
            self.ensure_running()

            scores = self.get_latest_scores()
            counts = self.get_latest_counts()

            return {
                "mode": self.mode,
                "heavy_road": self.heavy_road,
                "green_times": self.green_times,
                "current_road": self.current_road,
                "current_phase": self.current_phase,
                "remaining": self.get_remaining(),
                "lights": self.get_lights(),
                "counts": counts,
                "scores": scores,
                "densities": {road: density_label(scores[road]) for road in ORDER},
            }


MASTER = MasterState()


# ============================================================
# MASTER SERVER
# ============================================================

class MasterTCPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            req = safe_json_recv_line(self.request)

            if not req:
                return

            action = req.get("action")

            if action == "report":
                road = req["road"]
                raw_count = int(req["raw_count"])
                weighted_score = float(req["weighted_score"])

                MASTER.update_edge_data(road, raw_count, weighted_score)

                response = {
                    "ok": True,
                    "state": MASTER.current_state()
                }

                safe_json_send(self.request, response)

            elif action == "get_state":
                response = {
                    "ok": True,
                    "state": MASTER.current_state()
                }

                safe_json_send(self.request, response)

            else:
                safe_json_send(self.request, {
                    "ok": False,
                    "error": "unknown action"
                })

        except Exception as e:
            try:
                safe_json_send(self.request, {
                    "ok": False,
                    "error": str(e)
                })
            except Exception:
                pass


class ThreadedTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


# ============================================================
# DETECTION
# ============================================================

def detect_and_annotate(frame, model):
    results = model(
        frame,
        classes=VEHICLE_CLASSES,
        conf=CONFIDENCE,
        verbose=False
    )

    annotated = frame.copy()
    count = 0
    score = 0.0

    boxes = results[0].boxes

    if boxes is not None and len(boxes) > 0:
        for box in boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            label = model.names[cls_id]

            count += 1
            score += WEIGHTS.get(label, 1.0)

            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 180, 255), 2)
            cv2.putText(
                annotated,
                f"{label} {conf:.2f}",
                (x1, max(y1 - 8, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38,
                (255, 255, 255),
                2
            )

    return annotated, count, score


# ============================================================
# DARK MASTER INTERFACE WITH FOUR VIDEOS
# ============================================================

def draw_background(img):
    # Smooth dark background with subtle vertical gradient
    h, w = img.shape[:2]
    for y in range(h):
        shade = int(10 + (y / h) * 18)
        img[y, :] = (shade, shade + 3, shade + 5)

    # very subtle grid lines
    for x in range(0, w, 80):
        cv2.line(img, (x, 0), (x, h), (22, 28, 30), 1)
    for y in range(0, h, 80):
        cv2.line(img, (0, y), (w, y), (22, 28, 30), 1)


def draw_panel(img, x1, y1, x2, y2, title=None):
    # Cleaner dark panel with softer borders
    cv2.rectangle(img, (x1, y1), (x2, y2), (20, 25, 27), -1)

    # outer border
    cv2.rectangle(img, (x1, y1), (x2, y2), (95, 105, 108), 2)

    # inner highlight line
    cv2.rectangle(img, (x1 + 3, y1 + 3), (x2 - 3, y2 - 3), (42, 48, 50), 1)

    if title:
        cv2.putText(
            img, title, (x1 + 18, y1 + 32),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2
        )


def draw_light_icon(img, x, y, state):
    off = {
        "RED": (50, 50, 90),
        "YELLOW": (50, 90, 90),
        "GREEN": (50, 90, 50),
    }

    on = {
        "RED": (0, 0, 255),
        "YELLOW": (0, 255, 255),
        "GREEN": (0, 255, 0),
    }

    radius = 9
    spacing = 30
    order = ["RED", "YELLOW", "GREEN"]

    for i, s in enumerate(order):
        cy = y + i * spacing
        color = on[s] if s == state else off[s]
        cv2.circle(img, (x, cy), radius, color, -1)
        cv2.circle(img, (x, cy), radius, (190, 190, 190), 1)


def draw_progress_bar(img, x, y, w, h, remaining, total, color=(0, 200, 255)):
    cv2.rectangle(img, (x, y), (x + w, y + h), (90, 90, 90), 1)

    if total <= 0:
        fill = 0
    else:
        ratio = max(0.0, min(1.0, remaining / total))
        fill = int(w * ratio)

    if fill > 0:
        cv2.rectangle(img, (x, y), (x + fill, y + h), color, -1)


def draw_road_card(img, x1, y1, w, h, road, light_state, count, score, density,
                   is_active=False, remaining=0, phase_total=0):
    x2 = x1 + w
    y2 = y1 + h

    if light_state == "GREEN":
        border = (0, 255, 0)
    elif light_state == "YELLOW":
        border = (0, 255, 255)
    else:
        border = (0, 0, 255)

    bg = (52, 70, 52) if is_active and light_state == "GREEN" else \
         (70, 70, 40) if is_active and light_state == "YELLOW" else \
         (52, 52, 52)

    cv2.rectangle(img, (x1, y1), (x2, y2), bg, -1)
    cv2.rectangle(img, (x1, y1), (x2, y2), border, 3)

    cv2.putText(img, road.upper(), (x1 + 16, y1 + 34),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)

    if is_active:
        cv2.putText(img, "ACTIVE", (x2 - 95, y1 + 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 2)

    text_x = x1 + 16
    count_y = y1 + 95
    score_y = y1 + 130
    density_y = y1 + 165

    cv2.putText(img, f"Count: {count}", (text_x, count_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)

    cv2.putText(img, f"Score: {score:.1f}", (text_x, score_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)

    cv2.putText(img, f"Density: {density}", (text_x, density_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)

    circle_x = x2 - 42
    circle_y = y1 + 95
    draw_light_icon(img, circle_x, circle_y, light_state)

    if is_active:
        draw_progress_bar(img, x1 + 16, y2 - 20, w - 32, 10, remaining, phase_total)
        cv2.putText(img, f"{remaining}s", (x2 - 60, y2 - 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (220, 220, 220), 2)


def draw_video_panel(img, road, frame, x1, y1, x2, y2, light_state,
                     count=0, score=0.0, density="LOW", remaining=0,
                     phase_total=1, is_active=False):
    border = (120, 125, 125)

    # Card background and border
    cv2.rectangle(img, (x1, y1), (x2, y2), (18, 23, 25), -1)
    cv2.rectangle(img, (x1, y1), (x2, y2), border, 2)
    cv2.rectangle(img, (x1 + 3, y1 + 3), (x2 - 3, y2 - 3), (45, 50, 52), 1)

    # Top title and signal word, no circles
    cv2.putText(img, f"{road.upper()} EDGE VIEW", (x1 + 14, y1 + 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

    cv2.putText(img, light_state, (x2 - 92, y1 + 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, get_light_color(light_state), 2)

    # Video area
    inner_x1 = x1 + 14
    inner_y1 = y1 + 43
    inner_x2 = x2 - 14
    inner_y2 = y1 + 168

    if frame is None:
        cv2.rectangle(img, (inner_x1, inner_y1), (inner_x2, inner_y2), (15, 15, 15), -1)
        cv2.putText(img, "No video", (inner_x1 + 115, inner_y1 + 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.70, (180, 180, 180), 2)
    else:
        resized = cv2.resize(frame, (inner_x2 - inner_x1, inner_y2 - inner_y1))
        img[inner_y1:inner_y2, inner_x1:inner_x2] = resized

    # Metrics row under video
    metric_y = inner_y2 + 35
    cv2.putText(img, f"Count: {count}", (inner_x1, metric_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    cv2.putText(img, f"Score: {score:.1f}", (inner_x1 + 100, metric_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    cv2.putText(img, f"Density: {density}", (inner_x1 + 210, metric_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    # Progress bar bottom
    bar_x = inner_x1
    bar_y = y2 - 30
    bar_w = (inner_x2 - inner_x1) - 58
    bar_h = 10

    cv2.rectangle(img, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (120, 120, 120), 1)

    if is_active and phase_total > 0:
        ratio = max(0.0, min(1.0, remaining / phase_total))
        fill = int(bar_w * ratio)
    else:
        # Full-width inactive red/yellow bar
        fill = bar_w

    cv2.rectangle(img, (bar_x, bar_y), (bar_x + fill, bar_y + bar_h),
                  get_light_color(light_state), -1)

    if is_active:
        # Remaining time inside the panel, at the right side of the progress bar
        cv2.putText(img, f"{remaining}s",
                    (bar_x + bar_w + 14, bar_y + 8),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.44,
                    get_light_color(light_state),
                    2)


def draw_master_ui(state, video_frames):
    img = np.zeros((820, 1400, 3), dtype=np.uint8)
    draw_background(img)

    mode = state["mode"]
    heavy = state["heavy_road"] if state["heavy_road"] is not None else "None"
    current_road = state["current_road"]
    current_phase = state["current_phase"]
    remaining = state["remaining"]
    counts = state["counts"]
    scores = state["scores"]
    densities = state["densities"]
    lights = state["lights"]
    green_times = state["green_times"]

    phase_total = YELLOW_TIME if current_phase == "YELLOW" else green_times[current_road]

    # =========================
    # HEADER
    # =========================
    draw_panel(img, 15, 15, 1385, 90)

    title = "Traffic Guard - Live Traffic Dashboard"

    (font_w, font_h), _ = cv2.getTextSize(
        title,
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        3
    )

    title_x = (1400 - font_w) // 2

    cv2.putText(img, title, (title_x, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                (255, 255, 255), 3)


    # =========================
    # LEFT TOP: SIGNAL PLAN
    # =========================
    draw_panel(img, 30, 145, 540, 455, "Signal Plan")

    sp_label_x = 50
    sp_green_x = 175
    sp_yellow_x = 325
    sp_mark_x = 470
    sp_y = 235
    sp_gap = 55

    for i, road in enumerate(ORDER):
        yy = sp_y + i * sp_gap

        # Highlight ONLY active road
        if road == current_road:
            active_color = get_light_color(current_phase)
        else:
            active_color = (255, 255, 255)

        cv2.putText(img, f"{road.upper()}:", (sp_label_x, yy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.68, active_color, 2)

        cv2.putText(img, f"GREEN={green_times[road]}s", (sp_green_x, yy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.68, active_color, 2)

        cv2.putText(img, f"YELLOW={YELLOW_TIME}s", (sp_yellow_x, yy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.68, active_color, 2)

        if road == current_road:
            cv2.putText(img, "<==", (sp_mark_x, yy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.68, active_color, 2)

    # =========================
    # LEFT BOTTOM: SYSTEM STATUS
    # =========================
    draw_panel(img, 30, 472, 540, 795, "System Status")

    heavy_color = (0, 255, 0) if heavy != "None" else (255, 255, 255)

    ss_label_x = 50
    ss_value_x = 235
    ss_y = 550
    ss_gap = 48

    rows = [
        ("Mode", mode, (255, 255, 255)),
        ("Heavy road", str(heavy).upper(), heavy_color),
        ("Current road", current_road.upper(), (0, 255, 0)),
    ]

    for i, (label, value, value_color) in enumerate(rows):
        yy = ss_y + i * ss_gap

        cv2.putText(img, f"{label}:", (ss_label_x, yy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (240, 240, 240), 2)

        cv2.putText(img, value, (ss_value_x, yy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, value_color, 2)

    if mode == "DEFAULT":
        status_text = "Waiting for edge data..."
        status_color = (255, 255, 255)
    else:
        status_text = "Adaptive control active"
        status_color = (0, 255, 0)

    cv2.putText(img, "Status:", (ss_label_x, ss_y + 3 * ss_gap),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (240, 240, 240), 2)

    cv2.putText(img, status_text, (ss_value_x, ss_y + 3 * ss_gap),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, status_color, 2)

    # =========================
    # RIGHT: FOUR VIDEO VIEWS
    # =========================
    draw_panel(img, 558, 95, 1385, 795, "Live Edge Views")

    video_positions = {
        "North": (575, 145, 965, 452),
        "West": (980, 145, 1370, 452),
        "South": (575, 468, 965, 780),
        "East": (980, 468, 1370, 780),
    }

    for road in ["North", "West", "South", "East"]:
        x1, y1, x2, y2 = video_positions[road]
        draw_video_panel(
            img=img,
            road=road,
            frame=video_frames.get(road),
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            light_state=lights[road],
            count=counts[road],
            score=scores[road],
            density=densities[road],
            remaining=remaining if road == current_road else 0,
            phase_total=phase_total if road == current_road else 1,
            is_active=(road == current_road)
        )

    return img


# ============================================================
# NETWORK CLIENT
# ============================================================

def send_report(master_ip, port, payload):
    with socket.create_connection((master_ip, port), timeout=5.0) as sock:
        safe_json_send(sock, payload)
        return safe_json_recv_line(sock)


# ============================================================
# ALL-IN-ONE MODE
# ============================================================

class SharedFrameStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.frames = {road: None for road in ORDER}

    def update(self, road, frame):
        with self.lock:
            self.frames[road] = frame.copy()

    def get_all(self):
        with self.lock:
            return {
                road: None if frame is None else frame.copy()
                for road, frame in self.frames.items()
            }


def run_edge_thread_all_mode(road, video_path, model_path, frame_store):
    model = YOLO(model_path)
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        print(f"[ERROR] Cannot open video for {road}: {video_path}")
        return

    print(f"[EDGE {road}] Started video: {video_path}")

    last_report = 0.0

    while True:
        ret, frame = cap.read()

        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()

        if frame is None:
            continue

        annotated, count, score = detect_and_annotate(frame, model)
        frame_store.update(road, annotated)

        now = time.time()

        if now - last_report >= REPORT_INTERVAL:
            MASTER.update_edge_data(road, count, score)
            state = MASTER.current_state()

            print(
                f"[EDGE {road}] count={count}, score={score:.1f} | "
                f"MASTER mode={state['mode']} | heavy={state['heavy_road']} | "
                f"phase={state['current_road']} {state['current_phase']}"
            )

            last_report = now

        time.sleep(0.03)


def run_all_in_one(video_map, model_path):
    frame_store = SharedFrameStore()

    for road in ORDER:
        thread = threading.Thread(
            target=run_edge_thread_all_mode,
            args=(road, video_map[road], model_path, frame_store),
            daemon=True
        )
        thread.start()

    print("[INFO] All four edges started.")
    print("[INFO] Master dark interface started. Press ESC to exit.")

    while True:
        state = MASTER.current_state()
        video_frames = frame_store.get_all()

        dashboard = draw_master_ui(state, video_frames)
        # Scale down the dashboard for smaller screens without changing logic
        if UI_SCALE != 1.0:
            dashboard_disp = cv2.resize(dashboard, None, fx=UI_SCALE, fy=UI_SCALE, interpolation=cv2.INTER_AREA)
        else:
            dashboard_disp = dashboard
        cv2.imshow("MASTER - Traffic Control", dashboard_disp)

        key = cv2.waitKey(FRAME_DELAY) & 0xFF
        if key == 27:
            break

    cv2.destroyAllWindows()


# ============================================================
# MASTER ONLY MODE
# ============================================================

def run_master_only():
    server = ThreadedTCPServer((HOST, PORT), MasterTCPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(f"[MASTER] Listening on {HOST}:{PORT}")
    print("[MASTER] Waiting for edge devices. Press ESC to exit.")

    empty_frames = {road: None for road in ORDER}

    try:
        while True:
            state = MASTER.current_state()
            dashboard = draw_master_ui(state, empty_frames)
            # Scale down the dashboard for smaller screens
            if UI_SCALE != 1.0:
                dashboard_disp = cv2.resize(dashboard, None, fx=UI_SCALE, fy=UI_SCALE, interpolation=cv2.INTER_AREA)
            else:
                dashboard_disp = dashboard

            cv2.imshow("MASTER - Traffic Control", dashboard_disp)

            key = cv2.waitKey(FRAME_DELAY) & 0xFF
            if key == 27:
                break

    finally:
        server.shutdown()
        server.server_close()
        cv2.destroyAllWindows()


# ============================================================
# EDGE ONLY MODE
# ============================================================

def run_edge_only(road, video_path, master_ip, model_path, show_edge=False):
    model = YOLO(model_path)
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        print(f"[ERROR] Cannot open video for {road}: {video_path}")
        return

    print(f"[EDGE {road}] Started.")
    print(f"[EDGE {road}] Sending data to master {master_ip}:{PORT}")

    last_report = 0.0

    while True:
        ret, frame = cap.read()

        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()

        if frame is None:
            continue

        annotated, count, score = detect_and_annotate(frame, model)

        now = time.time()

        if now - last_report >= REPORT_INTERVAL:
            try:
                payload = {
                    "action": "report",
                    "road": road,
                    "raw_count": count,
                    "weighted_score": score
                }

                response = send_report(master_ip, PORT, payload)

                if response.get("ok"):
                    state = response["state"]
                    print(
                        f"[EDGE {road}] count={count}, score={score:.1f} | "
                        f"MASTER mode={state['mode']} | heavy={state['heavy_road']} | "
                        f"phase={state['current_road']} {state['current_phase']}"
                    )

                last_report = now

            except Exception as e:
                print(f"[EDGE {road}] Send error: {e}")

        if show_edge:
            # Show smaller edge preview window too
            edge_disp = cv2.resize(annotated, None, fx=UI_SCALE, fy=UI_SCALE, interpolation=cv2.INTER_AREA) if UI_SCALE != 1.0 else annotated
            cv2.imshow(f"EDGE - {road}", edge_disp)
            if cv2.waitKey(1) & 0xFF == 27:
                break

        time.sleep(0.03)

    cap.release()
    cv2.destroyAllWindows()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=["all", "master", "edge"],
        default="all",
        help="all = run four videos and master dashboard together, master = master only, edge = one edge only"
    )

    parser.add_argument("--model", default=MODEL_PATH)

    parser.add_argument("--north-video", default=VIDEOS["North"])
    parser.add_argument("--west-video", default=VIDEOS["West"])
    parser.add_argument("--south-video", default=VIDEOS["South"])
    parser.add_argument("--east-video", default=VIDEOS["East"])

    parser.add_argument("--road", choices=ORDER)
    parser.add_argument("--video")
    parser.add_argument("--master-ip", default="127.0.0.1")
    parser.add_argument("--show-edge", action="store_true")

    args = parser.parse_args()

    if args.mode == "all":
        # Kept the same mapping style from your pasted code.
        video_map = {
            "North": args.north_video,
            "West": args.east_video,
            "South": args.east_video,
            "East": args.north_video,
        }

        run_all_in_one(video_map, args.model)

    elif args.mode == "master":
        run_master_only()

    elif args.mode == "edge":
        if not args.road:
            raise SystemExit("edge mode needs --road")
        if not args.video:
            raise SystemExit("edge mode needs --video")

        run_edge_only(
            road=args.road,
            video_path=args.video,
            master_ip=args.master_ip,
            model_path=args.model,
            show_edge=args.show_edge
        )
