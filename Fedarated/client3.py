import copy
import os
import requests
import time
from datetime import datetime
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def resolve_project_path(path):
    """
    Resolve relative project paths safely from anywhere PyCharm/terminal runs this script.
    """
    if path is None:
        return None

    if isinstance(path, int):
        return path

    if str(path).isdigit():
        return int(path)

    if os.path.isabs(path):
        return path

    return os.path.join(BASE_DIR, path)
import threading

try:
    from ultralytics import YOLO
except Exception:
    YOLO = None  # Fallback if ultralytics is not installed; detection will be skipped

try:
    import cv2
except Exception:
    cv2 = None  # Fallback if OpenCV is not installed; streaming will be skipped

# 🔗 Server endpoints
SERVER_URL = "http://127.0.0.1:5000"
UPDATE_URL = f"{SERVER_URL}/federated/update"
GLOBAL_MODEL_URL = f"{SERVER_URL}/global_model"
DETECT_URL = f"{SERVER_URL}/detect"

# YOLO model (loaded lazily on first use)
_YOLO_MODEL = None

def get_yolo_model(path: str = None):
    global _YOLO_MODEL

    # If already loaded, return cached model instance
    if _YOLO_MODEL is not None and not isinstance(_YOLO_MODEL, str):
        return _YOLO_MODEL

    if YOLO is None:
        print("Ultralytics YOLO not available. Skipping real detection.")
        return None

    # Resolve model path priority:
    # 1. explicit path
    # 2. trained best.pt if it exists
    # 3. available local YOLO model files
    candidate_paths = [
        path,
        os.path.join(BASE_DIR, "yolo", "runs", "detect", "train8", "weights", "best.pt"),
        os.path.join(BASE_DIR, "yolo", "best.pt"),
        os.path.join(BASE_DIR, "yolo", "yolo11n.pt"),
        os.path.join(BASE_DIR, "yolo", "yolo26n.pt"),
    ]

    model_path = next(
        (candidate for candidate in candidate_paths if candidate and os.path.isfile(candidate)),
        None
    )

    if not model_path:
        print("YOLO model not found. Checked:")
        for candidate in candidate_paths:
            if candidate:
                print(f" - {candidate}")
        print("Real detection cancelled.")
        return None

    _YOLO_MODEL = YOLO(model_path)
    print(f"Loaded YOLO model from: {model_path}")
    return _YOLO_MODEL


def create_initial_model(device_id):
    """
    Create a deterministic lightweight local model per device.

    This avoids pure random weights while still giving each edge device
    slightly different starting parameters.
    """
    device_offset = sum(ord(char) for char in device_id) % 10 / 100

    return {
        "layer1": [
            round(0.20 + device_offset, 4),
            round(0.35 + device_offset, 4),
            round(0.50 + device_offset, 4)
        ],
        "layer2": [
            round(0.15 + device_offset, 4),
            round(0.30 + device_offset, 4)
        ],
        "bias": [
            round(0.05 + device_offset, 4)
        ]
    }


# Each simulated edge device owns its own local model.
local_models = {
    "ED-001": create_initial_model("ED-001"),
    "ED-002": create_initial_model("ED-002"),
    "ED-003": create_initial_model("ED-003")
}


def yolo_detect_accident(image_path: str, min_conf: float = 0.80, model_path: str = None):
    """
    Run YOLO on the provided image and return (detected: bool, confidence: float).

    Detection logic:
    - Prefer object detection boxes with class label 'accident' and conf >= min_conf.
    - If no boxes are present, try classification probs (if model is classification-type).
    """
    model = get_yolo_model(model_path)
    if model is None:
        return False, None

    if not os.path.isfile(image_path):
        print(f"Image not found: {image_path}")
        return False, None

    try:
        results = model(image_path)
    except Exception as e:
        print("YOLO inference error:", e)
        return False, None

    # Results parsing
    try:
        r = results[0]

        # 1) Object detection path
        if hasattr(r, 'boxes') and r.boxes is not None and len(r.boxes) > 0:
            names = getattr(r, 'names', None) or getattr(model, 'names', {})
            for b in r.boxes:
                # Extract class index robustly (tensor/list/scalar)
                cls_attr = getattr(b, 'cls', None)
                try:
                    if cls_attr is None:
                        cls_idx = None
                    elif hasattr(cls_attr, 'item'):
                        cls_idx = int(cls_attr.item())
                    elif isinstance(cls_attr, (list, tuple)):
                        cls_idx = int(cls_attr[0]) if cls_attr else None
                    else:
                        cls_idx = int(cls_attr)
                except Exception:
                    cls_idx = None

                # Extract confidence robustly (tensor/list/scalar)
                conf_attr = getattr(b, 'conf', None)
                try:
                    if conf_attr is None:
                        conf_val = 0.0
                    elif hasattr(conf_attr, 'item'):
                        conf_val = float(conf_attr.item())
                    elif isinstance(conf_attr, (list, tuple)):
                        conf_val = float(conf_attr[0]) if conf_attr else 0.0
                    else:
                        conf_val = float(conf_attr)
                except Exception:
                    conf_val = 0.0
                cls_name = names.get(cls_idx, str(cls_idx)) if isinstance(names, dict) else str(cls_idx)
                if str(cls_name).lower() == 'accident' and conf_val >= min_conf:
                    return True, conf_val

        # 2) Classification path
        if hasattr(r, 'probs') and r.probs is not None:
            names = getattr(r, 'names', None) or getattr(model, 'names', {})
            if hasattr(r.probs, 'top1') and hasattr(r.probs, 'top1conf'):
                top1 = int(r.probs.top1)
                top1conf = float(r.probs.top1conf)
                top1name = names.get(top1, str(top1)) if isinstance(names, dict) else str(top1)
                if str(top1name).lower() == 'accident' and top1conf >= min_conf:
                    return True, top1conf
    except Exception as e:
        print("YOLO results parsing error:", e)
        return False, None

    return False, None


def _ensure_dir(path: str):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


def _save_frame(frame, base_dir=os.path.join('yolo', 'captures')) -> str:
    """Save a BGR frame to disk as JPEG and return the file path."""
    _ensure_dir(base_dir)
    ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')
    file_path = os.path.join(base_dir, f'alert_{ts}.jpg')
    try:
        if cv2 is None:
            return None
        ok = cv2.imwrite(file_path, frame)
        return file_path if ok else None
    except Exception:
        return None


def _draw_boxes(frame, result, names):
    if cv2 is None:
        return frame
    try:
        if hasattr(result, 'boxes') and result.boxes is not None:
            for b in result.boxes:
                # Extract coordinates
                xyxy = getattr(b, 'xyxy', None)
                if xyxy is None:
                    continue
                x1, y1, x2, y2 = map(int, xyxy[0].tolist())
                cls_idx = int(getattr(b, 'cls', [None])[0]) if hasattr(b, 'cls') else -1
                conf_val = float(getattr(b, 'conf', [0.0])[0]) if hasattr(b, 'conf') else 0.0
                name = names.get(cls_idx, str(cls_idx)) if isinstance(names, dict) else str(cls_idx)
                color = (0, 200, 0) if str(name).lower() == 'accident' else (60, 100, 255)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                label = f"{name}:{conf_val:.2f}"
                cv2.putText(frame, label, (x1, max(0, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    except Exception:
        pass
    return frame


def run_stream(
    device_id: str = 'ED-001',
    source=None,
    model_path: str = None,
    min_conf: float = 0.80,
    cooldown_s: int = 120,
    show: bool = True
):
    """
    Run a continuous real-time detection loop using OpenCV and Ultralytics YOLO.

    - source: 0 (default webcam) or a path to a video file.
    - When an 'accident' is detected with confidence >= min_conf, save the frame and
      POST it to the backend /detect endpoint (multipart). A cooldown prevents spam.
    - Debug info printed each frame: class names, detections, and server responses.
    - Visualization (imshow with drawn boxes) is enabled by default.
    """
    if cv2 is None:
        print('OpenCV (cv2) is not installed. Streaming mode is unavailable.')
        return

    # Resolve default video source: prefer existing project test video over webcam
    if source is None:
        candidate_sources = [
            os.path.join(BASE_DIR, "yolo", "test", "Clayton South fatal car crash caught on CCTV.mp4"),
            os.path.join(BASE_DIR, "yolo", "test", "carandMotorCrash.mp4"),
            os.path.join(BASE_DIR, "yolo", "test", "yellowTruck.jpg"),
        ]

        chosen = None
        for candidate in candidate_sources:
            if os.path.isfile(candidate):
                chosen = candidate
                break

        source = chosen if chosen is not None else 0
    else:
        source = resolve_project_path(source)

    print(f"Resolved video source: {source}")
    print(f"Source exists: {os.path.isfile(source) if isinstance(source, str) else 'webcam'}")

    model = get_yolo_model(model_path)
    if model is None:
        print('YOLO model is not available. Streaming cancelled.')
        return
    if not callable(model):
        print(f"YOLO model object is not callable: {type(model)}. Check model loading.")
        return

    if isinstance(source, int):
        cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f'Failed to open video source: {source}')
        return

    print(f"Starting real-time detection on source: {source} (device {device_id})")
    last_sent_ts = 0.0

    names_logged = False
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                # For files, end of stream; for webcam, brief wait then retry
                time.sleep(0.02)
                if isinstance(source, (str, bytes)):
                    print('End of video or failed to read frame. Exiting stream loop.')
                    break
                continue

            # Run YOLO on the frame
            try:
                results = model(frame)
            except Exception as e:
                print('YOLO inference error on frame:', e)
                continue

            r = results[0]
            names = getattr(r, 'names', None) or getattr(model, 'names', {})
            if not names_logged:
                try:
                    if isinstance(names, dict):
                        print('YOLO class names:', names)
                    else:
                        print('YOLO class names not available as dict; model may be classification-type.')
                except Exception:
                    pass
                names_logged = True

            # Debug: list detections
            accident_conf = 0.0
            if hasattr(r, 'boxes') and r.boxes is not None:
                for b in r.boxes:
                    # Class
                    cls_attr = getattr(b, 'cls', None)
                    try:
                        if cls_attr is None:
                            cls_idx = -1
                        elif hasattr(cls_attr, 'item'):
                            cls_idx = int(cls_attr.item())
                        elif isinstance(cls_attr, (list, tuple)):
                            cls_idx = int(cls_attr[0]) if cls_attr else -1
                        else:
                            cls_idx = int(cls_attr)
                    except Exception:
                        cls_idx = -1
                    # Confidence
                    conf_attr = getattr(b, 'conf', None)
                    try:
                        if conf_attr is None:
                            conf_val = 0.0
                        elif hasattr(conf_attr, 'item'):
                            conf_val = float(conf_attr.item())
                        elif isinstance(conf_attr, (list, tuple)):
                            conf_val = float(conf_attr[0]) if conf_attr else 0.0
                        else:
                            conf_val = float(conf_attr)
                    except Exception:
                        conf_val = 0.0
                    cls_name = names.get(cls_idx, str(cls_idx)) if isinstance(names, dict) else str(cls_idx)
                    print(f"Detected: class={cls_name}, id={cls_idx}, conf={conf_val:.3f}")
                    if str(cls_name).lower() == 'accident':
                        accident_conf = max(accident_conf, conf_val)

            detected = accident_conf >= float(min_conf)
            print(f"accident_detected={detected}, threshold={float(min_conf):.2f}, max_conf={accident_conf:.3f}")
            if detected:
                now = time.time()
                if now - last_sent_ts >= float(cooldown_s):
                    # Save frame and send alert
                    file_path = _save_frame(frame)
                    if file_path:
                        print(f"Accident detected (conf={accident_conf:.2f}). Sending alert with frame: {file_path}")
                        try:
                            with open(file_path, 'rb') as f:
                                files = { 'image': f }
                                data = {
                                    'device_id': device_id,
                                    'type': 'accident',
                                    'confidence': accident_conf
                                }
                                resp = requests.post(DETECT_URL, files=files, data=data, timeout=15)
                                try:
                                    print('Server response:', resp.json())
                                except Exception:
                                    print('Server response (non-JSON):', resp.status_code, resp.text[:200])
                            last_sent_ts = now
                        except Exception as e:
                            print('Failed to send detection alert:', e)
                    else:
                        print('Failed to save frame. Alert not sent.')
                else:
                    remaining = float(cooldown_s) - (now - last_sent_ts)
                    print(f"Accident detected but in cooldown ({remaining:.1f}s remaining).")
            else:
                print("No 'accident' detected in this frame.")

            # Optional display
            if show:
                vis_frame = _draw_boxes(frame.copy(), r, names)
                try:
                    cv2.imshow('TrafficGuard — Live', vis_frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (27, ord('q')):  # ESC or q
                        print('Exit requested by user.')
                        break
                except Exception:
                    # In headless environments, imshow may fail; ignore
                    pass
    finally:
        try:
            cap.release()
        except Exception:
            pass
        if show and cv2 is not None:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass


def train_local_model(device_id, is_correct=True):
    """
    Feedback-based local training.

    This is intentionally lightweight:
    - If feedback says the model was correct, apply a small fine-tuning step.
    - If feedback says false alarm / incorrect, apply a stronger correction.

    Only model parameters are updated. No raw alert data is sent to the server.
    """
    if device_id not in local_models:
        local_models[device_id] = create_initial_model(device_id)

    model = copy.deepcopy(local_models[device_id])

    correction = 0.005 if is_correct else 0.025

    for layer_name, values in model.items():
        updated_values = []

        for index, value in enumerate(values):
            direction = 1 if index % 2 == 0 else -1

            if is_correct:
                new_value = value + (direction * correction)
            else:
                new_value = value + correction

            updated_values.append(round(max(0.0, min(1.0, new_value)), 6))

        model[layer_name] = updated_values

    local_models[device_id] = model
    print(f"{device_id} local model after training:", model)

    return model


def send_update(device_id):
    response = requests.post(UPDATE_URL, json={
        "device_id": device_id,
        "weights": local_models[device_id]
    })

    print(f"{device_id} sent update to server")
    print("Server response:", response.json())


def get_global_model():
    response = requests.get(GLOBAL_MODEL_URL)
    data = response.json()

    if "global_weights" in data:
        print("Received global model:", data["global_weights"])
        return data["global_weights"]

    print("No global model yet")
    return None


def update_local_model(device_id, global_weights):
    if global_weights:
        local_models[device_id] = global_weights
        print(f"{device_id} local model updated from global model")


def run_device(device_id, is_correct=True, image_path: str = None, min_conf: float = 0.80, model_path: str = None):
    print(f"\n--- Device {device_id} starting ---")

    detected, conf = yolo_detect_accident(image_path or os.path.join('yolo', 'test.jpg'), min_conf=min_conf, model_path=model_path)

    if detected:
        send_detection_alert_with_image(device_id, image_path=image_path or os.path.join('yolo', 'test.jpg'), confidence=conf)
    else:
        print(f"{device_id}: No accident detected by YOLO or below threshold {min_conf}.")

    train_local_model(device_id, is_correct=is_correct)
    send_update(device_id)

    global_weights = get_global_model()
    update_local_model(device_id, global_weights)


def run_federated_round(image_path: str = None, min_conf: float = 0.80, model_path: str = None):
    """
    Simulate one FL round with multiple devices.
    """
    feedback_by_device = {
        "ED-001": True,
        "ED-002": False,
        "ED-003": True
    }

    for device_id, is_correct in feedback_by_device.items():
        run_device(device_id, is_correct=is_correct, image_path=image_path, min_conf=min_conf, model_path=model_path)
        time.sleep(1)

def send_detection_alert_with_image(device_id, image_path: str, confidence: float = None):
    """
    Send an accident alert with image to the Flask backend via multipart/form-data.
    """
    if not os.path.isfile(image_path):
        print(f"Image not found, cannot send alert: {image_path}")
        return

    files = {
        "image": open(image_path, "rb")
    }
    data = {
        "device_id": device_id,
        "type": "accident"
    }
    if confidence is not None:
        data["confidence"] = confidence

    try:
        response = requests.post(DETECT_URL, files=files, data=data, timeout=15)
        print(f"{device_id} sent accident alert with image")
        print("Detect response:", response.json())
    except requests.RequestException as error:
        print(f"{device_id} failed to send alert:", error)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Traffic Guard client — streaming and federated functions')
    parser.add_argument('--stream', action='store_true', help='Run real-time detection stream (OpenCV + YOLO)')
    parser.add_argument('--device-id', default='ED-003', help='Device ID to report to server')
    parser.add_argument('--source', default='yolo/test/Dramatic video shows car plow into truck in Panorama City after.mp4', help='Video source: 0 (default webcam) or path to video file')
    parser.add_argument('--model', default='yolo/runs/detect/train8/weights/best.pt')
    parser.add_argument('--min-conf', type=float, default=0.80, help='Accident confidence threshold')
    parser.add_argument('--cooldown', type=int, default=120, help='Cooldown in seconds between alerts')
    parser.add_argument('--no-show', action='store_true', help='Disable OpenCV visualization window')

    # Legacy/demo run options
    parser.add_argument('--demo-round', action='store_true', help='Run one federated round using a single test image (legacy)')
    parser.add_argument('--image', default=os.path.join('yolo', 'test.jpg'), help='Test image path for legacy demo round')

    args = parser.parse_args()

    model_path = args.model
    device_id = args.device_id

    if args.stream:
        # Interpret source argument: '0' -> 0, else file path
        try:
            source = int(args.source)
        except ValueError:
            source = args.source
        run_stream(
            device_id=device_id,
            source=source,
            model_path=model_path,
            min_conf=args.min_conf,
            cooldown_s=args.cooldown,
            show=not args.no_show
        )
    elif args.demo_round:
        run_federated_round(image_path=args.image, min_conf=args.min_conf, model_path=model_path)
    else:
        # Default to a project test video instead of webcam.
        # Webcam source=0 can fail on Windows if camera permissions/backend are unavailable.
        try:
            source = args.source

            try:
                source = int(source)
            except ValueError:
                pass

            run_stream(
                device_id=device_id,
                source=source,
                model_path=model_path,
                min_conf=args.min_conf,
                cooldown_s=args.cooldown,
                show=not args.no_show
            )
        except Exception as e:
            print("Failed to start default stream:", e)