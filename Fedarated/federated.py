# This file handles aggregation of model updates from devices

import json
from backend.models import ModelUpdate

# In-memory updates are kept only for backward compatibility with old code.
device_updates = []


def add_update(device_id, weights):
    """
    Backward-compatible helper for older code paths.
    The main server route now stores updates in the database.
    """
    device_updates.append({
        "device_id": device_id,
        "weights": weights
    })


def parse_weights(raw_weights):
    """
    Parse model weights from the database.

    New format:
        JSON string containing a dictionary of layers.

    Example:
        {
            "layer1": [0.1, 0.2, 0.3],
            "layer2": [0.4, 0.5],
            "bias": [0.1]
        }
    """
    if isinstance(raw_weights, dict):
        return raw_weights

    try:
        parsed = json.loads(raw_weights)
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, json.JSONDecodeError):
        pass

    return None


def fedavg(weight_sets):
    """
    Average structured model weights across devices.

    Input:
        [
            {"layer1": [..], "layer2": [..]},
            {"layer1": [..], "layer2": [..]}
        ]

    Output:
        {"layer1": averaged_values, "layer2": averaged_values}
    """
    if not weight_sets:
        return None

    global_weights = {}
    layer_names = weight_sets[0].keys()

    for layer_name in layer_names:
        layer_values = [weights[layer_name] for weights in weight_sets if layer_name in weights]

        if not layer_values:
            continue

        global_weights[layer_name] = [
            round(sum(values) / len(values), 6)
            for values in zip(*layer_values)
        ]

    return global_weights


def aggregate_models():
    """
    Aggregate all model updates stored in the ModelUpdate table using FedAvg.
    """
    updates = ModelUpdate.query.order_by(ModelUpdate.timestamp.desc()).all()

    if not updates:
        return None

    all_weights = []
    participating_devices = set()

    for update in updates:
        weights = parse_weights(update.weights)

        if not weights:
            print("ERROR parsing weights:", update.weights)
            continue

        all_weights.append(weights)
        participating_devices.add(update.device_id)

    if not all_weights:
        return None

    global_weights = fedavg(all_weights)

    return {
        "global_weights": global_weights,
        "num_devices": len(participating_devices),
        "num_updates": len(all_weights)
    }


def clear_updates():
    """
    Clear only the in-memory compatibility list.
    Database updates are intentionally preserved for dashboard/history.
    """
    device_updates.clear()