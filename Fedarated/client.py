import copy
import requests
import time

# 🔗 Server endpoints
SERVER_URL = "http://127.0.0.1:5000"
UPDATE_URL = f"{SERVER_URL}/federated/update"
GLOBAL_MODEL_URL = f"{SERVER_URL}/global_model"
DETECT_URL = f"{SERVER_URL}/detect"


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


def detect_accident(device_id):
    """
    Lightweight deterministic detection simulation.
    """
    score = sum(local_models[device_id]["layer1"]) + sum(local_models[device_id]["layer2"])
    detected = score >= 1.45
    print(f"{device_id} detection result:", detected)
    return detected


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


def run_device(device_id, is_correct=True):
    print(f"\n--- Device {device_id} starting ---")

    detected = detect_accident(device_id)

    if detected:
        send_detection_alert(device_id, confidence=0.92)

    train_local_model(device_id, is_correct=is_correct)
    send_update(device_id)

    global_weights = get_global_model()
    update_local_model(device_id, global_weights)


def run_federated_round():
    """
    Simulate one FL round with multiple devices.
    """
    feedback_by_device = {
        "ED-001": True,
        "ED-002": False,
        "ED-003": True
    }

    for device_id, is_correct in feedback_by_device.items():
        run_device(device_id, is_correct=is_correct)
        time.sleep(1)

def send_detection_alert(device_id, confidence=0.92):
    """
    Send a real accident alert to the Flask backend.
    This creates a Pending alert in the database.
    """
    payload = {
        "device_id": device_id,
        "type": "accident",
        "confidence": confidence
    }

    try:
        response = requests.post(DETECT_URL, json=payload)
        print(f"{device_id} sent accident alert")
        print("Detect response:", response.json())
    except requests.RequestException as error:
        print(f"{device_id} failed to send alert:", error)

if __name__ == "__main__":
    run_federated_round()