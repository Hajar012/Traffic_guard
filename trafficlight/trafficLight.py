import cv2
import time
import numpy as np
from ultralytics import YOLO

# =========================
# CONFIG
# =========================
FRAME_DELAY = 150
MODEL_PATH = "yolo11n.pt"

VIDEOS = {
    "North": "north-lane.mp4",
    "East": "east-lane.mp4",
    "West": "east-lane.mp4",
    "South": "south-lane.mp4",
}

ORDER = ["North", "West", "South", "East"]

DEFAULT_GREEN = 10
REDUCED_GREEN = 6
YELLOW_TIME = 3
MIN_GREEN = 5

VEHICLE_CLASSES = [1, 2, 3, 5, 7]  # bicycle, car, motorcycle, bus, truck

WEIGHTS = {
    "bicycle": 0.5,
    "motorcycle": 0.5,
    "car": 1.0,
    "bus": 2.0,
    "truck": 2.0,
}

CONFIDENCE = 0.35
DASHBOARD_W = 1300
DASHBOARD_H = 760


# =========================
# HELPERS
# =========================

def density_label(score):
    if score < 3:
        return "LOW"
    elif score < 8:
        return "MEDIUM"
    return "HIGH"


def get_light_color(state):
    if state == "GREEN":
        return (0, 255, 0)
    if state == "YELLOW":
        return (0, 255, 255)
    return (0, 0, 255)


def previous_roads(heavy_road):
    index = ORDER.index(heavy_road)
    return ORDER[:index]


def build_signal_plan(scores):
    green_times = {road: DEFAULT_GREEN for road in ORDER}

    heavy_road = max(scores, key=scores.get)

    for road in previous_roads(heavy_road):
        green_times[road] = max(REDUCED_GREEN, MIN_GREEN)

    return heavy_road, green_times


def draw_traffic_light(img, x, y, state):
    cv2.rectangle(img, (x, y), (x + 55, y + 155), (85, 85, 85), -1)
    cv2.rectangle(img, (x, y), (x + 55, y + 155), (30, 30, 30), 2)

    red = (0, 0, 255) if state == "RED" else (40, 0, 0)
    yellow = (0, 255, 255) if state == "YELLOW" else (40, 40, 0)
    green = (0, 255, 0) if state == "GREEN" else (0, 40, 0)

    cv2.circle(img, (x + 28, y + 35), 20, red, -1)
    cv2.circle(img, (x + 28, y + 78), 20, yellow, -1)
    cv2.circle(img, (x + 28, y + 121), 20, green, -1)

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


def draw_panel(canvas, road, frame, x, y, w, h, light_state, count, score, density, remaining):
    # outer panel
    cv2.rectangle(canvas, (x, y), (x + w, y + h), (220, 220, 220), -1)
    cv2.rectangle(canvas, (x, y), (x + w, y + h), (70, 70, 70), 3)

    # traffic light
    light_x = x + 15
    light_y = y + 45
    draw_traffic_light(canvas, light_x, light_y, light_state)

    # video area
    video_x = x + 80
    video_y = y + 35
    video_w = w - 95
    video_h = h - 55

    resized = cv2.resize(frame, (video_w, video_h))
    canvas[video_y:video_y + video_h, video_x:video_x + video_w] = resized

    # road label
    cv2.rectangle(canvas, (video_x, video_y), (video_x + video_w, video_y + 38), (0, 0, 0), -1)
    cv2.putText(
        canvas,
        road,
        (video_x + video_w // 2 - 55, video_y + 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        2
    )

    # bottom info bar
    bar_y = video_y + video_h - 38
    cv2.rectangle(canvas, (video_x, bar_y), (video_x + video_w, video_y + video_h), (0, 0, 0), -1)

    info = f"Count: {count} | Score: {score:.1f} | Density: {density} | Light: {light_state} | Time: {remaining}s"
    cv2.putText(
        canvas,
        info,
        (video_x + 10, bar_y + 26),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.38,
        (255, 255, 255),
        2
    )


# =========================
# MAIN
# =========================

def main():
    print("[INFO] Loading YOLO model...")
    model = YOLO(MODEL_PATH)

    caps = {}
    for road, path in VIDEOS.items():
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            print(f"[ERROR] Cannot open video for {road}: {path}")
            return
        caps[road] = cap

    scores = {road: 0.0 for road in ORDER}
    counts = {road: 0 for road in ORDER}

    heavy_road = ORDER[0]
    green_times = {road: DEFAULT_GREEN for road in ORDER}

    current_index = 0
    current_road = ORDER[current_index]
    current_phase = "GREEN"
    phase_start = time.time()
    phase_duration = green_times[current_road]

    print("[INFO] Dashboard started. Press ESC to exit.")

    while True:
        frames = {}
        annotated_frames = {}

        # Read and process each video
        for road in ORDER:
            ret, frame = caps[road].read()

            if not ret:
                caps[road].set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = caps[road].read()

            if frame is None:
                continue

            annotated, count, score = detect_and_annotate(frame, model)

            frames[road] = frame
            annotated_frames[road] = annotated
            counts[road] = count
            scores[road] = score

        # Update signal plan based on latest scores
        heavy_road, green_times = build_signal_plan(scores)

        # Phase timing
        elapsed = time.time() - phase_start
        remaining = max(0, int(phase_duration - elapsed))

        if elapsed >= phase_duration:
            if current_phase == "GREEN":
                current_phase = "YELLOW"
                phase_duration = YELLOW_TIME
                phase_start = time.time()
            else:
                current_index = (current_index + 1) % len(ORDER)
                current_road = ORDER[current_index]
                current_phase = "GREEN"
                phase_duration = green_times[current_road]
                phase_start = time.time()

        lights = {road: "RED" for road in ORDER}
        lights[current_road] = current_phase

        # Dashboard canvas
        canvas = np.full((DASHBOARD_H, DASHBOARD_W, 3), 235, dtype=np.uint8)

        cv2.putText(
            canvas,
            "Traffic Guard - Live Traffic Dashboard",
            (280, 38),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 0, 0),
            3
        )

        # Master status bar
        cv2.rectangle(canvas, (40, 55), (1160, 95), (40, 40, 40), -1)

        status = (
            f"MASTER STATUS | Heavy Road: {heavy_road.upper()} | "
            f"Current Phase: {current_road.upper()} - {current_phase} | "
            f"Remaining: {remaining}s"
        )

        cv2.putText(
            canvas,
            status,
            (65, 82),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (255, 255, 255),
            2
        )

        # Panel positions
        panel_w = 575
        panel_h = 270

        positions = {
            "North": (40, 115),
            "East": (685, 115),
            "West": (40, 425),
            "South": (685, 425),
        }

        for road in ["North", "East", "West", "South"]:
            if road not in annotated_frames:
                continue

            x, y = positions[road]
            density = density_label(scores[road])

            road_remaining = remaining if road == current_road else 0

            draw_panel(
                canvas,
                road,
                annotated_frames[road],
                x,
                y,
                panel_w,
                panel_h,
                lights[road],
                counts[road],
                scores[road],
                density,
                road_remaining
            )

        cv2.imshow("Traffic Guard Dashboard", canvas)

        key = cv2.waitKey(FRAME_DELAY) & 0xFF
        if key == 27:
            break

    for cap in caps.values():
        cap.release()

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()