import argparse
import json
import socket
import socketserver
import threading
import time
from dataclasses import dataclass
from typing import Dict

import cv2
import numpy as np
from ultralytics import YOLO

model = YOLO("yolo11l.pt")
VEHICLE_CLASSES = [1, 2, 3, 5, 7]
ORDER = ["north", "west", "south", "east"]
CHECKPOINT = "east"

DEFAULT_GREEN = 30
REDUCED_GREEN = 20
MIN_GREEN = 15
YELLOW_TIME = 3

STALE_SECONDS = 8
REQUIRE_ALL_EDGES = True
REPORT_INTERVAL = 3

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

ROAD_POLYGONS = {
   
    "north": np.array([
        [0, 120],
        [220, 80],
        [420, 190],
        [190, 270]
    ], dtype=np.int32),
    "west": np.array([
        [0, 600],
        [250, 460],
        [350, 660],
        [40, 690]
    ], dtype=np.int32),

    "south": np.array([
        [1000, 480],
        [1700, 1150],
        [1150, 950],
        [750, 580]
    ], dtype=np.int32),

     "east": np.array([
        [750, 120],
        [1000, -20],
        [1000, 100],
        [800, 200]
    ], dtype=np.int32),
}


def density_label(value: float) -> str:
    if value < 3:
        return "LOW"
    if value < 8:
        return "MEDIUM"
    return "HIGH"


def previous_roads(road: str):
    idx = ORDER.index(road)
    return ORDER[:idx]


def point_in_polygon(cx: int, cy: int, polygon: np.ndarray) -> bool:
    return cv2.pointPolygonTest(polygon, (cx, cy), False) >= 0


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
        self.heavy_road = None
        self.green_times = {r: DEFAULT_GREEN for r in ORDER}

        self.current_road = ORDER[0]
        self.current_phase = "GREEN"
        self.phase_start = time.time()
        self.current_duration = DEFAULT_GREEN

        self.initialized = False

    def has_enough_data(self) -> bool:
        now = time.time()
        fresh = 0

        for road in ORDER:
            if self.counts[road].ts > 0 and (now - self.counts[road].ts <= STALE_SECONDS):
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
            if self.counts[road].ts > 0 and now - self.counts[road].ts <= STALE_SECONDS:
                scores[road] = self.counts[road].weighted_score
            else:
                scores[road] = 0.0
        return scores

    def get_latest_counts(self):
        now = time.time()
        counts = {}
        for road in ORDER:
            if self.counts[road].ts > 0 and now - self.counts[road].ts <= STALE_SECONDS:
                counts[road] = self.counts[road].raw_count
            else:
                counts[road] = 0
        return counts

    def build_signal_plan(self):
        green_times = {r: DEFAULT_GREEN for r in ORDER}

        if not self.has_enough_data():
            self.mode = "DEFAULT"
            self.heavy_road = None
            self.green_times = green_times
            return

        scores = self.get_latest_scores()
        heavy = max(scores, key=scores.get)

        self.mode = "ADAPTIVE"
        self.heavy_road = heavy

        prevs = previous_roads(heavy)
        for road in prevs:
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
            self.phase_start = time.time()
            self.current_duration = YELLOW_TIME
            return

        current_idx = ORDER.index(self.current_road)

        if self.current_road == CHECKPOINT:
            self.reset_cycle()
            return

        next_idx = (current_idx + 1) % len(ORDER)
        self.current_road = ORDER[next_idx]
        self.current_phase = "GREEN"
        self.phase_start = time.time()
        self.current_duration = self.green_times[self.current_road]

    def get_lights(self):
        lights = {r: "RED" for r in ORDER}
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
                "densities": {r: density_label(scores[r]) for r in ORDER},
            }


MASTER = MasterState()


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

                resp = {"ok": True, "state": MASTER.current_state()}
                safe_json_send(self.request, resp)

            elif action == "get_state":
                resp = {"ok": True, "state": MASTER.current_state()}
                safe_json_send(self.request, resp)

            else:
                safe_json_send(self.request, {"ok": False, "error": "unknown action"})

        except Exception as e:
            try:
                safe_json_send(self.request, {"ok": False, "error": str(e)})
            except Exception:
                pass


class ThreadedTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


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


def draw_panel(img, x1, y1, x2, y2, title=None):
    cv2.rectangle(img, (x1, y1), (x2, y2), (42, 42, 42), -1)
    cv2.rectangle(img, (x1, y1), (x2, y2), (170, 170, 170), 2)

    if title:
        cv2.putText(
            img, title, (x1 + 18, y1 + 32),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2
        )


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
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    if is_active:
        cv2.putText(img, "ACTIVE", (x2 - 95, y1 + 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 2)

    # Text lines
    text_x = x1 + 16
    count_y = y1 + 95
    score_y = y1 + 130
    density_y = y1 + 165

    cv2.putText(img, f"Count: {count}", (text_x, count_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

    cv2.putText(img, f"Score: {score:.1f}", (text_x, score_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

    cv2.putText(img, f"Density: {density}", (text_x, density_y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

    # Traffic light circles on the right of the info
    circle_x = x2 - 42
    circle_y = y1 + 95
    draw_light_icon(img, circle_x, circle_y, light_state)

    if is_active:
        draw_progress_bar(img, x1 + 16, y2 - 20, w - 32, 10, remaining, phase_total)
        cv2.putText(img, f"{remaining}s", (x2 - 60, y2 - 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 2)


def draw_master_ui(state, video_frame):
    img = np.full((820, 1400, 3), 22, dtype=np.uint8)

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
    draw_panel(img, 20, 20, 1380, 110)
    cv2.putText(img, "MASTER TRAFFIC CONTROLLER", (40, 70),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 3)

    # =========================
    # LEFT: ROAD CARDS (2x2)
    # =========================
    left_x = 20
    top_y = 140
    card_w = 285
    card_h = 210
    gap_x = 20
    gap_y = 20

    positions = {
        "north": (left_x, top_y),
        "west": (left_x + card_w + gap_x, top_y),
        "south": (left_x, top_y + card_h + gap_y),
        "east": (left_x + card_w + gap_x, top_y + card_h + gap_y),
    }

    for road in ORDER:
        x, y = positions[road]
        is_active = (road == current_road)
        road_remaining = remaining if is_active else 0
        road_total = phase_total if is_active else 0

        draw_road_card(
            img=img,
            x1=x,
            y1=y,
            w=card_w,
            h=card_h,
            road=road,
            light_state=lights[road],
            count=counts[road],
            score=scores[road],
            density=densities[road],
            is_active=is_active,
            remaining=road_remaining,
            phase_total=road_total
        )

    # =========================
    # RIGHT: VIDEO PANEL
    # =========================
    video_x1, video_y1 = 650, 140
    video_x2, video_y2 = 1380, 560
    draw_panel(img, video_x1, video_y1, video_x2, video_y2, "Live Intersection View")

    inner_x1 = video_x1 + 18
    inner_y1 = video_y1 + 48
    inner_x2 = video_x2 - 18
    inner_y2 = video_y2 - 18

    if video_frame is not None:
        target_w = inner_x2 - inner_x1
        target_h = inner_y2 - inner_y1
        video_resized = cv2.resize(video_frame, (target_w, target_h))
        img[inner_y1:inner_y2, inner_x1:inner_x2] = video_resized
    else:
        cv2.putText(img, "No video", (video_x1 + 260, video_y1 + 220),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (180, 180, 180), 2)

    # =========================
    # BOTTOM LEFT: SIGNAL PLAN
    # =========================
    draw_panel(img, 20, 600, 610, 790, "Signal Plan")

    sp_label_x = 40
    sp_green_x = 190
    sp_yellow_x = 360
    sp_mark_x = 520
    sp_y = 665
    sp_gap = 35

    for i, road in enumerate(ORDER):
        yy = sp_y + i * sp_gap
        row_color = (0, 220, 255) if road == current_road else (255, 255, 255)

        cv2.putText(img, f"{road.upper()}:", (sp_label_x, yy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, row_color, 2)

        cv2.putText(img, f"GREEN={green_times[road]}s", (sp_green_x, yy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, row_color, 2)

        cv2.putText(img, f"YELLOW={YELLOW_TIME}s", (sp_yellow_x, yy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, row_color, 2)

        if road == current_road:
            cv2.putText(img, "<==", (sp_mark_x, yy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 255), 2)

    # =========================
    # BOTTOM RIGHT: SYSTEM STATUS
    # =========================
    draw_panel(img, 650, 600, 1380, 790, "System Status")

    heavy_color = (0, 255, 0) if heavy != "None" else (0, 200, 255)

    ss_label_x = 670
    ss_value_x = 900
    ss_y = 665
    ss_gap = 38

    rows = [
        ("Mode", mode, (255, 255, 255)),
        ("Heavy road", str(heavy).upper(), heavy_color),
        ("Current road", current_road.upper(), (255, 255, 255)),
    ]

    for i, (label, value, value_color) in enumerate(rows):
        yy = ss_y + i * ss_gap

        cv2.putText(img, f"{label}:", (ss_label_x, yy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.72, (200, 200, 200), 2)

        cv2.putText(img, value, (ss_value_x, yy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.72, value_color, 2)

    if mode == "DEFAULT":
        status_text = "Waiting for enough edge data..."
        status_color = (0, 200, 255)
    else:
        status_text = "Adaptive control active"
        status_color = (0, 255, 0)

    cv2.putText(img, "Status:", (ss_label_x, ss_y + 3 * ss_gap),
                cv2.FONT_HERSHEY_SIMPLEX, 0.72, (200, 200, 200), 2)

    cv2.putText(img, status_text, (ss_value_x, ss_y + 3 * ss_gap),
                cv2.FONT_HERSHEY_SIMPLEX, 0.68, status_color, 2)

    return img


def run_master(display_video):
    server = ThreadedTCPServer((HOST, PORT), MasterTCPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    cap = cv2.VideoCapture(display_video)
    if not cap.isOpened():
        print(f"[MASTER] cannot open display video: {display_video}")
        server.shutdown()
        server.server_close()
        return

    print(f"[MASTER] listening on {HOST}:{PORT}")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
                if not ret:
                    break

            state = MASTER.current_state()
            ui = draw_master_ui(state, frame)
            cv2.imshow("MASTER - Traffic Control", ui)

            if cv2.waitKey(30) & 0xFF == 27:
                break
    finally:
        cap.release()
        server.shutdown()
        server.server_close()
        cv2.destroyAllWindows()


def send_report(master_ip, port, payload):
    with socket.create_connection((master_ip, port), timeout=5.0) as sock:
        safe_json_send(sock, payload)
        return safe_json_recv_line(sock)


def count_vehicles_for_road(frame, model, road, conf=0.35):
    polygon = ROAD_POLYGONS[road]

    results = model.track(
        frame,
        classes=VEHICLE_CLASSES,
        conf=conf,
        persist=True,
        verbose=False
    )

    raw_count = 0
    weighted_score = 0.0

    boxes = results[0].boxes
    if boxes is not None and len(boxes) > 0:
        for box in boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cls_id = int(box.cls[0])
            label = model.names[cls_id]

            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2

            if point_in_polygon(cx, cy, polygon):
                raw_count += 1
                weighted_score += WEIGHTS.get(label, 1.0)

    return raw_count, weighted_score


def run_edge(road, video, master_ip, model_path):
    model = YOLO(model_path)
    cap = cv2.VideoCapture(video)

    if not cap.isOpened():
        print(f"[EDGE {road}] cannot open video: {video}")
        return

    print(f"[EDGE {road}] sending to master {master_ip}:{PORT}")

    last_report = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue

        raw_count, weighted_score = count_vehicles_for_road(frame, model, road)

        now = time.time()
        if now - last_report >= REPORT_INTERVAL:
            try:
                payload = {
                    "action": "report",
                    "road": road,
                    "raw_count": raw_count,
                    "weighted_score": weighted_score
                }
                resp = send_report(master_ip, PORT, payload)
                if resp.get("ok"):
                    state = resp["state"]
                    print(
                        f"[EDGE {road}] count={raw_count}, score={weighted_score:.1f} | "
                        f"MASTER heavy={state['heavy_road']} | "
                        f"phase={state['current_road']} {state['current_phase']}"
                    )
                last_report = now
            except Exception as e:
                print(f"[EDGE {road}] error: {e}")

        time.sleep(0.03)

    cap.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["master", "edge"], required=True)
    parser.add_argument("--road", choices=ORDER)
    parser.add_argument("--video", default="videos/short-video.mp4")
    parser.add_argument("--display-video", default="videos/short-video.mp4")
    parser.add_argument("--master-ip", default="127.0.0.1")
    parser.add_argument("--model", default="yolo11n.pt")
    args = parser.parse_args()

    if args.mode == "master":
        run_master(args.display_video)
    else:
        if not args.road:
            raise SystemExit("edge mode يحتاج --road")
        run_edge(args.road, args.video, args.master_ip, args.model)