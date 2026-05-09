import requests
from yolo.train_yolo11 import model

weights = model.model.model[-1].weight.detach().cpu().numpy()
weights_small = weights.flatten()[:50]

requests.post("http://127.0.0.1:5000/federated/update", json={
    "device_id": "ED-001",
    "weights": weights_small.tolist()
})